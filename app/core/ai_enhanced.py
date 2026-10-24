"""
增强AI工具模块 (AIEnhanced)
==========================
集成本地和云端AI模型，提供个性化推荐和智能内容生成
"""

import json
import os
import time
from typing import Optional, Dict, List, Any, Generator
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


def try_import_cv2():
    """尝试导入cv2"""
    try:
        import cv2
        return cv2
    except ImportError:
        return None


def try_import_numpy():
    """尝试导入numpy"""
    try:
        import numpy as np
        return np
    except ImportError:
        return None


@dataclass
class AIGeneratedContent:
    """AI生成的内容"""
    type: str
    content: Any
    model: str
    confidence: float
    generation_time: float


class AIEnhanced:
    """增强AI工具"""
    
    _instance: Optional['AIEnhanced'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        # 尝试导入依赖
        self.cv2 = try_import_cv2()
        self.np = try_import_numpy()
        
        # 尝试导入云服务和本地模型
        self.cloud_api = None
        self.ollama_client = None
        
        try:
            from modules.lego.cloud_api import cloud_api_service
            self.cloud_api = cloud_api_service
        except ImportError:
            logger.warning("云服务API未找到")
        
        try:
            from modules.lego.ollama_client import ollama_client
            self.ollama_client = ollama_client
        except ImportError:
            logger.warning("Ollama客户端未找到")
        
        # 缓存
        self._cache: Dict[str, tuple] = {}
        self._cache_duration = 300  # 5分钟
        
        # 本地模型配置
        self._local_models = {
            "text": "llama3:8b",
            "image": None,
            "video": None
        }
        
        # 云端模型配置
        self._cloud_models = {
            "text": "deepseek",
            "image": None,
            "video": None
        }
    
    def _get_cache(self, key: str) -> Optional[Any]:
        """获取缓存"""
        if key in self._cache:
            value, timestamp = self._cache[key]
            if time.time() - timestamp < self._cache_duration:
                return value
            del self._cache[key]
        return None
    
    def _set_cache(self, key: str, value: Any):
        """设置缓存"""
        self._cache[key] = (value, time.time())
    
    def generate_content(
        self,
        content_type: str,
        prompt: str,
        use_local: bool = True,
        **kwargs
    ) -> Generator[str, None, None]:
        """生成内容"""
        cache_key = f"generate_{content_type}_{prompt[:100]}"
        cached = self._get_cache(cache_key)
        if cached:
            yield cached
            return
        
        if use_local and self.ollama_client and self.ollama_client.is_available():
            # 使用本地模型
            model = self._local_models.get(content_type, self._local_models["text"])
            if model:
                messages = [
                    {"role": "system", "content": "你是一个专业的视频内容创作者，擅长生成短视频相关的内容。"},
                    {"role": "user", "content": prompt}
                ]
                
                try:
                    result = ""
                    for chunk in self.ollama_client.chat(model, messages, stream=True, **kwargs):
                        result += chunk
                        yield chunk
                    self._set_cache(cache_key, result)
                    return
                except Exception as e:
                    logger.error(f"本地模型生成失败: {e}")
                    #  fallback到云端
        
        # 使用云端模型
        if self.cloud_api:
            provider = self._cloud_models.get(content_type, self._cloud_models["text"])
            if provider and self.cloud_api.is_configured(provider):
                messages = [
                    {"role": "system", "content": "你是一个专业的视频内容创作者，擅长生成短视频相关的内容。"},
                    {"role": "user", "content": prompt}
                ]
                
                try:
                    result = ""
                    for chunk in self.cloud_api.chat(provider, messages, stream=True, **kwargs):
                        result += chunk
                        yield chunk
                    self._set_cache(cache_key, result)
                    return
                except Exception as e:
                    logger.error(f"云端模型生成失败: {e}")
        
        yield "错误: 无法生成内容，请检查AI模型配置"
    
    def generate_video_idea(self, topic: str, platform: str = "douyin") -> Generator[str, None, None]:
        """生成视频创意"""
        prompt = f"为{platform}平台生成一个关于'{topic}'的短视频创意，包括：\n"
        prompt += "1. 视频标题\n"
        prompt += "2. 视频简介\n"
        prompt += "3. 视频结构（分镜头描述）\n"
        prompt += "4. 适合的背景音乐风格\n"
        prompt += "5. 推荐的标签和话题"
        
        yield from self.generate_content("text", prompt)
    
    def generate_subtitle(self, video_path: str) -> Generator[str, None, None]:
        """生成字幕"""
        if not self.cv2 or not self.np:
            yield "错误: 缺少视频处理模块"
            return
        
        try:
            # 这里简化处理，实际应该使用语音识别
            prompt = f"为视频生成字幕，视频内容是关于..."
            yield from self.generate_content("text", prompt)
        except Exception as e:
            logger.error(f"生成字幕失败: {e}")
            yield f"错误: {str(e)}"
    
    def generate_hashtags(self, content: str, platform: str = "douyin", count: int = 10) -> Generator[str, None, None]:
        """生成标签"""
        prompt = f"为以下内容生成{count}个适合{platform}平台的热门标签，用逗号分隔：\n{content}"
        yield from self.generate_content("text", prompt)
    
    def recommend_music(self, video_style: str, duration: int) -> Generator[str, None, None]:
        """推荐音乐"""
        prompt = f"推荐5首适合{video_style}风格、时长约{duration}秒的背景音乐，包括：\n"
        prompt += "1. 歌曲名称\n"
        prompt += "2. 歌手\n"
        prompt += "3. 风格描述\n"
        prompt += "4. 适合的视频场景"
        
        yield from self.generate_content("text", prompt)
    
    def analyze_video(self, video_path: str) -> Dict[str, Any]:
        """分析视频"""
        if not self.cv2 or not self.np:
            return {"error": "缺少视频处理模块"}
        
        try:
            cap = self.cv2.VideoCapture(video_path)
            if not cap.isOpened():
                return {"error": "无法打开视频文件"}
            
            fps = cap.get(self.cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(self.cv2.CAP_PROP_FRAME_COUNT))
            duration = total_frames / fps
            width = int(cap.get(self.cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(self.cv2.CAP_PROP_FRAME_HEIGHT))
            
            # 分析视频内容
            frames = []
            for i in range(0, total_frames, int(fps)):
                cap.set(self.cv2.CAP_PROP_POS_FRAMES, i)
                ret, frame = cap.read()
                if ret:
                    frames.append(frame)
            
            cap.release()
            
            # 简单的内容分析
            analysis = {
                "duration": duration,
                "resolution": f"{width}x{height}",
                "fps": fps,
                "frame_count": total_frames,
                "aspect_ratio": f"{width}:{height}"
            }
            
            return analysis
            
        except Exception as e:
            logger.error(f"分析视频失败: {e}")
            return {"error": str(e)}
    
    def personalize_recommendations(self, user_preferences: Dict[str, Any]) -> List[Dict[str, Any]]:
        """个性化推荐"""
        # 基于用户偏好生成推荐
        preferences_str = json.dumps(user_preferences, ensure_ascii=False)
        prompt = f"基于以下用户偏好，推荐5个短视频创作方向：\n{preferences_str}"
        
        # 生成推荐
        recommendations = []
        try:
            result = ""
            for chunk in self.generate_content("text", prompt):
                result += chunk
            
            # 解析结果
            lines = result.split('\n')
            for i, line in enumerate(lines):
                if line.strip() and not line.startswith('错误:'):
                    recommendations.append({
                        "id": i + 1,
                        "title": line.strip(),
                        "score": 1.0 - (i * 0.1)  # 简单的评分
                    })
        except Exception as e:
            logger.error(f"生成推荐失败: {e}")
        
        return recommendations
    
    def get_ai_capabilities(self) -> Dict[str, Any]:
        """获取AI能力"""
        capabilities = {
            "local_models": {
                "available": self.ollama_client is not None and self.ollama_client.is_available(),
                "models": []
            },
            "cloud_models": {
                "available": self.cloud_api is not None,
                "providers": []
            }
        }
        
        # 检查本地模型
        if self.ollama_client and self.ollama_client.is_available():
            models = self.ollama_client.list_models()
            capabilities["local_models"]["models"] = [m.name for m in models]
        
        # 检查云端模型
        if self.cloud_api:
            providers = self.cloud_api.list_providers()
            capabilities["cloud_models"]["providers"] = [p for p in providers if p != "ollama"]
        
        return capabilities
    
    def set_model_preference(self, content_type: str, local_model: str, cloud_provider: str):
        """设置模型偏好"""
        if content_type in self._local_models:
            self._local_models[content_type] = local_model
        if content_type in self._cloud_models:
            self._cloud_models[content_type] = cloud_provider


ai_enhanced = AIEnhanced()
