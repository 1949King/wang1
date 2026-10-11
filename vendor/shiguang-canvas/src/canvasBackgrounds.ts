/**
 * 画布背景预设 (Canvas Backgrounds)
 * ==================================
 *
 * 移植自 AI-Canvas-tauri (tenney95/AI-Canvas-tauri) `components/backgrounds/backgroundOptions.ts`
 * （6 个画布背景主题：默认暗色 / 太阳系 / 星云 / 米白浅色 / 磨砂暖光 / 自定义图片）。
 *
 * 为什么要单独成文件（V4.43.2）：
 *   `store.ts` / `styles.css` / `CanvasShell.tsx` 都在冻结区 `canvas-magnetic-intent` 内，
 *   本模块**不改它们**，改用「运行时注入 <style> + html[data-canvas-bg] 属性」实现，
 *   于是**零解冻**即可拿到真实画布背景（协作对象替换思路，见 frozen-zone-release 技能）。
 *   主题切换复用既有 `useCanvasStore.setTheme`（不改 store.ts，只调用）。
 *
 * 与 PyQt 设置的关系：
 *   PyQt「设置 → 外观 → 外观预设」写 QSettings 后，本模块轮询 `GET /host/canvas-settings`
 *   按 revision 号增量应用（只在设置真的变过时生效，不打断画布自己的主题切换按钮）。
 *
 * 用户裁定：2026-10-11「做真：移植画布背景预设」（授权解冻画布）。
 * 冻结区影响：仅 `canvasVersion.ts`（版本号三件套）；本文件 + `main.tsx` 均不在冻结区。
 */
import { BRIDGE, authHeaders } from "./bridge";
import { useCanvasStore } from "./store";

export type CanvasBackgroundId =
  | "default"
  | "solar-system"
  | "nebula"
  | "off-white"
  | "frosted-glass"
  | "custom";

export type CanvasBackgroundOption = {
  id: CanvasBackgroundId;
  label: string;
  /** 该背景建议搭配的主题（浅色背景配浅色主题，否则文字不可读） */
  theme: "dark" | "light";
};

/** 6 个画布背景（与开源 backgroundOptions.ts 一一对应） */
export const CANVAS_BACKGROUNDS: CanvasBackgroundOption[] = [
  { id: "default", label: "默认暗色", theme: "dark" },
  { id: "solar-system", label: "太阳系", theme: "dark" },
  { id: "nebula", label: "星云", theme: "dark" },
  { id: "off-white", label: "米白浅色", theme: "light" },
  { id: "frosted-glass", label: "磨砂暖光", theme: "light" },
  { id: "custom", label: "自定义图片", theme: "dark" },
];

const STORAGE_KEY = "shiguang-canvas:background:v1";
const REV_STORAGE_KEY = "shiguang-canvas:settings-rev:v1";
const STYLE_ID = "sg-canvas-bg-style";
/** 轮询间隔：本地 HTTP，代价极低；只在 revision 变化时应用 */
const POLL_MS = 2500;

const VALID_IDS = new Set<string>(CANVAS_BACKGROUNDS.map((b) => b.id));

function normalizeId(raw: unknown): CanvasBackgroundId {
  const id = String(raw || "");
  return (VALID_IDS.has(id) ? id : "default") as CanvasBackgroundId;
}

/**
 * 背景 CSS —— 全部通过覆盖 `--bg`（styles.css 里 `.shell` / `html` 都用 `background: var(--bg)`）
 * 实现，不改 styles.css。层叠优先级：注入的 <style> 在 styles.css 之后 → 同特异性下本表胜出。
 */
function buildCss(): string {
  return `
/* V4.43.2 画布背景预设（运行时注入，来源 canvasBackgrounds.ts） */
html[data-canvas-bg="default"] { --bg: #0a0e14; }
html[data-canvas-bg="solar-system"] {
  --bg:
    radial-gradient(circle at 78% 30%, rgba(249, 115, 22, 0.22) 0%, rgba(249, 115, 22, 0) 34%),
    radial-gradient(circle at 72% 34%, rgba(168, 85, 247, 0.30) 0%, rgba(168, 85, 247, 0) 46%),
    radial-gradient(circle at 20% 80%, rgba(99, 102, 241, 0.16) 0%, rgba(99, 102, 241, 0) 55%),
    #0a0a12;
}
html[data-canvas-bg="nebula"] {
  --bg:
    radial-gradient(circle at 24% 26%, rgba(168, 85, 247, 0.24) 0%, rgba(168, 85, 247, 0) 42%),
    radial-gradient(circle at 74% 68%, rgba(217, 70, 239, 0.20) 0%, rgba(217, 70, 239, 0) 46%),
    radial-gradient(circle at 52% 44%, rgba(139, 92, 246, 0.16) 0%, rgba(139, 92, 246, 0) 58%),
    #080510;
}
html[data-canvas-bg="off-white"] { --bg: #f6f8fc; }
html[data-canvas-bg="frosted-glass"] {
  --bg: linear-gradient(160deg, #fdfbf7 0%, #f3f5fb 52%, #eef1f8 100%);
}
/* V4.43.3：custom 用 var(--bg-img)（运行时由 PyQt 下发的 data:image/... 注入），
   缺省回落到默认暗色，避免画布第一次加载时空白。 */
html[data-canvas-bg="custom"] {
  --bg: var(--bg-img, #0a0e14);
  background-size: cover;
  background-position: center;
  background-repeat: no-repeat;
}

/* 让画布底透出上面的 --bg（ReactFlow 12 默认有不透明底色） */
html[data-canvas-bg] .react-flow,
html[data-canvas-bg] .react-flow__pane {
  --xy-background-color: transparent;
  background-color: transparent;
}
`;
}

