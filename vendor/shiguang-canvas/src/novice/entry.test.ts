/**
 * P0 小白模式意图入口回归（2026-10-11）
 *
 * 锁定四件事：
 * 1. NOVICE_ENTRY **全量覆盖 21 种内置 kind**（一个不少——2026-10-11 教训：藏卡片=越权）
 * 2. 每个入口 name/desc 非空、stage 落在 7 组内
 * 3. buildNoviceAddNodeGroups 分组完整（7 组 + 扩展）
 * 4. **专业模式零变化**：groupPaletteByCategory 仍按既有 5 大类组织、
 *    label 仍是技术名（小白映射只加不改的铁律）
 */
import { describe, expect, it } from "vitest";
import {
  NOVICE_ENTRY,
  NOVICE_STAGE_GROUPS,
  noviceEntryFor,
} from "./types";
import {
  buildAddNodeItems,
  buildNoviceAddNodeGroups,
  groupPaletteByCategory,
  isBuiltinNodeKind,
  NODE_PALETTE,
} from "../NodePalette";

/** 与 store 的 21 种内置 kind 同源清单（isBuiltinNodeKind 的字面量） */
const ALL_BUILTIN_KINDS = [
  "shot", "script", "image", "video", "prompt", "text", "config", "generator", "group", "audio",
  "markdown", "shotlist", "storyboard", "director", "directorCard", "digitalHuman", "animation",
  "panorama", "note", "source", "music",
];

describe("P0 小白模式意图入口（2026-10-11）", () => {
  it("NOVICE_ENTRY 全量覆盖 21 种内置 kind（一个不少）", () => {
    for (const k of ALL_BUILTIN_KINDS) {
      const e = NOVICE_ENTRY[k];
      expect(e, `kind=${k} 缺少小白入口`).toBeTruthy();
      expect(e.name.trim().length).toBeGreaterThan(0);
      expect(e.desc.trim().length).toBeGreaterThan(0);
    }
    // 反向：入口表不得发明不存在的 kind
    for (const k of Object.keys(NOVICE_ENTRY)) {
      expect(isBuiltinNodeKind(k), `NOVICE_ENTRY 出现未知 kind=${k}`).toBe(true);
    }
  });

  it("每个入口的 stage 都落在 7 组内", () => {
    const stageIds = new Set(NOVICE_STAGE_GROUPS.map((g) => g.id));
    expect(NOVICE_STAGE_GROUPS.length).toBe(7);
    for (const e of Object.values(NOVICE_ENTRY)) {
      expect(stageIds.has(e.stage), `未知 stage=${e.stage}`).toBe(true);
    }
  });

  it("noviceEntryFor：已知 kind 给入口、未知 kind 给 null（不编造）", () => {
    expect(noviceEntryFor("shot")?.name).toBe("出一张画面");
    expect(noviceEntryFor("__nope__")).toBeNull();
  });

  it("buildNoviceAddNodeGroups：21 种全部入组 + 入口用小白名", () => {
    const groups = buildNoviceAddNodeGroups();
    const items = groups.flatMap((g) => g.items);
    expect(items.length).toBe(ALL_BUILTIN_KINDS.length);
    for (const k of ALL_BUILTIN_KINDS) {
      const item = items.find((x) => x.type === k);
      expect(item, `分组里缺 kind=${k}`).toBeDefined();
      expect(item?.label).toBe(NOVICE_ENTRY[k].name);
      // hover 提示必须带专业模式原名（小白↔专业互认）
      expect(item?.hint).toContain("专业模式");
    }
  });

  it("★ 专业模式零变化：5 大类分组与技术名不受小白映射影响", () => {
    // 技术名查表仍是 NODE_PALETTE 的 label（镜头/图片/生成器…）
    const shot = NODE_PALETTE.find((p) => p.type === "shot");
    expect(shot?.label).toBe("镜头");
    const gen = NODE_PALETTE.find((p) => p.type === "generator");
    expect(gen?.label).toBe("生成器");

    // 专业模式分组仍产出 5 大类（cat 为既有 id），与小白 7 组互不污染
    const proGroups = groupPaletteByCategory(buildAddNodeItems());
    const proCats = proGroups.map((g) => g.cat);
    for (const c of ["create", "media", "generate", "space", "note"]) {
      expect(proCats, `专业模式缺大类 ${c}`).toContain(c);
    }
    // 专业模式的 label 绝不能是小白名（两种读法必须可区分）
    const proItems = proGroups.flatMap((g) => g.items);
    const proShot = proItems.find((x) => x.type === "shot");
    expect(proShot?.label).toBe("镜头");
  });
});
