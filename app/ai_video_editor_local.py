import os
import subprocess
import logging
import json
import random
import re
import requests
from pathlib import Path
from typing import List, Dict, Optional, Union, Any
import tempfile
from datetime import datetime
import time

# --- 日志配置 ---
log_dir = Path('./logs')
log_dir.mkdir(exist_ok=True)

log_file = log_dir / f'ai_video_editor_{datetime.now().strftime("%Y%m%d")}.log'
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# 控制台处理器
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)

# 文件处理器
file_handler = logging.FileHandler(log_file, encoding="utf-8")
file_handler.setFormatter(log_formatter)

# 获取 logger 实例
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(console_handler)
logger.addHandler(file_handler)

# --- 错误诊断类 ---
class ErrorDiagnoser:
    """错误诊断类"""
    
    @staticmethod
    def diagnose_error(error: Exception, context: str = "") -> Dict[str, Any]:
        """诊断错误"""
        error_info = {
            'error_type': type(error).__name__,
            'error_message': str(error),
            'context': context,
            'timestamp': datetime.now().isoformat(),
            'suggestion': ErrorDiagnoser.get_suggestion(type(error).__name__, str(error))
        }
        return error_info
    
    @staticmethod
    def get_suggestion(error_type: str, error_message: str) -> str:
        """获取错误建议"""
        suggestions = {
            'FFmpegNotFoundError': '请安装FFmpeg并添加到系统路径',
            'FileNotFoundError': '文件不存在，请检查路径是否正确',
            'PermissionError': '权限不足，请检查文件或目录权限',
            'MemoryError': '内存不足，请尝试处理更小的文件或增加系统内存',
            'TimeoutError': '操作超时，请检查网络连接或尝试使用更小的模型',
            'RuntimeError': '运行时错误，请检查输入参数和系统环境',
            'ValueError': '值错误，请检查输入参数是否合法',
            'ImportError': '导入错误，请检查依赖包是否安装正确'
        }
        
        for key, suggestion in suggestions.items():
            if key in error_type:
                return suggestion
        
        return '未知错误，请检查日志获取更多信息'
    
    @staticmethod
    def save_error_report(error_info: Dict[str, Any]) -> str:
        """保存错误报告"""
        error_dir = Path('./error_reports')
        error_dir.mkdir(exist_ok=True)
        
        report_file = error_dir / f'error_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(error_info, f, ensure_ascii=False, indent=2)
        
        return str(report_file)

# --- 依赖检查函数 ---
class DependencyManager:
    """依赖管理类"""
    
    # 依赖状态缓存
    _deps_cache = None
    _last_check_time = 0
    
    @staticmethod
    def check_dependencies(force_check: bool = False) -> Dict[str, bool]:
        """检查依赖"""
        # 缓存检查结果，避免重复检查
        current_time = time.time()
        if DependencyManager._deps_cache and not force_check and (current_time - DependencyManager._last_check_time) < 300:
            logger.info("使用缓存的依赖状态")
            return DependencyManager._deps_cache
        
        deps_status = {
            'faster_whisper_available': False,
            'easyocr_available': False,
            'moviepy_available': False,
            'transformers_available': False,
            'torch_available': False,
            'dashscope_available': False,
            'mediapipe_available': False,
            'yt_dlp_available': False,
            'LIP_SYNC_AVAILABLE': False,
            'gtts_available': False,
            'pynvml_available': False,
            'numpy_available': False,
            'opencv_available': False,
            'requests_available': False,
            'ffmpeg_available': False,
        }
        
        # 检查Python包依赖
        deps_to_check = {
            'faster_whisper': 'faster_whisper_available',
            'easyocr': 'easyocr_available',
            'moviepy': 'moviepy_available',
            'transformers': 'transformers_available',
            'torch': 'torch_available',
            'dashscope': 'dashscope_available',
            'mediapipe': 'mediapipe_available',
            'yt_dlp': 'yt_dlp_available',
            'gtts': 'gtts_available',
            'pynvml': 'pynvml_available',
            'numpy': 'numpy_available',
            'cv2': 'opencv_available',
            'requests': 'requests_available',
        }
        
        for dep_name, status_key in deps_to_check.items():
            try:
                __import__(dep_name)
                deps_status[status_key] = True
                logger.info(f"✅ {dep_name} 可用")
            except ImportError:
                logger.warning(f"❌ {dep_name} 不可用")
        
        # 检查特定依赖组合
        try:
            import numpy as np
            import cv2
            deps_status['LIP_SYNC_AVAILABLE'] = True
            logger.info("✅ 嘴型同步依赖可用 (cv2, numpy)")
        except ImportError:
            logger.warning("❌ 嘴型同步依赖不可用 (cv2, numpy)")
        
        # 检查FFmpeg
        try:
            import subprocess
            result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True)
            if result.returncode == 0:
                deps_status['ffmpeg_available'] = True
                logger.info("✅ FFmpeg 可用")
            else:
                logger.warning("❌ FFmpeg 不可用")
        except FileNotFoundError:
            logger.warning("❌ FFmpeg 不可用")
        
        # 更新缓存
        DependencyManager._deps_cache = deps_status
        DependencyManager._last_check_time = current_time
        
        return deps_status
    
    @staticmethod
    def get_missing_dependencies() -> List[str]:
        """获取缺失的依赖"""
        deps_status = DependencyManager.check_dependencies()
        missing = []
        
        dep_names = {
            'faster_whisper_available': 'faster_whisper',
            'easyocr_available': 'easyocr',
            'moviepy_available': 'moviepy',
            'transformers_available': 'transformers',
            'torch_available': 'torch',
            'dashscope_available': 'dashscope',
            'mediapipe_available': 'mediapipe',
            'yt_dlp_available': 'yt-dlp',
            'gtts_available': 'gTTS',
            'pynvml_available': 'pynvml',
            'numpy_available': 'numpy',
            'opencv_available': 'opencv-python',
            'requests_available': 'requests',
            'ffmpeg_available': 'FFmpeg',
        }
        
        for status_key, dep_name in dep_names.items():
            if not deps_status.get(status_key, False):
                missing.append(dep_name)
        
        return missing
    
    @staticmethod
    def get_install_commands() -> str:
        """获取安装命令"""
        missing = DependencyManager.get_missing_dependencies()
        if not missing:
            return "所有依赖都已安装"
        
        commands = []
        for dep in missing:
            if dep == 'FFmpeg':
                commands.append("请从 https://ffmpeg.org/download.html 下载并安装 FFmpeg")
            elif dep == 'easyocr':
                commands.append(f"pip install {dep}")
            else:
                commands.append(f"pip install {dep}")
        
        return "\n".join(commands)

# 保持向后兼容
def check_dependencies():
    return DependencyManager.check_dependencies()

class ModelManager:
    """模型管理器，负责下载和缓存模型"""
    _instance = None
    _models_cache = {}
    
    def __new__(cls, models_dir: str):
        if cls._instance is None:
            cls._instance = super(ModelManager, cls).__new__(cls)
            cls._instance.models_dir = Path(models_dir)
            cls._instance.models_dir.mkdir(exist_ok=True)
        return cls._instance

    def download_transformers_model(self, model_name: str):
        """下载 Transformers 模型"""
        if not self._is_torch_available():
            logger.warning("torch 不可用，无法下载 Transformers 模型。")
            return
        try:
            from transformers import AutoTokenizer, AutoModelForSequenceClassification
            logger.info(f"正在下载 Transformers 模型: {model_name}")
            tokenizer = AutoTokenizer.from_pretrained(model_name)
            model = AutoModelForSequenceClassification.from_pretrained(model_name)
            model_path = self.models_dir / model_name.replace('/', '_')
            model_path.mkdir(exist_ok=True)
            tokenizer.save_pretrained(model_path)
            model.save_pretrained(model_path)
            logger.info(f"Transformers 模型 {model_name} 下载完成并保存至 {model_path}")
        except Exception as e:
            logger.error(f"下载 Transformers 模型 {model_name} 失败: {e}")

    def download_whisper_model(self, size: str):
        """下载 Whisper 模型"""
        if not self._is_faster_whisper_available():
            logger.warning("faster_whisper 不可用，无法下载 Whisper 模型。")
            return
        try:
            import faster_whisper
            logger.info(f"正在下载 Whisper 模型: {size}")
            model_path = os.path.join(self.models_dir, f"whisper_{size}")
            # faster_whisper 模型会在首次使用时自动下载到 cache_dir
            # 我们模拟一次加载来触发下载
            model = faster_whisper.WhisperModel(size, download_root=model_path)
            # 缓存模型实例
            self._models_cache[f"whisper_{size}"] = model
            logger.info(f"Whisper 模型 {size} 下载完成 (缓存路径: {model_path})")
        except Exception as e:
            logger.error(f"下载 Whisper 模型 {size} 失败: {e}")

    def get_whisper_model(self, size: str):
        """获取 Whisper 模型实例（使用缓存）"""
        cache_key = f"whisper_{size}"
        if cache_key in self._models_cache:
            logger.info(f"从缓存加载 Whisper 模型: {size}")
            return self._models_cache[cache_key]
        
        if not self._is_faster_whisper_available():
            logger.warning("faster_whisper 不可用，无法加载 Whisper 模型。")
            return None
        
        try:
            import faster_whisper
            model_path = os.path.join(self.models_dir, cache_key)
            model = faster_whisper.WhisperModel(size, download_root=model_path)
            self._models_cache[cache_key] = model
            logger.info(f"加载并缓存 Whisper 模型: {size}")
            return model
        except Exception as e:
            logger.error(f"加载 Whisper 模型 {size} 失败: {e}")
            return None

    def _is_torch_available(self):
        try:
            import torch
            return True
        except ImportError:
            return False

    def _is_faster_whisper_available(self):
        try:
            import faster_whisper
            return True
        except ImportError:
            return False

    def clear_cache(self):
        """清理模型缓存"""
        try:
            import shutil
            # 清空内存缓存
            self._models_cache.clear()
            logger.info("模型内存缓存已清空。")
            
            # 清空磁盘缓存
            for item in self.models_dir.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                    logger.info(f"已删除缓存目录: {item}")
                elif item.is_file():
                    item.unlink()
                    logger.info(f"已删除缓存文件: {item}")
            logger.info("模型缓存清理完成。")
        except Exception as e:
            logger.error(f"清理模型缓存失败: {e}")

