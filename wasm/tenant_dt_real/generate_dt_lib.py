#!/usr/bin/env python3

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "models" / "decision_tree" / "breast_cancer" / "model.json"

m = json.loads(MODEL.read_text())

N_FEATURES = len(m["mean"])
N_NODES = m["tree"]["node_count"]

def f32_array(values):
    return "[" + ", ".join(f"{float(v):.10e}f32" for v in values) + "]"

def i32_array(values):
    return "[" + ", ".join(str(int(v)) for v in values) + "]"

code = f'''const N_FEATURES: usize = {N_FEATURES};
const N_NODES: usize = {N_NODES};

const MEAN: [f32; N_FEATURES] = {f32_array(m["mean"])};
const SCALE: [f32; N_FEATURES] = {f32_array(m["scale"])};

const CHILDREN_LEFT: [i32; N_NODES] = {i32_array(m["children_left"])};
const CHILDREN_RIGHT: [i32; N_NODES] = {i32_array(m["children_right"])};
const FEATURE: [i32; N_NODES] = {i32_array(m["feature"])};
const THRESHOLD: [f32; N_NODES] = {f32_array(m["threshold"])};
const LEAF_CLASS: [i32; N_NODES] = {i32_array(m["leaf_class"])};

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
pub extern "C" fn predict() -> i32 {{
    let mut node: usize = 0;

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
'''

out = Path(__file__).parent / "src" / "lib.rs"
out.write_text(code)

print("Generated:", out)
print("Features:", N_FEATURES)
print("Nodes:", N_NODES)
