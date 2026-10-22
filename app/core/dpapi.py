# -*- coding: utf-8 -*-
"""dpapi.py — Windows DPAPI 密钥守护（2026-10-23 · 密钥库解耦硬件指纹）

## 为什么要这个模块

`SecureStorage`（`config_manager.py`）与 `secure_store.py` 共用一把 Fernet 钥匙，
此前这把钥匙**来自机器码派生**：`platform.node() + system + machine + cpu_count
+ WMI UUID`，再 PBKDF2。副作用是：

- 改机器名 / 换主板 / BIOS 刷 UUID / 重装系统 ⇒ **已保存的 Key 全部解不开**
- A-14（2026-10-05）追加 UUID 部件那次，旧文件曾整体失效（见 config_manager
  `_legacy_key_candidates` 的注释与刀0 的取证）

本模块把「钥匙从哪来」换成 **纯随机 + DPAPI 守护**：

- **纯随机**：`Fernet.generate_key()`，与任何硬件特征无关
- **DPAPI 守护**：`CryptProtectData` / `CryptUnprotectData`（`CRYPTPROTECT_LOCAL_MACHINE`
  **不启用** ⇒ 绑定当前 Windows 用户账户）。密钥文件离开这台机器、或换用户账户
  都解不开，但**改机器名/换硬件/重装系统后只要还在同一账户下即可继续用**
  （重装系统属换账户场景，需备份 `secret.key.dpapi` 或在应用内重录 Key —— 诚实说明，
  不假装能跨系统迁移）。

## 平台与降级（诚实边界）

| 平台 | 行为 |
|---|---|
| Windows + crypt32 可用 | DPAPI 包裹（`DPAPI1:` 前缀），本期主路径 |
| Windows + crypt32 不可用 | 回退**明文密钥文件** + WARNING（不静默假装安全） |
| 非 Windows | 回退明文密钥文件 + WARNING；未来可接 Keychain / Secret Service |

## 文件格式

```
secret.key.dpapi    b"DPAPI1:" + base64(CryptProtectData(raw_fernet_key))
secret.key          （旧格式，明文 base64 的 Fernet 钥匙；**只读兼容**，读到即迁移后改名 .legacy）
```

调用方只需 `load_or_create_key(key_dir)`，不关心底层是 DPAPI 还是明文。
"""
from __future__ import annotations

import base64
import ctypes
import logging
import os
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Optional

logger = logging.getLogger("AI短剧编辑器.dpapi")

# DPAPI 包裹后的文件前缀；改这里等于改格式，需同步迁移逻辑
DPAPI_MARKER = b"DPAPI1:"

# 密钥文件名
KEY_FILE_DPAPI = "secret.key.dpapi"
KEY_FILE_LEGACY = "secret.key"

# CRYPTPROTECT_UI_FORBIDDEN：绝不让系统弹「允许访问加密数据」对话框
_CRYPTPROTECT_UI_FORBIDDEN = 0x1

_IS_WINDOWS = sys.platform == "win32"


class _DATA_BLOB(ctypes.Structure):
    """Win32 DATA_BLOB（crypt32 的输入/输出缓冲区）。"""

    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _blob_from_bytes(data: bytes) -> tuple:
    """bytes → (DATA_BLOB, 保活缓冲)。缓冲区必须比 BLOB 活得久，故一并返回。"""
    buf = ctypes.create_string_buffer(data, len(data))
    blob = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    return blob, buf


def dpapi_available() -> bool:
    """DPAPI 是否可用（Windows 且 crypt32 可加载）。"""
    if not _IS_WINDOWS:
        return False
    try:
        # getattr 而非裸属性访问：既完成「能否加载」的探测，又不产生无用表达式
        crypt32 = getattr(ctypes.windll, "crypt32", None)
        kernel32 = getattr(ctypes.windll, "kernel32", None)
        return crypt32 is not None and kernel32 is not None
    except (AttributeError, OSError):
        return False


