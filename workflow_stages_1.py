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
from pathlib import Path
from workflow_base import BaseStage, StageState, WorkflowContext, check_episode_completed
import cv2
import numpy as np
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
except Exception:
    pass
from tools.text_remover.comic_text_remover import get_easyocr_reader, ocr_lock
from recap_schema import validate_recap_file
from artifact_cache import EpisodeStageCache, source_hash, stage_fingerprint, validate_pdf_file
from moderation_utils import (
    MODERATION_MODEL_VERSION,
    MODERATION_PROMPT_VERSION,
    create_numbered_pdf,
    list_image_files,
    prepare_safe_pdf_bundle,
    should_use_safety_fallback,
)

def validate_recap_json(file_path):
    recap_path = Path(file_path)
    max_page = None
    for directory_name in ("images_pdf", "images_blur", "images"):
        image_dir = recap_path.parent / directory_name
        if image_dir.is_dir():
            count = sum(
                1
                for item in image_dir.iterdir()
                if item.is_file() and item.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
            )
            if count:
                max_page = count
                break
    return validate_recap_file(recap_path, max_page=max_page)

def safe_cv2_imread(path, flags=cv2.IMREAD_COLOR):
    try:
        with open(path, "rb") as f:
            data = np.frombuffer(f.read(), dtype=np.uint8)
            img = cv2.imdecode(data, flags)
            if img is not None:
                return img
    except Exception:
        pass
    try:
        return cv2.imread(path, flags)
    except Exception:
        return None

def safe_cv2_imwrite(path, img, params=None):
    try:
        ext = os.path.splitext(path)[1]
        success, encoded = cv2.imencode(ext, img, params) if params else cv2.imencode(ext, img)
        if success:
            with open(path, "wb") as f:
                f.write(encoded)
            return True
    except Exception:
        pass
    try:
        return cv2.imwrite(path, img, params)
    except Exception:
        return False

class Stage0_ProjectInit(BaseStage):
    @property
    def name(self) -> str: return "Stage 0 - Project Init"
    @property
    def weight(self) -> float: return 0.02

    async def execute(self, context: WorkflowContext) -> bool:
        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}"
        if not (sys.version_info.major == 3 and sys.version_info.minor >= 10):
            await context.log(f"Yêu cầu Python >= 3.10. Phiên bản hiện tại: {py_ver}", "error")
            return False
        await context.log(f"Python check pass ({py_ver})", "info")

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
        if "comic.naver.com" in parsed.netloc.lower():
            query = urllib.parse.parse_qs(parsed.query)
            t_id = query.get("titleId", [""])[0] or query.get("title_no", [""])[0]
            comic_title = f"Naver_{t_id}" if t_id else "Naver_Webtoon"
        elif "pocket.shonenmagazine.com" in parsed.netloc.lower():
            from magapoke_crawler import parse_magapoke_url
            m_info = parse_magapoke_url(url)
            t_id = m_info.get("title_id") or "magapoke"
            comic_title = f"MagaPoke_{t_id}"
        elif parsed.path:
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
        identity_hash = source_hash(context.task.comic_url)
        download_folder_name = f"{sanitized_title}_{context.task.from_episode}_{context.task.to_episode}_{context.task.payload.get('language', 'en')}_{identity_hash}"
        download_dir = os.path.join(project_dir, "downloads", download_folder_name)
        
        context.task.artifacts["download_folder_name"] = download_folder_name
        context.task.artifacts["download_dir"] = download_dir
        
        os.makedirs(download_dir, exist_ok=True)
        os.makedirs(os.path.join(download_dir, "output"), exist_ok=True)
        
        for ep in range(context.task.from_episode, context.task.to_episode + 1):
            ep_dir = os.path.join(download_dir, f"episode_{ep}")
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
        url = task.comic_url
        if "toongod.org" in url and "/chapter-" in url:
            url = re.sub(r"/chapter-[^/]+/?$", "/", url)
            task.comic_url = url
        elif "asura" in urllib.parse.urlparse(url).netloc.lower() and "/chapter/" in url:
            url = re.sub(r"/chapter/[^/]+/?$", "", url)
            task.comic_url = url
        elif "valirscans.org" in urllib.parse.urlparse(url).netloc.lower() and "/chapter/" in url:
            url = re.sub(r"/chapter/[^/]+/?$", "", url)
            task.comic_url = url
        elif "comic.naver.com" in url:
            parsed_naver = urllib.parse.urlparse(url)
            query = urllib.parse.parse_qs(parsed_naver.query)
            title_id = query.get("titleId", [""])[0] or query.get("title_no", [""])[0]
            if "/webtoon/detail" in parsed_naver.path and title_id:
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
        
        browser, context_pw = await get_shared_browser_context()
        nav_manager = NavigationManager(context)
        nav_manager.context = context_pw
        nav_manager.browser = browser
        page = await context_pw.new_page()
        
        try:
            await nav_manager.safe_goto(page, url, reason="Parse comic metadata", caller="Stage1_ComicParsing")
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
                    show_more_button = page.locator("button:has-text('Show more')")
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
                
                # Extract and sort unique chapter slugs (excluding locked/paid chapters)
                chapter_items = await page.locator("a[href*='/chapter-']").evaluate_all("""
                    elements => elements.map(el => {
                        const href = el.getAttribute('href');
                        const isLocked = !!el.querySelector('svg path[d*="M12 1.5"]') || 
                                         !!el.closest('div')?.querySelector('.text-yellow-500, .text-yellow-600') ||
                                         (el.innerText && el.innerText.includes('PAID'));
                        return { href, isLocked };
                    })
                """)
                vortex_chapters = []
                for item in chapter_items:
                    href = item.get("href")
                    if href and not item.get("isLocked"):
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
            elif "comic.naver.com" in url:
                try:
                    og_meta = await page.locator("meta[property='og:title']").evaluate_all(
                        "elements => elements.map(el => el.getAttribute('content'))"
                    )
                    if og_meta and og_meta[0]:
                        title_text = og_meta[0].strip()
                    if not title_text:
                        h2_list = await page.locator("h2").all_inner_texts()
                        if h2_list and h2_list[0].strip():
                            title_text = h2_list[0].strip()
                except Exception:
                    pass
            elif "pocket.shonenmagazine.com" in url:
                try:
                    from magapoke_crawler import fetch_magapoke_title_info, parse_magapoke_url
                    m_info = parse_magapoke_url(url)
                    task.artifacts["magapoke_title_id"] = m_info.get("title_id")
                    task.artifacts["magapoke_episode_id"] = m_info.get("episode_id")
                    
                    info = await fetch_magapoke_title_info(page, url)
                    if info.get("comic_title"):
                        title_text = info["comic_title"]
                    if info.get("episodes"):
                        task.artifacts["magapoke_episodes"] = info["episodes"]
                except Exception as ex:
                    await context.log(f"Lỗi fetch MagaPoke metadata: {ex}", "warning")
            if not title_text:
                title_text = await page.title()
            if " : 네이버" in title_text:
                title_text = title_text.split(" : 네이버")[0].strip()
            if " / マガポケ" in title_text:
                title_text = title_text.split(" / マガポケ")[0].strip()
            if "【第" in title_text and "】" in title_text:
                # E.g. "Title ~sub~ | 【第1話】..." -> get Title only
                pass
            title_text = title_text.split("|")[0].strip()
            title_text = title_text.split("Chapter")[0].strip()
            sanitized_title = sanitize_title(title_text)
            
            await context.log(f"Comic official title: {title_text}", "info")
            task.comic_title = title_text
            
            old_folder_name = task.artifacts.get("download_folder_name")
            identity_hash = source_hash(task.comic_url)
            new_folder_name = f"{sanitized_title}_{task.from_episode}_{task.to_episode}_{task.payload.get('language', 'en')}_{identity_hash}"
            project_dir = os.path.dirname(os.path.abspath(__file__))
            new_download_dir = os.path.join(project_dir, "downloads", new_folder_name)
            
            if old_folder_name != new_folder_name and os.path.exists(download_dir):
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

