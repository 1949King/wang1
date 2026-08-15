/**
 * Stage3D ControlNet 通道导出模块
 * 为 ComfyUI / SDXL ControlNet 工作流提供：Depth / Normal / OpenPose 三种关键输入。
 * 全部纯函数，接收 scene+camera+renderer，返回 dataURL（"data:image/png;base64,..."）。
 *
 * 实现思路：
 *  - Depth / Normal：临时替换材质 → 离屏 render → readPixels → 还原材质
 *  - OpenPose：遍历 actor 的 BoneMap，用 camera.project() 投到 2D，Canvas 2D 画骨架
 *
 * OpenPose 18 关键点索引（COCO 约定）：
 *   0:nose  1:neck  2:rShoulder  3:rElbow  4:rWrist
 *   5:lShoulder  6:lElbow  7:lWrist  8:rHip  9:rKnee  10:rAnkle
 *   11:lHip  12:lKnee  13:lAnkle  14:rEye  15:lEye  16:rEar  17:lEar
 */
import * as THREE from "three";
import { getPoseBones } from "./riggedHumanoid";

export type ControlNetResult = {
  depth: string | null;
  normal: string | null;
  openpose: string | null;
};

/** 把离屏 WebGLRenderTarget 的内容读回 PNG dataURL */
function readRenderTargetAsPNG(
  renderer: THREE.WebGLRenderer,
  target: THREE.WebGLRenderTarget,
  width: number,
  height: number,
): string {
  const pixels = new Uint8Array(width * height * 4);
  renderer.readRenderTargetPixels(target, 0, 0, width, height, pixels);
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d")!;
  const img = ctx.createImageData(width, height);
  img.data.set(pixels);
  ctx.putImageData(img, 0, 0);
  return canvas.toDataURL("image/png");
}

/** 临时替换 scene 中所有 Mesh 的材质，返回恢复函数 */
function swapSceneMaterials(
  scene: THREE.Scene,
  makeNewMat: (orig: THREE.Material) => THREE.Material,
): () => void {
  const meshMatched: THREE.Mesh[] = [];
  const originals: Map<THREE.Mesh, THREE.Material | THREE.Material[]> = new Map();
  scene.traverse((obj) => {
    if ((obj as THREE.Mesh).isMesh) {
      const mesh = obj as THREE.Mesh;
      originals.set(mesh, mesh.material);
      mesh.material = makeNewMat(mesh.material as THREE.Material);
      meshMatched.push(mesh);
    }
  });
  return () => {
    for (const mesh of meshMatched) {
      const orig = originals.get(mesh);
      if (orig) mesh.material = orig;
    }
  };
}

/** 捕获深度图（近黑远白，与 ControlNet depth 格式兼容） */
export function captureDepthMap(
  scene: THREE.Scene,
  camera: THREE.Camera,
  renderer: THREE.WebGLRenderer,
  width: number,
  height: number,
): string | null {
  try {
    const target = new THREE.WebGLRenderTarget(width, height, {
      minFilter: THREE.LinearFilter,
      magFilter: THREE.LinearFilter,
      format: THREE.RGBAFormat,
      type: THREE.UnsignedByteType,
    });
    // MeshDepthMaterial: 近=0, 远=1。反转一下，近白远黑（ControlNet 风格）
    const restore = swapSceneMaterials(scene, () => {
      const m = new THREE.MeshDepthMaterial();
      return m;
    });
    renderer.setRenderTarget(target);
    renderer.clear();
    renderer.render(scene, camera);
    renderer.setRenderTarget(null);
    restore();
    const url = readRenderTargetAsPNG(renderer, target, width, height);
    target.dispose();
    return url;
  } catch (e) {
    console.warn("[ControlNet] depth render failed:", e);
    return null;
  }
}