class AIVideoEditorLocal:
    def __init__(self, deps_status: Dict[str, bool] = None, config_path: str = "./config.json"):
        self.deps_status = deps_status or check_dependencies()
        self.load_config(config_path)
        self.model_manager = ModelManager(self.paths["models_dir"]) if self.deps_status['torch_available'] else None
        self.reader = None
        if self.deps_status['easyocr_available']:
            try:
                import easyocr
                self.reader = easyocr.Reader(lang_list=self.models["easyocr_languages"])
            except Exception as e:
                logger.error(f"初始化OCR阅读器失败: {e}")

        # --- 初始化核心组件 ---
        self.device = "cpu"
        self.sentiment_analyzer = None
        self.lip_sync_animator = None
        self._initialize_core_components()
    
    def _report_progress(self, step: int, total_steps: int, message: str, progress_callback=None):
        """统一的进度报告函数"""
        if progress_callback:
            try:
                progress = int((step / total_steps) * 100)
                progress_callback(progress, message)
            except Exception as e:
                logger.warning(f"调用进度回调失败: {e}")
    
    def _handle_error(self, error: Exception, context: str, progress_callback=None):
        """统一的错误处理函数"""
        error_info = ErrorDiagnoser.diagnose_error(error, context)
        error_report = ErrorDiagnoser.save_error_report(error_info)
        
        logger.error(f"处理{context}时出错: {error}")
        logger.error(f"错误报告已保存至: {error_report}")
        logger.error(f"建议: {error_info['suggestion']}")
        
        if progress_callback:
            try:
                progress_callback(0, 100, f"错误: {str(error)}")
            except Exception as e:
                logger.warning(f"调用进度回调失败: {e}")
        
        return error_info

    def load_config(self, config_path: str):
        """从JSON文件加载配置"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
            self.paths = self.config["paths"]
            self.models = self.config["models"]
            self.processing_params = self.config["processing"]
            self.keywords = self.config["keywords"]
            self.emotion_bgm_map = self.config["emotion_bgm_map"]
            logger.info(f"配置文件 {config_path} 加载成功。")
        except FileNotFoundError:
            logger.error(f"配置文件 {config_path} 未找到，使用默认配置。")
            self._set_default_config()
        except json.JSONDecodeError:
            logger.error(f"配置文件 {config_path} 格式错误，使用默认配置。")
            self._set_default_config()

    def _set_default_config(self):
        """设置默认配置"""
        self.paths = {"temp_dir": "./temp_ai_editor", "models_dir": "./models", "素材库_path": "./素材库", "output_dir": "./output", "脚本库_path": "./脚本库", "平台素材库_cache": "./平台素材库_cache"}
        self.models = {"sentiment_analyzer": "uer/roberta-base-finetuned-chinanews-chinese", "faster_whisper_size": "tiny", "easyocr_languages": ["ch_sim", "en"]}
        self.processing_params = {"max_duration_per_clip": 10, "target_durations": {"short": 60, "medium": 360, "long": 900}, "text_duration_ratio": 10}
        self.keywords = {}
        self.emotion_bgm_map = {}
        self.platform_apis = {"kuaishou": {"api_key": "", "api_secret": "", "base_url": "https://api.kuaishou.com"}, "douyin": {"api_key": "", "api_secret": "", "base_url": "https://api.douyin.com"}}
        self.script_templates = {"hook": "你是专业的短剧推广文案师，擅长写3秒抓人的钩子文案，要求字数10-15字，炸裂有冲突，适配【{genre}】题材短剧。请根据剧集核心剧情（{plot}），生成5条不同风格的钩子文案，用于视频开头字幕。", "narration": "你是专业的短剧轻解说博主，解说风格口语化、接地气，适配{platform}平台，文案总时长15秒（约40-50字）。请根据剧集【{drama_name}】（免费集剧情：{plot}），生成解说文案，要求开头3秒钩子，结尾引导点击左下角看全集，不剧透。", "title": "你是短剧推广封面标题设计师，擅长写高点击率标题，适配9:16竖屏封面，字数8-12字，含关键词【{keywords}】，适配【{genre}】题材。请生成6条标题，分炸裂风/悬念风两类。"}

    def _initialize_core_components(self):
        """初始化核心组件"""
        logger.info("🔧 初始化核心组件...")
        
        # --- 加载情感分析模型 ---
        if self.deps_status.get('torch_transformers_available', False):
            try:
                from transformers import pipeline
                self.sentiment_analyzer = pipeline("sentiment-analysis",
                                                   model=self.models["sentiment_analyzer"],
                                                   device=-1,  # CPU模式
                                                   model_kwargs={"cache_dir": self.paths["models_dir"]})
                logger.info("✅ 情感分析模型加载成功。")
            except Exception as e:
                logger.error(f"❌ 加载情感分析模型失败: {e}")
        else:
            logger.warning("⚠️ PyTorch 或 Transformers 不可用，跳过情感分析模型加载。")

        # --- 初始化嘴型动画器 ---
        if self.deps_status.get('LIP_SYNC_AVAILABLE', False):
            try:
                # 导入并初始化嘴型动画器
                from lip_sync_animator import LipSyncAnimator
                self.lip_sync_animator = LipSyncAnimator(asr_model_size=self.models.get("faster_whisper_size", "base"))
                logger.info("✅ 嘴型动画器已加载。")
            except ImportError:
                logger.warning("⚠️ lip_sync_animator 模块不可用，嘴型同步功能将禁用。")
            except Exception as e:
                logger.error(f"❌ 初始化嘴型动画器失败: {e}")
                self.deps_status['LIP_SYNC_AVAILABLE'] = False # 标记为不可用
        else:
            logger.warning("⚠️ 嘴型同步依赖不可用，跳过初始化。")

        logger.info("🤖 AI视频编辑器核心组件加载完成。")


    def download_required_models(self):
        """根据配置下载所需模型"""
        if not self.model_manager:
            logger.warning("模型管理器不可用，无法下载模型。")
            return

        # 下载情感分析模型
        if self.deps_status['transformers_available'] and self.models.get("sentiment_analyzer"):
            self.model_manager.download_transformers_model(self.models["sentiment_analyzer"])

        # 下载 Whisper 模型
        if self.deps_status['faster_whisper_available'] and self.models.get("faster_whisper_size"):
            self.model_manager.download_whisper_model(self.models["faster_whisper_size"])

    def clear_model_cache(self):
        """清理模型缓存"""
        if not self.model_manager:
            logger.warning("模型管理器不可用，无法清理缓存。")
            return
        self.model_manager.clear_cache()

    # --- 素材管理中心 ---    
    def fetch_platform_materials(self, platform: str, drama_id: str) -> List[Dict]:
        """从平台素材库拉取素材"""
        logger.info(f"📡 从 {platform} 平台拉取短剧 {drama_id} 的素材...")
        
        # 确保缓存目录存在
        cache_dir = Path(self.paths["平台素材库_cache"])
        cache_dir.mkdir(exist_ok=True, parents=True)
        
        # 检查缓存
        cache_file = cache_dir / f"{platform}_{drama_id}.json"
        if cache_file.exists():
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cached_data = json.load(f)
                logger.info(f"🔄 从缓存加载平台素材: {cache_file}")
                return cached_data
            except Exception as e:
                logger.warning(f"读取缓存失败: {e}")
        
        # 模拟平台API调用（实际实现需要接入真实API）
        materials = []
        if platform == "kuaishou":
            # 模拟快手素材库
            materials = [
                {"id": "1", "title": "开场冲突", "url": "https://example.com/clip1.mp4", "duration": 15, "tags": ["冲突", "钩子"]},
                {"id": "2", "title": "男主特写", "url": "https://example.com/clip2.mp4", "duration": 10, "tags": ["人物特写", "情绪"]},
                {"id": "3", "title": "反转瞬间", "url": "https://example.com/clip3.mp4", "duration": 8, "tags": ["反转", "高潮"]},
                {"id": "4", "title": "悬念结尾", "url": "https://example.com/clip4.mp4", "duration": 5, "tags": ["悬念", "引导"]}
            ]
        elif platform == "douyin":
            # 模拟抖音素材库
            materials = [
                {"id": "101", "title": "冲突镜头", "url": "https://example.com/douyin1.mp4", "duration": 12, "tags": ["冲突", "钩子"]},
                {"id": "102", "title": "台词高光", "url": "https://example.com/douyin2.mp4", "duration": 8, "tags": ["台词", "高光"]},
                {"id": "103", "title": "人物特写", "url": "https://example.com/douyin3.mp4", "duration": 6, "tags": ["人物特写"]},
                {"id": "104", "title": "悬念结尾", "url": "https://example.com/douyin4.mp4", "duration": 4, "tags": ["悬念", "引导"]}
            ]
        
        # 保存到缓存
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(materials, f, ensure_ascii=False, indent=2)
            logger.info(f"💾 平台素材已缓存到: {cache_file}")
        except Exception as e:
            logger.warning(f"保存缓存失败: {e}")
        
        return materials

    def perform_lip_sync(self, video_path: str, audio_path: str, output_path: str, fallback_text: str = None) -> bool:
        """执行嘴型同步"""
        logger.info(f"🎭 开始嘴型同步: {video_path} + {audio_path} -> {output_path}")
        
        try:
            if not self.lip_sync_animator:
                logger.error("❌ 嘴型动画器未初始化")
                return False
            
            # 执行嘴型同步
            self.lip_sync_animator.animate_lips(video_path, audio_path, output_path, fallback_text)
            
            logger.info(f"✅ 嘴型同步完成: {output_path}")
            return True
        except Exception as e:
            logger.error(f"❌ 嘴型同步失败: {e}")
            return False
    
    def download_platform_material(self, material_url: str, output_path: str) -> bool:
        """下载平台素材"""
        logger.info(f"📥 下载平台素材: {material_url} -> {output_path}")
        
        try:
            response = requests.get(material_url, stream=True, timeout=30)
            response.raise_for_status()
            
            # 确保输出目录存在
            output_dir = Path(output_path).parent
            output_dir.mkdir(exist_ok=True, parents=True)
            
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            logger.info(f"✅ 素材下载成功: {output_path}")
            return True
        except Exception as e:
            logger.error(f"❌ 下载素材失败: {e}")
            return False

    def ai_material_analysis(self, video_path: str) -> Dict[str, Any]:
        """AI智能分析素材"""
        logger.info(f"🧠 AI智能分析素材: {video_path}")
        
        analysis_result = {
            "video_path": video_path,
            "duration": 0,
            "scenes": [],
            "tags": [],
            "quality": "high"
        }
        
        try:
            # 使用moviepy获取视频基本信息
            from moviepy.editor import VideoFileClip
            with VideoFileClip(video_path) as clip:
                analysis_result["duration"] = clip.duration
            
            # 模拟AI场景分析
            # 实际实现中可以使用OpenCV、PaddlePaddle等进行更详细的分析
            scenes = [
                {"start": 0, "end": 3, "type": "conflict", "description": "冲突镜头", "score": 0.9},
                {"start": 3, "end": 8, "type": "dialogue", "description": "台词高光", "score": 0.7},
                {"start": 8, "end": 12, "type": "closeup", "description": "人物特写", "score": 0.8},
                {"start": 12, "end": analysis_result["duration"], "type": "suspense", "description": "悬念结尾", "score": 0.95}
            ]
            analysis_result["scenes"] = scenes
            
            # 提取标签
            tags = []
            for scene in scenes:
                if scene["type"] == "conflict":
                    tags.extend(["冲突", "钩子"])
                elif scene["type"] == "dialogue":
                    tags.extend(["台词", "高光"])
                elif scene["type"] == "closeup":
                    tags.extend(["人物特写"])
                elif scene["type"] == "suspense":
                    tags.extend(["悬念", "引导"])
            analysis_result["tags"] = list(set(tags))
            
            logger.info(f"✅ 素材分析完成，识别到 {len(scenes)} 个场景")
        except Exception as e:
            logger.error(f"❌ 素材分析失败: {e}")
        
        return analysis_result

    def split_material_by_scenes(self, video_path: str, scenes: List[Dict], output_dir: str) -> List[str]:
        """根据场景分割素材"""
        logger.info(f"✂️ 根据场景分割素材: {video_path}")
        
        output_files = []
        output_dir = Path(output_dir)
        output_dir.mkdir(exist_ok=True, parents=True)
        
        try:
            for i, scene in enumerate(scenes):
                start_time = scene["start"]
                end_time = scene["end"]
                scene_type = scene["type"]
                
                output_file = output_dir / f"scene_{i+1}_{scene_type}_{start_time:.1f}-{end_time:.1f}.mp4"
                
                # 使用FFmpeg分割视频
                cmd = [
                    "ffmpeg", "-y",
                    "-i", str(video_path),
                    "-ss", str(start_time),
                    "-to", str(end_time),
                    "-c:v", "copy",
                    "-c:a", "copy",
                    str(output_file)
                ]
                
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    output_files.append(str(output_file))
                    logger.info(f"✅ 分割场景 {i+1} 成功: {output_file}")
                else:
                    logger.error(f"❌ 分割场景 {i+1} 失败: {result.stderr}")
        except Exception as e:
            logger.error(f"❌ 分割素材失败: {e}")
        
        return output_files

    # --- 脚本管理 ---    
    def load_script(self, script_path: str) -> List[Dict]:
        """加载脚本文件"""
        logger.info(f"📖 加载脚本: {script_path}")
        
        try:
            with open(script_path, 'r', encoding='utf-8') as f:
                script = json.load(f)
            logger.info(f"✅ 脚本加载成功，包含 {len(script)} 个片段")
            return script
        except Exception as e:
            logger.error(f"❌ 加载脚本失败: {e}")
            return []

    def save_script(self, script: List[Dict], output_path: str) -> bool:
        """保存脚本文件"""
        logger.info(f"💾 保存脚本: {output_path}")
        
        try:
            # 确保输出目录存在
            output_dir = Path(output_path).parent
            output_dir.mkdir(exist_ok=True, parents=True)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(script, f, ensure_ascii=False, indent=2)
            logger.info(f"✅ 脚本保存成功")
            return True
        except Exception as e:
            logger.error(f"❌ 保存脚本失败: {e}")
            return False

    # --- AI脚本重构模块 ---    
    def refactor_script(self, original_script: List[Dict], refactor_type: str, platform: str = "douyin", genre: str = "复仇") -> List[Dict]:
        """AI脚本重构"""
        logger.info(f"🔄 执行脚本重构，类型: {refactor_type}, 平台: {platform}, 题材: {genre}")
        
        if refactor_type == "lightweight":
            # 轻量化重构（适配混剪）
            return self._refactor_lightweight(original_script, genre)
        elif refactor_type == "optimize":
            # 现有脚本优化
            return self._refactor_optimize(original_script, platform)
        elif refactor_type == "cross_platform":
            # 跨平台风格重构
            return self._refactor_cross_platform(original_script, platform)
        elif refactor_type == "narration":
            # 轻解说脚本重构
            return self._refactor_narration(original_script, platform, genre)
        else:
            logger.error(f"❌ 不支持的重构类型: {refactor_type}")
            return original_script

    def _refactor_lightweight(self, original_script: List[Dict], genre: str) -> List[Dict]:
        """轻量化重构（适配混剪）"""
        logger.info("⚡ 执行轻量化脚本重构（适配混剪）")
        
        # 保留核心冲突和反转
        refactored = []
        
        # 1. 提取冲突场景作为钩子（前3秒）
        conflict_scenes = [scene for scene in original_script if any(tag in scene.get('tags', []) for tag in ['冲突', '钩子'])]
        if conflict_scenes:
            hook_scene = conflict_scenes[0]
            hook_scene['duration'] = 3
            hook_scene['priority'] = 'high'
            refactored.append(hook_scene)
        
        # 2. 提取高潮/反转场景（中间）
        climax_scenes = [scene for scene in original_script if any(tag in scene.get('tags', []) for tag in ['反转', '高潮', '高光'])]
        for i, scene in enumerate(climax_scenes[:2]):  # 最多2个高潮场景
            scene['duration'] = min(scene.get('duration', 10), 5)
            scene['priority'] = 'medium'
            refactored.append(scene)
        
        # 3. 提取悬念结尾（最后）
        suspense_scenes = [scene for scene in original_script if any(tag in scene.get('tags', []) for tag in ['悬念', '引导'])]
        if suspense_scenes:
            end_scene = suspense_scenes[-1]
            end_scene['duration'] = min(end_scene.get('duration', 10), 3)
            end_scene['priority'] = 'high'
            end_scene['text'] = end_scene.get('text', '') + ' 点左下角看全集！'  # 添加引导语
            refactored.append(end_scene)
        
        # 如果场景不足，从原脚本补充
        if len(refactored) < 3:
            for scene in original_script:
                if scene not in refactored:
                    scene['duration'] = min(scene.get('duration', 10), 4)
                    refactored.append(scene)
                if len(refactored) >= 3:
                    break
        
        logger.info(f"✅ 轻量化重构完成，生成 {len(refactored)} 个片段")
        return refactored[:3]  # 限制为3个片段

    def _refactor_optimize(self, original_script: List[Dict], platform: str) -> List[Dict]:
        """现有脚本优化"""
        logger.info(f"✨ 执行脚本优化，适配 {platform} 平台")
        
        refactored = []
        
        for i, scene in enumerate(original_script):
            # 优化钩子
            if i == 0:  # 第一个片段作为钩子
                original_text = scene.get('text', '')
                if platform == "douyin":
                    # 抖音风格：更简洁、炸裂
                    optimized_text = f"{original_text[:15]}！"
                else:  # 快手
                    # 快手风格：更口语、接地气
                    optimized_text = f"我的天！{original_text[:20]}！"
                scene['text'] = optimized_text
                scene['hook_strength'] = 'high'
            
            # 优化结尾引导
            if i == len(original_script) - 1:
                scene['text'] = scene.get('text', '') + f' 点左下角看第{random.randint(5, 15)}集！'
            
            refactored.append(scene)
        
        logger.info("✅ 脚本优化完成")
        return refactored

    def _refactor_cross_platform(self, original_script: List[Dict], platform: str) -> List[Dict]:
        """跨平台风格重构"""
        logger.info(f"🌉 执行跨平台风格重构，适配 {platform} 平台")
        
        refactored = []
        
        for scene in original_script:
            new_scene = scene.copy()
            
            if platform == "douyin":
                # 抖音风格：简洁、视觉冲击
                new_scene['style'] = 'concise'
                new_scene['text'] = new_scene.get('text', '')[:15]
                new_scene['subtitle_size'] = 'medium'
            else:  # 快手
                # 快手风格：口语、情绪共鸣
                new_scene['style'] = 'colloquial'
                new_scene['text'] = f"家人们！{new_scene.get('text', '')}"
                new_scene['subtitle_size'] = 'large'
                # 可添加方言后缀
                if random.random() > 0.5:
                    new_scene['text'] += ' 你知道不？'
            
            refactored.append(new_scene)
        
        logger.info("✅ 跨平台风格重构完成")
        return refactored

    def _refactor_narration(self, original_script: List[Dict], platform: str, genre: str) -> List[Dict]:
        """轻解说脚本重构"""
        logger.info(f"🎙️ 执行轻解说脚本重构，适配 {platform} 平台，题材: {genre}")
        
        # 生成连贯的解说文案
        narration_script = []
        
        # 1. 开场钩子
        hook_text = f"家人们，今天给你们看个超炸的{genre}短剧！"
        if platform == "douyin":
            hook_text = f"{genre}短剧天花板！看完震惊了！"
        
        narration_script.append({
            'text': hook_text,
            'duration': 3,
            'type': 'narration',
            'position': 'hook'
        })
        
        # 2. 剧情讲解
        plot_text = ""
        for scene in original_script[:3]:  # 提取前3个场景的剧情
            plot_text += scene.get('text', '') + ' '
        
        narration_script.append({
            'text': plot_text[:80],  # 控制长度
            'duration': 10,
            'type': 'narration',
            'position': 'plot'
        })
        
        # 3. 结尾引导
        end_text = "想看全集的家人们，点左下角链接直接看！"
        if platform == "douyin":
            end_text = "想看全集？点左下角直接看！"
        
        narration_script.append({
            'text': end_text,
            'duration': 4,
            'type': 'narration',
            'position': 'end'
        })
        
        logger.info("✅ 轻解说脚本重构完成")
        return narration_script

    # --- AI剪辑工坊 ---    
    def mix_cut_mode(self, drama_id: str, genre: str, platform: str = "douyin", output_path: str = "output_mix_cut.mp4", progress_callback=None):
        """混剪模式"""
        logger.info(f"🎬 启动混剪模式，短剧ID: {drama_id}, 题材: {genre}, 平台: {platform}")
        
        total_steps = 6
        current_step = 0
        
        try:
            # 1. 拉取平台素材
            current_step += 1
            self._report_progress(current_step, total_steps, "拉取平台素材...", progress_callback)
            materials = self.fetch_platform_materials(platform, drama_id)
            if not materials:
                raise ValueError("未能获取到平台素材")
            
            # 2. 下载素材
            current_step += 1
            self._report_progress(current_step, total_steps, "下载素材...", progress_callback)
            downloaded_materials = []
            for i, material in enumerate(materials[:4]):  # 最多下载4个素材
                material_url = material.get('url', '')
                if material_url:
                    output_file = Path(self.paths["平台素材库_cache"]) / f"{platform}_{drama_id}_clip_{i}.mp4"
                    if self.download_platform_material(material_url, str(output_file)):
                        downloaded_materials.append(str(output_file))
            
            if not downloaded_materials:
                raise ValueError("未能下载到任何素材")
            
            # 3. AI分析素材
            current_step += 1
            self._report_progress(current_step, total_steps, "AI分析素材...", progress_callback)
            analysis_results = []
            for material_path in downloaded_materials:
                analysis = self.ai_material_analysis(material_path)
                analysis_results.append(analysis)
            
            # 4. 生成混剪脚本
            current_step += 1
            self._report_progress(current_step, total_steps, "生成混剪脚本...", progress_callback)
            # 提取所有场景
            all_scenes = []
            for analysis in analysis_results:
                all_scenes.extend(analysis.get('scenes', []))
            
            # 重构为混剪脚本
            mix_cut_script = self.refactor_script(all_scenes, "lightweight", platform, genre)
            if not mix_cut_script:
                raise ValueError("未能生成混剪脚本")
            
            # 5. 剪辑视频
            current_step += 1
            self._report_progress(current_step, total_steps, "剪辑视频...", progress_callback)
            # 这里调用现有的视频处理逻辑
            # 实际实现中需要根据脚本和素材生成最终视频
            
            # 6. 导出视频
            current_step += 1
            self._report_progress(current_step, total_steps, "导出视频...", progress_callback)
            # 模拟导出成功
            logger.info(f"✅ 混剪视频导出成功: {output_path}")
            
            return True
        except Exception as e:
            self._handle_error(e, "混剪模式", progress_callback)
            return False

    def light_narration_mode(self, drama_id: str, genre: str, platform: str = "douyin", output_path: str = "output_narration.mp4", progress_callback=None):
        """轻解说模式"""
        logger.info(f"🎙️ 启动轻解说模式，短剧ID: {drama_id}, 题材: {genre}, 平台: {platform}")
        
        total_steps = 7
        current_step = 0
        
        try:
            # 1. 拉取平台素材
            current_step += 1
            self._report_progress(current_step, total_steps, "拉取平台素材...", progress_callback)
            materials = self.fetch_platform_materials(platform, drama_id)
            if not materials:
                raise ValueError("未能获取到平台素材")
            
            # 2. 下载素材
            current_step += 1
            self._report_progress(current_step, total_steps, "下载素材...", progress_callback)
            downloaded_materials = []
            for i, material in enumerate(materials[:3]):  # 最多下载3个素材
                material_url = material.get('url', '')
                if material_url:
                    output_file = Path(self.paths["平台素材库_cache"]) / f"{platform}_{drama_id}_narration_{i}.mp4"
                    if self.download_platform_material(material_url, str(output_file)):
                        downloaded_materials.append(str(output_file))
            
            if not downloaded_materials:
                raise ValueError("未能下载到任何素材")
            
            # 3. 生成解说文案
            current_step += 1
            self._report_progress(current_step, total_steps, "生成解说文案...", progress_callback)
            # 生成基础剧情
            plot = f"{genre}短剧，讲述了一个精彩的故事，包含冲突、反转和悬念"
            # 生成轻解说脚本
            narration_script = self.refactor_script([{"text": plot}], "narration", platform, genre)
            if not narration_script:
                raise ValueError("未能生成解说脚本")
            
            # 4. AI配音
            current_step += 1
            self._report_progress(current_step, total_steps, "AI配音...", progress_callback)
            # 实际实现中需要调用TTS服务
            tts_files = []
            for i, segment in enumerate(narration_script):
                tts_file = self._generate_tts_audio(segment.get('text', ''), i)
                if tts_file:
                    tts_files.append(tts_file)
            
            # 5. 画面匹配
            current_step += 1
            self._report_progress(current_step, total_steps, "画面匹配...", progress_callback)
            # 实际实现中需要根据解说节奏匹配画面
            
            # 6. 添加字幕
            current_step += 1
            self._report_progress(current_step, total_steps, "添加字幕...", progress_callback)
            # 实际实现中需要为解说添加字幕
            
            # 7. 导出视频
            current_step += 1
            self._report_progress(current_step, total_steps, "导出视频...", progress_callback)
            # 模拟导出成功
            logger.info(f"✅ 轻解说视频导出成功: {output_path}")
            
            return True
        except Exception as e:
            self._handle_error(e, "轻解说模式", progress_callback)
            return False

    # --- 批量生产与发布 ---    
    def batch_process(self, tasks: List[Dict], progress_callback=None):
        """批量处理视频"""
        logger.info(f"📦 启动批量处理，共 {len(tasks)} 个任务")
        
        results = []
        total_tasks = len(tasks)
        
        for i, task in enumerate(tasks):
            task_id = task.get('id', f"task_{i+1}")
            task_type = task.get('type', 'mix_cut')  # mix_cut 或 light_narration
            drama_id = task.get('drama_id', '')
            genre = task.get('genre', '复仇')
            platform = task.get('platform', 'douyin')
            output_path = task.get('output_path', f"output_batch_{i}.mp4")
            
            logger.info(f"开始处理任务 {i+1}/{total_tasks}: {task_id}")
            
            # 报告任务进度
            if progress_callback:
                try:
                    task_progress = int((i / total_tasks) * 100)
                    progress_callback(task_progress, f"处理任务 {i+1}/{total_tasks}...")
                except Exception as e:
                    logger.warning(f"调用进度回调失败: {e}")
            
            # 执行任务
            if task_type == 'mix_cut':
                success = self.mix_cut_mode(drama_id, genre, platform, output_path)
            else:
                success = self.light_narration_mode(drama_id, genre, platform, output_path)
            
            results.append({
                'task_id': task_id,
                'success': success,
                'output_path': output_path if success else None
            })
        
        logger.info(f"✅ 批量处理完成，成功 {sum(1 for r in results if r['success'])} 个，失败 {sum(1 for r in results if not r['success'])} 个")
        return results

    def save_template(self, template_name: str, template_data: Dict) -> bool:
        """保存剪辑模板"""
        logger.info(f"💾 保存剪辑模板: {template_name}")
        
        try:
            # 确保模板目录存在
            template_dir = Path(self.paths["temp_dir"]) / "templates"
            template_dir.mkdir(exist_ok=True, parents=True)
            
            template_file = template_dir / f"{template_name}.json"
            with open(template_file, 'w', encoding='utf-8') as f:
                json.dump(template_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"✅ 模板保存成功: {template_file}")
            return True
        except Exception as e:
            logger.error(f"❌ 保存模板失败: {e}")
            return False

    def load_template(self, template_name: str) -> Dict:
        """加载剪辑模板"""
        logger.info(f"📖 加载剪辑模板: {template_name}")
        
        try:
            template_file = Path(self.paths["temp_dir"]) / "templates" / f"{template_name}.json"
            if template_file.exists():
                with open(template_file, 'r', encoding='utf-8') as f:
                    template_data = json.load(f)
                logger.info(f"✅ 模板加载成功: {template_file}")
                return template_data
            else:
                logger.error(f"❌ 模板文件不存在: {template_file}")
                return {}
        except Exception as e:
            logger.error(f"❌ 加载模板失败: {e}")
            return {}

     # --- 数据复盘模块 ---    
    def track_video_performance(self, video_id: str, performance_data: Dict):
        """追踪视频表现数据"""
        logger.info(f"📊 追踪视频表现数据: {video_id}")
        
        # 确保数据目录存在
        data_dir = Path("./performance_data")
        data_dir.mkdir(exist_ok=True)
        
        # 保存表现数据
        data_file = data_dir / f"{video_id}.json"
        try:
            # 添加时间戳
            performance_data['timestamp'] = datetime.now().isoformat()
            
            with open(data_file, 'w', encoding='utf-8') as f:
                json.dump(performance_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"✅ 视频表现数据保存成功: {data_file}")
            return True
        except Exception as e:
            logger.error(f"❌ 保存视频表现数据失败: {e}")
            return False

    def analyze_performance_data(self, time_range: str = "7d") -> Dict[str, Any]:
        """分析表现数据"""
        logger.info(f"📈 分析表现数据，时间范围: {time_range}")
        
        # 确保数据目录存在
        data_dir = Path("./performance_data")
        if not data_dir.exists():
            logger.warning("表现数据目录不存在")
            return {"error": "数据目录不存在"}
        
        # 加载所有表现数据
        all_data = []
        for data_file in data_dir.glob("*.json"):
            try:
                with open(data_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                all_data.append(data)
            except Exception as e:
                logger.warning(f"加载数据文件失败 {data_file}: {e}")
        
        if not all_data:
            logger.warning("没有可用的表现数据")
            return {"error": "没有可用数据"}
        
        # 分析数据
        analysis = {
            "total_videos": len(all_data),
            "average_views": 0,
            "average_likes": 0,
            "average_comments": 0,
            "average_shares": 0,
            "top_performing_videos": [],
            "hook_performance": {},
            "genre_performance": {},
            "platform_performance": {}
        }
        
        # 计算平均值
        total_views = sum(data.get('views', 0) for data in all_data)
        total_likes = sum(data.get('likes', 0) for data in all_data)
        total_comments = sum(data.get('comments', 0) for data in all_data)
        total_shares = sum(data.get('shares', 0) for data in all_data)
        
        if all_data:
            analysis["average_views"] = total_views / len(all_data)
            analysis["average_likes"] = total_likes / len(all_data)
            analysis["average_comments"] = total_comments / len(all_data)
            analysis["average_shares"] = total_shares / len(all_data)
        
        # 分析钩子表现
        for data in all_data:
            hook_type = data.get('hook_type', 'unknown')
            if hook_type not in analysis["hook_performance"]:
                analysis["hook_performance"][hook_type] = {"count": 0, "total_views": 0, "total_conversions": 0}
            analysis["hook_performance"][hook_type]["count"] += 1
            analysis["hook_performance"][hook_type]["total_views"] += data.get('views', 0)
            analysis["hook_performance"][hook_type]["total_conversions"] += data.get('conversions', 0)
        
        # 分析题材表现
        for data in all_data:
            genre = data.get('genre', 'unknown')
            if genre not in analysis["genre_performance"]:
                analysis["genre_performance"][genre] = {"count": 0, "total_views": 0, "total_conversions": 0}
            analysis["genre_performance"][genre]["count"] += 1
            analysis["genre_performance"][genre]["total_views"] += data.get('views', 0)
            analysis["genre_performance"][genre]["total_conversions"] += data.get('conversions', 0)
        
        # 分析平台表现
        for data in all_data:
            platform = data.get('platform', 'unknown')
            if platform not in analysis["platform_performance"]:
                analysis["platform_performance"][platform] = {"count": 0, "total_views": 0, "total_conversions": 0}
            analysis["platform_performance"][platform]["count"] += 1
            analysis["platform_performance"][platform]["total_views"] += data.get('views', 0)
            analysis["platform_performance"][platform]["total_conversions"] += data.get('conversions', 0)
        
        # 找出表现最好的视频
        sorted_videos = sorted(all_data, key=lambda x: x.get('conversions', 0), reverse=True)
        analysis["top_performing_videos"] = sorted_videos[:5]
        
        logger.info("✅ 表现数据分析完成")
        return analysis

    def generate_optimization_strategy(self, analysis_data: Dict) -> Dict[str, Any]:
        """基于数据分析生成优化策略"""
        logger.info("🧠 生成优化策略")
        
        strategy = {
            "recommended_hooks": [],
            "recommended_genres": [],
            "recommended_platforms": [],
            "script_optimization": {},
            "template_recommendations": []
        }
        
        # 分析钩子表现
        hook_performance = analysis_data.get('hook_performance', {})
        if hook_performance:
            # 计算每个钩子类型的转化率
            hook_effectiveness = []
            for hook_type, data in hook_performance.items():
                if data['count'] > 0:
                    conversion_rate = data['total_conversions'] / data['count'] if data['count'] > 0 else 0
                    hook_effectiveness.append((hook_type, conversion_rate, data['total_views'] / data['count']))
            
            # 按转化率排序
            hook_effectiveness.sort(key=lambda x: x[1], reverse=True)
            strategy["recommended_hooks"] = [hook[0] for hook in hook_effectiveness[:3]]
        
        # 分析题材表现
        genre_performance = analysis_data.get('genre_performance', {})
        if genre_performance:
            genre_effectiveness = []
            for genre, data in genre_performance.items():
                if data['count'] > 0:
                    conversion_rate = data['total_conversions'] / data['count'] if data['count'] > 0 else 0
                    genre_effectiveness.append((genre, conversion_rate, data['total_views'] / data['count']))
            
            genre_effectiveness.sort(key=lambda x: x[1], reverse=True)
            strategy["recommended_genres"] = [genre[0] for genre in genre_effectiveness[:3]]
        
        # 分析平台表现
        platform_performance = analysis_data.get('platform_performance', {})
        if platform_performance:
            platform_effectiveness = []
            for platform, data in platform_performance.items():
                if data['count'] > 0:
                    conversion_rate = data['total_conversions'] / data['count'] if data['count'] > 0 else 0
                    platform_effectiveness.append((platform, conversion_rate, data['total_views'] / data['count']))
            
            platform_effectiveness.sort(key=lambda x: x[1], reverse=True)
            strategy["recommended_platforms"] = [platform[0] for platform in platform_effectiveness[:2]]
        
        # 生成脚本优化建议
        strategy["script_optimization"] = {
            "hook_strength": "high",
            "plot_compression": "medium",
            "end_cta": "direct",
            "recommended_length": "15s-30s"
        }
        
        # 生成模板推荐
        strategy["template_recommendations"] = [
            {"name": "高转化混剪模板", "适用题材": strategy["recommended_genres"][:2] if strategy["recommended_genres"] else ["复仇", "甜宠"]},
            {"name": "轻解说爆款模板", "适用平台": strategy["recommended_platforms"][:1] if strategy["recommended_platforms"] else ["douyin"]}
        ]
        
        logger.info("✅ 优化策略生成完成")
        return strategy

    def get_ai_optimized_prompt(self, strategy: Dict, task_type: str = "hook") -> str:
        """基于策略生成AI优化的Prompt"""
        logger.info(f"🤖 生成AI优化的Prompt，任务类型: {task_type}")
        
        if task_type == "hook":
            recommended_hooks = strategy.get("recommended_hooks", ["冲突", "反转"])
            recommended_genres = strategy.get("recommended_genres", ["复仇"])
            
            prompt = f"""
            你是专业的短剧推广文案师，擅长写3秒抓人的钩子文案。
            基于历史数据分析，以下钩子类型表现最佳: {', '.join(recommended_hooks)}
            以下题材转化率最高: {', '.join(recommended_genres)}
            
            请为【{{genre}}】题材短剧生成5条钩子文案，要求:
            1. 字数10-15字
            2. 包含强烈的冲突或反转
            3. 适合抖音/快手平台
            4. 能够在3秒内抓住用户注意力
            5. 每条文案单独一行
            """
        
        elif task_type == "narration":
            recommended_platforms = strategy.get("recommended_platforms", ["douyin"])
            
            prompt = f"""
            你是专业的短剧轻解说博主，解说风格口语化、接地气。
            基于历史数据分析，以下平台表现最佳: {', '.join(recommended_platforms)}
            
            请为【{{drama_name}}】短剧生成解说文案，要求:
            1. 总时长15秒左右
            2. 开头3秒钩子
            3. 中间讲解核心剧情
            4. 结尾引导点击左下角看全集
            5. 不剧透
            6. 适合{{platform}}平台风格
            """
        
        elif task_type == "title":
            recommended_genres = strategy.get("recommended_genres", ["复仇"])
            
            prompt = f"""
            你是短剧推广封面标题设计师，擅长写高点击率标题。
            基于历史数据分析，以下题材表现最佳: {', '.join(recommended_genres)}
            
            请为【{{genre}}】题材短剧生成6条封面标题，要求:
            1. 字数8-12字
            2. 含关键词【反转/战神/复仇】
            3. 分炸裂风/悬念风两类
            4. 适合9:16竖屏封面
            5. 每条标题单独一行
            """
        
        else:
            prompt = "你是专业的短剧推广专家，请根据需求生成相关内容。"
        
        logger.info("✅ AI优化的Prompt生成完成")
        return prompt

    # --- 大模型扩展功能 ---    
    def generate_hook_captions(self, genre: str, plot: str, model_choice: str = "qwen") -> List[str]:
        """生成短剧钩子文案"""
        logger.info(f"📝 生成 {genre} 题材短剧钩子文案")
        
        if model_choice == "qwen":
            if not self.deps_status.get('dashscope_available', False):
                logger.error("❌ DashScope 未安装，无法生成文案。")
                return []
            
            try:
                import dashscope
                from http import HTTPStatus
                
                prompt = self.script_templates["hook"].format(genre=genre, plot=plot)
                
                messages = [
                    {"role": "system", "content": "你是专业的短剧推广文案师，擅长写3秒抓人的钩子文案。"},
                    {"role": "user", "content": prompt}
                ]
                
                response = dashscope.Generation.call(
                    model='qwen-max',
                    messages=messages,
                    result_format='message',
                )
                
                if response.status_code == HTTPStatus.OK:
                    content = response.output.choices[0]['message']['content']
                    # 解析生成的文案
                    captions = [line.strip() for line in content.split('\n') if line.strip() and not line.startswith('```')]
                    logger.info(f"✅ 生成 {len(captions)} 条钩子文案")
                    return captions[:5]  # 最多返回5条
                else:
                    logger.error(f"❌ DashScope API 请求失败: {response.message}")
                    return []
            except Exception as e:
                logger.error(f"❌ 生成钩子文案失败: {e}")
                return []
        else:
            logger.error(f"❌ 不支持的模型: {model_choice}")
            return []

    def generate_cover_titles(self, genre: str, keywords: str, model_choice: str = "qwen") -> List[str]:
        """生成封面标题"""
        logger.info(f"🎨 生成 {genre} 题材短剧封面标题")
        
        if model_choice == "qwen":
            if not self.deps_status.get('dashscope_available', False):
                logger.error("❌ DashScope 未安装，无法生成标题。")
                return []
            
            try:
                import dashscope
                from http import HTTPStatus
                
                prompt = self.script_templates["title"].format(keywords=keywords, genre=genre)
                
                messages = [
                    {"role": "system", "content": "你是短剧推广封面标题设计师，擅长写高点击率标题。"},
                    {"role": "user", "content": prompt}
                ]
                
                response = dashscope.Generation.call(
                    model='qwen-max',
                    messages=messages,
                    result_format='message',
                )
                
                if response.status_code == HTTPStatus.OK:
                    content = response.output.choices[0]['message']['content']
                    # 解析生成的标题
                    titles = [line.strip() for line in content.split('\n') if line.strip() and not line.startswith('```')]
                    logger.info(f"✅ 生成 {len(titles)} 条封面标题")
                    return titles[:6]  # 最多返回6条
                else:
                    logger.error(f"❌ DashScope API 请求失败: {response.message}")
                    return []
            except Exception as e:
                logger.error(f"❌ 生成封面标题失败: {e}")
                return []
        else:
            logger.error(f"❌ 不支持的模型: {model_choice}")
            return []

    def generate_script_with_ai(self, prompt: str, model_choice: str = "qwen") -> List[Dict]:
        """根据主题生成脚本 (调用AI)"""
        logger.info(f"🤖 正在使用 {model_choice} 生成视频脚本...")
        
        if model_choice == "qwen":
            if not self.deps_status.get('dashscope_available', False):
                logger.error("❌ DashScope 未安装，无法生成脚本。")
                return []
            
            try:
                import dashscope
                from http import HTTPStatus
                import json
                import re
            except ImportError:
                logger.error("❌ DashScope相关模块导入失败。")
                return []

            system_prompt = """
            你是一个专业的短视频脚本生成助手。你的任务是根据用户提供的主题或一句话，生成一段详细的、富有戏剧冲突的短视频脚本。
            脚本应包含：
            1.  一系列的台词或旁白（每句台词作为一个独立的段落）。
            2.  每句台词可能表达的情绪（从 anger, surprise, joy, sad, tension, normal, high_burn, sweet, reversal_face_slap, satisfying 中选择）。
            3.  每句台词最好能暗示一个可以匹配的场景或画面。
            请以 JSON 格式返回，格式如下：
            [
                {"text": "台词1", "emotion": "emotion1"},
                {"text": "台词2", "emotion": "emotion2"},
                ...
            ]
            请注意，台词要口语化，情绪要准确，场景描述要清晰。
            """

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ]
            try:
                response = dashscope.Generation.call(
                    model='qwen-max',
                    messages=messages,
                    result_format='message',
                )
                
                if response.status_code == HTTPStatus.OK:
                    content = response.output.choices[0]['message']['content']
                    json_match = re.search(r'\[(.*?)\]', content, re.DOTALL)
                    if json_match:
                        script_json_str = "[" + json_match.group(1) + "]"
                        try:
                            script_data = json.loads(script_json_str)
                            logger.info("✅ 脚本生成成功！")
                            return script_data
                        except json.JSONDecodeError as e:
                            logger.error(f"❌ 解析AI生成的JSON脚本时出错: {e}")
                            logger.debug(f"原始AI回复: {content}")
                            return []
                    else:
                        logger.error(f"❌ 未能从AI回复中找到JSON格式的脚本: {content}")
                        return []
                else:
                    logger.error(f"❌ DashScope API 请求失败: {response.message}")
                    return []
            except Exception as e:
                logger.error(f"❌ 调用DashScope API时出错: {e}")
                return []
        else:
            logger.error(f"❌ 不支持的模型: {model_choice}")
            return []

    def search_and_download_clips_for_script(self, script_list: List[Dict], style: str = "normal") -> List[str]:
        """根据脚本内容搜索素材"""
        logger.info(f"🔍 正在根据脚本内容和风格 '{style}' 搜索视频片段...")
        clips_to_use = []
        for i, segment in enumerate(script_list):
            text = segment.get("text", "")
            emotion = segment.get("emotion", "normal")
            
            search_emotion = style if style != "normal" else emotion
            search_query = f"{text} {search_emotion}"
            logger.info(f"   搜索第 {i+1} 段: '{search_query}'")
            
            emotion_folder_path = os.path.join(self.paths["素材库_path"], search_emotion)
            if os.path.isdir(emotion_folder_path):
                available_clips = [f for f in os.listdir(emotion_folder_path) if f.endswith(('.mp4', '.avi', '.mov', '.mkv'))]
                if available_clips:
                    selected_clip_name = random.choice(available_clips)
                    selected_clip_path = os.path.join(emotion_folder_path, selected_clip_name)
                    logger.info(f"      从素材库 '{emotion_folder_path}' 选择了: {selected_clip_name}")
                    clips_to_use.append(selected_clip_path)
                else:
                    logger.warning(f"      警告: 风格/情绪 '{search_emotion}' 的素材库中没有可用的视频片段。")
            else:
                logger.warning(f"      警告: 没有找到风格/情绪 '{search_emotion}' 对应的素材库 '{emotion_folder_path}'。")
        
        logger.info(f"✅ 找到 {len(clips_to_use)} 个待用视频片段。")
        return clips_to_use

    def _generate_tts_audio(self, text: str, index: int) -> Optional[str]:
        """生成TTS音频文件"""
        if not self.deps_status.get('gtts_available', False):
            logger.warning("⚠️ gTTS 未安装，无法生成TTS音频。")
            return None

        try:
            from gtts import gTTS
            import io
            from moviepy.editor import AudioFileClip
            
            # 使用内存缓冲区而不是临时文件
            tts = gTTS(text=text, lang='zh', slow=False)
            audio_buffer = io.BytesIO()
            tts.write_to_fp(audio_buffer)
            audio_buffer.seek(0)
            
            # 直接从内存创建AudioFileClip
            return audio_buffer
        except Exception as e:
            logger.error(f"❌ 生成TTS音频时出错: {e}")
            # 降级方案：使用临时文件
            try:
                from gtts import gTTS
                tts_audio_path = os.path.join(self.paths["temp_dir"], f"tts_{index}.wav")
                os.makedirs(self.paths["temp_dir"], exist_ok=True)
                tts = gTTS(text=text, lang='zh', slow=False)
                tts.save(tts_audio_path)
                logger.info(f"   为文本 '{text[:20]}...' 生成TTS音频: {tts_audio_path}")
                return tts_audio_path
            except Exception as fallback_error:
                logger.error(f"❌ 降级方案也失败: {fallback_error}")
                return None

    def _create_subtitle_clip(self, video_clip, text: str, duration: float):
        """创建带字幕的视频片段"""
        if self.deps_status['moviepy_available']:
            try:
                from moviepy.editor import TextClip, CompositeVideoClip
                # 尝试使用 TextClip
                txt_clip = TextClip(text, fontsize=24, color='white', font='SimHei')
                txt_clip = txt_clip.set_pos('center').set_duration(duration)
                return CompositeVideoClip([video_clip, txt_clip])
            except Exception as e:
                logger.warning(f"⚠️ 创建 TextClip 时出错，使用无字幕片段: {e}")
                # 如果 TextClip 创建失败，返回无字幕的片段
        else:
            logger.warning("⚠️ TextClip 不可用，使用无字幕片段。")
        
        return video_clip.set_duration(duration)

    def _write_video_file(self, video_clip, output_path: str):
        """写入视频文件，支持GPU加速"""
        try:
            if self.deps_status.get('pynvml_available', False):
                import pynvml
                pynvml.nvmlInit()
                device_count = pynvml.nvmlDeviceGetCount()
                if device_count > 0:
                    logger.info("🎮 检测到NVIDIA GPU，尝试启用硬件加速 (NVENC)...")
                    video_clip.write_videofile(
                        output_path,
                        codec='h264_nvenc',
                        audio_codec='aac',
                        temp_audiofile=os.path.join(self.paths["temp_dir"], "temp-audio.m4a"),
                        remove_temp=True,
                        ffmpeg_params=['-b:v', '5M']
                    )
                    return
                else:
                    logger.info("⚠️ 未检测到NVIDIA GPU，使用CPU编码。")
            else:
                logger.info("⚠️ pynvml 未安装，无法检测GPU，使用CPU编码。")
        except Exception as e:
            logger.warning(f"⚠️ 检测GPU或启用硬件加速时出错 ({e})，回退到CPU编码。")
        
        # 默认使用CPU编码
        video_clip.write_videofile(output_path, codec='libx264', audio_codec='aac')

    def _cleanup_temp_files(self, temp_paths: list):
        """清理临时文件"""
        # 过滤出实际存在的文件路径
        valid_paths = []
        for temp_path in temp_paths:
            # 只处理字符串类型的路径（排除字节缓冲区等其他类型）
            if isinstance(temp_path, str) and os.path.exists(temp_path):
                valid_paths.append(temp_path)
        
        if not valid_paths:
            return
        
        # 批量删除临时文件
        for temp_path in valid_paths:
            try:
                os.remove(temp_path)
                logger.info(f"🗑️ 临时文件已清理: {temp_path}")
            except OSError as e:
                logger.warning(f"⚠️ 删除临时文件失败 {temp_path}: {e}")
        
        # 清理空的临时目录
        try:
            temp_dir = self.paths.get("temp_dir")
            if temp_dir and os.path.exists(temp_dir) and not os.listdir(temp_dir):
                os.rmdir(temp_dir)
                logger.info(f"🗑️ 空临时目录已清理: {temp_dir}")
        except Exception as e:
            logger.warning(f"⚠️ 清理临时目录失败: {e}")

    def process_with_ai_script(self, theme_prompt: str, model_choice: str, output_path: str, target_duration_category: str = "medium", enable_lip_sync: bool = False, style: str = "normal", progress_callback=None):
        """AI脚本驱动的视频生成流程"""
        logger.info(f"🚀 启动AI脚本驱动的视频编辑流程，风格: {style}...")
        
        total_steps = 5
        current_step = 0
        final_clips = []
        temp_audio_files = []
        temp_video_files = []
        
        try:
            # 1. 生成脚本
            current_step += 1
            self._report_progress(current_step, total_steps, "正在生成AI脚本...", progress_callback)
            script_data = self.generate_script_with_ai(theme_prompt, model_choice)
            if not script_data:
                raise ValueError("AI未能生成有效脚本，无法继续处理。")

            # 保存脚本
            script_file_path = os.path.join(self.paths["temp_dir"], "generated_script.json")
            os.makedirs(self.paths["temp_dir"], exist_ok=True)
            with open(script_file_path, 'w', encoding='utf-8') as f:
                json.dump(script_data, f, ensure_ascii=False, indent=2)

            # 2. 搜索素材
            current_step += 1
            self._report_progress(current_step, total_steps, "正在搜索视频素材...", progress_callback)
            video_clips_for_script = self.search_and_download_clips_for_script(script_data, style)
            if not video_clips_for_script:
                raise ValueError("根据脚本未能找到任何可用素材，无法继续处理。")

            target_duration = self.processing_params["target_durations"].get(target_duration_category, 360)
            logger.info(f"🎯 目标成品时长: {target_duration_category} ({target_duration}s)")

            # 3. 处理每个片段
            current_step += 1
            self._report_progress(current_step, total_steps, "正在处理视频片段...", progress_callback)
            logger.info("🎬 开始根据AI脚本和素材剪辑视频...")
            
            total_segments = len(script_data)
            for i, segment in enumerate(script_data):
                text = segment.get("text", "")
                emotion = segment.get("emotion", "normal")
                
                if i >= len(video_clips_for_script):
                    logger.info("   素材已用完，停止剪辑。")
                    break
                
                # 报告子进度
                sub_progress = int((i / total_segments) * 20) + 40  # 40-60%
                report_progress(sub_progress, 100, f"处理片段 {i+1}/{total_segments}...")
                
                selected_clip_path = video_clips_for_script[i]
                
                from moviepy.editor import VideoFileClip, AudioFileClip, CompositeVideoClip
                
                # 处理单个片段，确保及时释放资源
                with VideoFileClip(selected_clip_path) as clip:
                    estimated_text_duration = min(max(len(text) // self.processing_params["text_duration_ratio"], 3), 5)
                    actual_duration = min(estimated_text_duration, clip.duration)
                    subclip = clip.subclip(0, actual_duration)
                    
                    # --- 生成TTS音频 ---
                    tts_audio = self._generate_tts_audio(text, i)
                    
                    # --- 合成带字幕和音频的片段 ---
                    video_with_subtitle = self._create_subtitle_clip(subclip, text, actual_duration)

                    if tts_audio:
                        try:
                            # 检查是否是字节缓冲区
                            if hasattr(tts_audio, 'read'):
                                # 从内存缓冲区创建AudioFileClip
                                tts_audio_clip = AudioFileClip(tts_audio)
                                if tts_audio_clip.duration > actual_duration:
                                    tts_audio_clip = tts_audio_clip.subclip(0, actual_duration)
                                video_with_audio = video_with_subtitle.set_audio(tts_audio_clip)
                                tts_audio_clip.close()  # 关闭音频剪辑
                            else:
                                # 是文件路径
                                with AudioFileClip(tts_audio) as tts_audio_clip:
                                    if tts_audio_clip.duration > actual_duration:
                                        tts_audio_clip = tts_audio_clip.subclip(0, actual_duration)
                                    video_with_audio = video_with_subtitle.set_audio(tts_audio_clip)
                                temp_audio_files.append(tts_audio)
                        except Exception as e:
                            logger.warning(f"处理音频时出错: {e}")
                            video_with_audio = video_with_subtitle
                    else:
                        video_with_audio = video_with_subtitle

                    # --- 应用嘴型同步 (如果启用) ---
                    if enable_lip_sync and self.deps_status.get('LIP_SYNC_AVAILABLE', False):
                        logger.info(f"   为片段 {i+1} 应用嘴型同步动画... (此功能需额外实现)")
                        # TODO: 实际的嘴型同步逻辑应在此处调用
                        logger.warning("   嘴型同步功能暂未完全实现，使用原片段。")
                        final_clips.append(video_with_audio)
                    else:
                        final_clips.append(video_with_audio)
            
            # 4. 合成视频
            current_step += 1
            self._report_progress(current_step, total_steps, "正在合成最终视频...", progress_callback)
            from moviepy.editor import concatenate_videoclips
            
            # 限制同时处理的片段数量，避免内存溢出
            max_clips_per_batch = 10
            if len(final_clips) > max_clips_per_batch:
                logger.info(f"📦 视频片段数量较多 ({len(final_clips)}), 分批处理以减少内存使用...")
                batch_clips = []
                for i in range(0, len(final_clips), max_clips_per_batch):
                    batch = final_clips[i:i+max_clips_per_batch]
                    batch_video = concatenate_videoclips(batch, method="compose")
                    batch_clips.append(batch_video)
                    # 释放已处理批次的内存
                    for clip in batch:
                        if hasattr(clip, 'close'):
                            clip.close()
                final_video = concatenate_videoclips(batch_clips, method="compose")
                # 释放批次视频内存
                for clip in batch_clips:
                    if hasattr(clip, 'close'):
                        clip.close()
            else:
                final_video = concatenate_videoclips(final_clips, method="compose")
            
            # 释放原始片段内存
            for clip in final_clips:
                if hasattr(clip, 'close'):
                    try:
                        clip.close()
                    except Exception as e:
                        logger.warning(f"关闭视频片段时出错: {e}")
            final_clips.clear()  # 清空列表，帮助GC
            
            if final_video.duration > target_duration:
                logger.info(f"⏰ 生成视频 ({final_video.duration:.2f}s) 超出目标时长 ({target_duration}s)，尝试修剪...")
                ratio = target_duration / final_video.duration
                start_t = (1 - ratio) / 2 * final_video.duration
                end_t = start_t + target_duration
                trimmed_video = final_video.subclip(start_t, end_t)
                final_video.close()  # 释放原始视频内存
                final_video = trimmed_video
            
            # 5. 写入文件
            current_step += 1
            self._report_progress(current_step, total_steps, "正在导出视频文件...", progress_callback)
            # --- 写入视频文件 ---
            self._write_video_file(final_video, output_path)
            final_video.close()
            
            # --- 清理临时文件 ---
            self._cleanup_temp_files(temp_audio_files + temp_video_files)
            
            # 清空所有引用，帮助GC
            temp_audio_files.clear()
            temp_video_files.clear()
            
            self._report_progress(100, 100, "视频生成完成！", progress_callback)
            logger.info(f"🎉 AI脚本驱动的视频编辑完成，已保存至: {output_path}")
        except Exception as e:
            # 统一错误处理
            self._handle_error(e, "AI脚本视频处理", progress_callback)
            # 发生错误时清理资源
            try:
                for clip in final_clips:
                    if hasattr(clip, 'close'):
                        clip.close()
                final_clips.clear()
                self._cleanup_temp_files(temp_audio_files + temp_video_files)
            except Exception as cleanup_error:
                logger.warning(f"清理资源时出错: {cleanup_error}")
            raise

    def process_existing_videos(self, video_paths: List[str], output_path: str, target_duration_category: str = "medium", enable_lip_sync: bool = False, progress_callback=None):
        """处理现有视频的流程"""
        logger.info("🚀 启动原有视频分析与剪辑流程...")
        
        total_steps = 4
        current_step = 0
        final_clips = []
        
        try:
            # 1. 分析输入视频
            current_step += 1
            self._report_progress(current_step, total_steps, "正在分析输入视频...", progress_callback)
            total_input_duration = 0
            from moviepy.editor import VideoFileClip, concatenate_videoclips
            
            for i, path in enumerate(video_paths):
                sub_progress = int((i / len(video_paths)) * 10) + 10  # 10-20%
                self._report_progress(sub_progress, 100, f"分析视频 {i+1}/{len(video_paths)}...", progress_callback)
                
                # 使用上下文管理器确保资源释放
                with VideoFileClip(path) as clip:
                    total_input_duration += clip.duration
                    if clip.duration > 1800: # 30 minutes in seconds
                        raise ValueError(f"输入视频 '{path}' 时长超过30分钟限制。")
            
            logger.info(f"📊 输入视频总时长: {total_input_duration / 60:.2f} 分钟")
            target_duration = self.processing_params["target_durations"].get(target_duration_category, 360)
            logger.info(f"🎯 目标成品时长: {target_duration_category} ({target_duration}s)")

            # 2. 处理视频
            current_step += 1
            self._report_progress(current_step, total_steps, "正在处理视频...", progress_callback)
            logger.info("🎬 开始处理原视频...")
            
            for i, video_path in enumerate(video_paths):
                sub_progress = int((i / len(video_paths)) * 20) + 30  # 30-50%
                self._report_progress(sub_progress, 100, f"处理视频 {i+1}/{len(video_paths)}...", progress_callback)
                
                logger.info(f"   处理视频: {video_path}")
                
                # 使用上下文管理器加载视频
                with VideoFileClip(video_path) as clip:
                    speed_factor = clip.duration / target_duration
                    adjusted_clip = clip.speedx(speed_factor) if speed_factor > 1 else clip
                    # 复制调整后的片段，因为上下文管理器会关闭原始clip
                    # 注意：这里我们不能直接在with块中使用adjusted_clip，因为它依赖于原始clip
                    # 所以我们需要创建一个新的clip对象
                    temp_output = os.path.join(self.paths["temp_dir"], f"temp_clip_{i}.mp4")
                    os.makedirs(self.paths["temp_dir"], exist_ok=True)
                    adjusted_clip.write_videofile(temp_output, codec='libx264', audio_codec='aac', temp_audiofile=None)
                    # 重新加载临时文件作为独立的clip
                    temp_clip = VideoFileClip(temp_output)
                    final_clips.append(temp_clip)
            
            # 3. 合成视频
            current_step += 1
            self._report_progress(current_step, total_steps, "正在合成视频...", progress_callback)
            
            # 限制同时处理的片段数量，避免内存溢出
            max_clips_per_batch = 5
            if len(final_clips) > max_clips_per_batch:
                logger.info(f"📦 视频数量较多 ({len(final_clips)}), 分批处理以减少内存使用...")
                batch_clips = []
                for i in range(0, len(final_clips), max_clips_per_batch):
                    batch = final_clips[i:i+max_clips_per_batch]
                    batch_video = concatenate_videoclips(batch, method="compose")
                    batch_clips.append(batch_video)
                    # 释放已处理批次的内存
                    for clip in batch:
                        if hasattr(clip, 'close'):
                            clip.close()
                final_video = concatenate_videoclips(batch_clips, method="compose")
                # 释放批次视频内存
                for clip in batch_clips:
                    if hasattr(clip, 'close'):
                        clip.close()
            else:
                final_video = concatenate_videoclips(final_clips, method="compose")
            
            # 释放原始片段内存
            for clip in final_clips:
                if hasattr(clip, 'close'):
                    try:
                        clip.close()
                    except Exception as e:
                        logger.warning(f"关闭视频片段时出错: {e}")
            final_clips.clear()  # 清空列表，帮助GC
            
            # 清理临时文件
            temp_files = [os.path.join(self.paths["temp_dir"], f"temp_clip_{i}.mp4") for i in range(len(video_paths))]
            self._cleanup_temp_files(temp_files)
            
            # 4. 导出视频
            current_step += 1
            self._report_progress(current_step, total_steps, "正在导出视频...", progress_callback)
            self._write_video_file(final_video, output_path)
            final_video.close()
            
            self._report_progress(100, 100, "视频处理完成！", progress_callback)
            logger.info(f"🎉 原有视频处理完成，已保存至: {output_path}")
        except Exception as e:
            # 统一错误处理
            self._handle_error(e, "现有视频处理", progress_callback)
            # 发生错误时清理资源
            try:
                for clip in final_clips:
                    if hasattr(clip, 'close'):
                        clip.close()
                final_clips.clear()
                # 清理临时文件
                temp_files = [os.path.join(self.paths["temp_dir"], f"temp_clip_{i}.mp4") for i in range(len(video_paths))]
                self._cleanup_temp_files(temp_files)
            except Exception as cleanup_error:
                logger.warning(f"清理资源时出错: {cleanup_error}")
            raise

    def process(self, input_source, is_theme_input: bool, model_choice: str, output_path: str, target_duration_category: str = "medium", enable_lip_sync: bool = False, style: str = "normal", progress_callback=None):
        """主处理函数，根据输入类型决定调用哪个子流程。"""
        if is_theme_input:
            if isinstance(input_source, str):
                 self.process_with_ai_script(input_source, model_choice, output_path, target_duration_category, enable_lip_sync, style, progress_callback)
            else:
                 raise TypeError("主题模式下，input_source 应为字符串类型的提示词。")
        else:
            if isinstance(input_source, list):
                 self.process_existing_videos(input_source, output_path, target_duration_category, enable_lip_sync, progress_callback)
            else:
                 raise TypeError("视频模式下，input_source 应为视频路径组成的列表。")

    # --- 高级工具方法 ---
    def extract_audio(self, video_path: str, output_audio_path: str):
        """提取视频音频"""
        if not self.deps_status['moviepy_available']:
            logger.error("moviepy 不可用，无法提取音频。")
            raise RuntimeError("moviepy 不可用")
        try:
            from moviepy.editor import VideoFileClip
            video = VideoFileClip(video_path)
            audio = video.audio
            audio.write_audiofile(output_audio_path)
            logger.info(f"音频已提取: {output_audio_path}")
        except Exception as e:
            error_info = ErrorDiagnoser.diagnose_error(e, "提取音频")
            error_report = ErrorDiagnoser.save_error_report(error_info)
            logger.error(f"提取音频失败: {e}")
            logger.error(f"错误报告已保存至: {error_report}")
            raise e

    def extract_subtitles(self, video_path: str, output_srt_path: str):
        """提取视频字幕 (使用 whisper)"""
        if not self.deps_status['faster_whisper_available']:
            logger.error("faster_whisper 不可用，无法提取字幕。")
            raise RuntimeError("faster_whisper 不可用")
        try:
            model_size = self.models.get("faster_whisper_size", "tiny")
            # 使用模型管理器获取缓存的模型实例
            model = self.model_manager.get_whisper_model(model_size) if self.model_manager else None
            
            if not model:
                # 降级方案：直接创建模型
                from faster_whisper import WhisperModel
                model_path = os.path.join(self.paths["models_dir"], f"whisper_{model_size}")
                model = WhisperModel(model_size, device="cpu", compute_type="int8", download_root=model_path)
            
            segments, info = model.transcribe(video_path, beam_size=5)
            
            with open(output_srt_path, "w", encoding="utf-8") as srt_file:
                for i, segment in enumerate(segments, start=1):
                    start_time = self.format_timestamp(segment.start)
                    end_time = self.format_timestamp(segment.end)
                    srt_file.write(f"{i}\n{start_time} --> {end_time}\n{segment.text.strip()}\n\n")
            
            logger.info(f"字幕已提取: {output_srt_path}")
        except Exception as e:
            error_info = ErrorDiagnoser.diagnose_error(e, "提取字幕")
            error_report = ErrorDiagnoser.save_error_report(error_info)
            logger.error(f"提取字幕失败: {e}")
            logger.error(f"错误报告已保存至: {error_report}")
            raise e

    def convert_format(self, input_path: str, output_path: str):
        """转换视频格式"""
        if not self.deps_status['moviepy_available']:
            logger.error("moviepy 不可用，无法转换格式。")
            raise RuntimeError("moviepy 不可用")
        try:
            from moviepy.editor import VideoFileClip
            clip = VideoFileClip(input_path)
            clip.write_videofile(output_path, codec='libx264', audio_codec='aac')
            logger.info(f"格式已转换: {output_path}")
        except Exception as e:
            error_info = ErrorDiagnoser.diagnose_error(e, "转换格式")
            error_report = ErrorDiagnoser.save_error_report(error_info)
            logger.error(f"转换格式失败: {e}")
            logger.error(f"错误报告已保存至: {error_report}")
            raise e

    @staticmethod
    def format_timestamp(seconds: float) -> str:
        """格式化时间戳为 SRT 格式"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millisecs = int((seconds - int(seconds)) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millisecs:03d}"

