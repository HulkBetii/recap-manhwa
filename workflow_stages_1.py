import os
import json
import asyncio
import base64
import urllib.parse
import sys
import shutil
import re
import random
import time
import traceback
from typing import Optional, Dict, Any, List
from workflow_base import BaseStage, StageState, WorkflowContext, check_episode_completed, find_and_copy_completed_episode
import cv2
import numpy as np
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
except Exception:
    pass
from tools.text_remover.comic_text_remover import get_easyocr_reader, ocr_lock

def natural_sort_key(s: str) -> list:
    """Natural sort key helper so '001.webp' or '1.jpg' sort in exact numerical order."""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

def safe_cv2_imread(path: str, flags: int = cv2.IMREAD_COLOR) -> Optional[np.ndarray]:
    """
    Đọc ảnh an toàn hỗ trợ đường dẫn Unicode trên Windows,
    không bao giờ bị crash Assertion failed !buf.empty() khi gặp file rỗng 0-byte hoặc lỗi buffer.
    """
    if not path or not os.path.exists(path):
        return None
    try:
        if os.path.getsize(path) == 0:
            return None
        buf = np.fromfile(path, dtype=np.uint8)
        if buf.size == 0:
            return None
        img = cv2.imdecode(buf, flags)
        if img is not None and img.size > 0:
            return img
    except Exception:
        pass
    try:
        return cv2.imread(path, flags)
    except Exception:
        return None

# Bảo vệ cv2.imread khỏi monkey-patch của ultralytics trên Windows gây crash khi gặp file 0-byte
_orig_cv2_imread = cv2.imread
def _guarded_cv2_imread(filename, flags=cv2.IMREAD_COLOR):
    try:
        if not filename or not os.path.exists(filename) or os.path.getsize(filename) == 0:
            return None
        buf = np.fromfile(filename, dtype=np.uint8)
        if buf.size == 0:
            return None
        return cv2.imdecode(buf, flags)
    except Exception:
        try:
            return _orig_cv2_imread(filename, flags)
        except Exception:
            return None

cv2.imread = _guarded_cv2_imread

async def human_delay(min_s: float = 0.25, max_s: float = 0.85):
    """Delay ngẫu nhiên ngắn (tối đa 1s) trước các thao tác automation để mô phỏng người dùng thật."""
    await asyncio.sleep(random.uniform(min_s, min(max_s, 1.0)))

def resolve_chapter_slug(slugs: list, ep: int, default_prefix: str = "") -> str:
    """
    Finds the slug in slugs that matches the episode/chapter number `ep`.
    Avoids 0-indexed off-by-one errors caused by Chapter 0 / Prologue.
    Handles sub-part variants ('chapter-2_01', 'chapter-2-01', 'chapter-2_1'),
    padded zeros ('chapter-02', 'chapter-002'), and decimals ('chapter-2.5').
    """
    if not slugs:
        return f"{default_prefix}{ep}" if default_prefix else f"{ep}"
    
    # 1. Exact direct matches
    exact_targets = [f"{default_prefix}{ep}", f"{ep}", f"chapter-{ep}"]
    for target in exact_targets:
        if target in slugs:
            return target

    # 2. Match with major chapter number = ep and sub-parts (e.g. 'chapter-2_01', 'chapter-2-01', 'chapter-2_1', 'chapter-02')
    candidates_with_sub = []
    for s in slugs:
        s_str = str(s).strip()
        m = re.search(r"(?:chapter-|ep-)?(\d+)(?:[_\.-](\d+))?", s_str, re.IGNORECASE)
        if m:
            try:
                major = int(m.group(1))
                if major == ep:
                    sub = m.group(2)
                    sub_val = int(sub) if (sub and sub.isdigit()) else 0
                    candidates_with_sub.append((sub_val, s_str))
            except ValueError:
                pass

    if candidates_with_sub:
        candidates_with_sub.sort(key=lambda x: x[0])
        return candidates_with_sub[0][1]

    # 3. Numeric float match on extracted chapter number (e.g. 'chapter-2.0', '2.0')
    for s in slugs:
        m = re.search(r"(?:chapter-|ep-)?(\d+\.?\d*)", str(s), re.IGNORECASE)
        if m:
            try:
                if abs(float(m.group(1)) - ep) < 0.01:
                    return str(s)
            except ValueError:
                pass
                
    # 4. Match standalone number in slug
    for s in slugs:
        m = re.search(r"\b(\d+\.?\d*)\b", str(s))
        if m:
            try:
                if abs(float(m.group(1)) - ep) < 0.01:
                    return str(s)
            except ValueError:
                pass

    # 5. Fallback: default slug format
    return f"{default_prefix}{ep}" if default_prefix else f"{ep}"

def validate_recap_json(file_path):
    if not os.path.exists(file_path):
        return False
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            parsed = json.load(f)
            if not isinstance(parsed, list) or len(parsed) == 0:
                return False
            for item in parsed:
                if not isinstance(item, dict) or "speech" not in item or "images" not in item:
                    return False
                if not isinstance(item["images"], list) or len(item["images"]) == 0:
                    return False
                total_priority = 0.0
                for img in item["images"]:
                    if not isinstance(img, dict) or "page" not in img or "priority" not in img:
                        return False
                    total_priority += float(img["priority"])
                if abs(total_priority - 1.0) > 0.02:
                    return False
            return True
    except Exception:
        return False

class Stage0_ProjectInit(BaseStage):
    @property
    def name(self) -> str: return "Stage 0 - Project Init"
    @property
    def weight(self) -> float: return 0.02

    async def execute(self, context: WorkflowContext) -> bool:
        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        if sys.version_info < (3, 11):
            await context.log(f"Yêu cầu tối thiểu Python 3.11+. Phiên bản hiện tại: {py_ver}", "error")
            return False
        if sys.version_info < (3, 12):
            await context.log(f"Python {py_ver} OK (khuyến nghị Python 3.12 để tương thích tối ưu)", "warning")
        else:
            await context.log(f"Python 3.12 check pass ({py_ver})", "info")

        try:
            from playwright.async_api import async_playwright
            import cv2
            from PIL import Image
            await context.log("Dependencies check OK (Playwright, OpenCV, Pillow)", "info")
        except ImportError as e:
            await context.log(f"Lỗi thiếu thư viện: {e}", "error")
            return False

        from app import find_ffmpeg
        ffmpeg_exe = find_ffmpeg()
        if not ffmpeg_exe or not os.path.exists(ffmpeg_exe):
            await context.log("Lỗi: Không tìm thấy FFmpeg binary", "error")
            return False
        await context.log(f"FFmpeg OK ({ffmpeg_exe})", "info")

        # Create folders
        url = context.task.comic_url
        parsed = urllib.parse.urlparse(url)
        comic_title = "Comic"
        if parsed.path:
            parts = [p for p in parsed.path.strip("/").split("/") if p]
            if parts:
                slug = parts[-1]
                if slug == 'list' and len(parts) >= 2: slug = parts[-2]
                elif slug == 'viewer' and len(parts) >= 3: slug = parts[-3]
                elif len(parts) >= 2 and parts[-1] in ('viewer', 'list'): slug = parts[-2]
                comic_title = slug.replace("-", " ").title()
        
        from app import sanitize_title
        sanitized_title = sanitize_title(comic_title)
        
        project_dir = os.path.dirname(os.path.abspath(__file__))
        download_folder_name = f"{sanitized_title}_{context.task.from_episode}_{context.task.to_episode}_{context.task.payload.get('language', 'vi')}"
        download_dir = os.path.join(project_dir, "downloads", download_folder_name)
        
        context.task.artifacts["download_folder_name"] = download_folder_name
        context.task.artifacts["download_dir"] = download_dir
        
        os.makedirs(download_dir, exist_ok=True)
        os.makedirs(os.path.join(download_dir, "output"), exist_ok=True)
        
        for ep in range(context.task.from_episode, context.task.to_episode + 1):
            ep_dir = os.path.join(download_dir, f"episode_{ep}")
            downloads_parent = os.path.dirname(download_dir)
            reused = find_and_copy_completed_episode(downloads_parent, sanitized_title, context.task.payload.get('language', 'vi'), download_dir, ep)
            
            if reused:
                await context.log(f"Tập {ep}: Phát hiện dữ liệu đã xử lý thành công ở job khác. Tiến hành sao chép và tái sử dụng.", "success")
            else:
                os.makedirs(os.path.join(ep_dir, "images"), exist_ok=True)
                os.makedirs(os.path.join(ep_dir, "images_blur"), exist_ok=True)
                os.makedirs(os.path.join(ep_dir, "images_pdf"), exist_ok=True)
                os.makedirs(os.path.join(ep_dir, "pdf"), exist_ok=True)
            
        await context.log("Thư mục dự án khởi tạo hoàn tất.", "info")
        await context.update_stage_progress(self.name, 100.0)
        return True

class Stage1_ComicParsing(BaseStage):
    @property
    def name(self) -> str: return "Stage 1 - Comic Parsing"
    @property
    def weight(self) -> float: return 0.03

    async def execute(self, context: WorkflowContext) -> bool:
        from app import get_shared_browser_context, NavigationManager, sanitize_title
        
        task = context.task
        url = (task.comic_url or "").strip()
        if not url or not (url.startswith("http://") or url.startswith("https://")):
            await context.log(f"URL truyện không hợp lệ hoặc đang để trống ('{url}'). Vui lòng kiểm tra lại đường link truyện.", "error")
            return False

        if "toongod.org" in url and "/chapter-" in url:
            url = re.sub(r"/chapter-[^/]+/?$", "/", url)
            task.comic_url = url
        elif "asura" in urllib.parse.urlparse(url).netloc.lower() and "/chapter/" in url:
            url = re.sub(r"/chapter/[^/]+/?$", "", url)
            task.comic_url = url
        elif "valirscans.org" in urllib.parse.urlparse(url).netloc.lower() and "/chapter/" in url:
            url = re.sub(r"/chapter/[^/]+/?$", "", url)
            task.comic_url = url
        elif "nyxscans.com" in urllib.parse.urlparse(url).netloc.lower() and ("/chapter-" in url or "/chapter/" in url):
            url = re.sub(r"/chapter-[^/]+/?$", "", url)
            url = re.sub(r"/chapter/[^/]+/?$", "", url)
            task.comic_url = url
        elif "manhuaplus.com" in urllib.parse.urlparse(url).netloc.lower() and "/chapter-" in url:
            url = re.sub(r"/chapter-[^/]+/?$", "/", url)
            task.comic_url = url
        elif "comic.naver.com" in url and "/webtoon/detail" in url:
            parsed_url = urllib.parse.urlparse(url)
            query_params = urllib.parse.parse_qs(parsed_url.query)
            title_id = query_params.get("titleId", [""])[0]
            if title_id:
                url = f"https://comic.naver.com/webtoon/list?titleId={title_id}"
                task.comic_url = url
        elif "comix.to" in url:
            parsed_url = urllib.parse.urlparse(url)
            parts = parsed_url.path.strip("/").split("/")
            if len(parts) >= 3 and parts[0] == "title":
                last_part = parts[-1]
                if re.search(r"\d+-chapter-", last_part):
                    m = re.search(r"(\d+)-chapter-(\d+\.?\d*)", last_part)
                    if m:
                        task.artifacts["user_comix_chap_id"] = m.group(1)
                        task.artifacts["user_comix_chap_num"] = float(m.group(2))
                    new_path = "/" + "/".join(parts[:-1])
                    url = urllib.parse.urlunparse(parsed_url._replace(path=new_path, query="", fragment=""))
                    task.comic_url = url
            
        download_dir = task.artifacts.get("download_dir")
        from app import load_config
        headless_val = task.payload.get("headless") if task.payload.get("headless") is not None else load_config().get("headless", False)
        
        browser, context_pw = await get_shared_browser_context(headless=headless_val)
        nav_manager = NavigationManager(context)
        nav_manager.context = context_pw
        nav_manager.browser = browser
        page = await context_pw.new_page()
        
        try:
            is_manhuaplus = "manhuaplus.com" in urllib.parse.urlparse(url).netloc.lower()
            goto_wait_until = "domcontentloaded"
            await nav_manager.safe_goto(page, url, reason="Parse comic metadata", caller="Stage1_ComicParsing", wait_until=goto_wait_until)
            title_text = ""
            if "vortexscans.org" in url:
                try:
                    await page.wait_for_selector("h1.break-words, h1.text-2xl", timeout=5000)
                    title_text = await page.locator("h1.break-words, h1.text-2xl").first.inner_text()
                except Exception:
                    pass
                
                # Load all chapters by clicking "Show more"
                click_count = 0
                while True:
                    show_more_button = page.locator("button:has-text('Show All'), button:has-text('Show more')")
                    visible_count = await show_more_button.count()
                    found_clickable = False
                    for idx in range(visible_count):
                        btn = show_more_button.nth(idx)
                        if await btn.is_visible() and await btn.is_enabled():
                            await btn.click()
                            await asyncio.sleep(1.0)
                            click_count += 1
                            found_clickable = True
                            break
                    if not found_clickable or click_count >= 10:
                        break
                
                # Extract and sort unique chapter slugs
                hrefs = await page.locator("a").evaluate_all("elements => elements.map(el => el.getAttribute('href'))")
                vortex_chapters = []
                for href in hrefs:
                    if href and "/chapter-" in href:
                        parsed_href = urllib.parse.urlparse(href)
                        parts = parsed_href.path.strip("/").split("/")
                        if parts:
                            last_part = parts[-1]
                            if last_part.startswith("chapter-"):
                                vortex_chapters.append(last_part)
                
                if vortex_chapters:
                    vortex_chapters = list(set(vortex_chapters))
                    def extract_chap_number(slug):
                        m = re.search(r"chapter-(\d+\.?\d*)", slug)
                        if m:
                            try:
                                return float(m.group(1))
                            except ValueError:
                                pass
                        return 0.0
                    vortex_chapters.sort(key=extract_chap_number)
                    task.artifacts["chapter_slugs"] = vortex_chapters
            elif "toongod.org" in url:
                try:
                    await page.wait_for_selector(".post-title h1", timeout=5000)
                    title_text = await page.locator(".post-title h1").first.inner_text()
                except Exception:
                    pass
                
                # Extract and sort unique chapter slugs for toongod
                hrefs = await page.locator("a").evaluate_all("elements => elements.map(el => el.getAttribute('href'))")
                toongod_chapters = []
                for href in hrefs:
                    if href and "/chapter-" in href:
                        parsed_href = urllib.parse.urlparse(href)
                        parts = parsed_href.path.strip("/").split("/")
                        if parts:
                            last_part = parts[-1]
                            if last_part.startswith("chapter-"):
                                toongod_chapters.append(last_part)
                if toongod_chapters:
                    toongod_chapters = list(set(toongod_chapters))
                    def extract_chap_number(slug):
                        m = re.search(r"chapter-(\d+\.?\d*)", slug)
                        if m:
                            try:
                                return float(m.group(1))
                            except ValueError:
                                pass
                        return 0.0
                    toongod_chapters.sort(key=extract_chap_number)
                    task.artifacts["chapter_slugs"] = toongod_chapters
            elif "asura" in urllib.parse.urlparse(url).netloc.lower():
                try:
                    await page.wait_for_selector("h1", timeout=5000)
                    title_text = await page.locator("h1").first.inner_text()
                except Exception:
                    pass
                
                try:
                    await page.wait_for_selector("a[href*='/chapter/']", timeout=10000)
                except Exception:
                    pass
                
                # Extract unique chapter slugs for asurascans (ending in /chapter/X)
                hrefs = await page.locator("a").evaluate_all("elements => elements.map(el => el.getAttribute('href'))")
                asura_chapters = []
                for href in hrefs:
                    if href and "/chapter/" in href:
                        parsed_href = urllib.parse.urlparse(href)
                        parts = parsed_href.path.strip("/").split("/")
                        if len(parts) >= 2 and parts[-2] == "chapter":
                            asura_chapters.append(parts[-1])
                if asura_chapters:
                    asura_chapters = list(set(asura_chapters))
                    def extract_asura_number(slug):
                        try:
                            return float(slug)
                        except ValueError:
                            pass
                        m = re.search(r"(\d+\.?\d*)", slug)
                        if m:
                            try:
                                return float(m.group(1))
                            except ValueError:
                                pass
                        return 0.0
                    asura_chapters.sort(key=extract_asura_number)
                    task.artifacts["chapter_slugs"] = asura_chapters
            elif "valirscans.org" in urllib.parse.urlparse(url).netloc.lower():
                try:
                    await page.wait_for_selector("h1", timeout=5000)
                    title_text = await page.locator("h1").first.inner_text()
                except Exception:
                    pass
                
                # Extract unique chapter slugs for valirscans (ending in /chapter/X)
                hrefs = await page.locator("a").evaluate_all("elements => elements.map(el => el.getAttribute('href'))")
                valir_chapters = []
                for href in hrefs:
                    if href and "/chapter/" in href:
                        parsed_href = urllib.parse.urlparse(href)
                        parts = parsed_href.path.strip("/").split("/")
                        if len(parts) >= 2 and parts[-2] == "chapter":
                            valir_chapters.append(parts[-1])
                if valir_chapters:
                    valir_chapters = list(set(valir_chapters))
                    def extract_valir_number(slug):
                        try:
                            return float(slug)
                        except ValueError:
                            pass
                        m = re.search(r"(\d+\.?\d*)", slug)
                        if m:
                            try:
                                return float(m.group(1))
                            except ValueError:
                                pass
                        return 0.0
                    valir_chapters.sort(key=extract_valir_number)
                    task.artifacts["chapter_slugs"] = valir_chapters
            elif "comix.to" in url:
                try:
                    await page.wait_for_selector("h1.mpage__title", timeout=5000)
                    title_text = await page.locator("h1.mpage__title").first.inner_text()
                except Exception:
                    pass
                
                chapters_data = await page.locator("div.mchap-row").evaluate_all("""
                    elements => elements.map(row => {
                        const primary = row.querySelector('a.mchap-row__primary');
                        const group = row.querySelector('a.mchap-row__group');
                        return {
                            href: primary ? primary.getAttribute('href') : null,
                            group_href: group ? group.getAttribute('href') : null,
                            group_name: group ? group.textContent.trim() : null
                        };
                    })
                """)
                
                comix_chapters_info = []
                for item in chapters_data:
                    href = item.get("href")
                    if href and "/title/" in href and "chapter" in href:
                        parsed_href = urllib.parse.urlparse(href)
                        parts = parsed_href.path.strip("/").split("/")
                        if len(parts) >= 3 and parts[0] == "title":
                            slug = parts[-1]
                            
                            group_id = None
                            group_href = item.get("group_href")
                            if group_href:
                                group_parts = group_href.strip("/").split("/")
                                if group_parts:
                                    group_id = group_parts[-1]
                                    
                            m = re.search(r"chapter-(\d+\.?\d*)", slug)
                            ch_num = None
                            if m:
                                try:
                                    ch_num = float(m.group(1))
                                except ValueError:
                                    pass
                            
                            comix_chapters_info.append({
                                "slug": slug,
                                "group_id": group_id,
                                "group_name": item.get("group_name"),
                                "chapter_num": ch_num
                            })
                
                comix_chapters_dict = {}
                all_comix_slugs = []
                max_ch = 0.0
                for info in comix_chapters_info:
                    slug = info["slug"]
                    ch_num = info["chapter_num"]
                    if slug not in all_comix_slugs:
                        all_comix_slugs.append(slug)
                    if ch_num is not None:
                        if ch_num > max_ch:
                            max_ch = ch_num
                        if ch_num not in comix_chapters_dict:
                            comix_chapters_dict[ch_num] = slug
                
                if comix_chapters_dict:
                    sorted_ch_nums = sorted(comix_chapters_dict.keys())
                    comix_chapters = [comix_chapters_dict[num] for num in sorted_ch_nums]
                    task.artifacts["chapter_slugs"] = comix_chapters
                    task.artifacts["all_chapter_slugs"] = all_comix_slugs
                    task.artifacts["comix_max_chapter"] = max_ch
                    task.artifacts["comix_chapters_info"] = comix_chapters_info
            elif "nyxscans.com" in urllib.parse.urlparse(url).netloc.lower():
                try:
                    h1s = await page.locator("h1").all_inner_texts()
                    if h1s:
                        for h in reversed(h1s):
                            if h.strip().lower() not in ['status', 'type', 'chapters', 'last update', 'genres']:
                                title_text = h.strip()
                                break
                except Exception:
                    pass
                
                # Expand all chapters by clicking Show More on Nyx Scans
                click_count = 0
                while click_count < 15:
                    show_more_button = page.locator("button:has-text('Show more'), button:has-text('Show More')").first
                    if await show_more_button.count() > 0 and await show_more_button.is_visible():
                        try:
                            await show_more_button.click()
                            await asyncio.sleep(0.8)
                            click_count += 1
                        except Exception:
                            break
                    else:
                        break

                hrefs = await page.locator("a").evaluate_all("elements => elements.map(el => el.getAttribute('href'))")
                nyx_chapters = []
                for href in hrefs:
                    if href and "/chapter-" in href:
                        parsed_href = urllib.parse.urlparse(href)
                        parts = parsed_href.path.strip("/").split("/")
                        if parts:
                            last_part = parts[-1]
                            if last_part.startswith("chapter-"):
                                nyx_chapters.append(last_part)

                # Comprehensive fallback from raw HTML / Next.js chunks
                try:
                    html_content = await page.content()
                    raw_matches = re.findall(r'chapter-[a-zA-Z0-9_\.-]+', html_content)
                    for rm in raw_matches:
                        clean_rm = re.sub(r'["\',;\\/<>].*$', '', rm).strip()
                        if clean_rm and clean_rm.startswith("chapter-") and len(clean_rm) <= 40:
                            nyx_chapters.append(clean_rm)
                except Exception:
                    pass

                if nyx_chapters:
                    nyx_chapters = list(dict.fromkeys(nyx_chapters))
                    def extract_nyx_number(slug):
                        m = re.search(r"chapter-(\d+)(?:[_\.-](\d+))?", str(slug), re.IGNORECASE)
                        if m:
                            try:
                                major = float(m.group(1))
                                sub = float(m.group(2)) if m.group(2) else 0.0
                                return (major, sub)
                            except ValueError:
                                pass
                        return (0.0, 0.0)
                    nyx_chapters.sort(key=extract_nyx_number)
                    task.artifacts["chapter_slugs"] = nyx_chapters
            elif "manhuaplus.com" in urllib.parse.urlparse(url).netloc.lower():
                try:
                    await page.wait_for_selector(".post-title h1, h1", timeout=5000)
                    title_text = await page.locator(".post-title h1, h1").first.inner_text()
                except Exception:
                    pass
                
                # Extract and sort unique chapter slugs for manhuaplus
                parsed_u = urllib.parse.urlparse(url)
                u_parts = parsed_u.path.strip("/").split("/")
                m_slug = u_parts[1] if len(u_parts) >= 2 and u_parts[0] == "manga" else (u_parts[0] if u_parts else "")
                
                hrefs = await page.locator("a").evaluate_all("elements => elements.map(el => el.getAttribute('href'))")
                manhua_chapters = []
                for href in hrefs:
                    if href and "/chapter-" in href:
                        if m_slug and f"/{m_slug}/" not in href:
                            continue
                        parsed_href = urllib.parse.urlparse(href)
                        parts = parsed_href.path.strip("/").split("/")
                        if parts:
                            last_part = parts[-1]
                            if last_part.startswith("chapter-"):
                                manhua_chapters.append(last_part)
                if manhua_chapters:
                    manhua_chapters = list(set(manhua_chapters))
                    def extract_manhua_number(slug):
                        m = re.search(r"chapter-(\d+\.?\d*)", slug)
                        if m:
                            try:
                                return float(m.group(1))
                            except ValueError:
                                pass
                        return 0.0
                    manhua_chapters.sort(key=extract_manhua_number)
                    task.artifacts["chapter_slugs"] = manhua_chapters
            elif "comic.naver.com" in url:
                try:
                    for sel in ["h2.EpisodeListInfo__title--mYLlC", "span.EpisodeListInfo__title--mYLlC", ".EpisodeListInfo__title", ".comic_info h2", "meta[property='og:title']"]:
                        if await page.locator(sel).count() > 0:
                            if sel.startswith("meta"):
                                title_text = await page.locator(sel).first.get_attribute("content") or ""
                            else:
                                title_text = await page.locator(sel).first.inner_text()
                            if title_text:
                                break
                    if title_text:
                        title_text = re.sub(r"\s*::\s*.*$", "", title_text).strip()
                        title_text = re.sub(r"\s*-\s*NAVER.*$", "", title_text, flags=re.IGNORECASE).strip()
                except Exception:
                    pass

                try:
                    await page.wait_for_selector("a[href*='/webtoon/detail?']", timeout=8000)
                except Exception:
                    pass

                hrefs = await page.locator("a[href*='/webtoon/detail?']").evaluate_all(
                    "elements => elements.map(el => el.getAttribute('href'))"
                )
                naver_nos = []
                for href in hrefs:
                    if href and "no=" in href:
                        m = re.search(r"no=(\d+)", href)
                        if m:
                            naver_nos.append(int(m.group(1)))
                if naver_nos:
                    naver_nos = sorted(list(set(naver_nos)))
                    task.artifacts["chapter_slugs"] = [str(n) for n in naver_nos]
                
                parsed_u = urllib.parse.urlparse(url)
                q_params = urllib.parse.parse_qs(parsed_u.query)
                t_id = q_params.get("titleId", [""])[0]
                if t_id:
                    task.artifacts["naver_title_id"] = t_id
            if not title_text:
                title_text = await page.title()
                title_text = title_text.split("|")[0].strip()
                title_text = title_text.split("::")[0].strip()
                title_text = title_text.split("Chapter")[0].strip()
            sanitized_title = sanitize_title(title_text)
            
            await context.log(f"Comic official title: {title_text}", "info")
            task.comic_title = title_text
            
            old_folder_name = task.artifacts.get("download_folder_name")
            new_folder_name = f"{sanitized_title}_{task.from_episode}_{task.to_episode}_{task.payload.get('language', 'vi')}"
            project_dir = os.path.dirname(os.path.abspath(__file__))
            new_download_dir = os.path.join(project_dir, "downloads", new_folder_name)
            
            if old_folder_name != new_folder_name and download_dir and os.path.exists(download_dir):
                try:
                    if os.path.exists(new_download_dir):
                        # Destination directory already exists. Merge contents instead of nesting.
                        for item in os.listdir(download_dir):
                            s = os.path.join(download_dir, item)
                            d = os.path.join(new_download_dir, item)
                            if os.path.isdir(s):
                                if os.path.exists(d):
                                    shutil.rmtree(d)
                                shutil.move(s, d)
                            else:
                                if os.path.exists(d):
                                    os.remove(d)
                                shutil.copy2(s, d)
                        shutil.rmtree(download_dir)
                    else:
                        shutil.move(download_dir, new_download_dir)
                    await context.log(f"Đã đổi tên thư mục sang {new_folder_name}", "info")
                except Exception as e:
                    await context.log(f"Không thể đổi tên: {e}", "warning")
                    new_download_dir = download_dir
                    new_folder_name = old_folder_name
            
            task.artifacts["download_folder_name"] = new_folder_name
            task.artifacts["download_dir"] = new_download_dir
            task.artifacts["comic_title"] = title_text
            
            await context.update_stage_progress(self.name, 100.0)
            return True
        finally:
            if 'page' in locals() and page:
                try:
                    await page.close()
                except Exception:
                    pass

