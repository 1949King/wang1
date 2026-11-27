/**
 * 全景真 3D 环视查看器（2026-11-20 · 本地三项优化项三）。
 *
 * 把旧 CSS 2D 假全景（PanoramaViewport，background-position 平移）升级为 three.js
 * 真等距柱状环视：内翻球面 + 等距柱状纹理，相机原点 YXZ 旋转环视，滚轮调 fov。
 * 拖拽灵敏度/符号与旧 2D 逐字一致（panoramaMath），节点头部「°」读数不变。
 *
 * 诚实降级：WebGL 创建失败 / 纹理加载失败 ⇒ 渲染 fallback（宿主传入旧 PanoramaViewport）。
 * 取景截图复用 stage3dGlUtils.readRenderTargetToDataURL（WebGLRenderTarget + readRenderTargetPixels），
 * 刻意不用 preserveDrawingBuffer+toDataURL —— 后者在 NVIDIA 上触发 GPU stall 甚至杀 GPU
 * 子进程（见 Stage3D.tsx:978 的血泪注释）。
 *
 * yaw/pitch 沿用既有 data 契约（props 进 / onYawPitch 出），fov 为本地 state 不持久化
 * ⇒ node-factory / store 零改动。unmount 全量 dispose，防 GL 上下文泄漏。
 */
