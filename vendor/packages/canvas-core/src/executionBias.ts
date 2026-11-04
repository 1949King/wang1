/**
 * 混合算力偏好的**展示口径**（纯函数，可单测）。
 *
 * 真源在 Python：`app/core/ai/compute_bias.py`（0=纯本地 … 50=动态混合 … 100=纯云端，
 * 三档边界 24/25/74/75）。这里只做 UI 文案，**不改档位语义**；边界若变，守卫
 * `_verify/check_execution_bias_mirror.py`（若存在）与这里的测试会一起报红。
 */
export const BIAS_LOCAL_MAX = 24;
export const BIAS_CLOUD_MIN = 75;

export type BiasMode = "local" | "engine" | "cloud";

export function biasMode(bias: number): BiasMode {
  const v = Number.isFinite(bias) ? bias : 50;
  if (v <= BIAS_LOCAL_MAX) return "local";
  if (v >= BIAS_CLOUD_MIN) return "cloud";
  return "engine";
}

export function biasModeLabel(bias: number): string {
  const m = biasMode(bias);
  return m === "local" ? "本地优先" : m === "cloud" ? "云端优先" : "动态混合";
}

export function biasModeHint(bias: number): string {
  const m = biasMode(bias);
  if (m === "local") return "尽量走本机 SD / SVD；本地做不了时如实失败，不假装产出";
  if (m === "cloud") return "尽量走云端渠道；本地只在云端不可用时兜底";
  return "按预算 λ 与硬件档动态决定：先本地还是先云端，失败再切另一路";
}
