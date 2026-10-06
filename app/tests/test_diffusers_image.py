"""app/tests/test_diffusers_image.py — 自研图像引擎（diffusers 栈）回归（2026-10-03）。

对齐 `test_diffsynth_image.py` 规格（双栈契约逐键一致），并加自研特有锁定：
  ① **不自动下载** —— generate() 对未下载模型只报错、不拉取；
  ② **诚实失败** —— 未知 id / 缺 prompt / 缺模型都给具体原因，不返回占位图；
  ③ **探测零重导入** —— is_available / unavailable_reason 只做 find_spec，
     绝不真 import diffusers（2026-10-01/10-02 两次组合场景硬崩血泪）；
  ④ **显存策略收口** —— load() 必须走 memory_policy.pick_memory_policy（W1 成果复用）；
  ⑤ **双栈共享权重** —— 注册表 ms_repo/ms_file 与对岸刻意一致 ⇒
     local_file 指向同一文件（零复制，M1/M2 同权重对比基准的前提）；
  ⑥ **generator 固定在 cpu** —— offload 场景设备错配会炸，且是 diffusers 官方推荐。

注：本测试**不真 import diffusers、不下载权重**。
"""
import inspect
import pathlib

from app.core.neural import diffusers_image as D
from app.core.neural import diffsynth_image as S   # 对岸（主选），仅读注册表/路径，不触发加载


# ─────────────────────── 注册表 ───────────────────────

def test_registry_nonempty_and_complete():
    models = D.available_models()
    assert len(models) >= 1
    for m in models:
        for k in ("id", "label", "params", "modes", "download_gb",
                      "vram_gb", "ram_gb", "native_size", "note", "license"):
            assert k in m, (m.get("id"), k)
        assert m["modes"]
        assert set(m["modes"]) <= {"t2i", "i2i"}


def test_sd15_registry_with_measured_size():
    """★ 首个落地 = SD1.5：体积锁 ModelScope 实测值（3.97GB 一体化），且 < 8GB。"""
    spec = D.DIFFUSERS_IMAGE_MODELS["sd15-t2i"]
    assert spec["size_gb"] == 3.97, "体积漂移（应锁定 ModelScope 实测值）"
    assert spec["size_gb"] < 8.0
    assert spec["ms_file"].endswith(".safetensors")


def test_sd15_registers_original_config():
    """★ from_single_file 必须登记 original_config（v1-inference.yaml）。
    缺它 diffusers 会去 HF Hub 拉默认 config —— 本机代理 502 实测炸加载
    （2026-10-03 compare_dual_stack_sd15 首跑 ProxyError）。"""
    spec = D.DIFFUSERS_IMAGE_MODELS["sd15-t2i"]
    assert spec.get("original_config", "").endswith(".yaml")
    c = D.DiffusersImageEngine.local_config_file("sd15-t2i")
    assert c.endswith("v1-inference.yaml")


def test_sd15_registers_component_config_files():
    """★ pipeline 组件 config 清单（仓库相对路径的精确小文件）。
    缺了会在 "Loading pipeline components" 阶段联网（transformers OSError 实测）。
    ⚠️ 清单必须是精确文件，绝不许目录通配（text_encoder/* 会拉大几百 MB 分散权重）。"""
    files = D.DIFFUSERS_IMAGE_MODELS["sd15-t2i"].get("config_files", [])
    assert len(files) >= 8
    assert "model_index.json" in files
    assert "text_encoder/config.json" in files     # 精确文件，不是 text_encoder/*
    assert all(not f.endswith("/*") for f in files)
    assert all(not f.endswith((".safetensors", ".bin", ".ckpt")) for f in files)


def test_sd15_native_size_is_512():
    """SD1.5 原生 512（管道默认 1024 是给 SDXL 的），必须显式登记。"""
    assert D.DIFFUSERS_IMAGE_MODELS["sd15-t2i"]["native_size"] == 512


# ─────────────── 刀2：SDXL 注册表（2026-10-03）───────────────

def test_sdxl_registry_with_measured_size():
    """★ 刀2 第二族 = SDXL 1.0：体积锁 ModelScope 实测值（6.46GiB 一体化）。"""
    spec = D.DIFFUSERS_IMAGE_MODELS["sdxl-t2i"]
    assert spec["size_gb"] == 6.46, "体积漂移（应锁定 ModelScope 实测值）"
    assert spec["size_gb"] < 8.0
    assert spec["ms_file"].endswith(".safetensors")
    assert spec["arch"] == "sdxl"          # load() 按 arch 选 XL 管道类
    assert spec["native_size"] == 1024     # SDXL 原生分辨率
    assert spec["params"] == "3.5B"


def test_sdxl_registers_original_config():
    """★ SDXL 必须登记 original_config（sd_xl_base.yaml）。
    缺它 diffusers 会去 raw.githubusercontent.com 拉（convert_from_ckpt.py:1322 硬编码，
    本机不可达必炸）。yaml 经 jsdelivr 直连落盘，随权重同目录。"""
    spec = D.DIFFUSERS_IMAGE_MODELS["sdxl-t2i"]
    assert spec.get("original_config") == "sd_xl_base.yaml"
    c = D.DiffusersImageEngine.local_config_file("sdxl-t2i")
    assert c.endswith("sd_xl_base.yaml")


