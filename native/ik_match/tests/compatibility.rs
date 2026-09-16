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