async def execute_single_episode_stage2(
    ep: int,
    context: WorkflowContext,
    context_pw=None,
    nav_manager=None,
    dl_sem: Optional[asyncio.Semaphore] = None
) -> bool:
    """Stage 2 - Image Crawling for a single episode."""
    stage_name = "Stage 2 - Image Crawling"
    from app import get_shared_browser_context, NavigationManager, download_image
    
    task = context.task
    url = task.comic_url
    download_dir = task.artifacts.get("download_dir")
    ep_key = str(ep)
    if ep_key not in task.episode_progress:
        task.episode_progress[ep_key] = {}
        
    ep_images_dir = os.path.join(download_dir, f"episode_{ep}", "images")
    has_crawled_images = is_episode_images_ready(ep, download_dir)
    if check_episode_completed(download_dir, ep) or has_crawled_images:
        await context.log(f"Tập {ep}: Đã có sẵn ảnh crawl hợp lệ trên ổ đĩa. Bỏ qua crawling.", "success", stage_name=stage_name, episode=ep)
        task.episode_progress[ep_key][stage_name] = StageState.SUCCESS
        task.episode_progress[ep_key]["Stage 2 - Async Image Crawling"] = StageState.SUCCESS
        total_eps = task.to_episode - task.from_episode + 1
        completed = sum(1 for e in range(task.from_episode, task.to_episode + 1) if task.episode_progress.get(str(e), {}).get(stage_name) == StageState.SUCCESS)
        await context.update_stage_progress(stage_name, (completed / total_eps) * 100.0)
        return True

    task.episode_progress[ep_key][stage_name] = StageState.RUNNING
    await context.manager.save_and_broadcast("EpisodeProgressUpdated", task)

    parsed = urllib.parse.urlparse(url)
    is_vortex = "vortexscans.org" in parsed.netloc
    is_toongod = "toongod.org" in parsed.netloc
    is_asura = "asura" in parsed.netloc.lower()
    is_comix = "comix.to" in parsed.netloc
    is_valir = "valirscans.org" in parsed.netloc.lower()
    is_nyx = "nyxscans.com" in parsed.netloc.lower()
    is_manhuaplus = "manhuaplus.com" in parsed.netloc.lower()
    is_naver = "comic.naver.com" in parsed.netloc.lower()
    
    if is_vortex:
        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "series":
            series_slug = parts[1]
        else:
            await context.log("Không tìm thấy series slug trong URL Vortex Scans.", "error", stage_name=stage_name, episode=ep)
            task.episode_progress[ep_key][stage_name] = StageState.FAILED
            return False
    elif is_toongod:
        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "webtoon":
            series_slug = parts[1]
        else:
            await context.log("Không tìm thấy series slug trong URL ToonGod.", "error", stage_name=stage_name, episode=ep)
            task.episode_progress[ep_key][stage_name] = StageState.FAILED
            return False
    elif is_asura:
        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] in ["comics", "series"]:
            asura_prefix = parts[0]
            series_slug = parts[1]
        elif len(parts) >= 1 and parts[0]:
            asura_prefix = "series"
            series_slug = parts[0]
        else:
            await context.log("Không tìm thấy series slug trong URL Asura Scans.", "error", stage_name=stage_name, episode=ep)
            task.episode_progress[ep_key][stage_name] = StageState.FAILED
            return False
    elif is_comix:
        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "title":
            series_slug = parts[1]
        else:
            await context.log("Không tìm thấy series slug trong URL Comix.", "error", stage_name=stage_name, episode=ep)
            task.episode_progress[ep_key][stage_name] = StageState.FAILED
            return False
    elif is_valir:
        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 3 and parts[0] == "series":
            series_slug = "/".join(parts[1:])
        elif len(parts) >= 2 and parts[0] == "series":
            series_slug = parts[1]
        else:
            await context.log("Không tìm thấy series slug trong URL Valir Scans.", "error", stage_name=stage_name, episode=ep)
            task.episode_progress[ep_key][stage_name] = StageState.FAILED
            return False
    elif is_nyx:
        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "series":
            series_slug = parts[1]
        else:
            await context.log("Không tìm thấy series slug trong URL Nyx Scans.", "error", stage_name=stage_name, episode=ep)
            task.episode_progress[ep_key][stage_name] = StageState.FAILED
            return False
    elif is_manhuaplus:
        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "manga":
            series_slug = parts[1]
        elif len(parts) >= 1 and parts[0]:
            series_slug = parts[0]
        else:
            await context.log("Không tìm thấy series slug trong URL ManhuaPlus.", "error", stage_name=stage_name, episode=ep)
            task.episode_progress[ep_key][stage_name] = StageState.FAILED
            return False
    elif is_naver:
        query = urllib.parse.parse_qs(parsed.query)
        naver_title_id = query.get("titleId", [""])[0] or task.artifacts.get("naver_title_id", "")
        if not naver_title_id:
            await context.log("Không tìm thấy titleId trong URL Naver Webtoon.", "error", stage_name=stage_name, episode=ep)
            task.episode_progress[ep_key][stage_name] = StageState.FAILED
            return False
    else:
        query = urllib.parse.parse_qs(parsed.query)
        title_no = query.get("title_no", [""])[0]
        if not title_no:
            await context.log("Không tìm thấy title_no trong URL.", "error", stage_name=stage_name, episode=ep)
            task.episode_progress[ep_key][stage_name] = StageState.FAILED
            return False
        parts = parsed.path.strip("/").split("/")
        base_path = "/".join(parts[:-1])

    if context_pw is None or nav_manager is None:
        from app import load_config
        headless_val = task.payload.get("headless") if task.payload.get("headless") is not None else load_config().get("headless", False)
        browser, context_pw = await get_shared_browser_context(headless=headless_val)
        nav_manager = NavigationManager(context)
        nav_manager.context = context_pw
        nav_manager.browser = browser

    async def block_resources(route):
        req_type = route.request.resource_type
        url_lower = route.request.url.lower()
        if req_type in ["font", "media"] or any(
            keyword in url_lower
            for keyword in ["google-analytics", "doubleclick", "facebook", "analytics", "tracking", "adsbygoogle", "popads", "popunder", "adnxs", "optimizely", "hotjar"]
        ):
            try:
                await route.abort()
            except Exception:
                pass
        else:
            try:
                await route.continue_()
            except Exception:
                pass

    last_error_msg = "Không rõ lỗi"
    for attempt_idx in range(1, 4):
        if context.cancel_token.is_cancelled():
            raise asyncio.CancelledError()

        page = None
        try:
            page = await context_pw.new_page()
            try:
                await page.route("**/*", block_resources)
            except Exception:
                pass
            
            if is_vortex:
                slugs = task.artifacts.get("chapter_slugs", [])
                chapter_slug = resolve_chapter_slug(slugs, ep, default_prefix="chapter-")
                viewer_url = f"{parsed.scheme}://{parsed.netloc}/series/{series_slug}/{chapter_slug}"
                wait_sel = "img[data-reader-page-image]"
            elif is_toongod:
                slugs = task.artifacts.get("chapter_slugs", [])
                chapter_slug = resolve_chapter_slug(slugs, ep, default_prefix="chapter-")
                viewer_url = f"{parsed.scheme}://{parsed.netloc}/webtoon/{series_slug}/{chapter_slug}/"
                wait_sel = ".reading-content img, .wp-manga-chapter-img, div.page-break img, #chapter_imgs img"
            elif is_asura:
                slugs = task.artifacts.get("chapter_slugs", [])
                chapter_slug = resolve_chapter_slug(slugs, ep, default_prefix="")
                viewer_url = f"{parsed.scheme}://{parsed.netloc}/{asura_prefix}/{series_slug}/chapter/{chapter_slug}"
                wait_sel = "main img.w-full.block, .ch-images img, .reading-content img, div.flex.flex-col.items-center img, img[alt*='chapter']"
            elif is_valir:
                slugs = task.artifacts.get("chapter_slugs", [])
                chapter_slug = resolve_chapter_slug(slugs, ep, default_prefix="")
                viewer_url = f"{parsed.scheme}://{parsed.netloc}/series/{series_slug}/chapter/{chapter_slug}"
                wait_sel = "img.select-none"
            elif is_nyx:
                slugs = task.artifacts.get("chapter_slugs", [])
                chapter_slug = resolve_chapter_slug(slugs, ep, default_prefix="chapter-")
                viewer_url = f"{parsed.scheme}://{parsed.netloc}/series/{series_slug}/{chapter_slug}"
                wait_sel = "img"
            elif is_manhuaplus:
                slugs = task.artifacts.get("chapter_slugs", [])
                chapter_slug = resolve_chapter_slug(slugs, ep, default_prefix="chapter-")
                viewer_url = f"{parsed.scheme}://{parsed.netloc}/manga/{series_slug}/{chapter_slug}/"
                wait_sel = ".reading-content img, .wp-manga-chapter-img, div.page-break img, #chapter_imgs img, img[src*='cdn.manhuaplus.com']"
            elif is_comix:
                slugs = task.artifacts.get("chapter_slugs", [])
                user_chap_id = task.artifacts.get("user_comix_chap_id")
                user_chap_num = task.artifacts.get("user_comix_chap_num")
                payload_group_id = task.payload.get("comix_group_id")
                
                def resolve_slug(ep_n):
                    chapters_info = task.artifacts.get("comix_chapters_info", [])
                    if payload_group_id:
                        for info in chapters_info:
                            if info["chapter_num"] is not None and abs(info["chapter_num"] - ep_n) < 0.01:
                                if info["group_id"] == payload_group_id or (info["group_name"] and info["group_name"].strip().lower() == payload_group_id.strip().lower()):
                                    return info["slug"]
                        for info in chapters_info:
                            if info["chapter_num"] is not None and abs(info["chapter_num"] - ep_n) < 0.01:
                                if info["slug"].startswith(f"{payload_group_id}-"):
                                    return info["slug"]
                    if user_chap_id and user_chap_num is not None and abs(user_chap_num - ep_n) < 0.01:
                        for info in chapters_info:
                            if info["chapter_num"] is not None and abs(info["chapter_num"] - ep_n) < 0.01:
                                if info["slug"].startswith(f"{user_chap_id}-"):
                                    return info["slug"]
                        if user_chap_num.is_integer():
                            return f"{user_chap_id}-chapter-{int(user_chap_num)}"
                        else:
                            return f"{user_chap_id}-chapter-{user_chap_num}"
                    for info in chapters_info:
                        if info["chapter_num"] is not None and abs(info["chapter_num"] - ep_n) < 0.01:
                            return info["slug"]
                    return None

                all_slugs = task.artifacts.get("all_chapter_slugs", [])
                chapter_slug = resolve_slug(ep)
                
                if not chapter_slug:
                    current_page = 2
                    while not chapter_slug and current_page <= 50:
                        await context.log(f"Tải trang mục lục {current_page} để tìm link cho tập {ep}...", "info", stage_name=stage_name, episode=ep)
                        list_url = f"{parsed.scheme}://{parsed.netloc}/title/{series_slug}/?page={current_page}"
                        try:
                            await nav_manager.safe_goto(page, list_url, reason=f"Parse chapters page {current_page} dynamically", caller="Stage2_AsyncImageCrawling")
                            await page.wait_for_load_state("networkidle", timeout=5000)
                            chapters_data = await page.locator("div.mchap-row").evaluate_all("""
                                elements => elements.map(row => {
                                    const primary = row.querySelector('a.mchap-row__primary');
                                    const group = row.querySelector('a.mchap-row__group');
                                    return {
                                        href: primary ? primary.getAttribute('href') : null,
                                        group_href: group ? group.getAttribute('href') : null,
                                        group_name: group ? group.textContent.trim() : null
                                    };
                                })
                            """)
                            
                            page_chapters_info = []
                            for item in chapters_data:
                                href = item.get("href")
                                if href and "/title/" in href and "chapter" in href:
                                    parsed_href = urllib.parse.urlparse(href)
                                    parts = parsed_href.path.strip("/").split("/")
                                    if len(parts) >= 3 and parts[0] == "title":
                                        slug = parts[-1]
                                        group_id = None
                                        group_href = item.get("group_href")
                                        if group_href:
                                            group_parts = group_href.strip("/").split("/")
                                            if group_parts:
                                                group_id = group_parts[-1]
                                                
                                        m = re.search(r"chapter-(\d+\.?\d*)", slug)
                                        ch_num = None
                                        if m:
                                            try:
                                                ch_num = float(m.group(1))
                                            except ValueError:
                                                pass
                                        
                                        page_chapters_info.append({
                                            "slug": slug,
                                            "group_id": group_id,
                                            "group_name": item.get("group_name"),
                                            "chapter_num": ch_num
                                        })
                                        
                            if not page_chapters_info:
                                break
                                
                            current_info = task.artifacts.get("comix_chapters_info", [])
                            for item in page_chapters_info:
                                if not any(x["slug"] == item["slug"] for x in current_info):
                                    current_info.append(item)
                                if item["slug"] not in all_slugs:
                                    all_slugs.append(item["slug"])
                                if item["slug"] not in slugs:
                                    slugs.append(item["slug"])
                                    
                            task.artifacts["comix_chapters_info"] = current_info
                            task.artifacts["all_chapter_slugs"] = all_slugs
                            task.artifacts["chapter_slugs"] = slugs
                            chapter_slug = resolve_slug(ep)
                        except Exception as parse_err:
                            await context.log(f"Không thể tải trang mục lục động: {parse_err}", "warning", stage_name=stage_name, episode=ep)
                            break
                        current_page += 1
                                
                if not chapter_slug:
                    chapter_slug = resolve_chapter_slug(slugs, ep, default_prefix="")
                        
                viewer_url = f"{parsed.scheme}://{parsed.netloc}/title/{series_slug}/{chapter_slug}"
                wait_sel = ".rpage-main, img.rpage-page__img"
            elif is_naver:
                slugs = task.artifacts.get("chapter_slugs", [])
                chapter_slug = resolve_chapter_slug(slugs, ep, default_prefix="")
                target_no = chapter_slug if chapter_slug else str(ep)
                viewer_url = f"https://comic.naver.com/webtoon/detail?titleId={naver_title_id}&no={target_no}"
                wait_sel = ".wt_viewer img, #comic_view_area img, div.wt_viewer img, img[src*='image-comic.pstatic.net']"
            else:
                viewer_url = f"{parsed.scheme}://{parsed.netloc}/{base_path}/ep-{ep}/viewer?title_no={title_no}&episode_no={ep}"
                wait_sel = "#_imageList img"
                
            goto_wait_until = "domcontentloaded"
            await nav_manager.safe_goto(page, viewer_url, reason=f"Download ep {ep} images (attempt {attempt_idx}/3)", caller="Stage2_AsyncImageCrawling", wait_until=goto_wait_until)

            wait_state = "attached" if is_manhuaplus else "visible"
            selector_found = False
            for sel_attempt in range(1, 4):
                try:
                    await page.wait_for_selector(wait_sel, timeout=15000, state=wait_state)
                    selector_found = True
                    break
                except Exception as wait_err:
                    curr_url = page.url
                    curr_title = ""
                    try:
                        curr_title = await page.title()
                    except Exception:
                        pass
                    if "just a moment" in curr_title.lower() or "cloudflare" in curr_title.lower():
                        await context.log(f"Tập {ep} (Lần {attempt_idx}/3): Đang đợi giải quyết Cloudflare ('{curr_title}')...", "warning", stage_name=stage_name, episode=ep)
                        await asyncio.sleep(5)
                    else:
                        await context.log(f"Tập {ep} (Lần {attempt_idx}/3): Chờ selector ảnh: {wait_err}. URL: {curr_url}", "warning", stage_name=stage_name, episode=ep)
                        await asyncio.sleep(2)

            if not selector_found:
                raise RuntimeError(f"Không tìm thấy selector ảnh '{wait_sel}' trên trang.")

            if is_comix:
                try:
                    scroll_height = await page.locator(".rpage-main").evaluate("el => el.scrollHeight")
                    current_scroll = 0
                    step = 6000
                    while current_scroll < scroll_height:
                        current_scroll += step
                        await page.locator(".rpage-main").evaluate(f"el => el.scrollTop = {current_scroll}")
                        await asyncio.sleep(0.2)
                        scroll_height = await page.locator(".rpage-main").evaluate("el => el.scrollHeight")
                except Exception as e:
                    await context.log(f"Lỗi scroll trang comix: {e}", "warning", stage_name=stage_name, episode=ep)

            if is_vortex:
                image_urls = await page.locator("img[data-reader-page-image]").evaluate_all(
                    "elements => elements.map(el => el.getAttribute('src'))"
                )
            elif is_toongod:
                image_urls = []
                for selector in [".reading-content img", ".wp-manga-chapter-img", "div.page-break img", "#chapter_imgs img"]:
                    cnt = await page.locator(selector).count()
                    if cnt > 0:
                        image_urls = await page.locator(selector).evaluate_all(
                            "elements => elements.map(el => el.getAttribute('data-src') || el.getAttribute('src') || el.getAttribute('data-cdn'))"
                        )
                        break
            elif is_asura:
                image_urls = []
                for selector in ["main img.w-full.block", ".ch-images img", ".reading-content img", "div.flex.flex-col.items-center img"]:
                    cnt = await page.locator(selector).count()
                    if cnt > 0:
                        image_urls = await page.locator(selector).evaluate_all(
                            "elements => elements.map(el => el.getAttribute('data-src') || el.getAttribute('src') || el.getAttribute('data-cdn'))"
                        )
                        break
            elif is_comix:
                image_urls = await page.locator("img.rpage-page__img").evaluate_all(
                    "elements => elements.map(el => el.getAttribute('src'))"
                )
            elif is_valir:
                try:
                    html_content = await page.content()
                    chunks = re.findall(r'self\.__next_f\.push\(\s*\[\s*\d+\s*,\s*"(.*?)"\s*\]\s*\)', html_content)
                    if not chunks:
                        chunks = re.findall(r"self\.__next_f\.push\(\s*\[\s*\d+\s*,\s*'(.*?)'\s*\]\s*\)", html_content)
                    
                    full_rsc_text = ""
                    for chunk in chunks:
                        try:
                            unescaped = json.loads(f'"{chunk}"')
                            full_rsc_text += unescaped
                        except Exception:
                            unescaped = chunk.replace('\\"', '"').replace('\\\\', '\\')
                            full_rsc_text += unescaped
                    
                    image_urls = []
                    pages_pos = full_rsc_text.find('"pages":[')
                    if pages_pos != -1:
                        brackets_count = 0
                        in_string = False
                        escape = False
                        start_index = pages_pos + len('"pages":')
                        end_index = -1
                        for idx in range(start_index, len(full_rsc_text)):
                            char = full_rsc_text[idx]
                            if escape:
                                escape = False
                                continue
                            if char == '\\':
                                escape = True
                                continue
                            if char == '"':
                                in_string = not in_string
                                continue
                            if not in_string:
                                if char == '[':
                                    brackets_count += 1
                                elif char == ']':
                                    brackets_count -= 1
                                    if brackets_count == 0:
                                        end_index = idx + 1
                                        break
                        if end_index != -1:
                            try:
                                pages_list = json.loads(full_rsc_text[start_index:end_index])
                                pages_sorted = sorted(pages_list, key=lambda p: p.get("pageNumber", 0))
                                image_urls = [p.get("imageUrl") for p in pages_sorted if p.get("imageUrl")]
                            except Exception:
                                pass
                    
                    if not image_urls:
                        image_urls = re.findall(r'"imageUrl"\s*:\s*"([^"]+)"', full_rsc_text)
                        
                    if not image_urls:
                        image_urls = await page.locator("img.select-none").evaluate_all(
                            "elements => elements.map(el => el.getAttribute('src'))"
                        )
                except Exception as ext_err:
                    await context.log(f"Lỗi trích xuất ảnh Valir: {ext_err}. Dùng fallback DOM.", "warning", stage_name=stage_name, episode=ep)
                    image_urls = await page.locator("img.select-none").evaluate_all(
                        "elements => elements.map(el => el.getAttribute('src'))"
                    )
            elif is_nyx:
                async def extract_nyx_images_from_page():
                    try:
                        dom_imgs = await page.locator("img").evaluate_all(
                            "elements => elements.map(el => el.getAttribute('src') || el.getAttribute('data-src') || el.src).filter(s => s && s.includes('upload/series/') && !s.includes('featured'))"
                        )
                        imgs = list(dict.fromkeys([u for u in dom_imgs if u]))
                        if imgs:
                            return imgs
                    except Exception:
                        pass

                    try:
                        html_content = await page.content()
                        chunks = re.findall(r'self\.__next_f\.push\(\s*\[\s*\d+\s*,\s*"(.*?)"\s*\]\s*\)', html_content)
                        if not chunks:
                            chunks = re.findall(r"self\.__next_f\.push\(\s*\[\s*\d+\s*,\s*'(.*?)'\s*\]\s*\)", html_content)
                        full_rsc_text = ""
                        for chunk in chunks:
                            try:
                                unescaped = json.loads(f'"{chunk}"')
                                full_rsc_text += unescaped
                            except Exception:
                                unescaped = chunk.replace('\\"', '"').replace('\\\\', '\\')
                                full_rsc_text += unescaped
                        urls = re.findall(r'https?://[^\s"\'<>]+\.(?:webp|jpg|jpeg|png)', full_rsc_text)
                        imgs = list(dict.fromkeys([u for u in urls if "upload/series/" in u and "featured" not in u]))
                        if imgs:
                            return imgs
                    except Exception:
                        pass
                    return []

                image_urls = await extract_nyx_images_from_page()

                if not image_urls:
                    fallback_slugs = [
                        f"chapter-{ep}_01", f"chapter-{ep}-01", f"chapter-{ep}_1", f"chapter-{ep}-1",
                        f"chapter-{str(ep).zfill(2)}", f"chapter-{str(ep).zfill(3)}",
                        f"chapter-{ep}", f"chapter-{ep}.0", f"chapter-{ep}_001", f"chapter-{ep}.1"
                    ]
                    for alt_slug in fallback_slugs:
                        if alt_slug == chapter_slug:
                            continue
                        alt_url = f"{parsed.scheme}://{parsed.netloc}/series/{series_slug}/{alt_slug}"
                        await context.log(f"Tập {ep}: Thử đường dẫn tập thay thế trên Nyx Scans: {alt_slug}...", "info", stage_name=stage_name, episode=ep)
                        try:
                            await nav_manager.safe_goto(page, alt_url, reason=f"Try alternate Nyx chapter {alt_slug}", caller="Stage2_AsyncImageCrawling", wait_until="domcontentloaded")
                            await asyncio.sleep(1.0)
                            image_urls = await extract_nyx_images_from_page()
                            if image_urls:
                                await context.log(f"Tập {ep}: Đã tìm thấy {len(image_urls)} ảnh với đường dẫn '{alt_slug}'!", "success", stage_name=stage_name, episode=ep)
                                chapter_slug = alt_slug
                                break
                        except Exception:
                            pass

                if not image_urls:
                    series_index_url = f"{parsed.scheme}://{parsed.netloc}/series/{series_slug}"
                    await context.log(f"Tập {ep}: Tải trang mục lục {series_index_url} để quét lại danh sách tập...", "info", stage_name=stage_name, episode=ep)
                    try:
                        await nav_manager.safe_goto(page, series_index_url, reason="Scan Nyx series index dynamically", caller="Stage2_AsyncImageCrawling", wait_until="domcontentloaded")
                        await asyncio.sleep(0.5)
                        # Expand Show more if present
                        for _ in range(10):
                            sm_btn = page.locator("button:has-text('Show more'), button:has-text('Show More')").first
                            if await sm_btn.count() > 0 and await sm_btn.is_visible():
                                try:
                                    await sm_btn.click()
                                    await asyncio.sleep(0.6)
                                except Exception:
                                    break
                            else:
                                break
                        series_html = await page.content()
                        raw_matches = re.findall(r'chapter-[a-zA-Z0-9_\.-]+', series_html)
                        all_found_slugs = []
                        for rm in raw_matches:
                            clean_rm = re.sub(r'["\',;\\/<>].*$', '', rm).strip()
                            if clean_rm and clean_rm.startswith("chapter-") and len(clean_rm) <= 40:
                                all_found_slugs.append(clean_rm)
                        if all_found_slugs:
                            all_found_slugs = list(dict.fromkeys(all_found_slugs))
                            resolved_alt = resolve_chapter_slug(all_found_slugs, ep, default_prefix="chapter-")
                            if resolved_alt and resolved_alt != chapter_slug:
                                alt_url = f"{parsed.scheme}://{parsed.netloc}/series/{series_slug}/{resolved_alt}"
                                await context.log(f"Tập {ep}: Tìm thấy slug '{resolved_alt}' từ mục lục. Đang điều hướng...", "info", stage_name=stage_name, episode=ep)
                                await nav_manager.safe_goto(page, alt_url, reason=f"Navigate to resolved Nyx slug {resolved_alt}", caller="Stage2_AsyncImageCrawling", wait_until="domcontentloaded")
                                await asyncio.sleep(1.0)
                                image_urls = await extract_nyx_images_from_page()
                    except Exception as idx_err:
                        await context.log(f"Tập {ep}: Lỗi quét mục lục động Nyx: {idx_err}", "warning", stage_name=stage_name, episode=ep)
            elif is_manhuaplus:
                image_urls = []
                for selector in [".reading-content img", ".wp-manga-chapter-img", "div.page-break img", "#chapter_imgs img", "img[src*='cdn.manhuaplus.com']"]:
                    cnt = await page.locator(selector).count()
                    if cnt > 0:
                        image_urls = await page.locator(selector).evaluate_all(
                            "elements => elements.map(el => el.getAttribute('data-src') || el.getAttribute('src') || el.getAttribute('data-cdn')).filter(Boolean)"
                        )
                        if image_urls:
                            break
                if not image_urls:
                    image_urls = await page.locator("img").evaluate_all(
                        "elements => elements.map(el => el.getAttribute('data-src') || el.getAttribute('src') || el.src).filter(s => s && s.includes('cdn.manhuaplus.com'))"
                    )
            elif is_naver:
                image_urls = await page.locator(".wt_viewer img, #comic_view_area img, div.wt_viewer img, img[src*='image-comic.pstatic.net']").evaluate_all(
                    "elements => elements.map(el => el.getAttribute('src') || el.getAttribute('data-src')).filter(s => s && (s.includes('image-comic.pstatic.net') || s.includes('pstatic.net') || s.includes('naver')))"
                )
            else:
                image_urls = await page.locator("#_imageList img").evaluate_all(
                    "elements => elements.map(el => el.getAttribute('data-url') || el.getAttribute('src'))"
                )
            image_urls = [src for src in image_urls if src]

            if not image_urls:
                raise RuntimeError(f"Không tìm thấy danh sách URL ảnh trên trang.")

            ep_dir = os.path.join(download_dir, f"episode_{ep}")
            images_dir = os.path.join(ep_dir, "images")
            os.makedirs(images_dir, exist_ok=True)

            success_count = 0
            if dl_sem is None:
                dl_concurrency = min(5, max(1, task.payload.get("concurrency", 3)))
                dl_sem = asyncio.Semaphore(dl_concurrency)

            async def dl_task(img_url, img_idx):
                nonlocal success_count
                async with dl_sem:
                    file_ext = ".jpg"
                    if ".png" in img_url.lower(): file_ext = ".png"
                    elif ".webp" in img_url.lower(): file_ext = ".webp"
                    save_path = os.path.join(images_dir, f"{str(img_idx).zfill(3)}{file_ext}")
                    
                    if is_vortex:
                        referer = "https://vortexscans.org/"
                    elif is_toongod:
                        referer = "https://www.toongod.org/"
                    elif is_asura:
                        referer = f"{parsed.scheme}://{parsed.netloc}/"
                    elif is_comix:
                        referer = "https://comix.to/"
                    elif is_valir:
                        referer = "https://valirscans.org/"
                    elif is_nyx:
                        referer = "https://nyxscans.com/"
                    elif is_manhuaplus:
                        referer = "https://manhuaplus.com/"
                    elif is_naver:
                        referer = "https://comic.naver.com/"
                    else:
                        referer = "https://www.webtoons.com/"
                        
                    try:
                        await download_image(img_url, save_path, referer=referer, browser_context=context_pw)
                        if os.path.exists(save_path) and os.path.getsize(save_path) > 0:
                            success_count += 1
                        else:
                            if os.path.exists(save_path):
                                try: os.remove(save_path)
                                except Exception: pass
                            raise ValueError("File ảnh tải về có kích thước 0 bytes.")
                    except Exception as e:
                        try:
                            await asyncio.sleep(0.5)
                            await download_image(img_url, save_path, referer=referer, browser_context=context_pw)
                            if os.path.exists(save_path) and os.path.getsize(save_path) > 0:
                                success_count += 1
                            else:
                                if os.path.exists(save_path):
                                    try: os.remove(save_path)
                                    except Exception: pass
                                await context.log(f"Lỗi tải ảnh {img_idx} ({img_url}): File rỗng 0 bytes. Bỏ qua ảnh này.", "warning", stage_name=stage_name, episode=ep)
                        except Exception as retry_err:
                            if os.path.exists(save_path) and os.path.getsize(save_path) == 0:
                                try: os.remove(save_path)
                                except Exception: pass
                            await context.log(f"Lỗi tải ảnh {img_idx} ({img_url}): {retry_err}. Bỏ qua ảnh này.", "warning", stage_name=stage_name, episode=ep)
            
            await asyncio.gather(*[dl_task(u, i) for i, u in enumerate(image_urls, 1)])
            
            if success_count == 0:
                raise RuntimeError("Không tải được bất kỳ ảnh nào thành công (tất cả ảnh đều lỗi hoặc 0 bytes).")
            elif success_count < len(image_urls):
                await context.log(f"Tập {ep}: Tải thành công {success_count}/{len(image_urls)} ảnh.", "warning", stage_name=stage_name, episode=ep)
                
            task.episode_progress[ep_key][stage_name] = StageState.SUCCESS
            total_eps = task.to_episode - task.from_episode + 1
            completed = sum(1 for e in range(task.from_episode, task.to_episode + 1) if task.episode_progress.get(str(e), {}).get(stage_name) == StageState.SUCCESS)
            await context.update_stage_progress(stage_name, (completed / total_eps) * 100.0)
            return True
        except Exception as attempt_err:
            last_error_msg = str(attempt_err)
            if attempt_idx < 3:
                await context.log(f"Tập {ep}: Crawl lần {attempt_idx}/3 thất bại ({last_error_msg}). Đang thử lại...", "warning", stage_name=stage_name, episode=ep)
                if os.path.exists(ep_images_dir):
                    try:
                        for f in os.listdir(ep_images_dir):
                            fp = os.path.join(ep_images_dir, f)
                            if os.path.isfile(fp):
                                os.remove(fp)
                    except Exception:
                        pass
                await asyncio.sleep(attempt_idx * 1.5)
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass

    # Nếu sau 3 lần đều thất bại mới trả về trạng thái lỗi
    await context.log(f"Tập {ep}: Crawl ảnh thất bại sau 3 lần thử: {last_error_msg}.", "error", stage_name=stage_name, episode=ep)
    task.episode_progress[ep_key][stage_name] = StageState.FAILED
    return False

