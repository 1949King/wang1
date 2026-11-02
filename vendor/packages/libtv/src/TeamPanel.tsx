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
import { useCallback, useEffect, useState } from "react";
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
  teamMembers,
  teamPull,
  teamPush,
  teamRelease,
  teamUploadAsset,
} from "./teamClient";
import {
  applyMediaIndex,
  collectMediaRefs,
  kindOf,
  rebaseAssetUrls,
  stripAssetTokens,
  uploadMediaRefs,
  type MediaRef,
} from "./teamAssets";
import "./teamPanel.css";

type Member = { id: string; name: string; role: string };

/** 拉下来的 bundle 里我们关心的字段（其余原样不带，避免把未知结构塞回 store）。 */
type PulledBundle = {
  nodes?: never[];
  edges?: never[];
  dramaTitle?: string;
  episode?: string;
  stage3d?: unknown;
  timeline?: { clips?: Record<string, unknown>[]; clip_count?: number };
};

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
  const [busy, setBusy] = useState<string>("");
  const [line, setLine] = useState<{ kind: "ok" | "err" | "info"; text: string }>({ kind: "info", text: "" });
  const [assets, setAssets] = useState<TeamAsset[]>([]);
  const [sync, setSync] = useState<string>("");
  /** 正在内联预览的附件 sha256（点开条目时设置，空串=收起）。 */
  const [preview, setPreview] = useState<string>("");

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
   * 三步，缺一不可：
   *  ① `getProjectBundle()` **不含 `timeline`**（剪辑器时间线是 PyQt 那边的真相源，
   *     要单独经 `/host/project-snapshot/export` 取）⇒ 不补这一步，同事只能拿到
   *     画布图，成片时间线整个丢失；
   *  ② 片段用**本地绝对路径**引用素材，画布 JS 读不到 ⇒ 先经后端换算成
   *     `/inbox_file/…`（只换算、不传字节，避开 canvas_server 的 30 秒上限）；
   *  ③ 所有媒体按 sha256 传进团队附件库，再把 bundle 里的 URL 换过去。
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

    const refs: MediaRef[] = collectMediaRefs(base);
    let uploaded = 0;
    let index: Record<string, string> = {};
    if (refs.length) {
      setSync(`准备上传 ${refs.length} 个素材…`);
      const res = await uploadMediaRefs(projectId, refs, (done, total, ref, phase) => {
        setSync(`上传素材 ${done}/${total}：${ref.name}${phase === "fail" ? "（失败）" : ""}`);
      });
      uploaded = res.uploaded;
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
    const bundle = stripAssetTokens(applyMediaIndex(base, projectId, index));
    return { bundle, warnings, clipCount: clips.length, mediaCount: refs.length, uploaded };
  };

  const startHost = async () => {
    setBusy("start");
    try {
      const st = await teamHostStart({ name: "拾光剪影团队" });
      setHost(st);
      say("ok", st.running ? `团队服务已启动：${st.address}` : "启动失败");
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
      setSelected(res.project_id);
      await refreshTeam();
      const tail = prep.warnings.length ? `；注意：${prep.warnings.join("；")}` : "";
      say(prep.warnings.length ? "info" : "ok",
        `已上传「${title}」rev ${pushed.rev}（${prep.clipCount} 片段 / ${prep.mediaCount} 个素材，成功 ${prep.uploaded}）${tail}`);
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
      const res = await teamPush(projectId, prep.bundle, p.rev, note || "更新画布");
      await refreshTeam();
      const tail = prep.warnings.length ? `；注意：${prep.warnings.join("；")}` : "";
      say(prep.warnings.length ? "info" : "ok",
        `已上传到「${p.name}」→ rev ${res.rev}（${prep.clipCount} 片段 / ${prep.mediaCount} 个素材，成功 ${prep.uploaded}）${tail}`);
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

  const pullFrom = async (projectId: string) => {
    const p = projects.find((x) => x.project_id === projectId);
    if (!p) return;
    if (!window.confirm(`拉取「${p.name}」会覆盖当前画布，继续？`)) return;
    setBusy("pull");
    try {
      const data = await teamPull(projectId);
      const fixed = loadPulled(data.bundle, p.name);
      say("ok", `已拉取「${p.name}」rev ${data.rev}`);
      await offerTimelineImport(fixed);
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  };

  /**
   * 时间线要不要直导剪辑器。
   *
   * 诚实边界：clips 里的 `path` 是**原作者机器上的路径**，换了机器基本指不到文件。
   * 问一句再导，比导进去一堆黑片段让同事以为"素材丢了"要好；画布里的图和视频
   * 不受影响（它们的 URL 已经指向团队附件库，能直接播）。
   */
  const offerTimelineImport = async (b: PulledBundle) => {
    const clips = b.timeline?.clips || [];
    if (!clips.length) return;
    const go = window.confirm(
      `这版还带着 ${clips.length} 个剪辑片段。\n\n` +
      "导入到剪辑器会套用**原作者电脑上的文件路径**，你这边可能找不到素材。\n" +
      "（画布上的图和视频不受影响，能直接播。）\n\n仍然导入到剪辑器？",
    );
    if (!go) {
      say("info", `画布已载入；${clips.length} 个片段未导入剪辑器`);
      return;
    }
    try {
      const { pushTimelineToEditor } = await import("./projectZip");
      const r = await pushTimelineToEditor(clips);
      say(r.ok ? "ok" : "err", r.message);
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
    setBusy("accept");
    try {
      await teamAck(item.handoff_id);
      if (!window.confirm(`接手「${item.project_name}」会覆盖当前画布，继续？`)) {
        await refreshTeam();
        return;
      }
      const data = await teamPull(item.project_id);
      const fixed = loadPulled(data.bundle, item.project_name);
      await teamClaim(item.project_id);
      say("ok", `已接手「${p?.name || item.project_name}」`);
      await refreshTeam();
      await offerTimelineImport(fixed);
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  };

  const selectedProject = projects.find((p) => p.project_id === selected);

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
      setSync(`上传 ${file.name}（${fmtBytes(file.size)}）…`);
      const a = await teamUploadAsset(selected, file, file.name, kindOf(file.name) || "file");
      say("ok", `已上传「${a.name}」（${fmtBytes(a.bytes)}），同事点「打开」就能看`);
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
      </section>

      {/* 2. 连接 */}
      <section className="sg-team-sec">
        <h4>② 我连别人的团队</h4>
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
          {projects.length ? (
            <div className="sg-team-list">
              {projects.map((p) => {
                const claimed = p.claimed_by && p.claim_expires_at > Date.now() / 1000;
                return (
                  <div key={p.project_id} className={`sg-team-item${selected === p.project_id ? " on" : ""}`}
                       onClick={() => setSelected(p.project_id)}>
                    <div className="sg-team-item-main">
                      <b>{p.name}</b>
                      <span className="sg-team-dim">rev {p.rev} · {p.owner} · {new Date(p.updated_at * 1000).toLocaleString()}</span>
                      {claimed ? <span className="sg-team-lock">🔒 {p.claimed_by}</span> : null}
                    </div>
                    <div className="sg-team-item-actions">
                      <button type="button" onClick={(e) => { e.stopPropagation(); void pullFrom(p.project_id); }}>拉取</button>
                      <button type="button" onClick={(e) => { e.stopPropagation(); void pushTo(p.project_id); }}>上传到此</button>
                      <button type="button" onClick={(e) => { e.stopPropagation(); void claim(p.project_id); }}>认领</button>
                      <button type="button" onClick={(e) => { e.stopPropagation(); void release(p.project_id); }}>释放</button>
                    </div>
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
              <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="留言（第 3 卡我改好了）" />
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
            <span className="sg-team-dim">成片 mp4 / 图 / 音频都行，同事点「打开」就能看</span>
          </div>
          {assets.length ? (
            <div className="sg-team-list">
              {assets.map((a) => {
                const url = teamAssetUrl(selected, a.sha256);
                const open = preview === a.sha256;
                return (
                  <div key={a.sha256} className="sg-team-item sg-team-asset">
                    <div className="sg-team-item-main">
                      <b>{kindIcon(a.kind)} {a.name}</b>
                      <span className="sg-team-dim">{fmtBytes(a.bytes)} · {a.author || "未知"}</span>
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
                          : a.kind === "video" ? <video src={url} controls preload="metadata" />
                            : a.kind === "image" ? <img src={url} alt={a.name} />
                              : a.kind === "audio" ? <audio src={url} controls />
                                : <a href={url} download={a.name}>下载「{a.name}」</a>}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          ) : <div className="sg-team-dim">这个项目还没有素材。成片视频、生成的图都可以从这里传。</div>}
        </section>
      ) : null}
    </div>
  );
}

/** 附件类型的小图标（不引第三方图标库，纯字符）。 */
function kindIcon(kind: string): string {
  return kind === "video" ? "🎬" : kind === "image" ? "🖼" : kind === "audio" ? "🎵" : kind === "text" ? "📄" : "📦";
}