function ensureStyles(): void {
  if (typeof document === "undefined") return;
  if (document.getElementById(STYLE_ID)) return;
  const el = document.createElement("style");
  el.id = STYLE_ID;
  el.textContent = buildCss();
  document.head.appendChild(el);
}

/** 读取本地已保存的背景（首次为 default） */
export function readStoredCanvasBackground(): CanvasBackgroundId {
  try {
    return normalizeId(localStorage.getItem(STORAGE_KEY));
  } catch {
    return "default";
  }
}

/**
 * 应用背景（只设 html 属性，样式由注入的 CSS 负责）。
 * @param id 背景 id
 * @param theme 可选：同时切换画布主题（复用 store.setTheme，避免与 store 状态分叉）
 * @param imageDataUrl 可选：custom 背景的 data URL（仅在 id === "custom" 时生效）
 */
export function applyCanvasBackground(
  id: string,
  theme?: "dark" | "light",
  imageDataUrl?: string,
): void {
  if (typeof document === "undefined") return;
  ensureStyles();
  const bg = normalizeId(id);
  document.documentElement.setAttribute("data-canvas-bg", bg);
  try {
    if (bg === "custom" && imageDataUrl) {
      // V4.43.3：custom 走 base64 data URL；同一会话多张图覆盖，旧值会被回收
      document.documentElement.style.setProperty("--bg-img", `url("${imageDataUrl}")`);
    } else {
      // 非 custom 或没传图：清除自定义内联，避免前一图残留
      document.documentElement.style.removeProperty("--bg-img");
    }
  } catch {
    /* 极少数环境 style 不可写：忽略 */
  }
  try {
    localStorage.setItem(STORAGE_KEY, bg);
  } catch {
    /* 沙箱/隐私模式写入失败不影响内存态 */
  }
  if (theme === "dark" || theme === "light") {
    try {
      useCanvasStore.getState().setTheme(theme);
    } catch {
      document.documentElement.setAttribute("data-theme", theme);
    }
  }
}

/** 从宿主拉取设置（PyQt QSettings），按 revision 增量应用 */
async function pullHostSettings(): Promise<void> {
  try {
    const res = await fetch(`${BRIDGE}/host/canvas-settings`, { headers: authHeaders() });
    if (!res.ok) return;
    const data = (await res.json()) as {
      revision?: number;
      canvas_background?: string;
      theme?: string;
      image_data_url?: string;
    };
    const rev = Number(data.revision || 0);
    let lastRev = 0;
    try {
      lastRev = Number(localStorage.getItem(REV_STORAGE_KEY) || 0);
    } catch {
      /* 忽略 */
    }
    // 只在宿主设置真的变过时应用，避免覆盖用户在画布里的本地切换
    if (rev > 0 && rev !== lastRev) {
      const theme = data.theme === "light" ? "light" : data.theme === "dark" ? "dark" : undefined;
      // V4.43.3：把 PyQt 下发的 image_data_url 传给 applyCanvasBackground
      const imageDataUrl = typeof data.image_data_url === "string" && data.image_data_url
        ? data.image_data_url
        : undefined;
      applyCanvasBackground(String(data.canvas_background || "default"), theme, imageDataUrl);
      try {
        localStorage.setItem(REV_STORAGE_KEY, String(rev));
      } catch {
        /* 忽略 */
      }
    }
  } catch {
    /* 桥未起或首次加载：静默（背景仍用本地值） */
  }
}

/**
 * 画布启动时调用（main.tsx）：
 *   1) 注入样式  2) 应用本地背景  3) 暴露全局供 PyQt `runJavaScript` 直推  4) 起轮询同步宿主设置
 */
export function initCanvasBackground(): void {
  ensureStyles();
  applyCanvasBackground(readStoredCanvasBackground());

  // 全局：Qt WebEngine 可 runJavaScript("__shiguangSetCanvasBackground('nebula','dark')")
  (window as unknown as Record<string, unknown>).__shiguangSetCanvasBackground = (
    id: string,
    theme?: string,
    imageDataUrl?: string,
  ) => applyCanvasBackground(
    id,
    theme === "light" || theme === "dark" ? theme : undefined,
    imageDataUrl,
  );

  void pullHostSettings();
  if (typeof window !== "undefined") {
    const timer = window.setInterval(() => void pullHostSettings(), POLL_MS);
    // 页面卸载时清理，避免热重载重复挂定时器
    window.addEventListener("beforeunload", () => window.clearInterval(timer));
  }
}
