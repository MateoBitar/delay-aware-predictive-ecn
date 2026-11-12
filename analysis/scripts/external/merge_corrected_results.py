from pathlib import Path
from collections import defaultdict
from datetime import datetime
import csv
import hashlib
import json
import math
import os
import random
import shutil
import statistics

ROOT = Path.home() / "ns3-external-validation"
ANALYSIS = ROOT / "external_analysis"
SIX = ANALYSIS / "six_metrics"
CMP = ANALYSIS / "six_metric_comparisons"
FIG = ROOT / "research_figures/external_comprehensive"
FIX = ROOT / "research_figures/external_corrected_v2"

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP = ROOT / ".maintenance_backups" / ("figure_merge_" + timestamp)

RUNS = SIX / "six_metrics_180_runs.csv"
SUMMARY = SIX / "six_metric_controller_summary.csv"
PAIRED = CMP / "all_paired_metric_comparisons.csv"
CONTROLLER_SUMMARY = CMP / "controller_summary_all_metrics.csv"
CORRECTED = FIX / "ecn_corrected_180_runs.csv"

MAPPINGS = {
    "figure_08_short_goodput_DELTA":
        "figure_08_short_flow_goodput",
    "figure_09_large_goodput_DELTA":
        "figure_09_large_flow_goodput",
    "figure_12_ecn_marking_CORRECTED":
        "figure_12_ecn_marking_stacked_bars",
}

def require(value, message):
    if not value:
        raise RuntimeError(message)

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def read_csv(path):
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)

def write_csv(path, fields, rows):
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)

def backup(path):
    relative = path.relative_to(ROOT)
    destination = BACKUP / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)

def percentile(data, fraction):
    data = sorted(data)
    position = (len(data) - 1) * fraction
    lo = math.floor(position)
    hi = math.ceil(position)
    return data[lo] + (data[hi] - data[lo]) * (position - lo)

def bootstrap(diffs, seed):
    rng = random.Random(seed)
    n = len(diffs)
    samples = []
    for _ in range(10000):
        samples.append(statistics.mean(
            diffs[rng.randrange(n)] for _ in range(n)
        ))
    return percentile(samples, .025), percentile(samples, .975)

print("========== PRE-MERGE VALIDATION ==========")

for path in [RUNS, SUMMARY, PAIRED, CONTROLLER_SUMMARY, CORRECTED]:
    require(path.is_file(), f"Missing required CSV: {path}")

for source, target in MAPPINGS.items():
    for extension in ("png", "pdf"):
        require((FIX / f"{source}.{extension}").is_file(),
                f"Missing corrected figure: {source}.{extension}")
        require((FIG / f"{target}.{extension}").is_file(),
                f"Missing original figure: {target}.{extension}")

run_fields, runs = read_csv(RUNS)
fix_fields, fixed = read_csv(CORRECTED)
summary_fields, summaries = read_csv(SUMMARY)
paired_fields, paired = read_csv(PAIRED)
controller_fields, controller_summaries = read_csv(CONTROLLER_SUMMARY)

require(len(runs) == len(fixed) == 180, "Expected 180 run rows")
require(len(summaries) == 30, "Expected 30 summary rows")
require(len(controller_summaries) == 30,
        "Expected 30 controller summary rows")
require(len(paired) == 935, "Expected 935 comparison rows")

def run_key(r):
    return (
        r["dataset"], int(r["load_percent"]),
        int(r["seed"]), r["controller"]
    )

fixed_by_key = {run_key(r): r for r in fixed}
require(len(fixed_by_key) == 180, "Duplicate corrected run keys")

for row in runs:
    key = run_key(row)
    require(key in fixed_by_key, f"Missing corrected run: {key}")
    other = fixed_by_key[key]

    require(
        row["manifest_sha256"] == other["manifest_sha256"],
        f"Manifest changed: {key}"
    )

    require(
        int(other["ecn_forced_marks"])
        + int(other["ecn_unforced_marks"])
        == int(row["ecn_marks_total"]),
        f"ECN counts do not reconcile: {key}"
    )

    row["ecn_forced_marks"] = other["ecn_forced_marks"]
    row["ecn_unforced_marks"] = other["ecn_unforced_marks"]

