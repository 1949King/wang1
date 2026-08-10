"""
数据回流分析器
==============
分析发布数据，优化创作策略
"""

import os
import json
import logging
from typing import Dict, List, Any
from datetime import datetime, timedelta
from collections import defaultdict

from .core import EventBus, EventType

logger = logging.getLogger(__name__)


class DataAnalyzer:
    """数据回流分析器"""
    
    def __init__(self):
        self._event_bus = EventBus.get_instance()
        self._event_bus.on(EventType.WORKFLOW_COMPLETED, self._on_workflow_completed)
        self._event_bus.on(EventType.PUBLISH_RESULT, self._on_publish_result)
        
        self._publish_records = []
        self._analysis_cache = {}
    
    def _on_workflow_completed(self, event):
        # 修复：event.data 不保证一定是 dict，直接 .get() 在其它类型上会
        # AttributeError 崩溃（EventBus 是全局总线，同一事件类型理论上
        # 可能被不同调用方以不同数据形状触发）
        data = event.data
        context = data.get("context") if isinstance(data, dict) else None
        if context:
            self._record_workflow(context)
    
    def _on_publish_result(self, event):
        result = event.data
        if not isinstance(result, dict):
            logger.debug(f"[DataAnalyzer] 忽略非 dict 的 PUBLISH_RESULT 事件数据: {type(result)}")
            return
        self._publish_records.append(result)
        self._update_strategy(result)
    
    def _record_workflow(self, context):
        record = {
            "timestamp": datetime.now().isoformat(),
            "drama_title": context.drama_info.title if context.drama_info else "",
            "platform": context.drama_info.platform if context.drama_info else "",
            "category": context.drama_info.category if context.drama_info else "",
            "video_path": context.video_path,
            "clip_count": len(context.clips),
            "creative": context.creative,
            "publish_result": context.publish_result
        }
        self._save_record(record)
    
    def _save_record(self, record):
        records_dir = "analytics"
        os.makedirs(records_dir, exist_ok=True)
        filename = f"{datetime.now().strftime('%Y%m%d')}_workflows.json"
        filepath = os.path.join(records_dir, filename)
        
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = []
        
        data.append(record)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def _update_strategy(self, publish_result):
        platform = publish_result.get("platform")
        success = publish_result.get("success", False)
        views = publish_result.get("views", 0)

        self._adjust_clip_strategy(platform, success, views)
        self._adjust_copy_strategy(platform, publish_result)

        # 回流到 Agent 长期记忆（新增，不破坏既有 strategies/ 文件写入）
        try:
            from app.core.agent_feedback_bridge import agent_feedback_bridge
            strategy = self._load_strategy(platform)
            agent_feedback_bridge.submit_feedback({
                "platform": platform,
                "success": success,
                "views": views,
                "low_metric": "views" if views < 5000 else "",
                "strategy_adjusted": strategy,
                "source": "data_analyzer",
            })
        except Exception as e:
            logger.debug(f"[DataAnalyzer] 反馈提交失败: {e}")
    
    def _adjust_clip_strategy(self, platform, success, views):
        strategy = self._load_strategy(platform)
        
        if success and views > 10000:
            strategy["highlight_ratio"] = min(0.8, strategy.get("highlight_ratio", 0.7) + 0.05)
        elif not success:
            strategy["highlight_ratio"] = max(0.5, strategy.get("highlight_ratio", 0.7) - 0.05)
        
        self._save_strategy(platform, strategy)
    
    def _adjust_copy_strategy(self, platform, result):
        # 如实说明：文案策略回流调整尚未实现（例如根据播放量调整标题长度/
        # 标签偏好），目前是空实现——调用方（_update_strategy）不依赖其
        # 返回值，不会造成假成功，但也不会有任何真实效果。留空 TODO 供后续
        # 实现，暂不在这轮里编造一个假的调整逻辑。
        pass
    
    def _load_strategy(self, platform):
        strategy_file = f"strategies/{platform}.json"
        if os.path.exists(strategy_file):
            with open(strategy_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"highlight_ratio": 0.7, "duration": 60}
    
    def _save_strategy(self, platform, strategy):
        os.makedirs("strategies", exist_ok=True)
        with open(f"strategies/{platform}.json", 'w', encoding='utf-8') as f:
            json.dump(strategy, f, ensure_ascii=False, indent=2)
    
    def get_recommendations(self, platform: str) -> Dict:
        strategy = self._load_strategy(platform)
        
        recent_records = self._get_recent_records(platform, days=7)
        
        if recent_records:
            avg_views = sum(r.get("views", 0) for r in recent_records) / len(recent_records)
            strategy["avg_views"] = avg_views
            
            if avg_views < 5000:
                strategy["recommendation"] = "建议增加高光比例，缩短视频时长"
            elif avg_views > 50000:
                strategy["recommendation"] = "当前策略效果良好，保持不变"
        
        return strategy
    
    def _get_recent_records(self, platform, days=7):
        """筛选最近 N 天的发布记录

        修复：此前 `r.get("timestamp", "")[:-1]` 对空字符串/正常
        `datetime.now().isoformat()` 格式（不带尾部 'Z'）做无条件切片，
        空字符串会让 `datetime.fromisoformat("")` 直接抛 ValueError 崩溃，
        非空字符串也会被错误地砍掉最后一位。改为不做多余切片，并对单条
        记录的解析失败做隔离（跳过而不是整体崩溃）。
        """
        cutoff = (datetime.now() - timedelta(days=days)).timestamp()
        recent = []
        for r in self._publish_records:
            ts = r.get("timestamp", "") if isinstance(r, dict) else ""
            if not ts:
                continue
            try:
                if datetime.fromisoformat(ts).timestamp() > cutoff:
                    recent.append(r)
            except ValueError:
                logger.debug(f"[DataAnalyzer] 无法解析记录时间戳，已跳过: {ts!r}")
        return recent


_data_analyzer = None

def get_data_analyzer():
    global _data_analyzer
    if _data_analyzer is None:
        _data_analyzer = DataAnalyzer()
    return _data_analyzer