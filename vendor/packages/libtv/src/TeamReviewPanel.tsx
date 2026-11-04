/**
 * 评审意见段（2026-11-04 · 画布 0.3.52）
 *
 * 面板到此为止解决了「传」，这一版补「说」。设计协作的循环是
 * 做 → 给人看 → 收意见 → 改，以前最后两步只能走微信（截图圈红框）。
 *
 * 三条界面纪律，都是踩过的：
 *   · **默认只看待处理**。未解决和已解决混在一屏，人会一直翻旧账最后不看了；
 *   · **提意见不强制选节点**。「整体色调偏冷」本来就针对整份画布，逼人先选一个
 *     节点会把最正常的一类意见挡掉；
 *   · **定位按钮不是「跳到第几版」**，是「选中那个节点」—— 选中就够，画布会高亮。
 *     自己算坐标去居中会在缩放/旋转下算错，而画布本来就有选中态。
 */
import { useCallback, useEffect, useState } from "react";

import {
  TeamError,
  type TeamComment,
  teamAddComment,
  teamComments,
  teamResolveComment,
} from "./teamClient";
import { agoText, anchorText, composeTarget, groupComments, revText } from "./teamReview";

type Props = {
  projectId: string;
  /** 当前项目名（为空时不显示这一段 —— 没选项目谈不上评审） */
  projectName: string;
  /** 有编辑权才能「标为已解决」；viewer 只能提 */
  canWrite: boolean;
  /** 画布当前选中的节点 id；提意见时挂在它上面 */
  selectedId: string | null;
  /** 选中节点的显示名（「镜 03」），没有就说「选中这一处」 */
  selectedLabel?: string;
  /** 点「定位」时把节点选中 */
  onLocate: (nodeId: string) => void;
  say: (kind: "ok" | "err" | "info", text: string) => void;
  fail: (e: unknown) => void;
};

const BODY_MAX = 2000;

export function TeamReview({
  projectId, projectName, canWrite, selectedId, selectedLabel, onLocate, say, fail,
}: Props) {
  const [list, setList] = useState<TeamComment[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [nowSec, setNowSec] = useState(() => Math.floor(Date.now() / 1000));

  const target = composeTarget(selectedId, selectedLabel);

  const load = useCallback(async () => {
    if (!projectId) {
      setList([]);
      return;
    }
    try {
      setList(await teamComments(projectId));
    } catch (e) {
      // 读失败不清空已有列表：网络抖一下不该让一屏意见突然消失
      fail(e);
    }
  }, [projectId, fail]);

  useEffect(() => {
    void load();
  }, [load]);

  // 相对时间每 30 秒刷新一次就够（没人盯着「几秒前」看），别跟着渲染跑
  useEffect(() => {
    const id = window.setInterval(() => setNowSec(Math.floor(Date.now() / 1000)), 30000);
    return () => window.clearInterval(id);
  }, []);

  const submit = async () => {
    const body = draft.trim();
    if (!body) {
      say("err", "先写一句要改什么 —— 空意见同事不知道动哪儿");
      return;
    }
    setBusy("add");
    try {
      const c = await teamAddComment(projectId, body.slice(0, BODY_MAX), target.nodeId, 0);
      setList((prev) => [...prev, c]);
      setDraft("");
      say("ok", `已提给「${anchorText(c, target.nodeId ? target.label : "")}」`);
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  };

  const toggle = async (c: TeamComment) => {
    setBusy(c.id);
    try {
      const next = await teamResolveComment(projectId, c.id, !c.resolved);
      setList((prev) => prev.map((x) => (x.id === next.id ? next : x)));
    } catch (e) {
      if (e instanceof TeamError && e.code === "forbidden") {
        say("err", "你是查看者，不能替人标「已解决」—— 让编辑者来点");
      } else {
        fail(e);
      }
    } finally {
      setBusy("");
    }
  };

  if (!projectId) {
    return (
      <section className="sg-team-sec">
        <h4>⑥ 评审意见</h4>
        <span className="sg-team-dim">先在 ③ 里选一个项目，再提意见</span>
      </section>
    );
  }

  const { open, done } = groupComments(list);
  const shown = showAll ? list : open;

  return (
    <section className="sg-team-sec">
      <h4>⑥ 评审意见 · {projectName || "当前项目"}</h4>

      <div className="sg-team-row">
        <textarea
          className="sg-team-note"
          value={draft}
          onChange={(e) => setDraft(e.target.value.slice(0, BODY_MAX))}
          placeholder={`要改什么？会挂在「${target.label}」上`}
          rows={2}
          spellCheck={false}
        />
      </div>
      <div className="sg-team-row">
        <button type="button" disabled={busy === "add" || !draft.trim()} onClick={() => void submit()}>
          {busy === "add" ? "提交中…" : `提给「${target.label}」`}
        </button>
        <button type="button" onClick={() => void load()}>刷新</button>
        <span className="sg-team-dim">
          {open.length ? `${open.length} 条待处理` : "没有待处理意见"}
          {done.length ? ` · ${done.length} 条已解决` : ""}
        </span>
      </div>

      <div className="sg-team-row">
        <button type="button" className={showAll ? "" : "on"} onClick={() => setShowAll(false)}>
          待处理 {open.length}
        </button>
        <button type="button" className={showAll ? "on" : ""} onClick={() => setShowAll(true)}>
          全部 {list.length}
        </button>
      </div>

      {shown.length ? (
        <div className="sg-team-list">
          {shown.map((c) => (
            <div key={c.id} className={`sg-team-cmt${c.resolved ? " done" : ""}`}>
              <div className="sg-team-cmt-head">
                <b>{c.author || "同事"}</b>
                <span className="sg-team-dim">{anchorText(c, c.node_id ? selectedLabel : "")}</span>
                {c.rev > 0 ? <span className="sg-team-dim">{revText(c)}</span> : null}
                <span className="sg-team-dim">{agoText(c.created_at, nowSec)}</span>
                {c.resolved ? <span className="sg-team-cmt-ok">已解决</span> : null}
              </div>
              <div className="sg-team-cmt-body">{c.body}</div>
              <div className="sg-team-cmt-acts">
                {c.node_id ? (
                  <button type="button" onClick={() => onLocate(c.node_id)}>定位</button>
                ) : null}
                {canWrite ? (
                  <button type="button" disabled={busy === c.id} onClick={() => void toggle(c)}>
                    {c.resolved ? "重新打开" : "标为已解决"}
                  </button>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <span className="sg-team-dim">
          {list.length ? "待处理都清完了 —— 切到「全部」看已解决的" : "还没有人提意见"}
        </span>
      )}
    </section>
  );
}
