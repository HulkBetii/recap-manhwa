"""Unit tests for updated plan_camera_motion() camera motion logic.

Strategy: Extract only the camera-motion helper functions and plan_camera_motion
from workflow_stages_2.py using line-range slicing, avoiding all heavy imports.
"""
import sys, types, math, enum, pathlib, importlib, re

# ─── Stubs ────────────────────────────────────────────────────────────────────
import numpy as np

for mod_name in [
    'cv2', 'config',
    'recap_schema', 'artifact_cache', 'tts_settings', 'moderation_utils',
    'workflow_stages_1', 'app',
]:
    sys.modules.setdefault(mod_name, types.ModuleType(mod_name))

# PIL stub with sub-modules
pil = types.ModuleType('PIL')
for sub in ['Image', 'ImageDraw', 'ImageFilter', 'ImageEnhance']:
    m = types.ModuleType(f'PIL.{sub}')
    setattr(pil, sub, m)
    sys.modules[f'PIL.{sub}'] = m
sys.modules['PIL'] = pil

# workflow_base stub with all needed symbols
wb = types.ModuleType('workflow_base')
class BaseStage: pass
class WorkflowContext: pass
class StageState(enum.Enum):
    PENDING = 'pending'; RUNNING = 'running'; DONE = 'done'; FAILED = 'failed'
wb.BaseStage = BaseStage
wb.WorkflowContext = WorkflowContext
wb.StageState = StageState
wb.check_episode_completed = lambda *a, **kw: False
sys.modules['workflow_base'] = wb

# artifact_cache stub attrs
ac = sys.modules['artifact_cache']
ac.EpisodeStageCache = object
ac.stage_fingerprint = lambda *a, **kw: ''
ac.validate_mp4_file = lambda *a: False
ac.validate_nonempty_file = lambda *a: False
ac.validate_srt_file = lambda *a: False

# moderation_utils stub
mu = sys.modules['moderation_utils']
mu.MODERATION_MODEL_VERSION = '1'
mu.MODERATION_PROMPT_VERSION = '1'
mu.list_image_files = lambda *a, **kw: []
mu.prepare_moderated_directory = lambda *a, **kw: None
mu.selected_file_names = lambda *a, **kw: []
mu.selected_page_numbers = lambda *a, **kw: []

# tts_settings stub
ts = sys.modules['tts_settings']
ts.normalize_tts_voice_mode = lambda *a, **kw: None

# recap_schema stub
rs = sys.modules['recap_schema']
rs.load_recap_dicts = lambda *a, **kw: {}

# cv2 stub — only need IMREAD_COLOR constant
cv2_stub = sys.modules['cv2']
cv2_stub.IMREAD_COLOR = 1

# ─── Import module ─────────────────────────────────────────────────────────────
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import workflow_stages_2 as ws2

planner = ws2.CameraPlanner()
plan_camera_motion = planner.generate_camera_plan

# ─── Test fixtures ─────────────────────────────────────────────────────────────
BOUNDS_TALL = (0, 0, 800, 2400)   # aspect=0.333 — siêu dài
BOUNDS_MED  = (0, 0, 800, 1400)   # aspect=0.571 — vừa  (0.55 < ar < 0.72)
BOUNDS_STD  = (0, 0, 800,  900)   # aspect=0.889 — chuẩn
DUR = 4.0

failures = []

def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        msg = f"  FAIL  {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)
        failures.append(name)

# ─── TEST 1: Ảnh siêu dài → Mode B ────────────────────────────────────────────
print("=== TEST 1: Ảnh siêu dài → vertical_pan_glide ===")
p1 = plan_camera_motion(1, DUR, BOUNDS_TALL, transition='cross_fade')
check("animation_type=vertical_pan_glide",
      p1['animation_type'] == 'vertical_pan_glide', p1['animation_type'])
kf1 = p1['keyframes']
check("3 keyframes",       len(kf1) == 3, str(len(kf1)))
check("start scale=1.00",  abs(kf1[0]['scale'] - 1.00) < 0.001)
check("mid   scale=1.03",  abs(kf1[1]['scale'] - 1.03) < 0.001, str(kf1[1]['scale']))
check("end   scale=1.00",  abs(kf1[2]['scale'] - 1.00) < 0.001)
check("mid time ≈ dur/2",  abs(kf1[1]['time'] - DUR * 0.5) < 0.01)

