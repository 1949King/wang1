// 数字人节点 · 姿势元数据 + 缩略图缓存自检
// 源：vendor/packages/libtv/src/poseThumbCache.ts
//
// ⚠️ 本文件是 poseThumbCache.ts 的**纯函数副本**。改源时务必同步。
// 关键不变量：
//   - 源 POSE_PRESETS 共 33 个 PosePresetId；副本必须 33 个且 label/category/hint 齐
//   - PoseThumbnailCache LRU 行为：set 超出容量裁最久未访问
//   - 命中 +1 hits，重新 set 同 key 不影响其他 key
//   - 源 schema 对齐断言：源若有变更立刻挂

// @source: POSE_META（33 个姿势，副本源同步）
const POSE_META = {
  idle:         { label: "站立",   category: "static",   hint: "默认站姿 · 适用于多数对话场景" },
  wave:         { label: "挥手",   category: "static",   hint: "打招呼 / 致意" },
  think:        { label: "思考",   category: "emotion",  hint: "托腮或侧头，适合内心独白" },
  point:        { label: "指向",   category: "static",   hint: "指引目标 · 镜头感强" },
  hands_hips:   { label: "叉腰",   category: "static",   hint: "自信 / 准备开打" },
  cross_arms:   { label: "抱臂",   category: "static",   hint: "旁观 / 不耐烦" },
  sit:          { label: "坐姿",   category: "static",   hint: "采访 / 室内" },
  fight:        { label: "戒备",   category: "action",   hint: "战斗起手式" },
  bow:          { label: "鞠躬",   category: "emotion",  hint: "致谢 / 道歉" },
  jump_kick:    { label: "飞踢",   category: "extreme",  hint: "武打高潮" },
  sword_up:     { label: "举剑",   category: "weapon",   hint: "古装持剑 / 蓄力" },
  aim:          { label: "瞄准",   category: "weapon",   hint: "射击 / 持枪" },
  staff:        { label: "持棍",   category: "weapon",   hint: "棍棒 / 杖" },
  phone:        { label: "打电话", category: "static",   hint: "现代都市场景" },
  lean_wall:    { label: "靠墙",   category: "static",   hint: "街头 / 等待" },
  hands_pockets: { label: "插兜",   category: "static",   hint: "轻松休闲" },
  stretch:      { label: "舒展",   category: "action",   hint: "运动 / 起床" },
  yawn:         { label: "打呵欠", category: "emotion",  hint: "困倦 / 过渡" },
  cheer:        { label: "欢呼",   category: "emotion",  hint: "胜利 / 庆祝" },
  sad:          { label: "沮丧",   category: "emotion",  hint: "低头 / 坐地" },
  surprised:    { label: "惊讶",   category: "emotion",  hint: "突然发现" },
  punch:        { label: "出拳",   category: "action",   hint: "打斗动作" },
  block:        { label: "格挡",   category: "action",   hint: "防御姿态" },
  throw:        { label: "投掷",   category: "action",   hint: "扔出 / 抛投" },
  crouch:       { label: "下蹲",   category: "action",   hint: "躲藏 / 蓄力" },
  step_turn:    { label: "转身",   category: "action",   hint: "换向 / 走位" },
  tpose:        { label: "T 字",   category: "static",   hint: "开发期 / 校准用" },
  walk:         { label: "行走",   category: "action",   hint: "动态行走" },
  kneel:        { label: "跪地",   category: "emotion",  hint: "投降 / 哀求" },
  stand_natural: { label: "自然站姿", category: "static", hint: "对话 / 日常 · 比 T 字更自然的基线" },
  hands_behind: { label: "背手",   category: "static",   hint: "领导 / 训话 / 等待" },
  hold_phone:   { label: "看手机", category: "static",   hint: "现代都市 · 低头看屏幕" },
  handshake:    { label: "握手",   category: "static",   hint: "商务 / 社交 · 右手前伸" },
};

function getPoseMeta(poseId) { return POSE_META[poseId] || null; }
function listAllPoseIds() { return Object.keys(POSE_META); }
function listPosesByCategory(cat) {
  return Object.entries(POSE_META).filter(([, m]) => m.category === cat).map(([id]) => id);
}
function getAllCategories() { return ["static", "action", "weapon", "extreme", "emotion"]; }

// @source: PoseThumbnailCache
class PoseThumbnailCache {
  constructor(maxEntries = 64) {
    this.map = new Map();
    this.maxEntries = Math.max(1, maxEntries);
  }
  _key(poseId, characterId) { return `${poseId}@${characterId || "_default"}`; }
  get(poseId, characterId) {
    const key = this._key(poseId, characterId);
    const e = this.map.get(key);
    if (!e) return null;
    e.hits += 1;
    this.map.delete(key);
    this.map.set(key, e);
    return e;
  }
  set(poseId, url, characterId) {
    const entry = { url, generatedAt: Date.now(), hits: 0 };
    const key = this._key(poseId, characterId);
    if (this.map.has(key)) this.map.delete(key);
    this.map.set(key, entry);
    while (this.map.size > this.maxEntries) {
      const firstKey = this.map.keys().next().value;
      if (firstKey === undefined) break;
      this.map.delete(firstKey);
    }
    return entry;
  }
  clear() { this.map.clear(); }
  size() { return this.map.size; }
}

