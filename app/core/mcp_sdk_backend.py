"""MCP 官方 Python SDK 后端（可选 · 自动回退）
============================================
本项目原有 :mod:`app.core.mcp_client` 是**手写 JSON-RPC 2.0 客户端**。它能跑通
Blender MCP（stdio），但有几处与协议规范有出入：

* ``initialize`` 之后**没有发 ``notifications/initialized``** 通知（规范要求）；
* stdio 用 ``text=True, bufsize=1`` 按行读，遇到大 payload / 多行 JSON 易截断；
* SSE 分支实际是按「HTTP POST /initialize」实现的，**不是** MCP 的 SSE 握手
  （先 GET SSE 流拿 message endpoint，再向该 endpoint POST）；
* 没有 streamable-HTTP 传输、没有 ``Mcp-Session-Id`` 头、没有能力协商与分页。

官方 SDK（``pip install mcp``，modelcontextprotocol/python-sdk）把上述全部处理掉了。

本模块提供**同一套同步门面**（open / list_tools / call_tool / close），
在后台线程跑 asyncio 事件循环，供 Qt 主线程同步调用。

设计原则
--------
1. **零硬依赖**：未安装 ``mcp`` 时 :func:`available` 返回 False，管理器自动回落手写实现；
2. **不改默认行为**：只有显式 ``backend="sdk"``（或 ``auto`` 且 SDK 可用）才走本后端；
3. **诚实失败**：连不上就报错，不伪造工具列表。

参考：Model Context Protocol Python SDK（MIT）。
"""
from __future__ import annotations

import asyncio
import importlib.util
import logging
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger("AI短剧编辑器.mcp.sdk")

#: 默认连接/初始化超时（秒）
DEFAULT_TIMEOUT = 30.0


def available() -> bool:
    """官方 ``mcp`` 包是否可用（**只探测，不导入**）。"""
    try:
        return importlib.util.find_spec("mcp") is not None
    except Exception:
        return False


def sdk_version() -> str:
    """官方 SDK 版本（未安装返回空串）。"""
    try:
        from importlib.metadata import version

        return version("mcp")
    except Exception:
        return ""


def _resolve_streamable_http_client():
    """取 streamable-HTTP 客户端上下文管理器。

    官方 SDK **2.0 改名**：``streamablehttp_client`` → ``streamable_http_client``
    （实测 mcp 2.3.0 只剩后者）。两个版本都兼容：同一模块里按名字取，
    取不到即诚实报错，不静默回退。
    """
    from mcp.client import streamable_http as _sh

    fn = getattr(_sh, "streamablehttp_client", None) or getattr(  # 1.x
        _sh, "streamable_http_client", None  # 2.x
    )
    if fn is None:
        raise RuntimeError(
            "当前 mcp SDK 未提供 streamable-HTTP 客户端"
            "（1.x 的 streamablehttp_client / 2.x 的 streamable_http_client 均缺失）"
        )
    return fn


def _unpack_streams(streams: Any):
    """把传输客户端产出的流对象解析成 ``(read, write)``。

    1.x 的 streamable-http 产出 3 元组 ``(read, write, get_session_id)``，
    2.x 产出 2 元组/``TransportStreams``；stdio / SSE 一直产出 2 元组。
    """
    if isinstance(streams, (tuple, list)):
        if len(streams) >= 2:
            return streams[0], streams[1]
    read = getattr(streams, "read", None)
    write = getattr(streams, "write", None)
    if read is not None and write is not None:
        return read, write
    raise ValueError(f"无法解析 MCP 传输流对象: {streams!r}")


