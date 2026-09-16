"""Reverse-foot pivot regression, with optional SUB_FOOT_FIXTURE .blend."""
from pathlib import Path
import os
fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
from mathutils import Matrix, Vector
channels = importlib.import_module(MODULE + '.source.extras.ik_channels')
source = os.environ.get('SUB_FOOT_FIXTURE')
if source:
    with bpy.data.libraries.load(source, link=False) as (src, dst):
        dst.objects = src.objects
    arm = next(obj for obj in dst.objects if obj and obj.type == 'ARMATURE'
               and 'FootL' in obj.pose.bones)
    bpy.context.collection.objects.link(arm)
else:
    data = bpy.data.armatures.new('Reverse foot')
    arm = bpy.data.objects.new('Reverse foot', data)
    bpy.context.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    for side, x in [('L', 1), ('R', -1)]:
        parent = None
        for name, head, tail in [
            ('Leg', (x, 0, 4), (x, -.2, 2.5)),
            ('Knee', (x, -.2, 2.5), (x, 0, 1)),
            ('Foot', (x, 0, 1), (x, 0, .2)),
            ('Toe', (x, -.2, .2), (x, -1, .2)),
            ('ToeTip', (x, -1, .2), (x, -1.3, .2)),
        ]:
            bone = data.edit_bones.new(name + side)
            bone.head, bone.tail, bone.parent = head, tail, parent
            bone.use_connect = False
            parent = bone
        target = data.edit_bones.new('FootIK' + side)
        target.head, target.tail = (x, 0, 1), (x, 0, 2)
        pole = data.edit_bones.new('KneeIK' + side)
        pole.head, pole.tail = (x, -2, 2), (x, -2, 2.5)
    bpy.ops.object.mode_set(mode='OBJECT')

bpy.context.view_layer.objects.active = arm
arm.select_set(True)
arm.animation_data_clear()
arm.data.animation_data_clear()
for bone in arm.pose.bones:
    bone.matrix_basis = Matrix.Identity(4)
if not list(channels.chains(arm, 'LEGS')):
    channels.create_controls(bpy.context, arm, 'LEGS')
channels.ensure(arm, bpy.context, 'LEGS')
for side in 'LR':
    terminal = channels.toe_pivot_name(arm, ('Leg' + side, 'Knee' + side, 'Foot' + side))
    if not source:
        assert terminal == 'ToeTip' + side
    elif Path(source).name == 'sceptile_fliip.blend':
        assert terminal == 'BaseToe' + side
    if terminal != 'Toe' + side:
        # Simulate an older rig still driving the root toe, then upgrade it.
        old = (arm.pose.bones['Toe' + side].constraints.get(channels.TOE_OUTPUT)
               or arm.pose.bones['Toe' + side].constraints.new('COPY_ROTATION'))
        old.name = channels.TOE_OUTPUT
        old.target, old.subtarget = arm, 'ToeIK' + side
channels.ensure(arm, bpy.context, 'LEGS')
for side in 'LR':
    terminal = channels.toe_pivot_name(arm, ('Leg' + side, 'Knee' + side, 'Foot' + side))
    assert arm.pose.bones[terminal].constraints.get(channels.TOE_OUTPUT)
    if terminal != 'Toe' + side:
        assert arm.pose.bones['Toe' + side].constraints[channels.TOE_OUTPUT].subtarget == channels.PREFIX + 'ToeBasis' + side
channels.match(bpy.context, arm, 'LEGS', entire=False, key=False)
arm.data.sub_use_ik_legs = 1
# Unlimited reach isolates reverse-foot geometry from leg reach limitations.
arm.data.sub_ik_stretch_legs = True

def snapshot():
    arm.update_tag()
    bpy.context.view_layer.update()
    evaluated = arm.evaluated_get(bpy.context.evaluated_depsgraph_get())
    return {b.name: b.matrix.copy() for b in evaluated.pose.bones}

