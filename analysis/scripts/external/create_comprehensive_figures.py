from pathlib import Path
import re
import json
import math
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path.home() / "ns3-external-validation"

RUNS = ROOT / (
    "external_analysis/six_metrics/six_metrics_180_runs.csv"
)

COMPARISONS = ROOT / (
    "external_analysis/six_metric_comparisons/"
    "all_paired_metric_comparisons.csv"
)

BENCHMARK = ROOT / (
    "overhead_benchmark/benchmark_results.txt"
)

OUT = ROOT / "research_figures/external_comprehensive"

CONTROLLERS = [
    "baseline", "lower_fixed", "trend",
    "ml_2ms", "ml_5ms", "ml_20ms"
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

CONDITIONS = [
    ("WebSearch", 60),
    ("WebSearch", 80),
    ("WebSearch", 95),
    ("FB_Hadoop", 60),
    ("FB_Hadoop", 95),
]

LABELS = [
    "WebSearch\n60%",
    "WebSearch\n80%",
    "WebSearch\n95%",
    "FB_Hadoop\n60%",
    "FB_Hadoop\n95%",
]

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

require(RUNS.is_file(), f"Missing {RUNS}")
require(COMPARISONS.is_file(), f"Missing {COMPARISONS}")
require(BENCHMARK.is_file(), f"Missing {BENCHMARK}")
require(not OUT.exists(), f"STOP: Output already exists: {OUT}")

runs = pd.read_csv(RUNS)
cmp = pd.read_csv(COMPARISONS)

require(len(runs) == 180, "Expected 180 run records")
require(len(cmp) == 935, "Expected 935 paired comparisons")

keys = [
    "dataset", "load_percent", "seed", "controller"
]

require(
    not runs.duplicated(keys).any(),
    "Duplicate run records"
)

expected = {
    (d, l, s, c)
    for d, l in CONDITIONS
    for s in range(230, 236)
    for c in CONTROLLERS
}

actual = set(
    tuple(r)
    for r in runs[keys].itertuples(
        index=False, name=None
    )
)

require(actual == expected, "Incomplete experiment coverage")

OUT.mkdir(parents=True)

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 9,
    "axes.titlesize": 12,
    "axes.labelsize": 10,
    "figure.dpi": 120,
    "savefig.dpi": 300,
    "pdf.fonttype": 42,
    "axes.spines.top": False,
    "axes.spines.right": False,
})

created = []

def save(fig, name):
    fig.savefig(
        OUT / f"{name}.png",
        dpi=300,
        bbox_inches="tight",
        facecolor="white"
    )
    fig.savefig(
        OUT / f"{name}.pdf",
        bbox_inches="tight",
        facecolor="white"
    )
    plt.close(fig)
    created.append(name)
    print(f"PASS: {len(created):02d} {name}", flush=True)

def sub(dataset, load, controller=None):
    x = runs[
        (runs.dataset == dataset)
        & (runs.load_percent == load)
    ]
    if controller is not None:
        x = x[x.controller == controller]
    return x

def mean_metric(dataset, load, controller, metric):
    values = sub(dataset, load, controller)[metric]
    require(len(values) == 6, "Missing six-seed group")
    return float(values.mean())

def comparison(dataset, load, controller, metric,
               reference="baseline"):
    x = cmp[
        (cmp.dataset == dataset)
        & (cmp.load_percent == load)
        & (cmp.controller == controller)
        & (cmp.reference == reference)
        & (cmp.metric == metric)
    ]
    require(len(x) == 1, "Missing comparison")
    return x.iloc[0]

def add_zero(ax):
    ax.axhline(0, color="#555555", linewidth=0.8)

# -----------------------------------------------------
# FIGURE 01: ABSOLUTE P95 FCT GROUPED BARS
# FIGURE 02: ABSOLUTE P99 FCT GROUPED BARS
# -----------------------------------------------------