/** 捕获法线图（RGB 即 XYZ，范围 0-1） */
export function captureNormalMap(
  scene: THREE.Scene,
  camera: THREE.Camera,
  renderer: THREE.WebGLRenderer,
  width: number,
  height: number,
): string | null {
  try {
    const target = new THREE.WebGLRenderTarget(width, height, {
      minFilter: THREE.LinearFilter,
      magFilter: THREE.LinearFilter,
      format: THREE.RGBAFormat,
      type: THREE.UnsignedByteType,
    });
    const restore = swapSceneMaterials(scene, () => new THREE.MeshNormalMaterial());
    renderer.setRenderTarget(target);
    renderer.clear();
    renderer.render(scene, camera);
    renderer.setRenderTarget(null);
    restore();
    const url = readRenderTargetAsPNG(renderer, target, width, height);
    target.dispose();
    return url;
  } catch (e) {
    console.warn("[ControlNet] normal render failed:", e);
    return null;
  }
}

/**
 * 从 actor 的 BoneMap 里提取 OpenPose 18 关键点的 3D 世界坐标
 * 然后投影到相机的 2D 屏幕坐标（CSS pixel）。
 */
function extractOpenPoseKeypoints(
  actor: THREE.Object3D,
  camera: THREE.Camera,
  width: number,
  height: number,
): { x: number; y: number; score: number }[] {
  const bones = getPoseBones(actor);
  const kps: { x: number; y: number; score: number }[] = Array(18)
    .fill(null)
    .map(() => ({ x: 0, y: 0, score: 0 }));
  if (!bones) return kps;

  const w = width;
  const h = height;

  function projectToScreen(v: THREE.Vector3) {
    const p = v.clone().project(camera);
    return {
      x: (p.x + 1) * 0.5 * w,
      y: (1 - (p.y + 1) * 0.5) * h,
    };
  }

  // 0: nose — 用 head 组的 forward 偏上一点
  const head = bones.head;
  if (head) {
    const noseWorld = new THREE.Vector3();
    head.getWorldPosition(noseWorld);
    noseWorld.z += 0.12; // 向前（本地+Z）
    noseWorld.y += 0.08;
    const p = projectToScreen(noseWorld);
    kps[0] = { ...p, score: 0.9 };
  }

  // 1: neck — head 底部 / spine 顶部之间
  const spine = bones.spine;
  if (spine) {
    const neckWorld = new THREE.Vector3();
    spine.getWorldPosition(neckWorld);
    neckWorld.y += 0.32;
    const p = projectToScreen(neckWorld);
    kps[1] = { ...p, score: 0.9 };
  }

  // 2-4: 右臂（shoulder → elbow → wrist）
  if (bones.rShoulder) {
    const p = new THREE.Vector3();
    bones.rShoulder.getWorldPosition(p);
    kps[2] = { ...projectToScreen(p), score: 0.9 };
  }
  if (bones.rElbow) {
    const p = new THREE.Vector3();
    bones.rElbow.getWorldPosition(p);
    kps[3] = { ...projectToScreen(p), score: 0.9 };
  }
  if (bones.rWrist) {
    const p = new THREE.Vector3();
    bones.rWrist.getWorldPosition(p);
    kps[4] = { ...projectToScreen(p), score: 0.9 };
  }

  // 5-7: 左臂
  if (bones.lShoulder) {
    const p = new THREE.Vector3();
    bones.lShoulder.getWorldPosition(p);
    kps[5] = { ...projectToScreen(p), score: 0.9 };
  }
  if (bones.lElbow) {
    const p = new THREE.Vector3();
    bones.lElbow.getWorldPosition(p);
    kps[6] = { ...projectToScreen(p), score: 0.9 };
  }
  if (bones.lWrist) {
    const p = new THREE.Vector3();
    bones.lWrist.getWorldPosition(p);
    kps[7] = { ...projectToScreen(p), score: 0.9 };
  }

  // 8-10: 右腿
  if (bones.rHip) {
    const p = new THREE.Vector3();
    bones.rHip.getWorldPosition(p);
    kps[8] = { ...projectToScreen(p), score: 0.9 };
  }
  if (bones.rKnee) {
    const p = new THREE.Vector3();
    bones.rKnee.getWorldPosition(p);
    kps[9] = { ...projectToScreen(p), score: 0.9 };
  }
  if (bones.rAnkle) {
    const p = new THREE.Vector3();
    bones.rAnkle.getWorldPosition(p);
    kps[10] = { ...projectToScreen(p), score: 0.9 };
  }

  // 11-13: 左腿
  if (bones.lHip) {
    const p = new THREE.Vector3();
    bones.lHip.getWorldPosition(p);
    kps[11] = { ...projectToScreen(p), score: 0.9 };
  }
  if (bones.lKnee) {
    const p = new THREE.Vector3();
    bones.lKnee.getWorldPosition(p);
    kps[12] = { ...projectToScreen(p), score: 0.9 };
  }
  if (bones.lAnkle) {
    const p = new THREE.Vector3();
    bones.lAnkle.getWorldPosition(p);
    kps[13] = { ...projectToScreen(p), score: 0.9 };
  }

  // 14-17: 眼睛、耳朵（head 组 + 小偏移）
  if (head) {
    const lEye = new THREE.Vector3();
    const rEye = new THREE.Vector3();
    const lEar = new THREE.Vector3();
    const rEar = new THREE.Vector3();
    head.getWorldPosition(lEye);
    rEye.copy(lEye);
    lEye.x -= 0.05;
    rEye.x += 0.05;
    lEye.y += 0.12;
    rEye.y += 0.12;
    lEye.z += 0.13;
    rEye.z += 0.13;
    lEar.copy(lEye);
    rEar.copy(rEye);
    lEar.x -= 0.1;
    rEar.x += 0.1;
    kps[14] = { ...projectToScreen(lEye), score: 0.85 };
    kps[15] = { ...projectToScreen(rEye), score: 0.85 };
    kps[16] = { ...projectToScreen(lEar), score: 0.7 };
    kps[17] = { ...projectToScreen(rEar), score: 0.7 };
  }

  return kps;
}

