# -*- coding: utf-8 -*-
"""Wan 内核 parity 对照：自研循环 vs 上游 WanPipeline（同 seed / 同 embeds / 同步数）。

判据（与族契约一致）：逐帧 PSNR。>=40dB 视为一致；inf = 比特级。
结果写 data/wan_kernel_parity.json。
"""
import json, os, sys, time

# 内核默认 off；wan 尚未 verified => 两个开关都要显式打开（契约要求「未验收不接管」）
os.environ["SHIGUANG_KERNEL"] = "on"
os.environ["SHIGUANG_KERNEL_ALLOW_UNVERIFIED"] = "1"
sys.path.insert(0, r"D:\拾光剪影")
import torch

MP = os.path.join(r"D:\拾光剪影", "app", "models", "cache", "Wan-AI_Wan2.1-T2V-1.3B-Diffusers")
PROMPT = "a cat walking on grass"
NEG = ""
SEED = 1234
W, H = 512, 512
FRAMES = 17
STEPS = 20
CFG = 5.0

from diffusers import AutoencoderKLWan, WanPipeline, WanTransformer3DModel
from diffusers.schedulers.scheduling_unipc_multistep import UniPCMultistepScheduler
from app.core.local_video_infer import _encode_wan_prompts, _WAN_NEGATIVE_DEFAULT

# ── Stage A：先编码（UMT5 ~5GB 用完即释放）──
# 顺序不能反：先载 7GB pipeline 再编码会让峰值 12GB 撞本机 15GB RAM 墙（2026-10-30 实测 OOM）
neg = NEG or _WAN_NEGATIVE_DEFAULT
pe, ne = _encode_wan_prompts(MP, PROMPT, neg, 8)
import gc as _gc
_gc.collect()
print("EMBEDS", tuple(pe.shape), flush=True)

# ── Stage B：只载 transformer + vae ──
dtype = torch.bfloat16
vae = AutoencoderKLWan.from_pretrained(MP, subfolder="vae", torch_dtype=dtype)
tr = WanTransformer3DModel.from_pretrained(MP, subfolder="transformer", torch_dtype=dtype)
sch = UniPCMultistepScheduler.from_pretrained(MP, subfolder="scheduler")
pipe = WanPipeline(transformer=tr, text_encoder=None, tokenizer=None, vae=vae, scheduler=sch)
pipe.enable_model_cpu_offload()   # 8GB 卡必须 offload；直接 to(cuda) 会 27GB 换页卡死（2026-10-30 实测）
print("PIPE_READY", flush=True)
import gc


neg = NEG or _WAN_NEGATIVE_DEFAULT

def frames_to_np(frames):
    import numpy as np
    if isinstance(frames, np.ndarray):
        return frames[0] if frames.ndim == 5 else frames
    return np.stack([np.asarray(f.convert("RGB") if hasattr(f, "convert") else f) for f in frames])

def psnr(a, b):
    import numpy as np
    a = a.astype(np.float64); b = b.astype(np.float64)
    if a.shape != b.shape:
        return None
    mse = float(np.mean((a - b) ** 2))
    if mse == 0:
        return float("inf")
    return round(10 * np.log10(255.0 ** 2 / mse), 3)

out = {"prompt": PROMPT, "seed": SEED, "size": [W, H], "frames": FRAMES, "steps": STEPS, "cfg": CFG}

# ── 上游 ──
g1 = torch.Generator("cpu").manual_seed(SEED)
t0 = time.perf_counter()
up = pipe(prompt_embeds=pe.unsqueeze(0).to(dtype).to("cuda"),
          negative_prompt_embeds=ne.unsqueeze(0).to(dtype).to("cuda"),
          num_frames=FRAMES, num_inference_steps=STEPS, guidance_scale=CFG,
          width=W, height=H, generator=g1, output_type="np")
out["upstream_s"] = round(time.perf_counter() - t0, 1)
up_arr = frames_to_np(up.frames)
out["upstream_frames"] = int(up_arr.shape[0])
print("UPSTREAM", out["upstream_s"], "s frames", up_arr.shape, flush=True)
# 上游跑完先释放激活值，避免两次推理的碎片互相挤压（8GB 实测必要）
gc.collect()
if torch.cuda.is_available():
    torch.cuda.empty_cache()

# ── 内核 ──
from app.core.neural.kernel import engine as KE
from app.core.neural.kernel.contracts import GenRequest

req = GenRequest(family="wan", model_id="wan21-t2v-1.3b", prompt=PROMPT,
                 negative_prompt=neg, width=W, height=H, frames=FRAMES,
                 steps=STEPS, cfg=CFG, seed=SEED)
g2 = torch.Generator("cpu").manual_seed(SEED)
t0 = time.perf_counter()
res = KE.run(pipe=pipe, req=req, generator=g2,
             extras={"model_path": MP, "vram_gb": 8})
out["kernel_s"] = round(time.perf_counter() - t0, 1)
out["kernel_ok"] = bool(res.get("ok"))
out["kernel_msg"] = str(res.get("message"))[:300]
rep = res.get("report")
out["kernel_report"] = rep.to_dict() if hasattr(rep, "to_dict") else str(rep)[:300]
print("KERNEL", out["kernel_ok"], out["kernel_s"], "s", out["kernel_msg"], flush=True)

if out["kernel_ok"] and res.get("frames"):
    k_arr = frames_to_np(res["frames"])
    out["kernel_frames"] = int(k_arr.shape[0])
    out["psnr_db"] = psnr(up_arr, k_arr)
    print("PSNR_DB", out["psnr_db"], flush=True)

os.makedirs("data", exist_ok=True)
with open(os.path.join("data", "wan_kernel_parity.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2, default=str)
print("DONE", flush=True)