class Stage2_AsyncImageCrawling(BaseStage):
    @property
    def name(self) -> str: return "Stage 2 - Image Crawling"
    @property
    def weight(self) -> float: return 0.12

    async def execute(self, context: WorkflowContext) -> bool:
        from app import get_shared_browser_context, NavigationManager, load_config
        task = context.task
        from_ep = task.from_episode
        to_ep = task.to_episode
        
        headless_val = task.payload.get("headless") if task.payload.get("headless") is not None else load_config().get("headless", False)
        browser, context_pw = await get_shared_browser_context(headless=headless_val)
        nav_manager = NavigationManager(context)
        nav_manager.context = context_pw
        nav_manager.browser = browser

        dl_concurrency = min(5, max(1, task.payload.get("concurrency", 3)))
        dl_sem = asyncio.Semaphore(dl_concurrency)

        episodes = list(range(from_ep, to_ep + 1))
        results = []
        for i, ep in enumerate(episodes):
            if context.cancel_token.is_cancelled():
                raise asyncio.CancelledError()
            
            res = await execute_single_episode_stage2(ep, context, context_pw, nav_manager, dl_sem)
            results.append(res)
            
            if i < len(episodes) - 1 and not context.cancel_token.is_cancelled():
                delay = round(random.uniform(1.2, 2.5), 2)
                await asyncio.sleep(delay)

        return all(results)