for number, metric, title in [
    (1, "p95_short_fct_ms", "P95"),
    (2, "p99_short_fct_ms", "P99"),
]:
    fig, ax = plt.subplots(figsize=(12, 5.5))
    x = np.arange(len(CONDITIONS))
    width = 0.13

    for i, controller in enumerate(CONTROLLERS):
        y = [
            mean_metric(d, l, controller, metric)
            for d, l in CONDITIONS
        ]
        ax.bar(
            x + (i - 2.5) * width,
            y, width,
            color=COLORS[controller],
            label=NAMES[controller]
        )

    ax.set_xticks(x, LABELS)
    ax.set_ylabel(f"Mean of per-seed {title} FCT (ms)")
    ax.set_title(
        f"{title} Short-Flow Completion Time Across Workloads"
    )
    ax.grid(axis="y", alpha=0.2)
    ax.set_axisbelow(True)
    ax.legend(ncol=3, fontsize=8)
    fig.tight_layout()

    save(
        fig,
        f"figure_{number:02d}_{title.lower()}_grouped_bars"
    )

# -----------------------------------------------------
# FIGURE 03: P99 RELATIVE-CHANGE HEATMAP
# -----------------------------------------------------

data = np.array([
    [
        float(comparison(d, l, c, "p99_short_fct_ms")[
            "mean_paired_change_pct"
        ])
        for d, l in CONDITIONS
    ]
    for c in CONTROLLERS[1:]
])

fig, ax = plt.subplots(figsize=(10.5, 5))
limit = max(1, np.max(np.abs(data)))

img = ax.imshow(
    data,
    cmap="RdBu_r",
    vmin=-limit,
    vmax=limit,
    aspect="auto"
)

ax.set_xticks(range(5), LABELS)
ax.set_yticks(
    range(5),
    [NAMES[c] for c in CONTROLLERS[1:]]
)

for i in range(5):
    for j in range(5):
        value = data[i, j]
        color = (
            "white"
            if abs(value) > limit * 0.65
            else "black"
        )
        ax.text(
            j, i, f"{value:+.1f}%",
            ha="center", va="center",
            color=color
        )

fig.colorbar(
    img, ax=ax,
    label="Mean paired P99 change (%)"
)

ax.set_title(
    "P99 FCT Change Relative to Standard ECN"
)
fig.text(
    0.5, 0.01,
    "Negative = lower P99. Six paired seeds per condition.",
    ha="center", fontsize=9
)
fig.tight_layout(rect=[0, 0.04, 1, 1])

save(fig, "figure_03_p99_relative_heatmap")

# -----------------------------------------------------
# FIGURE 04: P99 BOOTSTRAP CONFIDENCE INTERVALS
# -----------------------------------------------------

fig, axes = plt.subplots(
    1, 3, figsize=(15.5, 5.6), sharey=True
)

for ax, controller in zip(
    axes,
    ["ml_2ms", "ml_5ms", "ml_20ms"]
):
    for i, (dataset, load) in enumerate(CONDITIONS):
        r = comparison(
            dataset, load, controller,
            "p99_short_fct_ms"
        )

        center = float(r.mean_delta)
        low = float(r.ci_low)
        high = float(r.ci_high)

        ax.errorbar(
            center, i,
            xerr=[
                [max(0, center - low)],
                [max(0, high - center)]
            ],
            fmt="o",
            color=COLORS[controller],
            capsize=4
        )

    ax.axvline(
        0, color="#777777", linestyle="--"
    )
    ax.set_title(NAMES[controller])
    ax.set_xlabel("P99 difference versus ECN (ms)")
    ax.grid(axis="x", alpha=0.2)

axes[0].set_yticks(range(5), LABELS)
axes[0].invert_yaxis()

fig.suptitle(
    "Paired P99 Differences with Exploratory 95% CIs"
)
fig.text(
    0.5, 0.01,
    "Six seeds; bootstrap percentile CIs; "
    "not adjusted for multiple comparisons.",
    ha="center", fontsize=9
)
fig.tight_layout(rect=[0, 0.04, 1, 0.94])

