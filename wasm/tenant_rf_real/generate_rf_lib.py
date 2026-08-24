#!/usr/bin/env python3

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

m = json.loads(
    (ROOT / "models/random_forest/breast_cancer/model_packed.json").read_text()
)

N_FEATURES = len(m["mean"])
N_TREES = m["n_estimators"]
N_NODES = m["total_nodes"]

def f32_array(values):
    return "[" + ", ".join(
        f"{float(v):.10e}f32" for v in values
    ) + "]"

def i32_array(values):
    return "[" + ", ".join(
        str(int(v)) for v in values
    ) + "]"

def usize_array(values):
    return "[" + ", ".join(
        str(int(v)) for v in values
    ) + "]"

code = f'''const N_FEATURES: usize = {N_FEATURES};
const N_TREES: usize = {N_TREES};
const N_NODES: usize = {N_NODES};

const MEAN: [f32; N_FEATURES] =
    {f32_array(m["mean"])};

const SCALE: [f32; N_FEATURES] =
    {f32_array(m["scale"])};

const TREE_OFFSETS: [usize; N_TREES + 1] =
    {usize_array(m["tree_offsets"])};

const CHILDREN_LEFT: [i32; N_NODES] =
    {i32_array(m["children_left"])};

const CHILDREN_RIGHT: [i32; N_NODES] =
    {i32_array(m["children_right"])};

const FEATURE: [i32; N_NODES] =
    {i32_array(m["feature"])};

const THRESHOLD: [f32; N_NODES] =
    {f32_array(m["threshold"])};

const LEAF_CLASS: [i32; N_NODES] =
    {i32_array(m["leaf_class"])};

static mut INPUT: [f32; N_FEATURES] = [0.0; N_FEATURES];

#[no_mangle]
pub extern "C" fn input_ptr() -> i32 {{
    core::ptr::addr_of_mut!(INPUT) as *mut f32 as i32
}}

#[no_mangle]
pub extern "C" fn feature_count() -> i32 {{
    N_FEATURES as i32
}}

#[no_mangle]
pub extern "C" fn tree_count() -> i32 {{
    N_TREES as i32
}}

#[inline(always)]
fn run_tree(tree_index: usize) -> i32 {{
    let mut node = TREE_OFFSETS[tree_index];

    loop {{
        let left = CHILDREN_LEFT[node];
        let right = CHILDREN_RIGHT[node];

        if left == -1 && right == -1 {{
            return LEAF_CLASS[node];
        }}

        let f = FEATURE[node];

        if f < 0 {{
            return LEAF_CLASS[node];
        }}

        let idx = f as usize;

        let raw = unsafe {{ INPUT[idx] }};
        let x = (raw - MEAN[idx]) / SCALE[idx];

        if x <= THRESHOLD[node] {{
            node = left as usize;
        }} else {{
            node = right as usize;
        }}
    }}
}}

#[no_mangle]
pub extern "C" fn predict() -> i32 {{
    let mut votes_0 = 0usize;
    let mut votes_1 = 0usize;

    let mut t = 0usize;

    while t < N_TREES {{
        let pred = run_tree(t);

        if pred == 0 {{
            votes_0 += 1;
        }} else {{
            votes_1 += 1;
        }}

        t += 1;
    }}

    if votes_1 > votes_0 {{ 1 }} else {{ 0 }}
}}
'''

out = Path(__file__).parent / "src/lib.rs"
out.write_text(code)

print("Generated:", out)
print("Features:", N_FEATURES)
print("Trees:", N_TREES)
print("Nodes:", N_NODES)
