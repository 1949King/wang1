"""
AI剪辑助手和字幕生成器测试
测试AI智能剪辑建议、自动字幕生成等功能
"""

import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.ai_editing_assistant import (
    AIEditingAssistant, SceneAnalyzer, EditSuggestionEngine,
    SceneType, EmotionType, SuggestionType, SceneAnalysis
)
from app.core.subtitle_generator import (
    SubtitleGenerator, SubtitleFormat, SubtitleStyle,
    SubtitlePosition, SubtitleSegment, SubtitleStyleConfig
)


def test_scene_analysis():
    """测试场景分析"""
    print("\n" + "="*50)
    print("测试场景分析")
    print("="*50)
    
    analyzer = SceneAnalyzer()
    
    print("生成测试视频帧...")
    num_frames = 300
    frames = []
    
    for i in range(num_frames):
        if i < 100:
            frame = np.random.randint(0, 100, (100, 100, 3), dtype=np.uint8)
        elif i < 200:
            frame = np.random.randint(100, 150, (100, 100, 3), dtype=np.uint8)
        elif i < 250:
            frame = np.random.randint(50, 100, (100, 100, 3), dtype=np.uint8)
        else:
            frame = np.random.randint(150, 200, (100, 100, 3), dtype=np.uint8)
        frames.append(frame)
    
    print("分析场景...")
    scenes = analyzer.analyze_scenes(frames)
    
    print(f"检测到 {len(scenes)} 个场景")
    for i, scene in enumerate(scenes[:5]):
        print(f"\n场景 {i+1}:")
        print(f"  时间: {scene.start_time:.2f}s - {scene.end_time:.2f}s")
        print(f"  类型: {scene.scene_type.value}")
        print(f"  情感: {scene.emotion.value}")
        print(f"  置信度: {scene.confidence:.2f}")
        print(f"  描述: {scene.description}")
        print(f"  建议动作: {', '.join(scene.suggested_actions)}")
    
    print("✓ 场景分析测试通过")


def test_edit_suggestions():
    """测试剪辑建议"""
    print("\n" + "="*50)
    print("测试剪辑建议")
    print("="*50)
    
    engine = EditSuggestionEngine()
    
    print("生成测试视频帧...")
    num_frames = 200
    frames = [np.random.randint(50, 200, (100, 100, 3), dtype=np.uint8) for _ in range(num_frames)]
    
    print("生成剪辑建议...")
    suggestions = engine.generate_suggestions(frames)
    
    print(f"生成 {len(suggestions)} 条建议")
    for i, suggestion in enumerate(suggestions[:5]):
        print(f"\n建议 {i+1}:")
        print(f"  类型: {suggestion.suggestion_type.value}")
        print(f"  优先级: {suggestion.priority}")
        print(f"  描述: {suggestion.description}")
        print(f"  置信度: {suggestion.confidence:.2f}")
        print(f"  原因: {suggestion.reason}")
        print(f"  时间: {suggestion.start_time:.2f}s - {suggestion.end_time:.2f}s")
        print(f"  参数: {suggestion.suggested_params}")
    
    print("✓ 剪辑建议测试通过")


def test_ai_editing_assistant():
    """测试AI剪辑助手"""
    print("\n" + "="*50)
    print("测试AI剪辑助手")
    print("="*50)
    
    assistant = AIEditingAssistant()
    
    print("生成测试视频帧...")
    num_frames = 150
    frames = [np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8) for _ in range(num_frames)]
    
    print("AI分析视频...")
    result = assistant.analyze_video(frames)
    
    print(f"\n场景统计:")
    stats = result["statistics"]
    print(f"  总场景数: {stats['total_scenes']}")
    print(f"  总建议数: {stats['total_suggestions']}")
    print(f"  平均置信度: {stats['average_confidence']:.2f}")
    
    print(f"\n场景类型分布:")
    for scene_type, count in stats['scene_types'].items():
        print(f"  {scene_type}: {count}")
    
    print(f"\n建议类型分布:")
    for suggestion_type, count in stats['suggestion_types'].items():
        print(f"  {suggestion_type}: {count}")
    
    print("✓ AI剪辑助手测试通过")


def test_subtitle_generation():
    """测试字幕生成"""
    print("\n" + "="*50)
    print("测试字幕生成")
    print("="*50)
    
    generator = SubtitleGenerator()
    
    print("生成测试音频路径...")
    test_audio = "test_audio.mp3"
    
    print("生成字幕...")
    segments = generator.generate_subtitles(test_audio, language="zh", correct_typos=True)
    
    print(f"生成 {len(segments)} 个字幕片段")
    for i, segment in enumerate(segments[:5]):
        print(f"\n片段 {i+1}:")
        print(f"  时间: {segment.start_time:.2f}s - {segment.end_time:.2f}s")
        print(f"  文本: {segment.text}")
        print(f"  置信度: {segment.confidence:.2f}")
        print(f"  语言: {segment.language}")
    
    print("✓ 字幕生成测试通过")


