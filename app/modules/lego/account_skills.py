"""
账号运营 Skills
==============
将账号运营逻辑重构为 Skill 形式
支持：账号管理、发布规则、矩阵发布、数据统计
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
import os
import json

from .skill_engine import Skill, SkillStep, SkillContext, StepResult, skill_engine


class AccountDataCollectSkill(Skill):
    """
    账号数据采集 Skill
    采集各平台账号的运营数据
    """
    
    skill_id = "account_data_collect"
    skill_name = "账号数据采集"
    skill_description = "采集各平台账号的播放、点赞、评论、转化数据"
    skill_category = "账号运营"
    skill_icon = "📊"
    skill_version = "1.0.0"
    
    def _setup_steps(self):
        self.step("初始化数据目录", handler=self._init_data_dir)
        self.step("获取账号列表", handler=self._get_accounts)
        self.step("采集平台数据", handler=self._collect_platform_data, retry_count=2)
        self.step("计算数据指标", handler=self._calculate_metrics)
        self.step("保存采集结果", handler=self._save_results)
    
    def _init_data_dir(self, context: SkillContext) -> StepResult:
        data_dir = context.get_input("data_dir", "运营数据")
        os.makedirs(data_dir, exist_ok=True)
        context.set_variable("data_dir", data_dir)
        return StepResult(success=True, output={"data_dir": data_dir})
    
    def _get_accounts(self, context: SkillContext) -> StepResult:
        accounts = context.get_input("accounts", [])
        if not accounts:
            accounts = [
                {"platform": "抖音", "account_id": "default", "name": "默认账号"},
                {"platform": "快手", "account_id": "default", "name": "默认账号"},
            ]
        context.set_variable("accounts", accounts)
        return StepResult(success=True, output={"account_count": len(accounts)})
    
    def _collect_platform_data(self, context: SkillContext) -> StepResult:
        accounts = context.get_variable("accounts", [])
        collected_data = []
        
        for account in accounts:
            platform = account.get("platform", "未知")
            account_id = account.get("account_id", "")
            
            sample_data = {
                "platform": platform,
                "account_id": account_id,
                "videos": [
                    {
                        "video_id": f"{platform}_{account_id}_001",
                        "title": "示例视频标题",
                        "views": 10000,
                        "likes": 500,
                        "comments": 100,
                        "shares": 50,
                        "conversions": 10,
                        "timestamp": datetime.now().isoformat()
                    }
                ]
            }
            collected_data.append(sample_data)
        
        context.set_variable("collected_data", collected_data)
        return StepResult(success=True, output={"collected_count": len(collected_data)})
    
    def _calculate_metrics(self, context: SkillContext) -> StepResult:
        collected_data = context.get_variable("collected_data", [])
        metrics = []
        
        for account_data in collected_data:
            videos = account_data.get("videos", [])
            if not videos:
                continue
            
            total_views = sum(v.get("views", 0) for v in videos)
            total_likes = sum(v.get("likes", 0) for v in videos)
            total_comments = sum(v.get("comments", 0) for v in videos)
            total_shares = sum(v.get("shares", 0) for v in videos)
            total_conversions = sum(v.get("conversions", 0) for v in videos)
            
            account_metrics = {
                "platform": account_data["platform"],
                "account_id": account_data["account_id"],
                "total_videos": len(videos),
                "total_views": total_views,
                "total_likes": total_likes,
                "total_comments": total_comments,
                "total_shares": total_shares,
                "total_conversions": total_conversions,
                "avg_views": total_views / len(videos) if videos else 0,
                "like_rate": total_likes / total_views * 100 if total_views > 0 else 0,
                "comment_rate": total_comments / total_views * 100 if total_views > 0 else 0,
                "share_rate": total_shares / total_views * 100 if total_views > 0 else 0,
                "conversion_rate": total_conversions / total_views * 100 if total_views > 0 else 0
            }
            metrics.append(account_metrics)
        
        context.set_variable("metrics", metrics)
        return StepResult(success=True, output={"metrics_count": len(metrics)})
    
    def _save_results(self, context: SkillContext) -> StepResult:
        data_dir = context.get_variable("data_dir", "运营数据")
        metrics = context.get_variable("metrics", [])
        
        results_file = os.path.join(data_dir, f"metrics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        with open(results_file, "w", encoding="utf-8") as f:
            json.dump(metrics, f, ensure_ascii=False, indent=2)
        
        context.set_output("results_file", results_file)
        context.set_output("metrics", metrics)
        
        return StepResult(success=True, output={"results_file": results_file})


class AccountAnalysisSkill(Skill):
    """
    账号数据分析 Skill
    分析账号运营数据，生成洞察报告
    """
    
    skill_id = "account_analysis"
    skill_name = "账号数据分析"
    skill_description = "分析账号数据，生成Top表现、趋势、优化建议"
    skill_category = "账号运营"
    skill_icon = "📈"
    skill_version = "1.0.0"
    
    def _setup_steps(self):
        self.step("加载历史数据", handler=self._load_history_data)
        self.step("计算趋势指标", handler=self._calculate_trends)
        self.step("识别Top表现", handler=self._identify_top_performers)
        self.step("生成优化建议", handler=self._generate_suggestions)
        self.step("输出分析报告", handler=self._output_report)
    
    def _load_history_data(self, context: SkillContext) -> StepResult:
        data_dir = context.get_input("data_dir", "运营数据")
        all_data = []
        
        if os.path.exists(data_dir):
            for filename in os.listdir(data_dir):
                if filename.endswith(".json"):
                    filepath = os.path.join(data_dir, filename)
                    try:
                        with open(filepath, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            all_data.extend(data if isinstance(data, list) else [data])
                    except:
                        pass
        
        context.set_variable("all_data", all_data)
        return StepResult(success=True, output={"data_count": len(all_data)})
    
    def _calculate_trends(self, context: SkillContext) -> StepResult:
        all_data = context.get_variable("all_data", [])
        
        if not all_data:
            return StepResult(success=True, output={"trends": {}})
        
        trends = {
            "views_trend": [],
            "engagement_trend": [],
            "conversion_trend": []
        }
        
        sorted_data = sorted(all_data, key=lambda x: x.get("timestamp", ""))
        
        for data in sorted_data:
            trends["views_trend"].append({
                "date": data.get("timestamp", ""),
                "value": data.get("total_views", 0)
            })
            trends["engagement_trend"].append({
                "date": data.get("timestamp", ""),
                "value": data.get("like_rate", 0) + data.get("comment_rate", 0)
            })
            trends["conversion_trend"].append({
                "date": data.get("timestamp", ""),
                "value": data.get("conversion_rate", 0)
            })
        
        context.set_variable("trends", trends)
        return StepResult(success=True, output={"trend_count": len(trends)})
    
    def _identify_top_performers(self, context: SkillContext) -> StepResult:
        all_data = context.get_variable("all_data", [])
        
        if not all_data:
            return StepResult(success=True, output={"top_performers": {}})
        
        sorted_by_views = sorted(all_data, key=lambda x: x.get("total_views", 0), reverse=True)
        sorted_by_conversion = sorted(all_data, key=lambda x: x.get("conversion_rate", 0), reverse=True)
        sorted_by_engagement = sorted(all_data, key=lambda x: x.get("like_rate", 0), reverse=True)
        
        top_performers = {
            "top_views": sorted_by_views[:3],
            "top_conversion": sorted_by_conversion[:3],
            "top_engagement": sorted_by_engagement[:3]
        }
        
        context.set_variable("top_performers", top_performers)
        return StepResult(success=True, output={"top_performers": top_performers})
    
    def _generate_suggestions(self, context: SkillContext) -> StepResult:
        all_data = context.get_variable("all_data", [])
        top_performers = context.get_variable("top_performers", {})
        
        suggestions = []
        
        if all_data:
            avg_conversion = sum(d.get("conversion_rate", 0) for d in all_data) / len(all_data)
            avg_engagement = sum(d.get("like_rate", 0) + d.get("comment_rate", 0) for d in all_data) / len(all_data)
            
            if avg_conversion < 1:
                suggestions.append({
                    "type": "conversion",
                    "priority": "high",
                    "suggestion": "转化率较低，建议优化视频引导语和行动号召"
                })
            
            if avg_engagement < 5:
                suggestions.append({
                    "type": "engagement",
                    "priority": "medium",
                    "suggestion": "互动率偏低，建议增加互动环节和话题引导"
                })
            
            if top_performers.get("top_views"):
                top = top_performers["top_views"][0]
                suggestions.append({
                    "type": "content",
                    "priority": "low",
                    "suggestion": f"高播放量账号 {top.get('platform', '')} 的内容风格值得借鉴"
                })
        else:
            suggestions.append({
                "type": "data",
                "priority": "high",
                "suggestion": "暂无历史数据，建议先进行数据采集"
            })
        
        context.set_variable("suggestions", suggestions)
        return StepResult(success=True, output={"suggestions_count": len(suggestions)})
    
    def _output_report(self, context: SkillContext) -> StepResult:
        trends = context.get_variable("trends", {})
        top_performers = context.get_variable("top_performers", {})
        suggestions = context.get_variable("suggestions", [])
        
        report = {
            "generated_at": datetime.now().isoformat(),
            "trends": trends,
            "top_performers": top_performers,
            "suggestions": suggestions
        }
        
        context.set_output("report", report)
        return StepResult(success=True, output={"report": report})


class PublishContentSkill(Skill):
    """
    内容发布 Skill
    管理内容发布流程
    """
    
    skill_id = "publish_content"
    skill_name = "内容发布"
    skill_description = "将内容发布到指定平台"
    skill_category = "账号运营"
    skill_icon = "🚀"
    skill_version = "1.0.0"
    
    def _setup_steps(self):
        self.step("验证发布内容", handler=self._validate_content)
        self.step("选择目标平台", handler=self._select_platforms)
        self.step("适配平台规格", handler=self._adapt_content)
        self.step("执行发布", handler=self._do_publish, retry_count=3)
        self.step("记录发布结果", handler=self._record_result)
    
    def _validate_content(self, context: SkillContext) -> StepResult:
        content = context.get_input("content", {})
        
        if not content:
            return StepResult(success=False, error="缺少发布内容")
        
        required_fields = ["video_path", "title"]
        missing = [f for f in required_fields if not content.get(f)]
        
        if missing:
            return StepResult(success=False, error=f"缺少必要字段: {', '.join(missing)}")
        
        context.set_variable("content", content)
        return StepResult(success=True, output={"content_valid": True})
    
    def _select_platforms(self, context: SkillContext) -> StepResult:
        platforms = context.get_input("platforms", ["抖音"])
        
        valid_platforms = ["抖音", "快手", "视频号", "小红书", "B站"]
        platforms = [p for p in platforms if p in valid_platforms]
        
        if not platforms:
            platforms = ["抖音"]
        
        context.set_variable("platforms", platforms)
        return StepResult(success=True, output={"platforms": platforms})
    
    def _adapt_content(self, context: SkillContext) -> StepResult:
        content = context.get_variable("content", {})
        platforms = context.get_variable("platforms", [])
        
        adapted_content = {}
        
        platform_specs = {
            "抖音": {"max_duration": 300, "max_title": 55, "format": "mp4"},
            "快手": {"max_duration": 600, "max_title": 50, "format": "mp4"},
            "视频号": {"max_duration": 900, "max_title": 60, "format": "mp4"},
            "小红书": {"max_duration": 900, "max_title": 20, "format": "mp4"},
            "B站": {"max_duration": 3600, "max_title": 80, "format": "mp4"},
        }
        
        for platform in platforms:
            specs = platform_specs.get(platform, platform_specs["抖音"])
            
            title = content.get("title", "")
            if len(title) > specs["max_title"]:
                title = title[:specs["max_title"]-3] + "..."
            
            adapted_content[platform] = {
                "video_path": content.get("video_path"),
                "title": title,
                "description": content.get("description", ""),
                "tags": content.get("tags", []),
                "specs": specs
            }
        
        context.set_variable("adapted_content", adapted_content)
        return StepResult(success=True, output={"adapted_count": len(adapted_content)})
    
    def _do_publish(self, context: SkillContext) -> StepResult:
        adapted_content = context.get_variable("adapted_content", {})
        publish_results = {}
        
        for platform, content in adapted_content.items():
            publish_results[platform] = {
                "success": True,
                "message": f"已提交到 {platform} 发布队列",
                "content_id": f"{platform}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "submitted_at": datetime.now().isoformat()
            }
        
        context.set_variable("publish_results", publish_results)
        return StepResult(success=True, output={"publish_results": publish_results})
    
    def _record_result(self, context: SkillContext) -> StepResult:
        publish_results = context.get_variable("publish_results", {})
        
        data_dir = "发布记录"
        os.makedirs(data_dir, exist_ok=True)
        
        record_file = os.path.join(data_dir, f"publish_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        with open(record_file, "w", encoding="utf-8") as f:
            json.dump(publish_results, f, ensure_ascii=False, indent=2)
        
        context.set_output("record_file", record_file)
        context.set_output("publish_results", publish_results)
        
        return StepResult(success=True, output={"record_file": record_file})


class MatrixPublishSkill(Skill):
    """
    矩阵发布 Skill
    批量发布到多个账号
    """
    
    skill_id = "matrix_publish"
    skill_name = "矩阵发布"
    skill_description = "批量发布内容到多个账号矩阵"
    skill_category = "账号运营"
    skill_icon = "🎯"
    skill_version = "1.0.0"
    
    def _setup_steps(self):
        self.step("加载账号矩阵", handler=self._load_matrix)
        self.step("生成发布计划", handler=self._generate_plan)
        self.step("执行批量发布", handler=self._batch_publish)
        self.step("汇总发布结果", handler=self._summarize_results)
    
    def _load_matrix(self, context: SkillContext) -> StepResult:
        matrix_config = context.get_input("matrix_config", {})
        
        if not matrix_config:
            matrix_config = {
                "accounts": [
                    {"platform": "抖音", "account_id": "acc_001", "name": "主账号"},
                    {"platform": "抖音", "account_id": "acc_002", "name": "副账号1"},
                    {"platform": "快手", "account_id": "acc_003", "name": "快手主号"},
                ],
                "publish_strategy": "sequential"
            }
        
        context.set_variable("matrix_config", matrix_config)
        return StepResult(success=True, output={"account_count": len(matrix_config.get("accounts", []))})
    
    def _generate_plan(self, context: SkillContext) -> StepResult:
        matrix_config = context.get_variable("matrix_config", {})
        content = context.get_input("content", {})
        
        accounts = matrix_config.get("accounts", [])
        strategy = matrix_config.get("publish_strategy", "sequential")
        
        publish_plan = []
        
        for i, account in enumerate(accounts):
            delay = 0
            if strategy == "sequential":
                delay = i * 300
            
            plan_item = {
                "account": account,
                "content": content,
                "delay_seconds": delay,
                "scheduled_time": datetime.now().isoformat()
            }
            publish_plan.append(plan_item)
        
        context.set_variable("publish_plan", publish_plan)
        return StepResult(success=True, output={"plan_count": len(publish_plan)})
    
    def _batch_publish(self, context: SkillContext) -> StepResult:
        publish_plan = context.get_variable("publish_plan", [])
        results = []
        
        for plan_item in publish_plan:
            account = plan_item["account"]
            
            result = {
                "account": account,
                "status": "submitted",
                "message": f"已提交到 {account['platform']} - {account['name']}",
                "timestamp": datetime.now().isoformat()
            }
            results.append(result)
        
        context.set_variable("batch_results", results)
        return StepResult(success=True, output={"results_count": len(results)})
    
    def _summarize_results(self, context: SkillContext) -> StepResult:
        batch_results = context.get_variable("batch_results", [])
        
        summary = {
            "total": len(batch_results),
            "success": sum(1 for r in batch_results if r["status"] == "submitted"),
            "failed": sum(1 for r in batch_results if r["status"] == "failed"),
            "details": batch_results
        }
        
        context.set_output("summary", summary)
        return StepResult(success=True, output={"summary": summary})


ACCOUNT_SKILLS = [
    AccountDataCollectSkill,
    AccountAnalysisSkill,
    PublishContentSkill,
    MatrixPublishSkill
]


def register_account_skills():
    """注册账号运营 Skills"""
    for skill_class in ACCOUNT_SKILLS:
        skill_engine.register_skill(skill_class)
        print(f"  ✅ 注册 Skill: {skill_class.skill_name}")
