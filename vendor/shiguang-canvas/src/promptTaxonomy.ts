/** 提示词细分类与成熟度映射 */

export type Maturity = "sfw" | "mature" | "nsfw";

export type CategoryMeta = {
  id: string;
  label: string;
  group: string;
  maturity: Maturity;
  /** 匹配源里的 category / tags（小写） */
  aliases: string[];
};

/** 分组顺序：UI optgroup */
export const CATEGORY_GROUPS = [
  "摄影写实",
  "人像角色",
  "设计商业",
  "插画二次元",
  "短剧分镜",
  "成熟向",
  "成人向 18+",
  "其他",
] as const;

export const CATEGORY_TAXONOMY: CategoryMeta[] = [
  // —— 摄影写实 ——
  {
    id: "photo-realism",
    label: "摄影·照片级写实",
    group: "摄影写实",
    maturity: "sfw",
    aliases: ["摄影与照片级写实", "photo", "photography", "photorealistic", "写实", "现实"],
  },
  {
    id: "lifestyle",
    label: "生活日常",
    group: "摄影写实",
    maturity: "sfw",
    aliases: ["生活", "lifestyle", "daily", "street"],
  },
  {
    id: "food",
    label: "美食静物",
    group: "摄影写实",
    maturity: "sfw",
    aliases: ["food", "美食", "静物"],
  },
  {
    id: "architecture",
    label: "建筑空间",
    group: "摄影写实",
    maturity: "sfw",
    aliases: ["architecture", "建筑", "interior", "real-estate", "地产"],
  },
  {
    id: "product",
    label: "产品静物",
    group: "摄影写实",
    maturity: "sfw",
    aliases: ["product", "产品", "静物摄影"],
  },

  // —— 人像角色 ——
  {
    id: "portrait",
    label: "人像肖像",
    group: "人像角色",
    maturity: "sfw",
    aliases: ["portrait", "人像", "avatar", "头像"],
  },
  {
    id: "character",
    label: "角色设定",
    group: "人像角色",
    maturity: "sfw",
    aliases: ["character", "角色", "角色图", "oc"],
  },
  {
    id: "fashion",
    label: "时尚穿搭",
    group: "人像角色",
    maturity: "sfw",
    aliases: ["fashion", "时尚", "穿搭", "lookbook"],
  },
  {
    id: "cosplay",
    label: "Cosplay",
    group: "人像角色",
    maturity: "sfw",
    aliases: ["cosplay", "coser", "角色扮演"],
  },

  // —— 设计商业 ——
  {
    id: "ui-ux",
    label: "UI / UX / 社交媒资",
    group: "设计商业",
    maturity: "sfw",
    aliases: ["ui / ux 与社交媒体", "ui / ux", "ui", "ux", "webdesign", "社交媒体"],
  },
  {
    id: "poster",
    label: "海报主视觉",
    group: "设计商业",
    maturity: "sfw",
    aliases: ["poster", "海报", "主视觉", "kv"],
  },
  {
    id: "ecommerce",
    label: "电商主图",
    group: "设计商业",
    maturity: "sfw",
    aliases: ["ecommerce", "电商", "主图", "详情页"],
  },
  {
    id: "infographic",
    label: "信息图 / 文档",
    group: "设计商业",
    maturity: "sfw",
    aliases: ["infographic", "信息图", "信息图与演示文档", "文档", "slides"],
  },
  {
    id: "typography",
    label: "排版与海报字",
    group: "设计商业",
    maturity: "sfw",
    aliases: ["创意排版与海报文字", "typography", "排版", "字体"],
  },
  {
    id: "social",
    label: "社交媒体图",
    group: "设计商业",
    maturity: "sfw",
    aliases: ["social", "社交媒体", "小红书", "instagram"],
  },
  {
    id: "thumbnail",
    label: "缩略图 / 封面",
    group: "设计商业",
    maturity: "sfw",
    aliases: ["thumbnail", "缩略图", "封面", "youtube"],
  },
  {
    id: "design",
    label: "平面设计综合",
    group: "设计商业",
    maturity: "sfw",
    aliases: ["design", "设计", "creative", "创意"],
  },
  {
    id: "work",
    label: "工作办公",
    group: "设计商业",
    maturity: "sfw",
    aliases: ["工作", "office", "职场"],
  },
  {
    id: "learn",
    label: "学习教育",
    group: "设计商业",
    maturity: "sfw",
    aliases: ["学习", "education", "教育"],
  },

  // —— 插画二次元 ——
  {
    id: "illustration",
    label: "插画",
    group: "插画二次元",
    maturity: "sfw",
    aliases: ["illustration", "插画", "绘本"],
  },
  {
    id: "anime",
    label: "二次元 / 动漫",
    group: "插画二次元",
    maturity: "sfw",
    aliases: ["anime", "二次元", "动漫", "manga", "漫画"],
  },
  {
    id: "game-3d",
    label: "游戏 / 3D",
    group: "插画二次元",
    maturity: "sfw",
    aliases: ["游戏与3d", "game", "3d", "玩具", "toy"],
  },
  {
    id: "comic",
    label: "分格漫画",
    group: "插画二次元",
    maturity: "sfw",
    aliases: ["comic", "漫画分格", "四格"],
  },
  {
    id: "fun",
    label: "趣味梗图",
    group: "插画二次元",
    maturity: "sfw",
    aliases: ["有趣", "meme", "趣味", "梗图"],
  },

  // —— 短剧分镜 ——
  {
    id: "storyboard",
    label: "短剧分镜",
    group: "短剧分镜",
    maturity: "sfw",
    aliases: ["storyboard", "分镜", "短剧", "镜头", "cinematic"],
  },
  {
    id: "video-edit",
    label: "视频编辑拼贴",
    group: "短剧分镜",
    maturity: "sfw",
    aliases: ["视频编辑与拼贴", "video", "montage"],
  },
  {
    id: "style-transfer",
    label: "风格迁移 / 图编辑",
    group: "短剧分镜",
    maturity: "sfw",
    aliases: ["图像编辑与风格迁移", "style-transfer", "img2img", "重绘"],
  },
  {
    id: "consistency",
    label: "角色一致性",
    group: "短剧分镜",
    maturity: "sfw",
    aliases: ["角色一致性", "consistency", "同角色"],
  },

  // —— 成熟向（性感但不露骨） ——
  {
    id: "mature-glamour",
    label: "成熟魅力写真",
    group: "成熟向",
    maturity: "mature",
    aliases: ["glamour", "魅力", "成熟写真", "性感时尚", "sensual fashion"],
  },
  {
    id: "mature-lingerie",
    label: "内衣 / 泳装",
    group: "成熟向",
    maturity: "mature",
    aliases: ["lingerie", "内衣", "泳装", "bikini", "swimsuit", "蕾丝"],
  },
  {
    id: "mature-body",
    label: "身材 / 运动塑形",
    group: "成熟向",
    maturity: "mature",
    aliases: ["fitness", "身材", "塑形", "运动内衣"],
  },
  {
    id: "mature-atmosphere",
    label: "暧昧氛围",
    group: "成熟向",
    maturity: "mature",
    aliases: ["暧昧", "氛围感", "romantic tension", "晚礼服"],
  },

  // —— 成人向 18+ ——
  {
    id: "nsfw-artistic-nude",
    label: "艺术人体 / 半裸",
    group: "成人向 18+",
    maturity: "nsfw",
    aliases: ["artistic nude", "艺术人体", "半裸", "nude art", "人体艺术"],
  },
  {
    id: "nsfw-intimate",
    label: "亲密场景",
    group: "成人向 18+",
    maturity: "nsfw",
    aliases: ["intimate", "亲密", "双人亲密", "bedroom"],
  },
  {
    id: "nsfw-explicit",
    label: "露骨成人",
    group: "成人向 18+",
    maturity: "nsfw",
    aliases: ["nsfw", "explicit", "成人", "18+", "色情", "性爱"],
  },
  {
    id: "nsfw-fetish-light",
    label: "轻向癖好 / 道具氛围",
    group: "成人向 18+",
    maturity: "nsfw",
    aliases: ["fetish", "束缚", "乳胶", "道具氛围"],
  },
  {
    id: "nsfw-cosplay",
    label: "成人 Cos / 角色",
    group: "成人向 18+",
    maturity: "nsfw",
    aliases: ["nsfw cosplay", "成人cos", "性感cos"],
  },

  // —— 其他 ——
  {
    id: "other",
    label: "未归类",
    group: "其他",
    maturity: "sfw",
    aliases: ["other", "未分类", "misc", "unknown", "gpt-image-2", "gpt4o", "nano-banana-pro"],
  },
];

