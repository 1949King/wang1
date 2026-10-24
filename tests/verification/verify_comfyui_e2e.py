"""ComfyUI 端到端执行链路验证（模拟引擎就位 · 不触碰 GPL 闸门）。

在**不安装真实 ComfyUI 引擎**的前提下，用标准库 `http.server` 起一个最小 HTTP 桩，
模拟引擎的四个核心 REST 接口（`/system_stats`、`/prompt`、`/history/{id}`、`/view`），
并借 `SHIGUANG_COMFY_HOME` 环境变量指向一个含 `main.py` 的临时目录来模拟「引擎源码已就位」，
从而让 `comfy_client` 的「提交→轮询→下载→落箱」真实执行路径全量跑通。

验证目标（P3 端到端闭环）：
  粘贴 UI workflow → workflow_importer.parse（UI→graph）→ run_workflow 真实执行
  → POST /prompt 提交 → 轮询 /history（running→success）→ 下载 /view 出图
  → 落 canvas_inbox_dir → 返回可播放 inbox URL。

GPL 合规声明（方案 §4/§11）：本脚本只模拟 HTTP 接口，不打包、不发行、不复制任何
ComfyUI 源码；`main.py` 为测试期内临时空桩，验证结束即随 TemporaryDirectory 销毁。

运行方式（项目根目录）：
    python -m tests.verification.verify_comfyui_e2e
"""
from __future__ import annotations

import base64
import http.server
import json
import logging
import os
import tempfile
import threading

from app.core.ai.comfy_client import comfy_client

logger = logging.getLogger(__name__)

# 1x1 透明 PNG，作为 mock 引擎「生成结果」的下载负载（非空即可通过 size>0 校验）
_MOCK_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)
_MOCK_PROMPT_ID = "mock-0001"


class _MockComfyHandler(http.server.BaseHTTPRequestHandler):
    """模拟 ComfyUI 引擎的四个核心 REST 接口。

    行为约定（对齐 comfy_client 的 HTTP 契约）：
      - GET  /system_stats   → 200 {}（is_available 判定在线）
      - POST /prompt         → {"prompt_id": ...}（submit_prompt 取 prompt_id）
      - GET  /history/{id}   → {id: {status, outputs}}（首次 running，随后 success）
      - GET  /view           → 200 image/png 二进制（download_image 落盘）
    """

    _history_calls = 0  # 类变量：跨请求累计 /history 调用次数，驱动「running→success」轮询

    def do_GET(self):
        """分发 GET 请求（健康探测 / 历史查询 / 图片下载）。"""
        if self.path.startswith("/system_stats"):
            self._send_json(200, {})
            return
        if self.path.startswith("/history/"):
            type(self)._history_calls += 1
            prompt_id = self.path.rsplit("/", 1)[-1]
            entry = self._history_entry(type(self)._history_calls)
            self._send_json(200, {prompt_id: entry})
            return
        if self.path.startswith("/view"):
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(_MOCK_PNG)))
            self.end_headers()
            self.wfile.write(_MOCK_PNG)
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        """分发 POST 请求（仅 /prompt 提交）。"""
        if self.path.startswith("/prompt"):
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)  # 读取 graph 负载并丢弃（mock 不校验节点内容）
            self._send_json(200, {"prompt_id": _MOCK_PROMPT_ID})
            return
        self._send_json(404, {"error": "not found"})

    def _send_json(self, code: int, payload: dict):
        """回写 JSON 响应。"""
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _history_entry(call_index: int) -> dict:
        """首次返回 running（未完成，触发轮询），此后返回 success（完成 + 输出图）。"""
        if call_index < 2:
            return {"status": {"status_str": "running", "completed": False}}
        return {
            "status": {"status_str": "success", "completed": True, "messages": []},
            "outputs": {
                "9": {"images": [
                    {"filename": "mock_output_00001_.png", "subfolder": "", "type": "output"},
                ]},
            },
        }

    def log_message(self, format, *args):
        """静默 http.server 默认访问日志，避免污染验证输出。"""
        logger.debug(format, *args)


