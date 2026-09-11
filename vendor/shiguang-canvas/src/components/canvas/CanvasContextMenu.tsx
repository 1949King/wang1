/**
 * CanvasContextMenu — 画布右键菜单（tenney95 风格移植）
 *
 * 四种模式：pane（空白）/ node / edge / connect（连线松手接到新节点）
 * 特性：屏幕边界自动修正、子菜单展开、快捷键提示、从自研 useCanvasStore 直取方法
 */
import { memo, useCallback, useLayoutEffect, useRef, useState } from "react";
import { useCanvasStore, type NodeData } from "../../store";
import { importComfyWorkflowText } from "../../bridge";
import { calcFixedPosition, calcSubmenuPosition } from "../../utils/popupPosition";

const IS_MAC =
  typeof navigator !== "undefined" && /Macintosh|Mac OS X/.test(navigator.userAgent);
const KBD = {
  copy: IS_MAC ? "⌘ C" : "Ctrl C",
  paste: IS_MAC ? "⌘ V" : "Ctrl V",
  undo: IS_MAC ? "⌘ Z" : "Ctrl Z",
  redo: IS_MAC ? "⇧⌘ Z" : "Ctrl Y",
  delete: IS_MAC ? "⌫" : "Del",
  dup: IS_MAC ? "⌘ D" : "Ctrl D",
  fit: "F",
  selectAll: IS_MAC ? "⌘ A" : "Ctrl A",
};

interface AddNodeItem {
  label: string;
  kind: NodeData["kind"];
  group: "content" | "source";
  shortcut?: string;
}

/** 自研画布内置节点（对齐 BUILTIN_NODE_KINDS） */
const ADD_NODE_ITEMS: AddNodeItem[] = [
  { label: "剧本", kind: "script", group: "content", shortcut: "1" },
  { label: "分镜/镜头", kind: "shot", group: "content", shortcut: "2" },
  { label: "提示词", kind: "prompt", group: "content", shortcut: "3" },
  { label: "配置", kind: "config", group: "content", shortcut: "4" },
  { label: "生成器", kind: "generator", group: "content", shortcut: "5" },
  { label: "文本", kind: "text", group: "content", shortcut: "6" },
  { label: "Markdown", kind: "markdown", group: "content", shortcut: "7" },
  { label: "图像", kind: "image", group: "source", shortcut: IS_MAC ? "⌥ 1" : "Alt 1" },
  { label: "视频", kind: "video", group: "source", shortcut: IS_MAC ? "⌥ 2" : "Alt 2" },
  { label: "音频", kind: "audio", group: "source", shortcut: IS_MAC ? "⌥ 3" : "Alt 3" },
  { label: "音乐", kind: "music", group: "source", shortcut: IS_MAC ? "⌥ 4" : "Alt 4" },
  { label: "分镜表", kind: "shotlist", group: "source", shortcut: IS_MAC ? "⌥ 5" : "Alt 5" },
  { label: "3D 导演台", kind: "director", group: "source", shortcut: IS_MAC ? "⌥ 6" : "Alt 6" },
  { label: "数字人", kind: "digitalHuman", group: "source" },
  { label: "动画", kind: "animation", group: "source" },
  { label: "360 全景", kind: "panorama", group: "source" },
  { label: "便签", kind: "note", group: "source" },
];

type CtxMode = "pane" | "node" | "edge" | "connect";

export interface CtxMenuState {
  mode: CtxMode;
  clientX: number;
  clientY: number;
  flow?: { x: number; y: number };
  nodeId?: string;
  edgeId?: string;
  sourceId?: string;
  sourceHandle?: string;
}

interface Props {
  menu: CtxMenuState;
  onClose: () => void;
  onOpenStage3d: () => void;
  onBreakdown: () => void;
}

/** 菜单项行高估算 */
const ROW_H = 28;
const MENU_PAD = 10;
function estH(rows: number, seps = 0) {
  return rows * ROW_H + seps * 8 + MENU_PAD;
}
function estW() {
  return 200;
}

/**
 * CanvasContextMenu 主组件
 *
 * 所有 handler 从 useCanvasStore 直取（addNode / removeSelected / undoGraph ...）
 * 只接收 onClose / onOpenStage3d / onBreakdown 三个外部回调
 */
