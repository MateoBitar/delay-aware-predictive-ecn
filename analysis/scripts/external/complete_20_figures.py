from pathlib import Path
from collections import defaultdict
import csv
import hashlib
import json
import math

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.image as mpimg

HOME = Path.home()
ROOT = HOME / "ns3-external-validation"
ORIGINAL = HOME / "ns3-research-v2/ns-3.47"
STUDY = ORIGINAL / "research_horizon_study"
FIG = ROOT / "research_figures/external_comprehensive"

EXTERNAL = (
    ROOT / "external_analysis/six_metric_comparisons"
    / "all_paired_metric_comparisons.csv"
)

SOURCES = {
    "Main": (
        STUDY / "v2_full_evaluation/results_36_runs.csv",
        None,
        None,
        36,
    ),
    "Burst size": (
        STUDY / "v2_burst_size_sensitivity/results_72_runs.csv",
        "severity",
        "short_flow_base_bytes",
        72,
    ),
    "Link delay": (
        STUDY / "v2_delay_sensitivity/results_72_runs.csv",
        "delay_condition",
        "link_delay_us",
        72,
    ),
}

CONTROLLERS = [
    "baseline", "lower_fixed", "trend",
    "ml_2ms", "ml_5ms", "ml_20ms",
]

NAMES = {
    "baseline": "Standard ECN",
    "lower_fixed": "Lower fixed",
    "trend": "Trend",
    "ml_2ms": "ML 2 ms",
    "ml_5ms": "ML 5 ms",
    "ml_20ms": "ML 20 ms",
}

COLORS = {
    "baseline": "#374151",
    "lower_fixed": "#d97706",
    "trend": "#64748b",
    "ml_2ms": "#2563eb",
    "ml_5ms": "#059669",
    "ml_20ms": "#9333ea",
}

def check(value, message):
    if not value:
        raise RuntimeError(message)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def read_csv(path):
    check(path.is_file(), f"Missing source: {path}")
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    return rows

def display_condition(group, key):
    if group == "Main":
        return "Main evaluation"
    if group == "Burst size":
        return f"Burst severity: {key[0]} ({key[1]} B)"
    return f"Link delay: {key[0]} ({key[1]} µs)"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "pdf.fonttype": 42,
    "axes.spines.top": False,
    "axes.spines.right": False,
})

check(FIG.is_dir(), "Figure directory missing")
check(EXTERNAL.is_file(), "External comparisons missing")

for number in (17, 18):
    check(
        not list(FIG.glob(f"figure_{number:02d}_*.png")),
        f"STOP: Figure {number} already exists"
    )

original = {}
provenance = {}
all_groups = []

for group, (path, condition_column, config_column, expected_n) in SOURCES.items():
    rows = read_csv(path)
    check(
        len(rows) == expected_n,
        f"{group}: expected {expected_n} records, found {len(rows)}"
    )

    needed = {
        "seed", "controller", "p95_fct_ms",
        "p99_fct_ms", "completed_flows", "manifest_hash"
    }
    check(
        needed.issubset(rows[0]),
        f"{group}: missing required columns"
    )

    if condition_column:
        check(
            condition_column in rows[0]
            and config_column in rows[0],
            f"{group}: condition columns missing"
        )

    buckets = defaultdict(dict)
    manifest_hashes = defaultdict(set)

    for row in rows:
        condition = (
            (row[condition_column], row[config_column])
            if condition_column else ("main", "main")
        )
        seed = int(row["seed"])
        controller = row["controller"]
        key = (seed, controller)

        check(
            controller in CONTROLLERS,
            f"{group}: unknown controller {controller}"
        )
        check(
            key not in buckets[condition],
            f"{group}: duplicate {condition} {key}"
        )
        check(
            int(row["completed_flows"]) == 24,
            f"{group}: incomplete short flows {condition} {key}"
        )

        for metric in ("p95_fct_ms", "p99_fct_ms"):
            value = float(row[metric])
            check(
                math.isfinite(value) and value > 0,
                f"{group}: invalid {metric}"
            )

        buckets[condition][key] = row
        manifest_hashes[(condition, seed)].add(
            row["manifest_hash"]
        )

    expected_conditions = expected_n // (6 * 6)
    check(
        len(buckets) == expected_conditions,
        f"{group}: expected {expected_conditions} conditions"
    )

    for condition, records in buckets.items():
        seeds = {s for s, _ in records}
        check(
            len(seeds) == 6 and seeds == set(range(224, 230)),
            f"{group}: unexpected seeds {seeds}"
        )
        check(
            len(records) == 36,
            f"{group}: incomplete controller coverage"
        )
        for seed in seeds:
            check(
                all((seed, c) in records for c in CONTROLLERS),
                f"{group}: missing controller for seed {seed}"
            )
            check(
                len(manifest_hashes[(condition, seed)]) == 1,
                f"{group}: manifest mismatch for seed {seed}"
            )

    original[group] = buckets
    provenance[group] = {
        "file": str(path),
        "sha256": sha(path),
        "records": len(rows),
        "conditions": len(buckets),
    }

    for condition in sorted(buckets, key=str):
        all_groups.append((
            group, condition,
            display_condition(group, condition),
            buckets[condition],
        ))

