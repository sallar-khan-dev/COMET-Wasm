#!/usr/bin/env python3

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

m = json.loads(
    (ROOT / "models/svm/breast_cancer/model.json").read_text()
)

N_FEATURES = len(m["mean"])
N_SV = m["n_support_total"]

support_flat = [
    value
    for row in m["support_vectors"]
    for value in row
]

def f32_array(values):
    return "[" + ", ".join(
        f"{float(v):.10e}f32" for v in values
    ) + "]"

code = f'''const N_FEATURES: usize = {N_FEATURES};
const N_SV: usize = {N_SV};
const N_SV_VALUES: usize = N_FEATURES * N_SV;

const GAMMA: f32 = {float(m["gamma"]):.10e}f32;
const INTERCEPT: f32 = {float(m["intercept"]):.10e}f32;

const MEAN: [f32; N_FEATURES] =
    {f32_array(m["mean"])};

const SCALE: [f32; N_FEATURES] =
    {f32_array(m["scale"])};

const SUPPORT_VECTORS: [f32; N_SV_VALUES] =
    {f32_array(support_flat)};

const DUAL_COEF: [f32; N_SV] =
    {f32_array(m["dual_coef"])};

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
pub extern "C" fn support_vector_count() -> i32 {{
    N_SV as i32
}}

#[no_mangle]
pub extern "C" fn predict() -> i32 {{
    let mut decision = INTERCEPT;

    let mut sv = 0usize;

    while sv < N_SV {{
        let mut distance_sq = 0.0f32;
        let mut f = 0usize;

        while f < N_FEATURES {{
            let raw = unsafe {{ INPUT[f] }};
            let x = (raw - MEAN[f]) / SCALE[f];

            let sv_value =
                SUPPORT_VECTORS[sv * N_FEATURES + f];

            let diff = x - sv_value;
            distance_sq += diff * diff;

            f += 1;
        }}

        let kernel = (-GAMMA * distance_sq).exp();

        decision += DUAL_COEF[sv] * kernel;

        sv += 1;
    }}

    if decision > 0.0f32 {{
        1
    }} else {{
        0
    }}
}}
'''

out = Path(__file__).parent / "src/lib.rs"
out.write_text(code)

print("Generated:", out)
print("Features:", N_FEATURES)
print("Support vectors:", N_SV)
print("Packed SV values:", len(support_flat))
