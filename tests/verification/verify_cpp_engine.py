"""
P0#3 验证：MLT C++ 引擎真正跑通
- 验证代理层
- 端到端多片段工作流
"""
import sys
import os
import subprocess

sys.path.insert(0, 'app/core/video_processing')

# ===== STEP 1: 引擎代理层验证 =====
from mlt_engine_cpp import (
    is_mlt_cpp_available,
    is_video_engine_cpp_available,
    CppEngineProxy,
    get_video_engine,
)

print('=' * 60)
print('STEP 1: 引擎代理层验证')
print('=' * 60)
print(f'[1] 原生 MLT 可用: {is_mlt_cpp_available()}')
print(f'[2] 视频引擎可用(MLT+cpp): {is_video_engine_cpp_available()}')

eng = get_video_engine()
print(f'[3] 代理 backend: {eng.backend}')
print(f'[4] 代理 available: {eng.available}')

# ===== STEP 2: 端到端多片段工作流 =====
os.makedirs('app/temp', exist_ok=True)

# 生成两个测试源
src1 = 'app/temp/e2e_src1.mp4'
src2 = 'app/temp/e2e_src2.mp4'
for f, color in [(src1, 'red'), (src2, 'blue')]:
    if not os.path.exists(f):
        subprocess.run(
            ['ffmpeg', '-y', '-f', 'lavfi', '-i',
             f'color=c={color}:size=320x240:duration=2:rate=30',
             '-pix_fmt', 'yuv420p', f],
            capture_output=True
        )

print()
print('=' * 60)
print('STEP 2: 端到端多片段工作流')
print('=' * 60)

# 2.1 分析
info1 = eng.analyze_video(src1)
if info1:
    print(f'[2.1] src1 分析: {info1.width}x{info1.height} {info1.duration:.1f}s')
else:
    print('[2.1] src1 分析: FAIL')

# 2.2 剪辑
clipped = 'app/temp/e2e_clipped.mp4'
if os.path.exists(clipped):
    os.remove(clipped)
eng.clip_video(src1, clipped, start_time=0.3, duration=1.2)
clip_ok = os.path.exists(clipped) and os.path.getsize(clipped) > 0
print(f'[2.2] 剪辑: {"OK" if clip_ok else "FAIL"} ({os.path.getsize(clipped) if clip_ok else 0} bytes)')

# 2.3 水印
wmarked = 'app/temp/e2e_wmarked.mp4'
if os.path.exists(wmarked):
    os.remove(wmarked)
ok = eng.add_watermark(clipped, wmarked, 'AI Drama Editor', font_size=20, color='white')
wm_ok = ok and os.path.exists(wmarked)
print(f'[2.3] 水印: {"OK" if wm_ok else "FAIL"} ({os.path.getsize(wmarked) if wm_ok else 0} bytes)')

# 2.4 GPU 编码器
gpu = eng.detect_gpu_encoder()
print(f'[2.4] GPU 编码器: {gpu or "无（CPU libx264 兜底）"}')

# 2.5 性能统计
stats = eng.get_last_stats()
if stats:
    print(f'[2.5] 性能: {stats.frames_processed} 帧, {stats.fps_processed:.1f} fps, 耗时 {stats.processing_time:.2f}s')

# 2.6 缩略图
thumbs = eng.extract_thumbnails(src1, 4, 'app/temp/e2e_thumbs', width=160, height=90)
print(f'[2.6] 缩略图: {len(thumbs)} 张')

# 2.7 多片段合并
print()
print('=' * 60)
print('STEP 3: 多片段合并（核心剪辑能力）')
print('=' * 60)
from cpp_engine import ClipSegment, ExportConfig

def make_clip(source_path, start_time, end_time, position):
    """ClipSegment 默认无参构造，需逐字段 setattr（pybind11 限制）"""
    c = ClipSegment()
    c.source_path = source_path
    c.start_time = start_time
    c.end_time = end_time
    c.position = position
    return c

clips = [
    make_clip(os.path.abspath(src1), 0, 1.5, 0),
    make_clip(os.path.abspath(src2), 0.2, 1.8, 1.5),
    make_clip(os.path.abspath(clipped), 0, 1.0, 3.0),
]
merged = os.path.abspath('app/temp/e2e_merged.mp4')
if os.path.exists(merged):
    os.remove(merged)

cfg = ExportConfig()
cfg.codec = gpu or 'libx264'
cfg.preset = 'ultrafast'
cfg.bitrate = 1000000

result = eng.merge_clips(clips, merged, cfg)
merge_ok = result and getattr(result, 'success', False) and os.path.exists(merged)
print(f'[3.1] 合并 {len(clips)} 段 -> {merged}: {"OK" if merge_ok else "FAIL"}')
if merge_ok:
    print(f'      输出大小: {os.path.getsize(merged)} bytes')

# ===== STEP 4: 文件清单 =====
print()
print('=' * 60)
print('STEP 4: 端到端产出文件')
print('=' * 60)
files = [
    src1, src2, clipped, wmarked, merged,
] + thumbs
all_ok = True
for f in files:
    if os.path.exists(f):
        print(f'  OK  {f} ({os.path.getsize(f)} bytes)')
    else:
        print(f'  --  {f} (未生成)')
        all_ok = all_ok and (f in [src1, src2])  # 源文件允许已存在

print()
print('=' * 60)
if clip_ok and wm_ok and merge_ok:
    print('结论: C++ 引擎真正跑通，端到端工作流全绿')
else:
    print('结论: 部分步骤失败，需排查')
print('=' * 60)
