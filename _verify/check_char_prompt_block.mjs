// 回归：store.ts（主库 + 副库）的「角色设定块 → prompt」幂等替换。
//
// 不是测一份复制过来的逻辑 —— 直接从两个 store.ts 里把 charPromptBlock /
// CHAR_BLOCK_RE / applyCharBlock 三个函数的**真实源码**抽出来 eval，
// 保证测的就是线上跑的那份（测试副本会漂移，源码抽取不会）。
//
// 守三件事：
//   1. 角色设定块必须来自服务端下发的 prompt（含 visual 组全部字段），
//      不能退化回只拼 target.appearance
//   2. 重复绑定不得累积（旧 bug：删除正则锚 ^，追加却在末尾）
//   3. 解绑必须删得掉（同上）
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { dirname } from "node:path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
// P0-1 Phase 2（2026-10-18）：tauri 侧 libtv 副本已删除，两宿主共用真源包，只扫一处。
const FILES = [
  "vendor/packages/canvas-core/src/store.ts",
];

let fail = 0;
function eq(tag, got, want) {
  const ok = got === want;
  if (!ok) {
    fail++;
    console.log(`  ✗ ${tag}\n      期望 ${JSON.stringify(want)}\n      实到 ${JSON.stringify(got)}`);
  }
  return ok;
}

for (const rel of FILES) {
  const src = readFileSync(join(ROOT, rel), "utf8");
  console.log(`== ${rel}`);

  // ── 静态：不许退化回「只拼 appearance」的旧写法 ──
  const legacy = (src.match(/\[角色外貌: \$\{target\.appearance\}\]/g) || []).length;
  if (legacy > 0) {
    fail++;
    console.log(`  ✗ 仍有 ${legacy} 处旧写法（只拼 target.appearance），visual 组字段会丢`);
  } else {
    console.log("  ✓ 无「只拼 appearance」的旧写法");
  }
  if (!/charPromptBlock\(target\.prompt\)/.test(src)) {
    fail++;
    console.log("  ✗ 未使用服务端下发的 target.prompt");
  } else {
    console.log("  ✓ 使用服务端下发的 prompt");
  }

  // ── 抽取真实源码并 eval ──
  const start = src.indexOf("function charPromptBlock");
  const end = src.indexOf("export const useCanvasStore");
  if (start < 0 || end < 0 || end < start) {
    fail++;
    console.log("  ✗ 抽不到 charPromptBlock ~ applyCharBlock 源码段");
    continue;
  }
  const body = src.slice(start, end);
  // 剥掉 TS 类型标注（Node 不能直接 eval TS）。
  // 只针对「函数签名」和「const 变量标注」两种形态，不去碰正则字面量里的括号。
  const js = body
    .replace(
      /function\s+(\w+)\s*\(([^()]*)\)\s*:\s*[\w.|<>[\] ]+\s*\{/g,
      (_m, name, args) => `function ${name}(${args.replace(/:\s*[^,)]+/g, "")}) {`
    )
    .replace(/\bconst\s+(\w+)\s*:\s*[\w.|<>[\] ]+\s*=/g, "const $1 =");
  const helpers = new Function(
    js + "\nreturn { charPromptBlock, applyCharBlock };"
  )();
  const { charPromptBlock, applyCharBlock } = helpers;

  // ── 行为断言 ──
  const cases = [
    ["首次绑定", applyCharBlock("一个镜头", "[角色设定: X]"), "一个镜头\n[角色设定: X]"],
    ["空 prompt", applyCharBlock("", "[角色设定: X]"), "[角色设定: X]"],
    ["空块=删除", applyCharBlock("一个镜头", ""), "一个镜头"],
    ["重复绑定1", applyCharBlock("一个镜头", "[角色设定: A]"), "一个镜头\n[角色设定: A]"],
    ["重复绑定2", applyCharBlock(applyCharBlock("一个镜头", "[角色设定: A]"), "[角色设定: B]"), "一个镜头\n[角色设定: B]"],
    ["重复绑定3", applyCharBlock(applyCharBlock(applyCharBlock("一个镜头", "[角色设定: A]"), "[角色设定: B]"), "[角色设定: C]"), "一个镜头\n[角色设定: C]"],
    ["解绑删新块", applyCharBlock("一个镜头\n[角色设定: A]", ""), "一个镜头"],
    ["解绑删旧版块", applyCharBlock("一个镜头\n[角色外貌: 白衣] ", ""), "一个镜头"],
    ["解绑删开头块", applyCharBlock("[角色外貌: 白衣] 一个镜头", ""), "一个镜头"],
    ["块内含]", applyCharBlock("镜头\n[角色设定: 眼罩[a]与刀]", ""), "镜头"],
    ["块内含]再绑定", applyCharBlock("镜头\n[角色设定: 眼罩[a]与刀]", "[角色设定: Z]"), "镜头\n[角色设定: Z]"],
    ["多行压平", charPromptBlock("第一行\n第二行\n第三行"), "[角色设定: 第一行 第二行 第三行]"],
    ["压平后可删", applyCharBlock("镜头\n" + charPromptBlock("第一行\n第二行"), ""), "镜头"],
    // 不误伤：正文中间出现的 [角色设定: ...] 不在行首，不该被吃掉
    ["不误伤正文", applyCharBlock("正文\n见 [角色设定: 说明] 后", ""), "正文\n见 [角色设定: 说明] 后"],
  ];
  let okCount = 0;
  for (const [tag, got, want] of cases) if (eq(tag, got, want)) okCount++;
  console.log(`  ${okCount === cases.length ? "✓" : "✗"} 行为断言 ${okCount}/${cases.length}`);
}

console.log();
console.log(fail === 0 ? "OK 角色设定块幂等替换全部通过" : `✗ ${fail} 项失败`);
process.exit(fail === 0 ? 0 : 1);
