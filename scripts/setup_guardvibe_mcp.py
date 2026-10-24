#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
setup_guardvibe_mcp.py
======================
将 GuardVibe（AI 生成代码安全审计 MCP）写入 Trae IDE 项目级配置。

目标文件: <root>/.trae/mcp.json
GuardVibe: 456 条安全规则，CVE 检测，提示注入防护，全本地运行。

用法:
    python scripts/setup_guardvibe_mcp.py
"""

import json
import os
import shutil
import subprocess
import sys


def main():
    # 定位项目根目录（脚本位于 <root>/scripts/ 下）
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    trae_dir = os.path.join(root, ".trae")
    mcp_file = os.path.join(trae_dir, "mcp.json")

    # GuardVibe 预设配置（Trae IDE stdio 类型 MCP 标准格式）
    guardvibe_entry = {
        "command": "npx",
        "args": ["-y", "guardvibe"],
        "env": {
            "START_MCP_TIMEOUT_MS": "60000",
            "RUN_MCP_TIMEOUT_MS": "60000",
        },
    }

    # 1. 确保 .trae 目录存在
    os.makedirs(trae_dir, exist_ok=True)

    # 2. 检查 npx 是否可用（GuardVibe 依赖 npx 启动）
    npx_path = shutil.which("npx")
    if npx_path:
        print(f"[OK] 检测到 npx: {npx_path}")
    else:
        print("[警告] 未检测到 npx，GuardVibe 需要 Node.js (v18+) 环境。")
        print("       请安装 Node.js: https://nodejs.org/")

    # 3. 写入或合并 .trae/mcp.json
    if os.path.exists(mcp_file):
        print(f"[INFO] 检测到已有 mcp.json，将合并 guardvibe 配置...")
        try:
            with open(mcp_file, "r", encoding="utf-8") as f:
                config = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[警告] 解析现有 mcp.json 失败: {e}")
            print("       将备份原文件后覆盖写入。")
            shutil.copy2(mcp_file, mcp_file + ".bak")
            print(f"       已备份到: {mcp_file}.bak")
            config = {}

        if not isinstance(config, dict):
            config = {}
        servers = config.setdefault("mcpServers", {})
        if not isinstance(servers, dict):
            servers = {}
            config["mcpServers"] = servers
        servers["guardvibe"] = guardvibe_entry
    else:
        print(f"[INFO] 不存在 mcp.json，将新建。")
        config = {"mcpServers": {"guardvibe": guardvibe_entry}}

    # 4. 写入文件（UTF-8，无 BOM，缩进 2 空格）
    with open(mcp_file, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"[OK] 已写入: {mcp_file}")

    # 5. 输出配置预览
    print("\n=== 配置内容 ===")
    with open(mcp_file, "r", encoding="utf-8") as f:
        print(f.read())

    # 6. 后续启用说明
    print("=== 后续启用步骤 ===")
    print("1. 在 Trae IDE 中: 设置 -> MCP")
    print("2. 打开「启用项目级 MCP」开关（首次需在弹窗中确认）")
    print("3. 确认列表中出现 guardvibe 并处于已启用状态")
    print("4. 首次调用时 npx 会自动下载 guardvibe 包（约 30 秒）")
    print()
    print("=== GuardVibe 能力 ===")
    print("- 456 条安全规则（OWASP Top 10、CVE、提示注入、供应链）")
    print("- 39 个工具（扫描文件、修复建议、SARIF 导出、pre-commit 钩子）")
    print("- 全本地运行，无需 API Key，无需联网账号")
    print("- 支持 Next.js/Supabase/Stripe/Prisma 等 20+ 技术栈")
    print()
    print('[完成] 可在对话中直接说「用 guardvibe 扫描 xxx 文件」即可触发安全审计。')


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[错误] 执行失败: {e}", file=sys.stderr)
        sys.exit(1)
