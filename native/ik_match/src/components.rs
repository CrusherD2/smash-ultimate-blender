// SPDX-License-Identifier: GPL-2.0-or-later
//! Independent component fitting ABI. No Blender access and no changes to IK.
use std::slice;

#[no_mangle]
pub extern "C" fn sub_component_abi_version() -> u32 { 1 }

/// Compute inverse(left) * right for residual/isolated controls. Singular
/// transforms explicitly decline so Blender's inverted_safe policy is retained.
#[no_mangle]
pub unsafe extern "C" fn sub_component_relative(left: *const f64, right: *const f64, output: *mut f64) -> i32 {
    if left.is_null() || right.is_null() || output.is_null() { return 0; }
    let a=slice::from_raw_parts(left,16);
    let b=slice::from_raw_parts(right,16);
    if a.iter().chain(b).any(|x| !x.is_finite()) { return 0; }
    let mut m=[[0.0;8];4];
    for r in 0..4 { for c in 0..4 { m[r][c]=a[r*4+c]; m[r][c+4]=b[r*4+c]; }}
    for c in 0..4 {
        let p=(c..4).max_by(|&x,&y| m[x][c].abs().total_cmp(&m[y][c].abs())).unwrap();
        if m[p][c].abs()<1e-10 { return 0; }
        m.swap(p,c);
        let d=m[c][c];
        for j in 0..8 { m[c][j]/=d; }
        for r in 0..4 { if r!=c {
            let factor=m[r][c];
            for j in 0..8 { m[r][j]-=factor*m[c][j]; }
        }}
    }
    let out=slice::from_raw_parts_mut(output,16);
    for r in 0..4 { for c in 0..4 { out[r*4+c]=m[r][c+4]; }}
    if out.iter().all(|x| x.is_finite()) { 1 } else { 0 }
}

// One-sided Jacobi SVD, avoiding squared condition numbers from normal equations.
#[no_mangle]
pub unsafe extern "C" fn sub_component_lstsq(
    matrix: *const f64, goal: *const f64, rows: usize, cols: usize,
    output: *mut f64,
) -> i32 {
    if matrix.is_null() || goal.is_null() || output.is_null()
        || rows == 0 || cols == 0 || rows > 100000 || cols > 256 { return 0; }
    let mut a = slice::from_raw_parts(matrix,rows*cols).to_vec();
    let b = slice::from_raw_parts(goal,rows);
    if a.iter().chain(b).any(|x| !x.is_finite()) { return 0; }
    let mut v = vec![0.0;cols*cols];
    for i in 0..cols { v[i*cols+i]=1.0; }
    let mut converged = false;
    for _ in 0..100 {
        let mut changed = false;
        for p in 0..cols { for q in p+1..cols {
            let mut aa=0.0; let mut bb=0.0; let mut ab=0.0;
            for r in 0..rows {
                let x=a[r*cols+p]; let y=a[r*cols+q];
                aa+=x*x; bb+=y*y; ab+=x*y;
            }
            if ab.abs() <= 1e-14*(aa*bb).sqrt() || ab == 0.0 { continue; }
            changed=true;
            let z=(bb-aa)/(2.0*ab);
            let t=if z>=0.0 {1.0} else {-1.0}/(z.abs()+z.hypot(1.0));
            let c=1.0/(1.0+t*t).sqrt(); let s=c*t;
            for r in 0..rows {
                let x=a[r*cols+p]; let y=a[r*cols+q];
                a[r*cols+p]=c*x-s*y; a[r*cols+q]=s*x+c*y;
            }
            for r in 0..cols {
                let x=v[r*cols+p]; let y=v[r*cols+q];
                v[r*cols+p]=c*x-s*y; v[r*cols+q]=s*x+c*y;
            }
        }}
        if !changed { converged=true; break; }
    }
    if !converged { return 0; }
    let norms: Vec<f64>=(0..cols).map(|c| (0..rows).map(|r| a[r*cols+c].powi(2)).sum()).collect();
    let cutoff=norms.iter().copied().fold(0.0,f64::max)*1e-10;
    let out=slice::from_raw_parts_mut(output,cols);
    out.fill(0.0);
    for c in 0..cols {
        if norms[c]<=cutoff { continue; }
        let weight=(0..rows).map(|r| a[r*cols+c]*b[r]).sum::<f64>()/norms[c];
        for r in 0..cols { out[r]+=v[r*cols+c]*weight; }
    }
    if out.iter().all(|x| x.is_finite()) { 1 } else { 0 }
}

