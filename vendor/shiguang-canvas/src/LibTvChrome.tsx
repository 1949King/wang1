/**
 * LibTV 空画布四卡 + 底栏（图一）。
 */
import type { NodeData } from "./store";

export type EmptyCardId = "script" | "threeview" | "refvideo" | "audiovideo";

const CARDS: {
  id: EmptyCardId;
  title: string;
  badge?: string;
  tone: string;
  icon: string;
}[] = [
  { id: "script", title: "故事脚本生成", tone: "#22c55e", icon: "▣" },
  { id: "threeview", title: "角色三视图", tone: "#ef4444", icon: "☺" },
  { id: "refvideo", title: "全能参考生视频", badge: "SD 2.5", tone: "#3b82f6", icon: "〰" },
  { id: "audiovideo", title: "音频生视频", badge: "SD 2.5", tone: "#a855f7", icon: "♫" },
];

export function LibTvEmptyState({
  onCard,
}: {
  onCard: (id: EmptyCardId) => void;
}) {
  return (
    <div className="libtv-empty">
      <div className="libtv-empty-hint">
        <span className="libtv-wand">✧</span>
        双击画布 自由生成节点
      </div>
      <div className="libtv-empty-cards">
        {CARDS.map((c) => (
          <button
            key={c.id}
            type="button"
            className="libtv-empty-card"
            onClick={() => onCard(c.id)}
          >
            <span className="libtv-empty-ico" style={{ color: c.tone }}>
              {c.icon}
            </span>
            <span className="libtv-empty-label">{c.title}</span>
            {c.badge ? <span className="libtv-badge">{c.badge}</span> : null}
          </button>
        ))}
      </div>
    </div>
  );
}

export function LibTvBottomDock({
  zoomPct,
  onAdd,
  onAssets,
  onZoomFit,
  onHelp,
  onRole,
  onConnect,
  onSend,
  onShare,
  onBranch,
  onPreview,
  onHistory,
  onGallery,
}: {
  zoomPct: number;
  onAdd: () => void;
  onAssets: () => void;
  onZoomFit: () => void;
  onHelp: () => void;
  onRole: () => void;
  onConnect: () => void;
  onSend: () => void;
  onShare: () => void;
  onBranch: () => void;
  onPreview: () => void;
  onHistory: () => void;
  onGallery: () => void;
}) {
  return (
    <div className="libtv-dock">
      <div className="libtv-dock-left">
        <button type="button" className="libtv-dock-text" onClick={onAssets}>
          📁 资产管理
        </button>
        <button type="button" className="libtv-dock-ico" title="宫格" onClick={onZoomFit}>
          ▦
        </button>
        <button type="button" className="libtv-dock-ico" title="角色三视图" onClick={onRole}>
          ☺
        </button>
        <button type="button" className="libtv-dock-ico" title="自动连线" onClick={onConnect}>
          ⚭
        </button>
        <button type="button" className="libtv-dock-ico" title="聚焦全部" onClick={onZoomFit}>
          ◎
        </button>
        <span className="libtv-dock-zoom">{zoomPct}%</span>
      </div>
      <div className="libtv-dock-center">
        <button type="button" className="libtv-dock-plus" onClick={onAdd} title="添加节点">
          +
        </button>
        <button type="button" className="libtv-dock-ico" title="发送到剪辑" onClick={onSend}>
          ✈
        </button>
        <button type="button" className="libtv-dock-ico" title="分享 JSON" onClick={onShare}>
          ⤴
        </button>
        <button type="button" className="libtv-dock-ico" title="从选中分支" onClick={onBranch}>
          ⎇
        </button>
        <button type="button" className="libtv-dock-ico" title="预览" onClick={onPreview}>
          ⌕
        </button>
        <button type="button" className="libtv-dock-ico" title="历史" onClick={onHistory}>
          ⏱
        </button>
        <button type="button" className="libtv-dock-ico" title="图库" onClick={onGallery}>
          ▤
        </button>
        <button type="button" className="libtv-dock-ico" title="快捷键帮助" onClick={onHelp}>
          ?
        </button>
      </div>
    </div>
  );
}

/** 右键菜单：添加节点 / 添加资源（图二） */
export type CtxPaneAction =
  | { type: "node"; kind: NodeData["kind"] }
  | { type: "stage3d" }
  | { type: "breakdown" }
  | { type: "smart_edit" }
  | { type: "upload" }
  | { type: "history" }
  | { type: "assets" }
  | { type: "palette" }
  | { type: "paste" };

export function LibTvPaneContextMenu({
  onAction,
}: {
  onAction: (a: CtxPaneAction) => void;
}) {
  return (
    <>
      <div className="ctx-menu-title">添加节点</div>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "node", kind: "prompt" })}>
        <span className="ctx-ico">☰</span> 文本
      </button>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "node", kind: "image" })}>
        <span className="ctx-ico">🖼</span> 图片
      </button>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "node", kind: "video" })}>
        <span className="ctx-ico">▶</span> 视频
      </button>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "smart_edit" })}>
        <span className="ctx-ico">✂</span> 智能剪辑 <span className="badge-beta">Beta</span>
      </button>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "node", kind: "director" })}>
        <span className="ctx-ico">🎥</span> 3D 导演台节点 <span className="badge-new">NEW</span>
      </button>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "node", kind: "digitalHuman" })}>
        <span className="ctx-ico">🧑</span> 数字人 <span className="badge-new">NEW</span>
      </button>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "stage3d" })}>
        <span className="ctx-ico">▦</span> 打开导演台页
      </button>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "node", kind: "animation" })}>
        <span className="ctx-ico">🎞️</span> 逐帧动画
      </button>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "node", kind: "panorama" })}>
        <span className="ctx-ico">🌐</span> 全景
      </button>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "node", kind: "note" })}>
        <span className="ctx-ico">📌</span> 画布笔记
      </button>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "node", kind: "source" })}>
        <span className="ctx-ico">📂</span> 源文件
      </button>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "breakdown" })}>
        <span className="ctx-ico">🎞</span> 逐帧拉片 <span className="libtv-badge">SD 2.5</span>
      </button>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "node", kind: "audio" })}>
        <span className="ctx-ico">▮</span> 音频
      </button>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "node", kind: "script" })}>
        <span className="ctx-ico">📄</span> 脚本 <span className="ctx-chev">›</span>
      </button>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "assets" })}>
        <span className="ctx-ico">◇</span> 素材库 <span className="ctx-chev">›</span>
      </button>
      <div className="ctx-menu-sep" />
      <div className="ctx-menu-title">添加资源</div>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "upload" })}>
        <span className="ctx-ico">⬆</span> 上传
      </button>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "history" })}>
        <span className="ctx-ico">↩</span> 从生成历史选择
      </button>
      <div className="ctx-menu-sep" />
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "palette" })}>
        搜索添加…
      </button>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "paste" })}>
        粘贴
      </button>
    </>
  );
}
