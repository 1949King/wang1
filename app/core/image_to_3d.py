# -*- coding: utf-8 -*-
"""图片转3D · 深度重建 GLB 网格路（T5 项四，2026-11-20）。

对标上游无界工作台的 MoGe 深度→点云→GLB 网格路（三条 3D 路之一）：
单图 → Depth-Anything-V2-Small 逆深度 → fov 反投影 → 网格三角化 +
深度不连续剔除（MoGePointMapToMesh 原理）→ 顶点色 → trimesh 导出 GLB。

诚实纪律（本模块的红线）
========================
- 产物是**深度重建 2.5D 网格（单图浮雕）**，不是真体积重建 / 高斯泼溅；
  返回值 note 如实标注，前端节点同样显著标注，不冒充真 3D 生成。
- 深度**必须来自真深度模型**（复用 video_depth，本地优先）；模型缺失 ⇒
  ok:false + guidance（资源地址自取），**绝不触网下载、不用灰度冒充深度**。
- 深度是**相对逆深度**（越大越近，非米制）；反投影距离为相对单位，不吹尺度。
- trimesh 缺失 / 推理异常 / 外链图源 ⇒ 诚实失败，不产出半成品。

分层：core 层任务体，由 canvas_routes_post 经 canvas_gen_jobs.submit 调度
（worker 线程执行，不卡 HTTP/主界面）。重依赖（cv2/numpy/trimesh/video_depth）
懒 import，使 parse_image_to_3d_request 纯函数可在无重依赖环境单测。
"""
from __future__ import annotations

import base64
import logging
import math
import os
import time
import uuid
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("AI短剧编辑器.image_to_3d")

# fov / 网格分辨率钳制区间（默认值即推荐值）
FOV_MIN, FOV_MAX, FOV_DEFAULT = 30.0, 120.0, 60.0
MAX_SIDE_MIN, MAX_SIDE_MAX, MAX_SIDE_DEFAULT = 128, 512, 320

#: 深度不连续剔除阈值（归一化深度差，MoGePointMapToMesh 原理：跨物体边界的三角面剔除）
DISCONTINUITY_THRESHOLD = 0.04
#: 反投影相对距离区间（逆深度越大越近 ⇒ 距离越小；相对单位，非米制）
Z_NEAR, Z_FAR = 1.0, 3.0

#: 产物诚实标注（前端节点同步展示）
MESH_NOTE = "深度重建 2.5D 网格（单图浮雕），非真体积重建 / 高斯泼溅；深度为相对逆深度，非米制"


def parse_image_to_3d_request(body: Any) -> Dict[str, Any]:
    """解析 /host/image-to-3d 请求体（纯函数，不触网/不读图）。

    返回 {ok, image, fov, max_side, title} 或 {ok:False, error}。
    图源别名兼容 image / image_url / imageUrl / image_path / imagePath；
    fov 钳制 [30,120]，max_side 钳制 [128,512]。
    """
    if not isinstance(body, dict):
        return {"ok": False, "error": "请求体无效"}
    image = str(
        body.get("image") or body.get("image_url") or body.get("imageUrl")
        or body.get("image_path") or body.get("imagePath") or ""
    ).strip()
    if not image:
        return {"ok": False, "error": "缺少图像源（image / image_url / image_path）"}

    try:
        fov = float(body.get("fov") or FOV_DEFAULT)
    except (TypeError, ValueError):
        fov = FOV_DEFAULT
    fov = max(FOV_MIN, min(FOV_MAX, fov))

    try:
        max_side = int(float(body.get("max_side") or MAX_SIDE_DEFAULT))
    except (TypeError, ValueError):
        max_side = MAX_SIDE_DEFAULT
    max_side = max(MAX_SIDE_MIN, min(MAX_SIDE_MAX, max_side))

    return {"ok": True, "image": image, "fov": fov, "max_side": max_side,
            "title": str(body.get("title") or "")}


def _imread_unicode(path: str):
    """Unicode 安全读图（cv2.imread 中文路径静默失败 ⇒ np.fromfile+imdecode）。"""
    import cv2
    import numpy as np
    try:
        data = np.fromfile(path, dtype=np.uint8)
        if data.size == 0:
            return None
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception as e:
        logger.debug("[image_to_3d] 读图失败 %s: %s", path, e)
        return None


