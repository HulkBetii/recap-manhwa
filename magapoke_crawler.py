"""
Magazine Pocket (マガポケ - Kodansha) Manga Crawler Module
Platform: pocket.shonenmagazine.com
Supports extracting comic metadata, episode lists, and unscrambled high-resolution canvas pages.

Restored 2026-10-03: the module was deleted as "legacy" in bf12809 while Stage 1/2 still imported it,
so every MagaPoke task failed its import. The viewer now draws CDN images (descrambled in WebAssembly)
onto cross-origin "tainted" canvases, so canvas.toDataURL() throws SecurityError. Pages are captured as
rendered on screen instead (CDP screenshot of each visible canvas, at the canvas' own resolution); the
site's scrambling itself is not reverse-engineered. Cookies (optional, for logged-in reading) come from
MAGAPOKE_COOKIE_PATH or cookies/pocket.shonenmagazine.com.json (gitignored), never a personal path.
"""

import os
import json
import base64
import logging
import urllib.parse
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)

MAGAPOKE_HOST = "pocket.shonenmagazine.com"
COOKIE_ENV_VAR = "MAGAPOKE_COOKIE_PATH"
DEFAULT_COOKIE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies", f"{MAGAPOKE_HOST}.json")
NAVIGATION_TIMEOUT_MS = 60000
PAGE_SETTLE_MS = 3000
VIEWER_SETTLE_MS = 3500
SWEEP_KEY_DELAY_MS = 300
SWEEP_MAX_STEPS = 65
FALLBACK_PAGE_COUNT = 48      # used only when the viewer API does not report the page count
MIN_PAGE_CANVAS_PX = 500      # smaller canvases are thumbnails/ads, not manga pages
JPEG_QUALITY = 94
# Site URLs use zero-padded title ids ("/title/01152"); the API returns the number (1152), and
# "/title/1152/episode/..." renders a listing page with no viewer at all.
TITLE_ID_DIGITS = 5

# Rendered page canvases currently on screen, with their intrinsic size and on-screen box.
VISIBLE_CANVASES_JS = """(minPx) => [...document.querySelectorAll('.c-viewer__pages-item')].map((item, index) => {
    const cv = item.querySelector('canvas');
    if (!cv || cv.width <= minPx || cv.height <= minPx) return null;
    const r = cv.getBoundingClientRect();
    const visible = r.width > 0 && r.height > 0 && r.left >= 0 && r.top >= 0
        && r.right <= innerWidth + 1 && r.bottom <= innerHeight + 1;
    return { index, w: cv.width, h: cv.height, x: r.x, y: r.y, rw: r.width, rh: r.height, visible };
}).filter(Boolean)"""

# The viewer resumes from the last read page; clearing the history starts every episode at page 1.
RESET_HISTORY_JS = """
    try {
        localStorage.removeItem('episodeHistory');
        sessionStorage.clear();
    } catch (e) {}
"""


def cookie_paths() -> List[str]:
    env_path = os.environ.get(COOKIE_ENV_VAR, "").strip()
    return [p for p in (env_path, DEFAULT_COOKIE_PATH) if p]


def magapoke_episode_url(title_id: Any, episode_id: Any) -> str:
    title = str(title_id).strip()
    if title.isdigit():
        title = title.zfill(TITLE_ID_DIGITS)
    return f"https://{MAGAPOKE_HOST}/title/{title}/episode/{episode_id}"


def is_magapoke_url(url: str) -> bool:
    """Check if the provided URL belongs to pocket.shonenmagazine.com."""
    if not url:
        return False
    parsed = urllib.parse.urlparse(url)
    return MAGAPOKE_HOST in parsed.netloc.lower()


def parse_magapoke_url(url: str) -> Dict[str, Optional[str]]:
    """
    Extract title_id and episode_id from Magazine Pocket URL.
    Examples:
      - https://pocket.shonenmagazine.com/title/01152/episode/308806 -> title_id='01152', episode_id='308806'
      - https://pocket.shonenmagazine.com/title/01152 -> title_id='01152', episode_id=None
      - https://pocket.shonenmagazine.com/episode/308806 -> title_id=None, episode_id='308806'
    """
    result = {"title_id": None, "episode_id": None}
    parsed = urllib.parse.urlparse(url)
    parts = parsed.path.strip("/").split("/")

    for i, p in enumerate(parts):
        if p == "title" and i + 1 < len(parts):
            result["title_id"] = parts[i + 1]
        elif p == "episode" and i + 1 < len(parts):
            result["episode_id"] = parts[i + 1]

    return result


