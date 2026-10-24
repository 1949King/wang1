"""
综合性能测试套件
测试系统各模块的性能表现
"""

import os
import sys
import time
import psutil
import threading
import numpy as np
from typing import Dict, Any, List
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.plugin_hotloader import PluginManager
from app.core.multitrack_editor import MultiTrackEditor, EditMode
from app.core.audio_processor import AudioProcessor, BGMBeatDetector
from app.core.ai_editing_assistant import AIEditingAssistant
from app.core.music_recommendation import MusicRecommendationEngine
from app.core.subtitle_generator import SubtitleGenerator
from app.core.voice_generator import AIVoiceGenerator


class PerformanceMetrics:
    """性能指标收集器"""
    
    def __init__(self):
        self.metrics = defaultdict(list)
        self.start_times = {}
    
    def start_timer(self, name: str):
        """开始计时"""
        self.start_times[name] = time.time()
    
    def end_timer(self, name: str):
        """结束计时"""
        if name in self.start_times:
            elapsed = time.time() - self.start_times[name]
            self.metrics[name].append(elapsed)
            return elapsed
        return 0
    
    def record_memory(self, name: str):
        """记录内存使用"""
        process = psutil.Process(os.getpid())
        memory_mb = process.memory_info().rss / 1024 / 1024
        self.metrics[f"{name}_memory"].append(memory_mb)
        return memory_mb
    
    def get_statistics(self, name: str) -> Dict[str, float]:
        """获取统计信息"""
        values = self.metrics[name]
        if not values:
            return {}
        
        return {
            "count": len(values),
            "mean": np.mean(values),
            "std": np.std(values),
            "min": np.min(values),
            "max": np.max(values),
            "median": np.median(values)
        }
    
    def print_summary(self):
        """打印性能摘要"""
        print("\n" + "="*60)
        print("性能测试摘要")
        print("="*60)
        
        for name in sorted(self.metrics.keys()):
            if "_memory" in name:
                continue
            
            stats = self.get_statistics(name)
            if stats:
                print(f"\n{name}:")
                print(f"  次数: {stats['count']}")
                print(f"  平均: {stats['mean']:.4f}s")
                print(f"  最小: {stats['min']:.4f}s")
                print(f"  最大: {stats['max']:.4f}s")
                print(f"  标准差: {stats['std']:.4f}s")
                
                memory_stats = self.get_statistics(f"{name}_memory")
                if memory_stats:
                    print(f"  平均内存: {memory_stats['mean']:.2f}MB")
                    print(f"  最大内存: {memory_stats['max']:.2f}MB")


def test_plugin_loading_performance(metrics: PerformanceMetrics):
    """测试插件加载性能"""
    print("\n" + "="*50)
    print("测试插件加载性能")
    print("="*50)
    
    manager = PluginManager()
    plugins_dir = os.path.join(os.path.dirname(__file__), "app", "plugins")
    manager.add_plugin_dir(plugins_dir)
    
    for i in range(5):
        print(f"\n第 {i+1} 次测试...")
        
        metrics.start_timer("plugin_discovery")
        discovered = manager.discover_plugins()
        discovery_time = metrics.end_timer("plugin_discovery")
        
        metrics.record_memory("plugin_discovery")
        
        print(f"  发现插件: {len(discovered)} 个")
        print(f"  耗时: {discovery_time:.4f}s")
        
        metrics.start_timer("plugin_loading")
        for plugin_info in discovered:
            manager.load_plugin(plugin_info.id)
        loading_time = metrics.end_timer("plugin_loading")
        
        metrics.record_memory("plugin_loading")
        
        print(f"  加载耗时: {loading_time:.4f}s")
        print(f"  总耗时: {discovery_time + loading_time:.4f}s")
    
    print("✓ 插件加载性能测试完成")


