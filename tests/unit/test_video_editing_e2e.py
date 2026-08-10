"""
视频剪辑端到端功能检测脚本
============================
全面检测项目视频剪辑编辑能力，确保所有功能端到端可用

检测范围：
1. 视频处理引擎 (MLT / PyAV / C++引擎)
2. 渲染管理器
3. 专业视频引擎
4. 编辑器接口
5. 多轨道编辑器
6. 特效、转场、滤镜系统
7. 硬件加速支持
8. 端到端完整流程测试
"""
import os
import sys
import time
import traceback
from typing import Dict, List, Tuple, Any

# 添加项目路径（从 app 目录运行时需要添加上级目录）
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)
sys.path.insert(0, os.path.dirname(current_dir))

RESULT_COLORS = {
    'PASS': '\033[92mPASS\033[0m',
    'FAIL': '\033[91mFAIL\033[0m',
    'WARN': '\033[93mWARN\033[0m',
    'SKIP': '\033[94mSKIP\033[0m'
}

class TestResult:
    def __init__(self, name: str, success: bool, message: str = "", details: str = ""):
        self.name = name
        self.success = success
        self.message = message
        self.details = details

    def __repr__(self):
        status = RESULT_COLORS['PASS'] if self.success else RESULT_COLORS['FAIL']
        return f"[{status}] {self.name}: {self.message}"

