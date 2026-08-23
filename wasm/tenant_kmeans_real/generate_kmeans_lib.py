#!/usr/bin/env python3

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
m = json.loads(
    (ROOT / "models/kmeans/iris/model.json").read_text()
)

K = m["n_clusters"]
D = m["n_features"]

def arr1(values):
    return "[" + ", ".join(
        f"{float(v):.10e}f32" for v in values
    ) + "]"

def arr2(rows):
    return "[\n" + ",\n".join(
        "    " + arr1(row) for row in rows
    ) + "\n]"

code = f'''const K: usize = {K};
const D: usize = {D};

const CENTROIDS: [[f32; D]; K] =
{arr2(m["centroids"])};

static mut INPUT: [f32; D] = [0.0; D];

#[no_mangle]
pub extern "C" fn input_ptr() -> i32 {{
    core::ptr::addr_of_mut!(INPUT) as *mut f32 as i32
}}

#[no_mangle]
pub extern "C" fn feature_count() -> i32 {{
    D as i32
}}

#[no_mangle]
pub extern "C" fn cluster_count() -> i32 {{
    K as i32
}}

#[no_mangle]
pub extern "C" fn predict() -> i32 {{
    let mut best_cluster: usize = 0;
    let mut best_distance = f32::INFINITY;

    let mut c = 0usize;

    while c < K {{
        let mut distance = 0.0f32;
        let mut i = 0usize;

        while i < D {{
            let x = unsafe {{ INPUT[i] }};
            let diff = x - CENTROIDS[c][i];
            distance += diff * diff;
            i += 1;
        }}

        if distance < best_distance {{
            best_distance = distance;
            best_cluster = c;
        }}

        c += 1;
    }}

    best_cluster as i32
}}
'''

out = Path(__file__).parent / "src/lib.rs"
out.write_text(code)

print("Generated:", out)
print("Clusters:", K)
print("Features:", D)
