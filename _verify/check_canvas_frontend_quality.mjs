#!/usr/bin/env node
/**
 * 画布前端代码质量扫描（只读）
 *
 * 与既有的 _verify/check_char_prompt_block.mjs 同族：Node 直跑、只看不改。
 * 用「大括号配平」估算每个函数的起止行，得到可比较的长函数/圈复杂度榜单。
 *
 * 用法:
 *   node _verify/check_canvas_frontend_quality.mjs            # 人类可读报告
 *   node _verify/check_canvas_frontend_quality.mjs --json     # 机器可读
 *   node _verify/check_canvas_frontend_quality.mjs --top 40
 */
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(process.argv[1], "../../vendor/shiguang-canvas/src");
const args = process.argv.slice(2);
const AS_JSON = args.includes("--json");
const TOP = (() => {
  const i = args.indexOf("--top");
  return i >= 0 ? Number(args[i + 1]) || 25 : 25;
})();

/** 去掉注释与字符串字面量，避免括号误计 */
function strip(src) {
  let out = "";
  let i = 0;
  const n = src.length;
  while (i < n) {
    const c = src[i];
    const c2 = src[i + 1];
    if (c === "/" && c2 === "/") {
      while (i < n && src[i] !== "\n") i++;
      continue;
    }
    if (c === "/" && c2 === "*") {
      i += 2;
      while (i < n && !(src[i] === "*" && src[i + 1] === "/")) i++;
      i += 2;
      continue;
    }
    if (c === '"' || c === "'" || c === "`") {
      const q = c;
      i++;
      while (i < n) {
        if (src[i] === "\\") {
          i += 2;
          continue;
        }
        if (src[i] === q) {
          i++;
          break;
        }
        // 模板串里的 ${} 不展开，按普通字符处理
        i++;
      }
      out += '""';
      continue;
    }
    if (c === "\n") {
      out += "\n";
      i++;
      continue;
    }
    out += c;
    i++;
  }
  return out;
}

function walk(dir, acc = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, acc);
    else if (/\.(ts|tsx)$/.test(e.name)) acc.push(p);
  }
  return acc;
}

