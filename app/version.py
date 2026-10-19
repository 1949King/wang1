__version__ = "4.46.1"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 46,
    "patch": 1,
    "codename": "安全底座刀：密钥 Fernet · CORS 收紧 · 文件流式 Range",
    "release_date": "2026-10-20",
    "description": (
        "V4.46.1：安全底座三刀（缺陷清单 P1 #4/#5/#6，全在非冻结区，无需解冻）。\n"
        "\n【① 密钥存储升级】config_manager.SecureStorage 的自研 XOR（nonce 生成但不\n"
        "参与密钥流）替换为 Fernet（AES-128-CBC+HMAC，复用 secure_store.py 用户级\n"
        "secret.key，与既有 PII 加密同一把钥匙）；新文件带 `sgv2:` 标记；旧 XOR 文件\n"
        "读出成功后透明迁移；解密失败不再静默置空——损坏文件改名 .corrupt-<ts> 保留\n"
        "并 ERROR 级报错（旧行为=机器指纹变化后用户密钥凭空消失且无提示）。\n"
        "cryptography 缺失时回退旧 XOR（如实 warning，不假装更强）。\n"
        "\n【② CORS 收紧】canvas_server._cors 不再 Access-Control-Allow-Origin: *。\n"
        "本机桥暴露角色库/时间线/收件箱文件，`*` 意味着浏览器里任意恶意网页可带 fetch\n"
        "读走本地数据。改为只放行本机 Origin（127.0.0.1|localhost|::1 任意端口、\n"
        "tauri.localhost、127.0.0/8 全段）；陌生 Origin 不写 ACAO；无 Origin 照旧。\n"
        "判定下沉纯函数 cors_allow_origin 可单测；真桥实测 evil→无 ACAO / 本机→回显。\n"
        "\n【③ 文件流式化】/inbox_file 与 /editor_file 原先整文件读进内存（生成 mp4 常\n"
        "50~500MB ⇒ 一次预览吃满内存 + <video> 无法 seek）。新增 canvas_http_file.serve_file：\n"
        "1MB 分块拷贝 + 单段 Range（206/416；多段不支持降级整发）；真桥集成验证全过。\n"
        "\n【附带修复】test_config.TestSecureStorage 原实现把假 Key 写进真实 %APPDATA%\n"
        "密钥库（污染+覆盖真密钥），改为 tmp_path 重定向。\n"
        "\n【验证】run_all_checks 98 项全绿；pytest 1,789 passed（+15：加密迁移/隔离/Range/CORS）；\n"
        "frozen_zone_guard 107 锁完整（本刀零冻结区）；ruff 零违规。本机存量 secrets.enc 系\n"
        "机器指纹变化的不可解残留（旧代码同样返回空），现在如实报错+隔离，不丢可用数据。\n"
        "\n【上一版 V4.46.0『代码成片节点』见 docs/CHANGELOG.md。】"
    ),
}
