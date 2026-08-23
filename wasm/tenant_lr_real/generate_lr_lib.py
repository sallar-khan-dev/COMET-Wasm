import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
m = json.loads((ROOT / "models" / "logistic_regression" / "iris_lr" / "model.json").read_text())
def arr(vals): return "[" + ", ".join(f"{v:.10}f32" for v in vals) + "]"
code = f'''#[no_mangle]
pub extern "C" fn predict(f1: f32, f2: f32, f3: f32, f4: f32) -> i32 {{
    let weights: [f32; 4] = {arr(m["weights"])};
    let mean: [f32; 4] = {arr(m["mean"])};
    let scale: [f32; 4] = {arr(m["scale"])};
    let input: [f32; 4] = [f1, f2, f3, f4];
    let mut z: f32 = {m["bias"]:.10}f32;
    let mut i = 0;
    while i < 4 {{
        let x_scaled = (input[i] - mean[i]) / scale[i];
        z += weights[i] * x_scaled;
        i += 1;
    }}
    let probability = 1.0f32 / (1.0f32 + (-z).exp());
    if probability >= 0.5 {{ 1 }} else {{ 0 }}
}}
'''
Path("src/lib.rs").write_text(code)
print("Generated src/lib.rs")
