"""
全链路工作流管理器
==================
负责打通素材获取 → AI剪辑 → 文案生成 → 账号运营的完整链路
"""

import os
import json
import time
import logging
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime

from PyQt6.QtCore import QObject, pyqtSignal, QThread

from .core import EventBus, EventType
from .drama_crawler import DramaCrawler, DramaInfo
from .video_processor import VideoProcessor

logger = logging.getLogger(__name__)


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
        # 修复：event.data 不保证一定是 dict（其它模块也可能发这个事件类型但
        # 携带别的数据形状），直接 .get() 会 AttributeError 崩溃
        result = event.data
        if isinstance(result, dict) and result.get("success"):
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
        # 修复：此前四个步骤全部跑完（无论各步骤实际 success 与否）就无条件
        # emit 100% + "全流程完成"，即使素材没下载到、AI剪辑失败、发布也失败，
        # 用户依然会看到一个"完成"的绿色提示。这里收集每一步的真实结果，
        # 结尾按实际情况给出诚实的完成/部分完成/失败摘要。
        try:
            self.progress_updated.emit(10, "🎬 正在获取短剧素材...")
            fetch_result = self._step_fetch_drama()

            self.progress_updated.emit(30, "✂️ 正在AI智能剪辑...")
            clip_result = self._step_ai_clip()

            self.progress_updated.emit(60, "✍️ 正在生成文案...")
            copy_result = self._step_copywriting()

            self.progress_updated.emit(85, "🚀 正在准备发布...")
            publish_result = self._step_publish_prepare()

            step_results = {
                "fetch_drama": fetch_result,
                "ai_clip": clip_result,
                "copywriting": copy_result,
                "publish_prepare": publish_result,
            }
            failed_steps = [
                name for name, r in step_results.items()
                if not (isinstance(r, dict) and r.get("success"))
            ]
            self._context.status = "completed" if not failed_steps else "partial"
            self._context.error = None if not failed_steps else f"以下步骤未完全成功: {', '.join(failed_steps)}"

            if not failed_steps:
                self.progress_updated.emit(100, "🎉 全流程完成！")
            else:
                self.progress_updated.emit(100, f"⚠️ 流程结束，但以下步骤未成功: {', '.join(failed_steps)}")
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
                return result
            
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
                # 未能自动获取素材：如实报告未完成，等待用户手动导入
                result = {
                    "success": False,
                    "video_path": "",
                    "source": "pending_manual",
                    "error": f"素材自动下载暂不可用，请手动导入: {self._drama_info.title}",
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
            return result
        except Exception as e:
            result = {"success": False, "error": str(e)}
            self.step_completed.emit("fetch_drama", result)
            return result
    
    def _step_ai_clip(self):
        """Step 2: AI 智能剪辑 — 调用 VideoProcessor.process_auto_clip"""
        try:
            if not self._context.video_path:
                result = {"success": False, "error": "无素材路径，请先导入视频"}
                self.step_completed.emit("ai_clip", result)
                return result
            
            vp = self._manager._video_processor
            result = vp.process_auto_clip(
                self._context.video_path,
                platform=self._drama_info.platform or "douyin",
                duration=60
            )
            if result.get("success"):
                self._context.clips = result.get("clips", [])
                self.step_completed.emit("ai_clip", result)
                return result
            else:
                # 回退：使用原始视频（如实标注为回退，而不是真的 AI 剪辑结果）
                info = vp.get_info(self._context.video_path)
                self._context.clips = [{"duration": min(info.duration if info else 60, 60), "quality": "original"}]
                fallback_result = {
                    "success": True,
                    "clips": self._context.clips,
                    "video_info": {"duration": info.duration if info else 60} if info else {},
                    "note": "AI 高光检测失败，使用原始视频（非真实AI剪辑结果）",
                    "is_fallback": True,
                }
                self.step_completed.emit("ai_clip", fallback_result)
                return fallback_result
        except Exception as e:
            result = {"success": False, "error": str(e)}
            self.step_completed.emit("ai_clip", result)
            return result
    
    def _step_copywriting(self):
        """Step 3: AI 文案生成 — 调用 AI 引擎生成标题/描述/标签"""
        try:
            # 尝试使用 AI 引擎生成文案
            ai_content = self._try_ai_copywriting()
            if ai_content:
                ai_content.setdefault("success", True)
                self._context.creative = ai_content
                self.step_completed.emit("copywriting", ai_content)
                return ai_content
            
            # 回退：基于模板的文案
            # 修复：此前这个 dict 没有 "success" 字段，调用方无法判断该步骤
            # 是否完成——现补上，并如实标注是模板回退而非 AI 生成
            fallback = {
                "success": True,
                "title": f"🔥 {self._drama_info.title} 精彩片段",
                "description": f"《{self._drama_info.title}》精彩片段，不容错过！",
                "tags": list(self._drama_info.tags[:5]) + ["短剧", "精彩片段"],
                "scripts": ["这是一个精彩的短剧片段..."],
                "source": "template_fallback",
                "note": "AI 文案生成不可用，使用模板占位文案",
            }
            self._context.creative = fallback
            self.step_completed.emit("copywriting", fallback)
            return fallback
        except Exception as e:
            result = {"success": False, "error": str(e)}
            self.step_completed.emit("copywriting", result)
            return result
    
    def _try_ai_copywriting(self) -> Optional[Dict]:
        """尝试通过 AI 引擎生成文案"""
        try:
            # 修复：从 app/modules/lego/workflow_manager.py 数相对导入层级，
            # `..core` 实际指向不存在的 app.modules.core，AI 文案生成因此
            # 每次都必然 ImportError，被下方 except 静默吞掉、悄悄退化成模板
            # 文案——用户以为在用 AI 生成，实际上从来没有调用过 AI。
            from app.core.ai_engine import AIEngine
            ai = AIEngine.get_instance()
            prompt = (
                f"为短剧《{self._drama_info.title}》撰写一条推广文案。"
                f"类别: {self._drama_info.category}。"
                f"要求: 输出 JSON，包含 title(标题, 20字以内)、"
                f"description(描述, 50字以内)、tags(标签数组, 5-8个)。"
            )
            # chat_with_fallback 是生成器，需完整拼接后再解析
            response = "".join(ai.chat_with_fallback(
                messages=[{"role": "user", "content": prompt}],
            ))
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
                    # 修复：此前不管 publish_results（各平台 bool 结果）实际内容，
                    # 只要 publish_to_multiple_platforms 没抛异常就一律 success=True
                    # ——哪怕全部平台都发布失败也会报"发布准备完成"。这里按真实
                    # 每平台结果统计成功/失败数，success 只在至少一个平台成功时为真。
                    succeeded = [p for p, ok in (publish_results or {}).items() if ok]
                    failed = [p for p, ok in (publish_results or {}).items() if not ok]
                    publish_data = {
                        "success": bool(succeeded),
                        "platforms": platforms,
                        "succeeded_platforms": succeeded,
                        "failed_platforms": failed,
                        "results": publish_results,
                        "video_path": video_path,
                        "creative": creative,
                        "schedule_time": datetime.now().isoformat(),
                    }
                    if failed and not succeeded:
                        publish_data["error"] = f"全部平台发布失败: {', '.join(failed)}"
                    elif failed:
                        publish_data["note"] = f"部分平台发布失败: {', '.join(failed)}"
                except Exception as e:
                    logger.warning(f"PlatformIntegrator 不可用，未实际发布: {e}")
                    # 如实报告：未发布到任何平台，只是本地视频已就绪
                    publish_data = {
                        "success": False,
                        "platforms": [],
                        "video_path": video_path,
                        "creative": creative,
                        "schedule_time": datetime.now().isoformat(),
                        "error": f"自动发布不可用（{e}），视频已导出，需手动发布到各平台",
                        "note": "已导出视频（需手动发布到各平台）",
                    }
            
            self._context.publish_result = publish_data
            self.step_completed.emit("publish_prepare", publish_data)
            return publish_data
        except Exception as e:
            result = {"success": False, "error": str(e)}
            self.step_completed.emit("publish_prepare", result)
            return result


_workflow_manager: Optional[WorkflowManager] = None

def get_workflow_manager() -> WorkflowManager:
    global _workflow_manager
    if _workflow_manager is None:
        _workflow_manager = WorkflowManager()
    return _workflow_manager