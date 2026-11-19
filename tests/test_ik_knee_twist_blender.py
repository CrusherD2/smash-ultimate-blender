from pathlib import Path

import importlib
import math
from mathutils import Euler, Quaternion, Vector

def pose_hidden(pb):
    return pb.hide if hasattr(pb, 'hide') else pb.bone.hide

fixture = Path(__file__).with_name('test_ik_detail_acceleration_blender.py')
exec(compile(fixture.read_text().split('\naudit()\nfor repeat')[0], str(fixture), 'exec'))
rig = importlib.import_module(MODULE + '.source.extras.create_animation_rig')
scene.frame_set(8)
names = ('LegL', 'KneeL', 'FootL', 'LegR', 'KneeR', 'FootR')

def snapshot():
    obj.update_tag()
    bpy.context.view_layer.update()
    ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    return {name: ev.pose.bones[name].matrix.copy() for name in names}

def error(a, b):
    return max(abs(a[r][c] - b[r][c]) for r in range(4) for c in range(4))

def set_rotation(pole, rotation, mode):
    pole.rotation_mode = mode
    if mode == 'QUATERNION':
        pole.rotation_quaternion = rotation
    elif mode == 'AXIS_ANGLE':
        axis, angle = rotation.to_axis_angle()
        pole.rotation_axis_angle = (angle, *axis)
    else:
        pole.rotation_euler = rotation.to_euler(mode)

pole = obj.pose.bones['KneeIKL']
checks = Path(__file__).with_name('ik_pull_rotation_checks.py')
exec(compile(checks.read_text(), str(checks), 'exec'))
check_rotation_influences(obj, ik, ('Leg', 'Knee', 'Foot'), 'KneeIK')
rotation = Euler((0.4, -0.5, 0.7)).to_quaternion()

old = obj.pose.bones[ik.PULL_PREFIX + 'LegL'].constraints.new('COPY_ROTATION')
old.name = 'SUB IK Knee Twist'
ik.wire(obj)
assert all(not obj.pose.bones[ik.PULL_PREFIX + n].constraints.get('SUB IK Knee Twist') for n in ('LegL', 'KneeL'))
audit()
pole.rotation_mode = 'QUATERNION'
for frame, angle in ((1, 0.0), (16, 0.4)):
    pole.rotation_quaternion = Quaternion((0, 1, 0), angle)
    pole.keyframe_insert('rotation_quaternion', frame=frame)
ik.match(bpy.context, obj, 'LEGS', entire=True, key=True, _batch=True)
assert diag.record()['counts'].get('native_solves', 0) == 32, diag.record()
for frame, matrices in source.items():
    scene.frame_set(frame)
    actual = snapshot()
    for name in names:
        assert error(actual[name], matrices[name]) < 2e-4, (frame, name)
assert bpy.ops.sub.anim_rig_toggle_ik_fk(limbs='LEGS', set_enabled=True, enable_ik=False) == {'FINISHED'}
scene.frame_set(8)
original = obj.pose.bones['LegL']
before = snapshot()
original.rotation_mode = 'XYZ'
original.rotation_euler.y += 0.3
after = snapshot()
assert error(before['LegL'], after['LegL']) > 0.1
before = after
set_rotation(pole, rotation, 'QUATERNION')
assert error(before['LegL'], snapshot()['LegL']) < 2e-5
assert not pose_hidden(obj.pose.bones['LegL'])
helpers = [name for _, _, _, pole_name in jobs for name in ik.pole_rotation_names(pole_name)]
ik.remove(bpy.context, obj, 'LEGS')
assert not any(name in obj.data.bones for name in helpers)
print('KNEE X/Y PULL INFLUENCE, FIXED SOLVER/FOOT AND NATIVE MATCHING PASSED')