async def execute_single_episode_stage3(
    ep: int,
    context: WorkflowContext,
    nsfw_sem: Optional[asyncio.Semaphore] = None
) -> bool:
    """Stage 3 - NSFW Moderation for a single episode."""
    stage_name = "Stage 3 - NSFW Moderation"
    task = context.task
    download_dir = task.artifacts.get("download_dir")
    ep_key = str(ep)
    if ep_key not in task.episode_progress:
        task.episode_progress[ep_key] = {}

    ep_images_pdf_dir = os.path.join(download_dir, f"episode_{ep}", "images_pdf")
    has_nsfw_images = os.path.exists(ep_images_pdf_dir) and any(f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) for f in os.listdir(ep_images_pdf_dir))
    if check_episode_completed(download_dir, ep) or (task.episode_progress.get(ep_key, {}).get(stage_name) == StageState.SUCCESS and has_nsfw_images):
        task.episode_progress[ep_key][stage_name] = StageState.SUCCESS
        total_eps = task.to_episode - task.from_episode + 1
        completed = sum(1 for e in range(task.from_episode, task.to_episode + 1) if task.episode_progress.get(str(e), {}).get(stage_name) == StageState.SUCCESS)
        await context.update_stage_progress(stage_name, (completed / total_eps) * 100.0)
        return True

    task.episode_progress[ep_key][stage_name] = StageState.RUNNING
    await context.manager.save_and_broadcast("EpisodeProgressUpdated", task)

    async def _run():
        ep_dir = os.path.join(download_dir, f"episode_{ep}")
        images_dir = os.path.join(ep_dir, "images")
        images_blur_dir = os.path.join(ep_dir, "images_blur")
        images_pdf_dir = os.path.join(ep_dir, "images_pdf")
        
        if os.path.exists(images_blur_dir):
            shutil.rmtree(images_blur_dir)
        os.makedirs(images_blur_dir, exist_ok=True)
        if os.path.exists(images_pdf_dir):
            shutil.rmtree(images_pdf_dir)
        os.makedirs(images_pdf_dir, exist_ok=True)

        image_files = sorted([f for f in os.listdir(images_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))])
        if not image_files:
            await context.log(f"Tập {ep}: Không tìm thấy ảnh gốc.", "error", stage_name=stage_name, episode=ep)
            task.episode_progress[ep_key][stage_name] = StageState.FAILED
            return False

        def copy_images():
            for f in image_files:
                shutil.copy2(os.path.join(images_dir, f), os.path.join(images_blur_dir, f))
                shutil.copy2(os.path.join(images_dir, f), os.path.join(images_pdf_dir, f))

        await asyncio.to_thread(copy_images)
        await context.log(f"Tập {ep}: Đã chuẩn bị ảnh sạch cho giai đoạn tạo PDF.", "info", stage_name=stage_name, episode=ep)
        task.episode_progress[ep_key][stage_name] = StageState.SUCCESS
        total_eps = task.to_episode - task.from_episode + 1
        completed = sum(1 for e in range(task.from_episode, task.to_episode + 1) if task.episode_progress.get(str(e), {}).get(stage_name) == StageState.SUCCESS)
        await context.update_stage_progress(stage_name, (completed / total_eps) * 100.0)
        return True

    if nsfw_sem:
        async with nsfw_sem:
            return await _run()
    else:
        return await _run()

class Stage3_NSFWModeration(BaseStage):
    @property
    def name(self) -> str: return "Stage 3 - NSFW Moderation"
    @property
    def weight(self) -> float: return 0.08

    async def execute(self, context: WorkflowContext) -> bool:
        task = context.task
        from_ep = task.from_episode
        to_ep = task.to_episode
        concurrency = task.payload.get("concurrency", 5)
        nsfw_sem = asyncio.Semaphore(max(1, concurrency))
        episodes = list(range(from_ep, to_ep + 1))
        results = await asyncio.gather(*[execute_single_episode_stage3(ep, context, nsfw_sem) for ep in episodes])
        return all(results)

def generate_chapter_pdf(
    image_files: list,
    images_pdf_dir: str,
    pdf_path: str,
    page_scores: Optional[dict] = None,
    max_pdf_pages: Optional[int] = None,
    pdf_quality: int = 20,
    max_width: int = 540,
    page_types: Optional[dict] = None
) -> None:
    """
    Builds a chapter PDF from smart pagination pages with 80% image compression:
    1. Resizes each smart page to max_width=540.
    2. Draws a 2px black cut line at top and bottom of each page for pagination separation.
    3. Adds a compact watermark in the top-left corner: 'Page: {page_num} - Type: {type_label}'.
    4. Each page in image_files is rendered as an independent physical page in the PDF (1-to-1).
    5. Saves optimized, highly-compressed PDF file (quality=20).
    """
    import io
    from PIL import Image, ImageDraw, ImageFont
    from renderer.smart_pagination import VisualSemanticScorer, SmartPaginator, PageType, PageTag
    import cv2
    import numpy as np
    
    if not image_files:
        return

    image_files = sorted(image_files, key=natural_sort_key)

    font = None
    for font_name in ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf", "segoeui.ttf"]:
        try:
            font = ImageFont.truetype(font_name, 18)
            break
        except Exception:
            pass
    if font is None:
        try:
            font = ImageFont.load_default(size=18)
        except Exception:
            font = ImageFont.load_default()

    watermarked_pages = []
    try:
        for idx, f in enumerate(image_files):
            img_path = os.path.join(images_pdf_dir, f)
            with Image.open(img_path) as img:
                rgb_img = img.convert("RGB")
                rgb_img.load()

                # 1. Resize to max width 540
                if rgb_img.width > max_width:
                    resample_filter = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
                    new_h = int(rgb_img.height * (max_width / rgb_img.width))
                    rgb_img = rgb_img.resize((max_width, new_h), resample_filter)

                w, h = rgb_img.width, rgb_img.height
                draw = ImageDraw.Draw(rgb_img)

                # 2. Nét cắt đen nhỏ 2px ở mép trên và mép dưới để phân trang
                draw.rectangle([0, 0, w - 1, 1], fill=(0, 0, 0))
                draw.rectangle([0, h - 2, w - 1, h - 1], fill=(0, 0, 0))

                # 3. Watermark nằm lệch về bên trái trên cùng của page:
                # 5-Tag Classification System:
                # CHARACTER_ART (KEEP), CHARACTER_SCENE (KEEP), BACKGROUND_SCENE (KEEP), ACTION_ART (KEEP), NON_VISUAL (REJECT)
                page_num = idx + 1
                total_pages = len(image_files)

                badge_tag = None
                raw_type = None
                if page_types and isinstance(page_types, dict):
                    raw_type = page_types.get(page_num) or page_types.get(str(page_num))

                np_bgr = cv2.cvtColor(np.array(rgb_img), cv2.COLOR_RGB2BGR)

                if raw_type:
                    s_upper = str(raw_type).strip().upper()
                    if s_upper in ("CHARACTER_ART", "CHARACTER_SCENE", "BACKGROUND_SCENE", "ACTION_ART", "NON_VISUAL"):
                        badge_tag = s_upper
                    elif s_upper in ("CREDIT_ADS", "CREDIT", "ADS", "RECRUITMENT", "BANNED", "DIALOGUE", "TEXT_ONLY", "TEXT_BUBBLE", "THOAI", "EMPTY_GUTTER"):
                        badge_tag = PageTag.NON_VISUAL
                    elif s_upper in ("VISUAL", "VISUAL_WITH_TEXT", "TRANH", "CONTENT", "ARTWORK", "PANEL", "SCENE", "MIXED"):
                        badge_tag = SmartPaginator.classify_page_tag(np_bgr)
                    else:
                        badge_tag = SmartPaginator.classify_page_tag(np_bgr)
                else:
                    badge_tag = SmartPaginator.classify_page_tag(np_bgr)

                # Direct safety checks (secondary verification)
                if (page_num <= 2 or page_num >= max(1, total_pages - 2)):
                    if SmartPaginator.is_credit_or_recruitment_page(np_bgr, page_index=page_num, total_pages=total_pages):
                        badge_tag = PageTag.NON_VISUAL

                if badge_tag == PageTag.NON_VISUAL:
                    text = f"Page: {page_num} - Type: NON_VISUAL (REJECT)"
                    bg_color = (220, 20, 40)      # Crimson / Red
                elif badge_tag == PageTag.CHARACTER_ART:
                    text = f"Page: {page_num} - Type: CHARACTER_ART (KEEP)"
                    bg_color = (0, 160, 40)       # Emerald Green
                elif badge_tag == PageTag.CHARACTER_SCENE:
                    text = f"Page: {page_num} - Type: CHARACTER_SCENE (KEEP)"
                    bg_color = (0, 140, 100)      # Teal Green
                elif badge_tag == PageTag.BACKGROUND_SCENE:
                    text = f"Page: {page_num} - Type: BACKGROUND_SCENE (KEEP)"
                    bg_color = (25, 100, 180)     # Royal Blue
                elif badge_tag == PageTag.ACTION_ART:
                    text = f"Page: {page_num} - Type: ACTION_ART (KEEP)"
                    bg_color = (210, 95, 0)       # Amber / Deep Orange
                else:
                    text = f"Page: {page_num} - Type: CHARACTER_SCENE (KEEP)"
                    bg_color = (0, 160, 40)

                if hasattr(draw, "textbbox"):
                    bbox = draw.textbbox((0, 0), text, font=font)
                    text_w = bbox[2] - bbox[0]
                    text_h = bbox[3] - bbox[1]
                else:
                    text_w, text_h = draw.textsize(text, font=font)

                pad_x = 10
                pad_y = 5
                box_w = text_w + pad_x * 2
                box_h = text_h + pad_y * 2

                margin_x = 10
                margin_y = 10
                x1 = margin_x
                y1 = margin_y
                x2 = x1 + box_w
                y2 = y1 + box_h

                draw.rectangle([x1, y1, x2, y2], fill=bg_color, outline=(255, 255, 255), width=2)
                draw.text((x1 + pad_x, y1 + pad_y), text, fill=(255, 255, 255), font=font)

                watermarked_pages.append(rgb_img)

        if not watermarked_pages:
            return

        # Mỗi page là 1 page vật lý riêng biệt trong file PDF
        pdf_physical_pages = watermarked_pages

        os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
        if os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
            except Exception:
                pass

        # Use PyMuPDF with JPEG quality=20 for lightweight PDF output (~80-95% file size reduction)
        try:
            try:
                import pymupdf as fitz
            except ImportError:
                import fitz

            doc = fitz.open()
            for rgb_img in pdf_physical_pages:
                buf = io.BytesIO()
                rgb_img.save(buf, format="JPEG", quality=pdf_quality, optimize=True)
                img_bytes = buf.getvalue()
                page = doc.new_page(width=rgb_img.width, height=rgb_img.height)
                page.insert_image(fitz.Rect(0, 0, rgb_img.width, rgb_img.height), stream=img_bytes)

            doc.save(pdf_path, deflate=True, garbage=4)
            doc.close()
        except Exception:
            pdf_physical_pages[0].save(
                pdf_path,
                "PDF",
                save_all=True,
                append_images=pdf_physical_pages[1:],
                quality=pdf_quality,
                optimize=True
            )
    finally:
        for p in watermarked_pages:
            try:
                p.close()
            except Exception:
                pass


async def execute_single_episode_stage4(
    ep: int,
    context: WorkflowContext,
    pdf_sem: Optional[asyncio.Semaphore] = None
) -> bool:
    """Stage 4 - PDF Generation for a single episode."""
    stage_name = "Stage 4 - PDF Generation"
    task = context.task
    download_dir = task.artifacts.get("download_dir")
    ep_key = str(ep)
    if ep_key not in task.episode_progress:
        task.episode_progress[ep_key] = {}

    ep_dir = os.path.join(download_dir, f"episode_{ep}")
    clean_title = "".join(c for c in task.comic_title if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
    pdf_name = f"{clean_title}_Tap_{ep}.pdf"
    pdf_path = os.path.join(ep_dir, "pdf", pdf_name)
    has_pdf = is_episode_pdf_ready(ep, download_dir, task.comic_title)
    if check_episode_completed(download_dir, ep) or has_pdf:
        await context.log(f"Tập {ep}: Đã có sẵn file PDF hợp lệ trên ổ đĩa. Bỏ qua Stage 4.", "success", stage_name=stage_name, episode=ep)
        task.episode_progress[ep_key][stage_name] = StageState.SUCCESS
        total_eps = task.to_episode - task.from_episode + 1
        completed = sum(1 for e in range(task.from_episode, task.to_episode + 1) if task.episode_progress.get(str(e), {}).get(stage_name) == StageState.SUCCESS)
        await context.update_stage_progress(stage_name, (completed / total_eps) * 100.0)
        return True

    task.episode_progress[ep_key][stage_name] = StageState.RUNNING
    await context.manager.save_and_broadcast("EpisodeProgressUpdated", task)

    async def _run():
        repaging_meta_path = os.path.join(ep_dir, "debug_repaging", "repaging_metadata.json")
        if not os.path.exists(repaging_meta_path):
            repaging_meta_path = os.path.join(ep_dir, "repaging_metadata.json")
        if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0 and os.path.exists(repaging_meta_path):
            await context.log(f"Tập {ep}: Đã có file PDF {pdf_name} chuẩn canvas gốc được vẽ visual regions từ Stage 2b.", "info", stage_name=stage_name, episode=ep)
            task.episode_progress[ep_key][stage_name] = StageState.SUCCESS
            total_eps = task.to_episode - task.from_episode + 1
            completed = sum(1 for e in range(task.from_episode, task.to_episode + 1) if task.episode_progress.get(str(e), {}).get(stage_name) == StageState.SUCCESS)
            await context.update_stage_progress(stage_name, (completed / total_eps) * 100.0)
            return True

        images_pdf_dir = os.path.join(ep_dir, "images_pdf")
        if not os.path.exists(images_pdf_dir):
            images_pdf_dir = os.path.join(ep_dir, "images")
        image_files = sorted([f for f in os.listdir(images_pdf_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))])
        if not image_files:
            await context.log(f"Tập {ep}: Không có ảnh để tạo PDF.", "error", stage_name=stage_name, episode=ep)
            task.episode_progress[ep_key][stage_name] = StageState.FAILED
            return False

        page_scores = {}
        page_types = {}
        if os.path.exists(repaging_meta_path):
            try:
                with open(repaging_meta_path, "r", encoding="utf-8") as mf:
                    meta_data = json.load(mf)
                    for p in meta_data.get("output_pages", []):
                        p_idx = p.get("pageIndex")
                        p_score = p.get("visualScore", p.get("point"))
                        p_type = p.get("page_tag") or p.get("pageTag") or p.get("tag") or p.get("contentType") or p.get("content_type") or p.get("pageType")
                        if p_idx is not None:
                            if p_score is not None:
                                page_scores[int(p_idx)] = int(p_score)
                            if p_type:
                                page_types[int(p_idx)] = str(p_type)
            except Exception:
                pass

        pdf_quality = task.payload.get("pdf_quality", 20)
        max_pdf_pages = task.payload.get("max_pdf_pages", None)
        await context.log(f"Tập {ep}: Tạo file PDF {pdf_name} ({len(image_files)} trang vật lý riêng biệt)...", "info", stage_name=stage_name, episode=ep)

        def convert_to_pdf():
            generate_chapter_pdf(
                image_files=image_files,
                images_pdf_dir=images_pdf_dir,
                pdf_path=pdf_path,
                page_scores=page_scores,
                max_pdf_pages=max_pdf_pages,
                pdf_quality=pdf_quality,
                page_types=page_types
            )

        await asyncio.to_thread(convert_to_pdf)
        task.episode_progress[ep_key][stage_name] = StageState.SUCCESS
        total_eps = task.to_episode - task.from_episode + 1
        completed = sum(1 for e in range(task.from_episode, task.to_episode + 1) if task.episode_progress.get(str(e), {}).get(stage_name) == StageState.SUCCESS)
        await context.update_stage_progress(stage_name, (completed / total_eps) * 100.0)
        return True

    if pdf_sem:
        async with pdf_sem:
            return await _run()
    else:
        return await _run()

class Stage4_PDFGeneration(BaseStage):
    @property
    def name(self) -> str: return "Stage 4 - PDF Generation"
    @property
    def weight(self) -> float: return 0.05

    async def execute(self, context: WorkflowContext) -> bool:
        task = context.task
        from_ep = task.from_episode
        to_ep = task.to_episode
        concurrency = task.payload.get("concurrency", 5)
        sem = asyncio.Semaphore(concurrency)

        episodes = list(range(from_ep, to_ep + 1))
        results = await asyncio.gather(*[execute_single_episode_stage4(ep, context, sem) for ep in episodes])
        return all(results)