// Row-major pseudoinverse times a batch of target vectors. Parallelism is
// across frames, never across Blender data or dependency graph evaluation.
#[no_mangle]
pub unsafe extern "C" fn sub_component_project(
    inverse: *const f64, goals: *const f64, rows: usize, cols: usize,
    frames: usize, output: *mut f64,
) -> i32 {
    if inverse.is_null() || goals.is_null() || output.is_null()
        || rows == 0 || cols == 0 || frames == 0
        || rows.checked_mul(cols).is_none() || cols.checked_mul(frames).is_none()
        || rows.checked_mul(frames).is_none() { return 0; }
    let a = slice::from_raw_parts(inverse, rows * cols);
    let b = slice::from_raw_parts(goals, frames * cols);
    let out = slice::from_raw_parts_mut(output, frames * rows);
    if a.iter().chain(b).any(|x| !x.is_finite()) { return 0; }
    let solve = |f: usize, row: &mut [f64]| {
        for r in 0..rows {
            row[r] = (0..cols).map(|c| a[r*cols+c] * b[f*cols+c]).sum();
        }
    };
    if frames > 32 {
        use rayon::prelude::*;
        out.par_chunks_mut(rows).enumerate().for_each(|(f,row)| solve(f,row));
    } else {
        for (f,row) in out.chunks_mut(rows).enumerate() { solve(f,row); }
    }
    if out.iter().all(|x| x.is_finite()) { 1 } else { 0 }
}

// Each segment is [expression index, low, high, start[width], end[width]].
// Returns [squared error, expression index, strength] for every sampled frame.
#[no_mangle]
pub unsafe extern "C" fn sub_component_expressions(
    segments: *const f64, count: usize, goals: *const f64,
    width: usize, frames: usize, output: *mut f64,
) -> i32 {
    if segments.is_null() || goals.is_null() || output.is_null() || width == 0
        || width > 100000 || count > 10000 || frames > 1000000 { return 0; }
    let stride = 3 + width*2;
    let segments = slice::from_raw_parts(segments, count*stride);
    let goals = slice::from_raw_parts(goals, frames*width);
    let output = slice::from_raw_parts_mut(output, frames*3);
    if segments.iter().chain(goals).any(|x| !x.is_finite()) { return 0; }
    let solve = |f: usize, result: &mut [f64]| {
        let goal = &goals[f*width..(f+1)*width];
        result.copy_from_slice(&[goal.iter().map(|v| v*v).sum(),0.0,0.0]);
        for s in segments.chunks_exact(stride) {
            let start = &s[3..3+width];
            let end = &s[3+width..];
            let mut denominator = 0.0;
            let mut numerator = 0.0;
            for i in 0..width {
                let d = end[i]-start[i];
                denominator += d*d;
                numerator += (goal[i]-start[i])*d;
            }
            let t = if denominator > 1e-12 { (numerator/denominator).clamp(0.0,1.0) } else { 0.0 };
            let error: f64 = (0..width).map(|i| {
                let r = goal[i]-start[i]-(end[i]-start[i])*t; r*r
            }).sum();
            if error < result[0]-1e-12 {
                result.copy_from_slice(&[error,s[0],s[1]+(s[2]-s[1])*t]);
            }
        }
    };
    if frames > 32 {
        use rayon::prelude::*;
        output.par_chunks_mut(3).enumerate().for_each(|(f,row)| solve(f,row));
    } else {
        for (f,row) in output.chunks_mut(3).enumerate() { solve(f,row); }
    }
    1
}
