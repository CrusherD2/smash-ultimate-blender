// SPDX-License-Identifier: GPL-2.0-or-later
use rayon::prelude::*;
use serde::{Deserialize, Serialize};
use std::{fs, time::Instant};
use sub_ik_match_native::pose;

#[derive(Deserialize)]
struct Input {
    jobs: Vec<pose::Case>,
}
#[derive(Serialize)]
struct Report {
    threads: usize,
    jobs: usize,
    median_seconds: f64,
    runs: Vec<f64>,
    results: Vec<pose::Result>,
}
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() < 3 {
        return Err("usage: sub_ik_match_probe input.json output.json [threads] [runs]".into());
    }
    let input: Input = serde_json::from_slice(&fs::read(&args[1])?)?;
    let threads = args
        .get(3)
        .map(|v| v.parse())
        .transpose()?
        .unwrap_or(1usize);
    let runs = args
        .get(4)
        .map(|v| v.parse())
        .transpose()?
        .unwrap_or(7usize);
    if threads == 0 || runs == 0 {
        return Err("threads and runs must be positive".into());
    }
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(threads)
        .build()?;
    let execute = || pool.install(|| input.jobs.par_iter().map(pose::solve).collect::<Vec<_>>());
    let reference = execute();
    let mut times = Vec::new();
    for _ in 0..runs {
        let start = Instant::now();
        let result = execute();
        times.push(start.elapsed().as_secs_f64());
        assert!(
            reference
                .iter()
                .zip(&result)
                .all(|(a, b)| a.kernel.changes == b.kernel.changes && a.matrices == b.matrices),
            "nondeterministic kernel"
        );
        std::hint::black_box(result);
    }
    let mut sorted = times.clone();
    sorted.sort_by(f64::total_cmp);
    let report = Report {
        threads,
        jobs: input.jobs.len(),
        median_seconds: sorted[sorted.len() / 2],
        runs: times,
        results: reference,
    };
    fs::write(&args[2], serde_json::to_vec(&report)?)?;
    println!(
        "{} jobs, {} threads, median {:.6} seconds",
        report.jobs, threads, report.median_seconds
    );
    Ok(())
}
