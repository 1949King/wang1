import os
import time
import threading
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("AI短剧编辑器.scheduler")


def _resolve_module_path(module_path: str) -> list[str]:
    """
    解析模块导入路径，生成可能的导入路径列表。
    优先尝试带 app. 前缀的路径，然后尝试不带前缀的路径。
    
    Args:
        module_path: 原始模块路径
        
    Returns:
        可能的导入路径列表，按优先级排序
    """
    paths = []
    if module_path.startswith("app."):
        paths.append(module_path)
        paths.append(module_path[4:])
    else:
        paths.append(f"app.{module_path}")
        paths.append(module_path)
    return paths


def _safe_import(module_path: str, names: List[str]) -> tuple:
    """
    安全导入模块并获取指定属性，具有完善的错误处理和日志记录。
    
    Args:
        module_path: 模块导入路径
        names: 需要从模块中获取的属性名称列表
        
    Returns:
        包含请求属性的元组
        
    Raises:
        ImportError: 当所有导入路径都失败时抛出，包含详细的错误信息
    """
    import_errors = []
    possible_paths = _resolve_module_path(module_path)
    
    for attempt, path in enumerate(possible_paths, 1):
        try:
            logger.debug(f"尝试导入模块: {path} (第{attempt}次尝试)")
            mod = __import__(path, fromlist=names)
            
            missing_attrs = []
            attrs = []
            for name in names:
                try:
                    attr = getattr(mod, name)
                    attrs.append(attr)
                    logger.debug(f"成功获取属性: {path}.{name}")
                except AttributeError:
                    missing_attrs.append(name)
                    logger.warning(f"属性不存在: {path}.{name}")
            
            if missing_attrs:
                error_msg = f"模块 {path} 导入成功，但缺少属性: {', '.join(missing_attrs)}"
                logger.error(error_msg)
                import_errors.append(error_msg)
                continue
            
            logger.debug(f"成功导入模块和属性: {path} -> {', '.join(names)}")
            return tuple(attrs)
            
        except ImportError as e:
            error_msg = f"导入模块 {path} 失败: {str(e)}"
            logger.warning(error_msg)
            import_errors.append(error_msg)
        except Exception as e:
            error_msg = f"导入模块 {path} 时发生意外错误: {str(e)}"
            logger.error(error_msg)
            import_errors.append(error_msg)
    
    final_error = (
        f"无法从任何路径导入模块 '{module_path}' 的属性 {names}。"
        f"尝试的路径: {possible_paths}。错误详情: {'; '.join(import_errors)}"
    )
    logger.error(final_error)
    raise ImportError(final_error)


class EditorKernel(Enum):
    """编辑器内核类型 (双内核)"""
    LIGHTWEIGHT = "lightweight"    # 轻量内核 (PyAV, 默认启用)
    PROFESSIONAL = "professional"  # 专业内核 (C++引擎 → FFmpeg CLI 自动选)


class KernelSelection(Enum):
    """统一内核选择模式。"""
    AUTO = "auto"
    LIGHTWEIGHT = "lightweight"
    PROFESSIONAL = "professional"


