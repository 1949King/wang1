/**
 * LibTV 向「AI 识图导入」弹窗（图三/图四）。
 * 识图任务：本地上传后写入参考图；无宿主视觉 API 时诚实提示，仍可作站位参考层插入。
 */
import { useRef, useState } from "react";

export type StageImportMode = "insert" | "overwrite";

export type StageImportResult = {
  dataUrl: string;
  fileName: string;
  mode: StageImportMode;
};

type Props = {
  open: boolean;
  onClose: () => void;
  onConfirm: (result: StageImportResult) => void;
};

export default function StageImportModal({ open, onClose, onConfirm }: Props) {
  const [tab, setTab] = useState<"local" | "history">("local");
  const [preview, setPreview] = useState<string | null>(null);
  const [fileName, setFileName] = useState("");
  const [mode, setMode] = useState<StageImportMode>("insert");
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  if (!open) return null;

  const pickFile = async (file: File | null) => {
    if (!file) return;
    const reader = new FileReader();
    const dataUrl = await new Promise<string>((resolve, reject) => {
      reader.onload = () => resolve(String(reader.result || ""));
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(file);
    });
    setPreview(dataUrl);
    setFileName(file.name);
  };

  const submit = async () => {
    if (!preview) return;
    setBusy(true);
    try {
      // 诚实：当前无云端识图；把图当作站位参考层交给导演台
      onConfirm({ dataUrl: preview, fileName, mode });
      onClose();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="sg-modal-backdrop" onClick={onClose}>
      <div
        className="sg-modal stage-import-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="AI 识图导入"
      >
        <header className="sg-modal-head">
          <h2>AI 识图导入</h2>
          <button type="button" className="sg-modal-x" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </header>

        <div className="sg-modal-tabs">
          <button
            type="button"
            className={tab === "local" ? "on" : ""}
            onClick={() => setTab("local")}
          >
            本地上传
          </button>
          <button
            type="button"
            className={tab === "history" ? "on" : ""}
            onClick={() => setTab("history")}
          >
            历史记录
          </button>
        </div>

        {tab === "local" ? (
          <div
            className={`stage-import-drop${preview ? " has-preview" : ""}`}
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              void pickFile(e.dataTransfer.files?.[0] || null);
            }}
          >
            {preview ? (
              <img src={preview} alt={fileName || "preview"} />
            ) : (
              <>
                <div className="stage-import-drop-title">
                  点击上传图片 或 拖拽本地图片至此上传
                </div>
                <div className="stage-import-drop-sub">
                  上传后画布将新建一个图片节点并自动替换当前图源
                </div>
              </>
            )}
            <input
              ref={inputRef}
              type="file"
              accept="image/*"
              hidden
              onChange={(e) => {
                const f = e.target.files?.[0] || null;
                e.target.value = "";
                void pickFile(f);
              }}
            />
          </div>
        ) : (
          <div className="stage-import-history">
            <p className="muted">暂无云端识图历史。请用「本地上传」。</p>
          </div>
        )}

        <div className="stage-import-scene-title">选择是否覆盖场景</div>
        <div className="stage-import-modes">
          <button
            type="button"
            className={`stage-import-mode${mode === "insert" ? " on" : ""}`}
            onClick={() => setMode("insert")}
          >
            <span className="radio" />
            <div>
              <strong>插入当前导演台</strong>
              <p>作为站位参考层插入，不覆盖当前全景、角色和机位</p>
            </div>
          </button>
          <button
            type="button"
            className={`stage-import-mode${mode === "overwrite" ? " on" : ""}`}
            onClick={() => setMode("overwrite")}
          >
            <span className="radio" />
            <div>
              <strong>覆盖当前导演台</strong>
              <p>作为站位参考层插入，覆盖当前全景、角色和机位</p>
            </div>
          </button>
        </div>

        <footer className="sg-modal-foot">
          <span className="muted tiny">
            关闭不会中断识图任务，生成站位参考后自动导入导演台（当前为本地参考层，无云端识图）
          </span>
          <button
            type="button"
            className={`btn${preview ? " primary" : ""}`}
            disabled={!preview || busy}
            onClick={() => void submit()}
          >
            {busy ? "处理中…" : "生成站位参考"}
          </button>
        </footer>
      </div>
    </div>
  );
}
