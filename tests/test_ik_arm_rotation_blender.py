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

ik.match(bpy.context, obj, 'ARMS', entire=True, key=True)
def near_straight(matrices, side):
    root, joint, end = (matrices[part + side].translation for part in ('Shoulder', 'Arm', 'Hand'))
    length = (joint - root).length + (end - joint).length
    axis = (end - root).normalized()
    offset = joint - root - axis * (joint - root).dot(axis)
    return length if offset.length < .01 * length else None

for frame, matrices in source.items():
    scene.frame_set(frame)
    actual = snapshot()
    straight = [length for length in (near_straight(matrices, 'L'), near_straight(matrices, 'R')) if length]
    for name, matrix in matrices.items():
        if error(actual[name], matrix) < 2e-4:
            continue
        # Near-straight arms are nudged to fold toward their pole: under 1.5 degrees and 1.5% of the arm.
        assert straight, (frame, name)
        angle = actual[name].to_quaternion().rotation_difference(matrix.to_quaternion()).angle
        assert min(angle, 2 * math.pi - angle) < math.radians(1.5), (frame, name, angle)
        assert (actual[name].translation - matrix.translation).length < .015 * max(straight), (frame, name)
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
print('ARM MATCHING IS 1:1 AND FK ROTATION STILL DRIVES THE ARM PASSED')
