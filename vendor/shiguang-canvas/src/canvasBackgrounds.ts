/**
 * 画布背景预设 (Canvas Backgrounds)
 * ==================================
 *
 * 移植自 AI-Canvas-tauri (tenney95/AI-Canvas-tauri) `components/backgrounds/`：
 *   · `backgroundOptions.ts`  —— 6 个画布背景主题清单
 *   · `SolarSystemBackground.tsx` —— **8 张真实行星照片 + 每 80 秒轮播 + 淡入缩放**
 *   · `styles/backgrounds.css` —— 星场 60s 漂移动画 / 行星过渡 1.2s
 *
 * 为什么要单独成文件（V4.43.2）：
 *   `store.ts` / `styles.css` / `CanvasShell.tsx` 都在冻结区 `canvas-magnetic-intent` 内，
 *   本模块**不改它们**，改用「运行时注入 <style> + html[data-canvas-bg] 属性 + 一个
 *   自建背景 DOM 层」实现，于是**零解冻**即可拿到真实画布背景（协作对象替换思路，
 *   见 frozen-zone-release 技能）。主题切换复用既有 `useCanvasStore.setTheme`。
 *
 * V4.43.10（用户裁定「要」：照搬 AI Canvas 的行星素材 + 动效）：
 *   此前 solar-system 只是几层 CSS `radial-gradient` 静态色块；现改为
 *   **真实行星 PNG + 80s 轮播 + 星场漂移**，与开源实现对齐。
 *   素材来源：`vendor/AI-Canvas-tauri/src/assets/images/bg/1_mercury.png … 8_neptune.png`
 *   （已复制到 `src/assets/images/bg/`，属**新建文件**、不在冻结清单内）。
 *
 * 与 PyQt 设置的关系：
 *   PyQt「设置 → 外观 → 外观预设」写 QSettings 后，本模块轮询 `GET /host/canvas-settings`
 *   按 revision 号增量应用（只在设置真的变过时生效，不打断画布自己的主题切换按钮）。
 *
 * 冻结区影响：本文件 + `main.tsx` 均不在冻结区；`canvasVersion.ts` 在冻结区（版本号三件套）。
 */
import { BRIDGE, authHeaders } from "./bridge";
import { useCanvasStore } from "./store";

// ── 真实行星素材（V4.43.10，照搬开源 8 张 PNG）──────────────────────────────
import mercuryImg from "./assets/images/bg/1_mercury.png";
import venusImg from "./assets/images/bg/2_venus.png";
import earthImg from "./assets/images/bg/3_earth.png";
import marsImg from "./assets/images/bg/4_mars.png";
import jupiterImg from "./assets/images/bg/5_jupiter.png";
import saturnImg from "./assets/images/bg/6_saturn.png";
import uranusImg from "./assets/images/bg/7_uranus.png";
import neptuneImg from "./assets/images/bg/8_neptune.png";

/** 行星序（与开源一致：水星→金星→地球→火星→木星→土星→天王星→海王星） */
const PLANET_IMAGES: string[] = [
  mercuryImg, venusImg, earthImg, marsImg, jupiterImg, saturnImg, uranusImg, neptuneImg,
];

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
/** 太阳系背景 DOM 层（星场 + 行星图）*/
const SOLAR_LAYER_ID = "sg-solar-layer";
/** 轮播间隔：与开源一致，每 80 秒换一颗行星 */
const SOLAR_ROTATE_MS = 80_000;
/** 轮询间隔：本地 HTTP，代价极低；只在 revision 变化时应用 */
const POLL_MS = 2500;

const VALID_IDS = new Set<string>(CANVAS_BACKGROUNDS.map((b) => b.id));

function normalizeId(raw: unknown): CanvasBackgroundId {
  const id = String(raw || "");
  return (VALID_IDS.has(id) ? id : "default") as CanvasBackgroundId;
}

/**
 * 背景 CSS —— 通过覆盖 `--bg`（styles.css 里 `.shell` / `html` 都用 `background: var(--bg)`）
 * 实现，不改 styles.css。层叠优先级：注入的 <style> 在 styles.css 之后 → 同特异性下本表胜出。
 *
 * V4.43.10：solar-system 的 `--bg` 改为纯黑（与开源 `.solar-bg { background: #000 }` 一致），
 * 画面交给 `#sg-solar-layer`（星场 + 真实行星）。其余背景保持 V4.43.x 的渐变实现。
 */
