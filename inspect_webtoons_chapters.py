import urllib.request
import re

url = "https://www.webtoons.com/en/thriller/surviving-the-apocalypse/list?title_no=6678"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

for page in range(1, 7):
    p_url = f"{url}&page={page}"
    req = urllib.request.Request(p_url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        html = resp.read().decode("utf-8")
    
    items = re.findall(r'<li[^>]*data-episode-no=["\'](\d+)["\'][^>]*>(.*?)</li>', html, re.DOTALL)
    for ep, content in items:
        is_locked = any(k in content.lower() for k in ["ico_lock", "ico_fast", "ico_coin", "lock", "preview"])
        subj_match = re.search(r'<span class="subj"><span>(.*?)</span>', content)
        subj = subj_match.group(1) if subj_match else "N/A"
        date_match = re.search(r'<span class="date">(.*?)</span>', content)
        date = date_match.group(1) if date_match else "N/A"
        print(f"Ep {ep:>2}: {subj:<30} | Date: {date} | Locked: {is_locked}")
