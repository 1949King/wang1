# -*- coding: utf-8 -*-
"""SDXL 四档实测 + 双栈 M1/M2 第二组基准（刀2-4，2026-10-03）。

★ 已入库（刀 A1，2026-10-04，自 .workbuddy/tmp 迁入）：M1~M5 验收门可复测，
  不再漂在临时目录。运行：`python _verify/bench/bench_sdxl_modes.py`（需 GPU + 权重在盘）。

用法：
  无参      ⇒ 驱动：逐档起子进程（冷态公平 + 单档超时可杀），汇总出表
  --one X   ⇒ 工人：只跑 X 档，stdout 末行输出 "RESULT {json}"

档（自研 diffusers 栈四种装载）：
  whole_gpu    整模型上卡（预期 OOM 或 WDDM 分页 —— 诚实记录，这本身就是数据）
  model        enable_model_cpu_offload（整组件换入换出）
  sequential   enable_sequential_cpu_offload（逐叶子模块，最省显存最慢）
  layer_cpu    apply_layer_cpu_offload（刀2 新档：block 组 hook 逐层卸载）
另有两条引擎整链路（验证 #197 接线 + M1/M2 取值）：
  engine       自研引擎 load("sdxl-t2i")（policy 应判 layer_cpu）→ generate
  diffsynth    主选引擎 load("sdxl-t2i")（cpu_offload）→ generate

验收门（写死单点，勿分散）：
  刀2 档验收：layer_cpu 峰值显存 ≤ model × 0.90（「显著低于」的量化口径）
  M1 = engine 峰值 ≤ diffsynth 峰值 × 1.10
  M2 = engine 耗时 ≤ diffsynth 耗时 × 1.25（即「不慢于 80%」）

★ 参数与 SD1.5 基线同一套 COMMON（compare_dual_stack_sd15.py），跨模型可比。
★ 每档独立子进程 = 最干净的冷态；whole_gpu 设 420s 墙钟超时防 WDDM 卡死。
"""
import json
import os
import subprocess
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

MID = "sdxl-t2i"
OUT_DIR = os.path.join(".workbuddy", "tmp")
# 与 SD1.5 基线同一套 COMMON（单点常量，防双栈/跨模型漂移）
COMMON = {
    "prompt": "masterpiece, best quality, 1girl, anime style, standing in a sunlit garden, "
              "flowing dress, detailed background",
    "negative_prompt": "lowres, bad anatomy, bad hands, text, error, blurry",
    "seed": 42,
    "steps": 20,
    "cfg": 7.5,
    "width": 1024,
    "height": 1024,
}
# 各档墙钟超时（秒）：sequential 逐叶搬运最慢给足；whole_gpu 防分页卡死给硬上限
TIMEOUTS = {"whole_gpu": 420, "model": 600, "sequential": 1200,
            "layer_cpu": 600, "engine": 600, "diffsynth": 600}
LAYER_VS_MODEL_GATE = 0.90   # 「layer 显著低于 model」的量化口径
M1_GATE, M2_GATE = 1.10, 1.25


# ════════════════════════ 工人（子进程内）════════════════════════
def _peak_gb() -> float:
    import torch
    return round(torch.cuda.max_memory_allocated() / (1024 ** 3), 2)


def _reset_peak() -> None:
    import torch
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()


