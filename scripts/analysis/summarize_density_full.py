#!/usr/bin/env python3

import argparse
import json
import math
from pathlib import Path

import pandas as pd
from scipy.stats import t as student_t

ROOT = Path(__file__).resolve().parents[2]

parser = argparse.ArgumentParser()
parser.add_argument(
    "--backend",
    required=True,
    choices=["wasmtime", "docker"]
)
parser.add_argument(
    "--model",
    required=True
)

args = parser.parse_args()

backend = args.backend
model = args.model

raw = (
    ROOT
    / "results"
    / "raw"
    / "density"
    / f"{backend}_{model}_density_full.csv"
)

out = (
    ROOT
    / "results"
    / "processed"
    / "density"
    / f"{backend}_{model}_density_full_summary.json"
)

if not raw.exists():
    raise SystemExit(
        f"Raw data not found: {raw}"
    )

df = pd.read_csv(raw)

required = {
    "physical_tenants",
    "repetition",
    "rss_mib",
    "pss_mib",
    "private_mib",
}

missing = required - set(df.columns)

if missing:
    raise SystemExit(
        f"Missing columns: {sorted(missing)}"
    )

summary = {}

for level, g in df.groupby(
    "physical_tenants"
):

    pss = g["pss_mib"].astype(float)

    n = len(pss)
    mean = pss.mean()
    sd = pss.std(ddof=1)

    critical = student_t.ppf(
        0.975,
        df=n - 1
    )

    halfwidth = (
        critical
        * sd
        / math.sqrt(n)
    )

    relative = (
        halfwidth / abs(mean)
        if mean != 0
        else math.inf
    )

    summary[str(int(level))] = {
        "physical_tenants":
            int(level),

        "repetitions":
            n,

        "pss_mean_mib":
            float(mean),

        "pss_sd_mib":
            float(sd),

        "ci95_halfwidth_mib":
            float(halfwidth),

        "ci95_lower_mib":
            float(mean - halfwidth),

        "ci95_upper_mib":
            float(mean + halfwidth),

        "relative_ci_halfwidth":
            float(relative),

        "rss_mean_mib":
            float(
                g["rss_mib"].mean()
            ),

        "private_mean_mib":
            float(
                g["private_mib"].mean()
            ),

        "ci_target_met":
            bool(
                n >= 20
                and relative <= 0.025
            ),
    }


result = {
    "backend": backend,
    "model": model,
    "confidence_level": 0.95,
    "relative_ci_target": 0.025,
    "source": str(raw),
    "density_levels": [
        int(x)
        for x in sorted(
            df["physical_tenants"].unique()
        )
    ],
    "total_repetitions":
        int(len(df)),
    "summary":
        summary,
}


out.parent.mkdir(
    parents=True,
    exist_ok=True
)

out.write_text(
    json.dumps(
        result,
        indent=2
    )
)


print(
    "===== CONSOLIDATED FULL DENSITY SUMMARY ====="
)

for level in sorted(
    summary,
    key=lambda x: int(x)
):

    s = summary[level]

    print(
        f"{int(level):>3} tenants | "
        f"n={s['repetitions']:>2} | "
        f"PSS={s['pss_mean_mib']:.3f} MiB | "
        f"95% CI ±{s['ci95_halfwidth_mib']:.4f} | "
        f"rel={s['relative_ci_halfwidth']*100:.3f}% | "
        f"{'PASS' if s['ci_target_met'] else 'FAIL'}"
    )

print()
print(
    "Total repetitions:",
    len(df)
)
print(
    "Summary:",
    out
)
print()
print(
    "FULL DENSITY SUMMARY REBUILD: PASS"
)
