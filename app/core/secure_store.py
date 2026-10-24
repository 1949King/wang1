"""
secure_store.py
===============
修复 P0-C: 平台凭证 / 会话文件 PII 明文落盘问题
SSOT: app/config/platform_credentials.json 与 app/data/session.json
策略: 透明加密层 - 升级文件后缀为 .enc.json,新文件以 base64(Fernet ciphertext) 存储

使用方式 (零侵入):
    # 升级 (一次)
    from core.secure_store import upgrade_to_encrypted
    upgrade_to_encrypted("app/config/platform_credentials.json")
    upgrade_to_encrypted("app/data/session.json")

    # 加载 (透明, 旧代码无需改)
    from core.secure_store import load_secure_json
    data = load_secure_json("app/config/platform_credentials.enc.json")

    # 保存 (透明)
    from core.secure_store import save_secure_json
    save_secure_json("app/config/platform_credentials.enc.json", data)

密钥管理: 用户级 .secret_key (windows %APPDATA%/AI短剧编辑器/secret.key)
        - 首次运行自动生成,自动 chmod 0o600
        - 加载失败时回退到原文件,记录 warning
"""

import os
import json
import base64
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("AI短剧编辑器.secure_store")

_FERNET_KEY_FILE = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())) / "AI短剧编辑器" / "secret.key"


def _key_dirs() -> list:
    """密钥文件候选**目录**（按优先级）。

    2026-10-23 起密钥不再来自机器码，改由 `dpapi.load_or_create_key(dir)`
    在下列目录里找 `secret.key.dpapi`（DPAPI 包裹的随机钥匙）；保留多目录是
    为了兼容历史安装位置，**不再每个目录各生成一份** —— 只认第一个可用目录。
    """
    dirs = []
    for env_name in ("LOCALAPPDATA", "APPDATA"):
        base = os.environ.get(env_name, "")
        if base:
            dirs.append(Path(base) / "AI短剧编辑器")
    dirs.append(Path.home() / ".ai_drama_editor")
    dirs.append(Path(__file__).parent.parent / "logs")  # 兜底: app/logs/
    # 去重且保序
    seen, out = set(), []
    for d in dirs:
        key = str(d).lower()
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def _get_or_create_fernet_key():
    """获取或创建 Fernet 密钥 —— **纯随机 + DPAPI 守护**（不再绑硬件指纹）。

    历史行为（已弃用）：钥匙由机器码 PBKDF2 派生，改机器名/换硬件即失效。
    现行为：`Fernet.generate_key()` 生成随机钥匙，用 Windows DPAPI
    （绑定当前用户账户）加密后落盘 `secret.key.dpapi`；读到旧的明文
    `secret.key` 会自动迁移并改名 `.legacy`。
    """
    global _FERNET_INSTANCE
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        logger.warning("cryptography 库未安装, PII 加密降级为明文 (请 pip install cryptography)")
        return None

    try:
        from app.core.dpapi import load_or_create_key
    except ImportError:
        try:
            from core.dpapi import load_or_create_key  # type: ignore
        except ImportError:
            load_or_create_key = None  # type: ignore

    if load_or_create_key is not None:
        for key_dir in _key_dirs():
            try:
                key = load_or_create_key(key_dir)
            except Exception as e:  # 守卫：任何异常都不许炸穿调用方
                logger.warning("读取凭据密钥失败 %s: %s", key_dir, e)
                continue
            if key:
                try:
                    _FERNET_INSTANCE = Fernet(key)
                    return _FERNET_INSTANCE
                except Exception as e:
                    logger.warning("密钥格式不可用 %s: %s", key_dir, e)
                    continue

    logger.warning("所有候选路径均无法提供可用密钥, PII 加密降级 (cryptography 或权限受限)")
    return None


# 模块级单例 (避免每次都重新读密钥)
_FERNET_INSTANCE = None


def get_fernet():
    """公共入口：获取（或惰性创建）用户级 Fernet 实例；不可用时返回 None。

    供 config_manager.SecureStorage（V4.46.1 密钥加密升级）等复用同一把
    用户级密钥，避免多处各存一份钥匙。
    """
    return _fernet()


def _fernet():
    global _FERNET_INSTANCE
    if _FERNET_INSTANCE is None:
        _FERNET_INSTANCE = _get_or_create_fernet_key()
    return _FERNET_INSTANCE


def _is_encrypted_file(path: Path) -> bool:
    """通过文件后缀识别是否已加密: .enc.json"""
    return path.suffix == ".enc.json" or path.name.endswith(".enc.json")


