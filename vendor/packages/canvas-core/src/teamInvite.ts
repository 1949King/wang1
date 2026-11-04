/**
 * 邀请链接 / 配对码 / 主机地址 —— 一行文字里认出到底是哪种（2026-11-04）
 *
 * ## 为什么需要这个纯函数
 *
 * 二维码砍掉之后（用户决定），配对只剩两条路：**6 位数字码** 和 **邀请链接**。
 * 但「链接」如果只在发出端存在，就不算一条配对方式 —— 同事收到一串 URL，
 * 软件里没有地方吃得下它，等于发了个只能看的东西。
 *
 * 所以这里把三种粘贴形态统一收成一个结果，由调用方决定怎么连：
 *
 * | 粘贴的东西 | `kind` | 怎么用 |
 * |---|---|---|
 * | `229140` | `code` | 先 UDP 广播问「谁持有这张码」→ 拿到地址 → 换令牌 |
 * | `http://192.168.1.4:18770/pair?code=229140` | `link` | **不用广播**，地址就在链接里，直接换令牌 |
 * | `http://192.168.1.4:18770` | `host` | 老路：直连加入 |
 *
 * ## 不做什么
 *
 * **不联网、不猜、不兜底**。认不出来就返回 `none` 并把原因写进 `why`，
 * 让人看到「你粘的是啥」。猜一个地址出来只会把「连不上」变成更难查的错。
 *
 * 也不做 URL 解析的完整实现：`new URL()` 在 WebEngine 里行为稳定，但我们
 * 要接受**没有协议头**的 `192.168.1.4:18770/pair?code=…`（微信里常被剥掉），
 * 所以拿正则自己拆，比先补协议再 try/catch 更好读。
 */

/** 认出来的四种输入形态。`none` 表示「这不是任何一种」，`why` 里说原因。 */
export type InviteKind = "link" | "code" | "host" | "none";

export type Invite = {
  kind: InviteKind;
  /** 主机地址，形如 `192.168.1.4:18770`（不带协议 —— `normalizeAddress` 会补）。`code` 形态下是空串 */
  host: string;
  /** 6 位（宽松收 4~10 位，兼容历史码）纯数字。`host` 形态下是空串 */
  code: string;
  /** `kind === "none"` 时给人看的原因；其余情况是空串 */
  why: string;
};

const CODE_RE = /^\d{4,10}$/;

/**
 * 主机部分：IPv4 / 带方括号的 IPv6 / 域名，可选 `:端口`。
 *
 * 故意**不校验**每段 ≤ 255、端口 ≤ 65535 —— 真填错了连不上的报错比
 * 「格式不对」更有用（前者带着地址，后者只让人重试）。
 */
const HOST_OK =
  /^(?:(?:\d{1,3}\.){3}\d{1,3}|\[[0-9a-fA-F:]+\]|[a-zA-Z0-9][a-zA-Z0-9.\-]*)(?::\d{1,5})?$/;

/**
 * 清掉粘贴带进来的噪音。
 *
 * 真实来源：微信/QQ 复制的链接常带首尾引号或「」；手机上长按复制会带句号；
 * 从聊天记录里连说明文字一起选中；Word 里带零宽字符。这些都见过，一起收拾。
 */
function clean(raw: string): string {
  let s = String(raw || "").replace(/[\u200b-\u200d\ufeff]/g, "").trim();
  s = s.replace(/^[<"'「『（(]+/, "").replace(/[>"'」』）)]+$/, "");
  s = s.replace(/[。，,；;、!?！？]+$/, "");
  return s.trim();
}

/** 从任意一串里取出主机部分：去协议 → 截到第一个 `/ ? #` 之前。 */
function hostOf(s: string): string {
  const noProto = s.replace(/^[a-zA-Z][a-zA-Z0-9+.\-]*:\/\//, "");
  return noProto.split(/[/?#]/)[0].trim();
}

/** 认不认识这个主机串。 */
function hostOk(host: string): boolean {
  return !!host && HOST_OK.test(host);
}

/**
 * 主函数。`raw` 可以是码、链接、地址，或者一团认不出来的东西。
 *
 * 顺序有讲究：**先判纯数字码**。因为 `192168` 这种也可能被当成主机名，
 * 而人输 6 位数字时心里想的一定是码。
 */
export function parseInvite(raw: string): Invite {
  const s = clean(raw);
  if (!s) {
    return { kind: "none", host: "", code: "", why: "这里还是空的 —— 输入 6 位配对码，或者粘贴同事发来的链接" };
  }

  // ① 纯数字码（容忍中间有空格：「229 140」念的时候容易打成这样）
  const digits = s.replace(/\s+/g, "");
  if (CODE_RE.test(digits)) {
    return { kind: "code", host: "", code: digits, why: "" };
  }

  // ② 带 code 的邀请链接（`/pair?code=…`，也容忍 `?code=` 直接挂在根上）
  const host = hostOf(s);
  const m = s.match(/[?&#]code=(\d{4,10})/i);
  if (m) {
    if (!hostOk(host)) {
      return {
        kind: "none", host: "", code: "",
        why: "链接里的地址看不懂 —— 正常长这样：http://192.168.1.4:18770/pair?code=229140",
      };
    }
    return { kind: "link", host, code: m[1], why: "" };
  }

  // ③ 只是地址。要求带点或带端口（或 IPv6 方括号）：
  // 光一个 `abc` 也算「合法主机名」，但人粘错东西时最常见的形态正是这种单词，
  // 与其连到 `http://abc` 等一个超时，不如当场说一句。
  const looksHost = hostOk(host)
    && (/\./.test(host) || /:/.test(host) || /^\[/.test(host) || /^https?:\/\//i.test(s));
  if (looksHost) {
    return { kind: "host", host, code: "", why: "" };
  }

  return {
    kind: "none", host: "", code: "",
    why: "认不出这是什么 —— 应该是 6 位数字，或者一条 http:// 开头的邀请链接",
  };
}
