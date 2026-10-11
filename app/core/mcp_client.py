"""
MCP 客户端管理器 (McpClientManager)
===================================
基于 JSON-RPC 2.0 协议的 MCP 客户端实现，
支持 stdio（本地进程）和 SSE（远程HTTP）两种传输方式。

核心功能:
    - 连接/断开 MCP Server
    - 获取可用工具列表
    - 调用远程工具
    - Blender MCP 预设配置

协议规范:
    - JSON-RPC 2.0
    - MCP (Model Context Protocol)
    - 支持 tools/list, tools/call, initialize 等方法

使用示例:
    from app.core.mcp_client import McpClientManager

    manager = McpClientManager()

    # 连接 Blender MCP (stdio)
    config = {
        "type": "stdio",
        "command": "uvx",
        "args": ["blender-mcp"],
        "name": "Blender MCP"
    }
    manager.connect(config)

    # 列出工具
    tools = manager.list_tools()
    for tool in tools:
        print(tool['name'], tool['description'])

    # 调用工具
    result = manager.call_tool("create_cube", {"size": 2.0})

    # 断开连接
    manager.disconnect()
"""

import json
import subprocess
import threading
import time
import logging
import os
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger("AI短剧编辑器.mcp_client")


class McpTransportType(str, Enum):
    """MCP 传输类型"""
    STDIO = "stdio"     # 标准输入/输出（本地进程）
    SSE = "sse"         # Server-Sent Events（远程HTTP）


