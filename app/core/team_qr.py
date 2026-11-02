# -*- coding: utf-8 -*-
"""二维码生成（2026-11-02）—— 比「让同事念 IP」更进一步的那一步。

## 什么时候真的需要二维码

配对码（6 位数字）已经解决了「同事不用知道 IP」的主路径。二维码补的是**另一种**
场景：人不在旁边、要隔着微信/聊天软件把「这台机器的团队地址」递过去。

  · 复制一行 `http://192.168.1.4:18770` 发过去 —— 对方还得找地方粘贴；
  · 发一张二维码 —— 对方手机一扫就看见地址 + 配对码，能直接复制/转发。

所以它不是必需品，是「递地址」的载体。**不引入新依赖**：`cv2`（OpenCV）自带
QR 编码器，PIL 已在依赖里，两者都是本机现成的。cv2 不可用时回空串，
调用方只显示数字码，功能不受影响。
"""
from __future__ import annotations

import base64
import io
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def qr_png_data_uri(text: str, scale: int = 6, border: int = 4) -> str:
    """把 `text` 编成二维码，返回 `data:image/png;base64,…`；失败回空串。

    `border` 是**静区**（quiet zone）：二维码四边必须留白，少了手机扫不出来 ——
    这是最常见的「我明明生成了却扫不动」的原因。
    """
    payload = str(text or "").strip()
    if not payload:
        return ""
    try:
        import cv2
        import numpy as np
        from PIL import Image

        matrix = cv2.QRCodeEncoder_create().encode(payload)
        if matrix is None:
            return ""
        # cv2 回的是 (N,N) 或 (N,N,1) 的 0/255；统一成二维
        arr = np.asarray(matrix, dtype=np.uint8)
        if arr.ndim == 3:
            arr = arr[:, :, 0]
        if border > 0:
            arr = np.pad(arr, border, constant_values=255)
        img = Image.fromarray(arr, mode="L")
        side = max(1, int(scale))
        img = img.resize((img.width * side, img.height * side), Image.NEAREST)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        # 生成不出来只是少一张图，不能让它拦住「生成配对码」这件正事
        logger.debug("[team.qr] 二维码生成失败 text=%r", payload[:80], exc_info=True)
        return ""


def qr_selfcheck(text: str = "https://example.com/pair?code=482913") -> Optional[str]:
    """自检：生成后自己解一遍，解不回原文就返回原因（供测试/诊断用）。"""
    try:
        import cv2
        import numpy as np

        uri = qr_png_data_uri(text)
        if not uri:
            return "生成失败"
        raw = base64.b64decode(uri.split(",", 1)[1])
        arr = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if arr is None:
            return "解码失败（PNG 读不回来）"
        data, _pts, _straight = cv2.QRCodeDetector().detectAndDecode(arr)
        return None if data == text else "内容不一致：%r" % (data,)
    except Exception as e:  # pragma: no cover - 仅诊断入口
        return "%s: %s" % (type(e).__name__, e)
