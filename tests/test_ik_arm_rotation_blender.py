from pathlib import Path
import importlib
import math
from mathutils import Quaternion, Vector

fixture = Path(__file__).with_name('test_ik_detail_acceleration_blender.py')
setup = fixture.read_text().split('\naudit()\nfor repeat')[0]
setup = setup.replace('Leg', 'Shoulder').replace('Knee', 'Arm').replace('Foot', 'Hand').replace('LEGS', 'ARMS')
exec(compile(setup, str(fixture), 'exec'))
rig = importlib.import_module(MODULE + '.source.extras.create_animation_rig')
scene.frame_set(8)

def snapshot():
    obj.update_tag()
    bpy.context.view_layer.update()
    ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    return {name: ev.pose.bones[name].matrix.copy() for name in source[8]}

def error(a, b):
    return max(abs(a[r][c] - b[r][c]) for r in range(4) for c in range(4))

neutral = snapshot()
for side in ('L', 'R'):
    pole = obj.pose.bones['ArmIK' + side]
    pole.rotation_mode = 'QUATERNION'
    assert not any(pole.lock_rotation)
    for axis in ('X', 'Y', 'Z'):
        previous = None
        changed = 0.0
        for degrees in range(-185, 186, 5):
            vector = Vector(tuple(float(a == axis) for a in ('X', 'Y', 'Z')))
            pole.rotation_quaternion = Quaternion(vector, math.radians(degrees))
            actual = snapshot()
            changed = max(changed, error(actual['Shoulder'+side], neutral['Shoulder'+side]))
            assert error(actual['Hand'+side], neutral['Hand'+side]) < 3e-5
            other = 'R' if side == 'L' else 'L'
            for bone in ('Shoulder', 'Arm', 'Hand'):
                assert error(actual[bone+other], neutral[bone+other]) < 3e-5
            ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
            shoulder, arm, hand = [ev.pose.bones[n+side] for n in ('Shoulder', 'Arm', 'Hand')]
            assert (shoulder.tail - arm.head).length < 2e-4
            assert (arm.tail - hand.head).length < 2e-4
            if previous is not None:
                step = previous.to_quaternion().rotation_difference(actual['Shoulder'+side].to_quaternion()).angle
                assert step < 0.25, (side, axis, degrees, step)
            previous = actual['Shoulder'+side]
        assert changed > 0.01, (side, axis)
    pole.rotation_quaternion = Quaternion()
    snapshot()
audit()
ik.match(bpy.context, obj, 'ARMS', entire=True, key=True, _batch=True)
assert diag.record()['counts'].get('native_solves', 0) == 32
for frame, matrices in source.items():
    scene.frame_set(frame)
    actual = snapshot()
    for name, matrix in matrices.items():
        assert error(actual[name], matrix) < 2e-4
scene.frame_set(8)
assert bpy.ops.sub.anim_rig_toggle_ik_fk(limbs='ARMS', set_enabled=True, enable_ik=False) == {'FINISHED'}
for name in ('ShoulderL', 'ArmL', 'HandL'):
    pb = obj.pose.bones[name]
    pb.rotation_mode = 'XYZ'
    for axis in range(3):
        before = snapshot()[name]
        pb.rotation_euler[axis] += 0.3
        assert error(snapshot()[name], before) > 0.05, (name, axis)
        pb.rotation_euler[axis] -= 0.3
print('BOTH ARM POLES: SMOOTH XYZ, CONNECTED JOINTS, FIXED HANDS, FK ROTATION AND NATIVE MATCHING PASSED')
