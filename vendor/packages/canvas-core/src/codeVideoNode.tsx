/**
 * 代码成片节点（V4.46 · 2026-10-20）
 *
 * 输入：一段分镜表 JSON（数组）或 CodeVideoSpec JSON（对象）；
 * 输出：Chromium frame(t)+ffmpeg 渲染的 mp4，落画布 inbox，节点内可播放。
 * 进度：优先 SSE（code_video.*），SSE 不通时 2s 轮询兜底。
 *
 * 边界：不伪造成功——失败显示 stage+error；未填输入直接提示。
 */
import { memo, useEffect, useRef, useState } from "react";
import type { NodeProps } from "@xyflow/react";
import { Handle, Position, NodeResizer } from "@xyflow/react";
import { useCanvasStore } from "./store";
import "./codeVideoNode.css";
import { useVideoBad, VideoUnplayable } from "./videoUnplayable";
import { fetchPrefs, sendBlobToEditor } from "./bridge";
import {
  getCodeVideoJob,
  parseCodeVideoInput,
  startCodeVideoRender,
  subscribeCodeVideoJob,
  type CodeVideoJob,
} from "./codeVideoClient";

type CodeVideoData = {
  title?: string;
  storyboardText?: string;
  outputName?: string;
  qc?: boolean;
  videoUrl?: string;
  jobId?: string;
  status?: CodeVideoJob["status"];
  stage?: string;
  percent?: number;
  error?: string;
  lastIngest?: string;
};

const stop = (e: React.MouseEvent) => e.stopPropagation();

export const CodeVideoNode = memo(function CodeVideoNode({ id, data, selected }: NodeProps) {
  const d = data as CodeVideoData;
  const updateNodeData = useCanvasStore((s) => s.updateNodeData);
  const [busy, setBusy] = useState(false);
  const [ingesting, setIngesting] = useState(false);
  const [localError, setLocalError] = useState("");
  const unsubRef = useRef<null | (() => void)>(null);
  const pollRef = useRef<number | null>(null);

  const setJob = (patch: Partial<CodeVideoJob>) => {
    updateNodeData(id, {
      status: patch.status ?? d.status,
      stage: patch.stage ?? d.stage,
      percent: patch.percent ?? d.percent,
      error: patch.error ?? "",
      ...(patch.result
        ? {
            videoUrl:
              String((patch.result as Record<string, unknown>).url || "") ||
              String((patch.result as Record<string, unknown>).video_path || ""),
          }
        : {}),
    });
    if (patch.status === "done" || patch.status === "error") {
      setBusy(false);
      if (pollRef.current) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
    }
  };

  const attach = (jobId: string) => {
    unsubRef.current?.();
    unsubRef.current = subscribeCodeVideoJob(jobId, (job) => {
      setJob(job as Partial<CodeVideoJob>);
    });
    if (pollRef.current) window.clearInterval(pollRef.current);
    pollRef.current = window.setInterval(async () => {
      const job = await getCodeVideoJob(jobId);
      if (job) setJob(job);
    }, 2000);
  };

  useEffect(() => () => {
    unsubRef.current?.();
    if (pollRef.current) window.clearInterval(pollRef.current);
  }, []);

  const onRender = async () => {
    setLocalError("");
    const parsed = parseCodeVideoInput(d.storyboardText || "", {
      outputName: d.outputName,
      qc: d.qc !== false,
    });
    if (!parsed.payload) {
      setLocalError(parsed.error || "输入不合法");
      return;
    }
    setBusy(true);
    updateNodeData(id, {
      status: "queued", stage: "queued", percent: 0, error: "", videoUrl: "",
    });
    const started = await startCodeVideoRender(parsed.payload);
    if (!started.ok || !started.job) {
      setBusy(false);
      setLocalError(started.error || "提交失败");
      updateNodeData(id, { status: "error", error: started.error || "提交失败" });
      return;
    }
    updateNodeData(id, { jobId: started.job.id, status: started.job.status });
    attach(started.job.id);
  };

  const onIngest = async () => {
    if (!d.videoUrl) return;
    setLocalError("");
    setIngesting(true);
    try {
      const res = await fetch(d.videoUrl);
      if (!res.ok) throw new Error(`下载产物失败：HTTP ${res.status}`);
      const blob = await res.blob();
      const prefs = await fetchPrefs();
      const msg = await sendBlobToEditor(blob, `${d.outputName || "code_video"}.mp4`, prefs, {
        title: d.title || "代码成片",
        node_id: id,
        kind: "video",
      });
      updateNodeData(id, { lastIngest: msg });
    } catch (e: any) {
      setLocalError(`入轨失败：${e?.message || e}`);
    } finally {
      setIngesting(false);
    }
  };

  const status = d.status || "idle";
  const percent = Math.max(0, Math.min(100, Number(d.percent || 0)));
  const vbad = useVideoBad();
  return (
    <div className={`sg-node sg-code-video${selected ? " selected" : ""}`} onMouseDown={stop}>
      <NodeResizer minWidth={300} minHeight={260} isVisible={!!selected} />
      <Handle type="target" position={Position.Left} />
      <div className="head">
        <span>🧩 {d.title || "代码成片"}</span>
        <span className={`sg-cv-badge ${status}`}>{status}</span>
      </div>
      <div className="body nodrag">
        <textarea
          className="sg-cv-input"
          placeholder='分镜表 JSON：[{"shot":1,"description":"雨夜","duration":6}]'
          value={d.storyboardText || ""}
          onChange={(e) => updateNodeData(id, { storyboardText: e.target.value })}
          spellCheck={false}
        />
        <div className="sg-cv-row">
          <input
            className="sg-cv-name"
            placeholder="输出名（可选）"
            value={d.outputName || ""}
            onChange={(e) => updateNodeData(id, { outputName: e.target.value })}
          />
          <label className="sg-cv-qc">
            <input
              type="checkbox"
              checked={d.qc !== false}
              onChange={(e) => updateNodeData(id, { qc: e.target.checked })}
            />
            QC
          </label>
        </div>
        <button
          type="button"
          className="sg-node-mini-btn primary"
          disabled={busy}
          onClick={() => void onRender()}
        >
          {busy ? "渲染中…" : "▶ 渲染成片"}
        </button>
        {(status === "running" || status === "queued") && (
          <div className="sg-cv-progress">
            <div className="sg-cv-bar" style={{ width: `${percent}%` }} />
            <span>{d.stage || status} {percent}%</span>
          </div>
        )}
        {(localError || d.error) && (
          <div className="sg-cv-error">{localError || d.error}</div>
        )}
        {d.videoUrl ? (
          <>
            {/* 画布内核没带 H.264 ⇒ mp4 的 <video> 报 error.code=4，退回一帧图 + 说清原因 */}
            {vbad.bad ? (
              <VideoUnplayable />
            ) : (
              <video className="sg-cv-video" src={d.videoUrl} controls preload="metadata"
                     onError={vbad.onError} />
            )}
            <button
              type="button"
              className="sg-node-mini-btn"
              disabled={ingesting}
              onClick={() => void onIngest()}
            >
              {ingesting ? "入轨中…" : "→ 加入时间线"}
            </button>
          </>
        ) : (
          <div className="sg-cv-empty">尚未渲染 · 分镜/契约 → mp4（失败会显示 stage）</div>
        )}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
});

export default CodeVideoNode;
