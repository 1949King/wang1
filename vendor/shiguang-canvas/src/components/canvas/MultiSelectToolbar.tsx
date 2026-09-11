/**
 * MultiSelectToolbar — 多选工具栏（tenney95 风格融合）
 *
 * 选中 ≥2 个节点时悬浮在选中区域上方，支持：
 * - 批量生成（onGenerate）
 * - 复制节点
 * - 6 种对齐（左/中/右/上/中/下）
 * - 2 种分布（横/纵）
 */
import { memo, useMemo, useCallback, useState } from "react";
import { useCanvasStore } from "../../store";

type AlignKey = "left" | "center" | "right" | "top" | "middle" | "bottom";
type DistributeKey = "distribute-h" | "distribute-v";

interface ActionItem {
  icon: string;
  label: string;
  key: AlignKey | DistributeKey;
}

const ALIGN_ACTIONS: ActionItem[] = [
  { icon: "◀◀", label: "左对齐", key: "left" },
  { icon: "◀▶", label: "水平居中", key: "center" },
  { icon: "▶▶", label: "右对齐", key: "right" },
  { icon: "▲▲", label: "顶对齐", key: "top" },
  { icon: "▲▼", label: "垂直居中", key: "middle" },
  { icon: "▼▼", label: "底对齐", key: "bottom" },
];

const DISTRIBUTE_ACTIONS: ActionItem[] = [
  { icon: "⇔", label: "横向平均分布", key: "distribute-h" },
  { icon: "⇕", label: "纵向平均分布", key: "distribute-v" },
];

interface Props {
  onGenerate?: () => void;
}

function MultiSelectToolbar({ onGenerate }: Props) {
  const selectedId = useCanvasStore((s) => s.selectedId);
  const nodes = useCanvasStore((s) => s.nodes);
  const alignSelected = useCanvasStore((s) => s.alignSelected);
  const copySelected = useCanvasStore((s) => s.copySelected);
  const setStatus = useCanvasStore((s) => s.setStatus);

  // 选中节点（包括 selected 标记和 selectedId）
  const selectedNodeIds = useMemo(() => {
    const ids = new Set(nodes.filter((n) => n.selected).map((n) => n.id));
    if (selectedId) ids.add(selectedId);
    return ids;
  }, [nodes, selectedId]);

  const selectedCount = selectedNodeIds.size;
  const [batchRunning, setBatchRunning] = useState(false);

  // 计算工具栏位置（选中区域上方居中）
  const toolbarPos = useMemo(() => {
    if (selectedCount < 2) return null;
    const sel = nodes.filter((n) => selectedNodeIds.has(n.id));
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const node of sel) {
      const w = node.measured?.width || 180;
      const h = node.measured?.height || 120;
      if (node.position.x < minX) minX = node.position.x;
      if (node.position.y < minY) minY = node.position.y;
      if (node.position.x + w > maxX) maxX = node.position.x + w;
      if (node.position.y + h > maxY) maxY = node.position.y + h;
    }
    // 转换为屏幕坐标
    const centerX = (minX + maxX) / 2;
    return { x: centerX, y: minY };
  }, [selectedNodeIds, selectedCount, nodes]);

  // 批量生成
  const handleBatchGenerate = useCallback(() => {
    if (onGenerate) {
      onGenerate();
      setStatus(`批量生成 ${selectedCount} 个节点`);
    } else {
      setStatus("请先关联生成回调");
    }
  }, [onGenerate, selectedCount, setStatus]);

  // 复制
  const handleCopy = useCallback(() => {
    copySelected();
    setStatus(`已复制 ${selectedCount} 个节点`);
  }, [copySelected, selectedCount, setStatus]);

  if (selectedCount < 2 || !toolbarPos) return null;

  return (
    <div
      className="multi-select-toolbar"
      style={{
        left: toolbarPos.x,
        top: toolbarPos.y,
      }}
    >
      {/* 批量生成 */}
      <button
        type="button"
        className="multi-select-btn multi-select-btn-primary"
        title="批量生成"
        disabled={batchRunning}
        onClick={handleBatchGenerate}
      >
        ▶ {batchRunning ? "…" : ""}
      </button>

      <div className="multi-select-sep" />

      {/* 复制 */}
      <button
        type="button"
        className="multi-select-btn"
        title="复制节点"
        onClick={handleCopy}
      >
        ⧉
      </button>

      <div className="multi-select-sep" />

      {/* 对齐 */}
      {ALIGN_ACTIONS.map((act) => (
        <button
          key={act.key}
          type="button"
          className="multi-select-btn"
          title={act.label}
          onClick={() => {
            alignSelected(act.key as AlignKey);
            setStatus(act.label);
          }}
        >
          {act.icon}
        </button>
      ))}

      {/* 分布（需要 ≥3 节点） */}
      {selectedCount >= 3 && (
        <>
          <div className="multi-select-sep" />
          {DISTRIBUTE_ACTIONS.map((act) => (
            <button
              key={act.key}
              type="button"
              className="multi-select-btn"
              title={act.label}
              onClick={() => {
                alignSelected(act.key as DistributeKey);
                setStatus(act.label);
              }}
            >
              {act.icon}
            </button>
          ))}
        </>
      )}
    </div>
  );
}

export default memo(MultiSelectToolbar);