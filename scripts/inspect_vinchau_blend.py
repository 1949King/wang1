"""Inspect vinchau BodyChan/BodyKun .blend: objects, armatures, bone names."""
import bpy
import os

SRC = r"c:\Users\Administrator\Downloads\BodyChan - BodyKun  Posable Drawing Figures.blend"

bpy.ops.wm.open_mainfile(filepath=SRC)

print("=== OBJECTS ===")
for obj in bpy.data.objects:
    loc = tuple(round(v, 3) for v in obj.location)
    print(f"  {obj.type:10} {obj.name!r:40} parent={obj.parent.name if obj.parent else None} loc={loc}")

print("\n=== ARMATURES / BONES ===")
for arm in bpy.data.armatures:
    print(f"\nARM {arm.name} bones={len(arm.bones)}")
    for b in arm.bones:
        if b.parent is None or any(k in b.name.lower() for k in (
            "hip", "spine", "chest", "neck", "head", "shoulder", "upper_arm",
            "forearm", "hand", "thigh", "shin", "foot", "upleg", "arm", "leg",
            "torso", "pelvis", "DEF-", "ORG-", "MCH-",
        )):
            print(f"  {b.name}  parent={b.parent.name if b.parent else '-'}  head={tuple(round(x,3) for x in b.head_local)}")

print("\n=== MESHES ===")
for me in bpy.data.meshes:
    print(f"  {me.name} verts={len(me.vertices)} polys={len(me.polygons)}")

print("\n=== MATERIALS ===")
for mat in bpy.data.materials:
    print(f"  {mat.name}")