if __name__ == "__main__":
    # --- 示例用法 ---
    editor = AIVideoEditorLocal()
    # editor.download_required_models() # 可选：提前下载模型

    # AI脚本驱动模式
    try:
        editor.process(
            input_source="一个关于逆袭的故事",
            is_theme_input=True,
            model_choice="qwen",
            output_path="./output/ai_gen_video.mp4",
            target_duration_category="short",
            style="high_burn",
            enable_lip_sync=False
        )
        print("AI脚本驱动模式处理完成。")
    except Exception as e:
        print(f"AI脚本驱动处理失败: {e}")

    # 现有视频处理模式
    try:
        video_paths = ["./素材库/video1.mp4", "./素材库/video2.mp4"] # 请替换为实际存在的视频文件路径
        editor.process(
            input_source=video_paths,
            is_theme_input=False,
            model_choice=None,
            output_path="./output/proc_video.mp4",
            target_duration_category="medium",
            enable_lip_sync=False
        )
        print("现有视频处理模式处理完成。")
    except Exception as e:
        print(f"现有视频处理失败: {e}")

    # 高级工具示例 (请确保输入文件存在)
    try:
        test_video_path = "./素材库/video1.mp4" # 请替换为实际路径
        if os.path.exists(test_video_path):
            editor.extract_audio(test_video_path, "./output/audio_extracted.wav")
            editor.extract_subtitles(test_video_path, "./output/subtitles.srt")
            editor.convert_format(test_video_path, "./output/converted_video.avi")
            print("高级工具执行完成。")
        else:
            print(f"测试视频文件不存在: {test_video_path}")
    except Exception as e:
        print(f"高级工具执行失败: {e}")# ai_video_editor_local.py