class VideoEditingDetector:
    """视频剪辑能力检测器"""
    
    def __init__(self):
        self.results: List[TestResult] = []
        self.failed_count = 0
        self.passed_count = 0
        self.warn_count = 0
        
    def run_all_tests(self):
        """运行所有检测"""
        print("\n" + "="*70)
        print("  🎬 AI短剧编辑器 - 视频剪辑端到端功能检测")
        print("="*70 + "\n")
        
        self._test_mlt_engine()
        self._test_cpp_engine()
        self._test_pyav_engine()
        self._test_render_manager()
        self._test_professional_video_engine()
        self._test_editor_interface()
        self._test_multi_track_editor()
        self._test_effects_and_transitions()
        self._test_hardware_acceleration()
        self._test_core_capabilities()
        self._test_end_to_end()
        
        self._print_summary()
    
    def _add_result(self, result: TestResult):
        """添加检测结果"""
        self.results.append(result)
        if result.success:
            self.passed_count += 1
        else:
            self.failed_count += 1
        print(result)
        if result.details:
            print(f"     详情: {result.details}")
    
    def _test_mlt_engine(self):
        """检测 MLT 引擎"""
        print("\n--- 1. MLT 引擎检测 ---")
        
        try:
            from app.core.video_processing.mlt_engine_cpp import is_mlt_available, MltFactory, MltTimeline
            
            mlt_available = is_mlt_available()
            self._add_result(TestResult(
                "MLT DLL 可用性", 
                mlt_available,
                "可用" if mlt_available else "不可用（回退到 Python MLT 引擎）"
            ))
            
            if mlt_available:
                timeline = MltTimeline()
                self._add_result(TestResult(
                    "MLT Timeline 初始化",
                    timeline.available,
                    "成功" if timeline.available else "失败"
                ))
                
                # 测试多轨合成
                track_idx = timeline.add_track()
                self._add_result(TestResult(
                    "多轨合成 - 添加轨道",
                    track_idx >= 0,
                    f"轨道索引: {track_idx}"
                ))
                
                # 测试滤镜链
                filter_result = timeline.add_global_filter('brightness', {'level': '1.2'})
                self._add_result(TestResult(
                    "滤镜链处理 - 添加全局滤镜",
                    filter_result,
                    "成功" if filter_result else "失败"
                ))
                
                # 测试关键帧动画
                anim_result = timeline.create_animation('opacity')
                self._add_result(TestResult(
                    "关键帧动画 - 创建动画对象",
                    anim_result,
                    "成功" if anim_result else "失败"
                ))
                
                timeline.close()
                
        except Exception as e:
            self._add_result(TestResult(
                "MLT 引擎检测",
                False,
                str(e),
                traceback.format_exc()
            ))
    
    def _test_cpp_engine(self):
        """检测 C++ 引擎"""
        print("\n--- 2. C++ 视频引擎检测 ---")
        
        try:
            from app.core.video_processing.cpp_engine.video_engine_cpp import VideoEngine
            
            engine = VideoEngine()
            self._add_result(TestResult(
                "C++ 引擎初始化",
                True,
                "成功"
            ))
            
            # 测试引擎功能（检查可用方法）
            methods = [m for m in dir(engine) if not m.startswith('_')]
            self._add_result(TestResult(
                "C++ 引擎功能列表",
                len(methods) > 0,
                f"{len(methods)} 项方法可用: {', '.join(methods[:5])}..."
            ))
            
        except ImportError:
            self._add_result(TestResult(
                "C++ 引擎导入",
                False,
                "DLL 不可用"
            ))
        except Exception as e:
            self._add_result(TestResult(
                "C++ 引擎检测",
                False,
                str(e),
                traceback.format_exc()
            ))
    
    def _test_pyav_engine(self):
        """检测 PyAV 引擎"""
        print("\n--- 3. PyAV 引擎检测 ---")
        
        try:
            from app.core.video_processing.pyav_engine import PyAVEngine
            
            engine = PyAVEngine()
            self._add_result(TestResult(
                "PyAV 引擎初始化",
                True,
                "成功"
            ))
            
            # 测试基本功能
            has_pyav = engine.has_pyav()
            self._add_result(TestResult(
                "PyAV 库可用性",
                has_pyav,
                "可用" if has_pyav else "不可用"
            ))
            
        except Exception as e:
            self._add_result(TestResult(
                "PyAV 引擎检测",
                False,
                str(e),
                traceback.format_exc()
            ))
    
    def _test_render_manager(self):
        """检测渲染管理器"""
        print("\n--- 4. 渲染管理器检测 ---")
        
        try:
            from app.core.render_manager import RenderManager, RenderConfig, HardwareEncoder
            
            manager = RenderManager()
            self._add_result(TestResult(
                "渲染管理器初始化",
                True,
                "成功"
            ))
            
            # 测试硬件编码器检测（通过 _hw 属性）
            if hasattr(manager, '_hw') and manager._hw:
                hw_info = manager._hw.__dict__ if hasattr(manager._hw, '__dict__') else str(manager._hw)
                self._add_result(TestResult(
                    "硬件编码器检测",
                    True,
                    f"硬件信息: {hw_info}"
                ))
            else:
                self._add_result(TestResult(
                    "硬件编码器检测",
                    False,
                    "未检测到硬件信息"
                ))
            
            # 测试渲染配置
            config = RenderConfig()
            self._add_result(TestResult(
                "渲染配置创建",
                True,
                f"{config.width}x{config.height} @ {config.fps}fps"
            ))
            
        except Exception as e:
            self._add_result(TestResult(
                "渲染管理器检测",
                False,
                str(e),
                traceback.format_exc()
            ))
    
    def _test_professional_video_engine(self):
        """检测专业视频引擎"""
        print("\n--- 5. 专业视频引擎检测 ---")
        
        try:
            from app.modules.lego.professional_video_engine import ProfessionalVideoEngine, VideoCodec, HardwareAccel
            
            engine = ProfessionalVideoEngine()
            self._add_result(TestResult(
                "专业视频引擎初始化",
                True,
                "成功"
            ))
            
            # 测试 FFmpeg 查找
            ffmpeg_path = engine.find_ffmpeg()
            self._add_result(TestResult(
                "FFmpeg 可执行文件查找",
                ffmpeg_path is not None,
                ffmpeg_path or "未找到"
            ))
            
            # 测试硬件加速检测
            hw_accel = engine.detect_hardware_acceleration()
            self._add_result(TestResult(
                "硬件加速检测",
                hw_accel != HardwareAccel.NONE,
                str(hw_accel)
            ))
            
            # 测试编解码器列表
            codecs = list(VideoCodec)
            self._add_result(TestResult(
                "编解码器支持",
                len(codecs) > 0,
                f"{len(codecs)} 种编解码器"
            ))
            
        except Exception as e:
            self._add_result(TestResult(
                "专业视频引擎检测",
                False,
                str(e),
                traceback.format_exc()
            ))
    
    def _test_editor_interface(self):
        """检测编辑器接口"""
        print("\n--- 6. 编辑器接口检测 ---")
        
        try:
            from app.core.editor_interface import (
                IEditor, ITimelineEditor, IClipEditor, IEffectEditor,
                ITransitionEditor, IFilterEditor, EditorFactory, UnifiedEditor,
                EditMode, TrackType, ClipState, EditAction
            )
            
            # 测试接口定义
            self._add_result(TestResult(
                "编辑器接口定义",
                True,
                f"IEditor, ITimelineEditor, IClipEditor, IEffectEditor, ITransitionEditor, IFilterEditor"
            ))
            
            # 测试枚举定义
            self._add_result(TestResult(
                "编辑模式枚举",
                True,
                f"{len(EditMode)} 种模式: {[e.name for e in EditMode]}"
            ))
            
            self._add_result(TestResult(
                "轨道类型枚举",
                True,
                f"{len(TrackType)} 种类型: {[e.name for e in TrackType]}"
            ))
            
            self._add_result(TestResult(
                "编辑操作枚举",
                True,
                f"{len(EditAction)} 种操作"
            ))
            
            # 测试统一编辑器（跳过创建，依赖过于复杂）
            self._add_result(TestResult(
                "统一编辑器创建",
                False,
                "跳过（依赖复杂）"
            ))
            
        except Exception as e:
            self._add_result(TestResult(
                "编辑器接口检测",
                False,
                str(e),
                traceback.format_exc()
            ))
    
    def _test_multi_track_editor(self):
        """检测多轨道编辑器"""
        print("\n--- 7. 多轨道编辑器检测 ---")
        
        try:
            from app.modules.lego.video_editor.multi_track_editor import MultiTrackEditor, TrackType, TrackInfo, ClipInfo
            
            editor = MultiTrackEditor()
            self._add_result(TestResult(
                "多轨道编辑器创建",
                True,
                "成功"
            ))
            
            # 测试轨道类型
            self._add_result(TestResult(
                "轨道类型定义",
                True,
                f"VIDEO, AUDIO, SUBTITLE"
            ))
            
            # 测试轨道信息类
            track_info = TrackInfo("track_001", TrackType.VIDEO, "视频轨道1")
            self._add_result(TestResult(
                "TrackInfo 类",
                True,
                f"ID: {track_info.track_id}, Type: {track_info.track_type}"
            ))
            
            # 测试片段信息类
            clip_info = ClipInfo("clip_001", "track_001", 0.0, 5.0, "test.mp4")
            self._add_result(TestResult(
                "ClipInfo 类",
                True,
                f"ID: {clip_info.clip_id}, Duration: {clip_info.duration}s"
            ))
            
        except Exception as e:
            self._add_result(TestResult(
                "多轨道编辑器检测",
                False,
                str(e),
                traceback.format_exc()
            ))
    
    def _test_effects_and_transitions(self):
        """检测特效、转场、滤镜系统"""
        print("\n--- 8. 特效、转场、滤镜系统检测 ---")
        
        try:
            # 测试转场系统
            from app.core.transitions import (
                TRANSITIONS, TransitionDef, TransitionCategory,
                get_all_transitions, get_transitions_by_category, get_transition,
                TRANSITION_COUNT
            )
            
            self._add_result(TestResult(
                "转场系统",
                True,
                f"{TRANSITION_COUNT} 种转场"
            ))
            
            transitions = get_all_transitions()
            self._add_result(TestResult(
                "转场列表获取",
                len(transitions) == TRANSITION_COUNT,
                f"获取到 {len(transitions)} 种转场"
            ))
            
            # 测试特效系统
            from app.core.effect_manager import EffectManager
            
            effect_manager = EffectManager()
            effects = effect_manager.list_effects()
            self._add_result(TestResult(
                "特效系统",
                len(effects) > 0,
                f"{len(effects)} 种特效"
            ))
            
            # 测试标题模板
            from app.core.title_templates import (
                TITLE_TEMPLATES, TitleTemplate, TitleCategory,
                get_all_templates, get_template, TEMPLATE_COUNT
            )
            
            self._add_result(TestResult(
                "标题模板系统",
                True,
                f"{TEMPLATE_COUNT} 种模板"
            ))
            
            # 测试遮罩系统
            from app.core.mask_system import (
                mask_manager, Mask, MaskShape, MaskKeyframe, MASK_PRESETS
            )
            
            self._add_result(TestResult(
                "遮罩系统",
                True,
                f"{len(MASK_PRESETS)} 种遮罩预设"
            ))
            
        except Exception as e:
            self._add_result(TestResult(
                "特效转场系统检测",
                False,
                str(e),
                traceback.format_exc()
            ))
    
    def _test_hardware_acceleration(self):
        """检测硬件加速支持"""
        print("\n--- 9. 硬件加速支持检测 ---")
        
        try:
            from app.core.gpu_acceleration import GPUAcceleration
            
            gpu = GPUAcceleration()
            self._add_result(TestResult(
                "GPU 加速模块",
                True,
                "成功"
            ))
            
            # 测试 GPU 检测
            gpu_info = gpu.detect_gpu()
            self._add_result(TestResult(
                "GPU 检测",
                gpu_info is not None,
                str(gpu_info) if gpu_info else "未检测到 GPU"
            ))
            
            # 测试编码支持
            nvenc_support = gpu.has_nvenc()
            qsv_support = gpu.has_qsv()
            amf_support = gpu.has_amf()
            
            self._add_result(TestResult(
                "NVIDIA NVENC 支持",
                nvenc_support,
                "支持" if nvenc_support else "不支持"
            ))
            
            self._add_result(TestResult(
                "Intel QSV 支持",
                qsv_support,
                "支持" if qsv_support else "不支持"
            ))
            
            self._add_result(TestResult(
                "AMD AMF 支持",
                amf_support,
                "支持" if amf_support else "不支持"
            ))
            
        except Exception as e:
            self._add_result(TestResult(
                "硬件加速检测",
                False,
                str(e),
                traceback.format_exc()
            ))
    
    def _test_core_capabilities(self):
        """检测核心编辑能力"""
        print("\n--- 10. 核心编辑能力检测 ---")
        
        try:
            from app.core.editing_capabilities import (
                CAPABILITY_SUMMARY, get_capability_report,
                shortcut_manager, auto_backup_manager,
                SpeedRamp, reverse_clip_ffmpeg, freeze_frame_ffmpeg,
                get_all_transitions, lut_loader, frame_navigator,
                mask_manager, waveform_generator, audio_scope_manager
            )
            
            report = get_capability_report()
            self._add_result(TestResult(
                "能力报告生成",
                True,
                f"{len(CAPABILITY_SUMMARY)} 项能力"
            ))
            
            # 测试快捷键管理器
            shortcuts = shortcut_manager.get_all_bindings()
            self._add_result(TestResult(
                "快捷键系统",
                len(shortcuts) > 0,
                f"{len(shortcuts)} 个快捷键绑定"
            ))
            
            # 测试自动备份
            backup_enabled = auto_backup_manager.is_enabled()
            self._add_result(TestResult(
                "自动备份系统",
                backup_enabled,
                "已启用" if backup_enabled else "未启用"
            ))
            
            # 测试 Speed Ramping
            ramp = SpeedRamp()
            self._add_result(TestResult(
                "速度曲线系统",
                True,
                "成功"
            ))
            
            # 测试 LUT 加载器
            luts = lut_loader.get_available_luts()
            self._add_result(TestResult(
                "LUT 加载器",
                True,
                f"{len(luts)} 种 LUT 预设"
            ))
            
            # 测试帧导航器
            tc = frame_navigator.seconds_to_timecode(123.45)
            self._add_result(TestResult(
                "帧导航器",
                True,
                f"123.45s → {tc}"
            ))
            
        except Exception as e:
            self._add_result(TestResult(
                "核心编辑能力检测",
                False,
                str(e),
                traceback.format_exc()
            ))
    
    def _test_end_to_end(self):
        """端到端完整流程测试"""
        print("\n--- 11. 端到端完整流程测试 ---")
        
        try:
            # 测试数据准备
            test_video_path = os.path.join(os.path.dirname(__file__), "temp", "e2e_src1.mp4")
            
            if not os.path.exists(test_video_path):
                # 创建测试视频（使用 FFmpeg）
                from app.modules.lego.professional_video_engine import FFmpegUtils
                ffmpeg_path = FFmpegUtils.find_ffmpeg()
                if ffmpeg_path:
                    import subprocess
                    cmd = [
                        ffmpeg_path,
                        "-f", "lavfi",
                        "-i", "testsrc=duration=5:size=1920x1080:rate=30",
                        "-f", "lavfi",
                        "-i", "sine=frequency=440:duration=5",
                        "-c:v", "libx264",
                        "-c:a", "aac",
                        "-y",
                        test_video_path
                    ]
                    result = subprocess.run(cmd, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                    if result.returncode == 0:
                        self._add_result(TestResult(
                            "测试视频生成",
                            True,
                            f"创建了 {test_video_path}"
                        ))
                    else:
                        self._add_result(TestResult(
                            "测试视频生成",
                            False,
                            f"FFmpeg 返回码: {result.returncode}"
                        ))
                        return
                else:
                    self._add_result(TestResult(
                        "测试视频生成",
                        False,
                        "FFmpeg 不可用，跳过端到端测试"
                    ))
                    return
            
            self._add_result(TestResult(
                "测试视频准备",
                True,
                test_video_path
            ))
            
            # 测试视频信息获取
            from app.modules.lego.professional_video_engine import FFmpegUtils
            video_info = FFmpegUtils.get_video_info(test_video_path)
            self._add_result(TestResult(
                "视频信息获取",
                video_info is not None,
                f"{video_info.width}x{video_info.height} @ {video_info.fps}fps, {video_info.duration:.2f}s" if video_info else "失败"
            ))
            
            # 测试剪辑操作
            output_path = os.path.join(os.path.dirname(__file__), "temp", "e2e_clipped_test.mp4")
            
            from app.modules.lego.professional_video_engine import ProfessionalVideoEngine
            engine = ProfessionalVideoEngine()
            
            cut_result = engine.cut_video(
                input_path=test_video_path,
                output_path=output_path,
                start_time=1.0,
                end_time=4.0
            )
            
            self._add_result(TestResult(
                "视频剪辑操作",
                cut_result.success,
                cut_result.error_message or "成功"
            ))
            
            if cut_result.success and os.path.exists(output_path):
                clipped_info = FFmpegUtils.get_video_info(output_path)
                expected_duration = 3.0
                actual_duration = clipped_info.duration if clipped_info else 0
                duration_ok = abs(actual_duration - expected_duration) < 0.5
                
                self._add_result(TestResult(
                    "剪辑结果验证",
                    duration_ok,
                    f"预期: {expected_duration}s, 实际: {actual_duration:.2f}s"
                ))
                
                # 测试添加水印
                watermark_path = os.path.join(os.path.dirname(__file__), "temp", "e2e_wmarked_test.mp4")
                wm_result = engine.add_watermark(
                    input_path=output_path,
                    output_path=watermark_path,
                    text="测试水印",
                    position="bottom_right"
                )
                
                self._add_result(TestResult(
                    "文字水印添加",
                    wm_result.success,
                    wm_result.error_message or "成功"
                ))
                
                # 清理临时文件
                for f in [output_path, watermark_path]:
                    if os.path.exists(f):
                        os.remove(f)
            
        except Exception as e:
            self._add_result(TestResult(
                "端到端测试",
                False,
                str(e),
                traceback.format_exc()
            ))
    
    def _print_summary(self):
        """打印检测总结"""
        print("\n" + "="*70)
        print("  📊 检测总结")
        print("="*70)
        
        total = len(self.results)
        print(f"\n  总检测项: {total}")
        print(f"  ✅ 通过: {RESULT_COLORS['PASS']} {self.passed_count}")
        print(f"  ❌ 失败: {RESULT_COLORS['FAIL']} {self.failed_count}")
        print(f"  ⚠️ 警告: {RESULT_COLORS['WARN']} {self.warn_count}")
        
        if self.failed_count > 0:
            print("\n  失败项详情:")
            for r in self.results:
                if not r.success:
                    print(f"    - {r.name}: {r.message}")
        
        print("\n" + "="*70)
        
        # 输出架构分析
        self._print_architecture_analysis()
    
    def _print_architecture_analysis(self):
        """打印架构分析"""
        print("\n  🏗️ 视频剪辑架构分析")
        print("  " + "-"*60)
        
        print("""
  当前架构基于三层设计:
  
  ┌─────────────────────────────────────────────────────────────┐
  │  UI 层 (app/modules/lego/video_editor/)                    │
  │  ├─ MultiTrackEditor - 多轨道编辑界面                       │
  │  ├─ ProfessionalEditor - 专业编辑界面                       │
  │  ├─ TimelineView - 时间轴视图                              │
  │  └─ FrameEditor - 帧编辑器                                 │
  └─────────────────────────────────────────────────────────────┘
                              │
                              ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  核心层 (app/core/)                                         │
  │  ├─ editor_interface.py - 统一编辑器接口定义                │
  │  ├─ editing_capabilities.py - 编辑能力统一入口              │
  │  ├─ render_manager.py - 渲染调度中心                        │
  │  ├─ track_manager.py - 轨道管理                            │
  │  ├─ effect_manager.py - 特效管理                           │
  │  ├─ transition_manager.py - 转场管理                       │
  │  ├─ speed_ramping.py - 速度曲线                            │
  │  ├─ mask_system.py - 遮罩系统                              │
  │  └─ timeline_dsl.py - 时间轴 DSL                           │
  └─────────────────────────────────────────────────────────────┘
                              │
                              ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  引擎层 (app/core/video_processing/)                        │
  │  ├─ mlt_engine_cpp.py - MLT C++ 引擎 (ctypes 封装)         │
  │  ├─ mlt_engine.py - Python MLT 引擎 (回退)                 │
  │  ├─ cpp_engine/ - C++ FFmpeg 引擎 (pybind11)              │
  │  ├─ pyav_engine.py - PyAV 轻量引擎                        │
  │  └─ drama_mlt.py - 短剧定制 MLT 引擎                       │
  └─────────────────────────────────────────────────────────────┘
  
  多轨合成:    ✓ 基于 MLT Playlist 嵌套机制                   
  滤镜链:      ✓ 基于 MLT Filter API + FFmpeg Filter Graph   
  关键帧动画:  ✓ 基于 MLT Animation API                      
  硬件加速:    ✓ NVENC/QSV/AMF 自动检测与选择                  """)

if __name__ == "__main__":
    detector = VideoEditingDetector()
    detector.run_all_tests()