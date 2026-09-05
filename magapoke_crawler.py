"""
Magazine Pocket (マガポケ - Kodansha) Manga Crawler Module
Platform: pocket.shonenmagazine.com
Supports extracting comic metadata, episode lists, and unscrambled high-resolution canvas pages.
"""

import os
import re
import json
import base64
import asyncio
import urllib.parse
from pathlib import Path
from typing import List, Dict, Optional, Any

COOKIE_DEFAULT_PATHS = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies", "pocket.shonenmagazine.com.json"),
    r"C:\Users\HulkBeoti\Downloads\pocket.shonenmagazine.com_05-09-2026.json",
]

def is_magapoke_url(url: str) -> bool:
    """Check if the provided URL belongs to pocket.shonenmagazine.com."""
    if not url:
        return False
    parsed = urllib.parse.urlparse(url)
    return "pocket.shonenmagazine.com" in parsed.netloc.lower()

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
    """Load browser cookies for pocket.shonenmagazine.com."""
    candidate_paths = [cookie_path] if cookie_path else []
    candidate_paths.extend(COOKIE_DEFAULT_PATHS)
    
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
            except Exception as e:
                print(f"[MAGAPOKE] Warning: failed to parse cookies from {path}: {e}")
                
    return []

async def fetch_magapoke_title_info(page, url: str) -> Dict[str, Any]:
    """
    Fetch series title, author, and episode list from Magazine Pocket.
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
            except Exception:
                pass

    page.on("response", on_response)
    
    # Ensure cookies are added
    cookies = load_magapoke_cookies()
    if cookies:
        try:
            await page.context.add_cookies(cookies)
        except Exception:
            pass

    # Navigate to target page or title page
    target_nav_url = url
    if not parsed_info["title_id"] and parsed_info["episode_id"]:
        target_nav_url = f"https://pocket.shonenmagazine.com/episode/{parsed_info['episode_id']}"
    elif parsed_info["title_id"] and not parsed_info["episode_id"]:
        target_nav_url = f"https://pocket.shonenmagazine.com/title/{parsed_info['title_id']}"

    await page.goto(target_nav_url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(3000)

    # Extract official title
    comic_title = ""
    try:
        og_meta = await page.locator("meta[property='og:title']").evaluate_all(
            "elements => elements.map(el => el.getAttribute('content'))"
        )
        if og_meta and og_meta[0]:
            comic_title = og_meta[0].strip()
    except Exception:
        pass

    if not comic_title:
        try:
            comic_title = await page.title()
        except Exception:
            pass

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
            print(f"[MAGAPOKE] [{level.upper()}] {msg}")

    await log_msg(f"Bắt đầu crawl tập Magazine Pocket: {episode_url}")
    
    # Ensure cookies are attached
    cookies = load_magapoke_cookies()
    if cookies:
        try:
            await page.context.add_cookies(cookies)
        except Exception:
            pass

    total_pages_detected = 0
    
    async def on_response(response):
        nonlocal total_pages_detected
        if "episode/viewer" in response.url:
            try:
                data = await response.json()
                plist = data.get("page_list", [])
                if plist:
                    total_pages_detected = len(plist)
            except Exception:
                pass

    page.on("response", on_response)

    # Clear episode history storage before loading to avoid starting from previously read page
    try:
        await page.add_init_script("""
            try {
                localStorage.removeItem('episodeHistory');
                sessionStorage.clear();
            } catch (e) {}
        """)
    except Exception:
        pass

    # Navigate to episode viewer
    await page.goto(episode_url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(3500)

    if total_pages_detected > 0:
        await log_msg(f"Phát hiện {total_pages_detected} trang từ viewer API.", "info")
    else:
        await log_msg("Đang xác định số trang từ giao diện viewer...", "info")

    target_count = total_pages_detected if total_pages_detected > 0 else 48
    saved_pages: Dict[int, tuple] = {}

    async def scan_current_canvases():
        canvases_data = await page.evaluate('''() => {
            const items = document.querySelectorAll('.c-viewer__pages-item');
            const results = [];
            items.forEach((item, idx) => {
                const cv = item.querySelector('canvas');
                if (cv && cv.width > 500 && cv.height > 500) {
                    try {
                        const d = cv.toDataURL('image/jpeg', 0.94);
                        results.push({ index: idx, data: d, w: cv.width, h: cv.height });
                    } catch (e) {
                        results.push({ index: idx, error: e.toString() });
                    }
                }
            });
            return results;
        }''')

        new_found = 0
        for item in canvases_data:
            idx = item.get("index")
            if idx is not None and idx not in saved_pages and "data" in item and item["data"]:
                data_str = item["data"]
                if "," in data_str:
                    b64 = data_str.split(",")[1]
                    img_bytes = base64.b64decode(b64)
                    saved_pages[idx] = (idx, img_bytes)
                    new_found += 1
                    await log_msg(f"Thu hoạch trang DOM #{idx} ({item['w']}x{item['h']}, {len(img_bytes)} bytes) -> {len(saved_pages)}/{target_count}", "info")
        return new_found

    # Pass 1: Forward sweep (ArrowLeft for manga RTL reading)
    await scan_current_canvases()
    for _ in range(65):
        if len(saved_pages) >= target_count:
            break
        await page.keyboard.press("ArrowLeft")
        await page.wait_for_timeout(300)
        await scan_current_canvases()

    # Pass 2: Backward sweep if any pages were missed
    if len(saved_pages) < target_count:
        await log_msg(f"Quét ngược để hoàn thiện các trang còn thiếu ({len(saved_pages)}/{target_count})...", "info")
        for _ in range(65):
            if len(saved_pages) >= target_count:
                break
            await page.keyboard.press("ArrowRight")
            await page.wait_for_timeout(300)
            await scan_current_canvases()

    # Sort saved pages by their original DOM order and write sequentially as 001.jpg, 002.jpg...
    sorted_items = sorted(saved_pages.values(), key=lambda x: x[0])
    final_saved_paths = []
    
    for seq_idx, (dom_idx, img_bytes) in enumerate(sorted_items, start=1):
        seq_filename = f"{seq_idx:03d}.jpg"
        seq_path = os.path.join(output_dir, seq_filename)
        with open(seq_path, "wb") as f:
            f.write(img_bytes)
        final_saved_paths.append(seq_path)

    await log_msg(f"Hoàn thành thu hoạch {len(final_saved_paths)}/{target_count} trang manga Magazine Pocket!", "success")
    return final_saved_paths
