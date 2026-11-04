/**
 * 团队协作客户端单测（2026-10-31 · V4.49.1）
 *
 * vitest 环境是 node（无 localStorage / 无 fetch）⇒ 两个都要手动打桩。
 * 这里刻意**只测纯逻辑与错误映射**，不测 UI 交互（UI 交给 tsc + 人工冒烟）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type FakeLS = { getItem(k: string): string | null; setItem(k: string, v: string): void; removeItem(k: string): void };

function installFakes(): { store: Map<string, string> } {
  const store = new Map<string, string>();
  const ls: FakeLS = {
    getItem: (k) => (store.has(k) ? store.get(k)! : null),
    setItem: (k, v) => store.set(k, v),
    removeItem: (k) => store.delete(k),
  };
  (globalThis as unknown as { window: { localStorage: FakeLS } }).window = { localStorage: ls };
  // bridge.ts 里 `bridgeToken()` 读的是**全局** localStorage（不是 window.localStorage），
  // node 环境下不存在 ⇒ 不补这个桩，hostCall 会在装配请求头时就 ReferenceError。
  (globalThis as unknown as { localStorage: FakeLS }).localStorage = ls;
  return { store };
}

async function loadModule() {
  // 每次重新加载：模块内部依赖 window/fetch，需在打桩之后导入
  vi.resetModules();
  return await import("./teamClient");
}

describe("teamClient · 地址归一化", () => {
  beforeEach(() => installFakes());
  afterEach(() => {
    vi.restoreAllMocks();
    delete (globalThis as Record<string, unknown>).window;
  });

  it("补协议 / 去尾斜杠 / 空串保持空", async () => {
    const m = await loadModule();
    expect(m.normalizeAddress("192.168.1.4:18770")).toBe("http://192.168.1.4:18770");
    expect(m.normalizeAddress("  http://192.168.1.4:18770/  ")).toBe("http://192.168.1.4:18770");
    expect(m.normalizeAddress("https://team.example.com/")).toBe("https://team.example.com");
    expect(m.normalizeAddress("")).toBe("");
    expect(m.normalizeAddress("   ")).toBe("");
  });
});

describe("teamClient · 团队调用与错误映射", () => {
  beforeEach(() => installFakes());
  afterEach(() => {
    vi.restoreAllMocks();
    delete (globalThis as Record<string, unknown>).window;
  });

  it("join 会归一化地址并持久化凭据", async () => {
    const { store } = installFakes();
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({ ok: true, member_id: "m_1", name: "张三", token: "tok" }),
    }));
    (globalThis as unknown as { fetch: typeof fetch }).fetch = fetchMock as unknown as typeof fetch;

    const m = await loadModule();
    const cred = await m.teamJoin("192.168.1.4:18770", "张三");

    expect(cred.address).toBe("http://192.168.1.4:18770");
    expect(cred.token).toBe("tok");
    // 落盘可读回
    expect(m.teamCred()?.member_id).toBe("m_1");
    expect(store.size).toBeGreaterThan(0);
    // 请求确实打到了归一化后的地址
    const calledUrl = String((fetchMock.mock.calls[0] as unknown[])[0]);
    expect(calledUrl).toBe("http://192.168.1.4:18770/team/join");
  });

  it("409 冲突映射成 TeamError(conflict) 并带上作者", async () => {
    installFakes();
    // 先 join 拿到地址与令牌（teamPush 需要它们），再把响应改成 409
    const m0 = await loadModule();
    (globalThis as unknown as { fetch: typeof fetch }).fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ ok: true, member_id: "m_1", name: "张三", token: "tok" }),
    })) as unknown as typeof fetch;
    await m0.teamJoin("192.168.1.4:18770", "张三");

    (globalThis as unknown as { fetch: typeof fetch }).fetch = vi.fn(async () => ({
      ok: false,
      status: 409,
      json: async () => ({ ok: false, code: "conflict", message: "项目已被 张三 更新到第 2 版", author: "张三", current_rev: 2 }),
    })) as unknown as typeof fetch;

    const m = await loadModule();
    await expect(m.teamPush("p_1", { nodes: [] }, 1, "x")).rejects.toMatchObject({
      code: "conflict",
      extra: expect.objectContaining({ author: "张三", current_rev: 2 }),
    });
  });

  it("没有地址时立刻报 no_address（不发请求）", async () => {
    installFakes();
    const fetchMock = vi.fn();
    (globalThis as unknown as { fetch: typeof fetch }).fetch = fetchMock as unknown as typeof fetch;

    const m = await loadModule();
    await expect(m.teamListProjects()).rejects.toMatchObject({ code: "no_address" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

/**
 * 2026-11-02 · 用户实机只看到 `[WinError 10038] 在一个非套接字上尝试了一个操作。`
 * —— 原始错误码对使用者零信息量。这三条锁住「界面必须给人话 + 下一步动作」。
 */
