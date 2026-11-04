/**
 * 复制到剪贴板（2026-11-03 · 画布 0.3.44）
 *
 * 为什么不能直接 `navigator.clipboard.writeText`：画布跑在 Qt WebEngine 上，
 * 这个内核并没有完整实现 Clipboard API（也没有 jsdom 那层兜底）。直接调的结果
 * 是**有时能用有时静默失败** —— 而"复制失败"是最难自查的一类事：人以为码已经在
 * 剪贴板里，粘出来却是上一次的内容。
 *
 * 所以这里两条路都走，并且**如实返回成功与否**，让界面能说「没复制上，手动选中」。
 */

/** 复制文本；返回是否真的复制成功。 */
export async function copyText(text: string): Promise<boolean> {
  const s = String(text || "");
  // 只有空白的串复制了也没用 —— 直接算失败，别让人以为"复制上了"
  if (!s.trim()) return false;

  // ① 标准 API：只在真正拿到成功回调时才算数（异步失败必须能被捕获）
  try {
    const clip = (globalThis as { navigator?: { clipboard?: { writeText?: (t: string) => Promise<void> } } })
      .navigator?.clipboard;
    if (clip?.writeText) {
      await clip.writeText(s);
      return true;
    }
  } catch {
    /* 权限被拒 / 没有焦点 / 内核没实现 —— 落到 ② */
  }

  // ② 老办法：临时 textarea + execCommand
  try {
    const doc = (globalThis as { document?: Document }).document;
    if (!doc?.body) return false;
    const ta = doc.createElement("textarea");
    ta.value = s;
    ta.setAttribute("readonly", "readonly");
    // 不能 display:none —— 不可见元素选不中，execCommand 会返回 false
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    ta.style.top = "0";
    doc.body.appendChild(ta);
    ta.select();
    const ok = doc.execCommand("copy");
    doc.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}
