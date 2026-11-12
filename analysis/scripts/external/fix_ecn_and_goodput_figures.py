from pathlib import Path
from collections import Counter
import csv
import hashlib
import json
import math

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path.home() / "ns3-external-validation"
CAMPAIGN = ROOT / "external_evaluation_180"
SOURCE = ROOT / "external_analysis/six_metrics/six_metrics_180_runs.csv"
OUT = ROOT / "research_figures/external_corrected_v2"

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
ALTERNATIVES = CONTROLLERS[1:]

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

require(SOURCE.is_file(), f"Missing {SOURCE}")
require(not OUT.exists(), f"STOP: Output exists: {OUT}")

runs = pd.read_csv(SOURCE)
require(len(runs) == 180, "Expected 180 runs")

keycols = ["dataset", "load_percent", "seed", "controller"]
require(not runs.duplicated(keycols).any(), "Duplicate runs")

expected = {
    (dataset, load, seed, controller)
    for dataset, load in CONDITIONS
    for seed in range(230, 236)
    for controller in CONTROLLERS
}
actual = set(runs[keycols].itertuples(index=False, name=None))
require(actual == expected, "Incomplete campaign coverage")

OUT.mkdir(parents=True)

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "pdf.fonttype": 42,
    "axes.spines.top": False,
    "axes.spines.right": False,
})

def save(fig, name):
    fig.savefig(
        OUT / (name + ".png"),
        dpi=300, bbox_inches="tight", facecolor="white"
    )
    fig.savefig(
        OUT / (name + ".pdf"),
        bbox_inches="tight", facecolor="white"
    )
    plt.close(fig)
    print("PASS: Figure generated:", name, flush=True)

# =====================================================
# A. REPARSE ACTUAL ECN REASONS
# =====================================================

print("========== REPAIR ECN CLASSIFICATION ==========", flush=True)

corrected = runs.copy()
unknown = Counter()

for index, row in runs.iterrows():
    folder = (
        CAMPAIGN / row["dataset"]
        / f"load_{int(row['load_percent'])}"
        / f"seed_{int(row['seed'])}"
        / row["controller"]
    )

    trace = folder / "bursty-ecn.dat"
    require(trace.is_file(), f"Missing: {trace}")

    counts = Counter()

    with trace.open() as f:
        for line in f:
            if not line.strip() or line.startswith("#"):
                continue

            fields = line.split(maxsplit=5)
            require(
                len(fields) == 6,
                f"Invalid ECN record in {trace}: {line!r}"
            )

            reason = fields[5].strip()
            counts[reason] += 1

    for reason in counts:
        if reason not in ("Forced mark", "Unforced mark"):
            unknown[reason] += counts[reason]

    forced = counts["Forced mark"]
    unforced = counts["Unforced mark"]
    total = forced + unforced

    require(
        not any(reason not in ("Forced mark", "Unforced mark")
                for reason in counts),
        f"Unexpected ECN reason in {trace}: {dict(counts)}"
    )

    require(
        total == int(row["ecn_marks_total"]),
        f"ECN total mismatch: {folder}: "
        f"{total} vs {row['ecn_marks_total']}"
    )

    corrected.at[index, "ecn_forced_marks"] = forced
    corrected.at[index, "ecn_unforced_marks"] = unforced

    if (index + 1) % 30 == 0:
        print(f"PASS: {index + 1}/180 ECN traces verified",
              flush=True)

require(
    (corrected["ecn_forced_marks"] +
     corrected["ecn_unforced_marks"] ==
     corrected["ecn_marks_total"]).all(),
    "Final ECN mark integrity check failed"
)

corrected_path = OUT / "ecn_corrected_180_runs.csv"
corrected.to_csv(corrected_path, index=False)

print("PASS: All ECN counts reclassified and reconciled")

# =====================================================
# B. FIX FIGURE 12: STACKED ECN BARS
# =====================================================

fig, axes = plt.subplots(1, 2, figsize=(16, 6))

for ax, (dataset, load) in zip(
    axes, [("WebSearch", 95), ("FB_Hadoop", 95)]
):
    selected = corrected[
        (corrected["dataset"] == dataset)
        & (corrected["load_percent"] == load)
    ]

    forced = []
    unforced = []

    for controller in CONTROLLERS:
        group = selected[
            selected["controller"] == controller
        ]
        require(len(group) == 6, "Missing controller seeds")
        forced.append(group["ecn_forced_marks"].mean())
        unforced.append(group["ecn_unforced_marks"].mean())

    x = np.arange(len(CONTROLLERS))

    ax.bar(
        x, unforced,
        color="#60a5fa",
        label="Unforced ECN marks"
    )

    ax.bar(
        x, forced, bottom=unforced,
        color="#ea580c",
        label="Forced ECN marks"
    )

    ax.set_xticks(
        x,
        [NAMES[c] for c in CONTROLLERS],
        rotation=35, ha="right"
    )
    ax.set_ylabel("Mean ECN-marked packets per run")
    ax.set_title(f"{dataset} — {load}% nominal load")
    ax.grid(axis="y", alpha=0.2)
    ax.set_axisbelow(True)

    for i, total in enumerate(
        np.array(forced) + np.array(unforced)
    ):
        ax.text(
            i, total * 1.02,
            f"{total:,.0f}",
            ha="center", va="bottom", fontsize=8
        )

    ax.set_ylim(
        0,
        max(np.array(forced) + np.array(unforced)) * 1.17
    )

