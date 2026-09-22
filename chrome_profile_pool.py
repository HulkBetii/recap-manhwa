import asyncio
import os
import time
import shutil
import logging
from typing import List, Dict, Optional, Any, Tuple
from contextlib import asynccontextmanager

from app import (
    load_config,
    NavigationManager,
    sync_chrome_profile,
    cleanup_temp_profiles,
    get_gemini_model_display_name,
    check_gemini_login_and_limit_status,
    get_browser_context
)

logger = logging.getLogger("ChromeProfilePool")


class ProfileSession:
    """Represents an active allocated browser session for a specific Chrome Profile."""
    def __init__(self, profile_path: str, browser: Any, context: Any, nav_manager: Any):
        self.profile_path = profile_path
        self.browser = browser
        self.context = context
        self.nav_manager = nav_manager


class ChromeProfilePool:
    """
    Manages concurrent Playwright Chrome browser contexts across multiple profiles.
    Allows Stage 5 (Gemini Automation) to run multiple episodes concurrently without
    file-lock collisions or rate-limit lockouts.
    """
    def __init__(
        self,
        profiles: Optional[List[str]] = None,
        headless: Optional[bool] = None,
        max_concurrency: Optional[int] = None
    ):
        if profiles is None:
            cfg = load_config()
            configured = cfg.get("chrome_profiles", [])
            if configured:
                profiles = list(configured)
            else:
                default_path = os.getenv("CHROME_PROFILE_PATH") or os.path.join(os.getcwd(), "chrome_profile")
                profiles = [default_path]

        # Deduplicate while preserving order
        seen = set()
        cleaned_profiles = []
        for p in profiles:
            if p and p not in seen:
                seen.add(p)
                cleaned_profiles.append(p)

        if not cleaned_profiles:
            default_path = os.getenv("CHROME_PROFILE_PATH") or os.path.join(os.getcwd(), "chrome_profile")
            cleaned_profiles = [default_path]

        self.profiles: List[str] = cleaned_profiles
        self.headless: bool = headless if headless is not None else load_config().get("headless", False)
        self.max_concurrency: int = min(len(self.profiles), max_concurrency or len(self.profiles))

        self._queue: asyncio.Queue[str] = asyncio.Queue()
        for p in self.profiles:
            self._queue.put_nowait(p)

        self._playwright: Optional[Any] = None
        self._contexts: Dict[str, Tuple[Any, Any]] = {}  # profile_path -> (browser, context)
        self._locks: Dict[str, asyncio.Lock] = {p: asyncio.Lock() for p in self.profiles}
        self._cooldowns: Dict[str, float] = {}  # profile_path -> expire_time
        self._pool_lock = asyncio.Lock()
        self._closed = False

    @property
    def total_profiles(self) -> int:
        return len(self.profiles)

    @property
    def available_count(self) -> int:
        return self._queue.qsize()

    def mark_rate_limited(self, profile_path: str, cooldown_seconds: float = 600.0):
        """Marks a profile as rate limited with a cooldown duration."""
        self._cooldowns[profile_path] = time.time() + cooldown_seconds

    def is_in_cooldown(self, profile_path: str) -> bool:
        """Checks whether a profile is currently in cooldown."""
        expire = self._cooldowns.get(profile_path, 0)
        return time.time() < expire

    async def _ensure_playwright(self):
        async with self._pool_lock:
            if self._playwright is None:
                from playwright.async_api import async_playwright
                self._playwright = await async_playwright().start()

    async def _launch_profile_context(
        self,
        profile_path: str,
        headless: Optional[bool] = None
    ) -> Tuple[Any, Any]:
        """Launches or reuses a shared browser context for a specific profile path ensuring single window."""
        use_headless = self.headless if headless is None else headless

        from app import get_shared_browser_context
        br, ctx = await get_shared_browser_context(headless=use_headless, custom_profile_path=profile_path)
        self._contexts[profile_path] = (br, ctx)

        # Close any extra pages to enforce strictly 1 tab
        try:
            if ctx and len(ctx.pages) > 1:
                for p in ctx.pages[1:]:
                    try: await p.close()
                    except Exception: pass
        except Exception:
            pass

        return br, ctx

    @asynccontextmanager
    async def acquire(
        self,
        context_logger: Optional[Any] = None,
        target_model: str = "flash",
        headless: Optional[bool] = None
    ):
        """
        Acquires an available Chrome profile from the pool as an async context manager.
        The profile is dequeued, its browser launched (under a per-profile lock so two
        concurrent callers never race to open the same Chrome data-dir), and then the
        profile is returned to the queue *immediately* so that other tasks can queue
        behind it while this task is doing its own long-running VLM interaction.
        """
        if self._closed:
            raise RuntimeError("ChromeProfilePool has already been closed.")

        # --- 1. Dequeue next available profile (blocks until one is free) ----------
        profile_path = await self._queue.get()

        # Rotate past cooldown profiles
        checked_count = 0
        while self.is_in_cooldown(profile_path) and checked_count < len(self.profiles):
            self._queue.put_nowait(profile_path)
            profile_path = await self._queue.get()
            checked_count += 1

        if self.is_in_cooldown(profile_path):
            remaining = int(self._cooldowns.get(profile_path, 0) - time.time())
            if context_logger and remaining > 0:
                await context_logger.log(
                    f"Tất cả profiles đang trong thời gian chờ (cooldown). Tiếp tục thử với {profile_path}...",
                    "warning"
                )

        if profile_path not in self._locks:
            self._locks[profile_path] = asyncio.Lock()

        profile_lock = self._locks[profile_path]

        # --- 2. Launch / reuse browser under a short per-profile lock --------------
        # The lock only covers _launch_profile_context so two coroutines never try to
        # open the same Chrome user-data-dir simultaneously.  Once the context is
        # obtained the lock is released and the profile token is returned to the queue.
        async with profile_lock:
            browser, browser_context = await self._launch_profile_context(profile_path, headless=headless)

        nm = NavigationManager(context_logger)
        nm.context = browser_context
        nm.browser = browser

        session = ProfileSession(
            profile_path=profile_path,
            browser=browser,
            context=browser_context,
            nav_manager=nm
        )
        try:
            yield session
        finally:
            self._queue.put_nowait(profile_path)

    async def close_all(self):
        """Closes all open browser contexts and shuts down Playwright."""
        async with self._pool_lock:
            self._closed = True
            for profile_path, (br, ctx) in list(self._contexts.items()):
                try:
                    if ctx:
                        await ctx.close()
                except Exception:
                    pass
                try:
                    if br:
                        await br.close()
                except Exception:
                    pass
            self._contexts.clear()

            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None