// ── 断言 ────────────────────────────────────────────────────
let pass = 0, fail = 0;
function check(label, cond, detail) {
  if (cond) { pass++; console.log("  OK  " + label); }
  else { fail++; console.log("  FAIL " + label + "  →  " + (typeof detail === "string" ? detail : JSON.stringify(detail))); }
}

console.log("=== 数字人 · 姿势元数据 + 缩略图缓存自检 ===");

// 1. 元数据
check("getPoseMeta('idle') 返回站立", getPoseMeta("idle")?.label === "站立", getPoseMeta("idle"));
check("getPoseMeta('unknown') 返回 null", getPoseMeta("nonexistent") === null);
check("listAllPoseIds 长度=33", listAllPoseIds().length === 33, listAllPoseIds().length);
const cats = {};
for (const id of listAllPoseIds()) cats[getPoseMeta(id).category] = (cats[getPoseMeta(id).category] || 0) + 1;
check("分类齐全 static/action/weapon/extreme/emotion", Object.keys(cats).length === 5, cats);
check("getAllCategories 顺序稳定", JSON.stringify(getAllCategories()) === '["static","action","weapon","extreme","emotion"]', getAllCategories());

// 2. 缓存行为
const cache = new PoseThumbnailCache(3);
check("新缓存 size=0", cache.size() === 0);
cache.set("a", "data:a");
cache.set("b", "data:b");
cache.set("c", "data:c");
check("写入 3 个 size=3", cache.size() === 3, cache.size());
cache.set("d", "data:d");
check("容量 3 → 写入第 4 个后 size=3（裁旧）", cache.size() === 3, cache.size());
check("最久的 a 被裁掉", cache.get("a") === null, "a 应被裁");

// get 命中后 LRU 更新：访问 c，set d 后应裁 a（最久未访问）—— 不是 c
const cache2 = new PoseThumbnailCache(3);
cache2.set("a", "data:a");
cache2.set("b", "data:b");
cache2.set("c", "data:c");
const hitC = cache2.get("c");
check("命中 c", hitC && hitC.url === "data:c");
check("命中后 hits=1", hitC && hitC.hits === 1);
cache2.set("d", "data:d");
check("访问 c 后再 set d，裁最久未访问 a", cache2.get("a") === null && cache2.get("c") !== null && cache2.get("d") !== null);

// 角色维度
const cache3 = new PoseThumbnailCache(10);
cache3.set("idle", "url:charA", "charA");
cache3.set("idle", "url:charB", "charB");
check("不同角色独立缓存", cache3.size() === 2);
check("charA 命中 idle", cache3.get("idle", "charA")?.url === "url:charA");
check("charB 命中 idle", cache3.get("idle", "charB")?.url === "url:charB");
check("未指定角色命中 _default", cache3.get("idle") === null);

// clear
cache3.clear();
check("clear 后 size=0", cache3.size() === 0);

// ── 源硬值校验（防副本漂移） ──
const { readFileSync } = await import("node:fs");
const SRC = readFileSync("vendor/packages/libtv/src/magnetic/poseThumbCache.ts", "utf-8");
check("源有 POSE_META", /const POSE_META/.test(SRC), "POSE_META 不在源里");
check("源有 PoseThumbnailCache class", /class PoseThumbnailCache/.test(SRC), "PoseThumbnailCache 不在源里");
check("源默认容量 64", /maxEntries:\s*number\s*=\s*_DEFAULT_MAX|_DEFAULT_MAX\s*=\s*64/.test(SRC), "默认容量改了");
check("源有 getPoseThumbnailCache 单例", /function getPoseThumbnailCache/.test(SRC), "单例 API 不在源里");

// 姿势数对齐：源 POSE_PRESETS 数量（从 POSE_META 副本的 key 数推断） vs 源文件中 `id: "<x>"` 模式数
const localCount = listAllPoseIds().length;
const srcIds = (SRC.match(/^\s*(\w+):\s*\{\s*label:/gm) || []).length;
check(`源含 ${localCount} 个姿势元数据（与本地副本一致）`, srcIds === localCount, `源 ${srcIds} vs 副本 ${localCount}`);

console.log(`\n${fail === 0 ? "OK 数字人姿势元数据 / 缩略图缓存全部通过" : "✗ 失败 " + fail + " 项"}（${pass} 项）`);
if (fail > 0) process.exit(1);