class McpConnectionState(str, Enum):
    """MCP 连接状态"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class McpToolInfo:
    """MCP 工具信息"""
    name: str
    description: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    server_name: str = ""


def _sdk_available() -> bool:
    """官方 ``mcp`` 包是否可用（惰性探测，不硬依赖）。"""
    try:
        from app.core import mcp_sdk_backend

        return mcp_sdk_backend.available()
    except Exception:
        return False


class McpClientManager:
    """
    MCP 客户端管理器

    支持连接多个 MCP Server，统一管理工具调用。
    """

    def __init__(self):
        self._state = McpConnectionState.DISCONNECTED
        self._last_error: Optional[str] = None
        self._process: Optional[subprocess.Popen] = None
        self._session_id: Optional[str] = None
        self._message_id = 0
        self._pending_requests: Dict[int, Dict] = {}
        self._lock = threading.Lock()
        self._tools: List[McpToolInfo] = []
        self._server_name = ""
        #: 实际使用的后端："native"（手写 JSON-RPC） / "sdk"（官方 mcp 包）
        self._backend = "native"
        self._sdk: Optional[Any] = None
        #: auto 模式下 SDK 失败时保留的诊断信息
        self._sdk_soft_error: Optional[str] = None

    @property
    def state(self) -> McpConnectionState:
        """获取连接状态"""
        return self._state

    @property
    def backend(self) -> str:
        """当前实际使用的后端（native / sdk）。"""
        return self._backend

    @property
    def is_connected(self) -> bool:
        """是否已连接"""
        return self._state == McpConnectionState.CONNECTED

    @property
    def last_error(self) -> Optional[str]:
        """获取最后错误"""
        return self._last_error

    @property
    def tools(self) -> List[McpToolInfo]:
        """获取已加载的工具列表"""
        return self._tools.copy()

    def connect(self, config: Dict[str, Any]) -> bool:
        """
        连接 MCP Server

        Args:
            config: 连接配置
                - type: 传输类型 ("stdio" 或 "sse")
                - command: stdio 模式下的命令
                - args: stdio 模式下的参数
                - url: SSE 模式下的 URL
                - name: 服务器名称
                - backend: 后端选择 "auto"(默认) / "native" / "sdk"
                  auto = 装了官方 ``mcp`` 包就用它，否则回退手写实现

        Returns:
            是否连接成功
        """
        transport_type = config.get("type", "stdio")
        self._server_name = config.get("name", "Unknown MCP")

        self._state = McpConnectionState.CONNECTING
        self._last_error = None

        # 后端选择：native（手写） / sdk（官方 mcp 包） / auto（有 SDK 就用）
        pref = str(config.get("backend") or "auto").strip().lower()
        sdk_ok = _sdk_available()
        if pref == "native":
            use_sdk = False
        elif pref == "sdk":
            if not sdk_ok:
                # 显式要 SDK 却没装：诚实失败，绝不静默降级
                self._backend = "sdk"
                self._last_error = "指定 backend=sdk，但未安装官方 MCP SDK（pip install mcp）"
                self._state = McpConnectionState.ERROR
                return False
            use_sdk = True
        else:  # auto
            use_sdk = sdk_ok

        try:
            if use_sdk:
                self._backend = "sdk"
                success = self._connect_sdk(config)
                if not success and pref == "auto":
                    # auto 模式下 SDK 失败 → 回退手写实现（保留 SDK 报错供诊断）
                    logger.warning("MCP 官方 SDK 连接失败，回退手写实现: %s", self._last_error)
                    self._sdk_soft_error = self._last_error
                    self._sdk = None
                    self._backend = "native"
                    success = self._connect_native(transport_type, config)
            else:
                self._backend = "native"
                success = self._connect_native(transport_type, config)

            if success:
                self._state = McpConnectionState.CONNECTED
                # 获取工具列表
                self._fetch_tools()
            else:
                self._state = McpConnectionState.ERROR

            return success
        except Exception as e:
            self._last_error = str(e)
            self._state = McpConnectionState.ERROR
            logger.error(f"连接 MCP Server 失败: {e}")
            return False

    def _connect_native(self, transport_type: str, config: Dict[str, Any]) -> bool:
        """原手写 JSON-RPC 实现。"""
        if transport_type == McpTransportType.STDIO:
            return self._connect_stdio(config)
        if transport_type == McpTransportType.SSE:
            return self._connect_sse(config)
        self._last_error = f"不支持的传输类型: {transport_type}"
        return False

    def _connect_sdk(self, config: Dict[str, Any]) -> bool:
        """官方 mcp SDK 后端（后台线程跑 asyncio）。"""
        try:
            from app.core.mcp_sdk_backend import McpSdkSession
        except Exception as e:
            self._last_error = f"加载 MCP SDK 后端失败: {e}"
            return False
        sdk = McpSdkSession()
        ok = sdk.open(config)
        if not ok:
            self._last_error = sdk.error or "MCP SDK 连接失败"
            try:
                sdk.close()
            except Exception:
                logger.debug("SDK 连接失败后清理会话异常", exc_info=True)
            return False
        self._sdk = sdk
        self._session_id = sdk.session_id
        logger.info("MCP 已连接（官方 SDK 后端）: %s", self._server_name)
        return True

    def disconnect(self):
        """断开连接"""
        try:
            # 官方 SDK 后端：关闭 asyncio 会话与传输
            if self._sdk is not None:
                try:
                    self._sdk.close()
                except Exception as e:
                    logger.debug("关闭 MCP SDK 会话失败: %s", e)
                self._sdk = None

            if self._process:
                # 发送 shutdown 请求
                self._send_request("shutdown", {})
                time.sleep(0.5)

                # 终止进程
                self._process.terminate()
                try:
                    self._process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait()

                self._process = None

            self._state = McpConnectionState.DISCONNECTED
            self._session_id = None
            self._tools = []
            self._backend = "native"
            logger.info(f"已断开 MCP Server: {self._server_name}")
        except Exception as e:
            logger.error(f"断开连接失败: {e}")

    def list_tools(self) -> List[Dict[str, Any]]:
        """
        列出可用工具

        Returns:
            工具列表 [{name, description, parameters}, ...]
        """
        if not self.is_connected:
            return []

        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
                "server_name": tool.server_name,
            }
            for tool in self._tools
        ]

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """
        调用 MCP 工具

        Args:
            tool_name: 工具名称
            arguments: 工具参数

        Returns:
            工具执行结果
        """
        if not self.is_connected:
            self._last_error = "未连接 MCP Server"
            return None

        try:
            # 官方 SDK 后端：直接交给 SDK（它自己管理会话与分页）
            if self._backend == "sdk" and self._sdk is not None:
                result = self._sdk.call_tool(tool_name, arguments or {})
                if result is None:
                    self._last_error = self._sdk.error or f"工具调用无返回: {tool_name}"
                return result

            # 查找工具
            tool = next((t for t in self._tools if t.name == tool_name), None)
            if not tool:
                self._last_error = f"工具不存在: {tool_name}"
                return None

            # 发送调用请求
            result = self._send_request("tools/call", {
                "name": tool_name,
                "arguments": arguments,
            })

            return result
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"调用工具失败 {tool_name}: {e}")
            return None

    def _connect_stdio(self, config: Dict[str, Any]) -> bool:
        """通过 stdio 连接 MCP Server"""
        command = config.get("command")
        args = config.get("args", [])
        # cwd 支持（外部 MCP 的 .mcp.json 通常带 cwd 字段指定 server 工作目录）
        cwd = config.get("cwd")

        if not command:
            self._last_error = "未指定命令"
            return False

        try:
            # 启动 MCP Server 进程
            cmd_args = [command] + args
            logger.info(f"启动 MCP Server: {' '.join(cmd_args)} (cwd={cwd})")

            self._process = subprocess.Popen(
                cmd_args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                cwd=cwd if cwd else None,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            # 发送 initialize 请求
            init_result = self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "拾光剪影",
                    "version": "1.0.0"
                }
            })

            if init_result is not None:
                self._session_id = init_result.get("sessionId")
                logger.info(f"MCP Server 已初始化: {self._server_name}")
                return True
            else:
                self._last_error = "初始化失败"
                self.disconnect()
                return False
        except FileNotFoundError:
            self._last_error = f"命令不存在: {command}"
            return False
        except Exception as e:
            self._last_error = str(e)
            return False

    def _connect_sse(self, config: Dict[str, Any]) -> bool:
        """通过 SSE 连接 MCP Server (简化实现)"""
        url = config.get("url")
        if not url:
            self._last_error = "未指定 URL"
            return False

        try:
            # 发送 initialize 请求（HTTP POST）
            import requests
            response = requests.post(
                f"{url}/initialize",
                json={
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "拾光剪影",
                        "version": "1.0.0"
                    }
                },
                timeout=10,
                headers={"Content-Type": "application/json"}
            )

            if response.status_code == 200:
                result = response.json()
                self._session_id = result.get("sessionId")
                logger.info(f"MCP Server 已连接: {self._server_name}")
                return True
            else:
                self._last_error = f"HTTP {response.status_code}"
                return False
        except ImportError:
            self._last_error = "未安装 requests 库"
            return False
        except Exception as e:
            self._last_error = str(e)
            return False

    def _fetch_tools(self):
        """获取远程工具列表"""
        try:
            # 官方 SDK 后端：连接时已抓过，直接用
            if self._backend == "sdk" and self._sdk is not None:
                self._tools = [
                    McpToolInfo(
                        name=str(t.get("name", "")),
                        description=str(t.get("description", "") or ""),
                        parameters=t.get("parameters", {}) or {},
                        server_name=self._server_name,
                    )
                    for t in (self._sdk.list_tools() or [])
                    if t.get("name")
                ]
                logger.info(
                    f"已加载 {len(self._tools)} 个工具（官方 SDK 后端）: {self._server_name}"
                )
                return

            result = self._send_request("tools/list", {})
            if result and isinstance(result, dict):
                tools_data = result.get("tools", [])
                self._tools = [
                    McpToolInfo(
                        name=tool["name"],
                        description=tool.get("description", ""),
                        parameters=tool.get("inputSchema", {}),
                        server_name=self._server_name,
                    )
                    for tool in tools_data
                ]
                logger.info(f"已加载 {len(self._tools)} 个工具: {self._server_name}")
        except Exception as e:
            logger.error(f"获取工具列表失败: {e}")

    def _send_request(self, method: str, params: Dict[str, Any]) -> Optional[Any]:
        """
        发送 JSON-RPC 请求

        Args:
            method: 方法名
            params: 参数

        Returns:
            响应结果
        """
        with self._lock:
            self._message_id += 1
            message_id = self._message_id

            # 构造 JSON-RPC 请求
            request = {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
                "id": message_id,
            }

            if self._process and self._process.stdin:
                try:
                    # 发送请求
                    request_line = json.dumps(request) + "\n"
                    self._process.stdin.write(request_line)
                    self._process.stdin.flush()

                    # 使用 select 等待响应，设置 30 秒超时
                    import select
                    import sys
                    import os

                    stdout_fd = self._process.stdout.fileno()
                    ready, _, _ = select.select([stdout_fd], [], [], 30.0)

                    if ready:
                        response_line = self._process.stdout.readline()
                        if response_line:
                            response = json.loads(response_line.strip())

                            # 检查错误
                            if "error" in response:
                                self._last_error = response["error"].get("message", "未知错误")
                                return None

                            # 返回结果
                            return response.get("result")
                        else:
                            self._last_error = "读取响应为空"
                            return None
                    else:
                        self._last_error = "请求超时 (30秒)"
                        return None
                except ImportError:
                    # Windows 上 select 不支持管道，使用 threading.Timer 作为回退
                    import threading
                    import queue

                    result_queue = queue.Queue()

                    def read_response():
                        try:
                            line = self._process.stdout.readline()
                            result_queue.put(line if line else "")
                        except Exception as e:
                            result_queue.put(None)

                    # 在另一个线程中读取
                    read_thread = threading.Thread(target=read_response, daemon=True)
                    read_thread.start()

                    # 等待最多 30 秒
                    try:
                        response_line = result_queue.get(timeout=30)
                        if response_line and response_line.strip():
                            response = json.loads(response_line.strip())
                            if "error" in response:
                                self._last_error = response["error"].get("message", "未知错误")
                                return None
                            return response.get("result")
                        else:
                            self._last_error = "读取响应为空"
                            return None
                    except queue.Empty:
                        self._last_error = "请求超时 (30秒)"
                        return None
                    except json.JSONDecodeError as e:
                        self._last_error = f"JSON 解析失败: {e}"
                        return None
                    except Exception as e:
                        self._last_error = str(e)
                        return None
            else:
                self._last_error = "进程未启动"
                return None


# ═══════════════════════════════════════════════════════════════
# 预设 MCP Server 配置
# ═══════════════════════════════════════════════════════════════

# Blender MCP 预设配置
BLENDER_MCP_CONFIG = {
    "type": "stdio",
    "name": "Blender MCP",
    "description": "Blender 3D 建模与渲染 MCP 服务",
    "command": "uvx",
    "args": ["blender-mcp"],
    "category": "3D建模",
    "icon": "🎨",
}

# 其他常见 MCP 预设配置
MCP_PRESETS = {
    "blender": BLENDER_MCP_CONFIG,
    "filesystem": {
        "type": "stdio",
        "name": "Filesystem MCP",
        "description": "文件系统操作 MCP 服务",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "."],
        "category": "系统工具",
        "icon": "📁",
    },
    "github": {
        "type": "stdio",
        "name": "GitHub MCP",
        "description": "GitHub API 操作 MCP 服务",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "category": "开发工具",
        "icon": "🐙",
    },
    "weather": {
        "type": "stdio",
        "name": "Weather MCP",
        "description": "天气查询 MCP 服务",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-weather"],
        "category": "实用工具",
        "icon": "🌤️",
    },
    "guardvibe": {
        "type": "stdio",
        "name": "GuardVibe MCP",
        "description": "AI 生成代码安全审计 MCP 服务（456 条安全规则，CVE 检测，提示注入防护）",
        "command": "npx",
        "args": ["-y", "guardvibe"],
        "category": "安全防护",
        "icon": "🛡️",
    },
}


def get_mcp_preset(preset_id: str) -> Optional[Dict[str, Any]]:
    """获取 MCP 预设配置"""
    return MCP_PRESETS.get(preset_id)


def list_mcp_presets() -> List[Dict[str, Any]]:
    """列出所有 MCP 预设"""
    return [
        {
            "id": preset_id,
            **config
        }
        for preset_id, config in MCP_PRESETS.items()
    ]


# ═══════════════════════════════════════════════════════════════
# 外部 MCP 配置自动发现（扫描 app/skills/external/**/*.mcp.json）
# ═══════════════════════════════════════════════════════════════
# 设计目标：让 videocut-skills 等外部 MCP 配置被自动发现并展示，
# 用户在拓展中心面板一键连接，无需手动填写 command/args/cwd。
# 幂等：每次调用都重新扫描（外部 .mcp.json 可能增删），无状态。
# 健壮：单个 .mcp.json 解析失败不影响其他配置发现。


def _resolve_cwd(cwd_field: str, mcp_json_path: Path) -> str:
    """将 .mcp.json 中的 cwd 字段解析为绝对路径

    .mcp.json 的 cwd 通常是相对路径（如 "."），相对于 .mcp.json 所在目录。
    本函数把相对路径转换为绝对路径，避免主程序工作目录不同导致找不到文件。

    Args:
        cwd_field: .mcp.json 中的 cwd 字段值（可能是 "." 或 "./subdir"）
        mcp_json_path: .mcp.json 文件的绝对路径

    Returns:
        str: 解析后的绝对路径
    """
    if not cwd_field:
        return str(mcp_json_path.parent)
    cwd_path = Path(cwd_field)
    if not cwd_path.is_absolute():
        # 相对路径：相对于 .mcp.json 所在目录
        cwd_path = (mcp_json_path.parent / cwd_path).resolve()
    return str(cwd_path)


def discover_external_mcp_configs(
    external_root: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """扫描 app/skills/external/ 下所有 .mcp.json 并返回统一格式的预设列表

    扫描规则：
        - 递归扫描 external_root 下所有 .mcp.json 文件（跳过 .git 目录）
        - 解析每个 .mcp.json 的 mcpServers 字段（标准 MCP 配置格式）
        - 每个 server 转换为一个预设 dict，与 MCP_PRESETS 格式兼容

    Args:
        external_root: 外部 skill 根目录；默认为 app/skills/external/

    Returns:
        List[Dict[str, Any]]: 预设列表，每个元素形如：
            {
                "id": "<repo>__<server_name>",  # 唯一 id
                "type": "stdio",
                "name": "<server_name>",
                "description": "外部 MCP 服务（来源: <repo>）",
                "command": "node",
                "args": ["dist/server.mjs"],
                "cwd": "<abs_path>",  # 已解析为绝对路径
                "category": "外部 MCP",
                "icon": "📦",
                "source": "external",
                "config_path": "<abs_path_to_mcp_json>",
            }
    """
    if external_root is None:
        # 延迟导入避免循环依赖
        try:
            from app.skills import EXTERNAL_SKILLS_ROOT
            external_root = EXTERNAL_SKILLS_ROOT
        except Exception as e:
            logger.warning(f"获取 EXTERNAL_SKILLS_ROOT 失败: {e}")
            return []

    result: List[Dict[str, Any]] = []
    if not external_root.is_dir():
        logger.debug(f"外部 skill 根目录不存在: {external_root}")
        return result

    # 扫描所有 .mcp.json 文件
    mcp_json_files: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(external_root):
        # 原地过滤 dirnames，阻止 os.walk 进入 .git
        dirnames[:] = [d for d in dirnames if d != ".git"]
        if ".mcp.json" in filenames:
            mcp_json_files.append(Path(dirpath) / ".mcp.json")

    logger.info(f"发现 {len(mcp_json_files)} 个外部 .mcp.json 配置文件")

    for mcp_json_path in mcp_json_files:
        try:
            content = mcp_json_path.read_text(encoding="utf-8")
            data = json.loads(content)
            servers = data.get("mcpServers", {})
            if not isinstance(servers, dict):
                logger.warning(f".mcp.json mcpServers 字段非 dict: {mcp_json_path}")
                continue

            # 推断来源仓库名（external/ 下第一级目录名）
            try:
                rel = mcp_json_path.relative_to(external_root)
                source_repo = rel.parts[0] if rel.parts else "unknown"
            except ValueError:
                source_repo = "unknown"

            for server_name, server_cfg in servers.items():
                if not isinstance(server_cfg, dict):
                    continue
                command = server_cfg.get("command")
                if not command:
                    logger.warning(f".mcp.json server {server_name} 缺少 command: {mcp_json_path}")
                    continue
                args = server_cfg.get("args", []) or []
                cwd_field = server_cfg.get("cwd", ".")
                cwd_abs = _resolve_cwd(cwd_field, mcp_json_path)

                preset = {
                    "id": f"{source_repo}__{server_name}",
                    "type": "stdio",
                    "name": f"{server_name}",
                    "description": f"外部 MCP 服务（来源: {source_repo}）",
                    "command": command,
                    "args": args,
                    "cwd": cwd_abs,
                    "category": "外部 MCP",
                    "icon": "📦",
                    "source": "external",
                    "config_path": str(mcp_json_path),
                }
                result.append(preset)
                logger.info(f"已发现外部 MCP: {preset['id']} -> {command} {' '.join(args)}")
        except Exception as e:
            logger.warning(f"解析 .mcp.json 失败 {mcp_json_path}: {e}")

    return result


def list_all_mcp_presets_with_external() -> List[Dict[str, Any]]:
    """合并内置 MCP 预设 + 外部扫描到的 MCP 配置

    供 extensions_module._create_mcp_tab 调用，统一展示所有可连接的 MCP。
    """
    presets = list_mcp_presets()
    try:
        presets.extend(discover_external_mcp_configs())
    except Exception as e:
        logger.warning(f"扫描外部 MCP 配置失败: {e}")
    return presets
