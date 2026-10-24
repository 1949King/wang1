# monitor_service.py
from datetime import datetime
import requests
from app.modules.lego.data_collector import DataCollector
from models import VideoSnapshot, save_snapshot, get_snapshots
from config import BACKEND_PUSH_URL

collector = DataCollector()

def fetch_single_video(platform: str, video_id: str):
    """采集单条视频数据"""
    try:
        # 初始化采集器
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def collect():
            await collector.initialize()
            data = await collector.collect_video_data(platform, video_id)
            await collector.close()
            return data
        
        data = loop.run_until_complete(collect())
        loop.close()
        
        return {
            "play_count": data.get("views", 0),
            "digg_count": data.get("likes", 0),
            "comment_count": data.get("comments", 0),
            "share_count": data.get("shares", 0),
            "timestamp": datetime.now()
        }
    except Exception as e:
        print(f"采集失败 {platform} {video_id}: {e}")
        return None

def push_to_backend(snap: VideoSnapshot):
    """推送给后端接口"""
    payload = {
        "platform": snap.platform,
        "video_id": snap.video_id,
        "play_count": snap.play_count,
        "digg_count": snap.digg_count,
        "comment_count": snap.comment_count,
        "share_count": snap.share_count,
        "created_at": snap.created_at.isoformat()
    }
    try:
        requests.post(BACKEND_PUSH_URL, json=payload, timeout=5)
    except Exception as e:
        print("推送失败", e)

def monitor_task():
    """定时任务主体"""
    # 你要监控的视频列表
    target_videos = [
        {"platform": "douyin", "video_id": "7351269870012312345"},
        {"platform": "kuaishou", "video_id": "3xq6k7a..."},
    ]

    for item in target_videos:
        stats = fetch_single_video(item["platform"], item["video_id"])
        if not stats:
            continue

        snap = VideoSnapshot(
            platform=item["platform"],
            video_id=item["video_id"],
            play_count=stats["play_count"],
            digg_count=stats["digg_count"],
            comment_count=stats["comment_count"],
            share_count=stats["share_count"]
        )
        save_snapshot(snap)

        # 实时回传给业务端
        push_to_backend(snap)