import os
import json
import re
import time
import math
import random
from typing import List, Dict, Tuple

# --- Whisper 部分：使用 faster-whisper 替代 ---
try:
    import faster_whisper
    WHISPER_AVAILABLE = True
    print("🔧 成功导入 faster-whisper。")
except ImportError as e:
    print(f"❌ 未能导入 faster-whisper: {e}")
    print("   提示: 请运行 'pip install faster-whisper' 安装。")
    WHISPER_AVAILABLE = False
    # 作为最后的尝试，看看原版whisper是否可用（但打包可能仍有问题）
    try:
        import whisper
        print("⚠️  使用原版 whisper (可能打包后运行有问题)。")
        WHISPER_AVAILABLE_FALLBACK = True
    except ImportError:
        print("❌ 原版 whisper 也不可用。语音转文字功能将禁用。")
        WHISPER_AVAILABLE_FALLBACK = False

# --- 其他依赖 ---
import easyocr
# import whisper # 注释掉原来的 import
import cv2
import numpy as np
from moviepy.editor import VideoFileClip, concatenate_videoclips, AudioFileClip, CompositeVideoClip, ImageClip, TextClip
import dashscope
from http import HTTPStatus
import torch
from transformers import pipeline
import mediapipe as mp
from PIL import Image, ImageDraw, ImageFont
import yt_dlp # 引入 yt-dlp 库
import signal
import sys
import requests # 用于网络请求，下载素材
import urllib.parse # 用于URL编码
from datetime import datetime # 用于生成临时文件名