check(len(all_groups) == 5, "Expected five original conditions")
check(
    sum(x["records"] for x in provenance.values()) == 180,
    "Original run count incorrect"
)

external_rows = read_csv(EXTERNAL)
check(len(external_rows) == 935, "Expected 935 external comparisons")

external_lookup = {}

for row in external_rows:
    key = (
        row["dataset"],
        int(row["load_percent"]),
        row["controller"],
        row["reference"],
        row["metric"],
    )
    check(key not in external_lookup, f"Duplicate external comparison: {key}")
    external_lookup[key] = row

def orig_metric(records, controller, metric):
    return np.array([
        float(records[(seed, controller)][metric])
        for seed in range(224, 230)
    ])

def original_pct(records, controller, metric):
    b = orig_metric(records, "baseline", metric)
    a = orig_metric(records, controller, metric)
    return float(np.mean(100 * (a - b) / b))

def save(fig, name):
    for suffix in ("png", "pdf"):
        fig.savefig(
            FIG / f"{name}.{suffix}",
            dpi=300 if suffix == "png" else None,
            bbox_inches="tight",
            facecolor="white",
        )
    plt.close(fig)
    print("PASS:", name)

print("========== ORIGINAL EVALUATION AUDIT ==========")
for group, info in provenance.items():
    print(f"PASS: {group}: {info['records']} runs, "
          f"{info['conditions']} condition(s)")
print("PASS: 180/180 original runs accounted for")

# --------------------------------------------------
# FIGURE 17: ORIGINAL P95 AND P99
# Five condition rows, two metric columns
# --------------------------------------------------

fig, axes = plt.subplots(5, 2, figsize=(15, 17))

for i, (group, condition, label, records) in enumerate(all_groups):
    for j, (metric, metric_label) in enumerate([
        ("p95_fct_ms", "P95"),
        ("p99_fct_ms", "P99"),
    ]):
        ax = axes[i, j]
        x = np.arange(len(CONTROLLERS))

        means = [
            orig_metric(records, c, metric).mean()
            for c in CONTROLLERS
        ]
        stds = [
            orig_metric(records, c, metric).std(ddof=1)
            for c in CONTROLLERS
        ]

        ax.bar(
            x, means,
            color=[COLORS[c] for c in CONTROLLERS],
            yerr=stds,
            capsize=3,
            alpha=0.9,
        )
        ax.set_xticks(
            x,
            [NAMES[c] for c in CONTROLLERS],
            rotation=28,
            ha="right",
        )
        ax.set_title(f"{label} — {metric_label}")
        ax.set_ylabel("Mean per-seed FCT quantile (ms)")
        ax.grid(axis="y", alpha=0.18)
        ax.set_axisbelow(True)

fig.suptitle(
    "Original 180-Run Study: P95 and P99 Short-Flow FCT",
    fontsize=17,
)
fig.text(
    0.5, 0.008,
    "Bars = means across six seeds; error bars = seed SD. "
    "Each condition retains its own scale and workload.",
    ha="center",
    fontsize=10,
)
fig.tight_layout(rect=[0, 0.025, 1, 0.975])
save(fig, "figure_17_original_p95_p99_comparison")

# --------------------------------------------------
# FIGURE 18: ORIGINAL VS EXTERNAL
# Paired P99 percentage changes, separately grouped
# --------------------------------------------------

controllers = CONTROLLERS[1:]

orig_labels = [x[2] for x in all_groups]
orig_matrix = np.array([
    [
        original_pct(records, controller, "p99_fct_ms")
        for controller in controllers
    ]
    for _, _, _, records in all_groups
])

ext_conditions = [
    ("WebSearch", 60),
    ("WebSearch", 80),
    ("WebSearch", 95),
    ("FB_Hadoop", 60),
    ("FB_Hadoop", 95),
]

ext_labels = [
    f"{dataset} {load}%"
    for dataset, load in ext_conditions
]

ext_matrix = np.array([
    [
        float(external_lookup[
            (dataset, load, controller, "baseline", "p99_short_fct_ms")
        ]["mean_paired_change_pct"])
        for controller in controllers
    ]
    for dataset, load in ext_conditions
])

limit = max(
    1.0,
    float(np.max(np.abs(orig_matrix))),
    float(np.max(np.abs(ext_matrix))),
)

