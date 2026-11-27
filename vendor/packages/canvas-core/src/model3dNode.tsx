/**
 * 3D 模型节点（T5 图片转3D · 深度重建 GLB 网格路，2026-11-20）。
 *
 * 诚实纪律：产物是深度重建 2.5D 网格（单图浮雕），非真体积重建 / 高斯泼溅；
 * 节点显著标注 MODEL3D_NOTE，不冒充真 3D 生成。深度模型缺失 ⇒ 后端 guidance 透传。
 *
 * 渲染范式完全镜像 PanoramaViewer3D.tsx：按需渲染（controls change / 加载完成
 * 才 requestRender，静止零 draw call）+ 安全截图（WebGLRenderTarget 路径，
 * 禁 preserveDrawingBuffer+toDataURL，NVIDIA GPU stall 教训）+ 完整 teardown。
 * WebGL 不可用 / GLB 加载失败 ⇒ 诚实降级静态源图 + 标注。
 *
 * store.ts 冻结顶格不动 ⇒ Model3dData 类型本文件内定义 + cast；
 * 节点经 registerModel3dNode.ts 动态注册（defaultMetadata 自动生成 data），
 * CanvasShell / store / node-factory 零改动。
 */
import React, { forwardRef, memo, useEffect, useImperativeHandle, useRef, useState } from "react";
import { Handle, Position, NodeResizer, type NodeProps } from "@xyflow/react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { useCanvasStore } from "./store";
import { BRIDGE } from "./bridge";
import { runImageTo3d } from "./hostImageTo3d";
import { readRenderTargetToDataURL } from "./stage3dGlUtils";
import "./nodeActions.css";

/** model3d 节点数据（store 冻结 ⇒ 本地类型 + cast，updateNodeData 收 Record 无需 cast） */
export type Model3dData = {
  kind: "model3d";
  title: string;
  sourceImageUrl?: string;
  modelUrl?: string;
  status?: "idle" | "generating" | "success" | "failed";
  progress?: number;
  errorMessage?: string;
  guidance?: string;
  note?: string;
  vertices?: number;
  faces?: number;
};

/** 产物诚实标注（与后端 image_to_3d.MESH_NOTE 同口径） */
export const MODEL3D_NOTE = "深度重建 2.5D 网格（单图浮雕），非真体积重建 / 高斯泼溅";

function nodePropsEqual(prev: NodeProps, next: NodeProps): boolean {
  return (
    prev.id === next.id &&
    prev.selected === next.selected &&
    prev.dragging === next.dragging &&
    prev.data === next.data
  );
}

/** GLB URL 归一化：inbox 相对路径补桥前缀，绝对 URL 原样。 */
function resolveModelUrl(modelUrl: string): string {
  return modelUrl.startsWith("http") ? modelUrl : `${BRIDGE}${modelUrl}`;
}

/**
 * 对指定 model3d 节点发起深度重建（ImageNode「转3D」与节点内「重新生成」共用）。
 * 防重复：status==="generating" 直接返回；失败透传 guidance，不冒充。
 */
export async function generateModel3dForNode(nodeId: string, image: string): Promise<void> {
  const store = useCanvasStore.getState();
  const node = store.nodes.find((n) => n.id === nodeId);
  const d = node?.data as Model3dData | undefined;
  if (!image || d?.status === "generating") return;
  const update = (patch: Record<string, unknown>) =>
    useCanvasStore.getState().updateNodeData(nodeId, patch);
  update({ status: "generating", progress: 0, errorMessage: undefined, guidance: undefined });
  const res = await runImageTo3d({ image }, (stage, progress) => {
    update({ status: "generating", progress: progress ?? undefined, errorMessage: stage });
  });
  if (res.ok && res.modelUrl) {
    update({
      status: "success", progress: 100, modelUrl: res.modelUrl,
      errorMessage: undefined, guidance: undefined,
      note: res.note, vertices: res.vertices, faces: res.faces,
    });
  } else {
    update({
      status: "failed", progress: undefined,
      errorMessage: res.message || "图片转3D失败", guidance: res.guidance,
    });
  }
}