describe("teamClient · 网络失败翻译成人话", () => {
  /** 取断言用的拒绝原因：比 `.catch(e => e)` 干净 —— 后者会把成功返回类型并进联合类型。 */
  async function rejection(p: Promise<unknown>): Promise<Error & { code: string }> {
    try {
      await p;
    } catch (e) {
      return e as Error & { code: string };
    }
    throw new Error("预期请求失败，但它成功了");
  }

  beforeEach(() => installFakes());
  afterEach(() => {
    vi.restoreAllMocks();
    delete (globalThis as Record<string, unknown>).window;
  });

  it("fetch 抛 Failed to fetch ⇒ net_down，且提示里说清「对方要先启动服务」", async () => {
    (globalThis as unknown as { fetch: typeof fetch }).fetch = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    }) as unknown as typeof fetch;

    const m = await loadModule();
    const err = await rejection(m.teamJoin("192.168.1.4:18770", "张三"));

    expect(err.code).toBe("net_down");
    expect(err.message).toContain("启动团队服务");
    expect(err.message).toContain("18770");
    // 原始英文异常不许上界面（只进 console）
    expect(err.message).not.toContain("Failed to fetch");
  });

  it("[WinError 10061] 翻成「对方没启动团队服务」，并保留错误码便于反馈", async () => {
    (globalThis as unknown as { fetch: typeof fetch }).fetch = vi.fn(async () => {
      throw new Error("[WinError 10061] 由于目标计算机积极拒绝，无法连接。");
    }) as unknown as typeof fetch;

    const m = await loadModule();
    const err = await rejection(m.teamJoin("192.168.1.4:18770", "张三"));

    expect(err.code).toBe("net_10061");
    expect(err.message).toContain("没启动团队服务");
    expect(err.message).toContain("WinError 10061");
  });

  it("本机桥失败 ⇒ 指向 127.0.0.1:18765，不误导用户去查同事的网络", async () => {
    (globalThis as unknown as { fetch: typeof fetch }).fetch = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    }) as unknown as typeof fetch;

    const m = await loadModule();
    const err = await rejection(m.teamHostStatus());

    expect(err.code).toBe("net_down");
    expect(err.message).toContain("127.0.0.1:18765");
  });
});

/**
 * 2026-11-02 · 封面抽帧（`teamPoster`）
 *
 * 这个函数**失败必须回空串**：封面是锦上添花，抽不出来不能连累视频本体上传。
 * 并且它走的是本机桥（127.0.0.1:18765），不是同事的团队服务 —— 混了两边的
 * 鉴权就变成「把 host token 发给同事的机器」。
 */
