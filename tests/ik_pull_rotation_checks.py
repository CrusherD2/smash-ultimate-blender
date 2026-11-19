import math

import bpy
from mathutils import Quaternion, Vector


def check_rotation_influences(obj, ik, parts, pole_prefix):
    def set_rotation(pole, rotation, mode):
        pole.rotation_mode = mode
        if mode == 'QUATERNION':
            pole.rotation_quaternion = rotation
        elif mode == 'AXIS_ANGLE':
            axis, angle = rotation.to_axis_angle()
            pole.rotation_axis_angle = (angle, *axis)
        else:
            pole.rotation_euler = rotation.to_euler(mode)

    def evaluate():
        obj.update_tag()
        bpy.context.view_layer.update()
        return obj.evaluated_get(bpy.context.evaluated_depsgraph_get())

    for side in ('L', 'R'):
        pole = obj.pose.bones[pole_prefix + side]
        set_rotation(pole, Quaternion(), 'QUATERNION')
    neutral = evaluate()
    solver_matrices = {part + side: neutral.pose.bones[ik.PREFIX + part + side].matrix.copy()
                       for side in ('L', 'R') for part in parts}
    endpoints = {side: neutral.pose.bones[parts[-1] + side].matrix.copy() for side in ('L', 'R')}
    for side in ('L', 'R'):
        pole = obj.pose.bones[pole_prefix + side]
        for mode in ('XYZ', 'ZYX', 'QUATERNION', 'AXIS_ANGLE'):
            for axis in ('X', 'Y', 'Z'):
                for degrees in (-180, -135, -90, -45, 0, 45, 90, 135, 180):
                    vector = Vector(tuple(float(a == axis) for a in ('X', 'Y', 'Z')))
                    set_rotation(pole, Quaternion(vector, math.radians(degrees)), mode)
                    evaluated = evaluate()
                    for other in ('L', 'R'):
                        for index, part in enumerate(parts[:2]):
                            base = evaluated.pose.bones[ik.PULL_PREFIX + part + other].constraints[ik.PULL_BASE]
                            affected = other == side and axis == ('X', 'Y')[index]
                            expected = 1 - abs(degrees) / 180 if affected else 1
                            assert abs(base.influence - expected) < 2e-5, (side, mode, axis, degrees, part, other, base.influence)
                        for part in parts:
                            actual = evaluated.pose.bones[ik.PREFIX + part + other].matrix
                            reference = solver_matrices[part + other]
                            assert max(abs(actual[r][c] - reference[r][c]) for r in range(4) for c in range(4)) < 3e-5
                        actual = evaluated.pose.bones[parts[-1] + other].matrix
                        assert max(abs(actual[r][c] - endpoints[other][r][c]) for r in range(4) for c in range(4)) < 3e-5
            set_rotation(pole, Quaternion(), mode)
            evaluate()
    # Moving a target still fades stale match offsets, independently of rotation.
    target = next(target for _, _, target, pole in ik.chains(obj) if pole == pole_prefix + 'L')
    control = obj.pose.bones[target]
    before = control.location.copy()
    names = next(names for _, names, job_target, _ in ik.chains(obj) if job_target == target)
    control.location.x += ik._chain_rest_length(obj, ik.limb_path(obj, names)) + 1
    evaluated = evaluate()
    for part in parts[:2]:
        assert abs(evaluated.pose.bones[ik.PULL_PREFIX + part + 'L'].constraints[ik.PULL_BASE].influence) < 2e-5
    control.location = before
    evaluate()
