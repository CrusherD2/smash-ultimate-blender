// SPDX-License-Identifier: GPL-2.0-or-later
//! Detached evaluation of the generated component graph. Never accesses Blender.
use crate::component_math::{self, identity, inverse, mul, trs, Mat};
use serde::Deserialize;
use std::{panic::catch_unwind, ptr, slice};
type Blend = unsafe extern "C" fn(*const f32, *const f32, f32, *mut f32) -> i32;
type Convert = unsafe extern "C" fn(usize, bool, *const f32, *const f32, *mut f32) -> i32;
fn full_influence() -> f64 {
    1.0
}
#[derive(Deserialize)]
struct Expr {
    op: String,
    #[serde(default)]
    value: f64,
    #[serde(default)]
    index: usize,
    #[serde(default)]
    args: Vec<Expr>,
}
impl Expr {
    fn eval(&self, vars: &[f64]) -> Option<f64> {
        let arg = |i: usize| self.args.get(i)?.eval(vars);
        let v = match self.op.as_str() {
            "value" => self.value,
            "var" => *vars.get(self.index)?,
            "add" => arg(0)? + arg(1)?,
            "sub" => arg(0)? - arg(1)?,
            "mul" => arg(0)? * arg(1)?,
            "div" => arg(0)? / arg(1)?,
            "pow" => arg(0)?.powf(arg(1)?),
            "mod" | "floordiv" => {
                let a = arg(0)?;
                let b = arg(1)?;
                if b == 0.0 {
                    return None;
                }
                let mut rem = a % b;
                let mut div = (a - rem) / b;
                if rem != 0.0 && (rem < 0.0) != (b < 0.0) {
                    rem += b;
                    div -= 1.0;
                }
                if self.op == "mod" {
                    if rem == 0.0 {
                        0.0_f64.copysign(b)
                    } else {
                        rem
                    }
                } else {
                    let floor = div.floor();
                    if div - floor > 0.5 {
                        floor + 1.0
                    } else {
                        floor
                    }
                }
            }
            "neg" => -arg(0)?,
            "sin" => arg(0)?.sin(),
            "cos" => arg(0)?.cos(),
            "tan" => arg(0)?.tan(),
            "asin" => arg(0)?.asin(),
            "acos" => arg(0)?.acos(),
            "atan" => arg(0)?.atan(),
            "atan2" => arg(0)?.atan2(arg(1)?),
            "sqrt" => arg(0)?.sqrt(),
            "exp" => arg(0)?.exp(),
            "log" => arg(0)?.ln(),
            "log10" => arg(0)?.log10(),
            "abs" => arg(0)?.abs(),
            "floor" => arg(0)?.floor(),
            "ceil" => arg(0)?.ceil(),
            "trunc" => arg(0)?.trunc(),
            "degrees" => arg(0)?.to_degrees(),
            "radians" => arg(0)?.to_radians(),
            "if" => {
                if arg(0)? != 0.0 {
                    arg(1)?
                } else {
                    arg(2)?
                }
            }
            "not" => (arg(0)? == 0.0) as u8 as f64,
            "and" | "or" => {
                let mut value = arg(0)?;
                for i in 1..self.args.len() {
                    if (self.op == "and" && value == 0.0) || (self.op == "or" && value != 0.0) {
                        break;
                    }
                    value = arg(i)?;
                }
                value
            }
            "min" | "max" | "sum" | "average" => {
                let mut value = arg(0)?;
                for i in 1..self.args.len() {
                    let next = arg(i)?;
                    value = match self.op.as_str() {
                        "min" => value.min(next),
                        "max" => value.max(next),
                        _ => value + next,
                    };
                }
                if self.op == "average" {
                    value / self.args.len() as f64
                } else {
                    value
                }
            }
            "ne" => (arg(0)? != arg(1)?) as u8 as f64,
            "lt" => (arg(0)? < arg(1)?) as u8 as f64,
            "le" => (arg(0)? <= arg(1)?) as u8 as f64,
            "gt" => (arg(0)? > arg(1)?) as u8 as f64,
            "ge" => (arg(0)? >= arg(1)?) as u8 as f64,
            "eq" => {
                if arg(0)? == arg(1)? {
                    1.0
                } else {
                    0.0
                }
            }
            _ => return None,
        };
        if v.is_finite() {
            Some(v)
        } else {
            None
        }
    }
}
#[derive(Deserialize)]
struct Variable {
    node: usize,
    channel: usize,
    #[serde(default)]
    value: Option<f64>,
    #[serde(default)]
    world: bool,
    #[serde(default)]
    order: usize,
    #[serde(default)]
    compatible: bool,
}
#[derive(Deserialize)]
struct Driver {
    channel: usize,
    vars: Vec<Variable>,
    expression: Expr,
}
#[derive(Deserialize)]
struct Constraint {
    kind: String,
    #[serde(default)]
    target: usize,
    #[serde(default)]
    mode: String,
    #[serde(default)]
    target_local: bool,
    #[serde(default)]
    low: [f64; 3],
    #[serde(default)]
    high: [f64; 3],
    #[serde(default)]
    to_low: [f64; 3],
    #[serde(default)]
    to_high: [f64; 3],
    #[serde(default)]
    mapping: [usize; 3],
    #[serde(default)]
    extrapolate: bool,
    #[serde(default)]
    axis: usize,
    #[serde(default)]
    sign: f64,
    #[serde(default = "full_influence")]
    influence: f64,
    #[serde(default)]
    order: usize,
    #[serde(default)]
    owner_space: String,
    #[serde(default)]
    target_space: String,
    #[serde(default)]
    axes: [bool; 3],
    #[serde(default)]
    invert_axes: [bool; 3],
    #[serde(default)]
    offset: bool,
    #[serde(default)]
    uniform: bool,
    #[serde(default)]
    multiply: bool,
    #[serde(default)]
    legacy: bool,
    #[serde(default = "full_influence")]
    power: f64,
    #[serde(default = "identity")]
    inverse_matrix: Mat,
    #[serde(default)]
    target_matrix: Option<Mat>,
    #[serde(default)]
    channels: [bool; 9],
    #[serde(default)]
    target_order: usize,
}
#[derive(Deserialize)]
struct Node {
    parent: Option<usize>,
    offset: Mat,
    external: bool,
    drivers: Vec<Driver>,
    constraints: Vec<Constraint>,
    #[serde(default)]
    connected: bool,
    #[serde(default)]
    custom_inheritance: bool,
    #[serde(default)]
    driver_local: bool,
    #[serde(default = "identity")]
    rest: Mat,
    #[serde(default)]
    inherit_scale: String,
    #[serde(default)]
    no_inherit_rotation: bool,
    #[serde(default)]
    no_local_location: bool,
}
#[derive(Deserialize)]
pub struct Graph {
    nodes: Vec<Node>,
    #[serde(default = "identity")]
    object_world: Mat,
}
struct Evaluation<'a> {
    graph: &'a Graph,
    input: &'a [f64],
    external: &'a [f64],
    states: Vec<u8>,
    world: Vec<Mat>,
    local: Vec<Mat>,
    channels: Vec<[f64; 10]>,
    bases: Option<&'a [f64]>,
}
impl Evaluation<'_> {
    fn node(&mut self, i: usize) -> Option<()> {
        if i >= self.states.len() {
            return None;
        }
        if self.states[i] == 2 {
            return Some(());
        }
        if self.states[i] == 1 {
            return None;
        }
        self.states[i] = 1;
        let n = &self.graph.nodes[i];
        if n.external {
            self.world[i] = std::array::from_fn(|r| {
                std::array::from_fn(|c| self.external[i * 16 + r * 4 + c] as f32)
            });
            self.states[i] = 2;
            return Some(());
        }
        let mut v: [f64; 10] = self.input[i * 10..i * 10 + 10].try_into().ok()?;
        for d in &n.drivers {
            let mut vars = Vec::with_capacity(d.vars.len());
            for var in &d.vars {
                if let Some(value) = var.value {
                    vars.push(value);
                } else if var.channel == 9 {
                    vars.push(*self.input.get(var.node * 10 + 9)?);
                } else {
                    self.node(var.node)?;
                    let matrix = if var.world {
                        mul(self.graph.object_world, self.world[var.node])
                    } else {
                        self.local[var.node]
                    };
                    let value = match var.channel {
                        0..=2 => matrix[var.channel][3],
                        3..=5 => {
                            let angles = component_math::to_euler(matrix, var.order);
                            let old =
                                std::array::from_fn(|i| self.input[var.node * 10 + 3 + i] as f32);
                            (if var.compatible {
                                component_math::compatible(angles, old)
                            } else {
                                angles
                            })[var.channel - 3]
                        }
                        6..=8 => component_math::sizes(matrix)[var.channel - 6],
                        11 => component_math::det(matrix).cbrt(),
                        _ => return None,
                    };
                    vars.push(value as f64);
                }
            }
            *v.get_mut(d.channel)? = d.expression.eval(&vars)? as f32 as f64;
        }
        let mut local = if n.drivers.is_empty() && self.bases.is_some() {
            let data = self.bases?;
            std::array::from_fn(|r| std::array::from_fn(|c| data[i * 16 + r * 4 + c] as f32))
        } else {
            trs(&v)
        };
        if n.connected {
            for r in 0..3 {
                local[r][3] = 0.0;
            }
        }
        let parent = if let Some(p) = n.parent {
            self.node(p)?;
            self.world[p]
        } else {
            identity()
        };
        let parent_rest = n
            .parent
            .map(|p| self.graph.nodes[p].rest)
            .unwrap_or(identity());
        let native_parent = crate::component_space::parent_transform(
            if n.parent.is_some() { n.offset } else { n.rest },
            parent_rest,
            n.parent.map(|_| parent),
            &n.inherit_scale,
            !n.no_inherit_rotation,
            !n.no_local_location,
        );
        let convert =
            |matrix: Mat, invert: bool| -> Option<Mat> { native_parent.apply(matrix, invert) };
        let mut world = convert(local, false)?;
        let initial_location = [world[0][3], world[1][3], world[2][3]];
        for con in &n.constraints {
            let previous = world;
            // Constraints read evaluated LOCAL space, including the pose-to-bone
            // round trip. Reusing raw basis channels loses Blender rounding,
            // amplified by short slider ranges on large translated rigs.
            local = convert(world, true)?;
            match con.kind.as_str() {
                "limit_rotation" | "limit_scale" | "copy_location" | "copy_rotation"
                | "copy_scale" | "child_of" => {
                    let mut matrix = match con.owner_space.as_str() {
                        "LOCAL" => local,
                        "POSE" => world,
                        "WORLD" => mul(self.graph.object_world, world),
                        _ => return None,
                    };
                    let target = if let Some(matrix) = con.target_matrix {
                        matrix
                    } else if matches!(
                        con.kind.as_str(),
                        "copy_location" | "copy_rotation" | "copy_scale" | "child_of"
                    ) {
                        self.node(con.target)?;
                        match con.target_space.as_str() {
                            "LOCAL" => self.local[con.target],
                            "POSE" => self.world[con.target],
                            "WORLD" => mul(self.graph.object_world, self.world[con.target]),
                            _ => return None,
                        }
                    } else {
                        identity()
                    };
                    match con.kind.as_str() {
                        "limit_rotation" => {
                            matrix = component_math::limit_rotation(
                                matrix, con.low, con.high, con.axes, con.order, con.legacy,
                            )
                        }
                        "copy_location" => {
                            for c in 0..3 {
                                if con.axes[c] {
                                    matrix[c][3] = target[c][3]
                                        * (if con.invert_axes[c] { -1.0 } else { 1.0 })
                                        + if con.offset { matrix[c][3] } else { 0.0 };
                                }
                            }
                        }
                        "copy_rotation" => {
                            matrix = component_math::copy_rotation(
                                matrix,
                                target,
                                con.axes,
                                con.invert_axes,
                                con.order,
                                &con.mode,
                            )
                        }
                        "child_of" => {
                            let (target, inv) = if con.channels.iter().all(|v| *v) {
                                (target, con.inverse_matrix)
                            } else {
                                (
                                    component_math::filter_transform(
                                        target,
                                        con.channels,
                                        con.target_order,
                                    ),
                                    component_math::filter_transform(
                                        con.inverse_matrix,
                                        con.channels,
                                        con.order,
                                    ),
                                )
                            };
                            let original = matrix;
                            matrix = mul(mul(target, inv), matrix);
                            for c in 0..3 {
                                if !con.channels[c] {
                                    matrix[c][3] = original[c][3];
                                }
                            }
                        }
                        _ => {
                            let old = component_math::sizes(matrix);
                            let mut size = if con.kind == "limit_scale" {
                                old
                            } else {
                                component_math::sizes(target)
                            };
                            if con.kind == "limit_scale" {
                                for c in 0..3 {
                                    size[c] =
                                        size[c].max(con.low[c] as f32).min(con.high[c] as f32);
                                }
                            } else {
                                if con.uniform {
                                    let total = if con.axes.iter().all(|v| *v) {
                                        component_math::det(target).abs()
                                    } else {
                                        (0..3).filter(|i| con.axes[*i]).map(|i| size[i]).product()
                                    };
                                    size = [(total as f64).cbrt() as f32; 3];
                                }
                                for c in 0..3 {
                                    size[c] = size[c].powf(con.power as f32);
                                    if con.offset {
                                        size[c] = if con.multiply {
                                            size[c] * old[c]
                                        } else {
                                            size[c] + old[c] - 1.0
                                        };
                                    }
                                }
                            }
                            for c in 0..3 {
                                if old[c] != 0.0
                                    && (con.kind == "limit_scale" || con.axes[c] || con.uniform)
                                {
                                    for r in 0..3 {
                                        matrix[r][c] *= size[c] / old[c];
                                    }
                                }
                            }
                        }
                    }
                    world = match con.owner_space.as_str() {
                        "LOCAL" => convert(matrix, false)?,
                        "POSE" => matrix,
                        "WORLD" => mul(inverse(self.graph.object_world)?, matrix),
                        _ => return None,
                    };
                    local = convert(world, true)?;
                }
                "limit" => {
                    for c in 0..3 {
                        local[c][3] = local[c][3].clamp(con.low[c] as f32, con.high[c] as f32);
                    }
                    world = convert(local, false)?;
                }
                "transform" => {
                    self.node(con.target)?;
                    let target = self.local[con.target];
                    let mut rotation = [0.0_f32; 3];
                    for c in 0..3 {
                        let a = con.mapping[c];
                        if a >= 3 {
                            return None;
                        }
                        let low = con.low[a] as f32;
                        let high = con.high[a] as f32;
                        let value = if con.extrapolate {
                            target[a][3]
                        } else {
                            target[a][3].clamp(low, high)
                        };
                        let span = high - low;
                        let t = if span != 0.0 {
                            (value - low) / span
                        } else {
                            0.0
                        };
                        rotation[c] = con.to_low[c] as f32
                            + t * (con.to_high[c] as f32 - con.to_low[c] as f32);
                    }
                    local = component_math::transform_after(local, rotation, con.order);
                    world = convert(local, false)?;
                }
                "copy" => {
                    self.node(con.target)?;
                    let target = if con.target_local {
                        self.local[con.target]
                    } else {
                        self.world[con.target]
                    };
                    world = match con.mode.as_str() {
                        "replace" => target,
                        "after" => mul(world, target),
                        "before" => mul(target, world),
                        _ => return None,
                    };
                    local = convert(world, true)?;
                }
                "track" => {
                    let object_world = self.graph.object_world;
                    let target_world = if let Some(matrix) = con.target_matrix {
                        matrix
                    } else {
                        self.node(con.target)?;
                        mul(object_world, self.world[con.target])
                    };
                    world = mul(object_world, world);
                    let direction = std::array::from_fn(|r| target_world[r][3] - world[r][3]);
                    world =
                        component_math::damped_track(world, direction, con.axis, con.sign < 0.0);
                    world = mul(inverse(object_world)?, world);
                    local = convert(world, true)?;
                }
                _ => return None,
            }
            if con.influence != 1.0 {
                // Same polar-interpolation method as Blender, entirely native.
                let a = mul(self.graph.object_world, previous);
                let b = mul(self.graph.object_world, world);
                let result = crate::component_blend::interpolate(a, b, con.influence as f32)?;
                world = mul(inverse(self.graph.object_world)?, result);
                local = convert(world, true)?;
            }
        }
        if n.connected {
            for r in 0..3 {
                world[r][3] = initial_location[r];
            }
            local = convert(world, true)?;
        }
        self.channels[i] = v;
        self.world[i] = world;
        self.local[i] = convert(world, true)?;
        self.states[i] = 2;
        Some(())
    }
}
#[no_mangle]
pub unsafe extern "C" fn sub_component_graph_create(data: *const u8, len: usize) -> *mut Graph {
    if data.is_null() || len == 0 || len > 16000000 {
        return ptr::null_mut();
    }
    catch_unwind(|| {
        let graph: Graph = serde_json::from_slice(slice::from_raw_parts(data, len)).ok()?;
        if graph.nodes.is_empty() || graph.nodes.len() > 4096 {
            return None;
        }
        Some(Box::into_raw(Box::new(graph)))
    })
    .ok()
    .flatten()
    .unwrap_or(ptr::null_mut())
}
#[no_mangle]
pub unsafe extern "C" fn sub_component_graph_free(graph: *mut Graph) {
    if !graph.is_null() {
        drop(Box::from_raw(graph));
    }
}
#[no_mangle]
pub unsafe extern "C" fn sub_component_graph_eval(
    graph: *const Graph,
    input: *const f64,
    external: *const f64,
    output: *mut f64,
) -> i32 {
    sub_component_graph_eval_basis(graph, input, external, ptr::null(), output)
}

