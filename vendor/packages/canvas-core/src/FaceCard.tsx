/**
 * 独立捏脸卡片（FaceCard）—— 元数据驱动滑杆 + three.js 实时预览。
 *
 * 定位（与 faceParams.ts 头注释一致）：
 *  - 卡片只负责「调参数」；参数结构/校验/随机全部走 faceParams 唯一真相源；
 *  - 预览只负责「看效果」：用 faceHeadParts.buildFaceLayer 把参数长成 3D 头。
 *    ⚠️ 导演台挂载 faceLayer **尚未接线**（2026-10-13 审查实测）：
 *    riggedHumanoid / Stage3D 对 faceHeadParts 零引用，当前「卡片所见」
 *    只保证与未来挂载用**同一套几何代码**，不代表导演台已经能显示。
 *  - 本组件**不碰 store、不碰节点、不碰导演台**：initial 传入、onConfirm 回传序列化串，
 *    接线由调用方决定（当前仅卡片自身）。
 *
 * 纪律：
 *  - 零随机：随机走 randomFaceParams(确定性种子)，禁止 Math.random()。
 *  - 唯一入口：所有外部输入先过 normalizeFaceParams。
 *  - 资源：卸载时 disposeFaceParts + renderer/controls 全量释放，不泄漏 WebGL 上下文。
 */
import React, { memo, useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import {
  DEFAULT_FACE_PARAMS,
  EMOTION_PRESETS,
  ACCESSORY_META,
  BROW_LABELS,
  EYE_LABELS,
  LIP_LABELS,
  EYE_COLOR_HEX,
  MAKEUP_PALETTE,
  SKIN_PALETTE,
  HAIR_PALETTE,
  normalizeFaceParams,
  randomFaceParams,
  serializeFaceParams,
  type FaceParams,
  type FaceEmotionId,
  type BrowStyleId,
  type EyeStyleId,
  type EyeColorId,
  type LipStyleId,
  type HairAccessoryId,
} from "./faceParams";
import { buildFaceLayer, disposeFaceParts } from "./faceHeadParts";
import {
  FACE_TEMPLATE_THUMB_MANIFEST,
  OFFICIAL_FACE_TEMPLATES,
  applyFaceTemplate,
  describeFace,
  findFaceTemplate,
  templateThumbUrl,
  type FaceTemplate,
} from "./faceTemplates";
import { generateFaceTemplateViaHost } from "./bridge";
import {
  deleteFacePreset,
  downloadPresetFile,
  loadFacePresets,
  loadPresetParams,
  readPresetFile,
  saveFacePreset,
  type FacePreset,
} from "./facePresets";

export type FaceCardProps = {
  /** 初始参数（角色库存的序列化串 / 对象 / undefined 都合法，内部统一 normalize） */
  initial?: unknown;
  /** 角色 id（随机种子来源之一；缺省用 "face"） */
  characterId?: string;
  /** 该角色**已有**的头像参考图 URL（存在即「应用会覆盖它」⇒ 弹确认）。
   *  只读展示用，不参与任何生成逻辑；缺省/空串视为没有头像（首次创建，不打扰）。 */
  initialAvatarUrl?: string | null | undefined;
  /** 点「应用」：回传序列化串 + 规范化参数 + 预览快照 PNG(dataURL)。
   *  snapshot 供调用方上传为角色参考图；预览不可用时为 undefined（缺省即合法）。 */
  onConfirm?: (serialized: string, params: FaceParams, snapshot?: string) => void;
  /** 关闭卡片（必传，弹窗纪律） */
  onClose: () => void;
};

type TabId = "expression" | "features" | "shape" | "makeup" | "hair" | "skin" | "presets";

const TABS: { id: TabId; label: string }[] = [
  { id: "expression", label: "表情" },
  { id: "features", label: "五官" },
  { id: "shape", label: "头型" },
  { id: "makeup", label: "妆容" },
  { id: "hair", label: "发饰" },
  { id: "skin", label: "肤色" },
  { id: "presets", label: "预设" },
];

/** 头型滑杆元数据（Ruth2 式 shape sliders；字段名 → 展示名） */
const SHAPE_SLIDERS: { key: "headWidth" | "headHeight" | "jawWidth" | "cheekbone" | "chin"; label: string }[] = [
  { key: "headWidth", label: "脸宽" },
  { key: "headHeight", label: "脸长" },
  { key: "jawWidth", label: "下颌宽" },
  { key: "cheekbone", label: "颧骨" },
  { key: "chin", label: "下巴" },
];

/** 枚举选项：从 faceParams 的标签表派生（UI 不另写一份中文，杜绝两处漂移） */
const BROW_OPTIONS: { id: BrowStyleId; label: string }[] = (
  Object.keys(BROW_LABELS) as BrowStyleId[]
).map((id) => ({ id, label: BROW_LABELS[id] }));
const EYE_OPTIONS: { id: EyeStyleId; label: string }[] = (
  Object.keys(EYE_LABELS) as EyeStyleId[]
).map((id) => ({ id, label: EYE_LABELS[id] }));
const LIP_OPTIONS: { id: LipStyleId; label: string }[] = (
  Object.keys(LIP_LABELS) as LipStyleId[]
).map((id) => ({ id, label: LIP_LABELS[id] }));

/* ───────────────────────── 小组件 ───────────────────────── */

/** 数值滑杆（带锁定勾选：锁定字段随机重 roll 时保持原值） */
function SliderRow(props: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  locked: boolean;
  onLock?: (v: boolean) => void;
  onChange: (v: number) => void;
}) {
  const { label, value, min, max, step, locked, onLock, onChange } = props;
  return (
    <label className="fc-row">
      <span className="fc-label">{label}</span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      <span className="fc-num">{value.toFixed(2)}</span>
      {onLock ? (
        <span className="fc-lock" title="锁定：随机时保持此值">
          <input type="checkbox" checked={locked} onChange={(e) => onLock(e.target.checked)} />
        </span>
      ) : null}
    </label>
  );
}

