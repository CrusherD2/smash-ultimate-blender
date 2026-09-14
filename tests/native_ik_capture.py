# SPDX-License-Identifier: GPL-2.0-or-later
# Diagnostic transcription of Blender v4.5.0 execute_posetree input conversion.
from mathutils import Matrix, Vector
from native_ik_inverse_reference import inverse3, inverse4, f32
import math
matrix_list = lambda m: [list(row) for row in m]

def length_f32(vector):
    # Match BLI len_v3's float intermediates, rather than Vector.length's
    # higher-precision generic-vector reduction exposed through Python.
    value = f32(f32(f32(vector[0]*vector[0]) + f32(vector[1]*vector[1])) + f32(vector[2]*vector[2]))
    return f32(math.sqrt(value))


def multiply(a, b):
    # BLI mul_m3_m3m3 uses left-associated float sums; its SSE2 4x4
    # implementation uses two pairs. mathutils @ accumulates in double.
    size = len(a)
    def entry(r, c):
        p = [f32(a[r][k] * b[k][c]) for k in range(size)]
        return f32(f32(p[0] + p[1]) + (f32(p[2] + p[3]) if size == 4 else p[2]))
    return Matrix([[entry(r, c) for c in range(size)] for r in range(size)])


def multiply_vector(a, b):
    return Vector([f32(f32(f32(row[0]*b[0]) + f32(row[1]*b[1])) + f32(row[2]*b[2])) for row in a])


def capture_input(obj, job, solver, con, frame):
    parent = solver[0].parent.matrix.copy() if solver[0].parent else Matrix.Identity(4)
    poses = [b.matrix.copy() for b in solver]
    segments = []
    deltas = []
    for i, bone in enumerate(solver):
        prior = parent if i == 0 else poses[i-1]
        rotation = poses[i].to_3x3()
        length = f32(bone.bone.length * length_f32(rotation.col[1]))
        rotation.normalize()
        parent_rotation = prior.to_3x3()
        parent_rotation.normalize()
        inverse_parent_rotation = inverse3(parent_rotation)
        rest = bone.bone.matrix.copy()
        basis = multiply(rest.transposed(), multiply(inverse_parent_rotation, rotation))
        start = multiply_vector(inverse_parent_rotation, bone.head - solver[i-1].tail) if i else Vector((0,0,0))
        segments.append(dict(start=list(start), rest=matrix_list(rest), basis=matrix_list(basis), length=length))
        deltas.append(matrix_list(multiply(inverse4(prior), poses[i])))
    root = parent.copy()
    root.normalize()
    root.translation = poses[0].translation
    goal_inverse = inverse4(multiply(obj.matrix_world, root))
    goal = multiply(goal_inverse, multiply(obj.matrix_world, obj.pose.bones[con.subtarget].matrix)).translation
    pole = multiply(goal_inverse, multiply(obj.matrix_world, obj.pose.bones[con.pole_subtarget].matrix)).translation
    return dict(id=f'{job[2]}@{frame}', segments=segments, goal=list(goal), pole=list(pole),
                iterations=con.iterations, parent=matrix_list(parent), deltas=deltas,
                lengths=[b.length for b in solver], bones=[b.name for b in solver])


