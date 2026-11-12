from pathlib import Path
import pandas as pd
import numpy as np
import json

ROOT = Path("research_horizon_study")
ORIGINAL = ROOT / "closed_loop_test/test_results.csv"
REPRODUCED = ROOT / "closed_loop_reproduction/test_results.csv"
REPORT = ROOT / "closed_loop_reproduction/verification_report.json"

if not ORIGINAL.is_file() or not REPRODUCED.is_file():
    raise SystemExit(
        "STOP: Original or reproduced results are missing."
    )

original = pd.read_csv(ORIGINAL)
reproduced = pd.read_csv(REPRODUCED)

keys = ["seed", "controller"]

metrics = [
    "mean_fct_ms",
    "p95_fct_ms",
    "p99_fct_ms",
    "mean_queue_packets",
    "peak_queue_packets",
]

expected_seeds = set(range(224, 230))
expected_controllers = {
    "baseline", "lower_fixed", "trend",
    "ml_2ms", "ml_5ms", "ml_20ms"
}

for label, df in [
    ("original", original),
    ("reproduced", reproduced)
]:
    assert len(df) == 36, f"{label}: expected 36 runs"
    assert not df.duplicated(keys).any()
    assert set(df.seed) == expected_seeds
    assert set(df.controller) == expected_controllers
    assert df.groupby("seed").controller.nunique().eq(6).all()
    assert df.groupby("seed").manifest_hash.nunique().eq(1).all()
    assert df.completed_flows.eq(24).all()

joined = original.merge(
    reproduced,
    on=keys,
    suffixes=("_original", "_reproduced"),
    validate="one_to_one"
)

assert len(joined) == 36

print("========== CLOSED-LOOP REPRODUCIBILITY ==========")

results = {}
all_pass = True

for metric in metrics:
    a = joined[f"{metric}_original"].to_numpy(dtype=float)
    b = joined[f"{metric}_reproduced"].to_numpy(dtype=float)

    differences = np.abs(a - b)

    # Tolerance accommodates CSV serialization roundoff.
    tolerance = 1e-9
    passed = bool(np.all(differences <= tolerance))

    results[metric] = {
        "passed": passed,
        "max_absolute_difference": float(differences.max()),
        "tolerance": tolerance
    }

    all_pass &= passed

    print(
        f"{metric:24} "
        f"{'PASS' if passed else 'FAIL':5} "
        f"max_diff={differences.max():.12g}"
    )

manifest_equal = bool(
    (joined.manifest_hash_original ==
     joined.manifest_hash_reproduced).all()
)

flow_equal = bool(
    (joined.completed_flows_original ==
     joined.completed_flows_reproduced).all()
)

all_pass &= manifest_equal and flow_equal

print(
    "Workload manifests:",
    "IDENTICAL" if manifest_equal else "DIFFERENT"
)
print(
    "Completed flow counts:",
    "IDENTICAL" if flow_equal else "DIFFERENT"
)

report = {
    "result": "PASS" if all_pass else "FAIL",
    "comparison": "36 paired controller-scenario runs",
    "metrics": results,
    "manifest_hashes_identical": manifest_equal,
    "completion_counts_identical": flow_equal,
    "verified_runs": len(joined),
    "tolerance": 1e-9,
}

REPORT.parent.mkdir(parents=True, exist_ok=True)
REPORT.write_text(json.dumps(report, indent=2) + "\n")

print("\n========== FINAL RESULT ==========")
print(report["result"])
print("Verified runs:", len(joined))
print("Report:", REPORT)

if not all_pass:
    raise SystemExit(1)
