"""
OpenClow 自动化引擎模块
======================
提供多平台自动化运营功能：数据采集、自动发布、智能回复等

v2: 已接入 BrowserAutomation 真实浏览器自动化
"""

import os
import json
import time
import random
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

logger = logging.getLogger("AI短剧编辑器.openclow")


class OpenClowEngine:
    """OpenClow 自动化运营引擎 v2 — 已接入真实浏览器"""
    
    def __init__(self, data_dir: str = "openclow_data"):
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        self.platforms = ["抖音", "快手", "视频号", "B站", "小红书"]
        self.accounts: Dict[str, Dict] = {}
        self.published_content: List[Dict] = []
        self.reply_rules: List[Dict] = []
        self.operation_data: List[Dict] = []
        self._browser = None
        self._use_real_browser = False
        self._load_data()
    
    @property
    def use_real_browser(self) -> bool:
        return self._use_real_browser
    
    def enable_real_browser(self, headless: bool = True) -> bool:
        """启用真实浏览器自动化（替代模拟数据）"""
        try:
            from app.core.automation import get_browser_automation
            self._browser = get_browser_automation(headless=headless)
            if self._browser.start():
                self._use_real_browser = True
                logger.info("浏览器自动化已启用")
                return True
        except Exception as e:
            logger.warning(f"浏览器启动失败，回退模拟模式: {e}")
            self._use_real_browser = False
        return False
    
    def disable_browser(self):
        """关闭浏览器"""
        if self._browser:
            self._browser.stop()
        self._use_real_browser = False

    def _load_data(self):
        """加载持久化数据"""
        rules_file = os.path.join(self.data_dir, "reply_rules.json")
        if os.path.exists(rules_file):
            try:
                with open(rules_file, "r", encoding="utf-8") as f:
                    self.reply_rules = json.load(f)
            except Exception as e:
                logger.debug("加载回复规则失败: %s", e)
        
        accounts_file = os.path.join(self.data_dir, "accounts.json")
        if os.path.exists(accounts_file):
            try:
                with open(accounts_file, "r", encoding="utf-8") as f:
                    self.accounts = json.load(f)
            except Exception as e:
                logger.debug("加载账号数据失败: %s", e)
    
    def _save_accounts(self):
        """保存账号数据"""
        try:
            accounts_file = os.path.join(self.data_dir, "accounts.json")
            with open(accounts_file, "w", encoding="utf-8") as f:
                json.dump(self.accounts, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存账号数据失败: {e}")
    
    def add_account(self, platform: str, account_id: str, account_info: Dict) -> bool:
        """添加账号"""
        try:
            key = f"{platform}_{account_id}"
            self.accounts[key] = {
                "platform": platform,
                "account_id": account_id,
                "info": account_info,
                "created_at": datetime.now().isoformat()
            }
            self._save_accounts()
            return True
        except Exception as e:
            print(f"添加账号失败: {e}")
            return False
    
    def remove_account(self, platform: str, account_id: str) -> bool:
        """移除账号"""
        key = f"{platform}_{account_id}"
        if key in self.accounts:
            del self.accounts[key]
            self._save_accounts()
            return True
        return False
    
    def get_accounts(self, platform: Optional[str] = None) -> List[Dict]:
        """获取账号列表"""
        if platform:
            return [acc for acc in self.accounts.values() if acc["platform"] == platform]
        return list(self.accounts.values())
    
    def collect_data(self, platform: str, account_id: str) -> Optional[Dict]:
        """数据采集 — 真实浏览器 + 模拟回退"""
        try:
            print(f"开始采集{platform}账号{account_id}的数据...")
            
            # 优先使用真实浏览器采集
            if self._use_real_browser and self._browser:
                browser_data = self._browser.collect_analytics(platform)
                if browser_data:
                    collected_data = {
                        "platform": platform,
                        "account_id": account_id,
                        "timestamp": datetime.now().isoformat(),
                        "source": "browser_automation",
                        "data": browser_data
                    }
                    data_file = os.path.join(self.data_dir, f"{platform}_{account_id}_{int(time.time())}.json")
                    with open(data_file, "w", encoding="utf-8") as f:
                        json.dump(collected_data, f, ensure_ascii=False, indent=2)
                    print(f"{platform}真实数据采集完成 (截图: {browser_data.get('screenshot')})")
                    self.operation_data.append(collected_data)
                    return collected_data
            
            # 回退: 模拟数据（开发/测试用）
            collected_data = {
                "platform": platform,
                "account_id": account_id,
                "timestamp": datetime.now().isoformat(),
                "source": "simulated",
                "data": {
                    "views": random.randint(1000, 100000),
                    "likes": random.randint(100, 10000),
                    "comments": random.randint(10, 1000),
                    "shares": random.randint(5, 500),
                    "followers": random.randint(100, 50000)
                }
            }
            data_file = os.path.join(self.data_dir, f"{platform}_{account_id}_{int(time.time())}.json")
            with open(data_file, "w", encoding="utf-8") as f:
                json.dump(collected_data, f, ensure_ascii=False, indent=2)
            print(f"{platform}模拟数据采集完成")
            return collected_data
        except Exception as e:
            print(f"数据采集失败: {e}")
            return None
    
    def auto_publish(
        self, 
        platform: str, 
        account_id: str, 
        content: Dict, 
        schedule_time: Optional[str] = None
    ) -> Optional[Dict]:
        """内容自动发布 — 真实浏览器 + 本地记录"""
        try:
            publish_time = schedule_time if schedule_time else datetime.now().isoformat()
            print(f"开始发布内容到{platform}账号{account_id}...")
            
            # 优先使用真实浏览器发布
            if self._use_real_browser and self._browser:
                video_path = content.get("video_path", "")
                title = content.get("title", "")
                description = content.get("description", "")
                tags = content.get("tags", [])
                
                publish_result = self._browser.publish_video(
                    platform, video_path, title, description, tags
                )
                
                publish_record = {
                    "id": f"pub_{int(time.time())}",
                    "platform": platform,
                    "account_id": account_id,
                    "content": content,
                    "publish_time": publish_time,
                    "status": "published" if publish_result.get("success") else "pending",
                    "source": "browser_automation",
                    "browser_result": publish_result,
                    "timestamp": datetime.now().isoformat()
                }
            else:
                publish_record = {
                    "id": f"pub_{int(time.time())}",
                    "platform": platform,
                    "account_id": account_id,
                    "content": content,
                    "publish_time": publish_time,
                    "status": "published",
                    "source": "simulated",
                    "timestamp": datetime.now().isoformat()
                }
            
            self.published_content.append(publish_record)
            publish_file = os.path.join(self.data_dir, f"publish_{publish_record['id']}.json")
            with open(publish_file, "w", encoding="utf-8") as f:
                json.dump(publish_record, f, ensure_ascii=False, indent=2)
            
            print(f"内容已发布到{platform} ({publish_record['source']})")
            return publish_record
        except Exception as e:
            print(f"内容发布失败: {e}")
            return None
    
    def smart_reply(
        self, 
        platform: str, 
        account_id: str, 
        comment: str, 
        keywords: Optional[List[str]] = None
    ) -> Optional[Dict]:
        """评论智能回复"""
        try:
            print(f"处理{platform}账号{account_id}的评论...")
            
            reply = "感谢您的评论！"
            
            if keywords:
                for keyword in keywords:
                    if keyword in comment:
                        for rule in self.reply_rules:
                            if rule["keyword"] in comment:
                                reply = rule["reply"]
                                break
                        break
            
            reply_record = {
                "id": f"reply_{int(time.time())}",
                "platform": platform,
                "account_id": account_id,
                "comment": comment,
                "reply": reply,
                "timestamp": datetime.now().isoformat()
            }
            
            reply_file = os.path.join(self.data_dir, f"reply_{reply_record['id']}.json")
            with open(reply_file, "w", encoding="utf-8") as f:
                json.dump(reply_record, f, ensure_ascii=False, indent=2)
            
            print(f"已回复{platform}账号{account_id}的评论")
            return reply_record
        except Exception as e:
            print(f"智能回复失败: {e}")
            return None
    
    def write_back_data(self, platform: str, account_id: str, data: Dict) -> Optional[Dict]:
        """运营数据回写"""
        try:
            print(f"回写{platform}账号{account_id}的运营数据...")
            
            write_back_record = {
                "id": f"writeback_{int(time.time())}",
                "platform": platform,
                "account_id": account_id,
                "data": data,
                "timestamp": datetime.now().isoformat()
            }
            
            self.operation_data.append(write_back_record)
            
            write_back_file = os.path.join(self.data_dir, f"writeback_{write_back_record['id']}.json")
            with open(write_back_file, "w", encoding="utf-8") as f:
                json.dump(write_back_record, f, ensure_ascii=False, indent=2)
            
            print(f"{platform}账号{account_id}的运营数据回写完成")
            return write_back_record
        except Exception as e:
            print(f"数据回写失败: {e}")
            return None
    
    def generate_operation_suggestions(
        self, 
        platform: str, 
        account_id: str, 
        data: Dict
    ) -> Optional[Dict]:
        """生成运营建议"""
        try:
            print(f"为{platform}账号{account_id}生成运营建议...")
            
            suggestions = []
            
            views = data.get("views", 0)
            likes = data.get("likes", 0)
            comments = data.get("comments", 0)
            shares = data.get("shares", 0)
            followers = data.get("followers", 0)
            
            if views > 0:
                interaction_rate = (likes + comments + shares) / views
            else:
                interaction_rate = 0
            
            if views < 10000:
                suggestions.append("建议增加内容发布频率，提高账号曝光度")
            if interaction_rate < 0.05:
                suggestions.append("建议在视频中增加互动元素，提高观众参与度")
            if comments < 100:
                suggestions.append("建议主动回复评论，增强粉丝粘性")
            if shares < 50:
                suggestions.append("建议创作更具分享价值的内容")
            if followers < 1000:
                suggestions.append("建议优化账号简介和封面，吸引更多关注")
            
            if not suggestions:
                suggestions.append("账号运营状况良好，继续保持现有策略")
            
            suggestion_record = {
                "id": f"suggestion_{int(time.time())}",
                "platform": platform,
                "account_id": account_id,
                "data": data,
                "suggestions": suggestions,
                "timestamp": datetime.now().isoformat()
            }
            
            suggestion_file = os.path.join(self.data_dir, f"suggestion_{suggestion_record['id']}.json")
            with open(suggestion_file, "w", encoding="utf-8") as f:
                json.dump(suggestion_record, f, ensure_ascii=False, indent=2)
            
            print(f"已为{platform}账号{account_id}生成运营建议")
            return suggestion_record
        except Exception as e:
            print(f"生成运营建议失败: {e}")
            return None
    
    def add_reply_rule(self, keyword: str, reply: str) -> Dict:
        """添加回复规则"""
        rule = {
            "id": f"rule_{int(time.time())}",
            "keyword": keyword,
            "reply": reply,
            "timestamp": datetime.now().isoformat()
        }
        self.reply_rules.append(rule)
        
        rules_file = os.path.join(self.data_dir, "reply_rules.json")
        with open(rules_file, "w", encoding="utf-8") as f:
            json.dump(self.reply_rules, f, ensure_ascii=False, indent=2)
        
        return rule
    
    def remove_reply_rule(self, rule_id: str) -> bool:
        """移除回复规则"""
        for i, rule in enumerate(self.reply_rules):
            if rule["id"] == rule_id:
                del self.reply_rules[i]
                rules_file = os.path.join(self.data_dir, "reply_rules.json")
                with open(rules_file, "w", encoding="utf-8") as f:
                    json.dump(self.reply_rules, f, ensure_ascii=False, indent=2)
                return True
        return False
    
    def get_published_content(self) -> List[Dict]:
        """获取已发布的内容"""
        return self.published_content
    
    def get_operation_data(self) -> List[Dict]:
        """获取运营数据"""
        return self.operation_data
    
    def matrix_publish(
        self, 
        content: Dict, 
        platforms: List[str], 
        schedule_time: Optional[str] = None
    ) -> List[Dict]:
        """矩阵发布 - 同时发布到多个平台"""
        results = []
        for platform in platforms:
            accounts = self.get_accounts(platform)
            for account in accounts:
                result = self.auto_publish(
                    platform=platform,
                    account_id=account["account_id"],
                    content=content,
                    schedule_time=schedule_time
                )
                if result:
                    results.append(result)
        return results


_openclow_engine_instance: Optional[OpenClowEngine] = None


def get_openclow_engine(data_dir: str = "openclow_data") -> OpenClowEngine:
    """获取 OpenClow 引擎实例"""
    global _openclow_engine_instance
    
    if _openclow_engine_instance is None:
        _openclow_engine_instance = OpenClowEngine(data_dir)
    
    return _openclow_engine_instance
