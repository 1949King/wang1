import mediapipe as mp
import os

# 获取 pose 解决方案
mp_pose = mp.solutions.pose

# 尝试获取模型文件路径 (这会失败，但可能给我们线索)
# 检查 pose 模块的源文件位置
print(f"MediaPipe pose 模块位置: {mp_pose.__file__}")
print(f"MediaPipe 根目录: {os.path.dirname(os.path.dirname(mp_pose.__file__))}")

# 检查可能的模型路径
possible_paths = [
    os.path.join(os.path.dirname(os.path.dirname(mp_pose.__file__)), 'modules', 'pose_landmark_full.tflite'),
    os.path.join(os.path.dirname(os.path.dirname(mp_pose.__file__)), 'models', 'pose_landmark_full.tflite'),
]

for path in possible_paths:
    print(f"检查路径: {path} -> 存在: {os.path.exists(path)}")

# 尝试创建一个 Pose 实例，但不指定模型路径，看它默认去哪里找
# 这一步会失败，但可能打印出路径信息
try:
    pose = mp_pose.Pose()
except Exception as e:
    print(f"初始化失败，错误信息: {e}")
    print(f"错误类型: {type(e).__name__}")