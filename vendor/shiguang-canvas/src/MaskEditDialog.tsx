/** 蒙版局部重绘对话框 — 白笔=重绘区 */
import { useEffect, useRef, useState } from "react";

type Props = {
  imageUrl: string;
  open: boolean;
  busy?: boolean;
  onClose: () => void;
  onSubmit: (maskDataUrl: string, prompt: string) => void;
};

export default function MaskEditDialog({ imageUrl, open, busy, onClose, onSubmit }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);
  const drawing = useRef(false);
  const [prompt, setPrompt] = useState("保持构图，仅重绘蒙版区域");
  const [brush, setBrush] = useState(28);

  useEffect(() => {
    if (!open) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      imgRef.current = img;
      const maxW = 720;
      const scale = Math.min(1, maxW / img.width);
      canvas.width = Math.round(img.width * scale);
      canvas.height = Math.round(img.height * scale);
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      ctx.globalCompositeOperation = "source-over";
    };
    img.src = imageUrl;
  }, [open, imageUrl]);

  const paint = (ev: React.PointerEvent) => {
    const canvas = canvasRef.current;
    if (!canvas || !drawing.current) return;
    const rect = canvas.getBoundingClientRect();
    const x = ((ev.clientX - rect.left) / rect.width) * canvas.width;
    const y = ((ev.clientY - rect.top) / rect.height) * canvas.height;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.fillStyle = "rgba(255,255,255,0.85)";
    ctx.beginPath();
    ctx.arc(x, y, brush / 2, 0, Math.PI * 2);
    ctx.fill();
  };

  const buildMask = () => {
    const canvas = canvasRef.current;
    const img = imgRef.current;
    if (!canvas || !img) return "";
    const mask = document.createElement("canvas");
    mask.width = canvas.width;
    mask.height = canvas.height;
    const mctx = mask.getContext("2d");
    if (!mctx) return "";
    mctx.fillStyle = "#000";
    mctx.fillRect(0, 0, mask.width, mask.height);
    // 从展示画布提取偏白区域作为蒙版
    const src = canvas.getContext("2d");
    if (!src) return "";
    const data = src.getImageData(0, 0, canvas.width, canvas.height);
    const out = mctx.createImageData(canvas.width, canvas.height);
    for (let i = 0; i < data.data.length; i += 4) {
      const r = data.data[i];
      const g = data.data[i + 1];
      const b = data.data[i + 2];
      const bright = (r + g + b) / 3;
      const isMask = bright > 200;
      const v = isMask ? 255 : 0;
      out.data[i] = out.data[i + 1] = out.data[i + 2] = v;
      out.data[i + 3] = 255;
    }
    mctx.putImageData(out, 0, 0);
    return mask.toDataURL("image/png");
  };

  if (!open) return null;

  return (
    <div className="sg-modal-backdrop" onClick={onClose}>
      <div className="sg-modal" onClick={(e) => e.stopPropagation()}>
        <div className="sg-modal-head">
          <strong>蒙版局部重绘</strong>
          <button type="button" className="btn" onClick={onClose}>
            关闭
          </button>
        </div>
        <p className="muted" style={{ margin: "0 0 8px" }}>
          在图上涂白的区域会被重绘；黑区尽量保留。走宿主 /host/inpaint。
        </p>
        <canvas
          ref={canvasRef}
          className="sg-mask-canvas"
          onPointerDown={(e) => {
            drawing.current = true;
            (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
            paint(e);
          }}
          onPointerMove={paint}
          onPointerUp={() => {
            drawing.current = false;
          }}
        />
        <div className="field">
          <label>笔刷 {brush}px</label>
          <input
            type="range"
            min={8}
            max={80}
            value={brush}
            onChange={(e) => setBrush(Number(e.target.value))}
          />
        </div>
        <div className="field">
          <label>重绘提示词</label>
          <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={3} />
        </div>
        <div className="btn-row">
          <button
            type="button"
            className="btn"
            onClick={() => {
              const canvas = canvasRef.current;
              const img = imgRef.current;
              if (!canvas || !img) return;
              const ctx = canvas.getContext("2d");
              if (!ctx) return;
              ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
            }}
          >
            清除笔迹
          </button>
          <button
            type="button"
            className="btn primary"
            disabled={busy}
            onClick={() => {
              const mask = buildMask();
              if (!mask) return;
              onSubmit(mask, prompt);
            }}
          >
            {busy ? "重绘中…" : "提交重绘"}
          </button>
        </div>
      </div>
    </div>
  );
}