const FN_START = [
  /^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(/,
  /^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:async\s+)?(?:function\s*)?\(?[^=;]*?=>\s*\{\s*$/,
  /^\s*([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*(?::[^={]+)?\{\s*$/,
];
/** 多行头： const x = useCallback(  /  useMemo(  /  useEffect(  */
const HOOK_HEAD = /^\s*(?:export\s+)?(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*use(?:Callback|Memo)\(\s*$/;

const CYCLO_RE = /\b(if|else\s+if|for|while|case|catch)\b|&&|\|\||\?\?/g;

const files = walk(ROOT);
const fileStats = [];
const funcStats = [];
const dupNames = [];
let anyCount = 0;
const anyHits = [];
let tsIgnore = 0;
let hookStats = {};

for (const f of files) {
  const raw = fs.readFileSync(f, "utf8");
  const lines = raw.split("\n");
  const code = strip(raw);
  const cLines = code.split("\n");

  const rel = path.relative(ROOT, f).replace(/\\/g, "/");

  // 每行结束后的括号深度
  const depthAfter = [];
  let d = 0;
  for (const ln of cLines) {
    for (const ch of ln) {
      if (ch === "{" || ch === "(" || ch === "[") d++;
      else if (ch === "}" || ch === ")" || ch === "]") d--;
    }
    depthAfter.push(d);
  }

  // 每个文件的函数
  const local = [];
  for (let i = 0; i < lines.length; i++) {
    const tr = lines[i].trimEnd();
    const isBraceHead = tr.endsWith("{");
    const isHookHead = HOOK_HEAD.test(tr);
    if (!isBraceHead && !isHookHead) continue;

    let name = null;
    const hm = tr.match(HOOK_HEAD);
    if (hm) name = hm[1];
    if (!name) {
      for (const re of FN_START) {
        const m = tr.match(re);
        if (m) {
          name = m[1];
          break;
        }
      }
    }
    if (!name) continue;
    if (/^\s*(if|for|while|switch|catch|return|else)\b/.test(lines[i])) continue;
    if (/^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\(/.test(lines[i])) continue; // 匿名

    const base = i > 0 ? depthAfter[i - 1] : 0;
    let j = i;
    while (j < lines.length && depthAfter[j] <= base) j++;
    if (j >= lines.length) continue; // 没有函数体（声明/接口）
    let k = j;
    while (k < lines.length && depthAfter[k] > base) k++;
    const len = k - i;
    if (len < 3) continue;

    const body = cLines.slice(i, k).join("\n");
    const m = body.match(CYCLO_RE);
    const cyclo = m ? m.length : 0;

    const params = (() => {
      const pm = lines[i].match(/\(([^)]*)\)/);
      if (!pm || !pm[1].trim()) return 0;
      return pm[1].split(",").filter((s) => s.trim() && !s.includes("=>")).length;
    })();

    const rec = { file: rel, name, line: i + 1, len, cyclo, params };
    local.push(rec);
    funcStats.push(rec);
  }

  // 同文件重复函数名（真缺陷信号）
  const seen = new Map();
  for (const r of local) {
    if (!seen.has(r.name)) seen.set(r.name, []);
    seen.get(r.name).push(r);
  }
  for (const [nm, arr] of seen) {
    if (arr.length > 1 && nm.length > 3) {
      dupNames.push({ file: rel, name: nm, lines: arr.map((a) => a.line), sizes: arr.map((a) => a.len) });
    }
  }

  // any / ts-ignore / hooks
  const anyM = raw.match(/:\s*any\b|\bas\s+any\b|<any>|any\[\]|:\s*any\[\]/g);
  if (anyM) {
    anyCount += anyM.length;
    anyHits.push({ file: rel, n: anyM.length });
  }
  tsIgnore += (raw.match(/@ts-ignore|@ts-expect-error/g) || []).length;

  const useS = (raw.match(/\buseState\s*\(/g) || []).length;
  const useE = (raw.match(/\buseEffect\s*\(/g) || []).length;
  const useM = (raw.match(/\buseMemo\s*\(/g) || []).length;
  const useC = (raw.match(/\buseCallback\s*\(/g) || []).length;
  if (useS + useE + useM + useC > 0 || /\.tsx$/.test(rel)) {
    hookStats[rel] = { useState: useS, useEffect: useE, useMemo: useM, useCallback: useC };
  }

  fileStats.push({
    file: rel,
    lines: lines.length,
    fns: local.length,
    maxFn: local.reduce((a, b) => Math.max(a, b.len), 0),
    any: anyM ? anyM.length : 0,
  });
}

const byLen = [...funcStats].sort((a, b) => b.len - a.len);
const byCyclo = [...funcStats].sort((a, b) => b.cyclo - a.cyclo);

const summary = {
  files: files.length,
  totalLines: fileStats.reduce((a, b) => a + b.lines, 0),
  functions: funcStats.length,
  fnOver100: funcStats.filter((f) => f.len > 100).length,
  fnOver200: funcStats.filter((f) => f.len > 200).length,
  fnOver300: funcStats.filter((f) => f.len > 300).length,
  cycloOver40: funcStats.filter((f) => f.cyclo > 40).length,
  cycloOver60: funcStats.filter((f) => f.cyclo > 60).length,
  paramsOver5: funcStats.filter((f) => f.params > 5).length,
  anyCount,
  tsIgnore,
  dupNames: dupNames.length,
};

const out = {
  summary,
  topByLen: byLen.slice(0, TOP),
  topByCyclo: byCyclo.slice(0, TOP),
  biggestFiles: [...fileStats].sort((a, b) => b.lines - a.lines).slice(0, TOP),
  hookHeavy: Object.entries(hookStats)
    .map(([file, h]) => ({ file, ...h, total: h.useState + h.useEffect + h.useMemo + h.useCallback }))
    .sort((a, b) => b.total - a.total)
    .slice(0, 15),
  dupNames,
  anyHits: anyHits.sort((a, b) => b.n - a.n).slice(0, 15),
};

if (AS_JSON) {
  process.stdout.write(JSON.stringify(out, null, 2));
} else {
  const L = [];
  L.push("=== 画布前端质量扫描 ===");
  L.push(JSON.stringify(summary, null, 2));
  L.push("\n--- 最长函数 Top " + TOP + " ---");
  for (const f of out.topByLen) L.push(`${String(f.len).padStart(5)} 行 | cyclo ${String(f.cyclo).padStart(4)} | ${f.file}:${f.line}  ${f.name}`);
  L.push("\n--- 圈复杂度 Top " + TOP + " ---");
  for (const f of out.topByCyclo) L.push(`cyclo ${String(f.cyclo).padStart(4)} | ${String(f.len).padStart(5)} 行 | ${f.file}:${f.line}  ${f.name}`);
  L.push("\n--- 最大文件 Top " + TOP + " ---");
  for (const f of out.biggestFiles) L.push(`${String(f.lines).padStart(6)} 行 | fns ${String(f.fns).padStart(3)} | maxFn ${String(f.maxFn).padStart(4)} | any ${f.any} | ${f.file}`);
  L.push("\n--- hooks 最重 Top 15 ---");
  for (const h of out.hookHeavy) L.push(`total ${String(h.total).padStart(3)} (S${h.useState} E${h.useEffect} M${h.useMemo} C${h.useCallback}) | ${h.file}`);
  L.push("\n--- 同文件重复函数名（疑似静默覆盖）---");
  for (const d of out.dupNames) L.push(`${d.file}  ${d.name}  行 ${d.lines.join(", ")}  长度 ${d.sizes.join(", ")}`);
  process.stdout.write(L.join("\n") + "\n");
}
