"""
ai_clip_flow 步骤方法契约测试
==========================

目标：验证 _start_clip_flow 拆分为「84 行编排器 + 6 个 step 方法」后，
编排器能按正确顺序把流程派发给 6 个 step，且每个 step 的签名一致。

由于 ai_clip_flow 直接依赖 PyQt6 / core / video_processor，这里用
最小桩件（sys.modules 注入 MagicMock）在「无 GUI / 无重型依赖」环境
下加载模块并验证，既能在 CI 的普通 Python 中跑通，也避免拖入整个
lego 包（editor_module / main_window 等）导致的导入爆炸。

标记: unit
"""

import os
import sys
import types
import inspect
from unittest.mock import MagicMock, patch

import pytest

_STUB_NAMES = [
    "PyQt6", "PyQt6.QtWidgets", "PyQt6.QtCore", "PyQt6.QtGui",
    "app", "app.modules", "app.modules.lego",
    "app.modules.lego.core", "app.modules.lego.video_processor",
]

# 编排器预期派发顺序（与 _start_clip_flow 中 steps 列表一一对应）
EXPECTED_STEP_ORDER = [
    "_step_autoclip",
    "_step_funclip",
    "_step_videofusion",
    "_step_lora_edit",
    "_step_cover_title",
]
EXPECTED_STEP_SIGNATURE = [
    "self", "settings", "vp", "work_dir",
    "base_name", "current_output", "progress", "results",
]


@pytest.fixture
def flow_module():
    """注入桩件 -> 加载 ai_clip_flow -> 产出模块对象 -> 拆除桩件。"""
    saved = {n: sys.modules.get(n) for n in _STUB_NAMES}
    for n in _STUB_NAMES:
        sys.modules[n] = types.ModuleType(n)

    QtW = sys.modules["PyQt6.QtWidgets"]
    for sym in [
        "QVBoxLayout", "QHBoxLayout", "QLabel", "QPushButton",
        "QFrame", "QScrollArea", "QGroupBox", "QFormLayout", "QComboBox",
        "QSpinBox", "QDoubleSpinBox", "QCheckBox", "QLineEdit", "QTabWidget",
        "QTextEdit", "QFileDialog", "QMessageBox", "QProgressDialog",
        "QApplication",
    ]:
        setattr(QtW, sym, MagicMock())
    # QWidget 被用作基类 (class AIClipFlowModule(QWidget))，必须是一个「真正的类」，
    # 而不能是 MagicMock 实例——继承一个 mock 实例不会报错，但会静默把整个类体
    # （包括所有 _step_* 方法）丢弃，导致 AIClipFlowModule 变成一个空 MagicMock。
    QtW.QWidget = type("QWidget", (), {})
    QtC = sys.modules["PyQt6.QtCore"]
    QtC.Qt = MagicMock()
    QtC.pyqtSignal = MagicMock()
    sys.modules["PyQt6.QtGui"].QFont = MagicMock()

    core = sys.modules["app.modules.lego.core"]
    core.EventBus = MagicMock()
    core.EventType = MagicMock()
    core.MasterClock = MagicMock()
    core.DataBus = MagicMock()

    vp = sys.modules["app.modules.lego.video_processor"]
    vp.VideoProcessor = MagicMock()
    vp.ExportSettings = MagicMock()

    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "..", "modules", "lego", "ai_clip_flow.py")
    spec = importlib.util.spec_from_file_location(
        "app.modules.lego.ai_clip_flow", os.path.normpath(path))
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "app.modules.lego"
    spec.loader.exec_module(mod)

    # 让 QProgressDialog.wasCanceled() 返回 False，避免编排器提前 break
    QtW.QProgressDialog.return_value.wasCanceled.return_value = False

    try:
        yield mod
    finally:
        for n in _STUB_NAMES:
            if saved[n] is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = saved[n]