async def execute_single_episode_stage5(
    ep: int,
    context: WorkflowContext,
    vlm_sem: Optional[asyncio.Semaphore] = None,
    profile_pool: Optional[Any] = None
) -> bool:
    """Stage 5 - Gemini Automation for a single episode."""
    stage_name = "Stage 5 - Gemini Automation"
    task = context.task
    download_dir = task.artifacts.get("download_dir")
    ep_key = str(ep)
    if ep_key not in task.episode_progress:
        task.episode_progress[ep_key] = {}

    has_recap_json = is_episode_script_ready(ep, download_dir)
    if check_episode_completed(download_dir, ep) or has_recap_json:
        await context.log(f"Tập {ep}: Đã có sẵn kịch bản recap.json hợp lệ trên ổ đĩa. Bỏ qua Stage 5.", "success", stage_name=stage_name, episode=ep)
        task.episode_progress[ep_key][stage_name] = StageState.SUCCESS
        total_eps = task.to_episode - task.from_episode + 1
        completed = sum(1 for e in range(task.from_episode, task.to_episode + 1) if task.episode_progress.get(str(e), {}).get(stage_name) == StageState.SUCCESS)
        await context.update_stage_progress(stage_name, (completed / total_eps) * 100.0)
        return True

    task.episode_progress[ep_key][stage_name] = StageState.RUNNING
    await context.manager.save_and_broadcast("EpisodeProgressUpdated", task)

    async def _run():
        from app import get_browser_context, NavigationManager, textbox_selectors, send_selectors, response_selectors, generate_gemini_prompt, generate_intro_prompt, extract_json_from_text, parse_gemini_recap_text, clean_gemini_response, verify_gemini_response_format, count_recap_sentences
        import uuid
        import base64
        import random

        comic_title = task.artifacts.get("comic_title", "Manhwa")
        timeout = task.payload.get("timeout", 90)
        language = task.payload.get("language", "vi")
        safe_mode = task.payload.get("safe_mode", False)
        gemini_model = task.payload.get("gemini_model", "flash")
        if not gemini_model or gemini_model == "default":
            gemini_model = "flash"
        max_retries = 3

        from app import load_config
        headless_val = task.payload.get("headless") if task.payload.get("headless") is not None else load_config().get("headless", False)
        async def get_local_context():
            from app import check_and_rotate_profiles_until_ready, NavigationManager
            br, shared_ctx = await check_and_rotate_profiles_until_ready(context, force_check=False, target_model=gemini_model, headless=headless_val)
            ctx_id = f"ctx_{int(time.time() * 1000) % 10000}"
            nm = NavigationManager(context)
            nm.context = shared_ctx
            nm.browser = br
            return br, shared_ctx, ctx_id, nm, False

        js_paste_pdf = """
        async (args) => {
            const { xpath, base64Data, fileName, mimeType } = args;
            let element = null;
            if (xpath) {
                try {
                    if (xpath.startsWith('xpath=')) {
                        const result = document.evaluate(xpath.replace('xpath=', ''), document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
                        element = result.singleNodeValue;
                    } else {
                        element = document.querySelector(xpath);
                    }
                } catch (e) {}
            }
            if (!element) {
                element = document.querySelector("rich-textarea div[contenteditable='true'], rich-textarea p, div.ql-editor, div[contenteditable='true'], [role='textbox']");
            }
            if (!element) throw new Error("Không tìm thấy ô nhập prompt để đính kèm tệp.");
            element.focus();
            const res = await fetch("data:" + mimeType + ";base64," + base64Data);
            const blob = await res.blob();
            const file = new File([blob], fileName, { type: mimeType });
            const dataTransfer = new DataTransfer();
            dataTransfer.items.add(file);
            const pasteEvent = new ClipboardEvent('paste', { bubbles: true, cancelable: true, clipboardData: dataTransfer });
            element.dispatchEvent(pasteEvent);
            
            const rich = element.closest('rich-textarea');
            if (rich && rich !== element) {
                rich.dispatchEvent(new ClipboardEvent('paste', { bubbles: true, cancelable: true, clipboardData: dataTransfer }));
            }
            return true;
        }
        """

        vlm_name = "Gemini"
        vlm_url = "https://gemini.google.com/app"
        ep_dir = os.path.join(download_dir, f"episode_{ep}")
        clean_title = "".join(c for c in task.comic_title if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
        pdf_name = f"{clean_title}_Tap_{ep}.pdf"
        pdf_path = os.path.join(ep_dir, "pdf", pdf_name)
        if not os.path.exists(pdf_path):
            pdf_dir = os.path.join(ep_dir, "pdf")
            if os.path.exists(pdf_dir):
                pdf_files = [f for f in os.listdir(pdf_dir) if f.lower().endswith(".pdf")]
                if pdf_files:
                    pdf_path = os.path.join(pdf_dir, pdf_files[0])
        images_pdf_dir = os.path.join(ep_dir, "images_pdf")
        if not os.path.exists(images_pdf_dir):
            images_pdf_dir = os.path.join(ep_dir, "images")
        raw_response_path = os.path.join(ep_dir, "raw_gemini_response.txt")
        recap_json_path = os.path.join(ep_dir, "recap.json")

        image_files = sorted([f for f in os.listdir(images_pdf_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))])
        prompt_content = generate_gemini_prompt(comic_title, ep, len(image_files), language)

        success = False
        start_time = time.time()
        safe_mode_applied = False

        for attempt in range(1, max_retries + 1):
            if context.cancel_token.is_cancelled():
                break

            # Ở lần retry thứ 3 trên tool: Bật che hình ảnh nhạy cảm (Safe Mode DINO+SAM) và tạo lại PDF an toàn (nếu safe_mode được bật)
            if safe_mode and attempt >= 3 and not safe_mode_applied:
                await context.log(f"Tập {ep}: [Tool Retry Lần {attempt}/3] Đang kích hoạt Safe Mode (DINO+SAM) để che nội dung nhạy cảm trước khi upload PDF lên {vlm_name}...", "warning", stage_name=stage_name, episode=ep)
                try:
                    from app import sanitize_episode_images
                    images_blur_dir = os.path.join(ep_dir, "images_blur")
                    images_pdf_dir = os.path.join(ep_dir, "images_pdf")
                    images_dir = os.path.join(ep_dir, "images")
                    if not os.path.exists(images_dir):
                        images_dir = images_pdf_dir if os.path.exists(images_pdf_dir) else ep_dir

                    if os.path.exists(images_blur_dir): shutil.rmtree(images_blur_dir)
                    os.makedirs(images_blur_dir, exist_ok=True)

                    image_files_to_blur = sorted([f for f in os.listdir(images_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]) if os.path.exists(images_dir) else []
                    for f_blur in image_files_to_blur:
                        shutil.copy2(os.path.join(images_dir, f_blur), os.path.join(images_blur_dir, f_blur))

                    if os.path.exists(images_pdf_dir): shutil.rmtree(images_pdf_dir)
                    os.makedirs(images_pdf_dir, exist_ok=True)

                    await sanitize_episode_images(
                        ep_dir=images_blur_dir,
                        nsfw_threshold=task.payload.get("nsfw_threshold", 0.3),
                        nsfw_mode=task.payload.get("nsfw_mode", "mask"),
                        sse_logger=context,
                        concurrency=task.payload.get("concurrency", 5),
                        pdf_dir=images_pdf_dir
                    )

                    await context.log(f"Tập {ep}: Đang tạo lại file PDF an toàn (Safe Mode) cho {vlm_name}...", "info", stage_name=stage_name, episode=ep)
                    image_pdf_files = sorted([f for f in os.listdir(images_pdf_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))])
                    if image_pdf_files:
                        pdf_quality = task.payload.get("pdf_quality", 20)
                        max_pdf_pages = task.payload.get("max_pdf_pages", None)

                        page_scores_sync = {}
                        page_types_sync = {}
                        repaging_meta_path_sync = os.path.join(ep_dir, "debug_repaging", "repaging_metadata.json")
                        if not os.path.exists(repaging_meta_path_sync):
                            repaging_meta_path_sync = os.path.join(ep_dir, "repaging_metadata.json")
                        if os.path.exists(repaging_meta_path_sync):
                            try:
                                with open(repaging_meta_path_sync, "r", encoding="utf-8") as mf:
                                    meta_data = json.load(mf)
                                    for p in meta_data.get("output_pages", []):
                                        p_idx = p.get("pageIndex")
                                        p_score = p.get("visualScore", p.get("point"))
                                        p_type = p.get("page_tag") or p.get("pageTag") or p.get("tag") or p.get("contentType") or p.get("content_type") or p.get("pageType")
                                        if p_idx is not None:
                                            if p_score is not None: page_scores_sync[int(p_idx)] = int(p_score)
                                            if p_type: page_types_sync[int(p_idx)] = str(p_type)
                            except Exception: pass

                        def convert_to_pdf_sync():
                            generate_chapter_pdf(
                                image_files=image_pdf_files,
                                images_pdf_dir=images_pdf_dir,
                                pdf_path=pdf_path,
                                page_scores=page_scores_sync,
                                max_pdf_pages=max_pdf_pages,
                                pdf_quality=pdf_quality,
                                page_types=page_types_sync
                            )
                        await asyncio.to_thread(convert_to_pdf_sync)
                        safe_mode_applied = True
                except Exception as safe_err:
                    await context.log(f"Lỗi kích hoạt Safe Mode: {safe_err}", "error", stage_name=stage_name, episode=ep)

            local_br_ctx = None
            should_close_ctx = False
            session_ctx = None
            current_profile_path = None
            try:
                local_br, local_br_ctx, local_ctx_id, local_nm, should_close_ctx = await get_local_context()

                js_check_state = """() => {
                    const isVis = (el) => {
                        if (!el) return false;
                        try {
                            const style = window.getComputedStyle(el);
                            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                            const rect = el.getBoundingClientRect();
                            return rect.width > 0 || rect.height > 0 || el.offsetWidth > 0 || el.offsetHeight > 0 || el.getClientRects().length > 0;
                        } catch (e) {
                            return el.offsetParent !== null;
                        }
                    };

                    // 1. Check if stop generating button is visible
                    const stopSelectors = [
                        "button[aria-label*='Stop' i]",
                        "button[aria-label*='stop' i]",
                        "button[aria-label*='Dừng' i]",
                        "button[aria-label*='dừng' i]",
                        "button[aria-label*='Cancel' i]",
                        "button[aria-label*='Hủy' i]",
                        "button[data-testid*='stop' i]",
                        "[data-testid*='stop' i]",
                        "gem-icon-button[aria-label*='Stop' i]",
                        "gem-icon-button[aria-label*='Dừng' i]",
                        ".stop-button",
                        ".stop-icon",
                        "button.stop-generating-button"
                    ];
                    let isGenerating = false;
                    for (const sel of stopSelectors) {
                        const el = document.querySelector(sel);
                        if (el && isVis(el)) {
                            isGenerating = true;
                            break;
                        }
                    }

                    // 2. Check if streaming or spinning indicators are active
                    if (!isGenerating) {
                        const streamSelectors = [
                            "[class*='streaming']",
                            "[class*='generating']",
                            "[class*='typing']",
                            ".blinking-cursor",
                            ".cursor",
                            "gem-streaming-indicator",
                            "sparkle-icon.animate-spin",
                            "[data-is-generating='true']",
                            "[data-is-streaming='true']",
                            "input-area-v2 [role='progressbar']",
                            "form [role='progressbar']"
                        ];
                        for (const sel of streamSelectors) {
                            const el = document.querySelector(sel);
                            if (el && isVis(el)) {
                                isGenerating = true;
                                break;
                            }
                        }
                    }

                    // 3. Find the latest model-response element
                    const modelResponses = document.querySelectorAll("model-response, [data-test-id='model-response'], .model-response, response-container");
                    let lastModel = null;
                    if (modelResponses.length > 0) {
                        lastModel = modelResponses[modelResponses.length - 1];
                    }
                    if (!lastModel) {
                        const contentEls = document.querySelectorAll(".response-content-markdown, message-content, div.markdown, div.prose");
                        for (let i = contentEls.length - 1; i >= 0; i--) {
                            const el = contentEls[i];
                            if (!el.closest("user-query, user-message, [data-test-id='user-query'], .user-query-container, .query-text")) {
                                lastModel = el;
                                break;
                            }
                        }
                    }

                    let text = "";
                    let hasActionBar = false;
                    if (lastModel) {
                        text = (lastModel.innerText || lastModel.textContent || "").trim();
                        const actionEl = lastModel.querySelector("message-actions, .message-actions, [data-testid='message-actions'], .response-bottom-actions, button[aria-label*='Copy' i], button[aria-label*='Sao chép' i], button[aria-label*='Good response' i]");
                        if (actionEl && isVis(actionEl)) {
                            hasActionBar = true;
                        }
                    }

                    return {
                        text: text,
                        is_generating: isGenerating,
                        has_action_bar: hasActionBar
                    };
                }"""

                async def click_gemini_redo_button(page) -> bool:
                    """Thực hiện click nút Redo / Regenerate / Thử lại trên giao diện Gemini."""
                    retry_selectors = [
                        "button[aria-label*='Modify response' i]",
                        "button[aria-label*='Modify' i]",
                        "button[aria-label*='Chỉnh sửa phản hồi' i]",
                        "button[aria-label*='Chỉnh sửa câu trả lời' i]",
                        "button[aria-label*='Chỉnh sửa' i]",
                        "button[aria-label*='Redo' i]",
                        "button[aria-label*='Retry' i]",
                        "button[aria-label*='Thử lại' i]",
                        "button[aria-label*='Regenerate' i]",
                        "button[aria-label*='Tạo lại' i]",
                        "button[aria-label*='Try again' i]",
                        "button[data-test-id='regenerate-button']",
                        "button[data-testid='retry-button']",
                        "button[mattooltip*='Redo' i]",
                        "button[mattooltip*='Retry' i]",
                        "button[mattooltip*='Thử lại' i]",
                        "gem-icon-button[aria-label*='Modify' i]",
                        "gem-icon-button[aria-label*='Redo' i]",
                        "gem-icon-button[aria-label*='Retry' i]",
                        "gem-icon-button[aria-label*='Thử lại' i]",
                        "button:has(mat-icon:has-text('redo'))",
                        "button:has(mat-icon:has-text('refresh'))",
                        "button:has(mat-icon:has-text('tune'))",
                        "button:has(mat-icon[fonticon='redo'])",
                        "message-actions button:has(mat-icon:has-text('redo'))",
                        "message-actions button:has(mat-icon:has-text('refresh'))",
                        "message-actions button:has(mat-icon:has-text('tune'))",
                        "button:has-text('Try again')",
                        "button:has-text('Thử lại')",
                        "button:has-text('Retry')"
                    ]
                    retry_btn = None
                    for r_sel in retry_selectors:
                        try:
                            r_loc = page.locator(r_sel).last
                            if await r_loc.count() > 0 and await r_loc.is_visible():
                                retry_btn = r_loc
                                break
                        except Exception:
                            pass

                    if not retry_btn:
                        try:
                            for bar_sel in ["message-actions", ".message-actions", "response-container .response-bottom-actions", "[data-testid='message-actions']", "div.message-actions"]:
                                bar = page.locator(bar_sel).last
                                if await bar.count() > 0 and await bar.is_visible():
                                    btns = bar.locator("button, gem-icon-button")
                                    b_count = await btns.count()
                                    for b_i in range(b_count):
                                        btn_cand = btns.nth(b_i)
                                        btn_html = (await btn_cand.inner_html()).lower()
                                        aria_l = (await btn_cand.get_attribute("aria-label") or "").lower()
                                        tooltip = (await btn_cand.get_attribute("mattooltip") or "").lower()
                                        if any(k in btn_html or k in aria_l or k in tooltip for k in ["modify", "chỉnh sửa", "tune", "refresh", "replay", "redo", "rotate", "arrow", "sync", "autorenew", "retry", "tạo lại", "thử lại"]):
                                            retry_btn = btn_cand
                                            break
                                    if not retry_btn and b_count >= 3:
                                        retry_btn = btns.nth(2)
                                if retry_btn:
                                    break
                        except Exception:
                            pass

                    if retry_btn:
                        try:
                            await human_delay(0.25, 0.6)
                            await retry_btn.click()
                            await asyncio.sleep(0.5)

                            menu_selectors = [
                                "[role='menuitem']:has-text('Try again')",
                                "[role='menuitem']:has-text('Thử lại')",
                                "[role='menuitem']:has-text('Thử làm lại')",
                                "button[role='menuitem']:has-text('Try again')",
                                "button[role='menuitem']:has-text('Thử lại')",
                                ".mat-mdc-menu-item:has-text('Try again')",
                                ".mat-mdc-menu-item:has-text('Thử lại')",
                                "[role='menu'] button:has-text('Try again')",
                                "[role='menu'] button:has-text('Thử lại')",
                                "[role='menu'] [role='menuitem']:has-text('Try again')",
                                "[role='menu'] [role='menuitem']:has-text('Thử lại')",
                                ".cdk-overlay-pane [role='menuitem']:has-text('Try again')",
                                ".cdk-overlay-pane [role='menuitem']:has-text('Thử lại')",
                                ".cdk-overlay-pane button:has-text('Try again')",
                                ".cdk-overlay-pane button:has-text('Thử lại')",
                                "[role='menuitem']:has-text('Retry')",
                                "[role='menuitem']:has-text('Regenerate')",
                                "[role='menuitem']:has-text('Tạo lại')",
                                "button:has-text('Try again')",
                                "button:has-text('Thử lại')"
                            ]
                            menu_clicked = False
                            for _ in range(6):
                                for m_sel in menu_selectors:
                                    try:
                                        m_loc = page.locator(m_sel).first
                                        if await m_loc.count() > 0 and await m_loc.is_visible():
                                            await human_delay(0.2, 0.5)
                                            await m_loc.click()
                                            menu_clicked = True
                                            break
                                    except Exception:
                                        pass
                                if menu_clicked:
                                    break
                                await asyncio.sleep(0.3)

                            return True
                        except Exception:
                            return False

                    return False

                async def run_vlm_interaction(prompt_text, is_intro=False, min_sentences=1, step_label=""):
                    """
                    Mở tab, điền prompt, đính kèm PDF, click Gửi, rồi CHỦ ĐỘNG lắng nghe response.
                    Mỗi lần response về xong đều validate; nếu lỗi sẽ tự động click Redo trên web
                    tối đa 3 lần. Nếu 3 lần Redo trên web đều thất bại, escalate lên Tool retry (tối đa 3 lần tool).
                    Tổng cộng: 3 tool attempts x 3 web redos = 9 lần thử.
                    """
                    vlm_hard_timeout = max(timeout * 3 + 90, 300)

                    async def _interact():
                        nonlocal local_br, local_br_ctx, local_nm
                        page = None
                        try:
                            # --- Lấy / tái sử dụng tab (duy nhất 1 tab) ---
                            try:
                                pages = local_br_ctx.pages
                                if pages and len(pages) > 0:
                                    page = pages[0]
                                    for extra_page in pages[1:]:
                                        try: await extra_page.close()
                                        except Exception: pass
                                else:
                                    page = await local_br_ctx.new_page()
                            except Exception:
                                page = await local_br_ctx.new_page()

                            # Luôn navigate đến /app để bắt đầu chat mới hoàn toàn (tránh resume session cũ)
                            try:
                                page_url = page.url or ""
                                if "gemini.google.com/app" in page_url and not page_url.endswith("/app") and "?" not in page_url:
                                    # Đang trong một conversation cụ thể → navigate ra /app
                                    await local_nm.safe_goto(page, vlm_url,
                                        reason=f"Gemini New Chat Ep {ep} (attempt {attempt})",
                                        caller="Stage5_GeminiAutomation",
                                        wait_until="domcontentloaded")
                                elif "gemini.google.com" not in page_url:
                                    # Không phải Gemini → navigate vào
                                    await local_nm.safe_goto(page, vlm_url,
                                        reason=f"Gemini Init Ep {ep} (attempt {attempt})",
                                        caller="Stage5_GeminiAutomation",
                                        wait_until="domcontentloaded")
                                else:
                                    # Đang ở /app nhưng có thể có session cũ → force reload
                                    try:
                                        await page.goto(vlm_url, wait_until="domcontentloaded", timeout=30000)
                                    except Exception:
                                        pass
                                await asyncio.sleep(1.5)
                            except Exception:
                                await local_nm.safe_goto(page, vlm_url,
                                    reason=f"Gemini Fallback Ep {ep} (attempt {attempt})",
                                    caller="Stage5_GeminiAutomation",
                                    wait_until="domcontentloaded")


                            # Dismiss popups
                            try:
                                await page.evaluate("""() => {
                                    const closeBtns = document.querySelectorAll(
                                        "button[aria-label*='Close' i], button[aria-label*='Đóng' i], button[aria-label*='Dismiss' i], " +
                                        "button[aria-label*='Bỏ qua' i], .dismiss-button, mat-dialog-actions button"
                                    );
                                    for (const b of closeBtns) { try { b.click(); } catch(e) {} }
                                }""")
                            except Exception:
                                pass

                            # Check limit model Flash + chọn profile yêu cầu (xoay vòng 1->2->3->1... nếu bị limit)
                            from app import check_gemini_login_and_limit_status, ensure_model_selected, reset_shared_browser_context, check_and_rotate_profiles_until_ready, load_config, save_config
                            limit_status = await check_gemini_login_and_limit_status(page, target_model=gemini_model, context_logger=context)
                            if limit_status == "limited":
                                await context.log(f"Tập {ep}: Tài khoản hiện tại bị giới hạn (Rate limit) model Flash. Đang xoay vòng sang profile tiếp theo...", "warning", stage_name=stage_name, episode=ep)
                                cfg = load_config()
                                profs = cfg.get("chrome_profiles", [])
                                if profs:
                                    cur_idx = cfg.get("current_profile_index", 0)
                                    cfg["current_profile_index"] = (cur_idx + 1) % len(profs)
                                    save_config(cfg)
                                await reset_shared_browser_context()
                                br, shared_ctx = await check_and_rotate_profiles_until_ready(context, force_check=True, target_model=gemini_model, headless=headless_val)
                                local_br = br
                                local_br_ctx = shared_ctx
                                local_nm.context = shared_ctx
                                local_nm.browser = br
                                pages = local_br_ctx.pages
                                page = pages[0] if pages else await local_br_ctx.new_page()
                                await local_nm.safe_goto(page, vlm_url, reason=f"Gemini Rotated Ep {ep}", caller="Stage5_GeminiAutomation", wait_until="domcontentloaded")
                                await check_gemini_login_and_limit_status(page, target_model=gemini_model, context_logger=context)

                            await ensure_model_selected(page, target_model=gemini_model, context_logger=context)

                            # =========================================================================
                            # DUAL-ENGINE GEMINI AUTOMATION (DIRECT IN-BROWSER RPC + PLAYWRIGHT INTERCEPTOR)
                            # =========================================================================
                            from gemini_web_engine import (
                                GeminiPlaywrightEngine,
                                GeminiWebException,
                                GeminiRateLimitException,
                                GeminiSafetyBlockException,
                                GeminiServerErrorException,
                                GeminiStreamHangException,
                                GeminiAuthExpiredException,
                                classify_gemini_exception
                            )

                            engine = GeminiPlaywrightEngine(context_logger=context)

                            # --- TẦNG 1: DIRECT IN-BROWSER RPC (Không cào DOM, ~3-8s) ---
                            try:
                                rpc_text, rpc_thoughts = await engine.execute_direct_rpc(
                                    page=page,
                                    prompt_text=prompt_text,
                                    pdf_path=pdf_path,
                                    model_name=gemini_model,
                                    episode=ep
                                )
                                if rpc_text:
                                    is_valid, err_msg = verify_gemini_response_format(rpc_text, is_intro=is_intro, min_sentences=min_sentences)
                                    if is_valid:
                                        parsed = parse_gemini_recap_text(rpc_text)
                                        if not parsed or not isinstance(parsed, list):
                                            parsed = extract_json_from_text(rpc_text)
                                        if parsed and isinstance(parsed, list) and len(parsed) >= min_sentences:
                                            await context.log(f"Tập {ep}: [Direct RPC Thành Công] Đã nhận và parse kịch bản chuẩn xác ({len(parsed)} phân đoạn).", "success", stage_name=stage_name, episode=ep)
                                            return parsed, rpc_text
                            except GeminiRateLimitException:
                                raise
                            except GeminiSafetyBlockException:
                                raise
                            except Exception as rpc_e:
                                await context.log(f"Tập {ep}: Direct RPC fallback: {rpc_e}. Chuyển sang Playwright Interceptor...", "info", stage_name=stage_name, episode=ep)

                            # --- TẦNG 2: PLAYWRIGHT NETWORK INTERCEPTOR & DOM AUTOMATION ---
                            max_web_retries = 3
                            for web_attempt in range(1, max_web_retries + 1):
                                if page.is_closed():
                                    pages = local_br_ctx.pages
                                    page = pages[0] if pages else await local_br_ctx.new_page()
                                    await local_nm.safe_goto(page, vlm_url, reason=f"Gemini Ep {ep}", caller="Stage5_GeminiAutomation", wait_until="domcontentloaded")

                                is_redo_attempt = False
                                if web_attempt > 1:
                                    await context.log(
                                        f"Tập {ep}: [{step_label}] [Tool {attempt}/3 - Web {web_attempt}/3] Đang click Redo / Thử lại trên giao diện web...",
                                        "warning",
                                        stage_name=stage_name,
                                        episode=ep
                                    )
                                    redo_ok = await click_gemini_redo_button(page)
                                    if redo_ok:
                                        is_redo_attempt = True
                                        await context.log(f"Tập {ep}: Đã click nút Redo -> 'Try again' thành công. Đang chờ Gemini tạo lại...", "info", stage_name=stage_name, episode=ep)
                                        await asyncio.sleep(2.0)

                                resp_text = ""
                                try:
                                    resp_text, thoughts = await engine.execute_playwright_interceptor(
                                        page=page,
                                        prompt_text=prompt_text,
                                        pdf_path=pdf_path if (web_attempt == 1 and not is_redo_attempt) else None,
                                        model_name=gemini_model,
                                        is_intro=is_intro,
                                        min_sentences=min_sentences,
                                        timeout=timeout,
                                        episode=ep,
                                        step_label=f"{'Redo ' if is_redo_attempt else ''}{step_label} (Web {web_attempt}/3)",
                                        is_redo=is_redo_attempt
                                    )
                                except GeminiWebException:
                                    raise
                                except Exception as p_err:
                                    await context.log(f"Tập {ep}: [Web {web_attempt}/3] Lỗi tương tác: {p_err}", "warning", stage_name=stage_name, episode=ep)
                                    if web_attempt >= max_web_retries:
                                        raise

                                # Validate format
                                validation_error = None
                                if not resp_text:
                                    validation_error = f"Gemini không trả về nội dung hoặc bị timeout ({timeout}s)."
                                else:
                                    is_valid, err_msg = verify_gemini_response_format(resp_text, is_intro=is_intro, min_sentences=min_sentences)
                                    if not is_valid:
                                        validation_error = f"Phản hồi chưa đạt chuẩn: {err_msg}"
                                        preview = resp_text.replace('\n', ' ')[:120]
                                        await context.log(f"Tập {ep}: [Web {web_attempt}/3] Chưa đạt: {err_msg} | Preview: '{preview}'", "warning", stage_name=stage_name, episode=ep)
                                    else:
                                        parsed = parse_gemini_recap_text(resp_text)
                                        if not parsed or not isinstance(parsed, list):
                                            parsed = extract_json_from_text(resp_text)
                                        if not parsed or not isinstance(parsed, list):
                                            validation_error = "Không thể parse kịch bản JSON từ phản hồi."
                                        elif len(parsed) < min_sentences:
                                            validation_error = f"Kết quả chỉ có {len(parsed)} dòng (< {min_sentences} yêu cầu)."
                                        else:
                                            # Thành công hoàn tất ở lượt web này!
                                            return parsed, resp_text

                                if web_attempt >= max_web_retries:
                                    raise Exception(f"Sau {max_web_retries} lần thử trên web, phản hồi [{step_label}] vẫn lỗi: {validation_error}")

                        except Exception:
                            raise

                    # --- Bọc _interact bằng hard timeout ---
                    return await asyncio.wait_for(_interact(), timeout=vlm_hard_timeout)

                is_ep1 = (ep == 1 or str(ep).strip() in ("1", "01", "ep_1", "ep1"))

                if is_ep1:
                    # Phần 1: Khung chat 1 - Tạo Intro Hook (với 3 lần Web Redo)
                    await context.log(f"Tập 1: [Phần 1/2] [Tool Attempt {attempt}/3] Đang tạo Intro Hook bằng khung chat Gemini riêng biệt...", "info", stage_name=stage_name, episode=ep)
                    intro_prompt = generate_intro_prompt(comic_title, len(image_files), language)
                    parsed_intro, raw_intro_text = await run_vlm_interaction(intro_prompt, is_intro=True, min_sentences=1, step_label="Intro Hook")
                    await context.log(f"Tập 1: [Phần 1/2] Đã tạo Intro Hook thành công: '{parsed_intro[0].get('speech', '')[:60]}...'", "success", stage_name=stage_name, episode=ep)

                    # Phần 2: Khung chat 2 - Tạo Story Recap (với 3 lần Web Redo)
                    await context.log(f"Tập 1: [Phần 2/2] [Tool Attempt {attempt}/3] Đang mở khung chat Gemini thứ hai để tạo Story Recap...", "info", stage_name=stage_name, episode=ep)
                    story_prompt = generate_gemini_prompt(comic_title, ep, len(image_files), language)
                    parsed_story, raw_story_text = await run_vlm_interaction(story_prompt, is_intro=False, min_sentences=12, step_label="Story Recap")
                    await context.log(f"Tập 1: [Phần 2/2] Đã tạo Story Recap thành công ({len(parsed_story)} phân đoạn).", "success", stage_name=stage_name, episode=ep)

                    # Ghép kết quả 2 phần
                    parsed_data = parsed_intro + parsed_story
                    response_text = raw_intro_text.strip() + "\n" + raw_story_text.strip()
                    await context.log(f"Tập 1: Đã ghép Intro Hook ({len(parsed_intro)} dòng) + Story Recap ({len(parsed_story)} dòng) -> Tổng {len(parsed_data)} phân đoạn.", "success", stage_name=stage_name, episode=ep)

                else:
                    # Các tập bình thường (>= 2): Chạy 1 khung chat Story Recap (với 3 lần Web Redo)
                    await context.log(f"Tập {ep}: [Tool Attempt {attempt}/3] Đang tạo kịch bản recap từ Gemini...", "info", stage_name=stage_name, episode=ep)
                    story_prompt = generate_gemini_prompt(comic_title, ep, len(image_files), language)
                    parsed_data, response_text = await run_vlm_interaction(story_prompt, is_intro=False, min_sentences=12, step_label="Story Recap")

                with open(raw_response_path, "w", encoding="utf-8") as rf:
                    rf.write(response_text)
                with open(recap_json_path, "w", encoding="utf-8") as jf:
                    json.dump(parsed_data, jf, ensure_ascii=False, indent=2)

                await context.log(f"Tập {ep}: Tạo kịch bản recap.json thành công ({len(parsed_data)} phân đoạn, đạt chuẩn >= 12 dòng).", "success", stage_name=stage_name, episode=ep)
                success = True
                break

            except Exception as e:
                await context.log(f"Tập {ep}: Lỗi Gemini Automation (thử tool {attempt}/{max_retries}): {e}", "warning", stage_name=stage_name, episode=ep)
                err_str = str(e).lower()
                is_rate_limit = (
                    any(k in err_str for k in ["rate limit", "quota", "429", "tạm thời hết lượt", "bị giới hạn", "hạn mức", "1037"])
                    and not any(k in err_str for k in ["chưa đạt chuẩn", "parse", "format", "định dạng", "dòng", "câu", "thinking", "response contains only"])
                )
                if is_rate_limit:
                    await context.log(f"Tập {ep}: Phát hiện Rate Limit. Đang xoay vòng sang profile tiếp theo...", "warning", stage_name=stage_name, episode=ep)
                    from app import load_config, save_config, reset_shared_browser_context
                    cfg = load_config()
                    profs = cfg.get("chrome_profiles", [])
                    if profs:
                        cur_idx = cfg.get("current_profile_index", 0)
                        cfg["current_profile_index"] = (cur_idx + 1) % len(profs)
                        save_config(cfg)
                    await reset_shared_browser_context()
                if attempt < max_retries:
                    await asyncio.sleep(1.0)
            finally:
                if local_br_ctx:
                    try:
                        for p in local_br_ctx.pages[1:]:
                            try: await p.close()
                            except Exception: pass
                    except Exception:
                        pass
                if should_close_ctx and local_br_ctx:
                    try: await local_br_ctx.close()
                    except Exception: pass

        if not success:
            await context.log(f"Tập {ep}: Không thể lấy kịch bản hợp lệ từ Gemini sau {max_retries} lần thử tool (tổng 9 lần retry).", "error", stage_name=stage_name, episode=ep)
            task.episode_progress[ep_key][stage_name] = StageState.FAILED
            return False

        # Đóng các tab phụ sau khi hoàn tất, đảm bảo chỉ có tối đa 1 tab
        if local_br_ctx:
            try:
                for p in local_br_ctx.pages[1:]:
                    try: await p.close()
                    except Exception: pass
            except Exception:
                pass

        task.episode_progress[ep_key][stage_name] = StageState.SUCCESS
        total_eps = task.to_episode - task.from_episode + 1
        completed = sum(1 for e in range(task.from_episode, task.to_episode + 1) if task.episode_progress.get(str(e), {}).get(stage_name) == StageState.SUCCESS)
        await context.update_stage_progress(stage_name, (completed / total_eps) * 100.0)
        return True

    if profile_pool is not None:
        return await _run()
    elif vlm_sem:
        async with vlm_sem:
            return await _run()
    else:
        return await _run()

