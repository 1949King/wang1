"""
平台 OAuth 授权模块
===================
为各短视频/内容平台提供统一的 OAuth 2.0 授权流程。
支持: 抖音、快手、视频号(微信)、小红书、B站、微博、头条、西瓜

使用方式:
    from .platform_oauth import PlatformOAuthManager
    manager = PlatformOAuthManager()
    manager.authorize("douyin")  # 启动 OAuth 授权流程
"""

import json
import logging
import secrets
import threading
import time
import webbrowser
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Callable
from urllib.parse import urlencode

logger = logging.getLogger(__name__)


# ============================================================
# 平台 OAuth 配置
# ============================================================
@dataclass
class OAuthConfig:
    """OAuth 2.0 配置"""
    platform_id: str
    platform_name: str
    authorize_url: str
    token_url: str
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = "http://localhost:8888/callback"
    scopes: List[str] = field(default_factory=list)
    extra_params: Dict[str, str] = field(default_factory=dict)


@dataclass
class OAuthToken:
    """OAuth Token 存储"""
    platform_id: str
    account_name: str = ""
    access_token: str = ""
    refresh_token: str = ""
    token_type: str = "Bearer"
    expires_at: float = 0.0
    open_id: str = ""
    scope: str = ""
    created_at: str = ""
    last_refreshed: str = ""

    @property
    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        return time.time() > self.expires_at - 300  # 提前5分钟过期

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "OAuthToken":
        return cls(**data)


# ============================================================
# 各平台 OAuth 配置定义
# ============================================================
PLATFORM_OAUTH_CONFIGS = {
    "douyin": OAuthConfig(
        platform_id="douyin",
        platform_name="抖音",
        authorize_url="https://open.douyin.com/platform/oauth/connect/",
        token_url="https://open.douyin.com/oauth/access_token/",
        client_id="",  # 用户需在抖音开放平台申请
        scopes=["user_info", "video.list", "video.data", "video.publish"],
    ),
    "kuaishou": OAuthConfig(
        platform_id="kuaishou",
        platform_name="快手",
        authorize_url="https://open.kuaishou.com/oauth2/authorize",
        token_url="https://open.kuaishou.com/oauth2/access_token",
        scopes=["user_info", "user_video_info", "user_video_publish"],
    ),
    "weixin": OAuthConfig(
        platform_id="weixin",
        platform_name="视频号(微信)",
        authorize_url="https://open.weixin.qq.com/connect/oauth2/authorize",
        token_url="https://api.weixin.qq.com/sns/oauth2/access_token",
        scopes=["snsapi_userinfo"],
        extra_params={"response_type": "code"},
    ),
    "xiaohongshu": OAuthConfig(
        platform_id="xiaohongshu",
        platform_name="小红书",
        authorize_url="https://open.xiaohongshu.com/oauth/authorize",
        token_url="https://open.xiaohongshu.com/oauth/access_token",
        scopes=["user_info", "note.read", "note.write"],
    ),
    "bilibili": OAuthConfig(
        platform_id="bilibili",
        platform_name="B站",
        authorize_url="https://passport.bilibili.com/register/pc_oauth2.html",
        token_url="https://api.bilibili.com/x/account-oauth2/v1/access_token",
        scopes=["user_info", "video_upload"],
    ),
    "weibo": OAuthConfig(
        platform_id="weibo",
        platform_name="微博",
        authorize_url="https://api.weibo.com/oauth2/authorize",
        token_url="https://api.weibo.com/oauth2/access_token",
        scopes=["all"],
    ),
    "toutiao": OAuthConfig(
        platform_id="toutiao",
        platform_name="头条",
        authorize_url="https://open.snssdk.com/platform/oauth/connect/",
        token_url="https://open.snssdk.com/oauth/access_token/",
        scopes=["user_info", "video.data", "video.publish"],
    ),
    "xigua": OAuthConfig(
        platform_id="xigua",
        platform_name="西瓜",
        authorize_url="https://open-api.ixigua.com/platform/oauth/connect/",
        token_url="https://open-api.ixigua.com/oauth/access_token/",
        scopes=["user_info", "video.data", "video.publish"],
    ),
}