class Stage2_AsyncImageCrawling(BaseStage):
    @property
    def name(self) -> str: return "Stage 2 - Image Crawling"
    @property
    def weight(self) -> float: return 0.15

    async def execute(self, context: WorkflowContext) -> bool:
        from app import get_shared_browser_context, NavigationManager, download_image
        
        task = context.task
        url = task.comic_url
        from_ep = task.from_episode
        to_ep = task.to_episode
        download_dir = task.artifacts.get("download_dir")
        
        parsed = urllib.parse.urlparse(url)
        is_naver = "comic.naver.com" in parsed.netloc.lower()
        is_vortex = "vortexscans.org" in parsed.netloc
        is_toongod = "toongod.org" in parsed.netloc
        is_asura = "asura" in parsed.netloc.lower()
        is_comix = "comix.to" in parsed.netloc
        is_valir = "valirscans.org" in parsed.netloc.lower()
        is_magapoke = "pocket.shonenmagazine.com" in parsed.netloc.lower()
        
        if is_naver:
            query = urllib.parse.parse_qs(parsed.query)
            naver_title_id = query.get("titleId", [""])[0] or query.get("title_no", [""])[0]
            if not naver_title_id:
                await context.log("Không tìm thấy titleId trong URL Naver Webtoon.", "error")
                return False
        elif is_vortex:
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 2 and parts[0] == "series":
                series_slug = parts[1]
            else:
                await context.log("Không tìm thấy series slug trong URL Vortex Scans.", "error")
                return False
        elif is_toongod:
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 2 and parts[0] == "webtoon":
                series_slug = parts[1]
            else:
                await context.log("Không tìm thấy series slug trong URL ToonGod.", "error")
                return False
        elif is_asura:
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 2 and parts[0] == "comics":
                series_slug = parts[1]
            else:
                await context.log("Không tìm thấy series slug trong URL Asura Scans.", "error")
                return False
        elif is_comix:
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 2 and parts[0] == "title":
                series_slug = parts[1]
            else:
                await context.log("Không tìm thấy series slug trong URL Comix.", "error")
                return False
        elif is_valir:
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 3 and parts[0] == "series":
                series_slug = "/".join(parts[1:])
            elif len(parts) >= 2 and parts[0] == "series":
                series_slug = parts[1]
            else:
                await context.log("Không tìm thấy series slug trong URL Valir Scans.", "error")
                return False
        elif is_magapoke:
            series_slug = "magapoke"
        else:
            query = urllib.parse.parse_qs(parsed.query)
            title_no = query.get("title_no", [""])[0]
            if not title_no:
                await context.log("Không tìm thấy title_no trong URL.", "error")
                return False
            parts = parsed.path.strip("/").split("/")
            base_path = "/".join(parts[:-1])

        browser, context_pw = await get_shared_browser_context()
        nav_manager = NavigationManager(context)
        nav_manager.context = context_pw
        nav_manager.browser = browser
        page = await context_pw.new_page()
        
        # Block unnecessary resources to speed up page loads and save bandwidth
        async def block_resources(route):
            req_type = route.request.resource_type
            url_lower = route.request.url.lower()
            if "magazinepocket.com" in url_lower or "shonenmagazine.com" in url_lower:
                try:
                    await route.continue_()
                except Exception:
                    pass
                return
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
                    
        try:
            await page.route("**/*", block_resources)
        except Exception as route_err:
            await context.log(f"Lỗi khi thiết lập route filter: {route_err}", "warning")
            
        try:
            total_episodes = to_ep - from_ep + 1
            for idx, ep in enumerate(range(from_ep, to_ep + 1)):
                if context.cancel_token.is_cancelled(): raise asyncio.CancelledError()
                 
                ep_dir = os.path.join(download_dir, f"episode_{ep}")
                ep_images_dir = os.path.join(download_dir, f"episode_{ep}", "images")
                cache = EpisodeStageCache(ep_dir)
                fingerprint = stage_fingerprint(task, "image_crawl", ep, extra=task.artifacts.get("chapter_slugs", []))
                if cache.is_current(
                    stage="image_crawl",
                    fingerprint=fingerprint,
                    outputs=[ep_images_dir],
                    validate=lambda: os.path.isdir(ep_images_dir) and any(
                        name.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
                        for name in os.listdir(ep_images_dir)
                    ),
                ):
                    await context.log(f"Tập {ep}: Đã hoàn thành trước đó. Bỏ qua crawling.", "success")
                    await context.start_episode(ep)
                    await context.complete_episode(ep)
                    await context.update_stage_progress(self.name, ((idx + 1) / total_episodes) * 100.0)
                    continue
                
                await context.start_episode(ep)
                
                if is_magapoke:
                    from magapoke_crawler import crawl_magapoke_episode_images, parse_magapoke_url
                    ep_url = url
                    magapoke_episodes = task.artifacts.get("magapoke_episodes", [])
                    user_ep_id = task.artifacts.get("magapoke_episode_id")
                    if user_ep_id and ep == from_ep:
                        title_id = task.artifacts.get("magapoke_title_id") or "01152"
                        ep_url = f"https://pocket.shonenmagazine.com/title/{title_id}/episode/{user_ep_id}"
                    elif magapoke_episodes and 0 <= (ep - 1) < len(magapoke_episodes):
                        target_ep_obj = magapoke_episodes[ep - 1]
                        eid = target_ep_obj.get("episode_id")
                        title_id = target_ep_obj.get("title_id") or task.artifacts.get("magapoke_title_id") or "01152"
                        ep_url = f"https://pocket.shonenmagazine.com/title/{title_id}/episode/{eid}"

                    images_dir = os.path.join(ep_dir, "images")
                    downloaded_paths = await crawl_magapoke_episode_images(page, ep_url, images_dir, context_logger=context)
                    if not downloaded_paths:
                        await context.fail_episode(ep, "Không thể thu thập ảnh từ Magazine Pocket viewer.")
                        return False
                    
                    await context.log(f"Tập {ep}: Hoàn thành tải {len(downloaded_paths)} ảnh Magazine Pocket.", "success")
                    await context.complete_episode(ep)
                    await context.update_stage_progress(self.name, ((idx + 1) / total_episodes) * 100.0)
                    cache.commit(stage="image_crawl", fingerprint=fingerprint, outputs=[ep_images_dir])
                    continue
                
                if is_naver:
                    viewer_url = f"https://comic.naver.com/webtoon/detail?titleId={naver_title_id}&no={ep}"
                    wait_sel = ".wt_viewer img, #comic_view_area img"
                elif is_vortex:
                    slugs = task.artifacts.get("chapter_slugs", [])
                    if slugs and 0 <= (ep - 1) < len(slugs):
                        chapter_slug = slugs[ep - 1]
                    else:
                        chapter_slug = f"chapter-{ep}"
                    viewer_url = f"{parsed.scheme}://{parsed.netloc}/series/{series_slug}/{chapter_slug}"
                    wait_sel = "img[data-reader-page-image]"
                elif is_toongod:
                    slugs = task.artifacts.get("chapter_slugs", [])
                    if slugs and 0 <= (ep - 1) < len(slugs):
                        chapter_slug = slugs[ep - 1]
                    else:
                        chapter_slug = f"chapter-{ep}"
                    viewer_url = f"{parsed.scheme}://{parsed.netloc}/webtoon/{series_slug}/{chapter_slug}/"
                    wait_sel = ".reading-content img, .wp-manga-chapter-img, div.page-break img, #chapter_imgs img"
                elif is_asura:
                    slugs = task.artifacts.get("chapter_slugs", [])
                    if slugs and 0 <= (ep - 1) < len(slugs):
                        chapter_slug = slugs[ep - 1]
                    else:
                        chapter_slug = f"{ep}"
                    viewer_url = f"{parsed.scheme}://{parsed.netloc}/comics/{series_slug}/chapter/{chapter_slug}"
                    wait_sel = "main img.w-full.block, .ch-images img, .reading-content img, div.flex.flex-col.items-center img"
                elif is_valir:
                    slugs = task.artifacts.get("chapter_slugs", [])
                    if slugs and 0 <= (ep - 1) < len(slugs):
                        chapter_slug = slugs[ep - 1]
                    else:
                        chapter_slug = f"{ep}"
                    viewer_url = f"{parsed.scheme}://{parsed.netloc}/series/{series_slug}/chapter/{chapter_slug}"
                    wait_sel = "img.select-none"
                elif is_comix:
                    slugs = task.artifacts.get("chapter_slugs", [])
                    user_chap_id = task.artifacts.get("user_comix_chap_id")
                    user_chap_num = task.artifacts.get("user_comix_chap_num")
                    payload_group_id = task.payload.get("comix_group_id")
                    
                    def resolve_slug(ep):
                        chapters_info = task.artifacts.get("comix_chapters_info", [])
                        
                        # 1. Match by group_id or group_name first if payload_group_id is present
                        if payload_group_id:
                            for info in chapters_info:
                                if info["chapter_num"] is not None and abs(info["chapter_num"] - ep) < 0.01:
                                    if info["group_id"] == payload_group_id or (info["group_name"] and info["group_name"].strip().lower() == payload_group_id.strip().lower()):
                                        return info["slug"]
                            # Fallback: match prefix in slug
                            for info in chapters_info:
                                if info["chapter_num"] is not None and abs(info["chapter_num"] - ep) < 0.01:
                                    if info["slug"].startswith(f"{payload_group_id}-"):
                                        return info["slug"]
                                        
                        # 2. Match by user explicit chapter ID
                        if user_chap_id and user_chap_num is not None and abs(user_chap_num - ep) < 0.01:
                            for info in chapters_info:
                                if info["chapter_num"] is not None and abs(info["chapter_num"] - ep) < 0.01:
                                    if info["slug"].startswith(f"{user_chap_id}-"):
                                        return info["slug"]
                            if user_chap_num.is_integer():
                                return f"{user_chap_id}-chapter-{int(user_chap_num)}"
                            else:
                                return f"{user_chap_id}-chapter-{user_chap_num}"
                                
                        # 3. Match by chapter number default
                        for info in chapters_info:
                            if info["chapter_num"] is not None and abs(info["chapter_num"] - ep) < 0.01:
                                return info["slug"]
                        return None

                    all_slugs = task.artifacts.get("all_chapter_slugs", [])
                    chapter_slug = resolve_slug(ep)
                    
                    if not chapter_slug:
                        current_page = 2
                        while not chapter_slug and current_page <= 50:
                            await context.log(f"Tải trang mục lục {current_page} để tìm link cho tập {ep}...", "info")
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
                                    # Add unique slugs to current_info
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
                                await context.log(f"Không thể tải trang mục lục động: {parse_err}", "warning")
                                break
                            current_page += 1
                                    
                    if not chapter_slug:
                        if slugs and 0 <= (ep - 1) < len(slugs):
                            chapter_slug = slugs[ep - 1]
                        else:
                            chapter_slug = f"{ep}"
                            
                    viewer_url = f"{parsed.scheme}://{parsed.netloc}/title/{series_slug}/{chapter_slug}"
                    wait_sel = ".rpage-main, img.rpage-page__img"
                else:
                    viewer_url = f"{parsed.scheme}://{parsed.netloc}/{base_path}/ep-{ep}/viewer?title_no={title_no}&episode_no={ep}"
                    wait_sel = "#_imageList img"
                    
                await nav_manager.safe_goto(page, viewer_url, reason=f"Download ep {ep} images", caller="Stage2_AsyncImageCrawling")

                try:
                    await page.wait_for_selector(wait_sel, timeout=15000)
                except Exception:
                    page_text = ""
                    try:
                        page_text = await page.inner_text("body")
                    except Exception:
                        pass
                    if any(kw in page_text.lower() for kw in ["locked chapter", "premium chapter", "unlock chapters", "please login to unlock"]):
                        await context.log(f"Tập {ep} ({chapter_slug}) là tập khóa/trả phí (VIP/Coins). Tự động bỏ qua tập này.", "warning")
                        continue
                    await context.fail_episode(ep, "Không tìm thấy danh sách ảnh truyện.")
                    return False

                if is_comix:
                    try:
                        scroll_height = await page.locator(".rpage-main").evaluate("el => el.scrollHeight")
                        current_scroll = 0
                        step = 6000  # Optimized from 3000 to 6000
                        while current_scroll < scroll_height:
                            current_scroll += step
                            await page.locator(".rpage-main").evaluate(f"el => el.scrollTop = {current_scroll}")
                            await asyncio.sleep(0.2)  # Optimized from 0.5 to 0.2
                            scroll_height = await page.locator(".rpage-main").evaluate("el => el.scrollHeight")
                    except Exception as e:
                        await context.log(f"Lỗi scroll trang comix: {e}", "warning")

                if is_naver:
                    raw_imgs = await page.locator(".wt_viewer img, #comic_view_area img").evaluate_all(
                        "elements => elements.map(el => el.getAttribute('src') || el.getAttribute('data-src'))"
                    )
                    image_urls = [
                        src for src in raw_imgs
                        if src and "webtoon" in src and "agerate" not in src
                    ]
                elif is_vortex:
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
                        await context.log(f"Lỗi trích xuất ảnh Valir: {ext_err}. Dùng fallback DOM.", "warning")
                        image_urls = await page.locator("img.select-none").evaluate_all(
                            "elements => elements.map(el => el.getAttribute('src'))"
                        )
                else:
                    image_urls = await page.locator("#_imageList img").evaluate_all(
                        "elements => elements.map(el => el.getAttribute('data-url') || el.getAttribute('src'))"
                    )
                image_urls = [src for src in image_urls if src]

                if not image_urls:
                    await context.fail_episode(ep, "Không tìm thấy ảnh.")
                    return False

                ep_dir = os.path.join(download_dir, f"episode_{ep}")
                images_dir = os.path.join(ep_dir, "images")
                os.makedirs(images_dir, exist_ok=True)

                success_count = 0
                dl_concurrency = 4 if is_asura else max(8, task.payload.get("concurrency", 5))
                dl_sem = asyncio.Semaphore(dl_concurrency)
                async def dl_task(img_url, img_idx):
                    nonlocal success_count
                    async with dl_sem:
                        file_ext = ".jpg"
                        if ".png" in img_url.lower(): file_ext = ".png"
                        elif ".webp" in img_url.lower(): file_ext = ".webp"
                        save_path = os.path.join(images_dir, f"{str(img_idx).zfill(3)}{file_ext}")
                        
                        if is_naver:
                            referer = "https://comic.naver.com/"
                        elif is_vortex:
                            referer = "https://vortexscans.org/"
                        elif is_toongod:
                            referer = "https://www.toongod.org/"
                        elif is_asura:
                            referer = f"{parsed.scheme}://{parsed.netloc}/"
                        elif is_comix:
                            referer = "https://comix.to/"
                        elif is_valir:
                            referer = "https://valirscans.org/"
                        else:
                            referer = "https://www.webtoons.com/"
                            
                        try:
                            await download_image(img_url, save_path, referer=referer)
                            success_count += 1
                        except Exception as e:
                            await context.log(f"Lỗi tải ảnh {img_idx} ({img_url}): {e}. Bỏ qua ảnh này.", "warning")
                
                await asyncio.gather(*[dl_task(url, i) for i, url in enumerate(image_urls, 1)])
                
                if success_count == 0:
                    await context.fail_episode(ep, "Không tải được bất kỳ ảnh nào thành công.")
                    return False
                elif success_count < len(image_urls):
                    await context.log(f"Tải thành công {success_count}/{len(image_urls)} ảnh.", "warning")
                    
                await context.complete_episode(ep)
                cache.commit(stage="image_crawl", fingerprint=fingerprint, outputs=[ep_images_dir])
                await context.update_stage_progress(self.name, ((idx + 1) / total_episodes) * 100.0)

            return True
        finally:
            if 'page' in locals() and page:
                try:
                    await page.close()
                except Exception:
                    pass