export default function CanvasContextMenu({ menu, onClose, onOpenStage3d, onBreakdown }: Props) {
  const menuRef = useRef<HTMLDivElement | null>(null);
  const subRef = useRef<HTMLDivElement | null>(null);
  const [hoverSub, setHoverSub] = useState<boolean>(false);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  const [subPos, setSubPos] = useState<{ left: number; top: number } | null>(null);

  // —— 从 store 直取所有操作 ——
  const selectedNodes = useCanvasStore((s) => s.nodes.filter((n) => n.selected));
  const selectedId = useCanvasStore((s) => s.selectedId);
  const addNode = useCanvasStore((s) => s.addNode);
  const onConnect = useCanvasStore((s) => s.onConnect);
  const removeSelected = useCanvasStore((s) => s.removeSelected);
  const copySelected = useCanvasStore((s) => s.copySelected);
  const pasteClipboard = useCanvasStore((s) => s.pasteClipboard);
  const duplicateSelected = useCanvasStore((s) => s.duplicateSelected);
  const undoGraph = useCanvasStore((s) => s.undoGraph);
  const redoGraph = useCanvasStore((s) => s.redoGraph);
  const deleteEdge = useCanvasStore((s) => s.deleteEdge);
  const selectAll = useCanvasStore((s) => s.selectAll);
  const setStatus = useCanvasStore((s) => s.setStatus);

  const hasSelection = selectedNodes.length > 0 || Boolean(selectedId);

  // —— 计算菜单安全位置（避免超出屏幕边界）——
  useLayoutEffect(() => {
    const el = menuRef.current;
    if (!el) return;

    const rect = el.getBoundingClientRect();
    const safe = calcFixedPosition(
      menu.clientX,
      menu.clientY,
      rect.width || estW(),
      rect.height || estH(8, 3),
    );
    setPos(safe);

    if (hoverSub) {
      const subEl = subRef.current;
      const subRect = subEl?.getBoundingClientRect();
      const sp = calcSubmenuPosition(
        rect,
        subRect?.width ?? estW(),
        subRect?.height ?? estH(ADD_NODE_ITEMS.length, 1),
        "right",
      );
      setSubPos({ left: sp.left, top: sp.top });
    }
  }, [menu, hoverSub, hasSelection]);

  const handleAddNode = useCallback(
    (kind: NodeData["kind"]) => {
      const flow = menu.flow;
      const newId = addNode(kind, flow);
      if (menu.mode === "connect" && menu.sourceId && newId) {
        onConnect({
          source: menu.sourceId,
          target: newId,
          sourceHandle: menu.sourceHandle || null,
          targetHandle: null,
        });
        setStatus(`已连接并添加「${kind}」节点`);
      } else {
        setStatus(`已添加「${kind}」节点`);
      }
      onClose();
    },
    [menu, addNode, onConnect, setStatus, onClose],
  );

  // 导入 ComfyUI 工作流：弹输入框粘贴 JSON → dry-run 解析 → 状态反馈；引擎未安装时弹诊断
  const handleImportComfyWorkflow = useCallback(async () => {
    const text = window.prompt("请粘贴 ComfyUI 工作流 JSON（复制后 Ctrl+V 到此处）");
    if (text == null) return; // 用户取消
    const outcome = await importComfyWorkflowText(text);
    setStatus(outcome.message);
    if (outcome.engineMissing && outcome.detail) {
      window.alert(`ComfyUI 引擎未安装\n\n${outcome.detail}`);
    }
    onClose();
  }, [setStatus, onClose]);

  if (!menu) return null;
  if (!pos) return null;

  return (
    <>
      {/* Level 1: 主菜单 */}
      <div
        ref={menuRef}
        className="canvas-ctx-menu"
        style={{ left: pos.left, top: pos.top }}
        onClick={(e) => e.stopPropagation()}
        onContextMenu={(e) => e.preventDefault()}
      >
        {menu.mode === "pane" && (
          <PaneMenuContent
            hasSelection={hasSelection}
            hoverSub={hoverSub}
            onEnterSub={() => setHoverSub(true)}
            onLeaveSub={() => setHoverSub(false)}
            onAddNode={handleAddNode}
            onUndo={() => { undoGraph(); onClose(); }}
            onRedo={() => { redoGraph(); onClose(); }}
            onCopy={() => { copySelected(); onClose(); }}
            onPaste={() => { pasteClipboard(menu.flow); onClose(); }}
            onDelete={() => { removeSelected(); onClose(); }}
            onDup={() => { duplicateSelected(); onClose(); }}
            onSelectAll={() => { selectAll(); onClose(); }}
            onOpenStage3d={() => { onOpenStage3d(); onClose(); }}
            onBreakdown={() => { onBreakdown(); onClose(); }}
            onImportComfyWorkflow={handleImportComfyWorkflow}
          />
        )}
        {menu.mode === "node" && (
          <NodeMenuContent
            onCopy={() => { copySelected(); onClose(); }}
            onDup={() => { duplicateSelected(); onClose(); }}
            onDelete={() => { removeSelected(); onClose(); }}
            onAddNode={handleAddNode}
          />
        )}
        {menu.mode === "connect" && (
          <ConnectMenuContent onAddNode={handleAddNode} />
        )}
        {menu.mode === "edge" && (
          <EdgeMenuContent
            onDelete={() => { if (menu.edgeId) deleteEdge(menu.edgeId); onClose(); }}
          />
        )}
      </div>

      {/* 子菜单：添加节点（仅 pane 模式下 hover 时显示） */}
      {menu.mode === "pane" && hoverSub && subPos && (
        <div
          ref={subRef}
          className="canvas-ctx-menu canvas-ctx-submenu"
          style={{ left: subPos.left, top: subPos.top }}
          onMouseEnter={() => setHoverSub(true)}
          onMouseLeave={() => setHoverSub(false)}
          onClick={(e) => e.stopPropagation()}
        >
          {ADD_NODE_ITEMS.map((item, i) => (
            <div key={`${item.kind}-${i}`}>
              {i === 7 && <div className="ctx-menu-sep" />}
              <button
                type="button"
                className="ctx-menu-row ctx-menu-row-split"
                onClick={() => handleAddNode(item.kind)}
              >
                <span>{item.label}</span>
                {item.shortcut && <span className="ctx-menu-kbd">{item.shortcut}</span>}
              </button>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

// ——— 子组件：pane / node / edge 三种菜单内容 ———

function PaneMenuContent(props: {
  hasSelection: boolean;
  hoverSub: boolean;
  onEnterSub: () => void;
  onLeaveSub: () => void;
  onAddNode: (kind: NodeData["kind"]) => void;
  onUndo: () => void;
  onRedo: () => void;
  onCopy: () => void;
  onPaste: () => void;
  onDelete: () => void;
  onDup: () => void;
  onSelectAll: () => void;
  onOpenStage3d: () => void;
  onBreakdown: () => void;
  onImportComfyWorkflow: () => void;
}) {
  return (
    <>
      <button
        type="button"
        className={`ctx-menu-row ctx-menu-row-split${props.hoverSub ? " highlight" : ""}`}
        onMouseEnter={props.onEnterSub}
        onMouseLeave={props.onLeaveSub}
        onClick={props.onEnterSub}
      >
        <span>添加节点</span>
        <span className="ctx-menu-arrow">▶</span>
      </button>
      <div className="ctx-menu-sep" />
      {props.hasSelection && (
        <button type="button" className="ctx-menu-row ctx-menu-row-split" onClick={props.onCopy}>
          <span>复制</span>
          <span className="ctx-menu-kbd">{KBD.copy}</span>
        </button>
      )}
      <button type="button" className="ctx-menu-row ctx-menu-row-split" onClick={props.onPaste}>
        <span>粘贴</span>
        <span className="ctx-menu-kbd">{KBD.paste}</span>
      </button>
      {props.hasSelection && (
        <button type="button" className="ctx-menu-row ctx-menu-row-split" onClick={props.onDup}>
          <span>原地复制</span>
          <span className="ctx-menu-kbd">{KBD.dup}</span>
        </button>
      )}
      <button type="button" className="ctx-menu-row ctx-menu-row-split" onClick={props.onUndo}>
        <span>撤销</span>
        <span className="ctx-menu-kbd">{KBD.undo}</span>
      </button>
      <button type="button" className="ctx-menu-row ctx-menu-row-split" onClick={props.onRedo}>
        <span>重做</span>
        <span className="ctx-menu-kbd">{KBD.redo}</span>
      </button>
      <div className="ctx-menu-sep" />
      <button type="button" className="ctx-menu-row" onClick={props.onSelectAll}>
        <span>全选</span>
        <span className="ctx-menu-kbd">{KBD.selectAll}</span>
      </button>
      <button type="button" className="ctx-menu-row" onClick={props.onBreakdown}>
        <span>一键拉片</span>
      </button>
      <button type="button" className="ctx-menu-row" onClick={props.onImportComfyWorkflow}>
        <span>导入 ComfyUI 工作流</span>
      </button>
      <button type="button" className="ctx-menu-row" onClick={props.onOpenStage3d}>
        <span>打开 3D 导演台</span>
      </button>
      {props.hasSelection && (
        <>
          <div className="ctx-menu-sep" />
          <button
            type="button"
            className="ctx-menu-row ctx-menu-row-split ctx-menu-danger"
            onClick={props.onDelete}
          >
            <span>删除</span>
            <span className="ctx-menu-kbd">{KBD.delete}</span>
          </button>
        </>
      )}
    </>
  );
}

function NodeMenuContent(props: {
  onCopy: () => void;
  onDup: () => void;
  onDelete: () => void;
  onAddNode: (kind: NodeData["kind"]) => void;
}) {
  const [hoverSub, setHoverSub] = useState(false);
  const subRef = useRef<HTMLDivElement | null>(null);
  const [subPos, setSubPos] = useState<{ left: number; top: number } | null>(null);

  useLayoutEffect(() => {
    if (!hoverSub || !subRef.current) return;
    const main = subRef.current.parentElement?.getBoundingClientRect();
    const sb = subRef.current.getBoundingClientRect();
    if (!main) return;
    const sp = calcSubmenuPosition(main, sb.width || estW(), sb.height || estH(ADD_NODE_ITEMS.length, 1), "right");
    setSubPos({ left: sp.left, top: sp.top });
  }, [hoverSub]);

  return (
    <>
      <div className="ctx-menu-title">节点操作</div>
      <button type="button" className="ctx-menu-row ctx-menu-row-split" onClick={props.onCopy}>
        <span>复制</span>
        <span className="ctx-menu-kbd">{KBD.copy}</span>
      </button>
      <button type="button" className="ctx-menu-row ctx-menu-row-split" onClick={props.onDup}>
        <span>原地复制</span>
        <span className="ctx-menu-kbd">{KBD.dup}</span>
      </button>
      <button
        type="button"
        className="ctx-menu-row ctx-menu-row-split ctx-menu-danger"
        onClick={props.onDelete}
      >
        <span>删除</span>
        <span className="ctx-menu-kbd">{KBD.delete}</span>
      </button>
      <div className="ctx-menu-sep" />
      <button
        type="button"
        className={`ctx-menu-row ctx-menu-row-split${hoverSub ? " highlight" : ""}`}
        onMouseEnter={() => setHoverSub(true)}
        onMouseLeave={() => setHoverSub(false)}
      >
        <span>添加节点</span>
        <span className="ctx-menu-arrow">▶</span>
      </button>
      {hoverSub && subPos && (
        <div
          ref={subRef}
          className="canvas-ctx-menu canvas-ctx-submenu"
          style={{ left: subPos.left, top: subPos.top }}
          onMouseEnter={() => setHoverSub(true)}
          onMouseLeave={() => setHoverSub(false)}
        >
          {ADD_NODE_ITEMS.map((item, i) => (
            <div key={`${item.kind}-${i}`}>
              {i === 7 && <div className="ctx-menu-sep" />}
              <button
                type="button"
                className="ctx-menu-row ctx-menu-row-split"
                onClick={() => props.onAddNode(item.kind)}
              >
                <span>{item.label}</span>
                {item.shortcut && <span className="ctx-menu-kbd">{item.shortcut}</span>}
              </button>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

function ConnectMenuContent(props: {
  onAddNode: (kind: NodeData["kind"]) => void;
}) {
  return (
    <>
      <div className="ctx-menu-title">接到新节点</div>
      {ADD_NODE_ITEMS.map((item, i) => (
        <div key={`${item.kind}-${i}`}>
          {i === 7 && <div className="ctx-menu-sep" />}
          <button
            type="button"
            className="ctx-menu-row ctx-menu-row-split"
            onClick={() => props.onAddNode(item.kind)}
          >
            <span>{item.label}</span>
            {item.shortcut && <span className="ctx-menu-kbd">{item.shortcut}</span>}
          </button>
        </div>
      ))}
    </>
  );
}

function EdgeMenuContent({ onDelete }: { onDelete: () => void }) {
  return (
    <>
      <div className="ctx-menu-title">连线</div>
      <button
        type="button"
        className="ctx-menu-row ctx-menu-row-split ctx-menu-danger"
        onClick={onDelete}
      >
        <span>删除连线</span>
      </button>
    </>
  );
}