function buildCss(): string {
  return `
/* V4.43.2 画布背景预设（运行时注入，来源 canvasBackgrounds.ts） */
html[data-canvas-bg="default"] { --bg: #0a0e14; }
html[data-canvas-bg="solar-system"] { --bg: #000; }
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

/* ── V4.43.10 太阳系真实层（照搬开源 styles/backgrounds.css 的 .solar-* 规则）── */
#${SOLAR_LAYER_ID} {
  position: fixed;
  inset: 0;
  z-index: 0;
  overflow: hidden;
  background: #000;
  opacity: 0;
  transition: opacity 1.2s ease;
  pointer-events: none;
}
html[data-canvas-bg="solar-system"] #${SOLAR_LAYER_ID} { opacity: 1; }

/* 星场：14 个白点 + 60s 缓慢漂移（开源 .solar-stars / @keyframes stars-shift） */
#${SOLAR_LAYER_ID} .sg-solar-stars {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(1px 1px at 10% 15%, rgba(255,255,255,0.6), transparent),
    radial-gradient(1px 1px at 25% 35%, rgba(255,255,255,0.4), transparent),
    radial-gradient(1.5px 1.5px at 40% 10%, rgba(255,255,255,0.5), transparent),
    radial-gradient(1px 1px at 55% 45%, rgba(255,255,255,0.3), transparent),
    radial-gradient(1px 1px at 70% 20%, rgba(255,255,255,0.5), transparent),
    radial-gradient(1.5px 1.5px at 85% 55%, rgba(255,255,255,0.4), transparent),
    radial-gradient(1px 1px at 15% 65%, rgba(255,255,255,0.3), transparent),
    radial-gradient(1px 1px at 35% 80%, rgba(255,255,255,0.5), transparent),
    radial-gradient(1.5px 1.5px at 60% 70%, rgba(255,255,255,0.4), transparent),
    radial-gradient(1px 1px at 80% 85%, rgba(255,255,255,0.3), transparent),
    radial-gradient(1px 1px at 90% 30%, rgba(255,255,255,0.5), transparent),
    radial-gradient(1px 1px at 5% 40%, rgba(255,255,255,0.4), transparent),
    radial-gradient(1px 1px at 45% 90%, rgba(255,255,255,0.3), transparent),
    radial-gradient(1.5px 1.5px at 75% 5%, rgba(255,255,255,0.5), transparent);
  animation: sg-stars-shift 60s linear infinite;
}
@keyframes sg-stars-shift {
  0%   { transform: translate(0, 0); }
  100% { transform: translate(-20px, -10px); }
}

/* 行星容器：整体压到画面下方 30% 处、很淡（开源 .solar-planet-images） */
#${SOLAR_LAYER_ID} .sg-solar-planets {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  bottom: -70%;
  opacity: 0.13;
}
/* 单颗行星：默认透明 + 放大 1.05，激活时淡入 1.2s + 缩回 1（开源 .solar-planet-figure） */
#${SOLAR_LAYER_ID} .sg-solar-figure {
  position: absolute;
  opacity: 0;
  transform: scale(1.05);
  transition: opacity 1.2s ease, transform 1.2s ease;
  max-width: 80%;
  margin: 0;
}
#${SOLAR_LAYER_ID} .sg-solar-figure.is-active {
  opacity: 1;
  transform: scale(1);
}
#${SOLAR_LAYER_ID} .sg-solar-figure img {
  width: 100%;
  object-fit: contain;
  filter: brightness(0.75);
  border-radius: 50%;
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

// ── 太阳系层：建 DOM + 轮播（V4.43.10）─────────────────────────────────────
let solarTimer: number | null = null;
let solarIndex = 0;

/** 惰性创建背景层（只在用到太阳系时建，避免无谓 DOM） */
function ensureSolarLayer(): HTMLElement | null {
  if (typeof document === "undefined") return null;
  const existed = document.getElementById(SOLAR_LAYER_ID);
  if (existed) return existed;
  const layer = document.createElement("div");
  layer.id = SOLAR_LAYER_ID;
  const stars = document.createElement("div");
  stars.className = "sg-solar-stars";
  layer.appendChild(stars);
  const planets = document.createElement("div");
  planets.className = "sg-solar-planets";
  PLANET_IMAGES.forEach((src, i) => {
    const fig = document.createElement("figure");
    fig.className = "sg-solar-figure" + (i === 0 ? " is-active" : "");
    const img = document.createElement("img");
    img.src = src;
    img.alt = "";
    fig.appendChild(img);
    planets.appendChild(fig);
  });
  layer.appendChild(planets);
  document.body.appendChild(layer);
  return layer;
}

/** 高亮第 i 颗行星（其余淡出） */
function paintSolarIndex(layer: HTMLElement, i: number): void {
  const figures = layer.querySelectorAll(".sg-solar-figure");
  figures.forEach((f, idx) => {
    f.classList.toggle("is-active", idx === i);
  });
}

/** 启动 80s 轮播（幂等：重复调用不会叠加定时器） */
function startSolarRotation(layer: HTMLElement): void {
  paintSolarIndex(layer, solarIndex);
  if (solarTimer !== null) return;
  solarTimer = window.setInterval(() => {
    solarIndex = (solarIndex + 1) % PLANET_IMAGES.length;
    paintSolarIndex(layer, solarIndex);
  }, SOLAR_ROTATE_MS);
}

/** 切走太阳系时停表，避免后台空转 */
function stopSolarRotation(): void {
  if (solarTimer !== null) {
    window.clearInterval(solarTimer);
    solarTimer = null;
  }
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
 * 应用背景（设 html 属性 + 按需挂/卸太阳系真实层）。
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

  // V4.43.10：太阳系 = 真实行星层（星场 + 80s 轮播）；其它背景停表
  if (bg === "solar-system") {
    const layer = ensureSolarLayer();
    if (layer) startSolarRotation(layer);
  } else {
    stopSolarRotation();
  }

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
    window.addEventListener("beforeunload", () => {
      window.clearInterval(timer);
      stopSolarRotation();
    });
  }
}