class Stage3_NSFWModeration(BaseStage):
    @property
    def name(self) -> str: return "Stage 3 - NSFW Moderation"
    @property
    def weight(self) -> float: return 0.10

    async def execute(self, context: WorkflowContext) -> bool:
        task = context.task
        from_ep = task.from_episode
        to_ep = task.to_episode
        download_dir = task.artifacts.get("download_dir")
        safe_mode = task.payload.get("safe_mode", False)

        total_episodes = to_ep - from_ep + 1
        for idx, ep in enumerate(range(from_ep, to_ep + 1)):
            if context.cancel_token.is_cancelled(): raise asyncio.CancelledError()

            ep_dir = os.path.join(download_dir, f"episode_{ep}")
            await context.start_episode(ep)
            images_pdf_dir = os.path.join(ep_dir, "images_pdf")
            image_files = list_image_files(images_pdf_dir)
            if not image_files:
                await context.fail_episode(ep, "Không tìm thấy ảnh đã phân trang trong images_pdf.")
                return False

            if safe_mode:
                await context.log(
                    f"Tập {ep}: Hoãn kiểm duyệt {len(image_files)} ảnh; chỉ ảnh được recap chọn mới được kiểm duyệt trước render.",
                    "info",
                )
            else:
                await context.log(f"Tập {ep}: Safe Mode tắt; bỏ qua mọi đường kiểm duyệt.", "info")
            await context.complete_episode(ep)
            await context.update_stage_progress(self.name, ((idx + 1) / total_episodes) * 100.0)
        return True

