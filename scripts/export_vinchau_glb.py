"""
Export vinchau BodyChan / BodyKun (CC0, BlendSwap 23521) as Two.js-ready GLBs.

Source: https://www.blendswap.com/blend/23521
Sketchfab listing (not downloadable): 
  https://sketchfab.com/3d-models/poseable-drawing-figures-bodychan-bodykun-ed60f70cba9c4f14b837187d2129d8c9
"""
from __future__ import annotations

import os
import shutil

import bpy
from mathutils import Vector

SRC_CANDIDATES = [
    r"c:\Users\Administrator\Downloads\BodyChan - BodyKun  Posable Drawing Figures.blend",
    os.path.join(os.path.dirname(__file__), "..", "vendor", "shiguang-canvas", "models-src", "vinchau-bodychan-bodykun.blend"),
]
OUT_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "vendor", "shiguang-canvas", "public", "models")
)
SRC_COPY = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "vendor", "shiguang-canvas", "models-src", "vinchau-bodychan-bodykun.blend")
)
TARGET_HEIGHT = 1.70

# Most specific first (Rigify DEF → Mixamo names used by riggedHumanoid.ts)
BONE_RENAME = [
    ("DEF-upper_arm.L", "LeftArm"),
    ("DEF-upper_arm.R", "RightArm"),
    ("DEF-forearm.L", "LeftForeArm"),
    ("DEF-forearm.R", "RightForeArm"),
    ("DEF-shoulder.L", "LeftShoulder"),
    ("DEF-shoulder.R", "RightShoulder"),
    ("DEF-hand.L", "LeftHand"),
    ("DEF-hand.R", "RightHand"),
    ("DEF-thigh.L", "LeftUpLeg"),
    ("DEF-thigh.R", "RightUpLeg"),
    ("DEF-shin.L", "LeftLeg"),
    ("DEF-shin.R", "RightLeg"),
    ("DEF-foot.L", "LeftFoot"),
    ("DEF-foot.R", "RightFoot"),
    ("DEF-spine.006", "Head"),
    ("DEF-spine.004", "Neck"),
    ("DEF-spine.003", "Spine2"),
    ("DEF-spine.002", "Spine1"),
    ("DEF-spine.001", "Spine"),
    ("DEF-spine", "Hips"),
]


def find_src() -> str:
    for p in SRC_CANDIDATES:
        ap = os.path.abspath(p)
        if os.path.isfile(ap):
            return ap
    raise FileNotFoundError("vinchau BodyChan/BodyKun .blend not found")


def rest_pose(arm_obj):
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode="POSE")
    bpy.ops.pose.select_all(action="SELECT")
    bpy.ops.pose.transforms_clear()
    bpy.ops.object.mode_set(mode="OBJECT")


def body_meshes(arm_name: str):
    out = []
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        if o.name.startswith("WGT"):
            continue
        if o.parent and o.parent.name == arm_name:
            out.append(o)
    return out


def ensure_grey_material():
    name = "VinchauClay"
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.78, 0.78, 0.76, 1)
        bsdf.inputs["Roughness"].default_value = 0.72
        bsdf.inputs["Metallic"].default_value = 0.03
    return mat


def assign_clay(meshes):
    mat = ensure_grey_material()
    for o in meshes:
        o.data.materials.clear()
        o.data.materials.append(mat)


def rename_def_bones(arm_obj):
    bones = arm_obj.data.bones
    for old, new in BONE_RENAME:
        b = bones.get(old)
        if b:
            b.name = new
            print(f"  rename {old} -> {b.name}")
        else:
            print(f"  missing {old}")


def mesh_height(meshes) -> float:
    deps = bpy.context.evaluated_depsgraph_get()
    mn = Vector((1e9, 1e9, 1e9))
    mx = Vector((-1e9, -1e9, -1e9))
    for o in meshes:
        eo = o.evaluated_get(deps)
        for corner in eo.bound_box:
            w = eo.matrix_world @ Vector(corner)
            mn.x, mn.y, mn.z = min(mn.x, w.x), min(mn.y, w.y), min(mn.z, w.z)
            mx.x, mx.y, mx.z = max(mx.x, w.x), max(mx.y, w.y), max(mx.z, w.z)
    return max(0.01, mx.z - mn.z)


