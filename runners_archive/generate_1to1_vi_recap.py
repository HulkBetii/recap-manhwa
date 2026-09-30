import os
import json
import shutil
from deep_translator import GoogleTranslator

en_dir = os.path.join("downloads", "surviving_the_apocalypse_1_2_en_947dedf7")
vi_dir = os.path.join("downloads", "surviving_the_apocalypse_1_2_vi_947dedf7")

translator = GoogleTranslator(source='en', target='vi')

for ep in [1, 2]:
    en_ep_dir = os.path.join(en_dir, f"episode_{ep}")
    vi_ep_dir = os.path.join(vi_dir, f"episode_{ep}")
    os.makedirs(vi_ep_dir, exist_ok=True)
    
    # Copy images and images_pdf to guarantee 100% visual frame match
    for sub in ["images", "images_pdf"]:
        src = os.path.join(en_ep_dir, sub)
        dst = os.path.join(vi_ep_dir, sub)
        if os.path.exists(src):
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            print(f"[COPY] Copied {sub} for episode {ep}")
            
    en_recap_path = os.path.join(en_ep_dir, "recap.json")
    vi_recap_path = os.path.join(vi_ep_dir, "recap.json")
    
    with open(en_recap_path, "r", encoding="utf-8") as f:
        en_scenes = json.load(f)
        
    print(f"Translating Episode {ep} ({len(en_scenes)} scenes)...")
    vi_scenes = []
    for idx, s in enumerate(en_scenes):
        en_speech = s.get("speech", "").strip()
        if not en_speech:
            vi_speech = ""
        else:
            try:
                vi_speech = translator.translate(en_speech)
            except Exception as e:
                print(f"  [WARN] Translation error at scene {idx}: {e}")
                vi_speech = en_speech
                
        vi_scenes.append({
            "speech": vi_speech,
            "images": s.get("images", []),
            "action_type": s.get("action_type", "pan_zoom"),
        })
        
    with open(vi_recap_path, "w", encoding="utf-8") as f:
        json.dump(vi_scenes, f, ensure_ascii=False, indent=2)
        
    print(f"[SUCCESS] Episode {ep}: Saved {len(vi_scenes)} 1:1 translated scenes to {vi_recap_path}")