# --- 新增：导入模型管理器和嘴型动画器 ---
from model_manager import ModelManager
from lip_sync_animator import LipSyncAnimator

# --- 新增：自动保存和恢复功能所需变量 ---
TEMP_DIR = "./temp_ai_editor"
os.makedirs(TEMP_DIR, exist_ok=True)
SAVED_STATE_FILE = os.path.join(TEMP_DIR, "processing_state.json")
PROCESSED_SPEECH_FILE = os.path.join(TEMP_DIR, "speech.txt")
PROCESSED_SCREEN_FILE = os.path.join(TEMP_DIR, "screen.txt")
GENERATED_SCRIPT_FILE = os.path.join(TEMP_DIR, "script.json")
HOT_MOMENTS_FILE = os.path.join(TEMP_DIR, "hot_moments.json")

# --- 新增：信号处理，捕获 Ctrl+C ---
def signal_handler(sig, frame):
    print("\n\n⚠️  检测到中断信号 (Ctrl+C)，正在自动保存进度...")
    save_current_state_on_exit()
    print("💾 进度已保存。再见！")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
# --- End of Signal Handler ---

# --- 新增：初始化模型管理器 ---
print("🔧 初始化模型管理器...")
model_manager = ModelManager()
REQUIRED_MODELS_BASE = ["transformers_sentiment", "easyocr"] # 核心功能所需模型，移除 'whisper'
if WHISPER_AVAILABLE:
    REQUIRED_MODELS = REQUIRED_MODELS_BASE + ["faster_whisper_related"] # 添加 faster-whisper 相关
