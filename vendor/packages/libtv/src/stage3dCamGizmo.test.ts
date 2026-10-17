/**
 * stage3dCamGizmo 回归 —— 锁住「视锥必须由 fov 决定」这条不变量（V4.40.55）
 *
 * 为什么值得单独立锁：
 *   V4.40.55 之前的机位模型**完全忽略 fov**（实心圆锥+方块，体量硬编码），
 *   18° 长焦和 90° 广角长得一模一样 ⇒ 机位可视化唯一的价值（读出这台机位拍出来是什么景别）丢失。
 *   这类回归不报错、不崩溃、测试也不会红 —— 视图只会慢慢变得没用。**只有断言能拦住。**
 *
 * 环境：vitest `environment: "node"`，无 DOM。`makeLabelTexture` 在无 document 时返回 null，
 *       所以标签不参与断言；机身/视锥/状态色/显隐全部可测。
 */
import { describe, expect, it } from "vitest";
import * as THREE from "three";
import { fovToFocalLength, setHelpersVisible, syncCameraGizmos } from "./stage3dCamGizmo";
import type { GizmoCamera } from "./stage3dCamGizmo";

function makeApi() {
  return { scene: new THREE.Scene(), camHelpers: new Map<string, THREE.Object3D>() };
}

function cam(id: string, fov: number, name = id, shotSize = "中景"): GizmoCamera {
  return {
    id,
    name,
    position: [0, 1.6, 4],
    lookAt: [0, 1.2, 0],
    fov,
    shotSize,
  };
}

type Parts = {
  head: THREE.Object3D;
  body: THREE.LineSegments;
  lens: THREE.LineSegments;
  cone: THREE.LineSegments;
  ring: THREE.Mesh;
  drop: THREE.Line;
  label: THREE.Sprite;
  coneFov: number;
};

function partsOf(api: { camHelpers: Map<string, THREE.Object3D> }, id: string): Parts {
  const g = api.camHelpers.get(id);
  if (!g) throw new Error(`没有机位 ${id} 的可视化`);
  const parts = (g.userData as { parts?: Parts }).parts;
  if (!parts) throw new Error(`机位 ${id} 缺 userData.parts`);
  return parts;
}

/** 视锥远端开口的半宽/半高（直接从几何读，不碰实现里的常量） */
function coneOpening(cone: THREE.LineSegments): { halfW: number; halfH: number; z: number } {
  const pos = cone.geometry.getAttribute("position");
  let zMax = -Infinity;
  for (let i = 0; i < pos.count; i += 1) zMax = Math.max(zMax, pos.getZ(i));
  let halfW = 0;
  let halfH = 0;
  for (let i = 0; i < pos.count; i += 1) {
    if (Math.abs(pos.getZ(i) - zMax) < 1e-6) {
      halfW = Math.max(halfW, Math.abs(pos.getX(i)));
      halfH = Math.max(halfH, Math.abs(pos.getY(i)));
    }
  }
  return { halfW, halfH, z: zMax };
}

const colorOf = (o: THREE.LineSegments | THREE.Mesh | THREE.Line) =>
  (o.material as THREE.MeshBasicMaterial).color.getHexString();

/** LineSegments/Line 的 material 在 three 里是 `Material | Material[]` 联合，取用时统一窄化 */
const matOf = (o: THREE.LineSegments | THREE.Line) => o.material as THREE.LineBasicMaterial;

describe("fovToFocalLength（与截图元数据同源的唯一实现）", () => {
  it("常见 fov 吸附到常见焦段", () => {
    expect(fovToFocalLength(45)).toBe(50);
    expect(fovToFocalLength(40)).toBe(58);
    expect(fovToFocalLength(65)).toBe(35);
    expect(fovToFocalLength(18)).toBe(135);
    expect(fovToFocalLength(90)).toBe(24);
  });

  it("非法输入回落到 50mm 而不是 NaN", () => {
    expect(fovToFocalLength(0)).toBe(50);
    expect(fovToFocalLength(-10)).toBe(50);
  });
});

describe("syncCameraGizmos · 结构", () => {
  it("每台机位一个 helper；删机位后回收且从 scene 摘除", () => {
    const api = makeApi();
    syncCameraGizmos(api, [cam("a", 45), cam("b", 65)]);
    expect(api.camHelpers.size).toBe(2);
    expect(api.scene.children).toHaveLength(2);

    syncCameraGizmos(api, [cam("a", 45)]);
    expect(api.camHelpers.size).toBe(1);
    expect(api.scene.children).toHaveLength(1); // b 已摘除（不残留不可见垃圾）
  });

  it("位置跟随机位；朝向 = +Z 指向 lookAt", () => {
    const api = makeApi();
    const c = cam("a", 45);
    syncCameraGizmos(api, [c]);
    const g = api.camHelpers.get("a")!;
    expect(g.position.toArray()).toEqual(c.position);
    const fwd = new THREE.Vector3(0, 0, 1).applyQuaternion(partsOf(api, "a").head.quaternion);
    const want = new THREE.Vector3(...c.lookAt).sub(new THREE.Vector3(...c.position)).normalize();
    expect(fwd.dot(want)).toBeGreaterThan(0.999);
  });

  it("容器与**每一个可渲染子件**都打 userData.isHelper（导出通道据此摘除）", () => {
    const api = makeApi();
    syncCameraGizmos(api, [cam("a", 45)]);
    const root = api.camHelpers.get("a")!;
    expect(root.userData.isHelper).toBe(true);

    // 不数固定个数（树会演进）——查的是「有没有漏网的可渲染物」这个不变量
    const renderables: THREE.Object3D[] = [];
    root.traverse((o) => {
      const any = o as THREE.Mesh & THREE.Line & THREE.Sprite & THREE.LineSegments;
      if (any.isMesh || any.isLine || any.isLineSegments || any.isSprite) renderables.push(o);
    });
    // body / lens / cone / label / ring / drop
    expect(renderables.length).toBeGreaterThanOrEqual(6);
    for (const o of renderables) {
      expect(o.userData.isHelper, `${o.type} 漏打 isHelper ⇒ 会被烘进 ControlNet 图`).toBe(true);
    }
  });
});

