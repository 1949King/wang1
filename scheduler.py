# scheduler.py
import sched
import time
from monitor_service import monitor_task
from config import MONITOR_INTERVAL_MINUTES

def start_monitor():
    scheduler = sched.scheduler(time.time, time.sleep)
    
    def schedule_task():
        """调度任务"""
        try:
            monitor_task()
        except Exception as e:
            print(f"执行监控任务失败: {e}")
        finally:
            # 再次调度下一次任务
            scheduler.enter(MONITOR_INTERVAL_MINUTES * 60, 1, schedule_task)
    
    # 立即执行一次任务
    scheduler.enter(0, 1, schedule_task)
    print("视频监控任务已启动，间隔：{} 分钟".format(MONITOR_INTERVAL_MINUTES))
    
    try:
        scheduler.run()
    except KeyboardInterrupt:
        print("监控任务已停止")

if __name__ == "__main__":
    start_monitor()
