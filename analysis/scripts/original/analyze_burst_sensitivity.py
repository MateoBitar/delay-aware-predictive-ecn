#!/usr/bin/env python3
import csv
import math
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = ROOT / "research_horizon_study/v2_full_evaluation"
BURST = ROOT / "research_horizon_study/v2_burst_size_sensitivity"
OUT = BURST / "analysis"
OUT.mkdir(exist_ok=True)

SEEDS = list(range(224, 230))
CONTROLLERS = [
    "baseline", "lower_fixed", "trend",
    "ml_2ms", "ml_5ms", "ml_20ms"
]
LEVELS = ["moderate", "reference", "intense"]
SIZES = {"moderate": 50000, "reference": 100000, "intense": 150000}
METRICS = [
    "mean_fct_ms",
    "p95_fct_ms",
    "p99_fct_ms",
    "aggregate_goodput_mbps",
    "background_runwide_jain",
    "mean_queue_packets",
    "peak_queue_packets",
]
T95_DF5 = 2.5705818356

def read(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))

def save(path, rows):
    if not rows:
        return
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

def ci(values):
    if len(values) != 6:
        raise ValueError("Expected six paired seed differences")
    mean = statistics.mean(values)
    sd = statistics.stdev(values)
    margin = T95_DF5 * sd / math.sqrt(6)
    return mean, mean - margin, mean + margin

# Combine new sensitivity runs with previously validated reference.
data = []

for row in read(BASE / "results_36_runs.csv"):
    row["severity"] = "reference"
    row["short_flow_base_bytes"] = "100000"
    data.append(row)

data += read(BURST / "results_72_runs.csv")

indexed = {}
for row in data:
    key = (
        row["severity"],
        int(row["seed"]),
        row["controller"]
    )
    if key in indexed:
        raise RuntimeError(f"Duplicate result: {key}")
    indexed[key] = row

assert len(indexed) == 108, f"Expected 108, found {len(indexed)}"

for severity in LEVELS:
    for seed in SEEDS:
        manifests = set()
        for controller in CONTROLLERS:
            key = severity, seed, controller
            assert key in indexed, f"Missing {key}"
            row = indexed[key]
            assert int(row["completed_flows"]) == 24
            assert int(row["short_flow_base_bytes"]) == SIZES[severity]
            manifests.add(row["manifest_hash"])
            for metric in METRICS:
                assert math.isfinite(float(row[metric]))
        assert len(manifests) == 1, (
            f"Unmatched workloads: {severity}, seed {seed}"
        )

print("PASS: 108 unique controller-condition results")
print("PASS: Paired workload manifests and complete flow counts")

# 1. Controller means and SD by workload severity.
summary = []
for severity in LEVELS:
    for controller in CONTROLLERS:
        subset = [
            indexed[severity, seed, controller]
            for seed in SEEDS
        ]
        row = {"severity": severity, "controller": controller}
        for metric in METRICS:
            vals = [float(r[metric]) for r in subset]
            row[metric + "_mean"] = statistics.mean(vals)
            row[metric + "_sd"] = statistics.stdev(vals)
        summary.append(row)

save(OUT / "controller_by_severity.csv", summary)

# 2. Within each severity, compare alternatives to baseline,
# lower_fixed, and queue trend using matched seeds.
comparisons = []
for severity in LEVELS:
    for comparator in ("baseline", "lower_fixed", "trend"):
        for controller in CONTROLLERS:
            if controller == comparator:
                continue
            for metric in METRICS:
                differences = [
                    float(indexed[severity, seed, controller][metric])
                    - float(indexed[severity, seed, comparator][metric])
                    for seed in SEEDS
                ]
                mean, lo, hi = ci(differences)
                comparisons.append({
                    "severity": severity,
                    "metric": metric,
                    "controller": controller,
                    "comparator": comparator,
                    "paired_difference": mean,
                    "ci95_low": lo,
                    "ci95_high": hi,
                    "ci_excludes_zero": lo > 0 or hi < 0,
                })

save(OUT / "paired_by_severity.csv", comparisons)

# 3. Difference-in-differences:
# (controller - comparator) at new workload
# minus (controller - comparator) at reference workload.
interactions = []
for severity in ("moderate", "intense"):
    for comparator in ("baseline", "lower_fixed", "trend"):
        for controller in CONTROLLERS:
            if controller == comparator:
                continue
            for metric in METRICS:
                differences = []
                for seed in SEEDS:
                    effect_new = (
                        float(indexed[severity, seed, controller][metric])
                        - float(indexed[severity, seed, comparator][metric])
                    )
                    effect_reference = (
                        float(indexed["reference", seed, controller][metric])
                        - float(indexed["reference", seed, comparator][metric])
                    )
                    differences.append(effect_new - effect_reference)

                mean, lo, hi = ci(differences)
                interactions.append({
                    "severity_vs_reference": severity,
                    "metric": metric,
                    "controller": controller,
                    "comparator": comparator,
                    "interaction_difference": mean,
                    "ci95_low": lo,
                    "ci95_high": hi,
                    "ci_excludes_zero": lo > 0 or hi < 0,
                })

save(OUT / "workload_interactions.csv", interactions)

print("\n========== P99 FCT MEANS BY SEVERITY (ms) ==========")
print(f"{'Controller':14s} {'50 KB':>12s} {'100 KB':>12s} {'150 KB':>12s}")
for controller in CONTROLLERS:
    vals = []
    for severity in LEVELS:
        vals.append(statistics.mean(
            float(indexed[severity, seed, controller]["p99_fct_ms"])
            for seed in SEEDS
        ))
    print(f"{controller:14s} " + " ".join(f"{v:12.3f}" for v in vals))

print("\n========== ML 20 ms VS SIMPLE CONTROLLERS: P99 ==========")
for severity in LEVELS:
    for comparator in ("lower_fixed", "trend"):
        row = next(r for r in comparisons
                   if r["severity"] == severity
                   and r["metric"] == "p99_fct_ms"
                   and r["controller"] == "ml_20ms"
                   and r["comparator"] == comparator)
        print(
            f"{severity:9s} vs {comparator:11s}: "
            f"{row['paired_difference']:+.3f} ms "
            f"[{row['ci95_low']:+.3f}, {row['ci95_high']:+.3f}]"
        )

print("\n========== LOAD INTERACTION: ML 20 ms VS TREND ==========")
for severity in ("moderate", "intense"):
    for metric in ("mean_fct_ms", "p95_fct_ms", "p99_fct_ms",
                   "aggregate_goodput_mbps"):
        row = next(r for r in interactions
                   if r["severity_vs_reference"] == severity
                   and r["metric"] == metric
                   and r["controller"] == "ml_20ms"
                   and r["comparator"] == "trend")
        print(
            f"{severity:9s} {metric:26s}: "
            f"{row['interaction_difference']:+.6f} "
            f"[{row['ci95_low']:+.6f}, {row['ci95_high']:+.6f}]"
        )

print("\n========== OUTPUTS ==========")
for name in (
    "controller_by_severity.csv",
    "paired_by_severity.csv",
    "workload_interactions.csv",
):
    print(OUT / name)

print("\nPASS: Workload-sensitivity analysis complete.")
print("Caution: 95% intervals are exploratory and unadjusted.")
print("Only six held-out seeds per severity.")
print("Changed variable: nominal short-flow size, not arrival timing.")
