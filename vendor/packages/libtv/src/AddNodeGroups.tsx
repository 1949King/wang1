/**
 * V4.41.19 AI 画布重组：左侧 sidebar「添加节点」5 大类分组渲染组件。
 * 业界共识「左=库按类别分块」—— 替代原 20+ 按钮平铺堆叠。
 *
 * 从 CanvasShell.tsx 拆出（规模守卫：CanvasShell 基线 3199 + 容差 30）。
 */
import type { PaletteItem } from "./NodePalette";

export type AddNodeGroup = {
  cat: string;
  title: string;
  icon: string;
  items: PaletteItem[];
};

export default function AddNodeGroups({
  groups,
  onPick,
}: {
  groups: AddNodeGroup[];
  onPick: (type: string) => void;
}) {
  return (
    <>
      {groups.map((g) => (
        <details key={g.cat} className="node-cat-group" open={g.cat === "create"}>
          <summary>
            <span className="node-cat-ico">{g.icon}</span>
            {g.title}
            <span className="node-cat-count">{g.items.length}</span>
          </summary>
          <div className="btn-row node-cat-items">
            {g.items.map((it) => (
              <button
                key={it.type}
                className="btn"
                draggable
                title={it.hint}
                onDragStart={(e) => {
                  e.dataTransfer.setData("application/shiguang-node", it.type);
                  e.dataTransfer.effectAllowed = "copy";
                }}
                onClick={() => onPick(it.type)}
              >
                {it.label}
              </button>
            ))}
          </div>
        </details>
      ))}
    </>
  );
}
