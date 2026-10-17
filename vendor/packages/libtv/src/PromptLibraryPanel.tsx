import { useCallback, useEffect, useMemo, useState } from "react";
import ConfirmDialog from "./ConfirmDialog";
import PromptCoverImage from "./PromptCoverImage";
import PromptPreviewDialog from "./PromptPreviewDialog";
import {
  addCustomPromptSource,
  categoriesGrouped,
  fetchPromptLibrary,
  loadPromptSources,
  maturityLabel,
  refreshAllPromptSources,
  savePromptSources,
  toggleFavorite,
  type Maturity,
  type PromptItem,
  type PromptSource,
} from "./promptLibrary";
import { upsertPromptFromCommunity } from "./localLibrary";

export type PromptLibraryPanelProps = {
  onApply: (item: PromptItem) => void;
  onStatus?: (msg: string) => void;
  variant?: "sidebar" | "page";
};

type PendingConfirm =
  | { kind: "adult-source"; sourceId: string }
  | { kind: "custom-adult" }
  | null;

export default function PromptLibraryPanel({
  onApply,
  onStatus,
  variant = "sidebar",
}: PromptLibraryPanelProps) {
  const isPage = variant === "page";
  const [sources, setSources] = useState<PromptSource[]>(() => loadPromptSources());
  const [keyword, setKeyword] = useState("");
  const [categoryId, setCategoryId] = useState("all");
  const [tag, setTag] = useState("");
  const [maturity, setMaturity] = useState<Maturity | "all">("all");
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<PromptItem[]>([]);
  const [tags, setTags] = useState<string[]>([]);
  const [presentCategoryIds, setPresentCategoryIds] = useState<string[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [customName, setCustomName] = useState("");
  const [customUrl, setCustomUrl] = useState("");
  const [customAdult, setCustomAdult] = useState(false);
  const [pending, setPending] = useState<PendingConfirm>(null);
  const [previewItem, setPreviewItem] = useState<PromptItem | null>(null);
  const pageSize = isPage ? 24 : 20;

  const grouped = useMemo(() => categoriesGrouped(), []);
  const presentSet = useMemo(() => new Set(presentCategoryIds), [presentCategoryIds]);

  const loadPage = useCallback(
    async (opts?: { network?: boolean; quiet?: boolean }): Promise<number> => {
      const network = opts?.network !== false;
      if (!opts?.quiet) setLoading(true);
      try {
        const res = await fetchPromptLibrary({
          sources,
          keyword,
          categoryId,
          tag: tag || undefined,
          maturity,
          favoritesOnly,
          page,
          pageSize,
          network,
        });
        setItems(res.items);
        setTags(res.tags.slice(0, 40));
        setPresentCategoryIds(res.categoryIds);
        setTotal(res.total);
        return res.total;
      } catch (e) {
        onStatus?.(`提示词库加载失败：${e}`);
        return 0;
      } finally {
        if (!opts?.quiet) setLoading(false);
      }
    },
    [sources, keyword, categoryId, tag, maturity, favoritesOnly, page, pageSize, onStatus],
  );

  // 首屏本地+缓存秒开；空闲后后台联网补齐远程（渐进，不挡画布交互）
  useEffect(() => {
    let cancelled = false;
    let idleId = 0;
    let timer = 0;
    void loadPage({ network: false }).then(() => {
      if (cancelled) return;
      const runBg = () => {
        if (cancelled) return;
        onStatus?.("正在后台拉取社区提示词源…");
        void loadPage({ network: true, quiet: true }).then((n) => {
          if (cancelled) return;
          if (n >= 2500) {
            onStatus?.(`提示词库已就绪：${n} 条（含社区离线包）`);
          } else if (n >= 500) {
            onStatus?.(`提示词库 ${n} 条（部分源未缓存，可点「同步源」补全）`);
          } else {
            onStatus?.(`提示词库 ${n} 条离线；点「同步源」经宿主拉取社区库（需联网）`);
          }
        });
      };
      if (typeof window !== "undefined" && "requestIdleCallback" in window) {
        idleId = window.requestIdleCallback(runBg, { timeout: 2500 });
      } else {
        timer = setTimeout(runBg, 600);
      }
    });
    return () => {
      cancelled = true;
      if (idleId && "cancelIdleCallback" in window) window.cancelIdleCallback(idleId);
      if (timer) window.clearTimeout(timer);
    };
  }, [loadPage, onStatus]);

  useEffect(() => {
    setPage(1);
  }, [keyword, categoryId, tag, maturity, favoritesOnly]);

  const onRefresh = async () => {
    setRefreshing(true);
    onStatus?.("正在同步社区提示词源…");
    try {
      const r = await refreshAllPromptSources(sources);
      const extra = r.fail ? `，失败 ${r.fail}` : "";
      onStatus?.(`提示词库已更新：${r.total} 条（${r.ok} 源成功${extra}）`);
      setPage(1);
      await loadPage({ network: true });
    } catch (e) {
      onStatus?.(`同步失败：${e}`);
    } finally {
      setRefreshing(false);
    }
  };

  const applySourceToggle = (id: string) => {
    const next = sources.map((s) => (s.id === id ? { ...s, enabled: !s.enabled } : s));
    setSources(next);
    savePromptSources(next);
  };

  const toggleSource = (id: string) => {
    const target = sources.find((s) => s.id === id);
    if (target?.adult && !target.enabled) {
      setPending({ kind: "adult-source", sourceId: id });
      return;
    }
    applySourceToggle(id);
  };

  const onAddCustom = () => {
    if (!customUrl.trim()) {
      onStatus?.("请填写 GitHub raw JSON URL");
      return;
    }
    if (customAdult) {
      setPending({ kind: "custom-adult" });
      return;
    }
    commitCustomSource(false);
  };

  const commitCustomSource = (adult: boolean) => {
    const next = addCustomPromptSource({
      name: customName || "自定义源",
      url: customUrl.trim(),
      adult,
    });
    setSources(next);
    setCustomName("");
    setCustomUrl("");
    setCustomAdult(false);
    onStatus?.("已添加自定义提示词源，请点「同步源」拉取");
  };

  const onConfirmPending = () => {
    if (!pending) return;
    if (pending.kind === "adult-source") {
      applySourceToggle(pending.sourceId);
    } else if (pending.kind === "custom-adult") {
      commitCustomSource(true);
    }
    setPending(null);
  };

  const onToggleFav = (item: PromptItem) => {
    const now = toggleFavorite(item.sourceId, item.id);
    onStatus?.(now ? `已收藏：${item.title}` : `已取消收藏：${item.title}`);
    void loadPage({ network: true, quiet: true });
  };

  const onSaveLocal = (item: PromptItem) => {
    try {
      upsertPromptFromCommunity({
        title: item.title,
        prompt: item.prompt,
        tags: [...item.tags, item.category, "社区库"],
      });
      onStatus?.(`已保存到「我的本地提示词」：${item.title}`);
    } catch (e) {
      onStatus?.(`保存本地失败：${e}`);
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const confirmMessage =
    pending?.kind === "adult-source"
      ? "即将启用「成人向 18+」提示词源。\n内容仅面向成年人，禁止未成年人相关描述。\n确认启用？"
      : pending?.kind === "custom-adult"
        ? "将此自定义源标记为成人向 18+，确认继续？"
        : "";

  return (
    <div className={`prompt-lib${isPage ? " prompt-lib-page" : ""}`}>
      <ConfirmDialog
        open={!!pending}
        title="成人内容确认"
        message={confirmMessage}
        confirmLabel="启用"
        cancelLabel="取消"
        danger
        onConfirm={onConfirmPending}
        onCancel={() => setPending(null)}
      />
      <PromptPreviewDialog
        item={previewItem}
        onClose={() => setPreviewItem(null)}
        onApply={onApply}
        onToggleFavorite={(it) => {
          onToggleFav(it);
          setPreviewItem((cur) =>
            cur && cur.sourceId === it.sourceId && cur.id === it.id
              ? { ...cur, favorite: !cur.favorite }
              : cur,
          );
        }}
        onStatus={onStatus}
      />
      <div className="prompt-lib-toolbar">
        <input
          className="prompt-lib-search"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          placeholder="搜索标题 / 提示词 / 标签"
        />
        <button
          type="button"
          className={`btn${favoritesOnly ? " primary" : ""}`}
          onClick={() => setFavoritesOnly((v) => !v)}
        >
          {favoritesOnly ? "★ 收藏中" : "☆ 我的收藏"}
        </button>
        <button type="button" className="btn" onClick={() => void onRefresh()} disabled={refreshing}>
          {refreshing ? "同步中…" : "同步源"}
        </button>
      </div>
      <div className="prompt-lib-filters">
        <select value={maturity} onChange={(e) => setMaturity(e.target.value as Maturity | "all")}>
          <option value="all">全部尺度</option>
          <option value="sfw">全年龄</option>
          <option value="mature">成熟向</option>
          <option value="nsfw">成人向 18+</option>
        </select>
        <select value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
          <option value="all">全部分类</option>
          {grouped.map((g) => (
            <optgroup key={g.group} label={g.group}>
              {g.items.map((c) => (
                <option key={c.id} value={c.id} disabled={presentSet.size > 0 && !presentSet.has(c.id)}>
                  {c.label}
                  {c.maturity === "nsfw" ? " ·18+" : c.maturity === "mature" ? " ·成熟" : ""}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
        <select value={tag} onChange={(e) => setTag(e.target.value)}>
          <option value="">全部标签</option>
          {tags.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </div>
      <details className="prompt-lib-sources" open={isPage}>
        <summary>
          数据源（{sources.filter((s) => s.enabled).length}/{sources.length} 启用）· 远程默认开启，后台自动同步
        </summary>
        <ul>
          {sources.map((s) => (
            <li key={s.id}>
              <label>
                <input type="checkbox" checked={s.enabled} onChange={() => toggleSource(s.id)} />
                {s.name}
                {s.adult ? <span className="prompt-badge nsfw">18+</span> : null}
              </label>
            </li>
          ))}
        </ul>
        <div className="prompt-lib-custom">
          <input
            value={customName}
            onChange={(e) => setCustomName(e.target.value)}
            placeholder="自定义源名称"
          />
          <input
            value={customUrl}
            onChange={(e) => setCustomUrl(e.target.value)}
            placeholder="GitHub raw .json URL"
          />
          <label className="prompt-lib-adult-check">
            <input
              type="checkbox"
              checked={customAdult}
              onChange={(e) => setCustomAdult(e.target.checked)}
            />
            标记为 18+
          </label>
          <button type="button" className="btn" onClick={onAddCustom}>
            添加源
          </button>
        </div>
        <p className="hint">
          离线 bundled 约 3600+ 条（7 社区库 + StimQQ + NeXra + 拾光精选）；宿主 bridge 可读 public/prompts。首次若条数偏少请点「同步源」。
        </p>
      </details>
      {loading ? (
        <p className="hint">加载中…</p>
      ) : items.length === 0 ? (
        <p className="hint">
          {favoritesOnly
            ? "收藏夹为空。在条目上点 ★ 即可收藏。"
            : "暂无条目。正在加载本地/社区源，请稍候或点「同步源」。"}
        </p>
      ) : (
        <ul className={`prompt-lib-list${isPage ? " prompt-lib-grid" : ""}`}>
          {items.map((item) => (
            <li
              key={`${item.sourceId}:${item.id}`}
              className="prompt-lib-card"
              onClick={() => setPreviewItem(item)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setPreviewItem(item);
                }
              }}
              role="button"
              tabIndex={0}
              title="点击查看完整提示词与参考图"
            >
              {item.coverUrl ? (
                <PromptCoverImage url={item.coverUrl} className="prompt-lib-cover" fit="cover" />
              ) : (
                <div className="prompt-lib-cover placeholder" title="该条目无封面图">
                  🖼
                </div>
              )}
              <div className="prompt-lib-body">
                <div className="prompt-lib-title">
                  {item.title}
                  <span className={`prompt-badge ${item.maturity}`}>{maturityLabel(item.maturity)}</span>
                </div>
                <div className="prompt-lib-meta">
                  {item.categoryGroup} · {item.category}
                </div>
                <p className="prompt-lib-snippet">
                  {item.prompt.slice(0, isPage ? 160 : 120)}
                  {item.prompt.length > (isPage ? 160 : 120) ? "…" : ""}
                </p>
                <div className="btn-row" onClick={(e) => e.stopPropagation()}>
                  <button type="button" className="btn" onClick={() => setPreviewItem(item)}>
                    预览
                  </button>
                  <button type="button" className="btn primary" onClick={() => onApply(item)}>
                    {isPage ? "插入画布" : "应用到选中"}
                  </button>
                  <button type="button" className="btn" onClick={() => onToggleFav(item)}>
                    {item.favorite ? "★ 已藏" : "☆ 收藏"}
                  </button>
                  {isPage ? (
                    <button type="button" className="btn" onClick={() => onSaveLocal(item)}>
                      存本地
                    </button>
                  ) : null}
                  {item.githubUrl ? (
                    <a className="btn link" href={item.githubUrl} target="_blank" rel="noreferrer">
                      来源
                    </a>
                  ) : null}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
      {totalPages > 1 ? (
        <div className="prompt-lib-pager">
          <button type="button" className="btn" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            上一页
          </button>
          <span>
            {page}/{totalPages} · 共 {total} 条
          </span>
          <button
            type="button"
            className="btn"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => p + 1)}
          >
            下一页
          </button>
        </div>
      ) : (
        <p className="hint">共 {total} 条</p>
      )}
    </div>
  );
}