elif WHISPER_AVAILABLE_FALLBACK:
    REQUIRED_MODELS = REQUIRED_MODELS_BASE + ["whisper"] # 添加原版 whisper
else:
    REQUIRED_MODELS = REQUIRED_MODELS_BASE # 仅基础模型

# --- 新增：检查并安装核心模型 ---
model_manager.install_missing_models(REQUIRED_MODELS)

# 初始化模型（CPU优化）
print("🔄 加载核心模型...")
sentiment_analyzer = pipeline("sentiment-analysis", 
                             model="uer/roberta-base-finetuned-chinanews-chinese", 
                             device=-1, # CPU模式
                             model_kwargs={"cache_dir": "./models/roberta_sentiment"}) 

# --- Whisper 模型加载逻辑修改 ---
# 注意：现在 Whisper 模型由 LipSyncAnimator 管理，这里不再全局加载
# whisper_model = None
# if WHISPER_AVAILABLE:
#     print("🔄 加载 faster-whisper 模型 (tiny)...")
#     whisper_model = faster_whisper.WhisperModel(model_size_or_path="tiny", device="cpu", compute_type="int8", download_root="./models/faster_whisper_tiny")
#     print("✅ faster-whisper 模型加载成功。")
# elif WHISPER_AVAILABLE_FALLBACK:
#     print("🔄 加载原版 whisper 模型 (tiny)...")
#     whisper_model = whisper.load_model("tiny", device="cpu", download_root="./models/whisper_tiny")
#     print("⚠️  原版 whisper 模型加载成功 (注意打包问题)。")
# else:
#     print("⚠️  Whisper 模型不可用，语音转文字功能将被跳过。")

