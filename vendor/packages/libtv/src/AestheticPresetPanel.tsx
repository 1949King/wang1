/**
 * 美学预设包面板（审美能力的沉淀与复用）
 *
 * 落在「提示词库」页的第三个 Tab（StudioPages，非冻结）。
 * 只调用 store 既有 updateNodeData / updateSelectedData 写入分镜，不触碰画布冻结区；
 * 复用现有 .btn / .field / .lib-card / .studio-* 等样式类，不新增 CSS（styles.css 冻结）。
 */
import { useMemo, useState } from "react";
import { useCanvasStore } from "./store";
import type { NodeData, ShotData } from "./stores/node-factory";
import { ANGLE_PRESETS, FOCAL_PRESETS, MOVEMENT_OPTIONS } from "./shotCamera";
import {
  buildAestheticPatch,
  deleteAestheticPreset,
  downloadAestheticFile,
  getActiveAestheticName,
  isPresetUsable,
  loadAestheticPresets,
  normalizeAestheticPreset,
  readAestheticFile,
  saveAestheticPreset,
  setActiveAestheticPreset,
  type AestheticCamera,
  type AestheticPreset,
} from "./aestheticPresets";

type Props = { onStatus?: (msg: string) => void };

const SHOT_SIZES = ["", "大远景", "远景", "全景", "中景", "近景", "特写", "大特写"];
const APERTURES = ["", "1.4", "2.0", "2.8", "4", "8"];
const NONE = "__none__";

/** 单条预设摘要（列表里一眼看懂四维度都填了什么） */
function presetSummary(p: AestheticPreset): string {
  const cam = [
    p.camera.shotSize,
    p.camera.movement && MOVEMENT_OPTIONS.find((m) => m.id === p.camera.movement)?.label,
    p.camera.focalLength ? `${p.camera.focalLength}mm` : "",
  ]
    .filter(Boolean)
    .join(" · ");
  return [p.styleWords, cam, p.tone, p.rhythm, p.musicStyle].filter(Boolean).join(" ｜ ");
}

