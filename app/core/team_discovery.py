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
import socket
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

APP_TAG = "shiguang-team"
DISCOVER_PORT = 45123
DISCOVER_MAGIC = "SHIGUANG_DISCOVER"
BEACON_INTERVAL = 2.0


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

    def __init__(self, name: str, port: int, host: str = "", interval: float = BEACON_INTERVAL) -> None:
        self.name = name
        self.port = port
        self.host = host
        self.interval = interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._sock: Optional[socket.socket] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock = sock
        self._thread = threading.Thread(target=self._loop, name="TeamBeacon", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        sock = self._sock
        if sock is None:
            return
        # 监听 DISCOVER（用同一端口的另一个 socket，避免与发送互相干扰）
        listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.settimeout(0.5)
        try:
            listener.bind(("", DISCOVER_PORT))
        except Exception:  # stability-gate: allow-swallow（端口被占则只做被动广播，不中断服务）
            logger.warning("[team.discovery] 无法监听 %d（可能已被占用），降级为只广播", DISCOVER_PORT)
            listener.close()
            listener = None  # type: ignore[assignment]

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
            except Exception:  # stability-gate: allow-swallow（收包异常不终止 beacon）
                continue
            if raw.strip()[:32] == DISCOVER_MAGIC.encode():
                try:
                    listener.sendto(payload, peer)   # 单播回复：穿透广播抑制
                except Exception:  # stability-gate: allow-swallow（回复失败等下一次）
                    continue

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None


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
