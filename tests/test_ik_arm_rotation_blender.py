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

checks = Path(__file__).with_name('ik_pull_rotation_checks.py')
exec(compile(checks.read_text(), str(checks), 'exec'))
check_rotation_influences(obj, ik, ('Shoulder', 'Arm', 'Hand'), 'ArmIK')

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
print('ARM X/Y PULL INFLUENCE, FIXED SOLVER/HANDS, FK ROTATION AND NATIVE MATCHING PASSED')