def apply_uniform_scale(arm_obj, meshes, scale: float):
    arm_obj.scale = (scale, scale, scale)
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action="DESELECT")
    arm_obj.select_set(True)
    for m in meshes:
        m.select_set(True)
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)


def export_character(arm_name: str, out_path: str):
    arm = bpy.data.objects.get(arm_name)
    if not arm:
        raise RuntimeError(f"armature missing: {arm_name}")
    meshes = body_meshes(arm_name)
    if not meshes:
        raise RuntimeError(f"no meshes for {arm_name}")
    print(f"\n=== {arm_name} meshes={len(meshes)} -> {out_path}")

    rest_pose(arm)
    assign_clay(meshes)
    rename_def_bones(arm)

    h = mesh_height(meshes)
    scale = TARGET_HEIGHT / h
    print(f"  height={h:.3f} scale={scale:.5f}")
    apply_uniform_scale(arm, meshes, scale)

    for o in bpy.data.objects:
        skip = o.name.startswith("WGT") or o.type in {"CAMERA", "LIGHT"}
        if o.type == "ARMATURE" and o.name != arm_name:
            skip = True
        if skip:
            o.hide_viewport = True
            o.hide_render = True
            try:
                o.hide_set(True)
            except RuntimeError:
                pass

    vis = {arm, *meshes}
    for o in list(bpy.data.objects):
        want = o in vis
        o.hide_viewport = not want
        o.hide_render = not want

    exp = bpy.data.collections.new("SHIGUANG_EXPORT")
    bpy.context.scene.collection.children.link(exp)
    for o in vis:
        try:
            exp.objects.link(o)
        except RuntimeError:
            pass
    # make it the active collection
    layer = bpy.context.view_layer.layer_collection
    def find_lc(lc, name):
        if lc.collection.name == name:
            return lc
        for ch in lc.children:
            f = find_lc(ch, name)
            if f:
                return f
        return None
    lc = find_lc(layer, "SHIGUANG_EXPORT")
    if lc:
        bpy.context.view_layer.active_layer_collection = lc

    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    for m in meshes:
        m.select_set(True)
    print("  selected", [(o.name, o.type) for o in bpy.context.selected_objects])

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    kwargs = dict(
        filepath=out_path,
        export_format="GLB",
        use_selection=False,
        use_visible=True,
        use_active_collection=True,
        export_apply=False,
        export_yup=True,
        export_extras=False,
        export_cameras=False,
        export_lights=False,
        export_skins=True,
        export_animations=False,
        export_morph=False,
    )
    try:
        bpy.ops.export_scene.gltf(**kwargs, export_def_bones=True, export_rest_position_armature=True)
    except TypeError:
        kwargs.pop("use_visible", None)
        kwargs.pop("use_active_collection", None)
        kwargs["use_selection"] = True
        bpy.ops.export_scene.gltf(**kwargs)
    print("  WROTE", out_path, os.path.getsize(out_path) if os.path.isfile(out_path) else 0)


def main():
    src = find_src()
    os.makedirs(os.path.dirname(SRC_COPY), exist_ok=True)
    if os.path.abspath(src) != os.path.abspath(SRC_COPY):
        shutil.copy2(src, SRC_COPY)
        print("copied source ->", SRC_COPY)

    # BodyChan first (fresh file), then reopen for BodyKun so renames don't collide
    for arm_name, fname in (("rig", "bodychan.glb"), ("body_kun_rig", "bodykun.glb")):
        bpy.ops.wm.open_mainfile(filepath=SRC_COPY)
        export_character(arm_name, os.path.join(OUT_DIR, fname))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback

        traceback.print_exc()
        raise