baseline = snapshot()
for side in 'LR':
    roll = arm.pose.bones['FootRollIK' + side]
    for axis in range(3):
        for angle in (-.6, -.2, .2, .6):
            roll.rotation_euler[axis] = angle
            pose = snapshot()
            for name in (channels.toe_pivot_name(arm, ('Leg' + side, 'Knee' + side, 'Foot' + side)),):
                if name not in baseline:
                    continue
                error = max(abs(pose[name][i][j] - baseline[name][i][j])
                            for i in range(4) for j in range(4))
                assert error < 2e-4, (side, axis, angle, name, error)
            roll.rotation_euler[axis] = 0
    articulation = channels.toe_articulation(arm, ('Leg' + side, 'Knee' + side, 'Foot' + side))
    if articulation:
        bend = arm.pose.bones[articulation[0]]
        terminal = channels.toe_pivot_name(arm, ('Leg' + side, 'Knee' + side, 'Foot' + side))
        for roll_angle in (0, .35):
            roll.rotation_euler.x = roll_angle
            planted = snapshot()
            for axis in range(3):
                bend.rotation_euler[axis] = .3
                pose = snapshot()
                for name in (articulation[2], terminal):
                    assert max(abs(pose[name][i][j] - planted[name][i][j])
                               for i in range(4) for j in range(4)) < 2e-4, ('articulation anchor', name, axis)
                assert max(abs(pose['Foot' + side][i][j] - planted['Foot' + side][i][j])
                           for i in range(3) for j in range(3)) > .05, 'foot must articulate'
                bend.rotation_euler[axis] = 0
            roll.rotation_euler.x = 0
    # A regular curl still changes toe orientation independently.
    toe_control = arm.pose.bones['ToeIK' + side]
    toe_control.rotation_euler.x += .2
    pose = snapshot()
    assert (pose['Foot' + side].translation - baseline['Foot' + side].translation).length < 2e-4
    toe_control.rotation_euler.x -= .2

# Repair remains idempotent and does not add animation curves.
rest = {b.name: b.matrix_local.copy() for b in arm.data.bones}
channels.ensure(arm, bpy.context, 'LEGS')
for name, matrix in rest.items():
    assert max(abs(arm.data.bones[name].matrix_local[i][j] - matrix[i][j])
               for i in range(4) for j in range(4)) < 1e-6
# Control creation may create the initial IK mode key.
# Keyed matching includes the articulation control/seed; bake/remove preserves
# a combined heel lift + proximal bend on the original deform hierarchy.
channels.match(bpy.context, arm, 'LEGS', entire=False, key=True)
for side in 'LR':
    arm.pose.bones['FootRollIK' + side].rotation_euler.x = .25
    articulation = channels.toe_articulation(arm, ('Leg' + side, 'Knee' + side, 'Foot' + side))
    if articulation:
        arm.pose.bones[articulation[0]].rotation_euler.z = .3
    for name in ('FootRollIK' + side, *((articulation[0],) if articulation else ())):
        arm.pose.bones[name].keyframe_insert('rotation_euler', frame=bpy.context.scene.frame_current)
expected = snapshot()
rig = importlib.import_module(MODULE + '.source.extras.create_animation_rig')
names = list(rig._ik_driven_fk_bone_names(arm, 'LEGS'))
frame = bpy.context.scene.frame_current
channels.bake(bpy.context, arm, names, frame, frame)
channels.remove(bpy.context, arm, 'LEGS')
actual = snapshot()
for name in names:
    assert max(abs(actual[name][i][j] - expected[name][i][j])
               for i in range(4) for j in range(4)) < .005, ('bake articulation', name)
assert not any(n.startswith(('ToeBendIK', channels.PREFIX + 'ToeBasis')) for n in arm.pose.bones.keys())
print('REVERSE FOOT PIVOTS PASSED:', source or 'synthetic, reversed IK axes and toe descendants')