def test_multitrack_performance(metrics: PerformanceMetrics):
    """测试多轨道编辑性能"""
    print("\n" + "="*50)
    print("测试多轨道编辑性能")
    print("="*50)
    
    editor = MultiTrackEditor()
    
    for i in range(5):
        print(f"\n第 {i+1} 次测试...")
        
        metrics.start_timer("track_creation")
        track_ids = []
        for j in range(10):
            track = editor.create_track(f"Track {j+1}", "video")
            track_ids.append(track.id)
        creation_time = metrics.end_timer("track_creation")
        
        metrics.record_memory("track_creation")
        
        print(f"  创建轨道: {len(track_ids)} 个")
        print(f"  耗时: {creation_time:.4f}s")
        
        metrics.start_timer("clip_operations")
        for track_id in track_ids:
            for j in range(5):
                clip_id = editor.create_clip(
                    track_id,
                    f"clip_{j}",
                    f"media_{j}.mp4",
                    start=j * 10.0,
                    end=j * 10.0 + 5.0
                )
                editor.move_clip(clip_id, 1.0)
        operations_time = metrics.end_timer("clip_operations")
        
        metrics.record_memory("clip_operations")
        
        print(f"  添加片段: {len(track_ids) * 5} 个")
        print(f"  操作耗时: {operations_time:.4f}s")
        
        metrics.start_timer("edit_modes")
        editor.set_edit_mode(EditMode.RIPPLE)
        for track_id in track_ids[:3]:
            track = editor.get_track(track_id)
            if track and track.clips:
                editor.move_clip(track.clips[0].id, 2.0)
        edit_modes_time = metrics.end_timer("edit_modes")
        
        metrics.record_memory("edit_modes")
        
        print(f"  编辑模式操作耗时: {edit_modes_time:.4f}s")
        
        editor.clear_all()
    
    print("✓ 多轨道编辑性能测试完成")


def test_audio_processing_performance(metrics: PerformanceMetrics):
    """测试音频处理性能"""
    print("\n" + "="*50)
    print("测试音频处理性能")
    print("="*50)
    
    processor = AudioProcessor()
    beat_detector = BGMBeatDetector()
    
    for i in range(5):
        print(f"\n第 {i+1} 次测试...")
        
        sample_rate = 44100
        duration = 10.0
        audio_data = np.random.randn(int(sample_rate * duration)).astype(np.float32)
        
        metrics.start_timer("beat_detection")
        beats = beat_detector.detect_beats(audio_data, sample_rate)
        detection_time = metrics.end_timer("beat_detection")
        
        metrics.record_memory("beat_detection")
        
        print(f"  检测节拍: {len(beats)} 个")
        print(f"  耗时: {detection_time:.4f}s")
        
        metrics.start_timer("voice_cleanup")
        cleaned = processor.remove_mouth_sounds(audio_data, sample_rate)
        cleanup_time = metrics.end_timer("voice_cleanup")
        
        metrics.record_memory("voice_cleanup")
        
        print(f"  语音清理耗时: {cleanup_time:.4f}s")
        
        metrics.start_timer("voice_changing")
        changed = processor.apply_voice_change(audio_data, sample_rate, "male_normal")
        changing_time = metrics.end_timer("voice_changing")
        
        metrics.record_memory("voice_changing")
        
        print(f"  变声处理耗时: {changing_time:.4f}s")
    
    print("✓ 音频处理性能测试完成")


def test_ai_features_performance(metrics: PerformanceMetrics):
    """测试AI功能性能"""
    print("\n" + "="*50)
    print("测试AI功能性能")
    print("="*50)
    
    ai_assistant = AIEditingAssistant()
    music_engine = MusicRecommendationEngine()
    
    for i in range(5):
        print(f"\n第 {i+1} 次测试...")
        
        metrics.start_timer("scene_analysis")
        frames = [np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8) 
                 for _ in range(10)]
        result = ai_assistant.analyze_video(frames)
        analysis_time = metrics.end_timer("scene_analysis")
        
        metrics.record_memory("scene_analysis")
        
        print(f"  分析场景: {result.get('total_scenes', 0)} 个")
        print(f"  耗时: {analysis_time:.4f}s")
        
        metrics.start_timer("music_recommendation")
        from app.core.music_recommendation import SceneMusicRequirement
        requirement = SceneMusicRequirement(
            scene_type="emotion",
            emotion="happy",
            duration=30.0,
            min_bpm=90,
            max_bpm=120
        )
        recommendations = music_engine.recommend_music(requirement)
        recommendation_time = metrics.end_timer("music_recommendation")
        
        metrics.record_memory("music_recommendation")
        
        print(f"  推荐音乐: {len(recommendations)} 首")
        print(f"  耗时: {recommendation_time:.4f}s")
    
    print("✓ AI功能性能测试完成")


