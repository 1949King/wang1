import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import {
  listImageModels,
  sendBlobToEditor,
  dataUrlToBlob,
  fetchPrefs,
  type ImageModelOption,
} from "./bridge";
import {
  cancelGeneration,
  cancelPool,
  isTerminal,
  runGeneration,
  runGenerationPool,
  type GenJob,
  type PoolItem,
} from "./generationQueue";
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
type BatchItem = PoolItem<Record<string, unknown>>;

const barWrap: CSSProperties = {
  height: 6,
  borderRadius: 3,
  background: "rgba(120,120,120,.22)",
  overflow: "hidden",
  marginTop: 6,
};
const barFill = (pct: number): CSSProperties => ({
  height: "100%",
  width: `${Math.max(0, Math.min(100, pct))}%`,
  background: "#2563eb",
  transition: "width .3s ease",
});
const genBox: CSSProperties = {
  border: "1px solid rgba(120,120,120,.28)",
  borderRadius: 8,
  padding: "8px 10px",
  marginTop: 8,
  fontSize: 12,
  lineHeight: 1.6,
};
const rowBetween: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
};
const stagePill: CSSProperties = {
  display: "inline-block",
  padding: "1px 8px",
  borderRadius: 999,
  background: "rgba(37,99,235,.12)",
  color: "#1d4ed8",
  fontSize: 11,
};
const itemRow: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  fontSize: 12,
  padding: "3px 0",
};

function fmtSec(ms: number): string {
  return `${(Math.max(0, ms) / 1000).toFixed(1)}s`;
}

