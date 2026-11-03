"""VIS shape groups keep world transforms and stay visible to model mesh walks."""
import importlib
from pathlib import Path

import bpy
from mathutils import Vector

fixture = Path(__file__).with_name("test_addon_registration_blender.py")
exec(compile(fixture.read_text().split("addon_utils.disable(MODULE")[0], str(fixture), "exec"))
groups = importlib.import_module(MODULE + ".source.model.vis_shape_groups")


def add_mesh(armature, name, location):
    mesh = bpy.data.meshes.new(name)
    mesh.vertices.add(1)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = armature
    obj.location = location
    return obj


arm = bpy.data.objects.new("smush_blender_import", bpy.data.armatures.new("smush_blender_import"))
bpy.context.scene.collection.objects.link(arm)
arm.location = (2.0, -1.0, 0.5)
arm.rotation_mode = "XYZ"
arm.rotation_euler = (0.2, -0.4, 0.8)
angry = [
    add_mesh(arm, "baseform_Angry_VIS_O_OBJShape", Vector((0.4, 0.1, -0.2))),
    add_mesh(arm, "baseform_Angry_VIS_O_OBJShape", Vector((-0.3, 0.5, 0.2))),
    add_mesh(arm, "baseform_Angry_VIS_O_OBJShape", Vector((0.0, -0.2, 0.7))),
]
single = add_mesh(arm, "angelHalo_VIS_O_OBJShape", Vector((1.0, 0.0, 0.0)))
body = add_mesh(arm, "c00BodyShape", Vector((0.0, 0.0, 1.0)))
bpy.context.view_layer.update()
before = {obj.name: obj.matrix_world.copy() for obj in angry + [single, body]}

summary = groups.group_vis_shapes(arm, bpy.context)
assert summary == {"groups": 1, "meshes": 3}, summary
empty = next(child for child in arm.children if child.type == "EMPTY")
assert empty.name == "baseform_Angry", empty.name
assert empty.parent == arm
assert empty.get(groups.VIS_GROUP_ID) == "baseform_Angry"
assert tuple(empty.lock_location) == (True, True, True)
for obj in angry:
    assert obj.parent == empty, obj.name
    delta = (obj.matrix_world.translation - before[obj.name].translation).length
    assert delta < 1e-5, (obj.name, delta)
assert single.parent == arm and body.parent == arm
assert {obj.name for obj in groups.iter_model_meshes(arm)} == {obj.name for obj in angry + [single, body]}

again = groups.group_vis_shapes(arm, bpy.context)
assert again == {"groups": 1, "meshes": 3}, again
assert sum(1 for child in arm.children if child.type == "EMPTY") == 1

bpy.context.view_layer.objects.active = arm
assert bpy.ops.sub.ungroup_vis_shapes() == {"FINISHED"}
assert not any(child.type == "EMPTY" for child in arm.children)
for obj in angry + [single, body]:
    assert obj.parent == arm, obj.name
    delta = (obj.matrix_world.translation - before[obj.name].translation).length
    assert delta < 1e-5, (obj.name, delta)

addon_utils.disable(MODULE, default_set=False, handle_error=on_error)
assert not errors, errors
print("VIS SHAPE GROUPS PASSED")
