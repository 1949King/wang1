/**
 * hostImageTo3d 纯函数契约测试（T5 项四）。
 * 只测 parseImageTo3dResult / parsePanoramaResult（无网络/DOM 依赖），
 * 轮询与 fetch 路径由真机冒烟覆盖（诚实标注）。
 */
import { describe, expect, it } from "vitest";
import { parseImageTo3dResult, parsePanoramaResult } from "./hostImageTo3d";

describe("parseImageTo3dResult", () => {
  it("成功：ok + model_url ⇒ 透传网格统计与诚实标注", () => {
    const r = parseImageTo3dResult({
      ok: true,
      model_url: "/inbox_file/img3d_1.glb",
      model_path: "C:/inbox/img3d_1.glb",
      vertices: 3072,
      faces: 5922,
      culled: 0,
      fov: 60,
      engine: "depth-anything-v2-small",
      note: "深度重建 2.5D 网格（单图浮雕），非真体积重建 / 高斯泼溅",
    });
    expect(r.ok).toBe(true);
    expect(r.modelUrl).toBe("/inbox_file/img3d_1.glb");
    expect(r.vertices).toBe(3072);
    expect(r.faces).toBe(5922);
    expect(r.engine).toBe("depth-anything-v2-small");
    expect(r.note).toContain("2.5D");
  });

  it("ok:true 但缺 model_url ⇒ 判失败（不冒充）", () => {
    expect(parseImageTo3dResult({ ok: true }).ok).toBe(false);
    expect(parseImageTo3dResult({ ok: true, model_url: "" }).ok).toBe(false);
  });

  it("模型缺失：ok:false + error + guidance ⇒ 透传引导", () => {
    const r = parseImageTo3dResult({
      ok: false,
      error: "未找到深度模型（.onnx）",
      guidance: "请下载 Depth-Anything-V2-Small 放到 thirdparty/models/…",
    });
    expect(r.ok).toBe(false);
    expect(r.message).toContain("深度模型");
    expect(r.guidance).toContain("Depth-Anything");
  });

  it("非法输入 ⇒ 诚实失败", () => {
    expect(parseImageTo3dResult(null).ok).toBe(false);
    expect(parseImageTo3dResult("x").ok).toBe(false);
    expect(parseImageTo3dResult(42).ok).toBe(false);
  });
});

describe("parsePanoramaResult", () => {
  it("成功：ok + image_data_url ⇒ 透传署名 MiniMax H3", () => {
    const r = parsePanoramaResult({
      ok: true,
      image_data_url: "data:image/png;base64,AAAA",
      attribution: "MiniMax H3",
      message: "全景生成成功（MiniMax H3 · 拾光·无界网关）",
    });
    expect(r.ok).toBe(true);
    expect(r.imageDataUrl).toBe("data:image/png;base64,AAAA");
    expect(r.attribution).toBe("MiniMax H3");
  });

  it("ok:true 但 data URL 非法 ⇒ 判失败", () => {
    expect(parsePanoramaResult({ ok: true, image_data_url: "http://x/p.png" }).ok).toBe(false);
    expect(parsePanoramaResult({ ok: true }).ok).toBe(false);
  });

  it("网关未启用：ok:false + guidance ⇒ 透传", () => {
    const r = parsePanoramaResult({ ok: false, message: "无界网关未启用。", guidance: "【启用步骤】…" });
    expect(r.ok).toBe(false);
    expect(r.guidance).toContain("启用步骤");
  });

  it("非法输入 ⇒ 诚实失败", () => {
    expect(parsePanoramaResult(null).ok).toBe(false);
    expect(parsePanoramaResult({}).ok).toBe(false);
  });
});