describe("teamClient · 视频封面走本机桥", () => {
  beforeEach(() => installFakes());
  afterEach(() => {
    vi.restoreAllMocks();
    delete (globalThis as Record<string, unknown>).window;
  });

  function stubFetch(impl: (url: string) => unknown) {
    const calls: string[] = [];
    (globalThis as unknown as { fetch: typeof fetch }).fetch = vi.fn(async (url: string) => {
      calls.push(String(url));
      return impl(String(url));
    }) as unknown as typeof fetch;
    return calls;
  }

  it("成功时回 data_url，请求打到本机桥的 /host/team/poster", async () => {
    const calls = stubFetch(() => ({
      ok: true,
      json: async () => ({ ok: true, data_url: "data:image/jpeg;base64,AAAA", bytes: 3 }),
    }));

    const m = await loadModule();
    const url = await m.teamPoster("/inbox_file/成片.mp4");

    expect(url).toBe("data:image/jpeg;base64,AAAA");
    expect(calls[0]).toContain("127.0.0.1:18765/host/team/poster");
  });

  it("后端回 ok:false（没装 ffmpeg）⇒ 空串，不抛", async () => {
    stubFetch(() => ({
      ok: true,
      json: async () => ({ ok: false, code: "frame_failed", message: "抽不出帧" }),
    }));

    const m = await loadModule();
    await expect(m.teamPoster("/inbox_file/x.mp4")).resolves.toBe("");
  });

  it("桥连不上 ⇒ 也是空串（宁可没封面，不能把上传拦死）", async () => {
    (globalThis as unknown as { fetch: typeof fetch }).fetch = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    }) as unknown as typeof fetch;

    const m = await loadModule();
    await expect(m.teamPoster("/editor_file/x.mp4")).resolves.toBe("");
  });
});

/**
 * 2026-11-02 · 配对码 / 邀请链接
 *
 * 这套东西替掉的是「手填 IP」—— 它自己的坑必须锁住：
 *   · 找主机**只能**走本机桥（浏览器发不出 UDP 广播），不能打同事的服务器；
 *   · 换令牌那一条**必须不带 Authorization**（它就是拿码换令牌的那一条）；
 *   · 换失败不许把已有凭据冲掉（人还在团队里，只是这次码打错了）。
 */
