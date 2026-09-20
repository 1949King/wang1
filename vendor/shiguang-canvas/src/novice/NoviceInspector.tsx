/**
 * 小白模式右侧面板 — 参数降维 + 意图胶囊
 *
 * 对齐《磁吸意图画布》规格 7.x（2026-09-16 类型化升级）：
 * - L1 导演参数按字段存在性渲染（提示词 / 画质 / 时长 / 运动幅度 / 相似度 /
 *   景别——该类型在 node-factory 里有什么真实字段才显示什么）
 * - L2 进阶参数按类型分派（镜头→运镜/焦段/光圈/补帧；视频→首尾帧权重；
 *   音乐→风格/纯音乐/歌词；生成器→数量/产出/汇聚；动画→动作/帧数/帧率…
 *   纯文本类显示「没有进阶参数」）
 * - L3 专业参数在 L2 底部「▾ 专业参数」折叠展开（按字段存在性渲染），
 *   2026-09-16 用户裁定：L3 不再完全隐藏
 * - 双击卡片（store.requestProEdit）→ 本面板自动展开 L2 进入精细编辑
 * - 画质档位联动底层步数 / 补帧开关（spec 7.5，只写该类型真实存在的字段）
 *
 * 已移除 aspectRatio / styleStrength / negativePrompt：三个字段不在
 * node-factory 类型定义中，前后端生成链路均无消费，属假设置。
 */

import { useEffect, useState } from "react";
import { useCanvasStore } from "../store";
import { breakdownStoryboard } from "../bridge";
import {
  APERTURES,
  CAMERA_MOTIONS,
  FOCAL_LENGTHS,
  INTENT_LAYERS,
  INTERP_FPS_CHOICES,
  MOTION_LEVELS,
  QUALITY_PRESET,
  QUALITY_TIERS,
  SHOT_SIZES,
  intentHintFor,
  kindStyle,
  type IntentLayer,
} from "./types";
import "./novice-inspector.css";

type LooseData = Record<string, unknown> & {
  kind?: string;
  title?: string;
  prompt?: string;
  duration?: number;
  qualityTier?: string;
  motionStrength?: number;
  consistency?: number;
  movement?: string;
  seed?: number;
  cfg?: number;
  steps?: number;
  intentDepth?: number;
  imageUrl?: string;
  captureUrls?: string[];
  lastCameraName?: string;
  // 镜头语言（ShotData）
  shotSize?: string;
  focalLength?: number;
  aperture?: number;
  characterId?: string;
  characterName?: string;
  // 视频（VideoData）
  firstFrameWeight?: number;
  lastFrameWeight?: number;
  // 补帧（ShotData/ImageData）
  interpolationEnabled?: boolean;
  interpolationMode?: string;
  interpolationTargetFps?: number;
  // 音乐（MusicData）
  style?: string;
  lyrics?: string;
  instrumental?: boolean;
  // 生成器（GeneratorData）
  mode?: string;
  count?: number;
  autoCollectUpstream?: boolean;
  outputKind?: string;
  // 动画（AnimationData）
  action?: string;
  frames?: number;
  fps?: number;
  // 全景（PanoramaData）
  yaw?: number;
  pitch?: number;
};

