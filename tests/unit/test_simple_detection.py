"""
视频剪辑核心功能检测脚本
==========================
简化版检测脚本，专注核心功能
"""
import os
import sys
import traceback

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)
sys.path.insert(0, os.path.dirname(current_dir))

def test_mlt_engine():
    """检测 MLT 引擎"""
    print("\n--- 1. MLT 引擎检测 ---")
    try:
        from app.core.video_processing.mlt_engine_cpp import is_mlt_available, MltFactory, MltTimeline
        
        mlt_available = is_mlt_available()
        print(f"  MLT DLL 可用性: {'✓ 可用' if mlt_available else '✗ 不可用'}")
        
        if mlt_available:
            timeline = MltTimeline()
            print(f"  MLT Timeline 创建: ✓ 成功")
            
            track_count = timeline.add_track()
            print(f"  添加轨道: ✓ 成功 (轨道数: {track_count + 1})")
            
            can_animate = timeline.create_animation("volume")
            print(f"  关键帧动画支持: {'✓ 支持' if can_animate else '✗ 不支持'}")
            
            # 检查可用方法
            methods = [m for m in dir(timeline) if not m.startswith('_')]
            print(f"  可用方法: ✓ {len(methods)} 项")
            
            timeline.close()
        else:
            print("  → 使用 Python MLT 引擎")
            from app.core.video_processing.mlt_engine import MltEngine
            engine = MltEngine()
            print(f"  Python MLT 引擎: ✓ 可用")
            engine.close()
            
    except Exception as e:
        print(f"  ✗ 错误: {e}")
        traceback.print_exc()

def test_render_manager():
    """检测渲染管理器"""
    print("\n--- 2. 渲染管理器检测 ---")
    try:
        from app.core.render_manager import RenderManager
        
        manager = RenderManager()
        print(f"  渲染管理器创建: ✓ 成功")
        
        has_cpp_engine = hasattr(manager, '_cpp_engine') and manager._cpp_engine is not None
        print(f"  C++ 引擎: {'✓ 可用' if has_cpp_engine else '✗ 不可用'}")
        
        has_ffmpeg_engine = hasattr(manager, '_ffmpeg_engine') and manager._ffmpeg_engine is not None
        print(f"  FFmpeg 引擎: {'✓ 可用' if has_ffmpeg_engine else '✗ 不可用'}")
        
        # 硬件检测
        if hasattr(manager, '_hw'):
            hw_info = manager._hw
            print(f"  GPU 检测: ✓ {hw_info.get('gpu_name', '未知')}")
            print(f"  GPU 类型: ✓ {hw_info.get('gpu_type', '未知')}")
            
            # 可用编码器
            encoders = hw_info.get('encoders', [])
            if encoders:
                print(f"  可用编码器: ✓ {', '.join(encoders)}")
            else:
                print(f"  可用编码器: ✗ 未检测到")
        else:
            print(f"  GPU 检测: ✗ 硬件信息不可用")
            
    except Exception as e:
        print(f"  ✗ 错误: {e}")
        traceback.print_exc()

def test_effect_manager():
    """检测特效管理系统"""
    print("\n--- 3. 特效管理系统检测 ---")
    try:
        from app.core.effect_manager import EffectManager
        
        effect_manager = EffectManager()
        print(f"  特效管理器创建: ✓ 成功")
        
        effects = effect_manager.list_effects()
        print(f"  特效数量: ✓ {len(effects)} 种")
        
        if effects:
            print(f"  特效示例: {', '.join([e['name'] for e in effects[:3]])}...")
            
    except Exception as e:
        print(f"  ✗ 错误: {e}")
        traceback.print_exc()

