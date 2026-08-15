"""
Ollama 客户端模块 (OllamaClient)
================================
本地大模型 Ollama 集成，支持本地 AI 推理，无需云端 API。

┌──────────────────────────────────────────────────────────────┐
│  架构概述：                                                   │
│    单例模式 OllamaClient → HTTP 调用 localhost:11434          │
│    ├── 状态检测：diagnose() / is_available() / is_installed()│
│    ├── 模型管理：list_models() / pull_model() / delete_model()│
│    ├── 推理能力：generate() / chat() / embeddings()          │
│    └── 配置持久化：data/ollama_config.json                   │
├──────────────────────────────────────────────────────────────┤
│  关键修复（2026-06-13）：                                     │
│    ① host 自动补全 http:// − 修复 URL 缺少协议前缀的 bug     │
│    ② trust_env=False − 忽略系统代理，避免本地连接失败         │
│    ③ start_service() − 先检测是否已运行，避免重复启动         │
│    ④ diagnose() − 强制重新检测，不依赖缓存                    │
└──────────────────────────────────────────────────────────────┘
"""

import json
import requests
import subprocess
import os
import time
import threading
from typing import Optional, Dict, List, Any, Generator, Callable
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class OllamaModel:
    """Ollama 模型信息数据类

    字段:
      name: 模型名（如 "qwen2:7b"）
      size: 模型大小（人类可读格式，如 "4.4GB"）
      modified_at: 最后修改时间戳
      digest: SHA256 摘要值
    """
    name: str
    size: str
    modified_at: str
    digest: str

    @property
    def display_name(self) -> str:
        """显示名称：确保始终带有 :tag 后缀，如 llama3 → llama3:latest"""
        if ":" in self.name:
            return self.name
        return f"{self.name}:latest"


@dataclass
class OllamaConfig:
    """Ollama 连接配置

    默认连接本地 Ollama 服务（默认端口 11434）。
    host 必须以 http:// 或 https:// 开头。
    """
    host: str = "http://localhost"   # 服务地址（含协议前缀）
    port: int = 11434                # 默认 Ollama API 端口
    timeout: int = 300               # 推理超时（秒）

    @property
    def base_url(self) -> str:
        """拼接完整 URL 前缀，如 http://localhost:11434"""
        return f"{self.host}:{self.port}"


