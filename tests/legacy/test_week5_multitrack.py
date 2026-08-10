"""
多轨道编辑器测试
测试多轨道编辑功能
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.multitrack_editor import (
    TrackType, TrackState, EditMode, ClipState,
    Track, Clip, Marker, TrackGroup, MultiTrackEditor
)


def test_track_creation():
    """测试轨道创建"""
    print("\n" + "="*50)
    print("测试轨道创建")
    print("="*50)
    
    editor = MultiTrackEditor()
    
    print(f"创建视频轨道...")
    video_track = editor.create_track("视频轨道1", TrackType.VIDEO)
    assert video_track is not None
    assert video_track.track_type == TrackType.VIDEO
    assert video_track.index == 0
    
    print(f"创建音频轨道...")
    audio_track = editor.create_track("音频轨道1", TrackType.AUDIO)
    assert audio_track is not None
    assert audio_track.track_type == TrackType.AUDIO
    assert audio_track.index == 1
    
    print(f"获取轨道列表...")
    tracks = editor.get_tracks()
    assert len(tracks) == 2
    
    print(f"按类型获取轨道...")
    video_tracks = editor.get_tracks(TrackType.VIDEO)
    assert len(video_tracks) == 1
    
    print("✓ 轨道创建测试通过")


def test_track_operations():
    """测试轨道操作"""
    print("\n" + "="*50)
    print("测试轨道操作")
    print("="*50)
    
    editor = MultiTrackEditor()
    track = editor.create_track("测试轨道", TrackType.VIDEO)
    
    print(f"锁定轨道...")
    editor.lock_track(track.id)
    assert track.locked == True
    assert track.state == TrackState.LOCKED
    
    print(f"解锁轨道...")
    editor.unlock_track(track.id)
    assert track.locked == False
    assert track.state == TrackState.NORMAL
    
    print(f"静音轨道...")
    editor.mute_track(track.id)
    assert track.muted == True
    assert track.state == TrackState.MUTED
    
    print(f"取消静音...")
    editor.unmute_track(track.id)
    assert track.muted == False
    
    print(f"隐藏轨道...")
    editor.hide_track(track.id)
    assert track.visible == False
    assert track.state == TrackState.HIDDEN
    
    print(f"显示轨道...")
    editor.show_track(track.id)
    assert track.visible == True
    
    print(f"设置独奏...")
    editor.set_track_solo(track.id, True)
    assert track.solo == True
    
    print("✓ 轨道操作测试通过")


def test_clip_creation():
    """测试片段创建"""
    print("\n" + "="*50)
    print("测试片段创建")
    print("="*50)
    
    editor = MultiTrackEditor()
    track = editor.create_track("视频轨道", TrackType.VIDEO)
    
    print(f"创建片段...")
    clip = editor.create_clip(
        track_id=track.id,
        name="测试片段",
        media_path="test.mp4",
        start=0.0,
        end=10.0,
        source_start=0.0,
        source_end=10.0
    )
    
    assert clip is not None
    assert clip.track_id == track.id
    assert clip.start == 0.0
    assert clip.end == 10.0
    assert clip.duration == 10.0
    
    print(f"获取片段...")
    retrieved_clip = editor.get_clip(clip.id)
    assert retrieved_clip is not None
    assert retrieved_clip.id == clip.id
    
    print(f"获取轨道片段...")
    track_clip = track.get_clip(clip.id)
    assert track_clip is not None
    assert track_clip.id == clip.id
    
    print("✓ 片段创建测试通过")


def test_clip_operations():
    """测试片段操作"""
    print("\n" + "="*50)
    print("测试片段操作")
    print("="*50)
    
    editor = MultiTrackEditor()
    track = editor.create_track("视频轨道", TrackType.VIDEO)
    
    clip = editor.create_clip(
        track_id=track.id,
        name="测试片段",
        media_path="test.mp4",
        start=0.0,
        end=10.0,
        source_start=0.0,
        source_end=10.0
    )
    
    print(f"移动片段...")
    editor.move_clip(clip.id, 5.0)
    assert clip.start == 5.0
    assert clip.end == 15.0
    
    print(f"调整片段大小...")
    editor.resize_clip(clip.id, 15.0, anchor="start")
    assert clip.duration == 15.0
    assert clip.end == 20.0
    
    print(f"裁剪片段...")
    editor.trim_clip(clip.id, new_start=7.0, new_end=17.0)
    assert clip.start == 7.0
    assert clip.end == 17.0
    
    print(f"选择片段...")
    editor.select_clip(clip.id, True)
    assert clip.selected == True
    assert len(editor.get_selected_clips()) == 1
    
    print(f"取消选择...")
    editor.select_clip(clip.id, False)
    assert clip.selected == False
    assert len(editor.get_selected_clips()) == 0
    
    print("✓ 片段操作测试通过")


def test_clip_split():
    """测试片段分割"""
    print("\n" + "="*50)
    print("测试片段分割")
    print("="*50)
    
    editor = MultiTrackEditor()
    track = editor.create_track("视频轨道", TrackType.VIDEO)
    
    clip = editor.create_clip(
        track_id=track.id,
        name="测试片段",
        media_path="test.mp4",
        start=0.0,
        end=10.0,
        source_start=0.0,
        source_end=10.0
    )
    
    print(f"在位置5.0分割片段...")
    left_id, right_id = editor.split_clip(clip.id, 5.0)
    
    assert left_id is not None
    assert right_id is not None
    
    left_clip = editor.get_clip(left_id)
    right_clip = editor.get_clip(right_id)
    
    assert left_clip is not None
    assert right_clip is not None
    
    assert left_clip.start == 0.0
    assert left_clip.end == 5.0
    assert right_clip.start == 5.0
    assert right_clip.end == 10.0
    
    print(f"原始片段已删除...")
    assert editor.get_clip(clip.id) is None
    
    print("✓ 片段分割测试通过")


def test_edit_modes():
    """测试编辑模式"""
    print("\n" + "="*50)
    print("测试编辑模式")
    print("="*50)
    
    editor = MultiTrackEditor()
    
    track1 = editor.create_track("视频轨道1", TrackType.VIDEO)
    
    clip1 = editor.create_clip(
        track_id=track1.id,
        name="片段1",
        media_path="test1.mp4",
        start=0.0,
        end=10.0,
        source_start=0.0,
        source_end=10.0
    )
    
    clip2 = editor.create_clip(
        track_id=track1.id,
        name="片段2",
        media_path="test2.mp4",
        start=10.0,
        end=20.0,
        source_start=0.0,
        source_end=10.0
    )
    
    print(f"测试普通编辑模式...")
    editor.set_edit_mode(EditMode.NORMAL)
    editor.move_clip(clip1.id, 2.0)
    assert clip1.start == 2.0
    assert clip2.start == 10.0  # 不受影响
    
    print(f"测试波纹编辑模式...")
    clip1.start = 0.0
    clip1.end = 10.0
    clip2.start = 10.0
    clip2.end = 20.0
    
    editor.set_edit_mode(EditMode.RIPPLE)
    editor.move_clip(clip1.id, 2.0)
    assert clip1.start == 2.0
    assert clip2.start == 12.0  # 被波纹影响
    
    print(f"测试滚动编辑模式...")
    clip1.start = 2.0
    clip1.end = 12.0
    
    editor.set_edit_mode(EditMode.ROLLING)
    editor.move_clip(clip1.id, 2.0)
    assert clip1.duration == 12.0  # 时长改变
    
    print(f"测试滑动编辑模式...")
    clip1.start = 2.0
    clip1.end = 12.0
    
    editor.set_edit_mode(EditMode.SLIP)
    editor.move_clip(clip1.id, 2.0)
    assert clip1.source_start == 2.0  # 源时间改变
    
    print(f"测试滑移编辑模式...")
    clip1.source_start = 0.0
    clip1.source_end = 10.0
    
    editor.set_edit_mode(EditMode.SLIDE)
    editor.move_clip(clip1.id, 1.0)
    assert clip1.start == 3.0
    assert clip1.source_start == -1.0  # 位置和源时间都改变
    
    print("✓ 编辑模式测试通过")


def test_markers():
    """测试标记"""
    print("\n" + "="*50)
    print("测试标记")
    print("="*50)
    
    editor = MultiTrackEditor()
    
    print(f"添加标记...")
    marker1 = editor.add_marker(5.0, "标记1", "#f39c12", "这是一个标记")
    marker2 = editor.add_marker(10.0, "标记2", "#e74c3c")
    
    assert marker1 is not None
    assert marker2 is not None
    
    print(f"获取标记列表...")
    markers = editor.get_markers()
    assert len(markers) == 2
    assert markers[0].position == 5.0
    assert markers[1].position == 10.0
    
    print(f"获取指定位置的标记...")
    found_marker = editor.get_marker_at(5.0, tolerance=0.1)
    assert found_marker is not None
    assert found_marker.id == marker1.id
    
    print(f"移除标记...")
    editor.remove_marker(marker1.id)
    markers = editor.get_markers()
    assert len(markers) == 1
    
    print("✓ 标记测试通过")


def test_track_groups():
    """测试轨道组"""
    print("\n" + "="*50)
    print("测试轨道组")
    print("="*50)
    
    editor = MultiTrackEditor()
    
    track1 = editor.create_track("视频轨道1", TrackType.VIDEO)
    track2 = editor.create_track("视频轨道2", TrackType.VIDEO)
    track3 = editor.create_track("音频轨道1", TrackType.AUDIO)
    
    print(f"创建轨道组...")
    group = editor.create_track_group("视频组", [track1.id, track2.id])
    
    assert group is not None
    assert len(group.track_ids) == 2
    
    print(f"获取轨道组...")
    retrieved_group = editor.get_track_group(group.id)
    assert retrieved_group is not None
    assert retrieved_group.name == "视频组"
    
    print(f"添加轨道到组...")
    editor.add_track_to_group(group.id, track3.id)
    group = editor.get_track_group(group.id)
    assert len(group.track_ids) == 3
    
    print(f"从组中移除轨道...")
    editor.remove_track_from_group(group.id, track3.id)
    group = editor.get_track_group(group.id)
    assert len(group.track_ids) == 2
    
    print(f"获取所有轨道组...")
    groups = editor.get_track_groups()
    assert len(groups) == 1
    
    print("✓ 轨道组测试通过")


def test_selection():
    """测试选择功能"""
    print("\n" + "="*50)
    print("测试选择功能")
    print("="*50)
    
    editor = MultiTrackEditor()
    track = editor.create_track("视频轨道", TrackType.VIDEO)
    
    clip1 = editor.create_clip(
        track_id=track.id,
        name="片段1",
        media_path="test1.mp4",
        start=0.0,
        end=10.0,
        source_start=0.0,
        source_end=10.0
    )
    
    clip2 = editor.create_clip(
        track_id=track.id,
        name="片段2",
        media_path="test2.mp4",
        start=10.0,
        end=20.0,
        source_start=0.0,
        source_end=10.0
    )
    
    clip3 = editor.create_clip(
        track_id=track.id,
        name="片段3",
        media_path="test3.mp4",
        start=20.0,
        end=30.0,
        source_start=0.0,
        source_end=10.0
    )
    
    print(f"选择多个片段...")
    editor.select_clip(clip1.id, True)
    editor.select_clip(clip2.id, True)
    assert len(editor.get_selected_clips()) == 2
    
    print(f"选择时间范围内的片段...")
    editor.clear_selection()
    count = editor.select_clips_in_range(5.0, 15.0)
    assert count == 2  # clip1和clip2
    
    print(f"清除选择...")
    editor.clear_selection()
    assert len(editor.get_selected_clips()) == 0
    
    print("✓ 选择功能测试通过")


def test_timeline_operations():
    """测试时间轴操作"""
    print("\n" + "="*50)
    print("测试时间轴操作")
    print("="*50)
    
    editor = MultiTrackEditor()
    
    track1 = editor.create_track("视频轨道1", TrackType.VIDEO)
    track2 = editor.create_track("音频轨道1", TrackType.AUDIO)
    
    editor.create_clip(
        track_id=track1.id,
        name="片段1",
        media_path="test1.mp4",
        start=0.0,
        end=10.0,
        source_start=0.0,
        source_end=10.0
    )
    
    editor.create_clip(
        track_id=track2.id,
        name="片段2",
        media_path="test2.mp4",
        start=5.0,
        end=15.0,
        source_start=0.0,
        source_end=10.0
    )
    
    print(f"获取时间轴范围...")
    start, end = editor.get_timeline_range()
    assert start == 0.0
    assert end == 15.0
    
    print(f"获取指定位置的片段...")
    clips_at_7 = editor.get_clips_at(7.0)
    assert len(clips_at_7) == 2
    
    print(f"获取重叠片段...")
    clip1 = track1.clips[0]
    overlapping = editor.get_overlapping_clips(track1.id, clip1)
    assert len(overlapping) == 0
    
    print("✓ 时间轴操作测试通过")


def test_statistics():
    """测试统计信息"""
    print("\n" + "="*50)
    print("测试统计信息")
    print("="*50)
    
    editor = MultiTrackEditor()
    
    track1 = editor.create_track("视频轨道1", TrackType.VIDEO)
    track2 = editor.create_track("视频轨道2", TrackType.VIDEO)
    track3 = editor.create_track("音频轨道1", TrackType.AUDIO)
    
    editor.create_clip(
        track_id=track1.id,
        name="片段1",
        media_path="test1.mp4",
        start=0.0,
        end=10.0,
        source_start=0.0,
        source_end=10.0
    )
    
    editor.create_clip(
        track_id=track2.id,
        name="片段2",
        media_path="test2.mp4",
        start=10.0,
        end=20.0,
        source_start=0.0,
        source_end=10.0
    )
    
    editor.add_marker(5.0, "标记1")
    editor.create_track_group("视频组", [track1.id, track2.id])
    
    print(f"获取统计信息...")
    stats = editor.get_statistics()
    
    assert stats["total_tracks"] == 3
    assert stats["total_clips"] == 2
    assert stats["total_duration"] == 20.0
    assert stats["total_markers"] == 1
    assert stats["total_groups"] == 1
    assert stats["by_type"]["video"] == 2
    assert stats["by_type"]["audio"] == 1
    
    print("✓ 统计信息测试通过")


def test_complex_scenario():
    """测试复杂场景"""
    print("\n" + "="*50)
    print("测试复杂场景")
    print("="*50)
    
    editor = MultiTrackEditor()
    
    print(f"创建多个轨道...")
    video_track1 = editor.create_track("主视频", TrackType.VIDEO)
    video_track2 = editor.create_track("叠加视频", TrackType.VIDEO)
    audio_track1 = editor.create_track("背景音乐", TrackType.AUDIO)
    audio_track2 = editor.create_track("音效", TrackType.AUDIO)
    
    print(f"添加多个片段...")
    main_clip = editor.create_clip(
        track_id=video_track1.id,
        name="主片段",
        media_path="main.mp4",
        start=0.0,
        end=30.0,
        source_start=0.0,
        source_end=30.0
    )
    
    overlay_clip = editor.create_clip(
        track_id=video_track2.id,
        name="叠加片段",
        media_path="overlay.mp4",
        start=5.0,
        end=15.0,
        source_start=0.0,
        source_end=10.0
    )
    
    bgm_clip = editor.create_clip(
        track_id=audio_track1.id,
        name="背景音乐",
        media_path="bgm.mp3",
        start=0.0,
        end=30.0,
        source_start=0.0,
        source_end=30.0
    )
    
    print(f"分割主片段...")
    left_id, right_id = editor.split_clip(main_clip.id, 15.0)
    
    print(f"添加标记...")
    editor.add_marker(15.0, "分割点", "#e74c3c")
    editor.add_marker(5.0, "叠加开始", "#3498db")
    editor.add_marker(15.0, "叠加结束", "#3498db")
    
    print(f"创建轨道组...")
    video_group = editor.create_track_group("视频轨道组", [video_track1.id, video_track2.id])
    audio_group = editor.create_track_group("音频轨道组", [audio_track1.id, audio_track2.id])
    
    print(f"选择片段...")
    editor.select_clip(left_id, True)
    editor.select_clip(overlay_clip.id, True)
    
    print(f"获取统计信息...")
    stats = editor.get_statistics()
    
    assert stats["total_tracks"] == 4
    assert stats["total_clips"] == 4  # 分割后变成4个片段
    assert stats["selected_clips"] == 2
    
    print(f"时间轴范围: {editor.get_timeline_range()}")
    print(f"标记数量: {len(editor.get_markers())}")
    print(f"轨道组数量: {len(editor.get_track_groups())}")
    
    print("✓ 复杂场景测试通过")


def run_all_tests():
    """运行所有测试"""
    print("\n" + "="*60)
    print("多轨道编辑器测试套件")
    print("="*60)
    
    try:
        test_track_creation()
        test_track_operations()
        test_clip_creation()
        test_clip_operations()
        test_clip_split()
        test_edit_modes()
        test_markers()
        test_track_groups()
        test_selection()
        test_timeline_operations()
        test_statistics()
        test_complex_scenario()
        
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
