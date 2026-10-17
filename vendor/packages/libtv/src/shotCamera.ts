/** LibTV 式机位控制：水平环绕 / 俯仰 / 景别 / 焦段 → 提示词片段 */

export type AnglePreset = {
  id: string;
  label: string;
  yaw: number;
  pitch: number;
};

export const ANGLE_PRESETS: AnglePreset[] = [
  { id: "front", label: "正面", yaw: 0, pitch: 0 },
  { id: "left45", label: "左45°", yaw: -45, pitch: 0 },
  { id: "right45", label: "右45°", yaw: 45, pitch: 0 },
  { id: "left90", label: "左侧", yaw: -90, pitch: 0 },
  { id: "right90", label: "右侧", yaw: 90, pitch: 0 },
  { id: "back", label: "背面", yaw: 180, pitch: 0 },
  { id: "high", label: "俯拍", yaw: 0, pitch: -35 },
  { id: "low", label: "仰拍", yaw: 0, pitch: 28 },
];

export const FOCAL_PRESETS = [18, 24, 35, 50, 85, 135, 200];

export const MOVEMENT_OPTIONS: { id: string; label: string }[] = [
  { id: "static", label: "固定" },
  { id: "push-in", label: "推近" },
  { id: "pull-out", label: "拉远" },
  { id: "pan-left", label: "左摇" },
  { id: "pan-right", label: "右摇" },
  { id: "tilt-up", label: "上仰" },
  { id: "tilt-down", label: "下俯" },
  { id: "dolly", label: "跟移" },
  { id: "crane", label: "升降" },
];

function yawLabel(yaw: number): string {
  const y = ((Math.round(yaw) % 360) + 360) % 360;
  if (y <= 15 || y >= 345) return "正面机位";
  if (y >= 15 && y < 75) return "右前45°机位";
  if (y >= 75 && y < 105) return "右侧机位";
  if (y >= 105 && y < 165) return "右后45°机位";
  if (y >= 165 && y < 195) return "背面机位";
  if (y >= 195 && y < 255) return "左后45°机位";
  if (y >= 255 && y < 285) return "左侧机位";
  return "左前45°机位";
}

function pitchLabel(pitch: number): string {
  if (pitch <= -25) return "高角度俯拍";
  if (pitch <= -8) return "轻微俯拍";
  if (pitch >= 25) return "低角度仰拍";
  if (pitch >= 8) return "轻微仰拍";
  return "平视";
}

/** 将机位参数写入生图/生视频提示词 */
export function buildCameraPromptBlock(opts: {
  shotSize?: string;
  cameraYaw?: number;
  cameraPitch?: number;
  focalLength?: number;
  aperture?: number;
  movement?: string;
}): string {
  const parts: string[] = [];
  if (opts.shotSize) parts.push(`景别${opts.shotSize}`);
  const yaw = opts.cameraYaw ?? 0;
  const pitch = opts.cameraPitch ?? 0;
  parts.push(yawLabel(yaw));
  if (Math.abs(pitch) >= 5) parts.push(pitchLabel(pitch));
  if (opts.focalLength) {
    const fl = opts.focalLength;
    if (fl <= 24) parts.push(`${fl}mm广角镜头`);
    else if (fl >= 85) parts.push(`${fl}mm长焦镜头`);
    else parts.push(`${fl}mm标准镜头`);
  }
  if (opts.aperture) parts.push(`光圈f/${opts.aperture}浅景深`);
  if (opts.movement && opts.movement !== "static") {
    const m = MOVEMENT_OPTIONS.find((x) => x.id === opts.movement);
    if (m) parts.push(`运镜${m.label}`);
  }
  return parts.join("，");
}

/** 多角度批量生成用的角度列表（LibTV 式快速预览） */
export function multiAngleBatch(): AnglePreset[] {
  return ANGLE_PRESETS.filter((p) =>
    ["front", "left45", "right45", "left90", "high"].includes(p.id),
  );
}