class OllamaClient:
    """Ollama 客户端 - 线程安全单例

    使用 __new__ + _lock 实现线程安全的懒加载单例模式。
    通过 HTTP REST API 与本地 Ollama 服务通信。

    核心 API 端点：
      GET  /api/tags       → 列出已安装模型
      POST /api/pull       → 拉取模型
      POST /api/generate   → 文本生成
      POST /api/chat       → 对话
      POST /api/embeddings → 文本嵌入
      DELETE /api/delete   → 删除模型
      POST /api/show       → 模型详细信息
    """

    _instance: Optional['OllamaClient'] = None
    _lock = threading.Lock()

    def __new__(cls):
        """线程安全的单例构造。

        使用双重检查锁定（Double-Check Locking）模式：
          第一层 if（无锁快速路径）：避免每次都加锁
          第二层 if（持锁安全性）：防止并发创建多个实例
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    # 标记未初始化，__init__ 中会检测并跳过
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """初始化（仅首次调用时执行）"""
        if self._initialized:
            return   # 防止单例重复初始化
        self._initialized = True

        # ── 核心状态 ──
        self._config = OllamaConfig()                  # 连接配置
        self._available: Optional[bool] = None         # 服务可用性缓存（None=未检测）
        self._models: List[OllamaModel] = []           # 模型列表缓存
        self._last_check: float = 0                    # 上次检测时间戳（用于缓存控制）

        # ── 配置文件路径：{项目根}/data/ollama_config.json ──
        import os
        config_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
            "data"
        )
        os.makedirs(config_dir, exist_ok=True)
        self._config_file = os.path.join(config_dir, "ollama_config.json")

        self._load_config()

    @property
    def base_url(self) -> str:
        """获取 Ollama API 访问基础 URL"""
        return self._config.base_url

    # ═══════════════════════════════════════════════════════════
    # 状态检测（关键修复区域）
    # ═══════════════════════════════════════════════════════════

    def is_available(self, force_check: bool = False) -> bool:
        """检查 Ollama 服务是否可用。

        【缓存策略】
          默认缓存 60 秒，避免频繁 HTTP 请求。
          设置 force_check=True 可强制重新检测（绕过缓存）。

        【代理处理】
          使用 requests.Session(trust_env=False) 创建独立会话，
          确保本地 localhost 连接不走系统代理（这是之前检测失败的主要原因之一）。

        返回:
          True  → 服务正常响应（HTTP 200）
          False → 连接失败、超时或非 200 响应
        """
        now = time.time()

        # 缓存未过期且不强制刷新 → 直接返回缓存值
        if not force_check and self._available is not None and now - self._last_check < 60:
            return self._available

        try:
            # 创建忽略系统代理的独立会话
            session = requests.Session()
            session.trust_env = False   # 关键：不走系统 HTTP_PROXY/HTTPS_PROXY
            response = session.get(
                f"{self.base_url}/api/tags",
                timeout=8               # 超时 8 秒（原 5 秒，提高容错）
            )
            session.close()
            self._available = response.status_code == 200
            if not self._available:
                logger.warning(
                    f"Ollama 服务响应异常: HTTP {response.status_code} "
                    f"(url={self.base_url}/api/tags)"
                )
            self._last_check = now
            return self._available
        except requests.exceptions.ConnectionError as e:
            logger.warning(
                f"无法连接 Ollama 服务 ({self.base_url}): {e}\n"
                f"请确认:\n"
                f"  1. Ollama 已安装: 运行 'ollama --version'\n"
                f"  2. 服务已启动: 运行 'ollama serve' 或打开 Ollama 桌面应用\n"
                f"  3. 端口未被占用: {self.base_url}"
            )
            self._available = False
            self._last_check = now
            return False
        except requests.exceptions.Timeout:
            logger.warning(f"Ollama 服务连接超时 ({self.base_url})，服务可能未启动")
            self._available = False
            self._last_check = now
            return False
        except Exception as e:
            logger.warning(f"Ollama 服务不可用: {e}")
            self._available = False
            self._last_check = now
            return False

    def is_installed(self) -> bool:
        """检查 Ollama 是否已安装（通过执行 ollama --version 命令检测）。

        返回:
          True  → 命令返回码为 0，Ollama 已安装
          False → 命令未找到（FileNotFoundError）或执行失败
        """
        try:
            result = subprocess.run(
                ["ollama", "--version"],
                capture_output=True, text=True, timeout=5,
                # CREATE_NO_WINDOW: Windows 下不弹黑框
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            if result.returncode == 0:
                logger.info(f"Ollama 已安装: {result.stdout.strip()}")
                return True
            return False
        except FileNotFoundError:
            # ollama 命令不在系统 PATH 中
            logger.warning("Ollama 未找到 — 请从 https://ollama.com 下载安装")
            return False
        except Exception as e:
            logger.warning(f"检测 Ollama 安装状态失败: {e}")
            return False

    def diagnose(self) -> Dict[str, Any]:
        """诊断 Ollama 完整状态，返回详细报告。

        与 is_available() 的区别：
          • diagnose() 总是强制重新检测，不使用缓存
          • 返回结构化报告（installed / service_running / error / suggestion）
          • 结果会同步更新缓存（_available / _last_check）

        返回结构:
          {
            "installed": bool,        # 是否已安装 ollama 命令行工具
            "service_running": bool,  # 服务是否正常响应
            "base_url": str,          # 使用的 API 地址
            "error": str,             # 错误描述
            "suggestion": str,        # 解决问题的建议
          }
        """
        report = {
            "installed": self.is_installed(),
            "service_running": False,
            "base_url": self.base_url,
            "error": "",
            "suggestion": "",
        }

        # 未安装 → 直接返回，不尝试连接
        if not report["installed"]:
            report["suggestion"] = "请从 https://ollama.com 下载并安装 Ollama"
            return report

        # 已安装 → 强制重新检测服务状态
        try:
            session = requests.Session()
            session.trust_env = False   # 忽略系统代理
            response = session.get(f"{self.base_url}/api/tags", timeout=10)
            session.close()
            report["service_running"] = response.status_code == 200
            if not report["service_running"]:
                report["error"] = f"HTTP {response.status_code}"
                report["suggestion"] = (
                    "Ollama 已安装但服务未正常响应。请:\n"
                    "  1. 打开 Ollama 桌面应用，等待图标出现在系统托盘\n"
                    "  2. 或在终端运行: ollama serve"
                )
        except requests.exceptions.ConnectionError:
            report["error"] = "连接被拒绝"
            report["suggestion"] = (
                "Ollama 已安装但服务未启动。请:\n"
                "  1. 从开始菜单启动 'Ollama' 应用\n"
                "  2. 或在终端运行: ollama serve"
            )
        except requests.exceptions.Timeout:
            report["error"] = "连接超时"
            report["suggestion"] = (
                "Ollama 服务响应超时，请检查端口 11434 是否被占用或防火墙设置"
            )
        except Exception as e:
            report["error"] = str(e)
            report["suggestion"] = "请检查 Ollama 是否正确安装和运行"

        # 将诊断结果同步到缓存状态
        self._available = report["service_running"]
        self._last_check = time.time()

        return report

    @staticmethod
    def format_diagnose_report(report: Dict[str, Any]) -> str:
        """把 diagnose() 结果格式化为给用户看的中文说明。"""
        if not report:
            return "无法诊断 Ollama 状态"
        lines = [f"地址: {report.get('base_url', '')}"]
        if not report.get("installed"):
            lines.append("状态: 未安装")
        elif report.get("service_running"):
            lines.append("状态: 服务运行中")
        else:
            lines.append("状态: 已安装但服务未运行")
        err = (report.get("error") or "").strip()
        if err:
            lines.append(f"错误: {err}")
        sug = (report.get("suggestion") or "").strip()
        if sug:
            lines.append(f"建议:\n{sug}")
        return "\n".join(lines)

    def diagnose_user_message(self) -> str:
        """强制诊断并返回用户可读文案。"""
        return self.format_diagnose_report(self.diagnose())

    def start_service(self) -> bool:
        """启动 Ollama 服务进程（智能启动：先检测是否已在运行）。

        使用场景：
          • 设置面板中用户点击「启动服务」按钮
          • ModelManagementModule 自动尝试启动

        流程：
          ① 先尝试连接 localhost:11434，若已运行则直接返回 True
          ② 若未运行，调用 ollama serve 后台启动
          ③ 返回 True 表示启动命令已发出（不保证启动成功）

        返回值：
          True  → 已在运行 或 启动命令已成功发出
          False → ollama 命令未找到（FileNotFoundError）
        """
        import platform

        # ① 先检测是否已在运行（3秒超时快速检查）
        try:
            session = requests.Session()
            session.trust_env = False
            resp = session.get(f"{self.base_url}/api/tags", timeout=3)
            session.close()
            if resp.status_code == 200:
                logger.info("Ollama 服务已在运行，无需启动")
                self._available = True
                self._last_check = time.time()
                return True
        except Exception:
            # 未运行是预期情况，吞掉异常继续尝试启动
            pass

        # ② 启动 ollama serve 后台进程
        try:
            if platform.system() == "Windows":
                # Windows: 隐藏窗口启动
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                subprocess.Popen(
                    ["ollama", "serve"],
                    startupinfo=startupinfo,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            else:
                # macOS/Linux: 脱离终端启动
                subprocess.Popen(
                    ["ollama", "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
            logger.info("Ollama 服务启动命令已发出")
            # 清除缓存，让后续检测重新请求
            self._available = None
            return True
        except FileNotFoundError:
            logger.error("找不到 ollama 命令，请确认 Ollama 已安装且位于 PATH 中")
            return False
        except Exception as e:
            logger.error(f"启动 Ollama 服务失败: {e}")
            return False
    
    def _load_config(self):
        """加载持久化配置文件 data/ollama_config.json。

        关键防护：自动补全 host 的 http:// 前缀。
        如果用户手动编辑 JSON 写了 "host": "localhost"（缺少协议），
        会导致 requests 库报 "No connection adapters" 错误。
        此方法自动检测并补全 http:// 前缀。
        """
        try:
            if os.path.exists(self._config_file):
                with open(self._config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if "host" in data:
                    host = data["host"].strip()
                    # 【关键修复】自动补全协议前缀
                    # 原因：配置文件之前可能只写了 "localhost" 而非 "http://localhost"
                    # 缺少协议导致 requests.get("localhost:11434/api/tags") 报错：
                    #   No connection adapters were found
                    if not host.startswith("http://") and not host.startswith("https://"):
                        host = f"http://{host}"
                    self._config.host = host
                if "port" in data:
                    self._config.port = int(data["port"])
                if "timeout" in data:
                    self._config.timeout = int(data["timeout"])
                if "active_model" in data:
                    self._active_model = data["active_model"]
        except Exception:
            # 配置文件损坏时静默忽略，使用默认配置
            pass

    def save_config(self, host: str = None, port: int = None, timeout: int = None, active_model: str = None):
        """保存配置到 data/ollama_config.json（增量更新）。"""
        try:
            if host is not None:
                self._config.host = host
            if port is not None:
                self._config.port = port
            if timeout is not None:
                self._config.timeout = timeout
            if active_model is not None:
                self._active_model = active_model

            data = {
                "host": self._config.host,
                "port": self._config.port,
                "timeout": self._config.timeout,
            }
            if hasattr(self, '_active_model') and self._active_model:
                data["active_model"] = self._active_model

            with open(self._config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存 Ollama 配置失败: {e}")
    
    def list_models(self, force_refresh: bool = False) -> List[OllamaModel]:
        """获取已安装的模型列表"""
        if not force_refresh and self._models:
            return self._models

        if not self.is_available(force_check=True):
            return []
        
        try:
            session = requests.Session()
            session.trust_env = False  # 关键：不走系统 HTTP_PROXY/HTTPS_PROXY
            response = session.get(
                f"{self.base_url}/api/tags",
                timeout=10
            )
            session.close()
            
            if response.status_code != 200:
                return []
            
            data = response.json()
            models = []
            
            for model_data in data.get("models", []):
                models.append(OllamaModel(
                    name=model_data.get("name", ""),
                    size=model_data.get("size", ""),
                    modified_at=model_data.get("modified_at", ""),
                    digest=model_data.get("digest", "")
                ))
            
            self._models = models
            return models
            
        except Exception as e:
            logger.error(f"获取模型列表失败: {e}")
            return []
    
    def pull_model(self, model_name: str, progress_callback: Optional[Callable[[str], None]] = None) -> bool:
        """拉取模型"""
        try:
            session = requests.Session()
            session.trust_env = False  # 关键：不走系统 HTTP_PROXY/HTTPS_PROXY
            response = session.post(
                f"{self.base_url}/api/pull",
                json={"name": model_name},
                stream=True,
                timeout=3600
            )
            
            if response.status_code != 200:
                logger.error(f"Ollama pull 返回 {response.status_code}: {response.text[:200]}")
                if progress_callback:
                    progress_callback(f"错误: HTTP {response.status_code}")
                return False
            
            for line in response.iter_lines():
                if line:
                    data = json.loads(line)
                    status = data.get("status", "")
                    completed = data.get("completed", 0)
                    total = data.get("total", 0)
                    
                    display_status = self._format_pull_status(model_name, status, completed, total)
                    
                    if progress_callback:
                        progress_callback(display_status)
                    
                    if status == "success":
                        self._models = []
                        return True
                    
                    # 检查错误状态
                    if "error" in data:
                        err = data.get("error", "unknown")
                        logger.error(f"Ollama pull error: {err}")
                        if progress_callback:
                            progress_callback(f"错误: {err[:100]}")
                        return False
            
            logger.error(f"Ollama pull stream ended without success for {model_name}")
            return False
            
        except requests.exceptions.ConnectionError as e:
            logger.error(f"无法连接 Ollama: {e}")
            if progress_callback:
                progress_callback(f"连接失败: Ollama 服务未运行 ({self.base_url})")
            return False
        except Exception as e:
            logger.error(f"拉取模型失败: {e}")
            if progress_callback:
                progress_callback(f"出错: {str(e)[:100]}")
            return False
    
    def _format_pull_status(self, model_name: str, status: str, completed: int, total: int) -> str:
        """格式化拉取状态显示"""
        short_model = model_name.split(":")[0] if ":" in model_name else model_name
        
        if not status:
            return f"准备拉取 {short_model}..."
        
        if status == "pulling manifest":
            return f"正在获取 {short_model} 模型信息..."
        elif status.startswith("pulling "):
            if total > 0 and completed > 0:
                progress = int(completed / total * 100)
                completed_mb = completed / (1024 * 1024)
                total_mb = total / (1024 * 1024)
                return f"下载 {short_model}: {progress}% ({completed_mb:.0f}MB/{total_mb:.0f}MB)"
            return f"正在下载 {short_model}..."
        elif status == "verifying sha256 digest":
            return f"校验 {short_model} 文件完整性..."
        elif status == "writing manifest":
            return f"写入 {short_model} 清单..."
        elif status == "success":
            return f"{short_model} 拉取完成!"
        elif "already" in status.lower():
            return f"{short_model} 已存在"
        else:
            return f"处理 {short_model}: {status}"
    
    def delete_model(self, model_name: str) -> bool:
        """删除模型"""
        try:
            session = requests.Session()
            session.trust_env = False  # 关键：不走系统 HTTP_PROXY/HTTPS_PROXY
            response = session.delete(
                f"{self.base_url}/api/delete",
                json={"name": model_name},
                timeout=30
            )
            session.close()
            
            if response.status_code == 200:
                self._models = []
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"删除模型失败: {e}")
            return False
    
    def generate(
        self,
        model: str,
        prompt: str,
        system: Optional[str] = None,
        context: Optional[List[int]] = None,
        stream: bool = False,
        options: Optional[Dict[str, Any]] = None,
        format: Optional[str] = None,
    ) -> Generator[str, None, None]:
        """生成文本 (流式输出)
        
        Args:
            format: 强制输出格式，如 "json" 可强制 Ollama 返回合法 JSON
        """
        
        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": stream,
        }
        
        if system:
            payload["system"] = system
        
        if context:
            payload["context"] = context
        
        if options:
            payload["options"] = options

        if format:
            payload["format"] = format
        
        try:
            session = requests.Session()
            session.trust_env = False  # 关键：不走系统 HTTP_PROXY/HTTPS_PROXY
            response = session.post(
                f"{self.base_url}/api/generate",
                json=payload,
                stream=True,
                timeout=self._config.timeout
            )

            if response.status_code != 200:
                err_body = ""
                try:
                    err_body = response.json().get("error", "") or response.text[:300]
                except Exception:
                    err_body = response.text[:300]
                logger.error(f"Ollama /api/generate 返回 {response.status_code}: {err_body}")
                yield f"错误: Ollama 返回 {response.status_code}: {err_body or '未知错误'}"
                return

            full_response = ""
            
            for line in response.iter_lines():
                if line:
                    data = json.loads(line)
                    if data.get("error"):
                        logger.error(f"Ollama /api/generate 错误: {data.get('error')}")
                        yield f"错误: {data.get('error')}"
                        return
                    token = data.get("response", "")
                    full_response += token
                    
                    if stream:
                        yield token
            
            if not stream:
                yield full_response
                
        except Exception as e:
            logger.error(f"生成文本失败: {e}")
            yield f"错误: {str(e)}"
    
    def chat(
        self,
        model: str,
        messages: List[Dict[str, str]],
        stream: bool = False,
        options: Optional[Dict[str, Any]] = None
    ) -> Generator[str, None, None]:
        """对话模式"""
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream
        }
        
        if options:
            payload["options"] = options
        
        try:
            session = requests.Session()
            session.trust_env = False  # 关键：不走系统 HTTP_PROXY/HTTPS_PROXY
            response = session.post(
                f"{self.base_url}/api/chat",
                json=payload,
                stream=True,
                timeout=self._config.timeout
            )

            if response.status_code != 200:
                err_body = ""
                try:
                    err_body = response.json().get("error", "") or response.text[:300]
                except Exception:
                    err_body = response.text[:300]
                logger.error(f"Ollama /api/chat 返回 {response.status_code}: {err_body}")
                yield f"错误: Ollama 返回 {response.status_code}: {err_body or '未知错误'}"
                return

            full_response = ""
            
            for line in response.iter_lines():
                if line:
                    data = json.loads(line)
                    if data.get("error"):
                        logger.error(f"Ollama /api/chat 错误: {data.get('error')}")
                        yield f"错误: {data.get('error')}"
                        return
                    message = data.get("message", {})
                    content = message.get("content", "")
                    full_response += content
                    
                    if stream:
                        yield content
            
            if not stream:
                yield full_response
                
        except Exception as e:
            logger.error(f"对话失败: {e}")
            yield f"错误: {str(e)}"
    
    def embeddings(self, model: str, prompt: str) -> Optional[List[float]]:
        """获取文本嵌入向量"""
        try:
            session = requests.Session()
            session.trust_env = False  # 关键：不走系统 HTTP_PROXY/HTTPS_PROXY
            response = session.post(
                f"{self.base_url}/api/embeddings",
                json={
                    "model": model,
                    "prompt": prompt
                },
                timeout=60
            )
            session.close()
            
            if response.status_code == 200:
                data = response.json()
                return data.get("embedding", [])
            
            return None
            
        except Exception as e:
            logger.error(f"获取嵌入向量失败: {e}")
            return None
    
    def get_model_info(self, model_name: str) -> Optional[Dict[str, Any]]:
        """获取模型详细信息"""
        try:
            session = requests.Session()
            session.trust_env = False  # 关键：不走系统 HTTP_PROXY/HTTPS_PROXY
            response = session.post(
                f"{self.base_url}/api/show",
                json={"name": model_name},
                timeout=30
            )
            session.close()
            
            if response.status_code == 200:
                return response.json()
            
            return None
            
        except Exception as e:
            logger.error(f"获取模型信息失败: {e}")
            return None
    
    def start_ollama_server(self) -> bool:
        """尝试启动 Ollama 服务"""
        try:
            if os.name == 'nt':
                subprocess.Popen(
                    ["ollama", "serve"],
                    creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
                )
            else:
                subprocess.Popen(
                    ["ollama", "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
            
            time.sleep(3)
            return self.is_available(force_check=True)
            
        except Exception as e:
            logger.error(f"启动 Ollama 服务失败: {e}")
            return False


ollama_client = OllamaClient()


RECOMMENDED_MODELS = [
    {"name": "llama3.1:8b", "size": "4.7GB", "description": "Meta Llama 3.1 8B - 通用对话（Llama 3 更新版）"},
    {"name": "llama3.1:70b", "size": "40GB", "description": "Meta Llama 3.1 70B - 高性能通用模型"},
    {"name": "llama3.2:1b", "size": "1.3GB", "description": "Meta Llama 3.2 1B - 超轻量本地推理"},
    {"name": "llama3.2:3b", "size": "2.0GB", "description": "Meta Llama 3.2 3B - 轻量本地推理"},
    {"name": "qwen2.5:7b", "size": "4.4GB", "description": "通义千问 2.5 7B - 中文优化（2024 秋季版）"},
    {"name": "qwen2.5:72b", "size": "41GB", "description": "通义千问 2.5 72B - 高性能中文"},
    {"name": "deepseek-v3:latest", "size": "8GB", "description": "DeepSeek V3 开源版 - 中文推理强"},
    {"name": "deepseek-coder:6.7b", "size": "3.8GB", "description": "DeepSeek Coder - 代码生成"},
    {"name": "gemma3:4b", "size": "2.5GB", "description": "Google Gemma 3 4B - 轻量多任务"},
    {"name": "gemma3:27b", "size": "16GB", "description": "Google Gemma 3 27B - 高性能多任务"},
    {"name": "phi3.5:mini", "size": "2.2GB", "description": "Microsoft Phi-3.5 Mini - 小模型强能力"},
    {"name": "mistral-small3.1:24b", "size": "14GB", "description": "Mistral Small 3.1 - 高效推理"},
    {"name": "codellama:7b", "size": "3.8GB", "description": "Code Llama - 代码生成"},
    {"name": "llava:7b", "size": "4.5GB", "description": "LLaVA - 多模态视觉理解"},
    {"name": "bge-m3:latest", "size": "4.5GB", "description": "BGE-M3 - 中文向量嵌入（RAG 用）"},
]


def get_recommended_models() -> List[Dict[str, str]]:
    """获取推荐模型列表"""
    return RECOMMENDED_MODELS
