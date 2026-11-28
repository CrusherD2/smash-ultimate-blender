"""Line Up: a source that stands bigger, turned and elsewhere gets flagged, and Line Up Source fixes it via an offset."""
from math import radians
from pathlib import Path

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text(encoding='utf-8').split('floor = importlib.import_module')[0], str(fixture), 'exec'))
from mathutils import Euler, Vector

retarget = importlib.import_module(MODULE + '.source.retargeting')
alignment = importlib.import_module(MODULE + '.source.retargeting.alignment')
scene = bpy.context.scene

HUMAN = {  # name: (head, tail, parent); faces -Y, right side at -X
    'Hips': ((0, 0, 1), (0, 0, 1.2), None), 'Spine': ((0, 0, 1.2), (0, 0, 1.5), 'Hips'),
    'Head': ((0, 0, 1.6), (0, 0, 1.8), 'Spine'),
    'ArmR': ((-0.2, 0, 1.45), (-0.5, 0, 1.45), 'Spine'), 'ArmL': ((0.2, 0, 1.45), (0.5, 0, 1.45), 'Spine'),
    'LegR': ((-0.1, 0, 1), (-0.1, 0, 0.05), 'Hips'), 'LegL': ((0.1, 0, 1), (0.1, 0, 0.05), 'Hips'),
    'Toe': ((0, -0.1, 0.05), (0, -0.2, 0), 'Hips'),
}


def make(name, rename=lambda n: n):
    data = bpy.data.armatures.new(name)
    ob = bpy.data.objects.new(name, data)
    scene.collection.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode='EDIT')
    for bone, (head, tail, parent) in HUMAN.items():
        b = data.edit_bones.new(rename(bone))
        b.head, b.tail = head, tail
        if parent:
            b.parent = data.edit_bones[rename(parent)]
    bpy.ops.object.mode_set(mode='OBJECT')
    return ob


def mixamo(n):
    return 'mixamorig:' + {'ArmR': 'RightArm', 'ArmL': 'LeftArm', 'LegR': 'RightUpLeg', 'LegL': 'LeftUpLeg'}.get(n, n)


target = make('Target')
source = make('Source', mixamo)
assert not alignment.issues(source, target), alignment.issues(source, target)
# Side detection: names, not just mapping; "Shoulder" style endings must not read as right.
assert alignment._sides(source) == (['mixamorig:RightArm', 'mixamorig:RightUpLeg'], ['mixamorig:LeftArm', 'mixamorig:LeftUpLeg'])
assert alignment._RIGHT.search('ShoulderL') is None and alignment._RIGHT.search('ArmR')

# FBX-style source: 100x scale, turned to face +X, standing elsewhere.
source.scale = (100, 100, 100)
source.rotation_euler = Euler((0, 0, radians(90)))
source.location = (3, 1, 0)
bpy.context.view_layer.update()
kinds = {kind for kind, _ in alignment.issues(source, target)}
assert kinds == {'SCALE', 'ROTATION', 'LOCATION'}, kinds

scene.expykit_bind_to = source
scene.sub_retarget_apply_to = target
driver, receiver = source, target
assert retarget.alignment_state(bpy.context, driver, receiver) == 'off'
title, _, button = retarget.next_step(bpy.context, driver, receiver)
assert button[0] == 'sub.retarget_line_up', (title, button)
assert retarget.retarget_step_states(bpy.context, driver, receiver)['align'] == ('current', 'check')

# Line Up Source opens the offset pre-filled, which already lines the pair up.
bpy.context.preferences.view.smooth_view = 0
assert bpy.ops.sub.retarget_line_up() == {'FINISHED'}
view = next(area.spaces.active.region_3d for area in bpy.context.screen.areas if area.type == 'VIEW_3D')
assert view.view_perspective == 'ORTHO'
assert ((view.view_rotation @ Vector((0, 0, 1))) - Vector((0, -1, 0))).length < 1e-5

assert alignment.offset_open(scene) and source.parent == scene.expykit_offset.container
assert retarget.alignment_state(bpy.context, driver, receiver) == 'open'
assert retarget.next_step(bpy.context, driver, receiver)[2][0] == 'object.expykit_apply_offset'
assert abs(scene.expykit_offset.scale - 0.01) < 1e-4, scene.expykit_offset.scale
bpy.context.view_layer.update()
assert not alignment.issues(source, target), alignment.issues(source, target)
head = source.matrix_world @ source.data.bones['mixamorig:Head'].head_local
assert (head - Vector((0, 0, 1.6))).length < 1e-3, head
right = source.matrix_world @ source.data.bones['mixamorig:RightArm'].head_local
assert (right - Vector((-0.2, 0, 1.45))).length < 1e-3, right
assert bpy.ops.object.expykit_apply_offset() == {'FINISHED'}
assert retarget.alignment_state(bpy.context, driver, receiver) == 'ok'
assert retarget.retarget_step_states(bpy.context, driver, receiver)['align'][0] == 'done'
assert retarget.next_step(bpy.context, driver, receiver)[0] == 'Map the bones'

# A flagged pair can be kept as is, and stays kept.
source.location.x += 50
bpy.context.view_layer.update()
assert retarget.alignment_state(bpy.context, driver, receiver) == 'off'
assert bpy.ops.sub.retarget_accept_alignment() == {'FINISHED'}
assert retarget.alignment_state(bpy.context, driver, receiver) == 'ok'
print('RETARGET_ALIGNMENT_OK')