class Stage5_GeminiAutomation(BaseStage):
    @property
    def name(self) -> str: return "Stage 5 - Gemini Automation"
    @property
    def weight(self) -> float: return 0.15

    async def execute(self, context: WorkflowContext) -> bool:
        task = context.task
        from_ep = task.from_episode
        to_ep = task.to_episode
        download_dir = task.artifacts.get("download_dir")
        
        from app import check_and_rotate_profiles_until_ready, load_config
        gemini_model = task.payload.get("gemini_model", "flash") or "flash"
        headless_val = task.payload.get("headless") if task.payload.get("headless") is not None else load_config().get("headless", False)
        
        try:
            await check_and_rotate_profiles_until_ready(context, force_check=False, target_model=gemini_model, headless=headless_val)
        except Exception as init_err:
            await context.log(f"Không thể chuẩn bị tài khoản Gemini hợp lệ: {init_err}", "error")
            return False

        # Chỉ dùng 1 browser window + 1 profile, chạy tuần tự từng tập (tối đa 1 luồng playwright)
        vlm_sem = asyncio.Semaphore(1)
        for ep in range(from_ep, to_ep + 1):
            if context.cancel_token.is_cancelled(): raise asyncio.CancelledError()
            ok = await execute_single_episode_stage5(ep, context, vlm_sem)
            if not ok:
                return False
            await asyncio.sleep(1.0)
            
        return True

class Stage6_JSONExtraction(BaseStage):
    @property
    def name(self) -> str: return "Stage 6 - JSON Extraction"
    @property
    def weight(self) -> float: return 0.05

    async def execute(self, context: WorkflowContext) -> bool:
        from workflow_stages_2 import execute_single_episode_stage6
        task = context.task
        from_ep = task.from_episode
        to_ep = task.to_episode

        for ep in range(from_ep, to_ep + 1):
            if context.cancel_token.is_cancelled(): raise asyncio.CancelledError()
            await context.start_episode(ep)
            ok = await execute_single_episode_stage6(ep, context)
            if not ok:
                await context.fail_episode(ep, f"JSON tại tập {ep} không tồn tại hoặc không hợp lệ.")
                return False
            await context.complete_episode(ep)
        return True

