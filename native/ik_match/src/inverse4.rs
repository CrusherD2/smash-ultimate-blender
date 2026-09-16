// SPDX-License-Identifier: MPL-2.0
// Scalar packet transcription of Blender v4.5.0's vendored Eigen
// Eigen/src/LU/arch/InverseSize4.h.
// Copyright (C) 2001 Intel Corporation
// Copyright (C) 2010 Gael Guennebaud <gael.guennebaud@inria.fr>
// Copyright (C) 2009 Benoit Jacob <jacob.benoit.1@gmail.com>
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. See https://mozilla.org/MPL/2.0/.
// Intel's original notice: Permission is granted to use, copy, distribute
// and prepare derivative works of this library for any purpose and without
// fee, provided that the above copyright notice and this statement appear
// in all copies. Intel makes no representations about the suitability of
// this software for any purpose, and specifically disclaims all warranties.
use crate::pose::Mat4;
type P = [f32; 4];
fn mul(a: P, b: P) -> P {
    std::array::from_fn(|i| a[i] * b[i])
}
fn add(a: P, b: P) -> P {
    std::array::from_fn(|i| a[i] + b[i])
}
fn sub(a: P, b: P) -> P {
    std::array::from_fn(|i| a[i] - b[i])
}
fn sw(a: P, b: P, indices: [usize; 4]) -> P {
    [a[indices[0]], a[indices[1]], b[indices[2]], b[indices[3]]]
}
fn lo(a: P, b: P) -> P {
    [a[0], a[1], b[0], b[1]]
}
fn hi(a: P, b: P) -> P {
    [b[2], b[3], a[2], a[3]]
}
fn dup(a: P) -> P {
    [a[0]; 4]
}
fn det2(x: P) -> P {
    let v = mul(sw(x, x, [3, 3, 1, 1]), x);
    sub(v, hi(v, v))
}
pub fn inverse(matrix: Mat4) -> Mat4 {
    let [l1, l2, l3, l4] = std::array::from_fn(|c| std::array::from_fn(|r| matrix[r][c]));
    let (a, b, c, d) = (lo(l1, l2), hi(l2, l1), lo(l3, l4), hi(l4, l3));
    let ab = sub(
        mul(sw(a, a, [3, 3, 0, 0]), b),
        mul(sw(a, a, [1, 1, 2, 2]), sw(b, b, [2, 3, 0, 1])),
    );
    let dc = sub(
        mul(sw(d, d, [3, 3, 0, 0]), c),
        mul(sw(d, d, [1, 1, 2, 2]), sw(c, c, [2, 3, 0, 1])),
    );
    let (da, db, dc_det, dd) = (det2(a), det2(b), det2(c), det2(d));
    let trace = mul(sw(dc, dc, [0, 2, 1, 3]), ab);
    let trace = add(trace, hi(trace, trace));
    let trace = add(trace, sw(trace, trace, [1, 0, 0, 0]));
    let det = sub(add(mul(da, dd), mul(db, dc_det)), trace)[0];
    assert!(det != 0.0 && det.is_finite());
    let rd = 1.0 / det;
    let rd = [rd, -rd, -rd, rd];
    let di = sub(
        mul(d, dup(da)),
        add(
            mul(sw(c, c, [0, 0, 2, 2]), lo(ab, ab)),
            mul(sw(c, c, [1, 1, 3, 3]), hi(ab, ab)),
        ),
    );
    let ai = sub(
        mul(a, dup(dd)),
        add(
            mul(sw(b, b, [0, 0, 2, 2]), lo(dc, dc)),
            mul(sw(b, b, [1, 1, 3, 3]), hi(dc, dc)),
        ),
    );
    let bi = sub(
        mul(c, dup(db)),
        sub(
            mul(d, sw(ab, ab, [3, 0, 3, 0])),
            mul(sw(d, d, [1, 0, 3, 2]), sw(ab, ab, [2, 1, 2, 1])),
        ),
    );
    let ci = sub(
        mul(b, dup(dc_det)),
        sub(
            mul(a, sw(dc, dc, [3, 0, 3, 0])),
            mul(sw(a, a, [1, 0, 3, 2]), sw(dc, dc, [2, 1, 2, 1])),
        ),
    );
    let (ai, bi, ci, di) = (mul(ai, rd), mul(bi, rd), mul(ci, rd), mul(di, rd));
    let cols = [
        sw(ai, bi, [3, 1, 3, 1]),
        sw(ai, bi, [2, 0, 2, 0]),
        sw(ci, di, [3, 1, 3, 1]),
        sw(ci, di, [2, 0, 2, 0]),
    ];
    std::array::from_fn(|r| std::array::from_fn(|c| cols[c][r]))
}
