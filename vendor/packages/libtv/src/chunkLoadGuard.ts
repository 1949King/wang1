/**
 * 画布产物换代兜底（2026-10-25）。
 *
 * 故障链：dist 被重建/搬走 → 旧页面对应的 hashed chunk（如
 * `ImageStudio-DgQwIZ6p.js`、`AgentPanel-*.css`）已不存在 → 动态 import 404 →
 * App 抛出**异步**异常 → `AppErrorBoundary` 抓不到（它只管渲染期同步异常）→
 * React 树被卸载 → 整页黑屏，宿主侧表现为「画布进程已退出」。
 *
 * 这里补两层防线：
 * 1. `vite:preloadError` / `unhandledrejection` 捕获 chunk 加载失败；
 * 2. 冷却窗口内自动 reload 一次（新 index.html 会引用新 chunk），
 *    reload 无效则挂一个可见横幅，不让用户对着黑屏猜。
 *
 * 注意：不依赖 React / 不依赖 store —— 触发时 React 树可能已经崩了。
 */

/** reload 冷却窗口：避免"产物真坏了"导致无限刷新死循环。 */
const RELOAD_COOLDOWN_MS = 30_000;
const RELOAD_TS_KEY = "__sg_chunk_reload_ts";
const BANNER_ID = "__sg_chunk_error_banner";

/** 判定是否为「分包产物取不到」类错误。 */
export function isChunkLoadError(message: string): boolean {
  if (!message) return false;
  return /Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module|Unable to preload CSS|Unexpected token '<'/i.test(
    message,
  );
}

function readReloadTs(): number {
  try {
    return Number(window.sessionStorage.getItem(RELOAD_TS_KEY) || "0") || 0;
  } catch {
    return 0; // 隐私模式 / sessionStorage 被禁用
  }
}

function writeReloadTs(ts: number): void {
  try {
    window.sessionStorage.setItem(RELOAD_TS_KEY, String(ts));
  } catch {
    // 写不进去就退化为「不冷却」，靠下面的横幅兜住
  }
}

/** 挂一条可见横幅（React 可能已崩，用原生 DOM）。 */
export function showChunkErrorBanner(detail: string): void {
  if (typeof document === "undefined") return;
  if (document.getElementById(BANNER_ID)) return;
  const host = document.body || document.documentElement;
  if (!host) return;

  const el = document.createElement("div");
  el.id = BANNER_ID;
  el.setAttribute("role", "alert");
  // 暗底亮字：亮暗主题下都看得见（此处不接主题令牌，属最后兜底 UI）
  el.style.cssText = [
    "position:fixed",
    "left:50%",
    "top:18px",
    "transform:translateX(-50%)",
    "z-index:2147483647",
    "max-width:min(640px,calc(100vw - 32px))",
    "padding:12px 16px",
    "border-radius:10px",
    "border:1px solid #7a4a1e",
    "background:#2a1d12",
    "color:#ffd9a8",
    "font:13px/1.6 system-ui,-apple-system,'Segoe UI',sans-serif",
    "box-shadow:0 8px 28px rgba(0,0,0,.45)",
    "cursor:pointer",
    "white-space:pre-wrap",
  ].join(";");
  el.textContent =
    "画布资源加载失败：构建产物可能刚被重建/移动过。\n" +
    "点这里刷新即可对齐最新产物。\n" +
    `（${detail}）`;
  el.addEventListener("click", () => window.location.reload());
  host.appendChild(el);
}

/**
 * 处理一次 chunk 加载失败：冷却窗口外自动刷新，窗口内只显示横幅。
 */
export function handleChunkLoadFailure(detail: string): void {
  const now = Date.now();
  const last = readReloadTs();
  if (last && now - last < RELOAD_COOLDOWN_MS) {
    console.warn("[canvas] chunk 加载失败，刚刷新过，改为提示不刷新:", detail);
    showChunkErrorBanner(detail);
    return;
  }
  writeReloadTs(now);
  console.warn("[canvas] chunk 加载失败，自动刷新对齐最新产物:", detail);
  try {
    window.location.reload();
  } catch {
    showChunkErrorBanner(detail);
  }
}

/**
 * 安装全局兜底。幂等：重复调用只装一次。
 */
export function installChunkLoadGuard(): void {
  if (typeof window === "undefined") return;
  const w = window as Window & { __sgChunkGuardInstalled?: boolean };
  if (w.__sgChunkGuardInstalled) return;
  w.__sgChunkGuardInstalled = true;

  // Vite 官方事件（v5+）：preload 失败时派发，未 preventDefault 则继续冒泡为 unhandledrejection
  window.addEventListener("vite:preloadError", (event) => {
    const payload = (event as Event & { payload?: Error | string }).payload;
    const detail = typeof payload === "string" ? payload : (payload?.message ?? "preload error");
    handleChunkLoadFailure(detail);
  });

  // 非 Vite 分包的 import 失败（如插件运行时 import 远端 ESM）
  window.addEventListener("unhandledrejection", (event) => {
    const reason = (event as PromiseRejectionEvent).reason;
    const message =
      typeof reason === "string"
        ? reason
        : (reason && typeof reason === "object" && "message" in reason
            ? String((reason as { message?: unknown }).message ?? "")
            : "");
    if (!isChunkLoadError(message)) return;
    handleChunkLoadFailure(message);
  });
}