@dataclass
class KernelTaskPlan:
    """统一内核任务计划，用于记录调度决策和执行状态。"""
    task_id: str
    operation: str
    input_path: Optional[str] = None
    output_path: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    selected_kernel: EditorKernel = EditorKernel.LIGHTWEIGHT
    fallback_kernel: Optional[EditorKernel] = None
    reason: str = ""
    status: str = "planned"
    error_message: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """转为普通字典，避免 UI 层直接处理枚举对象。"""
        return {
            "task_id": self.task_id,
            "operation": self.operation,
            "input_path": self.input_path,
            "output_path": self.output_path,
            "params": self.params,
            "selected_kernel": self.selected_kernel.value,
            "fallback_kernel": self.fallback_kernel.value if self.fallback_kernel else "",
            "reason": self.reason,
            "status": self.status,
            "error_message": self.error_message,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class PerformanceMetrics:
    """性能监控指标"""
    
    def __init__(self):
        self.cpu_usage = 0.0
        self.memory_usage = 0.0
        self.gpu_usage = 0.0
        self.frame_rate = 0.0
        self.render_latency = 0.0
        self.task_queue_length = 0
        self._history: List[Dict[str, float]] = []
        self._max_history = 60
    
    def update(self, **kwargs):
        """更新性能指标"""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        
        record = {
            'cpu_usage': self.cpu_usage,
            'memory_usage': self.memory_usage,
            'frame_rate': self.frame_rate,
            'render_latency': self.render_latency,
        }
        self._history.append(record)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
    
    def get_average(self, metric: str) -> float:
        """获取指标历史平均值"""
        if not self._history:
            return 0.0
        values = [h.get(metric, 0) for h in self._history]
        return sum(values) / len(values)
    
    def to_dict(self) -> Dict[str, float]:
        """转为字典"""
        return {
            'cpu_usage': self.cpu_usage,
            'memory_usage': self.memory_usage,
            'gpu_usage': self.gpu_usage,
            'frame_rate': self.frame_rate,
            'render_latency': self.render_latency,
            'task_queue_length': self.task_queue_length,
            'avg_cpu_usage': self.get_average('cpu_usage'),
            'avg_frame_rate': self.get_average('frame_rate'),
        }


class EditorScheduler:
    """双内核调度器 (v3 - 精简为二核)"""
    
    def __init__(self):
        self._current_kernel = EditorKernel.LIGHTWEIGHT
        self._selection_mode = KernelSelection.AUTO
        self._kernels = {}
        self._kernel_lock = threading.Lock()
        self._render_mgr = None
        self._pyav_engine = None
        self._mlt_engine = None
        self._cpp_engine = None
        self._ffmpeg_engine = None
        self._video_processor = None
        self._top0_processor = None
        self._task_lock = threading.Lock()
        self._task_history: List[KernelTaskPlan] = []
        self._max_task_history = 80
        self._operation_profiles = self._build_operation_profiles()
        self._initialize_kernels()
        self._enable_kernel(EditorKernel.LIGHTWEIGHT)
        
        self._performance_metrics = PerformanceMetrics()
        self._last_switch_time = 0
        self._switch_cooldown = 5.0
        self._auto_degrade_enabled = True
        
    def _build_operation_profiles(self) -> Dict[str, Dict[str, Any]]:
        """建立任务画像，集中维护自动内核选择规则。"""
        return {
            "preview": {
                "preferred": EditorKernel.LIGHTWEIGHT,
                "fallback": None,
                "reason": "预览优先低延迟，使用轻量内核",
            },
            "probe": {
                "preferred": EditorKernel.LIGHTWEIGHT,
                "fallback": None,
                "reason": "素材探测只读取元信息，使用轻量内核",
            },
            "transcode": {
                "preferred": EditorKernel.LIGHTWEIGHT,
                "fallback": EditorKernel.PROFESSIONAL,
                "reason": "普通转码优先轻量操作链",
            },
            "clip": {
                "preferred": EditorKernel.PROFESSIONAL,
                "fallback": EditorKernel.LIGHTWEIGHT,
                "reason": "剪辑导出需要稳定编码，优先专业内核",
            },
            "export": {
                "preferred": EditorKernel.PROFESSIONAL,
                "fallback": EditorKernel.LIGHTWEIGHT,
                "reason": "成片导出优先专业渲染管理器",
            },
            "batch_export": {
                "preferred": EditorKernel.PROFESSIONAL,
                "fallback": EditorKernel.LIGHTWEIGHT,
                "reason": "批量导出需要完整渲染能力",
            },
            "ai_clip": {
                "preferred": EditorKernel.PROFESSIONAL,
                "fallback": None,
                "reason": "AI 智能剪辑依赖 TOP0 专业内核能力",
            },
            "multi_track": {
                "preferred": EditorKernel.PROFESSIONAL,
                "fallback": None,
                "reason": "多轨合成需要专业内核",
            },
            "color_grading": {
                "preferred": EditorKernel.PROFESSIONAL,
                "fallback": EditorKernel.LIGHTWEIGHT,
                "reason": "复杂调色优先专业内核",
            },
            "audio_mixing": {
                "preferred": EditorKernel.PROFESSIONAL,
                "fallback": None,
                "reason": "音频混合需要专业内核",
            },
        }

    def _initialize_kernels(self):
        """初始化内核"""
        self._kernels[EditorKernel.LIGHTWEIGHT] = {
            'enabled': False,
            'engine': None,
            'name': '轻量内核',
            'backend': 'PyAV',
            'capabilities': [
                'basic_editing', 'simple_effects', 'quick_export',
                'preview', 'frame_extraction', 'thumbnail_generation',
                'video_probe', 'lossless_trim', 'transcode',
            ],
            'performance': 'high',
        }
        
        self._kernels[EditorKernel.PROFESSIONAL] = {
            'enabled': False,
            'engine': None,
            'name': '专业内核',
            'backend': 'auto',  # 自动选 C++ > FFmpeg CLI
            'capabilities': [
                'advanced_editing', 'complex_effects', 'multi_track',
                'professional_export', 'color_grading', 'audio_mixing',
                'gpu_acceleration', 'cpp_acceleration', 'real_time_preview',
                'ai_clip', 'batch_export',
            ],
            'performance': 'ultra',
        }
        
    def _normalize_kernel(self, kernel) -> Optional[EditorKernel]:
        """兼容枚举和字符串形式的内核参数。"""
        if isinstance(kernel, EditorKernel):
            return kernel
        if isinstance(kernel, KernelSelection):
            if kernel == KernelSelection.AUTO:
                return self._current_kernel
            return EditorKernel(kernel.value)
        if isinstance(kernel, str):
            value = kernel.lower().strip()
            if value in ("light", "lite", "lightweight", "轻量"):
                return EditorKernel.LIGHTWEIGHT
            if value in ("pro", "professional", "专业"):
                return EditorKernel.PROFESSIONAL
        return None

    def switch_kernel(self, kernel: EditorKernel) -> bool:
        """手动切换当前执行内核。"""
        kernel = self._normalize_kernel(kernel)
        if kernel is None:
            return False

        if not self._check_cooldown() and kernel != self._current_kernel:
            logger.debug("内核切换冷却中，跳过切换")
            return False

        with self._kernel_lock:
            if kernel not in self._kernels:
                return False
            if not self._kernels[kernel]['enabled']:
                if not self._enable_kernel(kernel):
                    return False
            if self._current_kernel != kernel:
                self._deactivate_kernel(self._current_kernel)
            self._current_kernel = kernel
            self._selection_mode = KernelSelection(kernel.value)
            self._update_last_switch()
            logger.info(f"内核切换: {kernel.value}")
            return True

    def set_selection_mode(self, mode) -> bool:
        """设置统一选择模式：auto / lightweight / professional。"""
        if isinstance(mode, KernelSelection):
            selection = mode
        else:
            value = str(mode).lower().strip()
            if value in ("auto", "automatic", "自动", "智能"):
                selection = KernelSelection.AUTO
            elif value in ("light", "lite", "lightweight", "轻量"):
                selection = KernelSelection.LIGHTWEIGHT
            elif value in ("pro", "professional", "专业"):
                selection = KernelSelection.PROFESSIONAL
            else:
                return False

        if selection == KernelSelection.AUTO:
            self._selection_mode = KernelSelection.AUTO
            if not self._kernels[EditorKernel.LIGHTWEIGHT]['enabled']:
                self._enable_kernel(EditorKernel.LIGHTWEIGHT)
            logger.info("统一内核选择: 自动")
            return True

        return self.switch_kernel(EditorKernel(selection.value))

    def get_selection_mode(self) -> str:
        """返回当前选择模式。"""
        return self._selection_mode.value

    def _normalize_operation(self, operation: str) -> str:
        """标准化操作名，便于 UI、任务模块和 Agent 共用。"""
        value = str(operation or "preview").lower().strip()
        aliases = {
            "inspect": "probe",
            "video_probe": "probe",
            "render": "export",
            "professional_export": "export",
            "smart_clip": "ai_clip",
            "top0": "ai_clip",
            "cut": "clip",
            "trim": "clip",
        }
        return aliases.get(value, value)

    def _profile_for_operation(self, operation: str,
                               params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """获取任务画像，并根据参数做轻量动态修正。"""
        operation = self._normalize_operation(operation)
        profile = self._operation_profiles.get(
            operation,
            {
                "preferred": EditorKernel.LIGHTWEIGHT,
                "fallback": None,
                "reason": "未知轻量任务，默认使用轻量内核",
            },
        ).copy()

        params = params or {}
        if operation == "transcode":
            operations = params.get("operations") or []
            complex_ops = {"filter", "transition", "subtitle", "overlay", "watermark", "audio_mix"}
            if any(str(op.get("type", "")).lower() in complex_ops for op in operations if isinstance(op, dict)):
                profile.update({
                    "preferred": EditorKernel.PROFESSIONAL,
                    "fallback": EditorKernel.LIGHTWEIGHT,
                    "reason": "转码包含复杂效果，自动升级到专业内核",
                })
        return profile

    def plan_task(self, operation: str, input_path: Optional[str] = None,
                  output_path: Optional[str] = None,
                  params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """生成统一内核任务计划，不启动实际处理。"""
        operation = self._normalize_operation(operation)
        profile = self._profile_for_operation(operation, params)
        preferred = profile["preferred"]
        fallback = profile.get("fallback")

        if self._selection_mode == KernelSelection.LIGHTWEIGHT:
            preferred = EditorKernel.LIGHTWEIGHT
            fallback = None
            reason = "用户手动选择轻量内核"
        elif self._selection_mode == KernelSelection.PROFESSIONAL:
            preferred = EditorKernel.PROFESSIONAL
            fallback = fallback or EditorKernel.LIGHTWEIGHT
            reason = "用户手动选择专业内核"
        else:
            reason = profile.get("reason", "自动选择内核")

        task = KernelTaskPlan(
            task_id=f"{operation}_{int(time.time() * 1000)}",
            operation=operation,
            input_path=input_path,
            output_path=output_path,
            params=params or {},
            selected_kernel=preferred,
            fallback_kernel=fallback,
            reason=reason,
        )
        return task.to_dict()

    def _append_task(self, task: KernelTaskPlan):
        """记录最近任务，便于帮助诊断和后续任务图扩展。"""
        with self._task_lock:
            self._task_history.append(task)
            if len(self._task_history) > self._max_task_history:
                self._task_history = self._task_history[-self._max_task_history:]

    def _result_success(self, result) -> bool:
        """兼容 dict 和专业引擎 TaskResult 的成功状态。"""
        if isinstance(result, dict):
            return bool(result.get("success") or result.get("status") == "success")
        return bool(getattr(result, "success", False))

    def _begin_task(self, operation: str, input_path: Optional[str] = None,
                    output_path: Optional[str] = None,
                    params: Optional[Dict[str, Any]] = None) -> KernelTaskPlan:
        """创建并启动任务计划，记录最终实际选择的内核。"""
        plan = self.plan_task(operation, input_path, output_path, params)
        task = KernelTaskPlan(
            task_id=plan["task_id"],
            operation=plan["operation"],
            input_path=plan["input_path"],
            output_path=plan["output_path"],
            params=plan["params"],
            selected_kernel=EditorKernel(plan["selected_kernel"]),
            fallback_kernel=EditorKernel(plan["fallback_kernel"]) if plan["fallback_kernel"] else None,
            reason=plan["reason"],
            status="running",
            started_at=time.time(),
        )
        actual = self.resolve_kernel(task.operation, params=params)
        if actual != task.selected_kernel:
            task.reason = f"{task.reason}；实际回退到{self._kernels[actual]['name']}"
            task.selected_kernel = actual
        self._append_task(task)
        return task

    def _finish_task(self, task: KernelTaskPlan, result=None,
                     error_message: str = ""):
        """结束任务并更新执行状态。"""
        task.finished_at = time.time()
        task.error_message = error_message
        if error_message:
            task.status = "failed"
        else:
            task.status = "success" if self._result_success(result) else "failed"

    def get_recent_tasks(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取最近内核任务记录，供帮助页、诊断面板和 Agent 使用。"""
        with self._task_lock:
            tasks = self._task_history[-max(1, limit):]
            return [task.to_dict() for task in reversed(tasks)]

    def _check_cooldown(self) -> bool:
        """检查内核切换冷却时间"""
        now = time.time()
        return (now - self._last_switch_time) >= self._switch_cooldown

    def _update_last_switch(self):
        """更新最后切换时间"""
        self._last_switch_time = time.time()

    def update_performance_metrics(self, **kwargs):
        """更新性能监控指标"""
        self._performance_metrics.update(**kwargs)

    def get_performance_metrics(self) -> Dict[str, float]:
        """获取性能监控指标"""
        return self._performance_metrics.to_dict()

    def should_auto_degrade(self) -> bool:
        """判断是否需要自动降级到轻量内核"""
        if not self._auto_degrade_enabled:
            return False
        
        if not self._check_cooldown():
            return False
        
        metrics = self._performance_metrics
        avg_cpu = metrics.get_average('cpu_usage')
        avg_fps = metrics.get_average('frame_rate')
        avg_latency = metrics.get_average('render_latency')
        
        if avg_cpu > 85.0:
            logger.warning(f"CPU使用率过高 ({avg_cpu:.1f}%)，触发自动降级")
            return True
        if avg_fps > 0 and avg_fps < 15.0:
            logger.warning(f"帧率过低 ({avg_fps:.1f}fps)，触发自动降级")
            return True
        if avg_latency > 500.0:
            logger.warning(f"渲染延迟过高 ({avg_latency:.1f}ms)，触发自动降级")
            return True
        
        return False

    def set_auto_degrade_enabled(self, enabled: bool):
        """设置是否启用自动降级"""
        self._auto_degrade_enabled = enabled
        logger.info(f"自动降级: {'启用' if enabled else '禁用'}")

    def resolve_kernel(self, operation: str = "preview",
                       params: Optional[Dict[str, Any]] = None) -> EditorKernel:
        """根据任务画像自主选择轻量或专业内核。"""
        operation = self._normalize_operation(operation)
        
        if self.should_auto_degrade() and self._current_kernel == EditorKernel.PROFESSIONAL:
            logger.info("自动降级到轻量内核")
            self.switch_kernel(EditorKernel.LIGHTWEIGHT)
            return EditorKernel.LIGHTWEIGHT

        if self._selection_mode == KernelSelection.LIGHTWEIGHT:
            self.switch_kernel(EditorKernel.LIGHTWEIGHT)
            return EditorKernel.LIGHTWEIGHT

        if self._selection_mode == KernelSelection.PROFESSIONAL:
            if self.switch_kernel(EditorKernel.PROFESSIONAL):
                return EditorKernel.PROFESSIONAL
            self.switch_kernel(EditorKernel.LIGHTWEIGHT)
            return EditorKernel.LIGHTWEIGHT

        profile = self._profile_for_operation(operation, params)
        target = profile["preferred"]
        fallback = profile.get("fallback")
        if target == EditorKernel.PROFESSIONAL and not self.switch_kernel(target):
            self._selection_mode = KernelSelection.AUTO
            if fallback:
                self.switch_kernel(fallback)
                self._selection_mode = KernelSelection.AUTO
                return fallback
            self._selection_mode = KernelSelection.AUTO
            return EditorKernel.LIGHTWEIGHT

        self.switch_kernel(target)
        self._selection_mode = KernelSelection.AUTO
        return target
    
    def _deactivate_kernel(self, kernel: EditorKernel):
        """停用内核 — 清理引擎资源"""
        if kernel == EditorKernel.PROFESSIONAL:
            if self._mlt_engine:
                try:
                    self._mlt_engine.close()
                except Exception as e:
                    logger.warning(f"关闭 MLT 引擎时出错: {e}", exc_info=True)
                finally:
                    self._mlt_engine = None
            if self._ffmpeg_engine:
                try:
                    self._ffmpeg_engine.shutdown()
                except Exception as e:
                    logger.warning(f"关闭 FFmpeg 引擎时出错: {e}", exc_info=True)
                finally:
                    self._ffmpeg_engine = None
            self._kernels[kernel]['enabled'] = False
        elif kernel == EditorKernel.LIGHTWEIGHT:
            # PyAV 引擎是单例无状态，只需标记 disabled
            self._kernels[kernel]['enabled'] = False
    
    def _enable_kernel(self, kernel: EditorKernel) -> bool:
        """启用内核"""
        # --- 轻量内核: PyAV ---
        if kernel == EditorKernel.LIGHTWEIGHT:
            try:
                get_pyav_engine, is_pyav_available = _safe_import(
                    "app.core.video_processing.pyav_engine",
                    ["get_pyav_engine", "is_pyav_available"]
                )
                if is_pyav_available():
                    self._pyav_engine = get_pyav_engine()
                    self._kernels[kernel]['engine'] = self._pyav_engine
                    self._kernels[kernel]['enabled'] = True
                    self._kernels[kernel]['backend'] = 'PyAV'
                    logger.info("轻量内核已启用 (PyAV)")
                    return True
                else:
                    logger.warning("PyAV 不可用, 回退基础模式")
                    self._kernels[kernel]['enabled'] = True
                    return True
            except Exception as e:
                logger.warning(f"PyAV 加载失败: {e}, 回退基础模式")
                self._kernels[kernel]['enabled'] = True
                return True

        # --- 专业内核: MLT C++ → FFmpeg CLI ---
        if kernel == EditorKernel.PROFESSIONAL:
            success = False
            backend = "none"

            # 1. MLT C++ 引擎 (原生性能，多轨/关键帧/转场)
            try:
                is_mlt_cpp_available, get_mlt_cpp_engine = _safe_import(
                    "app.core.video_processing.mlt_engine_cpp",
                    ["is_mlt_cpp_available", "get_mlt_cpp_engine"]
                )
                if is_mlt_cpp_available():
                    self._mlt_engine = get_mlt_cpp_engine()
                    self._cpp_engine = self._mlt_engine
                    self._kernels[kernel]['engine'] = self._mlt_engine
                    success = True
                    backend = "MLT C++"
                    logger.info("专业内核 → MLT C++")
            except Exception as e:
                logger.debug(f"MLT 不可用: {e}")

            # 2. 回退 FFmpeg CLI
            if not success:
                try:
                    ProfessionalVideoEngine = _safe_import(
                        "app.modules.lego.professional_video_engine",
                        ["ProfessionalVideoEngine"]
                    )[0]
                    self._ffmpeg_engine = ProfessionalVideoEngine(max_workers=4)
                    self._kernels[kernel]['engine'] = self._ffmpeg_engine
                    success = True
                    backend = "FFmpeg CLI"
                    logger.info("专业内核 → FFmpeg CLI")
                except Exception as e:
                    logger.warning(f"FFmpeg CLI 不可用: {e}")
            
            if success:
                self._kernels[kernel]['enabled'] = True
                self._kernels[kernel]['backend'] = backend
                logger.info(f"专业内核已启用 ({backend})")
                return True
            return False
        
        return True
    
    # --- 公共接口 ---
    
    def get_render_manager(self):
        """获取统一渲染管理器 (懒加载)"""
        if self._render_mgr is None:
            try:
                get_render_manager = _safe_import(
                    "app.core.render_manager", ["get_render_manager"]
                )[0]
                self._render_mgr = get_render_manager()
            except Exception as e:
                logger.warning(f"渲染管理器加载失败: {e}")
        return self._render_mgr
    
    def get_pyav_engine(self):
        """获取 PyAV 轻量引擎"""
        if self._pyav_engine is None:
            self._enable_kernel(EditorKernel.LIGHTWEIGHT)
        return self._pyav_engine
    
    def get_cpp_engine(self):
        """获取 C++ 引擎 (需在专业模式下)"""
        return self._cpp_engine

    def get_professional_engine(self, max_workers: int = 4):
        """获取专业 FFmpeg 引擎，供剪辑/批处理等统一入口复用。"""
        if self._ffmpeg_engine is None:
            ProfessionalVideoEngine = _safe_import(
                "app.modules.lego.professional_video_engine",
                ["ProfessionalVideoEngine"]
            )[0]
            self._ffmpeg_engine = ProfessionalVideoEngine(max_workers=max_workers)
            self._kernels[EditorKernel.PROFESSIONAL]['engine'] = self._ffmpeg_engine
            self._kernels[EditorKernel.PROFESSIONAL]['enabled'] = True
            self._kernels[EditorKernel.PROFESSIONAL]['backend'] = "FFmpeg CLI"
        return self._ffmpeg_engine

    def get_video_processor(self):
        """获取轻量 VideoProcessor，供转码和简单操作链复用。"""
        if self._video_processor is None:
            VideoProcessor = _safe_import(
                "app.modules.lego.video_processor", ["VideoProcessor"]
            )[0]
            self._video_processor = VideoProcessor()
        return self._video_processor

    def get_top0_processor(self):
        """获取 TOP0 智能剪辑处理器，统一纳入专业内核能力。"""
        if self._top0_processor is None:
            Top0VideoProcessor = _safe_import(
                "app.modules.lego.top0_integration", ["Top0VideoProcessor"]
            )[0]
            self._top0_processor = Top0VideoProcessor()
        return self._top0_processor
    
    def get_current_kernel(self) -> EditorKernel:
        return self._current_kernel
    
    def get_kernel_capabilities(self) -> List[str]:
        return self._kernels[self._current_kernel]['capabilities']
    
    def supports_feature(self, feature: str) -> bool:
        return feature in self.get_kernel_capabilities()
    
    def get_performance_mode(self) -> str:
        return self._kernels[self._current_kernel]['performance']
    
    def is_professional_mode(self) -> bool:
        return self._current_kernel == EditorKernel.PROFESSIONAL
    
    def get_kernel_info(self) -> Dict[str, Any]:
        """获取当前内核详细信息"""
        info = self._kernels[self._current_kernel].copy()
        info['current'] = self._current_kernel.value
        info['selection_mode'] = self._selection_mode.value
        info['recent_tasks'] = self.get_recent_tasks(5)
        engine = info.get('engine')
        info['engine_type'] = type(engine).__name__ if engine else 'None'
        # 状态查询不能触发重型渲染后端加载，避免帮助页/诊断页引起原生库初始化。
        rm = self._render_mgr
        if rm:
            info['renderer'] = rm.get_status()
        return info

    # --- 统一视频处理入口 ---

    def cut_video(self, video_path: str, start_time: float, end_time: float,
                  output_path: Optional[str] = None, settings=None,
                  progress_callback=None):
        """统一剪辑入口，自动在专业/轻量内核之间选择。"""
        if not video_path or not os.path.exists(video_path):
            raise FileNotFoundError(f"视频文件不存在: {video_path}")

        task = self._begin_task(
            "clip", video_path, output_path,
            {"start_time": start_time, "end_time": end_time},
        )
        try:
            kernel = task.selected_kernel
            if kernel == EditorKernel.PROFESSIONAL:
                engine = self.get_professional_engine(max_workers=1)
                result = engine.cut_with_reencode(
                    video_path, start_time, end_time,
                    output_path=output_path,
                    settings=settings,
                    progress_callback=progress_callback,
                )
                self._finish_task(task, result)
                return result

            processor = self.get_video_processor()
            if output_path is None:
                base, _ = os.path.splitext(video_path)
                output_path = f"{base}_cut_{int(start_time)}_{int(end_time)}.mp4"
            ok = processor.process(
                video_path,
                output_path,
                [{"type": "trim", "start": start_time, "end": end_time}],
                progress_callback=progress_callback,
            )
            result = {
                "success": ok,
                "output_path": output_path if ok else "",
                "error_message": "" if ok else "轻量内核剪辑失败",
                "kernel": task.selected_kernel.value,
                "task_id": task.task_id,
            }
            self._finish_task(task, result)
            return result
        except Exception as e:
            self._finish_task(task, error_message=str(e))
            raise

    def export_video(self, video_path: str, output_path: Optional[str] = None,
                     platform: str = "通用HD", params: Optional[Dict[str, Any]] = None,
                     progress_callback=None):
        """统一导出入口，自动优先使用专业渲染管理器。"""
        if not video_path or not os.path.exists(video_path):
            raise FileNotFoundError(f"视频文件不存在: {video_path}")

        params = params or {}
        fmt = str(params.get("format", "mp4")).lstrip(".") or "mp4"
        if output_path is None:
            output_dir = params.get("output_dir") or "短剧AI剪辑输出"
            os.makedirs(output_dir, exist_ok=True)
            base_name = os.path.splitext(os.path.basename(video_path))[0]
            output_path = os.path.join(output_dir, f"{base_name}_{int(time.time())}.{fmt}")

        task = self._begin_task("export", video_path, output_path, params)

        def _finalize_with_settings(result):
            """套用 UI 导出设置（分辨率/帧率/码率/编码），此前被忽略。"""
            try:
                from app.modules.lego.video_processor import apply_export_settings
                fp = self.get_video_processor().ffmpeg_path
                if apply_export_settings(output_path, output_path, params, fp):
                    sz = os.path.getsize(output_path) if os.path.exists(output_path) else 0
                    if isinstance(result, dict):
                        result["output_size"] = sz
                    else:
                        try:
                            result.output_size = sz
                        except Exception:
                            pass
            except Exception as _se:
                logger.warning("套用导出设置失败（保留原渲染结果）: %s", _se)
            return result

        try:
            kernel = task.selected_kernel
            if kernel == EditorKernel.PROFESSIONAL:
                rm = self.get_render_manager()
                if rm is not None:
                    result = rm.render(video_path, output_path, platform=platform,
                                       on_progress=progress_callback)
                    if getattr(result, "success", False):
                        self._finish_task(task, result)
                        return _finalize_with_settings(result)
                    logger.warning(
                        "专业内核导出失败，回退轻量内核: %s",
                        getattr(result, "error_message", "unknown")
                    )
                    task.selected_kernel = EditorKernel.LIGHTWEIGHT
                    task.reason = f"{task.reason}；专业导出失败后回退轻量内核"

            processor = self.get_video_processor()
            operations = params.get("operations") or []
            ok = processor.process(video_path, output_path, operations,
                                   progress_callback=progress_callback)
            result = {
                "success": ok,
                "output_path": output_path if ok else "",
                "error_message": "" if ok else "轻量内核导出失败",
                "processing_time": 0.0,
                "output_size": os.path.getsize(output_path) if ok and os.path.exists(output_path) else 0,
                "kernel": task.selected_kernel.value,
                "task_id": task.task_id,
            }
            self._finish_task(task, result)
            return _finalize_with_settings(result)
        except Exception as e:
            self._finish_task(task, error_message=str(e))
            raise

    def transcode_video(self, video_path: str, output_path: str,
                        operations: Optional[List[Dict[str, Any]]] = None,
                        settings=None, progress_callback=None) -> Dict[str, Any]:
        """统一转码入口，默认走轻量操作链。"""
        if not video_path or not os.path.exists(video_path):
            return {"status": "error", "error": "视频文件不存在"}

        params = {"operations": operations or []}
        task = self._begin_task("transcode", video_path, output_path, params)
        try:
            if task.selected_kernel == EditorKernel.PROFESSIONAL and not params["operations"]:
                rm = self.get_render_manager()
                if rm is not None:
                    render_result = rm.render(video_path, output_path, on_progress=progress_callback)
                    result = {
                        "status": "success" if getattr(render_result, "success", False) else "error",
                        "output": output_path if getattr(render_result, "success", False) else "",
                        "error": "" if getattr(render_result, "success", False) else getattr(render_result, "error_message", "转码失败"),
                        "kernel": task.selected_kernel.value,
                        "task_id": task.task_id,
                    }
                    self._finish_task(task, result)
                    return result

            if task.selected_kernel == EditorKernel.PROFESSIONAL:
                task.selected_kernel = EditorKernel.LIGHTWEIGHT
                task.reason = f"{task.reason}；当前复杂转码操作链回退轻量处理器执行"

            processor = self.get_video_processor()
            ok = processor.process(
                video_path, output_path, operations or [],
                settings=settings,
                progress_callback=progress_callback,
            )
            result = {
                "status": "success" if ok else "error",
                "output": output_path if ok else "",
                "error": "" if ok else "转码失败",
                "kernel": task.selected_kernel.value,
                "task_id": task.task_id,
            }
            self._finish_task(task, result)
            return result
        except Exception as e:
            self._finish_task(task, error_message=str(e))
            return {
                "status": "error",
                "output": "",
                "error": str(e),
                "kernel": task.selected_kernel.value,
                "task_id": task.task_id,
            }

    def smart_clip(self, video_path: str, target_platform: str = "抖音",
                   video_style: str = "高光剪辑", target_duration: float = 60.0,
                   progress_callback=None) -> Dict[str, Any]:
        """统一 AI 智能剪辑入口，自动选择专业 TOP0 能力。"""
        if not video_path or not os.path.exists(video_path):
            return {"success": False, "errors": [{"error": "视频文件不存在"}]}

        task = self._begin_task(
            "ai_clip", video_path, None,
            {
                "target_platform": target_platform,
                "video_style": video_style,
                "target_duration": target_duration,
            },
        )
        try:
            if task.selected_kernel != EditorKernel.PROFESSIONAL:
                result = {"success": False, "errors": [{"error": "专业内核不可用，无法执行 AI 智能剪辑"}]}
                self._finish_task(task, result)
                return result

            processor = self.get_top0_processor()
            result = processor.smart_clip(
                video_path=video_path,
                target_platform=target_platform,
                video_style=video_style,
                target_duration=target_duration,
                progress_callback=progress_callback,
            )
            self._finish_task(task, result)
            return result
        except Exception as e:
            self._finish_task(task, error_message=str(e))
            return {"success": False, "errors": [{"error": str(e)}], "task_id": task.task_id}

    # --- Agent 工作流集成 ---

    def get_agent_workflow(self):
        """获取 AI Agent 协作工作流实例（懒加载）"""
        if not hasattr(self, '_agent_workflow') or self._agent_workflow is None:
            try:
                get_agent_workflow = _safe_import(
                    "app.modules.lego.agent_workflow", ["get_agent_workflow"]
                )[0]
                self._agent_workflow = get_agent_workflow()
            except Exception as e:
                logger.warning(f"Agent 工作流加载失败: {e}")
        return self._agent_workflow

    def run_ai_clip(self, video_path: str, platform: str = "抖音",
                    style: str = "高光剪辑", target_duration: float = 60.0,
                    output_dir: str = "",
                    on_progress=None, on_complete=None) -> bool:
        """
        启动 AI 智能剪辑工作流

        Args:
            video_path: 输入视频路径
            platform: 目标平台
            style: 剪辑风格
            target_duration: 目标时长
            output_dir: 输出目录
            on_progress: 进度回调(percent, message)
            on_complete: 完成回调

        Returns:
            是否成功启动
        """
        workflow = self.get_agent_workflow()
        if workflow is None:
            if on_complete:
                on_complete(None)
            return False

        # 确保轻量内核已启用
        if not self._kernels[EditorKernel.LIGHTWEIGHT]['enabled']:
            self._enable_kernel(EditorKernel.LIGHTWEIGHT)

        workflow.run_async(
            video_path, platform, style, target_duration,
            output_dir, on_progress, on_complete,
        )
        return True

    def get_ai_clip_status(self) -> Dict[str, Any]:
        """获取 AI 剪辑工作流状态"""
        workflow = self.get_agent_workflow()
        if workflow:
            return workflow.get_status()
        return {"phase": "unavailable", "message": "Agent 工作流未初始化"}

    def cancel_ai_clip(self):
        """取消 AI 剪辑工作流"""
        workflow = self.get_agent_workflow()
        if workflow:
            workflow.cancel()


editor_scheduler = EditorScheduler()
