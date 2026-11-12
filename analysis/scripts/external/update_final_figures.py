from pathlib import Path
from datetime import datetime
import csv
import json
import math
import shutil
import statistics

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

ROOT = Path.home() / "ns3-external-validation"
FIG = ROOT / "research_figures/external_comprehensive"
RUNS = ROOT / "external_analysis/six_metrics/six_metrics_180_runs.csv"
COMPARE = ROOT / "external_analysis/six_metric_comparisons/all_paired_metric_comparisons.csv"
CAMPAIGN = ROOT / "external_evaluation_180"

CONTROLLERS = [
    "baseline", "lower_fixed", "trend",
    "ml_2ms", "ml_5ms", "ml_20ms"
]

LABELS = {
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

CONDITIONS = [
    ("WebSearch", 60),
    ("WebSearch", 80),
    ("WebSearch", 95),
    ("FB_Hadoop", 60),
    ("FB_Hadoop", 95),
]

CONDITION_LABELS = [
    "WebSearch 60%",
    "WebSearch 80%",
    "WebSearch 95%",
    "FB_Hadoop 60%",
    "FB_Hadoop 95%",
]

def check(condition, message):
    if not condition:
        raise RuntimeError(message)

check(RUNS.is_file(), "Missing per-run results")
check(COMPARE.is_file(), "Missing comparison results")
check(FIG.is_dir(), "Missing existing figure directory")

runs = pd.read_csv(RUNS)
comparisons = pd.read_csv(COMPARE)

check(len(runs) == 180, "Expected 180 results")
check(len(comparisons) == 935, "Expected 935 comparisons")

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 11,
    "axes.titlesize": 14,
    "axes.labelsize": 11,
    "pdf.fonttype": 42,
    "axes.spines.top": False,
    "axes.spines.right": False,
})

REPLACEMENTS = {
    "figure_04_p99_confidence_intervals",
    "figure_07_p95_vs_p99_tradeoff",
    "figure_08_short_flow_goodput",
    "figure_09_large_flow_goodput",
    "figure_14_research_summary_table",
}

ADDITIONS = {
    "figure_15_queue_occupancy_timeline",
    "figure_16_controller_activation_timeline",
}

