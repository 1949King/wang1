import { useCallback, useEffect, useState } from "react";
import {
  generateImageViaHost,
  listImageModels,
  sendBlobToEditor,
  dataUrlToBlob,
  fetchPrefs,
  type ImageModelOption,
} from "./bridge";
import { addAsset, listAssets } from "./localLibrary";

type Props = {
  onOpenCanvas: () => void;
  onSyncModels: () => void;
  onSendToCanvas: (payload: {
    kind: "image";
    title: string;
    imageUrl: string;
    prompt: string;
  }) => void;
};

type ResultItem = { id: string; url: string; prompt: string; at: string };

export default function ImageStudio({ onOpenCanvas, onSyncModels, onSendToCanvas }: Props) {
  const [prompt, setPrompt] = useState("竖屏漫剧角色特写，电影光，高细节");
  const [models, setModels] = useState<ImageModelOption[]>([]);
  const [modelKey, setModelKey] = useState("");
  const [refUrl, setRefUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("就绪");
  const [results, setResults] = useState<ResultItem[]>([]);

  const refreshModels = useCallback(async () => {
    const { models: ms, default: def } = await listImageModels();
    setModels(ms);
    if (!modelKey) {
      if (def && def.includes("::")) {
        const [cid, ...rest] = def.split("::");
        const hit = ms.find((m) => m.channel_id === cid && m.model === rest.join("::"));
        if (hit) setModelKey(`${hit.channel_id}::${hit.model}`);
        else if (ms[0]) setModelKey(`${ms[0].channel_id}::${ms[0].model}`);
      } else if (ms[0]) setModelKey(`${ms[0].channel_id}::${ms[0].model}`);
    }
    setStatus(ms.length ? `已加载 ${ms.length} 个生图模型` : "无生图模型，请同步模型池并配置 Key");
  }, [modelKey]);

  useEffect(() => {
    refreshModels();
  }, [refreshModels]);

  const parseKey = () => {
    const [channel_id, ...rest] = modelKey.split("::");
    return { channel_id: channel_id || "", model: rest.join("::") };
  };

  const onGenerate = async () => {
    if (!prompt.trim()) {
      setStatus("请填写提示词");
      return;
    }
    setBusy(true);
    setStatus("正在生图…");
    try {
      const { channel_id, model } = parseKey();
      const res = await generateImageViaHost({
        prompt: prompt.trim(),
        channel_id,
        model,
        reference_image: refUrl || undefined,
        size: "768x1280",
      });
      if (!res.ok || !(res.image_data_url || res.image_url)) {
        setStatus(res.message || "生图失败");
        return;
      }
      const url = res.image_data_url || res.image_url || "";
      const item: ResultItem = {
        id: `img_${Date.now()}`,
        url,
        prompt: prompt.trim(),
        at: new Date().toLocaleTimeString(),
      };
      setResults((prev) => [item, ...prev].slice(0, 24));
      setStatus(res.message || "生图完成");
    } catch (e: any) {
      setStatus(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="studio-page">
      <aside className="studio-side">
        <h1>生图工作台</h1>
        <p className="muted">走宿主 AIGC 渠道（需模型广场 Key + 同步模型池）</p>
        <div className="field">
          <label>提示词</label>
          <textarea rows={5} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
        </div>
        <div className="field">
          <label>模型</label>
          <select value={modelKey} onChange={(e) => setModelKey(e.target.value)}>
            {models.length === 0 ? (
              <option value="">无可用模型</option>
            ) : (
              models.map((m) => (
                <option key={`${m.channel_id}::${m.model}`} value={`${m.channel_id}::${m.model}`}>
                  {m.label}
                </option>
              ))
            )}
          </select>
        </div>
        <div className="field">
          <label>参考图（可选，img2img）</label>
          {refUrl ? (
            <div className="frame-row">
              <img className="frame-thumb" src={refUrl} alt="ref" />
              <button type="button" className="btn" onClick={() => setRefUrl("")}>
                清除
              </button>
            </div>
          ) : null}
          <label className="file-btn">
            选择图片…
            <input
              type="file"
              accept="image/*"
              hidden
              onChange={async (e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (!f) return;
                const reader = new FileReader();
                reader.onload = () => setRefUrl(String(reader.result || ""));
                reader.readAsDataURL(f);
              }}
            />
          </label>
        </div>
        <button type="button" className="btn primary" disabled={busy} onClick={onGenerate}>
          {busy ? "生成中…" : "生成"}
        </button>
        <div className="btn-row">
          <button type="button" className="btn teal" onClick={onSyncModels}>
            同步模型池
          </button>
          <button type="button" className="btn" onClick={onOpenCanvas}>
            打开画布
          </button>
        </div>
        <p className="studio-status">{status}</p>
        <p className="muted">本地资产 {listAssets().length} 条</p>
      </aside>
      <section className="studio-results">
        {results.length === 0 ? (
          <div className="studio-empty">生成结果会出现在这里</div>
        ) : (
          <div className="studio-grid">
            {results.map((r) => (
              <article key={r.id} className="studio-card">
                <img src={r.url} alt="" />
                <div className="studio-card-actions">
                  <button
                    type="button"
                    className="btn"
                    onClick={() => {
                      addAsset({ title: r.prompt.slice(0, 24) || "生图", kind: "image", url: r.url, prompt: r.prompt });
                      setStatus("已保存到我的资产");
                    }}
                  >
                    存资产
                  </button>
                  <button
                    type="button"
                    className="btn primary"
                    onClick={() =>
                      onSendToCanvas({
                        kind: "image",
                        title: r.prompt.slice(0, 20) || "生图",
                        imageUrl: r.url,
                        prompt: r.prompt,
                      })
                    }
                  >
                    进画布
                  </button>
                  <button
                    type="button"
                    className="btn teal"
                    onClick={async () => {
                      try {
                        const blob = await dataUrlToBlob(r.url);
                        const prefs = await fetchPrefs();
                        const msg = await sendBlobToEditor(blob, `studio_${Date.now()}.png`, prefs, {
                          title: r.prompt.slice(0, 40) || "生图入轨",
                        });
                        setStatus(msg || "已入轨");
                      } catch (e: any) {
                        setStatus(String(e?.message || e));
                      }
                    }}
                  >
                    入轨
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
