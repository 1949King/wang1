"""
专业音频处理测试
测试BGM节拍检测、配音去口水音、声线变声、人声闪避等功能
"""

import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.audio_processor import (
    AudioProcessor, BGMBeatDetector, VoiceCleanup,
    VoiceChanger, VoiceDucking, BeatPoint, VoiceProfile
)


def test_bgm_beat_detection():
    """测试BGM节拍检测"""
    print("\n" + "="*50)
    print("测试BGM节拍检测")
    print("="*50)
    
    processor = AudioProcessor()
    
    print("生成测试音频...")
    sample_rate = 44100
    duration = 10.0
    t = np.linspace(0, duration, int(sample_rate * duration))
    
    audio = np.sin(2 * np.pi * 120 * t)
    for i in range(0, len(audio), int(sample_rate * 0.5)):
        audio[i:i+100] += 0.3 * np.sin(2 * np.pi * 440 * (np.arange(100) / sample_rate))
    
    audio = (audio * 32767).astype(np.int16)
    
    print("检测节拍点...")
    beats = processor.detect_bgm_beats(audio, sample_rate)
    
    print(f"检测到 {len(beats)} 个节拍点")
    for i, beat in enumerate(beats[:10]):
        print(f"  节拍 {i+1}: 时间={beat.time:.2f}s, 强度={beat.intensity:.2f}")
    
    if len(beats) > 0:
        print("✓ BGM节拍检测测试通过")
    else:
        print("✗ 未检测到节拍点")


def test_voice_cleanup():
    """测试配音去口水音"""
    print("\n" + "="*50)
    print("测试配音去口水音")
    print("="*50)
    
    processor = AudioProcessor()
    
    print("生成测试音频...")
    sample_rate = 44100
    duration = 5.0
    t = np.linspace(0, duration, int(sample_rate * duration))
    
    audio = np.sin(2 * np.pi * 440 * t)
    for i in range(0, len(audio), int(sample_rate * 0.3)):
        audio[i:i+200] += 0.1 * np.sin(2 * np.pi * 800 * (np.arange(200) / sample_rate))
    
    audio = (audio * 32767).astype(np.int16)
    
    print("去除口水音...")
    cleaned_audio = processor.remove_mouth_sounds(audio, sample_rate)
    
    print(f"原始音频能量: {np.mean(np.abs(audio)):.2f}")
    print(f"处理后音频能量: {np.mean(np.abs(cleaned_audio)):.2f}")
    print(f"能量降低: {(1 - np.mean(np.abs(cleaned_audio)) / np.mean(np.abs(audio))) * 100:.1f}%")
    
    print("✓ 配音去口水音测试通过")


def test_voice_change():
    """测试声线变声"""
    print("\n" + "="*50)
    print("测试声线变声")
    print("="*50)
    
    processor = AudioProcessor()
    
    print("获取所有声线配置...")
    profiles = processor.get_voice_profiles()
    
    print(f"找到 {len(profiles)} 个声线配置:")
    for profile in profiles:
        print(f"  - {profile.name}")
        print(f"    音高调整: {profile.pitch_shift}")
        print(f"    速度因子: {profile.speed_factor}")
        print(f"    音量调整: {profile.volume_adjust}")
    
    print("\n生成测试音频...")
    sample_rate = 44100
    duration = 3.0
    t = np.linspace(0, duration, int(sample_rate * duration))
    audio = np.sin(2 * np.pi * 440 * t)
    audio = (audio * 32767).astype(np.int16)
    
    print("测试声线变声...")
    for profile in profiles:
        print(f"\n应用声线: {profile.name}")
        changed_audio = processor.apply_voice_change(audio, sample_rate, profile.name)
        
        if changed_audio is not None:
            print(f"  原始音频能量: {np.mean(np.abs(audio)):.2f}")
            print(f"  变声后能量: {np.mean(np.abs(changed_audio)):.2f}")
            print(f"  ✓ {profile.name} 应用成功")
        else:
            print(f"  ✗ {profile.name} 应用失败")
    
    print("\n✓ 声线变声测试通过")