const ALIAS_INDEX = (() => {
  const m = new Map<string, CategoryMeta>();
  for (const cat of CATEGORY_TAXONOMY) {
    m.set(cat.id.toLowerCase(), cat);
    m.set(cat.label.toLowerCase(), cat);
    for (const a of cat.aliases) m.set(a.toLowerCase(), cat);
  }
  return m;
})();

const MINOR_HARD =
  /\b(loli|shota|lolita|underage|minor|child|children|kid|kids|toddler|infant|baby|schoolgirl|schoolboy)\b|萝莉|正太|幼女|儿童|小孩|未成年|小学生|初中生|幼化|稚嫩脸|儿化| pedo|儿童色情/i;

const MINOR_SOFT =
  /少女|少年|高中生|中学生|JK制服|学生妹|女高中生|男高中生/i;

/** 明确未成年人相关 → 丢弃（全库安全过滤） */
export function isMinorUnsafe(text: string, maturity?: Maturity): boolean {
  const t = text || "";
  if (MINOR_HARD.test(t)) return true;
  // 成人/成熟向额外收紧：避免「少女」等暧昧年龄词混入 18+ 库
  if ((maturity === "nsfw" || maturity === "mature") && MINOR_SOFT.test(t)) return true;
  return false;
}

const NSFW_HINT =
  /\b(nsfw|nude|naked|explicit|porn|sex|erotic|lingerie|bikini|breast|nipple|genital)\b|裸|半裸|性感|内衣|蕾丝|亲密|床戏|性爱|成人|18\+|露出|私处/i;

