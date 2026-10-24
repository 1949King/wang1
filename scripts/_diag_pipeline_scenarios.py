"""模拟用户实际场景测试"""
import sys, os

ROOT = r'd:\拾光剪影'
sys.path.insert(0, ROOT)

print('=== 场景1：无素材 + 无创意简报 ===')
try:
    from app.core.agent_pipeline_orchestrator import agent_pipeline_orchestrator
    session = agent_pipeline_orchestrator.execute(
        materials=[],          # 导入栏无素材
        creative_brief="",     # Agent输入框为空
        platform="douyin",
        target_duration=10.0,
        clip_duration=3.0,
        provider="local",
        auto_preview_pass=True,
        session_id="test1",
    )
    print(f'  success: {session.success}')
    print(f'  stage: {session.stage}')
    print(f'  error: {session.error or "(无)"}')
except Exception as e:
    print(f'  ❌ 异常: {e}')

print()
print('=== 场景2：无素材 + 有创意简报 ===')
try:
    session = agent_pipeline_orchestrator.execute(
        materials=[],
        creative_brief="一个关于城市夜景的短视频",
        platform="douyin",
        target_duration=10.0,
        clip_duration=3.0,
        provider="local",
        auto_preview_pass=True,
        session_id="test2",
    )
    print(f'  success: {session.success}')
    print(f'  stage: {session.stage}')
    print(f'  error: {session.error or "(无)"}')
    print(f'  生成片段数: {len(session.generation_result.get("clips", []))}')
except Exception as e:
    print(f'  ❌ 异常: {e}')

print()
print('=== 场景3：有素材 + 有创意简报 ===')
try:
    # 创建一个测试素材
    test_material = {
        "path": "",  # 空路径，会被过滤
        "type": "video",
        "duration": 5.0,
        "name": "test.mp4",
    }
    session = agent_pipeline_orchestrator.execute(
        materials=[test_material],
        creative_brief="",
        platform="douyin",
        target_duration=10.0,
        clip_duration=3.0,
        provider="local",
        auto_preview_pass=True,
        session_id="test3",
    )
    print(f'  success: {session.success}')
    print(f'  stage: {session.stage}')
    print(f'  route: {session.route}')
    print(f'  error: {session.error or "(无)"}')
except Exception as e:
    print(f'  ❌ 异常: {e}')