describe("syncCameraGizmos · 视锥必须由 fov 决定（本次修复的核心）", () => {
  it("广角开口明显大于长焦，且比例 = tan(fov/2)", () => {
    const api = makeApi();
    syncCameraGizmos(api, [cam("tele", 35), cam("wide", 65)]);
    const tele = coneOpening(partsOf(api, "tele").cone);
    const wide = coneOpening(partsOf(api, "wide").cone);

    expect(wide.halfW).toBeGreaterThan(tele.halfW * 1.8);
    const rad = Math.PI / 360;
    const wantRatio = Math.tan(65 * rad) / Math.tan(35 * rad);
    expect(wide.halfH / tele.halfH).toBeCloseTo(wantRatio, 4);
  });

  it("视锥按 fov 张开，且恒为 16:9", () => {
    const api = makeApi();
    syncCameraGizmos(api, [cam("a", 50)]);
    const { halfW, halfH } = coneOpening(partsOf(api, "a").cone);
    expect(halfW / halfH).toBeCloseTo(16 / 9, 4);
  });

  it("改 fov 会重建几何（不是建好就不管了）", () => {
    const api = makeApi();
    syncCameraGizmos(api, [cam("a", 35)]);
    const before = coneOpening(partsOf(api, "a").cone);
    const geoBefore = partsOf(api, "a").cone.geometry;

    syncCameraGizmos(api, [cam("a", 65)]);
    const after = coneOpening(partsOf(api, "a").cone);

    expect(after.halfW).toBeGreaterThan(before.halfW * 1.8);
    expect(partsOf(api, "a").cone.geometry).not.toBe(geoBefore);
    expect(partsOf(api, "a").coneFov).toBe(65);
  });

  it("长焦镜头座比广角长（焦距的第二个可读信号）", () => {
    const api = makeApi();
    syncCameraGizmos(api, [cam("tele", 18), cam("wide", 90)]);
    expect(partsOf(api, "tele").lens.scale.y).toBeGreaterThan(partsOf(api, "wide").lens.scale.y);
  });
});

describe("syncCameraGizmos · 状态色只表达状态", () => {
  it("默认中性灰，当前机位品牌蓝", () => {
    const api = makeApi();
    syncCameraGizmos(api, [cam("a", 45), cam("b", 45)], "b");
    const idle = partsOf(api, "a").body;
    const active = partsOf(api, "b").body;
    expect(colorOf(idle)).toBe("8ea3b8");
    expect(colorOf(active)).toBe("2563eb");
    expect(matOf(idle).transparent).toBe(true);
  });

  it("切换当前机位后前一台上色回中性", () => {
    const api = makeApi();
    syncCameraGizmos(api, [cam("a", 45), cam("b", 45)], "b");
    syncCameraGizmos(api, [cam("a", 45), cam("b", 45)], "a");
    expect(colorOf(partsOf(api, "a").body)).toBe("2563eb");
    expect(colorOf(partsOf(api, "b").body)).toBe("8ea3b8");
  });

  it("当前机位的视锥更实（不透明度假性也可读）", () => {
    const api = makeApi();
    syncCameraGizmos(api, [cam("a", 45), cam("b", 45)], "a");
    const a = matOf(partsOf(api, "a").cone);
    const b = matOf(partsOf(api, "b").cone);
    expect(a.opacity).toBeGreaterThan(b.opacity);
  });
});

describe("setHelpersVisible · 导出/截图前摘除辅助物", () => {
  it("隐藏后可还原为可见", () => {
    const api = makeApi();
    syncCameraGizmos(api, [cam("a", 45)]);
    const restore = setHelpersVisible(api.scene, false);
    expect(api.camHelpers.get("a")!.visible).toBe(false);
    restore();
    expect(api.camHelpers.get("a")!.visible).toBe(true);
  });

  it("原本就隐藏的 helper 不会被误点亮（axisHelper 常态就是 false）", () => {
    const api = makeApi();
    syncCameraGizmos(api, [cam("a", 45)]);
    const axis = new THREE.AxesHelper(1.2);
    axis.userData.isHelper = true;
    axis.visible = false; // 常态：只有选中角色时才亮
    api.scene.add(axis);

    const restore = setHelpersVisible(api.scene, false);
    restore();

    expect(axis.visible).toBe(false); // ← 关键：不能被"还原成 true"
    expect(api.camHelpers.get("a")!.visible).toBe(true);
  });

  it("不带 isHelper 标记的对象一律不动（角色/地面/灯光）", () => {
    const api = makeApi();
    syncCameraGizmos(api, [cam("a", 45)]);
    const actor = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial());
    api.scene.add(actor);
    const restore = setHelpersVisible(api.scene, false);
    expect(actor.visible).toBe(true);
    restore();
    expect(actor.visible).toBe(true);
  });
});
