/**
 * 人物卡（2026-11-01 · C 项前端）
 *
 * 为什么单独一个 store：画布 store.ts 属**冻结区**（canvas-magnetic-intent），
 * 加字段要先解冻。人物卡是"生成参数"，和 generationModels 同类，
 * 按既有先例放独立 store（同样带 localStorage 持久化）。
 *
 * 字段值一律用**中文枚举**（与后端 prompt_template.VALUES 的键一致）：
 * 后端负责翻英文 + 排序 + 裁剪，前端不重复维护词典 —— 避免两边漂移。
 */
import { create } from "zustand";

export type PersonCard = {
  gender?: string;
  hair?: string;
  face?: string;
  outfit?: string;
  pose?: string;
  prop?: string;
  setting?: string;
  lighting?: string;
  mood?: string;
  style?: string;
};

const STORAGE_KEY = "shiguang:person-card:default:v1";

/** 字段定义（UI 顺序 = 后端 FIELD_ORDER 的可见子集） */
export const CARD_FIELDS: Array<{
  key: keyof PersonCard;
  label: string;
  options: string[];
  /** 允许自由输入（不在枚举里也能写） */
  free?: boolean;
}> = [
  { key: "gender", label: "性别/年龄", options: ["女生", "男生", "少女", "少年", "中年", "老人"] },
  { key: "hair", label: "发型", options: ["黑长直", "空气刘海", "齐刘海", "短发", "马尾", "丸子头", "卷发", "银发"], free: true },
  { key: "face", label: "五官/妆容", options: ["淡妆", "素颜", "红唇", "圆脸", "鹅蛋脸"], free: true },
  { key: "outfit", label: "服装", options: ["白衬衫", "汉服", "旗袍", "西装", "连衣裙", "针织衫", "校服", "休闲装"], free: true },
  { key: "pose", label: "姿态", options: ["侧身回眸", "正视镜头", "微笑", "行走", "坐下", "站立", "双手捧杯"], free: true },
  { key: "prop", label: "道具", options: ["马克杯", "书本", "雨伞", "手提包"], free: true },
  { key: "setting", label: "场景", options: ["文创店", "办公室", "咖啡馆", "街道", "卧室", "教室", "古建筑", "宫殿"], free: true },
  { key: "lighting", label: "光照", options: ["柔和室内灯光", "暖光", "自然光", "逆光", "昏暗"] },
  { key: "mood", label: "氛围", options: ["温馨", "冷峻", "清新"] },
  { key: "style", label: "风格", options: ["写实", "电影感", "胶片", "二次元", "国风", "水彩"] },
];

function readDefault(): PersonCard {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const obj = JSON.parse(raw);
    return obj && typeof obj === "object" ? (obj as PersonCard) : {};
  } catch {
    return {};
  }
}

function saveDefault(card: PersonCard): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(card));
  } catch {
    /* localStorage 不可用时仅内存生效 */
  }
}

type Store = {
  card: PersonCard;
  setField: (key: keyof PersonCard, value: string) => void;
  replace: (card: PersonCard) => void;
  reset: () => void;
};

export const usePersonCardStore = create<Store>((set, get) => ({
  card: readDefault(),
  setField: (key, value) => {
    const next = { ...get().card, [key]: value };
    if (!value) delete next[key];
    saveDefault(next);
    set({ card: next });
  },
  replace: (card) => {
    saveDefault(card || {});
    set({ card: card || {} });
  },
  reset: () => {
    saveDefault({});
    set({ card: {} });
  },
}));

/** 卡里是否有内容（空卡不传，避免覆盖自由文本提示词） */
export function hasCard(card: PersonCard | undefined | null): boolean {
  if (!card) return false;
  return Object.values(card).some((v) => String(v || "").trim());
}

/** 合并：节点覆盖优先于默认卡 */
export function effectiveCard(nodeCard?: PersonCard | null): PersonCard {
  const base = usePersonCardStore.getState().card || {};
  return hasCard(nodeCard) ? { ...base, ...(nodeCard || {}) } : { ...base };
}