/** 色块选择（null = 关闭该项妆容） */
function SwatchRow(props: {
  label: string;
  value: string | null;
  palette: string[];
  onChange: (v: string | null) => void;
}) {
  const { label, value, palette, onChange } = props;
  return (
    <div className="fc-row fc-swatch-row">
      <span className="fc-label">{label}</span>
      <div className="fc-swatches">
        <button
          type="button"
          className={`fc-swatch fc-swatch-off${value === null ? " on" : ""}`}
          title="无"
          aria-pressed={value === null}
          onClick={() => onChange(null)}
        >
          ∅
        </button>
        {palette.map((c) => (
          <button
            key={c}
            type="button"
            className={`fc-swatch${value === c ? " on" : ""}`}
            style={{ background: c }}
            title={c}
            aria-pressed={value === c}
            onClick={() => onChange(c)}
          />
        ))}
      </div>
    </div>
  );
}

/** 单选按钮组（表情/眉形/眼型/唇形/发饰通用） */
function OptionRow<T extends string>(props: {
  label: string;
  value: T;
  options: { id: T; label: string }[];
  onChange: (v: T) => void;
}) {
  const { label, value, options, onChange } = props;
  return (
    <div className="fc-row fc-option-row">
      <span className="fc-label">{label}</span>
      <div className="fc-options">
        {options.map((o) => (
          <button
            key={o.id}
            type="button"
            className={`fc-opt${value === o.id ? " on" : ""}`}
            aria-pressed={value === o.id}
            onClick={() => onChange(o.id)}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

/* ───────────────────────── 3D 预览 ───────────────────────── */

/**
 * 捏脸预览视口：独立 mini-scene（无 GLB，肤色壳即「头」），
 * 几何全部来自 buildFaceLayer —— 与导演台同一真源。
 * 附带 Ruth2 式「眨眼预览」：确定性周期眨眼（非随机），仅作用于预览，不进参数。
 */
function FacePreview(props: { params: FaceParams; captureRef: React.MutableRefObject<(() => string | null) | null> }) {
  const { params, captureRef } = props;
  // P3 优化（2026-10-13）：用 useDeferredValue 把昂贵的整层重建从滑杆输入中剥离，
  // 拖动时 UI 立即响应，3D 预览在浏览器空闲后重建，避免卡顿。
  const deferredParams = useDeferredValue(params);
  const hostRef = useRef<HTMLDivElement>(null);
  const engineRef = useRef<{
    renderer: THREE.WebGLRenderer;
    scene: THREE.Scene;
    camera: THREE.PerspectiveCamera;
    controls: OrbitControls;
    raf: number;
    /** 眼组引用（重建层时刷新），眨眼动画只改 scale.y */
    eyes: THREE.Object3D[];
  } | null>(null);

  // 初始化一次（StrictMode 双挂载安全：cleanup 完整释放）
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const w = host.clientWidth || 320;
    const h = host.clientHeight || 360;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#10151f");
    // 相机对准「头中心」（faceLayer 坐标系：head 骨骼原点=颈根，头心 y≈0.112）
    const camera = new THREE.PerspectiveCamera(38, w / h, 0.01, 10);
    camera.position.set(0, 0.13, 0.55);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    renderer.setSize(w, h);
    host.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 0.112, 0);
    controls.enableDamping = true;
    controls.minDistance = 0.2;
    controls.maxDistance = 1.5;
    controls.update();

    // 三点布光（面部可读性优先，与导演台主光方向一致的 +Z 前光）
    scene.add(new THREE.AmbientLight(0xffffff, 0.55));
    const key = new THREE.DirectionalLight(0xffffff, 1.1);
    key.position.set(0.35, 0.5, 0.8);
    const rim = new THREE.DirectionalLight(0x88aaff, 0.45);
    rim.position.set(-0.6, 0.2, -0.5);
    scene.add(key, rim);

    let raf = 0;
    // 眨眼预览：每 4.2s 一次 140ms 闭眼脉冲（确定性时间函数，不用 Math.random）
    const BLINK_PERIOD = 4200;
    const BLINK_DUR = 140;
    const tick = () => {
      const eng = engineRef.current;
      if (eng && eng.eyes.length) {
        const phase = performance.now() % BLINK_PERIOD;
        const k = phase < BLINK_DUR ? 1 - Math.sin((Math.PI * phase) / BLINK_DUR) * 0.92 : 1;
        for (const eye of eng.eyes) {
          eye.scale.y = (eye.userData.baseOpenScale as number) * k;
        }
      }
      controls.update();
      renderer.render(scene, camera);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    engineRef.current = { renderer, scene, camera, controls, raf, eyes: [] };
    // 快照入口：先同步渲染一帧再读像素 —— WebGLRenderer 默认 preserveDrawingBuffer:false，
    // 不在渲染后立即读取会拿到空图（标准做法，勿删）。
    // P3 修复（2026-10-13 审查）：快照前把眨眼动画的 scale.y 重置回基准开合，
    // 否则 4.2s 周期里 140ms 闭眼窗内点「应用」会把闭眼脸存成 avatar_url 参考图。
    captureRef.current = () => {
      const eng = engineRef.current;
      if (eng) {
        for (const eye of eng.eyes) {
          eye.scale.y = (eye.userData.baseOpenScale as number) ?? 1;
        }
      }
      renderer.render(scene, camera);
      const out = renderer.domElement.toDataURL("image/png");
      return out;
    };

    const onResize = () => {
      const nw = host.clientWidth || w;
      const nh = host.clientHeight || h;
      camera.aspect = nw / nh;
      camera.updateProjectionMatrix();
      renderer.setSize(nw, nh);
    };
    const ro = new ResizeObserver(onResize);
    ro.observe(host);

    return () => {
      cancelAnimationFrame(engineRef.current?.raf ?? raf);
      ro.disconnect();
      controls.dispose();
      disposeFaceParts(scene);
      renderer.dispose();
      host.removeChild(renderer.domElement);
      engineRef.current = null;
      captureRef.current = null;
    };
  }, []);

  // 参数变化 → 整层重建（dispose 旧层防泄漏）。几何量小（~40 mesh），重建即预览，无需增量 diff。
  // 依赖 deferredParams：滑杆拖动时 params 高频变化，用 deferred 降低重建频率。
  useEffect(() => {
    const eng = engineRef.current;
    if (!eng) return;
    disposeFaceParts(eng.scene);
    eng.scene.add(buildFaceLayer(deferredParams));
    // 重建后刷新眼组引用（眨眼动画目标；makeEye 在 userData 打了 eyeSide/baseOpenScale）
    const eyes: THREE.Object3D[] = [];
    eng.scene.traverse((o) => {
      if (o.userData.eyeSide !== undefined) eyes.push(o);
    });
    eng.eyes = eyes;
  }, [deferredParams]);

  return <div ref={hostRef} className="fc-preview" />;
}

/* ───────────────────────── 卡片主体 ───────────────────────── */

export const FaceCard = memo(function FaceCard({ initial, characterId, initialAvatarUrl, onConfirm, onClose }: FaceCardProps) {
  const [params, setParams] = useState<FaceParams>(() => normalizeFaceParams(initial));
  const [tab, setTab] = useState<TabId>("expression");
  const [locked, setLocked] = useState<ReadonlySet<keyof FaceParams>>(new Set());
  /** 随机种子计数：每次点「随机」+1（确定性可复现，非 Math.random） */
  const [rollCount, setRollCount] = useState(0);
  /** 当前套用的官方模板（null = 自定义/AI 生成） */
  const [activeTemplateId, setActiveTemplateId] = useState<string | null>(null);
  /** AI 生成（提示词 → 参数），只改预览不落库 */
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiBusy, setAiBusy] = useState(false);
  const [aiMsg, setAiMsg] = useState("");
  /** 模板缩略图是否已生成（看清单；没有就回落「色点 + 名称」，不发 8 个 404） */
  const [thumbsReady, setThumbsReady] = useState(false);
  /** 预览快照入口（由 FacePreview 挂载后注入；点「应用」时取 3D 头 PNG 作参考图） */
  const captureRef = useRef<(() => string | null) | null>(null);

  // C + D：预设存取/导入导出状态
  const [presets, setPresets] = useState<FacePreset[]>([]);
  const [presetName, setPresetName] = useState("");
  const [selectedPreset, setSelectedPreset] = useState<FacePreset | null>(null);
  const [presetMsg, setPresetMsg] = useState("");
  useEffect(() => {
    try {
      setPresets(loadFacePresets());
    } catch {
      setPresets([]);
    }
  }, []);

  // 缩略图存在性探测：只看清单，不逐张 head 请求（清单由渲染脚本写）
  useEffect(() => {
    let cancelled = false;
    fetch(FACE_TEMPLATE_THUMB_MANIFEST, { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!cancelled && data && data.items && Object.keys(data.items).length > 0) {
          setThumbsReady(true);
        }
      })
      .catch(() => {
        /* 无清单 = 未生成，保持色点卡（诚实回落） */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const refreshPresets = () => {
    try {
      setPresets(loadFacePresets());
    } catch {
      /* localStorage 禁用时静默失败 */
    }
  };

  const set = <K extends keyof FaceParams>(key: K, value: FaceParams[K]) =>
    setParams((prev) => ({ ...prev, [key]: value }));

  /** 选表情预设：四滑杆跟随预设（保持「选表情即生效」语义，与 normalizeFaceParams 一致） */
  const pickEmotion = (id: FaceEmotionId) => {
    const pres = EMOTION_PRESETS[id];
    setParams((prev) => ({
      ...prev,
      emotion: id,
      browLift: pres.browLift,
      eyeOpen: pres.eyeOpen,
      mouthOpen: pres.mouthOpen,
      mouthCurve: pres.mouthCurve,
    }));
  };

  const toggleLock = (key: keyof FaceParams, v: boolean) => {
    setLocked((prev) => {
      const next = new Set(prev);
      if (v) next.add(key);
      else next.delete(key);
      return next;
    });
  };

  const doRandom = () => {
    const seedKey = `${characterId || "face"}#${rollCount + 1}`;
    setRollCount((c) => c + 1);
    setParams((prev) => randomFaceParams(seedKey, locked, prev));
    setActiveTemplateId(null);
  };

  /** 套用官方模板：从 DEFAULT 起算的完整脸（不是在当前脸上打补丁）。 */
  const applyTemplate = (template: FaceTemplate) => {
    setParams(applyFaceTemplate(template));
    setActiveTemplateId(template.id);
    setRollCount(0);
    setAiMsg("");
  };

  /** AI 生成：提示词 → 参数（不落库；用户点「应用」才写回角色库）。 */
  const handleAiGenerate = async () => {
    const prompt = aiPrompt.trim();
    if (!prompt) {
      setAiMsg("先描述想要的脸，例如：冷白皮、猫眼、戴眼镜的知性姐姐");
      return;
    }
    const template = findFaceTemplate(activeTemplateId);
    const base = template ? applyFaceTemplate(template) : null;
    setAiBusy(true);
    setAiMsg("正在请 AI 生成…");
    const res = await generateFaceTemplateViaHost(
      prompt,
      base ? (base as unknown as Record<string, unknown>) : null,
    );
    setAiBusy(false);
    if (!res.ok) {
      setAiMsg(res.message || "生成失败");
      return;
    }
    try {
      setParams(normalizeFaceParams(res.params));
      setActiveTemplateId(null);
      setRollCount(0);
      setAiMsg("已应用 AI 生成结果；可继续微调，满意后点「应用」写回角色库");
    } catch (err) {
      setAiMsg("AI 返回的参数无法解析：" + String(err));
    }
  };

  // ── 预设操作（C + D） ──
  const handleSavePreset = () => {
    const name = presetName.trim();
    if (!name) { setPresetMsg("请输入预设名"); return; }
    const ok = saveFacePreset(name, params);
    if (!ok) { setPresetMsg("保存失败"); return; }
    setPresetName("");
    refreshPresets();
    setPresetMsg(`已保存「${name}」`);
  };

  const handleLoadPreset = (p: FacePreset) => {
    try {
      setParams(loadPresetParams(p));
      setSelectedPreset(p);
      setRollCount(0);
      setPresetMsg(`已加载「${p.name}」`);
    } catch (e) {
      setPresetMsg(`加载失败: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const handleDeletePreset = (p: FacePreset) => {
    deleteFacePreset(p.name);
    refreshPresets();
    if (selectedPreset?.name === p.name) setSelectedPreset(null);
    setPresetMsg(`已删除「${p.name}」`);
  };

  const handleImportFile = async (file: File | null) => {
    if (!file) return;
    const res = await readPresetFile(file);
    if (!res.ok) { setPresetMsg(`导入失败: ${res.error}`); return; }
    setParams(res.params);
    setRollCount(0);
    setPresetMsg(`已导入「${res.name}」；可点保存写入本地预设`);
  };

  const handleExportSelected = () => {
    if (!selectedPreset) { setPresetMsg("请先选择要导出的预设"); return; }
    downloadPresetFile(selectedPreset);
    setPresetMsg(`已导出「${selectedPreset.name}」`);
  };

  const dirty = useMemo(() => serializeFaceParams(params) !== serializeFaceParams(DEFAULT_FACE_PARAMS), [params]);

  // P3 修复（2026-10-13 审查）：补 Esc 关闭 —— 项目 Modal 纪律（见 ShortcutSettings）
  // 是「Esc / 点遮罩」双通道；此前只有遮罩和 ×。
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const onConfirmRef = useRef(onConfirm);
  onConfirmRef.current = onConfirm;
  const paramsRef = useRef(params);
  paramsRef.current = params;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCloseRef.current();
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        const cap = captureRef.current?.() ?? undefined;
        onConfirmRef.current?.(serializeFaceParams(paramsRef.current), paramsRef.current, cap);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const handleBackdropClose = useCallback(() => {
    if (dirty && !window.confirm("已修改捏脸参数，关闭将丢弃，确认？")) return;
    onClose();
  }, [dirty, onClose]);

  return (
    <div className="sg-modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) handleBackdropClose(); }}>
      <div className="sg-modal fc-card" role="dialog" aria-label="捏脸卡片">
        <style>{FACE_CARD_CSS}</style>
        <div className="sg-modal-head">
          <h2>捏脸 · 独立卡片</h2>
          <button type="button" className="sg-modal-x" onClick={onClose} aria-label="关闭">×</button>
        </div>

        <div className="fc-body">
          {/* 左栏：官方模板 + AI 生成（先选模板起步，再用 AI 补细节） */}
          <div className="fc-templates">
            <div className="fc-rail-title">模板</div>
            {OFFICIAL_FACE_TEMPLATES.map((t) => (
              <button
                key={t.id}
                type="button"
                className={"fc-template" + (activeTemplateId === t.id ? " on" : "")}
                onClick={() => applyTemplate(t)}
                title={t.tagline}
              >
                {thumbsReady ? (
                  <img
                    className="fc-template-thumb"
                    src={templateThumbUrl(t.id)}
                    alt=""
                    onError={(e) => {
                      e.currentTarget.style.display = "none";
                    }}
                  />
                ) : (
                  <span className="fc-template-dot" style={{ background: t.accent }} />
                )}
                <span className="fc-template-text">
                  <span className="fc-template-name">{t.name}</span>
                  <span className="fc-template-tag">{t.tagline}</span>
                </span>
              </button>
            ))}
            <div className="fc-rail-title">AI 生成</div>
            <input
              className="fc-ai-input"
              value={aiPrompt}
              onChange={(e) => setAiPrompt(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !aiBusy) void handleAiGenerate();
              }}
              placeholder="描述想要的脸…"
              disabled={aiBusy}
            />
            <button
              type="button"
              className="btn small fc-ai-btn"
              onClick={() => void handleAiGenerate()}
              disabled={aiBusy}
            >
              {aiBusy ? "生成中…" : "✨ AI 生成"}
            </button>
            {aiMsg && <div className="fc-ai-msg">{aiMsg}</div>}
          </div>

          {/* 中间：实时预览 + 当前参数摘要 */}
          <div className="fc-stage">
            <FacePreview params={params} captureRef={captureRef} />
            <div className="fc-summary">
              {describeFace(params).map((trait) => (
                <span key={trait.key} className="fc-chip">{trait.label}</span>
              ))}
            </div>
          </div>

          <div className="fc-side">
            <div className="sg-modal-tabs">
              {TABS.map((t) => (
                <button key={t.id} type="button" className={tab === t.id ? "on" : ""} onClick={() => setTab(t.id)}>
                  {t.label}
                </button>
              ))}
            </div>

            {tab === "expression" && (
              <>
                <OptionRow
                  label="表情"
                  value={params.emotion}
                  options={(Object.keys(EMOTION_PRESETS) as FaceEmotionId[]).map((id) => ({ id, label: EMOTION_PRESETS[id].label }))}
                  onChange={pickEmotion}
                />
                <SliderRow label="表情强度" value={params.emotionIntensity} min={0} max={1} step={0.05}
                  locked={locked.has("emotionIntensity")} onLock={(v) => toggleLock("emotionIntensity", v)}
                  onChange={(v) => set("emotionIntensity", v)} />
                {params.emotionIntensity < 1 && (
                  <div className="fc-hint">
                    预览按强度 {Math.round(params.emotionIntensity * 100)}% 向「平静」打折显示；下方四个滑杆是满强度值
                  </div>
                )}
                <SliderRow label="眉毛扬压" value={params.browLift} min={-1} max={1} step={0.05}
                  locked={locked.has("browLift")} onLock={(v) => toggleLock("browLift", v)}
                  onChange={(v) => set("browLift", v)} />
                <SliderRow label="眼睛开合" value={params.eyeOpen} min={0} max={2} step={0.05}
                  locked={locked.has("eyeOpen")} onLock={(v) => toggleLock("eyeOpen", v)}
                  onChange={(v) => set("eyeOpen", v)} />
                <SliderRow label="嘴张开" value={params.mouthOpen} min={0} max={1} step={0.05}
                  locked={locked.has("mouthOpen")} onLock={(v) => toggleLock("mouthOpen", v)}
                  onChange={(v) => set("mouthOpen", v)} />
                <SliderRow label="嘴角弧度" value={params.mouthCurve} min={-1} max={1} step={0.05}
                  locked={locked.has("mouthCurve")} onLock={(v) => toggleLock("mouthCurve", v)}
                  onChange={(v) => set("mouthCurve", v)} />
              </>
            )}

            {tab === "features" && (
              <>
                <OptionRow label="眉形" value={params.browStyle} options={BROW_OPTIONS} onChange={(v) => set("browStyle", v)} />
                <SwatchRow label="眉色" value={params.browColor} palette={HAIR_PALETTE} onChange={(v) => set("browColor", v)} />
                <OptionRow label="眼型" value={params.eyeStyle} options={EYE_OPTIONS} onChange={(v) => set("eyeStyle", v)} />
                <div className="fc-row fc-option-row">
                  <span className="fc-label">瞳色</span>
                  <div className="fc-swatches">
                    {(Object.keys(EYE_COLOR_HEX) as EyeColorId[]).map((id) => (
                      <button key={id} type="button"
                        className={`fc-swatch${params.eyeColor === id ? " on" : ""}`}
                        style={{ background: EYE_COLOR_HEX[id] }} title={id}
                        onClick={() => setParams((prev) => ({ ...prev, eyeColor: id, eyeColorRight: null }))} />
                    ))}
                  </div>
                </div>
                <div className="fc-row fc-option-row">
                  <span className="fc-label">右眼异色</span>
                  <div className="fc-swatches">
                    <button type="button" className={`fc-swatch fc-swatch-off${params.eyeColorRight === null ? " on" : ""}`}
                      title="与左眼一致" onClick={() => set("eyeColorRight", null)}>∅</button>
                    {(Object.keys(EYE_COLOR_HEX) as EyeColorId[]).map((id) => (
                      <button key={id} type="button"
                        className={`fc-swatch${params.eyeColorRight === id ? " on" : ""}`}
                        style={{ background: EYE_COLOR_HEX[id] }} title={id}
                        onClick={() => set("eyeColorRight", id)} />
                    ))}
                  </div>
                </div>
                <OptionRow label="唇形" value={params.lipStyle} options={LIP_OPTIONS} onChange={(v) => set("lipStyle", v)} />
              </>
            )}

            {tab === "shape" && (
              <>
                {SHAPE_SLIDERS.map((s) => (
                  <SliderRow
                    key={s.key}
                    label={s.label}
                    value={params[s.key]}
                    min={-1}
                    max={1}
                    step={0.05}
                    locked={locked.has(s.key)}
                    onLock={(v) => toggleLock(s.key, v)}
                    onChange={(v) => set(s.key, v)}
                  />
                ))}
                <div className="fc-hint">头型滑杆走顶点位移（Ruth2 式 shape sliders）：肤色壳与五官落点同步变形</div>
              </>
            )}

            {tab === "makeup" && (
              <>
                <SwatchRow label="腮红" value={params.blush} palette={MAKEUP_PALETTE} onChange={(v) => set("blush", v)} />
                {params.blush && (
                  <SliderRow label="腮红浓度" value={params.blushAlpha} min={0} max={1} step={0.05}
                    locked={locked.has("blushAlpha")} onLock={(v) => toggleLock("blushAlpha", v)}
                    onChange={(v) => set("blushAlpha", v)} />
                )}
                <SwatchRow label="眼影" value={params.eyeshadow} palette={MAKEUP_PALETTE} onChange={(v) => set("eyeshadow", v)} />
                {params.eyeshadow && (
                  <SliderRow label="眼影浓度" value={params.eyeshadowAlpha} min={0} max={1} step={0.05}
                    locked={locked.has("eyeshadowAlpha")} onLock={(v) => toggleLock("eyeshadowAlpha", v)}
                    onChange={(v) => set("eyeshadowAlpha", v)} />
                )}
                <SwatchRow label="唇彩" value={params.lipColor} palette={MAKEUP_PALETTE} onChange={(v) => set("lipColor", v)} />
                {params.lipColor && (
                  <SliderRow label="唇彩浓度" value={params.lipAlpha} min={0} max={1} step={0.05}
                    locked={locked.has("lipAlpha")} onLock={(v) => toggleLock("lipAlpha", v)}
                    onChange={(v) => set("lipAlpha", v)} />
                )}
                <SwatchRow label="眼线" value={params.eyeliner} palette={["#111111", "#3a3f8c", "#a8326b"]} onChange={(v) => set("eyeliner", v)} />
                <SwatchRow label="面纹" value={params.faceMark} palette={MAKEUP_PALETTE} onChange={(v) => set("faceMark", v)} />
              </>
            )}

            {tab === "hair" && (
              <>
                <OptionRow
                  label="发饰"
                  value={params.hairAccessory}
                  options={(Object.keys(ACCESSORY_META) as HairAccessoryId[]).map((id) => ({ id, label: ACCESSORY_META[id].label }))}
                  onChange={(v) => set("hairAccessory", v)}
                />
                {params.hairAccessory !== "none" && (
                  <>
                    <SwatchRow label="主色" value={params.accessoryColor} palette={MAKEUP_PALETTE}
                      onChange={(v) => set("accessoryColor", v ?? DEFAULT_FACE_PARAMS.accessoryColor)} />
                    {ACCESSORY_META[params.hairAccessory].dual && (
                      <SwatchRow label="副色" value={params.accessoryColor2} palette={MAKEUP_PALETTE}
                        onChange={(v) => set("accessoryColor2", v ?? DEFAULT_FACE_PARAMS.accessoryColor2)} />
                    )}
                  </>
                )}
              </>
            )}

            {tab === "skin" && (
              <>
                <div className="fc-row fc-option-row">
                  <span className="fc-label">肤色</span>
                  <div className="fc-swatches">
                    {SKIN_PALETTE.map((c) => (
                      <button key={c} type="button"
                        className={`fc-swatch${params.skinTone === c ? " on" : ""}`}
                        style={{ background: c }} title={c}
                        onClick={() => set("skinTone", c)} />
                    ))}
                  </div>
                </div>
              </>
            )}

            {tab === "presets" && (
              <>
                <div className="fc-row fc-preset-save">
                  <input
                    type="text"
                    className="fc-preset-input"
                    placeholder="预设名（如：古风御姐）"
                    maxLength={32}
                    value={presetName}
                    onChange={(e) => setPresetName(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") handleSavePreset(); }}
                  />
                  <button type="button" className="btn" onClick={handleSavePreset}>保存当前</button>
                </div>
                <div className="fc-preset-list">
                  {presets.length === 0 && <div className="fc-hint">暂无本地预设；可导入 .json 或保存当前参数</div>}
                  {presets.map((p) => (
                    <div key={p.name} className={`fc-preset-item${selectedPreset?.name === p.name ? " on" : ""}`}>
                      <button type="button" className="fc-preset-name" onClick={() => handleLoadPreset(p)} title="加载">
                        {p.name}
                      </button>
                      <div className="fc-preset-actions">
                        <button type="button" className="btn small" onClick={() => handleExportSelected?.()} disabled={selectedPreset?.name !== p.name}>
                          导出
                        </button>
                        <button type="button" className="btn small danger" onClick={() => handleDeletePreset(p)}>删除</button>
                      </div>
                    </div>
                  ))}
                </div>
                <div className="fc-row fc-preset-import">
                  <label className="btn small">
                    导入 .json
                    <input type="file" accept=".json,application/json" onChange={(e) => handleImportFile(e.target.files?.[0] ?? null)} />
                  </label>
                  <button type="button" className="btn small" onClick={handleExportSelected} disabled={!selectedPreset}>导出选中</button>
                </div>
                {presetMsg && <div className="fc-preset-msg">{presetMsg}</div>}
                <div className="fc-hint">预设仅存于本机浏览器 localStorage；导出后可跨设备/会话迁移。</div>
              </>
            )}
          </div>
        </div>

        <div className="sg-modal-foot">
          <div className="fc-foot-hint">{dirty ? "已修改" : "默认素颜"} · 随机种子 #{rollCount}</div>
          <div className="fc-foot-actions">
            <button type="button" className="btn" onClick={() => setParams(normalizeFaceParams(undefined))}>重置</button>
            <button type="button" className="btn" onClick={doRandom}>随机</button>
            <button
              type="button"
              className="btn primary"
              onClick={() => {
                /* 覆盖参考图前确认（2026-10-21）：
                   点「应用」会把 3D 头快照写为该角色 avatar_url。若该角色已有头像，
                   无条件覆盖会让用户丢图且无感知 ⇒ 已有头像时显式确认。
                   只在**本次会真的带快照**时才问，避免「只想改参数」被多余打断。 */
                // captureRef 可能返回 string | null（null = 预览未就绪）⇒ 归一成 undefined，
                // 与 onConfirm 的 snapshot 可选参数签名一致（原实现直接用 ?? undefined）。
                const snap = captureRef.current?.() ?? undefined;
                const hasAvatar = typeof initialAvatarUrl === "string" && initialAvatarUrl.length > 0;
                if (snap && hasAvatar && !window.confirm("将用当前预览覆盖该角色已有的头像参考图？\n\n点「确定」覆盖；点「取消」则只保存参数、不动头像。")) {
                  return;
                }
                onConfirm?.(serializeFaceParams(params), params, snap);
              }}
            >
              应用
            </button>
          </div>
        </div>
      </div>
    </div>
  );
});

/* ───────────────────────── 卡片样式（内联，避免动全局 styles.css） ───────────────────────── */

const FACE_CARD_CSS = `
.fc-card { width: min(940px, 97vw); }
.fc-body { display: flex; gap: 12px; align-items: stretch; }
.fc-preview { flex: 1 1 auto; height: 300px; border-radius: 10px; overflow: hidden; background: #10151f; }
.fc-side { flex: 1; min-width: 0; max-height: 340px; overflow-y: auto; }

/* 左栏：模板库 + AI 生成（2026-10-21「永劫无间式」捏脸） */
.fc-templates { flex: 0 0 156px; max-height: 340px; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; }
.fc-rail-title { font-size: 10px; color: #6b7684; letter-spacing: 1px; margin: 2px 0 3px; text-transform: uppercase; }
.fc-template { display: flex; align-items: center; gap: 8px; padding: 7px 8px; border: 1px solid #2a3342; border-radius: 8px; background: #121822; color: #d6dde8; cursor: pointer; text-align: left; }
.fc-template:hover { border-color: #3a4658; }
.fc-template.on { border-color: #6c9fff; background: #172033; }
.fc-template-dot { width: 14px; height: 14px; border-radius: 50%; flex: 0 0 14px; }
.fc-template-thumb { width: 28px; height: 35px; border-radius: 4px; object-fit: cover; flex: 0 0 28px; }
.fc-template-text { display: flex; flex-direction: column; min-width: 0; }
.fc-template-name { font-size: 12px; }
.fc-template-tag { font-size: 10px; color: #7b8797; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.fc-ai-input { width: 100%; padding: 6px 8px; border-radius: 7px; border: 1px solid #2a3342; background: #0e141c; color: #d6dde8; font-size: 11px; box-sizing: border-box; }
.fc-ai-btn { width: 100%; }
.fc-ai-msg { font-size: 10px; color: #8b9bb0; line-height: 1.45; }
/* 中间：预览 + 参数摘要 */
.fc-stage { flex: 0 0 300px; display: flex; flex-direction: column; gap: 8px; }
.fc-summary { display: flex; flex-wrap: wrap; gap: 4px; }
.fc-chip { font-size: 10px; padding: 2px 7px; border-radius: 999px; border: 1px solid #2a3342; background: #121822; color: #9aa4b2; }
.fc-row { display: flex; align-items: center; gap: 8px; margin: 8px 0; }
.fc-label { flex: 0 0 64px; font-size: 12px; color: #9aa4b2; }
.fc-row input[type="range"] { flex: 1; }
.fc-num { flex: 0 0 38px; font-size: 11px; color: #6b7684; text-align: right; }
.fc-lock input { margin: 0; }
.fc-swatches { display: flex; flex-wrap: wrap; gap: 5px; }
.fc-swatch { width: 20px; height: 20px; border-radius: 5px; border: 1px solid #2a3342; cursor: pointer; padding: 0; }
.fc-swatch.on { outline: 2px solid #7aa2ff; outline-offset: 1px; }
.fc-swatch-off { background: #1a212d; color: #6b7684; font-size: 12px; line-height: 18px; }
.fc-options { display: flex; flex-wrap: wrap; gap: 6px; }
.fc-opt { padding: 4px 10px; border-radius: 6px; border: 1px solid #2a3342; background: #161d29; color: #9aa4b2; font-size: 12px; cursor: pointer; }
.fc-opt.on { color: #fff; border-color: #7aa2ff; background: #22304d; }
.fc-foot-hint { font-size: 12px; color: #6b7684; }
.fc-hint { margin: 8px 0; font-size: 11px; color: #6b7684; line-height: 1.5; }
.fc-foot-actions { display: flex; gap: 8px; }
.btn.small { padding: 3px 8px; font-size: 11px; }
.btn.small.danger { background: #3d1f24; color: #ff9aa2; border-color: #5c2a32; }
.btn.small.danger:hover { background: #5c2a32; }
.btn:disabled { opacity: 0.45; cursor: not-allowed; }
/* 预设面板 */
.fc-preset-save { gap: 8px; }
.fc-preset-input { flex: 1; min-width: 0; padding: 5px 8px; border-radius: 6px; border: 1px solid #2a3342; background: #10151f; color: #e2e8f0; font-size: 12px; }
.fc-preset-list { display: flex; flex-direction: column; gap: 6px; max-height: 180px; overflow-y: auto; margin: 8px 0; }
.fc-preset-item { display: flex; align-items: center; gap: 8px; padding: 5px 6px; border-radius: 6px; border: 1px solid transparent; background: #161d29; }
.fc-preset-item.on { border-color: #7aa2ff; background: #22304d; }
.fc-preset-name { flex: 1; text-align: left; background: transparent; border: none; color: #9aa4b2; font-size: 12px; cursor: pointer; padding: 0; }
.fc-preset-name:hover { color: #e2e8f0; }
.fc-preset-actions { display: flex; gap: 6px; }
.fc-preset-import { gap: 8px; }
.fc-preset-import input[type="file"] { display: none; }
.fc-preset-msg { font-size: 11px; color: #7aa2ff; margin: 4px 0; }
@media (max-width: 640px) {
  .fc-body { flex-direction: column; }
  .fc-preview { flex: none; width: 100%; }
  .fc-stage { flex: none; width: 100%; }
  .fc-templates { flex: none; max-height: 180px; }
}
/* P3 修复（2026-10-13 审查）：浅色主题适配（项目不变量 7「内联样式=主题盲区」点名反模式）。
   色板对齐 styles.css 的 html[data-theme='light'] token（--line/--text/--muted/--accent）。 */
html[data-theme='light'] .fc-label { color: #6b7790; }
html[data-theme='light'] .fc-num { color: #6b7790; }
html[data-theme='light'] .fc-swatch { border-color: #cdd5e3; }
html[data-theme='light'] .fc-swatch.on { outline-color: #2563eb; }
html[data-theme='light'] .fc-swatch-off { background: #eef1f7; color: #6b7790; }
html[data-theme='light'] .fc-opt { border-color: #cdd5e3; background: #ffffff; color: #172033; }
html[data-theme='light'] .fc-opt.on { color: #ffffff; border-color: #2563eb; background: #2563eb; }
html[data-theme='light'] .fc-foot-hint { color: #6b7790; }
html[data-theme='light'] .fc-hint { color: #6b7790; }
html[data-theme='light'] .fc-preset-input { background: #ffffff; color: #172033; border-color: #cdd5e3; }
html[data-theme='light'] .fc-preset-item { background: #f6f7fb; }
html[data-theme='light'] .fc-preset-item.on { background: #e6eefc; border-color: #2563eb; }
html[data-theme='light'] .fc-preset-name { color: #172033; }
html[data-theme='light'] .fc-preset-msg { color: #2563eb; }
html[data-theme='light'] .fc-rail-title { color: #6b7790; }
html[data-theme='light'] .fc-template { border-color: #cdd5e3; background: #ffffff; color: #172033; }
html[data-theme='light'] .fc-template.on { border-color: #2563eb; background: #e6eefc; }
html[data-theme='light'] .fc-template-tag { color: #6b7790; }
html[data-theme='light'] .fc-ai-input { border-color: #cdd5e3; background: #ffffff; color: #172033; }
html[data-theme='light'] .fc-ai-msg { color: #6b7790; }
html[data-theme='light'] .fc-chip { border-color: #cdd5e3; background: #f6f7fb; color: #6b7790; }
/* 3D 预览视口保持深底（建模软件惯例，浅底下五官对比度不足），仅统一圆角边线 */
html[data-theme='light'] .fc-preview { border: 1px solid #cdd5e3; }
`;

export default FaceCard;
