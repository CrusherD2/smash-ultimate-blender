use crate::{capture::Input, math::Backend};

pub fn decode(values: &[f32], bones: usize, iterations: usize, backend: u32) -> Option<Input> {
    if !(1..=16).contains(&bones)
        || !(1..=10000).contains(&iterations)
        || values.len() != 64 + bones * 32
        || values.iter().any(|value| !value.is_finite())
        || backend > 1
    {
        return None;
    }
    let matrix = |offset: usize| std::array::from_fn(|r| {
        std::array::from_fn(|c| values[offset + r * 4 + c])
    });
    let mut input = Input {
        parent: matrix(0), object: matrix(16), target: matrix(32), pole: matrix(48),
        poses: Vec::with_capacity(bones), rests: Vec::with_capacity(bones),
        heads: Vec::with_capacity(bones), tails: Vec::with_capacity(bones),
        lengths: Vec::with_capacity(bones), iterations,
        backend: if backend == 1 { Backend::Eigen } else { Backend::Approximate },
    };
    // Four row-major matrices, then pose/rest/head/tail/length per bone.
    for index in 0..bones {
        let start = 64 + index * 32;
        input.poses.push(matrix(start));
        input.rests.push(std::array::from_fn(|r| {
            std::array::from_fn(|c| values[start + 16 + r * 3 + c])
        }));
        input.heads.push(std::array::from_fn(|c| values[start + 25 + c]));
        input.tails.push(std::array::from_fn(|c| values[start + 28 + c]));
        input.lengths.push(values[start + 31]);
    }
    Some(input)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{capture, pose};

    #[test]
    fn packed_and_json_capture_are_identical() {
        let identity = [1.,0.,0.,0., 0.,1.,0.,0., 0.,0.,1.,0., 0.,0.,0.,1.];
        let mut packed = identity.repeat(4);
        for y in [0., 1.] {
            let mut matrix = identity;
            matrix[7] = y;
            packed.extend(matrix);
            packed.extend([1.,0.,0., 0.,1.,0., 0.,0.,1.]);
            packed.extend([0.,y,0., 0.,y+1.,0., 1.]);
        }
        let input = decode(&packed, 2, 100, 0).unwrap();
        let json = serde_json::json!({
            "parent":input.parent,"object":input.object,"target":input.target,"pole":input.pole,
            "poses":input.poses,"rests":input.rests,"heads":input.heads,"tails":input.tails,
            "lengths":input.lengths,"iterations":input.iterations
        });
        let from_json: Input = serde_json::from_value(json).unwrap();
        let expected = capture::convert(from_json);
        let actual = capture::convert(decode(&packed, 2, 100, 0).unwrap());
        assert_eq!(actual.parent, expected.parent);
        assert_eq!(actual.deltas, expected.deltas);
        assert_eq!(pose::solve_fast(&actual).matrices, pose::solve_fast(&expected).matrices);
        assert!(decode(&packed[..127], 2, 100, 0).is_none());
        assert!(decode(&packed, 0, 100, 0).is_none());
        assert!(decode(&packed, usize::MAX, 100, 0).is_none());
        assert!(decode(&packed, 2, 0, 0).is_none());
        assert!(decode(&packed, 2, 100, 2).is_none());
        packed[0] = f32::NAN;
        assert!(decode(&packed, 2, 100, 0).is_none());
    }
}
