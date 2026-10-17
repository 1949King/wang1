/**
 * AI-Canvas-tauri 对齐节点：Markdown / 分镜表 / 交互宫格
 * 纯前端实现，媒体与入轨仍走拾光 bridge / 剪辑真相源。
 */
import React, { memo, useMemo, useCallback, useState, useRef } from "react";
import { Handle, Position, NodeResizer, type NodeProps } from "@xyflow/react";
import {
  useCanvasStore,
  type NodeData,
  type MarkdownData,
  type ShotlistData,
  type ShotlistRow,
  type StoryboardData,
  createShotlistRow,
  defaultStoryboardCells,
} from "./store";
import { cropGridCell } from "./imageTools";
import { planStoryboardMemory, uploadAssetToHost, videoStoryboard, type MemoryPlanRow } from "./bridge";
import { pullDepthBreakdown } from "./hostBreakdownL2";
import { getVisionModel } from "./visionModel";
import type { MemoryType } from "./stores/node-factory";

function nodePropsEqual(prev: NodeProps, next: NodeProps): boolean {
  return (
    prev.id === next.id &&
    prev.selected === next.selected &&
    prev.dragging === next.dragging &&
    prev.data === next.data
  );
}

function stop(e: React.SyntheticEvent) {
  e.stopPropagation();
}

