from mcp.server import Server
from mcp.extensions import FilesystemExtension, GitExtension, PuppeteerExtension, FetchExtension, MemoryExtension

# 创建服务器实例
server = Server(
    host="127.0.0.1",
    port=8080,
    cors=True
)

# 添加扩展
server.add_extension(FilesystemExtension(
    root_path=".",
    read_only=False,
    allowed_extensions=["py", "json", "txt", "md", "jpg", "png", "mp4", "mp3"]
))

server.add_extension(GitExtension(
    repository_path=".",
    auto_commit=False
))

server.add_extension(PuppeteerExtension(
    headless=True,
    timeout=60000
))

server.add_extension(FetchExtension(
    timeout=30000,
    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
))

server.add_extension(MemoryExtension(
    storage_path=".trae/memory",
    max_items=1000
))

# 启动服务器
print("MCP 服务器正在启动...")
print("访问地址: http://127.0.0.1:8080")
server.run()