const MATURE_HINT =
  /\b(sensual|glamour|seductive|cleavage|swimsuit|bodysuit)\b|暧昧|魅力|晚礼服|深V|吊带|泳装|身材|低胸/i;

export function resolveCategory(
  rawCategory: string,
  tags: string[],
  title = "",
  prompt = "",
): CategoryMeta {
  const candidates = [rawCategory, ...tags].map((s) => String(s || "").trim()).filter(Boolean);
  for (const c of candidates) {
    const hit = ALIAS_INDEX.get(c.toLowerCase());
    if (hit && hit.id !== "other") return hit;
  }
  // 模糊包含
  for (const c of candidates) {
    const low = c.toLowerCase();
    for (const cat of CATEGORY_TAXONOMY) {
      if (cat.id === "other") continue;
      if (cat.aliases.some((a) => low.includes(a.toLowerCase()) || a.toLowerCase().includes(low))) {
        return cat;
      }
    }
  }
  const blob = `${title} ${prompt} ${candidates.join(" ")}`;
  if (NSFW_HINT.test(blob)) {
    if (/亲密|双人|bedroom|intimate/i.test(blob)) return ALIAS_INDEX.get("亲密场景")!;
    if (/内衣|lingerie|蕾丝|泳装|bikini/i.test(blob)) return ALIAS_INDEX.get("内衣 / 泳装")!;
    if (/裸|nude|半裸/i.test(blob)) return ALIAS_INDEX.get("艺术人体 / 半裸")!;
    return ALIAS_INDEX.get("nsfw") || CATEGORY_TAXONOMY.find((c) => c.id === "nsfw-explicit")!;
  }
  if (MATURE_HINT.test(blob)) {
    return CATEGORY_TAXONOMY.find((c) => c.id === "mature-glamour")!;
  }
  return CATEGORY_TAXONOMY.find((c) => c.id === "other")!;
}

export function resolveMaturity(cat: CategoryMeta, tags: string[], text: string): Maturity {
  if (cat.maturity === "nsfw") return "nsfw";
  if (tags.some((t) => /nsfw|18\+|成人|explicit/i.test(t))) return "nsfw";
  if (NSFW_HINT.test(text)) return "nsfw";
  if (cat.maturity === "mature") return "mature";
  if (MATURE_HINT.test(text)) return "mature";
  return "sfw";
}

export function maturityLabel(m: Maturity): string {
  if (m === "nsfw") return "18+";
  if (m === "mature") return "成熟";
  return "全龄";
}

export function categoriesGrouped(): { group: string; items: CategoryMeta[] }[] {
  return CATEGORY_GROUPS.map((group) => ({
    group,
    items: CATEGORY_TAXONOMY.filter((c) => c.group === group),
  })).filter((g) => g.items.length > 0);
}
