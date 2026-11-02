# -*- coding: utf-8 -*-
"""局域网自动发现（UDP 45123）—— 让同事不用手输 IP。

## 两种机制都做（互为兜底）

1. **被动**：服务端每 2 秒往广播地址发一次 beacon（JSON），客户端监听即可看到；
2. **主动**：客户端发 `DISCOVER` 广播，服务端**单播回复**自己的地址。

为什么两个都要：企业 Wi-Fi 常开"广播抑制"，被动收不到 beacon；而主动查询
是单播回复，能穿过大部分抑制策略。反过来，某些网络禁止客户端广播但允许服务端
广播，这时被动又成了唯一通路 —— **只做一种就会在特定网络里"扫不到"**。

## 报文格式（很短，UDP 有 512 字节舒适区）

```json
{"app":"shiguang-team","name":"拾光剪影团队","port":18770,"host":"192.168.1.5","ver":"1"}
```

校验：`app` 必须等于 `APP_TAG`，否则忽略（防止同端口别的软件误认）。
"""
from __future__ import annotations

import json
import logging
import re
import socket
import threading
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

APP_TAG = "shiguang-team"
DISCOVER_PORT = 45123
DISCOVER_MAGIC = "SHIGUANG_DISCOVER"
#: 配对码查询前缀（`SHIGUANG_PAIR:482913`）：同事只知道 6 位码、不知道 IP 时用。
#: 收到后**只有持有这张有效码的机器才回复** —— 无效码一律沉默，等于让穷举既慢又无反馈。
PAIR_MAGIC_PREFIX = "SHIGUANG_PAIR:"
BEACON_INTERVAL = 2.0

#: Windows 套接字错误码 → 能照着做的下一步。
#: 🔴 2026-11-02：用户实机对着面板只看到
#: `[WinError 10038] 在一个非套接字上尝试了一个操作。` —— 错误码本身对使用者零信息量，
#: 而且这是**唯一**会把原始 OSError 一路透到界面的地方（全库只有本模块碰 UDP/close）。
#: 纪律：技术细节留在日志里，界面只给「该做什么」。
_SOCK_HINTS: Dict[int, str] = {
    10013: "权限不足：端口被系统策略或防火墙挡住，换端口或放行程序",
    10038: "套接字已关闭：团队服务刚被停掉，重新启动一次就好",
    10048: "端口已占用：这台机器上已有一个团队服务在跑（或换台机器当服务器）",
    10049: "地址不可用：IP 不在本机网段，检查地址里的 IP 段",
    10053: "连接被对方中断：对方服务刚停，重试一次",
    10060: "连接超时：两台机器不在同一网段，或被防火墙拦住",
    10061: "拒绝连接：对方没启动团队服务，或端口不是 18770",
    10065: "网络不可达：两台机器没连到同一台路由器",
}


def friendly_socket_error(exc: BaseException) -> str:
    """把套接字错误翻成一句能照做的话；原始错误码附在末尾，便于用户反馈。

    非套接字错误（含 NotImplementedError 之类）原样返回，不吞信息。
    """
    win: Optional[int] = getattr(exc, "winerror", None)
    if win is None:
        m = re.search(r"\[WinError (\d+)\]", str(exc))
        win = int(m.group(1)) if m else None
    hint = _SOCK_HINTS.get(int(win)) if win is not None else None
    if hint:
        return "%s（WinError %s）" % (hint, win)
    return str(exc)


def encode_payload(name: str, port: int, host: str = "", ver: str = "1") -> bytes:
    return json.dumps({
        "app": APP_TAG,
        "name": str(name or "")[:64],
        "port": int(port),
        "host": str(host or ""),
        "ver": str(ver),
    }, ensure_ascii=False).encode("utf-8")


def decode_payload(raw: bytes) -> Optional[Dict[str, Any]]:
    """解析并校验；不是我们的报文就返回 None（静默忽略是正确行为）。"""
    try:
        data = json.loads(raw.decode("utf-8", errors="ignore").strip())
    except Exception:  # stability-gate: allow-swallow（UDP 上任何垃圾包都不该抛）
        return None
    if not isinstance(data, dict) or data.get("app") != APP_TAG:
        return None
    try:
        port = int(data.get("port") or 0)
    except Exception:  # stability-gate: allow-swallow（脏字段按无效报文丢弃）
        return None
    if not (0 < port < 65536):
        return None
    return {"name": str(data.get("name") or ""), "port": port,
            "host": str(data.get("host") or ""), "ver": str(data.get("ver") or "")}


