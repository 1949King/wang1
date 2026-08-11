/**
 * LibTV 向轻量 3D 导演台：人体素模站位 + 多机位 + FOV + 截图回画布。
 * 纯 three.js，无 R3F，便于 Qt WebEngine 稳定加载。
 */
import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

export type StageActor = {
  id: string;
  name: string;
  kind: "actor" | "box" | "cylinder";
  color: string;
  position: [number, number, number];
  rotationY: number;
  scale: number;
};

export type StageCamera = {
  id: string;
  name: string;
  position: [number, number, number];
  lookAt: [number, number, number];
  fov: number;
};

type Props = {
  onCapture: (dataUrl: string, meta: { cameraName: string; fov: number }) => void;
  onStatus: (msg: string) => void;
};

function uid(p: string) {
  return `${p}_${Math.random().toString(36).slice(2, 8)}`;
}

function makeHumanoid(color: string): THREE.Group {
  const g = new THREE.Group();
  const mat = new THREE.MeshStandardMaterial({ color, roughness: 0.55, metalness: 0.05 });
  const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.28, 0.9, 6, 12), mat);
  body.position.y = 0.95;
  body.castShadow = true;
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.22, 16, 12), mat);
  head.position.y = 1.72;
  head.castShadow = true;
  const nose = new THREE.Mesh(
    new THREE.ConeGeometry(0.06, 0.12, 8),
    new THREE.MeshStandardMaterial({ color: "#fbbf24" }),
  );
  nose.rotation.x = Math.PI / 2;
  nose.position.set(0, 1.72, 0.22);
  g.add(body, head, nose);
  return g;
}

function makeProp(kind: "box" | "cylinder", color: string): THREE.Mesh {
  const geo =
    kind === "box"
      ? new THREE.BoxGeometry(0.6, 0.6, 0.6)
      : new THREE.CylinderGeometry(0.28, 0.28, 0.8, 16);
  const mesh = new THREE.Mesh(
    geo,
    new THREE.MeshStandardMaterial({ color, roughness: 0.6 }),
  );
  mesh.position.y = kind === "box" ? 0.3 : 0.4;
  mesh.castShadow = true;
  return mesh;
}

