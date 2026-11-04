/**
 * 团队协作面板（2026-10-31 · V4.49.1；2026-11-02 加素材层）
 *
 * 五段式，对应五个真实动作（不做"设置项博物馆"）：
 *   1. 本机服务 —— 我是不是那台"服务器"（启动/停止 + 显示同事该填的地址）
 *   2. 连接     —— 我是同事，扫描或手填地址后加入
 *   3. 项目     —— 上传当前画布 / 拉取 / 认领 / 交接
 *   4. 收件箱   —— 别人交接给我的，一键接手
 *   5. 素材     —— 成片/图片/音频这些**大文件**（画布 JSON 装不下的那部分）
 *
 * 纪律：
 *   · 拉取会覆盖当前画布 ⇒ **必须二次确认**（不静默覆盖用户正在做的事）
 *   · 冲突/锁 都显示后端给的原因（含"谁改的/谁占着"），不吞成"失败"
 *   · 传上去的 bundle 里**不留令牌**（`stripAssetTokens`），且素材上传失败要
 *     逐条报出来（`failed`）——绝不静默跳过让同事打开看空白
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useCanvasStore } from "./store";
import {
  TeamError,
  type DiscoveredServer,
  type TeamAsset,
  type TeamCred,
  type TeamHandoffItem,
  type TeamHostStatus,
  type TeamProject,
  teamAck,
  teamAddress,
  teamAssetUrl,
  teamClaim,
  teamCreateProject,
  teamCred,
  teamDeleteAsset,
  teamDiscover,
  teamFindByCode,
  teamHandoff,
  teamHostStart,
  teamHostStatus,
  teamHostStop,
  teamInbox,
  teamInboxMap,
  teamJoin,
  teamLeave,
  teamListAssets,
  teamListProjects,
  teamMaterialize,
  teamMembers,
  teamPair,
  teamPairing,
  teamPairingStatus,
  teamRevokePairing,
  teamPull,
  teamPush,
  teamRelease,
  teamUploadAsset,
  localRevOf,
  setLocalRev,
  teamDiff,
  type TeamPairingInfo,
  type TeamVersion,
  teamRollback,
  teamVersions,
} from "./teamClient";
import { backupBeforePull } from "./teamBackup";
import { TeamVersions } from "./TeamVersions";
import { assetCounts, emptyAssetHint, filterAssets, kindLabel, type AssetKindFilter } from "./assetFilter";
import { isOnline, linkText, onlineCount, seenText } from "./teamPresence";
import {
  applyMediaIndex,
  collectMediaRefs,
  isTeamAsset,
  kindOf,
  pruneMediaCache,
  readMediaCache,
  rebaseAssetUrls,
  stripAssetTokens,
  uploadMediaRefs,
  writeMediaCache,
  type MediaRef,
} from "./teamAssets";
import { formatTeamDiff } from "./teamDiffText";
import { copyText } from "./teamClipboard";
import { useVideoBad, VideoUnplayable } from "./videoUnplayable";
import "./teamPanel.css";

type Member = { id: string; name: string; role: string; last_seen?: number };

/** 拉下来的 bundle 里我们关心的字段（其余原样不带，避免把未知结构塞回 store）。 */
type PulledBundle = {
  nodes?: never[];
  edges?: never[];
  dramaTitle?: string;
  episode?: string;
  stage3d?: unknown;
  timeline?: { clips?: Record<string, unknown>[]; clip_count?: number };
};

/**
 * 码不能用了以后，说清是**哪一种** —— 三种情况下一步动作完全不同：
 * 作废了要重新出码，用完了也要重新出码（但可以选更多人），过期了重新出码就行。
 * 都糊成「已失效」的话，人只会反复点重试。
 */
function deadPairReason(p: TeamPairingInfo): string {
  if (p.revoked) return "已被你作废";
  if (p.exhausted || p.remaining <= 0) return "名额用完了";
  if (p.expired) return "已过期（只活 2 分钟）";
  return "已失效";
}

