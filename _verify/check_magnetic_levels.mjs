// 磁吸意图系统 —— 纯函数单测（无 React、无 DOM、可独立运行）
// 运行：node _verify/check_magnetic_levels.mjs
//
// ⚠️ 重要约定：本文件包含**两套**断言：
//   1) 自包含断言（下面这个 getLevelMeta / listAllLevels / levelByGap）——
//      是源的**快照**。改源时务必同步本文件。
//   2) **源硬值断言**—— 用字面量核对源 magneticLevels.ts 里 5 个等级的
//      strength / rank 值，如果源改了这些数，**本测试会立刻挂**。
//      这是防止"源改了但测试副本没跟上"漂移的最后一道闸。
//
// 2026-09-18 变更：磁吸改为「靠近即吸附」——MagneticEngine 的 magneticStrength /
// getMagneticOffset 两个函数已删除（渐进吸引废除），本文件同步移除其快照与源硬值校验，
// 并补「源里不得再出现 magneticStrength / getMagneticOffset」的负向守卫。
//
// 源文件：
//   - vendor/packages/canvas-core/src/magnetic/magneticLevels.ts
//   - vendor/packages/canvas-core/src/magnetic/MagneticEngine.ts

// @source: magneticLevels.ts
const NONE = {
  short: "·",
  label: "无磁吸",
  hint: "未靠近任何目标节点",
  color: "#9ca3af",
  bg: "rgba(156,163,175,0.12)",
  strength: 0,
  rank: 0,
};
const WEAK = {
  short: "弱",
  label: "弱磁吸",
  hint: "靠近目标，但偏移很慢（避免误吸）",
  color: "#3b82f6",
  bg: "rgba(59,130,246,0.18)",
  strength: 0.12,
  rank: 1,
};
const MEDIUM = {
  short: "中",
  label: "中磁吸",
  hint: "典型吸附：拖拽会主动对齐到目标",
  color: "#f59e0b",
  bg: "rgba(245,158,11,0.20)",
  strength: 0.24,
  rank: 2,
};
const STRONG = {
  short: "强",
  label: "强磁吸",
  hint: "紧贴即吸：非常靠近时快速锁定",
  color: "#10b981",
  bg: "rgba(16,185,129,0.22)",
  strength: 0.45,
  rank: 3,
};
const INSTANT = {
  short: "瞬",
  label: "瞬时吸附",
  hint: "边对边立刻贴齐（Win11 磁贴手感）",
  color: "#8b5cf6",
  bg: "rgba(139,92,246,0.22)",
  strength: 1.0,
  rank: 4,
};
const TABLE = { none: NONE, weak: WEAK, medium: MEDIUM, strong: STRONG, instant: INSTANT };

function getLevelMeta(level) {
  return TABLE[level] || NONE;
}
function listAllLevels() {
  return [WEAK, MEDIUM, STRONG, INSTANT, NONE];
}
// ⚠️ 与源 magneticLevels.ts 的 levelByGap 严格同构：strongDistance(60) > mediumDistance(50)，
// 故 medium 档在实际阈值下不可达（历史遗留），本镜像照抄不改，保证与源行为一致。
function levelByGap(gap, config) {
  if (gap < 0) return "none";
  if (gap < config.instantDistance) return "instant";
  if (gap < config.strongDistance) return "strong";
  if (gap < config.mediumDistance) return "medium";
  if (gap < config.weakDistance) return "weak";
  return "none";
}

// ── 断言 ────────────────────────────────────────────────────
let pass = 0, fail = 0;
function check(label, cond, detail) {
  if (cond) { pass++; console.log("  OK  " + label); }
  else { fail++; console.log("  FAIL " + label + "  →  " + (typeof detail === "string" ? detail : JSON.stringify(detail))); }
}

console.log("=== 磁吸等级自检（靠近即吸附 · 5 档）===");

// getLevelMeta
const sm = getLevelMeta("strong");
check("strong.short 短标签（≤3 字）", typeof sm.short === "string" && sm.short.length <= 3, sm.short);
check("strong.label 中文", /磁吸/.test(sm.label), sm.label);
check("strong.hint 含解释", sm.hint.length > 4, sm.hint);
check("strong.strength=0.45", sm.strength === 0.45, sm.strength);
check("strong.rank=3", sm.rank === 3, sm.rank);
check("instant.strength=1.0", getLevelMeta("instant").strength === 1.0, getLevelMeta("instant").strength);
check("instant.rank=4（最高档）", getLevelMeta("instant").rank === 4, getLevelMeta("instant").rank);
check("none 有 hint", getLevelMeta("none").hint.length > 0, getLevelMeta("none"));

// listAllLevels
const all = listAllLevels();
check("listAllLevels 长度=5", all.length === 5, all.length);
check("listAllLevels 第一个 rank 最小", all[0].rank === 1, all.map(x => x.rank));
check("listAllLevels 末位是 none", all[all.length - 1].rank === 0, all.map(x => x.rank));

// levelByGap（当前真实阈值 120/50/60/10；medium 档被 strong 遮蔽，历史遗留）
const cfg = { weakDistance: 120, mediumDistance: 50, strongDistance: 60, instantDistance: 10 };
check("gap=5 → instant", levelByGap(5, cfg) === "instant", levelByGap(5, cfg));
check("gap=30 → strong", levelByGap(30, cfg) === "strong", levelByGap(30, cfg));
check("gap=80 → weak", levelByGap(80, cfg) === "weak", levelByGap(80, cfg));
check("gap=130 → none", levelByGap(130, cfg) === "none", levelByGap(130, cfg));
check("gap=0 → instant（贴合）", levelByGap(0, cfg) === "instant", levelByGap(0, cfg));

// ── 源硬值校验（防副本漂移） ──────────────────────────────────
const { readFileSync } = await import("node:fs");
const LEVELS_SRC = readFileSync(
  "vendor/packages/canvas-core/src/magnetic/magneticLevels.ts",
  "utf-8",
);
// 5 个等级的 strength / rank 字面量必须与源一致（用带逗号的字面量避免 0 误匹配 0.12）
const STRENGTHS = { none: "0,", weak: "0.12,", medium: "0.24,", strong: "0.45,", instant: "1.0," };
const RANKS = { none: "0,", weak: "1,", medium: "2,", strong: "3,", instant: "4," };
for (const [name, lit] of Object.entries(STRENGTHS)) {
  check(`源 ${name}.strength = ${lit.replace(",", "")}`, LEVELS_SRC.includes(`strength: ${lit}`), name);
}
for (const [name, lit] of Object.entries(RANKS)) {
  check(`源 ${name}.rank = ${lit.replace(",", "")}`, LEVELS_SRC.includes(`rank: ${lit}`), name);
}

// 负向守卫：MagneticEngine 不得再出现 magneticStrength / getMagneticOffset（渐进吸引已废除）
const ENGINE_SRC = readFileSync(
  "vendor/packages/canvas-core/src/magnetic/MagneticEngine.ts",
  "utf-8",
);
check("源已删除 magneticStrength", !/magneticStrength/.test(ENGINE_SRC), "仍存在 magneticStrength");
check("源已删除 getMagneticOffset", !/getMagneticOffset/.test(ENGINE_SRC), "仍存在 getMagneticOffset");

console.log(`\n${fail === 0 ? "OK 磁吸等级全部通过" : "✗ 失败 " + fail + " 项"}（${pass} 项）`);
if (fail > 0) process.exit(1);