def _start_mock_engine():
    """在随机空闲端口启动 mock 引擎（后台线程），返回 (server, port)。"""
    server = http.server.HTTPServer(("127.0.0.1", 0), _MockComfyHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


def main():
    """执行端到端验证：模拟引擎就位 → UI workflow 真实执行 → 断言完整闭环。"""
    old_env = os.environ.get("SHIGUANG_COMFY_HOME")
    download_paths: list = []

    # 临时引擎目录（含 main.py）模拟「引擎源码已就位」，通过环境变量注入 provider 探测
    with tempfile.TemporaryDirectory() as engine_dir:
        with open(os.path.join(engine_dir, "main.py"), "w", encoding="utf-8") as f:
            f.write("# mock ComfyUI entry\n")
        os.environ["SHIGUANG_COMFY_HOME"] = engine_dir

        server, port = _start_mock_engine()
        try:
            # 把客户端重定向到 mock 引擎（configure 会清空可用性缓存，触发重新探测）
            comfy_client.configure(host="http://127.0.0.1", port=port)

            from app.core.ai.comfy_provider import comfy_provider

            # 贴近「粘贴即用」：传 UI workflow（含 nodes/links），走 parse→graph→真实执行
            ui_workflow = {
                "nodes": [
                    {"id": 1, "type": "EmptyLatentImage",
                     "inputs": [
                         {"name": "width", "link": None, "widget": {"name": "width"}},
                         {"name": "height", "link": None, "widget": {"name": "height"}},
                         {"name": "batch_size", "link": None, "widget": {"name": "batch_size"}},
                     ],
                     "widgets_values": [64, 64, 1]},
                    {"id": 2, "type": "SaveImage",
                     "inputs": [
                         {"name": "images", "link": 10},
                         {"name": "filename_prefix", "link": None,
                          "widget": {"name": "filename_prefix"}},
                     ],
                     "widgets_values": ["mock"]},
                ],
                "links": [[10, 1, 0, 2, 0, "LATENT"]],
            }

            progress: list = []
            result = comfy_provider.run_workflow_from_json(
                ui_workflow, dry_run=False, progress_callback=progress.append
            )
            download_paths = list(result.get("paths") or [])

            # 断言完整闭环（失败即抛，暴露链路断点）
            assert result["ok"] is True, f"执行未成功: {result.get('error')}"
            assert result["prompt_id"] == _MOCK_PROMPT_ID
            assert result["engine_available"] is True, "引擎就位模拟未生效（has_engine 应为 True）"
            assert result["raw_format"] == "ui"
            assert result["node_ids"] == ["1", "2"]
            assert len(result["paths"]) == 1, f"落盘路径应恰好 1 张: {result['paths']}"
            assert len(result["urls"]) == 1
            assert "/inbox_file/" in result["urls"][0], "URL 未落到 inbox 通道"
            for p in result["paths"]:
                assert os.path.isfile(p) and os.path.getsize(p) > 0, f"落盘文件异常: {p}"
            assert progress, "progress_callback 未被调用（轮询未生效）"
            assert progress[-1] == "success", f"最终状态应为 success，实际 {progress}"

            logger.info(json.dumps({
                "ok": result["ok"],
                "prompt_id": result["prompt_id"],
                "raw_format": result["raw_format"],
                "node_ids": result["node_ids"],
                "class_types": result["class_types"],
                "engine_available": result["engine_available"],
                "progress_seq": progress,
                "download_path": result["paths"][0],
                "url": result["urls"][0],
            }, ensure_ascii=False, indent=2))
        finally:
            server.shutdown()
            server.server_close()
            # 清理验证期间落盘的测试图片，避免污染 canvas_inbox
            for p in download_paths:
                try:
                    if os.path.isfile(p):
                        os.remove(p)
                except OSError as e:
                    logger.debug(f"清理测试落盘文件失败 {p}: {e}")

    # 恢复环境变量，避免污染后续进程
    if old_env is None:
        os.environ.pop("SHIGUANG_COMFY_HOME", None)
    else:
        os.environ["SHIGUANG_COMFY_HOME"] = old_env


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
    logger.info("P3 端到端执行链路验证通过")