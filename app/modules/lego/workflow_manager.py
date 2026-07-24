"""
全链路工作流管理器
==================
负责打通素材获取 → AI剪辑 → 文案生成 → 账号运营的完整链路
"""

import os
import json
import time
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime

from PyQt6.QtCore import QObject, pyqtSignal, QThread

from .core import EventBus, EventType
from .drama_crawler import DramaCrawler, DramaInfo
from .video_processor import VideoProcessor


@dataclass
class WorkflowContext:
    """工作流上下文 - 贯穿全流程的数据载体"""
    drama_info: Optional['DramaInfo'] = None
    video_path: str = ""
    clips: List = field(default_factory=list)
    creative: Dict = field(default_factory=dict)
    publish_result: Dict = field(default_factory=dict)
    status: str = "idle"
    progress: float = 0.0
    error: Optional[str] = None


class WorkflowManager(QObject):
    """全链路工作流管理器"""
    
    progress_updated = pyqtSignal(float, str)
    step_completed = pyqtSignal(str, dict)
    workflow_completed = pyqtSignal(object)
    workflow_error = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self._event_bus = EventBus.get_instance()
        self._drama_crawler = DramaCrawler()
        self._video_processor = VideoProcessor()
        self._context = WorkflowContext()
        
        self._event_bus.on(EventType.DRAMA_SELECTED, self._on_drama_selected)
        self._event_bus.on(EventType.VIDEO_CLIPPED, self._on_video_clipped)
        self._event_bus.on(EventType.COPY_GENERATED, self._on_copy_generated)
    
    def _on_drama_selected(self, event):
        drama_info = event.data
        if isinstance(drama_info, DramaInfo):
            self._context.drama_info = drama_info
            self.start_workflow(drama_info)
    
    def _on_video_clipped(self, event):
        result = event.data
        if result.get("success"):
            self._context.clips = result.get("clips", [])
            self._context.video_path = result.get("output_path", "")
    
    def _on_copy_generated(self, event):
        self._context.creative = event.data
    
    def start_workflow(self, drama_info: DramaInfo):
        workflow_thread = WorkflowThread(self, drama_info)
        workflow_thread.progress_updated.connect(self.progress_updated)
        workflow_thread.step_completed.connect(self.step_completed)
        workflow_thread.workflow_completed.connect(self._on_workflow_completed)
        workflow_thread.workflow_error.connect(self.workflow_error)
        workflow_thread.start()
    
    def _on_workflow_completed(self, context):
        self._context = context
        self.workflow_completed.emit(context)
        
        self._event_bus.emit(EventType.WORKFLOW_COMPLETED, {
            "context": context,
            "timestamp": datetime.now().isoformat()
        })