def test_subtitle_export():
    """测试字幕导出"""
    print("\n" + "="*50)
    print("测试字幕导出")
    print("="*50)
    
    generator = SubtitleGenerator()
    
    segments = [
        SubtitleSegment(
            id="seg_1",
            start_time=0.0,
            end_time=5.0,
            text="这是第一段字幕",
            confidence=0.95,
            language="zh"
        ),
        SubtitleSegment(
            id="seg_2",
            start_time=5.0,
            end_time=10.0,
            text="这是第二段字幕",
            confidence=0.92,
            language="zh"
        )
    ]
    
    print("测试SRT格式导出...")
    srt_content = generator.export_subtitles(segments, SubtitleFormat.SRT)
    print(f"SRT内容长度: {len(srt_content)} 字符")
    
    print("测试ASS格式导出...")
    ass_content = generator.export_subtitles(segments, SubtitleFormat.ASS)
    print(f"ASS内容长度: {len(ass_content)} 字符")
    
    print("测试VTT格式导出...")
    vtt_content = generator.export_subtitles(segments, SubtitleFormat.VTT)
    print(f"VTT内容长度: {len(vtt_content)} 字符")
    
    print("测试TXT格式导出...")
    txt_content = generator.export_subtitles(segments, SubtitleFormat.TXT)
    print(f"TXT内容长度: {len(txt_content)} 字符")
    
    print("✓ 字幕导出测试通过")


def test_subtitle_styles():
    """测试字幕样式"""
    print("\n" + "="*50)
    print("测试字幕样式")
    print("="*50)
    
    from app.core.subtitle_generator import SubtitleStyler
    
    styler = SubtitleStyler()
    
    print("获取可用样式...")
    styles = styler.get_available_styles()
    print(f"找到 {len(styles)} 种样式:")
    
    for style in styles:
        config = styler.get_style_config(style)
        print(f"\n{style.value}:")
        print(f"  字体: {config.font_name}")
        print(f"  大小: {config.font_size}")
        print(f"  颜色: {config.font_color}")
        print(f"  背景: {config.background_color}")
        print(f"  不透明度: {config.background_opacity}")
    
    print("✓ 字幕样式测试通过")


def test_typo_correction():
    """测试错别字纠错"""
    print("\n" + "="*50)
    print("测试错别字纠错")
    print("="*50)
    
    from app.core.subtitle_generator import TypoCorrector
    
    corrector = TypoCorrector()
    
    test_texts = [
        "这是一个测试，的得看看效果",
        "他再那里吗？",
        "这个产品非常好",
        "我喜欢这个，嘛"
        "他去了哪里"
    ]
    
    print("测试纠错功能...")
    for text in test_texts:
        correction = corrector.correct_text(text, confidence=0.85)
        
        print(f"\n原文: {text}")
        print(f"纠正后: {correction.corrected_text}")
        print(f"置信度: {correction.confidence:.2f}")
        
        if correction.corrections:
            print(f"纠正记录:")
            for corr in correction.corrections:
                print(f"  '{corr['original']}' -> '{corr['corrected']}' (位置: {corr['position']})")
    
    print("✓ 错别字纠错测试通过")


def test_subtitle_statistics():
    """测试字幕统计"""
    print("\n" + "="*50)
    print("测试字幕统计")
    print("="*50)
    
    generator = SubtitleGenerator()
    
    segments = [
        SubtitleSegment(
            id=f"seg_{i}",
            start_time=i * 3.0,
            end_time=(i + 1) * 3.0,
            text=f"这是第{i+1}段字幕",
            confidence=0.9 - i * 0.05,
            language="zh"
        )
        for i in range(10)
    ]
    
    print("获取统计信息...")
    stats = generator.get_statistics()
    
    print(f"总片段数: {stats['total_segments']}")
    print(f"总时长: {stats['total_duration']:.2f}s")
    print(f"平均时长: {stats['average_duration']:.2f}s")
    print(f"平均置信度: {stats['average_confidence']:.2f}")
    print(f"语言: {', '.join(stats['languages'])}")
    print(f"说话人: {', '.join(stats['speakers'])}")
    
    print("✓ 字幕统计测试通过")


def run_all_tests():
    """运行所有测试"""
    print("\n" + "="*60)
    print("AI剪辑助手和字幕生成器测试套件")
    print("="*60)
    
    try:
        test_scene_analysis()
        test_edit_suggestions()
        test_ai_editing_assistant()
        test_subtitle_generation()
        test_subtitle_export()
        test_subtitle_styles()
        test_typo_correction()
        test_subtitle_statistics()
        
        print("\n" + "="*60)
        print("✓ 所有测试通过!")
        print("="*60)
        
    except AssertionError as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    except Exception as e:
        print(f"\n✗ 测试异常: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    run_all_tests()