save(fig, "figure_04_p99_confidence_intervals")

# -----------------------------------------------------
# FIGURE 05: FCT BOX PLOTS ACROSS SEEDS
# -----------------------------------------------------

dataset, load = "FB_Hadoop", 95

fig, axes = plt.subplots(
    1, 2, figsize=(13, 5.2)
)

for ax, metric, label in zip(
    axes,
    ["p95_short_fct_ms", "p99_short_fct_ms"],
    ["P95", "P99"]
):
    arrays = [
        sub(dataset, load, c)
        .sort_values("seed")[metric]
        .to_numpy()
        for c in CONTROLLERS
    ]

    plot = ax.boxplot(
        arrays,
        patch_artist=True,
        showmeans=True,
        meanprops={
            "marker": "D",
            "markerfacecolor": "white",
            "markeredgecolor": "black",
            "markersize": 4
        }
    )

    for patch, c in zip(
        plot["boxes"], CONTROLLERS
    ):
        patch.set_facecolor(COLORS[c])
        patch.set_alpha(0.65)

    ax.set_xticks(
        range(1, 7),
        [NAMES[c] for c in CONTROLLERS],
        rotation=35,
        ha="right"
    )
    ax.set_ylabel("FCT (ms)")
    ax.set_title(label)
    ax.grid(axis="y", alpha=0.2)

fig.suptitle(
    "Across-Seed Tail-FCT Variability: "
    "FB_Hadoop 95%"
)
fig.tight_layout()

save(fig, "figure_05_p95_p99_seed_boxplots")

# -----------------------------------------------------
# FIGURE 06: FAIRNESS BOX PLOTS
# -----------------------------------------------------

fig, axes = plt.subplots(
    1, 2, figsize=(13, 5)
)

for ax, (dataset, load) in zip(
    axes,
    [("WebSearch", 95), ("FB_Hadoop", 95)]
):
    arrays = [
        sub(dataset, load, c)[
            "sender_fairness_jain_100ms"
        ].dropna().to_numpy()
        for c in CONTROLLERS
    ]

    plot = ax.boxplot(
        arrays,
        patch_artist=True
    )

    for patch, c in zip(
        plot["boxes"], CONTROLLERS
    ):
        patch.set_facecolor(COLORS[c])
        patch.set_alpha(0.65)

    ax.set_xticks(
        range(1, 7),
        [NAMES[c] for c in CONTROLLERS],
        rotation=35,
        ha="right"
    )
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Jain fairness index")
    ax.set_title(f"{dataset}, {load}%")
    ax.grid(axis="y", alpha=0.2)

fig.suptitle(
    "Concurrent-Sender Fairness Proxy Across Seeds"
)
fig.text(
    0.5, 0.01,
    "100-ms eligible windows vary by controller; "
    "demand-sensitive descriptive proxy.",
    ha="center", fontsize=9
)
fig.tight_layout(rect=[0, 0.04, 1, 0.94])

save(fig, "figure_06_fairness_boxplots")

# -----------------------------------------------------
# FIGURE 07: P95 VS P99 TRADE-OFF SCATTER
# -----------------------------------------------------

fig, ax = plt.subplots(figsize=(9, 7))

for controller in CONTROLLERS[1:]:
    xx, yy = [], []

    for d, l in CONDITIONS:
        p95 = comparison(
            d, l, controller, "p95_short_fct_ms"
        )["mean_paired_change_pct"]

        p99 = comparison(
            d, l, controller, "p99_short_fct_ms"
        )["mean_paired_change_pct"]

        xx.append(float(p95))
        yy.append(float(p99))

    ax.scatter(
        xx, yy,
        s=65,
        color=COLORS[controller],
        label=NAMES[controller],
        alpha=0.85
    )

ax.axhline(0, color="gray", linestyle="--")
ax.axvline(0, color="gray", linestyle="--")

