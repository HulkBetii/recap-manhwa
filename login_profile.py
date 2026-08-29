import asyncio
import os
import sys
import json
import argparse
from playwright.async_api import async_playwright

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
PROFILES_DIR = os.path.join(PROJECT_ROOT, "Profiles")

def get_profile_path(profile_id: int) -> str:
    prof_name = f"Profile_{profile_id}"
    prof_path = os.path.join(PROFILES_DIR, prof_name)
    os.makedirs(prof_path, exist_ok=True)
    return prof_path

async def login_profile(profile_id: int):
    user_data_dir = get_profile_path(profile_id)
    print("=" * 60)
    print(f">>> DANG KHOI CHAY CHROME CHO PROFILE {profile_id}")
    print(f">>> Thu muc luu tru: {user_data_dir}")
    print("=" * 60)
    print("HUONG DAN:")
    print(f"1. Cua so Chrome se tu dong mo trang Google Gemini (https://gemini.google.com/app).")
    print(f"2. Ban hay tien hanh dang nhap tai khoan Google cua Profile {profile_id}.")
    print(f"3. Sau khi dang nhap thanh cong va nhin thay giao dien Gemini, ban chi can DONG CUA SO CHROME lai.")
    print(f"4. Session va cookies cua Profile {profile_id} se duoc luu tu dong.")
    print("=" * 60)

    # Clean lock files
    for lock_name in ["SingletonLock", "lock", "SingletonCookie", "SingletonSocket"]:
        for root, dirs, files in os.walk(user_data_dir):
            if lock_name in files:
                try:
                    os.remove(os.path.join(root, lock_name))
                except Exception:
                    pass

    async with async_playwright() as p:
        launch_args = [
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--start-maximized",
        ]

        try:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                channel="chrome",
                headless=False,
                no_viewport=True,
                args=launch_args,
                permissions=["clipboard-read", "clipboard-write"],
            )
        except Exception:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,
                no_viewport=True,
                args=launch_args,
                permissions=["clipboard-read", "clipboard-write"],
            )

        page = await context.new_page()
        print("\n>>> Dang chuyen huong toi https://gemini.google.com/app ...")
        try:
            await page.goto("https://gemini.google.com/app", timeout=60000)
        except Exception as e:
            print(f"Luu y khi mo trang: {e}")

        # Wait until browser/page is closed by user
        closed_event = asyncio.Event()
        context.on("close", lambda: closed_event.set())
        page.on("close", lambda p: closed_event.set())

        print("\n>>> Trinh duyet da san sang! Hay dang nhap tren Chrome va dong trinh duyet khi xong.")
        await closed_event.wait()

        # Update config.json
        config_file = os.path.join(PROJECT_ROOT, "config.json")
        config = {}
        if os.path.exists(config_file):
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception:
                config = {}
        
        profiles = config.get("chrome_profiles", [])
        target_default_path = os.path.join(user_data_dir, "Default")
        if target_default_path not in profiles:
            profiles.append(target_default_path)
            
        config["chrome_profiles"] = profiles
        try:
            config["current_profile_index"] = profiles.index(target_default_path)
        except ValueError:
            config["current_profile_index"] = 0
            
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

        print("\n" + "=" * 60)
        print(f">>> DA LUU PROFILE {profile_id} THANH CONG VAO HE THONG!")
        print("=" * 60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dang nhap Chrome Profile cho Gemini")
    parser.add_argument("--profile", type=int, default=1, help="So thu tu Profile (vi du: 1, 2, 3, 4...)")
    args = parser.parse_args()
    asyncio.run(login_profile(args.profile))