describe("teamClient · 配对码", () => {
  beforeEach(() => installFakes());
  afterEach(() => {
    vi.restoreAllMocks();
    delete (globalThis as Record<string, unknown>).window;
  });

  type Call = { url: string; init?: RequestInit };

  function stubSeq(impl: (url: string, init?: RequestInit) => unknown) {
    const calls: Call[] = [];
    (globalThis as unknown as { fetch: typeof fetch }).fetch = vi.fn(
      async (url: string, init?: RequestInit) => {
        calls.push({ url: String(url), init });
        return impl(String(url), init);
      },
    ) as unknown as typeof fetch;
    return calls;
  }

  function headersOf(c: Call): Record<string, string> {
    return (c.init?.headers || {}) as Record<string, string>;
  }

  it("find-code 走本机桥，找到就把地址归一化回来", async () => {
    const calls = stubSeq(() => ({
      ok: true,
      json: async () => ({ ok: true, server: { name: "老王的工作站", address: "http://192.168.1.4:18770/", port: 18770, host: "192.168.1.4" } }),
    }));

    const m = await loadModule();
    const found = await m.teamFindByCode("229140");

    expect(found.address).toBe("http://192.168.1.4:18770");
    expect(found.name).toBe("老王的工作站");
    // 🔴 必须是本机桥：走 teamCall 就等于把 host token 发给同事的机器
    expect(calls[0].url).toContain("127.0.0.1:18765/host/team/find-code");
    // 本机桥认的是 X-Shiguang-Token，团队服务认的是 Bearer —— 两套不能互换。
    // 只断言"带了这个头"：node 环境里桥令牌本身是空串，值不可断言。
    expect("X-Shiguang-Token" in headersOf(calls[0])).toBe(true);
    expect(headersOf(calls[0]).Authorization).toBeUndefined();
  });

  it("find-code 没找到 ⇒ 地址空串 + 后端那句话原样带回（不抛）", async () => {
    stubSeq(() => ({
      ok: true,
      json: async () => ({ ok: true, server: null, message: "没找到持有这个配对码的电脑。可能原因：码已过期" }),
    }));

    const m = await loadModule();
    const found = await m.teamFindByCode("229140");

    expect(found.address).toBe("");
    expect(found.message).toContain("码已过期");
  });

  it("码格式不对立刻报 bad_code，一个请求都不发", async () => {
    const calls = stubSeq(() => ({ ok: true, json: async () => ({}) }));

    const m = await loadModule();
    await expect(m.teamFindByCode("12ab")).rejects.toMatchObject({ code: "bad_code" });
    expect(calls.length).toBe(0);
  });

  it("pair 打 /team/pair 且**不带** Authorization，成功后凭据落盘", async () => {
    const { store } = installFakes();
    const calls = stubSeq(() => ({
      ok: true,
      json: async () => ({ ok: true, member_id: "m_9", name: "李四", token: "tok9", paired: true }),
    }));

    const m = await loadModule();
    const cred = await m.teamPair("229140", "李四", "192.168.1.4:18770");

    expect(cred.address).toBe("http://192.168.1.4:18770");
    expect(cred.token).toBe("tok9");
    expect(calls[0].url).toBe("http://192.168.1.4:18770/team/pair");
    expect(calls[0].init?.method).toBe("POST");
    // 这一条是「用码换令牌」，带上旧令牌只会让语义混乱
    expect(headersOf(calls[0]).Authorization).toBeUndefined();
    expect(m.teamCred()?.member_id).toBe("m_9");
    expect(store.size).toBeGreaterThan(0);
  });

  it("码已用过 ⇒ 抛 code_used，且不把已有凭据冲掉", async () => {
    installFakes();
    const m0 = await loadModule();
    stubSeq(() => ({
      ok: true,
      json: async () => ({ ok: true, member_id: "m_1", name: "张三", token: "tok" }),
    }));
    await m0.teamJoin("192.168.1.4:18770", "张三");

    stubSeq(() => ({
      ok: false,
      status: 409,
      json: async () => ({ ok: false, code: "code_used", message: "这个配对码已经用过了，让同事再点一次「让同事加入」" }),
    }));

    const m = await loadModule();
    await expect(m.teamPair("229140", "李四", "192.168.1.4:18770")).rejects.toMatchObject({ code: "code_used" });
    // 人本来就在团队里，只是这次码打错了 —— 凭据不能被清掉
    expect(m.teamCred()?.token).toBe("tok");
  });

  it("pairing 打 /team/pairing（带令牌），回码 + 邀请链接 + 到期时间", async () => {
    installFakes();
    const m0 = await loadModule();
    stubSeq(() => ({
      ok: true,
      json: async () => ({ ok: true, member_id: "m_1", name: "张三", token: "tok" }),
    }));
    await m0.teamJoin("192.168.1.4:18770", "张三");

    const calls = stubSeq(() => ({
      ok: true,
      json: async () => ({
        ok: true, code: "229140", ttl: 120, expires_at: 1700000000, reused: false,
        address: "http://192.168.1.4:18770",
        pair_url: "http://192.168.1.4:18770/pair?code=229140",
      }),
    }));

    const m = await loadModule();
    const p = await m.teamPairing();

    expect(p.code).toBe("229140");
    // 2026-11-04 移除二维码：链接是「第二种配对方式」，不再是图的附属品
    expect(p.pair_url).toContain("/pair?code=229140");
    expect(p.expires_at).toBeGreaterThan(0);
    expect(calls[0].url).toBe("http://192.168.1.4:18770/team/pairing");
    expect(headersOf(calls[0]).Authorization).toBe("Bearer tok");
  });
});

/**
 * 2026-11-03 · 配对码加强：名额 / 只读轮询 / 作废
 *
 * 这三条各自锁一件事：
 *   · 要几个名额必须真的发出去（否则「请 3 人」等于没做）；
 *   · 轮询那条**必须是 GET**（POST 会新建码 ⇒ 人还在念号码就变了）；
 *   · 作废要把 code 带上（后端只能废自己发的，不带就 404）。
 */