# Keep overwritten originals out of the published figure directory.
BACKUP = (
    ROOT / ".maintenance_backups"
    / ("visual_polish_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
)

for name in REPLACEMENTS:
    for ext in ("png", "pdf"):
        source = FIG / f"{name}.{ext}"
        check(source.is_file(), f"Missing original: {source}")

for name in ADDITIONS:
    for ext in ("png", "pdf"):
        check(
            not (FIG / f"{name}.{ext}").exists(),
            f"New figure already exists: {name}.{ext}"
        )

BACKUP.mkdir(parents=True)

for name in REPLACEMENTS:
    for ext in ("png", "pdf"):
        shutil.copy2(
            FIG / f"{name}.{ext}",
            BACKUP / f"{name}.{ext}"
        )

for name in ("FIGURE_MANIFEST.json", "ALL_14_FIGURES_REVIEW.png"):
    original = FIG / name
    if original.exists():
        shutil.copy2(original, BACKUP / name)

print("PASS: Previous figures backed up")

def save(fig, name):
    png = FIG / f"{name}.png"
    pdf = FIG / f"{name}.pdf"

    fig.savefig(
        png, dpi=300,
        bbox_inches="tight",
        facecolor="white"
    )
    fig.savefig(
        pdf,
        bbox_inches="tight",
        facecolor="white"
    )
    plt.close(fig)
    print("PASS:", name, flush=True)

def get_comparison(dataset, load, controller, metric, reference="baseline"):
    result = comparisons[
        (comparisons.dataset == dataset)
        & (comparisons.load_percent == load)
        & (comparisons.controller == controller)
        & (comparisons.reference == reference)
        & (comparisons.metric == metric)
    ]
    check(len(result) == 1, f"Missing comparison: {dataset} {load} {controller} {metric}")
    return result.iloc[0]

def get_run_group(dataset, load, controller):
    result = runs[
        (runs.dataset == dataset)
        & (runs.load_percent == load)
        & (runs.controller == controller)
    ].sort_values("seed")
    check(len(result) == 6, "Expected six seeds")
    return result

# =====================================================
# FIGURE 04 — Larger forest plot
# =====================================================

fig, ax = plt.subplots(figsize=(12, 9))

models = ["ml_2ms", "ml_5ms", "ml_20ms"]
offsets = [-0.24, 0, 0.24]

for model, offset in zip(models, offsets):
    for i, (dataset, load) in enumerate(CONDITIONS):
        row = get_comparison(
            dataset, load, model,
            "p99_short_fct_ms"
        )

        center = float(row["mean_delta"])
        low = float(row["ci_low"])
        high = float(row["ci_high"])

        ax.errorbar(
            center, i + offset,
            xerr=[
                [max(0, center - low)],
                [max(0, high - center)]
            ],
            fmt="o",
            capsize=5,
            linewidth=1.8,
            markersize=7,
            color=COLORS[model],
            label=LABELS[model] if i == 0 else None
        )

ax.axvline(0, color="#111827", linestyle="--", linewidth=1.2)
ax.set_yticks(range(5), CONDITION_LABELS)
ax.invert_yaxis()
ax.set_xlabel("Mean paired P99 difference vs standard ECN (ms)")
ax.set_title("P99 Tail-Latency Differences and 95% Bootstrap Intervals")
ax.grid(axis="x", alpha=0.22)
ax.legend(loc="lower right", ncol=3)
fig.text(
    0.5, 0.015,
    "Negative = faster than ECN. Six seeds; exploratory, unadjusted bootstrap intervals.",
    ha="center", fontsize=10
)
fig.tight_layout(rect=[0, 0.04, 1, 1])
save(fig, "figure_04_p99_confidence_intervals")

# =====================================================
# FIGURE 07 — Labeled P95/P99 trade-offs
# =====================================================

fig, ax = plt.subplots(figsize=(12, 9))

MARKERS = ["o", "s", "^", "D", "P"]
ABBREV = ["W60", "W80", "W95", "H60", "H95"]

for controller in CONTROLLERS[1:]:
    for i, (dataset, load) in enumerate(CONDITIONS):
        x = float(get_comparison(
            dataset, load, controller,
            "p95_short_fct_ms"
        )["mean_paired_change_pct"])

        y = float(get_comparison(
            dataset, load, controller,
            "p99_short_fct_ms"
        )["mean_paired_change_pct"])

        ax.scatter(
            x, y,
            marker=MARKERS[i],
            color=COLORS[controller],
            s=110,
            edgecolor="white",
            linewidth=0.8,
            zorder=3
        )
        ax.annotate(
            ABBREV[i],
            (x, y),
            xytext=(5, 5),
            textcoords="offset points",
            fontsize=8,
            alpha=0.8
        )

ax.axhline(0, color="#777777", linestyle="--")
ax.axvline(0, color="#777777", linestyle="--")
ax.grid(alpha=0.18)
ax.set_xlabel("P95 relative change versus ECN (%)")
ax.set_ylabel("P99 relative change versus ECN (%)")
ax.set_title("Tail-Latency Trade-offs: P95 versus P99")

controller_handles = [
    Line2D([0], [0], marker="o", linestyle="",
           color=COLORS[c], label=LABELS[c], markersize=8)
    for c in CONTROLLERS[1:]
]
condition_handles = [
    Line2D([0], [0], marker=MARKERS[i], linestyle="",
           color="#374151", label=ABBREV[i], markersize=8)
    for i in range(5)
]

legend1 = ax.legend(
    handles=controller_handles,
    title="Controller",
    loc="upper right",
    fontsize=9
)
ax.add_artist(legend1)

ax.legend(
    handles=condition_handles,
    title="Workload",
    loc="lower left",
    fontsize=9,
    ncol=2
)

fig.text(
    0.5, 0.01,
    "Lower-left quadrant: both tail metrics improve. Percentages are paired seed averages.",
    ha="center", fontsize=10
)
fig.tight_layout(rect=[0, 0.04, 1, 1])
save(fig, "figure_07_p95_vs_p99_tradeoff")

# =====================================================
# FIGURES 08–09 — Readable goodput comparisons
# =====================================================

def goodput_chart(metric, label, filename):
    fig, axes = plt.subplots(3, 2, figsize=(17, 13))
    axes = list(axes.flat)

    for idx, (dataset, load) in enumerate(CONDITIONS):
        ax = axes[idx]

        baseline = get_run_group(
            dataset, load, "baseline"
        ).set_index("seed")[metric]

        differences = []
        percentages = []

        for controller in CONTROLLERS[1:]:
            observed = get_run_group(
                dataset, load, controller
            ).set_index("seed")[metric]

            observed = observed.loc[baseline.index]
            difference = observed - baseline

            differences.append(float(difference.mean()))
            percentages.append(
                float((100 * difference / baseline).mean())
            )

        y = np.arange(5)
        ax.barh(
            y, differences,
            color=[COLORS[c] for c in CONTROLLERS[1:]],
            height=0.62
        )
        ax.axvline(0, color="#111827", linestyle="--", linewidth=1)

        extent = max(max(abs(x) for x in differences), 0.02)
        ax.set_xlim(-extent * 1.65, extent * 1.65)

        for j, (delta, pct) in enumerate(zip(differences, percentages)):
            pad = extent * 0.07
            ax.text(
                delta + (pad if delta >= 0 else -pad),
                j,
                f"{delta:+.3f} Mbps",
                ha="left" if delta >= 0 else "right",
                va="center",
                fontsize=9
            )

        ax.set_yticks(y, [LABELS[c] for c in CONTROLLERS[1:]])
        ax.invert_yaxis()
        ax.set_title(
            f"{dataset} {load}%  |  ECN: {baseline.mean():.2f} Mbps",
            fontsize=12
        )
        ax.set_xlabel("Mean paired difference (Mbps)")
        ax.grid(axis="x", alpha=0.2)
        ax.set_axisbelow(True)

    axes[5].axis("off")
    axes[5].text(
        0.05, 0.65,
        "How to read:\n\n"
        "Right of zero: higher goodput\n"
        "Left of zero: lower goodput\n\n"
        "Each panel has its own zoomed\n"
        "horizontal scale.\n\n"
        "Six paired workload seeds.",
        va="top",
        fontsize=13
    )

    fig.suptitle(
        f"{label} Application Goodput Relative to Standard ECN",
        fontsize=17
    )
    fig.tight_layout(rect=[0, 0.02, 1, 0.96])
    save(fig, filename)

goodput_chart(
    "mean_short_flow_goodput_mbps",
    "Short-flow",
    "figure_08_short_flow_goodput"
)

goodput_chart(
    "mean_large_flow_goodput_mbps",
    "Large-flow",
    "figure_09_large_flow_goodput"
)

# =====================================================
# FIGURE 14 — Larger publication summary table
# =====================================================

table_rows = []

for dataset, load in CONDITIONS:
    best = min(
        ["ml_2ms", "ml_5ms", "ml_20ms"],
        key=lambda c: get_run_group(
            dataset, load, c
        )["p99_short_fct_ms"].mean()
    )

    p95 = float(get_comparison(
        dataset, load, best,
        "p95_short_fct_ms"
    )["mean_paired_change_pct"])

    p99 = float(get_comparison(
        dataset, load, best,
        "p99_short_fct_ms"
    )["mean_paired_change_pct"])

    queue = float(get_comparison(
        dataset, load, best,
        "mean_queue_packets"
    )["mean_paired_change_pct"])

    table_rows.append([
        f"{dataset} {load}%",
        LABELS[best],
        f"{p95:+.1f}%",
        f"{p99:+.1f}%",
        f"{queue:+.1f}%",
    ])

fig, ax = plt.subplots(figsize=(14, 5.5))
ax.axis("off")

table = ax.table(
    cellText=table_rows,
    colLabels=[
        "Workload",
        "Lowest-P99 ML",
        "P95 change",
        "P99 change",
        "Mean queue change"
    ],
    cellLoc="center",
    loc="center",
    colWidths=[0.25, 0.20, 0.18, 0.18, 0.19]
)
table.auto_set_font_size(False)
table.set_fontsize(12)
table.scale(1, 2.4)

for (r, c), cell in table.get_celld().items():
    cell.set_edgecolor("#cbd5e1")
    if r == 0:
        cell.set_facecolor("#dbeafe")
        cell.set_text_props(weight="bold")
    elif r % 2 == 0:
        cell.set_facecolor("#f8fafc")

ax.set_title(
    "Descriptive Comparison of ML Prediction Horizons",
    fontsize=16, pad=22
)
fig.text(
    0.5, 0.025,
    "Lowest-P99 horizon selected retrospectively per workload. "
    "Changes relative to standard ECN; not an adaptive selection algorithm.",
    ha="center", fontsize=10
)
fig.tight_layout(rect=[0, 0.07, 1, 0.94])
save(fig, "figure_14_research_summary_table")

# =====================================================
# ACTUAL NS-3 TRACES FOR FIGURES 15–16
# =====================================================

DATASET = "FB_Hadoop"
LOAD = 95
SEED = 230
TRACE_CONTROLLERS = ["baseline", "trend", "ml_2ms"]

def trace_path(controller, name):
    return (
        CAMPAIGN / DATASET
        / f"load_{LOAD}"
        / f"seed_{SEED}"
        / controller
        / name
    )

def read_queue(controller):
    path = trace_path(controller, "bursty-queue.dat")
    check(path.is_file(), f"Missing queue trace: {path}")

    t, q = [], []
    with path.open() as f:
        for line in f:
            if not line.strip() or line.startswith("#"):
                continue
            fields = line.split()
            check(len(fields) >= 3, "Malformed queue row")
            t.append(float(fields[0]))
            q.append(float(fields[1]))

    return np.array(t), np.array(q)

def read_actions(controller):
    path = trace_path(controller, "bursty-controller-actions.dat")
    check(path.is_file(), f"Missing controller trace: {path}")

    events = []
    with path.open() as f:
        for line in f:
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split()
            check(len(parts) >= 5, "Malformed controller action")
            events.append((float(parts[0]), int(parts[1])))

    return sorted(events)

actions = {
    c: read_actions(c)
    for c in ["trend", "ml_2ms", "ml_5ms", "ml_20ms"]
}

first_events = [
    t for events in actions.values()
    for t, active in events
    if active == 1
]

# Use a window anchored to an actual activation.
if first_events:
    WINDOW_START = max(0, min(first_events) - 0.05)
else:
    WINDOW_START = 0.2

WINDOW_END = WINDOW_START + 2.5

def active_intervals(events, left, right):
    active = False

    for t, value in events:
        if t < left:
            active = bool(value)
        else:
            break

    start = left if active else None
    intervals = []

    for t, value in events:
        if t < left:
            continue
        if t > right:
            break

        if value == 1 and not active:
            active = True
            start = t
        elif value == 0 and active:
            intervals.append((start, t))
            active = False
            start = None

    if active and start is not None:
        intervals.append((start, right))

    return intervals

# =====================================================
# FIGURE 15 — Real queue occupancy over time
# =====================================================

fig, ax = plt.subplots(figsize=(15, 6))

for controller in TRACE_CONTROLLERS:
    t, q = read_queue(controller)
    mask = (t >= WINDOW_START) & (t <= WINDOW_END)

    check(mask.any(), f"No queue observations for {controller}")

    ax.plot(
        t[mask] - WINDOW_START,
        q[mask],
        color=COLORS[controller],
        linewidth=1.1,
        alpha=0.85,
        label=LABELS[controller]
    )

for start, end in active_intervals(
    actions["ml_2ms"], WINDOW_START, WINDOW_END
):
    ax.axvspan(
        start - WINDOW_START,
        end - WINDOW_START,
        color=COLORS["ml_2ms"],
        alpha=0.08
    )

ax.axhline(
    20, color="#dc2626",
    linestyle="--",
    linewidth=1,
    label="20-packet prediction target"
)

ax.set_xlim(0, WINDOW_END - WINDOW_START)
ax.set_xlabel("Time since beginning of selected window (s)")
ax.set_ylabel("Instantaneous sampled queue occupancy (packets)")
ax.set_title(
    "Queue Occupancy During Actual FB_Hadoop Bursts\n"
    "95% nominal load, seed 230"
)
ax.grid(alpha=0.18)
ax.legend(ncol=2)
fig.text(
    0.5, 0.015,
    "Blue shading: ML 2 ms early-marking periods. "
    "Separate controller runs share the workload manifest.",
    ha="center", fontsize=10
)
fig.tight_layout(rect=[0, 0.04, 1, 1])
save(fig, "figure_15_queue_occupancy_timeline")

# =====================================================
# FIGURE 16 — Actual controller activation timeline
# =====================================================

fig, ax = plt.subplots(figsize=(15, 5.5))

timeline_controllers = [
    "trend", "ml_2ms", "ml_5ms", "ml_20ms"
]

for i, controller in enumerate(timeline_controllers):
    ax.hlines(i, 0, WINDOW_END - WINDOW_START,
              color="#e5e7eb", linewidth=8)

    for start, end in active_intervals(
        actions[controller], WINDOW_START, WINDOW_END
    ):
        ax.hlines(
            i,
            start - WINDOW_START,
            end - WINDOW_START,
            color=COLORS[controller],
            linewidth=9
        )

ax.set_yticks(
    range(len(timeline_controllers)),
    [LABELS[c] for c in timeline_controllers]
)
ax.invert_yaxis()
ax.set_xlim(0, WINDOW_END - WINDOW_START)
ax.set_xlabel("Time since beginning of selected window (s)")
ax.set_title(
    "Early-ECN Activation and Release Timeline\n"
    "FB_Hadoop 95%, seed 230"
)
ax.grid(axis="x", alpha=0.2)
fig.text(
    0.5, 0.015,
    "Colored segments = active early-threshold state; "
    "gray segments = normal thresholds (20, 60).",
    ha="center", fontsize=10
)
fig.tight_layout(rect=[0, 0.05, 1, 1])
save(fig, "figure_16_controller_activation_timeline")

# =====================================================
# UPDATE MANIFEST
# =====================================================

manifest_path = FIG / "FIGURE_MANIFEST.json"

if manifest_path.exists():
    manifest = json.loads(manifest_path.read_text())
else:
    manifest = {}

manifest["figure_count"] = 16
manifest["figure_names"] = [
    f.stem for f in sorted(FIG.glob("figure_*.png"))
]
manifest["visual_polish"] = {
    "replaced_figures": sorted(REPLACEMENTS),
    "added_figures": sorted(ADDITIONS),
    "timeline_workload": DATASET,
    "timeline_load": LOAD,
    "timeline_seed": SEED,
    "timeline_start_s": WINDOW_START,
    "timeline_end_s": WINDOW_END,
    "backup": str(BACKUP),
    "simulation_results_modified": False
}

manifest_path.write_text(
    json.dumps(manifest, indent=2) + "\n"
)

# =====================================================
# REBUILD THE COMBINED CONTACT SHEET
# =====================================================

images = sorted(FIG.glob("figure_*.png"))
check(len(images) == 16, f"Expected 16 images, found {len(images)}")

fig, axes = plt.subplots(8, 2, figsize=(25, 40))

for ax, path in zip(axes.flat, images):
    image = plt.imread(path)
    ax.imshow(image)
    ax.set_title(
        path.stem.replace("_", " ").title(),
        fontsize=12, fontweight="bold", pad=10
    )
    ax.axis("off")

fig.suptitle(
    "Delay-Aware Predictive ECN — Complete Research Figures",
    fontsize=23, fontweight="bold"
)
fig.tight_layout(rect=[0, 0, 1, 0.983])

combined = FIG / "ALL_16_FIGURES_REVIEW.png"
fig.savefig(combined, dpi=140, facecolor="white")
plt.close(fig)

# Remove obsolete combined sheet only after the new one exists.
old_combined = FIG / "ALL_14_FIGURES_REVIEW.png"
if old_combined.exists():
    old_combined.unlink()

pngs = list(FIG.glob("figure_*.png"))
pdfs = list(FIG.glob("figure_*.pdf"))

check(len(pngs) == 16, "Incorrect PNG count")
check(len(pdfs) == 16, "Incorrect PDF count")
check(combined.stat().st_size > 0, "Combined PNG empty")

print()
print("========== UPDATED FIGURE AUDIT ==========")
print("PASS: 5 figures replaced under original filenames")
print("PASS: 2 new trace-based figures generated")
print("PASS: 16 individual PNG files")
print("PASS: 16 individual PDF files")
print("PASS: Combined 16-figure PNG regenerated")
print("PASS: Figure manifest updated")
print("PASS: Original simulations unchanged")
print("FIGURES:", FIG)
print("COMBINED:", combined)
print("BACKUP:", BACKUP)
