#!/usr/bin/env python3

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "models" / "naive_bayes" / "breast_cancer" / "model.json"

m = json.loads(MODEL.read_text())

N_FEATURES = len(m["mean"])
N_CLASSES = len(m["classes"])

def arr1(values):
    return "[" + ", ".join(f"{float(v):.10e}f32" for v in values) + "]"

def arr2(rows):
    return "[\n" + ",\n".join(
        "    " + arr1(row) for row in rows
    ) + "\n]"

code = f'''const N_FEATURES: usize = {N_FEATURES};
const N_CLASSES: usize = {N_CLASSES};

const MEAN: [f32; N_FEATURES] = {arr1(m["mean"])};
const SCALE: [f32; N_FEATURES] = {arr1(m["scale"])};

const CLASS_PRIOR: [f32; N_CLASSES] = {arr1(m["class_prior"])};
const THETA: [[f32; N_FEATURES]; N_CLASSES] = {arr2(m["theta"])};
const VAR: [[f32; N_FEATURES]; N_CLASSES] = {arr2(m["var"])};

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
    let mut best_class = 0usize;
    let mut best_log_prob = f32::NEG_INFINITY;

    let mut c = 0usize;

    while c < N_CLASSES {{
        let mut log_prob = CLASS_PRIOR[c].ln();

        let mut i = 0usize;

        while i < N_FEATURES {{
            let raw_x = unsafe {{ INPUT[i] }};
            let x = (raw_x - MEAN[i]) / SCALE[i];

            let variance = VAR[c][i];
            let diff = x - THETA[c][i];

            log_prob += -0.5f32 * (
                (2.0f32 * core::f32::consts::PI * variance).ln()
                + ((diff * diff) / variance)
            );

            i += 1;
        }}

        if log_prob > best_log_prob {{
            best_log_prob = log_prob;
            best_class = c;
        }}

        c += 1;
    }}

    best_class as i32
}}
'''

out = Path(__file__).parent / "src" / "lib.rs"
out.write_text(code)

print("Generated:", out)
print("Features:", N_FEATURES)
print("Classes:", N_CLASSES)