ax.set_xlabel("P95 relative change (%)")
ax.set_ylabel("P99 relative change (%)")

ax.set_title(
    "P95–P99 Trade-offs Across Workloads"
)

ax.text(
    0.02, 0.04,
    "Lower-left: both improve",
    transform=ax.transAxes,
    fontsize=9
)

ax.legend()
ax.grid(alpha=0.15)
fig.tight_layout()

save(fig, "figure_07_p95_vs_p99_tradeoff")

# -----------------------------------------------------
# FIGURE 08: SHORT-FLOW GOODPUT
# FIGURE 09: LARGE-FLOW GOODPUT
# -----------------------------------------------------

for number, metric, flow_label in [
    (
        8,
        "mean_short_flow_goodput_mbps",
        "Short-flow"
    ),
    (
        9,
        "mean_large_flow_goodput_mbps",
        "Large-flow"
    )
]:
    fig, axes = plt.subplots(
        1, 2, figsize=(13.5, 5),
        sharey=False
    )

    for ax, dataset in zip(
        axes, ["WebSearch", "FB_Hadoop"]
    ):
        loads = (
            [60, 80, 95]
            if dataset == "WebSearch"
            else [60, 95]
        )

        for c in CONTROLLERS:
            values = [
                mean_metric(
                    dataset, load, c, metric
                )
                for load in loads
            ]

            ax.plot(
                loads, values,
                marker="o",
                linewidth=1.7,
                color=COLORS[c],
                label=NAMES[c]
            )

        ax.set_xticks(loads)
        ax.set_xlabel("Nominal offered load (%)")
        ax.set_ylabel("Mean per-flow goodput (Mbps)")
        ax.set_title(dataset)
        ax.grid(alpha=0.2)

    axes[1].legend(
        fontsize=8, loc="best"
    )

    fig.suptitle(
        f"{flow_label} Application Goodput"
    )
    fig.tight_layout()

    save(
        fig,
        f"figure_{number:02d}_"
        f"{flow_label.lower().replace('-', '_')}_goodput"
    )

# -----------------------------------------------------
# FIGURE 10: QUEUE OCCUPANCY ACROSS LOADS
# -----------------------------------------------------

fig, axes = plt.subplots(
    1, 2, figsize=(13.5, 5)
)

for ax, dataset in zip(
    axes, ["WebSearch", "FB_Hadoop"]
):
    loads = (
        [60, 80, 95]
        if dataset == "WebSearch"
        else [60, 95]
    )

    for c in CONTROLLERS:
        y = [
            mean_metric(
                dataset, l, c,
                "mean_queue_packets"
            )
            for l in loads
        ]

        ax.plot(
            loads, y,
            marker="o",
            color=COLORS[c],
            label=NAMES[c]
        )

    ax.set_xticks(loads)
    ax.set_xlabel("Nominal offered load (%)")
    ax.set_ylabel("Mean sampled queue (packets)")
    ax.set_title(dataset)
    ax.grid(alpha=0.2)

axes[1].legend(fontsize=8)
fig.suptitle(
    "Mean Queue Occupancy by Workload and Load"
)
fig.tight_layout()

save(fig, "figure_10_queue_occupancy_lines")

# -----------------------------------------------------
# FIGURE 11: QUEUE DELAY DISTRIBUTION ACROSS SEEDS
# -----------------------------------------------------

fig, ax = plt.subplots(figsize=(11, 5))

arrays = [
    sub("FB_Hadoop", 95, c)[
        "p95_queue_delay_us"
    ].to_numpy() / 1000.0
    for c in CONTROLLERS
]

plot = ax.boxplot(
    arrays,
    patch_artist=True,
    showmeans=True
)

for patch, c in zip(
    plot["boxes"], CONTROLLERS
):
    patch.set_facecolor(COLORS[c])
    patch.set_alpha(0.65)