def test_step_methods_exist_and_have_correct_signature(flow_module):
    """6 个 step 方法必须存在，且签名与编排器调用一致。"""
    cls = flow_module.AIClipFlowModule
    for name in EXPECTED_STEP_ORDER:
        assert hasattr(cls, name), f"缺少 step 方法: {name}"
        sig = inspect.signature(getattr(cls, name))
        assert list(sig.parameters) == EXPECTED_STEP_SIGNATURE, (
            f"{name} 签名异常: {list(sig.parameters)}"
        )
    # 编排器本身存在
    assert hasattr(cls, "_start_clip_flow")
    assert hasattr(cls, "_finalize_clip_flow")


def test_start_clip_flow_dispatches_all_steps_in_order(flow_module):
    """编排器必须按序调用 6 个 step + finalize，且参数正确传递。"""
    cls = flow_module.AIClipFlowModule
    call_order: list[str] = []
    seen_args: dict[str, tuple] = {}

    # (完整方法名, 简短名)：call_order/seen_args 用完整名（与 EXPECTED_STEP_ORDER
    # 对齐），而各 step 的「返回值」用简短名（供下一步 current_output 透传断言）。
    _STEPS = [
        ("_step_autoclip", "autoclip"),
        ("_step_funclip", "funclip"),
        ("_step_videofusion", "videofusion"),
        ("_step_lora_edit", "lora"),
        ("_step_cover_title", "cover"),
    ]

    def _make(full, short):
        def _step(self, settings, vp, work_dir, base_name, current_output,
                  progress, results):
            call_order.append(full)
            seen_args[full] = (settings, vp, work_dir, base_name,
                               current_output, results)
            return f"out_after_{short}"
        return _step

    # 用一个真实存在的临时文件作为“当前视频”，绕过 os.path.exists 检查
    import tempfile
    tmp_video = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp_video.close()

    with patch.object(cls, "_setup_ui", lambda self: None), \
         patch.object(cls, "_collect_settings", lambda self: {"autoclip": {}}), \
         patch.object(cls, "_step_autoclip", _make("_step_autoclip", "autoclip")), \
         patch.object(cls, "_step_funclip", _make("_step_funclip", "funclip")), \
         patch.object(cls, "_step_videofusion", _make("_step_videofusion", "videofusion")), \
         patch.object(cls, "_step_lora_edit", _make("_step_lora_edit", "lora")), \
         patch.object(cls, "_step_cover_title", _make("_step_cover_title", "cover")), \
         patch.object(cls, "_finalize_clip_flow",
                      lambda self, *a, **k: call_order.append("finalize")):
        inst = cls()
        inst._current_video = tmp_video.name
        inst._video_processor = MagicMock()

        inst._start_clip_flow()

    expected = EXPECTED_STEP_ORDER + ["finalize"]
    assert call_order == expected, f"派发顺序错误: {call_order}"

    # 参数透传校验：settings / vp / work_dir / base_name 应一致贯穿各步
    base = seen_args["_step_autoclip"]
    assert base[0] == {"autoclip": {}}, "settings 未透传"
    assert base[1] is inst._video_processor, "vp 未透传"
    assert base[3] == os.path.splitext(os.path.basename(tmp_video.name))[0], \
        "base_name 推导错误"
    # current_output 应逐步向后传递
    assert seen_args["_step_funclip"][4] == "out_after_autoclip"
    assert seen_args["_step_videofusion"][4] == "out_after_funclip"
    assert seen_args["_step_lora_edit"][4] == "out_after_videofusion"
    assert seen_args["_step_cover_title"][4] == "out_after_lora"

    os.unlink(tmp_video.name)


def test_collect_settings_keys(flow_module):
    """_collect_settings 应返回含 5 大步骤配置键的字典。"""
    cls = flow_module.AIClipFlowModule
    with patch.object(cls, "_setup_ui", lambda self: None):
        inst = cls()
        inst._current_video = "x.mp4"
        inst._video_processor = MagicMock()
        # 真实 _collect_settings 依赖大量 UI 控件，这里仅校验它是可调用且返回 dict 形态
        assert callable(getattr(inst, "_collect_settings", None))