print("PASS: 180 corrected ECN records verified")

# Recalculate aggregate forced/unforced ECN columns.
groups = defaultdict(list)
by_key = {}

for row in runs:
    key = run_key(row)
    by_key[key] = row
    groups[(key[0], key[1], key[3])].append(row)

for columns, rows in [
    (summary_fields, summaries),
    (controller_fields, controller_summaries),
]:
    for metric in ("ecn_forced_marks", "ecn_unforced_marks"):
        if metric not in columns:
            columns.append(metric)

    for row in rows:
        key = (
            row["dataset"],
            int(row["load_percent"]),
            row["controller"]
        )
        group = groups[key]
        require(len(group) == 6, f"Missing seeds: {key}")

        for metric in ("ecn_forced_marks", "ecn_unforced_marks"):
            row[metric] = statistics.mean(
                int(r[metric]) for r in group
            )

        if "ecn_forced_marks_seeds_available" in columns or \
           "ecn_marks_total_seeds_available" in columns:
            for metric in ("ecn_forced_marks", "ecn_unforced_marks"):
                field = metric + "_seeds_available"
                if field not in columns:
                    columns.append(field)
                row[field] = 6
        elif "ecn_forced_marks_n" in columns or \
             "p99_short_fct_ms_n" in columns:
            for metric in ("ecn_forced_marks", "ecn_unforced_marks"):
                field = metric + "_n"
                if field not in columns:
                    columns.append(field)
                row[field] = 6

# Recompute affected paired comparisons using the same
# bootstrap settings and row-order-dependent seeds as
# the original comparison script.
updated_comparisons = 0

for index, row in enumerate(paired, 1):
    if row["metric"] != "ecn_forced_marks":
        continue

    dataset = row["dataset"]
    load = int(row["load_percent"])
    controller = row["controller"]
    reference = row["reference"]

    a = [
        float(by_key[(dataset, load, seed, controller)]
              ["ecn_forced_marks"])
        for seed in range(230, 236)
    ]
    b = [
        float(by_key[(dataset, load, seed, reference)]
              ["ecn_forced_marks"])
        for seed in range(230, 236)
    ]

    differences = [x - y for x, y in zip(a, b)]
    percentages = [
        100 * (x - y) / y
        for x, y in zip(a, b) if y != 0
    ]

    low, high = bootstrap(differences, 500000 + index)

    row["controller_mean"] = statistics.mean(a)
    row["reference_mean"] = statistics.mean(b)
    row["mean_delta"] = statistics.mean(differences)
    row["mean_paired_change_pct"] = (
        statistics.mean(percentages)
        if percentages else float("nan")
    )
    row["ci_low"] = low
    row["ci_high"] = high
    row["paired_seeds_available"] = 6
    row["ci_excludes_zero"] = int(low > 0 or high < 0)

    updated_comparisons += 1

require(updated_comparisons == 55,
        f"Expected 55 forced-mark comparisons, got {updated_comparisons}")

print("PASS: 30 aggregate records corrected")
print("PASS: 55 forced-mark comparisons recalculated")

# Confirm corrected figure directory has only expected files.
expected_fix_files = {
    "ecn_corrected_180_runs.csv",
    "CORRECTION_MANIFEST.json",
}
for source in MAPPINGS:
    for ext in ("png", "pdf"):
        expected_fix_files.add(f"{source}.{ext}")

actual_fix_files = {p.name for p in FIX.iterdir() if p.is_file()}
require(
    actual_fix_files == expected_fix_files,
    "Unexpected files in corrected directory; "
    "stopping rather than deleting unknown files"
)
require(
    all(p.is_file() for p in FIX.iterdir()),
    "Corrected directory contains unexpected subdirectories"
)