ax.set_xticks(
    range(1, 7),
    [NAMES[c] for c in CONTROLLERS]
)
ax.set_ylabel("Per-run P95 queue delay (ms)")
ax.set_title(
    "Queue-Delay Variability: FB_Hadoop 95%"
)
ax.grid(axis="y", alpha=0.2)
fig.tight_layout()

save(fig, "figure_11_queue_delay_boxplot")

# -----------------------------------------------------
# FIGURE 12: FORCED VS UNFORCED ECN MARKS
# -----------------------------------------------------

fig, ax = plt.subplots(figsize=(12, 5))

x = np.arange(6)
width = 0.35

for offset, (dataset, load) in enumerate([
    ("WebSearch", 95),
    ("FB_Hadoop", 95)
]):
    forced = [
        mean_metric(
            dataset, load, c,
            "ecn_forced_marks"
        )
        for c in CONTROLLERS
    ]

    unforced = [
        mean_metric(
            dataset, load, c,
            "ecn_unforced_marks"
        )
        for c in CONTROLLERS
    ]

    positions = x + (offset - 0.5) * width

    ax.bar(
        positions,
        forced,
        width,
        color="#c2410c" if offset == 0
        else "#2563eb",
        alpha=0.9,
        label=f"{dataset}: forced"
    )

    ax.bar(
        positions,
        unforced,
        width,
        bottom=forced,
        color="#fdba74" if offset == 0
        else "#93c5fd",
        label=f"{dataset}: unforced"
    )

ax.set_xticks(
    x, [NAMES[c] for c in CONTROLLERS]
)
ax.set_ylabel("Mean ECN marks per run")
ax.set_title(
    "ECN Marking Composition at 95% Nominal Load"
)
ax.legend(ncol=2, fontsize=8)
ax.grid(axis="y", alpha=0.2)
ax.set_axisbelow(True)
fig.tight_layout()

save(fig, "figure_12_ecn_marking_stacked_bars")

# -----------------------------------------------------
# FIGURE 13: COMPUTATIONAL OVERHEAD
# -----------------------------------------------------

text = BENCHMARK.read_text()

timings = {}

for horizon in (2, 5, 20):
    section = re.search(
        rf"========== {horizon} ms MODEL =========="
        rf"(.*?)(?==========|\Z)",
        text,
        flags=re.S
    )

    require(
        section is not None,
        f"Missing {horizon}ms benchmark"
    )

    def extract(name):
        match = re.search(
            rf"^{re.escape(name)}:\s*([0-9.]+)",
            section.group(1),
            flags=re.M
        )
        require(match is not None, f"Missing {name}")
        return float(match.group(1))

    timings[horizon] = (
        extract("History_only_ns_per_sample"),
        extract("History_plus_ML_ns_per_sample")
    )

fig, ax = plt.subplots(figsize=(9, 4.8))

x = np.arange(3)
history = [
    timings[h][0] for h in (2, 5, 20)
]
full = [
    timings[h][1] for h in (2, 5, 20)
]
incremental = [
    max(0, b - a)
    for a, b in zip(history, full)
]

ax.bar(
    x, history,
    color="#94a3b8",
    label="Queue history"
)

ax.bar(
    x, incremental,
    bottom=history,
    color="#2563eb",
    label="Incremental logistic inference"
)

for i, total in enumerate(full):
    ax.text(
        i, total + 0.6,
        f"{total:.2f} ns",
        ha="center",
        fontsize=9
    )

ax.set_xticks(
    x, ["2 ms", "5 ms", "20 ms"]
)
ax.set_ylim(0, max(full) * 1.20)
ax.set_ylabel("Nanoseconds per queue sample")
ax.set_title(
    "Measured Logistic-Regression Computation Cost"
)
ax.legend()
ax.grid(axis="y", alpha=0.2)
fig.tight_layout()

save(fig, "figure_13_predictor_overhead")

# -----------------------------------------------------
# FIGURE 14: SUMMARY TABLE FOR FIVE WORKLOADS
# -----------------------------------------------------