class Stage4_PDFGeneration(BaseStage):
    @property
    def name(self) -> str: return "Stage 4 - PDF Generation"
    @property
    def weight(self) -> float: return 0.05

    async def execute(self, context: WorkflowContext) -> bool:
        task = context.task
        from_ep = task.from_episode
        to_ep = task.to_episode
        download_dir = task.artifacts.get("download_dir")
        
        total_episodes = to_ep - from_ep + 1
        completed_eps = 0

        async def process_episode_pdf(ep):
            nonlocal completed_eps
            if context.cancel_token.is_cancelled(): raise asyncio.CancelledError()
            
            ep_dir = os.path.join(download_dir, f"episode_{ep}")
            clean_title = "".join(c for c in task.comic_title if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
            pdf_name = f"{clean_title}_Tap_{ep}.pdf"
            pdf_path = os.path.join(ep_dir, "pdf", pdf_name)
            images_pdf_dir = os.path.join(ep_dir, "images_pdf")
            cache = EpisodeStageCache(ep_dir)
            fingerprint = stage_fingerprint(task, "pdf", ep, input_paths=[images_pdf_dir])
            if cache.is_current(
                stage="pdf",
                fingerprint=fingerprint,
                outputs=[pdf_path],
                validate=lambda: validate_pdf_file(pdf_path),
            ):
                await context.log(f"Tập {ep}: Đã hoàn thành trước đó. Bỏ qua PDF Generation.", "success")
                await context.start_episode(ep)
                await context.complete_episode(ep)
                completed_eps += 1
                await context.update_stage_progress(self.name, (completed_eps / total_episodes) * 100.0)
                return True
                
            await context.start_episode(ep)
            image_files = list_image_files(images_pdf_dir)
            if not image_files:
                await context.fail_episode(ep, "Không có ảnh để tạo PDF.")
                return False

            pdf_quality = task.payload.get("pdf_quality", 30)
            await context.log(f"Tập {ep}: Tạo PDF gốc trực tiếp từ images_pdf...", "info")
            await asyncio.to_thread(create_numbered_pdf, images_pdf_dir, pdf_path, pdf_quality)
            await context.complete_episode(ep)
            cache.commit(stage="pdf", fingerprint=fingerprint, outputs=[pdf_path])
            completed_eps += 1
            await context.update_stage_progress(self.name, (completed_eps / total_episodes) * 100.0)
            return True

        concurrency = task.payload.get("concurrency", 5)
        sem = asyncio.Semaphore(concurrency)
        async def process_episode_pdf_sem(ep):
            async with sem:
                return await process_episode_pdf(ep)

        episodes = list(range(from_ep, to_ep + 1))
        tasks = [process_episode_pdf_sem(ep) for ep in episodes]
        results = await asyncio.gather(*tasks)
        return all(results)

class Stage5_GeminiAutomation(BaseStage):
    handles_retries = True

    @property
    def name(self) -> str: return "Stage 5 - Gemini Automation"
    @property
    def weight(self) -> float: return 0.15

    async def execute(self, context: WorkflowContext) -> bool:
        from app import get_browser_context, NavigationManager, textbox_selectors, send_selectors, response_selectors, generate_gemini_prompt, extract_json_from_text, parse_gemini_recap_text, clean_gemini_response
        from playwright.async_api import async_playwright
        import uuid
        import base64
        import random
        
        task = context.task
        from_ep = task.from_episode
        to_ep = task.to_episode
        download_dir = task.artifacts.get("download_dir")
        comic_title = task.artifacts.get("comic_title", "Manhwa")
        timeout = max(int(task.payload.get("timeout", 160)), 300)
        language = task.payload.get("language", "en")
        safe_mode = task.payload.get("safe_mode", False)

        # Configurations
        max_retries = task.payload.get("retry_count", 5)
        vlm_provider = "gemini"

        episodes_to_process = list(range(from_ep, to_ep + 1))

        total_eps = len(episodes_to_process)
        completed_eps_count = 0

        async def get_local_context():
            from app import check_and_rotate_profiles_until_ready, NavigationManager
            br, shared_ctx = await check_and_rotate_profiles_until_ready(context, force_check=False)
            ctx_id = f"ctx_{int(time.time() * 1000) % 10000}"
            nm = NavigationManager(context)
            nm.context = shared_ctx
            nm.browser = br
            return br, shared_ctx, ctx_id, nm, False

        js_paste_pdf = """
        async (args) => {
            const { xpath, base64Data, fileName, mimeType } = args;
            let element;
            if (xpath.startsWith('xpath=')) {
                const result = document.evaluate(xpath.replace('xpath=', ''), document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
                element = result.singleNodeValue;
            } else {
                element = document.querySelector(xpath);
            }
            if (!element) throw new Error("Không tìm thấy ô nhập prompt.");
            element.focus();
            const res = await fetch("data:" + mimeType + ";base64," + base64Data);
            const blob = await res.blob();
            const file = new File([blob], fileName, { type: mimeType });
            const dataTransfer = new DataTransfer();
            dataTransfer.items.add(file);
            const pasteEvent = new ClipboardEvent('paste', { bubbles: true, cancelable: true, clipboardData: dataTransfer });
            element.dispatchEvent(pasteEvent);
            return true;
        }
        """

        async def process_episode_vlm(ep):
            nonlocal completed_eps_count
            vlm_name = "Gemini"
            vlm_url = "https://gemini.google.com/app"
            
            ep_dir = os.path.join(download_dir, f"episode_{ep}")
            await context.start_episode(ep)
            clean_title = "".join(c for c in task.comic_title if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
            pdf_name = f"{clean_title}_Tap_{ep}.pdf"
            raw_pdf_path = os.path.join(ep_dir, "pdf", pdf_name)
            if not os.path.exists(raw_pdf_path):
                pdf_dir = os.path.join(ep_dir, "pdf")
                if os.path.exists(pdf_dir):
                    pdf_files = [f for f in os.listdir(pdf_dir) if f.lower().endswith(".pdf")]
                    if pdf_files:
                        raw_pdf_path = os.path.join(pdf_dir, pdf_files[0])
            images_pdf_dir = os.path.join(ep_dir, "images_pdf")
            raw_response_path = os.path.join(ep_dir, "raw_gemini_response.txt")
            recap_json_path = os.path.join(ep_dir, "recap.json")

            image_files = list_image_files(images_pdf_dir)
            market_id = task.payload.get("market_id")
            prompt_content = generate_gemini_prompt(comic_title, ep, len(image_files), language, market_id=market_id)
            cache = EpisodeStageCache(ep_dir)
            safe_bundle_dir = os.path.join(ep_dir, "gemini_safe")
            safe_pdf_path = os.path.join(safe_bundle_dir, pdf_name)
            safe_marker_path = os.path.join(safe_bundle_dir, "used.json")
            from types import SimpleNamespace
            fallback_task = SimpleNamespace(
                comic_url=task.comic_url,
                payload={**task.payload, "safe_mode": True},
            )
            safe_fingerprint = stage_fingerprint(
                fallback_task,
                "gemini_safe_pdf",
                ep,
                input_paths=[images_pdf_dir],
                extra={
                    "model": MODERATION_MODEL_VERSION,
                    "prompt": MODERATION_PROMPT_VERSION,
                },
            )
            raw_gemini_fingerprint = stage_fingerprint(
                task, "gemini", ep, input_paths=[raw_pdf_path], extra=prompt_content
            )
            cached_gemini_fingerprint = cache.data.get("stages", {}).get("gemini", {}).get("fingerprint")
            cached_safe_gemini_fingerprint = None
            if validate_pdf_file(safe_pdf_path) and os.path.isfile(safe_marker_path):
                cached_safe_gemini_fingerprint = stage_fingerprint(
                    task, "gemini", ep, input_paths=[safe_pdf_path], extra=prompt_content
                )

            if (
                cached_safe_gemini_fingerprint is not None
                and cached_gemini_fingerprint == str(cached_safe_gemini_fingerprint)
            ):
                pdf_path = safe_pdf_path
                fingerprint = cached_safe_gemini_fingerprint
            else:
                pdf_path = raw_pdf_path
                fingerprint = raw_gemini_fingerprint

            if cache.is_current(
                stage="gemini",
                fingerprint=fingerprint,
                outputs=[raw_response_path, recap_json_path],
                validate=lambda: validate_recap_json(recap_json_path),
            ):
                await context.log(f"Tập {ep}: Cache Gemini hợp lệ. Bỏ qua automation.", "success")
                await context.complete_episode(ep)
                completed_eps_count += 1
                await context.update_stage_progress(self.name, (completed_eps_count / total_eps) * 100.0)
                return True

            safe_bundle_current = False
            if safe_mode and os.path.isdir(safe_bundle_dir):
                safe_bundle_current = cache.is_current(
                    stage="gemini_safe_pdf",
                    fingerprint=safe_fingerprint,
                    outputs=[safe_bundle_dir],
                    validate=lambda: validate_pdf_file(safe_pdf_path) and os.path.isfile(safe_marker_path),
                )
            safe_gemini_fingerprint = None
            if safe_bundle_current:
                safe_gemini_fingerprint = stage_fingerprint(
                    task, "gemini", ep, input_paths=[safe_pdf_path], extra=prompt_content
                )
            pdf_path = safe_pdf_path if safe_mode and safe_bundle_current else raw_pdf_path
            fingerprint = (
                safe_gemini_fingerprint
                if pdf_path == safe_pdf_path and safe_gemini_fingerprint is not None
                else raw_gemini_fingerprint
            )

            success = False
            start_time = time.time()

            for attempt in range(1, max_retries + 1):
                if context.cancel_token.is_cancelled():
                    break
                response_text = ""
                attempt_deadline = time.monotonic() + timeout
                try:
                    local_br, local_br_ctx, local_ctx_id, local_nm, should_close_ctx = await asyncio.wait_for(
                        get_local_context(),
                        timeout=max(0.1, attempt_deadline - time.monotonic()),
                    )
                except asyncio.TimeoutError:
                    await context.log(
                        f"Tập {ep}: Hết thời gian {timeout}s khi khởi tạo browser (thử {attempt}/{max_retries}).",
                        "warning",
                        episode=ep,
                    )
                    continue
                except Exception as ctx_err:
                    await context.log(f"Không thể khởi tạo browser context: {ctx_err}", "error", episode=ep)
                    continue

                page_id = f"page_{ep}_{attempt}_{int(time.time() * 1000) % 1000}"
                await context.log(f"[{local_ctx_id}] [Page {page_id}] Bắt đầu xử lý tập {ep} (Lần {attempt}) bằng {vlm_name}...", "info", episode=ep)
                attempt_task = asyncio.current_task()
                attempt_timed_out = False

                def cancel_timed_out_attempt():
                    nonlocal attempt_timed_out
                    attempt_timed_out = True
                    if attempt_task is not None:
                        attempt_task.cancel()

                timeout_handle = asyncio.get_running_loop().call_later(
                    max(0.0, attempt_deadline - time.monotonic()),
                    cancel_timed_out_attempt,
                )

                def extend_attempt_timeout(additional_seconds=60):
                    nonlocal timeout_handle
                    if timeout_handle is not None:
                        timeout_handle.cancel()
                    timeout_handle = asyncio.get_running_loop().call_later(
                        max(5.0, additional_seconds),
                        cancel_timed_out_attempt,
                    )
                page = None
                try:
                    page = await local_br_ctx.new_page()
                    
                    # STEP 1: Open VLM
                    nav_start = time.time()
                    await local_nm.safe_goto(page, vlm_url, reason=f"Load {vlm_name} ep {ep}", caller=f"Ep_{ep}")
                    await asyncio.sleep(2.0)
                    
                    # Ensure 3.6 Flash is selected and check rate-limit status on this page before prompting
                    try:
                        from app import check_gemini_login_and_limit_status
                        status = await check_gemini_login_and_limit_status(page, context)
                        if status == "limited":
                            raise Exception("Tài khoản đang bị giới hạn model 3.6 Flash.")
                        elif status == "needs_login":
                            await context.log("Tài khoản chưa đăng nhập. Đang chờ đăng nhập thủ công (tối đa 180s)...", "warning", episode=ep)
                            login_success = False
                            for _ in range(90):
                                await asyncio.sleep(2)
                                new_status = await check_gemini_login_and_limit_status(page, None)
                                if new_status != "needs_login":
                                    login_success = True
                                    status = new_status
                                    await context.log("Đăng nhập thành công!", "success", episode=ep)
                                    break
                            if not login_success:
                                raise Exception("Bỏ qua tài khoản do hết thời gian chờ đăng nhập.")
                            if status == "limited":
                                raise Exception("Tài khoản đang bị giới hạn model 3.6 Flash.")
                    except Exception as select_err:
                        if "giới hạn" in str(select_err) or "đăng nhập" in str(select_err):
                            raise select_err
                        await context.log(f"Cảnh báo: Không thể kiểm tra/chọn model 3.6 Flash: {select_err}", "warning", episode=ep)
                        
                    nav_time = round(time.time() - nav_start, 1)

                    textbox = None
                    textbox_xpath = None
                    for sel in textbox_selectors:
                        loc = page.locator(sel).first
                        if await loc.count() > 0 and await loc.is_visible():
                            textbox = loc
                            textbox_xpath = sel
                            break
                    if not textbox:
                        raise Exception("Không tìm thấy input textbox.")

                    # STEP 2: Upload PDF
                    # STEP 2: Upload PDF
                    upload_start = time.time()
                    await context.log(f"[Page {page_id}] Tập {ep}: Bắt đầu tải lên PDF...", "info", episode=ep)
                    
                    upload_success = False
                    try:
                        attach_button = None
                        attach_selectors = [
                            "button[data-testid='file-uploader']",
                            "button[aria-label='Upload & tools']",
                            "button[aria-label*='Attach']",
                            "button[aria-label*='attach']",
                            "button[aria-label*='Đính kèm']",
                            "button[aria-label*='đính kèm']",
                            "button[aria-label*='Upload']",
                            "button:has-text('+')",
                        ]
                        for sel in attach_selectors:
                            loc = page.locator(sel).first
                            if await loc.count() > 0 and await loc.is_visible():
                                attach_button = loc
                                break
                        
                        if attach_button:
                            await attach_button.click()
                            await asyncio.sleep(1.5)
                        
                        file_input = page.locator("input[type='file'][accept*='.pdf'], input.hidden-file-input, input[type='file']").first
                        if await file_input.count() > 0:
                            await file_input.set_input_files(pdf_path)
                            upload_success = True
                            await context.log(f"[Page {page_id}] Tập {ep}: Đã tải lên PDF bằng file input thành công.", "info", episode=ep)
                    except Exception as upload_err:
                        await context.log(f"[Page {page_id}] Thử tải lên bằng file input thất bại: {upload_err}. Thử fallback...", "warning", episode=ep)

                    if not upload_success:
                        with open(pdf_path, "rb") as pdf_file:
                            pdf_base64 = base64.b64encode(pdf_file.read()).decode("utf-8")
                        await page.evaluate(js_paste_pdf, {
                            "xpath": textbox_xpath,
                            "base64Data": pdf_base64,
                            "fileName": os.path.basename(pdf_path),
                            "mimeType": "application/pdf"
                        })
                        await context.log(f"[Page {page_id}] Tập {ep}: Đã tải lên PDF bằng Clipboard Fallback.", "info", episode=ep)
                    
                    await asyncio.sleep(2.0)
                    upload_time = round(time.time() - upload_start, 1)

                    # STEP 3: Wait for PDF attachment chip & upload completion
                    await context.log(f"[Page {page_id}] Tập {ep}: Đang kiểm tra trạng thái tải lên của PDF...", "info", episode=ep)
                    attachment_appeared = False
                    for _ in range(15):
                        if context.cancel_token.is_cancelled():
                            break
                        chip = page.locator("gem-attachment, .attachment-container, [data-testid*='attachment'], [class*='file-card'], div:has-text('.pdf')").first
                        if await chip.count() > 0:
                            attachment_appeared = True
                            break
                        await asyncio.sleep(1)

                    if not attachment_appeared:
                        await context.log(f"[Page {page_id}] Tập {ep}: Cảnh báo: Chưa phát hiện thẻ attachment sau 15s. Tiếp tục kiểm tra spinner...", "warning", episode=ep)

                    loader_check_sec = 0
                    while loader_check_sec < 90:
                        if context.cancel_token.is_cancelled():
                            break
                        try:
                            spinner = page.locator("gem-attachment mat-spinner, gem-attachment .mat-mdc-progress-spinner, gem-attachment [role='progressbar'], .loading-indicator").first
                            if await spinner.count() > 0 and await spinner.is_visible():
                                if loader_check_sec % 10 == 0:
                                    await context.log(f"[Page {page_id}] Tập {ep}: PDF đang tải lên/xử lý (loading). Đã chờ {loader_check_sec} giây...", "info", episode=ep)
                                await asyncio.sleep(1)
                                loader_check_sec += 1
                                continue
                        except Exception:
                            pass
                        break

                    await context.log(f"[Page {page_id}] Tập {ep}: PDF đã tải xong (trạng thái loading biến mất).", "success", episode=ep)
                    await asyncio.sleep(2.0)

                    # STEP 4: Paste Prompt
                    await textbox.click(force=True)
                    await textbox.fill(prompt_content)
                    try:
                        await textbox.press_sequentially(" ")
                        await textbox.press("Backspace")
                    except Exception:
                        pass
                    await asyncio.sleep(2.0)

                    # STEP 4: Send Prompt
                    editor_text = ""
                    for locator_sel in ["rich-textarea", "div[contenteditable='true']"]:
                        try:
                            loc = page.locator(locator_sel).first
                            if await loc.count() > 0:
                                txt = await loc.inner_text()
                                if txt and txt.strip():
                                    editor_text = txt
                                    break
                        except Exception:
                            pass
                    if not editor_text:
                        try:
                            editor_text = await textbox.input_value()
                        except Exception:
                            try:
                                editor_text = await textbox.inner_text()
                            except Exception:
                                editor_text = ""
                    if not editor_text or not editor_text.strip():
                        raise Exception("Xác thực thất bại: Prompt editor bị trống.")

                    # STEP 5: Click Send/Submit!
                    send_button = None
                    button_found = False
                    for wait_sec in range(30):  # Chờ tối đa 30 giây để file processing xong và nút Gửi được bật
                        if context.cancel_token.is_cancelled():
                            break
                        
                        target_btn = None
                        for sel in send_selectors:
                            try:
                                loc = page.locator(sel).first
                                if await loc.count() > 0 and await loc.is_visible():
                                    target_btn = loc
                                    break
                            except Exception:
                                pass
                        
                        if target_btn:
                            button_found = True
                            if await target_btn.is_enabled():
                                send_button = target_btn
                                break
                            else:
                                if wait_sec % 5 == 0:
                                    await context.log(f"[Page {page_id}] Tập {ep}: Nút Gửi đã tìm thấy nhưng đang bị tắt (disabled). Có thể tệp đang được xử lý tiếp. Đang chờ...", "info", episode=ep)
                        
                        await asyncio.sleep(1)

                    if send_button:
                        await send_button.click(force=True)
                        await context.log(f"[Page {page_id}] Tập {ep}: Đã click nút Gửi.", "success", episode=ep)
                    elif button_found:
                        raise Exception("Nút Gửi vẫn bị tắt (disabled) sau 30 giây chờ xử lý tệp. Bỏ qua để thử lại.")
                    else:
                        await textbox.press("Control+Enter")
                        await context.log(f"[Page {page_id}] Tập {ep}: Không tìm thấy nút Gửi, gửi prompt bằng Control+Enter.", "success", episode=ep)
                    
                    gen_start = time.time()
                    response_text = ""
                    error_reason = None
                    response_deadline = time.monotonic() + timeout
                    extend_attempt_timeout(timeout)
                    unchanged_seconds = 0
                    last_checked_text = ""
                    
                    while time.monotonic() < response_deadline:
                        if context.cancel_token.is_cancelled():
                            break
                        await asyncio.sleep(3)
                        
                        # Optimized DOM error check
                        for sel in ["div.message-content", "div.model-response-text", "div.alert", "div[data-message-author-role='assistant']"]:
                            loc = page.locator(sel)
                            count = await loc.count()
                            for idx in range(count):
                                elem = loc.nth(idx)
                                txt = await elem.inner_text()
                                if any(err in txt for err in ["Something went wrong", "1155", "1152", "1099", "1076", "There was an error generating", "an error occurred"]):
                                    error_reason = f"VLM Error detected: {txt}"
                                    break
                            if error_reason:
                                break
                        
                        if error_reason:
                            break

                        # Check thinking container state
                        has_thinking = False
                        is_still_thinking = False
                        has_finished_thinking = False
                        
                        thinking_container = page.locator(".thinking-container, [data-testid='thinking-indicator']").first
                        if await thinking_container.count() > 0 and await thinking_container.is_visible():
                            has_thinking = True
                            chevron_down = page.locator(".thinking-container svg.lucide-chevron-down, [data-testid='thinking-indicator'] svg.lucide-chevron-down").first
                            if await chevron_down.count() > 0 and await chevron_down.is_visible():
                                is_still_thinking = True
                            
                            panel_left_open = page.locator(".thinking-container svg.lucide-panel-left-open, [data-testid='thinking-indicator'] svg.lucide-panel-left-open").first
                            if await panel_left_open.count() > 0 and await panel_left_open.is_visible():
                                has_finished_thinking = True

                        # Check if still generating by looking for stop button/icon
                        is_generating = False
                        stop_button_selectors = [
                            "button[aria-label='Stop generating']",
                            "button[aria-label*='Stop']",
                            "button[aria-label*='stop']",
                            "button[aria-label*='Dừng']",
                            "button[aria-label*='dừng']",
                            "button[data-testid='stop-button']",
                            "[data-testid='stop-button']",
                            "[aria-label='Stop generating']",
                            "[aria-label='Stop']",
                            "[aria-label='stop']",
                            "mat-icon:has-text('stop')",
                            "mat-icon[fonticon='stop']",
                            "gem-icon-button[aria-label*='Stop']",
                            "gem-icon-button[aria-label*='stop']",
                            "gem-icon-button[aria-label*='Dừng']",
                            "gem-icon-button[aria-label*='dừng']"
                        ]
                        for stop_sel in stop_button_selectors:
                            try:
                                loc = page.locator(stop_sel).first
                                if await loc.count() > 0 and await loc.is_visible():
                                    is_generating = True
                                    break
                            except Exception:
                                pass

                        # As long as Gemini is thinking or generating, keep extending deadline
                        if is_generating or is_still_thinking:
                            response_deadline = max(response_deadline, time.monotonic() + 90)
                            extend_attempt_timeout(90)

                        # Get response text using response selectors
                        text_content = None
                        for sel in response_selectors:
                            loc = page.locator(sel).last
                            if await loc.count() > 0:
                                txt = await loc.inner_text()
                                if txt.strip():
                                    if "you are an elite" in txt.lower():
                                        continue
                                    text_content = txt
                                    break
                                    
                        if text_content:
                            response_text = text_content
                            if response_text == last_checked_text:
                                unchanged_seconds += 3
                            else:
                                unchanged_seconds = 0
                                last_checked_text = response_text
                                # Extend deadline and asyncio timeout handle as long as text is actively streaming
                                response_deadline = max(response_deadline, time.monotonic() + 90)
                                extend_attempt_timeout(90)

                            cleaned_response = clean_gemini_response(response_text).strip()
                            can_check_completion = True
                            if is_generating:
                                can_check_completion = False

                            if has_thinking:
                                if is_still_thinking or not has_finished_thinking:
                                    if not cleaned_response.endswith("#"):
                                        can_check_completion = False

                            # Safety backup check: if response has not changed for at least 9 seconds, we can treat it as done.
                            if not can_check_completion and unchanged_seconds >= 9:
                                can_check_completion = True

                            if can_check_completion:
                                try:
                                    parsed = parse_gemini_recap_text(response_text)
                                    if parsed and len(parsed) > 0:
                                        if cleaned_response.endswith("#") or unchanged_seconds >= 6:
                                            break
                                except Exception:
                                    pass
                                    
                                extracted = extract_json_from_text(response_text)
                                if extracted:
                                    try:
                                        parsed = json.loads(extracted)
                                        if isinstance(parsed, list) and len(parsed) > 0:
                                            valid_schema = True
                                            for item in parsed:
                                                if not isinstance(item, dict) or "speech" not in item or "images" not in item:
                                                    valid_schema = False
                                                    break
                                            if valid_schema:
                                                break
                                    except Exception:
                                        pass
                            
                            if unchanged_seconds >= 45:
                                break

                    if error_reason:
                        raise Exception(error_reason)

                    if not response_text:
                        raise Exception("Không nhận được phản hồi hoặc phản hồi rỗng.")

                    parsed_data = parse_gemini_recap_text(response_text)
                    if not parsed_data:
                        raise Exception(f"Không thể trích xuất kịch bản recap từ phản hồi của {vlm_name}.")
                    
                    from recap_schema import parse_recap_data
                    normalized_data = [item.model_dump(mode="json") for item in parse_recap_data(parsed_data, max_page=len(image_files))]
                    raw_temp_path = raw_response_path + ".tmp"
                    recap_temp_path = recap_json_path + ".tmp"
                    with open(raw_temp_path, "w", encoding="utf-8") as rf:
                        rf.write(response_text)
                    with open(recap_temp_path, "w", encoding="utf-8") as jf:
                        json.dump(normalized_data, jf, ensure_ascii=False, indent=2, allow_nan=False)
                    os.replace(raw_temp_path, raw_response_path)
                    os.replace(recap_temp_path, recap_json_path)
                    cache.commit(stage="gemini", fingerprint=fingerprint, outputs=[raw_response_path, recap_json_path])

                    gen_time = round(time.time() - gen_start, 1)
                    total_dur = round(time.time() - start_time, 1)
                    
                    await context.log(
                        f"[{local_ctx_id}] [Page {page_id}] [Tập {ep}] Thành công. Nav: {nav_time}s | Upload: {upload_time}s | Gen: {gen_time}s | Thử: {attempt}/{max_retries} | Tổng: {total_dur}s",
                        "success", episode=ep
                    )
                    success = True
                    await context.complete_episode(ep)
                    break

                except asyncio.CancelledError:
                    if not attempt_timed_out:
                        raise
                    if attempt_task is not None and hasattr(attempt_task, "uncancel"):
                        attempt_task.uncancel()
                    await context.log(
                        f"Tập {ep}: Vượt quá deadline {timeout}s (thử {attempt}/{max_retries}).",
                        "warning",
                        episode=ep,
                    )
                except Exception as e:
                    await context.log(
                        f"[{local_ctx_id}] [Page {page_id}] Lỗi xử lý tập {ep} (Thử {attempt}/{max_retries}): {e}",
                        "warning", episode=ep
                    )

                    failure_text = f"{e}\n{response_text}"
                    should_retry_with_safe_pdf = should_use_safety_fallback(
                        safe_mode=safe_mode,
                        attempt=attempt,
                        response=failure_text,
                    )

                    if should_retry_with_safe_pdf:
                        await context.log(
                            f"Tập {ep}: Gemini từ chối vì safety; chỉ chapter này sẽ được kiểm duyệt toàn bộ vào PDF fallback tạm.",
                            "info",
                            episode=ep,
                        )
                        try:
                            from app import sanitize_episode_images

                            pdf_path = str(await prepare_safe_pdf_bundle(
                                images_pdf_dir,
                                safe_bundle_dir,
                                pdf_name=pdf_name,
                                pdf_quality=task.payload.get("pdf_quality", 30),
                                sanitizer=sanitize_episode_images,
                                sanitizer_kwargs={
                                    "nsfw_threshold": task.payload.get("nsfw_threshold", 0.3),
                                    "nsfw_mode": task.payload.get("nsfw_mode", "mask"),
                                    "sse_logger": context,
                                    "concurrency": task.payload.get("concurrency", 5),
                                },
                            ))
                            cache.commit(
                                stage="gemini_safe_pdf",
                                fingerprint=safe_fingerprint,
                                outputs=[safe_bundle_dir],
                            )
                            fingerprint = stage_fingerprint(
                                task,
                                "gemini",
                                ep,
                                input_paths=[pdf_path],
                                extra=prompt_content,
                            )
                            await context.log(
                                f"Tập {ep}: Đã tạo PDF fallback riêng; ảnh chuẩn và PDF gốc không bị thay đổi.",
                                "success",
                                episode=ep,
                            )
                        except Exception as safe_err:
                            pdf_path = raw_pdf_path
                            fingerprint = stage_fingerprint(
                                task,
                                "gemini",
                                ep,
                                input_paths=[pdf_path],
                                extra=prompt_content,
                            )
                            await context.log(f"Lỗi tạo PDF safety fallback: {safe_err}", "error", episode=ep)
                            
                    # Reset shared context on any failure so next attempt checks rate limit and rotates profile if needed
                    await context.log("Đặt lại browser context để sẵn sàng xoay vòng tài khoản nếu cần...", "warning", episode=ep)
                    try:
                        from app import reset_shared_browser_context
                        await reset_shared_browser_context()
                    except Exception:
                        pass

                finally:
                    timeout_handle.cancel()
                    if page:
                        try:
                            await page.close()
                        except Exception:
                            pass
                        page = None
                    if should_close_ctx and local_br_ctx:
                        try:
                            await local_br_ctx.close()
                        except Exception:
                            pass

            if not success:
                await context.fail_episode(ep, f"Không thể lấy được JSON hợp lệ sau {max_retries} lần thử.")
            
            valid_count = sum(1 for e in range(from_ep, to_ep + 1) if validate_recap_json(os.path.join(download_dir, f"episode_{e}", "recap.json")))
            await context.update_stage_progress(self.name, (valid_count / (to_ep - from_ep + 1)) * 100.0)
            return success

        # Process episodes sequentially
        await context.log(f"Stage 5: Bắt đầu xử lý tuần tự từng chap bằng {vlm_provider.capitalize()}.", "info")

        for ep in episodes_to_process:
            if context.cancel_token.is_cancelled():
                break
            try:
                await process_episode_vlm(ep)
            except Exception as e:
                await context.log(f"Lỗi không mong muốn trong tiến trình chạy tập {ep}: {e}", "error")

        # Playwright persistent Chrome Profile context handles storage state saving natively
        pass

        all_passed = True
        for ep in range(from_ep, to_ep + 1):
            ep_dir = os.path.join(download_dir, f"episode_{ep}")
            recap_json_path = os.path.join(ep_dir, "recap.json")
            if not validate_recap_json(recap_json_path):
                all_passed = False
                break

        if all_passed:
            await context.update_stage_progress(self.name, 100.0)
            return True
        else:
            await context.log("Một số tập phim không tạo được JSON hợp lệ.", "error")
            return False

class Stage6_JSONExtraction(BaseStage):
    @property
    def name(self) -> str: return "Stage 6 - JSON Extraction"
    @property
    def weight(self) -> float: return 0.05

    async def execute(self, context: WorkflowContext) -> bool:
        task = context.task
        from_ep = task.from_episode
        to_ep = task.to_episode
        download_dir = task.artifacts.get("download_dir")

        total_episodes = to_ep - from_ep + 1
        for idx, ep in enumerate(range(from_ep, to_ep + 1)):
            if context.cancel_token.is_cancelled(): raise asyncio.CancelledError()
            
            recap_json_path = os.path.join(download_dir, f"episode_{ep}", "recap.json")
            await context.start_episode(ep)
            ep_dir = os.path.join(download_dir, f"episode_{ep}")
            recap_json_path = os.path.join(ep_dir, "recap.json")

            if not validate_recap_json(recap_json_path):
                await context.fail_episode(ep, f"JSON tại tập {ep} không tồn tại hoặc không hợp lệ.")
                return False
            await context.complete_episode(ep)
            await context.update_stage_progress(self.name, ((idx + 1) / total_episodes) * 100.0)
        return True

class Stage2b_IntelligentRepagination(BaseStage):
    @property
    def name(self) -> str: return "Stage 2b - Intelligent Re-pagination"
    @property
    def weight(self) -> float: return 0.05

    async def execute(self, context: WorkflowContext) -> bool:
        import os
        import json
        import shutil
        import asyncio
        import cv2
        import numpy as np
        import matplotlib.pyplot as plt
        
        task = context.task
        from_ep = task.from_episode
        to_ep = task.to_episode
        download_dir = task.artifacts.get("download_dir")
        
        # Pre-initialize EasyOCR reader on main thread
        from tools.text_remover.comic_text_remover import get_easyocr_reader
        try:
            get_easyocr_reader(['en'])
        except Exception:
            pass
        
        # Configurations (Optimized for Sub-panel Segmentation)
        min_height = task.payload.get("repage_min_height", 350)
        max_height = task.payload.get("repage_max_height", 1400)
        canny_low = task.payload.get("repage_canny_low", 50)
        canny_high = task.payload.get("repage_canny_high", 150)
        
        # New split optimization configurations
        tolerance = task.payload.get("repage_tolerance", 15)
        bg_threshold = task.payload.get("repage_bg_threshold", 0.98)
        min_panel_h = task.payload.get("repage_min_panel_h", 8)
        forbidden_padding = task.payload.get("repage_forbidden_padding", 10)
        skip_blank = task.payload.get("repage_skip_blank", True)
        use_ocr = task.payload.get("repage_use_ocr", False)
        
        total_episodes = to_ep - from_ep + 1
        
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

        def optimize_splits(height, clean_rows, is_forbidden, target_h, min_h, max_h, row_complexity=None):
            clean_bands = group_clean_bands(clean_rows)
            
            splits = [0]
            y_curr = 0
            
            while y_curr < height:
                y_ideal = y_curr + target_h
                y_min = y_curr + min_h
                y_max = y_curr + max_h
                
                # If the remaining part is within the maximum limit, finish it
                if height - y_curr <= max_h:
                    splits.append(height)
                    break
                    
                # Limit search space to image bounds
                y_min = min(y_min, height - 1)
                y_max = min(y_max, height - 1)
                
                # Step 1: Look for clean bands whose centers fall in [y_min, y_max] and are not forbidden
                best_clean_split = None
                best_clean_dist = float('inf')
                
                for start, end, center in clean_bands:
                    if y_min <= center <= y_max:
                        # Check if this center or band is forbidden
                        if not is_forbidden[center]:
                            dist = abs(center - y_ideal)
                            if dist < best_clean_dist:
                                best_clean_dist = dist
                                best_clean_split = center
                                
                if best_clean_split is not None:
                    splits.append(best_clean_split)
                    y_curr = best_clean_split
                    continue
                    
                # Step 2: Fall back to any non-forbidden rows in [y_min, y_max]
                best_non_forbidden = None
                best_dist = float('inf')
                
                for y_test in range(y_min, y_max + 1):
                    if not is_forbidden[y_test]:
                        dist = abs(y_test - y_ideal)
                        if dist < best_dist:
                            best_dist = dist
                            best_non_forbidden = y_test
                            
                if best_non_forbidden is not None:
                    splits.append(best_non_forbidden)
                    y_curr = best_non_forbidden
                    continue
                    
                # Step 3: Expand search outwards to preserve panel/content integrity
                found_outward = False
                back_limit = y_curr + (min_h // 2)
                fwd_limit = min(height - 1, y_curr + int(max_h * 1.5))
                
                max_search_offset = max(y_ideal - back_limit, fwd_limit - y_ideal)
                
                # Search outward from y_ideal
                for offset in range(1, max_search_offset + 1):
                    y_back = y_ideal - offset
                    y_fwd = y_ideal + offset
                    
                    # Prefer backward split if valid and reasonable size
                    if y_back >= back_limit and y_back < height and not is_forbidden[y_back]:
                        splits.append(y_back)
                        y_curr = y_back
                        found_outward = True
                        break
                        
                    if y_fwd <= fwd_limit and y_fwd < height and not is_forbidden[y_fwd]:
                        splits.append(y_fwd)
                        y_curr = y_fwd
                        found_outward = True
                        break
                        
                if found_outward:
                    continue
                    
                # Step 4: Absolute fallback (if everything is forbidden, e.g. huge panels without borders)
                if row_complexity is not None:
                    min_comp = float('inf')
                    best_fb = y_ideal
                    for y_test in range(y_min, y_max + 1):
                        comp = row_complexity[y_test]
                        if comp < min_comp:
                            min_comp = comp
                            best_fb = y_test
                        elif comp == min_comp:
                            # Tie-breaker: choose row closer to ideal height
                            if abs(y_test - y_ideal) < abs(best_fb - y_ideal):
                                best_fb = y_test
                    splits.append(best_fb)
                    y_curr = best_fb
                else:
                    # Search for any clean row in the range [y_min, y_max] even if forbidden
                    best_fallback = None
                    best_fallback_dist = float('inf')
                    for y_test in range(y_min, y_max + 1):
                        if clean_rows[y_test]:
                            dist = abs(y_test - y_ideal)
                            if dist < best_fallback_dist:
                                best_fallback_dist = dist
                                best_fallback = y_test
                                
                    if best_fallback is not None:
                        splits.append(best_fallback)
                        y_curr = best_fallback
                    else:
                        # Last resort: just split at y_ideal
                        splits.append(y_ideal)
                        y_curr = y_ideal
                        
            return splits

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

        def get_protected_ranges(img_bgr, bg_val, tolerance):
            if img_bgr is None or img_bgr.shape[0] <= 0 or img_bgr.shape[1] <= 0:
                return []
            h_img, w_img = img_bgr.shape[:2]
            protected = []
            
            # Resize image for faster contour/OCR detection (width 400px is sweet spot)
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
                    # Use detect() instead of readtext() to bypass recognition model (4x speedup)
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
                
            # 2. Panel bounding boxes using contours with dynamic background threshold
            try:
                gray_img = cv2.cvtColor(resized_img, cv2.COLOR_BGR2GRAY)
                if bg_val > 127:
                    # Light background -> invert threshold
                    _, thresh = cv2.threshold(gray_img, bg_val - tolerance, 255, cv2.THRESH_BINARY_INV)
                else:
                    # Dark background -> direct threshold
                    _, thresh = cv2.threshold(gray_img, bg_val + tolerance, 255, cv2.THRESH_BINARY)
                
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

        async def process_episode(ep):
            if context.cancel_token.is_cancelled(): raise asyncio.CancelledError()
            await context.start_episode(ep)
            
            ep_dir = os.path.join(download_dir, f"episode_{ep}")
            images_dir = os.path.join(ep_dir, "images")
            images_pdf_dir = os.path.join(ep_dir, "images_pdf")
            debug_dir = os.path.join(ep_dir, "debug_repaging")
            
            if not os.path.exists(images_dir):
                await context.fail_episode(ep, "Không tìm thấy thư mục ảnh gốc.")
                return False
                
            # Read original images
            files = sorted([f for f in os.listdir(images_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))])
            if not files:
                await context.fail_episode(ep, "Không tìm thấy ảnh truyện tranh nào.")
                return False
                
            image_paths = [os.path.join(images_dir, f) for f in files]
            
            # Execute CPU-intensive image loading and range detection in thread pool
            loop = asyncio.get_running_loop()
            
            def process_single_slice(path):
                img = safe_cv2_imread(path)
                if img is None:
                    return None
                h, w = img.shape[:2]
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
                from concurrent.futures import ThreadPoolExecutor
                
                with ThreadPoolExecutor() as executor:
                    slice_results = list(executor.map(process_single_slice, image_paths))
                    
                total_height = 0
                offsets = []
                global_protected = []
                loaded_images = []
                bg_vals = []
                
                for res in slice_results:
                    if res is None:
                        continue
                    img = res["img"]
                    h = res["height"]
                    loaded_images.append(img)
                    bg_vals.append(res["slice_bg"])
                    
                    for ymin, ymax in res["protected"]:
                        global_protected.append((ymin + total_height, ymax + total_height))
                        
                    offsets.append({
                        "filename": res["filename"],
                        "offset_y_start": total_height,
                        "offset_y_end": total_height + h,
                        "height": h
                    })
                    total_height += h
                    
                if not loaded_images:
                    return None
                    
                global_protected = merge_ranges(global_protected)
                
                # Determine final background value (median of slices)
                final_bg_val = int(np.median(bg_vals))
                
                # Standardize canvas width using median slice width to prevent artificial side padding
                target_w = int(np.median([img.shape[1] for img in loaded_images]))
                if target_w < 400:
                    target_w = max(img.shape[1] for img in loaded_images)
                
                canvas = np.ones((total_height, target_w, 3), dtype=np.uint8) * final_bg_val
                
                current_y = 0
                for img in loaded_images:
                    h, w = img.shape[:2]
                    if w != target_w:
                        img_fitted = cv2.resize(img, (target_w, h), interpolation=cv2.INTER_AREA if w > target_w else cv2.INTER_CUBIC)
                    else:
                        img_fitted = img
                    canvas[current_y:current_y+h, :] = img_fitted
                    current_y += h
                    
                return canvas, total_height, target_w, offsets, global_protected, final_bg_val
                
            res = await loop.run_in_executor(None, run_detection_and_stitch)
            import torch
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
            
            # Row content scores calculation
            def analyze_content():
                # Downscale width to 100px for speed, keeping total_height intact!
                target_w = 100
                if max_w <= 0 or total_height <= 0:
                    return np.zeros(1), np.zeros(1)
                scale = target_w / max_w
                
                # Resize only the width
                gray_small = cv2.resize(cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY), (target_w, total_height), interpolation=cv2.INTER_NEAREST)
                canny = cv2.Canny(gray_small, canny_low, canny_high)
                
                gray_row_means = np.mean(gray_small, axis=1)
                canny_row_means = np.mean(canny, axis=1)
                
                bg_diff = np.abs(gray_row_means - final_bg_val)
                row_scores = bg_diff + canny_row_means
                
                # Smooth signal
                w_size = 101
                kernel = np.ones(w_size) / w_size
                smoothed_scores = np.convolve(row_scores, kernel, mode='same')
                return row_scores, smoothed_scores
                
            row_scores, smoothed_scores = await loop.run_in_executor(None, analyze_content)
            
            # Define target height
            target_height = task.payload.get("repage_target_height", int((min_height + max_height) // 2))
            
            # Find optimal splits
            gray_canvas = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY)
            clean_rows = get_clean_rows(gray_canvas, final_bg_val, tol=tolerance, bg_threshold=bg_threshold)
            
            # Build global forbidden mask from global protected ranges
            is_forbidden = np.zeros(total_height, dtype=bool)
            for p_start, p_end in global_protected:
                # apply padding
                start = max(0, p_start - forbidden_padding)
                end = min(total_height - 1, p_end + forbidden_padding)
                is_forbidden[start:end + 1] = True
                
            # Un-forbid clean background rows
            is_forbidden = is_forbidden & ~clean_rows
            
            cuts = optimize_splits(
                total_height, 
                clean_rows, 
                is_forbidden, 
                target_height, 
                min_height, 
                max_height, 
                row_complexity=row_scores
            )
            
            # Export and overwrite pages
            os.makedirs(debug_dir, exist_ok=True)
            os.makedirs(images_pdf_dir, exist_ok=True)
            
            def export_pages_and_visualizations():
                # Re-pagination is derived output; keep original crawl images immutable.
                for f_name in os.listdir(images_pdf_dir):
                    f_path = os.path.join(images_pdf_dir, f_name)
                    if os.path.isfile(f_path):
                        try:
                            os.remove(f_path)
                        except Exception:
                            pass
                
                from moderation_utils import is_junk_or_title_page
                
                def find_content_range(slice_img, pad=10):
                    h, w = slice_img.shape[:2]
                    if h <= 2 * pad:
                        return 0, h
                    
                    gray = cv2.cvtColor(slice_img, cv2.COLOR_BGR2GRAY)
                    canny = cv2.Canny(gray, 30, 100)
                    edge_proj = np.sum(canny > 0, axis=1)
                    row_vars = np.var(gray, axis=1)
                    
                    top_med = np.median(gray[:min(10, h), :])
                    bot_med = np.median(gray[max(0, h-10):, :])
                    row_diff_top = np.abs(np.mean(gray, axis=1) - top_med)
                    row_diff_bot = np.abs(np.mean(gray, axis=1) - bot_med)
                    
                    min_edge_pixels = max(8, int(w * 0.01))
                    
                    is_content = np.zeros(h, dtype=bool)
                    for y in range(h):
                        has_edges = edge_proj[y] >= min_edge_pixels
                        has_variance = row_vars[y] >= 120.0
                        is_different_bg = (row_diff_top[y] >= 15.0) or (row_diff_bot[y] >= 15.0)
                        
                        if has_edges or has_variance or (is_different_bg and row_vars[y] >= 10.0):
                            is_content[y] = True
                            
                    cleaned_content = np.copy(is_content)
                    for y in range(h):
                        if is_content[y]:
                            w_start = max(0, y - 2)
                            w_end = min(h - 1, y + 2)
                            if np.sum(is_content[w_start:w_end+1]) < 2:
                                cleaned_content[y] = False
                                
                    y_top = 0
                    for y in range(h):
                        if cleaned_content[y]:
                            y_top = y
                            break
                            
                    y_bottom = h
                    for y in range(h - 1, -1, -1):
                        if cleaned_content[y]:
                            y_bottom = y + 1
                            break
                            
                    # Apply safety padding
                    y_top = max(0, y_top - pad)
                    y_bottom = min(h, y_bottom + pad)
                    
                    if y_top >= y_bottom or (y_bottom - y_top) < 100:
                        return 0, h
                        
                    return y_top, y_bottom

                # Export new pages (Clear old files in directory first)
                if os.path.exists(images_pdf_dir):
                    for old_f in os.listdir(images_pdf_dir):
                        try:
                            os.remove(os.path.join(images_pdf_dir, old_f))
                        except Exception:
                            pass
                else:
                    os.makedirs(images_pdf_dir, exist_ok=True)

                new_pages = []
                page_counter = 0
                skipped_count = 0
                
                write_tasks = []
                for i in range(len(cuts) - 1):
                    y_start = cuts[i]
                    y_end = cuts[i+1]
                    slice_img = canvas[y_start:y_end, :]
                    
                    if skip_blank:
                        is_junk_raw, _ = is_junk_or_title_page(slice_img, bg_val=final_bg_val, tol=tolerance)
                        if is_junk_raw:
                            skipped_count += 1
                            continue
                        
                    # Calculate content boundaries to crop unnecessary whitespace from top and bottom
                    pad_val = task.payload.get("repage_crop_padding", 10)
                    y_top, y_bottom = find_content_range(slice_img, pad=pad_val)
                    
                    # Apply crop to image slice
                    cropped_slice = slice_img[y_top:y_bottom, :]
                    
                    if skip_blank:
                        is_junk_cropped, _ = is_junk_or_title_page(cropped_slice, bg_val=final_bg_val, tol=tolerance)
                        if is_junk_cropped:
                            skipped_count += 1
                            continue
                    
                    page_counter += 1
                    new_filename = f"{page_counter:03d}.webp"
                    new_path = os.path.join(images_pdf_dir, new_filename)
                    
                    write_tasks.append((new_path, cropped_slice))
                    
                    y_crop_start = y_start + y_top
                    y_crop_end = y_start + y_bottom
                    
                    sources = []
                    for offset in offsets:
                        o_start = max(y_crop_start, offset["offset_y_start"])
                        o_end = min(y_crop_end, offset["offset_y_end"])
                        if o_start < o_end:
                            src_y_start = o_start - offset["offset_y_start"]
                            src_y_end = o_end - offset["offset_y_start"]
                            tgt_y_start = o_start - y_crop_start
                            tgt_y_end = o_end - y_crop_start
                            
                            sources.append({
                                "filename": offset["filename"],
                                "source_y_start": int(src_y_start),
                                "source_y_end": int(src_y_end),
                                "target_y_start": int(tgt_y_start),
                                "target_y_end": int(tgt_y_end)
                            })
                            
                    new_pages.append({
                        "filename": new_filename,
                        "height": y_bottom - y_top,
                        "cut_y_start": int(y_crop_start),
                        "cut_y_end": int(y_crop_end),
                        "sources": sources
                    })
                    
                # Write metadata
                metadata = {
                    "source_images": offsets,
                    "output_pages": new_pages
                }
                with open(os.path.join(debug_dir, "repaging_metadata.json"), "w", encoding="utf-8") as mf:
                    json.dump(metadata, mf, ensure_ascii=False, indent=2)
                    
                # Generate content plot
                try:
                    plt.figure(figsize=(12, 6))
                    plt.plot(smoothed_scores, label="Smoothed Content Score")
                    for cut in cuts[1:-1]:
                        plt.axvline(x=cut, color='r', linestyle='--', alpha=0.8, label="Cut Line" if cut == cuts[1] else "")
                    plt.title(f"Episode {ep} Repagination Content Profile")
                    plt.xlabel("Row Pixel Index")
                    plt.ylabel("Activity Score")
                    plt.legend()
                    plt.tight_layout()
                    
                    plot_path = os.path.join(debug_dir, "content_profile.png")
                    plt.savefig(plot_path, dpi=150)
                    plt.close()
                except Exception:
                    pass
                    
                # Generate downscaled overlay
                try:
                    scale_factor = 0.1
                    overlay_w = max(1, int(max_w * scale_factor))
                    overlay_h = max(1, int(total_height * scale_factor))
                    small_canvas = cv2.resize(canvas, (overlay_w, overlay_h), interpolation=cv2.INTER_AREA)
                    for cut in cuts[1:-1]:
                        scaled_cut = int(cut * scale_factor)
                        cv2.line(small_canvas, (0, scaled_cut), (overlay_w, scaled_cut), (0, 0, 255), 2)
                    safe_cv2_imwrite(os.path.join(debug_dir, "cut_line_overlay.jpg"), small_canvas)
                except Exception:
                    pass
                    
                # Parallel WebP page writes
                from concurrent.futures import ThreadPoolExecutor
                def save_webp(task_tuple):
                    path, img = task_tuple
                    safe_cv2_imwrite(path, img, [cv2.IMWRITE_WEBP_QUALITY, 80])
                    
                with ThreadPoolExecutor() as executor:
                    executor.map(save_webp, write_tasks)
                    
                return skipped_count
                
            skipped_count = await loop.run_in_executor(None, export_pages_and_visualizations)
            
            if skipped_count > 0:
                await context.log(f"Tập {ep}: Phát hiện và loại bỏ {skipped_count} trang không có nội dung.", "warning")
            await context.log(f"Tập {ep}: Hoàn thành phân trang thông minh thành công.", "success")
            await context.complete_episode(ep)
            return True

        for idx, ep in enumerate(range(from_ep, to_ep + 1)):
            ep_dir = os.path.join(download_dir, f"episode_{ep}")
            images_dir = os.path.join(ep_dir, "images")
            images_pdf_dir = os.path.join(ep_dir, "images_pdf")
            repag_meta = os.path.join(ep_dir, "debug_repaging", "repaging_metadata.json")
            cache = EpisodeStageCache(ep_dir)
            fingerprint = stage_fingerprint(
                task,
                "repagination",
                ep,
                input_paths=[images_dir],
                extra={
                    "min_height": min_height,
                    "max_height": max_height,
                    "canny_low": canny_low,
                    "canny_high": canny_high,
                    "tolerance": tolerance,
                    "bg_threshold": bg_threshold,
                    "min_panel_h": min_panel_h,
                    "forbidden_padding": forbidden_padding,
                    "skip_blank": skip_blank,
                    "use_ocr": use_ocr,
                },
            )
            if cache.is_current(
                stage="repagination",
                fingerprint=fingerprint,
                outputs=[images_pdf_dir, repag_meta],
                validate=lambda: os.path.isfile(repag_meta) and os.path.isdir(images_pdf_dir),
            ):
                await context.log(f"Tập {ep}: Đã hoàn thành trước đó. Bỏ qua phân trang thông minh.", "success")
                await context.start_episode(ep)
                await context.complete_episode(ep)
                await context.update_stage_progress(self.name, ((idx + 1) / total_episodes) * 100.0)
                continue
                
            success = await process_episode(ep)
            if not success:
                return False
            try:
                cache.commit(stage="repagination", fingerprint=fingerprint, outputs=[images_pdf_dir, repag_meta])
            except FileNotFoundError as exc:
                await context.fail_episode(ep, str(exc))
                return False
            await context.update_stage_progress(self.name, ((idx + 1) / total_episodes) * 100.0)
            
        return True
