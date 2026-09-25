"""ComfyUI 内置引擎生命周期管理 + workflow 执行落箱（P2 · 文生图闭环）。

职责：
  - 引擎生命周期：探测引擎目录 → 自动拉起进程 → 就绪探测 → 停止/释放。
  - workflow 执行：把 `workflow_importer` 产出的 graph prompt 交给 `comfy_client`
    提交执行，下载输出图片并落 `canvas_inbox_dir`，返回可播放 URL。

合规提醒（方案 §4/§11 硬闸门）：本模块仅「就地拉起已安装的引擎进程做开发验证」，
内置引擎的打包 / 发行必须在 GPL 合规结论通过后再做，此 provider 不负责打包。

设计原则：
  - 线程安全单例；调用方应在 worker 线程调用，本模块不阻塞 Qt 主线程。
  - 显存检测复用 `gpu_acceleration.detect_gpu()`，不重复写硬件检测逻辑。
  - 落箱路径复用 `canvas_bridge.canvas_inbox_dir()`，端口复用 `DEFAULT_PORT`。
  - 失败不抛裸异常：启动 / 提交 / 下载问题记日志并在返回值中诚实说明。
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

from app.core.ai.comfy_client import comfy_client

logger = logging.getLogger(__name__)

# 内置引擎默认监听（与 comfy_client.ComfyConfig 默认一致）
_DEFAULT_HOST = "http://127.0.0.1"
_DEFAULT_PORT = 8188

_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)


class ComfyEngineProvider:
    """ComfyUI 内置引擎生命周期管理与执行落箱 —— 线程安全单例。

    使用方式：
        from app.core.ai.comfy_provider import comfy_provider
        result = comfy_provider.run_workflow(graph_prompt)
        if result["ok"]:
            urls = result["urls"]  # 直接喂给画布播放
    """

    _instance: Optional['ComfyEngineProvider'] = None
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
        self._host = _DEFAULT_HOST
        self._port = _DEFAULT_PORT
        self._process: Optional[subprocess.Popen] = None  # 引擎子进程句柄

    @classmethod
    def get_instance(cls) -> 'ComfyEngineProvider':
        return cls()

    # ═══════════════════════════════════════════════════════════
    # 引擎生命周期
    # ═══════════════════════════════════════════════════════════

    def is_running(self) -> bool:
        """引擎是否在线（进程存活且 API 响应）。"""
        return self._is_process_alive() and comfy_client.is_available()

    def has_engine(self) -> bool:
        """是否检测到内置引擎目录（仅文件系统检查，不发网络请求）。

        供 dry-run / 演练模式快速判断「引擎是否已安装」，避免触发缓慢的 /system_stats 探测。
        """
        return self._find_engine_dir() is not None

    def ensure_engine(self, timeout: float = 120.0) -> bool:
        """确保引擎就绪：已在线则直接返回，否则尝试自动拉起。"""
        if comfy_client.is_available():
            return True
        return self.start_engine(timeout=timeout)

    def start_engine(self, timeout: float = 120.0) -> bool:
        """拉起内置引擎进程并等待就绪。

        流程：探测引擎目录 → 干净启动（监听 127.0.0.1，不对外网）→ 轮询 /system_stats
        直到就绪。引擎目录缺失或进程提前退出时诚实返回 False，不假成功。
        """
        with self._lock:
            # 已在运行 → 幂等返回
            if self._is_process_alive() and comfy_client.is_available(force_check=True):
                logger.info("[ComfyProvider] ComfyUI 引擎已在运行，无需重复启动")
                return True

            engine_dir = self._find_engine_dir()
            if not engine_dir:
                logger.error("[ComfyProvider] 未找到 ComfyUI 引擎目录（main.py），无法自动拉起")
                return False

            python = self._find_engine_python(engine_dir)
            cmd = [
                python,
                os.path.join(engine_dir, "main.py"),
                "--port", str(self._port),
                "--listen", "127.0.0.1",  # 仅本地监听，避免开放到局域网
            ]

            # 同步客户端端口后启动
            comfy_client.configure(host=self._host, port=self._port)
            try:
                if sys.platform == "win32":
                    self._process = subprocess.Popen(
                        cmd, cwd=engine_dir,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=self._no_window_flags(),
                    )
                else:
                    self._process = subprocess.Popen(
                        cmd, cwd=engine_dir,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
            except OSError as e:
                logger.error(f"[ComfyProvider] 启动 ComfyUI 引擎失败: {e}")
                self._process = None
                return False

            logger.info(f"[ComfyProvider] 正在拉起 ComfyUI 引擎（{python} main.py --port {self._port}）")

            # 轮询就绪，进程若提前退出则立即失败
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if self._process.poll() is not None:
                    logger.error(f"[ComfyProvider] 引擎进程提前退出，返回码 {self._process.returncode}")
                    self._process = None
                    return False
                if comfy_client.is_available(force_check=True):
                    logger.info("[ComfyProvider] ComfyUI 引擎已就绪")
                    return True
                time.sleep(1.0)

            logger.error(f"[ComfyProvider] 等待引擎就绪超时（{timeout:.0f}s）")
            return False

    def stop_engine(self) -> bool:
        """停止引擎进程；无本地句柄视为已停止，返回 True。"""
        with self._lock:
            process = self._process
            self._process = None
            if process is None or process.poll() is not None:
                return True
            try:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                logger.info("[ComfyProvider] ComfyUI 引擎已停止")
                return True
            except OSError as e:
                logger.warning(f"[ComfyProvider] 停止引擎失败: {e}")
                return False

    def release_for_export(self) -> bool:
        """剪辑导出前调用：停止引擎释放显存，避免与导出争抢 GPU。"""
        logger.info("[ComfyProvider] 剪辑导出前释放 ComfyUI 引擎显存")
        return self.stop_engine()

    def engine_status(self) -> Dict[str, Any]:
        """返回引擎状态报告（目录 / 进程 / 诊断 / 安装指引），供 UI 或日志判读。

        引擎目录缺失且无本地进程时不做网络探测（引擎必然不在线），改用静态诊断并附
        安装指引，避免 /system_stats 的 8s 超时拖慢「查看状态」；其余情况才发一次探测。
        """
        engine_dir = self._find_engine_dir()
        valid = bool(engine_dir)
        process_alive = self._is_process_alive()

        if valid or process_alive:
            # 目录在或进程在，才值得发一次网络探测判断 API 是否就绪
            diagnose = comfy_client.diagnose()
            if not diagnose["available"]:
                # 目录就绪但 API 未响应 → 语境从「连接失败」收敛为「可自动拉起」
                diagnose["suggestion"] = (
                    "内置 ComfyUI 引擎目录已就绪但尚未运行，导入工作流时会自动拉起，"
                    "无需额外操作。"
                )
        else:
            # 引擎未安装且未运行：静态诊断，零网络开销
            diagnose = {
                "available": False,
                "base_url": f"{self._host}:{self._port}",
                "error": "未检测到内置 ComfyUI 引擎",
                "suggestion": self._install_hint(),
            }

        return {
            "engine_dir": engine_dir or "",
            "engine_valid": valid,
            "process_alive": process_alive,
            "host": self._host,
            "port": self._port,
            "diagnose": diagnose,
        }

    # ═══════════════════════════════════════════════════════════
    # workflow 执行 + 落箱
    # ═══════════════════════════════════════════════════════════

    def run_workflow(
        self,
        graph_prompt: Dict[str, Any],
        timeout: Optional[float] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """执行 graph prompt 并把输出图片落 `canvas_inbox_dir`。

        返回：
            {
              "ok": bool,
              "prompt_id": str,
              "images": [原始 image 元数据...],
              "paths":  [本地绝对路径...],
              "urls":   [可播放 /inbox_file/ URL...],
              "error":  str,
            }
        任一步失败均返回 ok=False 且 error 非空，不抛异常。
        """
        empty_result: Dict[str, Any] = {
            "ok": False, "prompt_id": "", "images": [], "paths": [], "urls": [], "error": "",
        }
        if not graph_prompt:
            empty_result["error"] = "空的 graph_prompt，无法执行"
            return empty_result

        if not self.ensure_engine():
            empty_result["error"] = "ComfyUI 引擎未就绪，无法执行（见 engine_status 诊断）"
            return empty_result

        prompt_id = comfy_client.submit_prompt(graph_prompt)
        if not prompt_id:
            empty_result["error"] = "提交 workflow 失败（引擎返回异常）"
            return empty_result
        empty_result["prompt_id"] = prompt_id

        entry = comfy_client.wait_for_completion(
            prompt_id, timeout=timeout, progress_callback=progress_callback
        )
        if not entry:
            empty_result["error"] = "执行超时或引擎无响应"
            return empty_result

        status = entry.get("status") or {}
        if status.get("status_str") == "error":
            messages = status.get("messages") or []
            empty_result["error"] = "; ".join(str(m) for m in messages) or "引擎执行出错"
            return empty_result

        images = comfy_client.collect_output_images(entry)
        if not images:
            empty_result["error"] = "执行完成但无输出图片"
            return empty_result

        inbox = self._inbox_dir()
        paths = comfy_client.download_all_images(images, inbox)
        if not paths:
            empty_result["error"] = "输出图片下载失败"
            return empty_result

        urls = [self._inbox_url(os.path.basename(p)) for p in paths]
        return {
            "ok": True, "prompt_id": prompt_id, "images": images,
            "paths": paths, "urls": urls, "error": "",
        }

    def run_workflow_from_json(
        self,
        workflow_json: Dict[str, Any],
        dry_run: bool = False,
        timeout: Optional[float] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """解析 workflow JSON 并执行；dry_run=True 时引擎缺位仍走通「解析→落箱」链路。

        本方法是画布端到端链路的统一入口：无论输入是 UI workflow（含 nodes/links）
        还是 graph 格式，先经 `workflow_importer.parse` 规范成 graph prompt，再按模式分流：

          · dry_run=True  ：演练模式。不真实拉起/提交引擎，仅完成解析 + 结构校验，
                           返回可执行性与诊断、引擎安装状态与落箱目录，前端据此提示
                           「工作流已就绪 / 引擎未安装」。
          · dry_run=False ：真实执行。复用 `run_workflow` 完成 提交→轮询→下载→落箱。

        返回键统一含：ok / dry_run / raw_format / node_ids / class_types / errors /
        warnings / missing_nodes / engine_available / engine_running / inbox_dir /
        prompt_id / images / paths / urls / message / error。失败不抛异常。
        """
        from app.core.ai.workflow_importer import workflow_importer

        result: Dict[str, Any] = {
            "ok": False,
            "dry_run": bool(dry_run),
            "raw_format": "unknown",
            "node_ids": [],
            "class_types": [],
            "errors": [],
            "warnings": [],
            "missing_nodes": [],
            "engine_available": self.has_engine(),
            "engine_running": self._is_process_alive(),  # 仅本地句柄判断，避免 dry-run 触发网络探测
            "inbox_dir": self._inbox_dir(),
            "prompt_id": "",
            "images": [],
            "paths": [],
            "urls": [],
            "message": "",
            "error": "",
        }

        if not isinstance(workflow_json, dict) or not workflow_json:
            result["error"] = "空的 workflow_json，无法解析"
            return result

        parse_result = workflow_importer.parse(workflow_json)
        result["raw_format"] = parse_result.raw_format
        result["node_ids"] = parse_result.node_ids
        result["class_types"] = parse_result.class_types
        result["errors"] = parse_result.errors
        result["warnings"] = parse_result.warnings
        result["missing_nodes"] = parse_result.missing_nodes

        if not parse_result.is_executable:
            result["error"] = "；".join(parse_result.errors) or "workflow 解析后不可执行"
            return result

        graph_prompt = parse_result.graph_prompt

        if dry_run:
            # 演练模式：解析→落箱链路已走通，诚实回报引擎安装状态，不隐含「已可运行」
            node_count = len(graph_prompt)
            type_count = len(set(parse_result.class_types))
            result["ok"] = True
            result["message"] = (
                f"dry-run 演练通过：解析出 {node_count} 个节点、{type_count} 种节点类型；"
                f"引擎{'已安装' if result['engine_available'] else '未安装'}；"
                f"生成结果将落箱到 {result['inbox_dir']}"
            )
            return result

        # 真实执行：附加解析诊断后复用 run_workflow 的 提交→轮询→下载→落箱
        exec_result = self.run_workflow(
            graph_prompt, timeout=timeout, progress_callback=progress_callback
        )
        exec_result["dry_run"] = False
        exec_result["raw_format"] = parse_result.raw_format
        exec_result["node_ids"] = parse_result.node_ids
        exec_result["class_types"] = parse_result.class_types
        exec_result["warnings"] = parse_result.warnings
        exec_result["missing_nodes"] = parse_result.missing_nodes
        exec_result["engine_available"] = result["engine_available"]
        exec_result["engine_running"] = self._is_process_alive()
        exec_result["inbox_dir"] = result["inbox_dir"]
        return exec_result

    # ═══════════════════════════════════════════════════════════
    # 硬资源与落箱工具
    # ═══════════════════════════════════════════════════════════

    def gpu_memory_mb(self) -> int:
        """检测 GPU 显存（MB），复用 gpu_acceleration.detect_gpu；失败返回 0。"""
        try:
            from app.core.gpu_acceleration import detect_gpu

            return int(detect_gpu().memory_mb)
        except Exception as e:
            logger.debug(f"[ComfyProvider] 检测显存失败: {e}")
            return 0

    @staticmethod
    def _inbox_dir() -> str:
        """画布收件目录（惰性取 canvas_bridge，避免循环导入与重依赖）。"""
        from app.core.canvas_bridge import canvas_inbox_dir

        return canvas_inbox_dir()

    @staticmethod
    def _inbox_url(filename: str) -> str:
        """拼接可播放的 inbox 文件 URL（端口复用 canvas_bridge.DEFAULT_PORT）。"""
        from app.core.canvas_bridge import DEFAULT_PORT

        return f"http://127.0.0.1:{DEFAULT_PORT}/inbox_file/{quote(filename)}"

    # ═══════════════════════════════════════════════════════════
    # 私有工具
    # ═══════════════════════════════════════════════════════════

    def _is_process_alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @staticmethod
    def _no_window_flags() -> int:
        """Windows 下隐藏子进程控制台窗口。"""
        if sys.platform == "win32":
            return 0x08000000  # CREATE_NO_WINDOW
        return 0

    @staticmethod
    def _common_install_candidates() -> List[str]:
        """常见安装位置候选（有限深度，只做一次 listdir，不做全盘递归）。

        背景（2026-09-25 实测）：本机装了秋叶整合包
        ``~/Desktop/ComfyUI-aki-v1.7/ComfyUI`` 与源码版 ``D:/_comfy_compare/ComfyUI``，
        但两者都不在原固定候选里 ⇒ 画布顶栏误报「引擎未安装」。
        这里补「桌面下的 ComfyUI*/ComfyUI」与「项目同级目录」两类常见位置。
        """
        found: List[str] = []
        try:
            home = os.path.expanduser("~")
            for base in (os.path.join(home, "Desktop"), os.path.join(home, "桌面")):
                if not os.path.isdir(base):
                    continue
                for name in sorted(os.listdir(base)):
                    d = os.path.join(base, name, "ComfyUI")
                    if os.path.isfile(os.path.join(d, "main.py")):
                        found.append(d)
        except OSError as e:
            logger.debug("扫描桌面 ComfyUI 安装失败: %s", e)
        try:
            parent = os.path.dirname(_PROJECT_ROOT)
            for name in sorted(os.listdir(parent)):
                d = os.path.join(parent, name, "ComfyUI")
                if os.path.isfile(os.path.join(d, "main.py")):
                    found.append(d)
        except OSError as e:
            logger.debug("扫描项目同级 ComfyUI 安装失败: %s", e)
        return found

    @staticmethod
    def _own_python_candidates(engine_dir: str) -> List[str]:
        """引擎**自带**解释器的候选路径（含整合包的常见布局）。

        覆盖三类布局：
          · ``<引擎>/python_embeded/``  —— 官方便携包
          · ``<引擎>/venv/``            —— 源码版自建虚拟环境
          · ``<引擎>/../python/``       —— **秋叶整合包**（解释器在引擎上一级）
        """
        if sys.platform == "win32":
            rel = [
                ("python_embeded", "python.exe"),
                ("venv", os.path.join("Scripts", "python.exe")),
                (os.path.join("..", "python"), "python.exe"),
                (os.path.join("..", "python_embeded"), "python.exe"),
            ]
        else:
            rel = [
                ("python_embeded", os.path.join("bin", "python")),
                ("venv", os.path.join("bin", "python")),
                (os.path.join("..", "python"), os.path.join("bin", "python")),
            ]
        return [os.path.normpath(os.path.join(engine_dir, a, b)) for a, b in rel]

    @classmethod
    def _has_own_python(cls, engine_dir: str) -> bool:
        """引擎是否自带可用解释器（决定它能不能被直接拉起）。"""
        return any(os.path.isfile(p) for p in cls._own_python_candidates(engine_dir))

    @staticmethod
    def _find_engine_dir() -> Optional[str]:
        """探测 ComfyUI 引擎目录（含 main.py）。

        优先级：环境变量 → 项目内 → 常见安装位置（桌面 / 项目同级）。
        在候选中**优先返回自带解释器的那一个**，因为只有它才拉得起来；
        若都没自带解释器，则返回首个命中项（由 ``_find_engine_python`` 回退当前解释器）。
        选中的目录会记 INFO 日志，避免「不知道用的是哪一份」。
        """
        candidates: List[str] = []
        env_dir = os.environ.get("SHIGUANG_COMFY_HOME")
        if env_dir:
            candidates.append(env_dir)
        candidates += [
            os.path.join(_PROJECT_ROOT, "thirdparty", "ComfyUI"),
            os.path.join(_PROJECT_ROOT, "comfyui"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "comfyui"),
        ]
        candidates += ComfyEngineProvider._common_install_candidates()

        fallback: Optional[str] = None
        for directory in candidates:
            if not directory or not os.path.isfile(os.path.join(directory, "main.py")):
                continue
            if ComfyEngineProvider._has_own_python(directory):
                logger.info("ComfyUI 引擎目录: %s（自带解释器，可直接拉起）", directory)
                return directory
            if fallback is None:
                fallback = directory
        if fallback:
            logger.info("ComfyUI 引擎目录: %s（未发现自带解释器，将回退当前解释器）", fallback)
        return fallback

    @staticmethod
    def _install_hint() -> str:
        """引擎未安装时的安装指引（含期望目录与环境变量），供 UI 直接展示。"""
        candidates = [
            os.path.join(_PROJECT_ROOT, "thirdparty", "ComfyUI"),
            os.path.join(_PROJECT_ROOT, "comfyui"),
        ]
        return (
            "未检测到内置 ComfyUI 引擎：请将 ComfyUI 源码放到 "
            + " 或 ".join(candidates)
            + "（也可设置环境变量 SHIGUANG_COMFY_HOME 指向引擎目录），"
            "目录下需包含 main.py。"
        )

    @staticmethod
    def _find_engine_python(engine_dir: str) -> str:
        """定位引擎侧 Python 解释器（便携版 / venv / **整合包上一级**），回退当前解释器。

        修正（2026-09-25）：原实现只找 ``<引擎>/python_embeded`` 与 ``<引擎>/venv``，
        于是**秋叶整合包**（解释器在 ``<引擎>/../python/python.exe``）命中不了 ⇒
        静默回退到当前解释器（拾光剪影 venv，缺 ComfyUI 依赖）⇒ 拉起必然失败。
        现复用 ``_own_python_candidates``，与 ``_has_own_python`` 口径一致。
        """
        for candidate in ComfyEngineProvider._own_python_candidates(engine_dir):
            if os.path.isfile(candidate):
                return candidate
        logger.info(
            "引擎目录 %s 未发现自带解释器，回退当前解释器（可能缺引擎依赖）", engine_dir)
        return sys.executable


# 全局单例便捷引用
comfy_provider = ComfyEngineProvider.get_instance()


if __name__ == "__main__":
    """命令行自测：打印引擎状态 / 落箱目录 / 显存 / URL 拼装（不拉起真实引擎）。"""
    logging.basicConfig(level=logging.INFO)
    import json

    logger.info(json.dumps({
        "engine_status": comfy_provider.engine_status(),
        "inbox_dir": comfy_provider._inbox_dir(),
        "sample_inbox_url": comfy_provider._inbox_url("sample_00001_.png"),
        "gpu_memory_mb": comfy_provider.gpu_memory_mb(),
    }, ensure_ascii=False, indent=2))