def _resolve_image_bgr(source: str) -> Tuple[Optional[Any], str]:
    """图源归一化为 BGR ndarray：data URL / inbox 引用 / 本地路径。

    外链（非 inbox 的 http/https）⇒ 诚实失败（本地深度重建需本地文件）。
    返回 (img_bgr, error)；成功 error 为空串。
    """
    import cv2
    import numpy as np

    value = (source or "").strip()
    if not value:
        return None, "缺少图像源"

    # 形态 1：data URL（画布小图直传）→ 解码内存读图
    if value.startswith("data:"):
        try:
            _, b64 = value.split(",", 1)
            raw = base64.b64decode(b64)
        except Exception:
            return None, "图像 data URL 解码失败"
        img = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return None, "图像 data URL 不是有效图片"
        return img, ""

    # 形态 2：画布 inbox 引用（/inbox_file/xxx 或 http://127.0.0.1:port/inbox_file/xxx）
    if "/inbox_file/" in value:
        from app.core.canvas_bridge import canvas_inbox_dir
        name = os.path.basename(value.split("/inbox_file/", 1)[-1].split("?")[0])
        path = os.path.join(canvas_inbox_dir(), name)
        if not os.path.isfile(path):
            return None, f"收件箱图像不存在: {name}"
        img = _imread_unicode(path)
        if img is None:
            return None, f"收件箱图像读取失败: {name}"
        return img, ""

    # 形态 3：外链 ⇒ 诚实失败（不触网下载）
    if value.startswith(("http://", "https://")):
        return None, "外链图像不支持本地深度重建（请先上传到画布收件箱）"

    # 形态 4：本地路径
    if os.path.isfile(value):
        img = _imread_unicode(value)
        if img is None:
            return None, f"图像读取失败: {value}"
        return img, ""
    return None, f"图像文件不存在: {value}"


def _build_mesh_arrays(img_bgr, depth, fov: float, max_side: int):
    """逆深度 → fov 反投影 → 网格三角化 + 不连续剔除 → 顶点色。

    纯 numpy/cv2 计算（可单测）。返回 (vertices(N,3) float32, faces(M,3) int64,
    colors(N,3) uint8 RGB, culled int)。网格降采样到 max_side 控制面数。
    """
    import cv2
    import numpy as np

    h0, w0 = depth.shape[:2]
    scale = min(1.0, float(max_side) / max(h0, w0))
    nh = max(2, int(round(h0 * scale)))
    nw = max(2, int(round(w0 * scale)))
    if (nh, nw) != (h0, w0):
        img_s = cv2.resize(img_bgr, (nw, nh), interpolation=cv2.INTER_AREA)
        d_s = cv2.resize(depth, (nw, nh), interpolation=cv2.INTER_AREA)
    else:
        img_s, d_s = img_bgr, depth

    d = np.asarray(d_s, dtype="float32")
    lo, hi = float(np.min(d)), float(np.max(d))
    if not math.isfinite(lo) or not math.isfinite(hi) or hi - lo < 1e-6:
        dn = np.full(d.shape, 0.5, dtype="float32")   # 全平 ⇒ 平面浮雕
    else:
        dn = (d - lo) / (hi - lo)                     # 归一化逆深度（越大越近）

    # fov 反投影：相对距离 = 近 + (1-逆深度)×(远-近)；方形像素 fx=fy
    dist = Z_NEAR + (1.0 - dn) * (Z_FAR - Z_NEAR)
    fx = (nw / 2.0) / math.tan(math.radians(fov) / 2.0)
    cx, cy = (nw - 1) / 2.0, (nh - 1) / 2.0
    us, vs = np.meshgrid(np.arange(nw, dtype="float32"),
                         np.arange(nh, dtype="float32"))
    xs = (us - cx) * dist / fx
    ys = -(vs - cy) * dist / fx        # 图像 y 向下 ⇒ three.js y 向上取反
    zs = -dist                          # 相机朝 -z（three.js 惯例）
    verts = np.stack([xs, ys, zs], axis=-1).reshape(-1, 3)
    verts -= verts.mean(axis=0)         # 居中 ⇒ OrbitControls 绕原点环绕
    colors = cv2.cvtColor(img_s, cv2.COLOR_BGR2RGB).reshape(-1, 3)

    # 网格三角化（每格两三角）+ 深度不连续剔除（跨物体边界的面剔除）
    idx = np.arange(nh * nw).reshape(nh, nw)
    a = idx[:-1, :-1].ravel()
    b = idx[:-1, 1:].ravel()
    c = idx[1:, :-1].ravel()
    e = idx[1:, 1:].ravel()
    tris = np.concatenate([np.stack([a, b, c], axis=1),
                           np.stack([b, e, c], axis=1)])
    td = dn.ravel()[tris]
    span = td.max(axis=1) - td.min(axis=1)
    keep = span <= DISCONTINUITY_THRESHOLD
    faces = tris[keep]
    culled = int((~keep).sum())
    return verts.astype("float32"), faces.astype("int64"), colors, culled


