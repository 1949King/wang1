/**
 * 剪辑 → 画布自动落源节点；画布节点 ← 时间线快照回写入出点。
 * 已见过的 outbox id 记在 localStorage，避免重复加点。
 */
import { useEffect, useRef, useState } from "react";
import { fetchEditorOutbox, fetchTimelineSnapshot, type EditorOutboxItem, type TimelineSnapshot } from "../bridge";
import { useCanvasStore } from "../store";

const SEEN_KEY = "sg-editor-outbox-seen";

function loadSeen(): Set<string> {
  try {
    const raw = JSON.parse(localStorage.getItem(SEEN_KEY) || "[]");
    return new Set(Array.isArray(raw) ? raw.map(String) : []);
  } catch {
    return new Set();
  }
}

function saveSeen(seen: Set<string>) {
  localStorage.setItem(SEEN_KEY, JSON.stringify([...seen].slice(-80)));
}

function mediaTypeOf(it: EditorOutboxItem): "image" | "video" | "audio" {
  const e = (it.ext || "").toLowerCase();
  const k = (it.kind || "").toLowerCase();
  if (k === "audio" || k === "music" || [".mp3", ".wav", ".m4a", ".aac"].includes(e)) return "audio";
  if (
    k === "image" ||
    k === "shot" ||
    k === "director" ||
    [".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"].includes(e)
  ) {
    return "image";
  }
  return "video";
}

function rangeLabel(it: { in_point?: number; out_point?: number; start_time?: number; duration?: number }) {
  const a = it.in_point ?? it.start_time;
  const b = it.out_point ?? (typeof a === "number" && typeof it.duration === "number" ? a + it.duration : undefined);
  if (typeof a !== "number" || typeof b !== "number") return "";
  return `${a.toFixed(1)}s–${b.toFixed(1)}s`;
}

export function useEditorCanvasLink(): { clipCount: number } {
  const [clipCount, setClipCount] = useState(0);
  const seenRef = useRef<Set<string>>(loadSeen());
  const addStudioNode = useCanvasStore((s) => s.addStudioNode);
  const updateNodeData = useCanvasStore((s) => s.updateNodeData);
  const setStatus = useCanvasStore((s) => s.setStatus);

  useEffect(() => {
    let cancelled = false;

    const ingestOutbox = async () => {
      const items = await fetchEditorOutbox();
      if (cancelled || !items.length) return;
      let added = 0;
      for (const it of items) {
        if (!it.id || seenRef.current.has(it.id)) continue;
        seenRef.current.add(it.id);
        const nodes = useCanvasStore.getState().nodes;
        const linked = it.canvas_node_id
          ? nodes.find((n) => n.id === it.canvas_node_id)
          : undefined;
        const media = mediaTypeOf(it);
        const range = rangeLabel(it);
        if (linked) {
          updateNodeData(linked.id, {
            editorStatus: "sent",
            editorRange: range || undefined,
            editorClipId: it.clip_id,
          });
        } else {
          const extra: Record<string, unknown> = {
            title: it.title || it.filename || "来自剪辑",
            mediaType: media,
            fileName: it.filename,
            editorClipId: it.clip_id || "",
            editorStatus: "sent",
            editorRange: range,
          };
          if (media === "video") extra.videoUrl = it.url;
          else if (media === "audio") extra.audioUrl = it.url;
          else extra.imageUrl = it.url;
          addStudioNode("source", extra as never);
          added += 1;
        }
      }
      if (added) {
        saveSeen(seenRef.current);
        setStatus(`已从剪辑接入 ${added} 个源节点`);
      } else {
        saveSeen(seenRef.current);
      }
    };

    const syncSnapshot = async () => {
      const snap: TimelineSnapshot = await fetchTimelineSnapshot();
      if (cancelled) return;
      setClipCount(Number(snap.clip_count) || (snap.clips || []).length);
      const nodes = useCanvasStore.getState().nodes;
      for (const clip of snap.clips || []) {
        const nid = String(clip.canvas_node_id || "");
        if (!nid) continue;
        const hit = nodes.find((n) => n.id === nid);
        if (!hit) continue;
        const start = Number(clip.start_time) || 0;
        const end = Number(clip.end_time) || start + (Number(clip.duration) || 0);
        updateNodeData(nid, {
          editorStatus: "in_timeline",
          editorRange: `${start.toFixed(1)}s–${end.toFixed(1)}s`,
          editorClipId: clip.id,
        });
      }
    };

    void ingestOutbox();
    void syncSnapshot();
    const a = window.setInterval(() => void ingestOutbox(), 4000);
    const b = window.setInterval(() => void syncSnapshot(), 6000);
    return () => {
      cancelled = true;
      window.clearInterval(a);
      window.clearInterval(b);
    };
  }, [addStudioNode, updateNodeData, setStatus]);

  return { clipCount };
}
