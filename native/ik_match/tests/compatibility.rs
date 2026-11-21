use serde::Deserialize;
use sub_ik_match_native::pose;

#[derive(Deserialize)]
struct Fixture {
    #[serde(flatten)]
    case: pose::Case,
    expected: Vec<pose::Mat4>,
}

#[test]
fn captured_blender_matrices_are_exact() {
    let cases: Vec<Fixture> =
        serde_json::from_str(include_str!("data/compatibility.json")).unwrap();
    assert!(!cases.is_empty());
    for case in cases {
        assert_eq!(
            pose::solve(&case.case).matrices,
            case.expected,
            "{}",
            case.case.job.id
        );
    }
}

#[test]
fn calibration_recovers_a_captured_bend_direction() {
    let cases: Vec<Fixture> =
        serde_json::from_str(include_str!("data/compatibility.json")).unwrap();
    let mut case = cases[0].case.clone();
    case.job.angle = 0.3;
    let target = pose::solve_fast(&case).matrices;
    let root: [f32; 3] = std::array::from_fn(|i| target[0][i][3]);
    let mid: [f32; 3] = std::array::from_fn(|i| target[1][i][3]);
    let mut axis: [f32; 3] = std::array::from_fn(|i|
        mid[i] + target[1][i][1] * case.job.segments[1].length as f32 - root[i]);
    let length = axis.iter().map(|v| v*v).sum::<f32>().sqrt();
    for value in &mut axis { *value /= length; }
    let points = [root[0],root[1],root[2],mid[0],mid[1],mid[2],axis[0],axis[1],axis[2]];
    let (_, matrices) = pose::calibrate(&mut case, points, 0.).unwrap();
    let squared: f32 = (0..3).map(|i| (matrices[1][i][3]-mid[i]).powi(2)).sum();
    assert!(squared < 1e-8, "middle joint error: {squared}");
}