class McpSdkSession:
    """官方 SDK 会话的**同步门面**。

    内部起一个 daemon 线程跑 asyncio 事件循环；所有 async 上下文（transport、
    ClientSession）都挂在同一个 ``AsyncExitStack`` 上，保证按 LIFO 正确关闭。
    """

    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._closed = threading.Event()
        self._exit_stack: Any = None
        self._session: Any = None
        self._error: Optional[str] = None
        self._tools: List[Dict[str, Any]] = []
        self._server_name = ""

    # ─────────── 生命周期 ───────────

    @staticmethod
    def available() -> bool:
        """官方 ``mcp`` 包是否可用（等价于模块级 :func:`available`）。"""
        return available()

    @property
    def error(self) -> Optional[str]:
        return self._error

    @property
    def session_id(self) -> Optional[str]:
        """官方 SDK 的会话标识（取自 server session id，可能为空）。"""
        sid = getattr(self._session, "session_id", None) if self._session else None
        return str(sid) if sid else None

    def open(self, config: Dict[str, Any], timeout: float = DEFAULT_TIMEOUT) -> bool:
        """建立连接并抓取工具列表。返回是否成功。"""
        if not available():
            self._error = "未安装官方 MCP SDK（pip install mcp）"
            return False
        self._server_name = str(config.get("name") or "Unknown MCP")
        self._thread = threading.Thread(
            target=self._run_loop, args=(dict(config),), name="McpSdkSession", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(timeout):
            self._error = self._error or f"连接超时（{timeout}s）"
            self.close()
            return False
        if self._error:
            return False
        # 抓工具列表（失败不致命，但记录）
        tools = self.list_tools()
        if tools:
            self._tools = tools
        return True

    def _run_loop(self, config: Dict[str, Any]) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._open_async(config))
            if self._error is None:
                loop.run_forever()
        except Exception as e:  # pragma: no cover - 环境相关
            self._error = self._error or str(e)
            logger.debug("MCP SDK 事件循环异常", exc_info=True)
        finally:
            self._ready.set()
            self._closed.set()
            try:
                # 取消残留任务，避免 "Task was destroyed" 噪声
                pending = asyncio.all_tasks(loop)
                for t in pending:
                    t.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            except Exception:
                logger.debug("回收 MCP SDK 残留任务失败", exc_info=True)
            try:
                loop.close()
            except Exception:
                logger.debug("关闭 MCP SDK 事件循环失败", exc_info=True)

    async def _open_async(self, config: Dict[str, Any]) -> None:
        from contextlib import AsyncExitStack

        from mcp import ClientSession

        stack = AsyncExitStack()
        transport = str(config.get("type") or "stdio").lower()
        try:
            if transport == "stdio":
                from mcp import StdioServerParameters
                from mcp.client.stdio import stdio_client

                command = config.get("command")
                if not command:
                    raise ValueError("未指定命令")
                params = StdioServerParameters(
                    command=str(command),
                    args=[str(a) for a in (config.get("args") or [])],
                    env=config.get("env") or None,
                    cwd=config.get("cwd") or None,
                )
                read, write = _unpack_streams(
                    await stack.enter_async_context(stdio_client(params))
                )
            elif transport in ("sse", "http", "streamable_http"):
                url = config.get("url")
                if not url:
                    raise ValueError("未指定 URL")
                if transport == "sse":
                    from mcp.client.sse import sse_client

                    ctx = sse_client(str(url))
                else:
                    ctx = _resolve_streamable_http_client()(str(url))
                read, write = _unpack_streams(await stack.enter_async_context(ctx))
            else:
                raise ValueError(f"不支持的传输类型: {transport}")

            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self._exit_stack = stack
            self._session = session
            logger.info("MCP SDK 已连接: %s (%s)", self._server_name, transport)
        except Exception as e:
            self._error = str(e)
            try:
                await stack.aclose()
            except Exception:
                logger.debug("连接失败后释放 MCP SDK 资源异常", exc_info=True)
        finally:
            self._ready.set()

    # ─────────── 操作 ───────────

    def _submit(self, coro, timeout: float = DEFAULT_TIMEOUT) -> Any:
        """把协程投给后台事件循环并同步等待结果。"""
        loop = self._loop
        if loop is None or self._closed.is_set():
            self._error = "MCP SDK 会话未运行"
            return None
        try:
            fut = asyncio.run_coroutine_threadsafe(coro, loop)
            return fut.result(timeout=timeout)
        except Exception as e:
            self._error = str(e)
            logger.warning("MCP SDK 调用失败: %s", e)
            return None

    def list_tools(self, timeout: float = DEFAULT_TIMEOUT) -> List[Dict[str, Any]]:
        """``tools/list``（SDK 自动处理分页）。"""
        if self._session is None:
            return []

        async def _go():
            resp = await self._session.list_tools()
            return list(getattr(resp, "tools", []) or [])

        tools = self._submit(_go(), timeout=timeout)
        if not tools:
            return []
        out: List[Dict[str, Any]] = []
        for t in tools:
            schema = getattr(t, "inputSchema", None) or {}
            out.append({
                "name": str(getattr(t, "name", "")),
                "description": str(getattr(t, "description", "") or ""),
                "parameters": schema if isinstance(schema, dict) else {},
                "server_name": self._server_name,
            })
        return out

    def call_tool(
        self, tool_name: str, arguments: Dict[str, Any], timeout: float = DEFAULT_TIMEOUT
    ) -> Any:
        """``tools/call``。返回**可直接消费**的结果：优先结构化内容，其次文本。"""
        if self._session is None:
            self._error = "MCP SDK 会话未运行"
            return None

        async def _go():
            return await self._session.call_tool(tool_name, arguments or {})

        result = self._submit(_go(), timeout=timeout)
        return _normalize_call_result(result)

    def close(self, timeout: float = 10.0) -> None:
        """关闭会话与传输（幂等）。"""
        loop = self._loop
        if loop is None:
            return
        if not self._closed.is_set():
            try:
                fut = asyncio.run_coroutine_threadsafe(self._close_async(), loop)
                fut.result(timeout=timeout)
            except Exception as e:  # pragma: no cover - 关闭竞态
                logger.debug("MCP SDK 关闭异常: %s", e)
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                logger.debug("停止 MCP SDK 事件循环失败", exc_info=True)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._session = None
        self._exit_stack = None
        self._loop = None

    async def _close_async(self) -> None:
        stack, self._exit_stack = self._exit_stack, None
        if stack is not None:
            try:
                await stack.aclose()
            except Exception as e:  # pragma: no cover
                logger.debug("MCP SDK AsyncExitStack 关闭异常: %s", e)
        self._session = None


def _normalize_call_result(result: Any) -> Any:
    """把 SDK 的 CallToolResult 压成项目现有消费方习惯的形状。

    项目既有代码期望 ``call_tool`` 返回「可直接 json 化的东西」——原先手写实现
    直接返回 JSON-RPC 的 ``result`` 字段。这里保持一致：
    结构化内容（structuredContent）优先，否则拼接文本内容，最后回退 isError 标记。
    """
    if result is None:
        return None
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return structured
    contents = list(getattr(result, "content", None) or [])
    texts: List[str] = []
    for c in contents:
        txt = getattr(c, "text", None)
        if txt is not None:
            texts.append(str(txt))
    if texts:
        if len(texts) == 1:
            return _maybe_json(texts[0])
        return [_maybe_json(t) for t in texts]
    is_error = bool(getattr(result, "isError", False))
    if is_error:
        return {"isError": True}
    return {}


def _maybe_json(text: str) -> Any:
    """文本恰好是 JSON 时解析成对象，否则原样返回字符串。"""
    s = (text or "").strip()
    if s[:1] in ("{", "[") and s[-1:] in ("}", "]"):
        import json

        try:
            return json.loads(s)
        except Exception:
            return text
    return text