axes[0].legend(loc="upper left", fontsize=9)

fig.suptitle(
    "ECN Marking Composition Across Controllers",
    fontsize=14
)
fig.tight_layout(rect=[0, 0, 1, 0.95])

save(fig, "figure_12_ecn_marking_CORRECTED")

# =====================================================
# C. GOODPUT: PAIRED DELTA IN Mbps
# =====================================================

def plot_goodput(metric, label, filename):
    fig, axes = plt.subplots(
        len(CONDITIONS), 1,
        figsize=(12, 15),
        sharex=False
    )

    for ax, (dataset, load) in zip(axes, CONDITIONS):
        subset = runs[
            (runs["dataset"] == dataset)
            & (runs["load_percent"] == load)
        ]

        baseline = subset[
            subset["controller"] == "baseline"
        ].set_index("seed")[metric]

        require(len(baseline) == 6, "Missing baseline seeds")

        means = []
        percentages = []
        y = np.arange(len(ALTERNATIVES))

        for controller in ALTERNATIVES:
            observed = subset[
                subset["controller"] == controller
            ].set_index("seed")[metric]

            require(
                set(observed.index) == set(baseline.index),
                "Unpaired goodput observations"
            )

            observed = observed.loc[baseline.index]

            delta = observed - baseline
            relative = 100 * delta / baseline

            means.append(float(delta.mean()))
            percentages.append(float(relative.mean()))

        ax.barh(
            y, means,
            color=[COLORS[c] for c in ALTERNATIVES],
            height=0.64
        )

        ax.axvline(
            0, color="#111827",
            linestyle="--", linewidth=1
        )

        span = max(abs(v) for v in means)
        span = max(span, 0.02)
        limit = span * 1.55

        ax.set_xlim(-limit, limit)

        for i, (delta, pct) in enumerate(
            zip(means, percentages)
        ):
            offset = span * 0.05
            ax.text(
                delta + (offset if delta >= 0 else -offset),
                i,
                f"{delta:+.3f} Mbps ({pct:+.2f}%)",
                ha="left" if delta >= 0 else "right",
                va="center", fontsize=9
            )

        ax.set_yticks(
            y, [NAMES[c] for c in ALTERNATIVES]
        )
        ax.invert_yaxis()
        ax.set_title(
            f"{dataset} {load}%   |   "
            f"Standard ECN mean: {baseline.mean():.3f} Mbps",
            fontsize=11
        )
        ax.set_xlabel(
            "Mean paired goodput difference vs standard ECN (Mbps)"
        )
        ax.grid(axis="x", alpha=0.2)
        ax.set_axisbelow(True)

    fig.suptitle(
        f"{label} Goodput — Zoomed Controller Differences",
        fontsize=15
    )
    fig.text(
        0.5, 0.005,
        "Bars show mean paired Mbps differences across six seeds. "
        "Percentages are means of seed-level relative differences. "
        "Each panel uses its own explicitly labeled scale.",
        ha="center", fontsize=9
    )

    fig.tight_layout(rect=[0, 0.025, 1, 0.975])
    save(fig, filename)

plot_goodput(
    "mean_short_flow_goodput_mbps",
    "Short-flow application",
    "figure_08_short_goodput_DELTA"
)

plot_goodput(
    "mean_large_flow_goodput_mbps",
    "Large-flow application",
    "figure_09_large_goodput_DELTA"
)

# =====================================================
# D. PROVENANCE
# =====================================================

manifest = {
    "purpose": "Correct ECN reason parsing and improve goodput scales",
    "original_run_results": str(SOURCE),
    "original_run_results_sha256": sha(SOURCE),
    "corrected_results": str(corrected_path),
    "corrected_results_sha256": sha(corrected_path),
    "runs_verified": 180,
    "fix": "Strip trailing whitespace from the final ECN reason field",
    "goodput_metric": "Mean of six paired differences in Mbps",
    "outputs": [
        "figure_12_ecn_marking_CORRECTED",
        "figure_08_short_goodput_DELTA",
        "figure_09_large_goodput_DELTA"
    ],
    "original_simulation_results_modified": False
}

(OUT / "CORRECTION_MANIFEST.json").write_text(
    json.dumps(manifest, indent=2) + "\n"
)

print()
print("========== CORRECTION AUDIT ==========")
print("PASS: 180/180 ECN traces reconciled")
print("PASS: Forced/unforced ECN marks correctly classified")
print("PASS: Short-flow goodput scale improved")
print("PASS: Large-flow goodput scale improved")
print("PASS: Three corrected figures, PNG and PDF")
print("PASS: Original research outputs preserved")
print("OUTPUT:", OUT)
