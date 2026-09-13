// SPDX-License-Identifier: GPL-2.0-or-later
//! Experimental, versioned C ABI. Buffers belong to the caller; no Blender API.
use crate::capture;
use crate::pose;
use rayon::prelude::*;
use std::sync::OnceLock;
use std::{
    panic::{catch_unwind, AssertUnwindSafe},
    ptr, slice,
};

/// # Safety
/// `data` must point to `len` readable bytes. Returned handles must be released
/// exactly once with sub_ik_free and not used concurrently or after release.
#[no_mangle]
pub unsafe extern "C" fn sub_ik_create(data: *const u8, len: usize) -> *mut pose::Case {
    if data.is_null() || len == 0 || len > 1_000_000 {
        return ptr::null_mut();
    }
    catch_unwind(|| {
        let case: pose::Case = serde_json::from_slice(slice::from_raw_parts(data, len)).ok()?;
        if case.job.segments.is_empty()
            || case.job.segments.len() > 16
            || case.deltas.len() != case.job.segments.len()
            || case.job.iterations == 0
            || case.job.iterations > 10000
        {
            return None;
        }
        Some(Box::into_raw(Box::new(case)))
    })
    .ok()
    .flatten()
    .unwrap_or(ptr::null_mut())
}

/// # Safety
/// Same buffer ownership and handle lifetime requirements as sub_ik_create.
#[no_mangle]
pub unsafe extern "C" fn sub_ik_create_raw(data: *const u8, len: usize) -> *mut pose::Case {
    if data.is_null() || len == 0 || len > 1_000_000 {
        return ptr::null_mut();
    }
    catch_unwind(|| {
        let input: capture::Input =
            serde_json::from_slice(slice::from_raw_parts(data, len)).ok()?;
        Some(Box::into_raw(Box::new(capture::convert(input))))
    })
    .ok()
    .flatten()
    .unwrap_or(ptr::null_mut())
}

/// # Safety
/// `handle` must be live and exclusively borrowed, and `output` must point to
/// `len` writable floats. No pointers or references are retained after return.
#[no_mangle]
pub unsafe extern "C" fn sub_ik_solve(
    handle: *mut pose::Case,
    angle: f32,
    output: *mut f32,
    len: usize,
) -> i32 {
    if handle.is_null() || output.is_null() || !angle.is_finite() {
        return 0;
    }
    catch_unwind(AssertUnwindSafe(|| {
        let case = &mut *handle;
        if len != case.deltas.len() * 16 {
            return 0;
        }
        case.job.angle = angle as f64;
        let result = pose::solve_fast(case);
        let target = slice::from_raw_parts_mut(output, len);
        for (dst, src) in target
            .iter_mut()
            .zip(result.matrices.iter().flatten().flatten())
        {
            if !src.is_finite() {
                return 0;
            }
            *dst = *src;
        }
        if result.kernel.converged {
            1
        } else {
            2
        }
    }))
    .unwrap_or(0)
}

/// # Safety
/// The handle must be null or a live handle returned by sub_ik_create.
#[no_mangle]
pub unsafe extern "C" fn sub_ik_free(handle: *mut pose::Case) {
    if !handle.is_null() {
        drop(Box::from_raw(handle));
    }
}

#[no_mangle]
pub extern "C" fn sub_ik_abi_version() -> u32 {
    3
}

/// Run the whole pole search for one chain and frame.
///
/// `reference` is `bones * 16` float32 values, bone-major then column-major,
/// matching the order `ik_channels` builds `reference_columns` in. `seeds`
/// points at the three candidate angles.
///
/// Returns 1 on success, 0 on a malformed request, and 2 when the caller must
/// fall back to Blender -- the same meaning status 2 carries in sub_ik_solve.
///
/// # Safety
/// The handle must be live. `reference` holds `reference_len` readable floats,
/// `seeds` three readable doubles, and `out_matrices` `out_len` writable
/// floats that do not overlap the inputs.
#[no_mangle]
pub unsafe extern "C" fn sub_ik_search(
    handle: *mut pose::Case,
    reference: *const f32,
    reference_len: usize,
    seeds: *const f64,
    tolerance: f64,
    refine_steps: usize,
    out_angle: *mut f64,
    out_matrices: *mut f32,
    out_len: usize,
) -> i32 {
    if handle.is_null()
        || reference.is_null()
        || seeds.is_null()
        || out_angle.is_null()
        || out_matrices.is_null()
        || refine_steps > 1000
    {
        return 0;
    }
    catch_unwind(AssertUnwindSafe(|| {
        let case = &mut *handle;
        let bones = reference_len / 16;
        if bones == 0 || reference_len % 16 != 0 || out_len != bones * 16 {
            return 0;
        }
        let flat = slice::from_raw_parts(reference, reference_len);
        if flat.iter().any(|v| !v.is_finite()) {
            return 0;
        }
        let columns: Vec<pose::Columns> = (0..bones)
            .map(|b| std::array::from_fn(|c| std::array::from_fn(|r| flat[b * 16 + c * 4 + r])))
            .collect();
        let seeds = slice::from_raw_parts(seeds, 3);
        if seeds.iter().any(|v| !v.is_finite()) || !tolerance.is_finite() {
            return 0;
        }
        let found = pose::search(
            case,
            &columns,
            [seeds[0], seeds[1], seeds[2]],
            tolerance,
            refine_steps,
        );
        let Some((angle, matrices)) = found else {
            return 2;
        };
        let target = slice::from_raw_parts_mut(out_matrices, out_len);
        for (dst, src) in target
            .iter_mut()
            .zip(matrices.iter().flatten().flatten())
        {
            if !src.is_finite() {
                return 0;
            }
            *dst = *src;
        }
        *out_angle = angle;
        1
    }))
    .unwrap_or(0)
}

