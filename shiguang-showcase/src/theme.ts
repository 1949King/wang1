// 主题层：字体、配色、缓动与通用插值工具（拾光剪影官网展示片）
import { Easing, interpolate } from "remotion";
import { loadFont as loadSerif } from "@remotion/google-fonts/NotoSerifSC";
import { loadFont as loadSans } from "@remotion/google-fonts/NotoSansSC";

// 中文衬线（标题）+ 中文无衬线（正文）
export const { fontFamily: serifFont } = loadSerif("normal", {
  weights: ["600", "900"],
  subsets: ["chinese-simplified", "latin"],
});

export const { fontFamily: sansFont } = loadSans("normal", {
  weights: ["300", "400", "500", "700"],
  subsets: ["chinese-simplified", "latin"],
});

// 深色电影感配色：拾光金为主色，青/紫/琥珀作功能色
export const COLORS = {
  bg: "#070B14",
  panel: "rgba(255, 255, 255, 0.035)",
  panelBorder: "rgba(245, 196, 81, 0.18)",
  gold: "#F5C451",
  goldDeep: "#D9A441",
  amber: "#FFA94D",
  cyan: "#5EEAD4",
  violet: "#A78BFA",
  blue: "#7DD3FC",
  text: "#F6F8FC",
  textDim: "#9AA7BD",
};

// 入场曲线：强 ease-out（对应 CSS cubic-bezier(0.16, 1, 0.3, 1)）
export const EASE_OUT = Easing.bezier(0.16, 1, 0.3, 1);
// 编辑级对称曲线：用于扫光等匀速感运动
export const EASE_IN_OUT = Easing.bezier(0.45, 0, 0.55, 1);

// 归一化入场进度（0→1），带夹取，防止越界
export const enter = (frame: number, start: number, duration: number) =>
  interpolate(frame, [start, start + duration], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: EASE_OUT,
  });

// 通用夹取插值：把「时间」与「映射值」分离，便于多属性复用同一进度
export const clampInterpolate = (
  frame: number,
  input: [number, number],
  output: [number, number],
  easing = EASE_OUT,
) =>
  interpolate(frame, input, output, {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing,
  });
