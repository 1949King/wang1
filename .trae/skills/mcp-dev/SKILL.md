---
name: "mcp-dev"
description: "Model Context Protocol (MCP) 服务器开发专家。用于设计和实现 MCP 服务端、连接 AI 模型到外部工具/API/数据库。当需要创建 MCP server、集成外部数据源到 AI 应用、或理解 MCP 协议标准时调用。"
---

# MCP (Model Context Protocol) 服务器开发技能

## 概述
MCP 是 Anthropic 于 2024年11月推出的 AI 与外部工具连接开放标准，现由 Linux Foundation 的 Agentic AI Foundation 管理。SDK 月下载量 97M+，Claude/ChatGPT/Cursor/Copilot 原生支持。

## 核心架构
```
AI 客户端 (Claude/Cursor) ←→ MCP Client ←→ JSON-RPC 2.0 ←→ MCP Server ←→ 外部工具/API/DB
```

## 三要素
- **Tools**: Agent 可执行的操作 (动作)
- **Resources**: 上下文数据源 (只读)
- **Prompts**: 可复用的提示模板

## MCP Server 快速模板 (Python)
```python
from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationCapabilities
import mcp.server.stdio
import mcp.types as types

server = Server("my-server")

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
        types.Tool(name="my_tool", description="工具描述",
                   inputSchema={"type": "object", "properties": {
                       "param1": {"type": "string", "description": "参数1"}
                   }, "required": ["param1"]})
    ]

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "my_tool":
        result = f"处理结果: {arguments['param1']}"
        return [types.TextContent(type="text", text=result)]
    raise ValueError(f"未知工具: {name}")

async def main():
    async with mcp.server.stdio.stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

## 常用传输方式
- **stdio**: 本地子进程通信 (Claude Desktop/Cursor)
- **Streamable HTTP**: 远程服务器 (生产环境)
- **SSE**: 实时推送 (流式数据)

## 客户端配置示例 (Claude Desktop)
```json
{
  "mcpServers": {
    "my-server": {
      "command": "python",
      "args": ["path/to/server.py"]
    }
  }
}
```

## 资源
- 官方规范: https://spec.modelcontextprotocol.io/
- GitHub: https://github.com/modelcontextprotocol
- 全球已发布 17000+ MCP Server

## 使用场景
- 集成企业数据库/API 到 AI 对话
- 为 AI短剧编辑器 创建 MCP Server 实现自然语言操控视频编辑
- 连接 Puppeteer/Playwright 实现浏览器自动化
- 为 Skill 系统提供标准化外部接口