def test_timeline_core():
    """检测时间线核心"""
    print("\n--- 4. 时间线核心检测 ---")
    try:
        from app.core.timeline import timeline_core
        
        print(f"  时间线核心: ✓ 可用")
        
        # 创建时间线
        timeline = timeline_core.create_timeline("测试时间线")
        print(f"  创建时间线: ✓ 成功 (ID: {timeline['id']})")
        
        # 获取当前时间线
        current_tl = timeline_core.get_current_timeline()
        print(f"  获取当前时间线: ✓ 成功")
        
        # 获取统计信息
        stats = timeline_core.get_timeline_stats()
        print(f"  获取统计信息: ✓ 成功 (轨道数: {stats.get('total_tracks', 0)})")
        
        # 获取特定时间线
        tl = timeline_core.get_timeline(timeline['id'])
        print(f"  获取指定时间线: ✓ 成功")
        
    except Exception as e:
        print(f"  ✗ 错误: {e}")
        traceback.print_exc()

def test_editor_interface():
    """检测编辑器接口"""
    print("\n--- 5. 编辑器接口检测 ---")
    try:
        from app.core.editor_interface import (
            IEditor, ITimelineEditor, IClipEditor, IEffectEditor,
            ITransitionEditor, IFilterEditor, EditMode, TrackType, ClipState, EditAction
        )
        
        print(f"  接口定义: ✓ IEditor, ITimelineEditor, IClipEditor, IEffectEditor, ITransitionEditor, IFilterEditor")
        print(f"  编辑模式: ✓ {len(EditMode)} 种")
        print(f"  轨道类型: ✓ {len(TrackType)} 种")
        print(f"  剪辑状态: ✓ {len(ClipState)} 种")
        print(f"  编辑操作: ✓ {len(EditAction)} 种")
        
    except Exception as e:
        print(f"  ✗ 错误: {e}")
        traceback.print_exc()

def test_professional_engine():
    """检测专业视频引擎"""
    print("\n--- 6. 专业视频引擎检测 ---")
    try:
        from app.modules.lego.professional_video_engine import ProfessionalVideoEngine
        
        engine = ProfessionalVideoEngine()
        print(f"  专业视频引擎创建: ✓ 成功")
        
        methods = [m for m in dir(engine) if not m.startswith('_')]
        print(f"  可用方法: ✓ {len(methods)} 项")
        
    except Exception as e:
        print(f"  ✗ 错误: {e}")
        traceback.print_exc()

def test_gpu_acceleration():
    """检测GPU加速"""
    print("\n--- 7. GPU加速检测 ---")
    try:
        from app.core.gpu_acceleration import GPUDetector
        
        gpu_detector = GPUDetector()
        print(f"  GPU检测模块: ✓ 可用")
        
        gpu_info = gpu_detector.detect_gpu()
        print(f"  GPU型号: ✓ {gpu_info.name or '未知'}")
        print(f"  GPU类型: ✓ {gpu_info.gpu_type.name if gpu_info.gpu_type else '未知'}")
        print(f"  CUDA可用: ✓ {'支持' if gpu_info.cuda_available else '不支持'}")
        
    except Exception as e:
        print(f"  ✗ 错误: {e}")
        traceback.print_exc()

def test_pyav_engine():
    """检测PyAV引擎"""
    print("\n--- 8. PyAV引擎检测 ---")
    try:
        from app.core.video_processing.pyav_engine import PyAVVideoEngine
        
        engine = PyAVVideoEngine()
        print(f"  PyAV引擎创建: ✓ 成功")
        
        # 检查可用方法
        methods = [m for m in dir(engine) if not m.startswith('_')]
        print(f"  可用方法: ✓ {len(methods)} 项")
        
    except Exception as e:
        print(f"  ✗ 错误: {e}")
        traceback.print_exc()

def main():
    """运行所有检测"""
    print("\n" + "="*70)
    print("  🎬 AI短剧编辑器 - 核心功能检测")
    print("="*70)
    
    test_mlt_engine()
    test_pyav_engine()
    test_render_manager()
    test_professional_engine()
    test_editor_interface()
    test_effect_manager()
    test_timeline_core()
    test_gpu_acceleration()
    
    print("\n" + "="*70)
    print("  检测完成")
    print("="*70)

if __name__ == "__main__":
    main()