class WorkflowThread(QThread):
    """工作流执行线程"""
    
    progress_updated = pyqtSignal(float, str)
    step_completed = pyqtSignal(str, dict)
    workflow_completed = pyqtSignal(object)
    workflow_error = pyqtSignal(str)
    
    def __init__(self, manager: WorkflowManager, drama_info: DramaInfo):
        super().__init__()
        self._manager = manager
        self._drama_info = drama_info
        self._context = WorkflowContext(drama_info=drama_info)
    
    def run(self):
        try:
            self.progress_updated.emit(10, "🎬 正在获取短剧素材...")
            self._step_fetch_drama()
            
            self.progress_updated.emit(30, "✂️ 正在AI智能剪辑...")
            self._step_ai_clip()
            
            self.progress_updated.emit(60, "✍️ 正在生成文案...")
            self._step_copywriting()
            
            self.progress_updated.emit(85, "🚀 正在准备发布...")
            self._step_publish_prepare()
            
            self.progress_updated.emit(100, "🎉 全流程完成！")
            self.workflow_completed.emit(self._context)
            
        except Exception as e:
            self.workflow_error.emit(str(e))
    
    def _step_fetch_drama(self):
        """Step 1: 获取短剧素材 — 通过 DramaCrawler 下载"""
        try:
            # 检查本地是否已有素材
            if self._context.video_path and os.path.exists(self._context.video_path):
                result = {
                    "success": True,
                    "video_path": self._context.video_path,
                    "source": "local_cache",
                    "metadata": {
                        "title": self._drama_info.title,
                        "category": self._drama_info.category,
                        "platform": self._drama_info.platform
                    }
                }
                self._context.video_path = result["video_path"]
                self.step_completed.emit("fetch_drama", result)
                return
            
            # 尝试通过 DramaCrawler 获取
            crawler = self._manager._drama_crawler
            download_result = None
            if hasattr(crawler, 'download_drama'):
                download_result = crawler.download_drama(self._drama_info)
            
            if download_result and download_result.get("video_path"):
                result = {
                    "success": True,
                    "video_path": download_result["video_path"],
                    "source": "crawler",
                    "metadata": {
                        "title": self._drama_info.title,
                        "category": self._drama_info.category,
                        "platform": self._drama_info.platform
                    }
                }
                self._context.video_path = result["video_path"]
            else:
                # 回退：记录素材信息，等待用户手动导入
                result = {
                    "success": True,
                    "video_path": "",
                    "source": "pending_manual",
                    "message": f"素材自动下载暂不可用，请手动导入: {self._drama_info.title}",
                    "metadata": {
                        "title": self._drama_info.title,
                        "source_url": self._drama_info.source_url,
                        "category": self._drama_info.category,
                        "platform": self._drama_info.platform,
                    }
                }
                self._context.video_path = result.get("video_path", "")
            self.step_completed.emit("fetch_drama", result)
        except Exception as e:
            self.step_completed.emit("fetch_drama", {"success": False, "error": str(e)})
    
    def _step_ai_clip(self):
        """Step 2: AI 智能剪辑 — 调用 VideoProcessor.process_auto_clip"""
        try:
            if not self._context.video_path:
                self.step_completed.emit("ai_clip", {
                    "success": False,
                    "error": "无素材路径，请先导入视频"
                })
                return
            
            vp = self._manager._video_processor
            result = vp.process_auto_clip(
                self._context.video_path,
                platform=self._drama_info.platform or "douyin",
                duration=60
            )
            if result.get("success"):
                self._context.clips = result.get("clips", [])
                self.step_completed.emit("ai_clip", result)
            else:
                # 回退：基础视频信息
                info = vp.get_info(self._context.video_path)
                self._context.clips = [{"duration": min(info.duration if info else 60, 60), "quality": "original"}]
                self.step_completed.emit("ai_clip", {
                    "success": True,
                    "clips": self._context.clips,
                    "video_info": {"duration": info.duration if info else 60} if info else {},
                    "note": "AI 高光检测失败，使用原始视频"
                })
        except Exception as e:
            self.step_completed.emit("ai_clip", {"success": False, "error": str(e)})
    
    def _step_copywriting(self):
        """Step 3: AI 文案生成 — 调用 AI 引擎生成标题/描述/标签"""
        try:
            # 尝试使用 AI 引擎生成文案
            ai_content = self._try_ai_copywriting()
            if ai_content:
                self._context.creative = ai_content
                self.step_completed.emit("copywriting", ai_content)
                return
            
            # 回退：基于模板的文案
            fallback = {
                "title": f"🔥 {self._drama_info.title} 精彩片段",
                "description": f"《{self._drama_info.title}》精彩片段，不容错过！",
                "tags": list(self._drama_info.tags[:5]) + ["短剧", "精彩片段"],
                "scripts": ["这是一个精彩的短剧片段..."],
                "source": "template_fallback"
            }
            self._context.creative = fallback
            self.step_completed.emit("copywriting", fallback)
        except Exception as e:
            self.step_completed.emit("copywriting", {"success": False, "error": str(e)})
    
    def _try_ai_copywriting(self) -> Optional[Dict]:
        """尝试通过 AI 引擎生成文案"""
        try:
            from ..core.ai_engine import AIEngine
            ai = AIEngine.get_instance()
            prompt = (
                f"为短剧《{self._drama_info.title}》撰写一条推广文案。"
                f"类别: {self._drama_info.category}。"
                f"要求: 输出 JSON，包含 title(标题, 20字以内)、"
                f"description(描述, 50字以内)、tags(标签数组, 5-8个)。"
            )
            response = ai.chat_with_fallback(prompt, task="copywriting")
            if response:
                # 尝试从 AI 响应中提取 JSON
                import re as _re
                json_match = _re.search(r'\{[\s\S]*\}', response)
                if json_match:
                    parsed = json.loads(json_match.group())
                    parsed["source"] = "ai_generated"
                    parsed["scripts"] = [response]
                    return parsed
        except Exception as e:
            logger.debug(f"AI 文案生成不可用: {e}")
        return None
    
    def _step_publish_prepare(self):
        """Step 4: 发布准备 — 对接 PlatformIntegrator"""
        try:
            # 尝试发布到平台
            video_path = self._context.video_path
            creative = self._context.creative or {}
            
            if not video_path:
                publish_data = {
                    "success": False,
                    "error": "无视频可发布",
                    "platforms": [],
                }
            else:
                try:
                    from app.integrations.platforms import PlatformIntegrator
                    integrator = PlatformIntegrator()
                    platforms = ["douyin", "kuaishou", "bilibili"]
                    
                    publish_results = integrator.publish_to_multiple_platforms(
                        platforms,
                        video_path,
                        creative.get("title", self._drama_info.title),
                        creative.get("description", ""),
                        creative.get("tags", [])
                    )
                    publish_data = {
                        "success": True,
                        "platforms": platforms,
                        "results": publish_results,
                        "video_path": video_path,
                        "creative": creative,
                        "schedule_time": datetime.now().isoformat()
                    }
                except Exception as e:
                    logger.warning(f"PlatformIntegrator 不可用: {e}")
                    publish_data = {
                        "success": True,
                        "platforms": ["douyin", "kuaishou", "xiaohongshu"],
                        "video_path": video_path,
                        "creative": creative,
                        "schedule_time": datetime.now().isoformat(),
                        "note": "已导出视频（需手动发布到各平台）"
                    }
            
            self._context.publish_result = publish_data
            self.step_completed.emit("publish_prepare", publish_data)
        except Exception as e:
            self.step_completed.emit("publish_prepare", {"success": False, "error": str(e)})


_workflow_manager: Optional[WorkflowManager] = None

def get_workflow_manager() -> WorkflowManager:
    global _workflow_manager
    if _workflow_manager is None:
        _workflow_manager = WorkflowManager()
    return _workflow_manager