#[no_mangle]
pub extern "C" fn sub_component_graph_abi_version() -> u32 {
    5
}

#[no_mangle]
pub unsafe extern "C" fn sub_component_graph_eval_basis(
    graph: *const Graph,
    input: *const f64,
    external: *const f64,
    bases: *const f64,
    output: *mut f64,
) -> i32 {
    sub_component_graph_eval_blend(graph, input, external, bases, output, None, None)
}

#[no_mangle]
pub unsafe extern "C" fn sub_component_graph_eval_blend(
    graph: *const Graph,
    input: *const f64,
    external: *const f64,
    bases: *const f64,
    output: *mut f64,
    _blend: Option<Blend>,
    _convert: Option<Convert>,
) -> i32 {
    if graph.is_null() || input.is_null() || external.is_null() || output.is_null() {
        return 0;
    }
    catch_unwind(|| {
        let graph = &*graph;
        let count = graph.nodes.len();
        let input = slice::from_raw_parts(input, count * 10);
        let external = slice::from_raw_parts(external, count * 16);
        let bases = if bases.is_null() {
            None
        } else {
            Some(slice::from_raw_parts(bases, count * 16))
        };
        if input.iter().chain(external).any(|v| !v.is_finite()) {
            return None;
        }
        if bases.is_some_and(|data| data.iter().any(|v| !v.is_finite())) {
            return None;
        }
        let mut eval = Evaluation {
            graph,
            input,
            external,
            states: vec![0; count],
            world: vec![identity(); count],
            local: vec![identity(); count],
            channels: vec![[0.0; 10]; count],
            bases,
        };
        for i in 0..count {
            eval.node(i)?;
        }
        let out = slice::from_raw_parts_mut(output, count * 16);
        for i in 0..count {
            for r in 0..4 {
                for c in 0..4 {
                    out[i * 16 + r * 4 + c] = eval.world[i][r][c] as f64;
                }
            }
        }
        if out.iter().all(|v| v.is_finite()) {
            Some(1)
        } else {
            None
        }
    })
    .ok()
    .flatten()
    .unwrap_or(0)
}