# ★ 两相峰口径（V2 修正，2026-10-03）：
#   peak_setup_gb = 装载+档位施加阶段的峰值（layer_cpu 的「整上卡再下块」瞬时峰在这里，
#                   首轮把它误当全程峰 ⇒ 6.57GB 假高峰，修正）
#   peak_gen_gb   = 生成稳态峰值（M1 与档验收的判定口径；reset 在 generate 前一刻）
def work_diffusers(mode: str) -> dict:
    import time as _t
    import torch
    from diffusers import StableDiffusionXLPipeline
    from app.core.neural.diffusers_image import DiffusersImageEngine as E

    _reset_peak()
    t0 = _t.time()
    pipe = StableDiffusionXLPipeline.from_single_file(
        E.local_file(MID), config=E.local_dir(MID),
        original_config=(E.local_config_file(MID) or None),
        torch_dtype=torch.float16, use_safetensors=True,
        local_files_only=True, safety_checker=None, feature_extractor=None)
    if mode == "whole_gpu":
        pipe.to("cuda")
    elif mode == "model":
        pipe.enable_model_cpu_offload()
    elif mode == "sequential":
        pipe.enable_sequential_cpu_offload()
    elif mode == "layer_cpu":
        from app.core.neural.layer_offload import apply_layer_cpu_offload
        apply_layer_cpu_offload(pipe)
    t_load = round(_t.time() - t0, 1)
    peak_setup = _peak_gb()

    torch.cuda.reset_peak_memory_stats()
    gen = torch.Generator("cpu").manual_seed(COMMON["seed"])
    out = os.path.join(OUT_DIR, f"sdxl_{mode}.png")
    t0 = _t.time()
    img = pipe(
        prompt=COMMON["prompt"], negative_prompt=COMMON["negative_prompt"],
        guidance_scale=COMMON["cfg"], height=COMMON["height"], width=COMMON["width"],
        num_inference_steps=COMMON["steps"], generator=gen).images[0]
    t_gen = round(_t.time() - t0, 1)
    os.makedirs(OUT_DIR, exist_ok=True)
    img.save(out)
    return {"ok": True, "mode": mode, "t_load": t_load, "t_gen": t_gen,
            "peak_setup_gb": peak_setup, "peak_gen_gb": _peak_gb(), "out": out}


def work_engine() -> dict:
    """自研引擎整链路（policy 按注册表 prefer_mode 应判 sequential —— 验证决策-执行一致）。"""
    from app.core.neural.diffusers_image import get_diffusers_image_engine
    eng = get_diffusers_image_engine()
    eng.unload()
    _reset_peak()
    t0 = time.time()
    r = eng.load(MID)
    t_load = round(time.time() - t0, 1)
    if not r["ok"]:
        return {"ok": False, "mode": "engine", "message": r["message"]}
    peak_setup = _peak_gb()
    import torch
    torch.cuda.reset_peak_memory_stats()
    t0 = time.time()
    g = eng.generate(MID, out_path=os.path.join(OUT_DIR, "sdxl_engine.png"), **COMMON)
    t_gen = round(time.time() - t0, 1)
    res = {"ok": g["ok"], "mode": "engine", "t_load": t_load, "t_gen": t_gen,
           "peak_setup_gb": peak_setup, "peak_gen_gb": _peak_gb(),
           "offload": eng._offload, "message": g.get("message", "")}
    eng.unload()
    return res


def work_diffsynth() -> dict:
    """主选引擎整链路（DiffSynth SDXLImagePipeline + cpu_offload）。"""
    from app.core.neural.diffsynth_image import get_image_engine
    eng = get_image_engine()
    eng.unload()
    _reset_peak()
    t0 = time.time()
    r = eng.load(MID)
    t_load = round(time.time() - t0, 1)
    if not r["ok"]:
        return {"ok": False, "mode": "diffsynth", "message": r["message"]}
    peak_setup = _peak_gb()
    import torch
    torch.cuda.reset_peak_memory_stats()
    t0 = time.time()
    g = eng.generate(MID, out_path=os.path.join(OUT_DIR, "sdxl_diffsynth.png"), **COMMON)
    t_gen = round(time.time() - t0, 1)
    res = {"ok": g["ok"], "mode": "diffsynth", "t_load": t_load, "t_gen": t_gen,
           "peak_setup_gb": peak_setup, "peak_gen_gb": _peak_gb(),
           "message": g.get("message", "")}
    eng.unload()
    return res