# ─── TEST 2: Ảnh vừa (ngưỡng 80px mới) → Mode B ──────────────────────────────
print("\n=== TEST 2: Ảnh vừa (aspect 0.571) → vertical_pan_glide ===")
p2 = plan_camera_motion(1, DUR, BOUNDS_MED, transition='cross_fade')
check("animation_type=vertical_pan_glide",
      p2['animation_type'] == 'vertical_pan_glide', p2['animation_type'])
kf2 = p2['keyframes']
check("3 keyframes",      len(kf2) == 3, str(len(kf2)))
check("mid scale=1.03",   abs(kf2[1]['scale'] - 1.03) < 0.001, str(kf2[1]['scale']))

# ─── TEST 3: focal_zoom_in end scale 1.08 ─────────────────────────────────────
print("\n=== TEST 3: focal_zoom_in → end scale=1.08 ===")
p3 = plan_camera_motion(1, DUR, BOUNDS_STD, transition='cross_fade', shot_index=0)
check("animation_type=focal_zoom_in",
      p3['animation_type'] == 'focal_zoom_in', p3['animation_type'])
check("end scale=1.08",
      abs(p3['keyframes'][-1]['scale'] - 1.08) < 0.001, str(p3['keyframes'][-1]['scale']))

# ─── TEST 4: focal_zoom_out start scale 1.08 ──────────────────────────────────
print("\n=== TEST 4: focal_zoom_out → start scale=1.08 ===")
p4 = plan_camera_motion(1, DUR, BOUNDS_STD, transition='cross_fade', shot_index=1)
check("animation_type=focal_zoom_out",
      p4['animation_type'] == 'focal_zoom_out', p4['animation_type'])
check("start scale=1.08",
      abs(p4['keyframes'][0]['scale'] - 1.08) < 0.001, str(p4['keyframes'][0]['scale']))

# ─── TEST 5: action_punch_zoom end scale 1.08 ─────────────────────────────────
print("\n=== TEST 5: action_punch_zoom → end scale=1.08 ===")
p5 = plan_camera_motion(1, DUR, BOUNDS_STD, transition='cross_fade', shot_index=2)
check("animation_type=action_punch_zoom",
      p5['animation_type'] == 'action_punch_zoom', p5['animation_type'])
check("end scale=1.08",
      abs(p5['keyframes'][-1]['scale'] - 1.08) < 0.001, str(p5['keyframes'][-1]['scale']))

# ─── TEST 6: dual_zone_ken_burns giữ nguyên peak 1.15 ─────────────────────────
print("\n=== TEST 6: dual_zone_ken_burns (has_char, dur>=5) peak=1.15 (GIỮ NGUYÊN) ===")
p6 = plan_camera_motion(1, 6.0, BOUNDS_STD, transition='cross_fade', shot_index=0,
                         skin_ratio=0.15, character_presence=70.0)
check("animation_type=dual_zone_ken_burns",
      p6['animation_type'] == 'dual_zone_ken_burns', p6['animation_type'])
peak6 = max(kf['scale'] for kf in p6['keyframes'])
check("peak scale=1.15", abs(peak6 - 1.15) < 0.001, str(peak6))

# ─── TEST 7: dual_shot_cinematic (dur>7s) peak 1.08 ──────────────────────────
print("\n=== TEST 7: dual_shot_cinematic (dur>7s) peak=1.08 ===")
p7 = plan_camera_motion(1, 8.0, BOUNDS_STD, transition='cross_fade', shot_index=1)
check("animation_type=dual_shot_cinematic",
      p7['animation_type'] == 'dual_shot_cinematic', p7['animation_type'])
peak7 = max(kf['scale'] for kf in p7['keyframes'])
check("peak scale=1.08", abs(peak7 - 1.08) < 0.001, str(peak7))

# ─── Summary ──────────────────────────────────────────────────────────────────
print()
if failures:
    print(f"FAILED {len(failures)} test(s): {failures}")
    sys.exit(1)
else:
    print("All 7 tests PASSED ✓")
