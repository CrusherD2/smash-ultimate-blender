"""New IK hand/foot controls follow the bone they drive and leave the FK pose unchanged."""
from pathlib import Path

from mathutils import Euler

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('floor = importlib.import_module')[0], str(fixture), 'exec'))
ikc = importlib.import_module(MODULE + '.source.extras.ik_channels')

scene = bpy.context.scene
data = bpy.data.armatures.new('Rig')
arm = bpy.data.objects.new('Rig', data)
scene.collection.objects.link(arm)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode='EDIT')
chains = (
    ('Trans', None, (0, 0, 0), (0, 0, 1), 0.0),
    ('LegL', 'Trans', (1, 0, 10), (1, 0.4, 5), 0.0),
    ('KneeL', 'LegL', (1, 0.4, 5), (1, 0, 1), 0.0),
    ('FootL', 'KneeL', (1, 0, 1), (1, -2, 0), 0.3),
    ('ShoulderL', 'Trans', (1, 0, 15), (4, 0, 15), 0.0),
    ('ArmL', 'ShoulderL', (4, 0, 15), (7, 0.2, 15), 0.0),
    ('HandL', 'ArmL', (7, 0.2, 15), (8, 0.2, 15), 1.2),
)
for name, parent, head, tail, roll in chains:
    bone = data.edit_bones.new(name)
    bone.head, bone.tail, bone.roll = head, tail, roll
    if parent:
        bone.parent = data.edit_bones[parent]
        bone.use_connect = name in ('KneeL', 'FootL', 'ArmL', 'HandL')
bpy.ops.object.mode_set(mode='POSE')
for name, rot in (('LegL', (0.3, 0, 0.1)), ('KneeL', (-0.5, 0, 0)), ('ArmL', (0, 0.4, 0.3)), ('HandL', (0.2, 0.1, 0))):
    arm.pose.bones[name].rotation_mode = 'XYZ'
    arm.pose.bones[name].rotation_euler = Euler(rot)
bpy.context.view_layer.update()
before = {n: arm.pose.bones[n].matrix.copy() for n in ('FootL', 'HandL')}

assert ikc.create_controls(bpy.context, arm, 'BOTH') == 2
for control, source in (('FootIKL', 'FootL'), ('HandIKL', 'HandL')):
    c, s = data.bones[control], data.bones[source]
    assert (c.head_local - s.head_local).length < 1e-5
    for axis in range(3):
        assert (c.matrix_local.col[axis].xyz - s.matrix_local.col[axis].xyz).length < 1e-4, (control, axis)
    assert abs(c.length - s.length * 2.0) < 1e-4, (control, c.length)
bpy.context.view_layer.update()
# Matching seeds each control from the FK pose it replaces.
for control, source in (('FootIKL', 'FootL'), ('HandIKL', 'HandL')):
    seeded = arm.pose.bones[control].matrix.to_3x3()
    fk = before[source].to_3x3()
    assert max(abs(seeded[r][c] - fk[r][c]) for r in range(3) for c in range(3)) < 1e-3, control
bpy.data.objects.remove(arm)
print('IK_CONTROL_ORIENTATION_OK')
