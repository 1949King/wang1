/**
 * 在线状态推算（2026-11-04 · 画布 0.3.50）
 *
 * 这里错一次的代价是**两个人同时改同一版**：谎报「离线」会让人以为对方走了。
 * 所以三条都锁「宁可说在线，不要瞎报离线」。
 */
import { describe, expect, it } from "vitest";

import { isOnline, linkText, ONLINE_WINDOW, onlineCount, seenText } from "./teamPresence";
import type { TeamMember } from "./teamClient";

const M = (id: string, last_seen?: number): TeamMember => ({ id, name: id, role: "editor", last_seen });

describe("isOnline", () => {
  it("窗口内算在线，窗口外算离线", () => {
    expect(isOnline(1000, 1000 + ONLINE_WINDOW)).toBe(true);
    expect(isOnline(1000, 1000 + ONLINE_WINDOW + 1)).toBe(false);
  });

  it("last_seen 为 0 / undefined ⇒ 离线（老库补列后就是 0，那是真的不知道）", () => {
    expect(isOnline(0, 9999)).toBe(false);
    expect(isOnline(undefined, 9999)).toBe(false);
  });
});

describe("onlineCount", () => {
  it("只数在线的", () => {
    const now = 10_000;
    const list = [M("a", now - 5), M("b", now - 30), M("c", now - 9999)];
    expect(onlineCount(list, now)).toBe(2);
  });
});

describe("seenText", () => {
  // 用一个足够大的「现在」：now - 3 天 不能变成负数，否则测的是「时间戳<=0」那条分支
  const now = 10_000_000;

  it("在线就写「在线」，不写「刚刚」（后者会让人以为他刚到）", () => {
    expect(seenText(now - 3, now)).toBe("在线");
  });

  it("离线按分钟/小时/天递进，且不出现「0 分钟前」", () => {
    expect(seenText(now - 200, now)).toBe("3 分钟前");
    expect(seenText(now - 7200, now)).toBe("2 小时前");
    expect(seenText(now - 86400 * 3, now)).toBe("3 天前");
  });

  it("从没上线过要直说，不能显示成「很久以前」", () => {
    expect(seenText(0, now)).toBe("还没上线过");
  });
});

describe("linkText", () => {
  it("断线优先：「断了」要盖住人数信息，别只说一句团队 3 人", () => {
    expect(linkText("down", 3, 1)).toContain("断开");
    expect(linkText("down", 3, 1)).not.toContain("在线 1");
  });

  it("还没探测过时只说人数，不谎报连接状态", () => {
    expect(linkText("", 3, 0)).toBe("团队 3 人");
  });

  it("正常时把人数和在线一起说清", () => {
    expect(linkText("ok", 3, 2)).toContain("团队 3 人");
    expect(linkText("ok", 3, 2)).toContain("在线 2");
  });
});
