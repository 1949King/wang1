/** 蒙版局部重绘对话框 — 白笔=重绘区。
 *  T3：mode 三选（inpaint 默认走原 onSubmit；remove/outpaint 走宿主本地优先 + 可选网关）。 */
import { useEffect, useRef, useState } from "react";
import { gatewayEdit } from "./bridge";

type EditMode = "inpaint" | "remove" | "outpaint";

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
  const [mode, setMode] = useState<EditMode>("inpaint");
  const [megapixels, setMegapixels] = useState(1.0);
  const [gwBusy, setGwBusy] = useState(false);
  const [resultUrl, setResultUrl] = useState("");
  const [resultMsg, setResultMsg] = useState("");

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

  // 干净原图 data URL（与蒙版同尺寸，供 remove/outpaint 走宿主）
  const buildImageDataUrl = () => {
    const canvas = canvasRef.current;
    const img = imgRef.current;
    if (!canvas || !img) return "";
    const tmp = document.createElement("canvas");
    tmp.width = canvas.width;
    tmp.height = canvas.height;
    const ctx = tmp.getContext("2d");
    if (!ctx) return "";
    ctx.drawImage(img, 0, 0, tmp.width, tmp.height);
    return tmp.toDataURL("image/png");
  };

  const handleSubmit = async () => {
    const mask = buildMask();
    // 默认 inpaint：走原 onSubmit（CanvasShell 零改动）
    if (mode === "inpaint") {
      if (!mask) return;
      onSubmit(mask, prompt);
      return;
    }
    // remove/outpaint：宿主本地优先 + 可选网关
    const image = buildImageDataUrl();
    if (!image) return;
    if (mode === "remove" && !mask) return;
    setGwBusy(true);
    setResultUrl("");
    setResultMsg("");
    const res = await gatewayEdit({
      mode,
      image,
      mask: mode === "outpaint" ? "" : mask,
      prompt,
      megapixels,
    });
    setGwBusy(false);
    if (res.ok && res.image_data_url) {
      setResultUrl(res.image_data_url);
      setResultMsg(res.message || "处理成功");
    } else {
      setResultMsg(res.guidance || res.message || "处理失败");
    }
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
        <div className="btn-row" style={{ margin: "0 0 8px" }}>
          {(["inpaint", "remove", "outpaint"] as EditMode[]).map((m) => (
            <button
              key={m}
              type="button"
              className={mode === m ? "btn primary" : "btn"}
              onClick={() => {
                setMode(m);
                setResultUrl("");
                setResultMsg("");
              }}
            >
              {m === "inpaint" ? "语义重绘" : m === "remove" ? "物体移除" : "扩图"}
            </button>
          ))}
        </div>
        <p className="muted" style={{ margin: "0 0 8px" }}>
          {mode === "inpaint"
            ? "涂白区域按提示词重绘，黑区逐字节保留。走宿主 /host/inpaint。"
            : mode === "remove"
              ? "涂白区域将被移除（本地 LaMa/SD1.5 优先，可选网关）。"
              : "向外扩展画面（单图 + megapixels，走可选网关；未启用诚实提示）。"}
        </p>
        {mode === "outpaint" && (
          <div className="field">
            <label>扩图像素（megapixels）</label>
            <input
              type="number"
              min={0.5}
              max={8}
              step={0.5}
              value={megapixels}
              onChange={(e) => setMegapixels(Number(e.target.value))}
            />
          </div>
        )}
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
            disabled={busy || gwBusy}
            onClick={handleSubmit}
          >
            {busy || gwBusy
              ? "处理中…"
              : mode === "inpaint"
                ? "提交重绘"
                : mode === "remove"
                  ? "提交移除"
                  : "提交扩图"}
          </button>
        </div>
        {resultUrl && (
          <div className="field">
            <label>处理结果</label>
            <img src={resultUrl} alt="编辑结果" style={{ maxWidth: "100%", borderRadius: 8 }} />
            <div className="btn-row">
              <a className="btn" href={resultUrl} download="shiguang-edit.png">
                下载结果
              </a>
            </div>
          </div>
        )}
        {resultMsg && (
          <p className="muted" style={{ margin: "8px 0 0", whiteSpace: "pre-wrap" }}>
            {resultMsg}
          </p>
        )}
      </div>
    </div>
  );
}
