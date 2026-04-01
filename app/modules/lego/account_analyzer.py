"""
账号分析模块 (AccountAnalyzer)
=============================
提供账号数据分析、优化建议生成等功能
"""

import os
import json
from datetime import datetime
from typing import Dict, List, Any, Optional


class AccountAnalyzer:
    """账号数据分析器"""
    
    def __init__(self, data_dir: str = "运营数据"):
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
    
    def add_video_data(
        self, 
        video_id: str, 
        title: str, 
        views: int, 
        likes: int, 
        comments: int, 
        shares: int, 
        conversions: int
    ) -> bool:
        """添加视频数据"""
        try:
            data = {
                "video_id": video_id,
                "title": title,
                "views": views,
                "likes": likes,
                "comments": comments,
                "shares": shares,
                "conversions": conversions,
                "timestamp": datetime.now().isoformat(),
                "like_rate": likes / views if views > 0 else 0,
                "comment_rate": comments / views if views > 0 else 0,
                "share_rate": shares / views if views > 0 else 0,
                "conversion_rate": conversions / views if views > 0 else 0
            }
            
            data_file = os.path.join(self.data_dir, f"{video_id}.json")
            with open(data_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            print(f"添加视频数据失败: {e}")
            return False
    
    def analyze_data(self) -> Dict[str, Any]:
        """分析所有数据"""
        try:
            all_data = []
            for file in os.listdir(self.data_dir):
                if file.endswith(".json"):
                    file_path = os.path.join(self.data_dir, file)
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            all_data.append(data)
                    except:
                        pass
            
            if not all_data:
                return {"error": "无数据"}
            
            total_views = sum(d.get("views", 0) for d in all_data)
            total_likes = sum(d.get("likes", 0) for d in all_data)
            total_comments = sum(d.get("comments", 0) for d in all_data)
            total_shares = sum(d.get("shares", 0) for d in all_data)
            total_conversions = sum(d.get("conversions", 0) for d in all_data)
            
            avg_views = total_views / len(all_data)
            avg_likes = total_likes / len(all_data)
            avg_comments = total_comments / len(all_data)
            avg_shares = total_shares / len(all_data)
            avg_conversions = total_conversions / len(all_data)
            
            avg_like_rate = sum(d.get("like_rate", 0) for d in all_data) / len(all_data)
            avg_comment_rate = sum(d.get("comment_rate", 0) for d in all_data) / len(all_data)
            avg_share_rate = sum(d.get("share_rate", 0) for d in all_data) / len(all_data)
            avg_conversion_rate = sum(d.get("conversion_rate", 0) for d in all_data) / len(all_data)
            
            top_views = sorted(all_data, key=lambda x: x.get("views", 0), reverse=True)[:3]
            top_conversions = sorted(all_data, key=lambda x: x.get("conversions", 0), reverse=True)[:3]
            top_conversion_rate = sorted(all_data, key=lambda x: x.get("conversion_rate", 0), reverse=True)[:3]
            
            return {
                "total_videos": len(all_data),
                "total_views": total_views,
                "total_likes": total_likes,
                "total_comments": total_comments,
                "total_shares": total_shares,
                "total_conversions": total_conversions,
                "average_views": avg_views,
                "average_likes": avg_likes,
                "average_comments": avg_comments,
                "average_shares": avg_shares,
                "average_conversions": avg_conversions,
                "average_like_rate": avg_like_rate,
                "average_comment_rate": avg_comment_rate,
                "average_share_rate": avg_share_rate,
                "average_conversion_rate": avg_conversion_rate,
                "top_views": top_views,
                "top_conversions": top_conversions,
                "top_conversion_rate": top_conversion_rate
            }
        except Exception as e:
            print(f"分析数据失败: {e}")
            return {"error": str(e)}
    
    def generate_optimization_suggestions(self, analysis_data: Dict[str, Any]) -> str:
        """生成优化建议"""
        if "error" in analysis_data:
            return "暂无数据，无法生成建议"
        
        suggestions = []
        
        if analysis_data["average_like_rate"] < 0.05:
            suggestions.append("建议优化视频内容质量，增加情感共鸣点")
        
        if analysis_data["average_comment_rate"] < 0.01:
            suggestions.append("建议在视频中设置互动问题，鼓励观众评论")
        
        if analysis_data["average_share_rate"] < 0.005:
            suggestions.append("建议增加视频的价值性和分享点")
        
        if analysis_data["average_conversion_rate"] < 0.001:
            suggestions.append("建议优化引导语和转化路径")
        
        if not suggestions:
            suggestions.append("数据表现良好，继续保持")
        
        return "\n".join(suggestions)
    
    def get_video_data(self, video_id: str) -> Optional[Dict[str, Any]]:
        """获取单个视频数据"""
        data_file = os.path.join(self.data_dir, f"{video_id}.json")
        if os.path.exists(data_file):
            try:
                with open(data_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                return None
        return None
    
    def delete_video_data(self, video_id: str) -> bool:
        """删除视频数据"""
        data_file = os.path.join(self.data_dir, f"{video_id}.json")
        if os.path.exists(data_file):
            try:
                os.remove(data_file)
                return True
            except:
                return False
        return False
    
    def export_report(self, output_path: str) -> bool:
        """导出分析报告"""
        try:
            analysis = self.analyze_data()
            suggestions = self.generate_optimization_suggestions(analysis)
            
            report = {
                "generated_at": datetime.now().isoformat(),
                "analysis": analysis,
                "suggestions": suggestions
            }
            
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            print(f"导出报告失败: {e}")
            return False


_account_analyzer_instance: Optional[AccountAnalyzer] = None


def get_account_analyzer(data_dir: str = "运营数据") -> AccountAnalyzer:
    """获取账号分析器实例"""
    global _account_analyzer_instance
    
    if _account_analyzer_instance is None:
        _account_analyzer_instance = AccountAnalyzer(data_dir)
    
    return _account_analyzer_instance
