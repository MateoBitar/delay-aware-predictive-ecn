from pathlib import Path
from collections import defaultdict
import csv
import hashlib
import json
import math
import random
import statistics
import sys

ROOT = Path.home() / "ns3-external-validation"
SOURCE = ROOT / "external_analysis/six_metrics/six_metrics_180_runs.csv"
OUT = ROOT / "external_analysis/six_metric_comparisons"

CONDITIONS = [
    ("WebSearch", 60),
    ("WebSearch", 80),
    ("WebSearch", 95),
    ("FB_Hadoop", 60),
    ("FB_Hadoop", 95),
]

SEEDS = range(230, 236)

CONTROLLERS = [
    "baseline",
    "lower_fixed",
    "trend",
    "ml_2ms",
    "ml_5ms",
    "ml_20ms",
]

# Lower is better: FCT, queueing and forced marks.
# Higher is better: goodput and Jain fairness proxy.
# Activity metrics have no universal better direction.
METRICS = {
    "p95_short_fct_ms": "lower",
    "p99_short_fct_ms": "lower",
    "mean_short_flow_goodput_mbps": "higher",
    "mean_large_flow_goodput_mbps": "higher",
    "arrival_window_goodput_mbps": "higher",
    "sender_fairness_jain_100ms": "higher",
    "mean_queue_packets": "lower",
    "p95_queue_packets": "lower",
    "max_queue_packets": "lower",
    "mean_queue_delay_us": "lower",
    "p95_queue_delay_us": "lower",
    "fraction_queue_ge_20": "lower",
    "fraction_queue_ge_60": "lower",
    "ecn_marks_total": "descriptive",
    "ecn_forced_marks": "descriptive",
    "early_activations": "descriptive",
    "inference_per_simulated_second": "descriptive",
}

def require(ok, msg):
    if not ok:
        raise RuntimeError(msg)

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def quantile(values, fraction):
    values = sorted(values)
    x = (len(values) - 1) * fraction
    lo, hi = math.floor(x), math.ceil(x)
    return values[lo] + (values[hi] - values[lo]) * (x - lo)

def bootstrap(differences, seed, repetitions=10000):
    n = len(differences)
    rng = random.Random(seed)

    samples = []
    for _ in range(repetitions):
        samples.append(statistics.mean(
            differences[rng.randrange(n)]
            for _ in range(n)
        ))

    return quantile(samples, .025), quantile(samples, .975)

def load_records():
    require(SOURCE.is_file(), f"Missing: {SOURCE}")

    with SOURCE.open(newline="") as f:
        rows = list(csv.DictReader(f))

    require(len(rows) == 180, "Expected 180 run records")

    records = {}
    hashes = defaultdict(set)

    for row in rows:
        key = (
            row["dataset"],
            int(row["load_percent"]),
            int(row["seed"]),
            row["controller"],
        )

        require(key not in records, f"Duplicate {key}")
        require(key[:2] in CONDITIONS, f"Unknown condition: {key}")
        require(key[2] in SEEDS, f"Unknown seed: {key}")
        require(key[3] in CONTROLLERS, f"Unknown controller: {key}")
        require(int(row["flows_verified"]) == 240,
                f"Unverified flows: {key}")

        for metric in METRICS:
            require(metric in row, f"Missing metric: {metric}")

        records[key] = row
        hashes[key[:3]].add(row["manifest_sha256"])

    for dataset, load in CONDITIONS:
        for seed in SEEDS:
            require(
                len(hashes[(dataset, load, seed)]) == 1,
                f"Manifest mismatch: {dataset} {load} {seed}"
            )
            for controller in CONTROLLERS:
                require(
                    (dataset, load, seed, controller) in records,
                    f"Missing controller: {dataset} {load} "
                    f"{seed} {controller}"
                )

    return records

