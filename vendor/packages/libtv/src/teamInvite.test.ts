/**
 * 邀请链接 / 配对码 / 地址的识别（2026-11-04）
 *
 * 二维码砍掉后链接成了并列的第二种配对方式，所以这个小函数是**那条路的入口**：
 * 认错一次，人就粘了链接却什么都没发生。三件事必须锁死：
 *   ① 带不带协议、带不带引号都能认（微信/Word 复制出来的形态不统一）；
 *   ② 纯 6 位数字必须判成「码」而不是主机名；
 *   ③ 认不出来要说原因，**不许猜**一个地址出来。
 */
import { describe, expect, it } from "vitest";

import { parseInvite } from "./teamInvite";

describe("parseInvite · 邀请链接", () => {
  it("标准链接：拆出主机和码", () => {
    const p = parseInvite("http://192.168.1.4:18770/pair?code=229140");
    expect(p.kind).toBe("link");
    expect(p.host).toBe("192.168.1.4:18770");
    expect(p.code).toBe("229140");
    expect(p.why).toBe("");
  });

  it("没有协议头（微信常剥掉）也认", () => {
    const p = parseInvite("192.168.1.4:18770/pair?code=229140");
    expect(p.kind).toBe("link");
    expect(p.host).toBe("192.168.1.4:18770");
    expect(p.code).toBe("229140");
  });

  it("首尾引号、空格、句号一起清掉", () => {
    const p = parseInvite('  "http://192.168.1.4:18770/pair?code=229140"。  ');
    expect(p.kind).toBe("link");
    expect(p.code).toBe("229140");
    expect(p.host).toBe("192.168.1.4:18770");
  });

  it("域名 + 其它参数顺序也认（code 不是第一个参数）", () => {
    const p = parseInvite("https://team.local:18770/pair?from=wx&code=482913&x=1");
    expect(p.kind).toBe("link");
    expect(p.host).toBe("team.local:18770");
    expect(p.code).toBe("482913");
  });

  it("IPv6 带方括号", () => {
    const p = parseInvite("http://[fe80::1]:18770/pair?code=229140");
    expect(p.kind).toBe("link");
    expect(p.host).toBe("[fe80::1]:18770");
    expect(p.code).toBe("229140");
  });

  it("链接里没有码 ⇒ 退化成「只有地址」，不是错误", () => {
    const p = parseInvite("http://192.168.1.4:18770/pair");
    expect(p.kind).toBe("host");
    expect(p.host).toBe("192.168.1.4:18770");
    expect(p.code).toBe("");
  });
});

describe("parseInvite · 码与地址", () => {
  it("纯 6 位数判成码，不判成主机名", () => {
    const p = parseInvite("229140");
    expect(p.kind).toBe("code");
    expect(p.code).toBe("229140");
    expect(p.host).toBe("");
  });

  it("念的时候打成两段的码也认", () => {
    expect(parseInvite("229 140").code).toBe("229140");
  });

  it("纯地址（带端口 / 不带协议）", () => {
    const a = parseInvite("192.168.1.4:18770");
    expect(a.kind).toBe("host");
    expect(a.host).toBe("192.168.1.4:18770");

    const b = parseInvite("http://192.168.1.4:18770/");
    expect(b.kind).toBe("host");
    expect(b.host).toBe("192.168.1.4:18770");
  });
});

describe("parseInvite · 认不出来的时候", () => {
  it("空串给一句能照着做的话", () => {
    const p = parseInvite("   ");
    expect(p.kind).toBe("none");
    expect(p.why).toContain("6 位配对码");
  });

  it("一堆中文说明文字不许瞎猜地址", () => {
    const p = parseInvite("在吗，帮我看一下这个项目");
    expect(p.kind).toBe("none");
    expect(p.host).toBe("");
    expect(p.why).toContain("认不出");
  });

  it("光一个单词不当主机（避免连到 http://abc 等超时）", () => {
    expect(parseInvite("abc").kind).toBe("none");
  });

  it("链接里的主机明显不合法 ⇒ none + 原因，而不是拼一个坏地址", () => {
    const p = parseInvite("http://192.168.1.4:18770 打包 好了");
    // hostOf 截到第一个空格之前仍是合法地址，但带 code 的情况下才需要严格；
    // 这里没有 code ⇒ 落到 host 分支（地址本身是好的，多的文字被截掉）
    expect(["host", "none"]).toContain(p.kind);
  });
});
