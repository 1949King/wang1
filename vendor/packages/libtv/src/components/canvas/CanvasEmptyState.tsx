/**
 * CanvasEmptyState — 画布空状态引导（tenney95 风格融合）
 *
 * 画布无节点时居中显示，提供快速预设工作流入口按钮。
 * 所有操作直接从 useCanvasStore 获取，无需外部 props 传递。
 */
import { memo } from "react";
import { useCanvasStore } from "../../store";

interface QuickCard {
  id: string;
  title: string;
  subtitle: string;
  icon: string;
  color: string;
  badge?: string;
  action: () => void;
}

function CanvasEmptyState() {
  const addNode = useCanvasStore((s) => s.addNode);
  const addThreeView = useCanvasStore((s) => s.addThreeView);
  const setStatus = useCanvasStore((s) => s.setStatus);

  const cards: QuickCard[] = [
    {
      id: "directorCard",
      title: "导演卡",
      subtitle: "粘剧本，一键拆解成分镜",
      icon: "🎬",
      color: "#c084fc",
      badge: "NEW",
      action: () => {
        addNode("directorCard");
        setStatus("已添加导演卡 · 粘贴剧本后点「自动拆解」");
      },
    },
    {
      id: "script",
      title: "故事脚本",
      subtitle: "添加剧本节点，可一键拉片",
      icon: "▣",
      color: "#22c55e",
      action: () => {
        addNode("script");
        setStatus("已添加剧本节点，可继续一键拉片");
      },
    },
    {
      id: "threeview",
      title: "角色三视图",
      subtitle: "正/侧/背 三视图分镜",
      icon: "☺",
      color: "#ef4444",
      action: () => {
        addThreeView();
      },
    },
    {
      id: "refvideo",
      title: "参考生视频",
      subtitle: "上传参考视频生成",
      icon: "〰",
      color: "#3b82f6",
      badge: "SD 2.5",
      action: () => {
        addNode("video");
        setStatus("已添加视频节点 · 可上传全能参考片段");
      },
    },
    {
      id: "audiovideo",
      title: "音频生视频",
      subtitle: "音频驱动视频生成",
      icon: "♫",
      color: "#a855f7",
      action: () => {
        addNode("audio");
        addNode("video", { x: 360, y: 160 });
        setStatus("已添加音频 + 视频节点（音频生视频工作流起点）");
      },
    },
    {
      id: "digitalHuman",
      title: "数字人",
      subtitle: "形象 + 台词配音入轨",
      icon: "🧑",
      color: "#38bdf8",
      badge: "NEW",
      action: () => {
        addNode("digitalHuman");
        setStatus("已添加数字人节点 · 填写台词生成配音，口型成片未接入");
      },
    },
    {
      id: "shot",
      title: "分镜/镜头",
      subtitle: "添加一个镜头节点",
      icon: "◇",
      color: "#f59e0b",
      action: () => {
        addNode("shot");
        setStatus("已添加镜头节点，可编辑提示词和机位");
      },
    },
    {
      id: "prompt",
      title: "提示词",
      subtitle: "添加提示词节点",
      icon: "✎",
      color: "#06b6d4",
      action: () => {
        addNode("prompt");
        setStatus("已添加提示词节点，可填写生成描述");
      },
    },
  ];

  return (
    <div className="canvas-empty-state">
      <div className="canvas-empty-state-inner">
        <div className="canvas-empty-state-logo">
          <span className="canvas-empty-state-icon">⟦⟧</span>
        </div>
        <div className="canvas-empty-state-text">
          <div className="canvas-empty-state-title">拾光导演台</div>
          <div className="canvas-empty-state-hint">
            双击画布空白处或按 <kbd>/</kbd> 搜索添加节点
          </div>
        </div>
        <div className="canvas-empty-state-cards">
          {cards.map((card) => (
            <button
              key={card.id}
              type="button"
              className="canvas-empty-state-card"
              onClick={card.action}
              title={card.subtitle}
            >
              <span className="canvas-empty-state-card-icon" style={{ color: card.color }}>
                {card.icon}
              </span>
              <span className="canvas-empty-state-card-title">{card.title}</span>
              {card.badge ? (
                <span className="canvas-empty-state-card-badge">{card.badge}</span>
              ) : null}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export default memo(CanvasEmptyState);