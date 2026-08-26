const N_FEATURES: usize = 4;

static mut INPUT: [f32; N_FEATURES] = [0.0; N_FEATURES];

#[no_mangle]
pub extern "C" fn input_ptr() -> i32 {
    core::ptr::addr_of_mut!(INPUT) as *mut f32 as i32
}

#[no_mangle]
pub extern "C" fn feature_count() -> i32 {
    N_FEATURES as i32
}

#[no_mangle]
pub extern "C" fn predict() -> i32 {
    let f1 = unsafe { INPUT[0] };
    let f2 = unsafe { INPUT[1] };
    let f3 = unsafe { INPUT[2] };
    let f4 = unsafe { INPUT[3] };

let weights: [f32; 4] = [0.5435686295f32, -0.3396157602f32, 1.878629174f32, 2.737636864f32];
    let mean: [f32; 4] = [5.835238095f32, 3.098095238f32, 3.697142857f32, 1.179047619f32];
    let scale: [f32; 4] = [0.8678359459f32, 0.4318246894f32, 1.841503379f32, 0.7945882717f32];
    let input: [f32; 4] = [f1, f2, f3, f4];
    let mut z: f32 = -3.441903479f32;
    let mut i = 0;
    while i < 4 {
        let x_scaled = (input[i] - mean[i]) / scale[i];
        z += weights[i] * x_scaled;
        i += 1;
    }
    let probability = 1.0f32 / (1.0f32 + (-z).exp());
    if probability >= 0.5 { 1 } else { 0 }
}
