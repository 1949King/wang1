/**
 * 本地一键拉片 · 视觉模型选择（I1）
 *
 * 本机 Ollama 视觉模型（如 qwen3.5:4b）把参考视频代表帧解析成景别/运镜/描述；
 * 素材只发往 localhost，不出机。对齐 aestheticPresets 的「空值 = 自动」约定：
 * 空串表示自动（后端优先挑第一个可用视觉模型）。
 */
const VISION_MODEL_KEY = "shiguang-vision-model-v1";

/** 当前选择的视觉模型名（空 = 自动） */
export function getVisionModel(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(VISION_MODEL_KEY) || "";
  } catch {
    return "";
  }
}

/** 设置当前视觉模型（空串 = 自动） */
export function setVisionModel(name: string): void {
  if (typeof window === "undefined") return;
  try {
    if (name) window.localStorage.setItem(VISION_MODEL_KEY, name);
    else window.localStorage.removeItem(VISION_MODEL_KEY);
  } catch {
    // 禁用 localStorage 时静默失败
  }
}