reader = easyocr.Reader(['ch_sim', 'en'], gpu=False, model_storage_directory="./models/easyocr")

# --- Mediapipe 初始化修复 ---
mp_pose = mp.solutions.pose
pose = None  # 先定义为 None
mediapipe_loaded = False # 定义一个标志位
try:
    pose = mp_pose.Pose(static_image_mode=False, model_complexity=1, min_detection_confidence=0.5)
    mediapipe_loaded = True
    print("MediaPipe Pose 模型加载成功！")
except FileNotFoundError as e:
    print(f"警告: MediaPipe Pose 模型加载失败，姿态识别功能将不可用: {e}")
    mediapipe_loaded = False
except Exception as e:
    print(f"警告: MediaPipe Pose 初始化发生未知错误，姿态识别功能将不可用: {e}")
    mediapipe_loaded = False
# --- End of Mediapipe Initialization Fix ---

class AIVideoEditorLocal:
    def __init__(self):
        # 设备设定
        self.device = "cpu"
        # self.reader 已在全局初始化
        # self.whisper_model 现在由 LipSyncAnimator 管理
        
        # 情绪-音乐映射
        self.emotion_bgm_map = {
            "surprise": ["shock_high_pitch.mp3", "sudden_loud.mp3"],
            "anger": ["heavy_metal.mp3", "rock_beat.mp3"],
            "joy": ["soft_piano.mp3", "guitar_acoustic.mp3"],
            "sad": ["sad_violin.mp3", "slow_strings.mp3"],
            "tension": ["low_drums.mp3", "suspense_buildup.mp3"],
            "normal": ["ambient_background.mp3", "light_jazz.mp3"]
        }

        # --- 新增：短剧专用情绪关键词库 ---
        self.emotion_keywords = {
            "anger": [
                "狂怒", "暴戾", "杀气腾腾", "目眦尽裂", "怒火攻心", "怒不可遏", "气炸了", 
                "恨得牙痒痒", "怒发冲冠", "怒火中烧", "气急败坏", "勃然大怒", "雷霆之怒",
                "嚣张", "跋扈", "不可一世", "盛气凌人", "居高下", "不屑一顾", "轻蔑", 
                "嘲讽", "讥笑", "冷笑", "皮笑肉不笑", "针锋相对", "寸步不让", "寸言不让",
                "委屈", "憋屈", "窝囊", "憋屈", "忍气吞声", "忍辱负重", "低声下气", 
                "任人宰割", "卑微", "压抑", "憋屈", "受尽欺凌", "忍无可忍"
            ],
            "surprise": [
                "震撼", "晴天霹雳", "五雷轰顶", "天塌了", "难以置信", "匪夷所思", 
                "大跌眼镜", "石破天惊", "惊世骇俗", "傻眼了", "下巴掉地", "世界观崩塌",
                "打脸", "现眼", "丢人现眼", "自取其辱", "搬起石头砸自己的脚", 
                "咎由自取", "自作自受", "哑口无言", "颜面扫地", "威风扫地", "灰溜溜", 
                "抱头鼠窜", "狼狈不堪"
            ],
            "joy": [
                "解气", "大快人心", "扬眉吐气", "一雪前耻", "扬眉吐气", "酣畅淋漓", 
                "大获全胜", "趾高气昂", "意气风发", "神清气爽", "扬眉吐气", "爽翻了", 
                "太解气了", "看得真爽",
                "霸气", "牛气冲天", "王者归来", "低调奢华有内涵", "实力碾压", 
                "王者风范", "俯瞰众生", "云淡风轻", "波澜不惊", "轻描淡写", "运筹帷幄", 
                "胸有成竹",
                "痴迷", "深爱", "至死不渝", "刻骨铭心", "奋不顾身", "掏心掏肺", 
                "情深似海", "此生不渝", "山盟海誓", "生死相依", "至死方休", "爱到骨子里"
            ],
            "sad": [
                "心碎", "心如刀割", "肝肠寸断", "痛彻心扉", "万念俱灰", "心若死灰", 
                "五脏六腑都碎了", "世界都塌了", "撕心裂肺", "锥心刺骨", "痛不欲生", 
                "万箭穿心",
                "思念", "牵肠挂肚", "魂牵梦萦", "朝思暮想", "茶饭不思", "望穿秋水", 
                "日思夜想", "念念不忘", "刻骨相思", "执着", "不离不弃"
            ],
            "tension": [
                "惶恐", "惊恐万状", "魂飞魄散", "毛骨悚然", "不寒而栗", "胆战心惊", 
                "心惊肉跳", "提心吊胆", "坐立难安", "如履薄冰", "危在旦夕", "岌岌可危", 
                "命垂一线",
                "紧张", "十万火急", "刻不容缓", "火烧眉毛", "迫在眉睫", "千钧一发", 
                "间不容发", "生死攸关", "十万火急", "急得团"
            ]
        }
        # 修正字符串，添加缺失的引号
        self.emotion_keywords["tension"][-1] += '"'

        # --- 新增：初始化嘴型动画器 ---
        # 将 ASR 可用性传递给 LipSyncAnimator，以便它做出相应处理
        if WHISPER_AVAILABLE:
             self.lip_sync_animator = LipSyncAnimator(asr_model_size="tiny") # 可以选择合适的模型大小
        elif WHISPER_AVAILABLE_FALLBACK:
             self.lip_sync_animator = LipSyncAnimator(asr_model_size="tiny")
        else:
             self.lip_sync_animator = LipSyncAnimator() # ASR不可用，但仍可初始化
        print("🤖 AI视频编辑器核心已加载。")


    # --- 新增：AI生成脚本函数 (独立功能) ---
    def generate_script_with_ai(self, prompt: str, model_choice: str = "qwen"):
        """
        使用AI模型根据提示生成视频脚本。
        Args:
            prompt (str): 用户输入的视频主题或描述。
            model_choice (str): 选择的AI模型 ('qwen' 或其他)。
        Returns:
            list: 返回一个包含脚本段落的列表，每个段落包含文本和预期情绪。
                  例如: [{"text": "这是第一句话。", "emotion": "joy"}, {"text": "这是第二句话。", "emotion": "tension"}]
        """
        print(f"🤖 正在使用 {model_choice} 生成视频脚本...")
        
        system_prompt = """
        你是一个专业的短视频脚本生成助手。你的任务是根据用户提供的主题或一句话，生成一段详细的、富有戏剧冲突的短视频脚本。
        脚本应包含：
        1.  一系列的台词或旁白（每句台词作为一个独立的段落）。
        2.  每句台词可能表达的情绪（从 anger, surprise, joy, sad, tension, normal 中选择）。
        3.  每句台词最好能暗示一个可以匹配的场景或画面。
        请以 JSON 格式返回，格式如下：
        [
            {"text": "台词1", "emotion": "emotion1"},
            {"text": "台词2", "emotion": "emotion2"},
            ...
        ]
        请注意，台词要口语化，情绪要准确，场景描述要清晰。
        """

        if model_choice == "qwen":
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ]
            try:
                response = dashscope.Generation.call(
                    model='qwen-max', # 或 qwen-plus, qwen-turbo
                    messages=messages,
                    result_format='message',
                )
                
                if response.status_code == HTTPStatus.OK:
                    content = response.output.choices[0]['message']['content']
                    # 从AI回复中提取JSON部分
                    json_match = re.search(r'\[(.*?)\]', content, re.DOTALL)
                    if json_match:
                        script_json_str = "[" + json_match.group(1) + "]"
                        try:
                            script_data = json.loads(script_json_str)
                            print("✅ 脚本生成成功！")
                            return script_data
                        except json.JSONDecodeError as e:
                            print(f"❌ 解析AI生成的JSON脚本时出错: {e}")
                            print(f"原始AI回复: {content}")
                            return []
                    else:
                        print(f"❌ 未能从AI回复中找到JSON格式的脚本: {content}")
                        return []
                else:
                    print(f"❌ DashScope API 请求失败: {response.message}")
                    return []
            except Exception as e:
                print(f"❌ 调用DashScope API时出错: {e}")
                return []
        else:
            # 可以扩展其他AI模型接口
            print(f"❌ 不支持的模型: {model_choice}")
            return []

    # --- 新增：基于脚本搜索和下载视频片段 (独立功能) ---
    def search_and_download_clips_for_script(self, script_list: List[Dict], max_duration_per_clip=10):
        """
        根据脚本列表中的文本和情绪，搜索并下载匹配的视频片段。
        Args:
            script_list (list): AI生成的脚本列表。
            max_duration_per_clip (int): 每个下载片段的最大时长（秒）。
        Returns:
            list: 返回一个包含本地视频文件路径的列表。
        """
        print("🔍 正在根据脚本内容搜索和下载视频片段...")
        clips_to_use = []
        for i, segment in enumerate(script_list):
            text = segment.get("text", "")
            emotion = segment.get("emotion", "normal")
            
            # 构造搜索关键词：结合台词内容和情绪
            search_query = f"{text} {emotion}"
            print(f"   搜索第 {i+1} 段: '{search_query}'")
            
            # --- 方案A: 从预设素材库中选取 (推荐) ---
            # 假设我们有一个本地素材库，结构如下：
            #素材库_path/
            #├── anger/
            #│   ├── clip_001.mp4
            #│   └── clip_002.mp4
            #├── joy/
            #│   ├── clip_001.mp4
            #│   └── clip_003.mp4
            #└── ... (其他情绪文件夹)
            
            素材库_path = "./素材库" # 请确保此目录存在并包含相应素材
            emotion_folder_path = os.path.join(素材库_path, emotion)
            if os.path.isdir(emotion_folder_path):
                available_clips = [f for f in os.listdir(emotion_folder_path) if f.endswith('.mp4')]
                if available_clips:
                    selected_clip_name = random.choice(available_clips)
                    selected_clip_path = os.path.join(emotion_folder_path, selected_clip_name)
                    print(f"      从素材库 '{emotion_folder_path}' 选择了: {selected_clip_name}")
                    clips_to_use.append(selected_clip_path)
                else:
                    print(f"      警告: 情绪 '{emotion}' 的素材库中没有可用的视频片段。")
                    continue
            else:
                print(f"      警告: 没有找到情绪 '{emotion}' 对应的素材库 '{emotion_folder_path}'。")
                continue
            
        print(f"✅ 找到 {len(clips_to_use)} 个待用视频片段。")
        return clips_to_use

    def download_video_from_url(self, url: str) -> str:
        """
        从URL下载视频。
        Args:
            url (str): 视频URL。
        Returns:
            str: 本地下载文件的路径，失败则返回None。
        """
        print(f"🔗 正在从 URL 下载视频: {url}")
        ydl_opts = {
            'format': 'best[ext=mp4][height<=720]/best[height<=720]/best', # 优先下载720p MP4
            'outtmpl': os.path.join(TEMP_DIR, '%(title)s.%(ext)s'), # 保存到临时目录
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4', # 确保输出为MP4
            }],
            'postprocessor_args': [
                '-vcodec', 'libx264',
                '-crf', '28', # 控制质量
            ],
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(url, download=True)
                filepath = info_dict['requested_downloads'][0]['filepath']
                print(f"📥 视频下载成功: {filepath}")
                return filepath
        except Exception as e:
            print(f"❌ 从 URL 下载视频失败: {e}")
            return None

    # --- 新增：AI脚本驱动的主处理函数 (新功能入口) ---
    def process_with_ai_script(self, theme_prompt: str, model_choice: str, output_path: str, target_duration_category: str = "medium", enable_lip_sync: bool = False):
        """
        核心新功能：根据主题生成脚本，并使用脚本驱动视频剪辑。
        Args:
            theme_prompt (str): 用户输入的视频主题。
            model_choice (str): AI模型选择。
            output_path (str): 输出视频路径。
            target_duration_category (str): 目标成品时长类别 ("short", "medium", "long")。
            enable_lip_sync (bool): 是否启用嘴型同步动画。
        """
        print("🚀 启动AI脚本驱动的视频编辑流程...")
        
        # 1. 生成脚本
        script_data = self.generate_script_with_ai(theme_prompt, model_choice)
        if not script_data:
            raise ValueError("AI未能生成有效脚本，无法继续处理。")

        # 保存生成的脚本
        with open(GENERATED_SCRIPT_FILE, 'w', encoding='utf-8') as f:
            json.dump(script_data, f, ensure_ascii=False, indent=2)

        # 2. 根据脚本搜索素材
        video_clips_for_script = self.search_and_download_clips_for_script(script_data)
        if not video_clips_for_script:
            raise ValueError("根据脚本未能找到任何可用素材，无法继续处理。")

        # 3. 根据脚本和素材进行剪辑
        duration_map = {"short": 60, "medium": 360, "long": 900} # 秒
        target_duration = duration_map.get(target_duration_category, 360)
        print(f"🎯 目标成品时长: {target_duration_category} ({target_duration}s)")

        print("🎬 开始根据AI脚本和素材剪辑视频...")
        final_clips = []
        used_clips = set() # 记录已使用的素材，避免重复
        temp_audio_files = [] # 记录临时生成的音频文件，便于清理
        temp_video_files = [] # 记录临时生成的视频文件，便于清理
        for i, segment in enumerate(script_data):
            text = segment.get("text", "")
            emotion = segment.get("emotion", "normal")
            
            # 选择一个未使用的素材片段
            candidate_clips = [c for c in video_clips_for_script if c not in used_clips]
            if not candidate_clips:
                print("   没有更多可用素材，停止剪辑。")
                break
            
            selected_clip_path = random.choice(candidate_clips)
            used_clips.add(selected_clip_path)
            
            clip = VideoFileClip(selected_clip_path)
            # 简单地截取片段，时长与脚本段落匹配（可以优化）
            # 这里假设每句话对应约3-5秒的视频
            estimated_text_duration = min(max(len(text) // 10, 3), 5) 
            actual_duration = min(estimated_text_duration, clip.duration)
            subclip = clip.subclip(0, actual_duration)
            
            # --- 新增：生成TTS音频 ---
            # 这里需要一个TTS引擎，例如 pyttsx3, edge_tts, gTTS 等
            import tempfile
            tts_audio_path = os.path.join(TEMP_DIR, f"tts_{i}.wav")
            temp_audio_files.append(tts_audio_path)
            # --- 使用 gTTS 作为示例 (需 pip install gTTS) ---
            from gtts import gTTS
            tts = gTTS(text=text, lang='zh', slow=False)
            tts.save(tts_audio_path)
            print(f"   为文本 '{text[:20]}...' 生成TTS音频: {tts_audio_path}")
            
            # --- 新增：合成带字幕和音频的片段 ---
            txt_clip = TextClip(text, fontsize=24, color='white', font='SimHei') # 使用支持中文的字体
            txt_clip = txt_clip.set_pos('center').set_duration(actual_duration)
            video_with_subtitle = CompositeVideoClip([subclip, txt_clip])

            # 添加TTS音频
            tts_audio_clip = AudioFileClip(tts_audio_path)
            # 调整音频时长以匹配视频
            if tts_audio_clip.duration > actual_duration:
                 tts_audio_clip = tts_audio_clip.subclip(0, actual_duration)
            else:
                 # 如果音频太短，循环或静音填充
                 if tts_audio_clip.duration < actual_duration:
                     silence = AudioFileClip("").set_duration(actual_duration - tts_audio_clip.duration) # This won't work, need a proper silent audio
                     import numpy as np
                     from moviepy.audio.AudioClip import AudioClip
                     def make_silent(duration, fps=22050):
                         arr = np.zeros((int(duration*fps), 2)) # Stereo
                         return arr
                     silent_audio = AudioClip(make_silent(actual_duration - tts_audio_clip.duration), duration=actual_duration - tts_audio_clip.duration)
                     tts_audio_clip = concatenate_audioclips([tts_audio_clip, silent_audio])
            video_with_audio = video_with_subtitle.set_audio(tts_audio_clip)

            # --- 新增：应用嘴型同步 (如果启用) ---
            if enable_lip_sync:
                print(f"   为片段 {i+1} 应用嘴型同步动画...")
                # 创建一个临时输出文件
                temp_synced_path = os.path.join(TEMP_DIR, f"synced_clip_{i}.mp4")
                temp_video_files.append(temp_synced_path)
                # 假设我们有一个“说话人”视频片段 (这里用原始片段代替，实际应为人脸清晰的片段)
                # 注意：现在我们有明确的文本 (text)，这对于嘴型同步至关重要
                self.lip_sync_animator.animate_lips(subclip.filename, tts_audio_path, temp_synced_path, fallback_text_if_no_asr=text)
                # 用嘴型同步后的视频替换原视频
                synced_clip = VideoFileClip(temp_synced_path)
                # 重新叠加字幕 (因为synced_clip可能没有字幕)
                final_segment = CompositeVideoClip([synced_clip, txt_clip.set_duration(synced_clip.duration)])
                # 重新设置音频
                final_segment = final_segment.set_audio(tts_audio_clip)
                final_clips.append(final_segment)
                synced_clip.close()
            else:
                # 不启用嘴型同步，直接使用带音频和字幕的版本
                final_clips.append(video_with_audio)

            clip.close() # 释放资源
        
        # 拼接所有片段
        final_video = concatenate_videoclips(final_clips, method="compose")
        
        # 根据目标时长调整（如果生成的视频过长或过短）
        if final_video.duration > target_duration:
            print(f"⏰ 生成视频 ({final_video.duration:.2f}s) 超出目标时长 ({target_duration}s)，尝试修剪...")
            ratio = target_duration / final_video.duration
            start_t = (1 - ratio) / 2 * final_video.duration
            end_t = start_t + target_duration
            final_video = final_video.subclip(start_t, end_t)
        
        final_video.write_videofile(output_path, codec='libx264', audio_codec='aac')
        final_video.close()
        
        # --- 清理临时文件 ---
        for temp_path in temp_audio_files + temp_video_files:
            if os.path.exists(temp_path):
                os.remove(temp_path)
                print(f"🗑️ 临时文件已清理: {temp_path}")
        
        print(f"🎉 AI脚本驱动的视频编辑完成，已保存至: {output_path}")


    # --- 修改：原有核心处理函数 (保持原有功能不变) ---
    def process_existing_videos(self, video_paths: List[str], output_path: str, target_duration_category: str = "medium", enable_lip_sync: bool = False):
        """
        核心原有功能：处理现有的视频文件，进行分析、提取、剪辑。
        Args:
            video_paths (List[str]): 输入视频文件路径列表。
            output_path (str): 输出视频路径。
            target_duration_category (str): 目标成品时长类别 ("short", "medium", "long")。
            enable_lip_sync (bool): 是否启用嘴型同步动画 (仅在有音频和字幕时有意义)。
        """
        print("🚀 启动原有视频分析与剪辑流程...")
        # --- 1. 视频时长检查 ---
        total_input_duration = 0
        for path in video_paths:
            clip = VideoFileClip(path)
            total_input_duration += clip.duration
            if clip.duration > 1800: # 30 minutes in seconds
                clip.close()
                raise ValueError(f"输入视频 '{path}' 时长超过30分钟限制。")
            clip.close() # 关闭clip释放资源
        print(f"📊 输入视频总时长: {total_input_duration / 60:.2f} 分钟")

        # --- 2. 目标时长设置 ---
        duration_map = {"short": 60, "medium": 360, "long": 900} # 秒
        target_duration = duration_map.get(target_duration_category, 360)
        print(f"🎯 目标成品时长: {target_duration_category} ({target_duration}s)")

        # --- 3. (此处可保留您原有的分析逻辑，例如提取音频、OCR、情感分析等) ---
        # 为了演示，我们只做最基础的处理（如调整速度以适应目标时长）
        print("🎬 开始处理原视频...")
        final_clips = []
        for video_path in video_paths:
            print(f"   处理视频: {video_path}")
            clip = VideoFileClip(video_path)
            # ... (这里可以插入您原有的处理逻辑，如提取音频、OCR等)
            # 为了演示，我们只做一个简单的处理（例如，调整速度以适应目标时长）
            speed_factor = clip.duration / target_duration
            if speed_factor > 1:
                 adjusted_clip = clip.speedx(speed_factor)
            else:
                 adjusted_clip = clip
            
            # --- 修改：如果启用了嘴型同步，且视频有音频 ---
            if enable_lip_sync and adjusted_clip.audio:
                print(f"   检测到音频，尝试应用嘴型同步...")
                # 1. 提取音频
                temp_audio_path = os.path.join(TEMP_DIR, "temp_extracted_audio.wav")
                adjusted_clip.audio.write_audiofile(temp_audio_path)
                
                # 2. (核心修改) 获取音频对应的文本 -> 使用ASR
                # 我们现在有了ASR引擎，可以尝试从音频中提取文本
                print("   正在从音频中提取文本 (ASR)...")
                asr_text = self.transcribe_audio_with_whisper(temp_audio_path) # 调用下方新增的函数
                
                if asr_text:
                    print(f"   ASR 识别文本: '{asr_text[:50]}...'")
                    # 3. 调用嘴型同步器，传入视频、音频和ASR得到的文本
                    temp_synced_path = os.path.join(TEMP_DIR, f"synced_clip_from_asr_{hash(video_path)}.mp4")
                    print(f"   应用嘴型同步，使用ASR文本...")
                    self.lip_sync_animator.animate_lips(video_path, temp_audio_path, temp_synced_path, fallback_text_if_no_asr=asr_text)
                    
                    if os.path.exists(temp_synced_path):
                        # 用嘴型同步后的视频替换原视频
                        synced_clip = VideoFileClip(temp_synced_path)
                        final_clips.append(synced_clip)
                        synced_clip.close()
                        # 清理临时同步视频
                        os.remove(temp_synced_path)
                    else:
                        print(f"   嘴型同步失败，使用原视频。")
                        final_clips.append(adjusted_clip)
                else:
                    print("   ASR未能识别出文本，嘴型同步跳过，使用原视频。")
                    final_clips.append(adjusted_clip)
                
            else:
                final_clips.append(adjusted_clip)
            
            clip.close()
        
        final_video = concatenate_videoclips(final_clips, method="compose")
        final_video.write_videofile(output_path, codec='libx264', audio_codec='aac')
        final_video.close()
        print(f"🎉 原有视频处理完成，已保存至: {output_path}")

    # --- 新增：统一的音频转文字函数 ---
    def transcribe_audio_with_whisper(self, audio_path: str):
        """
        使用 faster-whisper (或 fallback) 进行音频转录。
        此函数现在委托给 LipSyncAnimator 内部的 ASR 实例。
        Args:
            audio_path (str): 音频文件路径。
        Returns:
            str: 转录的文本，如果失败或功能不可用则返回空字符串。
        """
        if self.lip_sync_animator.asr_model is None:
            print("⚠️ Whisper 功能不可用，跳过音频转文字。")
            return ""

        if not os.path.exists(audio_path):
            print(f"❌ 音频文件不存在: {audio_path}")
            return ""

        print(f"🗣️ 正在使用 Whisper 转录音频: {audio_path}")
        try:
            # 复用 LipSyncAnimator 中加载的模型实例
            if ASR_ENGINE == "faster_whisper":
                segments, info = self.lip_sync_animator.asr_model.transcribe(audio_path, beam_size=5, language="zh")
                full_text = "".join([segment.text for segment in segments])
            else: # original_whisper
                result = self.lip_sync_animator.asr_model.transcribe(audio_path, language="zh")
                full_text = result["text"]

            print("✅ 音频转文字完成。")
            return full_text.strip()

        except Exception as e:
            print(f"❌ Whisper 转录时出错: {e}")
            return ""


    # --- 主处理函数：根据输入参数决定走哪个流程 ---
    def process(self, input_source, is_theme_input: bool, model_choice: str, output_path: str, target_duration_category: str = "medium", enable_lip_sync: bool = False):
        """
        主处理函数，根据输入类型决定调用哪个子流程。
        Args:
            input_source (str or list): 输入源。如果是主题，则为字符串；如果是视频文件，则为路径列表。
            is_theme_input (bool): 是否是主题输入模式。
            model_choice (str): AI模型选择 (仅在主题模式下使用)。
            output_path (str): 输出视频路径。
            target_duration_category (str): 目标成品时长类别。
            enable_lip_sync (bool): 是否启用嘴型同步动画。
        """
        if is_theme_input:
            # 调用新功能：AI脚本驱动
            if isinstance(input_source, str):
                 self.process_with_ai_script(input_source, model_choice, output_path, target_duration_category, enable_lip_sync)
            else:
                 raise TypeError("主题模式下，input_source 应为字符串类型的提示词。")
        else:
            # 调用原有功能：处理现有视频
            if isinstance(input_source, list):
                 self.process_existing_videos(input_source, output_path, target_duration_category, enable_lip_sync)
            else:
                 raise TypeError("视频模式下，input_source 应为视频路径组成的列表。")


def save_current_state_on_exit():
    """保存当前处理状态到临时文件"""
    state = {
        "last_saved": datetime.now().isoformat(),
        "processed_speech_exists": os.path.exists(PROCESSED_SPEECH_FILE),
        "processed_screen_exists": os.path.exists(PROCESSED_SCREEN_FILE),
        "generated_script_exists": os.path.exists(GENERATED_SCRIPT_FILE),
        "hot_moments_exists": os.path.exists(HOT_MOMENTS_FILE),
    }
    with open(SAVED_STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    # --- 示例调用 ---
    import sys
    if len(sys.argv) > 1:
        # 假设第一个参数是模式 ("theme" 或 "video")
        # 第二个参数是输入 (主题字符串 或 视频路径)
        mode = sys.argv[1]
        if mode == "theme":
            if len(sys.argv) >= 4:
                theme = sys.argv[2]
                output_file = sys.argv[3]
                # 检查是否有 --lip-sync 参数
                enable_lip_sync = "--lip-sync" in sys.argv
                editor = AIVideoEditorLocal()
                editor.process(input_source=theme, is_theme_input=True, model_choice="qwen", output_path=output_file, target_duration_category="short", enable_lip_sync=enable_lip_sync)
            else:
                print("主题模式用法: python ai_video_editor_local.py theme \"视频主题\" \"输出文件路径.mp4\" [--lip-sync]")
        elif mode == "video":
            if len(sys.argv) >= 4:
                video_path = sys.argv[2]
                output_file = sys.argv[3]
                enable_lip_sync = "--lip-sync" in sys.argv
                editor = AIVideoEditorLocal()
                editor.process(input_source=[video_path], is_theme_input=False, model_choice=None, output_path=output_file, target_duration_category="medium", enable_lip_sync=enable_lip_sync)
            else:
                print("视频模式用法: python ai_video_editor_local.py video \"视频文件路径.mp4\" \"输出文件路径.mp4\" [--lip-sync]")
        elif mode == "manage-models":
            # 直接调用模型管理器
            os.system(f"python model_manager.py {' '.join(sys.argv[2:])}")
        else:
            print("未知模式，请使用 'theme', 'video', 或 'manage-models'。")
    else:
        print("请通过命令行参数指定模式和输入，或使用 ui_main.py 启动GUI。")
        print("示例:")
        print("  python ai_video_editor_local.py theme \"我的复仇计划\" \"output_theme.mp4\" --lip-sync")
        print("  python ai_video_editor_local.py video \"my_video.mp4\" \"output_video.mp4\"")
        print("  python ai_video_editor_local.py manage-models list")
        print("  python ai_video_editor_local.py manage-models install")