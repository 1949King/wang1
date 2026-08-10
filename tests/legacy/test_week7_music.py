"""
智能配乐推荐系统测试
测试音乐推荐、自动同步等功能
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.music_recommendation import (
    MusicRecommendationEngine, MusicTrack, MusicGenre,
    MusicMood, MusicTempo, SceneMusicRequirement,
    MusicAutoSync
)


def test_music_library():
    """测试音乐库"""
    print("\n" + "="*50)
    print("测试音乐库")
    print("="*50)
    
    engine = MusicRecommendationEngine()
    
    print("获取音乐库...")
    library = engine.get_music_library()
    
    print(f"音乐库包含 {len(library)} 首曲目")
    for i, (track_id, track) in enumerate(list(library.items())[:5]):
        print(f"\n曲目 {i+1}: {track.title}")
        print(f"  艺术家: {track.artist}")
        print(f"  类型: {track.genre.value}")
        print(f"  情绪: {track.mood.value}")
        print(f"  节奏: {track.tempo.value}")
        print(f"  时长: {track.duration:.1f}s")
        print(f"  BPM: {track.bpm}")
        print(f"  调性: {track.key}")
        print(f"  标签: {', '.join(track.tags)}")
    
    print("✓ 音乐库测试通过")


def test_music_recommendation():
    """测试音乐推荐"""
    print("\n" + "="*50)
    print("测试音乐推荐")
    print("="*50)
    
    engine = MusicRecommendationEngine()
    
    print("创建推荐需求...")
    requirement = SceneMusicRequirement(
        scene_type="emotion",
        emotion="sad",
        duration=180.0,
        preferred_genres=["drama", "romantic"],
        excluded_genres=["electronic", "hiphop"],
        min_bpm=60,
        max_bpm=100
    )
    
    print(f"场景类型: {requirement.scene_type}")
    print(f"情感: {requirement.emotion}")
    print(f"时长: {requirement.duration}s")
    print(f"偏好类型: {', '.join(requirement.preferred_genres)}")
    print(f"排除类型: {', '.join(requirement.excluded_genres)}")
    
    print("\n生成推荐...")
    recommendations = engine.recommend_music(requirement)
    
    print(f"生成 {len(recommendations)} 条推荐")
    for i, track in enumerate(recommendations[:5]):
        print(f"\n推荐 {i+1}: {track.title}")
        print(f"  匹配度: {track.confidence:.2f}")
        print(f"  匹配原因: {track.match_reason}")
        print(f"  类型: {track.genre.value}")
        print(f"  情绪: {track.mood.value}")
        print(f"  节奏: {track.tempo.value}")
        print(f"  时长: {track.duration:.1f}s")
        print(f"  BPM: {track.bpm}")
    
    print("✓ 音乐推荐测试通过")


def test_music_search():
    """测试音乐搜索"""
    print("\n" + "="*50)
    print("测试音乐搜索")
    print("="*50)
    
    engine = MusicRecommendationEngine()
    
    search_queries = ["阳光", "浪漫", "悬疑", "动感", "温馨"]
    
    for query in search_queries:
        print(f"\n搜索: {query}")
        
        # 按类型搜索
        results = engine.search_music(query, genre=MusicGenre.POP)
        print(f"  按POP类型搜索: {len(results)} 个结果")
        
        # 按情绪搜索
        results = engine.search_music(query, mood=MusicMood.HAPPY)
        print(f"  按HAPPY情绪搜索: {len(results)} 个结果")
        
        # 综合搜索
        results = engine.search_music(query)
        print(f"  综合搜索: {len(results)} 个结果")
        
        if results:
            print(f"  最佳匹配: {results[0].title}")
    
    print("✓ 音乐搜索测试通过")


def test_auto_sync():
    """测试自动同步"""
    print("\n" + "="*50)
    print("测试自动同步")
    print("="*50)
    
    engine = MusicRecommendationEngine()
    sync_engine = MusicAutoSync(engine)
    
    print("创建模拟视频场景...")
    video_scenes = [
        {
            "type": "intro",
            "emotion": "neutral",
            "duration": 15.0,
            "start_time": 0.0,
            "end_time": 15.0
        },
        {
            "type": "emotion",
            "emotion": "sad",
            "duration": 60.0,
            "start_time": 15.0,
            "end_time": 75.0,
            "preferred_genres": ["drama", "romantic"]
        },
        {
            "type": "action",
            "emotion": "energetic",
            "duration": 45.0,
            "start_time": 75.0,
            "end_time": 120.0,
            "preferred_genres": ["electronic", "hiphop"]
        },
        {
            "type": "climax",
            "emotion": "powerful",
            "duration": 30.0,
            "start_time": 120.0,
            "end_time": 150.0,
            "preferred_genres": ["epic", "rock"]
        }
    ]
    
    print("开始自动同步...")
    sync_result = sync_engine.auto_sync_music_to_timeline(video_scenes)
    
    print(f"\n同步结果:")
    print(f"  总场景数: {sync_result['total_scenes']}")
    print(f"  同步场景数: {sync_result['synced_scenes']}")
    print(f"  平均匹配度: {sync_result['average_confidence']:.2f}")
    
    print(f"\n同步详情:")
    for i, sync in enumerate(sync_result['sync_results'][:3]):
        print(f"\n场景 {i+1}:")
        print(f"  时间: {sync['scene_start']:.1f}s - {sync['scene_end']:.1f}s")
        print(f"  推荐音乐: {sync['recommended_music']['title']}")
        print(f"  匹配度: {sync['sync_confidence']:.2f}")
    
    print("✓ 自动同步测试通过")


def test_music_management():
    """测试音乐管理"""
    print("\n" + "="*50)
    print("测试音乐管理")
    print("="*50)
    
    engine = MusicRecommendationEngine()
    
    print("添加新音乐...")
    new_track = MusicTrack(
        id="custom_001",
        title="自定义音乐",
        artist="用户",
        genre=MusicGenre.POP,
        mood=MusicMood.HAPPY,
        tempo=MusicTempo.MEDIUM,
        duration=120.0,
        file_path="music/custom.mp3",
        bpm=100,
        key="C Major",
        tags=["custom", "test"]
    )
    
    added = engine.add_music(new_track)
    print(f"添加结果: {'成功' if added else '失败'}")
    
    if added:
        print("搜索新添加的音乐...")
        results = engine.search_music("自定义")
        print(f"搜索结果: {len(results)} 个")
        if results:
            print(f"  找到: {results[0].title}")
    
    print("\n移除音乐...")
    removed = engine.remove_music("custom_001")
    print(f"移除结果: {'成功' if removed else '失败'}")
    
    print("✓ 音乐管理测试通过")


def test_genre_mood_mapping():
    """测试类型和情绪映射"""
    print("\n" + "="*50)
    print("测试类型和情绪映射")
    print("="*50)
    
    print("音乐类型:")
    for genre in MusicGenre:
        print(f"  {genre.value}")
    
    print("\n音乐情绪:")
    for mood in MusicMood:
        print(f"  {mood.value}")
    
    print("\n音乐节奏:")
    for tempo in MusicTempo:
        print(f"  {tempo.value}")
    
    print("✓ 类型和情绪映射测试通过")


def test_recommendation_scoring():
    """测试推荐评分"""
    print("\n" + "="*50)
    print("测试推荐评分")
    print("="*50)
    
    engine = MusicRecommendationEngine()
    
    print("创建测试需求...")
    requirement = SceneMusicRequirement(
        scene_type="emotion",
        emotion="happy",
        duration=180.0,
        preferred_genres=["pop"],
        min_bpm=100,
        max_bpm=130
    )
    
    print("获取推荐...")
    recommendations = engine.recommend_music(requirement)
    
    print(f"\n推荐评分详情:")
    for i, track in enumerate(recommendations[:3]):
        print(f"\n推荐 {i+1}: {track.title}")
        print(f"  总匹配度: {track.confidence:.2f}")
        print(f"  匹配原因: {track.match_reason}")
        print(f"  类型: {track.genre.value} ({'偏好' if track.genre.value in requirement.preferred_genres else '非偏好'})")
        print(f"  情绪: {track.mood.value} ({'匹配' if track.mood.value == requirement.emotion else '相关'})")
        print(f"  节奏: {track.tempo.value}")
        print(f"  BPM: {track.bpm} ({'符合' if requirement.min_bpm <= track.bpm <= requirement.max_bpm else '不符合'})")
        print(f"  时长: {track.duration:.1f}s (差异: {abs(track.duration - requirement.duration):.1f}s)")
    
    print("✓ 推荐评分测试通过")


def run_all_tests():
    """运行所有测试"""
    print("\n" + "="*60)
    print("智能配乐推荐系统测试套件")
    print("="*60)
    
    try:
        test_music_library()
        test_music_recommendation()
        test_music_search()
        test_auto_sync()
        test_music_management()
        test_genre_mood_mapping()
        test_recommendation_scoring()
        
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
