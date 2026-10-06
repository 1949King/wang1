"""app/tests/test_layer_offload.py — layer_cpu_offload 执行端回归（2026-10-03，刀2）。

锁定的纪律（全部源码/AST 锁，**不真 import torch、不加载模型**）：
  ① **顶层零重依赖** —— torch 只在函数内 import（pytest 组合场景血泪）；
  ② **hook 挂对地方** —— UNet 逐 block（down/mid/up）、双 text_encoder、
     vae.decoder/vae.encoder（⚠️ vae.decode/encode 不走 vae.forward，
     挂 vae 本体 = hook 死代码）；
  ③ **先整上卡再卸载** —— pipe.to(device) 必须在挂 hook 之前
     （否则 pipe.device=cpu，中间张量全线设备错配）；
  ④ **与 accelerate offload 互斥** —— 本模块绝不调 enable_model/sequential_cpu_offload；
  ⑤ **诚实上报** —— 返回挂接清单（决策可见性同 R9），CUDA 缺失直接 raise
     （由调用方 try/except 兜底层级回退，绝不静默假成功）。
"""
import ast
import inspect
import pathlib

from app.core.neural import layer_offload as L


def test_top_level_no_heavy_imports():
    """★ 顶层不得 import torch/diffusers（与 memory_policy 同戒律）。"""
    src = pathlib.Path(L.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = " ".join(a.name for a in node.names)
            mod = getattr(node, "module", "") or ""
            for heavy in ("torch", "diffusers", "modelscope"):
                assert heavy not in names and heavy not in mod, (heavy, node.lineno)


def test_hooks_target_real_forward_modules():
    """★ 挂接清单：UNet 逐 block + 双 text_encoder + vae.decoder/encoder。
    vae 本体挂上没用（decode/encode 是普通方法，不触发 vae.forward）。"""
    src = inspect.getsource(L.apply_layer_cpu_offload)
    for needle in ("down_blocks", "mid_block", "up_blocks",
                   "text_encoder", "text_encoder_2",
                   "vae.decoder", "vae.encoder"):
        assert needle in src, needle
    # hook 注册用的是 PyTorch 原生 API（不引入包装类）
    assert "register_forward_pre_hook" in src
    assert "register_forward_hook" in src


def test_pipe_on_device_before_unloading_blocks():
    """★ 顺序锁：pipe.to(device) 整上卡必须先于**首个 _hook 调用点**
    （hook 块的 module.to(_CPU) 卸载发生在 _hook 内；比的是执行序不是文本序）。
    反了 = pipe.device 推导成 cpu，prompt_embeds/latents 全线错配。"""
    src = inspect.getsource(L.apply_layer_cpu_offload)
    assert "pipe.to(device)" in src and "module.to(_CPU)" in src
    first_hook_call = src.index("_hook(blk")   # 首个挂接调用点（UNet down_blocks）
    assert src.index("pipe.to(device)") < first_hook_call


def test_no_accelerate_offload_mixed_in():
    """★ 互斥纪律：本模块绝不调 accelerate 的两种 offload（引擎 load() 分支保证
    二选一）。★ 必须 AST 查真实属性节点 —— docstring 里写「绝不调
    enable_model_cpu_offload」也会命中裸 substring（本用例踩过）。"""
    src = pathlib.Path(L.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in ("enable_model_cpu_offload",
                                     "enable_sequential_cpu_offload"), node.attr


def test_reports_hooked_list_and_marks_pipe():
    """★ 诚实上报：返回挂接清单 + 管道打标记（排查时能确认走的是 layer 档）。"""
    src = inspect.getsource(L.apply_layer_cpu_offload)
    assert '"hooked"' in src
    assert "_shiguang_layer_cpu_offload" in src


def test_raises_without_cuda():
    """★ CUDA 缺失必须 raise（由引擎 try/except 兜底回退整卡），
    绝不静默「假装挂上了」。"""
    src = inspect.getsource(L.apply_layer_cpu_offload)
    assert "raise RuntimeError" in src
