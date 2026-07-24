---
name: "puppeteer-mcp"
description: "Puppeteer 浏览器自动化 MCP Server。用于让 AI Agent 操控 Chrome/Chromium 浏览器执行网页导航、截图、表单填写、JS 执行等操作。当需要网页采集、自动化测试、平台自动登录发布时调用。"
---

# Puppeteer MCP - 浏览器自动化技能

## 概述
Puppeteer MCP Server 是 MCP 官方参考实现之一，将 Google 的 Puppeteer 无头浏览器自动化库封装为 MCP 服务，让 AI Agent 能够操控真实浏览器。

## 安装
```bash
npx -y @modelcontextprotocol/server-puppeteer
```

## 可用工具 (15+)
| 工具 | 功能 |
|------|------|
| `puppeteer_navigate` | 导航到 URL |
| `puppeteer_screenshot` | 截屏 (整页/元素) |
| `puppeteer_click` | 点击元素 |
| `puppeteer_fill` | 填写输入框 |
| `puppeteer_select` | 选择下拉框 |
| `puppeteer_hover` | 悬停元素 |
| `puppeteer_evaluate` | 执行 JS 代码 |

## Claude Desktop 配置
```json
{
  "mcpServers": {
    "puppeteer": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-puppeteer"]
    }
  }
}
```

## 典型用例：抖音创作者平台自动发布
```
1. puppeteer_navigate("https://creator.douyin.com/")
2. puppeteer_screenshot(name="login") → 查看登录状态
3. puppeteer_fill(selector="input[name=title]", value="短剧标题")
4. puppeteer_click(selector=".upload-btn")
5. puppeteer_fill(selector="input[type=file]", value="/path/to/video.mp4")
```

## 安全注意事项
- 默认沙箱模式，禁止 `--no-sandbox` (除非 Docker 环境)
- 使用 `allowDangerous: false` 防止危险启动参数
- 生产环境建议 Docker 部署

## 高级技巧
- `PUPPETEER_LAUNCH_OPTIONS` 环境变量自定义浏览器行为
- `--remote-debugging-port` 连接已有 Chrome 实例
- 支持 Cookie 管理和会话保持
