# trend.py
import matplotlib.pyplot as plt
from models import get_snapshots

def show_trend(platform: str, video_id: str):
    snaps = get_snapshots(platform=platform, video_id=video_id)
    snaps.sort(key=lambda x: x.created_at)  # 按时间排序

    times = [s.created_at for s in snaps]
    plays = [s.play_count for s in snaps]

    plt.rcParams["font.sans-serif"] = ["SimHei"]
    plt.plot(times, plays, marker=".")
    plt.title(f"{platform} {video_id} 播放量趋势")
    plt.xlabel("时间")
    plt.ylabel("播放量")
    plt.xticks(rotation=30)
    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    show_trend("douyin", "7351269870012312345")