// ── GLB 查看器（按需渲染 + 安全截图，镜像 PanoramaViewer3D）─────────────────

type GlState = {
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  controls: OrbitControls;
  raf: number;
  pending: boolean;
  disposed: boolean;
};

export type Model3dViewerHandle = {
  /** 安全截图：render 到离屏 target 再读像素，返回 dataURL；不可用返回 ""。 */
  capture: () => string;
};

const Model3dViewer = forwardRef<Model3dViewerHandle, {
  modelUrl: string;
  sourceImageUrl?: string;
}>(function Model3dViewer({ modelUrl, sourceImageUrl }, ref) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const glRef = useRef<GlState | null>(null);
  const [glOk] = useState(
    () => typeof window !== "undefined" && !!window.WebGLRenderingContext,
  );
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    const host = hostRef.current;
    if (!host || !glOk || !modelUrl) return;
    setLoadError(false);
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    } catch {
      setLoadError(true);
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(host.clientWidth || 300, host.clientHeight || 200);
    host.appendChild(renderer.domElement);
    renderer.domElement.style.display = "block";
    renderer.domElement.style.width = "100%";
    renderer.domElement.style.height = "100%";

    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#0b1220");
    const camera = new THREE.PerspectiveCamera(
      50, (host.clientWidth || 300) / (host.clientHeight || 200), 0.01, 100,
    );
    camera.position.set(0, 0, 3);
    // 顶点色 PBR 材质需光照；环境光为主 + 方向光补立体感
    scene.add(new THREE.AmbientLight(0xffffff, 1.0));
    const dir = new THREE.DirectionalLight(0xffffff, 0.8);
    dir.position.set(1, 2, 3);
    scene.add(dir);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 0.3;
    controls.maxDistance = 30;

    const gl: GlState = { renderer, scene, camera, controls, raf: 0, pending: true, disposed: false };
    glRef.current = gl;
    const requestRender = () => { gl.pending = true; };
    controls.addEventListener("change", requestRender);

    // 加载 GLB：双面材质（浮雕开放曲面）+ 包围盒拟合相机
    new GLTFLoader().load(
      resolveModelUrl(modelUrl),
      (gltf) => {
        if (gl.disposed) return;
        gltf.scene.traverse((obj) => {
          const mesh = obj as THREE.Mesh;
          if (mesh.isMesh && mesh.material) {
            const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
            mats.forEach((m) => { m.side = THREE.DoubleSide; });
          }
        });
        scene.add(gltf.scene);
        const box = new THREE.Box3().setFromObject(gltf.scene);
        const center = box.getCenter(new THREE.Vector3());
        const size = box.getSize(new THREE.Vector3());
        const maxDim = Math.max(size.x, size.y, size.z, 0.1);
        controls.target.copy(center);
        camera.position.set(center.x, center.y, center.z + maxDim * 1.8);
        controls.update();
        requestRender();
      },
      undefined,
      () => { if (!gl.disposed) setLoadError(true); },
    );

    // 按需渲染循环：仅 pending 时 draw；damping 未稳 ⇒ controls.update() 返 true 续帧
    const loop = () => {
      if (gl.disposed) return;
      gl.raf = requestAnimationFrame(loop);
      if (!gl.pending) return;
      gl.pending = false;
      if (controls.update()) gl.pending = true;
      renderer.render(scene, camera);
    };
    gl.raf = requestAnimationFrame(loop);

    const ro = new ResizeObserver(() => {
      const w = host.clientWidth, h = host.clientHeight;
      if (w > 0 && h > 0) {
        renderer.setSize(w, h);
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
        requestRender();
      }
    });
    ro.observe(host);

    return () => {
      gl.disposed = true;
      cancelAnimationFrame(gl.raf);
      ro.disconnect();
      controls.removeEventListener("change", requestRender);
      controls.dispose();
      scene.traverse((obj) => {
        const mesh = obj as THREE.Mesh;
        if (mesh.isMesh) {
          mesh.geometry?.dispose();
          const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
          mats.forEach((m) => m?.dispose());
        }
      });
      renderer.dispose();
      if (renderer.domElement.parentNode === host) host.removeChild(renderer.domElement);
      glRef.current = null;
    };
  }, [modelUrl, glOk]);

  useImperativeHandle(ref, () => ({
    capture: () => {
      const gl = glRef.current;
      const host = hostRef.current;
      if (!gl || !host) return "";
      const w = host.clientWidth || 300, h = host.clientHeight || 200;
      const target = new THREE.WebGLRenderTarget(w, h);
      gl.renderer.setRenderTarget(target);
      gl.renderer.render(gl.scene, gl.camera);
      const url = readRenderTargetToDataURL(gl.renderer, target, w, h);
      gl.renderer.setRenderTarget(null);
      target.dispose();
      gl.pending = true;
      return url;
    },
  }), []);

  // 诚实降级：WebGL 不可用 / GLB 加载失败 ⇒ 静态源图 + 标注
  if (!glOk || loadError) {
    return (
      <div className="sg-model3d-fallback" style={{ position: "relative", width: "100%", height: "100%", minHeight: 140, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 4, background: "#0b1220", color: "#8b96a8", fontSize: 11, textAlign: "center", padding: 8 }}>
        {sourceImageUrl
          ? <img src={sourceImageUrl} alt="静态预览" style={{ maxWidth: "100%", maxHeight: "70%", objectFit: "contain" }} />
          : null}
        <span>{!glOk ? "WebGL 不可用 · 静态预览" : "GLB 加载失败 · 静态预览"}</span>
      </div>
    );
  }
  return <div ref={hostRef} className="sg-model3d-view" style={{ position: "relative", width: "100%", height: "100%", minHeight: 140 }} />;
});