def work(mode: str) -> dict:
    try:
        if mode in ("whole_gpu", "model", "sequential", "layer_cpu"):
            return work_diffusers(mode)
        if mode == "engine":
            return work_engine()
        if mode == "diffsynth":
            return work_diffsynth()
        return {"ok": False, "mode": mode, "message": f"未知档 {mode}"}
    except Exception as e:  # 单档失败必须诚实记录并继续其它档
        return {"ok": False, "mode": mode,
                "message": f"{type(e).__name__}: {str(e)[:300]}"}


# ════════════════════════ 驱动 ════════════════════════
def _gpu_telemetry() -> dict:
    """nvidia-smi 遥测快照（降频证据钉进数据：频率/温度/功耗/显存占用）。"""
    try:
        p = subprocess.run(
            ["nvidia-smi", "--query-gpu=clocks.sm,temperature.gpu,power.draw,memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15)
        parts = [x.strip() for x in p.stdout.strip().split(",")]
        return {"clocks_sm_mhz": parts[0], "temp_c": parts[1],
                "power_w": parts[2], "mem_used_mib": parts[3]}
    except Exception as e:  # 遥测失败不阻塞测量
        return {"error": f"{type(e).__name__}: {e}"}


def drive() -> int:
    # whole_gpu 首轮已证伪（420s 墙钟超时已杀，WDDM 分页卡死）—— 复用结论不重跑
    results = {"whole_gpu": {"ok": False, "mode": "whole_gpu",
                             "message": "首轮已证伪：420s 墙钟超时已杀（WDDM 分页卡死）",
                             "reused_round1": True}}
    modes = ["model", "sequential", "layer_cpu", "engine", "diffsynth"]
    # --modes a,b,c 只跑指定档（异常值裁决探针用）
    if "--modes" in sys.argv:
        modes = sys.argv[sys.argv.index("--modes") + 1].split(",")
    # R3 受控协议：每档前 GPU 冷却（消顺序/热污染），遥测快照进数据
    COOLDOWN_S = 25
    for i, m in enumerate(modes):
        if i:
            print(f"----- 冷却 {COOLDOWN_S}s（消热/顺序污染）...", flush=True)
            time.sleep(COOLDOWN_S)
        tele_before = _gpu_telemetry()
        print(f"===== [{m}] 子进程开跑（超时 {TIMEOUTS[m]}s）遥测前={tele_before} =====",
              flush=True)
        t0 = time.time()
        try:
            p = subprocess.run(
                [sys.executable, os.path.abspath(__file__), "--one", m],
                capture_output=True, text=True, timeout=TIMEOUTS[m], cwd=ROOT,
                encoding="utf-8", errors="replace")
            line = next((ln for ln in reversed(p.stdout.splitlines())
                         if ln.startswith("RESULT ")), None)
            if line:
                results[m] = json.loads(line[len("RESULT "):])
            else:
                results[m] = {"ok": False, "mode": m,
                              "message": f"无 RESULT 行（exit={p.returncode}）"
                                         f" stderr: {(p.stderr or '')[-300:]}"}
        except subprocess.TimeoutExpired:
            results[m] = {"ok": False, "mode": m,
                          "message": f"墙钟超时 {TIMEOUTS[m]}s 已杀（疑似 WDDM 分页卡死）"}
        results[m]["wall_s"] = round(time.time() - t0, 1)
        results[m]["telemetry_before"] = tele_before
        results[m]["telemetry_after"] = _gpu_telemetry()
        print(f"----- [{m}] {results[m]}", flush=True)

    all_modes = ["whole_gpu"] + modes
    print("\n===== SDXL 四档 + 双栈汇总（两相峰口径 V2）=====")
    print(f"{'档':<12}{'ok':<6}{'load/s':<9}{'gen/s':<9}{'peak装载':<10}{'peak生成':<10}{'备注'}")
    for m in all_modes:
        r = results[m]
        note = r.get("offload", "") or (r.get("message", "")[:56] if not r.get("ok") else "")
        print(f"{m:<12}{str(r.get('ok')):<6}{str(r.get('t_load', '-')):<9}"
              f"{str(r.get('t_gen', '-')):<9}{str(r.get('peak_setup_gb', '-')):<10}"
              f"{str(r.get('peak_gen_gb', '-')):<10}{note}")

    # ── 档对比（peak_gen 稳态口径）：sequential vs model vs layer ──
    if not all(k in results for k in ("sequential", "model", "layer_cpu")):
        print("\n（子集运行，跳过档对比/M1M2 汇总）")
        with open(os.path.join(OUT_DIR, "bench_sdxl_modes.json"), "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        return 0
    print("\n===== 档对比（首轮已证伪 whole_gpu；本轮判 model/sequential/layer）=====")
    r_s, r_m, r_l = results["sequential"], results["model"], results["layer_cpu"]
    if r_s.get("ok") and r_m.get("ok"):
        print(f"sequential {r_s['peak_gen_gb']}GB/{r_s['t_gen']}s vs "
              f"model {r_m['peak_gen_gb']}GB/{r_m['t_gen']}s "
              f"⇒ sequential 两轴{'更优' if r_s['peak_gen_gb'] < r_m['peak_gen_gb'] and r_s['t_gen'] < r_m['t_gen'] else '未全胜'}")
    if r_l.get("ok") and r_s.get("ok"):
        ratio = r_l["peak_gen_gb"] / r_s["peak_gen_gb"]
        spd = r_l["t_gen"] / r_s["t_gen"]
        print(f"layer_cpu {r_l['peak_gen_gb']}GB/{r_l['t_gen']}s vs "
              f"sequential {r_s['peak_gen_gb']}GB/{r_s['t_gen']}s "
              f"⇒ 显存比 {ratio:.2f} · 速度比 {spd:.2f}"
              f"（layer v1 {'落败留档' if spd > 1 else '翻盘，需复评'}）")

    # ── M1/M2 第二组：engine（按 prefer_mode 应判 sequential）vs diffsynth ──
    print("\n===== M1/M2（第二组，peak_gen 稳态口径）=====")
    r_e, r_d = results["engine"], results["diffsynth"]
    if r_e.get("ok") and r_d.get("ok"):
        m1 = r_e["peak_gen_gb"] / r_d["peak_gen_gb"]
        m2 = r_e["t_gen"] / r_d["t_gen"]
        print(f"M1：自研 {r_e['peak_gen_gb']}GB / 主选 {r_d['peak_gen_gb']}GB "
              f"⇒ {m1:.2f}（门 ≤{M1_GATE}：{'PASS' if m1 <= M1_GATE else 'FAIL'}）")
        print(f"M2：自研 {r_e['t_gen']}s / 主选 {r_d['t_gen']}s "
              f"⇒ {m2:.2f}（门 ≤{M2_GATE}：{'PASS' if m2 <= M2_GATE else 'FAIL'}）")
        print(f"（附：engine 实际 offload = {r_e.get('offload')}，prefer_mode 应为 sequential；"
              f"装载峰 {r_e.get('peak_setup_gb')} vs {r_d.get('peak_setup_gb')}GB；"
              f"加载 {r_e['t_load']}s vs {r_d['t_load']}s）")
    else:
        print(f"M1/M2 无法判定：engine={r_e.get('message')} diffsynth={r_d.get('message')}")

    with open(os.path.join(OUT_DIR, "bench_sdxl_modes.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n明细已存 {os.path.join(OUT_DIR, 'bench_sdxl_modes.json')}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--one":
        r = work(sys.argv[2])
        print("RESULT " + json.dumps(r, ensure_ascii=False))
        sys.exit(0 if r.get("ok") else 1)
    sys.exit(drive())