fig, axes = plt.subplots(
    2, 1,
    figsize=(13, 10),
    gridspec_kw={"height_ratios": [1, 1]},
)

for ax, data, labels, title in [
    (
        axes[0], orig_matrix, orig_labels,
        "A. Original synthetic workloads (seeds 224–229)"
    ),
    (
        axes[1], ext_matrix, ext_labels,
        "B. External CDF-derived workloads (seeds 230–235)"
    ),
]:
    im = ax.imshow(
        data,
        cmap="RdBu_r",
        vmin=-limit,
        vmax=limit,
        aspect="auto",
    )
    ax.set_yticks(range(len(labels)), labels)
    ax.set_xticks(
        range(len(controllers)),
        [NAMES[c] for c in controllers],
    )
    ax.set_title(title, fontsize=13)

    for r in range(data.shape[0]):
        for c in range(data.shape[1]):
            val = data[r, c]
            ax.text(
                c, r, f"{val:+.1f}%",
                ha="center", va="center",
                color="white" if abs(val) > .65 * limit else "black",
                fontsize=10,
            )

fig.colorbar(
    im,
    ax=list(axes),
    fraction=0.025,
    pad=0.02,
    label="Mean paired P99 change relative to baseline (%)",
)

fig.suptitle(
    "Generalization Across Original and External Workloads",
    fontsize=16,
    y=0.99,
)

fig.text(
    0.5, 0.01,
    "Negative = lower P99. Changes are relative to each study's "
    "own baseline; raw FCTs are not pooled.",
    ha="center",
    fontsize=9,
)

fig.subplots_adjust(
    left=0.26, right=0.88,
    top=0.93, bottom=0.065,
    hspace=0.32,
)
save(fig, "figure_18_original_vs_external_matrix")

# --------------------------------------------------
# AUDIT 20 FIGURES, UPDATE MANIFEST, CONTACT SHEET
# --------------------------------------------------

individual = sorted(FIG.glob("figure_*.png"))
pdfs = sorted(FIG.glob("figure_*.pdf"))

check(len(individual) == 20, f"Expected 20 PNGs, found {len(individual)}")
check(len(pdfs) == 20, f"Expected 20 PDFs, found {len(pdfs)}")

expected_numbers = set(range(1, 21))
actual_numbers = {
    int(path.name.split("_")[1])
    for path in individual
}
check(
    actual_numbers == expected_numbers,
    "Some figure numbers are missing or duplicated"
)

manifest_path = FIG / "FIGURE_MANIFEST.json"
manifest = (
    json.loads(manifest_path.read_text())
    if manifest_path.exists() else {}
)
manifest.update({
    "figure_count": 20,
    "figure_names": [p.stem for p in individual],
    "original_180_sources": provenance,
    "external_comparison_source": str(EXTERNAL),
    "external_comparison_sha256": sha(EXTERNAL),
    "interpretation_notes": [
        "Original and external FCT metrics are not pooled.",
        "Original conditions are independently labeled.",
        "Original bars show seed SD, not confidence intervals.",
        "Relative changes are averages of paired seed percentages.",
        "Original and external workload generators differ.",
        "Figure 20 uses held-out synthetic classifier results.",
        "No simulations, models, or raw traces were modified."
    ]
})
manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

fig, axes = plt.subplots(10, 2, figsize=(26, 50))

for ax, path in zip(axes.flat, individual):
    ax.imshow(mpimg.imread(path))
    ax.set_title(
        path.stem.replace("_", " ").title(),
        fontsize=12,
        fontweight="bold",
        pad=8,
    )
    ax.axis("off")

fig.suptitle(
    "Delay-Aware Predictive ECN — All 20 Research Figures",
    fontsize=24,
    fontweight="bold",
)
fig.tight_layout(rect=[0, 0, 1, 0.982])

combined = FIG / "ALL_20_FIGURES_REVIEW.png"
fig.savefig(combined, dpi=135, facecolor="white")
plt.close(fig)

check(combined.is_file() and combined.stat().st_size > 0,
      "Combined image was not generated")

old_contact = FIG / "ALL_16_FIGURES_REVIEW.png"
if old_contact.exists():
    old_contact.unlink()

print()
print("========== FINAL 20-FIGURE AUDIT ==========")
print("PASS: Original 180 runs verified across 3 evaluation groups")
print("PASS: Figure 17 original P95/P99 generated")
print("PASS: Figure 18 cross-study P99 matrix generated")
print("PASS: 20 individual PNG figures")
print("PASS: 20 individual PDF figures")
print("PASS: Combined 20-figure PNG generated")
print("PASS: Figure manifest updated")
print("PASS: No original simulations or models modified")
print("OUTPUT:", FIG)
print("COMBINED:", combined)