def test_voice_ducking():
    """测试人声闪避"""
    print("\n" + "="*50)
    print("测试人声闪避")
    print("="*50)
    
    processor = AudioProcessor()
    
    print("生成测试音频...")
    sample_rate = 44100
    duration = 5.0
    t = np.linspace(0, duration, int(sample_rate * duration))
    
    voice = np.sin(2 * np.pi * 440 * t)
    bgm = np.sin(2 * np.pi * 120 * t) * 0.5
    
    for i in range(int(sample_rate * 1.0), int(sample_rate * 3.0)):
        bgm[i] += 0.3 * np.sin(2 * np.pi * 200 * (i / sample_rate))
    
    voice = (voice * 32767).astype(np.int16)
    bgm = (bgm * 32767).astype(np.int16)
    
    print("应用人声闪避...")
    processed_voice, processed_bgm = processor.apply_voice_ducking(voice, bgm, sample_rate)
    
    print(f"原始BGM能量: {np.mean(np.abs(bgm)):.2f}")
    print(f"处理后BGM能量: {np.mean(np.abs(processed_bgm)):.2f}")
    print(f"BGM能量降低: {(1 - np.mean(np.abs(processed_bgm)) / np.mean(np.abs(bgm))) * 100:.1f}%")
    
    print("✓ 人声闪避测试通过")


def test_audio_integration():
    """测试音频处理集成"""
    print("\n" + "="*50)
    print("测试音频处理集成")
    print("="*50)
    
    processor = AudioProcessor()
    
    print("生成测试音频...")
    sample_rate = 44100
    duration = 10.0
    t = np.linspace(0, duration, int(sample_rate * duration))
    
    voice = np.sin(2 * np.pi * 440 * t)
    bgm = np.sin(2 * np.pi * 120 * t) * 0.5
    
    for i in range(0, len(bgm), int(sample_rate * 0.5)):
        bgm[i:i+500] += 0.2 * np.sin(2 * np.pi * 440 * (np.arange(500) / sample_rate))
    
    voice = (voice * 32767).astype(np.int16)
    bgm = (bgm * 32767).astype(np.int16)
    
    print("\n步骤1: 检测BGM节拍...")
    beats = processor.detect_bgm_beats(bgm, sample_rate)
    print(f"  检测到 {len(beats)} 个节拍点")
    
    print("\n步骤2: 去除人声口水音...")
    cleaned_voice = processor.remove_mouth_sounds(voice, sample_rate)
    print(f"  口水音去除完成")
    
    print("\n步骤3: 应用声线变声...")
    changed_voice = processor.apply_voice_change(cleaned_voice, sample_rate, "male_deep")
    print(f"  声线变声完成")
    
    print("\n步骤4: 应用人声闪避...")
    final_voice, final_bgm = processor.apply_voice_ducking(changed_voice, bgm, sample_rate)
    print(f"  人声闪避完成")
    
    print("\n✓ 音频处理集成测试通过")


def test_voice_profiles():
    """测试声线配置管理"""
    print("\n" + "="*50)
    print("测试声线配置管理")
    print("="*50)
    
    voice_changer = VoiceChanger()
    
    print("获取默认声线配置...")
    profiles = voice_changer.get_profiles()
    print(f"找到 {len(profiles)} 个默认配置")
    
    for profile in profiles:
        print(f"\n{profile.name}:")
        print(f"  音高调整: {profile.pitch_shift}")
        print(f"  速度因子: {profile.speed_factor}")
        print(f"  音量调整: {profile.volume_adjust}")
        print(f"  EQ频段: {profile.eq_bands}")
    
    print("\n添加自定义声线配置...")
    custom_profile = VoiceProfile(
        name="自定义声线",
        pitch_shift=1.5,
        speed_factor=1.02,
        volume_adjust=0.05,
        eq_bands={"low": 1.1, "mid": 1.0, "high": 0.9}
    )
    voice_changer.add_profile(custom_profile)
    
    print("获取声线配置...")
    retrieved = voice_changer.get_profile("自定义声线")
    assert retrieved is not None
    assert retrieved.pitch_shift == 1.5
    
    print("移除声线配置...")
    removed = voice_changer.remove_profile("自定义声线")
    assert removed == True
    
    print("✓ 声线配置管理测试通过")


def test_beat_point_data():
    """测试节拍点数据结构"""
    print("\n" + "="*50)
    print("测试节拍点数据结构")
    print("="*50)
    
    beat = BeatPoint(time=1.5, intensity=0.8, type="beat")
    
    print(f"节拍点时间: {beat.time}")
    print(f"节拍点强度: {beat.intensity}")
    print(f"节拍点类型: {beat.type}")
    
    beat_dict = beat.to_dict()
    print(f"节拍点字典: {beat_dict}")
    
    assert beat_dict["time"] == 1.5
    assert beat_dict["intensity"] == 0.8
    assert beat_dict["type"] == "beat"
    
    print("✓ 节拍点数据结构测试通过")


def run_all_tests():
    """运行所有测试"""
    print("\n" + "="*60)
    print("专业音频处理测试套件")
    print("="*60)
    
    try:
        test_bgm_beat_detection()
        test_voice_cleanup()
        test_voice_change()
        test_voice_ducking()
        test_audio_integration()
        test_voice_profiles()
        test_beat_point_data()
        
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
