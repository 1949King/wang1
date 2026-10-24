/**
 * 录制运镜 —— 把用户在 3D 导演台手动拖动的相机轨迹，采样成 pathPoints 关键帧路径，
 * 用于「录一段运镜 → 导出当动态 Layout / 播放 / 首尾帧成片」。
 *
 * ⚠️ 纯相机层模块：只读相机 position + controls.target，绝不触碰 GLB 模型加载、
 *    骨骼绑定、材质渲染（stage3d-core 冻结红线）。
 */

export type CamRecordFrame = {
  pos: [number, number, number];
  look: [number, number, number];
  /** 相对录制起点的毫秒 */
  t: number;
};

export type CamPathPoint = {
  pos: [number, number, number];
  look: [number, number, number];
};

/** 把采样帧按时间均匀抽稀到 maxPoints 个路径点（保首尾，中间等距抽）。 */
export function thinRecordFrames(frames: CamRecordFrame[], maxPoints: number): CamPathPoint[] {
  if (!frames.length) return [];
  const n = Math.max(1, Math.min(maxPoints, frames.length));
  const out: CamPathPoint[] = [];
  for (let i = 0; i < n; i++) {
    const idx = i === n - 1 ? frames.length - 1 : Math.floor((i / (n - 1)) * (frames.length - 1));
    const f = frames[idx];
    out.push({ pos: [...f.pos] as CamRecordFrame["pos"], look: [...f.look] as CamRecordFrame["look"] });
  }
  return out;
}

export class CameraRecorder {
  private frames: CamRecordFrame[] = [];
  private startAt = 0;
  private _recording = false;
  /** 最小采样间隔（ms），避免每 rAF 都堆点导致路径过密 */
  private minGapMs = 16;

  get isRecording(): boolean {
    return this._recording;
  }

  get count(): number {
    return this.frames.length;
  }

  start(now = performance.now()): void {
    this.frames = [];
    this.startAt = now;
    this._recording = true;
  }

  /** 渲染循环里每帧调用：记录当前相机位姿。 */
  record(pos: [number, number, number], look: [number, number, number], now = performance.now()): void {
    if (!this._recording) return;
    const t = now - this.startAt;
    const last = this.frames[this.frames.length - 1];
    if (last && t - last.t < this.minGapMs) return;
    this.frames.push({
      pos: [...pos] as [number, number, number],
      look: [...look] as [number, number, number],
      t,
    });
  }

  /** 结束录制，返回时长与抽稀后的路径点。 */
  stop(maxPoints = 24): { durationMs: number; pathPoints: CamPathPoint[] } {
    this._recording = false;
    const durationMs = this.frames.length ? this.frames[this.frames.length - 1].t : 0;
    return { durationMs, pathPoints: thinRecordFrames(this.frames, maxPoints) };
  }

  clear(): void {
    this.frames = [];
    this._recording = false;
  }
}