# ============================================================
# Token 持久化存储
# ============================================================
class OAuthTokenStore:
    """OAuth Token 持久化管理"""

    def __init__(self):
        self._tokens: Dict[str, OAuthToken] = {}
        self._load()

    @classmethod
    def _token_file(cls) -> Path:
        workspace = Path(__file__).parent.parent.parent.parent
        data_dir = workspace / "data" / "oauth"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / "tokens.json"

    def _load(self):
        """从磁盘加载已保存的 token"""
        tf = self._token_file()
        if tf.exists():
            try:
                with open(tf, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for pid, token_data in data.items():
                    token = OAuthToken.from_dict(token_data)
                    if not token.is_expired:
                        self._tokens[pid] = token
                        logger.info(f"[OAuth] 加载 {pid} 有效 token")
                    else:
                        logger.info(f"[OAuth] {pid} token 已过期，将尝试刷新")
                        # 保留过期 token，可用于 refresh
                        self._tokens[pid] = token
            except Exception as e:
                logger.warning(f"[OAuth] 加载 token 文件失败: {e}")

    def _save(self):
        """保存 token 到磁盘"""
        tf = self._token_file()
        try:
            data = {pid: token.to_dict() for pid, token in self._tokens.items()}
            with open(tf, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[OAuth] 保存 token 失败: {e}")

    def get_token(self, platform_id: str) -> Optional[OAuthToken]:
        return self._tokens.get(platform_id)

    def set_token(self, platform_id: str, token: OAuthToken):
        self._tokens[platform_id] = token
        self._save()

    def remove_token(self, platform_id: str):
        self._tokens.pop(platform_id, None)
        self._save()

    def get_all_authorized_platforms(self) -> List[str]:
        return [pid for pid, t in self._tokens.items() if not t.is_expired]


# ============================================================
# OAuth 授权管理器
# ============================================================
class PlatformOAuthManager:
    """
    平台 OAuth 授权管理器
    负责:
    1. 启动 OAuth 2.0 授权流程
    2. 回调拦截获取 access_token
    3. Token 刷新和持久化
    4. 授权状态查询
    """

    def __init__(self):
        self._token_store = OAuthTokenStore()
        self._pending_states: Dict[str, OAuthConfig] = {}
        self._local_server = None
        self._callbacks: Dict[str, Callable] = {}

    # ---- 公共 API ----

    def get_authorized_platforms(self) -> List[str]:
        """获取已授权的平台列表"""
        return self._token_store.get_all_authorized_platforms()

    def is_authorized(self, platform_id: str) -> bool:
        """检查平台是否已授权"""
        token = self._token_store.get_token(platform_id)
        return token is not None and not token.is_expired

    def get_token(self, platform_id: str) -> Optional[OAuthToken]:
        """获取平台 access_token"""
        return self._token_store.get_token(platform_id)

    def get_platform_config(self, platform_id: str) -> Optional[OAuthConfig]:
        """获取平台 OAuth 配置"""
        return PLATFORM_OAUTH_CONFIGS.get(platform_id)

    def has_client_credentials(self, platform_id: str) -> bool:
        """检查是否已配置 client_id 和 client_secret"""
        cfg = PLATFORM_OAUTH_CONFIGS.get(platform_id)
        return cfg is not None and bool(cfg.client_id and cfg.client_secret)

    def set_client_credentials(self, platform_id: str, client_id: str, client_secret: str):
        """设置平台的 client_id 和 client_secret"""
        cfg = PLATFORM_OAUTH_CONFIGS.get(platform_id)
        if cfg:
            cfg.client_id = client_id
            cfg.client_secret = client_secret
            logger.info(f"[OAuth] {cfg.platform_name} 凭证已配置")

    # ---- OAuth 2.0 授权流程 ----

    def authorize(self, platform_id: str,
                  on_success: Callable = None,
                  on_error: Callable = None) -> bool:
        """
        启动 OAuth 2.0 授权流程
        返回 True 表示已启动授权流程（浏览器已打开）
        """
        cfg = PLATFORM_OAUTH_CONFIGS.get(platform_id)
        if not cfg:
            logger.error(f"[OAuth] 未知平台: {platform_id}")
            if on_error:
                on_error(f"不支持的平台: {platform_id}")
            return False

        if not cfg.client_id:
            logger.warning(f"[OAuth] {cfg.platform_name} 未配置 client_id")
            if on_error:
                on_error(f"{cfg.platform_name} 未配置 Client ID，请先在开放平台申请并填入设置")
            return False

        # 生成 state 防 CSRF
        state = secrets.token_urlsafe(32)
        self._pending_states[state] = cfg

        if on_success:
            self._callbacks[f"success_{state}"] = on_success
        if on_error:
            self._callbacks[f"error_{state}"] = on_error

        # 构建授权 URL
        params = {
            "client_id": cfg.client_id,
            "redirect_uri": cfg.redirect_uri,
            "response_type": "code",
            "scope": " ".join(cfg.scopes),
            "state": state,
        }
        params.update(cfg.extra_params)
        auth_url = f"{cfg.authorize_url}?{urlencode(params)}"

        logger.info(f"[OAuth] 启动 {cfg.platform_name} 授权: {auth_url[:100]}...")
        webbrowser.open(auth_url)

        # 启动本地回调服务器（如果尚未运行）
        self._ensure_local_server()

        return True

    def _ensure_local_server(self):
        """确保本地回调 HTTP 服务器正在运行"""
        if self._local_server is not None:
            return

        try:
            from http.server import HTTPServer, BaseHTTPRequestHandler

            manager = self  # 闭包引用

            class OAuthCallbackHandler(BaseHTTPRequestHandler):
                def do_GET(self):
                    from urllib.parse import urlparse, parse_qs

                    parsed = urlparse(self.path)
                    if parsed.path == "/callback":
                        params = parse_qs(parsed.query)
                        code = params.get("code", [None])[0]
                        state = params.get("state", [None])[0]
                        error = params.get("error", [None])[0]
                        error_desc = params.get("error_description", [None])[0]

                        if error:
                            self._send_html(400, "授权失败",
                                            f"平台返回错误: {error}<br>{error_desc or ''}")
                            cb = manager._callbacks.pop(f"error_{state}", None)
                            if cb:
                                cb(f"OAuth 错误: {error} - {error_desc}")
                            return

                        if not code or not state:
                            self._send_html(400, "参数错误", "缺少 code 或 state 参数")
                            return

                        cfg = manager._pending_states.pop(state, None)
                        if not cfg:
                            self._send_html(400, "无效请求", "state 不匹配，请重新发起授权")
                            return

                        # 用 code 换取 access_token
                        success, result = manager._exchange_code(cfg, code)

                        if success:
                            self._send_html(200, "授权成功",
                                            f"<h2>✅ {cfg.platform_name} 授权成功！</h2>"
                                            f"<p>您可以关闭此页面。</p>")
                            cb = manager._callbacks.pop(f"success_{state}", None)
                            if cb:
                                cb(result)
                        else:
                            self._send_html(400, "授权失败",
                                            f"<h2>❌ Token 交换失败</h2><p>{result}</p>")
                            cb = manager._callbacks.pop(f"error_{state}", None)
                            if cb:
                                cb(result)
                    else:
                        self.send_response(404)
                        self.end_headers()

                def _send_html(self, code: int, title: str, body: str):
                    self.send_response(code)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>body{{font-family:system-ui;display:flex;justify-content:center;
align-items:center;min-height:100vh;margin:0;background:#0f0f0f;color:#e0e0e0;}}
.card{{background:#1a1a1a;padding:40px;border-radius:16px;text-align:center;max-width:480px;}}
h2{{margin-bottom:16px;}}p{{color:#999;line-height:1.6;}}</style></head>
<body><div class="card">{body}</div></body></html>"""
                    self.wfile.write(html.encode("utf-8"))

                def log_message(self, format, *args):
                    pass  # 抑制 HTTP 日志

            self._local_server = HTTPServer(("127.0.0.1", 8888), OAuthCallbackHandler)
            server_thread = threading.Thread(
                target=self._local_server.serve_forever,
                daemon=True,
                name="oauth-callback-server"
            )
            server_thread.start()
            logger.info("[OAuth] 本地回调服务器已启动: http://127.0.0.1:8888/callback")

        except Exception as e:
            logger.warning(f"[OAuth] 无法启动本地回调服务器: {e}")
            self._local_server = None

    def _exchange_code(self, cfg: OAuthConfig, code: str) -> tuple:
        """
        用授权码换取 access_token
        返回 (success: bool, result: str|OAuthToken)
        """
        import requests

        try:
            data = {
                "client_id": cfg.client_id,
                "client_secret": cfg.client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": cfg.redirect_uri,
            }

            logger.info(f"[OAuth] 正在为 {cfg.platform_name} 交换 token...")
            resp = requests.post(cfg.token_url, data=data, timeout=30)
            resp_data = resp.json()

            if "access_token" not in resp_data:
                error_msg = resp_data.get("error_description",
                                           resp_data.get("error", str(resp_data)))
                logger.error(f"[OAuth] {cfg.platform_name} token 交换失败: {error_msg}")
                return False, f"Token 交换失败: {error_msg}"

            # 构建 OAuthToken
            expires_in = resp_data.get("expires_in", 7200)
            token = OAuthToken(
                platform_id=cfg.platform_id,
                account_name="",  # 后续通过 API 获取
                access_token=resp_data["access_token"],
                refresh_token=resp_data.get("refresh_token", ""),
                token_type=resp_data.get("token_type", "Bearer"),
                expires_at=time.time() + int(expires_in),
                open_id=resp_data.get("open_id", resp_data.get("openid", "")),
                scope=resp_data.get("scope", " ".join(cfg.scopes)),
                created_at=datetime.now().isoformat(),
                last_refreshed=datetime.now().isoformat(),
            )

            # 持久化
            self._token_store.set_token(cfg.platform_id, token)
            logger.info(f"[OAuth] {cfg.platform_name} 授权成功")

            return True, token

        except requests.exceptions.Timeout:
            return False, "Token 交换超时，请检查网络连接"
        except requests.exceptions.ConnectionError:
            return False, "无法连接到平台服务器，请检查网络"
        except Exception as e:
            logger.error(f"[OAuth] {cfg.platform_name} token 交换异常: {e}")
            return False, f"Token 交换异常: {str(e)}"

    def refresh_token(self, platform_id: str) -> bool:
        """刷新过期的 access_token"""
        token = self._token_store.get_token(platform_id)
        cfg = PLATFORM_OAUTH_CONFIGS.get(platform_id)

        if not token or not cfg:
            return False
        if not token.refresh_token:
            logger.warning(f"[OAuth] {platform_id} 无 refresh_token，无法刷新")
            return False

        import requests
        try:
            data = {
                "client_id": cfg.client_id,
                "client_secret": cfg.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": token.refresh_token,
            }

            resp = requests.post(cfg.token_url, data=data, timeout=30)
            resp_data = resp.json()

            if "access_token" in resp_data:
                expires_in = resp_data.get("expires_in", 7200)
                token.access_token = resp_data["access_token"]
                token.refresh_token = resp_data.get("refresh_token", token.refresh_token)
                token.expires_at = time.time() + int(expires_in)
                token.last_refreshed = datetime.now().isoformat()
                self._token_store.set_token(platform_id, token)
                logger.info(f"[OAuth] {cfg.platform_name} token 刷新成功")
                return True

        except Exception as e:
            logger.warning(f"[OAuth] {cfg.platform_name} token 刷新失败: {e}")

        return False

    def revoke(self, platform_id: str):
        """撤销授权"""
        self._token_store.remove_token(platform_id)
        logger.info(f"[OAuth] {platform_id} 授权已撤销")


# ============================================================
# 全局单例
# ============================================================
_oauth_manager: Optional[PlatformOAuthManager] = None


def get_oauth_manager() -> PlatformOAuthManager:
    """获取全局 OAuth 管理器单例"""
    global _oauth_manager
    if _oauth_manager is None:
        _oauth_manager = PlatformOAuthManager()
    return _oauth_manager