/** OpenPose 18 点骨架的骨架连线（COCO 标准定义） */
const OPENPOSE_SKELETON: [number, number][] = [
  [0, 1], [0, 14], [0, 15], [1, 2], [1, 5], [1, 8], [1, 11],
  [2, 3], [2, 16], [3, 4], [5, 6], [5, 17], [6, 7],
  [8, 9], [9, 10], [11, 12], [12, 13], [14, 16], [15, 17],
];

/**
 * 绘制 OpenPose 骨架图（纯 Canvas 2D，不依赖 WebGL）
 * 多 actor 会叠加绘制，每个 actor 一种颜色。
 */
export function captureOpenPoseImage(
  actors: THREE.Object3D[],
  camera: THREE.Camera,
  width: number,
  height: number,
): string | null {
  if (!actors || actors.length === 0) return null;
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  // 黑色背景（ControlNet 标准底色）
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, width, height);

  const palette = ["#ff3b30", "#00c7be", "#ffcc00", "#af52de", "#ff9500", "#34c759"];
  const lineW = Math.max(2, Math.round(Math.min(width, height) * 0.006));
  const dotR = Math.max(3, Math.round(Math.min(width, height) * 0.008));

  for (let i = 0; i < actors.length; i++) {
    const actor = actors[i];
    const color = palette[i % palette.length];
    const kps = extractOpenPoseKeypoints(actor, camera, width, height);

    ctx.strokeStyle = color;
    ctx.lineWidth = lineW;
    ctx.lineCap = "round";
    // 骨架连线
    for (const [a, b] of OPENPOSE_SKELETON) {
      if (kps[a].score > 0 && kps[b].score > 0) {
        ctx.beginPath();
        ctx.moveTo(kps[a].x, kps[a].y);
        ctx.lineTo(kps[b].x, kps[b].y);
        ctx.stroke();
      }
    }
    // 关键点
    ctx.fillStyle = "#ffffff";
    for (const kp of kps) {
      if (kp.score > 0) {
        ctx.beginPath();
        ctx.arc(kp.x, kp.y, dotR, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }
  return canvas.toDataURL("image/png");
}

/** 一站式导出三种通道 */
export function exportAllControlNetChannels(
  scene: THREE.Scene,
  camera: THREE.Camera,
  renderer: THREE.WebGLRenderer,
  actors: THREE.Object3D[],
  width: number,
  height: number,
): ControlNetResult {
  return {
    depth: captureDepthMap(scene, camera, renderer, width, height),
    normal: captureNormalMap(scene, camera, renderer, width, height),
    openpose: captureOpenPoseImage(actors, camera, width, height),
  };
}