def finite(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (ValueError, TypeError):
        return None

def compare(records, dataset, load, controller,
            reference, metric, bootstrap_seed):

    values = []
    reference_values = []
    differences = []
    percentages = []

    for seed in SEEDS:
        a = finite(records[
            (dataset, load, seed, controller)
        ][metric])

        b = finite(records[
            (dataset, load, seed, reference)
        ][metric])

        # Use paired, simultaneously available observations.
        if a is None or b is None:
            continue

        values.append(a)
        reference_values.append(b)
        differences.append(a - b)

        if b != 0:
            percentages.append(100.0 * (a - b) / b)

    n = len(differences)

    if n >= 2:
        lo, hi = bootstrap(differences, bootstrap_seed)
        avg_delta = statistics.mean(differences)
    else:
        lo = hi = avg_delta = float("nan")

    direction = METRICS[metric]

    wins = None

    if direction == "lower":
        wins = sum(x < 0 for x in differences)
    elif direction == "higher":
        wins = sum(x > 0 for x in differences)

    return {
        "dataset": dataset,
        "load_percent": load,
        "controller": controller,
        "reference": reference,
        "metric": metric,
        "preferred_direction": direction,
        "paired_seeds_available": n,
        "controller_mean": (
            statistics.mean(values) if values else float("nan")
        ),
        "reference_mean": (
            statistics.mean(reference_values)
            if reference_values else float("nan")
        ),
        "mean_delta": avg_delta,
        "mean_paired_change_pct": (
            statistics.mean(percentages)
            if percentages else float("nan")
        ),
        "ci_low": lo,
        "ci_high": hi,
        "wins": wins if wins is not None else "",
        "ci_excludes_zero": (
            int(lo > 0 or hi < 0)
            if n >= 2 else ""
        ),
    }

def save_csv(path, rows):
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

def fmt_pct(value):
    return f"{value:+.1f}%" if math.isfinite(value) else "N/A"

def main():
    records = load_records()

    require(
        not OUT.exists(),
        f"STOP: Output directory already exists: {OUT}"
    )

    OUT.mkdir(parents=True)

    comparisons = []

    # All five alternatives versus baseline.
    pairs = [
        (controller, "baseline")
        for controller in CONTROLLERS
        if controller != "baseline"
    ]

    # Direct ML comparisons against simpler controls.
    pairs.extend(
        (controller, reference)
        for controller in ("ml_2ms", "ml_5ms", "ml_20ms")
        for reference in ("trend", "lower_fixed")
    )

    counter = 0

    for dataset, load in CONDITIONS:
        for controller, reference in pairs:
            for metric in METRICS:
                counter += 1

                comparisons.append(compare(
                    records,
                    dataset,
                    load,
                    controller,
                    reference,
                    metric,
                    500000 + counter,
                ))

    require(len(comparisons) == 935,
            "Expected 935 metric comparisons")

    save_csv(
        OUT / "all_paired_metric_comparisons.csv",
        comparisons,
    )

    # 30 controller-condition summary rows.
    summaries = []

    for dataset, load in CONDITIONS:
        for controller in CONTROLLERS:
            group = [
                records[(dataset, load, seed, controller)]
                for seed in SEEDS
            ]

            summary = {
                "dataset": dataset,
                "load_percent": load,
                "controller": controller,
                "seeds": 6,
            }

            for metric in METRICS:
                values = [
                    finite(r[metric]) for r in group
                ]
                values = [v for v in values if v is not None]

                summary[metric] = (
                    statistics.mean(values)
                    if values else float("nan")
                )
                summary[metric + "_n"] = len(values)

            summaries.append(summary)

    save_csv(
        OUT / "controller_summary_all_metrics.csv",
        summaries,
    )

    lookup = {
        (
            c["dataset"],
            c["load_percent"],
            c["controller"],
            c["reference"],
            c["metric"],
        ): c for c in comparisons
    }

    print("========== SIX-METRIC COMPARISON ==========")
    print("Negative FCT change means faster than baseline.")
    print("Positive goodput change means higher goodput.")
    print("Fairness is a demand-sensitive proxy.")
    print()

    for dataset, load in CONDITIONS:
        print(f"--- {dataset}, {load}% ---")
        print(
            f"{'Controller':<12}"
            f"{'P95':>10}"
            f"{'P99':>10}"
            f"{'Goodput':>11}"
            f"{'Fairness':>12}"
            f"{'Queue':>11}"
        )

        for controller in CONTROLLERS[1:]:
            def get(metric):
                return lookup[
                    (dataset, load, controller, "baseline", metric)
                ]["mean_paired_change_pct"]

            print(
                f"{controller:<12}"
                f"{fmt_pct(get('p95_short_fct_ms')):>10}"
                f"{fmt_pct(get('p99_short_fct_ms')):>10}"
                f"{fmt_pct(get('arrival_window_goodput_mbps')):>11}"
                f"{fmt_pct(get('sender_fairness_jain_100ms')):>12}"
                f"{fmt_pct(get('mean_queue_packets')):>11}"
            )

        print()

    print("========== DIRECT ML COMPARISONS: P99 ==========")

    for dataset, load in CONDITIONS:
        print(f"\n{dataset} {load}%")

        for model in ("ml_2ms", "ml_5ms", "ml_20ms"):
            for reference in ("trend", "lower_fixed"):
                r = lookup[(
                    dataset, load, model, reference,
                    "p99_short_fct_ms"
                )]

                print(
                    f"  {model} vs {reference}: "
                    f"{r['mean_delta']:+.2f} ms; "
                    f"{fmt_pct(r['mean_paired_change_pct'])}; "
                    f"wins={r['wins']}/{r['paired_seeds_available']}; "
                    f"CI=[{r['ci_low']:+.2f}, "
                    f"{r['ci_high']:+.2f}] ms"
                )

    provenance = {
        "source_file": str(SOURCE),
        "source_sha256": digest(SOURCE),
        "run_count": 180,
        "conditions": len(CONDITIONS),
        "controller_reference_pairs_per_condition": len(pairs),
        "metrics": METRICS,
        "comparisons": len(comparisons),
        "bootstrap": (
            "10,000 paired-seed resamples; exploratory "
            "95% percentile intervals; no multiplicity correction"
        ),
        "limitations": [
            "Six independent seeds per condition",
            "Goodput measured at application layer",
            "Fairness is a demand-sensitive active-sender proxy",
            "Fairness-eligible windows vary by controller",
            "Inference activity is not CPU-time measurement",
            "Offered load is nominal, not measured utilization",
            "No correction for multiple comparisons",
        ],
    }

    (OUT / "analysis_provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )

    print("\n========== ANALYSIS AUDIT ==========")
    print("PASS: All 180 runs checked")
    print("PASS: 30 controller-condition summaries")
    print("PASS: 935 paired metric comparisons")
    print("PASS: P95 and P99 both included")
    print("PASS: Goodput and fairness comparisons included")
    print("PASS: Queue and control activity comparisons included")
    print("PASS: Analysis provenance recorded")
    print("RESULTS:", OUT)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"STOP: {e}", file=sys.stderr)
        sys.exit(1)
