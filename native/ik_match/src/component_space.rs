// SPDX-FileCopyrightText: Blender Authors
// SPDX-License-Identifier: GPL-2.0-or-later
//! BoneParentTransform math from Blender armature.cc, independent of Blender RNA.
use crate::component_math::{det, identity, inverse, mul, orthogonalize, sizes, Mat};
#[derive(Clone, Copy)]
pub struct ParentTransform {
    rotation: Mat,
    location: Mat,
    scale: [f32; 3],
}
fn rescale(mut m: Mat, size: [f32; 3]) -> Mat {
    for r in 0..3 {
        for c in 0..3 {
            m[r][c] *= size[c];
        }
    }
    m
}
fn normalize(mut m: Mat) -> (Mat, [f32; 3]) {
    let mut size = sizes(m);
    for c in 0..3 {
        if size[c] * size[c] > 1e-35 {
            let reciprocal = 1.0 / size[c];
            for r in 0..3 {
                m[r][c] *= reciprocal;
            }
        } else {
            size[c] = 0.0;
            for r in 0..3 {
                m[r][c] = 0.0;
            }
        }
    }
    (m, size)
}
fn shear_size(m: Mat) -> [f32; 3] {
    let mut size = sizes(m);
    let volume = size[0] * size[1] * size[2];
    if volume != 0.0 {
        let factor = (det(m) / volume).abs().cbrt();
        size = size.map(|v| v * factor);
    }
    size
}
fn point(m: Mat, v: [f32; 3]) -> [f32; 3] {
    std::array::from_fn(|r| ((m[r][0] * v[0] + m[r][1] * v[1]) + m[r][2] * v[2]) + m[r][3])
}
pub fn parent_transform(
    offset: Mat,
    parent_rest: Mat,
    parent: Option<Mat>,
    mode: &str,
    rotation: bool,
    local: bool,
) -> ParentTransform {
    let mut post = [1.0; 3];
    let (rot, loc) = if let Some(parent) = parent {
        let full = rotation && mode == "FULL";
        let rot = if full {
            mul(parent, offset)
        } else {
            let mut matrix = if rotation {
                match mode {
                    "NONE" | "AVERAGE" => orthogonalize(parent, true),
                    "ALIGNED" => {
                        let (matrix, size) = normalize(orthogonalize(parent, false));
                        post = size;
                        matrix
                    }
                    "NONE_LEGACY" => normalize(parent).0,
                    _ => parent,
                }
            } else {
                match mode {
                    "FULL" => rescale(parent_rest, sizes(parent)),
                    "FIX_SHEAR" => rescale(parent_rest, shear_size(parent)),
                    "ALIGNED" => {
                        post = shear_size(parent);
                        parent_rest
                    }
                    _ => parent_rest,
                }
            };
            if mode == "AVERAGE" {
                matrix = rescale(matrix, [det(parent).abs().cbrt(); 3]);
            }
            matrix = mul(matrix, offset);
            if mode == "FIX_SHEAR" {
                matrix = orthogonalize(matrix, false);
            }
            matrix
        };
        let loc = if !local {
            let mut matrix = parent;
            let loc = point(parent, [offset[0][3], offset[1][3], offset[2][3]]);
            for r in 0..3 {
                matrix[r][3] = loc[r];
            }
            matrix
        } else if !full {
            mul(parent, offset)
        } else {
            rot
        };
        (rot, loc)
    } else {
        let mut loc = if local { offset } else { identity() };
        for r in 0..3 {
            loc[r][3] = offset[r][3];
        }
        (offset, loc)
    };
    ParentTransform {
        rotation: rot,
        location: loc,
        scale: post,
    }
}
impl ParentTransform {
    pub fn apply(self, matrix: Mat, invert: bool) -> Option<Mat> {
        let (rotation, location, scale) = if invert {
            (
                inverse(self.rotation)?,
                inverse(self.location)?,
                self.scale.map(|v| if v != 0.0 { 1.0 / v } else { 0.0 }),
            )
        } else {
            (self.rotation, self.location, self.scale)
        };
        let mut out = mul(rotation, matrix);
        let loc = point(location, [matrix[0][3], matrix[1][3], matrix[2][3]]);
        for r in 0..3 {
            out[r][3] = loc[r];
        }
        Some(rescale(out, scale))
    }
}
