"""自研最小 ComfyUI 引擎客户端（P1 · 文生图透传执行线）。

职责：与内置透明引擎（后台自拉起、用户无感）通信，把 `workflow_importer`
产出的 graph prompt 提交执行，并取回生成图片。只实现标准 REST 接口，
不引用 / 复制 openshot-qt 的 GPL ComfyUI 客户端（「参考思路，不搬代码」）。

接口覆盖（ComfyUI 官方 API）：
  - GET  /system_stats     引擎健康探测
  - GET  /object_info      节点定义（供 workflow_importer 做 schema 校验）
  - POST /prompt           提交 graph prompt，返回 prompt_id
  - GET  /history/{id}     查询执行结果
  - GET  /view             下载输出图片
  - POST /upload/image     上传输入图（P2 img2img 用，已薄实现）

设计原则：
  - 线程安全单例；调用方应在 worker 线程调用，本模块不阻塞 Qt 主线程。
  - 本地连接一律 trust_env=False，绕开系统代理（与 ollama_client 一致）。
  - 只做数据/文件搬运，不写 UI；结果落哪由调用方（provider）决定目录。
  - 失败不抛裸异常：连接/HTTP/解析问题记日志并返回 None 或空结果。
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)


@dataclass
class ComfyConfig:
    """ComfyUI 引擎连接配置。"""

    host: str = "http://127.0.0.1"   # 引擎地址（含协议前缀）
    port: int = 8188                 # 默认 ComfyUI API 端口
    timeout: float = 30.0            # 单次 HTTP 请求超时（秒）
    poll_interval: float = 0.5       # 轮询 /history 的间隔（秒）
    poll_timeout: float = 300.0      # 等待单次生成完成的总超时（秒）

    @property
    def base_url(self) -> str:
        """拼接完整 URL 前缀，如 http://127.0.0.1:8188。"""
        return f"{self.host.rstrip('/')}:{self.port}"


