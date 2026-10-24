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
import { repairImageViaHost } from "../canvasRepair";
import {
  enhanceImageViaHost,
  scriptWriteViaHost,
  toEnhanceDataUrl,
} from "../canvasEnhanceActions";
import { yuePlanViaHost, yueTranscribeViaHost } from "../canvasYue";
import {
  bucketComplianceLevels,
  checkScriptCompliance,
  collectComplianceCharacters,
  collectComplianceShots,
  complianceHeadline,
  type ComplianceResult,
} from "../hostCompliance";
import {
  fetchEnhanceIntents,
  intentButtonLabel,
  selectDirectIntents,
  type EnhanceIntent,
  type EnhanceIntentCatalog,
} from "../hostEnhanceIntents";
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
  ASPECTS,
  YUE_COT,
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
  aspect?: string;
  /** YuE 全曲生成字段（2026-09-28）；style/lyrics 已在下方声明，勿重复 */
  engine?: string;
  abc?: string;
  cot?: string;
  yueMode?: string;
  referenceAudioUrl?: string;
  yueExecutor?: string;
  /** 抽卡闭环产物（V4.40.10）：最近一次生成的推荐 / 代理分 / 坏区修复计划 */
  lastSeed?: number;
  lastSeedSent?: boolean;
  proxyScore?: number;
  isProxy?: boolean;
  recommendation?: { best_seed?: number; mean?: number; n?: number; last_used?: number };
  repairPlan?: { has_bad_regions?: boolean; boxes?: number[][]; region_count?: number };
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

/**
 * 增强意图目录不可用时的回落集合（Wave 0 #13）。
 * 文案与后端 `ENHANCE_INTENTS`（app/core/canvas_enhance.py:54）逐字对齐 ——
 * 只用于「bridge 没起来 / 端点失败」，此时前端给老行为，不白屏。
 * 目录一旦拉到，本常量即被后端数据取代（后端是单一真源）。
 */
