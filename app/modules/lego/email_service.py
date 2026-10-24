"""
邮件服务模块 (EmailService)
=========================
使用第三方邮件服务发送验证码
支持: SendGrid、阿里云邮件推送
"""

import secrets
import time
import json
import os
from typing import Optional, Dict, Tuple
from dataclasses import dataclass
from datetime import datetime
import threading
import logging

logger = logging.getLogger(__name__)


@dataclass
class EmailServiceConfig:
    """邮件服务配置"""
    provider: str = "sendgrid"  # sendgrid, aliyun
    api_key: str = ""
    sender_email: str = "noreply@aishortdrama.com"
    sender_name: str = "AI短剧编辑器"


@dataclass
class VerificationCode:
    """验证码记录"""
    email: str
    code: str
    created_at: float
    expires_at: float
    used: bool = False


class EmailService:
    """邮件服务 - 使用第三方邮件服务"""
    
    _instance: Optional['EmailService'] = None
    _lock = threading.Lock()
    
    CODE_EXPIRE_SECONDS = 300
    CODE_LENGTH = 6
    
    # 内置的SendGrid API密钥（开发者配置）
    DEFAULT_API_KEY = ""
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        self._config: EmailServiceConfig = EmailServiceConfig()
        self._codes: Dict[str, VerificationCode] = {}
        self._config_path = self._get_config_path()
        self._load_config()
    
    def _get_config_path(self) -> str:
        """获取配置文件路径"""
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        data_dir = os.path.join(base_dir, "data")
        os.makedirs(data_dir, exist_ok=True)
        return os.path.join(data_dir, "email_service_config.json")
    
    def _load_config(self):
        """加载邮件服务配置"""
        if os.path.exists(self._config_path):
            try:
                with open(self._config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self._config = EmailServiceConfig(
                    provider=data.get("provider", "sendgrid"),
                    api_key=data.get("api_key", ""),
                    sender_email=data.get("sender_email", "noreply@aishortdrama.com"),
                    sender_name=data.get("sender_name", "AI短剧编辑器")
                )
                logger.info("邮件服务配置加载成功")
            except Exception as e:
                logger.warning(f"邮件服务配置加载失败: {e}")
                self._config = EmailServiceConfig()
    
    def save_config(self, config: EmailServiceConfig) -> bool:
        """保存邮件服务配置"""
        try:
            data = {
                "provider": config.provider,
                "api_key": config.api_key,
                "sender_email": config.sender_email,
                "sender_name": config.sender_name
            }
            with open(self._config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self._config = config
            logger.info("邮件服务配置保存成功")
            return True
        except Exception as e:
            logger.error(f"邮件服务配置保存失败: {e}")
            return False
    
    def is_configured(self) -> bool:
        """检查是否已配置邮件服务"""
        return bool(self._config.api_key)
    
    def _generate_code(self) -> str:
        """生成验证码"""
        return ''.join([str(secrets.randbelow(10)) for _ in range(self.CODE_LENGTH)])
    
    def _create_email_content(self, code: str) -> Tuple[str, str, str]:
        """创建邮件内容"""
        subject = f"【AI短剧编辑器】邮箱验证码"
        
        text_content = f"""
您好！

您的邮箱验证码是：{code}

验证码有效期为 5 分钟，请尽快完成验证。

如果这不是您的操作，请忽略此邮件。

---
AI短剧编辑器团队
{datetime.now().strftime('%Y-%m-%d')}
"""
        
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ font-family: 'Microsoft YaHei', Arial, sans-serif; background-color: #f5f5f5; padding: 20px; }}
        .container {{ max-width: 600px; margin: 0 auto; background: white; border-radius: 10px; padding: 30px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        .header {{ text-align: center; border-bottom: 2px solid #1e6bde; padding-bottom: 20px; margin-bottom: 20px; }}
        .logo {{ font-size: 24px; font-weight: bold; color: #1e6bde; }}
        .code-box {{ background: linear-gradient(135deg, #1e6bde, #6366f1); color: white; padding: 20px; border-radius: 8px; text-align: center; margin: 30px 0; }}
        .code {{ font-size: 32px; font-weight: bold; letter-spacing: 8px; }}
        .info {{ color: #666; font-size: 14px; line-height: 1.8; }}
        .warning {{ color: #e74c3c; font-size: 12px; margin-top: 20px; }}
        .footer {{ text-align: center; color: #999; font-size: 12px; margin-top: 30px; padding-top: 20px; border-top: 1px solid #eee; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="logo">🎬 AI短剧编辑器</div>
        </div>
        
        <p class="info">您好！</p>
        <p class="info">您正在进行邮箱验证，验证码如下：</p>
        
        <div class="code-box">
            <div class="code">{code}</div>
        </div>
        
        <p class="info">验证码有效期为 <strong>5 分钟</strong>，请尽快完成验证。</p>
        
        <p class="warning">⚠️ 如果这不是您的操作，请忽略此邮件。</p>
        
        <div class="footer">
            <p>AI短剧编辑器团队</p>
            <p>{datetime.now().strftime('%Y-%m-%d')}</p>
        </div>
    </div>
</body>
</html>
"""
        
        return subject, text_content, html_content
    
    def _send_via_sendgrid(self, email: str, subject: str, text_content: str, html_content: str) -> Tuple[bool, str]:
        """使用SendGrid发送邮件"""
        try:
            import requests
            
            url = "https://api.sendgrid.com/v3/mail/send"
            headers = {
                "Authorization": f"Bearer {self._config.api_key}",
                "Content-Type": "application/json"
            }
            
            data = {
                "personalizations": [{
                    "to": [{"email": email}]
                }],
                "from": {
                    "email": self._config.sender_email,
                    "name": self._config.sender_name
                },
                "subject": subject,
                "content": [
                    {"type": "text/plain", "value": text_content},
                    {"type": "text/html", "value": html_content}
                ]
            }
            
            response = requests.post(url, headers=headers, json=data, timeout=30)
            
            if response.status_code == 202:
                return True, "邮件发送成功"
            else:
                logger.error(f"SendGrid发送失败: {response.status_code} - {response.text}")
                return False, f"邮件发送失败: {response.status_code}"
                
        except ImportError:
            return False, "请先安装requests库: pip install requests"
        except Exception as e:
            logger.error(f"SendGrid发送失败: {e}")
            return False, f"邮件发送失败: {str(e)}"
    
    def _send_via_aliyun(self, email: str, subject: str, text_content: str, html_content: str) -> Tuple[bool, str]:
        """使用阿里云邮件推送发送邮件"""
        try:
            import requests
            import hmac
            import hashlib
            import base64
            from urllib.parse import quote
            
            # 阿里云邮件推送API
            url = "https://dm.aliyuncs.com/"
            
            # 构建请求参数
            params = {
                "Action": "SingleSendMail",
                "AccountName": self._config.sender_email,
                "ReplyToAddress": "false",
                "AddressType": "1",
                "ToAddress": email,
                "Subject": subject,
                "HtmlBody": html_content,
                "TextBody": text_content,
                "FromAlias": self._config.sender_name
            }
            
            # 这里需要实现阿里云签名逻辑
            # 简化处理，实际使用时需要完整的签名实现
            logger.warning("阿里云邮件推送需要完整的API签名实现")
            return False, "阿里云邮件推送功能待完善"
            
        except ImportError:
            return False, "请先安装requests库: pip install requests"
        except Exception as e:
            logger.error(f"阿里云发送失败: {e}")
            return False, f"邮件发送失败: {str(e)}"
    
    def send_verification_code(self, email: str) -> Tuple[bool, str]:
        """发送验证码"""
        # 检查是否配置了API密钥
        if not self.is_configured():
            # 如果没有配置，使用模拟发送（开发测试用）
            code = self._generate_code()
            now = time.time()
            
            self._codes[email] = VerificationCode(
                email=email,
                code=code,
                created_at=now,
                expires_at=now + self.CODE_EXPIRE_SECONDS
            )
            
            # 在开发模式下，直接返回验证码
            logger.info(f"开发模式 - 验证码: {code}")
            return True, f"验证码: {code} (开发模式)"
        
        code = self._generate_code()
        now = time.time()
        
        self._codes[email] = VerificationCode(
            email=email,
            code=code,
            created_at=now,
            expires_at=now + self.CODE_EXPIRE_SECONDS
        )
        
        try:
            subject, text_content, html_content = self._create_email_content(code)
            
            # 根据配置的提供商发送邮件
            if self._config.provider == "sendgrid":
                success, message = self._send_via_sendgrid(email, subject, text_content, html_content)
            elif self._config.provider == "aliyun":
                success, message = self._send_via_aliyun(email, subject, text_content, html_content)
            else:
                return False, "不支持的邮件服务提供商"
            
            if success:
                logger.info(f"验证码已发送到: {email}")
                return True, "验证码已发送，请查收邮件"
            else:
                return False, message
                
        except Exception as e:
            logger.error(f"发送验证码失败: {e}")
            return False, f"发送失败: {str(e)}"
    
    def verify_code(self, email: str, code: str) -> Tuple[bool, str]:
        """验证验证码"""
        if email not in self._codes:
            return False, "验证码不存在或已过期"
        
        record = self._codes[email]
        now = time.time()
        
        if record.used:
            return False, "验证码已使用"
        
        if now > record.expires_at:
            del self._codes[email]
            return False, "验证码已过期"
        
        if record.code != code:
            return False, "验证码错误"
        
        record.used = True
        logger.info(f"邮箱验证成功: {email}")
        return True, "验证成功"
    
    def get_remaining_time(self, email: str) -> int:
        """获取验证码剩余有效时间"""
        if email not in self._codes:
            return 0
        
        record = self._codes[email]
        remaining = int(record.expires_at - time.time())
        return max(0, remaining)
    
    def can_resend(self, email: str, cooldown: int = 60) -> Tuple[bool, int]:
        """检查是否可以重新发送"""
        if email not in self._codes:
            return True, 0
        
        record = self._codes[email]
        elapsed = int(time.time() - record.created_at)
        
        if elapsed < cooldown:
            return False, cooldown - elapsed
        
        return True, 0


# 全局邮件服务实例
email_service = EmailService()
