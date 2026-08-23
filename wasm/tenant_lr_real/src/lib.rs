#[no_mangle]
pub extern "C" fn predict(f1: f32, f2: f32, f3: f32, f4: f32) -> i32 {
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
