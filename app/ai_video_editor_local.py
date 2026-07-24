import os
import subprocess
import logging
import json
import random
import re
import requests
from pathlib import Path
from typing import List, Dict, Optional, Any
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
            import numpy as np  # type: ignore[reportUnusedImport]
            import cv2  # type: ignore[reportUnusedImport]
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
            import torch  # type: ignore[reportUnusedImport]
            return True
        except ImportError:
            return False

    def _is_faster_whisper_available(self):
        try:
            import faster_whisper  # type: ignore[reportUnusedImport]
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
    def search_and_download_clips_for_script(self, script_list: List[Dict[str, Any]], max_duration_per_clip=10):
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

    def download_video_from_url(self, url: str) -> Optional[str]:
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
            ASR_ENGINE = getattr(self, '_asr_engine', "faster_whisper")
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
                editor.process(input_source=[video_path], is_theme_input=False, model_choice=None, output_path=output_file, target_duration_category="medium", enable_lip_sync=enable_lip_sync)  # type: ignore[reportArgumentType]
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