import json, os

ep1_dir = 'downloads/veteran_of_the_apocalypse_1_2_vi_e826e8f9/episode_1'
recap_path = os.path.join(ep1_dir, 'recap.json')

with open(recap_path, 'r', encoding='utf-8') as f:
    recap = json.load(f)

for i, s in enumerate(recap[:10]):
    print(f"Seg {i+1}: imgs={s.get('images')} speech={s.get('speech')}")
