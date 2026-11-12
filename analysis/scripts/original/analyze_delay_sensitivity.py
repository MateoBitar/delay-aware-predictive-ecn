#!/usr/bin/env python3
import csv
import math
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = ROOT / "research_horizon_study/v2_full_evaluation"
DELAY = ROOT / "research_horizon_study/v2_delay_sensitivity"
OUT = DELAY / "analysis"
OUT.mkdir(parents=True, exist_ok=True)

SEEDS = list(range(224, 230))
CONTROLLERS = [
    "baseline", "lower_fixed", "trend",
    "ml_2ms", "ml_5ms", "ml_20ms"
]
LEVELS = ["original", "medium", "high"]
DELAYS = {"original": 10, "medium": 250, "high": 1000}

METRICS = [
    "mean_fct_ms",
    "p95_fct_ms",
    "p99_fct_ms",
    "aggregate_goodput_mbps",
    "background_runwide_jain"
]

# Two-sided 95% t critical value for six paired seeds (df=5).
T_CRITICAL = 2.5705818356

def read_csv(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))

def save_csv(path, rows):
    if not rows:
        return
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=list(rows[0])
        )
        writer.writeheader()
        writer.writerows(rows)

def paired_ci(values):
    assert len(values) == 6
    mean = statistics.mean(values)
    sd = statistics.stdev(values)
    margin = T_CRITICAL * sd / math.sqrt(6)
    return mean, mean - margin, mean + margin

print("========== INPUT VALIDATION ==========")

data = []

for row in read_csv(BASE / "results_36_runs.csv"):
    row["delay_condition"] = "original"
    row["link_delay_us"] = "10"
    data.append(row)

data.extend(read_csv(DELAY / "results_72_runs.csv"))

indexed = {}

for row in data:
    key = (
        row["delay_condition"],
        int(row["seed"]),
        row["controller"]
    )

    if key in indexed:
        raise RuntimeError(f"Duplicate experiment: {key}")

    indexed[key] = row

assert len(indexed) == 108, (
    f"Expected 108 experiments, found {len(indexed)}"
)

for level in LEVELS:
    for seed in SEEDS:
        hashes = set()

        for controller in CONTROLLERS:
            key = (level, seed, controller)

            assert key in indexed, f"Missing {key}"

            row = indexed[key]

            assert int(row["link_delay_us"]) == DELAYS[level]
            assert int(row["completed_flows"]) == 24

            hashes.add(row["manifest_hash"])

            for metric in METRICS:
                assert math.isfinite(float(row[metric]))

        assert len(hashes) == 1, (
            f"Unpaired workload: {level}, seed {seed}"
        )

    print(
        f"PASS: {level:8s} "
        f"({DELAYS[level]:4d} us), 36 validated results"
    )

# Confirm each seed retains the same original workload
# across all three delay conditions.
for seed in SEEDS:
    hashes = {
        indexed[(level, seed, "baseline")]["manifest_hash"]
        for level in LEVELS
    }
    assert len(hashes) == 1, (
        f"Workload changed across delays for seed {seed}"
    )

print("PASS: All cross-delay workload hashes matched")
print("PASS: 108 unique observations")

# ---------------------------------------------------------
# 1. Controller means and SD within each delay condition.
# ---------------------------------------------------------
summary = []

for level in LEVELS:
    for controller in CONTROLLERS:
        row = {
            "delay_condition": level,
            "link_delay_us": DELAYS[level],
            "controller": controller
        }

        for metric in METRICS:
            values = [
                float(indexed[(level, seed, controller)][metric])
                for seed in SEEDS
            ]
            row[metric + "_mean"] = statistics.mean(values)
            row[metric + "_sd"] = statistics.stdev(values)

        summary.append(row)

save_csv(OUT / "controller_by_delay.csv", summary)

# ---------------------------------------------------------
# 2. Paired comparisons at each delay level.
# ---------------------------------------------------------
comparisons = []

for level in LEVELS:
    for comparator in ("baseline", "lower_fixed", "trend"):
        for controller in CONTROLLERS:
            if controller == comparator:
                continue

            for metric in METRICS:
                differences = [
                    float(indexed[(level, seed, controller)][metric])
                    - float(indexed[(level, seed, comparator)][metric])
                    for seed in SEEDS
                ]

                mean, low, high = paired_ci(differences)

                comparisons.append({
                    "delay_condition": level,
                    "link_delay_us": DELAYS[level],
                    "metric": metric,
                    "controller": controller,
                    "comparator": comparator,
                    "paired_difference": mean,
                    "ci95_low": low,
                    "ci95_high": high,
                    "ci_excludes_zero": low > 0 or high < 0,
                    "n_seeds": 6
                })

