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
reference = snapshot()
for mode in ('XYZ', 'ZYX', 'QUATERNION', 'AXIS_ANGLE'):
    for axis in ('X', 'Y', 'Z'):
        set_rotation(pole, Quaternion(), mode)
        before = snapshot()
        previous = before
        max_change = 0.0
        for degrees in range(-185, 186, 5):
            vector = Vector(tuple(float(a == axis) for a in ('X', 'Y', 'Z')))
            set_rotation(pole, Quaternion(vector, math.radians(degrees)), mode)
            current = snapshot()
            for name in ('FootL', 'LegR', 'KneeR', 'FootR'):
                assert error(current[name], reference[name]) < 3e-5, (mode, axis, degrees, name)
            for name in ('LegL', 'KneeL'):
                assert all(math.isfinite(value) for row in current[name] for value in row)
                max_change = max(max_change, error(current[name], before[name]))
                if degrees > -185:
                    step = previous[name].to_quaternion().rotation_difference(current[name].to_quaternion()).angle
                    assert step < 0.25, (mode, axis, degrees, name, step)
            ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
            leg, knee, foot = [ev.pose.bones[ik.PREFIX + n] for n in ('LegL', 'KneeL', 'FootL')]
            assert (leg.tail - knee.head).length < 2e-4, (mode, axis, degrees)
            assert (knee.tail - foot.head).length < 2e-4, (mode, axis, degrees)
            leg, knee, foot = [ev.pose.bones[n] for n in ('LegL', 'KneeL', 'FootL')]
            assert (leg.tail - knee.head).length < 2e-4, (mode, axis, degrees, 'deform knee')
            assert (knee.tail - foot.head).length < 2e-4, (mode, axis, degrees, 'deform ankle')
            previous = current
        assert max_change > 0.02, (mode, axis, max_change)
    set_rotation(pole, Quaternion(), mode)
    actual = snapshot()
    assert max(error(actual[name], reference[name]) for name in names) < 3e-5

rotation = Euler((0.4, -0.5, 0.7)).to_quaternion()
set_rotation(pole, rotation, 'XYZ')
expected = snapshot()
for mode in ('QUATERNION', 'AXIS_ANGLE', 'ZYX'):
    set_rotation(pole, rotation, mode)
    actual = snapshot()
    assert max(error(actual[name], expected[name]) for name in names) < 3e-5, mode

set_rotation(pole, Quaternion(), 'QUATERNION')
right_pole = obj.pose.bones['KneeIKR']
neutral = snapshot()
for axis in ('X', 'Y', 'Z'):
    vector = Vector(tuple(float(a == axis) for a in ('X', 'Y', 'Z')))
    set_rotation(right_pole, Quaternion(vector, 0.7), 'QUATERNION')
    current = snapshot()
    assert error(current['LegR'], neutral['LegR']) > 0.01, axis
    for name in ('LegL', 'KneeL', 'FootL', 'FootR'):
        assert error(current[name], neutral[name]) < 3e-5, (axis, name)
set_rotation(right_pole, Quaternion(), 'QUATERNION')

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
print('SMOOTH XYZ KNEE ROTATION, CONNECTED JOINTS, PLANTED FOOT AND NATIVE MATCHING PASSED')
