/**
 * 画布形态切换（小白 / 专业）—— 与「画布 / 3D 导演台」并排的**视图级**控件。
 *
 * 2026-10-19（用户纠正）：它不属于左侧竖排导航，也不属于宿主顶栏的「挂到角色」，
 * 必须和「画布 / 3D 导演台」放在一起（同一类操作：换视图）。
 *
 * 单独成文件的原因：`CanvasShell.tsx` 已贴体积守卫上限（3251 + 30 容差），
 * 内联这段 JSX 会把文件顶出阈值 —— 按本项目纪律「新逻辑另开文件，拆模块不抬基线」。
 */
import type { CanvasTier } from "./store";

const TIERS: { id: CanvasTier; label: string }[] = [
  { id: "novice", label: "小白" },
  { id: "pro", label: "专业" },
];

export default function CanvasTierSeg({
  tier,
  onChange,
}: {
  tier: CanvasTier;
  onChange: (tier: CanvasTier) => void;
}) {
  return (
    <div
      className="seg"
      title="小白模式 = 磁吸意图画布（拖卡片靠近即吸附成关系）；专业模式 = 节点画布（同一份数据，随时互切）"
    >
      {TIERS.map((t) => (
        <button
          key={t.id}
          type="button"
          className={tier === t.id ? "on" : ""}
          onClick={() => onChange(t.id)}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