def run_image_to_3d(req: Dict[str, Any], report: Any) -> Dict[str, Any]:
    """任务体：读图 → 深度估计 → 网格重建 → 导出 GLB 落 inbox。

    report 为 canvas_gen_jobs.StageReporter（stage/progress/note）。
    返回 {ok, model_path, model_url, vertices, faces, culled, fov, engine, note}
    或 {ok:False, error, guidance?}。深度模型无细粒度进度信号 ⇒ progress(None)。
    """
    from app.core import canvas_gen_jobs, video_depth
    from app.core.canvas_bridge import canvas_inbox_dir

    # ── 1. 深度模型缺失：诚实报错 + 引导（先于读图快速失败，绝不触网、不冒充）──
    av = video_depth.available()
    if not av.get("available"):
        return {"ok": False, "error": av.get("reason", "深度模型不可用"),
                "guidance": av.get("hint", "")}

    # ── 2. 图源归一化（外链诚实失败）──
    report.stage("resolve", "读取图像")
    report.progress(None)
    img, err = _resolve_image_bgr(str(req.get("image") or ""))
    if img is None:
        return {"ok": False, "error": err}

    tok = canvas_gen_jobs.current_token()
    if tok is not None and tok.cancelled:
        raise canvas_gen_jobs.GenCancelled()

    # ── 3. 深度估计（真模型，相对逆深度）──
    report.stage("depth", "深度估计")
    report.note("深度模型无细粒度进度信号，按阶段提示")
    depth = video_depth.estimate_depth_bgr(img)
    if depth is None:
        return {"ok": False, "error": "深度推理失败（模型加载/推理异常，详见日志）"}

    tok = canvas_gen_jobs.current_token()
    if tok is not None and tok.cancelled:
        raise canvas_gen_jobs.GenCancelled()

    # ── 4. 网格重建（反投影 + 不连续剔除）──
    report.stage("mesh", "网格重建")
    fov = float(req.get("fov") or FOV_DEFAULT)
    max_side = int(req.get("max_side") or MAX_SIDE_DEFAULT)
    verts, faces, colors, culled = _build_mesh_arrays(img, depth, fov, max_side)
    if len(faces) == 0:
        return {"ok": False, "error": "深度不连续剔除后无有效面（画面深度跳变过大）"}

    try:
        import trimesh
    except ImportError:
        return {"ok": False, "error": "trimesh 未安装，无法导出 GLB（pip install trimesh）"}

    # ── 5. 导出 GLB 落 inbox（顶点色，process=False 保顶点数不变）──
    report.stage("export", "导出 GLB")
    try:
        mesh = trimesh.Trimesh(vertices=verts, faces=faces,
                               vertex_colors=colors, process=False)
        glb = mesh.export(file_type="glb")
    except Exception as e:
        logger.exception("[image_to_3d] GLB 导出失败")
        return {"ok": False, "error": f"GLB 导出失败: {e}"}
    name = f"img3d_{int(time.time())}_{uuid.uuid4().hex[:6]}.glb"
    path = os.path.join(canvas_inbox_dir(), name)
    try:
        with open(path, "wb") as f:
            f.write(glb)
    except Exception as e:
        logger.exception("[image_to_3d] GLB 落盘失败")
        return {"ok": False, "error": f"GLB 落盘失败: {e}"}

    return {
        "ok": True,
        "model_path": path,
        "model_url": f"/inbox_file/{name}",
        "vertices": int(len(verts)),
        "faces": int(len(faces)),
        "culled": culled,
        "fov": fov,
        "engine": "depth-anything-v2-small",
        "note": MESH_NOTE,
    }
