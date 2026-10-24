// 直接从 three.js 的 GLTFLoader 拿到 glTF JSON，打印骨架
// glTF = JSON header + binary buffer
const fs = require("fs");
const path = require("path");

function parseGLB(filePath) {
  const buf = fs.readFileSync(filePath);
  const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);

  // glTF header: magic(4), version(4), length(4)
  const magic = String.fromCharCode(dv.getUint8(0), dv.getUint8(1), dv.getUint8(2), dv.getUint8(3));
  const version = dv.getUint32(4, true);
  const length = dv.getUint32(8, true);
  if (magic !== "glTF") throw new Error(`Not GLB: magic=${magic}`);

  // chunks: each has length(4), type(4), data(length)
  let offset = 12;
  let jsonChunk = null;
  while (offset < length) {
    const chunkLen = dv.getUint32(offset, true);
    const chunkType = dv.getUint32(offset + 4, true);
    const dataStart = offset + 8;
    if (chunkType === 0x4e4f534a) { // "JSON"
      jsonChunk = Buffer.from(buf.buffer, buf.byteOffset + dataStart, chunkLen).toString("utf8");
    }
    offset = dataStart + chunkLen;
  }
  return JSON.parse(jsonChunk);
}

function analyze(filePath) {
  const json = parseGLB(filePath);
  const name = path.basename(filePath);

  console.log(`\n${"=".repeat(60)}`);
  console.log(`FILE: ${name}`);
  console.log(`$ {"=".repeat(60)}`);

  // --- SkinnedMeshes ---
  const skins = json.skins || [];
  console.log(`\n[skins] count=${skins.length}`);
  skins.forEach((sk, i) => {
    console.log(`  skin[${i}]: joints=${sk.joints.length}`);
  });

  // --- Meshes ---
  const meshes = json.meshes || [];
  console.log(`\n[meshes] count=${meshes.length}`);
  meshes.forEach((m, i) => {
    console.log(`  mesh[${i}]: "${m.name || "(none)"}" primitives=${m.primitives.length}`);
    m.primitives.forEach((p, j) => {
      console.log(`    primitive[${j}]: material=${p.material} mode=${p.mode} indices=${p.indices}`);
      if (p.skin !== undefined) console.log(`      → skinned with skin[${p.skin}]`);
    });
  });

  // --- Nodes (scene graph, bones are just nodes with skin refs) ---
  const nodes = json.nodes || [];
  console.log(`\n[nodes total] count=${nodes.length}`);

  // 找到所有有 skin 关联的节点（即根骨骼）
  const skinnedNodes = new Set();
  meshes.forEach(m => m.primitives.forEach(p => {
    if (p.skin !== undefined) skinnedNodes.add(p.target);
  }));

  // 打印骨骼树：从根节点开始
  const visited = new Set();
  function printNode(idx, depth) {
    if (visited.has(idx)) return;
    visited.add(idx);
    const n = nodes[idx];
    const indent = "│  ".repeat(depth);
    const marker = n.skin !== undefined ? "◆" : "○";
    const meshTag = n.mesh !== undefined ? ` [mesh:${n.mesh}]` : "";
    const jointTag = skinnedNodes.has(idx) ? ` [skinned-root]` : "";
    console.log(`  ${indent}${marker} [${String(idx).padStart(3)}] "${n.name || "(none)"}"${meshTag}${jointTag}`);
    if (n.children) {
      n.children.forEach(c => printNode(c, depth + 1));
    }
  }

  // 找到所有 root 节点（没有 parent 的——在 glTF 里 scenes[*].nodes 列出）
  const scenes = json.scenes || [];
  scenes.forEach((scene, si) => {
    console.log(`\n[scene ${si}]`);
    scene.nodes.forEach(ni => printNode(ni, 0));
  });

  // 单独列出所有 mixamorig 骨骼名
  console.log(`\n[All bone-like node names]`);
  nodes.forEach((n, i) => {
    if (n.name) console.log(`  [${String(i).padStart(3)}] "${n.name}"`);
  });

  // --- Animations ---
  const animations = json.animations || [];
  console.log(`\n[animations] count=${animations.length}`);
  animations.forEach((a, i) => {
    console.log(`  [${i}] "${a.name || "(none)"}" samplers=${a.samplers.length} channels=${a.channels.length}`);
  });

  // --- 计算关键骨骼的 transform 信息 ---
  console.log(`\n[HUMAN JOINT CANDIDATES]`);
  const humanBones = [
    "Hips", "Spine", "Spine1", "Spine2", "Chest", "Neck", "Head",
    "LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand",
    "RightShoulder", "RightArm", "RightForeArm", "RightHand",
    "LeftUpLeg", "LeftLeg", "LeftFoot", "LeftToe",
    "RightUpLeg", "RightLeg", "RightFoot", "RightToe",
  ];
  const mixamoPrefixes = ["mixamorig", "mixamorig:", "mixamorig_"];
  function matchBone(keyword) {
    return nodes.findIndex(n => {
      if (!n.name) return false;
      const lower = n.name.toLowerCase();
      return lower.includes(keyword.toLowerCase()) ||
        mixamoPrefixes.some(p => n.name.startsWith(p)) && lower.includes(keyword.toLowerCase());
    });
  }
  humanBones.forEach(kb => {
    const idx = matchBone(kb);
    if (idx >= 0) {
      const n = nodes[idx];
      console.log(`  ✓ "${kb}" → node[${idx}] = "${n.name}"`);
    } else {
      // 宽松匹配
      const loose = nodes.find(n => n.name && n.name.toLowerCase().includes(kb.toLowerCase()));
      if (loose) console.log(`  ? "${kb}" → "${loose.name}"`);
      else console.log(`  ✗ "${kb}" NOT FOUND`);
    }
  });
}

const dir = path.join(__dirname, "vendor", "shiguang-canvas", "public", "models");
["Soldier.glb", "Xbot.glb"].forEach(f => {
  try { analyze(path.join(dir, f)); }
  catch (e) { console.log(`ERROR ${f}: ${e.message}`); }
});