def _broadcast_addrs() -> List[str]:
    """全局广播 + 各网卡定向广播（定向广播穿透力更强）。"""
    addrs = ["255.255.255.255"]
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ip = info[4][0]
            if ip and "." in ip and not ip.startswith("127."):
                addrs.append(ip.rsplit(".", 1)[0] + ".255")
    except Exception:  # stability-gate: allow-swallow（拿不到网卡信息就只用全局广播）
        logger.debug("[team.discovery] 枚举网卡失败", exc_info=True)
    return list(dict.fromkeys(addrs))


class Beacon:
    """服务端：周期性广播 + 应答 DISCOVER。"""

    def __init__(self, name: str, port: int, host: str = "", interval: float = BEACON_INTERVAL,
                 pair_alive: Optional[Callable[[str], bool]] = None) -> None:
        self.name = name
        self.port = port
        self.host = host
        self.interval = interval
        #: 配对码校验回调（由 Hub 提供）。没给就只应答 DISCOVER，不理配对请求。
        self.pair_alive = pair_alive
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._sock: Optional[socket.socket] = None
        self._listener: Optional[socket.socket] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        # 🔴 2026-11-02 实锤 bug：stop() 会把 _stop 置位，start() 从来没清回来。
        # 后果（本机实测 is_alive()=False）：**停止团队服务再重新启动后，beacon 线程刚起来就退出**，
        # HTTP 服务照常能用、同事手填地址也能连，但「扫描局域网」永远扫不到这台机 ——
        # 现象和「网络限制广播」一模一样，几乎不可能从界面归因。
        self._stop.clear()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock = sock
        self._thread = threading.Thread(target=self._loop, name="TeamBeacon", daemon=True)
        self._thread.start()

    def _open_listener(self) -> Optional[socket.socket]:
        """监听 DISCOVER（用独立 socket，避免与发送互相干扰）；端口被占则降级为只广播。"""
        listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.settimeout(0.5)
        try:
            listener.bind(("", DISCOVER_PORT))
        except Exception:  # stability-gate: allow-swallow（端口被占则只做被动广播，不中断服务）
            logger.warning("[team.discovery] 无法监听 %d（可能已被占用），降级为只广播", DISCOVER_PORT)
            listener.close()
            return None
        self._listener = listener
        return listener

    def _close_listener(self) -> None:
        """关掉监听 socket 并摘掉引用（幂等）。

        🔴 必须显式关：原先靠局部变量出作用域后 GC 收尾，导致
        「停止 → 立刻启动」时 45123 偶尔还占着 ⇒ 新 beacon 静默降级成只广播。
        """
        listener, self._listener = self._listener, None
        if listener is None:
            return
        try:
            listener.close()
        except OSError:  # stability-gate: allow-swallow（关闭失败不该打断停止流程）
            logger.debug("[team.discovery] 关闭监听 socket 失败", exc_info=True)

    def _loop(self) -> None:
        sock = self._sock
        if sock is None:
            return
        listener = self._open_listener()
        try:
            payload = encode_payload(self.name, self.port, self.host)
            last = 0.0
            while not self._stop.is_set():
                now = time.time()
                if now - last >= self.interval:
                    last = now
                    for addr in _broadcast_addrs():
                        try:
                            sock.sendto(payload, (addr, DISCOVER_PORT))
                        except Exception:  # stability-gate: allow-swallow（单播地址不可达就换下一个）
                            continue
                if listener is None:
                    self._stop.wait(0.5)
                    continue
                try:
                    raw, peer = listener.recvfrom(1024)
                except socket.timeout:
                    continue
                except OSError:
                    # stop() 从别的线程关掉 listener 时这里会立刻抛（Windows 上是
                    # WinError 10038）。这是**正常退出路径**，不是故障；循环头会看到 _stop 并结束。
                    if self._stop.is_set():
                        break
                    continue
                except Exception:  # stability-gate: allow-swallow（收包异常不终止 beacon）
                    continue
                text = raw.strip()[:32].decode("ascii", "ignore")
                if text == DISCOVER_MAGIC:
                    try:
                        listener.sendto(payload, peer)   # 单播回复：穿透广播抑制
                    except Exception:  # stability-gate: allow-swallow（回复失败等下一次）
                        continue
                    continue
                # 配对码查询：只有「我这儿真有这张有效码」才出声
                code = decode_pair_request(raw)
                if code and self.pair_alive is not None:
                    try:
                        ok = bool(self.pair_alive(code))
                    except Exception:  # stability-gate: allow-swallow（校验失败按无效处理，别回错包）
                        logger.debug("[team.discovery] 配对码校验异常 code=%s", code, exc_info=True)
                        ok = False
                    if ok:
                        try:
                            listener.sendto(payload, peer)
                        except Exception:  # stability-gate: allow-swallow（回复失败等下一次）
                            continue
        finally:
            self._close_listener()

    def stop(self) -> None:
        self._stop.set()
        # 先关 listener：recvfrom 有 0.5s 超时也能退出，但先关能让线程立刻返回，
        # 也让 45123 尽早释放（否则立刻重启会降级成只广播）。
        self._close_listener()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:  # stability-gate: allow-swallow（已被系统回收时 close 会抛，忽略）
                logger.debug("[team.discovery] 关闭广播 socket 失败", exc_info=True)


