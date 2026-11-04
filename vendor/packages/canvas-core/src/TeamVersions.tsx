/**
 * 历史版本列表（2026-11-04 · 画布 0.3.48）
 *
 * 解决的问题：服务器一直在存历史版本、也在存每版的备注，但**前端从来没有把它们
 * 显示出来过** —— 于是「版本命名」等于往黑箱里写字，「改错了能不能救回来」等于
 * 全凭运气。这个组件只做一件事：把已有的东西摆出来，并给两个动作。
 *
 * 两个动作的分工必须一眼看懂，所以文案不省：
 *   · 「拉这一版」  = 只影响我本地，不动服务器，最安全
 *   · 「覆盖最新版」= 让全组都变成这一版（服务端记成新的一版，历史不删）
 *
 * 回滚的确认框里要说清「不会删掉别人的版本」—— 不然没人敢按。
 */
import type { TeamVersion } from "./teamClient";

export type TeamVersionsProps = {
  versions: TeamVersion[];
  loading: boolean;
  /** 当前项目在服务器上的最新 rev（＝列表第一版的 rev） */
  latestRev: number;
  onLoadRev: (rev: number) => void;
  onRollback: (rev: number) => void;
};

const pad2 = (n: number) => String(n).padStart(2, "0");

/** 服务器时间戳（秒）→ 「11-04 15:20」。本地时区，跟用户手表一致。 */
export function versionStamp(sec: number): string {
  const d = new Date((Number(sec) || 0) * 1000);
  if (!Number.isFinite(d.getTime()) || d.getTime() <= 0) return "—";
  return `${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}

export function versionBytes(n: number): string {
  const v = Number(n) || 0;
  if (v >= 1048576) return `${(v / 1048576).toFixed(1)}MB`;
  if (v >= 1024) return `${Math.round(v / 1024)}KB`;
  return `${v}B`;
}

export function TeamVersions({ versions, loading, latestRev, onLoadRev, onRollback }: TeamVersionsProps) {
  if (loading) return <div className="sg-team-dim">正在读历史版本…</div>;
  if (!versions.length) return <div className="sg-team-dim">还没有版本记录</div>;
  return (
    <div className="sg-team-vers">
      <div className="sg-team-dim">
        共 {versions.length} 版。「拉这一版」只改你本机；「覆盖最新版」会让全组都变成这一版
        —— 它不删任何历史，只是又提交了一版。
      </div>
      {versions.map((v) => {
        const isLatest = v.rev === latestRev;
        return (
          <div className="sg-team-ver" key={v.rev}>
            <div className="sg-team-ver-head">
              <b>rev {v.rev}</b>
              {isLatest ? <span className="sg-team-ver-now">最新</span> : null}
              <span className="sg-team-dim">
                {v.author || "?"} · {versionStamp(v.created_at)} · {versionBytes(v.bytes)}
              </span>
            </div>
            <div className="sg-team-ver-note">{v.message || "（这一版没写备注）"}</div>
            <div className="sg-team-item-actions">
              <button type="button" onClick={() => onLoadRev(v.rev)}>拉这一版</button>
              {isLatest ? null : (
                <button type="button" onClick={() => onRollback(v.rev)}>覆盖最新版</button>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