export function TeamPanel({ onClose }: { onClose?: () => void }) {
  const [host, setHost] = useState<TeamHostStatus | null>(null);
  const [cred, setCred] = useState<TeamCred | null>(() => teamCred());
  const [address, setAddress] = useState<string>(() => teamCred()?.address || teamAddress());
  const [name, setName] = useState<string>(() => teamCred()?.name || "");
  const [discovered, setDiscovered] = useState<DiscoveredServer[]>([]);
  const [projects, setProjects] = useState<TeamProject[]>([]);
  const [inbox, setInbox] = useState<TeamHandoffItem[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [target, setTarget] = useState<string>("");
  const [note, setNote] = useState<string>("");
  /** 展开历史版本的项目 id（空串=都收起）。 */
  const [verFor, setVerFor] = useState<string>("");
  const [vers, setVers] = useState<TeamVersion[]>([]);
  const [verLoading, setVerLoading] = useState<boolean>(false);
  const [busy, setBusy] = useState<string>("");
  /** 心跳结论："" = 还没探过（不谎报），ok = 通，down = 断了。 */
  const [link, setLink] = useState<"ok" | "down" | "">("");
  /** 「现在」的秒级时间戳，跟着心跳往前走 —— 在线状态要靠它算「几分钟前」。 */
  const [nowSec, setNowSec] = useState<number>(() => Date.now() / 1000);
  const [line, setLine] = useState<{ kind: "ok" | "err" | "info"; text: string }>({ kind: "info", text: "" });
  const [assets, setAssets] = useState<TeamAsset[]>([]);
  /** ⑤ 段素材的类型筛选（全部/视频/图片/音频/其他）。 */
  const [assetKind, setAssetKind] = useState<AssetKindFilter>("all");
  /** ⑤ 段素材的搜索词（匹配文件名 / 出处 / 作者）。 */
  const [assetQ, setAssetQ] = useState<string>("");
  const [sync, setSync] = useState<string>("");
  /** 正在内联预览的附件 sha256（点开条目时设置，空串=收起）。 */
  const [preview, setPreview] = useState<string>("");
  /** 主机侧刚生成（或复用）的配对码；null = 还没点过。 */
  const [pair, setPair] = useState<TeamPairingInfo | null>(null);
  /** 这次要请几个人（1/3/5/9）。人数只能往上加：要得更多时会作废旧码。 */
  const [pairUses, setPairUses] = useState<number>(1);
  /** 卡片底下那行小提示（「已复制」「作废了」），比全局提示更贴近动作。 */
  const [pairNote, setPairNote] = useState<string>("");
  /** 同事侧输入框里的 6 位码。 */
  const [codeIn, setCodeIn] = useState<string>("");
  /** 倒计时用的"现在"（秒）。只在有码时每秒跳一次。 */
  const [now, setNow] = useState<number>(0);
  /** 出码那一刻的成员 ID 快照：之后多出来的人就是「刚用码进来的」。 */
  const memberBaseline = useRef<string>("");

  // 码只在 120 秒内有效，秒数必须自己走 —— 否则面板停在那儿显示「120 秒有效」，
  // 人以为永远有效，念晚了同事就白试一次。
  const pairEnd = pair?.expires_at || 0;
  useEffect(() => {
    if (!pairEnd) return;
    setNow(Date.now() / 1000);
    const t = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(t);
  }, [pairEnd]);
  const pairLeft = pairEnd ? Math.max(0, Math.ceil(pairEnd - (now || pairEnd))) : 0;

  const say = (kind: "ok" | "err" | "info", text: string) => setLine({ kind, text });
  const fail = (e: unknown) => {
    if (e instanceof TeamError) {
      const extra = e.extra as { author?: string; holder?: string; current_rev?: number };
      const tail = extra?.author ? `（${extra.author} 改到第 ${extra.current_rev ?? "?"} 版）`
        : extra?.holder ? `（${extra.holder} 占着）` : "";
      say("err", e.code === "conflict" ? `冲突：${e.message}${tail}` : e.message + tail);
    } else {
      say("err", String(e));
    }
  };

  const refreshHost = useCallback(async () => {
    try {
      setHost(await teamHostStatus());
    } catch (e) {
      fail(e);
    }
  }, []);

  const refreshTeam = useCallback(async () => {
    if (!teamCred()) return;
    try {
      const [ps, ib, ms] = await Promise.all([teamListProjects(), teamInbox(), teamMembers()]);
      setProjects(ps);
      setInbox(ib);
      setMembers(ms);
    } catch (e) {
      fail(e);
    }
  }, []);

  useEffect(() => {
    void refreshHost();
    void refreshTeam();
  }, [refreshHost, refreshTeam]);

  // ── 动作 ──────────────────────────────────────────
  /**
   * 把「画布 + 剪辑时间线 + 所有媒体」打成一份**可上传的 bundle**。
   *
   * 四步，缺一不可：
   *  ① `getProjectBundle()` **不含 `timeline`**（剪辑器时间线是 PyQt 那边的真相源，
   *     要单独经 `/host/project-snapshot/export` 取）⇒ 不补这一步，同事只能拿到
   *     画布图，成片时间线整个丢失；
   *  ② 片段用**本地绝对路径**引用素材，画布 JS 读不到 ⇒ 先经后端换算成
   *     `/inbox_file/…`（只换算、不传字节，避开 canvas_server 的 30 秒上限）；
   *  ③ **媒体索引缓存**：上次已经传过的素材直接复用 sha，不再重走网络。
   *     用之前先拿服务端附件列表做交集 —— 用户删过的附件必须重新传，
   *     否则写进去的是死链，而界面看上去「已同步」；
   *  ④ 剩余新素材按 sha256 传进附件库，再把 bundle 里的 URL 换过去。
   *
   * 返回的 bundle 已剥掉令牌，可以直接 push。
   */
  const prepareTeamBundle = async (projectId: string) => {
    const base = useCanvasStore.getState().getProjectBundle() as Record<string, unknown>;
    const warnings: string[] = [];
    let clips: Record<string, unknown>[] = [];

    try {
      const { fetchProjectTimeline } = await import("./projectZip");
      const tl = (await fetchProjectTimeline()) as { clips?: Record<string, unknown>[] } | null;
      clips = Array.isArray(tl?.clips) ? tl!.clips! : [];
    } catch (e) {
      warnings.push("取剪辑时间线失败：" + (e instanceof Error ? e.message : String(e)));
    }
    if (clips.length) base.timeline = { clips, clip_count: clips.length };

    const paths = clips.map((c) => String(c.path || "")).filter(Boolean);
    if (paths.length) {
      try {
        const { map, outside } = await teamInboxMap(paths);
        for (const c of clips) {
          const p = String(c.path || "");
          if (p && map[p]) c.path = map[p];     // 只改副本，不动剪辑器真相源
        }
        if (outside.length) {
          warnings.push(`${outside.length} 个片段素材不在素材库目录里，同事那边打不开`);
        }
      } catch (e) {
        warnings.push("片段素材路径换算失败：" + (e instanceof Error ? e.message : String(e)));
      }
    }

    // ③ 复用上次传过的：先确认这些 sha 在服务器上还活着
    let cached: Record<string, string> = readMediaCache(projectId);
    let reused = 0;
    if (Object.keys(cached).length) {
      try {
        const alive = new Set((await teamListAssets(projectId)).map((a) => a.sha256));
        const pruned = pruneMediaCache(cached, alive);
        cached = pruned.kept;
        reused = Object.keys(cached).length;
        if (pruned.dropped) {
          warnings.push(`${pruned.dropped} 个素材在服务器上已被删除，这次会重新上传`);
        }
      } catch {
        // 查不到存活状态就全部重传：宁可慢一趟，也不能写出指向已删附件的死链
        cached = {};
        reused = 0;
      }
    }
    const staged = applyMediaIndex(base, projectId, cached);

    // ④ 只传新增的
    const refs: MediaRef[] = collectMediaRefs(staged);
    let uploaded = 0;
    let posters = 0;
    let index: Record<string, string> = {};
    if (refs.length) {
      let done = 0;
      let curName = refs[0]?.name || "";
      let lastTick = 0;
      const total = refs.length;
      const res = await uploadMediaRefs(
        projectId,
        refs,
        (d, _t, ref, _phase) => {
          done = d;
          curName = ref.name;
          setSync(`上传 ${Math.min(d + 1, total)}/${total}：${ref.name}`);
        },
        (loaded, all) => {
          // 每 64KB 回调一次：200MB 会有 3000+ 次，不节流会把 React 拖死
          const now = Date.now();
          if (now - lastTick < 120) return;
          lastTick = now;
          const pct = all > 0 ? Math.round((loaded / all) * 100) : 0;
          setSync(`上传 ${Math.min(done + 1, total)}/${total}：${curName} ${pct}%`);
        },
      );
      uploaded = res.uploaded;
      posters = res.posters;
      index = res.map;
      if (res.failed.length) {
        warnings.push(
          `${res.failed.length} 个素材传不上去：` +
          res.failed.slice(0, 3).map((f) => `${f.name}（${f.why}）`).join("；") +
          (res.failed.length > 3 ? " 等" : ""),
        );
      }
    }
    setSync("");
    const merged = { ...cached, ...index };
    writeMediaCache(projectId, merged);
    const bundle = stripAssetTokens(applyMediaIndex(staged, projectId, index));
    return {
      bundle, warnings, clipCount: clips.length,
      mediaCount: refs.length + reused, uploaded, reused, posters,
    };
  };

  const startHost = async () => {
    setBusy("start");
    try {
      const st = await teamHostStart({ name: "拾光剪影团队" });
      setHost(st);
      // 2026-11-04：服务端启动时已把「本机主人」认了，凭据在 teamHostStart 里落了盘。
      // 同步一份到面板状态，否则「已连接」那一行和出码按钮仍按「没身份」处理。
      if (st.owner?.member_id) {
        setCred(teamCred());
        say("ok", `团队服务已启动：${st.address} —— 你已经是本机主人，可以直接出配对码`);
      } else if (st.running && st.address) {
        // 老服务端（还没这一天改动）或凭据没签出来：保留原来的兜底
        if (!cred) setAddress(st.address);
        say("ok", `团队服务已启动：${st.address}`);
      } else {
        say("err", "启动失败");
      }
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  };

  const stopHost = async () => {
    setBusy("stop");
    try {
      setHost(await teamHostStop());
      say("info", "团队服务已停止");
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  };

  const scan = async () => {
    setBusy("scan");
    say("info", "正在扫描局域网（3 秒）…");
    try {
      const servers = await teamDiscover();
      setDiscovered(servers);
      if (!servers.length) say("info", "没扫到服务器：确认对方已「启动团队服务」，且在同一网段");
      else if (servers.length === 1) {
        setAddress(servers[0].address);
        say("ok", `发现「${servers[0].name}」${servers[0].address}`);
      } else say("ok", `发现 ${servers.length} 台，选一个`);
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  };

  const join = async (addr = address) => {
    setBusy("join");
    try {
      const c = await teamJoin(addr, name || "同事");
      setCred(c);
      setAddress(c.address);
      say("ok", `已加入：${c.name}`);
      await refreshTeam();
    } catch (e) {
      // 🔴 2026-11-02：首次使用最常见的卡点就在这里 —— 本机服务还没启动，
      // 地址却填了自己（或同事）的机器，于是面板只丢一句网络错误，人不知道下一步点哪。
      // 有 `host.running` 这个已知状态就要用上：把「该点 ①」直接写进错误行。
      if (!host?.running && e instanceof TeamError && e.code.startsWith("net_")) {
        say("err", `${e.message}；如果这台就是服务器，先点 ① 的「启动团队服务」再回来加入`);
      } else {
        fail(e);
      }
      void refreshHost();
    } finally {
      setBusy("");
    }
  };

  /**
   * 出码之后每 2 秒问一次：名额变了没有 / 有没有人刚加进来。
   *
   * 用**只读**的 `GET /team/pairing`：那条路径绝不新建码 —— 否则人还在念，
   * 面板就换了个号码。码失效（用尽 / 作废 / 过期）后自动停掉轮询。
   *
   * `say` / `refreshHost` 走 ref：它们每次渲染都是新引用，放进依赖会让这个
   * 2 秒定时器不停重建（清掉再建），反而更容易丢帧。
   */
  const pairCode = pair?.code || "";
  const pairLive = !!pair?.alive && pairLeft > 0;
  const sayRef = useRef(say);
  sayRef.current = say;
  const hostRef = useRef(refreshHost);
  hostRef.current = refreshHost;

  useEffect(() => {
    if (!pairCode || !pairLive) return;
    let stop = false;
    const tick = async () => {
      try {
        const st = await teamPairingStatus();
        if (stop) return;
        if (st.code === pairCode) {
          setPair((prev) => (prev ? { ...prev, ...st } : st));
        } else {
          // 服务端手上已经没有活码了（用尽/被废/过期清理）
          setPair((prev) => (prev ? { ...prev, alive: false, remaining: 0, exhausted: true } : prev));
          setPairNote("这张码已经不能用了，重新出一个");
        }
      } catch {
        /* 网络抖一下就跳过，下一轮再来 —— 轮询失败不该弹错误打扰正在念码的人 */
      }
      try {
        const list = await teamMembers();
        if (stop) return;
        setMembers(list);
        const ids = list.map((m) => m.id).sort().join(",");
        if (!memberBaseline.current) {
          memberBaseline.current = ids;         // 出码那一刻的基线
        } else if (ids !== memberBaseline.current) {
          const before = memberBaseline.current.split(",");
          const fresh = list.filter((m) => !before.includes(m.id));
          if (fresh.length) {
            sayRef.current("ok",
              `${fresh.map((m) => m.name).join("、")} 已用配对码加入 —— 团队现在 ${list.length} 人`);
          }
          memberBaseline.current = ids;
          void hostRef.current();
        }
      } catch {
        /* 同上 */
      }
    };
    void tick();
    const timer = window.setInterval(() => { void tick(); }, 2000);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [pairCode, pairLive]);

  /**
   * 心跳：确认「服务器还在不在」，顺手把成员在线状态刷新一次。
   *
   * 为什么必须有一条：所有请求都只在**你点按钮时**才发。空闲时服务器被关掉、网线松了、
   * 笔记本换了 Wi-Fi，面板一个字都不变 —— 你以为还连着，改完点上传才发现白改。
   * 这里用一次轻请求（成员列表）同时当心跳和 presence 刷新，不另造机制。
   *
   * `loud=false` 时不弹错误：掉线每 12 秒弹一次提示等于骚扰，红字常驻就够。
   */
  const beat = async (loud = false): Promise<boolean> => {
    if (!teamCred()) return false;
    try {
      const list = await teamMembers();
      setMembers(list);
      setNowSec(Date.now() / 1000);
      setLink("ok");
      if (loud) say("ok", `连接正常 —— 团队 ${list.length} 人`);
      return true;
    } catch (e) {
      setLink("down");
      setNowSec(Date.now() / 1000);
      if (loud) fail(e);
      return false;
    }
  };
  const beatRef = useRef(beat);
  beatRef.current = beat;

  useEffect(() => {
    if (!cred) {
      setLink("");
      return;
    }
    let stop = false;
    // 名字别叫 tick：上面出码轮询里已经有一个 tick，重名会被质量棘轮记一笔
    const pulse = () => {
      if (stop) return;
      // 出码那 2 分钟里配对轮询本来就在刷成员，别再叠一层心跳
      if (pairCode && pairLive) return;
      void beatRef.current();
    };
    void pulse();
    const timer = window.setInterval(pulse, 12000);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [cred, pairCode, pairLive]);

  const probeLink = async () => {
    setBusy("ping");
    try {
      await beat(true);
    } finally {
      setBusy("");
    }
  };

  /**
   * 主机侧：出一张配对码给身边的同事。
   *
   * 生成码要**本机身份**（`created_by`），所以还没加入团队时会拿到 401 —— 那种
   * 情况不翻译成"令牌无效"，直接说下一步该点哪（面板语言纪律）。
   */
  const makePairing = async () => {
    setBusy("pairing");
    try {
      const p = await teamPairing(pairUses);
      setNow(Date.now() / 1000);
      setPair(p);
      setPairNote(p.replaced ? "名额变多了，旧码已作废" : "");
      memberBaseline.current = members.map((m) => m.id).sort().join(",");
      if (!p.expires_at) say("err", p.message || "暂时生不出配对码，等一秒再点一次");
      else if (p.reused) say("ok", `配对码还是 ${p.code}（上次那张没过期，接着用）`);
      else say("ok", `配对码 ${p.code}，能请 ${p.max_uses} 人，念给同事听`);
    } catch (e) {
      if (e instanceof TeamError && e.code === "unauthorized") {
        // 2026-11-04 起服务端启动就把主人认了，正常不会再走到这里；
        // 剩下两种可能：服务没起来，或升级前建的老库还没签过主人凭据。
        say("err", "这台机器还没有主人凭据 —— 先「停止」再「启动团队服务」一次即可");
        if (host?.address) setAddress(host.address);
      } else {
        fail(e);
      }
    } finally {
      setBusy("");
    }
  };

  /** 复制码 / 复制邀请链接：失败要说实话（画布内核的剪贴板不一定好使）。 */
  const copyPair = async (what: "code" | "url") => {
    if (!pair) return;
    const text = what === "code" ? pair.code : pair.pair_url;
    if (!text) {
      setPairNote("这台机器没有可用的内网地址，链接发不出去 —— 直接用 6 位数");
      return;
    }
    const ok = await copyText(text);
    setPairNote(ok ? (what === "code" ? `已复制 ${pair.code}` : "已复制邀请链接，发给同事即可")
      : "复制失败 —— 手动选中上面那串再按 Ctrl+C");
  };

  /** 作废这张码：念给了错的人时，比干等 2 分钟强。 */
  const revokePair = async () => {
    if (!pair?.code) return;
    setBusy("revoke");
    try {
      await teamRevokePairing(pair.code);
      setPairNote("已作废 —— 念出去也进不来了");
      setPair((prev) => (prev ? { ...prev, alive: false, revoked: true, remaining: 0 } : prev));
      say("info", "配对码已作废");
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  };

  /**
   * 同事侧：码 → 地址 → 令牌，一步到位。
   *
   * 分成两步是**必须的**：浏览器发不出 UDP 广播，地址只能由本机桥去问（`find-code`）。
   * 找到之后立刻 setAddress，这样即使下一步换令牌失败，人也能在地址栏里看到
   * 到底连的是哪台机器 —— 不至于"没反应"。
   */
  const joinByCode = async () => {
    const c = codeIn.trim();
    if (!/^\d{4,10}$/.test(c)) {
      say("err", "配对码是主机面板上那 6 位数字，检查一下再输");
      return;
    }
    setBusy("paircode");
    say("info", "正在用配对码在局域网里找主机…");
    try {
      const found = await teamFindByCode(c);
      if (!found.address) {
        say("err", found.message || "没找到持有这个配对码的电脑");
        return;
      }
      setAddress(found.address);
      say("info", `找到「${found.name || "主机"}」${found.address}，正在加入…`);
      const cc = await teamPair(c, name || "同事", found.address);
      setCred(cc);
      setAddress(cc.address);
      setCodeIn("");
      say("ok", `已用配对码加入：${cc.name}` +
        (cc.max_uses > 1 ? `（这张码还能请 ${cc.remaining} 人）` : ""));
      await refreshTeam();
    } catch (e) {
      // 码用过 / 过期 / 试太多次 —— 后端的 message 都能照着做，原样显示
      fail(e);
      void refreshHost();
    } finally {
      setBusy("");
    }
  };

  const uploadCurrent = async () => {
    setBusy("upload");
    try {
      const bundle = useCanvasStore.getState().getProjectBundle();
      const title = bundle.dramaTitle || "未命名画布";
      // 先建项目拿 project_id —— 附件必须挂在项目下，没有 id 无处可传
      const res = await teamCreateProject(title, bundle);
      // 再补一次：带时间线 + 已上传的素材（rev 1 → 2，中间只有几十毫秒）
      const prep = await prepareTeamBundle(res.project_id);
      const pushed = await teamPush(res.project_id, prep.bundle, res.rev, "补传时间线与素材");
      setLocalRev(res.project_id, pushed.rev);
      setSelected(res.project_id);
      await refreshTeam();
      const tail = prep.warnings.length ? `；注意：${prep.warnings.join("；")}` : "";
      say(prep.warnings.length ? "info" : "ok",
        `已上传「${title}」rev ${pushed.rev}（${prep.clipCount} 片段 / ${prep.mediaCount} 个素材，` +
        `新传 ${prep.uploaded}、复用 ${prep.reused}${prep.posters ? `、封面 ${prep.posters}` : ""}）${tail}`);
    } catch (e) {
      fail(e);
    } finally {
      setSync("");
      setBusy("");
    }
  };

  const pushTo = async (projectId: string) => {
    const p = projects.find((x) => x.project_id === projectId);
    if (!p) return;
    setBusy("push");
    try {
      const prep = await prepareTeamBundle(projectId);
      // base_rev 优先用「我本地这份是基于哪一版」：项目列表里的 rev 是刷新那一刻的，
      // 中间别人提交过它也不会变 —— 拿它当 base 会把别人的版本闷着盖掉。
      // 有本地锚点就按锚点判冲突；没有（从没拉过）才退回列表里的 rev。
      const baseRev = localRevOf(projectId) || p.rev;
      const res = await teamPush(projectId, prep.bundle, baseRev, note || "更新画布");
      setLocalRev(projectId, res.rev);
      await refreshTeam();
      const tail = prep.warnings.length ? `；注意：${prep.warnings.join("；")}` : "";
      say(prep.warnings.length ? "info" : "ok",
        `已上传到「${p.name}」→ rev ${res.rev}（${prep.clipCount} 片段 / ${prep.mediaCount} 个素材，` +
        `新传 ${prep.uploaded}、复用 ${prep.reused}${prep.posters ? `、封面 ${prep.posters}` : ""}）${tail}`);
    } catch (e) {
      fail(e);
    } finally {
      setSync("");
      setBusy("");
    }
  };

  /** 把拉下来的 bundle 装进画布。媒体 URL 换成**当前**团队地址（服务器换 IP 也能复活）。 */
  const loadPulled = (raw: unknown, fallbackName: string): PulledBundle => {
    const fixed = rebaseAssetUrls(raw) as PulledBundle;
    useCanvasStore.getState().loadProjectBundle({
      nodes: fixed.nodes || [],
      edges: fixed.edges || [],
      dramaTitle: fixed.dramaTitle || fallbackName,
      episode: fixed.episode,
      stage3d: fixed.stage3d,
    });
    return fixed;
  };

  /**
   * 拉取前先算差异 —— 「同事到底改了哪」。
   *
   * 多人协作最贵的错误不是冲突，是**盲目覆盖**：不知道对方改了 5 个节点就把自己
   * 手上的版本盖掉，那一遍白改。所以先算一次摘要差异摆出来，再让人决定。
   * 差异拿不到（老服务器没这端点 / 网络抖）**不拦拉取**，如实说明后继续问。
   */
  const confirmPull = async (projectId: string, title: string): Promise<boolean> => {
    const myRev = localRevOf(projectId);
    setBusy("diff");
    setSync("正在对比版本…");
    let preview = "";
    try {
      const d = await teamDiff(projectId, myRev, 0);
      preview = "\n\n" + formatTeamDiff(d, myRev);
    } catch (e) {
      preview = "\n\n（拿不到差异摘要：" + (e instanceof Error ? e.message : String(e)) + "）";
    } finally {
      setSync("");
      setBusy("");
    }
    return window.confirm(
      `拉取「${title}」会覆盖当前画布。${preview}\n\n` +
      `覆盖前会先把现在的画布另存为一个本地工程（名字带「覆盖前 时间」），\n` +
      `需要时能在「我的画布」里找到它。\n\n继续？`,
    );
  };

  /**
   * 拉取/接手之后顺手认领，返回一句能接在提示语后面的说明。
   *
   * 「打开就该占坑」：不认领的话，你在改的这段时间别人看到的项目是空闲的，
   * 他一上传你就白改。锁被别人占着**不算失败** —— 如实说「锁在 X 手上」，
   * 比闷着不认领然后上传时才冲突要好。
   */
  const claimNote = async (projectId: string): Promise<string> => {
    try {
      const r = await teamClaim(projectId);
      const mins = Math.max(1, Math.round((r.expires_at - Date.now() / 1000) / 60));
      return `，已顺手认领（${mins} 分钟内别人上传会看到你在改）`;
    } catch (e) {
      if (e instanceof TeamError && e.code === "locked") return `；⚠️ 没认领上：${e.message}，上传时可能撞`;
      return `；没认领上（${e instanceof Error ? e.message : String(e)}），不影响这次拉取`;
    }
  };

  const pullFrom = async (projectId: string) => {
    const p = projects.find((x) => x.project_id === projectId);
    if (!p) return;
    if (!(await confirmPull(projectId, p.name))) return;
    // 先另存再覆盖：确认弹窗里答应过「会先存一份」，做不到就得当场说，不能照拉。
    const keep = backupBeforePull();
    if (!keep.ok && !window.confirm(
      `另存一份失败：${keep.why}\n\n继续拉取会覆盖当前画布，而且找不回来。仍要继续？`,
    )) return;
    setBusy("pull");
    try {
      const data = await teamPull(projectId);
      const fixed = loadPulled(data.bundle, p.name);
      setLocalRev(projectId, data.rev);
      const saved = keep.skipped ? "" : keep.ok ? `；当前画布已另存为「${keep.name}」` : "；⚠️ 没能另存一份";
      const lock = await claimNote(projectId);
      say(keep.ok ? "ok" : "info", `已拉取「${p.name}」rev ${data.rev}${saved}${lock}`);
      await refreshTeam();
      await offerTimelineImport(fixed);
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  };

  /** 展开/收起某个项目的历史版本；展开时现拉一次（不留旧缓存，免得看到的 rev 是过期的）。 */
  const openVersions = async (projectId: string) => {
    if (verFor === projectId) {
      setVerFor("");
      return;
    }
    setVerFor(projectId);
    setVers([]);
    setVerLoading(true);
    try {
      setVers(await teamVersions(projectId));
    } catch (e) {
      fail(e);
    } finally {
      setVerLoading(false);
    }
  };

  /** 把历史上某一版拉到我本地（不动服务器）。覆盖前同样先另存一份。 */
  const pullRev = async (projectId: string, rev: number, name: string) => {
    if (!window.confirm(
      `把「${name}」的 rev ${rev} 拉到你本地？\n\n` +
      `只影响你这台机器，服务器上的版本一个都不会动。\n` +
      `会覆盖当前画布 —— 覆盖前同样会先把现在的画布另存为一个本地工程。`,
    )) return;
    const keep = backupBeforePull();
    if (!keep.ok && !window.confirm(
      `另存一份失败：${keep.why}\n\n继续会覆盖当前画布，而且找不回来。仍要继续？`,
    )) return;
    setBusy("pull");
    try {
      const data = await teamPull(projectId, rev);
      loadPulled(data.bundle, name);
      // 锚点记成本地实际拿到的那一版：之后算差异、上传判冲突都以它为基准
      setLocalRev(projectId, rev);
      const saved = keep.skipped ? "" : keep.ok ? `；当前画布已另存为「${keep.name}」` : "；⚠️ 没能另存一份";
      say("ok", `已把「${name}」rev ${rev} 拉到本地${saved}`);
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  };

  /**
   * 让全组都变成历史上某一版。服务端记成**新的一版**（历史只增不删），
   * 所以这句话必须在确认框里说清，否则没人敢按。
   */
  const rollbackTo = async (projectId: string, toRev: number, name: string, latestRev: number) => {
    if (!window.confirm(
      `让「${name}」全组回到 rev ${toRev}？\n\n` +
      `· 同事现在看到的是 rev ${latestRev}，会被替换成 rev ${toRev} 的内容\n` +
      `· **不会删掉任何历史版本** —— 服务端记成新的一版（rev ${latestRev + 1}），\n` +
      `  后悔了还能再回滚回来\n` +
      `· 想只影响自己、不动别人，请用旁边那个「拉这一版」`,
    )) return;
    setBusy("rollback");
    try {
      const r = await teamRollback(projectId, toRev, latestRev);
      say("ok", `已回滚到 rev ${toRev}（记为新的一版 rev ${r.rev}，历史都还在）`);
      await refreshTeam();
      setVers(await teamVersions(projectId));
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  };

  /**
   * 时间线要不要导进剪辑器，以及**先把素材落地到本机**。
   *
   * 同事要「接着改」就绕不开这一步：剪辑器只认本地文件路径，而拉下来的片段
   * 指向的是团队服务器。所以先串行下载（一次一个，避开 canvas_server 的 30 秒
   * 上限），把每个片段的 `path` 换成本机素材库路径，再直导。
   *
   * 下载失败的片段**不静默丢**：照样导入并明说「这几段要手动重新链接素材」，
   * 让人知道去哪找原因，而不是发现黑片段却不知道发生了什么。
   */
  const offerTimelineImport = async (b: PulledBundle) => {
    const clips = b.timeline?.clips || [];
    if (!clips.length) return;

    const remote = clips.filter((c) => isTeamAsset(String(c.path || "")));
    const ask = remote.length
      ? `这版带着 ${clips.length} 个剪辑片段，其中 ${remote.length} 个素材在团队服务器上。\n\n` +
        `「确定」= 先把素材下载到本机素材库，再导入剪辑器（推荐）\n` +
        `「取消」= 只看画布，先不碰剪辑器`
      : `这版带着 ${clips.length} 个剪辑片段，但它们的素材路径不是团队附件，` +
        `导入后大概率找不到文件。\n\n仍然导入剪辑器？`;
    if (!window.confirm(ask)) {
      say("info", `画布已载入；${clips.length} 个片段未导入剪辑器`);
      return;
    }

    const failed: string[] = [];
    if (remote.length) {
      setBusy("materialize");
      try {
        for (let i = 0; i < remote.length; i++) {
          const c = remote[i];
          const url = String(c.path || "");
          const name = String(c.name || "") || `片段${i + 1}`;
          setSync(`下载素材 ${i + 1}/${remote.length}：${name}`);
          try {
            const r = await teamMaterialize(url, name);
            if (r.ok && r.path) c.path = r.path;
            else failed.push(`${name}（${r.message || "未知原因"}）`);
          } catch (e) {
            failed.push(`${name}（${e instanceof Error ? e.message : String(e)}）`);
          }
        }
      } finally {
        setSync("");
        setBusy("");
      }
    }

    try {
      const { pushTimelineToEditor } = await import("./projectZip");
      const r = await pushTimelineToEditor(clips);
      const tail = failed.length
        ? `；${failed.length} 个素材没下载成功，这些片段导入后需手动重新链接（${failed.slice(0, 2).join("；")}）`
        : remote.length ? `；已落地 ${remote.length} 个素材到本机素材库` : "";
      say(failed.length ? "info" : r.ok ? "ok" : "err", r.message + tail);
    } catch (e) {
      fail(e);
    }
  };

  const claim = async (projectId: string) => {
    setBusy("claim");
    try {
      const r = await teamClaim(projectId);
      const mins = Math.max(1, Math.round((r.expires_at - Date.now() / 1000) / 60));
      say("ok", `已认领，${mins} 分钟内别人不能编辑`);
      await refreshTeam();
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  };

  const release = async (projectId: string) => {
    setBusy("release");
    try {
      await teamRelease(projectId);
      say("info", "已释放");
      await refreshTeam();
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  };

  const doHandoff = async (projectId: string) => {
    if (!target) {
      say("err", "先选一个同事");
      return;
    }
    setBusy("handoff");
    try {
      await teamHandoff(projectId, target, note || "交给你接手");
      say("ok", `已交接给 ${members.find((m) => m.id === target)?.name || target}`);
      await refreshTeam();
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  };

  const accept = async (item: TeamHandoffItem) => {
    const p = projects.find((x) => x.project_id === item.project_id);
    // 先问再 ack：反过来会在用户点「取消」时把交接单也确认掉了
    if (!(await confirmPull(item.project_id, item.project_name || item.project_id))) return;
    setBusy("accept");
    try {
      await teamAck(item.handoff_id);
      const data = await teamPull(item.project_id);
      const fixed = loadPulled(data.bundle, item.project_name);
      setLocalRev(item.project_id, data.rev);
      // 交接单已经确认掉了，这里认领失败（锁在别人手上）不该把整次接手判失败
      const lock = await claimNote(item.project_id);
      say("ok", `已接手「${p?.name || item.project_name}」${lock}`);
      await refreshTeam();
      await offerTimelineImport(fixed);
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  };

  const selectedProject = projects.find((p) => p.project_id === selected);
  const assetTally = assetCounts(assets);
  const shownAssets = filterAssets(assets, assetKind, assetQ);

  const fmtBytes = (n: number) => {
    const v = Number(n) || 0;
    if (v >= 1048576) return `${(v / 1048576).toFixed(1)}MB`;
    if (v >= 1024) return `${Math.round(v / 1024)}KB`;
    return `${v}B`;
  };

  const refreshAssets = useCallback(async (projectId: string) => {
    if (!projectId || !teamCred()) {
      setAssets([]);
      return;
    }
    try {
      setAssets(await teamListAssets(projectId));
    } catch (e) {
      fail(e);
    }
  }, []);

  useEffect(() => {
    setPreview("");
    // 换项目时把筛选清掉：带着上一个项目的「只看视频 + 搜索镜 03」进新项目，
    // 大概率是一片空白，而用户会以为新项目没素材。
    setAssetKind("all");
    setAssetQ("");
    void refreshAssets(selected);
  }, [selected, refreshAssets]);

  /** 从磁盘挑一个文件传上去（成片 mp4 走这里最快，不必先进画布）。 */
  const uploadFile = async (file: File | null) => {
    if (!file) return;
    if (!selected) {
      say("err", "先在 ③ 里选一个共享项目，素材要挂在项目下面");
      return;
    }
    setBusy("asset");
    try {
      // 归属取自画布上**当前选中的节点**：用户站在「镜 03」那条上点上传，
      // 这条素材就该标成「来自 镜 03」。没有选中就留空，不瞎猜。
      const owner = selectedNodeTitle();
      setSync(`上传 ${file.name}（${fmtBytes(file.size)}）…`);
      const a = await teamUploadAsset(selected, file, file.name, kindOf(file.name) || "file",
        undefined, { owner });
      say("ok", `已上传「${a.name}」（${fmtBytes(a.bytes)}）${owner ? `，标注来自 ${owner}` : ""}`);
      await refreshAssets(selected);
    } catch (e) {
      fail(e);
    } finally {
      setSync("");
      setBusy("");
    }
  };

  const dropAsset = async (sha: string, name: string) => {
    if (!selected || !window.confirm(`从团队里删掉「${name}」？画布里引用它的地方会失效。`)) return;
    setBusy("asset-del");
    try {
      await teamDeleteAsset(selected, sha);
      say("info", `已删除「${name}」`);
      if (preview === sha) setPreview("");
      await refreshAssets(selected);
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="sg-team-panel" role="dialog" aria-label="团队协作">
      <div className="sg-team-head">
        <b>👥 团队协作</b>
        <span className="sg-team-sub">{cred ? `已连接 · ${cred.name} @ ${cred.address}` : "未加入团队"}</span>
        {onClose ? (
          <button type="button" className="sg-team-x" onClick={onClose} title="关闭">×</button>
        ) : null}
      </div>

      {line.text ? <div className={`sg-team-line ${line.kind}`}>{line.text}</div> : null}
      {sync ? <div className="sg-team-line info">{sync}</div> : null}

      {/* 1. 本机服务 */}
      <section className="sg-team-sec">
        <h4>① 我当服务器（同事连我）</h4>
        {host?.running ? (
          <div className="sg-team-row">
            <code className="sg-team-addr">{host.address}</code>
            <button type="button" disabled={busy === "stop"} onClick={() => void stopHost()}>停止</button>
            <span className="sg-team-dim">
              {host.stats?.projects ?? 0} 项目 · {host.stats?.members ?? 0} 成员
            </span>
          </div>
        ) : (
          <div className="sg-team-row">
            <button type="button" disabled={busy === "start"} onClick={() => void startHost()}>
              {busy === "start" ? "启动中…" : "启动团队服务"}
            </button>
            <span className="sg-team-dim">启动后把地址发给同事；只需一台机器当服务器</span>
          </div>
        )}
        {/* 配对码：把「念一串 IP」换成「念 6 个数字」 */}
        {host?.running ? (
          <div className="sg-team-pair">
            <div className="sg-team-row">
              <select
                value={pairUses}
                onChange={(e) => setPairUses(Number(e.target.value))}
                disabled={busy === "pairing"}
                title="这张码能请几个人"
              >
                <option value={1}>请 1 人</option>
                <option value={3}>请 3 人</option>
                <option value={5}>请 5 人</option>
                <option value={9}>请 9 人</option>
              </select>
              <button type="button" disabled={busy === "pairing"} onClick={() => void makePairing()}>
                {busy === "pairing" ? "生成中…" : pair?.code ? "重新出码" : "让同事加入（出 6 位码）"}
              </button>
              {pair?.code ? null : <span className="sg-team-dim">不用念 IP —— 给他 6 位数字就行</span>}
            </div>
            {pair?.code ? (
              <div className={`sg-team-code${pairLive ? "" : " dead"}`}>
                <div className="sg-team-code-main">
                  <b className={pairLive ? "" : "dead"}>{pair.code}</b>
                  {pair.qr && pairLive ? <img src={pair.qr} alt="配对二维码" /> : null}
                  <div className="sg-team-code-facts">
                    <span className={pairLive ? "sg-team-left" : "sg-team-left off"}>
                      {pairLive ? `还能请 ${pair.remaining} 人 · ${pairLeft} 秒后失效` : deadPairReason(pair)}
                    </span>
                    <span className="sg-team-dim">
                      共 {pair.max_uses} 个名额 · 已用 {pair.uses}
                      {/* host_name 是**服务器名**（TeamServer.name），不是人名 —— 原来写「发码方」
                          会让人以为是同事的名字，实机截图里还因为太长折成三行 */}
                      {pair.host_name ? ` · 服务器 ${pair.host_name}` : ""}
                    </span>
                  </div>
                </div>
                {pairLive ? (
                  <div className="sg-team-bar">
                    {/* 分母是服务端的 PAIR_TTL（120 秒），只用来画这条进度；能不能用一律以 alive 为准 */}
                    <i style={{ width: `${Math.min(100, Math.max(0, Math.round((pairLeft / 120) * 100)))}%` }} />
                  </div>
                ) : null}
                <div className="sg-team-acts">
                  <button type="button" onClick={() => void copyPair("code")}>复制码</button>
                  <button type="button" onClick={() => void copyPair("url")}>复制邀请链接</button>
                  {pairLive ? (
                    <button type="button" disabled={busy === "revoke"} onClick={() => void revokePair()}>
                      {busy === "revoke" ? "作废中…" : "立即作废"}
                    </button>
                  ) : null}
                </div>
                <span className="sg-team-dim">
                  {pairNote || "同事在 ② 填这 6 位数字；手机扫二维码能看到地址和名额，方便转发"}
                </span>
              </div>
            ) : null}
          </div>
        ) : null}
      </section>

      {/* 2. 连接 */}
      <section className="sg-team-sec">
        <h4>② 我连别人的团队</h4>
        {/* 首选这条路：一张 6 位码换地址，不必问对方 IP */}
        <div className="sg-team-row">
          <input
            value={codeIn}
            onChange={(e) => setCodeIn(e.target.value.replace(/\D/g, "").slice(0, 10))}
            placeholder="主机给的 6 位配对码"
            inputMode="numeric"
            spellCheck={false}
            style={{ width: 156 }}
          />
          <button type="button" disabled={busy === "paircode"} onClick={() => void joinByCode()}>
            {busy === "paircode" ? "查找中…" : "用配对码加入"}
          </button>
          <span className="sg-team-dim">2 分钟内有效、只能用一次</span>
        </div>
        <div className="sg-team-row">
          <button type="button" disabled={busy === "scan"} onClick={() => void scan()}>
            {busy === "scan" ? "扫描中…" : "扫描局域网"}
          </button>
          {discovered.length > 1 ? (
            <select value={address} onChange={(e) => setAddress(e.target.value)}>
              {discovered.map((d) => (
                <option key={d.address} value={d.address}>{d.name} · {d.address}</option>
              ))}
            </select>
          ) : null}
        </div>
        <div className="sg-team-row">
          <input
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            placeholder="http://192.168.1.4:18770"
            spellCheck={false}
          />
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="我的名字"
            style={{ width: 110 }}
          />
          <button type="button" disabled={busy === "join"} onClick={() => void join()}>
            {busy === "join" ? "加入中…" : "加入"}
          </button>
          {cred ? (
            <button type="button" onClick={() => { teamLeave(); setCred(null); say("info", "已退出团队"); }}>
              退出
            </button>
          ) : null}
        </div>
        {/* 连接状态与「谁还在」：挂在 ② 段末尾，不另开一段（信息架构不动） */}
        {cred ? (
          <>
            <div className="sg-team-row">
              <span className={link === "down" ? "sg-team-linkbad" : "sg-team-dim"}>
                {linkText(link, members.length, onlineCount(members, nowSec))}
              </span>
              <button type="button" disabled={busy === "ping"} onClick={() => void probeLink()}>
                {busy === "ping" ? "检查中…" : link === "down" ? "重新连" : "检查连接"}
              </button>
            </div>
            {members.length ? (
              <div className="sg-team-people">
                {members.map((m) => (
                  <span key={m.id} className={`sg-team-who${isOnline(m.last_seen, nowSec) ? " on" : ""}`}>
                    {m.name}{m.id === cred.member_id ? "（我）" : ""} · {seenText(m.last_seen, nowSec)}
                  </span>
                ))}
              </div>
            ) : null}
          </>
        ) : null}
      </section>

      {/* 3. 项目 */}
      {cred ? (
        <section className="sg-team-sec">
          <h4>③ 共享项目</h4>
          <div className="sg-team-row">
            <button type="button" disabled={busy === "upload"} onClick={() => void uploadCurrent()}>
              {busy === "upload" ? "上传中…" : "上传当前画布"}
            </button>
            <button type="button" onClick={() => void refreshTeam()}>刷新</button>
            <span className="sg-team-dim">上传=新建一个共享项目；别的项目用下方「上传到此」</span>
          </div>
          {/* 备注框放在这里而不是「交接」那一行：它是**上传时的版本名**，
              放在交接框里等于用户上传时根本看不见它，「版本命名」就成了黑箱。 */}
          <div className="sg-team-row">
            <input value={note} onChange={(e) => setNote(e.target.value)}
                   placeholder="版本备注（改了第 3 卡的字幕）—— 上传和交接都会带上" />
          </div>
          {projects.length ? (
            <div className="sg-team-list">
              {projects.map((p) => {
                const claimed = p.claimed_by && p.claim_expires_at > Date.now() / 1000;
                return (
                  <div key={p.project_id} className="sg-team-proj">
                  <div className={`sg-team-item${selected === p.project_id ? " on" : ""}`}
                       onClick={() => setSelected(p.project_id)}>
                    <div className="sg-team-item-main">
                      <b>{p.name}</b>
                      <span className="sg-team-dim">rev {p.rev} · {p.owner} · {new Date(p.updated_at * 1000).toLocaleString()}</span>
                      {claimed ? <span className="sg-team-lock">🔒 {p.claimed_by}</span> : null}
                    </div>
                    <div className="sg-team-item-actions">
                      <button type="button" onClick={(e) => { e.stopPropagation(); void pullFrom(p.project_id); }}>拉取</button>
                      <button type="button" onClick={(e) => { e.stopPropagation(); void pushTo(p.project_id); }}>上传到此</button>
                      <button type="button" onClick={(e) => { e.stopPropagation(); void openVersions(p.project_id); }}>
                        {verFor === p.project_id ? "收起历史" : "历史"}
                      </button>
                      <button type="button" onClick={(e) => { e.stopPropagation(); void claim(p.project_id); }}>认领</button>
                      <button type="button" onClick={(e) => { e.stopPropagation(); void release(p.project_id); }}>释放</button>
                    </div>
                  </div>
                  {verFor === p.project_id ? (
                    <TeamVersions
                      versions={vers}
                      loading={verLoading}
                      latestRev={p.rev}
                      onLoadRev={(rev) => void pullRev(p.project_id, rev, p.name)}
                      onRollback={(rev) => void rollbackTo(p.project_id, rev, p.name, p.rev)}
                    />
                  ) : null}
                  </div>
                );
              })}
            </div>
          ) : <div className="sg-team-dim">还没有共享项目</div>}

          {selectedProject ? (
            <div className="sg-team-handoff">
              <select value={target} onChange={(e) => setTarget(e.target.value)}>
                <option value="">交接给…</option>
                {members.filter((m) => m.id !== cred.member_id).map((m) => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))}
              </select>
              <button type="button" disabled={busy === "handoff"} onClick={() => void doHandoff(selectedProject.project_id)}>
                交接
              </button>
            </div>
          ) : null}
        </section>
      ) : null}

      {/* 4. 收件箱 */}
      {cred ? (
        <section className="sg-team-sec">
          <h4>④ 交接给我的（{inbox.length}）</h4>
          {inbox.length ? inbox.map((it) => (
            <div key={it.handoff_id} className="sg-team-item">
              <div className="sg-team-item-main">
                <b>{it.project_name || it.project_id}</b>
                <span className="sg-team-dim">来自 {it.from} · {it.message}</span>
              </div>
              <div className="sg-team-item-actions">
                <button type="button" disabled={busy === "accept"} onClick={() => void accept(it)}>接手</button>
              </div>
            </div>
          )) : <div className="sg-team-dim">没有待接手的交接</div>}
        </section>
      ) : null}

      {/* 5. 素材（大文件：画布 JSON 装不下的那部分）*/}
      {cred ? (
        <section className="sg-team-sec">
          <h4>⑤ 素材与成片（{assets.length}）</h4>
          <div className="sg-team-row">
            <label className={`sg-team-file${!selected || busy === "asset" ? " off" : ""}`}>
              <input
                type="file"
                disabled={!selected || busy === "asset"}
                onChange={(ev) => {
                  const f = ev.currentTarget.files?.[0] || null;
                  ev.currentTarget.value = "";   // 允许连续选同一个文件
                  void uploadFile(f);
                }}
              />
              <span>{selected ? (busy === "asset" ? "上传中…" : "选文件上传") : "先在 ③ 选个共享项目"}</span>
            </label>
            <button type="button" disabled={!selected} onClick={() => void refreshAssets(selected)}>刷新</button>
            <span className="sg-team-dim">成片 mp4 / 图 / 音频都行；有封面的会显示缩略图</span>
          </div>
          {assets.length ? (
            <>
              {/* 筛与搜：项目跑到三十几条时，「找镜 03 那个视频」只能靠这两个 */}
              <div className="sg-team-row sg-team-filters">
                {(["all", "video", "image", "audio", "other"] as AssetKindFilter[]).map((k) => (
                  <button
                    key={k}
                    type="button"
                    className={`sg-team-chip${assetKind === k ? " on" : ""}`}
                    onClick={() => setAssetKind(k)}
                  >
                    {kindLabel(k)} {assetTally[k]}
                  </button>
                ))}
                <input
                  value={assetQ}
                  onChange={(e) => setAssetQ(e.target.value)}
                  placeholder="搜文件名 / 出处（镜 03）"
                />
              </div>
              {shownAssets.length ? (
                <div className="sg-team-list">
                  {shownAssets.map((a) => {
                const url = teamAssetUrl(selected, a.sha256);
                const open = preview === a.sha256;
                const posterUrl = a.poster ? teamAssetUrl(selected, a.poster) : "";
                return (
                  <div key={a.sha256} className="sg-team-item sg-team-asset">
                    <div className="sg-team-asset-row">
                      <AssetThumb url={url} posterUrl={posterUrl} kind={a.kind} icon={kindIcon(a.kind)} />
                      <div className="sg-team-item-main">
                        <b>{a.name}</b>
                        <span className="sg-team-dim">
                          {kindIcon(a.kind)} {fmtBytes(a.bytes)} · {a.author || "未知"}
                          {a.owner ? ` · 来自 ${a.owner}` : ""}
                        </span>
                      </div>
                    </div>
                    <div className="sg-team-item-actions">
                      <button type="button" onClick={() => setPreview(open ? "" : a.sha256)}>
                        {open ? "收起" : "打开"}
                      </button>
                      <button type="button" disabled={busy === "asset-del"} onClick={() => void dropAsset(a.sha256, a.name)}>删除</button>
                    </div>
                    {open ? (
                      <div className="sg-team-preview">
                        {!url ? <span className="sg-team-dim">还没加入团队，拿不到地址</span>
                          : a.kind === "video" ? <VideoPreview url={url} name={a.name} />
                            : a.kind === "image" ? <img src={url} alt={a.name} />
                              : a.kind === "audio" ? <audio src={url} controls />
                                : <a href={url} download={a.name}>下载「{a.name}」</a>}
                      </div>
                    ) : null}
                  </div>
                );
                  })}
                </div>
              ) : (
                <div className="sg-team-dim">{emptyAssetHint(assets.length, assetKind, assetQ)}</div>
              )}
            </>
          ) : <div className="sg-team-dim">{emptyAssetHint(0, "all", "")}</div>}
        </section>
      ) : null}
    </div>
  );
}

/** 附件类型的小图标（不引第三方图标库，纯字符）。 */
function kindIcon(kind: string): string {
  return kind === "video" ? "🎬" : kind === "image" ? "🖼" : kind === "audio" ? "🎵" : kind === "text" ? "📄" : "📦";
}

/**
 * 画布上当前选中节点的标题（`镜 03`），没有选中就是空串。
 *
 * 为什么不弹框让用户手填：上传这件事本来就发生在「我正在看某个镜」的上下文里，
 * 让用户再打一遍字属于白问；真正不知道的时候（没选节点）留空比瞎猜安全。
 */
function selectedNodeTitle(): string {
  try {
    const bundle = useCanvasStore.getState().getProjectBundle() as { nodes?: Record<string, unknown>[] };
    const nodes = Array.isArray(bundle?.nodes) ? bundle.nodes : [];
    const sel = nodes.find((n) => n && n.selected);
    const data = (sel?.data || {}) as Record<string, unknown>;
    for (const k of ["title", "label", "name"]) {
      const v = data[k];
      if (typeof v === "string" && v.trim()) return v.trim().slice(0, 40);
    }
  } catch {
    /* 拿不到 store 就当没有归属，别让它拦住上传 */
  }
  return "";
}

/**
 * 列表里的缩略图（52×30）。
 *
 * 优先级：**视频封面附件** → 图片本体 → 类型图标。
 *
 * 为什么视频必须靠上传时存下的封面：画布内核（Qt WebEngine）没有 H.264 解码器，
 * `<video>` 对 mp4 直接 `error.code=4`，`#t=0.1` 片段定位、`canvas.drawImage`
 * 也全都拿不到像素（实测 webm 正常、mp4 全黑）。所以这里绝不去「现场截帧」，
 * 只用后端用 ffmpeg 抽好、随附件一起传上去的那张 JPEG。
 */
function AssetThumb({ url, posterUrl, kind, icon }: {
  url: string; posterUrl: string; kind: string; icon: string;
}) {
  const [broken, setBroken] = useState(false);
  const src = posterUrl || (kind === "image" ? url : "");
  if (!src || broken) return <span className="sg-team-thumb">{icon}</span>;
  // loading=lazy：列表里十几张大图不必一次全拉；解码也丢给异步线程
  return (
    <img className="sg-team-thumb" src={src} alt="" loading="lazy" decoding="async"
         onError={() => setBroken(true)} />
  );
}

/**
 * 视频预览：放不出来时**说清原因**，而不是留一块黑。
 *
 * 本机 Qt WebEngine 不带 H.264/AAC，而产品自己渲染的成片正是 h264 ⇒ 这是
 * 常态而非异常。用户看到黑框只会以为文件坏了、反复重传。
 * 文案与节点侧共用（`videoFallback.ts`），这里只多给一条下载出路。
 */
function VideoPreview({ url, name }: { url: string; name: string }) {
  const v = useVideoBad();
  if (v.bad) {
    return (
      <VideoUnplayable>
        <a href={url} download={name}>下载「{name}」用系统播放器看</a>
      </VideoUnplayable>
    );
  }
  return <video src={url} controls preload="metadata" onError={v.onError} />;
}