import * as THREE from "three";
import React, { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

import { readRenderTargetToDataURL } from "./stage3dGlUtils";
import { FOV_DEFAULT, degToRad, dragToYawPitch, wheelFov } from "./panoramaMath";
import "./panorama-viewer.css";

/** 暴露给宿主的取景句柄。 */
export interface PanoramaViewer3DHandle {
  /** 截取当前环视画面为 PNG data URL；不可用返回 null（诚实失败）。 */
  capture(): string | null;
}

interface PanoramaViewer3DProps {
  imageUrl: string;
  yaw: number;
  pitch: number;
  onYawPitch: (yaw: number, pitch: number) => void;
  /** WebGL 不可用时的回退视图（宿主传旧 2D PanoramaViewport）。 */
  fallback?: React.ReactNode;
}

/** 单个 GL 实例的全部可变状态（存 ref，拖拽每帧只读不重建）。 */
interface GlState {
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  rt: THREE.WebGLRenderTarget;
  geometry: THREE.SphereGeometry;
  material: THREE.MeshBasicMaterial;
  mesh: THREE.Mesh;
  texture: THREE.Texture | null;
  container: HTMLDivElement;
  observer: ResizeObserver | null;
  listeners: Array<[string, EventListener]>;
  raf: number;
  rafPending: boolean;
  disposed: boolean;
  propYaw: number;
  propPitch: number;
  propFov: number;
  onYawPitch: (yaw: number, pitch: number) => void;
  pendingWrite: { yaw: number; pitch: number } | null;
  drag: { x: number; y: number; yaw: number; pitch: number } | null;
}

/** 把最新 yaw/pitch/fov 落到相机（pendingWrite 优先，保证拖拽当帧即所见）。 */
function applyCamera(s: GlState): void {
  const yaw = s.pendingWrite ? s.pendingWrite.yaw : s.propYaw;
  const pitch = s.pendingWrite ? s.pendingWrite.pitch : s.propPitch;
  s.camera.rotation.set(degToRad(pitch), degToRad(yaw), 0);
  if (s.camera.fov !== s.propFov) {
    s.camera.fov = s.propFov;
    s.camera.updateProjectionMatrix();
  }
}

/** 按需渲染：合并到一帧，避免拖拽/滚轮高频重绘。 */
function scheduleRender(s: GlState): void {
  if (s.disposed || s.rafPending) return;
  s.rafPending = true;
  s.raf = requestAnimationFrame(() => {
    s.rafPending = false;
    if (s.disposed) return;
    applyCamera(s);
    s.renderer.render(s.scene, s.camera);
    // 渲染后再写回 store（rAF 节流），避免 pointermove 高频 setState
    if (s.pendingWrite) {
      const w = s.pendingWrite;
      s.pendingWrite = null;
      s.onYawPitch(w.yaw, w.pitch);
    }
  });
}

/** 容器尺寸变化 ⇒ 同步 renderer / camera / RenderTarget。 */
function resize(s: GlState): void {
  const w = s.container.clientWidth;
  const h = s.container.clientHeight;
  if (!w || !h) return;
  s.renderer.setSize(w, h, false);
  s.camera.aspect = w / h;
  s.camera.updateProjectionMatrix();
  const pr = s.renderer.getPixelRatio();
  s.rt.setSize(Math.max(1, Math.floor(w * pr)), Math.max(1, Math.floor(h * pr)));
  scheduleRender(s);
}

/** 全量释放 GL 资源与监听器（unmount / imageUrl 切换 / 降级时调用）。 */
function teardown(s: GlState): void {
  s.disposed = true;
  if (s.raf) cancelAnimationFrame(s.raf);
  if (s.observer) s.observer.disconnect();
  for (const [type, fn] of s.listeners) s.container.removeEventListener(type, fn);
  if (s.texture) s.texture.dispose();
  s.geometry.dispose();
  s.material.dispose();
  s.rt.dispose();
  s.renderer.dispose();
  if (s.renderer.domElement.parentNode === s.container) {
    s.container.removeChild(s.renderer.domElement);
  }
}

export const PanoramaViewer3D = forwardRef<PanoramaViewer3DHandle, PanoramaViewer3DProps>(
  function PanoramaViewer3D({ imageUrl, yaw, pitch, onYawPitch, fallback }, ref) {
    const containerRef = useRef<HTMLDivElement | null>(null);
    const glRef = useRef<GlState | null>(null);
    const [fov, setFov] = useState(FOV_DEFAULT);
    // node/SSR 无 WebGLRenderingContext ⇒ 首帧即降级；浏览器有则先渲染容器再实测创建
    const [webglFailed, setWebglFailed] = useState<boolean>(
      () => typeof WebGLRenderingContext === "undefined",
    );

    // 最新 props 写入 ref，供 rAF 读取（不入 GL 初始化依赖，拖拽不重建上下文）
    const gl = glRef.current;
    if (gl) {
      gl.propYaw = yaw;
      gl.propPitch = pitch;
      gl.propFov = fov;
      gl.onYawPitch = onYawPitch;
    }

    useImperativeHandle(
      ref,
      () => ({
        capture(): string | null {
          const s = glRef.current;
          if (!s || s.disposed) return null;
          try {
            applyCamera(s);
            s.renderer.setRenderTarget(s.rt);
            s.renderer.render(s.scene, s.camera);
            s.renderer.setRenderTarget(null);
            return readRenderTargetToDataURL(s.renderer, s.rt, s.rt.width, s.rt.height);
          } catch (err) {
            console.warn("[PanoramaViewer3D] 取景截图失败:", err);
            return null;
          }
        },
      }),
      [],
    );

    // yaw/pitch/fov 变化 ⇒ 调度一帧
    useEffect(() => {
      const s = glRef.current;
      if (s && !s.disposed) scheduleRender(s);
    }, [yaw, pitch, fov]);

    // GL 初始化：imageUrl 变化重建；webglFailed 后不再尝试
    useEffect(() => {
      const container = containerRef.current;
      if (!container || webglFailed) return;

      let renderer: THREE.WebGLRenderer;
      try {
        renderer = new THREE.WebGLRenderer({ antialias: true });
      } catch (err) {
        console.warn("[PanoramaViewer3D] WebGL 创建失败，回退旧 2D:", err);
        setWebglFailed(true);
        return;
      }

      const width = container.clientWidth || 300;
      const height = container.clientHeight || 140;
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.setSize(width, height, false);
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      container.appendChild(renderer.domElement);

      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(fov, width / height, 0.1, 100);
      camera.rotation.order = "YXZ";
      camera.position.set(0, 0, 0);

      // 内翻球面：从球心向内看等距柱状纹理
      const geometry = new THREE.SphereGeometry(10, 64, 40);
      geometry.scale(-1, 1, 1);
      const material = new THREE.MeshBasicMaterial({ color: 0x223344 });
      const mesh = new THREE.Mesh(geometry, material);
      scene.add(mesh);

      const pr = renderer.getPixelRatio();
      const rt = new THREE.WebGLRenderTarget(
        Math.max(1, Math.floor(width * pr)),
        Math.max(1, Math.floor(height * pr)),
      );
      rt.texture.colorSpace = THREE.SRGBColorSpace;

      const s: GlState = {
        renderer,
        scene,
        camera,
        rt,
        geometry,
        material,
        mesh,
        texture: null,
        container,
        observer: null,
        listeners: [],
        raf: 0,
        rafPending: false,
        disposed: false,
        propYaw: yaw,
        propPitch: pitch,
        propFov: fov,
        onYawPitch,
        pendingWrite: null,
        drag: null,
      };
      glRef.current = s;

      // 纹理加载：失败 ⇒ 诚实回退旧 2D
      new THREE.TextureLoader().load(
        imageUrl,
        (tex) => {
          if (s.disposed) {
            tex.dispose();
            return;
          }
          tex.colorSpace = THREE.SRGBColorSpace;
          if (s.texture) s.texture.dispose();
          s.texture = tex;
          s.material.map = tex;
          s.material.color.set(0xffffff);
          s.material.needsUpdate = true;
          scheduleRender(s);
        },
        undefined,
        (err) => {
          if (s.disposed) return;
          console.warn("[PanoramaViewer3D] 全景纹理加载失败，回退旧 2D:", err);
          setWebglFailed(true);
        },
      );

      // 原生指针/滚轮监听（wheel 需 passive:false 才能 preventDefault）
      const down = (e: PointerEvent) => {
        container.setPointerCapture(e.pointerId);
        s.drag = { x: e.clientX, y: e.clientY, yaw: s.propYaw, pitch: s.propPitch };
      };
      const move = (e: PointerEvent) => {
        if (!s.drag) return;
        const dx = e.clientX - s.drag.x;
        const dy = e.clientY - s.drag.y;
        s.pendingWrite = dragToYawPitch(s.drag.yaw, s.drag.pitch, dx, dy);
        scheduleRender(s);
      };
      const up = (e: PointerEvent) => {
        s.drag = null;
        if (container.hasPointerCapture(e.pointerId)) container.releasePointerCapture(e.pointerId);
      };
      const wheel = (e: WheelEvent) => {
        e.preventDefault();
        setFov((f) => wheelFov(f, e.deltaY));
      };
      container.addEventListener("pointerdown", down);
      container.addEventListener("pointermove", move);
      container.addEventListener("pointerup", up);
      container.addEventListener("pointercancel", up);
      container.addEventListener("wheel", wheel, { passive: false });
      s.listeners = [
        ["pointerdown", down as EventListener],
        ["pointermove", move as EventListener],
        ["pointerup", up as EventListener],
        ["pointercancel", up as EventListener],
        ["wheel", wheel as EventListener],
      ];

      const observer = new ResizeObserver(() => resize(s));
      observer.observe(container);
      s.observer = observer;

      applyCamera(s);
      scheduleRender(s);

      return () => {
        teardown(s);
        if (glRef.current === s) glRef.current = null;
      };
      // yaw/pitch/fov 经 ref 读取，刻意不入依赖（避免拖拽重建 GL）
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [imageUrl, webglFailed]);

    if (webglFailed) {
      return fallback != null ? (
        <>{fallback}</>
      ) : (
        <div className="sg-pano-3d-fallback">全景环视不可用</div>
      );
    }
    return <div ref={containerRef} className="sg-pano-3d" />;
  },
);