class ComfyClient:
    """ComfyUI 引擎客户端 —— 线程安全单例。

    使用方式：
        from app.core.ai.comfy_client import comfy_client
        prompt_id = comfy_client.submit_prompt(graph_prompt)
        entry = comfy_client.wait_for_completion(prompt_id)
        images = comfy_client.collect_output_images(entry)
        paths = comfy_client.download_all_images(images, output_dir)
    """

    _instance: Optional['ComfyClient'] = None
    _lock = threading.Lock()

    def __new__(cls):
        """线程安全单例构造（双重检查锁定）。"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._config = ComfyConfig()
        self._available: Optional[bool] = None   # 可用性缓存（None=未探测）
        self._last_check: float = 0.0            # 上次探测时间戳

    @classmethod
    def get_instance(cls) -> 'ComfyClient':
        return cls()

    @property
    def base_url(self) -> str:
        return self._config.base_url

    def configure(self, host: Optional[str] = None, port: Optional[int] = None,
                  timeout: Optional[float] = None) -> 'ComfyClient':
        """运行期刷新引擎地址/端口（provider 拉起引擎后调用），返回 self 便于链式。"""
        if host is not None:
            self._config.host = host
        if port is not None:
            self._config.port = port
        if timeout is not None:
            self._config.timeout = timeout
        # 地址变化后清空缓存，让后续探测重新请求
        self._available = None
        self._last_check = 0.0
        return self

    # ═══════════════════════════════════════════════════════════
    # 连接与元信息
    # ═══════════════════════════════════════════════════════════

    def is_available(self, force_check: bool = False, timeout: float = 8.0) -> bool:
        """引擎是否在线（GET /system_stats）。默认缓存 60 秒。"""
        now = time.monotonic()
        if not force_check and self._available is not None and now - self._last_check < 60:
            return self._available
        try:
            session = self._new_session()
            try:
                resp = session.get(f"{self._config.base_url}/system_stats", timeout=timeout)
                self._available = resp.status_code == 200
            finally:
                session.close()
        except requests.exceptions.RequestException as e:
            logger.warning(f"[ComfyClient] system_stats 不可达: {e}")
            self._available = False
        self._last_check = time.monotonic()
        return self._available

    def diagnose(self) -> Dict[str, Any]:
        """强制探测并返回结构化诊断报告（供 UI 或 provider 判读）。

        2026-10-20：状态查询用 1.2s 短超时（原 8s）。本机引擎在/不在都应秒回；
        引擎冷启动中的短暂误报由 provider 的「可自动拉起」语境兜底。
        """
        ok = self.is_available(force_check=True, timeout=1.2)
        return {
            "available": ok,
            "base_url": self._config.base_url,
            "error": "" if ok else "连接失败或引擎未启动",
            "suggestion": "" if ok else "内置 ComfyUI 引擎未就绪，请先启动引擎进程并确认端口",
        }

    def get_object_info(self) -> Optional[Dict[str, Any]]:
        """获取节点定义（/object_info），返回 None 表示不可用。"""
        data = self._get_json("/object_info")
        if isinstance(data, dict):
            return data
        logger.warning("[ComfyClient] /object_info 返回结构异常")
        return None

    # ═══════════════════════════════════════════════════════════
    # 执行线（文生图闭环）
    # ═══════════════════════════════════════════════════════════

    def submit_prompt(self, graph_prompt: Dict[str, Any], client_id: str = "") -> Optional[str]:
        """提交 graph prompt 到 /prompt，返回 prompt_id；失败返回 None。"""
        if not graph_prompt:
            logger.error("[ComfyClient] 空的 graph_prompt，无法提交")
            return None
        data = self._post_json("/prompt", body={"prompt": graph_prompt, "client_id": client_id})
        if not data:
            return None
        prompt_id = data.get("prompt_id")
        if not prompt_id:
            logger.error(f"[ComfyClient] /prompt 未返回 prompt_id: {data}")
            return None
        return str(prompt_id)

    def get_history(self, prompt_id: str) -> Optional[Dict[str, Any]]:
        """查询单次执行结果；未就绪返回 None。"""
        if not prompt_id:
            return None
        data = self._get_json(f"/history/{quote(str(prompt_id))}")
        if not isinstance(data, dict):
            return None
        return data.get(str(prompt_id)) or data.get(prompt_id)

    def wait_for_completion(
        self,
        prompt_id: str,
        timeout: Optional[float] = None,
        poll_interval: Optional[float] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Optional[Dict[str, Any]]:
        """轮询 /history 直到执行完成（或超时），返回 history 条目。

        progress_callback 每次轮询拿到 status_str（如 "running"/"success"/"error"），
        供上层回传进度；无真实 step 数（WS 才有），此处仅作状态透传。
        """
        if not prompt_id:
            return None
        timeout = timeout if timeout is not None else self._config.poll_timeout
        poll_interval = poll_interval if poll_interval is not None else self._config.poll_interval
        deadline = time.monotonic() + timeout

        while True:
            entry = self.get_history(prompt_id)
            if entry:
                status = entry.get("status") or {}
                status_str = str(status.get("status_str") or "")
                if progress_callback:
                    progress_callback(status_str)
                if status.get("completed"):
                    return entry
                if status_str == "error":
                    logger.warning(f"[ComfyClient] 执行出错: {status.get('messages')}")
                    return entry  # 交由上层按 status_str 判定并诚实失败
            if time.monotonic() >= deadline:
                logger.warning(f"[ComfyClient] 等待生成完成超时 ({timeout:.0f}s): {prompt_id}")
                return None
            time.sleep(poll_interval)

    def collect_output_images(self, history_entry: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """从 history 条目提取输出图片列表（仅 type=output 的 images）。"""
        images: List[Dict[str, Any]] = []
        if not history_entry:
            return images
        outputs = history_entry.get("outputs") or {}
        for node_output in outputs.values():
            if not isinstance(node_output, dict):
                continue
            for img in node_output.get("images") or []:
                if isinstance(img, dict) and img.get("type") == "output":
                    images.append(img)
        return images

    def download_image(self, image: Dict[str, Any], output_dir: str) -> Optional[str]:
        """下载单张输出图到 output_dir，返回本地绝对路径；失败返回 None。

        只取 basename 落盘，避免 filename/subfolder 造成的路径穿越。
        """
        filename = image.get("filename") or ""
        if not filename:
            logger.warning("[ComfyClient] 输出图片缺少 filename")
            return None
        subfolder = image.get("subfolder") or ""
        img_type = image.get("type") or "output"
        dest = os.path.join(output_dir, os.path.basename(filename))
        try:
            os.makedirs(output_dir, exist_ok=True)
        except OSError as e:
            logger.warning(f"[ComfyClient] 创建输出目录失败 {output_dir}: {e}")
            return None
        ok = self._download(
            "/view",
            params={"filename": filename, "subfolder": subfolder, "type": img_type},
            dest_path=dest,
        )
        if ok and os.path.isfile(dest) and os.path.getsize(dest) > 0:
            return dest
        return None

    def download_all_images(self, images: List[Dict[str, Any]], output_dir: str) -> List[str]:
        """批量下载输出图片，返回成功落盘的本地路径列表。"""
        paths: List[str] = []
        for image in images:
            dest = self.download_image(image, output_dir)
            if dest:
                paths.append(dest)
        return paths

    # ═══════════════════════════════════════════════════════════
    # 输入侧（P2 img2img / 图生视频用，先薄实现）
    # ═══════════════════════════════════════════════════════════

    def upload_image(self, path: str, subfolder: str = "",
                     img_type: str = "input", overwrite: bool = True) -> Optional[str]:
        """上传本地图片到引擎输入目录，返回引擎侧文件名；失败返回 None。"""
        if not os.path.isfile(path):
            logger.error(f"[ComfyClient] 待上传图片不存在: {path}")
            return None
        try:
            session = self._new_session()
            try:
                with open(path, "rb") as f:
                    resp = session.post(
                        f"{self._config.base_url}/upload/image",
                        data={"subfolder": subfolder, "type": img_type,
                              "overwrite": str(overwrite).lower()},
                        files={"image": (os.path.basename(path), f)},
                        timeout=self._config.timeout,
                    )
                if resp.status_code != 200:
                    logger.warning(f"[ComfyClient] /upload/image 返回 HTTP {resp.status_code}")
                    return None
                return resp.json().get("name") or None
            finally:
                session.close()
        except (requests.exceptions.RequestException, ValueError, OSError) as e:
            logger.warning(f"[ComfyClient] 上传图片失败 {path}: {e}")
            return None

    def image_url(self, image: Dict[str, Any]) -> str:
        """拼接输出图片的 /view 完整 URL（供上层直接返回给前端播放/展示）。"""
        filename = quote(image.get("filename") or "")
        subfolder = quote(image.get("subfolder") or "")
        img_type = quote(image.get("type") or "output")
        return f"{self._config.base_url}/view?filename={filename}&subfolder={subfolder}&type={img_type}"

    # ═══════════════════════════════════════════════════════════
    # 低层 HTTP 工具
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _new_session() -> requests.Session:
        """创建忽略系统代理的会话（本地 localhost 连接关键配置）。"""
        session = requests.Session()
        session.trust_env = False
        return session

    def _get_json(self, path: str, *, params: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        """GET 并解析 JSON；连接失败 / 非 200 / 非 JSON 一律返回 None。"""
        try:
            session = self._new_session()
            try:
                resp = session.get(f"{self._config.base_url}{path}", params=params,
                                   timeout=self._config.timeout)
                if resp.status_code != 200:
                    logger.warning(f"[ComfyClient] GET {path} 返回 HTTP {resp.status_code}")
                    return None
                return resp.json()
            finally:
                session.close()
        except requests.exceptions.RequestException as e:
            logger.warning(f"[ComfyClient] GET {path} 失败: {e}")
            return None
        except ValueError as e:
            logger.warning(f"[ComfyClient] GET {path} 响应非合法 JSON: {e}")
            return None

    def _post_json(self, path: str, *, body: Dict[str, Any]) -> Optional[Any]:
        """POST JSON 并解析响应；连接失败 / 非 200 / 非 JSON 一律返回 None。"""
        try:
            session = self._new_session()
            try:
                resp = session.post(f"{self._config.base_url}{path}", json=body,
                                    timeout=self._config.timeout)
                if resp.status_code != 200:
                    logger.warning(f"[ComfyClient] POST {path} 返回 HTTP {resp.status_code}")
                    return None
                return resp.json()
            finally:
                session.close()
        except requests.exceptions.RequestException as e:
            logger.warning(f"[ComfyClient] POST {path} 失败: {e}")
            return None
        except ValueError as e:
            logger.warning(f"[ComfyClient] POST {path} 响应非合法 JSON: {e}")
            return None

    def _download(self, path: str, *, params: Dict[str, Any], dest_path: str) -> bool:
        """GET 二进制流式写入 dest_path，成功返回 True。"""
        try:
            session = self._new_session()
            try:
                with session.get(f"{self._config.base_url}{path}", params=params,
                                 timeout=self._config.timeout, stream=True) as resp:
                    if resp.status_code != 200:
                        logger.warning(f"[ComfyClient] 下载失败 {path}: HTTP {resp.status_code}")
                        return False
                    with open(dest_path, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                return True
            finally:
                session.close()
        except requests.exceptions.RequestException as e:
            logger.warning(f"[ComfyClient] 下载失败 {path}: {e}")
            return False
        except OSError as e:
            logger.warning(f"[ComfyClient] 写文件失败 {dest_path}: {e}")
            return False


# 全局单例便捷引用
comfy_client = ComfyClient.get_instance()


if __name__ == "__main__":
    """命令行自测：探测引擎 + 用假 history 条目验证结果提取与 URL 拼装（不依赖真实引擎）。"""
    logging.basicConfig(level=logging.INFO)
    import json

    # 1. 连接性诊断（引擎未启动时给出非空诊断信息即可）
    diagnosis = comfy_client.diagnose()

    # 2. 假 history 条目：模拟一个 SaveImage 节点产出两张图
    fake_entry = {
        "prompt": [],
        "outputs": {
            "9": {"images": [
                {"filename": "ComfyUI_00001_.png", "subfolder": "", "type": "output"},
                {"filename": "ComfyUI_00002_.png", "subfolder": "batch", "type": "output"},
                {"filename": "ignored.tmp", "subfolder": "temp", "type": "temp"},
            ]},
        },
        "status": {"status_str": "success", "completed": True, "messages": []},
    }
    images = comfy_client.collect_output_images(fake_entry)
    urls = [comfy_client.image_url(img) for img in images]

    logger.info(json.dumps({
        "diagnose": diagnosis,
        "collected_image_count": len(images),
        "collected_images": images,
        "image_urls": urls,
    }, ensure_ascii=False, indent=2))