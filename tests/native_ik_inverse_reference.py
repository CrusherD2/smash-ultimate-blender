# SPDX-License-Identifier: MPL-2.0
# Packet-operation transcription of Eigen v4.5.0 Blender vendored
# Eigen/src/LU/arch/InverseSize4.h (diagnostic harness only).
# Copyright (C) 2001 Intel Corporation
# Copyright (C) 2010 Gael Guennebaud <gael.guennebaud@inria.fr>
# Copyright (C) 2009 Benoit Jacob <jacob.benoit.1@gmail.com>
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. See https://mozilla.org/MPL/2.0/.
# Intel's original notice: Permission is granted to use, copy, distribute
# and prepare derivative works of this library for any purpose and without
# fee, provided that the above copyright notice and this statement appear
# in all copies. Intel makes no representations about the suitability of
# this software for any purpose, and specifically disclaims all warranties.
import struct
from mathutils import Matrix


def f32(x):
    return struct.unpack('f', struct.pack('f', x))[0]


def inverse4(matrix):
    """Eigen's four-float packet inverse, matching column-major storage."""
    def mul(a, b):
        return [f32(x*y) for x, y in zip(a, b)]
    def add(a, b):
        return [f32(x+y) for x, y in zip(a, b)]
    def sub(a, b):
        return [f32(x-y) for x, y in zip(a, b)]
    def sw(a, b, i, j, k, l):
        return [a[i], a[j], b[k], b[l]]
    def lo(a, b):
        return a[:2]+b[:2]
    def hi(a, b):
        return b[2:]+a[2:]
    def dup(a):
        return [a[0]]*4
    l1, l2, l3, l4 = [list(c) for c in matrix.col]
    a, b, c, d = lo(l1, l2), hi(l2, l1), lo(l3, l4), hi(l4, l3)
    ab = sub(mul(sw(a,a,3,3,0,0),b), mul(sw(a,a,1,1,2,2),sw(b,b,2,3,0,1)))
    dc = sub(mul(sw(d,d,3,3,0,0),c), mul(sw(d,d,1,1,2,2),sw(c,c,2,3,0,1)))
    def det2(x):
        v = mul(sw(x,x,3,3,1,1),x)
        return sub(v,hi(v,v))
    da, db, dc_det, dd = map(det2, (a,b,c,d))
    trace = mul(sw(dc,dc,0,2,1,3),ab)
    trace = add(trace,hi(trace,trace))
    trace = add(trace,sw(trace,trace,1,0,0,0))
    det = sub(add(mul(da,dd),mul(db,dc_det)),trace)[0]
    assert det != 0
    rd = f32(1/det)
    rd = [rd,-rd,-rd,rd]
    di = sub(mul(d,dup(da)),add(mul(sw(c,c,0,0,2,2),lo(ab,ab)),mul(sw(c,c,1,1,3,3),hi(ab,ab))))
    ai = sub(mul(a,dup(dd)),add(mul(sw(b,b,0,0,2,2),lo(dc,dc)),mul(sw(b,b,1,1,3,3),hi(dc,dc))))
    bi = sub(mul(c,dup(db)),sub(mul(d,sw(ab,ab,3,0,3,0)),mul(sw(d,d,1,0,3,2),sw(ab,ab,2,1,2,1))))
    ci = sub(mul(b,dup(dc_det)),sub(mul(a,sw(dc,dc,3,0,3,0)),mul(sw(a,a,1,0,3,2),sw(dc,dc,2,1,2,1))))
    ai, bi, ci, di = [mul(x,rd) for x in (ai,bi,ci,di)]
    return Matrix([sw(ai,bi,3,1,3,1),sw(ai,bi,2,0,2,0),sw(ci,di,3,1,3,1),sw(ci,di,2,0,2,0)]).transposed()


def inverse3(matrix):
    # BLI uses an adjugate times a float reciprocal, whereas mathutils divides
    # each cofactor by the determinant and evaluates it in a different order.
    m = list(matrix.col)
    def minor(a,b,c,d):
        return f32(f32(a*b)-f32(c*d))
    co = [[0.0]*3 for _ in range(3)]
    for r in range(3):
        for c in range(3):
            rows = [i for i in range(3) if i != c]
            cols = [i for i in range(3) if i != r]
            co[r][c] = minor(m[rows[0]][cols[0]],m[rows[1]][cols[1]],m[rows[0]][cols[1]],m[rows[1]][cols[0]]) * (-1 if (r+c)%2 else 1)
    det = f32(f32(f32(m[0][0]*co[0][0])+f32(m[1][0]*co[0][1]))+f32(m[2][0]*co[0][2]))
    inv = f32(1/det)
    return Matrix([[f32(x*inv) for x in row] for row in co]).transposed()