def _encrypt_str(plain: str) -> str:
    """加密字符串 → base64(Fernet ciphertext) 文本"""
    f = _fernet()
    if f is None:
        return plain
    token = f.encrypt(plain.encode("utf-8"))
    return base64.b64encode(token).decode("ascii")


def _decrypt_str(cipher_b64: str) -> str:
    """解密 base64(Fernet ciphertext) → 原文"""
    f = _fernet()
    if f is None:
        return cipher_b64
    try:
        token = base64.b64decode(cipher_b64)
        return f.decrypt(token).decode("utf-8")
    except Exception as e:
        logger.error(f"解密失败: {e}")
        return cipher_b64


def save_secure_json(file_path: str, data: Any) -> bool:
    """
    安全保存 JSON 数据 (自动加密).
    接收: file_path 必须以 .enc.json 结尾
    """
    p = Path(file_path)
    if not _is_encrypted_file(p):
        logger.error(f"save_secure_json 拒绝明文文件: {p}, 必须使用 .enc.json 后缀")
        return False

    try:
        plain = json.dumps(data, ensure_ascii=False, indent=2)
        cipher = _encrypt_str(plain)
        p.parent.mkdir(parents=True, exist_ok=True)
        # 原子写
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(cipher, encoding="utf-8")
        os.replace(tmp, p)
        return True
    except Exception as e:
        logger.error(f"安全保存失败 {p}: {e}")
        return False


def load_secure_json(file_path: str) -> Any:
    """
    安全加载 JSON 数据 (自动解密).
    支持两种后缀:
      - .enc.json  → 自动解密
      - .json      → 原样加载 (兼容旧文件, 记录 deprecation 警告一次)
    """
    p = Path(file_path)
    if not p.exists():
        return None

    try:
        text = p.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"读取文件失败 {p}: {e}")
        return None

    if _is_encrypted_file(p):
        plain = _decrypt_str(text.strip())
    else:
        # 兼容旧明文文件
        plain = text

    try:
        return json.loads(plain)
    except Exception as e:
        logger.error(f"JSON 解析失败 {p}: {e}")
        return None


def upgrade_to_encrypted(file_path: str, delete_plain: bool = True) -> bool:
    """
    升级流程 (一次性):
      1. 读取原明文 JSON
      2. 加密写入 .enc.json
      3. (可选) 删除原明文
    失败回滚: 不删原文件, 业务零影响
    """
    p = Path(file_path)
    if not p.exists():
        logger.warning(f"升级目标不存在, 跳过: {p}")
        return False

    if _is_encrypted_file(p):
        logger.info(f"已是加密文件, 跳过: {p}")
        return True

    enc_path = p.with_name(p.stem + ".enc.json")
    if enc_path.exists():
        logger.info(f"加密副本已存在, 跳过: {enc_path}")
        return True

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"读取明文失败 {p}: {e}")
        return False

    if not save_secure_json(str(enc_path), data):
        logger.error(f"加密写入失败, 已保留原文件: {p}")
        return False

    if delete_plain:
        try:
            p.unlink()
            logger.info(f"P0-C 升级成功: {p.name} → {enc_path.name} (原明文已删)")
        except Exception as e:
            logger.warning(f"删除原明文失败, 请手动删除 {p}: {e}")
    else:
        logger.info(f"P0-C 升级成功: {p.name} → {enc_path.name} (原明文保留)")

    return True


# 一键升级入口 (供 main_qt6.py 启动时调用)
def upgrade_pii_files():
    """升级所有 PII 文件到加密格式 (P0-C 修复)"""
    # 兼容两种调用方式:
    # 1. 以 app/main_qt6.py 为 cwd 启动 -> APP_DIR = app/
    # 2. 以 app/ 为 sys.path[0] 启动 -> 当前文件 = app/core/secure_store.py, parent.parent = app/
    app_root = Path(__file__).resolve().parent.parent
    # 验证: 找到 main_qt6.py 才算 app 根
    if not (app_root / "main_qt6.py").exists():
        # 回退: 用当前工作目录
        app_root = Path.cwd()
    targets = [
        app_root / "config" / "platform_credentials.json",
        app_root / "data" / "session.json",
    ]
    for rel in targets:
        upgrade_to_encrypted(str(rel))


if __name__ == "__main__":
    # 独立运行: python -m core.secure_store
    print("PII 加密升级工具 (P0-C 修复)")
    print("=" * 50)
    upgrade_pii_files()
    print("=" * 50)
    print("完成")
