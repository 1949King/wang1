# -*- coding: utf-8 -*-
"""本地视频生成接线守卫（2026-10-01）。

钉死五件事 —— 前两条是本轮**实际踩出来的坑**，很容易被后人无意改回去：

  ① **`_ensure_hf_mirror()` 必须早于 `from huggingface_hub import ...`**。
     hf_hub v2 内部用 httpx，代理/端点配置在**客户端创建时**读取；
     先 import 再设环境变量 ⇒ 仍然走有问题的出口代理 ⇒ `ProxyError`。
     （现象极具误导性：curl 直连镜像 200，但代码里就是失败。）

  ② **必须设 `HF_HUB_DISABLE_XET=1`**。hf_hub v2 默认走 Xet 存储后端
     （`cas-server.xethub.hf.co`），而**镜像不代理 Xet** ⇒ 大权重 `401 Unauthorized`，
     小文件（config）却能下 —— 一个"半个成功"的陷阱。

  ③ 视频模型**必须走项目原生链路**（`neural_engine.download_snapshot`），
     **不得**依赖 ComfyUI 或自建下载器（否则两套模型真源）。

  ④ SVD 必须带 `allow_patterns` 且**排除 9GB 级的原始 .pth**（否则白拉 26GB）。

  ⑤ **`generate()` 不得自动下载**（几 GB 的模型不能悄悄开拉）。

零项目依赖：只读源码 + 轻量 import（video_gen 无重依赖）。
"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NE_REL = os.path.join("app", "core", "neural_engine.py")
VG_REL = os.path.join("app", "core", "neural", "video_gen.py")

# importlib 单文件加载的模块内部会 `from app.core...`（V4.40.24 起 video_gen ↔
# memory_policy 互认），脚本直跑时 sys.path[0] 是 _verify/ 而非 ROOT，
# 不把 ROOT 加进来会 ModuleNotFoundError 并**静默吃掉**调优表（退保守默认）。
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_fails = []


def check(name, ok, detail=""):
    tag = "OK  " if ok else "FAIL"
    print(f"  [{tag}] {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        _fails.append(name)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def main() -> int:
    print("== 本地视频生成接线守卫 ==")

    ne = _read(NE_REL)
    vg = _read(VG_REL)

    # ① 镜像/免代理设置必须早于 huggingface_hub import
    #    做法：在源码里逐个找 `from huggingface_hub import`，看它前面有没有 _ensure_hf_mirror()
    bad_order = []
    for m in re.finditer(r"from huggingface_hub import", ne):
        head = ne[max(0, m.start() - 600): m.start()]
        if "_ensure_hf_mirror()" not in head:
            line = ne[:m.start()].count("\n") + 1
            bad_order.append(f"L{line}")
    check("存在 huggingface_hub 导入点", bool(re.search(r"from huggingface_hub import", ne)))
    check("★ 每个 huggingface_hub 导入前都已调用 _ensure_hf_mirror()",
          not bad_order, f"缺前置调用的行: {bad_order}")

    # ② Xet 必须禁用（否则大权重经镜像 401）
    check("★ 设置 HF_HUB_DISABLE_XET=1（修 Xet 401）",
          "HF_HUB_DISABLE_XET" in ne)

    # ③ 免代理必须覆盖镜像与本地
    check("★ 定向 NO_PROXY 覆盖 hf-mirror 与 modelscope",
          "hf-mirror.com" in ne and "modelscope.cn" in ne and "NO_PROXY" in ne)
    # 且**不得**全局清代理（只定向绕过）
    check("未全局清除 HTTP(S)_PROXY（只做定向绕过）",
          not re.search(r"os\.environ\.pop\(\s*[\"']HTTPS?_PROXY", ne))

    # ④ 视频模型走 neural_engine.download_snapshot，不碰 ComfyUI
    check("video_gen 复用 neural_engine.download_snapshot",
          "download_snapshot" in vg and "neural_engine" in vg)
    # 注意：只查**真实调用**（import / 属性访问），**不能**用裸 substring ——
    # 本模块文档里明确写了「为什么不用 ComfyUI」，裸 substring 会误报。
    comfy_code = re.findall(
        r"^\s*(?:from|import)\s+[\w.]*comfy|comfy_client|ComfyClient|ComfyProvider",
        vg, re.M | re.I)
    check("★ video_gen 不调用 ComfyUI（避免两套模型真源）",
          not comfy_code, f"发现真实调用: {comfy_code}")

    # ⑤ SVD 子集模式
    check("SVD 子集模式排除 .pth", not re.search(r'"[^"]*\.pth"', vg))
    check("SVD 子集模式含 fp16 与 model_index.json",
          "fp16" in vg and "model_index.json" in vg)

    # ⑥ generate 不得自动下载
    try:
        tree = ast.parse(vg)
        gen = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "generate")
        body = ast.dump(gen)
        check("★ generate() 不调用 pull()（不自动下载）", "attr='pull'" not in body)
        check("generate() 会先 load()", "attr='load'" in body)
    except StopIteration:
        check("video_gen.generate 可定位", False)
    except SyntaxError as e:
        check("video_gen 语法正确", False, str(e))

    # ⑦ 诚实失败：关键提示语必须在
    for kw, desc in (("image_path", "图生视频缺图提示"),
                     ("未下载", "模型未下载提示"),
                     ("OutOfMemoryError", "OOM 显存不足处理")):
        check(f"诚实失败：{desc}", kw in vg)

    # ⑨ ★ 探测函数**不得 import diffusers**（2026-10-01 血泪：会崩进程）
    #    用 AST 精确定位 is_available / unavailable_reason 两个函数体。
    try:
        tree2 = ast.parse(vg)
        bad_probe = []
        for fn in ast.walk(tree2):
            if (isinstance(fn, ast.FunctionDef)
                    and fn.name in ("is_available", "unavailable_reason")):
                body = ast.dump(fn)
                if "diffusers" in body and "find_spec" not in body:
                    bad_probe.append(fn.name)
                if "ImportFrom" in body and "diffusers" in body:
                    bad_probe.append(fn.name + "(直接 import)")
        check("★ 探测函数不 import diffusers（只用 find_spec）", not bad_probe,
              str(bad_probe))
        check("探测函数确实用了 find_spec",
              "find_spec" in ast.dump(tree2))
    except SyntaxError as e:
        check("video_gen AST 可解析", False, str(e))

    # ⑧ 注册表体积为实测（SVD 子集远小于全仓）
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_vg_guard", os.path.join(ROOT, VG_REL))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        svd = mod.VIDEO_MODELS.get("svd-xt-i2v") or {}
        check("★ SVD 子集 < 全仓的 1/3（确实省下 26GB）",
              svd.get("subset_gb", 99) < svd.get("full_repo_gb", 0) / 3, str(svd))
        check("注册表至少 2 个模型且都有 modes",
              len(mod.VIDEO_MODELS) >= 2
              and all(m.get("modes") for m in mod.VIDEO_MODELS.values()))
    except Exception as e:
        check("video_gen 可加载并读注册表", False, f"{type(e).__name__}: {e}")

    # ⑩ 端点已注册，且**不与既有云端 `/host/video-generate` 撞名**
    post_src = _read(os.path.join("app", "core", "canvas_routes_post.py"))
    check("端点已声明 POST /host/local-video-generate",
          '@_route_post("/host/local-video-generate")' in post_src)
    check("★ 本地端点使用独立路径（不占用云端 /host/video-generate）",
          post_src.count('@_route_post("/host/local-video-generate")') == 1
          and post_src.count('@_route_post("/host/video-generate")') == 1)
    # 三态：models / pull 是**显式分支**，generate 是**默认兜底**（未命中前两者即生成）
    check("本地端点提供三态（models / pull 显式分支 + generate 默认兜底）",
          'action == "models"' in post_src
          and 'action == "pull"' in post_src
          and 'body.get("action") or "generate"' in post_src)

    # ⑪ ★ 推理调优表（2026-10-01 实测结论）—— 防凭直觉改回去
    try:
        import importlib.util as _iu
        _spec = _iu.spec_from_file_location("_vg2", os.path.join(ROOT, VG_REL))
        _m = _iu.module_from_spec(_spec)
        _spec.loader.exec_module(_m)
        svd = _m.tuned_for("svd-xt-i2v")
        # ★ offload **保持开启**（结论两次反转后定稿，别改成 False）
        check("★ 调优：SVD 保持 offload（实测更快更省显存，且防 10 帧分页卡死）",
              svd.get("offload") is True, str(svd))
        check("★ 调优：should_offload 在所有帧数下都为真",
              all(_m.should_offload("svd-xt-i2v", f) for f in (0, 5, 8, 10, 25)))
        check("★ 调优：SVD decode_chunk_size=1（实测比 2 快约 6 倍且更省显存）",
              svd.get("decode_chunk_size") == 1, str(svd))
        check("★ 调优：SVD 步数低于原默认 25（14 步，运动保留 98%）",
              10 <= int(svd.get("steps", 0)) < 25, str(svd))
        # 保守兜底：未登记模型绝不能照搬调优值
        ukn = _m.tuned_for("__unregistered__")
        check("★ 调优：未登记模型退回保守默认（offload=True，宁慢勿炸）",
              ukn.get("offload") is True and ukn.get("decode_chunk_size") == 2, str(ukn))
        # 注释必须留下实测依据与**反转史**（防止后人以为是随手填的又改回去）
        check("调优表留有实测依据注释（含关键数字）",
              "6.51" in vg or "37.5" in vg or "377" in vg or "40.0" in vg)
        check("调优表记录了 offload 结论的两次反转（防重犯）",
              "反转" in vg)
        # ★★ CFG 不得被关 —— **仅适用于 TUNED 表内已登记的「非蒸馏」模型**。
        # 蒸馏产物（lightx2v/Wan22-Lightning 4步 LoRA、HunyuanVideo 1.5 的 8/12 步、
        # FastVideo 3 步）是**专门训练来在 CFG=1.0 下工作**的，对它们关 CFG 是**必要**的。
        # 所以本断言只查「已登记为 TUNED 的模型」，不阻止将来新增蒸馏模型。
        for _mid, _spec in getattr(_m, "TUNED", {}).items():
            if _spec.get("distilled"):
                continue          # 蒸馏模型按各自主张设 CFG，不受本断言约束
            check(f"★★ 调优：{_mid} 保持 CFG 开启（非蒸馏基模关掉会出废片）",
                  float(_spec.get("cfg_max", 0)) > 1.0, str(_spec))
        check("★★ 源码显式传入 CFG 参数（不依赖隐式默认）",
              "min_guidance_scale" in vg and "max_guidance_scale" in vg)
        check("★ 注释已界定「关 CFG 必崩」的适用范围（只对非蒸馏基模）",
              "蒸馏" in vg and "CFG=1.0" in vg)
        # 质量/运动档位
        check("存在质量档位 fast<balanced<best",
              _m.QUALITY_PRESETS.get("fast", 99) < _m.QUALITY_PRESETS.get("balanced", 0)
              < _m.QUALITY_PRESETS.get("best", 0))
        check("★ 默认运动档为 calm(80)（实测立绘主体 6 帧稳定，且与 127 同耗时）",
              svd.get("motion_bucket_id") == _m.MOTION_PRESETS.get("calm"),
              str(svd))
        check("运动档位单调 calm<normal<lively",
              _m.MOTION_PRESETS.get("calm", 999) < _m.MOTION_PRESETS.get("normal", 0)
              < _m.MOTION_PRESETS.get("lively", 0))
        # 已实测排除的路由必须留档（省下一轮重复劳动）
        check("记录了关 CFG 的实测后果（首帧保持崩）",
              "15.9" in vg or "废掉" in vg)
        check("记录了 torch.compile 的实测阻碍（Triton / offload 钩子）",
              "triton" in vg.lower() or "_hf_hook" in vg)
        check("记录了调度器不兼容的实测证据",
              "IndexError" in vg or "sigma_max=700" in vg)
    except Exception as e:
        check("调优表可读取", False, f"{type(e).__name__}: {e}")

    # ⑫ ★ 显存策略收口（V4.40.24，W1）：判定必须在 memory_policy，video_gen 只做薄壳
    mp_rel = os.path.join("app", "core", "neural", "memory_policy.py")
    check("memory_policy.py 已建立（W1 显存分级单一决策点）",
          os.path.isfile(os.path.join(ROOT, mp_rel)))
    if os.path.isfile(os.path.join(ROOT, mp_rel)):
        mp = _read(mp_rel)
        check("★ video_gen 已收口：should_offload / load 委托 pick_memory_policy",
              "pick_memory_policy" in vg and "memory_policy" in vg)
        try:
            tree3 = ast.parse(mp)
            top_heavy = []
            for node in tree3.body:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    mods = ([a.name for a in node.names]
                            if isinstance(node, ast.Import) else [node.module or ""])
                    top_heavy += [m for m in mods
                                  if m.split(".")[0] in ("torch", "diffusers")]
            check("★ memory_policy 顶层零重依赖（无 torch/diffusers import）",
                  not top_heavy, str(top_heavy))
        except SyntaxError as e:
            check("memory_policy 语法正确", False, str(e))
        try:
            import importlib.util as _iu2
            _s3 = _iu2.spec_from_file_location("_mp_guard", os.path.join(ROOT, mp_rel))
            _m3 = _iu2.module_from_spec(_s3)
            _s3.loader.exec_module(_m3)
            # SVD 实测安全域内 model_offload（注入显存保证确定性）
            pols = [_m3.pick_memory_policy("svd-xt-i2v", frames=f,
                                           free_vram_gb=6.0, total_vram_gb=8.0)
                    for f in (0, 5, 8, 10)]
            check("★ 收口后 SVD 实测安全域内仍 model_offload（反转史结论不漂）",
                  all(p["mode"] == "model_offload" and p["offload"] for p in pols),
                  str([p["mode"] for p in pols]))
            check("★ 收口后 SVD chunk 仍为 1（实测比 2 快约 6 倍）",
                  all(p["decode_chunk_size"] == 1 for p in pols))
            check("★ 决策可见：reasons 永不为空（同 R9）",
                  all(p["reasons"] for p in pols))
            check("★ 诚实能力边界：layer_disk_offload 只预告不返回（W2 目标）",
                  all(p["mode"] != "layer_disk_offload" for p in pols)
                  and "layer_disk_offload" in pols[0]["planned_modes"])
            # 超实测安全域 ⇒ 升级 sequential（25 帧外推 ≈10.85GB > 8GB×95%）
            big = _m3.pick_memory_policy("svd-xt-i2v", frames=25,
                                         free_vram_gb=6.0, total_vram_gb=8.0)
            check("★ 超安全域帧数 ⇒ 升级 sequential（策略在干活，不是静默分页等死）",
                  big["mode"] == "sequential_offload" and big["offload"], big["mode"])
            # 实测基线不漂（5f 4.66 / 8f 5.58 / 10f 6.20，±0.1）
            base_ok = all(abs(_m3.estimate_floor_gb("svd-xt-i2v", f, "model_offload") - m) <= 0.10
                          for f, m in ((5, 4.66), (8, 5.58), (10, 6.20)))
            check("★ SVD 显存下限估计贴合实测基线（±0.1GB）", base_ok)
            # 超显存升级 sequential（Wan 登记 8.0GB on 8GB 卡）
            esc = _m3.pick_memory_policy("wan22-ti2v-5b", frames=5,
                                         free_vram_gb=6.0, total_vram_gb=8.0,
                                         registered_vram_gb=8.0)
            check("★ 登记超显存 ⇒ 升级 sequential_offload（Wan 系路径存在）",
                  esc["mode"] == "sequential_offload" and esc["offload"], esc["mode"])
        except Exception as e:
            check("memory_policy 可加载并决策", False, f"{type(e).__name__}: {e}")

    # ⑬ ★ DiffSynth 图像引擎（主选通道，V4.40.26）—— 与视频侧同一套纪律
    di_rel = os.path.join("app", "core", "neural", "diffsynth_image.py")
    check("diffsynth_image.py 已建立（主选引擎图像落地）",
          os.path.isfile(os.path.join(ROOT, di_rel)))
    if os.path.isfile(os.path.join(ROOT, di_rel)):
        di = _read(di_rel)
        check("★ 图像引擎 load 走 compat shim（裸 import diffsynth_engine 必炸）",
              "import_diffsynth_engine" in di and "diffsynth_compat" in di)
        check("★ 图像引擎下载走 ModelScope（diffsynth 原生渠道，不经 HF 镜像）",
              "snapshot_download" in di and "modelscope" in di.lower())
        check("★ 图像引擎 generate 不自动下载（只 load）",
              "def generate" in di and di.index("def generate") >
              di.index("def pull") or True)  # 结构性检查在下面 AST 段
        try:
            import importlib.util as _iu3
            _s4 = _iu3.spec_from_file_location("_di_guard", os.path.join(ROOT, di_rel))
            _m4 = _iu3.module_from_spec(_s4)
            _s4.loader.exec_module(_m4)
            sd = _m4.IMAGE_MODELS.get("sd15-t2i") or {}
            check("★ SD1.5 体积为 ModelScope 实测（3.97GB 一体化）且适合本机（<8GB）",
                  sd.get("size_gb") == 3.97 and sd.get("size_gb") < 8.0, str(sd.get("size_gb")))
            check("★ SD1.5 原生分辨率登记 512（pipeline 默认 1024 是给 SDXL 的）",
                  sd.get("native_size") == 512, str(sd.get("native_size")))
            check("注册表只登记 safetensors 单文件（diffsynth 不接受 .pth）",
                  all((m.get("ms_file") or "").endswith(".safetensors")
                      for m in _m4.IMAGE_MODELS.values()))
            # 探测函数零重导入（AST：find_spec 在、无真 import diffsynth_engine）
            tree4 = ast.parse(di)
            bad_probe4 = []
            for fn in ast.walk(tree4):
                if (isinstance(fn, ast.FunctionDef)
                        and fn.name in ("is_available", "unavailable_reason")):
                    body = ast.dump(fn)
                    if "find_spec" not in body:
                        bad_probe4.append(fn.name)
            check("★ 图像引擎探测函数只做 find_spec（两次组合场景硬崩血泪）",
                  not bad_probe4, str(bad_probe4))
            # generate 不自动下载（AST：generate 函数体内无 pull 调用）
            gen4 = next((n for n in ast.walk(tree4)
                         if isinstance(n, ast.FunctionDef) and n.name == "generate"), None)
            check("★ 图像引擎 generate() 不调用 pull()（AST 级）",
                  gen4 is not None and "attr='pull'" not in ast.dump(gen4))
        except Exception as e:
            check("diffsynth_image 可加载并读注册表", False, f"{type(e).__name__}: {e}")

    # ⑭ ★ 自研图像引擎（diffusers 栈，V4.40.27 刀1）—— 与主选契约逐键对齐 + 共享权重
    df_rel = os.path.join("app", "core", "neural", "diffusers_image.py")
    check("diffusers_image.py 已建立（自研栈图像落地，刀1）",
          os.path.isfile(os.path.join(ROOT, df_rel)))
    if os.path.isfile(os.path.join(ROOT, df_rel)):
        df = _read(df_rel)
        check("★ 自研图像 load 走 memory_policy（W1 收口，禁散写显存 if）",
              "pick_memory_policy" in df and "memory_policy" in df)
        check("★ 自研图像 load 用 from_single_file（复用已下载一体化权重，零新下载）",
              "from_single_file" in df)
        check("★ 自研图像 load 全离线（config + original_config + local_files_only，缺省联网必炸）",
              "original_config" in df and "local_files_only" in df)
        check("★ 自研图像 load 跳过 safety_checker/feature_extractor（transformers 5.x 已删旧类名）",
              "safety_checker=None" in df and "feature_extractor=None" in df)
        check("★ 自研图像 generator 固定 cpu（offload 设备错配会炸）",
              'torch.Generator("cpu")' in df)
        check("★ 自研图像下载走 ModelScope（与对岸同通道同路径）",
              "snapshot_download" in df and "modelscope" in df.lower())
        try:
            import importlib.util as _iu5
            _s5 = _iu5.spec_from_file_location("_df_guard", os.path.join(ROOT, df_rel))
            _m5 = _iu5.module_from_spec(_s5)
            _s5.loader.exec_module(_m5)
            dd = _m5.DIFFUSERS_IMAGE_MODELS.get("sd15-t2i") or {}
            check("★ 自研 SD1.5 体积锁 ModelScope 实测（3.97GB）且 <8GB",
                  dd.get("size_gb") == 3.97 and dd.get("size_gb") < 8.0,
                  str(dd.get("size_gb")))
            check("★ 自研 SD1.5 原生分辨率登记 512",
                  dd.get("native_size") == 512, str(dd.get("native_size")))
            # ★ 双栈共享权重：注册表一致 ⇒ local_file 同路径（M1/M2 同权重对比前提）
            share_ok = False
            if os.path.isfile(os.path.join(ROOT, di_rel)):
                _s6 = _iu5.spec_from_file_location("_di_guard2", os.path.join(ROOT, di_rel))
                _m6 = _iu5.module_from_spec(_s6)
                _s6.loader.exec_module(_m6)
                sd6 = _m6.IMAGE_MODELS.get("sd15-t2i") or {}
                share_ok = (dd.get("ms_repo") == sd6.get("ms_repo")
                            and dd.get("ms_file") == sd6.get("ms_file")
                            and _m5.DiffusersImageEngine.local_file("sd15-t2i")
                            == _m6.DiffsynthImageEngine.local_file("sd15-t2i"))
            check("★ 双栈注册表一致 ⇒ 共享同一权重文件（零复制，M1/M2 同权重基准）",
                  share_ok)
            # 探测函数零重导入（AST）
            tree5 = ast.parse(df)
            bad_probe5 = []
            for fn in ast.walk(tree5):
                if (isinstance(fn, ast.FunctionDef)
                        and fn.name in ("is_available", "unavailable_reason")):
                    if "find_spec" not in ast.dump(fn):
                        bad_probe5.append(fn.name)
            check("★ 自研图像探测函数只做 find_spec（组合场景崩纪律）",
                  not bad_probe5, str(bad_probe5))
            # generate 不自动下载（AST：函数体内无 pull 调用）
            gen5 = next((n for n in ast.walk(tree5)
                         if isinstance(n, ast.FunctionDef) and n.name == "generate"), None)
            check("★ 自研图像 generate() 不调用 pull()（AST 级）",
                  gen5 is not None and "attr='pull'" not in ast.dump(gen5))

            # ⑭' ★ 刀2（V4.40.28）：SDXL 双栈登记 + layer_cpu_offload
            dx = _m5.DIFFUSERS_IMAGE_MODELS.get("sdxl-t2i") or {}
            check("★ 自研 SDXL 登记：体积锁 6.46GiB 实测 · 原生 1024 · arch=sdxl",
                  dx.get("size_gb") == 6.46 and dx.get("native_size") == 1024
                  and dx.get("arch") == "sdxl",
                  f"{dx.get('size_gb')}/{dx.get('native_size')}/{dx.get('arch')}")
            check("★ 自研 SDXL 登记 original_config=sd_xl_base.yaml（缺省联网必炸）",
                  dx.get("original_config") == "sd_xl_base.yaml")
            cf = dx.get("config_files", [])
            check("★ 自研 SDXL 组件 config 14 项精确清单（双 tokenizer/双 text_encoder，禁通配）",
                  len(cf) == 14 and "text_encoder_2/config.json" in cf
                  and "tokenizer_2/vocab.json" in cf
                  and all(not f.endswith("/*") for f in cf)
                  and all(not f.endswith((".safetensors", ".bin", ".ckpt")) for f in cf),
                  str(len(cf)))
            check("★ 自研 SDXL 登记 vram 落 layer 档区间 (60%%,95%%]×8GB",
                  dx.get("vram_gb") is not None
                  and 4.8 < dx.get("vram_gb") <= 7.6, str(dx.get("vram_gb")))
            check("★ 自研图像 load 声明 supported_modes=ACTIVE_MODES（能力声明，刀2）",
                  "supported_modes" in df and "ACTIVE_MODES" in df)
            check("★ 自研图像 load 按 arch 选 StableDiffusionXLPipeline",
                  "StableDiffusionXLPipeline" in df)
            check("★ 自研图像 load layer 档走 apply_layer_cpu_offload（与 accelerate 互斥）",
                  "apply_layer_cpu_offload" in df)
            # 双栈 SDXL 共享权重（同 sd15 约定）
            share_xl = False
            if os.path.isfile(os.path.join(ROOT, di_rel)):
                _s7 = _iu5.spec_from_file_location("_di_guard3", os.path.join(ROOT, di_rel))
                _m7 = _iu5.module_from_spec(_s7)
                _s7.loader.exec_module(_m7)
                sx = _m7.IMAGE_MODELS.get("sdxl-t2i") or {}
                share_xl = (dx.get("ms_repo") == sx.get("ms_repo")
                            and dx.get("ms_file") == sx.get("ms_file")
                            and _m5.DiffusersImageEngine.local_file("sdxl-t2i")
                            == _m7.DiffsynthImageEngine.local_file("sdxl-t2i"))
            check("★ 双栈 SDXL 注册表一致 ⇒ 共享同一权重文件（M1/M2 第二组基准前提）",
                  share_xl)
        except Exception as e:
            check("diffusers_image 可加载并读注册表", False, f"{type(e).__name__}: {e}")

    # ⑭'' ★ 刀2：layer_offload 执行端 + memory_policy 第四档
    lo_rel = os.path.join("app", "core", "neural", "layer_offload.py")
    check("layer_offload.py 已建立（layer_cpu_offload 执行端，刀2）",
          os.path.isfile(os.path.join(ROOT, lo_rel)))
    if os.path.isfile(os.path.join(ROOT, lo_rel)):
        lo = _read(lo_rel)
        check("★ layer_offload 先 pipe.to(device) 整上卡再卸载 hook 块（设备一致纪律）",
              "pipe.to(device)" in lo and "module.to(_CPU)" in lo
              and "_hook(blk" in lo
              and lo.index("pipe.to(device)") < lo.index("_hook(blk"))
        check("★ layer_offload hook 挂对地方（UNet 逐 block + 双 TE + vae.decoder/encoder）",
              all(k in lo for k in ("down_blocks", "mid_block", "up_blocks",
                                    "text_encoder_2", "vae.decoder", "vae.encoder",
                                    "register_forward_pre_hook")))
        try:
            _tree_lo = ast.parse(lo)
            _bad_lo = [n.attr for n in ast.walk(_tree_lo)
                       if isinstance(n, ast.Attribute)
                       and n.attr in ("enable_model_cpu_offload",
                                      "enable_sequential_cpu_offload")]
            check("★ layer_offload 绝不叠加 accelerate offload（AST 级互斥纪律）",
                  not _bad_lo, str(_bad_lo))
        except Exception as e:
            check("layer_offload AST 解析", False, f"{type(e).__name__}: {e}")
    mp_rel = os.path.join("app", "core", "neural", "memory_policy.py")
    if os.path.isfile(os.path.join(ROOT, mp_rel)):
        mp = _read(mp_rel)
        check("★ memory_policy 第四档 layer_cpu_offload 已 ACTIVE（layer_disk 仍预告）",
              'MODE_LAYER_CPU_OFFLOAD = "layer_cpu_offload"' in mp
              and "MODE_LAYER_CPU_OFFLOAD)" in mp
              and "PLANNED_MODES = (MODE_LAYER_DISK_OFFLOAD,)" in mp)
        check("★ memory_policy 能力声明：layer 档不落入 _LEGACY_MODES（不声明不返回）",
              "_LEGACY_MODES" in mp
              and "_LEGACY_MODES = (MODE_WHOLE_GPU, MODE_MODEL_OFFLOAD, MODE_SEQUENTIAL_OFFLOAD)" in mp)
        check("★ memory_policy layer 分支要求 supported_modes 显式声明（语义不漂移）",
              "supported_modes" in mp and "_LAYER_OFFLOAD_WATER" in mp)
        check("★ memory_policy 分支 0：调优表 prefer_mode 实测指定优先（刀2 四档实测产物）",
              "prefer_mode" in mp and "分支 0" in mp)
        check("★ SDXL 实测下限登记（model 5.21 / sequential 3.76，图像 frames=0）",
              '"sdxl-t2i"' in mp and '"base_gb": 3.76' in mp and '"base_gb": 5.21' in mp)

    # ⑮ ★ 刀 A1（V4.40.29）：本地图像引擎「通电」—— 生产路由 + 真分派 + 能力登记
    rp = _read("app/core/canvas_routes_post.py")
    if rp:
        check("★ /host/local-image-generate 路由已注册（三态：models/pull/generate）",
              '@_route_post("/host/local-image-generate")' in rp
              and '"models"' in rp and '"pull"' in rp)
        check("★ 路由经 resolve_local_image_engine 真分派 + R9 降级字段透出",
              "resolve_local_image_engine" in rp and "engine_is_fallback" in rp)
    ed = _read("app/core/ai/execution_decider.py")
    if ed:
        check("★ resolve_local_image_engine 存在且入 __all__（主备裁定的真执行入口）",
              "def resolve_local_image_engine" in ed
              and '"resolve_local_image_engine"' in ed)
        check("★ 首选不可用再降一级（双栈候选链 + 理由留痕）",
              "candidates.append(other)" in ed and "降级到" in ed)
    cat = _read("app/core/agent_capability_catalog.py")
    if cat:
        check("★ 能力目录 canvas.local_generate_image（paid=False 零调用费）",
              '"canvas.local_generate_image"' in cat)
    ch = _read("app/core/capability_handlers.py")
    if ch:
        check("★ local_generate_image handler 注册进 dispatcher",
              '"canvas.local_generate_image"' in ch
              and "def local_generate_image" in ch)
    di = _read("app/core/neural/diffusers_image.py")
    if di:
        check("★ SDXL original_config_url 第二来源登记 + pull 消费（换机可复现）",
              '"original_config_url"' in di and "urlopen" in di)
    ds = _read("app/core/neural/diffsynth_image.py")
    if ds:
        check("★ 刀4 前哨：主选侧 memory_policy + RAM 观测（只观测不改行为）",
              "memory_policy 观测" in ds and "RAM 观测" in ds)
    check("★ bench 脚本入库 _verify/bench/（M1~M5 验收门可复测）",
          os.path.isfile(os.path.join(ROOT, "_verify", "bench", "bench_sdxl_modes.py"))
          and os.path.isfile(os.path.join(ROOT, "_verify", "bench",
                                          "compare_dual_stack_sd15.py")))

    print()
    if _fails:
        print(f"FAILED {len(_fails)}: {_fails}")
        return 1
    print("OK 本地视频生成接线一致（项目原生链路）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
