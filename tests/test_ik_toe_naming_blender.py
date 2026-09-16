"""Toe chains with non-default names, and the off-mode bone visibility toggle.

Run with Blender --background --factory-startup --python-exit-code 1 --python this_file.
"""
from pathlib import Path
import importlib

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))

ik = importlib.import_module(MODULE + '.source.extras.ik_channels')
rig = importlib.import_module(MODULE + '.source.extras.create_animation_rig')

NAMES = ('LegL', 'UpperOffsetL', 'KneeL', 'LowerOffsetL', 'FootL')
POINTS = [(0, 0, 4), (0, -.2, 3), (0, -.4, 2), (0, -.2, 1), (0, 0, 0), (0, 1, 0)]
CHAIN = ('LegL', 'KneeL', 'FootL')


def build_leg(toe_names):
    """A leg whose toe hierarchy uses the given bone names, in order."""
    bpy.ops.object.armature_add()
    obj = bpy.context.object
    bpy.ops.object.mode_set(mode='EDIT')
    bones = obj.data.edit_bones
    bones.remove(bones[0])
    parent = None
    for index, name in enumerate(NAMES):
        bone = bones.new(name)
        bone.head, bone.tail = POINTS[index], POINTS[index + 1]
        bone.parent = parent
        bone.use_connect = parent is not None
        parent = bone
    for index, name in enumerate(toe_names):
        toe = bones.new(name)
        toe.head = (0, 1 + index * .3, 0)
        toe.tail = (0, 1.3 + index * .3, 0)
        toe.parent = parent
        parent = toe
    bpy.ops.object.mode_set(mode='OBJECT')
    return obj


def discard(obj):
    if obj.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.data.objects.remove(obj, do_unlink=True)


# A plain ToeL still resolves to itself, with no separate articulation control.
obj = build_leg(['ToeL'])
assert ik.connected_toe_bones(obj, CHAIN) == ('ToeL',)
assert ik.toe_pivot_name(obj, CHAIN) == 'ToeL'
assert ik.foot_controls(CHAIN, obj) == ('FootRollIKL', 'ToeIKL', ik.PREFIX + 'FootTargetL', 'ToeL')
assert ik.toe_articulation(obj, CHAIN) is None
discard(obj)

# Split toes have no bone called exactly ToeL, so the hierarchy has to find them.
obj = build_leg(['Toe1L', 'Toe2L'])
assert ik.connected_toe_bones(obj, CHAIN) == ('Toe1L', 'Toe2L')
assert ik.toe_pivot_name(obj, CHAIN) == 'Toe2L', 'the foot rolls over the deepest toe'
assert ik.foot_controls(CHAIN, obj)[3] == 'Toe2L'
assert ik.toe_articulation(obj, CHAIN) == ('ToeBendIKL', ik.PREFIX + 'ToeBasisL', 'Toe1L')

# The foot roll and toe controls must actually be built for such a rig.
assert ik.create_controls(bpy.context, obj, 'LEGS') == 1
controls = rig._ik_control_bone_names(obj, 'LEGS')
assert {'FootRollIKL', 'ToeIKL', 'ToeBendIKL'} <= set(controls), controls

# Hiding follows the mode: FK bones go while the leg is in IK...
fk_names, ik_names = rig._off_mode_bone_names(obj, 'LEGS')
assert 'Toe2L' in fk_names and 'FootRollIKL' in ik_names
assert rig.off_mode_hiding_enabled(obj)
assert all(obj.data.bones[name].hide for name in ('LegL', 'KneeL', 'FootL'))
assert not any(obj.data.bones[name].hide for name in ik_names)

# ...the toggle brings everything back...
assert bpy.ops.sub.toggle_off_mode_bones() == {'FINISHED'}
assert not rig.off_mode_hiding_enabled(obj)
assert not any(obj.data.bones[name].hide for name in (*fk_names, *ik_names))

# ...and the automatic mode sync must not quietly re-hide them.
rig._set_ik_bone_visibility(obj, True, 'LEGS')
assert not any(obj.data.bones[name].hide for name in fk_names)

# Switching back to FK hides the IK controls instead of the FK bones.
assert bpy.ops.sub.toggle_off_mode_bones() == {'FINISHED'}
assert rig.off_mode_hiding_enabled(obj)
obj.data.sub_use_ik_legs = 0.0
bpy.context.view_layer.update()
rig.set_off_mode_bones_hidden(obj, True, 'LEGS')
assert all(obj.data.bones[name].hide for name in ik_names)
assert not any(obj.data.bones[name].hide for name in ('LegL', 'KneeL', 'FootL'))
discard(obj)

addon_utils.disable(MODULE, default_set=False, handle_error=on_error)
assert not errors, errors
print('TOE NAMING AND OFF-MODE VISIBILITY PASSED')
profile.cleanup()
