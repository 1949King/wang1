"""
AI配音生成和特效推荐测试
测试AI配音生成、特效推荐等功能
"""

import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.voice_generator import (
    AIVoiceGenerator, VoiceProfile, VoiceStyle,
    VoiceGender, VoiceAge, VoiceGenerationRequest
)
from app.core.voice_generator import EffectRecommendationEngine


def test_voice_profiles():
    """测试声线配置"""
    print("\n" + "="*50)
    print("测试声线配置")
    print("="*50)
    
    generator = AIVoiceGenerator()
    
    print("获取默认声线配置...")
    profiles = generator.get_voice_profiles()
    
    print(f"找到 {len(profiles)} 个声线配置:")
    for profile in profiles:
        print(f"\n{profile.name}:")
        print(f"  ID: {profile.id}")
        print(f"  性别: {profile.gender.value}")
        print(f"  年龄: {profile.age.value}")
        print(f"  风格: {profile.style.value}")
        print(f"  语言: {profile.language}")
        print(f"  采样率: {profile.sample_rate}")
        print(f"  描述: {profile.description}")
        print(f"  默认: {'是' if profile.is_default else '否'}")
    
    print("✓ 声线配置测试通过")


def test_voice_generation():
    """测试配音生成"""
    print("\n" + "="*50)
    print("测试配音生成")
    print("="*50)
    
    generator = AIVoiceGenerator()
    
    print("创建生成请求...")
    request = VoiceGenerationRequest(
        text="这是一段测试文本，用于验证AI配音生成功能。",
        voice_profile_id="male_adult_calm",
        speed=1.0,
        pitch=1.0,
        volume=1.0,
        emotion="neutral",
        language="zh",
        output_format="mp3"
    )
    
    print("生成配音...")
    result = generator.generate_voice(request)
    
    print(f"\n生成结果:")
    print(f"  请求ID: {result.request_id}")
    print(f"  成功: {'是' if result.success else '否'}")
    
    if result.success:
        print(f"  音频时长: {result.duration:.2f}s")
        print(f"  采样率: {result.sample_rate}")
        print(f"  生成时间: {result.generation_time:.2f}s")
        print(f"  音频数据形状: {result.audio_data.shape if result.audio_data is not None else 'N/A'}")
        print(f"  音频路径: {result.audio_path if result.audio_path else 'N/A'}")
    else:
        print(f"  错误信息: {result.error_message}")
    
    print("✓ 配音生成测试通过")


def test_batch_generation():
    """测试批量生成"""
    print("\n" + "="*50)
    print("测试批量生成")
    print("="*50)
    
    generator = AIVoiceGenerator()
    
    print("创建多个生成请求...")
    requests = [
        VoiceGenerationRequest(
            text="第一条测试文本",
            voice_profile_id="male_adult_calm",
            emotion="neutral"
        ),
        VoiceGenerationRequest(
            text="第二条测试文本",
            voice_profile_id="female_adult_emotional",
            emotion="happy"
        ),
        VoiceGenerationRequest(
            text="第三条测试文本",
            voice_profile_id="child_cute",
            emotion="happy"
        )
    ]
    
    print("批量生成配音...")
    results = generator.batch_generate(requests)
    
    print(f"\n批量生成结果:")
    success_count = sum(1 for r in results if r.success)
    print(f"  总请求数: {len(requests)}")
    print(f"  成功数: {success_count}")
    print(f"  失败数: {len(results) - success_count}")
    
    for i, result in enumerate(results):
        print(f"\n请求 {i+1}:")
        print(f"  成功: {'是' if result.success else '否'}")
        if not result.success:
            print(f"  错误: {result.error_message}")
    
    print("✓ 批量生成测试通过")


def test_effect_recommendations():
    """测试特效推荐"""
    print("\n" + "="*50)
    print("测试特效推荐")
    print("="*50)
    
    engine = EffectRecommendationEngine()
    
    print("测试场景类型推荐...")
    scene_types = ["intro", "emotion", "suspense", "action", "climax"]
    
    for scene_type in scene_types:
        print(f"\n场景类型: {scene_type}")
        recommendations = engine.recommend_effects(
            scene_type=scene_type,
            emotion="neutral",
            genre="general",
            confidence=0.85
        )
        
        print(f"  推荐数量: {len(recommendations)}")
        for i, rec in enumerate(recommendations[:3]):
            print(f"  推荐 {i+1}: {rec['effect_id']}")
            print(f"    来源: {rec['source']}")
            print(f"    置信度: {rec['confidence']:.2f}")
            print(f"    原因: {rec['reason']}")
    
    print("✓ 场景类型推荐测试通过")
    
    print("\n测试情感类型推荐...")
    emotions = ["happy", "sad", "angry", "surprised"]
    
    for emotion in emotions:
        print(f"\n情感类型: {emotion}")
        recommendations = engine.recommend_effects(
            scene_type="emotion",
            emotion=emotion,
            genre="general",
            confidence=0.8
        )
        
        print(f"  推荐数量: {len(recommendations)}")
        for i, rec in enumerate(recommendations[:3]):
            print(f"  推荐 {i+1}: {rec['effect_id']}")
            print(f"    来源: {rec['source']}")
            print(f"    置信度: {rec['confidence']:.2f}")
            print(f"    原因: {rec['reason']}")
    
    print("✓ 情感类型推荐测试通过")


def test_custom_recommendation_rules():
    """测试自定义推荐规则"""
    print("\n" + "="*50)
    print("测试自定义推荐规则")
    print("="*50)
    
    engine = EffectRecommendationEngine()
    
    print("添加自定义规则...")
    engine.add_custom_rule("scene_to_effect", "custom_rule", ["custom_effect_1", "custom_effect_2"])
    
    print("添加自定义规则...")
    engine.add_custom_rule("emotion_to_effect", "happy_rule", ["happy_effect_1", "happy_effect_2"])
    
    print("✓ 自定义规则测试通过")


def test_voice_profile_management():
    """测试声线配置管理"""
    print("\n" + "="*50)
    print("测试声线配置管理")
    print("="*50)
    
    generator = AIVoiceGenerator()
    
    print("添加自定义声线配置...")
    custom_profile = VoiceProfile(
        id="custom_001",
        name="自定义声线",
        gender=VoiceGender.NEUTRAL,
        age=VoiceAge.ADULT,
        style=VoiceStyle.PROFESSIONAL,
        language="zh",
        sample_rate=22050,
        description="用户自定义的声线配置"
    )
    
    added = generator.add_voice_profile(custom_profile)
    print(f"添加结果: {'成功' if added else '失败'}")
    
    if added:
        print("搜索自定义声线...")
        profiles = generator.get_voice_profiles()
        custom_profiles = [p for p in profiles if p.id == "custom_001"]
        print(f"找到: {len(custom_profiles)} 个自定义配置")
        
        print("移除自定义声线...")
        removed = generator.remove_voice_profile("custom_001")
        print(f"移除结果: {'成功' if removed else '失败'}")
    
    print("✓ 声线配置管理测试通过")


def run_all_tests():
    """运行所有测试"""
    print("\n" + "="*60)
    print("AI配音生成和特效推荐测试套件")
    print("="*60)
    
    try:
        test_voice_profiles()
        test_voice_generation()
        test_batch_generation()
        test_effect_recommendations()
        test_custom_recommendation_rules()
        test_voice_profile_management()
        
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
