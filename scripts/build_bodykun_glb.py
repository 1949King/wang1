"""
Generate BodyKun / BodyChan style GLBs (grey mannequin + contour grid + ball joints).
Original recreation for Three.js — Mixamo bone names so existing JointPose retarget works.

Run:
  "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" --background --python scripts/build_bodykun_glb.py
"""
from __future__ import annotations

import math
import os
import sys

import bpy
from mathutils import Vector

OUT_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "vendor", "shiguang-canvas", "public", "models")
)

# Mixamo-compatible names used by riggedHumanoid.buildGLBBoneMap
BONES = [
    ("Hips", None, (0, 0, 0.92)),
    ("Spine", "Hips", (0, 0, 0.10)),
    ("Spine1", "Spine", (0, 0, 0.12)),
    ("Spine2", "Spine1", (0, 0, 0.14)),
    ("Neck", "Spine2", (0, 0, 0.16)),
    ("Head", "Neck", (0, 0, 0.08)),
    ("LeftShoulder", "Spine2", (0.08, 0, 0.12)),
    ("LeftArm", "LeftShoulder", (0.14, 0, 0)),
    ("LeftForeArm", "LeftArm", (0.26, 0, 0)),
    ("LeftHand", "LeftForeArm", (0.24, 0, 0)),
    ("RightShoulder", "Spine2", (-0.08, 0, 0)),
    ("RightArm", "RightShoulder", (-0.14, 0, 0)),
    ("RightForeArm", "RightArm", (-0.26, 0, 0)),
    ("RightHand", "RightForeArm", (-0.24, 0, 0)),
    ("LeftUpLeg", "Hips", (0.10, 0, 0)),
    ("LeftLeg", "LeftUpLeg", (0, 0, -0.42)),
    ("LeftFoot", "LeftLeg", (0, 0, -0.40)),
    ("RightUpLeg", "Hips", (-0.10, 0, 0)),
    ("RightLeg", "RightUpLeg", (0, 0, -0.42)),
    ("RightFoot", "RightLeg", (0, 0, -0.40)),
]


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def make_grid_image(name: str, size: int = 512) -> bpy.types.Image:
    img = bpy.data.images.new(name, width=size, height=size, alpha=False)
    pixels = [0.0] * (size * size * 4)
    bg = (0.78, 0.78, 0.76)
    line = (0.08, 0.08, 0.10)
    n_m, n_p = 12, 14
    for y in range(size):
        for x in range(size):
            i = (y * size + x) * 4
            on = False
            for k in range(n_m + 1):
                cx = int(k * (size - 1) / n_m)
                thick = 2 if k in (0, n_m // 2, n_m) else 1
                if abs(x - cx) <= thick:
                    on = True
            for k in range(n_p + 1):
                cy = int(k * (size - 1) / n_p)
                thick = 2 if k in (0, n_p // 2, n_p) else 1
                if abs(y - cy) <= thick:
                    on = True
            c = line if on else bg
            pixels[i : i + 4] = [c[0], c[1], c[2], 1.0]
    img.pixels = pixels
    img.file_format = "PNG"
    os.makedirs(OUT_DIR, exist_ok=True)
    img.filepath_raw = os.path.join(OUT_DIR, "_bodygrid.png")
    img.save()
    img.pack()
    return img


def make_material(img: bpy.types.Image, name: str) -> bpy.types.Material:
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    tex.interpolation = "Linear"
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.72
    bsdf.inputs["Metallic"].default_value = 0.02
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.2
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def make_joint_mat() -> bpy.types.Material:
    mat = bpy.data.materials.new("JointMat")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.42, 0.42, 0.40, 1)
        bsdf.inputs["Roughness"].default_value = 0.45
        bsdf.inputs["Metallic"].default_value = 0.18
    return mat


def add_uv_sphere(radius: float, loc, segs=32) -> bpy.types.Object:
    bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, segments=segs, ring_count=max(16, segs // 2), location=loc)
    obj = bpy.context.active_object
    bpy.ops.object.shade_smooth()
    return obj


def add_cylinder(r_top, r_bot, depth, loc, rot=(0, 0, 0), verts=32) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cone_add(
        radius1=r_bot, radius2=r_top, depth=depth, vertices=verts, location=loc
    )
    obj = bpy.context.active_object
    obj.rotation_euler = rot
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
    bpy.ops.object.shade_smooth()
    return obj


def assign_mat(obj, mat):
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)


def parent_keep(child, parent):
    child.parent = parent
    child.matrix_parent_inverse.identity()


def bone_empty(name, parent, local):
    bpy.ops.object.empty_add(type="PLAIN_AXES", location=(0, 0, 0))
    e = bpy.context.active_object
    e.name = name
    e.empty_display_size = 0.04
    if parent:
        e.parent = parent
        e.location = Vector(local)
    else:
        e.location = Vector(local)
    return e


def build_figure(kind: str, grid_mat, joint_mat):
    """kind: kun | chan. Blender Z-up; we rotate to Y-up on export via glTF."""
    female = kind == "chan"
    # proportions (meters, Z-up)
    hips_z = 0.86 if female else 0.92
    shoulder_w = 0.34 if female else 0.44
    chest_r = 0.13 if female else 0.16
    waist_r = 0.10 if female else 0.12
    pelvis_r = 0.13 if female else 0.14
    if female:
        pelvis_r = 0.145
    arm_r = 0.038 if female else 0.048
    fore_r = 0.032 if female else 0.040
    thigh_r = 0.055 if female else 0.068
    shin_r = 0.042 if female else 0.052
    head_r = 0.105 if female else 0.112
    upper_arm = 0.24 if female else 0.26
    forearm = 0.22 if female else 0.24
    thigh_len = 0.40 if female else 0.42
    shin_len = 0.38 if female else 0.40

    nodes = {}
    # Hips at world
    nodes["Hips"] = bone_empty("Hips", None, (0, 0, hips_z))
    nodes["Spine"] = bone_empty("Spine", nodes["Hips"], (0, 0, 0.09))
    nodes["Spine1"] = bone_empty("Spine1", nodes["Spine"], (0, 0, 0.11))
    nodes["Spine2"] = bone_empty("Spine2", nodes["Spine1"], (0, 0, 0.13))
    nodes["Neck"] = bone_empty("Neck", nodes["Spine2"], (0, 0, 0.14))
    nodes["Head"] = bone_empty("Head", nodes["Neck"], (0, 0, 0.07))

    sx = shoulder_w / 2
    # 手臂沿 -Z 下垂（导出 glTF Y-up 后为 -Y），对齐胶囊素模 rest pose
    nodes["LeftShoulder"] = bone_empty("LeftShoulder", nodes["Spine2"], (sx * 0.72, -0.02, 0.08))
    nodes["LeftArm"] = bone_empty("LeftArm", nodes["LeftShoulder"], (sx * 0.22, 0, -0.02))
    nodes["LeftForeArm"] = bone_empty("LeftForeArm", nodes["LeftArm"], (0, 0, -upper_arm))
    nodes["LeftHand"] = bone_empty("LeftHand", nodes["LeftForeArm"], (0, 0, -forearm))
    nodes["RightShoulder"] = bone_empty("RightShoulder", nodes["Spine2"], (-sx * 0.72, -0.02, 0.08))
    nodes["RightArm"] = bone_empty("RightArm", nodes["RightShoulder"], (-sx * 0.22, 0, -0.02))
    nodes["RightForeArm"] = bone_empty("RightForeArm", nodes["RightArm"], (0, 0, -upper_arm))
    nodes["RightHand"] = bone_empty("RightHand", nodes["RightForeArm"], (0, 0, -forearm))

    hx = 0.11 if female else 0.10
    nodes["LeftUpLeg"] = bone_empty("LeftUpLeg", nodes["Hips"], (hx, 0, 0))
    nodes["LeftLeg"] = bone_empty("LeftLeg", nodes["LeftUpLeg"], (0, 0, -thigh_len))
    nodes["LeftFoot"] = bone_empty("LeftFoot", nodes["LeftLeg"], (0, 0.04, -shin_len))
    nodes["RightUpLeg"] = bone_empty("RightUpLeg", nodes["Hips"], (-hx, 0, 0))
    nodes["RightLeg"] = bone_empty("RightLeg", nodes["RightUpLeg"], (0, 0, -thigh_len))
    nodes["RightFoot"] = bone_empty("RightFoot", nodes["RightLeg"], (0, 0.04, -shin_len))

    def part_sphere(parent, r, loc=(0, 0, 0), segs=32, scale=(1.0, 1.0, 1.0)):
        obj = add_uv_sphere(r, (0, 0, 0), segs)
        assign_mat(obj, grid_mat)
        parent_keep(obj, parent)
        obj.location = Vector(loc)
        obj.scale = Vector(scale)
        return obj

    def part_cyl(parent, r0, r1, length, axis="z"):
        gap = 0.028
        usable = max(0.06, length - gap)
        loc = (0, 0, usable / 2)
        rot = (0, 0, 0)
        if axis == "x+":
            rot = (0, math.pi / 2, 0)
            loc = (usable / 2, 0, 0)
        elif axis == "x-":
            rot = (0, -math.pi / 2, 0)
            loc = (-usable / 2, 0, 0)
        elif axis == "z-":
            rot = (math.pi, 0, 0)
            loc = (0, 0, -usable / 2)
        obj = add_cylinder(r0, r1, usable, (0, 0, 0), rot, verts=32)
        assign_mat(obj, grid_mat)
        parent_keep(obj, parent)
        obj.location = Vector(loc)
        return obj

    def joint(parent, r):
        obj = add_uv_sphere(r, (0, 0, 0), 24)
        assign_mat(obj, joint_mat)
        parent_keep(obj, parent)
        obj.location = Vector((0, 0, 0))
        return obj

    # pelvis + abdomen + chest（圆润体积，不要横杆）
    part_sphere(nodes["Hips"], pelvis_r, (0, -0.01, -0.02), 32, (1.05, 0.82, 0.9) if female else (1.0, 0.78, 0.88))
    part_cyl(nodes["Spine"], waist_r * (0.92 if female else 1.0), pelvis_r * 0.62, 0.11, "z")
    part_cyl(nodes["Spine1"], chest_r * 0.78, waist_r * (0.95 if female else 1.02), 0.13, "z")
    part_cyl(nodes["Spine2"], chest_r * 0.62, chest_r, 0.16, "z")
    if female:
        part_sphere(nodes["Spine2"], chest_r * 0.52, (0.05, -0.07, 0.01), 28, (1.05, 0.88, 1.12))
        part_sphere(nodes["Spine2"], chest_r * 0.52, (-0.05, -0.07, 0.01), 28, (1.05, 0.88, 1.12))
    else:
        part_sphere(nodes["Spine2"], chest_r * 0.48, (0.055, -0.05, 0.02), 28, (1.15, 0.7, 0.85))
        part_sphere(nodes["Spine2"], chest_r * 0.48, (-0.055, -0.05, 0.02), 28, (1.15, 0.7, 0.85))
    # 三角肌，替代肩杠
    part_sphere(nodes["LeftShoulder"], 0.052 if female else 0.062, (0.02, -0.01, 0.0), 24)
    part_sphere(nodes["RightShoulder"], 0.052 if female else 0.062, (-0.02, -0.01, 0.0), 24)

    joint(nodes["Hips"], 0.058)
    joint(nodes["Spine"], 0.05)
    joint(nodes["Spine2"], 0.052)
    joint(nodes["Neck"], 0.044)

    part_cyl(nodes["Neck"], 0.046, 0.04, 0.07, "z")
    part_sphere(nodes["Head"], head_r, (0, -0.01, head_r * 0.78), 32, (0.92, 0.88, 1.14))

    for side in ("Left", "Right"):
        joint(nodes[f"{side}Shoulder"], 0.052)
        part_cyl(nodes[f"{side}Arm"], arm_r * 1.05, arm_r * 0.9, upper_arm, "z-")
        joint(nodes[f"{side}ForeArm"], 0.044)
        part_cyl(nodes[f"{side}ForeArm"], arm_r * 0.82, fore_r, forearm, "z-")
        joint(nodes[f"{side}Hand"], 0.034)
        part_sphere(nodes[f"{side}Hand"], 0.04 if female else 0.044, (0, -0.012, -0.032), 20, (0.85, 0.7, 1.25))

    for side in ("Left", "Right"):
        joint(nodes[f"{side}UpLeg"], 0.06)
        part_cyl(nodes[f"{side}UpLeg"], thigh_r, thigh_r * 0.8, thigh_len, "z-")
        joint(nodes[f"{side}Leg"], 0.05)
        part_cyl(nodes[f"{side}Leg"], shin_r * 1.02, shin_r * 0.76, shin_len, "z-")
        joint(nodes[f"{side}Foot"], 0.04)
        part_sphere(nodes[f"{side}Foot"], 0.048, (0, 0.055, -0.018), 20, (0.7, 1.65, 0.52))

    # root wrapper
    bpy.ops.object.empty_add(type="PLAIN_AXES", location=(0, 0, 0))
    root = bpy.context.active_object
    root.name = "BodyKun" if kind == "kun" else "BodyChan"
    nodes["Hips"].parent = root
    return root


def export_glb(root, path):
    bpy.ops.object.select_all(action="DESELECT")
    root.select_set(True)
    for obj in bpy.data.objects:
        if obj.parent:
            obj.select_set(True)
        p = obj.parent
        while p:
            if p == root:
                obj.select_set(True)
                break
            p = p.parent
    bpy.context.view_layer.objects.active = root
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=path,
        export_format="GLB",
        use_selection=True,
        export_apply=True,
        export_yup=True,
        export_extras=False,
        export_cameras=False,
        export_lights=False,
        export_skins=False,
        export_animations=False,
    )


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    img = make_grid_image("BodyGrid")
    grid_mat = make_material(img, "BodyGridMat")
    joint_mat = make_joint_mat()

    for kind, fname in (("kun", "bodykun.glb"), ("chan", "bodychan.glb")):
        reset_scene()
        # recreate materials after factory reset
        img = make_grid_image("BodyGrid")
        grid_mat = make_material(img, "BodyGridMat")
        joint_mat = make_joint_mat()
        root = build_figure(kind, grid_mat, joint_mat)
        out = os.path.join(OUT_DIR, fname)
        export_glb(root, out)
        print("WROTE", out, "size", os.path.getsize(out) if os.path.isfile(out) else 0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback

        traceback.print_exc()
        sys.exit(1)
