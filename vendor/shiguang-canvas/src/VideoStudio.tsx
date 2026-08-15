import { useCallback, useEffect, useState } from "react";
import {
  generateVideoViaHost,
  listVideoModels,
  sendBlobToEditor,
  fetchPrefs,
  type VideoModelOption,
} from "./bridge";
import { addAsset, listAssets } from "./localLibrary";

type Props = {
  onOpenCanvas: () => void;
  onSyncModels: () => void;
  onSendToCanvas: (payload: {
    kind: "video";
    title: string;
    videoUrl: string;
    posterUrl?: string;
    prompt: string;
  }) => void;
};

type ResultItem = { id: string; url: string; prompt: string; at: string };

export default function VideoStudio({ onOpenCanvas, onSyncModels, onSendToCanvas }: Props) {
  const [prompt, setPrompt] = useState("镜头缓缓推近角色，夜景霓虹，电影感");
  const [models, setModels] = useState<VideoModelOption[]>([]);
  const [modelKey, setModelKey] = useState("");
  const [duration, setDuration] = useState(5);
  const [refUrl, setRefUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("就绪");
  const [results, setResults] = useState<ResultItem[]>([]);

  const refreshModels = useCallback(async () => {
    const { models: ms, default: def } = await listVideoModels();
    setModels(ms);
    if (!modelKey) {
      if (def && def.includes("::")) {
        const [cid, ...rest] = def.split("::");
        const hit = ms.find((m) => m.channel_id === cid && m.model === rest.join("::"));
        if (hit) setModelKey(`${hit.channel_id}::${hit.model}`);
        else if (ms[0]) setModelKey(`${ms[0].channel_id}::${ms[0].model}`);
      } else if (ms[0]) setModelKey(`${ms[0].channel_id}::${ms[0].model}`);
    }
    setStatus(
      ms.length
        ? `已加载 ${ms.length} 个生视频模型`
        : "无生视频模型。请在模型管理配置含视频能力的 Key，再同步模型池。",
    );
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
    if (!models.length) {
      setStatus("没有可用生视频模型，无法生成（不会假成功）");
      return;
    }
    setBusy(true);
    setStatus("正在生视频（可能需要 1–3 分钟）…");
    try {
      const { channel_id, model } = parseKey();
      const res = await generateVideoViaHost({
        prompt: prompt.trim(),
        channel_id,
        model,
        duration,
        reference_image: refUrl || undefined,
        size: "720x1280",
      });
      if (!res.ok || !res.video_url) {
        setStatus(res.message || "生视频失败");
        return;
      }
      const item: ResultItem = {
        id: `vid_${Date.now()}`,
        url: res.video_url,
        prompt: prompt.trim(),
        at: new Date().toLocaleTimeString(),
      };
      setResults((prev) => [item, ...prev].slice(0, 12));
      setStatus(res.message || "生视频完成");
    } catch (e: any) {
      setStatus(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="studio-page">
      <aside className="studio-side">
        <h1>视频创作台</h1>
        <p className="muted">真实调用宿主视频渠道；无模型或 API 失败会明确报错，不做假成功。</p>
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
          <label>时长（秒）</label>
          <input
            type="number"
            min={2}
            max={10}
            value={duration}
            onChange={(e) => setDuration(Number(e.target.value) || 5)}
          />
        </div>
        <div className="field">
          <label>首帧参考（可选 I2V）</label>
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
          {busy ? "生成中…" : "生成视频"}
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
          <div className="studio-empty">视频结果会出现在这里</div>
        ) : (
          <div className="studio-grid">
            {results.map((r) => (
              <article key={r.id} className="studio-card">
                <video src={r.url} controls playsInline />
                <div className="studio-card-actions">
                  <button
                    type="button"
                    className="btn"
                    onClick={() => {
                      addAsset({
                        title: r.prompt.slice(0, 24) || "视频",
                        kind: "video",
                        url: r.url,
                        prompt: r.prompt,
                      });
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
                        kind: "video",
                        title: r.prompt.slice(0, 20) || "视频",
                        videoUrl: r.url,
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
                        const resp = await fetch(r.url);
                        const blob = await resp.blob();
                        const prefs = await fetchPrefs();
                        const msg = await sendBlobToEditor(blob, `studio_${Date.now()}.mp4`, prefs, {
                          title: r.prompt.slice(0, 40) || "视频入轨",
                          duration_sec: duration,
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