describe("teamClient · 配对码名额与作废", () => {
  beforeEach(() => installFakes());
  afterEach(() => {
    vi.restoreAllMocks();
    delete (globalThis as Record<string, unknown>).window;
  });

  type PairCall = { url: string; init?: RequestInit };

  function stubPair(impl: (url: string, init?: RequestInit) => unknown) {
    const calls: PairCall[] = [];
    (globalThis as unknown as { fetch: typeof fetch }).fetch = vi.fn(
      async (url: string, init?: RequestInit) => {
        calls.push({ url: String(url), init });
        return impl(String(url), init);
      },
    ) as unknown as typeof fetch;
    return calls;
  }

  async function joined(token = "tok") {
    installFakes();
    const m0 = await loadModule();
    const calls = stubPair(() => ({
      ok: true,
      json: async () => ({ ok: true, member_id: "m_1", name: "张三", token }),
    }));
    await m0.teamJoin("192.168.1.4:18770", "张三");
    expect(calls.length).toBe(1);
    return token;
  }

  const basePayload = {
    ok: true, code: "229140", max_uses: 3, uses: 0, remaining: 3,
    expires_at: 1700000000, ttl: 118, alive: true, exhausted: false, expired: false,
    revoked: false, reused: false, replaced: false, host_name: "老王的工作站",
    address: "http://192.168.1.4:18770",
    pair_url: "http://192.168.1.4:18770/pair?code=229140",
  };

  it("要 3 个名额 ⇒ 请求体里带 max_uses=3", async () => {
    await joined();
    const calls = stubPair(() => ({ ok: true, json: async () => basePayload }));
    const m = await loadModule();
    const p = await m.teamPairing(3);

    // 2026-11-04 起请求体固定带 role（默认 editor）：角色是码的属性，
    // 不能等加入后再设置 —— 「给他看但别动」得在发出去那一刻就成立
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ max_uses: 3, role: "editor" });
    expect(p.max_uses).toBe(3);
    expect(p.remaining).toBe(3);
  });

  it("轮询状态走 GET（不带 body）—— POST 会新建码", async () => {
    await joined();
    const calls = stubPair(() => ({ ok: true, json: async () => basePayload }));
    const m = await loadModule();
    const p = await m.teamPairingStatus();

    expect(calls[0].url).toBe("http://192.168.1.4:18770/team/pairing");
    // teamCall 没给 body 就应该是 GET：GET /team/pairing 是只读的
    expect(calls[0].init?.method).toBe("GET");
    expect(calls[0].init?.body).toBeUndefined();
    expect(p.code).toBe("229140");
  });

  it("作废把 code 一起发出去", async () => {
    await joined();
    const calls = stubPair(() => ({
      ok: true,
      json: async () => ({ ...basePayload, alive: false, revoked: true, remaining: 0, code: "229140" }),
    }));
    const m = await loadModule();
    const r = await m.teamRevokePairing("229140");

    expect(calls[0].url).toBe("http://192.168.1.4:18770/team/pairing/revoke");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ code: "229140" });
    expect(r.revoked).toBe(true);
    expect(r.alive).toBe(false);
  });

  it("用码加入要回「还剩几个名额」，界面靠它告诉人还能带几个", async () => {
    installFakes();
    const calls = stubPair(() => ({
      ok: true,
      json: async () => ({
        ok: true, member_id: "m_9", name: "李四", token: "tok9", paired: true,
        remaining: 2, max_uses: 3, host_name: "老王的工作站",
      }),
    }));
    const m = await loadModule();
    const r = await m.teamPair("229140", "李四", "192.168.1.4:18770");

    expect(r.remaining).toBe(2);
    expect(r.max_uses).toBe(3);
    expect(r.host_name).toBe("老王的工作站");
    // 兑换这一条仍然不带令牌
    expect((calls[0].init?.headers as Record<string, string>).Authorization).toBeUndefined();
  });
});