export default function ImageStudio({ onOpenCanvas, onSyncModels, onSendToCanvas }: Props) {
  const [prompt, setPrompt] = useState("竖屏漫剧角色特写，电影光，高细节");
  const [models, setModels] = useState<ImageModelOption[]>([]);
  const [modelKey, setModelKey] = useState("");
  const [refUrl, setRefUrl] = useState("");
  const [count, setCount] = useState(1);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("就绪");
  const [results, setResults] = useState<ResultItem[]>([]);
  /** 单张生成时的任务快照（异步 · 真进度 · 可取消） */
  const [job, setJob] = useState<GenJob | null>(null);
  /** 批量生成时的逐条状态 */
  const [batch, setBatch] = useState<BatchItem[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  const running = useMemo(
    () => (job ? !isTerminal(job.status) : false) || batch.some((b) => !isTerminal(b.status as any)),
    [job, batch],
  );

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

  const pushResults = (urls: Array<{ url: string; prompt: string }>) => {
    if (!urls.length) return;
    const items: ResultItem[] = urls.map((u, i) => ({
      id: `img_${Date.now()}_${i}`,
      url: u.url,
      prompt: u.prompt,
      at: new Date().toLocaleTimeString(),
    }));
    setResults((prev) => [...items, ...prev].slice(0, 24));
  };

  const payloadFor = (p: string) => {
    const { channel_id, model } = parseKey();
    return {
      prompt: p,
      channel_id,
      model,
      reference_image: refUrl || "",
      size: "768x1280",
      quality: "standard",
    };
  };

  const onCancel = async () => {
    abortRef.current?.abort();
    if (job && !isTerminal(job.status)) {
      const r = await cancelGeneration(job.job_id);
      setStatus(r.ok ? "已取消（结果已丢弃）" : r.message || "取消失败");
    }
    if (batch.length) {
      await cancelPool(batch);
      setStatus("已取消批量任务");
    }
  };

  const onGenerate = async () => {
    const text = prompt.trim();
    if (!text) {
      setStatus("请填写提示词");
      return;
    }
    const ac = new AbortController();
    abortRef.current = ac;
    setBusy(true);

    try {
      if (count <= 1) {
        setBatch([]);
        setJob(null);
        setStatus("已提交，等待渠道响应…");
        const { job: final, result } = await runGeneration("image", payloadFor(text), {
          label: text.slice(0, 24),
          maxAttempts: 1,
          signal: ac.signal,
          onProgress: (j) => {
            setJob(j);
            // 诚实展示：有真百分比才写 %，否则只显示阶段 + 已用时
            setStatus(
              j.progress !== null
                ? `${j.stage_label} ${j.progress}%（${fmtSec(j.elapsed_ms)}）`
                : `${j.stage_label} · 已用时 ${fmtSec(j.elapsed_ms)}`,
            );
          },
        });
        const url = String(result.image_data_url || result.image_url || "");
        if (!url) throw new Error("渠道未返回图像");
        pushResults([{ url, prompt: text }]);
        setJob(final);
        setStatus(`生图完成（${fmtSec(final.elapsed_ms)}）`);
      } else {
        setJob(null);
        const tasks = Array.from({ length: count }, (_, i) => ({
          key: `t${i}`,
          label: `第 ${i + 1} 张`,
          payload: payloadFor(text),
        }));
        // 并发池：逐条进度、逐条重试（后端退避），互不阻塞
        const all = await runGenerationPool("image", tasks, {
          concurrency: Math.min(3, count),
          maxAttempts: 2,
          signal: ac.signal,
          onItem: (_it, _i, list) => {
            setBatch([...list]);
            const done = list.filter((x) => x.status === "done").length;
            const failed = list.filter((x) => x.status === "failed").length;
            const active = list.find((x) => x.status === "running" || x.status === "queued");
            setStatus(
              `批量 ${done}/${list.length} 完成${failed ? ` · ${failed} 失败` : ""}` +
                (active ? ` · 当前：${active.stage_label}` : ""),
            );
          },
        });
        setBatch(all);
        const ok = all.filter((x) => x.status === "done" && (x.result?.image_data_url || x.result?.image_url));
        pushResults(
          ok.map((x) => ({ url: String(x.result?.image_data_url || x.result?.image_url || ""), prompt: text })),
        );
        setStatus(`批量生图完成：成功 ${ok.length}/${all.length}（每条可单独重试）`);
      }
    } catch (e: any) {
      if (e?.name === "AbortError") setStatus("已取消");
      else setStatus(String(e?.message || e));
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
  };

  const retryOne = async (index: number) => {
    const it = batch[index];
    if (!it) return;
    const ac = new AbortController();
    abortRef.current = ac;
    const tasks = [{ key: it.key, label: it.label, payload: payloadFor(prompt.trim()) }];
    const [out] = await runGenerationPool("image", tasks, {
      concurrency: 1,
      maxAttempts: 2,
      signal: ac.signal,
      onItem: (_x, _i, list) => {
        setBatch((prev) => {
          const next = [...prev];
          next[index] = list[0];
          return next;
        });
      },
    });
    if (out.status === "done") {
      const url = String(out.result?.image_data_url || out.result?.image_url || "");
      if (url) pushResults([{ url, prompt: prompt.trim() }]);
    }
    abortRef.current = null;
  };

  return (
    <main className="studio-page">
      <aside className="studio-side">
        <h1>生图工作台</h1>
        <p className="muted">任务制：提交即返回，进度真实、可随时取消</p>
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
          <label>数量（&gt;1 走并发队列，逐条进度/重试）</label>
          <select value={count} onChange={(e) => setCount(Number(e.target.value))}>
            {[1, 2, 3, 4].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
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

        <div className="btn-row">
          <button type="button" className="btn primary" disabled={busy} onClick={onGenerate}>
            {busy ? "生成中…" : count > 1 ? `批量生成 ${count} 张` : "生成"}
          </button>
          {running ? (
            <button type="button" className="btn" onClick={onCancel}>
              取消
            </button>
          ) : null}
        </div>
        <div className="btn-row">
          <button type="button" className="btn teal" onClick={onSyncModels}>
            同步模型池
          </button>
          <button type="button" className="btn" onClick={onOpenCanvas}>
            打开画布
          </button>
        </div>

        {job && !isTerminal(job.status) ? (
          <div style={genBox}>
            <div style={rowBetween}>
              <span style={stagePill}>{job.stage_label}</span>
              <span className="muted">已用时 {fmtSec(job.elapsed_ms)}</span>
            </div>
            {job.progress !== null ? (
              <div style={barWrap}>
                <div style={barFill(job.progress)} />
              </div>
            ) : (
              <p className="muted" style={{ margin: "6px 0 0" }}>
                上游未提供进度信号 · 按阶段提示
              </p>
            )}
            {job.note ? <p className="muted" style={{ margin: "4px 0 0" }}>{job.note}</p> : null}
            {job.attempts > 1 ? (
              <p className="muted" style={{ margin: "4px 0 0" }}>
                第 {job.attempts}/{job.max_attempts} 次尝试
              </p>
            ) : null}
          </div>
        ) : null}

        {batch.length > 0 ? (
          <div style={genBox}>
            {batch.map((b, i) => (
              <div key={b.key} style={itemRow}>
                <span style={{ minWidth: 54 }}>{b.label}</span>
                <span style={stagePill}>{b.stage_label}</span>
                <span style={{ flex: 1 }}>
                  {b.progress !== null ? (
                    <span style={barWrap}>
                      <span style={{ ...barFill(b.progress), display: "block" }} />
                    </span>
                  ) : null}
                </span>
                <span className="muted">{fmtSec(b.elapsed_ms)}</span>
                {b.status === "failed" ? (
                  <button type="button" className="btn" style={{ padding: "0 6px" }} onClick={() => retryOne(i)}>
                    重试
                  </button>
                ) : null}
              </div>
            ))}
          </div>
        ) : null}

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