# Safety backups are kept out of the published figure folder.
for path in [
    RUNS, SUMMARY, PAIRED, CONTROLLER_SUMMARY,
    FIG / "FIGURE_MANIFEST.json",
]:
    if path.is_file():
        backup(path)

for target in MAPPINGS.values():
    for ext in ("png", "pdf"):
        backup(FIG / f"{target}.{ext}")

backup(FIX / "CORRECTION_MANIFEST.json")

print("PASS: Original files backed up to", BACKUP)

# Write corrected CSVs in their permanent locations.
write_csv(RUNS, run_fields, runs)
write_csv(SUMMARY, summary_fields, summaries)
write_csv(PAIRED, paired_fields, paired)
write_csv(CONTROLLER_SUMMARY, controller_fields,
          controller_summaries)

# Replace the original figures using their established names.
for source, target in MAPPINGS.items():
    for ext in ("png", "pdf"):
        os.replace(
            FIX / f"{source}.{ext}",
            FIG / f"{target}.{ext}"
        )

# Update the existing figure manifest.
figure_manifest = FIG / "FIGURE_MANIFEST.json"

if figure_manifest.is_file():
    manifest = json.loads(figure_manifest.read_text())
    manifest["figure_corrections"] = {
        "figures_replaced": list(MAPPINGS.values()),
        "ecn_source": str(RUNS),
        "ecn_forced_and_unforced_counts": "Corrected",
        "goodput_figures": "Zoomed paired Mbps differences",
        "original_simulation_traces_modified": False
    }
    figure_manifest.write_text(
        json.dumps(manifest, indent=2) + "\n"
    )

# Keep correction provenance beside the corrected CSVs.
record = {
    "date": datetime.now().isoformat(),
    "correction": (
        "Reclassified forced/unforced ECN marks from "
        "original traces; replaced Figures 08, 09 and 12"
    ),
    "per_run_csv": str(RUNS),
    "per_run_csv_sha256": digest(RUNS),
    "summary_csv": str(SUMMARY),
    "paired_comparisons_csv": str(PAIRED),
    "updated_forced_mark_comparisons": updated_comparisons,
    "figure_directory": str(FIG),
    "backup_directory": str(BACKUP),
    "original_simulation_traces_modified": False,
    "note": (
        "The original six-metric CSV contained correct "
        "total ECN marks but incorrect forced/unforced "
        "classification. All 180 traces were reconciled."
    )
}

(SIX / "ECN_CORRECTION_PROVENANCE.json").write_text(
    json.dumps(record, indent=2) + "\n"
)

# Remove the now-redundant corrected directory only
# after the corrected figures and CSVs are installed.
shutil.rmtree(FIX)

# Final integrity check.
new_fields, new_runs = read_csv(RUNS)

require(len(new_runs) == 180, "Merged CSV row count changed")
require(
    all(
        int(r["ecn_forced_marks"])
        + int(r["ecn_unforced_marks"])
        == int(r["ecn_marks_total"])
        for r in new_runs
    ),
    "Post-merge ECN integrity failure"
)

for target in MAPPINGS.values():
    for ext in ("png", "pdf"):
        require(
            (FIG / f"{target}.{ext}").stat().st_size > 0,
            f"Empty replacement figure: {target}.{ext}"
        )

print()
print("========== FINAL CONSOLIDATION AUDIT ==========")
print("PASS: Main 180-run CSV contains corrected ECN counts")
print("PASS: Controller summaries updated")
print("PASS: 55 forced-mark paired comparisons updated")
print("PASS: Figures 08, 09, 12 replaced under original names")
print("PASS: PNG and PDF versions replaced")
print("PASS: Correction provenance stored beside analysis CSVs")
print("PASS: Redundant corrected-figures folder removed")
print("PASS: Original simulation results untouched")
print("FIGURES:", FIG)
print("ANALYSIS:", SIX)
print("BACKUP:", BACKUP)