/** 极简 Markdown → HTML（无外部依赖） */
export function renderLiteMarkdown(src: string): string {
  const esc = src
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  return esc
    .replace(/^### (.+)$/gm, "<h3>$1</h3>")
    .replace(/^## (.+)$/gm, "<h2>$1</h2>")
    .replace(/^# (.+)$/gm, "<h1>$1</h1>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/^\- (.+)$/gm, "<li>$1</li>")
    .replace(/(<li>.*<\/li>\n?)+/g, (m) => `<ul>${m}</ul>`)
    .replace(/\n{2,}/g, "<br/><br/>")
    .replace(/\n/g, "<br/>");
}

export const MarkdownNode = memo(function MarkdownNode({ id, data, selected }: NodeProps) {
  const d = data as MarkdownData;
  const updateNodeData = useCanvasStore((s) => s.updateNodeData);
  const preview = !!d.preview;

  return (
    <div className={`sg-node markdown${selected ? " selected" : ""}`} onMouseDown={stop}>
      <NodeResizer minWidth={240} minHeight={160} isVisible={!!selected} />
      <Handle type="target" position={Position.Left} />
      <div className="head">
        <span>📑 {d.title || "Markdown"}</span>
        <button
          type="button"
          className="sg-node-mini-btn"
          onClick={() => updateNodeData(id, { preview: !preview })}
        >
          {preview ? "编辑" : "预览"}
        </button>
      </div>
      <div className="body nodrag">
        {preview ? (
          <div
            className="sg-md-preview"
            dangerouslySetInnerHTML={{ __html: renderLiteMarkdown(d.content || "") }}
          />
        ) : (
          <textarea
            className="sg-md-editor"
            value={d.content || ""}
            onChange={(e) => updateNodeData(id, { content: e.target.value })}
            placeholder="# 标题&#10;&#10;正文…"
          />
        )}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}, nodePropsEqual);

const SHOT_SIZES = ["远景", "全景", "中景", "近景", "特写", "大特写"];
const CAMERAS = ["固定", "推", "拉", "摇", "移", "跟", "升", "降", "手持", "环绕"];

/**
 * 观众记忆类型 —— 决定「这一镜该给多少秒」。
 * 三档对应后端 memory_model 的三条衰减曲线（24h 基线保留率：细节 < 意义 < 情绪）。
 *
 * ⚠️ 这里只写**相对**描述，具体百分比一律显示后端回传的真值 ——
 *    前端硬编码数字会和 Python 侧的 λ 漂移（角色提示词就是这个坑）。
 */
const MEMORY_OPTIONS: { value: MemoryType; label: string; hint: string }[] = [
  { value: "detail", label: "细节", hint: "衰减最快：本来就会被忘记，可剪短剪碎" },
  { value: "meaning", label: "意义", hint: "衰减居中：三档里的中性基准" },
  { value: "emotion", label: "情绪", hint: "衰减最慢：是「被记住」的真正载体，值得给足时长" },
];

export const ShotlistNode = memo(function ShotlistNode({ id, data, selected }: NodeProps) {
  const d = data as ShotlistData;
  const rows = d.rows || [];
  const updateNodeData = useCanvasStore((s) => s.updateNodeData);
  const nodes = useCanvasStore((s) => s.nodes);
  const selectedId = useCanvasStore((s) => s.selectedId);
  const setStatus = useCanvasStore((s) => s.setStatus);

  const setRows = useCallback(
    (next: ShotlistRow[]) => updateNodeData(id, { rows: next }),
    [id, updateNodeData],
  );

  const patchRow = (rowId: string, patch: Partial<ShotlistRow>) => {
    setRows(rows.map((r) => (r.id === rowId ? { ...r, ...patch } : r)));
  };

  const [memoryPlan, setMemoryPlan] = useState<MemoryPlanRow[] | null>(null);
  const [memoryWarnings, setMemoryWarnings] = useState<string[]>([]);
  const [tHours, setTHours] = useState<number>(24);
  const [planning, setPlanning] = useState(false);
  const [pulling, setPulling] = useState(false);
  const [l2Pulling, setL2Pulling] = useState(false);
  const pullRef = useRef<HTMLInputElement>(null);
  /** 拉片模式：llm=既有「📹 拉片」（videoStoryboard，LLM 猜景别/运镜）；
   *  l2 = Wave 0 #13 新增「🧊 深度拉片」（referenceBreakdownL2，深度实测+置信度门槛）。
   *  两条线**并行不替换** —— 证据等级不同（LLM 推断 vs 深度实测），让用户自己选。 */
  const [pullMode, setPullMode] = useState<"llm" | "l2">("llm");
  /** 深度拉片是否启用云端视觉 enrich（**素材出域**，故默认 false，须显式勾选）。 */
  const [l2UseVision, setL2UseVision] = useState(false);

  /** 一键拉片：上传参考视频 → 后端检测镜头边界 + 抽帧 + 色调/景别 → 填分镜表。
   *  按 `pullMode` 分两条线（Wave 0 #13 新增 l2 分支）：
   *   - llm：videoStoryboard，景别/运镜靠 LLM 推断（既有行为，逐键不变）；
   *   - l2：referenceBreakdownL2，景别/运镜靠深度图实测 + 置信度门槛。
   *  ⚠️ l2 分支**不用本机视觉模型**（那是 llm 线的），且景别/运镜留空时**保持留空**
   *  （见hostBreakdownL2.ts 诚实边界说明）。 */
  const onPickReferenceVideo = async (file: File | null) => {
    if (!file) return;
    if (pullMode === "l2") {
      await runDepthBreakdown(file);
      if (pullRef.current) pullRef.current.value = "";
      return;
    }
    setPulling(true);
    try {
      const up = await uploadAssetToHost(file);
      if (!up.ok || !up.path) throw new Error(up.message || "上传失败");
      // I1：走本机视觉模型逐镜解析（素材不出机）；未装视觉模型时后端诚实降级
      const res = await videoStoryboard({ path: up.path, use_llm: true, vision_model: getVisionModel() });
      if (!res.ok || !res.shots?.length) {
        setStatus?.(`拉片失败：${res.message || "无镜头"}`);
        return;
      }
      const next: ShotlistRow[] = res.shots.map((s, i) => ({
        id: `row_${Math.random().toString(36).slice(2, 9)}`,
        shotNo: String(i + 1).padStart(2, "0"),
        shotSize: s.shot || "中景",
        camera: s.camera || "固定",
        content: s.description || "",
        dialogue: s.dialogue || "",
        duration: Number(s.duration) || 3,
        note:
          s.tone || s.brightness != null
            ? `${s.tone || "中性"}色调` +
              (s.brightness != null ? ` · 亮度${Math.round(s.brightness * 100)}%` : "")
            : "",
        memoryType: "meaning",
        frameUrl: s.frame || undefined,
        frameKind: "image",
      }));
      setRows(next);
      const vmsg = (res as { vision_message?: string }).vision_message;
      setStatus?.(
        `拉片完成：${next.length} 镜（${res.scene_source || "自动"}检测）${vmsg ? ` · ${vmsg}` : ""}`,
      );
} catch (e) {
      setStatus?.(`拉片失败：${e}`);
    } finally {
      setPulling(false);
      if (pullRef.current) pullRef.current.value = "";
    }
  };

  /** 深度拉片（Wave 0 #13 第 4 条，2026-10-15）：上传参考片 → `/host/reference-breakdown-l2`
   *  → 深度图实测运镜（带置信度门槛）+ 运动量/亮度/对比度实测值 → 填分镜表。
   *
   *  与上面 `videoStoryboard` 那条线的区别是**证据等级**：
   * 那边景别/运镜是LLM 推断，这边是 CV 实测；两条线并存，用户自己选。
   *
   *  ⚠️ `use_vision` **默认 false**：开它会让素材出域到云端视觉模型，
   *  必须用户在按钮上显式勾选（沿用后端 reference_breakdown 的同一纪律）。
   *  ⚠️ 覆盖现有分镜表前**必须显式确认**（会改用户数据，与 repair-image 同纪律）。
   *  ⚠️ 拉片成功也不给每行填默认景别/运镜 —— 后端留空就是留空，如实呈现。 */
  const runDepthBreakdown = async (file: File) => {
    setL2Pulling(true);
    try {
      const up = await uploadAssetToHost(file);
      if (!up.ok || !up.path) throw new Error(up.message || "上传失败");
      const res = await pullDepthBreakdown({
        videoPath: up.path,
        useVision: l2UseVision,
        visionModel: getVisionModel(),
      });
      if (!res.ok || !res.rows.length) {
        setStatus?.(`深度拉片失败：${res.message || "无镜头"}`);
        return;
      }
      // ⚠️ 覆盖现有行是不可逆的数据改动 ⇒ 有旧数据时先问一次。
      // 用 `window.confirm` 而非项目的 `ConfirmDialog`：后者需在组件里挂载 fixed 定位
      // 模态，而本组件是 xyflow 节点（在带 transform 的 viewport 内）⇒ 会踩
      // 「viewport 内渲染固定定位模态」的已知陷阱。项目内 DirectorPanel / Stage3D /
      // WorkspaceCanvasMenus 同样直接用 window.confirm，此处与之保持一致。
      if (rows.length && !window.confirm(`深度拉片将用 ${res.rows.length} 镜覆盖当前 ${rows.length} 行分镜表，继续？`)) {
        setStatus?.("深度拉片已取消（分镜表未改动）");
        return;
      }
      setRows(res.rows);
      // 一行结论由 hostBreakdownL2.summarizeL2Pull 生成：留空就说留空，不含糊
      setStatus?.(
        res.message ||
          `深度拉片完成：${res.rows.length} 镜${res.duration ? ` · ${res.duration.toFixed(1)}s` : ""}`,
      );
    } catch (e) {
      setStatus?.(`深度拉片失败：${e}`);
    } finally {
      setL2Pulling(false);
    }
  };
  const runMemoryPlan = async () => {
    if (!rows.length) return;
    setPlanning(true);
    try {
      const res = await planStoryboardMemory({
        rows: rows.map((r) => ({
          id: r.id,
          memoryType: r.memoryType || "meaning",
          duration: Number(r.duration) || 3,
        })),
      });
      if (!res.ok || !res.rows?.length) {
        setStatus?.(`记忆规划失败：${res.message || "无返回"}`);
        return;
      }
      setMemoryPlan(res.rows);
      setMemoryWarnings(res.warnings || []);
      setTHours(res.t_hours ?? 24);
      const byId = new Map(res.rows.map((r) => [r.id, r.suggestedDuration]));
      setRows(rows.map((r) => (byId.has(r.id) ? { ...r, duration: byId.get(r.id) as number } : r)));
      setStatus?.(
        `已按记忆重排时长：${res.totalCurrent ?? 0}s → ${res.totalSuggested ?? 0}s（总时长守恒）` +
          (res.warnings?.length ? ` · ⚠ ${res.warnings[0]}` : ""),
      );
    } catch (e) {
      setStatus?.(`记忆规划失败：${e}`);
    } finally {
      setPlanning(false);
    }
  };

  const bindSelectedFrame = (rowId: string) => {
    const n = nodes.find((x) => x.id === selectedId && x.id !== id);
    if (!n) return;
    const nd = n.data as NodeData;
    if (nd.kind === "image" || nd.kind === "shot") {
      patchRow(rowId, {
        frameNodeId: n.id,
        frameKind: "image",
        frameUrl: (nd as any).imageUrl || "",
      });
    } else if (nd.kind === "video") {
      patchRow(rowId, {
        frameNodeId: n.id,
        frameKind: "video",
        frameUrl: nd.posterUrl || nd.videoUrl || "",
      });
    }
  };

  const expandToShots = () => {
    const st = useCanvasStore.getState();
    const base = st.nodes.find((n) => n.id === id);
    const ox = (base?.position.x || 0) + 760;
    const oy = base?.position.y || 80;
    rows.forEach((row, i) => {
      st.addNode("shot", { x: ox, y: oy + i * 180 });
      const sid = useCanvasStore.getState().selectedId;
      if (!sid) return;
      st.updateNodeData(sid, {
        title: `镜 ${row.shotNo}`,
        shotSize: row.shotSize || "中景",
        duration: row.duration || 3,
        dialogue: row.dialogue || "",
        prompt: [row.content, row.camera, row.note].filter(Boolean).join("，"),
        imageUrl: row.frameUrl || undefined,
        movement:
          row.camera === "推"
            ? "push-in"
            : row.camera === "拉"
              ? "pull-out"
              : row.camera === "固定"
                ? "static"
                : undefined,
      });
    });
    st.setStatus(`已从分镜表展开 ${rows.length} 个镜头`);
  };

  return (
    <div className={`sg-node shotlist${selected ? " selected" : ""}`} onMouseDown={stop}>
      <NodeResizer minWidth={520} minHeight={220} isVisible={!!selected} />
      <Handle type="target" position={Position.Left} />
      <div className="head">
        <span>📋 {d.title || "分镜表"} · {rows.length} 镜</span>
        <div className="sg-node-head-actions">
          <button
            type="button"
            className="sg-node-mini-btn"
            onClick={() => setRows([...rows, createShotlistRow(rows.length + 1)])}
          >
            +行
          </button>
          <button
            type="button"
            className="sg-node-mini-btn"
            onClick={() => {
              setPullMode("llm");
              pullRef.current?.click();
            }}
            disabled={pulling || l2Pulling}
            title="上传参考片 → 自动检测镜头边界 + 抽代表帧 + 判色调/景别（景别/运镜由 LLM 推断）"
          >
            {pulling && pullMode === "llm" ? "拉片中…" : "📹 拉片"}
          </button>
          <button
            type="button"
            className="sg-node-mini-btn"
            onClick={() => {
              setPullMode("l2");
              pullRef.current?.click();
            }}
            disabled={pulling || l2Pulling}
            title="上传参考片 → 深度图实测运镜（带置信度门槛）+ 实测运动量/亮度/对比度。景别/运镜测不出时留空，不猜"
          >
            {l2Pulling ? "深度拉片中…" : "🧊 深度拉片"}
          </button>
          {pullMode === "l2" ? (
            <label className="sg-node-mini-check" title="勾选后素材会送到云端视觉模型做景别/画面描述解析（素材出域），留空则只跑本机深度">
              <input
                type="checkbox"
                checked={l2UseVision}
                onChange={(e) => setL2UseVision(e.target.checked)}
              />
              云端视觉（素材出域）
            </label>
          ) : null}
          <button
            type="button"
            className="sg-node-mini-btn"
            onClick={() => void runMemoryPlan()}
            disabled={planning || !rows.length}
            title="按观众记忆保留率重排各镜时长（总时长守恒）：细节让位、情绪拿时长"
          >
            {planning ? "规划中…" : "按记忆重排时长"}
          </button>
          <button
            type="button"
            className="sg-node-mini-btn primary"
            onClick={expandToShots}
          >
            展开为镜头
          </button>
        </div>
      </div>
      <div className="body nodrag nowheel">
        <input
          ref={pullRef}
          type="file"
          accept="video/*"
          hidden
          onChange={(e) => void onPickReferenceVideo(e.target.files?.[0] || null)}
        />
        <table className="sg-shotlist-table">
          <thead>
            <tr>
              <th>镜号</th>
              <th>画面</th>
              <th>景别</th>
              <th>运镜</th>
              <th>内容</th>
              <th>台词</th>
              <th>秒</th>
              <th title="观众记忆类型：决定这一镜该给多少秒">记忆</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const live = row.frameNodeId
                ? nodes.find((n) => n.id === row.frameNodeId)
                : null;
              const liveUrl =
                (live &&
                  ((live.data as any).imageUrl ||
                    (live.data as any).posterUrl ||
                    (live.data as any).videoUrl)) ||
                row.frameUrl;
              const planRow = memoryPlan?.find((p) => p.id === row.id);
              const memType = row.memoryType || "meaning";
              return (
                <tr key={row.id}>
                  <td>
                    <input
                      value={row.shotNo}
                      onChange={(e) => patchRow(row.id, { shotNo: e.target.value })}
                    />
                  </td>
                  <td className="sg-shotlist-frame">
                    {liveUrl ? <img src={liveUrl} alt="" /> : <span className="muted">空</span>}
                    <button type="button" className="sg-node-mini-btn" onClick={() => bindSelectedFrame(row.id)}>
                      绑定选中
                    </button>
                  </td>
                  <td>
                    <select
                      value={row.shotSize}
                      onChange={(e) => patchRow(row.id, { shotSize: e.target.value })}
                    >
                      {SHOT_SIZES.map((s) => (
                        <option key={s} value={s}>
                          {s}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <select
                      value={row.camera}
                      onChange={(e) => patchRow(row.id, { camera: e.target.value })}
                    >
                      {CAMERAS.map((s) => (
                        <option key={s} value={s}>
                          {s}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input
                      value={row.content}
                      onChange={(e) => patchRow(row.id, { content: e.target.value })}
                      placeholder="画面内容"
                    />
                  </td>
                  <td>
                    <input
                      value={row.dialogue}
                      onChange={(e) => patchRow(row.id, { dialogue: e.target.value })}
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      min={0.5}
                      step={0.5}
                      value={row.duration}
                      onChange={(e) => patchRow(row.id, { duration: Number(e.target.value) || 3 })}
                    />
                  </td>
                  <td>
                    <select
                      value={memType}
                      title={MEMORY_OPTIONS.find((m) => m.value === memType)?.hint}
                      onChange={(e) => patchRow(row.id, { memoryType: e.target.value as MemoryType })}
                    >
                      {MEMORY_OPTIONS.map((m) => (
                        <option key={m.value} value={m.value}>
                          {m.label}
                        </option>
                      ))}
                    </select>
                    {planRow ? (
                      <span
                        className="muted"
                        title={`${tHours}h 后约保留 ${(planRow.retention * 100).toFixed(1)}%（后端按记忆衰减模型算）`}
                      >
                        {(planRow.retention * 100).toFixed(0)}%
                      </span>
                    ) : null}
                  </td>
                  <td>
                    <button
                      type="button"
                      className="sg-node-mini-btn danger"
                      onClick={() => setRows(rows.filter((r) => r.id !== row.id))}
                    >
                      ×
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {memoryWarnings.length
          ? memoryWarnings.map((w, i) => (
              <p className="meta" key={i}>
                ⚠ {w}
              </p>
            ))
          : null}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}, nodePropsEqual);

export const StoryboardNode = memo(function StoryboardNode({ id, data, selected }: NodeProps) {
  const d = data as StoryboardData;
  const cols = d.cols || 3;
  const rows = d.rows || 3;
  const cells = useMemo(() => {
    const need = cols * rows;
    const cur = d.cells || [];
    if (cur.length === need) return cur;
    return defaultStoryboardCells(cols, rows).map((c, i) => cur[i] || c);
  }, [d.cells, cols, rows]);
  const updateNodeData = useCanvasStore((s) => s.updateNodeData);
  const selectedId = useCanvasStore((s) => s.selectedId);
  const nodes = useCanvasStore((s) => s.nodes);
  const setStatus = useCanvasStore((s) => s.setStatus);
  const [busy, setBusy] = useState<number | null>(null);

  const bindSourceFromSelected = () => {
    const n = nodes.find((x) => x.id === selectedId && x.id !== id);
    if (!n) {
      setStatus?.("请先选中一张图片/镜头节点");
      return;
    }
    const url = (n.data as any).imageUrl as string | undefined;
    if (!url) {
      setStatus?.("选中节点没有可用图片");
      return;
    }
    updateNodeData(id, { sourceUrl: url });
  };

  const resizeGrid = (c: 2 | 3 | 4 | 5, r: 2 | 3 | 4 | 5) => {
    updateNodeData(id, {
      cols: c,
      rows: r,
      cells: defaultStoryboardCells(c, r).map((cell, i) => (d.cells || [])[i] || cell),
    });
  };

  const extractCell = async (index: number) => {
    if (!d.sourceUrl) {
      setStatus?.("请先绑定源图");
      return;
    }
    setBusy(index);
    try {
      const url = cells[index]?.overrideUrl || (await cropGridCell(d.sourceUrl, cols, rows, index));
      const st = useCanvasStore.getState();
      const base = st.nodes.find((n) => n.id === id);
      st.addNode("image", {
        x: (base?.position.x || 0) + 460,
        y: (base?.position.y || 0) + (index % cols) * 40 + Math.floor(index / cols) * 160,
      });
      const sid = useCanvasStore.getState().selectedId;
      if (sid) {
        st.updateNodeData(sid, {
          title: `格 ${index + 1}`,
          imageUrl: url,
          prompt: d.prompt || `宫格分镜第 ${index + 1} 格`,
        });
      }
      setStatus?.(`已拖出第 ${index + 1} 格为图片节点`);
    } catch (e) {
      setStatus?.(`裁格失败：${e}`);
    } finally {
      setBusy(null);
    }
  };

  const extractAll = async () => {
    if (!d.sourceUrl) return;
    for (let i = 0; i < cols * rows; i++) {
      // sequential to keep positions stable
      // eslint-disable-next-line no-await-in-loop
      await extractCell(i);
    }
  };

  return (
    <div className={`sg-node storyboard${selected ? " selected" : ""}`} onMouseDown={stop}>
      <NodeResizer minWidth={300} minHeight={240} isVisible={!!selected} />
      <Handle type="target" position={Position.Left} />
      <div className="head">
        <span>▦ {d.title || "宫格分镜"} · {cols}×{rows}</span>
        <div className="sg-node-head-actions">
          <button type="button" className="sg-node-mini-btn" onClick={bindSourceFromSelected}>
            绑源图
          </button>
          <button type="button" className="sg-node-mini-btn" onClick={() => void extractAll()} disabled={!d.sourceUrl}>
            全部拖出
          </button>
        </div>
      </div>
      <div className="body nodrag">
        <div className="sg-storyboard-toolbar">
          {[2, 3, 4, 5].map((n) => (
            <button
              key={n}
              type="button"
              className={`sg-node-mini-btn${cols === n && rows === n ? " primary" : ""}`}
              onClick={() => resizeGrid(n as 2 | 3 | 4 | 5, n as 2 | 3 | 4 | 5)}
            >
              {n}×{n}
            </button>
          ))}
        </div>
        <div
          className="sg-storyboard-grid"
          style={{ gridTemplateColumns: `repeat(${cols}, 1fr)` }}
        >
          {cells.map((cell, i) => {
            const thumb = cell.overrideUrl || d.sourceUrl;
            return (
              <button
                key={i}
                type="button"
                className="sg-storyboard-cell"
                title="点击裁出为图片节点"
                disabled={busy === i}
                onClick={() => void extractCell(i)}
                style={
                  thumb && !cell.overrideUrl
                    ? {
                        backgroundImage: `url(${thumb})`,
                        backgroundSize: `${cols * 100}% ${rows * 100}%`,
                        backgroundPosition: `${(i % cols) * (100 / (cols - 1 || 1))}% ${
                          Math.floor(i / cols) * (100 / (rows - 1 || 1))
                        }%`,
                      }
                    : cell.overrideUrl
                      ? { backgroundImage: `url(${cell.overrideUrl})`, backgroundSize: "cover" }
                      : undefined
                }
              >
                <span>{i + 1}</span>
              </button>
            );
          })}
        </div>
        {!d.sourceUrl ? <p className="meta">先选中图片/镜头节点，再点「绑源图」</p> : null}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}, nodePropsEqual);