def load_magapoke_cookies(cookie_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load browser cookies (browser-extension JSON export) for pocket.shonenmagazine.com."""
    candidate_paths = [cookie_path] if cookie_path else []
    candidate_paths.extend(cookie_paths())

    for path in candidate_paths:
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                raw_cookies = data.get("cookies", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                pw_cookies = []
                for c in raw_cookies:
                    cookie = {
                        "name": c["name"],
                        "value": c["value"],
                        "domain": c["domain"],
                        "path": c.get("path", "/"),
                    }
                    if "expirationDate" in c:
                        cookie["expires"] = c["expirationDate"]
                    if "httpOnly" in c:
                        cookie["httpOnly"] = c["httpOnly"]
                    if "secure" in c:
                        cookie["secure"] = c["secure"]
                    same_site = c.get("sameSite", "unspecified").lower()
                    if same_site in ("strict", "lax", "none"):
                        cookie["sameSite"] = same_site.capitalize() if same_site != "none" else "None"
                    pw_cookies.append(cookie)
                return pw_cookies
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
                logger.warning("MagaPoke: failed to parse cookies from %s: %s", path, e)

    return []


async def _add_cookies(page) -> None:
    cookies = load_magapoke_cookies()
    if not cookies:
        return
    try:
        await page.context.add_cookies(cookies)
    except Exception as err:
        logger.warning("MagaPoke: cookies rejected by the browser context: %s", err)


async def fetch_magapoke_title_info(page, url: str) -> Dict[str, Any]:
    """
    Fetch series title and episode list from Magazine Pocket.
    """
    parsed_info = parse_magapoke_url(url)
    title_id = parsed_info["title_id"]

    episodes_from_api: List[Dict[str, Any]] = []

    async def on_response(response):
        if "episode/list" in response.url:
            try:
                if "json" in response.headers.get("content-type", ""):
                    data = await response.json()
                    if "episode_list" in data and isinstance(data["episode_list"], list):
                        episodes_from_api.extend(data["episode_list"])
            except Exception as err:
                logger.warning("MagaPoke: unreadable episode list response %s: %s", response.url, err)

    await _add_cookies(page)

    # Navigate to target page or title page
    target_nav_url = url
    if not parsed_info["title_id"] and parsed_info["episode_id"]:
        target_nav_url = f"https://{MAGAPOKE_HOST}/episode/{parsed_info['episode_id']}"
    elif parsed_info["title_id"] and not parsed_info["episode_id"]:
        target_nav_url = f"https://{MAGAPOKE_HOST}/title/{parsed_info['title_id']}"

    page.on("response", on_response)
    try:
        await page.goto(target_nav_url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
        await page.wait_for_timeout(PAGE_SETTLE_MS)
    finally:
        page.remove_listener("response", on_response)

    # Extract official title
    comic_title = ""
    try:
        og_meta = await page.locator("meta[property='og:title']").evaluate_all(
            "elements => elements.map(el => el.getAttribute('content'))"
        )
        if og_meta and og_meta[0]:
            comic_title = og_meta[0].strip()
        if not comic_title:
            comic_title = await page.title()
    except Exception as err:
        logger.warning("MagaPoke: could not read the series title on %s: %s", target_nav_url, err)

    # Clean title
    if " : " in comic_title:
        comic_title = comic_title.split(" : ")[0].strip()
    if " | " in comic_title:
        comic_title = comic_title.split(" | ")[0].strip()

    # Deduplicate episodes
    unique_episodes = []
    seen_ids = set()
    for ep in episodes_from_api:
        eid = ep.get("episode_id")
        if eid and eid not in seen_ids:
            seen_ids.add(eid)
            unique_episodes.append(ep)

    return {
        "title_id": title_id,
        "comic_title": comic_title or "Magazine Pocket Comic",
        "episodes": unique_episodes,
        "parsed_info": parsed_info
    }


async def crawl_magapoke_episode_images(
    page,
    episode_url: str,
    output_dir: str,
    context_logger=None
) -> List[str]:
    """
    Crawls and extracts all unscrambled pages from a Magazine Pocket episode viewer.
    Uses two-way sweep navigation (ArrowLeft & ArrowRight) to harvest 100% of pages reliably.
    """
    os.makedirs(output_dir, exist_ok=True)

    async def log_msg(msg: str, level: str = "info"):
        if context_logger:
            await context_logger.log(f"[MAGAPOKE] {msg}", level)
        else:
            logger.info("[MAGAPOKE] %s", msg)

    await log_msg(f"Bắt đầu crawl tập Magazine Pocket: {episode_url}")
    await _add_cookies(page)

    total_pages_detected = 0

    async def on_response(response):
        nonlocal total_pages_detected
        if "episode/viewer" in response.url:
            try:
                data = await response.json()
                plist = data.get("page_list", [])
                if plist:
                    total_pages_detected = len(plist)
            except Exception as err:
                logger.warning("MagaPoke: unreadable viewer response %s: %s", response.url, err)

    page.on("response", on_response)
    try:
        return await _harvest_pages(page, episode_url, output_dir, log_msg, lambda: total_pages_detected)
    finally:
        # The page is reused for every episode; stale listeners would pile up.
        page.remove_listener("response", on_response)


async def _harvest_pages(page, episode_url: str, output_dir: str, log_msg, detected_count) -> List[str]:
    try:
        await page.add_init_script(RESET_HISTORY_JS)
    except Exception as err:
        logger.warning("MagaPoke: could not reset the reading history: %s", err)

    # Navigate to episode viewer
    await page.goto(episode_url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
    await page.wait_for_timeout(VIEWER_SETTLE_MS)

    total_pages_detected = detected_count()
    if total_pages_detected > 0:
        await log_msg(f"Phát hiện {total_pages_detected} trang từ viewer API.", "info")
    else:
        await log_msg("Đang xác định số trang từ giao diện viewer...", "info")

    target_count = total_pages_detected if total_pages_detected > 0 else FALLBACK_PAGE_COUNT
    saved_pages: Dict[int, tuple] = {}
    cdp = await page.context.new_cdp_session(page)

    async def capture(item) -> bytes:
        # Screenshot scaled so the capture has the canvas' own pixel size, not its smaller display size.
        result = await cdp.send("Page.captureScreenshot", {
            "format": "jpeg",
            "quality": JPEG_QUALITY,
            "clip": {"x": item["x"], "y": item["y"], "width": item["rw"], "height": item["rh"],
                     "scale": item["w"] / item["rw"]},
        })
        return base64.b64decode(result["data"])

    async def scan_current_canvases():
        new_found = 0
        for item in await page.evaluate(VISIBLE_CANVASES_JS, MIN_PAGE_CANVAS_PX):
            idx = item["index"]
            if idx in saved_pages or not item["visible"]:
                continue
            try:
                img_bytes = await capture(item)
            except Exception as err:
                logger.warning("MagaPoke: capture of page #%s failed: %s", idx, err)
                continue
            saved_pages[idx] = (idx, img_bytes)
            new_found += 1
            await log_msg(f"Thu hoạch trang DOM #{idx} ({item['w']}x{item['h']}, {len(img_bytes)} bytes) -> {len(saved_pages)}/{target_count}", "info")
        return new_found

    try:
        # Pass 1: Forward sweep (ArrowLeft for manga RTL reading)
        await scan_current_canvases()
        for _ in range(SWEEP_MAX_STEPS):
            if len(saved_pages) >= target_count:
                break
            await page.keyboard.press("ArrowLeft")
            await page.wait_for_timeout(SWEEP_KEY_DELAY_MS)
            await scan_current_canvases()

        # Pass 2: Backward sweep if any pages were missed
        if len(saved_pages) < target_count:
            await log_msg(f"Quét ngược để hoàn thiện các trang còn thiếu ({len(saved_pages)}/{target_count})...", "info")
            for _ in range(SWEEP_MAX_STEPS):
                if len(saved_pages) >= target_count:
                    break
                await page.keyboard.press("ArrowRight")
                await page.wait_for_timeout(SWEEP_KEY_DELAY_MS)
                await scan_current_canvases()
    finally:
        try:
            await cdp.detach()
        except Exception as err:
            logger.warning("MagaPoke: CDP session detach failed: %s", err)

    # Sort saved pages by their original DOM order and write sequentially as 001.jpg, 002.jpg...
    sorted_items = sorted(saved_pages.values(), key=lambda x: x[0])
    final_saved_paths = []

    for seq_idx, (dom_idx, img_bytes) in enumerate(sorted_items, start=1):
        seq_path = os.path.join(output_dir, f"{seq_idx:03d}.jpg")
        with open(seq_path, "wb") as f:
            f.write(img_bytes)
        final_saved_paths.append(seq_path)

    await log_msg(f"Hoàn thành thu hoạch {len(final_saved_paths)}/{target_count} trang manga Magazine Pocket!", "success")
    return final_saved_paths
