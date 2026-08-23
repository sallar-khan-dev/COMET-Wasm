#!/usr/bin/env python3
import argparse, csv, re, subprocess, time
from pathlib import Path
import numpy as np
from scipy import stats

def run_hey(url, body, concurrency, duration_s):
    cmd = ["hey", "-z", f"{duration_s}s", "-c", str(concurrency), "-m", "POST", "-H", "Content-Type: application/json", "-d", body, url]
    out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
    def extract(pattern, default=np.nan):
        m = re.search(pattern, out)
        return float(m.group(1)) if m else default
    return {"rps": extract(r"Requests/sec:\s+([0-9.]+)"), "avg_ms": extract(r"Average:\s+([0-9.]+)")*1000, "p50_ms": extract(r"50%% in\s+([0-9.]+)")*1000, "p95_ms": extract(r"95%% in\s+([0-9.]+)")*1000, "p99_ms": extract(r"99%% in\s+([0-9.]+)")*1000}

def rel_ci(values, confidence=0.95):
    arr = np.array(values, dtype=float); n = len(arr); mean = float(np.mean(arr))
    if n < 2 or mean == 0: return mean, float("inf")
    h = stats.sem(arr) * stats.t.ppf((1 + confidence) / 2.0, n - 1)
    return mean, abs(h / mean)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True); ap.add_argument("--url", required=True); ap.add_argument("--body", required=True)
    ap.add_argument("--concurrency", type=int, default=32); ap.add_argument("--duration-s", type=int, default=5); ap.add_argument("--warmup", type=int, default=1)
    ap.add_argument("--repeat-min", type=int, default=20); ap.add_argument("--repeat-max", type=int, default=60); ap.add_argument("--rel-precision", type=float, default=0.025); ap.add_argument("--cooldown-s", type=float, default=1.0)
    args = ap.parse_args()
    out_dir = Path("results/ci_runs"); out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / f"{args.name}_raw.csv"; summary_path = out_dir / f"{args.name}_summary.csv"
    print(f"Experiment: {args.name}\nURL: {args.url}\nConcurrency: {args.concurrency}\nDuration per repeat: {args.duration_s}s\nPrecision target: {args.rel_precision*100:.2f}%")
    for i in range(args.warmup): print(f"Warmup {i+1}/{args.warmup}"); run_hey(args.url, args.body, args.concurrency, args.duration_s)
    rows = []
    with raw_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["run", "rps", "avg_ms", "p50_ms", "p95_ms", "p99_ms"]); writer.writeheader()
        for i in range(1, args.repeat_max + 1):
            print(f"Measured run {i}/{args.repeat_max}"); row = run_hey(args.url, args.body, args.concurrency, args.duration_s); row["run"] = i; rows.append(row); writer.writerow(row); f.flush()
            if i >= args.repeat_min:
                p95_mean, p95_rel = rel_ci([r["p95_ms"] for r in rows]); rps_mean, rps_rel = rel_ci([r["rps"] for r in rows])
                print(f"  p95 mean={p95_mean:.4f} ms, relCI={p95_rel*100:.2f}%"); print(f"  rps mean={rps_mean:.2f}, relCI={rps_rel*100:.2f}%")
                if p95_rel <= args.rel_precision and rps_rel <= args.rel_precision: print("Precision target reached."); break
            time.sleep(args.cooldown_s)
    with summary_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["metric", "mean", "std", "min", "max", "p95_rel_ci", "n"]); writer.writeheader()
        for metric in ["rps", "avg_ms", "p50_ms", "p95_ms", "p99_ms"]:
            vals = [r[metric] for r in rows]; mean, rel = rel_ci(vals)
            writer.writerow({"metric": metric, "mean": mean, "std": float(np.std(vals, ddof=1)) if len(vals)>1 else 0, "min": float(np.min(vals)), "max": float(np.max(vals)), "p95_rel_ci": rel, "n": len(vals)})
    print(f"Saved raw results: {raw_path}\nSaved summary: {summary_path}")
if __name__ == "__main__": main()