save_csv(OUT / "paired_by_delay.csv", comparisons)

# ---------------------------------------------------------
# 3. Paired difference-in-differences interactions.
# ---------------------------------------------------------
interactions = []

for level in ("medium", "high"):
    for comparator in ("baseline", "lower_fixed", "trend"):
        for controller in CONTROLLERS:
            if controller == comparator:
                continue

            for metric in METRICS:
                changes = []

                for seed in SEEDS:
                    alternative_new = float(
                        indexed[(level, seed, controller)][metric]
                    )
                    comparator_new = float(
                        indexed[(level, seed, comparator)][metric]
                    )

                    alternative_original = float(
                        indexed[("original", seed, controller)][metric]
                    )
                    comparator_original = float(
                        indexed[("original", seed, comparator)][metric]
                    )

                    relative_new = (
                        alternative_new - comparator_new
                    )
                    relative_original = (
                        alternative_original - comparator_original
                    )

                    changes.append(
                        relative_new - relative_original
                    )

                mean, low, high = paired_ci(changes)

                interactions.append({
                    "delay_vs_original": level,
                    "link_delay_us": DELAYS[level],
                    "metric": metric,
                    "controller": controller,
                    "comparator": comparator,
                    "interaction_difference": mean,
                    "ci95_low": low,
                    "ci95_high": high,
                    "ci_excludes_zero": low > 0 or high < 0,
                    "n_seeds": 6
                })

save_csv(OUT / "delay_interactions.csv", interactions)

# ---------------------------------------------------------
# Print the key research comparisons.
# ---------------------------------------------------------
print("\n========== P99 FCT MEANS (ms) ==========")

print(
    f"{'Controller':14s} "
    f"{'10 us':>11s} "
    f"{'250 us':>11s} "
    f"{'1000 us':>11s}"
)

for controller in CONTROLLERS:
    values = []

    for level in LEVELS:
        values.append(
            statistics.mean(
                float(indexed[(level, seed, controller)]["p99_fct_ms"])
                for seed in SEEDS
            )
        )

    print(
        f"{controller:14s} "
        + " ".join(f"{value:11.3f}" for value in values)
    )

print("\n========== ML VS SIMPLE CONTROLLERS: P99 ==========")

for level in LEVELS:
    for ml in ("ml_2ms", "ml_5ms", "ml_20ms"):
        for comparator in ("lower_fixed", "trend"):
            result = next(
                r for r in comparisons
                if r["delay_condition"] == level
                and r["metric"] == "p99_fct_ms"
                and r["controller"] == ml
                and r["comparator"] == comparator
            )

            print(
                f"{level:8s} {ml:8s} vs {comparator:11s}: "
                f"{result['paired_difference']:+8.3f} ms "
                f"[{result['ci95_low']:+8.3f}, "
                f"{result['ci95_high']:+8.3f}]"
            )

print("\n========== DELAY INTERACTIONS: P99 ==========")

for level in ("medium", "high"):
    for ml in ("ml_2ms", "ml_5ms", "ml_20ms"):
        for comparator in ("baseline", "lower_fixed", "trend"):
            result = next(
                r for r in interactions
                if r["delay_vs_original"] == level
                and r["metric"] == "p99_fct_ms"
                and r["controller"] == ml
                and r["comparator"] == comparator
            )

            print(
                f"{level:8s} {ml:8s} vs {comparator:11s}: "
                f"{result['interaction_difference']:+8.3f} ms "
                f"[{result['ci95_low']:+8.3f}, "
                f"{result['ci95_high']:+8.3f}]"
            )

print("\n========== OUTPUT FILES ==========")
for filename in (
    "controller_by_delay.csv",
    "paired_by_delay.csv",
    "delay_interactions.csv"
):
    print(OUT / filename)

print("\nPASS: Delay-sensitivity statistical analysis complete")
print("95% intervals are exploratory and unadjusted.")
print("Six paired workload seeds per delay configuration.")
print("Physical propagation delay varied; RED LinkDelay remained fixed.")
