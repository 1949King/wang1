# MCP 服务器配置和使用说明

## 配置完成

✅ 已创建 MCP 配置文件: `.trae/settings.json`
✅ 已配置以下 MCP 扩展:
- filesystem: 文件系统操作
- git: Git 版本控制
- puppeteer: 网页自动化
- brave-search: 网络搜索
- memory: 记忆存储
- fetch: 网页内容抓取

## 使用方法

由于系统执行策略限制，我们无法直接安装和运行 MCP 服务器。但您可以通过以下方式使用 MCP：

### 1. 使用 Trae IDE 内置 MCP
Trae IDE 已经内置了 MCP 功能，您可以在 `.trae/settings.json` 中配置 MCP 服务器。

### 2. 手动启动 MCP 服务器
当您需要使用 MCP 时，可以运行：
```bash
# 启动 MCP 服务器
python start_mcp.py
```

### 3. 安装和运行步骤
1. 安装 MCP 服务器：
   ```bash
   npm install -g @modelcontextprotocol/server
   ```

2. 启动服务器：
   ```bash
   mcp-server --config .trae/settings.json
   ```

### 4. 测试 MCP 服务器
服务器启动后，访问：
http://127.0.0.1:8080

### 5. 集成到项目中
在您的 Python 代码中使用 MCP：
```python
from mcp.client import Client

client = Client("http://127.0.0.1:8080")

# 使用 filesystem MCP
result = client.filesystem.read("README.md")

# 使用 git MCP
result = client.git.commit("Update README")

# 使用 puppeteer MCP
result = client.puppeteer.navigate("https://www.kuaishou.com")
```

## 推荐的 MCP 扩展

1. **filesystem** - 用于项目文件管理
2. **puppeteer** - 用于账号登录和数据采集
3. **git** - 用于代码版本控制
4. **fetch** - 用于网页数据采集
5. **memory** - 用于持久化存储

## 注意事项

- MCP 服务器默认运行在 8080 端口
- 确保端口未被其他应用占用
- 首次使用时可能需要安装依赖
- 部分 MCP 扩展可能需要额外的系统依赖
