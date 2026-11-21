from pathlib import Path
import math

fixture = Path(__file__).with_name('test_ik_hip_continuity_blender.py')
exec(compile(fixture.read_text().split('assert ik.create_controls')[0], str(fixture), 'exec'))
assert ik.create_controls(bpy.context, obj) == 4
ik.upgrade_pull_controls(bpy.context, obj)
ik.upgrade_pull_controls(bpy.context, obj)
for name, matrix in original.items():
    error = max(abs(a - b) for row, wanted in zip(obj.pose.bones[name].matrix, matrix)
                for a, b in zip(row, wanted))
    assert error < 2e-4, (name, error)
for kind, names, target, pole in ik.chains(obj):
    for name in names[:-1]:
        constraints = obj.pose.bones[ik.PULL_PREFIX + name].constraints
        for label in (ik.PULL_ROTATION, ik.PULL_TWIST):
            assert sum(con.name == label for con in constraints) == 1
    for control_name in (pole, target):
        control = obj.pose.bones[control_name]
        origin = control.location.copy()
        rest = ik._chain_rest_length(obj, ik.limb_path(obj, names))
        worst = 0.0
        for axis in range(3):
            for step in range(-20, 21):
                control.location = origin
                control.location[axis] += rest * step / 40
                obj.update_tag()
                bpy.context.view_layer.update()
                for name in names[:-1]:
                    pull = obj.pose.bones[ik.PULL_PREFIX + name]
                    correction = obj.pose.bones[ik.CORRECTION_PREFIX + name]
                    angle = pull.matrix.to_quaternion().rotation_difference(correction.matrix.to_quaternion()).angle
                    worst = max(worst, min(angle, 2 * math.pi - angle))
        control.location = origin
        obj.update_tag()
        bpy.context.view_layer.update()
        assert worst < 1e-3, (control_name, worst)
print('POLE AND TARGET TRANSLATION PRESERVE MATCHED TWIST PASSED')
