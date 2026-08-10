"""诊断 AI 视频生成业务线失败原因"""
import sys, os, shutil

ROOT = r'd:\拾光剪影'
sys.path.insert(0, ROOT)

print('=== 1. FFmpeg 检查 ===')
# 检查 thirdparty 路径
for p in [
    os.path.join(ROOT, 'thirdparty', 'ffmpeg', 'bin', 'ffmpeg.exe'),
    os.path.join(ROOT, 'ffmpeg', 'ffmpeg.exe'),
    os.path.join(ROOT, 'bin', 'ffmpeg.exe'),
]:
    exists = os.path.isfile(p)
    print(f'  {p}: {"✅" if exists else "❌"}')

# 系统 PATH
sys_ff = shutil.which('ffmpeg') or shutil.which('ffmpeg.exe')
print(f'  系统PATH: {sys_ff or "❌ 未找到"}')

# ffmpeg_utils
try:
    from app.core.ffmpeg_utils import find_ffmpeg
    path = find_ffmpeg()
    print(f'  ffmpeg_utils.find: {path or "❌"}')
    if path:
        print(f'    存在: {os.path.isfile(path)}')
except Exception as e:
    print(f'  ffmpeg_utils 异常: {e}')

print()
print('=== 2. VideoGenerationClient 本地占位测试 ===')
try:
    from app.core.ai.video_generation_client import VideoGenerationClient
    client = VideoGenerationClient()
    result = client._call_local_fallback(
        prompt="测试提示词",
        duration=5.0,
        count=1,
        width=1280,
        height=720,
    )
    print(f'  占位生成结果: {len(result)} 个文件')
    for r in result:
        print(f'    {r} (大小: {os.path.getsize(r)/1024:.1f}KB)' if os.path.exists(r) else f'    {r} (不存在)')
except Exception as e:
    print(f'  ❌ 异常: {e}')
    import traceback
    traceback.print_exc()

print()
print('=== 3. AIVideoGenerationPipeline 执行测试 ===')
try:
    from app.core.ai_video_generation_pipeline import AIVideoGenerationPipeline
    pipeline = AIVideoGenerationPipeline()
    result = pipeline.execute(
        creative_brief="测试视频内容",
        platform="douyin",
        target_duration=10.0,
        clip_duration=3.0,
        provider="local",  # 只用本地占位
        request_id="diag_test",
    )
    print(f'  success: {result.success}')
    print(f'  error: {result.error or "(无)"}')
    print(f'  clips 数量: {len(result.clips)}')
    for c in result.clips:
        print(f'    clip_id={c.clip_id}, path={c.path}, duration={c.duration}')
        if hasattr(c, 'path') and os.path.exists(c.path):
            print(f'      文件存在, 大小: {os.path.getsize(c.path)/1024:.1f}KB')
        else:
            print(f'      ❌ 文件不存在')
except Exception as e:
    print(f'  ❌ 异常: {e}')
    import traceback
    traceback.print_exc()

print()
print('=== 诊断完成 ===')