export default function NoviceInspector() {
  const selectedId = useCanvasStore((s) => s.selectedId);
  const node = useCanvasStore((s) => s.nodes.find((n) => n.id === s.selectedId));
  const updateSelectedData = useCanvasStore((s) => s.updateSelectedData);
  const addNode = useCanvasStore((s) => s.addNode);
  const openDirectorForNode = useCanvasStore((s) => s.openDirectorForNode);
  const breakdownDirectorCard = useCanvasStore((s) => s.breakdownDirectorCard);
  const updateNodeData = useCanvasStore((s) => s.updateNodeData);
  const listTemplates = useCanvasStore((s) => s.listTemplates);
  const loadTemplate = useCanvasStore((s) => s.loadTemplate);
  const saveSelectionTemplate = useCanvasStore((s) => s.saveSelectionTemplate);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [proOpen, setProOpen] = useState(false);
  const [capsuleOpen, setCapsuleOpen] = useState(false);
  // 意图胶囊「一句话解析」：空状态内嵌输入框的展开态 + 解析状态
  const [intentOpen, setIntentOpen] = useState(false);
  const [intentText, setIntentText] = useState("");
  const [intentBusy, setIntentBusy] = useState(false);

  // 双击卡片 = 打开精细编辑：订阅 store 的双击信号，自动展开进阶设置
  const proEditNonce = useCanvasStore((s) => s.proEditNonce);
  useEffect(() => {
    if (proEditNonce > 0) {
      setAdvancedOpen(true);
      setProOpen(false);
    }
  }, [proEditNonce]);

  /** 意图胶囊解析：打一句话 → 建导演卡承载意图 → 调 LLM 拆镜 → 自动铺出分镜序列 */
  const runIntentBreakdown = async () => {
    const script = intentText.trim();
    if (!script) return;
    setIntentBusy(true);
    let cardId = "";
    try {
      // 1. 建导演卡（意图胶囊的化身），把这句话写进 script
      cardId = addNode("directorCard" as never);
      updateNodeData(cardId, { script, status: "generating" });
      // 2. 调后端拆镜
      const res = await breakdownStoryboard(script);
      if (!res.ok && !(res.shots && res.shots.length)) {
        updateNodeData(cardId, { status: "failed", errorMessage: res.message || "拆解失败" });
        return;
      }
      // 3. 自动铺出分镜序列（非破坏，挂到导演卡下游）
      breakdownDirectorCard(cardId, res.shots || []);
    } catch (e) {
      // 诚实失败：不吞异常，把状态落到「刚建的那张」导演卡（而非画布上任意一张）
      if (cardId) {
        useCanvasStore.getState().updateNodeData(cardId, {
          status: "failed",
          errorMessage: String(e).slice(0, 200),
        });
      }
    } finally {
      setIntentBusy(false);
      setIntentText("");
      setIntentOpen(false);
    }
  };

  if (!selectedId || !node) {
    return (
      <div className="nv-inspector">
        <div className="nv-insp-title">一句话，开始你的片子</div>
        <div className="nv-insp-quick">
          {!intentOpen ? (
            <button
              type="button"
              className="nv-insp-quick-btn primary"
              onClick={() => setIntentOpen(true)}
            >
              <span className="nv-insp-quick-ico">🎬</span>
              <span>
                <b>从一句话开始</b>
                <em>写一句剧情，自动拆成一整套分镜卡片</em>
              </span>
            </button>
          ) : (
            <div className="nv-insp-intent">
              <textarea
                className="nv-insp-textarea"
                rows={4}
                autoFocus
                value={intentText}
                placeholder="例如：女主深夜回到空荡的老屋，发现桌上的照片全都变成了一年前的样子，她决定查清真相"
                onChange={(e) => setIntentText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                    e.preventDefault();
                    if (!intentBusy) void runIntentBreakdown();
                  }
                }}
              />
              <div className="nv-insp-intent-actions">
                <button
                  type="button"
                  className="nv-insp-mini"
                  onClick={() => {
                    setIntentOpen(false);
                    setIntentText("");
                  }}
                >
                  取消
                </button>
                <button
                  type="button"
                  className="nv-insp-quick-go"
                  disabled={intentBusy || !intentText.trim()}
                  onClick={() => void runIntentBreakdown()}
                >
                  {intentBusy ? "拆解中…" : "生成分镜"}
                </button>
              </div>
              <p className="nv-insp-tip">写一句话描述你的开场剧情，系统会拆成「导演卡 → 一串分镜卡片」，你逐个生成画面即可。</p>
            </div>
          )}
          <button
            type="button"
            className="nv-insp-quick-btn"
            onClick={() => addNode("shot" as never)}
          >
            <span className="nv-insp-quick-ico">🖼️</span>
            <span>
              <b>直接生一张图</b>
              <em>写一句画面描述，点生成</em>
            </span>
          </button>
        </div>

        <div className="nv-insp-title">快速开始 · 模板</div>
        <div className="nv-insp-tpl">
          {listTemplates().map((t) => (
            <button
              key={t.id}
              type="button"
              className="nv-insp-tpl-item"
              onClick={() => loadTemplate(t.id)}
            >
              <span className="nv-insp-tpl-ico" aria-hidden>
                {t.builtin ? "✨" : "💾"}
              </span>
              <span className="nv-insp-tpl-txt">
                <b>{t.name}</b>
                {t.description ? <em>{t.description}</em> : null}
              </span>
            </button>
          ))}
        </div>

        <div className="nv-insp-title">怎么用这张画布</div>
        <ol className="nv-insp-steps">
          <li>点上面「从一句话开始」，写一句剧情</li>
          <li>系统自动拆成一串分镜卡片，横向排成时间链</li>
          <li>点中卡片，在下面写「你想要什么」</li>
          <li>点底部「生成选中」开始出图 / 出视频</li>
        </ol>
      </div>
    );
  }

  const d = node.data as LooseData;
  const kind = String(d.kind || "");
  const style = kindStyle(kind);
  const depth = Math.min(3, Math.max(1, Number(d.intentDepth) || 2));

  // ===== 3D 导演台专属面板：把「摆姿 / 机位 / 截图回写」完整带进小白模式 =====
  if (kind === "director") {
    const captures = Array.isArray(d.captureUrls) ? (d.captureUrls as string[]) : [];
    const main = (d.imageUrl as string) || captures[captures.length - 1] || "";
    return (
      <div className="nv-inspector">
        <div className="nv-insp-head">
          <span className="nv-insp-ico" aria-hidden>
            {style.icon}
          </span>
          <input
            className="nv-insp-title-input"
            value={String(d.title || "")}
            placeholder="给这张导演台卡片起个名字"
            onChange={(e) => updateSelectedData({ title: e.target.value })}
          />
          <span className="nv-insp-kind">{style.label}</span>
        </div>

        <button
          type="button"
          className="nv-insp-quick-btn primary"
          onClick={() => openDirectorForNode(selectedId!)}
        >
          <span className="nv-insp-quick-ico">🎥</span>
          <span>
            <b>打开舞台</b>
            <em>摆好角色姿势、定机位，截图自动回写这张卡片</em>
          </span>
        </button>

        {main ? (
          <div className="nv-director-preview">
            <img src={main} alt="导演台主图" />
          </div>
        ) : (
          <div className="nv-director-empty">还没截图，点「打开舞台」摆好机位截图</div>
        )}

        {d.lastCameraName ? (
          <div className="nv-insp-field">
            <label>
              最近机位 <b>{String(d.lastCameraName)}</b>
            </label>
          </div>
        ) : null}

        {captures.length > 1 ? (
          <>
            <div className="nv-insp-title">历史截图（点一张设为主图）</div>
            <div className="nv-director-thumbs">
              {captures
                .slice(-12)
                .reverse()
                .map((u, i) => (
                  <button
                    key={`${i}_${u.slice(0, 24)}`}
                    type="button"
                    className={`nv-director-thumb${u === main ? " on" : ""}`}
                    onClick={() => updateSelectedData({ imageUrl: u })}
                  >
                    <img src={u} alt="" />
                  </button>
                ))}
            </div>
          </>
        ) : null}

        <div className="nv-insp-title">镜头意图（下游提示词备注）</div>
        <textarea
          className="nv-insp-textarea"
          rows={3}
          value={String(d.prompt || "")}
          placeholder="写一句这个机位想表达什么，作为下游镜头卡的提示词参考"
          onChange={(e) => updateSelectedData({ prompt: e.target.value })}
        />

        <button
          type="button"
          className={`nv-insp-fold${capsuleOpen ? " on" : ""}`}
          onClick={() => setCapsuleOpen((v) => !v)}
        >
          {capsuleOpen ? "▾" : "▸"} 意图胶囊（这张卡片的里面）
        </button>
        {capsuleOpen ? (
          <div className="nv-insp-capsule">
            {INTENT_LAYERS.map((l, i) => (
              <button
                key={l.id}
                type="button"
                className={`nv-capsule-row${depth === i + 1 ? " on" : ""}`}
                onClick={() => updateSelectedData({ intentDepth: i + 1 })}
              >
                <span className="nv-capsule-idx">{i + 1}</span>
                <span className="nv-capsule-txt">
                  <b>{l.label}</b>
                  <em>{intentHintFor(kind, l.id)}</em>
                </span>
              </button>
            ))}
          </div>
        ) : null}

        <p className="nv-insp-foot">
          这是 3D 导演台卡片：摆姿、机位、截图都在内嵌舞台里完成。
          截图回写后，你可以把这张卡拖到别的镜头卡旁边，自动吸附成「机位 → 镜头」的关系。
        </p>
      </div>
    );
  }

  const quality = (d.qualityTier as string) || "standard";
  const motion = Number(d.motionStrength ?? 55);
  const similarity = Number(d.consistency ?? 75);
  const duration = Number(d.duration ?? 5);

  // ── L1 字段存在性表（2026-09-16 类型化）：该类型在 node-factory 里
  //    真实拥有的字段才渲染，不再对纯文本卡片显示「运动幅度」这类错位参数
  const GEN_WITH_SHOTSIZE = kind === "shot";                     // ShotData.shotSize
  const GEN_WITH_QUALITY = kind === "shot" || kind === "image" || kind === "video"; // qualityTier
  const GEN_WITH_DURATION = kind === "shot" || kind === "video" || kind === "audio" || kind === "music"; // duration
  const GEN_WITH_MOTION = kind === "video";                      // motionStrength
  const GEN_WITH_SIMILARITY = kind === "video";                  // consistency

  /** 画质档位联动：只写该类型真实存在的字段（video 无 steps/补帧字段，不伪造） */
  const applyQuality = (tier: string) => {
    const preset = QUALITY_PRESET[tier as keyof typeof QUALITY_PRESET];
    if (!preset) return updateSelectedData({ qualityTier: tier });
    if (kind === "shot" || kind === "image") {
      updateSelectedData({
        qualityTier: tier,
        steps: preset.steps,
        interpolationEnabled: preset.frameInterpolate,
      });
    } else {
      updateSelectedData({ qualityTier: tier });
    }
  };

  const motionId =
    MOTION_LEVELS.reduce((best, m) =>
      Math.abs(m.value - motion) < Math.abs(best.value - motion) ? m : best,
    ).id;

  return (
    <div className="nv-inspector">
      <div className="nv-insp-head">
        <span className="nv-insp-ico" aria-hidden>
          {style.icon}
        </span>
        <input
          className="nv-insp-title-input"
          value={String(d.title || "")}
          placeholder="给这张卡片起个名字"
          onChange={(e) => updateSelectedData({ title: e.target.value })}
        />
        <span className="nv-insp-kind">{style.label}</span>
      </div>

      <div className="nv-insp-title">你想要什么</div>
      <textarea
        className="nv-insp-textarea"
        rows={4}
        value={String(d.prompt || "")}
        placeholder="用大白话描述画面，例如：女主在雨夜街头回头，电影感，竖屏漫剧分镜"
        onChange={(e) => updateSelectedData({ prompt: e.target.value })}
      />

      <div className="nv-insp-title">导演参数</div>

      {GEN_WITH_SHOTSIZE ? (
        <div className="nv-insp-field">
          <label>景别</label>
          <div className="nv-seg wrap">
            {SHOT_SIZES.map((s) => (
              <button
                key={s}
                type="button"
                className={(d.shotSize || "中景") === s ? "on" : ""}
                onClick={() => updateSelectedData({ shotSize: s })}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {GEN_WITH_QUALITY ? (
        <div className="nv-insp-field">
          <label>画质</label>
          <div className="nv-seg">
            {QUALITY_TIERS.map((q) => (
              <button
                key={q.id}
                type="button"
                className={quality === q.id ? "on" : ""}
                title={q.desc}
                onClick={() => applyQuality(q.id)}
              >
                {q.label}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {GEN_WITH_DURATION ? (
        <div className="nv-insp-field">
          <label>
            时长 <b>{duration}s</b>
          </label>
          <input
            type="range"
            min={2}
            max={30}
            step={1}
            value={duration}
            onChange={(e) => updateSelectedData({ duration: Number(e.target.value) })}
          />
        </div>
      ) : null}

      {GEN_WITH_MOTION ? (
        <div className="nv-insp-field">
          <label>运动幅度</label>
          <div className="nv-seg">
            {MOTION_LEVELS.map((m) => (
              <button
                key={m.id}
                type="button"
                className={motionId === m.id ? "on" : ""}
                onClick={() => updateSelectedData({ motionStrength: m.value })}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {GEN_WITH_SIMILARITY ? (
        <div className="nv-insp-field">
          <label>
            相似度 <b>{similarity}%</b>
          </label>
          <input
            type="range"
            min={0}
            max={100}
            step={1}
            value={similarity}
            onChange={(e) => updateSelectedData({ consistency: Number(e.target.value) })}
          />
          <p className="nv-insp-tip">越高越贴近参考图，越低越自由发挥</p>
        </div>
      ) : null}

      <button
        type="button"
        className={`nv-insp-fold${advancedOpen ? " on" : ""}`}
        onClick={() => setAdvancedOpen((v) => !v)}
      >
        {advancedOpen ? "▾" : "▸"} 进阶设置（双击卡片也能打开）
      </button>

      {advancedOpen ? (
        <div className="nv-insp-advanced">
          {/*
           * L2 按类型分派（2026-09-16）：每类卡片只显示自己的进阶参数，
           * 字段全部来自 node-factory 类型定义；纯文本类没有进阶参数。
           */}
          {kind === "shot" ? (
            <>
              <div className="nv-insp-field">
                <label>镜头怎么动</label>
                <div className="nv-seg wrap">
                  {CAMERA_MOTIONS.map((c) => (
                    <button
                      key={c.id}
                      type="button"
                      className={(d.movement || "static") === c.id ? "on" : ""}
                      onClick={() => updateSelectedData({ movement: c.id })}
                    >
                      {c.label}
                    </button>
                  ))}
                </div>
              </div>
              <div className="nv-insp-field">
                <label>焦段（mm）</label>
                <div className="nv-seg wrap">
                  {FOCAL_LENGTHS.map((f) => (
                    <button
                      key={f}
                      type="button"
                      className={Number(d.focalLength ?? 35) === f ? "on" : ""}
                      onClick={() => updateSelectedData({ focalLength: f })}
                    >
                      {f}
                    </button>
                  ))}
                </div>
              </div>
              <div className="nv-insp-field">
                <label>光圈（f/）</label>
                <div className="nv-seg wrap">
                  {APERTURES.map((a) => (
                    <button
                      key={a}
                      type="button"
                      className={Number(d.aperture ?? 2.8) === a ? "on" : ""}
                      onClick={() => updateSelectedData({ aperture: a })}
                    >
                      {a}
                    </button>
                  ))}
                </div>
              </div>
              <div className="nv-insp-field">
                <label>发送剪辑时自动补帧</label>
                <div className="nv-seg">
                  <button
                    type="button"
                    className={d.interpolationEnabled ? "on" : ""}
                    onClick={() => updateSelectedData({ interpolationEnabled: true })}
                  >
                    开
                  </button>
                  <button
                    type="button"
                    className={!d.interpolationEnabled ? "on" : ""}
                    onClick={() => updateSelectedData({ interpolationEnabled: false })}
                  >
                    关
                  </button>
                </div>
              </div>
              {d.characterName ? (
                <div className="nv-insp-field">
                  <label>
                    绑定角色 <b>{String(d.characterName)}</b>
                  </label>
                  <button
                    type="button"
                    className="nv-insp-mini"
                    onClick={() => updateSelectedData({ characterId: "", characterName: "", characterAppearance: "" })}
                  >
                    解除绑定
                  </button>
                </div>
              ) : null}
            </>
          ) : null}

          {kind === "image" ? (
            <div className="nv-insp-field">
              <label>发送剪辑时自动补帧</label>
              <div className="nv-seg">
                <button
                  type="button"
                  className={d.interpolationEnabled ? "on" : ""}
                  onClick={() => updateSelectedData({ interpolationEnabled: true })}
                >
                  开
                </button>
                <button
                  type="button"
                  className={!d.interpolationEnabled ? "on" : ""}
                  onClick={() => updateSelectedData({ interpolationEnabled: false })}
                >
                  关
                </button>
              </div>
            </div>
          ) : null}

          {kind === "video" ? (
            <>
              <div className="nv-insp-field">
                <label>
                  首帧权重 <b>{Math.round(Number(d.firstFrameWeight ?? 0.5) * 100)}%</b>
                </label>
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.05}
                  value={Number(d.firstFrameWeight ?? 0.5)}
                  onChange={(e) => updateSelectedData({ firstFrameWeight: Number(e.target.value) })}
                />
              </div>
              <div className="nv-insp-field">
                <label>
                  尾帧权重 <b>{Math.round(Number(d.lastFrameWeight ?? 0.5) * 100)}%</b>
                </label>
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.05}
                  value={Number(d.lastFrameWeight ?? 0.5)}
                  onChange={(e) => updateSelectedData({ lastFrameWeight: Number(e.target.value) })}
                />
              </div>
            </>
          ) : null}

          {kind === "music" ? (
            <>
              <div className="nv-insp-field">
                <label>音乐风格</label>
                <input
                  type="text"
                  value={String(d.style || "")}
                  placeholder="例如：国风、电子、抒情钢琴"
                  onChange={(e) => updateSelectedData({ style: e.target.value })}
                />
              </div>
              <div className="nv-insp-field">
                <label>纯音乐（无人声）</label>
                <div className="nv-seg">
                  <button
                    type="button"
                    className={d.instrumental ? "on" : ""}
                    onClick={() => updateSelectedData({ instrumental: true })}
                  >
                    是
                  </button>
                  <button
                    type="button"
                    className={!d.instrumental ? "on" : ""}
                    onClick={() => updateSelectedData({ instrumental: false })}
                  >
                    否
                  </button>
                </div>
              </div>
              <div className="nv-insp-field">
                <label>歌词（非纯音乐时生效）</label>
                <textarea
                  className="nv-insp-textarea"
                  rows={3}
                  value={String(d.lyrics || "")}
                  placeholder="写歌词，留空则由 AI 自拟"
                  onChange={(e) => updateSelectedData({ lyrics: e.target.value })}
                />
              </div>
            </>
          ) : null}

          {kind === "generator" ? (
            <>
              <div className="nv-insp-field">
                <label>
                  产出数量 <b>{Number(d.count ?? 4)}</b>
                </label>
                <input
                  type="range"
                  min={1}
                  max={8}
                  step={1}
                  value={Number(d.count ?? 4)}
                  onChange={(e) => updateSelectedData({ count: Number(e.target.value) })}
                />
              </div>
              <div className="nv-insp-field">
                <label>产出类型</label>
                <div className="nv-seg">
                  {(["image", "video"] as const).map((k) => (
                    <button
                      key={k}
                      type="button"
                      className={(d.outputKind || "image") === k ? "on" : ""}
                      onClick={() => updateSelectedData({ outputKind: k })}
                    >
                      {k === "image" ? "图片" : "视频"}
                    </button>
                  ))}
                </div>
              </div>
              <div className="nv-insp-field">
                <label>自动汇聚上游素材</label>
                <div className="nv-seg">
                  <button
                    type="button"
                    className={d.autoCollectUpstream ? "on" : ""}
                    onClick={() => updateSelectedData({ autoCollectUpstream: true })}
                  >
                    开
                  </button>
                  <button
                    type="button"
                    className={!d.autoCollectUpstream ? "on" : ""}
                    onClick={() => updateSelectedData({ autoCollectUpstream: false })}
                  >
                    关
                  </button>
                </div>
              </div>
            </>
          ) : null}

          {kind === "animation" ? (
            <>
              <div className="nv-insp-field">
                <label>动作</label>
                <div className="nv-seg wrap">
                  {["idle", "walk", "run", "jump", "attack", "hit"].map((a) => (
                    <button
                      key={a}
                      type="button"
                      className={(d.action || "idle") === a ? "on" : ""}
                      onClick={() => updateSelectedData({ action: a })}
                    >
                      {({ idle: "待机", walk: "走", run: "跑", jump: "跳", attack: "攻击", hit: "受击" } as Record<string, string>)[a]}
                    </button>
                  ))}
                </div>
              </div>
              <div className="nv-insp-field">
                <label>帧数</label>
                <div className="nv-seg wrap">
                  {[6, 8, 12, 16, 20].map((f) => (
                    <button
                      key={f}
                      type="button"
                      className={Number(d.frames ?? 8) === f ? "on" : ""}
                      onClick={() => updateSelectedData({ frames: f })}
                    >
                      {f}
                    </button>
                  ))}
                </div>
              </div>
              <div className="nv-insp-field">
                <label>
                  帧率 <b>{Number(d.fps ?? 12)} fps</b>
                </label>
                <input
                  type="range"
                  min={4}
                  max={30}
                  step={1}
                  value={Number(d.fps ?? 12)}
                  onChange={(e) => updateSelectedData({ fps: Number(e.target.value) })}
                />
              </div>
            </>
          ) : null}

          {kind === "digitalHuman" ? (
            <>
              <div className="nv-insp-field">
                <label>角色名</label>
                <input
                  type="text"
                  value={String(d.characterName || "")}
                  placeholder="角色名字"
                  onChange={(e) => updateSelectedData({ characterName: e.target.value })}
                />
              </div>
              <div className="nv-insp-field">
                <label>台词</label>
                <textarea
                  className="nv-insp-textarea"
                  rows={3}
                  value={String(d.line || "")}
                  placeholder="角色要说的台词"
                  onChange={(e) => updateSelectedData({ line: e.target.value })}
                />
              </div>
            </>
          ) : null}

          {kind === "panorama" ? (
            <>
              <div className="nv-insp-field">
                <label>
                  水平视角 <b>{Math.round(Number(d.yaw ?? 0))}°</b>
                </label>
                <input
                  type="range"
                  min={-180}
                  max={180}
                  step={1}
                  value={Number(d.yaw ?? 0)}
                  onChange={(e) => updateSelectedData({ yaw: Number(e.target.value) })}
                />
              </div>
              <div className="nv-insp-field">
                <label>
                  俯仰视角 <b>{Math.round(Number(d.pitch ?? 0))}°</b>
                </label>
                <input
                  type="range"
                  min={-90}
                  max={90}
                  step={1}
                  value={Number(d.pitch ?? 0)}
                  onChange={(e) => updateSelectedData({ pitch: Number(e.target.value) })}
                />
              </div>
            </>
          ) : null}

          {[
            "script", "directorCard", "markdown", "text", "prompt", "note",
            "audio", "shotlist", "storyboard", "group", "source", "config",
          ].includes(kind) ? (
            <p className="nv-insp-tip">这类卡片没有进阶参数——文字直接在卡片上写就行。</p>
          ) : null}

          {/*
           * L3 专业参数（2026-09-16 用户裁定：不再完全隐藏）——
           * 向下展开箭头，按字段存在性渲染：只显示该类型真实拥有的字段。
           */}
          {["shot", "image", "video", "audio", "generator"].includes(kind) ? (
            <>
              <button
                type="button"
                className={`nv-insp-fold nv-insp-pro${proOpen ? " on" : ""}`}
                onClick={() => setProOpen((v) => !v)}
                title="L3 专业参数"
              >
                <span className={`nv-pro-arrow${proOpen ? " down" : ""}`}>▸</span> 专业参数（L3）
              </button>
              {proOpen ? (
                <div className="nv-insp-advanced nv-insp-l3">
                  {kind === "shot" || kind === "image" ? (
                    <div className="nv-insp-field">
                      <label>
                        生成步数 <b>{Number(d.steps ?? 22)}</b>
                      </label>
                      <input
                        type="range"
                        min={8}
                        max={50}
                        step={1}
                        value={Number(d.steps ?? 22)}
                        onChange={(e) => updateSelectedData({ steps: Number(e.target.value) })}
                      />
                    </div>
                  ) : null}
                  {kind === "shot" || kind === "image" || kind === "generator" ? (
                    <div className="nv-insp-field">
                      <label>
                        提示词强度 cfg <b>{Number(d.cfg ?? 7)}</b>
                      </label>
                      <input
                        type="range"
                        min={1}
                        max={20}
                        step={0.5}
                        value={Number(d.cfg ?? 7)}
                        onChange={(e) => updateSelectedData({ cfg: Number(e.target.value) })}
                      />
                    </div>
                  ) : null}
                  {/*
                   * seed：L3 白名单五类（shot/image/video/audio/generator）
                   * 在 node-factory 里都有 seed 字段，直接渲染。
                   */}
                  <div className="nv-insp-field">
                    <label>随机种子（-1 = 每次随机）</label>
                    <div className="nv-insp-row">
                      <input
                        type="number"
                        value={Number(d.seed ?? -1)}
                        onChange={(e) => updateSelectedData({ seed: Number(e.target.value) })}
                      />
                      <button
                        type="button"
                        className="nv-insp-mini"
                        onClick={() => updateSelectedData({ seed: Math.floor(Math.random() * 1_000_000) })}
                      >
                        随机
                      </button>
                    </div>
                  </div>
                  {kind === "shot" || kind === "image" ? (
                    <>
                      <div className="nv-insp-field">
                        <label>补帧模式</label>
                        <div className="nv-seg wrap">
                          {[
                            ["disabled", "关闭"],
                            ["auto", "自动"],
                            ["always", "总是"],
                            ["smart", "智能"],
                          ].map(([v, label]) => (
                            <button
                              key={v}
                              type="button"
                              className={(d.interpolationMode || "auto") === v ? "on" : ""}
                              onClick={() => updateSelectedData({ interpolationMode: v })}
                            >
                              {label}
                            </button>
                          ))}
                        </div>
                      </div>
                      <div className="nv-insp-field">
                        <label>补帧目标帧率</label>
                        <div className="nv-seg">
                          {INTERP_FPS_CHOICES.map((f) => (
                            <button
                              key={f}
                              type="button"
                              className={Number(d.interpolationTargetFps ?? 30) === f ? "on" : ""}
                              onClick={() => updateSelectedData({ interpolationTargetFps: f })}
                            >
                              {f} fps
                            </button>
                          ))}
                        </div>
                      </div>
                    </>
                  ) : null}
                </div>
              ) : null}
            </>
          ) : null}
        </div>
      ) : null}

      <button
        type="button"
        className={`nv-insp-fold${capsuleOpen ? " on" : ""}`}
        onClick={() => setCapsuleOpen((v) => !v)}
      >
        {capsuleOpen ? "▾" : "▸"} 意图胶囊（这张卡片的里面）
      </button>

      {capsuleOpen ? (
        <div className="nv-insp-capsule">
          {INTENT_LAYERS.map((l, i) => (
            <button
              key={l.id}
              type="button"
              className={`nv-capsule-row${depth === i + 1 ? " on" : ""}`}
              onClick={() => updateSelectedData({ intentDepth: i + 1 })}
            >
              <span className="nv-capsule-idx">{i + 1}</span>
              <span className="nv-capsule-txt">
                <b>{l.label}</b>
                <em>{intentHintFor(kind, l.id)}</em>
              </span>
            </button>
          ))}
        </div>
      ) : null}

      <button
        type="button"
        className="nv-insp-fold"
        onClick={() => saveSelectionTemplate(d.title ? String(d.title) : "卡片组合")}
      >
        💾 沉淀为模板（选中的卡片可复用）
      </button>

      <p className="nv-insp-foot">
        「进阶设置」里是这类卡片自己的参数；点「▸ 专业参数（L3）」可以展开步数、
        种子这类技术参数。想看全部节点级参数，切到右上角「专业模式」。
      </p>
    </div>
  );
}

/** 供外部判断当前是否处于某个意图层（预留） */
export function isIntentLayer(v: unknown): v is IntentLayer {
  return v === "surface" || v === "semantic" || v === "implementation";
}
