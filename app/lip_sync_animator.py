import os
import numpy as np
import cv2
from moviepy.editor import VideoFileClip, AudioFileClip

# --- ASR 导入逻辑：优先 faster-whisper，回退到原版 whisper ---
try:
    import faster_whisper
    ASR_ENGINE = "faster_whisper"
    print("🔧 成功导入 faster-whisper 作为ASR引擎。")
except ImportError as e:
    print(f"❌ 未能导入 faster-whisper: {e}")
    try:
        import whisper
        ASR_ENGINE = "original_whisper"
        print("⚠️  使用原版 whisper 作为ASR引擎。")
    except ImportError:
        ASR_ENGINE = None
        print("❌ ASR引擎均不可用 (faster-whisper, whisper)。")
        print("   提示: 请安装其中之一，例如 'pip install faster-whisper'。")
# --- End of ASR Import Logic ---

import tempfile
import logging

# --- 日志设置 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class LipSyncAnimator:
    def __init__(self, asr_model_size="base"):
        """
        初始化嘴型同步动画器。
        Args:
            asr_model_size (str): ASR模型大小。
        """
        if ASR_ENGINE is None:
            logger.error("无法初始化 LipSyncAnimator，因为没有可用的ASR引擎。")
            self.asr_model = None
            return

        logger.info(f"正在加载 {ASR_ENGINE} ASR 模型 ({asr_model_size})...")
        if ASR_ENGINE == "faster_whisper":
            self.asr_model = faster_whisper.WhisperModel(model_size_or_path=asr_model_size, device="cpu", compute_type="int8")
        else: # original_whisper
            self.asr_model = whisper.load_model(asr_model_size, device="cpu")
        logger.info("ASR 模型加载完成。")
        # 这里可以加载其他用于嘴型动画的模型，例如 Wav2Lip, SadTalker 等。
        # 由于这些模型的集成较为复杂，此处我们使用一个模拟的动画函数。

    def _simulate_lip_sync(self, face_region, audio_array, sample_rate, aligned_text):
        """
        模拟嘴型同步动画的实现。
        基于音频的音量变化来模拟嘴部的张合效果。
        """
        # 注意：aligned_text 包含了时间戳信息，可以用来精确定位发音阶段
        logger.info(f"模拟嘴型动画处理，音频长度: {len(audio_array)/sample_rate:.2f}s, 文本: '{aligned_text[:50]}...'")
        
        # 计算需要生成的帧数
        fps = 25
        num_frames = int((len(audio_array) / sample_rate) * fps)
        logger.info(f"需要生成 {num_frames} 帧")
        
        # 计算每帧对应的音频样本数
        samples_per_frame = int(len(audio_array) / num_frames)
        
        # 计算音频的音量变化
        volumes = []
        for i in range(num_frames):
            start = i * samples_per_frame
            end = min(start + samples_per_frame, len(audio_array))
            frame_audio = audio_array[start:end]
            # 计算音量（均方根）
            if len(frame_audio) > 0:
                if len(frame_audio.shape) > 1:
                    # 立体声音频，取平均值
                    volume = np.sqrt(np.mean(np.square(frame_audio), axis=0)).mean()
                else:
                    # 单声道音频
                    volume = np.sqrt(np.mean(np.square(frame_audio)))
            else:
                volume = 0
            volumes.append(volume)
        
        # 归一化音量
        max_volume = max(volumes) if volumes else 1
        normalized_volumes = [v / max_volume for v in volumes]
        
        # 生成动画帧
        animated_frames = []
        for i in range(num_frames):
            # 复制原始帧
            frame = face_region.copy()
            
            # 根据音量计算嘴部张合程度
            mouth_openness = normalized_volumes[i]
            
            # 在面部中央绘制一个简单的嘴巴形状
            # 注意：这只是一个演示，实际应用中需要更精确的嘴部定位
            height, width = frame.shape[:2]
            mouth_center = (width // 2, height // 2 + height // 4)
            mouth_radius = int(min(width, height) * 0.1 * (0.3 + mouth_openness * 0.7))
            
            # 绘制嘴巴
            cv2.circle(frame, mouth_center, mouth_radius, (0, 0, 0), -1)
            
            # 添加一些细节
            inner_radius = int(mouth_radius * 0.7)
            cv2.circle(frame, mouth_center, inner_radius, (255, 0, 0), -1)
            
            animated_frames.append(frame)
        
        logger.info(f"嘴型动画生成完成，共 {len(animated_frames)} 帧")
        return animated_frames

    def _extract_face(self, video_path):
        """
        提取面部区域，使用OpenCV的Haar级联分类器进行人脸检测。
        如果检测不到人脸，则回退到中心裁剪方法。
        """
        logger.info("正在提取面部区域...")
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logger.error(f"无法打开视频文件: {video_path}")
            return None
        
        # 读取视频的前几帧，尝试检测人脸
        face_detected = False
        face_region = None
        
        # 尝试加载Haar级联分类器
        face_cascade = None
        try:
            # 使用OpenCV内置的Haar级联分类器
            face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
            logger.info("成功加载人脸检测器")
        except Exception as e:
            logger.warning(f"加载人脸检测器失败: {e}，将使用中心裁剪方法")
        
        # 尝试在前10帧中检测人脸
        for _ in range(10):
            ret, frame = cap.read()
            if not ret:
                break
            
            if face_cascade:
                # 转换为灰度图像
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                
                # 检测人脸
                faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
                
                if len(faces) > 0:
                    # 选择最大的人脸
                    (x, y, w, h) = max(faces, key=lambda rect: rect[2] * rect[3])
                    
                    # 扩展区域以包含完整的头部
                    padding = int(min(w, h) * 0.2)
                    height, width = frame.shape[:2]
                    x = max(0, x - padding)
                    y = max(0, y - padding)
                    w = min(width - x, w + 2 * padding)
                    h = min(height - y, h + 2 * padding)
                    
                    # 确保宽高相等，便于后续处理
                    size = min(w, h)
                    x_center = x + w // 2
                    y_center = y + h // 2
                    x = max(0, x_center - size // 2)
                    y = max(0, y_center - size // 2)
                    size = min(size, width - x, height - y)
                    
                    face_region = frame[y:y+size, x:x+size]
                    face_detected = True
                    logger.info(f"成功检测到人脸，区域尺寸: {face_region.shape}")
                    break
        
        # 如果没有检测到人脸，使用中心裁剪方法
        if not face_detected:
            logger.warning("未检测到人脸，使用中心裁剪方法")
            ret, frame = cap.read()
            if not ret:
                logger.error("无法读取视频帧")
                cap.release()
                return None
            
            height, width = frame.shape[:2]
            # 中心裁剪，这里假设人脸在中央
            crop_width = min(width, height)
            crop_height = crop_width
            start_x = (width - crop_width) // 2
            start_y = (height - crop_height) // 2
            
            face_region = frame[start_y:start_y+crop_height, start_x:start_x+crop_width]
            logger.info(f"中心裁剪的面部区域尺寸: {face_region.shape}")
        
        cap.release()
        return face_region

    def animate_lips(self, reference_video_path, audio_path, output_path, fallback_text_if_no_asr=None):
        """
        执行嘴型同步动画。
        Args:
            reference_video_path (str): 参考视频路径，从中提取面部。
            audio_path (str): 驱动嘴型同步的音频路径。
            output_path (str): 输出视频路径。
            fallback_text_if_no_asr (str, optional): 如果ASR失败，使用的备用文本。
        """
        if self.asr_model is None:
            logger.error("ASR模型未加载，无法进行嘴型同步。")
            return

        logger.info(f"开始嘴型同步动画: 视频={reference_video_path}, 音频={audio_path}")

        # 1. ASR: 从音频中提取文本
        logger.info("步骤 1: 使用 Whisper 进行 ASR...")
        asr_text = ""
        asr_segments = []
        try:
            if ASR_ENGINE == "faster_whisper":
                segments, info = self.asr_model.transcribe(audio_path, beam_size=5, language="zh")
                asr_text = "".join([segment.text for segment in segments])
                asr_segments = [{"start": s.start, "end": s.end, "text": s.text} for s in segments]
            else: # original_whisper
                result = self.asr_model.transcribe(audio_path, language="zh")
                asr_text = result["text"].strip()
                asr_segments = result.get("segments", [])
            
            logger.info(f"ASR 识别文本: {asr_text}")
            
            if not asr_text:
                 logger.warning("ASR 未识别出任何文本。")
                 if not fallback_text_if_no_asr:
                      logger.error("没有提供备用文本，无法进行嘴型同步。")
                      return
                 asr_text = fallback_text_if_no_asr
                 # 如果没有ASR结果，手动创建一个覆盖整个音频时长的段落
                 audio_duration = AudioFileClip(audio_path).duration
                 asr_segments = [{"start": 0, "end": audio_duration, "text": asr_text}]
        except Exception as e:
            logger.error(f"ASR 过程出错: {e}")
            if fallback_text_if_no_asr:
                 logger.info("使用备用文本进行处理。")
                 asr_text = fallback_text_if_no_asr
                 audio_duration = AudioFileClip(audio_path).duration
                 asr_segments = [{"start": 0, "end": audio_duration, "text": asr_text}]
            else:
                 logger.error("ASR失败且无备用文本，终止嘴型同步。")
                 return

        # 2. 提取面部
        logger.info("步骤 2: 从参考视频中提取面部区域...")
        face_image = self._extract_face(reference_video_path)
        if face_image is None:
            logger.error("面部提取失败，无法进行嘴型同步。")
            return

        # 3. 加载音频
        logger.info("步骤 3: 加载并处理音频...")
        try:
            audio_clip = AudioFileClip(audio_path)
            audio_array = audio_clip.to_soundarray()
            sample_rate = audio_clip.fps
            audio_clip.close()
        except Exception as e:
            logger.error(f"加载音频失败: {e}")
            return

        # 4. 执行嘴型同步动画
        logger.info("步骤 4: 执行嘴型同步动画...")
        animated_frames = self._simulate_lip_sync(face_image, audio_array, sample_rate, asr_text)
        if not animated_frames:
            logger.error("嘴型动画生成失败。")
            return

        # 5. 保存结果
        logger.info(f"步骤 5: 保存结果到 {output_path}...")
        try:
            # 直接使用moviepy处理整个过程，更高效
            from moviepy.editor import ImageSequenceClip
            
            # 创建图像序列剪辑
            height, width = face_image.shape[:2]
            clip = ImageSequenceClip(animated_frames, fps=25)
            
            # 加载音频
            audio_clip = AudioFileClip(audio_path)
            
            # 调整音频长度以匹配视频
            if audio_clip.duration > clip.duration:
                audio_clip = audio_clip.subclip(0, clip.duration)
            else:
                # 如果音频较短，循环播放直到视频结束
                while audio_clip.duration < clip.duration:
                    audio_clip = audio_clip.set_duration(audio_clip.duration * 2)
                audio_clip = audio_clip.subclip(0, clip.duration)
            
            # 添加音频到视频
            final_clip = clip.set_audio(audio_clip)
            
            # 保存结果
            final_clip.write_videofile(
                output_path,
                codec='libx264',
                audio_codec='aac',
                fps=25,
                preset='medium',  # 平衡速度和质量
                threads=4  # 使用多线程加速
            )
            
            # 清理资源
            clip.close()
            audio_clip.close()
            final_clip.close()
            
            logger.info(f"嘴型同步动画已成功保存到: {output_path}")
        except Exception as e:
            logger.error(f"保存结果失败: {e}")
            return