export default function AestheticPresetPanel({ onStatus }: Props) {
  const nodes = useCanvasStore((s) => s.nodes);
  const shotCount = useMemo(
    () => nodes.filter((n) => (n.data as NodeData).kind === "shot").length,
    [nodes],
  );

  const [presets, setPresets] = useState<AestheticPreset[]>(() => loadAestheticPresets());
  // 生成时自动注入的激活预设名（空 = 不注入）
  const [activeName, setActiveName] = useState<string>(() => getActiveAestheticName());
  // 表单
  const [name, setName] = useState("");
  const [styleWords, setStyleWords] = useState("");
  const [shotSize, setShotSize] = useState("");
  const [movement, setMovement] = useState("");
  const [focalLength, setFocalLength] = useState("");
  const [aperture, setAperture] = useState("");
  const [angleId, setAngleId] = useState(NONE);
  const [tone, setTone] = useState("");
  const [rhythm, setRhythm] = useState("");
  const [musicStyle, setMusicStyle] = useState("");

  const refresh = () => setPresets(loadAestheticPresets());

  const readCamera = (): AestheticCamera => {
    const angle = ANGLE_PRESETS.find((a) => a.id === angleId);
    return {
      shotSize: shotSize || undefined,
      movement: movement || undefined,
      focalLength: focalLength ? Number(focalLength) : undefined,
      aperture: aperture ? Number(aperture) : undefined,
      cameraYaw: angle ? angle.yaw : undefined,
      cameraPitch: angle ? angle.pitch : undefined,
    };
  };

  const toPreset = (): AestheticPreset =>
    normalizeAestheticPreset({
      name: name.trim() || "未命名预设",
      styleWords,
      camera: readCamera(),
      tone,
      rhythm,
      musicStyle,
    });

  const loadToForm = (p: AestheticPreset) => {
    setName(p.name);
    setStyleWords(p.styleWords);
    setShotSize(p.camera.shotSize || "");
    setMovement(p.camera.movement || "");
    setFocalLength(p.camera.focalLength ? String(p.camera.focalLength) : "");
    setAperture(p.camera.aperture ? String(p.camera.aperture) : "");
    const angle = ANGLE_PRESETS.find(
      (a) => a.yaw === (p.camera.cameraYaw ?? 0) && a.pitch === (p.camera.cameraPitch ?? 0),
    );
    setAngleId(angle ? angle.id : NONE);
    setTone(p.tone);
    setRhythm(p.rhythm);
    setMusicStyle(p.musicStyle);
  };

  const clearForm = () => {
    setName("");
    setStyleWords("");
    setShotSize("");
    setMovement("");
    setFocalLength("");
    setAperture("");
    setAngleId(NONE);
    setTone("");
    setRhythm("");
    setMusicStyle("");
  };

  const onSave = () => {
    if (!name.trim()) {
      onStatus?.("请先填写预设名称");
      return;
    }
    const preset = toPreset();
    if (!isPresetUsable(preset)) {
      onStatus?.("至少填写一个维度（风格词 / 镜头语言 / 色调 / 节奏 / 音乐）");
      return;
    }
    saveAestheticPreset(preset);
    refresh();
    onStatus?.(`已沉淀预设「${preset.name}」`);
  };

  const onDelete = (p: AestheticPreset) => {
    deleteAestheticPreset(p.name);
    // 删除的是当前激活项 → 一并取消激活，避免生成时注入已被删的脏预设
    if (activeName === p.name) {
      setActiveAestheticPreset(null);
      setActiveName("");
    }
    refresh();
    onStatus?.(`已删除预设「${p.name}」`);
  };

  /** 切换生成时自动注入：同一项再点 = 取消；不同项 = 改激活目标 */
  const toggleActive = (p: AestheticPreset) => {
    const next = activeName === p.name ? null : p.name;
    setActiveAestheticPreset(next);
    setActiveName(next || "");
    onStatus?.(
      next
        ? `已启用「${p.name}」生成自动注入（风格/色调/节奏/音乐维度）`
        : `已取消自动注入`,
    );
  };

  /** 套到画布全部分镜（用 getState 取快照，避免 selector 造新数组触发 React #185） */
  const applyAll = (p: AestheticPreset) => {
    const { nodes: all, updateNodeData } = useCanvasStore.getState();
    const shots = all.filter((n) => (n.data as NodeData).kind === "shot");
    if (shots.length === 0) {
      onStatus?.("画布暂无分镜卡，先拉片或添加分镜节点");
      return;
    }
    for (const s of shots) {
      const d = s.data as ShotData;
      updateNodeData(s.id, buildAestheticPatch(d.prompt || "", p));
    }
    onStatus?.(`已套用「${p.name}」到 ${shots.length} 个分镜`);
  };

  const applySelected = (p: AestheticPreset) => {
    const { nodes: all, selectedId, updateNodeData } = useCanvasStore.getState();
    const sel = all.find((n) => n.id === selectedId);
    if (!sel || (sel.data as NodeData).kind !== "shot") {
      onStatus?.("请先在画布选中一个分镜节点");
      return;
    }
    updateNodeData(sel.id, buildAestheticPatch((sel.data as ShotData).prompt || "", p));
    onStatus?.(`已套用「${p.name}」到选中分镜`);
  };

  const onImportFile = async (file: File | undefined) => {
    if (!file) return;
    const res = await readAestheticFile(file);
    if (!res.ok) {
      onStatus?.(`导入失败：${res.error}`);
      return;
    }
    loadToForm(res.preset);
    saveAestheticPreset(res.preset);
    refresh();
    onStatus?.(`已导入预设「${res.preset.name}」`);
  };

  return (
    <div className="studio-aesthetic">
      <div className="prompt-lib-toolbar">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="预设名（如：王家卫 · 复古港风）"
        />
        <button type="button" className="btn primary" onClick={onSave}>
          沉淀为预设
        </button>
        <button type="button" className="btn" onClick={clearForm}>
          清空
        </button>
        <label className="btn link" title="导入本模块导出的 JSON 预设">
          导入
          <input
            type="file"
            accept="application/json,.json"
            style={{ display: "none" }}
            onChange={(e) => {
              void onImportFile(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
        </label>
      </div>

      <details className="prompt-lib-sources" open>
        <summary>四维度（点开编辑）· 提示词风格 / 镜头语言 / 色调 · LUT / 节奏 · 音乐</summary>
        <div className="field">
          <label>① 提示词风格词库（前缀，如：电影感，港风复古，颗粒噪点）</label>
          <textarea rows={2} value={styleWords} onChange={(e) => setStyleWords(e.target.value)} />
        </div>
        <div className="prompt-lib-filters">
          <select value={shotSize} onChange={(e) => setShotSize(e.target.value)}>
            <option value="">景别：默认</option>
            {SHOT_SIZES.filter(Boolean).map((s) => (
              <option key={s} value={s}>
                景别：{s}
              </option>
            ))}
          </select>
          <select value={angleId} onChange={(e) => setAngleId(e.target.value)}>
            <option value={NONE}>机位：默认</option>
            {ANGLE_PRESETS.map((a) => (
              <option key={a.id} value={a.id}>
                机位：{a.label}
              </option>
            ))}
          </select>
          <select value={movement} onChange={(e) => setMovement(e.target.value)}>
            <option value="">运镜：默认</option>
            {MOVEMENT_OPTIONS.map((m) => (
              <option key={m.id} value={m.id}>
                运镜：{m.label}
              </option>
            ))}
          </select>
          <select value={focalLength} onChange={(e) => setFocalLength(e.target.value)}>
            <option value="">焦段：默认</option>
            {FOCAL_PRESETS.map((f) => (
              <option key={f} value={f}>
                焦段：{f}mm
              </option>
            ))}
          </select>
          <select value={aperture} onChange={(e) => setAperture(e.target.value)}>
            <option value="">光圈：默认</option>
            {APERTURES.filter(Boolean).map((a) => (
              <option key={a} value={a}>
                光圈：f/{a}
              </option>
            ))}
          </select>
        </div>
        <div className="prompt-lib-filters">
          <input
            value={tone}
            onChange={(e) => setTone(e.target.value)}
            placeholder="③ 色调 · LUT（如：青橙色调，低饱和，LUT teal-orange）"
          />
          <input
            value={rhythm}
            onChange={(e) => setRhythm(e.target.value)}
            placeholder="④ 节奏（如：前紧后松，卡点 2s）"
          />
          <input
            value={musicStyle}
            onChange={(e) => setMusicStyle(e.target.value)}
            placeholder="④ 音乐风格（如：港式电子，Lo-fi）"
          />
        </div>
      </details>

      <div className="prompt-lib-toolbar">
        <span className="hint">
          已沉淀 {presets.length} 个预设 · 画布现有 {shotCount} 个分镜
          {activeName ? ` · 生成自动注入：${activeName}` : " · 未启用自动注入"}
        </span>
      </div>
      {presets.length === 0 ? (
        <div className="studio-empty">
          还没有美学预设。填好四维度后点「沉淀为预设」，之后可一键套到全部/选中分镜，或导出 JSON 复用。
        </div>
      ) : (
        <div className="lib-list">
          {presets.map((p) => (
            <article key={p.name} className="lib-card">
              <h3>{p.name}</h3>
              <p>{presetSummary(p) || "（空预设）"}</p>
              <div className="studio-card-actions">
                <button
                  type="button"
                  className={`btn${activeName === p.name ? " primary" : ""}`}
                  onClick={() => toggleActive(p)}
                  title="启用后，本预设的风格/色调/节奏/音乐维度会在生成分镜时自动拼进提示词"
                >
                  {activeName === p.name ? "取消自动注入" : "生成自动注入"}
                </button>
                <button type="button" className="btn primary" onClick={() => applyAll(p)}>
                  套到全部分镜
                </button>
                <button type="button" className="btn" onClick={() => applySelected(p)}>
                  套到选中分镜
                </button>
                <button type="button" className="btn" onClick={() => loadToForm(p)}>
                  载入表单
                </button>
                <button type="button" className="btn" onClick={() => downloadAestheticFile(p)}>
                  导出
                </button>
                <button type="button" className="btn" onClick={() => onDelete(p)}>
                  删除
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