/// # Safety
/// The handle must be live and remain immutable for this diagnostic call.
#[no_mangle]
pub unsafe extern "C" fn sub_ik_iterations(handle: *const pose::Case) -> usize {
    if handle.is_null() {
        return 0;
    }
    catch_unwind(|| crate::solver::solve(&(*handle).job).iterations).unwrap_or(0)
}

/// # Safety
/// `handles`/`angles` point to `count` entries; each handle is live and remains
/// immutable for this call. `output` holds `len` writable floats and does not
/// overlap inputs. Work uses owned numeric copies; no pointers enter the pool.
#[no_mangle]
pub unsafe extern "C" fn sub_ik_solve_many(
    handles: *const *mut pose::Case,
    angles: *const f32,
    count: usize,
    output: *mut f32,
    len: usize,
    threads: usize,
    statuses: *mut u8,
) -> bool {
    if handles.is_null()
        || angles.is_null()
        || output.is_null()
        || statuses.is_null()
        || count == 0
        || count > 16
        || ![1, 4].contains(&threads)
    {
        return false;
    }
    catch_unwind(AssertUnwindSafe(|| {
        let handles = slice::from_raw_parts(handles, count);
        let angles = slice::from_raw_parts(angles, count);
        if handles.iter().any(|p| p.is_null()) || angles.iter().any(|v| !v.is_finite()) {
            return false;
        }
        let cases: Vec<_> = handles
            .iter()
            .zip(angles)
            .map(|(&p, &angle)| {
                let mut case = (*p).clone();
                case.job.angle = angle as f64;
                case
            })
            .collect();
        if cases.iter().map(|c| c.deltas.len() * 16).sum::<usize>() != len {
            return false;
        }
        let results: Vec<_> = if threads == 1 {
            cases.iter().map(pose::solve_fast).collect()
        } else {
            static POOL: OnceLock<rayon::ThreadPool> = OnceLock::new();
            let pool = POOL.get_or_init(|| {
                rayon::ThreadPoolBuilder::new()
                    .num_threads(4)
                    .build()
                    .expect("IK thread pool")
            });
            pool.install(|| cases.par_iter().map(pose::solve_fast).collect())
        };
        let values: Vec<_> = results
            .iter()
            .flat_map(|r| r.matrices.iter().flatten().flatten().copied())
            .collect();
        if values.iter().any(|v| !v.is_finite()) {
            return false;
        }
        slice::from_raw_parts_mut(output, len).copy_from_slice(&values);
        for (i, result) in results.iter().enumerate() {
            *statuses.add(i) = if result.kernel.converged { 1 } else { 2 };
        }
        true
    }))
    .unwrap_or(false)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn abi_version_advertises_the_search() {
        // Bumped with sub_ik_search: an add-on holding an older DLL must be
        // refused on this check rather than calling a missing symbol.
        assert_eq!(sub_ik_abi_version(), 3);
    }
    #[test]
    fn search_rejects_malformed_requests() {
        let seeds = [0.0f64; 3];
        let mut angle = 0.0f64;
        let mut out = [0.0f32; 32];
        unsafe {
            assert_eq!(
                sub_ik_search(ptr::null_mut(), ptr::null(), 0, seeds.as_ptr(), 1e-9, 12,
                              &mut angle, out.as_mut_ptr(), out.len()),
                0
            );
        }
    }
    #[test]
    fn ffi_buffers_and_thread_counts() {
        let fixture: serde_json::Value =
            serde_json::from_str(include_str!("../tests/data/compatibility.json")).unwrap();
        let bytes = serde_json::to_vec(&fixture[0]).unwrap();
        let angle = fixture[0]["angle"].as_f64().unwrap() as f32;
        unsafe {
            assert!(sub_ik_create(ptr::null(), 0).is_null());
            assert!(sub_ik_create(b"bad".as_ptr(), 3).is_null());
            let handle = sub_ik_create(bytes.as_ptr(), bytes.len());
            assert!(!handle.is_null());
            let mut single = vec![0.0; (*handle).deltas.len() * 16];
            assert_eq!(
                sub_ik_solve(handle, angle, single.as_mut_ptr(), single.len() - 1),
                0
            );
            assert_eq!(
                sub_ik_solve(handle, angle, single.as_mut_ptr(), single.len()),
                1
            );
            for threads in [1, 4] {
                let mut batch = vec![0.0; single.len()];
                let mut status = 0u8;
                assert!(sub_ik_solve_many(
                    &handle,
                    &angle,
                    1,
                    batch.as_mut_ptr(),
                    batch.len(),
                    threads,
                    &mut status
                ));
                assert_eq!(status, 1);
                assert_eq!(single, batch);
            }
            sub_ik_free(handle);
            sub_ik_free(ptr::null_mut());
        }
    }
}