// ── ImageNode「转3D」动作（冻结 nodes.tsx 仅挂载本组件，逻辑在此）─────────────

export function ImageTo3dAction({ id, src }: { id: string; src: string }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [guidance, setGuidance] = useState("");
  const run = async () => {
    if (busy || !src) return;
    setBusy(true); setMsg(""); setGuidance("");
    try {
      const st = useCanvasStore.getState();
      const me = st.nodes.find((n) => n.id === id);
      const pos = me ? { x: me.position.x + 300, y: me.position.y } : undefined;
      st.addRegistryNode("model3d", pos);
      const nid = useCanvasStore.getState().selectedId;
      const nd = useCanvasStore.getState().nodes.find((n) => n.id === nid);
      // 注册失败守卫：selectedId 未指向新建 model3d 节点 ⇒ 诚实报错
      if (!nid || nid === id || (nd?.data as { kind?: string } | undefined)?.kind !== "model3d") {
        setMsg("3D 节点类型未注册");
        return;
      }
      useCanvasStore.getState().updateNodeData(nid, { sourceImageUrl: src, title: "3D模型" });
      await generateModel3dForNode(nid, src);
      const d = useCanvasStore.getState().nodes.find((n) => n.id === nid)?.data as Model3dData | undefined;
      if (d?.status === "failed") {
        setMsg(d.errorMessage || "转3D失败");
        setGuidance(d.guidance || "");
      } else {
        setMsg("已生成 3D 模型节点 →");
      }
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="sg-node-actions nodrag" onMouseDown={(e) => e.stopPropagation()} style={{ flexDirection: "column", alignItems: "stretch" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <button className="sg-gen-btn subtle" disabled={busy || !src} onClick={() => void run()} title="本地深度重建 2.5D 网格（权重自取，见下载中心）">
          {busy ? "重建中…" : "🧊 转3D"}
        </button>
        {msg ? <span className="sg-gen-hint">{msg}</span> : null}
      </div>
      {guidance ? <div className="sg-gen-hint" style={{ whiteSpace: "pre-line", textAlign: "left" }}>{guidance}</div> : null}
    </div>
  );
}

// ── model3d 节点卡 ─────────────────────────────────────────────────────────

export const Model3dNode = memo(function Model3dNode({ id, data, selected }: NodeProps) {
  const d = data as unknown as Model3dData;
  const viewerRef = useRef<Model3dViewerHandle | null>(null);
  const [captureMsg, setCaptureMsg] = useState("");
  const update = (patch: Record<string, unknown>) =>
    useCanvasStore.getState().updateNodeData(id, patch);
  const busy = d.status === "generating";

  const capture = () => {
    const url = viewerRef.current?.capture() || "";
    if (!url) { setCaptureMsg("截图失败（WebGL 不可用）"); return; }
    const me = useCanvasStore.getState().nodes.find((n) => n.id === id);
    const pos = me ? { x: me.position.x + 300, y: me.position.y } : undefined;
    const nid = useCanvasStore.getState().addNode("image", pos);
    if (nid) {
      useCanvasStore.getState().updateNodeData(nid, {
        imageUrl: url, title: `${d.title || "3D模型"}·取景`, status: "success",
      });
      setCaptureMsg("已截图 → 新图片节点");
    }
  };

  return (
    <div className={`sg-node-card sg-node-model3d${selected ? " selected" : ""}`}>
      <NodeResizer isVisible={!!selected} minWidth={240} minHeight={260} />
      <Handle type="target" position={Position.Left} />
      <div className="sg-node-title">
        <input
          value={d.title || "3D模型"}
          onChange={(e) => update({ title: e.target.value })}
          placeholder="3D模型"
        />
      </div>
      <div className="sg-node-media">
        {d.modelUrl ? (
          <Model3dViewer ref={viewerRef} modelUrl={d.modelUrl} sourceImageUrl={d.sourceImageUrl} />
        ) : (
          <div className="sg-node-placeholder">
            🧊 图片转3D · 待生成
            <br />
            （图片节点点「转3D」，或下方重新生成）
          </div>
        )}
      </div>
      <div className="sg-node-actions nodrag" onMouseDown={(e) => e.stopPropagation()}>
        {d.modelUrl ? (
          <button className="sg-gen-btn subtle" onClick={capture} title="截取当前视角 → 新图片节点">📷 截图</button>
        ) : null}
        {d.sourceImageUrl ? (
          <button className="sg-gen-btn subtle" disabled={busy} onClick={() => void generateModel3dForNode(id, d.sourceImageUrl || "")}>
            {busy ? "重建中…" : "🔄 重新生成"}
          </button>
        ) : null}
        <span className="sg-gen-hint">
          {captureMsg || (busy ? `生成中${d.progress != null ? ` ${Math.round(d.progress)}%` : "…"}` : "")}
        </span>
      </div>
      {d.modelUrl ? (
        <div style={{ fontSize: 10, color: "var(--text-dim, #8b96a8)", padding: "2px 8px", lineHeight: 1.4 }}>
          {d.note || MODEL3D_NOTE}
          {d.vertices != null && d.faces != null ? ` · ${d.vertices} 顶点 / ${d.faces} 面` : ""}
        </div>
      ) : null}
      {d.status === "failed" && d.errorMessage ? (
        <div style={{ fontSize: 11, color: "#f87171", padding: "2px 8px" }}>{d.errorMessage}</div>
      ) : null}
      {d.guidance ? (
        <div style={{ fontSize: 10, color: "var(--text-dim, #8b96a8)", padding: "2px 8px", whiteSpace: "pre-line", lineHeight: 1.4 }}>{d.guidance}</div>
      ) : null}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}, nodePropsEqual);
