import mediapipe as mp
import cv2

print("正在初始化 MediaPipe Pose...")

# 尝试初始化 Pose 模型，这可能会触发模型文件的下载
try:
    mp_pose = mp.solutions.pose
    pose = mp_pose.Pose(
        static_image_mode=False,
        model_complexity=1,
        min_detection_confidence=0.5
    )
    print("MediaPipe Pose 初始化成功！")
    pose.close() # 使用完毕后关闭
except FileNotFoundError as e:
    print(f"MediaPipe Pose 初始化失败，找不到模型文件: {e}")
except Exception as e:
    print(f"MediaPipe Pose 初始化发生其他错误: {e}")

print("测试结束。")