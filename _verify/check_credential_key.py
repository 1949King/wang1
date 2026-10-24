# -*- coding: utf-8 -*-
"""凭据密钥库守卫（2026-10-23 · 密钥库解耦硬件指纹）

背景：密钥库曾用**机器码派生**的钥匙加密（`platform.node/system/machine/cpu`
+ WMI UUID → PBKDF2）。A-14（2026-10-05）追加 UUID 部件那次，旧库整体失效；
改机器名/换主板同样必挂。现改为「**纯随机钥匙 + DPAPI 守护**」。

断言：
  ① DPAPI 网关：`dpapi_available()` 在 Windows 为真（非 Windows 允许假，如实降级）
  ② 加解密往返：protect→unprotect 恒等；密文**不含明文**
  ③ 钥匙与硬件无关：`load_or_create_key` 生成的钥匙**不依赖**任何机器码输入
     —— 通过「篡改机器码派生结果后仍能读回」的行为反例验证
  ④ 落盘格式：DPAPI 可用时写 `secret.key.dpapi` 且带 `DPAPI1:` 前缀；
     历史明文 `secret.key` 读到即**迁移**并改名 `.legacy`
  ⑤ 写入路由唯一：`SecureStorage._encrypt` **不得再产出 XOR 密文**
     （Fernet 不可用时必须返回空/失败，绝不回退 XOR——否则又造出解不开的库）
  ⑥ 空密文不落盘：`_save_secrets` 收到空字节必须返回 False，磁盘保持不变
  ⑦ 只读兼容仍在：旧 XOR 库**仍能读出**并自动迁移为 `sgv2:`
  ⑧ 无第二套密钥派生：全库不得再出现「机器码 → PBKDF2 → Fernet 钥匙」的写入用法

用法（项目根执行）：python _verify/check_credential_key.py
退出码 0 = 通过；1 = 有漂移。
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 临时目录钉到项目内（沙箱拦系统 Temp 之外的写盘，同 check_media_perception 先例）
try:
    _SG_TMP = os.path.join(ROOT, ".workbuddy", "tmp")
    os.makedirs(_SG_TMP, exist_ok=True)
    tempfile.tempdir = _SG_TMP
except OSError:
    pass

problems = []


def _fail(msg: str) -> None:
    problems.append(msg)


# ── ① DPAPI 网关 ──────────────────────────────────────────────────────

def check_gateway() -> None:
    from app.core import dpapi

    available = dpapi.dpapi_available()
    if sys.platform == "win32" and not available:
        _fail("① Windows 下 DPAPI 不可用（crypt32 加载失败）：密钥将退化为明文落盘")
    if not hasattr(dpapi, "DPAPI_MARKER") or dpapi.DPAPI_MARKER != b"DPAPI1:":
        _fail("① DPAPI_MARKER 漂移（改了格式需同步迁移逻辑）")


# ── ② 加解密往返 ──────────────────────────────────────────────────────

def check_roundtrip() -> None:
    from app.core import dpapi

    if not dpapi.dpapi_available():
        return
    secret = b"fernet-key-44bytes-abcdefghijklmnopqrstuvwxyz="
    sealed = dpapi.dpapi_protect(secret)
    if not sealed:
        _fail("② protect 返回空（DPAPI 加密失败）")
        return
    if secret in sealed:
        _fail("② 密文里出现明文（DPAPI 未真正加密）")
    back = dpapi.dpapi_unprotect(sealed)
    if back != secret:
        _fail(f"② 解密往返不一致：{back!r}")
    # 垃圾输入不抛、返回 None
    if dpapi.dpapi_unprotect(b"not-a-dpapi-blob") is not None:
        _fail("② 非法密文竟被解出内容（应返回 None）")


# ── ③ 钥匙与硬件无关 ──────────────────────────────────────────────────

def check_key_independent_of_hardware() -> None:
    from app.core import config_manager, secure_store

    root = Path(tempfile.mkdtemp(prefix="sg_key_hw_"))
    try:
        key_dir = root / "keys"
        key_dir.mkdir(parents=True, exist_ok=True)

        from app.core.dpapi import load_or_create_key

        key1 = load_or_create_key(key_dir)
        if not key1:
            _fail("③ 无法生成钥匙（DPAPI 与明文兜底都失败）")
            return
        key2 = load_or_create_key(key_dir)
        if key1 != key2:
            _fail("③ 同一目录两次读取得到不同钥匙（落盘/读取不一致）")

        # 行为反例：把「机器码派生」彻底篡改后，凭据库仍须可读
        store_path = root / "secrets.enc"
        original_instance = config_manager.SecureStorage._instance
        original_path = config_manager.SecureStorage._get_storage_path
        original_fernet = config_manager.SecureStorage._get_fernet
        original_dirs = secure_store._key_dirs
        original_cached = secure_store._FERNET_INSTANCE
        try:
            config_manager.SecureStorage._instance = None
            config_manager.SecureStorage._get_storage_path = lambda self: store_path
            config_manager.SecureStorage._get_fernet = lambda self: secure_store.get_fernet()
            secure_store._key_dirs = lambda: [key_dir]
            secure_store._FERNET_INSTANCE = None

            st = config_manager.SecureStorage()
            if not st.set("probe", "value-1"):
                _fail("③ 保存失败（密钥目录不可写）")
                return
            if not store_path.read_bytes().startswith(b"sgv2:"):
                _fail("③ 新库未写成 sgv2 格式")

            # 篡改机器码派生（模拟换机器/改 UUID），并**清掉会话内所有缓存**
            # —— 不清 `_FERNET_INSTANCE` / `_fernet` 就等于还在用旧钥匙测旧钥匙，
            #   本守卫首轮实测因此漏过「钥匙重新绑机器码」的反例。
            config_manager.SecureStorage._instance = None
            secure_store._FERNET_INSTANCE = None
            original_derive = config_manager.SecureStorage._derive_key
            config_manager.SecureStorage._derive_key = (
                lambda self: hashlib.sha256(b"changed-machine-identity").digest()
            )
            try:
                again = config_manager.SecureStorage()
                if again.get("probe") != "value-1":
                    _fail("③ 机器码变化后读不出凭据（钥匙仍与硬件指纹耦合）")
            finally:
                config_manager.SecureStorage._derive_key = original_derive
        finally:
            config_manager.SecureStorage._instance = original_instance
            config_manager.SecureStorage._get_storage_path = original_path
            config_manager.SecureStorage._get_fernet = original_fernet
            secure_store._key_dirs = original_dirs
            secure_store._FERNET_INSTANCE = original_cached
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ── ④ 落盘格式与历史密钥迁移 ──────────────────────────────────────────

def check_key_file_format() -> None:
    from app.core import dpapi

    root = Path(tempfile.mkdtemp(prefix="sg_key_fmt_"))
    try:
        # 全新
        fresh = root / "fresh"
        fresh.mkdir()
        k = dpapi.load_or_create_key(fresh)
        if not k:
            _fail("④ 全新目录未生成钥匙")
            return
        if dpapi.dpapi_available():
            target = fresh / dpapi.KEY_FILE_DPAPI
            if not target.exists():
                _fail("④ DPAPI 可用却未写 secret.key.dpapi")
            elif not target.read_bytes().startswith(dpapi.DPAPI_MARKER):
                _fail("④ 密钥文件缺少 DPAPI1: 前缀")
            elif k in target.read_bytes():
                _fail("④ 密钥文件里出现明文钥匙（DPAPI 未生效）")

        # 历史明文迁移
        legacy = root / "legacy"
        legacy.mkdir()
        legacy_key = b"legacy-plaintext-fernet-key-000000000000000="
        (legacy / dpapi.KEY_FILE_LEGACY).write_bytes(legacy_key)
        got = dpapi.load_or_create_key(legacy)
        if got != legacy_key:
            _fail("④ 历史明文钥匙未被读回（旧安装会丢密钥）")
        if dpapi.dpapi_available() and not (legacy / dpapi.KEY_FILE_DPAPI).exists():
            _fail("④ 历史明文钥匙未迁移为 DPAPI 格式")
        if (legacy / dpapi.KEY_FILE_LEGACY).exists():
            _fail("④ 历史明文钥匙未改名 .legacy（明文长期留盘）")
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ── ⑤ 写入路由唯一（不得回退 XOR） ───────────────────────────────────

def check_no_xor_write() -> None:
    """**行为**判定而非关键词判定：真跑一次 `_encrypt`，密文必须带 sgv2 标记。

    关键词扫描（找 `token_bytes` / `cipher.append`）不可靠——注入一个
    `base64.b64encode(b'0'*16 + ...)` 就能绕过（本守卫首轮实测漏过）。
    故改为黑盒断言：只要 Fernet 可用，`_encrypt` 的输出**必须**以 `_ENC_MARKER`
    开头；Fernet 不可用时**必须**是空（诚实失败），而不是任何别的字节。
    """
    from app.core import config_manager

    root = Path(tempfile.mkdtemp(prefix="sg_key_xor_"))
    try:
        store_path = root / "secrets.enc"
        original_instance = config_manager.SecureStorage._instance
        original_path = config_manager.SecureStorage._get_storage_path
        try:
            config_manager.SecureStorage._instance = None
            config_manager.SecureStorage._get_storage_path = lambda self: store_path
            st = config_manager.SecureStorage()

            sample = json.dumps({"k": "v"})
            if st._get_fernet() is not None:
                out = st._encrypt(sample)
                if not isinstance(out, (bytes, bytearray)) or not out:
                    _fail("⑤ Fernet 可用时 _encrypt 返回空（写入路径断裂）")
                elif not out.startswith(config_manager.SecureStorage._ENC_MARKER):
                    _fail(f"⑤ _encrypt 产出的不是 sgv2 密文（首 6 字节 {bytes(out[:6])!r}）"
                          "—— XOR 回退被放回，会再造解不开的库")
                elif sample.encode() in out:
                    _fail("⑤ 密文里出现明文（加密未生效）")

            # Fernet 不可用时必须诚实失败（空），不得回退任何其它格式
            original_get_fernet = config_manager.SecureStorage._get_fernet
            try:
                config_manager.SecureStorage._get_fernet = lambda self: None
                degraded = st._encrypt(sample)
                if degraded != b"":
                    _fail(f"⑤ Fernet 不可用时 _encrypt 未诚实失败，而是产出 "
                          f"{len(degraded)} 字节（疑似 XOR 回退）")
            finally:
                config_manager.SecureStorage._get_fernet = original_get_fernet
        finally:
            config_manager.SecureStorage._instance = original_instance
            config_manager.SecureStorage._get_storage_path = original_path
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ── ⑥ 空密文不落盘 ────────────────────────────────────────────────────

def check_empty_cipher_not_persisted() -> None:
    from app.core import config_manager

    root = Path(tempfile.mkdtemp(prefix="sg_key_empty_"))
    try:
        store_path = root / "secrets.enc"
        original_instance = config_manager.SecureStorage._instance
        original_path = config_manager.SecureStorage._get_storage_path
        try:
            config_manager.SecureStorage._instance = None
            config_manager.SecureStorage._get_storage_path = lambda self: store_path
            st = config_manager.SecureStorage()
            st._secrets = {"k": "v"}
            st._encrypt = lambda data: b""  # 模拟 Fernet 不可用
            if st._save_secrets() is not False:
                _fail("⑥ 空密文竟被当作保存成功（会落 0 字节库）")
            if store_path.exists() and store_path.stat().st_size == 0:
                _fail("⑥ 空密文把 0 字节文件写到了磁盘")
        finally:
            config_manager.SecureStorage._instance = original_instance
            config_manager.SecureStorage._get_storage_path = original_path
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ── ⑦ 旧 XOR 只读兼容仍在 ─────────────────────────────────────────────

def check_legacy_read_still_works() -> None:
    from app.core import config_manager

    root = Path(tempfile.mkdtemp(prefix="sg_key_legacy_"))
    try:
        store_path = root / "secrets.enc"
        # 造「A-14 之前」的旧 XOR 库：机器码不含 UUID
        base = [platform.node(), platform.system(), platform.machine(),
                str(os.cpu_count() or 0)]
        legacy_mid = hashlib.sha256('|'.join(base).encode()).hexdigest()[:32]
        legacy_key = hashlib.pbkdf2_hmac(
            'sha256', legacy_mid.encode(), b'ai_drama_editor_salt_v1', 100000, dklen=32)
        payload = b'{"openai_api_key": "sk-legacy-sentinel"}'
        cipher = bytes(b ^ legacy_key[i % len(legacy_key)] for i, b in enumerate(payload))
        store_path.write_bytes(base64.b64encode(b"\x00" * 16 + cipher))

        original_instance = config_manager.SecureStorage._instance
        original_path = config_manager.SecureStorage._get_storage_path
        try:
            config_manager.SecureStorage._instance = None
            config_manager.SecureStorage._get_storage_path = lambda self: store_path
            st = config_manager.SecureStorage()
            if st.get("openai_api_key") != "sk-legacy-sentinel":
                _fail("⑦ 旧 XOR 库读不出来（只读兼容被破坏，老用户会丢 Key）")
            if st._get_fernet() is not None and not store_path.read_bytes().startswith(b"sgv2:"):
                _fail("⑦ 旧库读出后未自动迁移为 sgv2")
            if list(root.glob("secrets.corrupt-*.enc")):
                _fail("⑦ 能读出的旧库被误隔离成 .corrupt（误判为损坏）")
        finally:
            config_manager.SecureStorage._instance = original_instance
            config_manager.SecureStorage._get_storage_path = original_path
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ── ⑧ 无第二套钥匙派生写入 ────────────────────────────────────────────

def check_single_key_derivation() -> None:
    """写入路径的钥匙来源必须是 DPAPI 提供的 Fernet，**不得**再取自机器码。

    为什么需要静态检查：行为测试（③）为了控制变量会把 `_get_fernet`
    整个替换掉，于是「把钥匙改回机器码派生」这种注入根本不会被执行到
    —— 本守卫首轮实测因此漏过。故这里直接读 `_get_fernet` 函数体，
    断言其中不出现机器码钥匙引用。
    """
    path = os.path.join(ROOT, "app", "core", "config_manager.py")
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    start = src.find("def _get_fernet(self)")
    if start < 0:
        _fail("⑧ 找不到 _get_fernet（被改名？需同步本守卫）")
        return
    end = src.find("def _get_storage_path", start)
    body = src[start:end] if end > start else src[start:start + 2000]
    for token in ("self._key", "_derive_key", "_legacy_key_candidates"):
        if token in body:
            _fail(f"⑧ `_get_fernet` 引用了机器码钥匙 `{token}`"
                  "（写入路径的钥匙必须来自 DPAPI 守护的随机密钥）")
    if "get_fernet" not in body:
        _fail("⑧ `_get_fernet` 不再委托 secure_store.get_fernet（钥匙来源被换掉）")

    # _encrypt 也不得引用机器码钥匙
    enc_start = src.find("def _encrypt(self, data: str)")
    enc_end = src.find("def _decrypt", enc_start)
    enc_body = src[enc_start:enc_end] if enc_end > enc_start else ""
    for token in ("_derive_key", "_legacy_key_candidates", "self._key"):
        if token in enc_body:
            _fail(f"⑧ `_encrypt` 引用机器码钥匙 `{token}`（写入须只用 DPAPI 提供的 Fernet）")


# ── ⑨ 落盘失败必须拒绝，不许返回临时钥匙 ─────────────────────────────

def check_fail_closed_on_persist_failure() -> None:
    """落盘失败时**不得**返回临时钥匙。

    为什么：调用方会拿这把钥匙加密并落盘密钥库；重启后钥匙已不存在 ⇒
    用户本次保存的所有 Key 一律读不出（静默数据丢失）。这条是 2026-10-23
    实测踩到的真实隐患（启动日志里 `secret.key.dpapi` 写入 Permission denied，
    而代码当时仍返回了新钥匙）。
    """
    import io

    src = io.open(os.path.join(ROOT, "app", "core", "dpapi.py"),
                  encoding="utf-8").read()
    start = src.find("def load_or_create_key")
    body = src[start:] if start >= 0 else ""
    persist_at = body.find("if not _persist_key(")
    if persist_at < 0:
        _fail("⑨ 找不到「落盘失败」分支（防线被删）")
        return
    tail = body[persist_at:]
    # 该分支必须在返回 None 之前，不能顺着往下 `return key`
    branch = tail[:tail.find("return key")] if "return key" in tail else tail
    if "return None" not in branch:
        _fail("⑨ 落盘失败时未返回 None（会给出临时钥匙 ⇒ 用户存了 Key 下次读不出）")
    if "本次会话可用" in body:
        _fail("⑨ 仍保留「本次会话可用，重启后失效」的旧说法（那是数据丢失陷阱）")


def main() -> int:
    check_gateway()
    check_roundtrip()
    check_key_independent_of_hardware()
    check_key_file_format()
    check_no_xor_write()
    check_empty_cipher_not_persisted()
    check_legacy_read_still_works()
    check_single_key_derivation()
    check_fail_closed_on_persist_failure()
    if problems:
        for p in problems:
            print(f"FAIL  {p}")
        return 1
    print("PASS  凭据密钥库：DPAPI可用/往返恒等/钥匙与硬件解耦/DPAPI1落盘+旧键迁移/"
          "唯一写入路由(禁XOR)/空密文不落盘/旧库只读兼容/无第二套派生/"
          "落盘失败拒用临时钥匙")
    return 0


if __name__ == "__main__":
    sys.exit(main())
