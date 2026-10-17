/** 落地页 — 视觉对齐 infinite-canvas home（深色点阵 + 大标题 + 双 CTA + 沉淀区） */
type ShowcaseItem = {
  id: string;
  title: string;
  prompt: string;
  coverUrl?: string;
  tags?: string[];
};

type Props = {
  onStart: () => void;
  onOpenCanvas: () => void;
  onViewPrompts: () => void;
  showcase?: ShowcaseItem[];
};

const FALLBACK_SHOWCASE: ShowcaseItem[] = [
  {
    id: "f1",
    title: "竖屏漫剧开场",
    prompt: "夜色霓虹巷口，主角逆光站立，电影感景深",
    tags: ["漫剧", "开场"],
  },
  {
    id: "f2",
    title: "角色三视图",
    prompt: "同一角色正/侧/背统一光照，便于一致性生成",
    tags: ["角色", "三视图"],
  },
  {
    id: "f3",
    title: "九宫格分镜",
    prompt: "情绪递进九镜：建立→冲突→反转",
    tags: ["分镜"],
  },
  {
    id: "f4",
    title: "表情变体",
    prompt: "同一构图换喜怒哀，保持服装与光影",
    tags: ["变体"],
  },
];

export default function HomeLanding({
  onStart,
  onOpenCanvas,
  onViewPrompts,
  showcase,
}: Props) {
  const items = showcase && showcase.length > 0 ? showcase : FALLBACK_SHOWCASE;

  return (
    <main className="ic-home">
      <section className="ic-home-hero-wrap">
        <div className="ic-deco ic-deco-a" aria-hidden />
        <div className="ic-deco ic-deco-b" aria-hidden />

        <div className="ic-home-hero">
          <h1 className="ic-title">无限画布</h1>
          <p className="ic-lead">
            在 <em className="hl-under">无限画布</em> 中生成、连接和重组{" "}
            <em className="hl-mark">图片、文字与图形</em>
            ，让创作从单次生成变成连续推演。
          </p>
          <div className="ic-cta-row">
            <button type="button" className="ic-btn-primary" onClick={onStart}>
              开始使用
              <span aria-hidden>→</span>
            </button>
            <button type="button" className="ic-btn-ghost" onClick={onOpenCanvas}>
              打开画布
            </button>
          </div>
        </div>

        <section className="ic-showcase">
          <div className="ic-showcase-head">
            <div className="ic-showcase-copy">
              <h2>沉淀每一次好结果</h2>
              <p>收藏稳定出图的提示词、参考风格和结果图片，让下一次创作从已有经验开始。</p>
            </div>
            <button type="button" className="ic-link" onClick={onViewPrompts}>
              查看提示词库 →
            </button>
          </div>
          <div className="ic-showcase-grid">
            {items.slice(0, 6).map((item, index) => (
              <button
                key={item.id}
                type="button"
                className={`ic-card${index === 0 ? " wide tall" : ""}${index === 3 ? " wide" : ""}`}
                onClick={onOpenCanvas}
              >
                {item.coverUrl ? (
                  <img src={item.coverUrl} alt="" />
                ) : (
                  <div className={`ic-card-ph ph-${(index % 4) + 1}`} />
                )}
                <div className="ic-card-meta">
                  <div className="ic-card-tags">
                    {(item.tags || []).slice(0, 2).map((t) => (
                      <span key={t}>{t}</span>
                    ))}
                  </div>
                  <h3>{item.title}</h3>
                  <p>{item.prompt}</p>
                </div>
              </button>
            ))}
          </div>
        </section>
      </section>
    </main>
  );
}
