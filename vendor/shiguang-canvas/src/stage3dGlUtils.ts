/**
 * Stage3D 离屏渲染工具（从 Stage3D.tsx 抽出，2026-10-12）
 * ========================================================
 * 抽这三个的理由：**它们是纯函数**（只依赖入参与 `THREE`，不闭包任何组件状态），
 * 搬走等于零行为变化；而 `Stage3D.tsx` 距单文件规模守卫上限只剩 30 行，
 * 后续刀次（产物入轨 / 角色库投递）都要往那里加代码。
 *
 * ⚠️ 纪律：本文件属于「薄工具层」——只放**无状态**的 Three.js 操作。
 * 任何需要读组件 state / ref 的逻辑都不要往这里塞（那会立刻退化成第二个 Stage3D）。
 *
 * 冻结保护：本文件已登记进 `stage3d-core` 的 `files`（见 docs/knowledge/frozen_zones.json）。
 */
import * as THREE from "three";

/**
 * 从离屏 WebGLRenderTarget 读像素 → Canvas → PNG data URL。
 *
 * 为什么不用 `canvas.toDataURL()` 直接抓主画面：主 renderer 是
 * `preserveDrawingBuffer:false`（Qt WebEngine 下省显存），抓不到稳定像素。
 * 走 RenderTarget 则是「要哪帧渲染哪帧」。
 *
 * WebGL 以左下角为原点、Canvas 以左上角为原点 ⇒ **必须逐行垂直翻转**（漏了就整幅倒过来）。
 */
export function readRenderTargetToDataURL(
  renderer: THREE.WebGLRenderer,
  rt: THREE.WebGLRenderTarget,
  w: number,
  h: number,
): string {
  const buf = new Uint8Array(w * h * 4);
  renderer.readRenderTargetPixels(rt, 0, 0, w, h, buf);
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d")!;
  const imgData = ctx.createImageData(w, h);
  // WebGL 左下角起点 → Canvas 左上角起点，需要垂直翻转
  for (let row = 0; row < h; row++) {
    const srcStart = row * w * 4;
    const dstStart = (h - 1 - row) * w * 4;
    for (let col = 0; col < w * 4; col++) {
      imgData.data[dstStart + col] = buf[srcStart + col];
    }
  }
  ctx.putImageData(imgData, 0, 0);
  return canvas.toDataURL("image/png");
}

/** 沿父链判断对象在世界里是否可见（任一祖先 `visible=false` 即不可见）。 */
export function isWorldVisible(obj: THREE.Object3D): boolean {
  let p: THREE.Object3D | null = obj;
  while (p) {
    if (!p.visible) return false;
    p = p.parent;
  }
  return true;
}

/** 释放对象树里的几何/材质；**GLB 模板共享的几何/材质必须跳过**。 */
export function disposeObject3D(obj: THREE.Object3D) {
  obj.userData._disposed = true;
  obj.traverse((ch) => {
    if (!(ch instanceof THREE.Mesh)) return;
    // GLB 模板几何/材质是共享的，dispose 会把缓存里的人偶一起毁掉，下次只能看到胶囊骨架
    if (ch.userData.sharedTemplate) return;
    ch.geometry?.dispose();
    const mat = ch.material;
    if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
    else mat?.dispose();
  });
}
