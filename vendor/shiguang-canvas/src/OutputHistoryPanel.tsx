/**
 * OutputHistoryPanel.tsx — 「输出历史」面板（2026-10-06 对标参考产品）。
 *
 * 定位：**抽卡/生成闭环的复盘端**。此前项目的账本（`draw_book`）、生成任务表、
 * 画布产物都在，但**用户没有任何地方能看到"我做过什么、哪张最好、用了什么提示词和种子"**。
 *
 * 数据来源与判据全在 `outputHistory.ts`（纯函数、已单测）；
 * 本组件只管画，并且**只读**画布 store（选中 = `setSelected`，不改内容）。
 *
 * 纪律：
 *  · 搜索范围与参考产品对齐（提示词 / 输出内容 / 模型），并**多给一个种子**；
 *  · 「复制配方」是**兑现口**：把提示词+种子+模型抄走（无种子时如实不写种子，不编造）；
 *  · 空状态明说"开始第一次生成后会自动记录"，不假装有数据。
 */
import { useEffect, useMemo, useState } from "react";

import {
  CATEGORY_LABEL,
  collectHistory,
  countByCategory,
  filterHistory,
  recipeOf,
  type HistoryCategory,
} from "./outputHistory";
import { useCanvasStore } from "./store";
import "./outputHistory.css";

const PIN_KEY = "shiguang-canvas:output-history:pinned";

export default function OutputHistoryPanel({ onClose }: { onClose: () => void }) {
  const nodes = useCanvasStore((s) => s.nodes);
  const setSelected = useCanvasStore((s) => s.setSelected);
  const [category, setCategory] = useState<HistoryCategory | "all">("all");
  const [query, setQuery] = useState("");
  const [pinned, setPinned] = useState(() => {
    try {
      return localStorage.getItem(PIN_KEY) === "1";
    } catch {
      return false;
    }
  });
  const [copied, setCopied] = useState("");

  useEffect(() => {
    try {
      localStorage.setItem(PIN_KEY, pinned ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, [pinned]);

  const all = useMemo(() => collectHistory(nodes as never), [nodes]);
  const counts = useMemo(() => countByCategory(all), [all]);
  const rows = useMemo(
    () => filterHistory(all, { category, query }),
    [all, category, query],
  );

  const copyRecipe = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(text.slice(0, 18));
      setTimeout(() => setCopied(""), 1500);
    } catch {
      setCopied("");
    }
  };

  const tabs: Array<[HistoryCategory | "all", string]> = [
    ["all", "全部"],
    ["text", CATEGORY_LABEL.text],
    ["image", CATEGORY_LABEL.image],
    ["video", CATEGORY_LABEL.video],
    ["audio", CATEGORY_LABEL.audio],
  ];

  return (
    <div className="oh-panel" data-pinned={pinned ? "1" : "0"}>
      <header className="oh-head">
        <span className="oh-title">输出历史</span>
        <span className="oh-count">共 {counts.all} 条</span>
        <span className="oh-spacer" />
        <label className="oh-pin" title="固定面板：勾选后下次打开画布自动显示">
          <input
            type="checkbox"
            checked={pinned}
            onChange={(e) => setPinned(e.target.checked)}
          />
          固定面板
        </label>
        <button type="button" className="oh-close" onClick={onClose} title="关闭">
          ×
        </button>
      </header>

      <div className="oh-toolbar">
        <div className="oh-tabs">
          {tabs.map(([key, label]) => (
            <button
              type="button"
              key={key}
              className={`oh-tab${category === key ? " on" : ""}`}
              onClick={() => setCategory(key)}
            >
              {label}
              <i>{counts[key] ?? 0}</i>
            </button>
          ))}
        </div>
        <input
          className="oh-search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜索提示词、输出内容或模型"
        />
      </div>

      {rows.length === 0 ? (
        <div className="oh-empty">
          {all.length === 0
            ? "暂无生成记录，开始第一次生成后会自动记录"
            : "没有匹配的记录（换个关键词或切回「全部」）"}
        </div>
      ) : (
        <ul className="oh-list">
          {rows.map((e) => (
            <li key={e.id} className="oh-row">
              <div className="oh-thumb">
                {e.category === "image" && e.assetUrl ? (
                  <img src={e.assetUrl} alt="" loading="lazy" />
                ) : e.category === "video" && e.assetUrl ? (
                  <img src={e.assetUrl} alt="" loading="lazy" />
                ) : (
                  <span className="oh-thumb-tag">{CATEGORY_LABEL[e.category]}</span>
                )}
              </div>
              <div className="oh-main">
                <div className="oh-row-title">{e.title}</div>
                {e.prompt ? <div className="oh-row-prompt">{e.prompt}</div> : null}
                <div className="oh-meta">
                  <span className="oh-chip">{e.kind}</span>
                  {e.model ? <span className="oh-chip">{e.model}</span> : null}
                  {e.seed != null ? (
                    <span className="oh-chip" title={e.seedSent ? "渠道已收到该种子（可复现）" : "渠道未透传，不可复现"}>
                      seed {e.seed}
                      {e.seedSent ? "" : "?"}
                    </span>
                  ) : null}
                  {e.score != null ? (
                    <span className="oh-chip" title="代理分（几何/清晰度/崩图闸门），非审美真值">
                      代理分 {e.score.toFixed(2)}
                    </span>
                  ) : null}
                </div>
              </div>
              <div className="oh-actions">
                <button
                  type="button"
                  onClick={() => {
                    setSelected(e.id);
                    onClose();
                  }}
                  title="定位到该节点"
                >
                  定位
                </button>
                <button
                  type="button"
                  onClick={() => void copyRecipe(recipeOf(e))}
                  title="复制提示词 + 种子 + 模型（抽卡配方）"
                >
                  {copied && copied === recipeOf(e).slice(0, 18) ? "已复制" : "复制配方"}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