table_rows = []

for dataset, load in CONDITIONS:
    baseline_p99 = mean_metric(
        dataset, load,
        "baseline", "p99_short_fct_ms"
    )

    best_ml = min(
        ["ml_2ms", "ml_5ms", "ml_20ms"],
        key=lambda c: mean_metric(
            dataset, load, c,
            "p99_short_fct_ms"
        )
    )

    p95 = comparison(
        dataset, load, best_ml,
        "p95_short_fct_ms"
    )["mean_paired_change_pct"]

    p99 = comparison(
        dataset, load, best_ml,
        "p99_short_fct_ms"
    )["mean_paired_change_pct"]

    queue = comparison(
        dataset, load, best_ml,
        "mean_queue_packets"
    )["mean_paired_change_pct"]

    table_rows.append([
        f"{dataset} {load}%",
        NAMES[best_ml],
        f"{baseline_p99:.1f}",
        f"{float(p95):+.1f}%",
        f"{float(p99):+.1f}%",
        f"{float(queue):+.1f}%",
    ])

fig, ax = plt.subplots(figsize=(11, 3.8))
ax.axis("off")

column_labels = [
    "Condition",
    "Lowest-P99 ML",
    "ECN P99\n(ms)",
    "ML P95\nchange",
    "ML P99\nchange",
    "ML queue\nchange"
]

table = ax.table(
    cellText=table_rows,
    colLabels=column_labels,
    cellLoc="center",
    loc="center",
    colWidths=[
        0.21, 0.18, 0.16,
        0.15, 0.15, 0.15
    ]
)

table.auto_set_font_size(False)
table.set_fontsize(9)
table.scale(1, 1.65)

for (r, c), cell in table.get_celld().items():
    cell.set_edgecolor("#cbd5e1")
    if r == 0:
        cell.set_facecolor("#e2e8f0")
        cell.set_text_props(weight="bold")
    elif r % 2 == 0:
        cell.set_facecolor("#f8fafc")

ax.set_title(
    "Descriptive ML Horizon Comparison",
    fontsize=12,
    pad=18
)

fig.text(
    0.5, 0.04,
    "Best horizon selected retrospectively by mean P99. "
    "Not a prespecified deployable selection policy.",
    ha="center", fontsize=8
)

fig.tight_layout(rect=[0, 0.08, 1, 0.95])

save(fig, "figure_14_research_summary_table")

# -----------------------------------------------------
# FINAL VALIDATION
# -----------------------------------------------------

png_files = sorted(OUT.glob("*.png"))
pdf_files = sorted(OUT.glob("*.pdf"))

require(len(png_files) == 14, "Expected 14 PNG figures")
require(len(pdf_files) == 14, "Expected 14 PDF figures")

manifest = {
    "research": "Delay-Aware Predictive ECN",
    "source_runs": str(RUNS),
    "source_comparisons": str(COMPARISONS),
    "source_benchmark": str(BENCHMARK),
    "figure_count": len(created),
    "figure_names": created,
    "notes": [
        "Each workload condition contains six evaluation seeds.",
        "P95 and P99 are averages of run-level quantiles.",
        "Relative percentages are averages of paired seed changes.",
        "Confidence intervals are exploratory and unadjusted.",
        "Fairness is a demand-sensitive sender-level proxy.",
        "Computational overhead is a standalone microbenchmark.",
        "Horizon selection in the summary table is retrospective.",
        "No additional simulations were executed."
    ]
}

(OUT / "FIGURE_MANIFEST.json").write_text(
    json.dumps(manifest, indent=2) + "\n"
)

print()
print("========== COMPREHENSIVE FIGURE AUDIT ==========")
print("PASS: 14 distinct research figures")
print("PASS: 14 high-resolution PNG files")
print("PASS: 14 PDF files")
print("PASS: Figure provenance recorded")
print("PASS: Original experiments unchanged")
print("OUTPUT:", OUT)
