const K: usize = 3;
const D: usize = 4;

const CENTROIDS: [[f32; D]; K] =
[
    [5.9016129032e+00f32, 2.7483870968e+00f32, 4.3935483871e+00f32, 1.4338709677e+00f32],
    [5.0060000000e+00f32, 3.4280000000e+00f32, 1.4620000000e+00f32, 2.4600000000e-01f32],
    [6.8500000000e+00f32, 3.0736842105e+00f32, 5.7421052632e+00f32, 2.0710526316e+00f32]
];

static mut INPUT: [f32; D] = [0.0; D];

#[no_mangle]
pub extern "C" fn input_ptr() -> i32 {
    core::ptr::addr_of_mut!(INPUT) as *mut f32 as i32
}

#[no_mangle]
pub extern "C" fn feature_count() -> i32 {
    D as i32
}

#[no_mangle]
pub extern "C" fn cluster_count() -> i32 {
    K as i32
}

#[no_mangle]
pub extern "C" fn predict() -> i32 {
    let mut best_cluster: usize = 0;
    let mut best_distance = f32::INFINITY;

    let mut c = 0usize;

    while c < K {
        let mut distance = 0.0f32;
        let mut i = 0usize;

        while i < D {
            let x = unsafe { INPUT[i] };
            let diff = x - CENTROIDS[c][i];
            distance += diff * diff;
            i += 1;
        }

        if distance < best_distance {
            best_distance = distance;
            best_cluster = c;
        }

        c += 1;
    }

    best_cluster as i32
}
