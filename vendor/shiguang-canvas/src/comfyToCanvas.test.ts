import { describe, it, expect } from "vitest";
import { comfyToCanvasNodes, isComfyWorkflowText } from "./comfyToCanvas";

// 一份最小但结构完整的 UI workflow（对齐后端 workflow_importer 自测样例）
const UI_WORKFLOW = {
  last_node_id: 9,
  nodes: [
    {
      id: 4,
      type: "CheckpointLoaderSimple",
      inputs: [{ name: "ckpt_name", type: "COMBO", link: null, widget: { name: "ckpt_name" } }],
      outputs: [{ name: "MODEL", type: "MODEL", links: [10] }],
      widgets_values: ["sd_xl_base_1.0.safetensors"],
      title: "模型",
    },
    {
      id: 6,
      type: "CLIPTextEncode",
      inputs: [
        { name: "text", type: "STRING", link: null, widget: { name: "text" } },
        { name: "clip", type: "CLIP", link: 11 },
      ],
      outputs: [{ name: "CONDITIONING", type: "CONDITIONING", links: [13] }],
      widgets_values: ["a cinematic photo of a mountain at sunset"],
    },
    {
      id: 9,
      type: "SaveImage",
      inputs: [{ name: "images", type: "IMAGE", link: 20 }],
      widgets_values: [],
      title: "保存图",
    },
  ],
  links: [
    [10, 4, 0, 6, 0, "MODEL"],
    [11, 4, 1, 6, 1, "CLIP"],
    [20, 6, 0, 9, 0, "IMAGE"],
  ],
};

// graph 格式（API 用）
const GRAPH_WORKFLOW = {
  "1": { class_type: "CheckpointLoaderSimple", inputs: { ckpt_name: "model.safetensors" } },
  "2": { class_type: "CLIPTextEncode", inputs: { text: "a sunset", clip: ["1", 0] } },
  "3": { class_type: "VAEDecode", inputs: { samples: ["2", 0], vae: ["1", 2] } },
};

describe("comfyToCanvasNodes", () => {
  it("UI workflow：映射节点数量与 class_type 正确", () => {
    const r = comfyToCanvasNodes(UI_WORKFLOW);
    expect(r.nodes.length).toBe(3);
    expect(r.classTypes).toContain("CheckpointLoaderSimple");
    expect(r.classTypes).toContain("CLIPTextEncode");
    expect(r.classTypes).toContain("SaveImage");
  });

  it("UI workflow：CLIPTextEncode 提取 text widget 作 prompt", () => {
    const r = comfyToCanvasNodes(UI_WORKFLOW);
    const prompt = r.nodes.find((n) => n.kind === "prompt");
    expect(prompt).toBeTruthy();
    expect(prompt?.data.prompt).toBe("a cinematic photo of a mountain at sunset");
  });

  it("UI workflow：class_type 正确归类 kind（模型→config，输出→image）", () => {
    const r = comfyToCanvasNodes(UI_WORKFLOW);
    const config = r.nodes.find((n) => n.comfyId === "4");
    const image = r.nodes.find((n) => n.comfyId === "9");
    expect(config?.kind).toBe("config");
    expect(image?.kind).toBe("image");
  });

  it("UI workflow：links 正确映射成 edges（同源同目标去重）", () => {
    const r = comfyToCanvasNodes(UI_WORKFLOW);
    // link 10/11 都是 4→6（不同 slot），去重后共 2 条边：4→6、6→9
    expect(r.edges.length).toBe(2);
    expect(r.edges.some((e) => e.source === "4" && e.target === "6")).toBe(true);
    expect(r.edges.some((e) => e.source === "6" && e.target === "9")).toBe(true);
  });

  it("graph 格式：识别 class_type 并映射节点", () => {
    const r = comfyToCanvasNodes(GRAPH_WORKFLOW);
    expect(r.nodes.length).toBe(3);
    expect(r.classTypes).toContain("CLIPTextEncode");
  });

  it("graph 格式：inputs 里的 [id, slot] 引用映射成 edges", () => {
    const r = comfyToCanvasNodes(GRAPH_WORKFLOW);
    expect(r.edges.some((e) => e.source === "1" && e.target === "2")).toBe(true);
    expect(r.edges.some((e) => e.source === "2" && e.target === "3")).toBe(true);
  });

  it("graph 格式：提取 text 输入作 prompt", () => {
    const r = comfyToCanvasNodes(GRAPH_WORKFLOW);
    const prompt = r.nodes.find((n) => n.kind === "prompt");
    expect(prompt?.data.prompt).toBe("a sunset");
  });

  it("非 workflow 输入返回空 nodes（诚实失败）", () => {
    expect(comfyToCanvasNodes({ foo: 1 }).nodes.length).toBe(0);
    expect(comfyToCanvasNodes(null).nodes.length).toBe(0);
    expect(comfyToCanvasNodes([1, 2, 3]).nodes.length).toBe(0);
    expect(comfyToCanvasNodes("hello").nodes.length).toBe(0);
  });

  it("未知 class_type 保底映射为 text（不丢节点）", () => {
    const r = comfyToCanvasNodes({
      "7": { class_type: "MysteryCustomNode", inputs: { x: 1 } },
    });
    expect(r.nodes.length).toBe(1);
    expect(r.nodes[0].kind).toBe("text");
    expect(r.nodes[0].title).toBe("MysteryCustomNode");
  });
});

describe("isComfyWorkflowText", () => {
  it("识别 UI workflow JSON 文本", () => {
    expect(isComfyWorkflowText(JSON.stringify(UI_WORKFLOW))).toBe(true);
  });
  it("识别 graph 格式 JSON 文本", () => {
    expect(isComfyWorkflowText(JSON.stringify(GRAPH_WORKFLOW))).toBe(true);
  });
  it("拒绝普通文本 / 非 JSON / 非 workflow", () => {
    expect(isComfyWorkflowText("")).toBe(false);
    expect(isComfyWorkflowText("普通文字")).toBe(false);
    expect(isComfyWorkflowText('{"foo": 1}')).toBe(false);
    expect(isComfyWorkflowText("{ 无效 json")).toBe(false);
  });
});