def scan(timeout: float = 2.0) -> List[Dict[str, Any]]:
    """客户端：发 DISCOVER + 被动收集 beacon，返回去重后的服务列表。"""
    found: Dict[tuple, Dict[str, Any]] = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(0.4)
    try:
        try:
            sock.bind(("", 0))
        except Exception:  # stability-gate: allow-swallow（绑定失败仍可尝试发送）
            logger.debug("[team.discovery] 客户端 bind 失败", exc_info=True)
        for addr in _broadcast_addrs():
            try:
                sock.sendto(DISCOVER_MAGIC.encode(), (addr, DISCOVER_PORT))
            except Exception:  # stability-gate: allow-swallow（某网段不可达就跳过）
                continue
        deadline = time.time() + max(0.5, float(timeout))
        while time.time() < deadline:
            try:
                raw, peer = sock.recvfrom(1024)
            except socket.timeout:
                continue
            except Exception:  # stability-gate: allow-swallow（收包异常继续等待）
                continue
            info = decode_payload(raw)
            if info is None:
                continue
            ip = info.get("host") or peer[0]
            info["address"] = "http://%s:%d" % (ip, info["port"])
            info["peer"] = peer[0]
            found[(ip, info["port"])] = info
    finally:
        sock.close()
    return list(found.values())


def decode_pair_request(raw: bytes) -> Optional[str]:
    """从报文里解出配对码；不是配对请求 / 格式不对一律 `None`。

    纯函数：不碰网络，便于在测试里喂反例（空包、别的软件的包、超长码）。
    """
    text = raw.decode("ascii", "ignore").strip() if isinstance(raw, (bytes, bytearray)) else ""
    if not text.startswith(PAIR_MAGIC_PREFIX):
        return None
    code = text[len(PAIR_MAGIC_PREFIX):].strip()
    return code if re.fullmatch(r"\d{4,10}", code) else None


def find_by_code(code: str, timeout: float = 2.5) -> Optional[Dict[str, Any]]:
    """**只凭 6 位配对码**找主机 —— 同事不需要知道任何 IP。

    这就是「多屏协同」里那一步：码替地址。广播出去后，只有真的持有这张有效码的
    机器会单播应答（`Beacon` 里的 `pair_alive` 回调），其余全部沉默。

    返回与 `scan()` 同一形状的字典（含 `address` / `peer`），找不到回 `None`。
    """
    clean = str(code or "").strip()
    if not re.fullmatch(r"\d{4,10}", clean):
        return None
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(0.4)
    try:
        try:
            sock.bind(("", 0))
        except Exception:  # stability-gate: allow-swallow（绑定失败仍可尝试发送）
            logger.debug("[team.discovery] 配对查询 bind 失败", exc_info=True)
        msg = (PAIR_MAGIC_PREFIX + clean).encode()
        sent = 0
        for addr in _broadcast_addrs():
            try:
                sock.sendto(msg, (addr, DISCOVER_PORT))
                sent += 1
            except Exception:  # stability-gate: allow-swallow（某网段不可达就跳过）
                continue
        if not sent:
            logger.warning("[team.discovery] 配对查询无处可发（没有可用广播地址）")
            return None
        deadline = time.time() + max(0.6, float(timeout))
        while time.time() < deadline:
            try:
                raw, peer = sock.recvfrom(1024)
            except socket.timeout:
                continue
            except Exception:  # stability-gate: allow-swallow（收包异常继续等）
                continue
            info = decode_payload(raw)
            if info is None:
                continue
            ip = info.get("host") or peer[0]
            info["address"] = "http://%s:%d" % (ip, info["port"])
            info["peer"] = peer[0]
            return info
        return None
    finally:
        sock.close()