def dpapi_protect(plaintext: bytes) -> Optional[bytes]:
    """用当前用户凭据加密；不可用或失败返回 None（调用方须诚实降级）。"""
    if not dpapi_available():
        return None
    blob_in, buf_in = _blob_from_bytes(plaintext)
    blob_out = _DATA_BLOB()
    try:
        ok = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(blob_in),      # pDataIn
            None,                        # szDataDescr（不写描述，避免泄露线索）
            None,                        # pOptionalEntropy
            None,                        # pvReserved
            None,                        # pPromptStruct
            _CRYPTPROTECT_UI_FORBIDDEN,  # dwFlags（不绑机器，绑用户）
            ctypes.byref(blob_out),      # pDataOut
        )
    except OSError as e:
        logger.warning("DPAPI 加密调用异常: %s", e)
        return None
    finally:
        del buf_in  # 用完即可释放；失败路径也不留引用
    if not ok:
        logger.warning("DPAPI 加密失败（GetLastError=%s）", ctypes.GetLastError())
        return None
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def dpapi_unprotect(ciphertext: bytes) -> Optional[bytes]:
    """用当前用户凭据解密；不可用或失败返回 None。"""
    if not dpapi_available():
        return None
    blob_in, buf_in = _blob_from_bytes(ciphertext)
    blob_out = _DATA_BLOB()
    try:
        ok = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in),
            None,                        # ppszDataDescr
            None,                        # pOptionalEntropy
            None,                        # pvReserved
            None,                        # pPromptStruct
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(blob_out),
        )
    except OSError as e:
        logger.warning("DPAPI 解密调用异常: %s", e)
        return None
    finally:
        del buf_in
    if not ok:
        logger.warning("DPAPI 解密失败（GetLastError=%s）", ctypes.GetLastError())
        return None
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _write_atomic(path: Path, data: bytes) -> bool:
    """原子写（tmp + os.replace）；失败返回 False，不抛。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        return True
    except OSError as e:
        logger.warning("写入密钥文件失败 %s: %s", path, e)
        return False
    finally:
        try:
            tmp_path = path.with_name(path.name + ".tmp")
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError as e:
            # 残留 tmp 不致命，但要留痕（静默吞会让「写失败」变成无解释的怪现象）
            logger.debug("清理临时密钥文件失败（不影响主流程）%s: %s", path, e)


def load_or_create_key(key_dir: Path) -> Optional[bytes]:
    """取「用户级 Fernet 钥匙」：DPAPI 守护的随机钥匙，或明文兜底。

    读取顺序（**只读兼容历史，写入一律新格式**）：
      ① `secret.key.dpapi`（`DPAPI1:` + base64）——本期格式
      ② `secret.key`（历史明文 base64）——读到即迁移成 ①，并把旧文件改名 `.legacy`
      ③ 都不存在 ⇒ 生成新随机钥匙，按①落盘（DPAPI 不可用则落②明文 + WARNING）

    返回 44 字节 base64 的 Fernet 钥匙（bytes）；全程不可用返回 None，
    调用方照旧走它自己的诚实降级（**本函数不抛异常**）。
    """
    key_dir = Path(key_dir)

    # ① 本期格式
    dpapi_path = key_dir / KEY_FILE_DPAPI
    if dpapi_path.exists():
        try:
            raw = dpapi_path.read_bytes()
        except OSError as e:
            logger.warning("读取 %s 失败: %s", dpapi_path, e)
            raw = b""
        if raw.startswith(DPAPI_MARKER):
            plain = dpapi_unprotect(base64.b64decode(raw[len(DPAPI_MARKER):]))
            if plain:
                return plain
            logger.error(
                "密钥库 %s 解不开：DPAPI 绑定的是当前 Windows 用户账户，"
                "换用户/换机器后需重新填写各渠道 Key（或恢复备份）", dpapi_path,
            )
            return None
        # 无标记 ⇒ 被外部改坏，当作不可用（不猜内容）
        logger.error("密钥文件 %s 缺少 %s 标记，拒绝解析", dpapi_path, DPAPI_MARKER.decode())
        return None

    # ② 历史明文（读到即迁移）
    legacy_path = key_dir / KEY_FILE_LEGACY
    if legacy_path.exists():
        try:
            legacy = legacy_path.read_bytes().strip()
        except OSError as e:
            logger.warning("读取历史密钥失败 %s: %s", legacy_path, e)
            legacy = b""
        if legacy:
            logger.info("发现历史明文密钥 %s，迁移为 DPAPI 守护格式", legacy_path)
            _persist_key(key_dir, legacy)
            try:
                legacy_path.rename(legacy_path.with_name(KEY_FILE_LEGACY + ".legacy"))
            except OSError as e:
                logger.debug("历史密钥改名失败（不影响使用）: %s", e)
            return legacy
        logger.warning("历史密钥文件为空，按不存在处理: %s", legacy_path)

    # ③ 全新生成（纯随机，与硬件无关）
    try:
        from cryptography.fernet import Fernet

        key = Fernet.generate_key()
    except ImportError:
        logger.warning("cryptography 不可用，无法生成 Fernet 钥匙")
        return None
    if not _persist_key(key_dir, key):
        logger.error("新密钥落盘失败（%s）；本次会话可用，重启后失效", key_dir)
    return key


def _persist_key(key_dir: Path, key: bytes) -> bool:
    """把钥匙按可用性落盘：优先 DPAPI，否则明文 + WARNING。"""
    if dpapi_available():
        sealed = dpapi_protect(key)
        if sealed:
            payload = DPAPI_MARKER + base64.b64encode(sealed)
            if _write_atomic(Path(key_dir) / KEY_FILE_DPAPI, payload):
                return True
            return False
        logger.warning("DPAPI 包裹失败，回退明文密钥文件")
    else:
        logger.warning(
            "DPAPI 不可用（平台=%s），密钥以**明文**落盘于 %s；"
            "本机账户外不可读，但不具备 DPAPI 的用户绑定强度",
            sys.platform, Path(key_dir) / KEY_FILE_LEGACY,
        )
    return _write_atomic(Path(key_dir) / KEY_FILE_LEGACY, key)
