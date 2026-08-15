const fs = require('fs');
const p = 'd:/拾光剪影/vendor/shiguang-canvas/src/riggedHumanoid.ts';
let content = fs.readFileSync(p, 'utf8');
if (content.includes('/* END GLUE */')) {
  console.log('already appended');
  process.exit(0);
}

const glbCode = `

/* ───────────────────────────────────────────────────────────────────────
 * GLB Retarget 层
 *
 * 方案 A 真正含义：
 *   1. 加载 GLB → 拿到 SkinnedMesh + mixamorig:* 骨架
 *   2. 用 GLB 自带骨架做骨骼动画（顶点权重绑定在它们身上）
 *   3. 建立 JointPose 字段 → GLB 骨骼的 retarget 映射表
 *   4. applyPoseToGLB 把旋转叠加到 GLB 骨架上（保留 T-Pose identity）
 *
 * 这样：现有姿势库、穿模修正、体型缩放全部复用，
 *      只是 mesh 从 capsule 变成写实 GLB。
 * ─────────────────────────────────────────────────────────────────────── */

type GLBBoneMap = Partial<Record<
  | "hips" | "abdomen" | "spine" | "spine2"
  | "head" | "neck"
  | "lShoulder" | "lArm" | "lForeArm" | "lWrist"
  | "rShoulder" | "rArm" | "rForeArm" | "rWrist"
  | "lHip" | "lKnee" | "lAnkle"
  | "rHip" | "rKnee" | "rAnkle",
  THREE.Object3D
>>;

function findGLBBone(scene: THREE.Object3D, keyword: string): THREE.Object3D | null {
  let hit: THREE.Object3D | null = null;
  scene.traverse((obj) => {
    if (hit) return;
    const name = obj.name || "";
    const tail = name.replace(/^(mixamorig|mixamo):?[\\s_-]?/i, "");
    if (tail.toLowerCase() === keyword.toLowerCase() || name.toLowerCase().includes(keyword.toLowerCase())) {
      hit = obj;
    }
  });
  return hit;
}

function buildGLBBoneMap(scene: THREE.Object3D): GLBBoneMap {
  const B: GLBBoneMap = {};
  B.hips = findGLBBone(scene, "Hips");
  B.abdomen = findGLBBone(scene, "Spine");
  B.spine = findGLBBone(scene, "Spine1");
  B.spine2 = findGLBBone(scene, "Spine2");
  B.neck = findGLBBone(scene, "Neck");
  B.head = findGLBBone(scene, "Head");
  B.lShoulder = findGLBBone(scene, "LeftShoulder");
  B.lArm = findGLBBone(scene, "LeftArm");
  B.lForeArm = findGLBBone(scene, "LeftForeArm");
  B.lWrist = findGLBBone(scene, "LeftHand");
  B.rShoulder = findGLBBone(scene, "RightShoulder");
  B.rArm = findGLBBone(scene, "RightArm");
  B.rForeArm = findGLBBone(scene, "RightForeArm");
  B.rWrist = findGLBBone(scene, "RightHand");
  B.lHip = findGLBBone(scene, "LeftUpLeg");
  B.lKnee = findGLBBone(scene, "LeftLeg");
  B.lAnkle = findGLBBone(scene, "LeftFoot");
  B.rHip = findGLBBone(scene, "RightUpLeg");
  B.rKnee = findGLBBone(scene, "RightLeg");
  B.rAnkle = findGLBBone(scene, "RightFoot");
  return B;
}

function recordGLBTPose(bones: GLBBoneMap): Record<string, THREE.Euler> {
  const identity: Record<string, THREE.Euler> = {};
  for (const [key, bone] of Object.entries(bones)) {
    if (bone) identity[key] = bone.rotation.clone();
  }
  return identity;
}

/** 把 JointPose 旋转叠加到 GLB 骨架上（retarget） */
export function applyPoseToGLB(
  bones: GLBBoneMap,
  pose: JointPose,
  identity: Record<string, THREE.Euler>,
): void {
  const p = resolveClampPose(mergePose(defaultPose(), pose));
  const neg = (v: number) => -v;

  if (bones.abdomen) bones.abdomen.rotation.set(
    deg(neg(p.abdomenX)) + (identity.abdomen?.x ?? 0),
    identity.abdomen?.y ?? 0,
    identity.abdomen?.z ?? 0,
  );
  if (bones.spine2) bones.spine2.rotation.set(
    deg(neg(p.spineX)) + (identity.spine2?.x ?? 0),
    deg(p.spineY) + (identity.spine2?.y ?? 0),
    identity.spine2?.z ?? 0,
  );
  if (bones.head) bones.head.rotation.set(
    deg(neg(p.headX)) + (identity.head?.x ?? 0),
    deg(p.headY) + (identity.head?.y ?? 0),
    identity.head?.z ?? 0,
  );
  if (bones.lShoulder) bones.lShoulder.rotation.set(
    deg(neg(p.lShoulderX)) + (identity.lShoulder?.x ?? 0),
    identity.lShoulder?.y ?? 0,
    deg(p.lShoulderZ) + (identity.lShoulder?.z ?? 0),
  );
  if (bones.lArm) bones.lArm.rotation.set(
    deg(neg(p.lElbowX)) + (identity.lArm?.x ?? 0),
    identity.lArm?.y ?? 0,
    identity.lArm?.z ?? 0,
  );
  if (bones.lForeArm) bones.lForeArm.rotation.set(
    deg(neg(p.lWristX)) + (identity.lForeArm?.x ?? 0),
    identity.lForeArm?.y ?? 0,
    identity.lForeArm?.z ?? 0,
  );
  if (bones.rShoulder) bones.rShoulder.rotation.set(
    deg(neg(p.rShoulderX)) + (identity.rShoulder?.x ?? 0),
    identity.rShoulder?.y ?? 0,
    deg(p.rShoulderZ) + (identity.rShoulder?.z ?? 0),
  );
  if (bones.rArm) bones.rArm.rotation.set(
    deg(neg(p.rElbowX)) + (identity.rArm?.x ?? 0),
    identity.rArm?.y ?? 0,
    identity.rArm?.z ?? 0,
  );
  if (bones.rForeArm) bones.rForeArm.rotation.set(
    deg(neg(p.rWristX)) + (identity.rForeArm?.x ?? 0),
    identity.rForeArm?.y ?? 0,
    identity.rForeArm?.z ?? 0,
  );
  if (bones.lHip) bones.lHip.rotation.set(
    deg(neg(p.lHipX)) + (identity.lHip?.x ?? 0),
    identity.lHip?.y ?? 0,
    deg(p.lHipZ) + (identity.lHip?.z ?? 0),
  );
  if (bones.lKnee) bones.lKnee.rotation.set(
    deg(neg(p.lKneeX)) + (identity.lKnee?.x ?? 0),
    identity.lKnee?.y ?? 0,
    identity.lKnee?.z ?? 0,
  );
  if (bones.lAnkle) bones.lAnkle.rotation.set(
    deg(neg(p.lAnkleX)) + (identity.lAnkle?.x ?? 0),
    identity.lAnkle?.y ?? 0,
    identity.lAnkle?.z ?? 0,
  );
  if (bones.rHip) bones.rHip.rotation.set(
    deg(neg(p.rHipX)) + (identity.rHip?.x ?? 0),
    identity.rHip?.y ?? 0,
    deg(p.rHipZ) + (identity.rHip?.z ?? 0),
  );
  if (bones.rKnee) bones.rKnee.rotation.set(
    deg(neg(p.rKneeX)) + (identity.rKnee?.x ?? 0),
    identity.rKnee?.y ?? 0,
    identity.rKnee?.z ?? 0,
  );
  if (bones.rAnkle) bones.rAnkle.rotation.set(
    deg(neg(p.rAnkleX)) + (identity.rAnkle?.x ?? 0),
    identity.rAnkle?.y ?? 0,
    identity.rAnkle?.z ?? 0,
  );
}

let _sharedGLTFLoader: GLTFLoader | null = null;
function getGLTFLoader(): GLTFLoader {
  if (!_sharedGLTFLoader) _sharedGLTFLoader = new GLTFLoader();
  return _sharedGLTFLoader;
}

const _glbCache = new Map<string, Promise<THREE.Group>>();

export type LoadGLBOptions = {
  wireframeOverlay?: boolean;
  overrideColor?: string;
  scale?: number;
};

export function loadGLBRiggedHumanoid(
  url: string,
  options?: LoadGLBOptions,
): Promise<THREE.Group> {
  const cached = _glbCache.get(url);
  if (cached) return cached;

  const task = new Promise<THREE.Group>((resolve, reject) => {
    getGLTFLoader().load(url, (gltf) => {
      const scene = gltf.scene;
      scene.name = "glb_scene_" + (url.split("/").pop()?.replace(/\\.glb$/i, "") ?? "");

      const boneMap = buildGLBBoneMap(scene);
      const identity = recordGLBTPose(boneMap);

      const color = options?.overrideColor;
      scene.traverse((obj) => {
        if ((obj as THREE.Mesh).isMesh) {
          const m = obj as THREE.Mesh;
          if (color) {
            m.material = new THREE.MeshStandardMaterial({
              color, roughness: 0.6, metalness: 0.05, skinning: true,
            });
          }
          m.castShadow = true;
          m.receiveShadow = true;
        }
      });

      if (options?.wireframeOverlay) {
        scene.traverse((obj) => {
          if ((obj as THREE.Mesh).isMesh) {
            const m = obj as THREE.Mesh;
            try {
              const edges = new THREE.EdgesGeometry(m.geometry, 25);
              const line = new THREE.LineSegments(
                edges,
                new THREE.LineBasicMaterial({ color: "#1e293b", transparent: true, opacity: 0.7 }),
              );
              line.renderOrder = 10;
              m.add(line);
            } catch { /* skip */ }
          }
        });
      }

      const root = new THREE.Group();
      root.add(scene);

      const hipsBone = boneMap.hips;
      if (hipsBone) {
        const wp = new THREE.Vector3();
        hipsBone.getWorldPosition(wp);
        scene.position.y = 0.92 - wp.y;
      }

      scene.scale.setScalar(options?.scale ?? 1.0);

      root.userData.glBones = boneMap;
      root.userData.glBonesIdentity = identity;
      root.userData.meshStyle = "glb-" + (url.split("/").pop()?.replace(/\\.glb$/i, "") ?? "");
      root.userData.sourceUrl = url;

      const foundCount = Object.values(boneMap).filter(Boolean).length;
      console.log("[RiggedHumanoid] GLB loaded:", { url, foundBones: foundCount });

      resolve(root);
    }, undefined, (err) => {
      console.error("[RiggedHumanoid] GLB failed:", url, err);
      reject(err);
    });
  });

  _glbCache.set(url, task);
  return task;
}

/* END GLUE */`;

content += glbCode;
fs.writeFileSync(p, content, 'utf8');
console.log('OK appended, total lines:', content.split('\n').length);
