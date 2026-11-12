from pathlib import Path
from collections import defaultdict
import csv
import math
import random
import statistics

ROOT = Path.home() / "ns3-external-validation"
SOURCE = ROOT / "external_evaluation_180/results_180_runs.csv"
OUT = ROOT / "external_analysis"

CONDITIONS = [
    ("WebSearch", 60),
    ("WebSearch", 80),
    ("WebSearch", 95),
    ("FB_Hadoop", 60),
    ("FB_Hadoop", 95),
]

CONTROLLERS = [
    "baseline",
    "lower_fixed",
    "trend",
    "ml_2ms",
    "ml_5ms",
    "ml_20ms",
]

SEEDS = list(range(230, 236))

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def quantile(values, q):
    values = sorted(values)
    pos = (len(values) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)

def paired_bootstrap_ci(differences, seed):
    rng = random.Random(seed)
    n = len(differences)
    estimates = []

    for _ in range(10000):
        sample = [
            differences[rng.randrange(n)]
            for _ in range(n)
        ]
        estimates.append(statistics.mean(sample))

    return quantile(estimates, .025), quantile(estimates, .975)

require(SOURCE.is_file(), f"Missing: {SOURCE}")
require(not OUT.exists(),
        f"STOP: Analysis directory already exists: {OUT}")

with SOURCE.open(newline="") as f:
    raw_rows = list(csv.DictReader(f))

require(len(raw_rows) == 180,
        f"Expected 180 results, found {len(raw_rows)}")

records = {}
manifest_hashes = defaultdict(set)

for row in raw_rows:
    dataset = row["dataset"]
    load = int(row["load_percent"])
    seed = int(row["seed"])
    controller = row["controller"]

    key = (dataset, load, seed, controller)

    require(key not in records, f"Duplicate result: {key}")
    require((dataset, load) in CONDITIONS,
            f"Unexpected condition: {key}")
    require(seed in SEEDS, f"Unexpected seed: {key}")
    require(controller in CONTROLLERS,
            f"Unexpected controller: {key}")
    require(int(row["completed_flows"]) == 240,
            f"Incomplete flows: {key}")
    require(int(row["short_flows"]) > 0,
            f"No short flows: {key}")

    manifest_hashes[(dataset, load, seed)].add(
        row["manifest_sha256"]
    )

    records[key] = row

for dataset, load in CONDITIONS:
    for seed in SEEDS:
        for controller in CONTROLLERS:
            require(
                (dataset, load, seed, controller) in records,
                f"Missing result: {(dataset, load, seed, controller)}"
            )

        require(
            len(manifest_hashes[(dataset, load, seed)]) == 1,
            f"Manifest mismatch: {dataset}, {load}, {seed}"
        )

OUT.mkdir(parents=True)

summary = []

print("========== EXTERNAL WORKLOAD ANALYSIS ==========")
print("Runs:", len(records))
print("Conditions:", len(CONDITIONS))
print("Paired seeds per condition:", len(SEEDS))
print()

for ci, (dataset, load) in enumerate(CONDITIONS):
    print(f"--- {dataset}, {load}% nominal load ---")
    print(
        f"{'Controller':<15} {'P95 ms':>11} "
        f"{'P99 ms':>11} {'P99 change':>13}"
    )

    for controller_index, controller in enumerate(CONTROLLERS):
        values = {
            metric: [
                float(records[
                    (dataset, load, seed, controller)
                ][metric])
                for seed in SEEDS
            ]
            for metric in (
                "mean_short_fct_ms",
                "p95_short_fct_ms",
                "p99_short_fct_ms",
            )
        }

        baseline = {
            metric: [
                float(records[
                    (dataset, load, seed, "baseline")
                ][metric])
                for seed in SEEDS
            ]
            for metric in values
        }

        output = {
            "dataset": dataset,
            "load_percent": load,
            "controller": controller,
            "seeds": len(SEEDS),
        }

        for mi, metric in enumerate(values):
            observed = values[metric]
            reference = baseline[metric]

            differences = [
                x - y
                for x, y in zip(observed, reference)
            ]

            relative = [
                100.0 * (x - y) / y
                for x, y in zip(observed, reference)
            ]

            ci_low, ci_high = paired_bootstrap_ci(
                differences,
                100000 + ci * 1000
                + controller_index * 100 + mi
            )

            prefix = metric.replace("_short_fct_ms", "")

            output[f"{prefix}_ms"] = statistics.mean(observed)
            output[f"{prefix}_delta_ms"] = (
                statistics.mean(differences)
            )
            output[f"{prefix}_relative_change_pct"] = (
                statistics.mean(relative)
            )
            output[f"{prefix}_delta_ci_low_ms"] = ci_low
            output[f"{prefix}_delta_ci_high_ms"] = ci_high

        summary.append(output)

        print(
            f"{controller:<15} "
            f"{output['p95_ms']:>11.3f} "
            f"{output['p99_ms']:>11.3f} "
            f"{output['p99_relative_change_pct']:>+12.2f}%"
        )

    print()

output_file = OUT / "external_controller_summary.csv"

with output_file.open("w", newline="") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=list(summary[0].keys())
    )
    writer.writeheader()
    writer.writerows(summary)

with (OUT / "ANALYSIS_NOTES.txt").open("w") as f:
    f.write(
        "Analysis: 180 frozen-model external-workload runs.\n"
        "Unit of pairing: workload seed (six seeds per condition).\n"
        "Metrics: mean of six per-seed short-flow metrics.\n"
        "Relative changes: mean of six paired percentage changes.\n"
        "Positive change means worse FCT than baseline.\n"
        "Confidence intervals: exploratory paired seed bootstrap,\n"
        "10,000 resamples, percentile method, two-sided 95%.\n"
        "These intervals are not multiple-comparison adjusted.\n"
        "With only six seeds, uncertainty estimates are limited.\n"
        "P95/P99 are averaged across run-level quantiles;\n"
        "they are not quantiles of pooled flow completions.\n"
        "The offered-load percentages are nominal, not\n"
        "measurements of actual bottleneck utilization.\n"
    )

print("========== ANALYSIS COMPLETE ==========")
print("PASS: 180 unique results verified")
print("PASS: Every paired comparison has six seeds")
print("PASS: Identical manifest hashes within paired runs")
print("PASS: 30 controller-condition summary rows generated")
print("RESULTS:", output_file)