def test_concurrent_performance(metrics: PerformanceMetrics):
    """测试并发性能"""
    print("\n" + "="*50)
    print("测试并发性能")
    print("="*50)
    
    def worker(worker_id: int, results: List):
        """工作线程"""
        editor = MultiTrackEditor()
        
        start_time = time.time()
        
        for i in range(10):
            track = editor.create_track(f"Worker{worker_id}_Track{i}", "video")
            for j in range(5):
                editor.create_clip(track.id, f"clip_{j}", f"media_{j}.mp4", j * 10.0, j * 10.0 + 5.0)
        
        elapsed = time.time() - start_time
        results.append(elapsed)
    
    for i in range(5):
        print(f"\n第 {i+1} 次测试...")
        
        metrics.start_timer("concurrent_operations")
        
        results = []
        threads = []
        for j in range(4):
            thread = threading.Thread(target=worker, args=(j, results))
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        concurrent_time = metrics.end_timer("concurrent_operations")
        
        metrics.record_memory("concurrent_operations")
        
        print(f"  并发线程: {len(threads)} 个")
        print(f"  平均耗时: {np.mean(results):.4f}s")
        print(f"  总耗时: {concurrent_time:.4f}s")
    
    print("✓ 并发性能测试完成")


def test_memory_leak(metrics: PerformanceMetrics):
    """测试内存泄漏"""
    print("\n" + "="*50)
    print("测试内存泄漏")
    print("="*50)
    
    memory_usage = []
    
    for i in range(10):
        print(f"\n第 {i+1} 次迭代...")
        
        editor = MultiTrackEditor()
        processor = AudioProcessor()
        
        for j in range(5):
            track = editor.create_track(f"Track_{j}", "video")
            editor.create_clip(track.id, f"clip_{j}", f"media_{j}.mp4", j * 10.0, j * 10.0 + 5.0)
        
        audio_data = np.random.randn(441000).astype(np.float32)
        processor.remove_mouth_sounds(audio_data, 44100)
        
        process = psutil.Process(os.getpid())
        memory_mb = process.memory_info().rss / 1024 / 1024
        memory_usage.append(memory_mb)
        
        print(f"  内存使用: {memory_mb:.2f}MB")
        
        del editor
        del processor
        del audio_data
    
    memory_growth = memory_usage[-1] - memory_usage[0]
    print(f"\n内存增长: {memory_growth:.2f}MB")
    
    if memory_growth < 50:
        print("✓ 内存泄漏测试通过（内存增长在正常范围内）")
    else:
        print("⚠ 内存泄漏测试警告（内存增长较大）")


def run_all_performance_tests():
    """运行所有性能测试"""
    print("\n" + "="*60)
    print("ShortPlayAI Engine V1.0 - 综合性能测试")
    print("="*60)
    
    metrics = PerformanceMetrics()
    
    try:
        test_plugin_loading_performance(metrics)
        test_multitrack_performance(metrics)
        test_audio_processing_performance(metrics)
        test_ai_features_performance(metrics)
        test_concurrent_performance(metrics)
        test_memory_leak(metrics)
        
        metrics.print_summary()
        
        print("\n" + "="*60)
        print("✓ 所有性能测试完成!")
        print("="*60)
        
    except Exception as e:
        print(f"\n✗ 性能测试异常: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    run_all_performance_tests()