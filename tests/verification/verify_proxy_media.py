"""
P0#1 验证：代理媒体端到端跑通
- 智能判定
- 同步生成
- 缓存命中
- LRU 清理
- 异步生成
"""
import sys
import os
import time
import subprocess

sys.path.insert(0, r"d:\本地磁盘(当前分区)(C)\Users\Administrator\Desktop\AI短剧编辑器2\app\core")

from proxy_media import (
    ProxyMediaManager,
    ProxyStrategy,
    ProxyConfig,
    get_proxy_manager,
)

print("=" * 60)
print("P0#1 代理媒体端到端验证")
print("=" * 60)

# ===== STEP 1: 准备源（高分辨率以触发代理策略）=====
# 2026-10-10 T1：app/temp 已迁出产品树，临时产物改钉 .workbuddy/tmp
_TEMP_DIR = os.path.join('.workbuddy', 'tmp')
os.makedirs(_TEMP_DIR, exist_ok=True)
src = os.path.abspath(os.path.join(_TEMP_DIR, 'proxy_src.mp4'))
if not os.path.exists(src):
    print(f"[生成] 高分辨率源: {src}")
    subprocess.run([
        'ffmpeg', '-y',
        '-f', 'lavfi', '-i', f'color=c=green:size=1920x1080:duration=3:rate=30',
        '-f', 'lavfi', '-i', 'sine=frequency=440:duration=3:sample_rate=44100',
        '-pix_fmt', 'yuv420p',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-b:v', '8000k',
        '-c:a', 'aac', '-shortest',
        src,
    ], capture_output=True)

src_size = os.path.getsize(src)
print(f"[1] 源文件: {src} ({src_size} bytes)")

# ===== STEP 2: 智能判定 =====
mgr = get_proxy_manager(strategy=ProxyStrategy.AUTO)
print()
print("=" * 60)
print("STEP 2: 智能判定 (AUTO 策略)")
print("=" * 60)
should = mgr.should_generate_proxy(src, width=1920, height=1080, bitrate_kbps=8000)
print(f"[2.1] 1920x1080 @ 8Mbps → 需要代理: {should} (预期 True)")

should2 = mgr.should_generate_proxy(src, width=1280, height=720, bitrate_kbps=3000)
print(f"[2.2] 1280x720  @ 3Mbps → 需要代理: {should2} (预期 False)")

# ===== STEP 3: 同步生成代理 =====
print()
print("=" * 60)
print("STEP 3: 同步生成代理")
print("=" * 60)
proxy_path = mgr.get_proxy_path(src)
print(f"[3.0] 代理路径: {proxy_path}")
if os.path.exists(proxy_path):
    os.remove(proxy_path)
print(f"[3.1] 代理已存在: {mgr.has_proxy(src)} (预期 False)")

ok = mgr.generate_sync(src)
print(f"[3.2] 生成结果: {ok}")
print(f"[3.3] 代理已存在: {mgr.has_proxy(src)} (预期 True)")
print(f"[3.4] 代理大小: {os.path.getsize(proxy_path) if os.path.exists(proxy_path) else 0} bytes")

# ===== STEP 4: 状态查询 =====
print()
print("=" * 60)
print("STEP 4: 状态查询")
print("=" * 60)
st = mgr.get_status(src)
print(f"[4.1] status: {st['status']}")
print(f"[4.2] progress: {st['progress']}")
print(f"[4.3] proxy_path: {os.path.basename(st['proxy_path'])}")

# ===== STEP 5: 缓存统计 =====
print()
print("=" * 60)
print("STEP 5: 缓存统计")
print("=" * 60)
cached = mgr.list_cached()
print(f"[5.1] 缓存文件数: {len(cached)}")
print(f"[5.2] 缓存总大小: {mgr.get_cache_size_mb():.2f} MB")

# ===== STEP 6: 异步生成 =====
print()
print("=" * 60)
print("STEP 6: 异步生成 (后台线程)")
print("=" * 60)
src2 = os.path.abspath(os.path.join(_TEMP_DIR, 'proxy_src2.mp4'))
if not os.path.exists(src2):
    subprocess.run([
        'ffmpeg', '-y',
        '-f', 'lavfi', '-i', 'color=c=yellow:size=1920x1080:duration=2:rate=30',
        '-pix_fmt', 'yuv420p',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-b:v', '6000k',
        src2,
    ], capture_output=True)

done_flag = [False]
def on_done(ok, path):
    done_flag[0] = True
    print(f"[6.1] 异步回调: ok={ok}, size={os.path.getsize(path) if os.path.exists(path) else 0}")

t = mgr.generate_async(src2, on_done=on_done)
t.join(timeout=20)
print(f"[6.2] 异步完成: {done_flag[0]}, 代理存在: {mgr.has_proxy(src2)}")

# ===== STEP 7: LRU 清理 =====
print()
print("=" * 60)
print("STEP 7: LRU 缓存清理")
print("=" * 60)
before = mgr.list_cached()
print(f"[7.1] 清理前文件数: {len(before)}")
deleted = mgr.clear_cache_lru(keep_mb=0.001)  # 强制清空
after = mgr.list_cached()
print(f"[7.2] 清理后文件数: {len(after)} (删除 {deleted} 个)")

# ===== STEP 8: 重新生成验证（验证缓存清理后可重建）=====
print()
print("=" * 60)
print("STEP 8: 清理后重新生成（验证流程闭环）")
print("=" * 60)
print(f"[8.1] 清理后 has_proxy: {mgr.has_proxy(src)} (预期 False)")
ok2 = mgr.generate_sync(src)
print(f"[8.2] 重新生成: {ok2}")
print(f"[8.3] 再次 has_proxy: {mgr.has_proxy(src)} (预期 True)")

# ===== 结论 =====
print()
print("=" * 60)
all_ok = (
    should           # 高码率需要代理
    and not should2  # 低码率不需要
    and mgr.has_proxy(src)  # 重新生成成功
    and done_flag[0]        # 异步回调成功
)
if all_ok:
    print("结论: P0#1 代理媒体端到端跑通 ✓")
else:
    print("结论: 部分失败，需排查")
print("=" * 60)