export default function Stage3D({ onCapture, onStatus }: Props) {
  const mountRef = useRef<HTMLDivElement>(null);
  const apiRef = useRef<{
    scene: THREE.Scene;
    camera: THREE.PerspectiveCamera;
    renderer: THREE.WebGLRenderer;
    controls: OrbitControls;
    objects: Map<string, THREE.Object3D>;
    camHelpers: Map<string, THREE.Object3D>;
    raycaster: THREE.Raycaster;
    ground: THREE.Mesh;
  } | null>(null);

  const [actors, setActors] = useState<StageActor[]>([
    {
      id: uid("a"),
      name: "角色 A",
      kind: "actor",
      color: "#60a5fa",
      position: [-1.2, 0, 0],
      rotationY: 0.4,
      scale: 1,
    },
    {
      id: uid("a"),
      name: "角色 B",
      kind: "actor",
      color: "#f472b6",
      position: [1.2, 0, 0.3],
      rotationY: -0.5,
      scale: 1,
    },
  ]);
  const [cameras, setCameras] = useState<StageCamera[]>([
    {
      id: uid("cam"),
      name: "机位 1",
      position: [0, 1.6, 4.5],
      lookAt: [0, 1.2, 0],
      fov: 45,
    },
  ]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [activeCamId, setActiveCamId] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"director" | "camera">("director");
  const [tool, setTool] = useState<"move" | "rotate" | "scale">("move");
  const [fov, setFov] = useState(45);
  const [aspect, setAspect] = useState<"16:9" | "9:16" | "1:1">("9:16");

  const selected = actors.find((a) => a.id === selectedId) || null;
  const activeCam = cameras.find((c) => c.id === activeCamId) || cameras[0] || null;

  // Init three.js
  useEffect(() => {
    const el = mountRef.current;
    if (!el) return;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#0c1118");
    scene.fog = new THREE.Fog("#0c1118", 18, 42);

    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
    camera.position.set(5, 4, 7);

    const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    el.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.target.set(0, 1, 0);

    const hemi = new THREE.HemisphereLight(0xb8d4ff, 0x1a1a1a, 0.85);
    scene.add(hemi);
    const dir = new THREE.DirectionalLight(0xffffff, 1.1);
    dir.position.set(4, 8, 3);
    dir.castShadow = true;
    scene.add(dir);

    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(40, 40),
      new THREE.MeshStandardMaterial({ color: "#141c28", roughness: 0.95 }),
    );
    ground.rotation.x = -Math.PI / 2;
    ground.receiveShadow = true;
    scene.add(ground);

    const grid = new THREE.GridHelper(40, 40, 0x2a3a4d, 0x1a2433);
    (grid.material as THREE.Material).opacity = 0.55;
    (grid.material as THREE.Material).transparent = true;
    scene.add(grid);

    const objects = new Map<string, THREE.Object3D>();
    const camHelpers = new Map<string, THREE.Object3D>();
    const raycaster = new THREE.Raycaster();

    apiRef.current = {
      scene,
      camera,
      renderer,
      controls,
      objects,
      camHelpers,
      raycaster,
      ground,
    };

    const resize = () => {
      const w = el.clientWidth;
      const h = el.clientHeight;
      if (w < 2 || h < 2) return;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h, false);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(el);

    let raf = 0;
    const tick = () => {
      raf = requestAnimationFrame(tick);
      controls.update();
      renderer.render(scene, camera);
    };
    tick();

    onStatus("3D 导演台就绪 — V 移动 · R 旋转 · S 缩放 · 截图回画布");

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      controls.dispose();
      renderer.dispose();
      el.removeChild(renderer.domElement);
      apiRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Sync actors into scene
  useEffect(() => {
    const api = apiRef.current;
    if (!api) return;
    const keep = new Set(actors.map((a) => a.id));
    for (const [id, obj] of api.objects) {
      if (!keep.has(id)) {
        api.scene.remove(obj);
        api.objects.delete(id);
      }
    }
    for (const a of actors) {
      let obj = api.objects.get(a.id);
      if (!obj) {
        obj =
          a.kind === "actor"
            ? makeHumanoid(a.color)
            : makeProp(a.kind, a.color);
        obj.userData.id = a.id;
        api.scene.add(obj);
        api.objects.set(a.id, obj);
      }
      obj.position.set(a.position[0], a.position[1], a.position[2]);
      obj.rotation.y = a.rotationY;
      obj.scale.setScalar(a.scale);
      // selection outline via emissive
      obj.traverse((ch) => {
        if (ch instanceof THREE.Mesh && ch.material instanceof THREE.MeshStandardMaterial) {
          ch.material.emissive = new THREE.Color(a.id === selectedId ? "#1d4ed8" : "#000000");
          ch.material.emissiveIntensity = a.id === selectedId ? 0.35 : 0;
        }
      });
    }
  }, [actors, selectedId]);

  // Sync camera helpers
  useEffect(() => {
    const api = apiRef.current;
    if (!api) return;
    const keep = new Set(cameras.map((c) => c.id));
    for (const [id, obj] of api.camHelpers) {
      if (!keep.has(id)) {
        api.scene.remove(obj);
        api.camHelpers.delete(id);
      }
    }
    for (const c of cameras) {
      let helper = api.camHelpers.get(c.id);
      if (!helper) {
        const g = new THREE.Group();
        const cone = new THREE.Mesh(
          new THREE.ConeGeometry(0.18, 0.4, 12),
          new THREE.MeshStandardMaterial({ color: "#fbbf24" }),
        );
        cone.rotation.x = Math.PI / 2;
        const body = new THREE.Mesh(
          new THREE.BoxGeometry(0.28, 0.2, 0.35),
          new THREE.MeshStandardMaterial({ color: "#f59e0b" }),
        );
        body.position.z = 0.2;
        g.add(cone, body);
        api.scene.add(g);
        api.camHelpers.set(c.id, g);
        helper = g;
      }
      helper.position.set(c.position[0], c.position[1], c.position[2]);
      helper.lookAt(c.lookAt[0], c.lookAt[1], c.lookAt[2]);
    }
  }, [cameras]);

  // Director vs camera view
  useEffect(() => {
    const api = apiRef.current;
    if (!api) return;
    if (viewMode === "camera" && activeCam) {
      api.controls.enabled = false;
      api.camera.fov = activeCam.fov || fov;
      api.camera.position.set(...activeCam.position);
      api.camera.lookAt(...activeCam.lookAt);
      api.camera.updateProjectionMatrix();
    } else {
      api.controls.enabled = true;
      api.camera.fov = 45;
      api.camera.updateProjectionMatrix();
    }
  }, [viewMode, activeCam, fov]);

  // Pointer interactions
  useEffect(() => {
    const api = apiRef.current;
    const el = mountRef.current;
    if (!api || !el) return;

    const onPointerDown = (ev: PointerEvent) => {
      const rect = el.getBoundingClientRect();
      const x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
      const y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;
      api.raycaster.setFromCamera(new THREE.Vector2(x, y), api.camera);
      const meshes: THREE.Object3D[] = [];
      api.objects.forEach((o) => meshes.push(o));
      const hits = api.raycaster.intersectObjects(meshes, true);
      if (hits.length) {
        let obj: THREE.Object3D | null = hits[0].object;
        while (obj && !obj.userData.id) obj = obj.parent;
        if (obj?.userData.id) {
          setSelectedId(obj.userData.id);
          ev.stopPropagation();
        }
      }
    };

    const onPointerMove = (ev: PointerEvent) => {
      if (ev.buttons !== 1 || !selectedId || tool !== "move" || viewMode === "camera") return;
      const rect = el.getBoundingClientRect();
      const x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
      const y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;
      api.raycaster.setFromCamera(new THREE.Vector2(x, y), api.camera);
      const hit = api.raycaster.intersectObject(api.ground)[0];
      if (!hit) return;
      setActors((prev) =>
        prev.map((a) =>
          a.id === selectedId
            ? { ...a, position: [hit.point.x, 0, hit.point.z] as [number, number, number] }
            : a,
        ),
      );
    };

    const onKey = (ev: KeyboardEvent) => {
      const k = ev.key.toLowerCase();
      if (k === "v") setTool("move");
      if (k === "r") setTool("rotate");
      if (k === "s") setTool("scale");
      if (k === "delete" || k === "backspace") {
        if (selectedId) {
          setActors((prev) => prev.filter((a) => a.id !== selectedId));
          setSelectedId(null);
        }
      }
    };

    el.addEventListener("pointerdown", onPointerDown);
    el.addEventListener("pointermove", onPointerMove);
    window.addEventListener("keydown", onKey);
    return () => {
      el.removeEventListener("pointerdown", onPointerDown);
      el.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("keydown", onKey);
    };
  }, [selectedId, tool, viewMode]);

  const addActor = (kind: StageActor["kind"]) => {
    const colors = ["#60a5fa", "#f472b6", "#34d399", "#a78bfa", "#fb923c"];
    const n = actors.length;
    setActors((prev) => [
      ...prev,
      {
        id: uid("a"),
        name: kind === "actor" ? `角色 ${n + 1}` : kind === "box" ? `方块 ${n + 1}` : `柱体 ${n + 1}`,
        kind,
        color: colors[n % colors.length],
        position: [n * 0.4 - 1, 0, n * 0.2],
        rotationY: 0,
        scale: 1,
      },
    ]);
  };

  const addCameraFromView = () => {
    const api = apiRef.current;
    if (!api) return;
    const p = api.camera.position;
    const t = api.controls.target;
    const cam: StageCamera = {
      id: uid("cam"),
      name: `机位 ${cameras.length + 1}`,
      position: [p.x, p.y, p.z],
      lookAt: [t.x, t.y, t.z],
      fov,
    };
    setCameras((prev) => [...prev, cam]);
    setActiveCamId(cam.id);
    onStatus(`已保存 ${cam.name}`);
  };

  const capture = () => {
    const api = apiRef.current;
    if (!api) return;
    // temporary aspect framing
    const el = mountRef.current!;
    const w = el.clientWidth;
    const h = el.clientHeight;
    let rw = w;
    let rh = h;
    if (aspect === "9:16") {
      rh = h;
      rw = Math.round(h * (9 / 16));
    } else if (aspect === "16:9") {
      rw = w;
      rh = Math.round(w * (9 / 16));
    } else {
      const s = Math.min(w, h);
      rw = s;
      rh = s;
    }
    const prevW = api.renderer.domElement.width;
    const prevH = api.renderer.domElement.height;
    api.renderer.setSize(rw, rh, false);
    if (viewMode === "camera" && activeCam) {
      api.camera.fov = activeCam.fov || fov;
      api.camera.aspect = rw / rh;
      api.camera.position.set(...activeCam.position);
      api.camera.lookAt(...activeCam.lookAt);
      api.camera.updateProjectionMatrix();
    } else {
      api.camera.aspect = rw / rh;
      api.camera.updateProjectionMatrix();
    }
    api.renderer.render(api.scene, api.camera);
    const dataUrl = api.renderer.domElement.toDataURL("image/png");
    api.renderer.setSize(prevW, prevH, false);
    api.camera.aspect = w / Math.max(h, 1);
    api.camera.updateProjectionMatrix();
    onCapture(dataUrl, {
      cameraName: activeCam?.name || "导演视角",
      fov: activeCam?.fov || fov,
    });
  };

  const patchSelected = (patch: Partial<StageActor>) => {
    if (!selectedId) return;
    setActors((prev) => prev.map((a) => (a.id === selectedId ? { ...a, ...patch } : a)));
  };

  return (
    <div className="stage3d">
      <div className="stage3d-viewport" ref={mountRef} />
      <div className="stage3d-frame" data-aspect={aspect} />

      <aside className="stage3d-rail left">
        <div className="stage3d-title">3D 导演台</div>
        <p className="muted">摆站位 → 设机位 → 截图回画布作生成参考</p>

        <div className="seg">
          <button
            type="button"
            className={viewMode === "director" ? "on" : ""}
            onClick={() => setViewMode("director")}
          >
            导演视角
          </button>
          <button
            type="button"
            className={viewMode === "camera" ? "on" : ""}
            onClick={() => setViewMode("camera")}
          >
            机位视角
          </button>
        </div>

        <div className="seg">
          <button type="button" className={tool === "move" ? "on" : ""} onClick={() => setTool("move")}>
            V 移动
          </button>
          <button type="button" className={tool === "rotate" ? "on" : ""} onClick={() => setTool("rotate")}>
            R 旋转
          </button>
          <button type="button" className={tool === "scale" ? "on" : ""} onClick={() => setTool("scale")}>
            S 缩放
          </button>
        </div>

        <div className="section-title">添加</div>
        <button className="btn" onClick={() => addActor("actor")}>
          + 人体素模
        </button>
        <button className="btn" onClick={() => addActor("box")}>
          + 方块道具
        </button>
        <button className="btn" onClick={() => addActor("cylinder")}>
          + 柱体道具
        </button>

        <div className="section-title">元素</div>
        <div className="stage3d-list">
          {actors.map((a) => (
            <button
              key={a.id}
              type="button"
              className={`stage3d-item${a.id === selectedId ? " on" : ""}`}
              onClick={() => setSelectedId(a.id)}
            >
              <span className="dot" style={{ background: a.color }} />
              {a.name}
            </button>
          ))}
        </div>
      </aside>

      <aside className="stage3d-rail right">
        <div className="section-title">摄像机</div>
        <button className="btn primary" onClick={addCameraFromView}>
          从当前视角存机位
        </button>
        <div className="stage3d-list">
          {cameras.map((c) => (
            <button
              key={c.id}
              type="button"
              className={`stage3d-item${c.id === activeCamId ? " on" : ""}`}
              onClick={() => {
                setActiveCamId(c.id);
                setFov(c.fov);
                setViewMode("camera");
              }}
            >
              📷 {c.name} · {c.fov}°
            </button>
          ))}
        </div>

        <div className="field">
          <label>FOV {fov}°</label>
          <input
            type="range"
            min={18}
            max={90}
            value={fov}
            onChange={(e) => {
              const v = Number(e.target.value);
              setFov(v);
              if (activeCamId) {
                setCameras((prev) =>
                  prev.map((c) => (c.id === activeCamId ? { ...c, fov: v } : c)),
                );
              }
            }}
          />
        </div>
        <div className="field">
          <label>截图比例</label>
          <select value={aspect} onChange={(e) => setAspect(e.target.value as typeof aspect)}>
            <option value="9:16">9:16 竖屏漫剧</option>
            <option value="16:9">16:9</option>
            <option value="1:1">1:1</option>
          </select>
        </div>
        <button className="btn primary" onClick={capture}>
          截图 → 画布
        </button>

        {selected ? (
          <>
            <div className="section-title">选中：{selected.name}</div>
            <div className="field">
              <label>名称</label>
              <input
                value={selected.name}
                onChange={(e) => patchSelected({ name: e.target.value })}
              />
            </div>
            {tool === "rotate" || true ? (
              <div className="field">
                <label>朝向 Y</label>
                <input
                  type="range"
                  min={-Math.PI}
                  max={Math.PI}
                  step={0.01}
                  value={selected.rotationY}
                  onChange={(e) => patchSelected({ rotationY: Number(e.target.value) })}
                />
              </div>
            ) : null}
            <div className="field">
              <label>缩放</label>
              <input
                type="range"
                min={0.4}
                max={2.5}
                step={0.05}
                value={selected.scale}
                onChange={(e) => patchSelected({ scale: Number(e.target.value) })}
              />
            </div>
            <button
              className="btn"
              onClick={() => {
                setActors((prev) => prev.filter((a) => a.id !== selected.id));
                setSelectedId(null);
              }}
            >
              删除元素
            </button>
          </>
        ) : (
          <p className="muted">点击场景中的角色/道具进行编辑</p>
        )}
      </aside>
    </div>
  );
}