/**
 * 2026-11-04 · 批注与角色
 *
 * 这里只锁**路径和请求体**：正文怎么分组、时间怎么说人话在 `teamReview.test.ts`。
 * 路径错一位（`/comments` 写成 `/comment`）后端会 404，但那只有真机上才看得见 ——
 * 单测里花一行就能拦住。
 */
describe("teamClient · 批注与角色", () => {
  beforeEach(() => installFakes());
  afterEach(() => {
    vi.restoreAllMocks();
    delete (globalThis as Record<string, unknown>).window;
  });

  type Call = { url: string; init?: RequestInit };

  function stub(impl: () => unknown) {
    const calls: Call[] = [];
    (globalThis as unknown as { fetch: typeof fetch }).fetch = vi.fn(
      async (url: string, init?: RequestInit) => {
        calls.push({ url: String(url), init });
        return impl();
      },
    ) as unknown as typeof fetch;
    return calls;
  }

  async function ready() {
    installFakes();
    const m0 = await loadModule();
    stub(() => ({ ok: true, json: async () => ({ ok: true, member_id: "m_1", name: "张三", token: "tok" }) }));
    await m0.teamJoin("192.168.1.4:18770", "张三");
  }

  const oneComment = {
    ok: true,
    comment: {
      id: "c_1", project_id: "p_1", node_id: "n1", rev: 2, author_id: "m_1",
      author: "张三", body: "字幕压住脸了", created_at: 100, resolved: false,
      resolved_at: 0, resolved_by: "", resolver: "",
    },
  };

  it("提批注：POST /comments，正文与 node_id 一起发", async () => {
    await ready();
    const calls = stub(() => ({ ok: true, json: async () => oneComment }));
    const m = await loadModule();
    const c = await m.teamAddComment("p_1", "字幕压住脸了", "n1", 2);

    expect(calls[0].url).toBe("http://192.168.1.4:18770/team/projects/p_1/comments");
    expect(calls[0].init?.method).toBe("POST");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      body: "字幕压住脸了", node_id: "n1", rev: 2,
    });
    expect(c.author).toBe("张三");
  });

  it("解决批注：路径带评论 id，body 带 resolved", async () => {
    await ready();
    const calls = stub(() => ({ ok: true, json: async () => oneComment }));
    const m = await loadModule();
    await m.teamResolveComment("p_1", "c_1", true);

    expect(calls[0].url).toBe("http://192.168.1.4:18770/team/projects/p_1/comments/c_1");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ resolved: true });
  });

  it("列表：GET /comments，不是 POST（POST 会新建一条）", async () => {
    await ready();
    const calls = stub(() => ({ ok: true, json: async () => ({ ok: true, comments: [oneComment.comment] }) }));
    const m = await loadModule();
    const list = await m.teamComments("p_1");

    expect(calls[0].url).toBe("http://192.168.1.4:18770/team/projects/p_1/comments");
    expect(calls[0].init?.body).toBeUndefined();
    expect(list.length).toBe(1);
  });

  it("改角色：POST /team/members/{id}/role", async () => {
    await ready();
    const calls = stub(() => ({
      ok: true,
      json: async () => ({ ok: true, member: { id: "m_2", name: "李四", role: "viewer" } }),
    }));
    const m = await loadModule();
    const row = await m.teamSetRole("m_2", "viewer");

    expect(calls[0].url).toBe("http://192.168.1.4:18770/team/members/m_2/role");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ role: "viewer" });
    expect(row.role).toBe("viewer");
  });

  it("出码可以指定只读角色（甲方那一档）", async () => {
    await ready();
    const calls = stub(() => ({
      ok: true,
      json: async () => ({
        ok: true, code: "229140", role: "viewer", max_uses: 1, uses: 0, remaining: 1,
        expires_at: 1700000000, ttl: 120, alive: true,
        pair_url: "http://192.168.1.4:18770/pair?code=229140",
      }),
    }));
    const m = await loadModule();
    const p = await m.teamPairing(1, "viewer");

    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ max_uses: 1, role: "viewer" });
    expect(p.role).toBe("viewer");
  });
});
