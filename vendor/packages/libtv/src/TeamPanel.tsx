/**
 * 团队协作面板（2026-10-31 · V4.49.1）
 *
 * 四段式，对应四个真实动作（不做"设置项博物馆"）：
 *   1. 本机服务 —— 我是不是那台"服务器"（启动/停止 + 显示同事该填的地址）
 *   2. 连接     —— 我是同事，扫描或手填地址后加入
 *   3. 项目     —— 上传当前画布 / 拉取 / 认领 / 交接
 *   4. 收件箱   —— 别人交接给我的，一键接手
 *
 * 纪律：
 *   · 拉取会覆盖当前画布 ⇒ **必须二次确认**（不静默覆盖用户正在做的事）
 *   · 冲突/锁 都显示后端给的原因（含"谁改的/谁占着"），不吞成"失败"
 */
import { useCallback, useEffect, useState } from "react";
import { useCanvasStore } from "./store";
import {
  TeamError,
  type DiscoveredServer,
  type TeamCred,
  type TeamHandoffItem,
  type TeamHostStatus,
  type TeamProject,
  teamAck,
  teamAddress,
  teamClaim,
  teamCreateProject,
  teamCred,
  teamDiscover,
  teamHandoff,
  teamHostStart,
  teamHostStatus,
  teamHostStop,
  teamInbox,
  teamJoin,
  teamLeave,
  teamListProjects,
  teamMembers,
  teamPull,
  teamPush,
  teamRelease,
} from "./teamClient";
import "./teamPanel.css";

type Member = { id: string; name: string; role: string };

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
      fail(e);
    } finally {
      setBusy("");
    }
  };

  const uploadCurrent = async () => {
    setBusy("upload");
    try {
      const bundle = useCanvasStore.getState().getProjectBundle();
      const title = bundle.dramaTitle || "未命名画布";
      const res = await teamCreateProject(title, bundle);
      say("ok", `已上传为「${title}」（rev ${res.rev}）`);
      setSelected(res.project_id);
      await refreshTeam();
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  };

  const pushTo = async (projectId: string) => {
    const p = projects.find((x) => x.project_id === projectId);
    if (!p) return;
    setBusy("push");
    try {
      const bundle = useCanvasStore.getState().getProjectBundle();
      const res = await teamPush(projectId, bundle, p.rev, note || "更新画布");
      say("ok", `已上传到「${p.name}」→ rev ${res.rev}`);
      await refreshTeam();
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  };

  const pullFrom = async (projectId: string) => {
    const p = projects.find((x) => x.project_id === projectId);
    if (!p) return;
    if (!window.confirm(`拉取「${p.name}」会覆盖当前画布，继续？`)) return;
    setBusy("pull");
    try {
      const data = await teamPull(projectId);
      const b = data.bundle as { nodes?: unknown[]; edges?: unknown[]; dramaTitle?: string; episode?: string; stage3d?: unknown };
      useCanvasStore.getState().loadProjectBundle({
        nodes: (b.nodes as never[]) || [],
        edges: (b.edges as never[]) || [],
        dramaTitle: b.dramaTitle || p.name,
        episode: b.episode,
        stage3d: b.stage3d,
      });
      say("ok", `已拉取「${p.name}」rev ${data.rev}`);
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
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
      const b = data.bundle as { nodes?: never[]; edges?: never[]; dramaTitle?: string; episode?: string; stage3d?: unknown };
      useCanvasStore.getState().loadProjectBundle({
        nodes: b.nodes || [],
        edges: b.edges || [],
        dramaTitle: b.dramaTitle || item.project_name,
        episode: b.episode,
        stage3d: b.stage3d,
      });
      await teamClaim(item.project_id);
      say("ok", `已接手「${p?.name || item.project_name}」`);
      await refreshTeam();
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  };

  const selectedProject = projects.find((p) => p.project_id === selected);

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
    </div>
  );
}
