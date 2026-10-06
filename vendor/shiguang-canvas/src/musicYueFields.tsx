/**
 * YuE（乐）专业模式字段组 —— 从 CanvasShell 抽出（2026-09-28）。
 *
 * 抽出理由：CanvasShell 已顶到单文件规模守卫容差（存量文件只许减不许增），
 * 而 YuE 又要新增「创作模式 / 翻唱参考曲」字段。整组抽成组件后：
 * 主文件**净减行数**（通过守卫），字段逻辑也有了独立归属。
 *
 * 与小白侧 `NoviceInspector` 的 YuE 面板同源（同一批字段：engine / yueMode / cot /
 * referenceAudioUrl / abc），只是专业模式用下拉、小白模式用分段按钮。
 */

type UpdateFn = (patch: Record<string, unknown>) => void;

type Props = {
  data: Record<string, unknown>;
  onUpdate: UpdateFn;
};

export function MusicYueFields({ data, onUpdate }: Props) {
  const engine = String(data.engine || "suno");
  const yueMode = String(data.yueMode || "original");

  return (
    <>
      <div className="field">
        <label title="YuE 先生成可编辑乐谱再渲染整曲；需配置 SHIGUANG_YUE_ENDPOINT 或 SHIGUANG_YUE_HOME，未配置时不会造假音频">
          🎼 生成引擎
        </label>
        <select value={engine} style={{ width: "100%" }}
          onChange={(e) => onUpdate({ engine: e.target.value })}>
          <option value="suno">Suno（黑盒文生音乐）</option>
          <option value="yue">YuE 乐（符号规划 → 可编辑乐谱 → 渲染）</option>
        </select>
      </div>
      {engine === "yue" && (<>
        <div className="field">
          <label>🎯 创作模式</label>
          <select value={yueMode} style={{ width: "100%" }}
            onChange={(e) => onUpdate({ yueMode: e.target.value,
              ...(e.target.value === "cover" ? { cot: "melody" } : {}) })}>
            <option value="original">原创（引擎规划乐谱）</option>
            <option value="cover">翻唱（参考曲转录旋律 → 换风格重唱）</option>
          </select>
        </div>
        {yueMode === "cover" && (
          <div className="field">
            <label>🎧 参考曲（本地路径 / inbox 链接）</label>
            <input type="text" value={String(data.referenceAudioUrl || "")}
              onChange={(e) => onUpdate({ referenceAudioUrl: e.target.value })}
              placeholder="转录用 SheetSage2（独立环境）；转录错误会带进翻唱，请先审阅乐谱" />
          </div>
        )}
        <div className="field">
          <label>🧠 规划模式（cot）</label>
          <select value={String(data.cot || "full")} style={{ width: "100%" }}
            onChange={(e) => onUpdate({ cot: e.target.value })}>
            <option value="full">旋律 + 和弦（可编辑，新歌默认）</option>
            <option value="melody">旋律翻唱（旋律规划 + 自由伴奏）</option>
            <option value="off">直接生成（不出谱）</option>
          </select>
        </div>
        <div className="field">
          <label>🎼 乐谱（ABC，可编辑；空则由引擎自规划）</label>
          <textarea rows={6} spellCheck={false} value={String(data.abc || "")}
            onChange={(e) => onUpdate({ abc: e.target.value })}
            placeholder="在小白卡片里点「生成可编辑乐谱」或「转录旋律」后，谱面会出现在这里，可直接改" />
        </div>
      </>)}
    </>
  );
}