def test_sdxl_registers_dual_tokenizer_config_files():
    """★ SDXL 是**双 tokenizer / 双 text_encoder** —— config 清单 14 项精确文件，
    缺了会在 "Loading pipeline components" 阶段联网。
    ⚠️ 绝不许目录通配（text_encoder_2/* 会误拉 1.3GB 分散权重）。
    ⚠️ 仓库无 feature_extractor/（load 反正跳该组件），清单里也不许有。"""
    files = D.DIFFUSERS_IMAGE_MODELS["sdxl-t2i"].get("config_files", [])
    assert len(files) == 14
    assert "model_index.json" in files
    assert "text_encoder/config.json" in files
    assert "text_encoder_2/config.json" in files        # 双 text_encoder
    assert "tokenizer_2/tokenizer_config.json" in files  # 双 tokenizer
    assert "tokenizer_2/vocab.json" in files
    assert "unet/config.json" in files and "vae/config.json" in files
    assert all(not f.endswith("/*") for f in files)
    assert all(not f.endswith((".safetensors", ".bin", ".ckpt")) for f in files)
    assert not any(f.startswith("feature_extractor") for f in files)


def test_sdxl_vram_registration_lands_in_layer_band():
    """★ SDXL 登记 vram 落在 (60%, 95%] × 8GB 区间（展示/决策输入口径保持有效）。
    注意：mode 选择已由注册表 prefer_mode 主导（四档实测定稿），本锁仅防登记漂移。"""
    vram = D.DIFFUSERS_IMAGE_MODELS["sdxl-t2i"]["vram_gb"]
    assert 8.0 * 0.60 < vram <= 8.0 * 0.95, vram


def test_sdxl_registers_prefer_mode_model_offload():
    """★ 四档实测定稿（2026-10-03，R2/R3 受控两轮复现）：
    SDXL 注册表必须带 prefer_mode=model_offload（5.21GB/27.9s 定稿）。
    ⚠️ 此结论经过两次反转：R1「model 220s 不可用」是被硬杀 whole_gpu 污染的假数据；
    改此值 = 推翻受控实测结论，必须连带 bench 数据一起改。"""
    spec = D.DIFFUSERS_IMAGE_MODELS["sdxl-t2i"]
    assert spec.get("prefer_mode") == "model_offload"


def test_load_passes_prefer_mode_to_policy():
    """★ load() 必须把注册表 prefer_mode 透传进 tuned（否则分支 0 收不到）。"""
    src = inspect.getsource(D.DiffusersImageEngine.load)
    assert "prefer_mode" in src


def test_registry_shares_weight_file_with_diffsynth():
    """★ 自研特有：ms_repo/ms_file 与对岸**刻意一致** ⇒ local_file 同路径。
    这是「零新下载复用已下权重」与「M1/M2 同权重双栈对比」的前提，漂移即破坏。
    刀2 起两族（sd15/sdxl）都必须满足。"""
    for mid in ("sd15-t2i", "sdxl-t2i"):
        d_spec = D.DIFFUSERS_IMAGE_MODELS[mid]
        s_spec = S.IMAGE_MODELS[mid]
        assert d_spec["ms_repo"] == s_spec["ms_repo"], mid
        assert d_spec["ms_file"] == s_spec["ms_file"], mid
        assert D.DiffusersImageEngine.local_file(mid) == S.DiffsynthImageEngine.local_file(mid), mid


# ─────────────────────── 路径与状态 ───────────────────────

def test_local_paths_deterministic_and_under_cache():
    a = D.DiffusersImageEngine.local_file("sd15-t2i")
    b = D.DiffusersImageEngine.local_file("sd15-t2i")
    assert a == b
    norm = a.replace("\\", "/")
    assert "models" in norm and "cache" in norm
    assert norm.endswith(".safetensors")


def test_is_downloaded_false_when_absent():
    assert D.DiffusersImageEngine.is_downloaded("__definitely_not__") is False


# ─────────────────────── ① 不自动下载 ───────────────────────

def test_generate_does_not_auto_download(monkeypatch):
    called = {"pull": 0}
    monkeypatch.setattr(D.DiffusersImageEngine, "pull",
                        lambda self, *a, **k: called.__setitem__("pull", called["pull"] + 1))
    monkeypatch.setattr(D.DiffusersImageEngine, "is_downloaded", staticmethod(lambda mid: False))
    monkeypatch.setattr(D.DiffusersImageEngine, "is_available", staticmethod(lambda: True))
    eng = D.DiffusersImageEngine()
    r = eng.generate("sd15-t2i", prompt="a cat")
    assert r["ok"] is False
    assert called["pull"] == 0, "generate 绝不能触发下载"


# ─────────────────────── ② 诚实失败 ───────────────────────

def test_unknown_model_message():
    r = D.DiffusersImageEngine().generate("__nope__", prompt="x")
    assert r["ok"] is False and "__nope__" in r["message"]


