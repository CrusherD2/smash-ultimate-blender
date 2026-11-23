from pathlib import Path
import math

fixture = Path(__file__).with_name('test_ik_control_orientation_blender.py')
exec(compile(fixture.read_text().split('assert ikc.create_controls')[0], str(fixture), 'exec'))
assert ikc.create_controls(bpy.context, arm, 'ARMS') == 1
for name in ('ShoulderL', 'ArmL', 'HandL'):
    for prefix in (ikc.PREFIX, ikc.PULL_PREFIX, ikc.POSE_PREFIX):
        actual, expected = data.bones[prefix + name].matrix_local, data.bones[name].matrix_local
        assert max(abs(actual[r][c] - expected[r][c]) for r in range(4) for c in range(4)) < 2e-5, (prefix, name)
control = arm.pose.bones['HandIKL']
origin = control.matrix.copy()
reference_hand = arm.pose.bones['HandL'].matrix.to_quaternion()
data.sub_ik_stretch_arms = True
for chain in (False, True):
    data.sub_ik_stretch_chain_arms = chain
    previous = {}
    # Stretch out, then compress inward past the initial matched pose.
    for distance in [i * .025 for i in range(161)] + [4 - i * .025 for i in range(281)]:
        matrix = origin.copy()
        matrix.translation.x += distance
        control.matrix = matrix
        arm.update_tag()
        bpy.context.view_layer.update()
        evaluated = arm.evaluated_get(bpy.context.evaluated_depsgraph_get())
        hand = evaluated.pose.bones['HandL']
        angle = hand.matrix.to_quaternion().rotation_difference(reference_hand).angle
        assert min(angle, 2 * math.pi - angle) < 1e-3, (chain, distance, angle)
        assert (hand.head - evaluated.pose.bones['HandIKL'].head).length < 2e-4
        for part in ('ShoulderL', 'ArmL'):
            rotation = evaluated.pose.bones[part].matrix.to_quaternion()
            assert all(math.isfinite(value) for value in rotation)
            if part in previous:
                angle = rotation.rotation_difference(previous[part]).angle
                assert min(angle, 2 * math.pi - angle) < .25, (chain, distance, part, angle)
            previous[part] = rotation
print('OUTWARD STRETCH AND INWARD COMPRESSION KEEP HAND ROTATION AND AVOID ARM FLIPS PASSED')
