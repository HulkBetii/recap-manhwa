# -*- coding: utf-8 -*-
import asyncio
import os
import sys

# Ensure UTF-8 output on Windows console
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

from playwright.async_api import async_playwright

PROFILES = [
    (1, r"C:\Data\Profile 1"),
    (2, r"C:\Data\Profile 2"),
    (3, r"C:\Data\Profile 3"),
    (4, r"C:\Data\Profile 4"),
    (5, r"C:\Data\Profile 5"),
]

async def check_single_profile(idx: int, profile_path: str, playwright) -> dict:
    result = {
        "index": idx,
        "path": profile_path,
        "exists": os.path.exists(profile_path),
        "logged_in": False,
        "user_email": None,
        "cookies_count": 0,
        "details": ""
    }
    
    if not result["exists"]:
        result["details"] = "Thu muc khong ton tai"
        return result

    try:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=profile_path,
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ]
        )
        
        # Check cookies
        cookies = await context.cookies("https://google.com")
        result["cookies_count"] = len(cookies)
        cookie_names = {c["name"] for c in cookies}
        has_auth_cookies = any(k in cookie_names for k in ["SID", "__Secure-1PSID", "__Secure-3PSID", "SAPISID", "SSID", "HSID"])
        
        page = await context.new_page()
        try:
            resp = await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded", timeout=12000)
            await asyncio.sleep(2.0)
            
            curr_url = page.url
            
            # Check if redirected to login page
            is_login_page = "accounts.google.com" in curr_url or "signin" in curr_url.lower()
            
            # Check for chat input element or prompt box
            has_input_box = await page.evaluate("""() => {
                const el = document.querySelector('div[contenteditable="true"], textarea, rich-textarea, .ql-editor');
                return el !== null;
            }""")
            
            # Try to get account email/avatar if available
            account_label = await page.evaluate("""() => {
                const btn = document.querySelector('button[aria-label*="@"], a[aria-label*="@"], button[aria-label*="Google Account"], a[aria-label*="Tài khoản Google"]');
                return btn ? btn.getAttribute('aria-label') : null;
            }""")
            
            if (not is_login_page) and (has_auth_cookies or has_input_box):
                result["logged_in"] = True
                result["details"] = f"Da dang nhap Gemini (Cookies: {len(cookies)})"
                if account_label:
                    result["user_email"] = account_label
            else:
                result["logged_in"] = False
                result["details"] = "Chua dang nhap (Trang yeu cau Sign In)"
        except Exception as nav_err:
            if has_auth_cookies:
                result["logged_in"] = True
                result["details"] = f"Da co auth cookies ({len(cookies)} cookies)"
            else:
                result["logged_in"] = False
                result["details"] = f"Chua dang nhap ({nav_err})"
        finally:
            await context.close()
            
    except Exception as err:
        result["details"] = f"Loi khoi chay context: {err}"
        
    return result

async def main():
    print("=" * 70)
    print("       CHECK TRANG THAI DANG NHAP 5 CHROME PROFILES")
    print("=" * 70)
    
    results = []
    async with async_playwright() as playwright:
        for idx, path in PROFILES:
            print(f"[*] Dang kiem tra Profile {idx}...")
            res = await check_single_profile(idx, path, playwright)
            results.append(res)
            status_text = "[DA DANG NHAP]" if res["logged_in"] else "[CHUA DANG NHAP]"
            print(f"    -> Profile {idx}: {status_text}")
            print(f"       Chi tiet : {res['details']}")
            if res["user_email"]:
                print(f"       Tai khoan: {res['user_email']}")
            print("-" * 70)
            
    print("\n" + "=" * 70)
    print("                      BANG TONG HOP KET QUA")
    print("=" * 70)
    print(f"{'Profile':<12} | {'Trang Thai':<18} | {'Cookies':<10} | {'Chi Tiet':<30}")
    print("-" * 70)
    for r in results:
        status_str = "Da dang nhap" if r["logged_in"] else "Chua dang nhap"
        print(f"Profile {r['index']:<4} | {status_str:<18} | {r['cookies_count']:<10} | {r['details']:<30}")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(main())