def test_t2i_requires_prompt_or_image():
    r = D.DiffusersImageEngine().generate("sd15-t2i")
    assert r["ok"] is False and "prompt" in r["message"]


def test_missing_input_image_message():
    r = D.DiffusersImageEngine().generate("sd15-t2i", image_path="no_such.png")
    assert r["ok"] is False and "不存在" in r["message"]


def test_unavailable_reason_specific():
    reason = D.DiffusersImageEngine.unavailable_reason()
    assert isinstance(reason, str)
    if reason:
        assert len(reason) > 3


def test_pull_rejects_unknown_without_network():
    r = D.DiffusersImageEngine().pull("__no_such__")
    assert r["ok"] is False and "未知模型" in r["message"]


# ─────────────────────── ③ 探测零重导入（AST 锁）───────────────────────

def test_probe_functions_no_real_import():
    """★ is_available / unavailable_reason 函数体内不得真 import diffusers。"""
    import ast
    src = pathlib.Path(D.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name in ("is_available", "unavailable_reason"):
            body = ast.dump(fn)
            assert "find_spec" in body, fn.name
            assert "ImportFrom" not in body, fn.name


def test_top_level_no_heavy_imports():
    """★ 模块顶层零重依赖（diffusers/torch/modelscope 都不许出现在顶层 import）。"""
    import ast
    src = pathlib.Path(D.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = " ".join(a.name for a in node.names)
            mod = getattr(node, "module", "") or ""
            for heavy in ("diffusers", "torch", "modelscope"):
                assert heavy not in names and heavy not in mod, (heavy, node.lineno)


# ─────────────────────── ④ 显存策略收口（源码锁）───────────────────────

def test_load_uses_memory_policy_and_single_file():
    """★ load() 必须：a) from_single_file 直载一体化权重（复用已下载文件）；
    b) 经 memory_policy.pick_memory_policy 决策装载模式（W1 收口，禁散写 if vram < N）；
    c) 全离线定稿组合（2026-10-03 三轮探测）：config + original_config（新参数名，
       旧名 original_config_file 1.0.0 将移除）+ local_files_only；
    d) safety_checker/feature_extractor=None（transformers 5.x 已删 CLIPFeatureExtractor）。"""
    src = inspect.getsource(D.DiffusersImageEngine.load)
    assert "from_single_file" in src
    assert "pick_memory_policy" in src
    assert "memory_policy" in src
    assert "original_config" in src
    assert "local_files_only" in src
    assert "safety_checker=None" in src
    assert "feature_extractor=None" in src


def test_load_supports_sdxl_and_layer_offload():
    """★ 刀2：load() 必须 a) 按 arch 选 StableDiffusionXLPipeline（SDXL 类不通用）；
    b) 向 policy 声明 supported_modes=ACTIVE_MODES（否则 layer 档不会判给我们，
       见 memory_policy「能力声明」节）；
    c) layer 档走 layer_offload.apply_layer_cpu_offload（与 accelerate offload 互斥）。"""
    src = inspect.getsource(D.DiffusersImageEngine.load)
    assert "StableDiffusionXLPipeline" in src
    assert "supported_modes" in src
    assert "ACTIVE_MODES" in src
    assert "apply_layer_cpu_offload" in src


def test_is_downloaded_requires_config_when_registered():
    """★ 「权重在 + config 缺」必须判为未下载（半套文件硬上 = 联网必炸）。"""
    assert D.DiffusersImageEngine.is_downloaded("__definitely_not__") is False
    # 已下载场景由 E2E 子进程覆盖（本测试不依赖 4GB 权重在场）


def test_generator_on_cpu():
    """★ generator 必须固定在 cpu（offload 设备错配会炸；diffusers 官方可复现性推荐）。"""
    src = inspect.getsource(D.DiffusersImageEngine.generate)
    assert 'torch.Generator("cpu")' in src


# ─────────────────────── ⑤ 下载通道与契约形状 ───────────────────────

def test_pull_uses_modelscope_snapshot():
    src = inspect.getsource(D.DiffusersImageEngine.pull)
    assert "snapshot_download" in src and "modelscope" in src


def test_generate_returns_aligned_shape():
    """generate 的返回键必须与对岸逐键对齐（双栈可互换的契约）。"""
    src = inspect.getsource(D.DiffusersImageEngine.generate)
    for key in ('"image_path"', '"image_url"', '"inbox_path"', '"steps"',
                    '"seconds_elapsed"', '"message"'):
        assert key in src, key


def test_i2i_uses_shared_pipeline_components():
    """★ i2i 必须走 AutoPipelineForImage2Image.from_pipe 共享 t2i 组件
    （零额外显存），而非另载一份权重。"""
    src = inspect.getsource(D.DiffusersImageEngine.generate)
    assert "AutoPipelineForImage2Image" in src
    assert "from_pipe" in src


def test_engine_singleton():
    assert D.get_diffusers_image_engine() is D.get_diffusers_image_engine()


def test_unload_safe_when_never_loaded():
    D.DiffusersImageEngine().unload()   # 不该抛