const FALLBACK_INTENTS: EnhanceIntent[] = [
  { id: "face", label: "修复人脸", hint: "让面部更清晰自然；没有检测到人脸时原样返回" },
  { id: "cutout", label: "抠像换背景", hint: "把主体从背景里分离出来；可换成纯色底或保留透明底" },
  { id: "sharpen", label: "超分放大", hint: "放大画面并补细节；高质量档更清晰但更慢" },
];

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
  // 局部重绘（P4）：进度/结果态。会真花一次云端额度，故须用户显式点击触发。
  const [repairBusy, setRepairBusy] = useState(false);
  const [repairMsg, setRepairMsg] = useState("");
  // YuE 符号规划：只出可编辑谱（不出音频）。慢，故显式点击 + 进度提示。
  const [planBusy, setPlanBusy] = useState(false);
  const [planMsg, setPlanMsg] = useState("");
  // YuE 翻唱前置：参考曲 → 旋律谱（独立环境 SheetSage2，慢）
  const [trBusy, setTrBusy] = useState(false);
  const [trMsg, setTrMsg] = useState("");
  // AI 增强 / AI 编剧（LibTV 对标补强 刀3，2026-10-12 用户授权解冻 canvas-magnetic-intent）：
  // 图像节点超分/抠像（本地引擎不花云端额度）+ 剧本节点 AI 写剧本（走 LLM）。
  // 均显式点击触发 + 诚实回报实际引擎（degraded/降级必标注）。
  const [enhBusy, setEnhBusy] = useState(false);
  const [enhMsg, setEnhMsg] = useState("");
  // 增强意图目录（Wave 0 #13）：后端下发，取代硬编码的两个按钮。空 =尚未拉到/拉取失败。
  const [intentsCat, setIntentsCat] = useState<EnhanceIntentCatalog | null>(null);
  const [swBusy, setSwBusy] = useState(false);
  const [swMsg, setSwMsg] = useState("");
  // 剧本合规守护（Wave 0 #13）：显式点击触发。判定全在后端，前端只展示。
  const [cpBusy, setCpBusy] = useState(false);
  const [cpMsg, setCpMsg] = useState("");
  const [cpRes, setCpRes] = useState<ComplianceResult | null>(null);

  // 双击卡片 = 打开精细编辑：订阅 store 的双击信号，自动展开进阶设置
  const proEditNonce = useCanvasStore((s) => s.proEditNonce);
  useEffect(() => {
    if (proEditNonce > 0) {
      setAdvancedOpen(true);
      setProOpen(false);
    }
  }, [proEditNonce]);

  // 增强意图目录：挂载即拉一次（纯只读目录端点，不加载任何模型，见 canvas_enhance.available_intents）。
  // 失败不重试 —— 回落 FALLBACK_INTENTS 即老行为，反复打一个失败端点是噪音。
  useEffect(() => {
    let alive = true;
    void fetchEnhanceIntents().then((cat) => {
      if (alive && cat?.ok) setIntentsCat(cat);
    });
    return () => {
      alive = false;
    };
  }, []);

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
  // 画幅缺省 portrait（竖屏短剧）——与后端 DEFAULT_ASPECT 一致
  const aspect = (d.aspect as string) || "portrait";
  // YuE 全曲生成字段（2026-09-28）：引擎缺省 suno（向后兼容旧节点）
  const engine = (d.engine as string) || "suno";
  const cot = (d.cot as string) || "full";
  const abc = (d.abc as string) || "";
  const yueMode = (d.yueMode as string) || "original";
  const refAudio = (d.referenceAudioUrl as string) || "";

  // ── 抽卡闭环产物（V4.40.10 DEFECT C 修复：前端消费后端回传）──
  const rec = d.recommendation as
    | { best_seed?: number; mean?: number; n?: number; last_used?: number }
    | undefined;
  const proxyScore = typeof d.proxyScore === "number" ? (d.proxyScore as number) : undefined;
  const isProxy = d.isProxy === true;
  const repairPlan = d.repairPlan as
    | { has_bad_regions?: boolean; boxes?: number[][]; region_count?: number }
    | undefined;
  const badCount =
    repairPlan && repairPlan.has_bad_regions
      ? repairPlan.region_count ?? (repairPlan.boxes?.length || 0)
      : 0;
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
  const IS_MUSIC = kind === "music";                             // engine/abc/cot（YuE）

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

  /** 局部重绘：把当前图片交给后端找坏区并修掉（只修坏区，其余像素保持原图）。 */
  const doRepair = async () => {
    const img = (d.imageUrl as string) || "";
    if (!img || repairBusy) return;
    setRepairBusy(true);
    setRepairMsg("正在定位坏区并局部重绘…");
    try {
      const res = await repairImageViaHost({
        image: img,
        prompt: (d.prompt as string) || "",
        size: "",
      });
      if (res.ok && res.repaired && res.image_data_url) {
        updateSelectedData({ imageUrl: res.image_data_url, repairPlan: undefined });
        setRepairMsg(`已修复 ${res.used || 0} 处坏区`);
      } else if (res.ok && !res.repaired) {
        setRepairMsg(res.message || "未检出坏区，无需修复");
      } else {
        setRepairMsg(res.message || "局部重绘失败");
      }
    } catch (e) {
      setRepairMsg(`局部重绘异常: ${e}`);
    } finally {
      setRepairBusy(false);
    }
  };

  /** AI 增强（刀3）：共用后端 /host/canvas-enhance 意图级实现（Agent 能力 canvas.ai_upscale /
   *  canvas.ai_matte 同一后端 canvas_enhance.apply_intents）。
   *  如实回报实际引擎：degraded 必标注，绝不把双三次插值说成 AI 超分。
   *
   *  Wave 0 #13（2026-10-15）：意图列表不再硬编码 —— 由 GET /host/enhance-intents 下发
   *  （hostEnhanceIntents.selectDirectIntents）。原先这里是字面量 `"sharpen" | "cutout"`，
   *  后端 ENHANCE_INTENTS 里的 `face`（修复人脸）前端完全够不着。
   *  拉不到目录时回落到 FALLBACK_INTENTS（老行为，不白屏）。 */
  const doEnhance = async (intent: string) => {
    const img = (d.imageUrl as string) || "";
    if (!img || enhBusy) return;
    const label =
      selectDirectIntents(intentsCat).find((i) => i.id === intent)?.label ||
      FALLBACK_INTENTS.find((i) => i.id === intent)?.label ||
      intent;
    setEnhBusy(true);
    // 进行中文案用后端 label，不自造描述（自造=可能与实际引擎不符）
    setEnhMsg(`正在「${label}」…（本地引擎，结果如实回报）`);
    try {
      // 后端只认 data URL；节点图可能是 /inbox_file/…，先归一化
      const dataUrl = await toEnhanceDataUrl(img);
      if (!dataUrl) {
        setEnhMsg("图片读取失败（无法把节点图转成 data URL）");
        return;
      }
      const res = await enhanceImageViaHost({
        image: dataUrl,
        intents: [intent],
        quality: "standard",
      });
      const step = (res.applied || []).find((a) => a.intent === intent);
      if (res.ok && res.changed && res.image_data_url && step) {
        updateSelectedData({ imageUrl: res.image_data_url });
        const note = step.degraded
          ? `⚠️ 降级：${step.reason || step.engine || "非 AI 路径"}`
          : `引擎 ${step.engine || "unknown"}`;
        // 完成文案用后端回的 label（apply_intents 的 applied[].label），前端不编
        setEnhMsg(`已「${step.label || label}」 · ${note}`);
      } else {
        const why =
          (res.skipped || []).find((s) => s.intent === intent)?.reason ||
          res.message ||
          "未生效（原图未动）";
        setEnhMsg(String(why));
      }
    } catch (e) {
      setEnhMsg(`AI 增强异常: ${e}`);
    } finally {
      setEnhBusy(false);
    }
  };

  /** AI 写剧本（刀3）：卡片标题当主题 → LLM 完整剧本写入 content。
   *  已有正文不覆盖（想重写先清空）；模板降级 fallback 如实标注。 */
  const doScriptWrite = async () => {
    if (swBusy) return;
    const topic = String(d.title || "").trim();
    const content = String(d.content || "");
    if (!topic && !content.trim()) {
      setSwMsg("先在卡片标题里写主题（或先写一句梗概）");
      return;
    }
    if (content.trim()) {
      setSwMsg("卡片已有正文，不覆盖——想重写就先清空内容再点");
      return;
    }
    setSwBusy(true);
    setSwMsg("正在生成剧本…（云 → 本地 → 模板三级降级）");
    try {
      const res = await scriptWriteViaHost({ topic: topic || content.trim() });
      if (res.ok && res.script) {
        updateSelectedData({ content: res.script });
        setSwMsg(
          res.fallback
            ? "⚠️ LLM 不可用，已写入模板占位剧本（如实标注）"
            : "剧本已生成，可直接在卡片上修改",
        );
      } else {
        setSwMsg(res.message || "剧本生成失败");
      }
    } catch (e) {
      setSwMsg(`剧本生成异常: ${e}`);
    } finally {
      setSwBusy(false);
    }
  };

  /** 剧本合规守护（Wave 0 #13 孤儿端点接线第2 条，2026-10-15）：
   *  调 POST /host/compliance-check。后端 script_compliance_check 是唯一判定源
   *  （app/core/project_agent_host.py:741），前端**不复制任何一条检查规则**，
   *  只把返回的 suggestions 按 level 分桶展示。
   *  收集范围：画布上全部 shot 节点（有title 或 prompt）+ character 节点（有 characterName）。
   *  ⚠️ 后端会同时 SSE 推 compliance.report（AgentPanel 已消费）⇒ 这里不新增推送通道。
   */
  const runComplianceCheck = async () => {
    if (cpBusy) return;
    const content = String(d.content || "").trim();
    if (!content) {
      setCpMsg("剧本是空的，先写正文再查合规");
      return;
    }
    setCpBusy(true);
    setCpMsg("正在检查（本地启发式 + AI 审查，AI 较慢）…");
    try {
      const st = useCanvasStore.getState();
      const res = await checkScriptCompliance({
        script: content,
        shots: collectComplianceShots(st.nodes),
        characters: collectComplianceCharacters(st.nodes),
      });
      setCpRes(res);
      setCpMsg(complianceHeadline(res) || "检查完成");
    } catch (e) {
      setCpMsg(`合规检查异常: ${e}`);
    } finally {
      setCpBusy(false);
    }
  };

  /** YuE 符号规划：歌词+风格 → 可编辑的旋律/和弦 ABC 谱（不出音频，也不花钱渲染）。 */
  const doYuePlan = async () => {
    if (planBusy) return;
    const lyrics = (d.lyrics as string) || "";
    const style = (d.style as string) || (d.prompt as string) || "";
    if (!lyrics.trim() && !style.trim()) {
      setPlanMsg("先填风格或歌词，再生成谱面");
      return;
    }
    setPlanBusy(true);
    setPlanMsg("正在规划旋律与和弦…（首次会下载模型，较慢）");
    try {
      const res = await yuePlanViaHost({
        lyrics,
        style,
        cot: (d.cot as any) || "full",
        seed: typeof d.seed === "number" ? (d.seed as number) : undefined,
      });
      if (res.ok && res.abc) {
        updateSelectedData({ engine: "yue", abc: res.abc, cot: res.cot || "full" });
        setPlanMsg("谱面已生成，可在下方编辑后渲染整曲");
      } else {
        setPlanMsg(res.message || "谱面生成失败");
      }
    } catch (e) {
      setPlanMsg(`谱面生成异常: ${e}`);
    } finally {
      setPlanBusy(false);
    }
  };

  /** YuE 翻唱前置：参考曲 → 旋律乐谱（只留旋律去和弦，便于伴奏适配新风格）。 */
  const doYueTranscribe = async () => {
    if (trBusy) return;
    const ref = (d.referenceAudioUrl as string) || "";
    if (!ref.trim()) {
      setTrMsg("先填参考曲（本地路径或 inbox 链接）");
      return;
    }
    setTrBusy(true);
    setTrMsg("正在转录旋律…（SheetSage2 独立环境，首次较慢）");
    try {
      const res = await yueTranscribeViaHost({ audio: ref, melodyOnly: true });
      if (res.ok && res.abc) {
        // 转录结果 = 旋律谱 → 自动切到 melody 模式，符合官方翻唱用法
        updateSelectedData({ abc: res.abc, cot: "melody", engine: "yue", yueMode: "cover" });
        setTrMsg("旋律谱已生成（已切到「旋律翻唱」模式）。请先审阅乐谱再渲染");
      } else {
        setTrMsg(res.message || "转录失败");
      }
    } catch (e) {
      setTrMsg(`转录异常: ${e}`);
    } finally {
      setTrBusy(false);
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

      {GEN_WITH_QUALITY ? (
        <div className="nv-insp-field">
          <label>画幅</label>
          <div className="nv-seg">
            {ASPECTS.map((a) => (
              <button
                key={a.id}
                type="button"
                className={aspect === a.id ? "on" : ""}
                title={a.desc}
                onClick={() => updateSelectedData({ aspect: a.id })}
              >
                {a.label}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {/* YuE（乐）全曲生成：引擎 / 规划模式 / 可编辑乐谱（2026-09-28 适配）
          意图卡片在此承载「符号规划」——先给一张可改的谱，再谈渲染整曲。 */}
      {IS_MUSIC ? (
        <div className="nv-insp-field nv-insp-yue">
          <label>音乐引擎</label>
          <div className="nv-seg">
            <button
              type="button"
              className={engine === "suno" ? "on" : ""}
              title="Suno 黑盒：填风格/歌词直接出曲"
              onClick={() => updateSelectedData({ engine: "suno" })}
            >
              Suno
            </button>
            <button
              type="button"
              className={engine === "yue" ? "on" : ""}
              title="YuE：先出可编辑乐谱（旋律+和弦），改完再渲染整曲"
              onClick={() => updateSelectedData({ engine: "yue" })}
            >
              YuE 乐
            </button>
          </div>
          {engine === "yue" ? (
            <div className="nv-yue-body">
              <div className="nv-seg">
                <button
                  type="button"
                  className={yueMode === "original" ? "on" : ""}
                  title="原创：由引擎规划乐谱（或用下面「生成可编辑乐谱」自己规划）"
                  onClick={() => updateSelectedData({ yueMode: "original" })}
                >
                  原创
                </button>
                <button
                  type="button"
                  className={yueMode === "cover" ? "on" : ""}
                  title="翻唱：先把参考曲转录成旋律谱，再换风格/歌词重唱"
                  onClick={() => updateSelectedData({ yueMode: "cover" })}
                >
                  翻唱
                </button>
              </div>
              {yueMode === "cover" ? (
                <div className="nv-yue-cover">
                  <div className="nv-yue-abc-label">参考曲（本地路径或 inbox 链接）</div>
                  <input
                    type="text"
                    className="nv-yue-ref nodrag"
                    value={refAudio}
                    spellCheck={false}
                    placeholder="例：D:/素材/原曲.wav 或 http://127.0.0.1:18765/inbox_file/xxx.wav"
                    onChange={(e) => updateSelectedData({ referenceAudioUrl: e.target.value })}
                  />
                  <button
                    type="button"
                    className="nv-yue-plan"
                    disabled={trBusy}
                    onClick={doYueTranscribe}
                    title="转录参考曲的旋律（只留旋律去和弦，便于伴奏适配新风格）"
                  >
                    {trBusy ? "转录中…" : "转录旋律"}
                  </button>
                  {trMsg ? <div className="nv-loop-msg">{trMsg}</div> : null}
                </div>
              ) : null}
              <div className="nv-seg">
                {YUE_COT.map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    className={cot === m.id ? "on" : ""}
                    title={m.desc}
                    onClick={() => updateSelectedData({ cot: m.id })}
                  >
                    {m.label}
                  </button>
                ))}
              </div>
              <button
                type="button"
                className="nv-yue-plan"
                disabled={planBusy}
                onClick={doYuePlan}
                title="只生成可编辑乐谱，不出音频（不出钱渲染）"
              >
                {planBusy ? "规划中…" : "生成可编辑乐谱"}
              </button>
              {abc ? (
                <>
                  <div className="nv-yue-abc-label">乐谱（ABC，可直接改）</div>
                  <textarea
                    className="nv-yue-abc nodrag"
                    rows={6}
                    value={abc}
                    spellCheck={false}
                    onChange={(e) => updateSelectedData({ abc: e.target.value })}
                  />
                </>
              ) : null}
              {planMsg ? <div className="nv-loop-msg">{planMsg}</div> : null}
            </div>
          ) : null}
        </div>
      ) : null}

      {/* 抽卡闭环产物（V4.40.10）：推荐种子 / 代理分 / 坏区重绘。
          此前这些字段只回传给 Agent、前端零消费（DEFECT C），现直接展示在卡片检查器里。 */}
      {GEN_WITH_QUALITY && (rec || proxyScore !== undefined || badCount > 0) ? (
        <div className="nv-insp-field nv-insp-loop">
          <label>抽卡闭环</label>
          <div className="nv-loop-body">
            {rec && (rec.best_seed != null || rec.mean != null) ? (
              <div className="nv-loop-row">
                <span className="nv-loop-k">推荐</span>
                <span className="nv-loop-v">
                  {rec.best_seed != null ? `种子 ${rec.best_seed}` : "高分组"}
                  {rec.mean != null ? ` · 均分 ${(rec.mean * 100).toFixed(0)}` : ""}
                  {rec.n ? ` · ${rec.n} 次` : ""}
                </span>
              </div>
            ) : null}
            <div className="nv-loop-row">
              <span className="nv-loop-k">代理分</span>
              <span className="nv-loop-v">
                {proxyScore !== undefined
                  ? `${(proxyScore * 100).toFixed(0)} 分${isProxy ? "（仅供参考）" : ""}`
                  : "—"}
              </span>
            </div>
            {badCount > 0 ? (
              <div className="nv-loop-row">
                <span className="nv-loop-k">坏区</span>
                <span className="nv-loop-v nv-loop-warn">
                  检出 {badCount} 处，可局部重绘（只修坏区，不重抽整张）
                </span>
              </div>
            ) : null}
            {badCount > 0 && typeof d.imageUrl === "string" && d.imageUrl ? (
              <div className="nv-loop-row">
                <button
                  type="button"
                  className="nv-loop-repair"
                  disabled={repairBusy}
                  onClick={doRepair}
                  title="只重绘坏区，其余像素保持原图；会消耗一次云端额度"
                >
                  {repairBusy ? "修复中…" : "局部重绘坏区"}
                </button>
              </div>
            ) : null}
            {repairMsg ? <div className="nv-loop-msg">{repairMsg}</div> : null}
          </div>
        </div>
      ) : null}

      {/* AI 增强（LibTV 对标补强 刀3，2026-10-12 用户授权解冻）：图像节点本地引擎
          超分/抠像，与 Agent 能力 canvas.ai_upscale / canvas.ai_matte 同一后端。
          复用 .nv-loop-* 既有样式；如实回报引擎与降级。
          不改：磁吸阈值/卡片尺寸 240×200/gap/三段式阻力/跟手/单轴吸附/让位/Bond/方向无语义/空间记忆配色。
          Wave 0 #13（2026-10-15）：按钮由 GET /host/enhance-intents 目录驱动
          （原先硬编码两个，现后端 face 意图也能用）。heal/style 因缺参数控件不渲染
          —— 见 hostEnhanceIntents.ts 判据表。 */}
      {kind === "image" && typeof d.imageUrl === "string" && d.imageUrl ? (
        <div className="nv-insp-field nv-insp-loop">
          <label>AI 增强</label>
          <div className="nv-loop-body">
            {(() => {
              // 目录优先；拉不到（bridge 未起/端点失败）回落 FALLBACK_INTENTS，不白屏。
              const intents = selectDirectIntents(intentsCat);
              const shown = intents.length ? intents : FALLBACK_INTENTS;
              return shown.map((it) => (
                <div className="nv-loop-row" key={it.id}>
                  <button
                    type="button"
                    className="nv-loop-repair"
                    disabled={enhBusy}
                    onClick={() => doEnhance(it.id)}
                    title={it.hint || intentButtonLabel(it)}
                  >
                    {enhBusy ? "处理中…" : `AI ${intentButtonLabel(it)}`}
                  </button>
                </div>
              ));
            })()}
            {intentsCat === null ? (
              <div className="nv-loop-msg">意图目录未取到，用内置清单</div>
            ) : null}
            {enhMsg ? <div className="nv-loop-msg">{enhMsg}</div> : null}
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

          {/* AI 编剧（LibTV 对标补强 刀3，2026-10-12 用户授权解冻）：剧本卡片标题当
              主题 → LLM 完整剧本（pipeline.script_write / /host/script-write 同源）。
              已有正文不覆盖；模板降级如实标注。复用 .nv-loop-* 既有样式。 */}
          {kind === "script" ? (
            <div className="nv-insp-field nv-insp-loop">
              <label>AI 编剧</label>
              <div className="nv-loop-body">
                <div className="nv-loop-row">
                  <button
                    type="button"
                    className="nv-loop-repair"
                    disabled={swBusy}
                    onClick={doScriptWrite}
                    title="把卡片标题当主题，LLM 生成完整剧本（云→本地→模板三级降级）"
                  >
                    {swBusy ? "写作中…" : "AI 生成剧本"}
                  </button>
                  <button
                    type="button"
                    className="nv-loop-repair"
                    disabled={cpBusy}
                    onClick={runComplianceCheck}
                    title="对照画布上的镜头与角色做一致性检查（角色冲突 / 场景遗漏 / 节奏断裂 / Prompt 偏离），提审前查一遍"
                  >
                    {cpBusy ? "检查中…" : "🛡️ 合规检查"}
                  </button>
                </div>
                {swMsg ? <div className="nv-loop-msg">{swMsg}</div> : null}
                {cpMsg ? <div className="nv-loop-msg">{cpMsg}</div> : null}
                {(() => {
                  // 分桶渲染：warning 置前且标红，info 标黄，其余（ok 等）中性。
                  // 逐条 message 来自后端 suggestions，前端不加工文案。
                  const sug = cpRes?.suggestions || [];
                  if (!sug.length) return null;
                  const b = bucketComplianceLevels(sug);
                  return (
                    <ul className="nv-cp-list">
                      {[...b.warning, ...b.info, ...b.other].map((s, i) => {
                        const lv = String(s.level || "").trim().toLowerCase();
                        const cls =
                          lv === "warning" ? "warn" : lv === "info" ? "info" : "other";
                        return (
                          <li key={i} className={`nv-cp-item ${cls}`}>
                            <b>{s.category || "建议"}</b>
                            {s.message || ""}
                          </li>
                        );
                      })}
                    </ul>
                  );
                })()}
              </div>
            </div>
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
