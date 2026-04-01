"""
邮件验证模块 (EmailVerify)
=========================
无服务器邮件验证系统
支持 SMTP 发送验证码到用户邮箱
"""

import smtplib
import ssl
import secrets
import time
import json
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, Dict, Tuple
from dataclasses import dataclass
from datetime import datetime
import threading
import logging

logger = logging.getLogger(__name__)


@dataclass
class SMTPConfig:
    """SMTP 配置"""
    host: str = "smtp.qq.com"
    port: int = 465
    username: str = ""
    password: str = ""
    sender_name: str = "AI短剧编辑器"
    use_ssl: bool = True


@dataclass
class VerificationCode:
    """验证码记录"""
    email: str
    code: str
    created_at: float
    expires_at: float
    used: bool = False


class EmailVerificationService:
    """邮件验证服务"""
    
    _instance: Optional['EmailVerificationService'] = None
    _lock = threading.Lock()
    
    CODE_EXPIRE_SECONDS = 300
    CODE_LENGTH = 6
    
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
        
        self._config: Optional[SMTPConfig] = None
        self._codes: Dict[str, VerificationCode] = {}
        self._config_path = self._get_config_path()
        self._load_config()
    
    def _get_config_path(self) -> str:
        """获取配置文件路径"""
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        data_dir = os.path.join(base_dir, "data")
        os.makedirs(data_dir, exist_ok=True)
        return os.path.join(data_dir, "smtp_config.json")
    
    def _load_config(self):
        """加载 SMTP 配置"""
        if os.path.exists(self._config_path):
            try:
                with open(self._config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self._config = SMTPConfig(
                    host=data.get("host", "smtp.qq.com"),
                    port=data.get("port", 465),
                    username=data.get("username", ""),
                    password=data.get("password", ""),
                    sender_name=data.get("sender_name", "AI短剧编辑器"),
                    use_ssl=data.get("use_ssl", True)
                )
                logger.info("SMTP 配置加载成功")
            except Exception as e:
                logger.warning(f"SMTP 配置加载失败: {e}")
                self._config = None
    
    def save_config(self, config: SMTPConfig) -> bool:
        """保存 SMTP 配置"""
        try:
            data = {
                "host": config.host,
                "port": config.port,
                "username": config.username,
                "password": config.password,
                "sender_name": config.sender_name,
                "use_ssl": config.use_ssl
            }
            with open(self._config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self._config = config
            logger.info("SMTP 配置保存成功")
            return True
        except Exception as e:
            logger.error(f"SMTP 配置保存失败: {e}")
            return False
    
    def is_configured(self) -> bool:
        """检查是否已配置 SMTP"""
        return self._config is not None and bool(self._config.username) and bool(self._config.password)
    
    def _generate_code(self) -> str:
        """生成验证码"""
        return ''.join([str(secrets.randbelow(10)) for _ in range(self.CODE_LENGTH)])
    
    def _create_email_content(self, code: str) -> Tuple[str, str]:
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
    
    def send_verification_code(self, email: str) -> Tuple[bool, str]:
        """发送验证码"""
        if not self.is_configured():
            return False, "SMTP 未配置，请先在设置中配置邮箱服务"
        
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
            
            message = MIMEMultipart("alternative")
            message["Subject"] = subject
            message["From"] = f"{self._config.sender_name} <{self._config.username}>"
            message["To"] = email
            
            message.attach(MIMEText(text_content, "plain", "utf-8"))
            message.attach(MIMEText(html_content, "html", "utf-8"))
            
            if self._config.use_ssl:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(self._config.host, self._config.port, context=context) as server:
                    server.login(self._config.username, self._config.password)
                    server.sendmail(self._config.username, email, message.as_string())
            else:
                with smtplib.SMTP(self._config.host, self._config.port) as server:
                    server.starttls()
                    server.login(self._config.username, self._config.password)
                    server.sendmail(self._config.username, email, message.as_string())
            
            logger.info(f"验证码已发送到: {email}")
            return True, "验证码已发送，请查收邮件"
            
        except smtplib.SMTPAuthenticationError:
            return False, "SMTP 认证失败，请检查用户名和密码"
        except smtplib.SMTPException as e:
            logger.error(f"SMTP 发送失败: {e}")
            return False, f"邮件发送失败: {str(e)}"
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


email_verification_service = EmailVerificationService()


SMTP_PRESETS = {
    "QQ邮箱": SMTPConfig(
        host="smtp.qq.com",
        port=465,
        use_ssl=True,
        sender_name="AI短剧编辑器"
    ),
    "163邮箱": SMTPConfig(
        host="smtp.163.com",
        port=465,
        use_ssl=True,
        sender_name="AI短剧编辑器"
    ),
    "Gmail": SMTPConfig(
        host="smtp.gmail.com",
        port=587,
        use_ssl=False,
        sender_name="AI短剧编辑器"
    ),
    "Outlook": SMTPConfig(
        host="smtp-mail.outlook.com",
        port=587,
        use_ssl=False,
        sender_name="AI短剧编辑器"
    ),
    "阿里企业邮箱": SMTPConfig(
        host="smtp.qiye.aliyun.com",
        port=465,
        use_ssl=True,
        sender_name="AI短剧编辑器"
    ),
}
