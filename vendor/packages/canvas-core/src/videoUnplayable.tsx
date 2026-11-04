/**
 * videoUnplayable.tsx — `<video>` 报错时退回「首帧图 + 说人话」（2026-11-02）
 *
 * 用法（三行改动，不动播放逻辑本身）：
 *
 * ```tsx
 * const v = useVideoBad();
 * v.bad ? <VideoUnplayable poster={pickVideoPoster(d.posterUrl, d.firstFrameUrl)} />
 *       : <video src={d.videoUrl} onError={v.onError} … />
 * ```
 *
 * 只有 `onError` 触发才切换 —— 不去预判编码，也不主动 `canPlayType`：
 * WebM 在这台机器上能播，一刀切会把能播的也拦掉。
 */
import { useState, type ReactNode } from "react";
import {
  VIDEO_UNPLAYABLE_HINT,
  VIDEO_UNPLAYABLE_TITLE,
} from "./videoFallback";
import "./videoFallback.css";

/** `<video>` 的报错状态。`onError` 只置位一次，不来回抖。 */
export function useVideoBad(): { bad: boolean; onError: () => void } {
  const [bad, setBad] = useState(false);
  return { bad, onError: () => setBad(true) };
}

/**
 * 放不出画面时显示什么。
 *
 * `poster` 传 `pickVideoPoster(...)` 的结果；`children` 可塞额外出路
 * （团队面板塞「下载」链接，画布节点不塞）。
 */
export function VideoUnplayable({ poster, children }: { poster?: string; children?: ReactNode }) {
  const [posterBroken, setPosterBroken] = useState(false);
  const shot = String(poster || "").trim();
  return (
    <div className="sg-vbad">
      <div className="sg-vbad-pic">
        {shot && !posterBroken
          ? <img src={shot} alt="视频首帧" onError={() => setPosterBroken(true)} />
          : <span aria-hidden="true">🎬</span>}
      </div>
      <div className="sg-vbad-txt">
        <b>{VIDEO_UNPLAYABLE_TITLE}</b>
        <span>{VIDEO_UNPLAYABLE_HINT}</span>
        {children}
      </div>
    </div>
  );
}