async def execute_single_episode_stage2b(
    ep: int,
    context: WorkflowContext,
    repage_sem: Optional[asyncio.Semaphore] = None
) -> bool:
    """Stage 2b - Intelligent Re-pagination for a single episode."""
    import os
    import json
    import shutil
    import asyncio
    import cv2
    import numpy as np
    from collections import Counter
    import torch
    from tools.text_remover.comic_text_remover import get_easyocr_reader, ocr_lock

    stage_name = "Stage 2b - Intelligent Re-pagination"
    task = context.task
    download_dir = task.artifacts.get("download_dir")
    ep_key = str(ep)
    if ep_key not in task.episode_progress:
        task.episode_progress[ep_key] = {}

    has_repag_meta = is_episode_repage_ready(ep, download_dir)
    if check_episode_completed(download_dir, ep) or has_repag_meta:
        task.episode_progress[ep_key][stage_name] = StageState.SUCCESS
        total_eps = task.to_episode - task.from_episode + 1
        completed = sum(1 for e in range(task.from_episode, task.to_episode + 1) if task.episode_progress.get(str(e), {}).get(stage_name) == StageState.SUCCESS)
        await context.update_stage_progress(stage_name, (completed / total_eps) * 100.0)
        return True

    task.episode_progress[ep_key][stage_name] = StageState.RUNNING
    await context.manager.save_and_broadcast("EpisodeProgressUpdated", task)

    # Configurations
    min_height = task.payload.get("repage_min_height", 1000)
    max_height = task.payload.get("repage_max_height", 2500)
    canny_low = task.payload.get("repage_canny_low", 50)
    canny_high = task.payload.get("repage_canny_high", 150)
    tolerance = task.payload.get("repage_tolerance", 15)
    bg_threshold = task.payload.get("repage_bg_threshold", 0.98)
    min_panel_h = task.payload.get("repage_min_panel_h", 8)
    forbidden_padding = task.payload.get("repage_forbidden_padding", 10)
    skip_blank = task.payload.get("repage_skip_blank", True)
    use_ocr = task.payload.get("repage_use_ocr", False)

    if use_ocr:
        try:
            get_easyocr_reader(['en'])
        except Exception:
            pass

    def detect_background(img_gray):
        h, w = img_gray.shape
        if h == 0 or w == 0:
            return 255
        border_pixels = np.concatenate([
            img_gray[0, :],
            img_gray[-1, :],
            img_gray[:, 0],
            img_gray[:, -1]
        ])
        return int(np.median(border_pixels))

    def get_clean_rows(img_gray, bg_val, tol=15, bg_threshold=0.98):
        h, w = img_gray.shape
        col_margin = int(w * 0.05)
        col_start = col_margin
        col_end = w - col_margin
        img_mid = img_gray[:, col_start:col_end]
        diff = np.abs(img_mid.astype(np.int32) - bg_val)
        bg_ratio = np.mean(diff <= tol, axis=1)
        return bg_ratio >= bg_threshold

    def group_clean_bands(clean_rows):
        height = len(clean_rows)
        bands = []
        in_band = False
        start_y = 0
        for y in range(height):
            if clean_rows[y]:
                if not in_band:
                    start_y = y
                    in_band = True
            else:
                if in_band:
                    end_y = y - 1
                    center_y = (start_y + end_y) // 2
                    bands.append((start_y, end_y, center_y))
                    in_band = False
        if in_band:
            bands.append((start_y, height - 1, (start_y + height - 1) // 2))
        return bands

    def merge_ranges(ranges):
        if not ranges:
            return []
        sorted_ranges = sorted(ranges, key=lambda x: x[0])
        merged = [sorted_ranges[0]]
        for current in sorted_ranges[1:]:
            prev_start, prev_end = merged[-1]
            curr_start, curr_end = current
            if curr_start <= prev_end:
                merged[-1] = (prev_start, max(prev_end, curr_end))
            else:
                merged.append(current)
        return merged

    def get_protected_ranges(img_bgr, bg_val, tol):
        if img_bgr is None or img_bgr.shape[0] <= 0 or img_bgr.shape[1] <= 0:
            return []
        h_img, w_img = img_bgr.shape[:2]
        protected = []
        target_w = 400
        scale = target_w / w_img if w_img > target_w else 1.0
        if w_img > target_w:
            target_h = max(1, int(h_img * scale))
            resized_img = cv2.resize(img_bgr, (target_w, target_h))
        else:
            resized_img = img_bgr
            
        if use_ocr:
            try:
                reader = get_easyocr_reader(['en'])
                with ocr_lock:
                    horiz, free = reader.detect(resized_img, canvas_size=640)
                if horiz and len(horiz) > 0:
                    for box in horiz[0]:
                        ymin = max(0, int(box[2] / scale))
                        ymax = min(h_img, int(box[3] / scale))
                        protected.append((ymin, ymax))
                if free and len(free) > 0:
                    for quad in free[0]:
                        if len(quad) > 0:
                            ys = [pt[1] for pt in quad]
                            ymin = max(0, int(min(ys) / scale))
                            ymax = min(h_img, int(max(ys) / scale))
                            protected.append((ymin, ymax))
            except Exception:
                pass
            
        try:
            gray_img = cv2.cvtColor(resized_img, cv2.COLOR_BGR2GRAY)
            if bg_val > 127:
                _, thresh = cv2.threshold(gray_img, bg_val - tol, 255, cv2.THRESH_BINARY_INV)
            else:
                _, thresh = cv2.threshold(gray_img, bg_val + tol, 255, cv2.THRESH_BINARY)
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (20, 20))
            closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
            contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for c in contours:
                cx, cy, cw, ch = cv2.boundingRect(c)
                if cw > int(80 * scale) and ch > int(80 * scale):
                    ymin = max(0, int(cy / scale))
                    ymax = min(h_img, int((cy + ch) / scale))
                    protected.append((ymin, ymax))
        except Exception:
            pass
        return merge_ranges(protected)

    async def _run_repage():
        if context.cancel_token.is_cancelled(): raise asyncio.CancelledError()
        ep_dir = os.path.join(download_dir, f"episode_{ep}")
        images_dir = os.path.join(ep_dir, "images")
        debug_dir = os.path.join(ep_dir, "debug_repaging")
        source_raw_dir = os.path.join(ep_dir, "images_source_raw")
        
        if os.path.exists(source_raw_dir) and any(f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) for f in os.listdir(source_raw_dir)):
            src_input_dir = source_raw_dir
        else:
            src_input_dir = images_dir
            if os.path.exists(images_dir):
                os.makedirs(source_raw_dir, exist_ok=True)
                for f in os.listdir(images_dir):
                    if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                        shutil.copy2(os.path.join(images_dir, f), os.path.join(source_raw_dir, f))
        
        files = []
        if os.path.exists(src_input_dir):
            files = sorted([
                f for f in os.listdir(src_input_dir)
                if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))
                and os.path.exists(os.path.join(src_input_dir, f))
                and os.path.getsize(os.path.join(src_input_dir, f)) > 0
            ])

        pdf_path = None
        if not files:
            pdf_dir = os.path.join(ep_dir, "pdf")
            for cand_dir in [pdf_dir, ep_dir, src_input_dir]:
                if os.path.exists(cand_dir):
                    cand_pdfs = [os.path.join(cand_dir, f) for f in os.listdir(cand_dir) if f.lower().endswith(".pdf")]
                    if cand_pdfs:
                        pdf_path = cand_pdfs[0]
                        break

        if not files and not pdf_path:
            await context.fail_episode(ep, "Không tìm thấy ảnh hoặc file PDF truyện tranh nào hợp lệ.")
            return False

        os.makedirs(images_dir, exist_ok=True)
        image_paths = [os.path.join(src_input_dir, f) for f in files] if files else []
        loop = asyncio.get_running_loop()

        def process_single_slice(path):
            if not os.path.exists(path) or os.path.getsize(path) == 0:
                return None
            img = safe_cv2_imread(path)
            if img is None or img.size == 0:
                return None
            h, w = img.shape[:2]
            if h <= 0 or w <= 0:
                return None
            gray_img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            slice_bg = detect_background(gray_img)
            page_protected = get_protected_ranges(img, slice_bg, tolerance)
            return {
                "filename": os.path.basename(path),
                "img": img,
                "height": h,
                "width": w,
                "slice_bg": slice_bg,
                "protected": page_protected
            }

        def run_detection_and_stitch():
            if pdf_path:
                try:
                    import fitz
                except ImportError:
                    import pymupdf as fitz
                doc = fitz.open(pdf_path)
                slice_results = []
                target_w = 1459
                try:
                    for p_idx in range(len(doc)):
                        p = doc[p_idx]
                        rect = p.rect
                        scale = float(target_w) / float(rect.width) if rect.width > 0 else 2.0
                        mat = fitz.Matrix(scale, scale)
                        pix = p.get_pixmap(matrix=mat, alpha=False)
                        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, 3))
                        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
                        h, w = img.shape[:2]
                        gray_img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                        slice_bg = detect_background(gray_img)
                        page_protected = get_protected_ranges(img, slice_bg, tolerance)
                        slice_results.append({
                            "filename": f"page_{p_idx+1:03d}.webp",
                            "img": img,
                            "height": h,
                            "width": w,
                            "slice_bg": slice_bg,
                            "protected": page_protected,
                            "pdf_page": p_idx + 1
                        })
                finally:
                    doc.close()
            else:
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=min(16, os.cpu_count() or 8)) as pool:
                    raw_slices = list(pool.map(process_single_slice, image_paths))
                slice_results = [s for s in raw_slices if s is not None]

            if not slice_results:
                return None

            bg_vals = [s["slice_bg"] for s in slice_results]
            final_bg_val = Counter(bg_vals).most_common(1)[0][0]
            loaded_images = [s["img"] for s in slice_results]
            slice_widths = [s["width"] for s in slice_results]
            mode_w = Counter(slice_widths).most_common(1)[0][0]
            
            normalized_images = []
            for img in loaded_images:
                h, w = img.shape[:2]
                if w != mode_w:
                    new_h = max(1, int(round(h * (mode_w / float(w)))))
                    resized = cv2.resize(img, (mode_w, new_h), interpolation=cv2.INTER_AREA)
                    normalized_images.append(resized)
                else:
                    normalized_images.append(img)
                    
            total_height = sum(img.shape[0] for img in normalized_images)
            canvas = np.ones((total_height, mode_w, 3), dtype=np.uint8) * final_bg_val
            
            current_y = 0
            offsets = []
            for idx, img in enumerate(normalized_images):
                h, w = img.shape[:2]
                canvas[current_y:current_y+h, 0:mode_w] = img
                off_item = {
                    "filename": slice_results[idx]["filename"],
                    "offset_y_start": current_y,
                    "offset_y_end": current_y + h,
                    "height": h
                }
                if "pdf_page" in slice_results[idx]:
                    off_item["pdf_page"] = slice_results[idx]["pdf_page"]
                offsets.append(off_item)
                current_y += h
                
            return canvas, total_height, mode_w, offsets, [], final_bg_val

        res = await loop.run_in_executor(None, run_detection_and_stitch)
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        elif hasattr(torch, 'mps') and torch.backends.mps.is_available():
            torch.mps.empty_cache()
        if res is None:
            await context.fail_episode(ep, "Lỗi nạp hoặc ghép nối ảnh.")
            return False
            
        canvas, total_height, max_w, offsets, global_protected, final_bg_val = res
        if canvas is None or total_height <= 0 or max_w <= 0:
            await context.fail_episode(ep, "Lỗi nạp hoặc ghép nối ảnh: canvas trống hoặc kích thước không hợp lệ.")
            return False

        os.makedirs(debug_dir, exist_ok=True)
        
        def export_pages_and_visualizations():
            from pure_visual.pipeline import PureVisualPipeline
            from pure_visual.config import DetectionConfig
            
            pv_device = "cuda" if (torch.cuda.is_available() and task.payload.get("use_gpu", True)) else "cpu"
            pv_config = DetectionConfig(
                device=pv_device,
                min_clean_height=task.payload.get("min_clean_height", 380),
                min_laplacian_var=task.payload.get("min_laplacian_var", 250.0),
                export_annotated_pdf=True,
                export_webp_frames=True
            )
            pipeline = PureVisualPipeline(pv_config)
            
            clean_title = "".join(c for c in task.comic_title if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
            chapter_pdf_path = os.path.join(ep_dir, "pdf", f"{clean_title}_Tap_{ep}.pdf")
            meta_json_path = os.path.join(debug_dir, "pure_visual_regions_metadata.json")
            repaging_json_path = os.path.join(debug_dir, "repaging_metadata.json")
            
            old_pdf_path = os.path.join(ep_dir, "pdf", "visual_regions_annotated.pdf")
            if os.path.exists(old_pdf_path):
                try:
                    os.remove(old_pdf_path)
                except Exception:
                    pass

            pipe_result = pipeline.process_canvas(
                canvas=canvas,
                output_images_dir=images_dir,
                output_pdf_path=chapter_pdf_path,
                output_metadata_path=meta_json_path,
                source_offsets=offsets,
                bg_val=final_bg_val
            )
                    
            output_pages_meta = []
            for p_idx, reg in enumerate(pipe_result.regions, start=1):
                reg_dict = reg.to_dict()
                reg_dict["pageIndex"] = p_idx
                reg_dict["page_index"] = p_idx
                reg_dict["page_id"] = f"page_{p_idx:03d}"
                reg_dict["filename"] = f"{p_idx:03d}.webp"
                reg_dict["yStart"] = reg.details.get("yStart", reg.original_bbox.y1)
                reg_dict["yEnd"] = reg.details.get("yEnd", reg.original_bbox.y2)
                output_pages_meta.append(reg_dict)
                
            repaging_metadata = {
                "source_images": offsets,
                "output_pages": output_pages_meta,
                "all_detected_pages": output_pages_meta,
                "video_filter_applied": True,
                "total_detected": pipe_result.statistics.get("total_candidates", len(pipe_result.regions)),
                "total_exported": len(pipe_result.regions),
                "dropped_non_visual_count": pipe_result.statistics.get("total_junk_dropped", 0),
                "pdf_annotated_path": chapter_pdf_path,
                "pdf_exported": pipe_result.statistics.get("pdf_exported", True)
            }
            with open(repaging_json_path, "w", encoding="utf-8") as rf:
                json.dump(repaging_metadata, rf, ensure_ascii=False, indent=2)

            return len(pipe_result.regions)

        num_pages = await loop.run_in_executor(None, export_pages_and_visualizations)
        await context.log(f"Tập {ep}: Phân trang thông minh V2 hoàn tất. Tạo thành công {num_pages} trang tối ưu video 1080px.", "success")
        return True

    if repage_sem is not None:
        async with repage_sem:
            ok = await _run_repage()
    else:
        ok = await _run_repage()

    if ok:
        task.episode_progress[ep_key][stage_name] = StageState.SUCCESS
    else:
        task.episode_progress[ep_key][stage_name] = StageState.FAILED

    total_eps = task.to_episode - task.from_episode + 1
    completed = sum(1 for e in range(task.from_episode, task.to_episode + 1) if task.episode_progress.get(str(e), {}).get(stage_name) == StageState.SUCCESS)
    await context.update_stage_progress(stage_name, (completed / total_eps) * 100.0)
    await context.manager.save_and_broadcast("EpisodeProgressUpdated", task)
    return ok


class Stage2b_IntelligentRepagination(BaseStage):
    @property
    def name(self) -> str: return "Stage 2b - Intelligent Re-pagination"
    @property
    def weight(self) -> float: return 0.05

    async def execute(self, context: WorkflowContext) -> bool:
        task = context.task
        from_ep = task.from_episode
        to_ep = task.to_episode
        repage_concurrency = min(4, max(1, task.payload.get("concurrency", os.cpu_count() or 4)))
        repage_sem = asyncio.Semaphore(repage_concurrency)
        episodes = list(range(from_ep, to_ep + 1))
        results = await asyncio.gather(*[execute_single_episode_stage2b(ep, context, repage_sem) for ep in episodes])
        return all(results)


async def execute_episode_full_pipeline(
    ep: int,
    context: WorkflowContext,
    crawl_lock: asyncio.Lock,
    browser_context,
    nav_manager,
    dl_sem: asyncio.Semaphore,
    repage_sem: asyncio.Semaphore,
    nsfw_sem: asyncio.Semaphore,
    pdf_sem: asyncio.Semaphore,
    vlm_sem: Optional[asyncio.Semaphore],
    tts_sem: asyncio.Semaphore,
    render_sem: asyncio.Semaphore,
    prev_s2_done_event: Optional[asyncio.Event] = None,
    s2_done_event: Optional[asyncio.Event] = None,
    profile_pool: Optional[Any] = None,
) -> bool:
    """
    Executes the full pipeline for a single episode (Stages 2 -> 10) with streaming concurrency:
    - Waits for prev_s2_done_event (ensuring Episode N only starts crawling after Episode N-1 completes Stage 2).
    - Stage 2 crawls images serially with crawl_lock (ensuring safety & anti-ban delays).
    - As soon as Episode N finishes Stage 2, it signals s2_done_event so Episode N+1 can start crawling,
      while Episode N immediately enters Stage 2b -> 3 -> 4 -> 5 -> 6 -> 7 -> 8 -> 9 -> 10 in parallel!
    """
    if prev_s2_done_event is not None:
        try:
            await prev_s2_done_event.wait()
        except asyncio.CancelledError:
            if s2_done_event is not None:
                s2_done_event.set()
            raise

    if context.cancel_token.is_cancelled():
        if s2_done_event is not None:
            s2_done_event.set()
        raise asyncio.CancelledError()

    try:
        await context.start_episode(ep, "Stage 2 - Async Image Crawling")

        # 1. Stage 2: Crawl images serially
        try:
            async with crawl_lock:
                if context.cancel_token.is_cancelled():
                    raise asyncio.CancelledError()
                await context.update_episode_stage(ep, "Stage 2 - Async Image Crawling", StageState.RUNNING)
                s2_ok = await execute_single_episode_stage2(ep, context, browser_context, nav_manager, dl_sem)
                if not s2_ok:
                    await context.fail_episode(ep, f"Tập {ep}: Crawl ảnh thất bại ở Stage 2.", stage_name="Stage 2 - Async Image Crawling")
                    return False
                # Human delay before releasing lock for next episode crawl
                await asyncio.sleep(round(random.uniform(1.2, 2.5), 2))
        finally:
            # Immediately signal the next episode that Stage 2 for this episode has finished!
            if s2_done_event is not None:
                s2_done_event.set()

        # 2. Stage 2b: Intelligent Re-pagination (starts immediately)
        if context.cancel_token.is_cancelled():
            raise asyncio.CancelledError()
        await context.update_episode_stage(ep, "Stage 2b - Intelligent Re-pagination", StageState.RUNNING)
        s2b_ok = await execute_single_episode_stage2b(ep, context, repage_sem)
        if not s2b_ok:
            await context.fail_episode(ep, f"Tập {ep}: Phân trang thất bại ở Stage 2b.", stage_name="Stage 2b - Intelligent Re-pagination")
            return False

        # 3. Stage 3: NSFW Moderation
        if context.cancel_token.is_cancelled():
            raise asyncio.CancelledError()
        await context.update_episode_stage(ep, "Stage 3 - NSFW Moderation", StageState.RUNNING)
        s3_ok = await execute_single_episode_stage3(ep, context, nsfw_sem)
        if not s3_ok:
            await context.fail_episode(ep, f"Tập {ep}: NSFW Moderation thất bại ở Stage 3.", stage_name="Stage 3 - NSFW Moderation")
            return False

        # 4. Stage 4: PDF Generation
        if context.cancel_token.is_cancelled():
            raise asyncio.CancelledError()
        await context.update_episode_stage(ep, "Stage 4 - PDF Generation", StageState.RUNNING)
        s4_ok = await execute_single_episode_stage4(ep, context, pdf_sem)
        if not s4_ok:
            await context.fail_episode(ep, f"Tập {ep}: Tạo PDF thất bại ở Stage 4.", stage_name="Stage 4 - PDF Generation")
            return False

        # 5. Stage 5: Gemini VLM Recap Generation
        if context.cancel_token.is_cancelled():
            raise asyncio.CancelledError()
        await context.update_episode_stage(ep, "Stage 5 - Gemini Automation", StageState.RUNNING)
        s5_ok = await execute_single_episode_stage5(ep, context, vlm_sem=vlm_sem, profile_pool=profile_pool)
        if not s5_ok:
            await context.fail_episode(ep, f"Tập {ep}: Tạo kịch bản VLM thất bại ở Stage 5.", stage_name="Stage 5 - Gemini Automation")
            return False

        from workflow_stages_2 import (
            execute_single_episode_stage6,
            execute_single_episode_stage7,
            execute_single_episode_stage8,
            execute_single_episode_stage9,
            execute_single_episode_stage10,
        )

        # 6. Stage 6: Script Post-processing
        if context.cancel_token.is_cancelled():
            raise asyncio.CancelledError()
        await context.update_episode_stage(ep, "Stage 6 - JSON Extraction", StageState.RUNNING)
        s6_ok = await execute_single_episode_stage6(ep, context)
        if not s6_ok:
            await context.fail_episode(ep, f"Tập {ep}: Xử lý kịch bản thất bại ở Stage 6.", stage_name="Stage 6 - JSON Extraction")
            return False

        # 7. Stage 7: Audio Script & SSML Aggregation
        if context.cancel_token.is_cancelled():
            raise asyncio.CancelledError()
        await context.update_episode_stage(ep, "Stage 7 - Narration Aggregation", StageState.RUNNING)
        s7_ok = await execute_single_episode_stage7(ep, context)
        if not s7_ok:
            await context.fail_episode(ep, f"Tập {ep}: Tổng hợp lời thoại thất bại ở Stage 7.", stage_name="Stage 7 - Narration Aggregation")
            return False

        # 8. Stage 8: Local TTS Audio Generation
        if context.cancel_token.is_cancelled():
            raise asyncio.CancelledError()
        await context.update_episode_stage(ep, "Stage 8 - Local TTS", StageState.RUNNING)
        s8_ok = await execute_single_episode_stage8(ep, context, tts_sem)
        if not s8_ok:
            await context.fail_episode(ep, f"Tập {ep}: Tạo âm thanh TTS thất bại ở Stage 8.", stage_name="Stage 8 - Local TTS")
            return False

        # 9. Stage 9: Dynamic Visual Timeline Builder & Subtitles
        if context.cancel_token.is_cancelled():
            raise asyncio.CancelledError()
        await context.update_episode_stage(ep, "Stage 9 - Subtitle Normalization", StageState.RUNNING)
        s9_ok = await execute_single_episode_stage9(ep, context)
        if not s9_ok:
            await context.fail_episode(ep, f"Tập {ep}: Tạo timeline phụ đề thất bại ở Stage 9.", stage_name="Stage 9 - Subtitle Normalization")
            return False

        # 10. Stage 10: Video Rendering
        if context.cancel_token.is_cancelled():
            raise asyncio.CancelledError()
        await context.update_episode_stage(ep, "Stage 10 - Episode Video Rendering", StageState.RUNNING)
        s10_ok = await execute_single_episode_stage10(ep, context, render_sem)
        if not s10_ok:
            await context.fail_episode(ep, f"Tập {ep}: Render video tập thất bại ở Stage 10.", stage_name="Stage 10 - Episode Video Rendering")
            return False

        await context.complete_episode(ep)
        await context.log(f"Tập {ep}: Đã hoàn tất toàn bộ quy trình từ tải ảnh đến render video!", "success")
        return True
    except asyncio.CancelledError:
        if s2_done_event is not None:
            s2_done_event.set()
        raise
    except Exception as exc:
        if s2_done_event is not None:
            s2_done_event.set()
        await context.fail_episode(ep, f"Tập {ep}: Lỗi xử lý: {exc}")
        return False


def is_episode_images_ready(ep: int, download_dir: Optional[str]) -> bool:
    """Kiểm tra tập ep đã tải xong các ảnh truyện gốc hợp lệ (> 0 ảnh) hay chưa."""
    if not download_dir:
        return False
    ep_images_dir = os.path.join(download_dir, f"episode_{ep}", "images")
    if not os.path.exists(ep_images_dir):
        return False
    return any(
        f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and os.path.getsize(os.path.join(ep_images_dir, f)) > 0
        for f in os.listdir(ep_images_dir)
    )


def is_episode_repage_ready(ep: int, download_dir: Optional[str]) -> bool:
    """Kiểm tra tập ep đã có kết quả phân trang Stage 2b hợp lệ hay chưa."""
    if not download_dir:
        return False
    ep_dir = os.path.join(download_dir, f"episode_{ep}")
    meta_p1 = os.path.join(ep_dir, "debug_repaging", "repaging_metadata.json")
    meta_p2 = os.path.join(ep_dir, "repaging_metadata.json")
    return (
        (os.path.exists(meta_p1) and os.path.getsize(meta_p1) > 0)
        or (os.path.exists(meta_p2) and os.path.getsize(meta_p2) > 0)
    )


def is_episode_nsfw_ready(ep: int, download_dir: Optional[str]) -> bool:
    """Kiểm tra tập ep đã hoàn tất xử lý Stage 3 NSFW / images_pdf hay chưa."""
    if not download_dir:
        return False
    ep_images_pdf_dir = os.path.join(download_dir, f"episode_{ep}", "images_pdf")
    if not os.path.exists(ep_images_pdf_dir):
        return False
    return any(
        f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and os.path.getsize(os.path.join(ep_images_pdf_dir, f)) > 0
        for f in os.listdir(ep_images_pdf_dir)
    )


def is_episode_pdf_ready(ep: int, download_dir: Optional[str], comic_title: str) -> bool:
    """Kiểm tra tập ep đã có file PDF hợp lệ (> 0 bytes) hay chưa."""
    if not download_dir:
        return False
    ep_dir = os.path.join(download_dir, f"episode_{ep}")
    if not os.path.exists(ep_dir):
        return False
    clean_title = "".join(c for c in comic_title if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
    pdf_path = os.path.join(ep_dir, "pdf", f"{clean_title}_Tap_{ep}.pdf")
    if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
        return True
    pdf_dir = os.path.join(ep_dir, "pdf")
    if os.path.exists(pdf_dir):
        pdf_files = [f for f in os.listdir(pdf_dir) if f.lower().endswith(".pdf") and os.path.getsize(os.path.join(pdf_dir, f)) > 0]
        if pdf_files:
            return True
    return False


def is_episode_script_ready(ep: int, download_dir: Optional[str]) -> bool:
    """Kiểm tra tập ep đã có kịch bản recap.json hợp lệ từ Stage 5 hay chưa."""
    if not download_dir:
        return False
    recap_path = os.path.join(download_dir, f"episode_{ep}", "recap.json")
    return os.path.exists(recap_path) and validate_recap_json(recap_path)


def is_episode_narration_ready(ep: int, download_dir: Optional[str]) -> bool:
    """Kiểm tra tập ep đã có narration.txt từ Stage 7 hay chưa."""
    if not download_dir:
        return False
    p = os.path.join(download_dir, f"episode_{ep}", "narration.txt")
    return os.path.exists(p) and os.path.getsize(p) > 0


def is_episode_audio_ready(ep: int, download_dir: Optional[str]) -> bool:
    """Kiểm tra tập ep đã có audio.mp3 và transcript.srt từ Stage 8 hay chưa."""
    if not download_dir:
        return False
    ep_dir = os.path.join(download_dir, f"episode_{ep}")
    a_path = os.path.join(ep_dir, "audio.mp3")
    srt_path = os.path.join(ep_dir, "transcript.srt")
    return os.path.exists(a_path) and os.path.getsize(a_path) > 1024 and os.path.exists(srt_path) and os.path.getsize(srt_path) > 0


def is_episode_subtitles_ready(ep: int, download_dir: Optional[str]) -> bool:
    """Kiểm tra tập ep đã hoàn tất chuẩn hóa phụ đề Stage 9 hay chưa."""
    if not download_dir:
        return False
    ep_dir = os.path.join(download_dir, f"episode_{ep}")
    srt_path = os.path.join(ep_dir, "transcript.srt")
    return os.path.exists(srt_path) and os.path.getsize(srt_path) > 0


def is_episode_video_ready(ep: int, download_dir: Optional[str]) -> bool:
    """Kiểm tra tập ep đã có file video.mp4 hoàn chỉnh (> 1024 bytes) hay chưa."""
    if not download_dir:
        return False
    ep_dir = os.path.join(download_dir, f"episode_{ep}")
    if not os.path.exists(ep_dir):
        return False
    video_path = os.path.join(ep_dir, "video.mp4")
    if os.path.exists(video_path) and os.path.getsize(video_path) > 1024:
        return True
    return False


async def execute_multi_episode_pipelined_workflow(
    context: WorkflowContext,
    browser_context=None,
    profile_pool=None,
    max_phase_retries: int = 3
) -> bool:
    """
    Quy trình xử lý nhiều tập truyện trong 1 task theo kiến trúc 2 Phase có rào chắn & retry:
    - Phase 1: Crawl tuần tự 1 -> N. Tập nào crawl xong đẩy ngay sang Detect Visual Region & Tạo PDF (tối đa 3 luồng song song).
    - Barrier Phase 1: Đợi toàn bộ các tập 1 -> N có file PDF.
    - Phase 2: Gemini tạo kịch bản tuần tự 1 -> N. Tập nào có kịch bản & audio đẩy ngay sang Render Video (tối đa 3 luồng song song)
      trong lúc Gemini tiếp tục kịch bản cho tập tiếp theo.
    - Phase 3: Kiểm tra toàn bộ danh sách tập. Nếu có tập lỗi/thiếu video -> tự động chạy lại đến khi tất cả các tập đều có video.
    """
    task = context.task
    download_dir = task.artifacts.get("download_dir")
    comic_title = task.artifacts.get("comic_title", task.comic_title)
    episodes = list(range(task.from_episode, task.to_episode + 1))
    
    # Giới hạn 3 luồng song song cho detect visual region & render video theo yêu cầu
    repage_pdf_sem = asyncio.Semaphore(3)
    nsfw_sem = asyncio.Semaphore(3)
    pdf_sem = asyncio.Semaphore(3)
    dl_sem = asyncio.Semaphore(min(12, max(1, 3 * 2)))
    render_sem = asyncio.Semaphore(3)
    tts_sem = asyncio.Semaphore(3)

    # =========================================================================
    # PHASE 1: CRAWL TUẦN TỰ & DETECT VISUAL REGION / PDF SONG SONG (TỐI ĐA 3 LUỒNG)
    # =========================================================================
    await context.log(
        f"=== [PHASE 1] Bắt đầu Crawl tuần tự ({task.from_episode} -> {task.to_episode}) & Detect Visual Region / PDF song song (tối đa 3 luồng) ===",
        "info"
    )

    phase1_tasks = {}

    async def _run_visual_and_pdf(ep_num: int) -> bool:
        # Nếu chưa có slot, đánh dấu trạng thái hàng chờ (WAITING)
        if repage_pdf_sem._value <= 0:
            task.episode_progress.setdefault(str(ep_num), {})["Stage 2b - Intelligent Re-pagination"] = StageState.WAITING
            await context.manager.save_and_broadcast("EpisodeProgressUpdated", task)

        async with repage_pdf_sem:
            if context.cancel_token.is_cancelled():
                raise asyncio.CancelledError()

            # Stage 2b: Detect visual region / Intelligent re-pagination
            if not is_episode_repage_ready(ep_num, download_dir):
                await context.log(f"Tập {ep_num}: Nhận slot xử lý Stage 2 (Detect Visual Region & Tạo PDF). Bắt đầu phân trang...", "info", episode=ep_num)
                await context.update_episode_stage(ep_num, "Stage 2b - Intelligent Re-pagination", StageState.RUNNING)
                s2b_ok = await execute_single_episode_stage2b(ep_num, context, repage_sem=None)
                if not s2b_ok:
                    await context.fail_episode(ep_num, f"Tập {ep_num}: Phân trang / detect visual region thất bại ở Stage 2b.", stage_name="Stage 2b - Intelligent Re-pagination")
                    return False
            else:
                task.episode_progress.setdefault(str(ep_num), {})["Stage 2b - Intelligent Re-pagination"] = StageState.SUCCESS
                await context.log(f"Tập {ep_num}: Đã có dữ liệu phân trang Stage 2b từ trước. Bỏ qua.", "info", stage_name="Stage 2b - Intelligent Re-pagination", episode=ep_num)

            # Stage 3: NSFW Moderation
            if not is_episode_nsfw_ready(ep_num, download_dir):
                if context.cancel_token.is_cancelled():
                    raise asyncio.CancelledError()
                await context.update_episode_stage(ep_num, "Stage 3 - NSFW Moderation", StageState.RUNNING)
                s3_ok = await execute_single_episode_stage3(ep_num, context, nsfw_sem=nsfw_sem)
                if not s3_ok:
                    await context.fail_episode(ep_num, f"Tập {ep_num}: NSFW Moderation thất bại ở Stage 3.", stage_name="Stage 3 - NSFW Moderation")
                    return False
            else:
                task.episode_progress.setdefault(str(ep_num), {})["Stage 3 - NSFW Moderation"] = StageState.SUCCESS
                await context.log(f"Tập {ep_num}: Đã có dữ liệu Stage 3 (NSFW Moderation) từ trước. Bỏ qua.", "info", stage_name="Stage 3 - NSFW Moderation", episode=ep_num)

            # Stage 4: PDF Generation
            if not is_episode_pdf_ready(ep_num, download_dir, comic_title):
                if context.cancel_token.is_cancelled():
                    raise asyncio.CancelledError()
                await context.update_episode_stage(ep_num, "Stage 4 - PDF Generation", StageState.RUNNING)
                s4_ok = await execute_single_episode_stage4(ep_num, context, pdf_sem=pdf_sem)
                if not s4_ok:
                    await context.fail_episode(ep_num, f"Tập {ep_num}: Tạo file PDF thất bại ở Stage 4.", stage_name="Stage 4 - PDF Generation")
                    return False
            else:
                task.episode_progress.setdefault(str(ep_num), {})["Stage 4 - PDF Generation"] = StageState.SUCCESS
                await context.log(f"Tập {ep_num}: Đã có file PDF từ trước. Bỏ qua Stage 4.", "info", stage_name="Stage 4 - PDF Generation", episode=ep_num)

            await context.log(f"Tập {ep_num}: Đã hoàn tất xử lý PDF.", "success", stage_name="Stage 4 - PDF Generation", episode=ep_num)
            return True

    # Crawl tuần tự từng tập
    for ep in episodes:
        if context.cancel_token.is_cancelled():
            raise asyncio.CancelledError()

        # Nếu tập đã có PDF từ trước, cập nhật trạng thái và bỏ qua
        if is_episode_pdf_ready(ep, download_dir, comic_title):
            await context.log(f"Tập {ep}: Đã có sẵn file PDF hợp lệ, bỏ qua bước crawl & visual region.", "info", episode=ep)
            task.episode_progress.setdefault(str(ep), {})["Stage 2 - Async Image Crawling"] = StageState.SUCCESS
            task.episode_progress.setdefault(str(ep), {})["Stage 2 - Image Crawling"] = StageState.SUCCESS
            task.episode_progress.setdefault(str(ep), {})["Stage 2b - Intelligent Re-pagination"] = StageState.SUCCESS
            task.episode_progress.setdefault(str(ep), {})["Stage 3 - NSFW Moderation"] = StageState.SUCCESS
            task.episode_progress.setdefault(str(ep), {})["Stage 4 - PDF Generation"] = StageState.SUCCESS
            continue

        # Nếu tập đã có ảnh crawl hợp lệ (ví dụ bị lỗi ở Stage 3 hoặc Stage 4 lần trước)
        if is_episode_images_ready(ep, download_dir):
            await context.log(f"Tập {ep}: Đã có sẵn ảnh crawl hợp lệ, bỏ qua Stage 2 và tiếp tục xử lý visual region & PDF.", "info", episode=ep)
            task.episode_progress.setdefault(str(ep), {})["Stage 2 - Async Image Crawling"] = StageState.SUCCESS
            task.episode_progress.setdefault(str(ep), {})["Stage 2 - Image Crawling"] = StageState.SUCCESS
            if repage_pdf_sem._value <= 0:
                await context.update_episode_stage(ep, "Stage 2b - Intelligent Re-pagination", StageState.WAITING)
            phase1_tasks[ep] = asyncio.create_task(_run_visual_and_pdf(ep))
            continue

        await context.start_episode(ep, "Stage 2 - Async Image Crawling")
        await context.update_episode_stage(ep, "Stage 2 - Async Image Crawling", StageState.RUNNING)
        s2_ok = await execute_single_episode_stage2(ep, context, browser_context, None, dl_sem)
        if not s2_ok:
            await context.fail_episode(ep, f"Tập {ep}: Crawl ảnh thất bại ở Stage 2.", stage_name="Stage 2 - Async Image Crawling")
        else:
            if repage_pdf_sem._value <= 0:
                await context.log(
                    f"Tập {ep}: Crawl xong. Hiện đang chạy tối đa 3 luồng Stage 2 song song (hết slot trống) -> Thêm Tập {ep} vào hàng chờ Stage 2 và tiếp tục crawl luôn tập tiếp theo...",
                    "info",
                    stage_name="Stage 2 - Async Image Crawling",
                    episode=ep
                )
                await context.update_episode_stage(ep, "Stage 2b - Intelligent Re-pagination", StageState.WAITING)
            else:
                await context.log(
                    f"Tập {ep}: Crawl xong (còn slot trống Stage 2), đẩy ngay sang Detect Visual Region & Tạo PDF song song.",
                    "info",
                    stage_name="Stage 2 - Async Image Crawling",
                    episode=ep
                )
            # Đẩy ngay sang xử lý detect visual region & tạo PDF chạy nền
            phase1_tasks[ep] = asyncio.create_task(_run_visual_and_pdf(ep))

        # Delay ngẫu nhiên nhỏ giữa các lần crawl tuần tự
        await asyncio.sleep(round(random.uniform(0.5, 1.2), 2))

    # Barrier 1: Đợi TẤT CẢ các tập hoàn thành tạo PDF
    if phase1_tasks:
        await context.log(f"Đang chờ tất cả {len(phase1_tasks)} tập hoàn tất xử lý visual region và xuất file PDF...", "info")
        await asyncio.gather(*phase1_tasks.values(), return_exceptions=True)

    # Kiểm tra xem có tập nào thiếu PDF không, retry ngay trong Phase 1 nếu cần
    missing_pdfs = [ep for ep in episodes if not is_episode_pdf_ready(ep, download_dir, comic_title)]
    if missing_pdfs:
        await context.log(f"Cảnh báo: Có {len(missing_pdfs)} tập thiếu file PDF ({missing_pdfs}). Đang thử lại Phase 1...", "warning")
        for ep in missing_pdfs:
            if context.cancel_token.is_cancelled():
                raise asyncio.CancelledError()
            if not is_episode_images_ready(ep, download_dir):
                s2_ok = await execute_single_episode_stage2(ep, context, browser_context, None, dl_sem)
                if s2_ok:
                    await _run_visual_and_pdf(ep)
            else:
                await _run_visual_and_pdf(ep)

    # =========================================================================
    # PHASE 2: GEMINI TẠO KỊCH BẢN TUẦN TỰ & RENDER VIDEO SONG SONG (TỐI ĐA 3 LUỒNG)
    # =========================================================================
    await context.log(
        f"=== [PHASE 2] Tất cả các tập đã có PDF. Bắt đầu Gemini tạo kịch bản tuần tự (1 -> {len(episodes)}) & Render Video song song (tối đa 3 luồng) ===",
        "info"
    )

    from workflow_stages_2 import (
        execute_single_episode_stage6,
        execute_single_episode_stage7,
        execute_single_episode_stage8,
        execute_single_episode_stage9,
        execute_single_episode_stage10,
    )

    render_tasks = []

    # Chạy Gemini tạo kịch bản tuần tự từng tập 1 -> N
    for ep in episodes:
        if context.cancel_token.is_cancelled():
            raise asyncio.CancelledError()

        # Nếu tập đã có video hoàn chỉnh, bỏ qua
        if is_episode_video_ready(ep, download_dir):
            await context.log(f"Tập {ep}: Đã có sẵn video hoàn chỉnh, bỏ qua Gemini & Render.", "info", episode=ep)
            for s_name in [
                "Stage 5 - Gemini Automation",
                "Stage 6 - JSON Extraction",
                "Stage 7 - Narration Aggregation",
                "Stage 8 - Local TTS",
                "Stage 9 - Subtitle Normalization",
                "Stage 10 - Episode Video Rendering"
            ]:
                task.episode_progress.setdefault(str(ep), {})[s_name] = StageState.SUCCESS
            await context.complete_episode(ep)
            continue

        # Stage 5: Gemini Automation
        if not is_episode_script_ready(ep, download_dir):
            await context.update_episode_stage(ep, "Stage 5 - Gemini Automation", StageState.RUNNING)
            s5_ok = await execute_single_episode_stage5(ep, context, vlm_sem=None, profile_pool=profile_pool)
            if not s5_ok:
                await context.fail_episode(ep, f"Tập {ep}: Tạo kịch bản Gemini thất bại ở Stage 5.", stage_name="Stage 5 - Gemini Automation")
                continue
        else:
            task.episode_progress.setdefault(str(ep), {})["Stage 5 - Gemini Automation"] = StageState.SUCCESS
            await context.log(f"Tập {ep}: Đã có sẵn kịch bản recap.json hợp lệ từ trước. Bỏ qua Stage 5.", "info", stage_name="Stage 5 - Gemini Automation", episode=ep)

        # Tập ep vừa hoàn tất Stage 5 (Gemini kịch bản) -> Đẩy ngay sang toàn bộ quy trình hậu kỳ & Render Video (Stage 6 -> 10)
        # Chạy nền với render_sem tối đa 3 luồng song song, để Gemini chuyển ngay sang tạo kịch bản cho tập tiếp theo.
        async def _pipeline_from_stage6_to_video(ep_num: int) -> bool:
            try:
                ep_key = str(ep_num)
                # Stage 6: JSON Extraction
                if context.cancel_token.is_cancelled(): return False
                if not is_episode_script_ready(ep_num, download_dir):
                    await context.update_episode_stage(ep_num, "Stage 6 - JSON Extraction", StageState.RUNNING)
                    if not await execute_single_episode_stage6(ep_num, context):
                        await context.fail_episode(ep_num, f"Tập {ep_num}: Trích xuất JSON thất bại ở Stage 6.", stage_name="Stage 6 - JSON Extraction")
                        return False
                else:
                    task.episode_progress.setdefault(ep_key, {})["Stage 6 - JSON Extraction"] = StageState.SUCCESS

                # Stage 7: Narration Aggregation
                if context.cancel_token.is_cancelled(): return False
                if not is_episode_narration_ready(ep_num, download_dir):
                    await context.update_episode_stage(ep_num, "Stage 7 - Narration Aggregation", StageState.RUNNING)
                    if not await execute_single_episode_stage7(ep_num, context):
                        await context.fail_episode(ep_num, f"Tập {ep_num}: Tổng hợp lời thoại thất bại ở Stage 7.", stage_name="Stage 7 - Narration Aggregation")
                        return False
                else:
                    task.episode_progress.setdefault(ep_key, {})["Stage 7 - Narration Aggregation"] = StageState.SUCCESS
                    await context.log(f"Tập {ep_num}: Đã có narration.txt từ trước. Bỏ qua Stage 7.", "info", stage_name="Stage 7 - Narration Aggregation", episode=ep_num)

                # Stage 8: Local TTS
                if context.cancel_token.is_cancelled(): return False
                if not is_episode_audio_ready(ep_num, download_dir):
                    await context.update_episode_stage(ep_num, "Stage 8 - Local TTS", StageState.RUNNING)
                    if not await execute_single_episode_stage8(ep_num, context, tts_sem=tts_sem):
                        await context.fail_episode(ep_num, f"Tập {ep_num}: Tạo âm thanh TTS thất bại ở Stage 8.", stage_name="Stage 8 - Local TTS")
                        return False
                else:
                    task.episode_progress.setdefault(ep_key, {})["Stage 8 - Local TTS"] = StageState.SUCCESS
                    await context.log(f"Tập {ep_num}: Đã có audio.mp3 và transcript.srt từ trước. Bỏ qua sinh TTS ở Stage 8.", "info", stage_name="Stage 8 - Local TTS", episode=ep_num)

                # Stage 9: Subtitle Normalization
                if context.cancel_token.is_cancelled(): return False
                if not is_episode_subtitles_ready(ep_num, download_dir):
                    await context.update_episode_stage(ep_num, "Stage 9 - Subtitle Normalization", StageState.RUNNING)
                    if not await execute_single_episode_stage9(ep_num, context):
                        await context.fail_episode(ep_num, f"Tập {ep_num}: Tạo timeline phụ đề thất bại ở Stage 9.", stage_name="Stage 9 - Subtitle Normalization")
                        return False
                else:
                    task.episode_progress.setdefault(ep_key, {})["Stage 9 - Subtitle Normalization"] = StageState.SUCCESS

                # Stage 10: Render Video (tối đa 3 luồng song song qua render_sem)
                if not is_episode_video_ready(ep_num, download_dir):
                    async with render_sem:
                        if context.cancel_token.is_cancelled(): return False
                        await context.update_episode_stage(ep_num, "Stage 10 - Episode Video Rendering", StageState.RUNNING)
                        if not await execute_single_episode_stage10(ep_num, context, render_sem=None):
                            await context.fail_episode(ep_num, f"Tập {ep_num}: Render video thất bại ở Stage 10.", stage_name="Stage 10 - Episode Video Rendering")
                            return False
                        await context.complete_episode(ep_num)
                        await context.log(f"Tập {ep_num}: Đã render video hoàn tất thành công!", "success", stage_name="Stage 10 - Episode Video Rendering", episode=ep_num)
                        return True
                else:
                    task.episode_progress.setdefault(ep_key, {})["Stage 10 - Episode Video Rendering"] = StageState.SUCCESS
                    await context.complete_episode(ep_num)
                    await context.log(f"Tập {ep_num}: Đã có sẵn video hoàn chỉnh. Hoàn tất!", "success", stage_name="Stage 10 - Episode Video Rendering", episode=ep_num)
                    return True
            except Exception as pipe_err:
                await context.log(f"Lỗi pipeline hậu kỳ/render tập {ep_num}: {pipe_err}", "error", episode=ep_num)
                return False

        await context.log(
            f"Tập {ep}: Đã tạo xong kịch bản Stage 5 -> Bắn ngay sang pipeline hậu kỳ & Render Video (tối đa 3 luồng), Gemini tiếp tục tập tiếp theo...",
            "info",
            episode=ep
        )
        r_task = asyncio.create_task(_pipeline_from_stage6_to_video(ep))
        render_tasks.append((ep, r_task))

    # Đợi toàn bộ các tác vụ render video nền hoàn tất
    if render_tasks:
        await context.log(f"Đang chờ {len(render_tasks)} tiến trình render video hoàn tất...", "info")
        await asyncio.gather(*[t for _, t in render_tasks], return_exceptions=True)

    # =========================================================================
    # PHASE 3: KIỂM TRA TOÀN BỘ DANH SÁCH TẬP & TỰ ĐỘNG CHẠY LẠI TẬP LỖI
    # =========================================================================
    await context.log("=== [PHASE 3] Kiểm tra tính toàn vẹn danh sách video của tất cả các tập ===", "info")
    for retry_round in range(1, max_phase_retries + 1):
        if context.cancel_token.is_cancelled():
            raise asyncio.CancelledError()

        failed_eps = [ep for ep in episodes if not is_episode_video_ready(ep, download_dir)]
        if not failed_eps:
            await context.log(f"Xác nhận toàn bộ {len(episodes)} tập đều đã có video hoàn chỉnh!", "success")
            break

        await context.log(
            f"[Vòng thử lại {retry_round}/{max_phase_retries}] Phát hiện {len(failed_eps)} tập chưa có video: {failed_eps}. Đang tiến hành chạy lại...",
            "warning"
        )

        retry_render_tasks = []
        for ep in failed_eps:
            if context.cancel_token.is_cancelled():
                raise asyncio.CancelledError()

            # Nếu tập thiếu PDF, chạy lại các stage thiếu trong Phase 1 cho tập này
            if not is_episode_pdf_ready(ep, download_dir, comic_title):
                await context.log(f"Tập {ep} (Retry): Kiểm tra và chạy lại các stage thiếu của Phase 1...", "info", episode=ep)
                if not is_episode_images_ready(ep, download_dir):
                    s2_ok = await execute_single_episode_stage2(ep, context, browser_context, None, dl_sem)
                    if s2_ok:
                        await _run_visual_and_pdf(ep)
                else:
                    await _run_visual_and_pdf(ep)

            if not is_episode_pdf_ready(ep, download_dir, comic_title):
                await context.log(f"Tập {ep} (Retry): Vẫn thiếu PDF, không thể tiếp tục kịch bản.", "error", episode=ep)
                continue

            # Nếu tập thiếu kịch bản recap.json, chạy lại Stage 5
            if not is_episode_script_ready(ep, download_dir):
                await context.log(f"Tập {ep} (Retry): Chạy lại Gemini kịch bản Stage 5...", "info", episode=ep)
                s5_ok = await execute_single_episode_stage5(ep, context, vlm_sem=None, profile_pool=profile_pool)
                if not s5_ok:
                    continue
            else:
                task.episode_progress.setdefault(str(ep), {})["Stage 5 - Gemini Automation"] = StageState.SUCCESS

            # Đẩy sang pipeline hậu kỳ & render video nền
            r_task = asyncio.create_task(_pipeline_from_stage6_to_video(ep))
            retry_render_tasks.append((ep, r_task))

        if retry_render_tasks:
            await asyncio.gather(*[t for _, t in retry_render_tasks], return_exceptions=True)

    # Kiểm tra lần cuối
    still_failed = [ep for ep in episodes if not is_episode_video_ready(ep, download_dir)]
    if still_failed:
        await context.log(f"Lỗi: Sau {max_phase_retries} lần thử lại, các tập sau vẫn chưa có video: {still_failed}", "error")
        return False

    return True
