from pathlib import Path
from collections import Counter
import csv
import hashlib
import json
import os

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HOME = Path.home()
ROOT = HOME / "ns3-external-validation"
ORIGINAL = HOME / "ns3-research-v2/ns-3.47"

FIG = ROOT / "research_figures/external_comprehensive"
MODELS = ROOT / "ns-3.47/research_horizon_study/horizon_models"
CMP = ROOT / (
    "external_analysis/six_metric_comparisons/"
    "all_paired_metric_comparisons.csv"
)

NAME = "figure_20_prediction_quality_vs_external_fct"

def require(ok, message):
    if not ok:
        raise RuntimeError(message)

require(FIG.is_dir(), "Figure directory missing")
require(CMP.is_file(), "Comparison CSV missing")
require(ORIGINAL.is_dir(), "Original experiment workspace missing")

for extension in ("png", "pdf"):
    require(
        not (FIG / f"{NAME}.{extension}").exists(),
        f"STOP: Figure 20 already exists ({extension})"
    )

# --------------------------------------------------
# A. Held-out synthetic prediction-quality metrics
# --------------------------------------------------

horizons = [2, 5, 20]
quality = {}

for horizon in horizons:
    path = MODELS / f"results_{horizon}ms.json"
    require(path.is_file(), f"Missing {path}")

    data = json.loads(path.read_text())
    require(data["horizon_ms"] == horizon,
            "Model horizon mismatch")

    test = data["test"]
    quality[horizon] = {
        key: float(test[key])
        for key in ("precision", "recall", "f1")
    }

# --------------------------------------------------
# B. External-workload P99 metrics
# --------------------------------------------------

df = pd.read_csv(CMP)

conditions = [
    ("WebSearch", 60, "WebSearch 60%"),
    ("WebSearch", 80, "WebSearch 80%"),
    ("WebSearch", 95, "WebSearch 95%"),
    ("FB_Hadoop", 60, "FB_Hadoop 60%"),
    ("FB_Hadoop", 95, "FB_Hadoop 95%"),
]

external = {}

for horizon in horizons:
    external[horizon] = []

    for dataset, load, label in conditions:
        selected = df[
            (df["dataset"] == dataset)
            & (df["load_percent"] == load)
            & (df["controller"] == f"ml_{horizon}ms")
            & (df["reference"] == "baseline")
            & (df["metric"] == "p99_short_fct_ms")
        ]

        require(len(selected) == 1,
                f"Missing external result: {label}, {horizon}ms")

        external[horizon].append(
            float(selected.iloc[0]["mean_paired_change_pct"])
        )

# --------------------------------------------------
# C. Publication figure with separated evidence
# --------------------------------------------------

colors = {
    2: "#2563eb",
    5: "#059669",
    20: "#9333ea",
}

fig, axes = plt.subplots(
    1, 2, figsize=(15, 6.5),
    gridspec_kw={"width_ratios": [1, 1.5]}
)

ax = axes[0]
x = np.arange(3)
width = 0.24

for i, metric in enumerate(("precision", "recall", "f1")):
    values = [quality[h][metric] for h in horizons]
    bars = ax.bar(
        x + (i - 1) * width,
        values,
        width=width,
        label=metric.capitalize(),
    )
    for bar, value in zip(bars, values):
        ax.annotate(
            f"{value:.2f}",
            (bar.get_x() + bar.get_width() / 2,
             bar.get_height()),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            fontsize=9,
        )

ax.set_xticks(x, [f"{h} ms" for h in horizons])
ax.set_ylim(0, 1.05)
ax.set_ylabel("Held-out classification metric")
ax.set_xlabel("Prediction horizon")
ax.set_title("A. Synthetic held-out prediction quality")
ax.legend()
ax.grid(axis="y", alpha=0.2)
ax.set_axisbelow(True)

ax = axes[1]
y = np.arange(len(conditions))
offsets = [-0.20, 0, 0.20]

for horizon, offset in zip(horizons, offsets):
    ax.scatter(
        external[horizon],
        y + offset,
        s=85,
        color=colors[horizon],
        label=f"ML {horizon} ms",
        zorder=3,
    )

ax.axvline(0, color="#374151", linestyle="--")
ax.set_yticks(y, [item[2] for item in conditions])
ax.invert_yaxis()
ax.set_xlabel("Mean paired P99 FCT change vs ECN (%)")
ax.set_title("B. External-workload latency outcomes")
ax.legend(loc="lower right")
ax.grid(axis="x", alpha=0.2)

fig.suptitle(
    "Offline Predictor Quality and Observed Tail-Latency Outcomes",
    fontsize=15,
)

fig.text(
    0.5, 0.015,
    "Panels use different evaluation workloads. "
    "No causal relationship between F1 and FCT is inferred. "
    "Negative P99 change = lower latency.",
    ha="center",
    fontsize=9,
)

fig.tight_layout(rect=[0, 0.055, 1, 0.94])

for extension in ("png", "pdf"):
    fig.savefig(
        FIG / f"{NAME}.{extension}",
        dpi=300 if extension == "png" else None,
        bbox_inches="tight",
        facecolor="white",
    )

plt.close(fig)

print("========== FIGURE 20 ==========")
print("PASS: Synthetic held-out precision/recall/F1 plotted")
print("PASS: External-workload P99 changes plotted separately")
print("PASS: No cross-workload pooling")
print("OUTPUT:", FIG / f"{NAME}.png")

# --------------------------------------------------
# D. Locate original final controller results
# --------------------------------------------------

print("\n========== ORIGINAL CONTROLLER RESULTS SEARCH ==========")

candidates = []

for directory, dirs, files in os.walk(ORIGINAL):
    current = Path(directory)
    relative = current.relative_to(ORIGINAL)

    dirs[:] = [
        d for d in dirs
        if d not in (
            "build", ".git", "__pycache__",
            "baseline_dataset", "horizon_models",
            "node_modules",
        )
    ]

    if len(relative.parts) > 7:
        dirs[:] = []
        continue

    for filename in files:
        path = current / filename

        if path.suffix.lower() != ".csv":
            continue
        if path.stat().st_size > 10_000_000:
            continue

        with path.open(errors="replace") as f:
            header = f.readline().strip().lower()

        terms = (
            "controller", "scenario", "condition", "seed",
            "p95", "p99", "fct", "mode"
        )
        score = sum(term in header for term in terms)

        name = filename.lower()
        if "result" in name or "summary" in name:
            score += 2
        if "comparison" in name or "final" in name:
            score += 2
        if "baseline" in str(relative).lower():
            score -= 1

        if score >= 3:
            candidates.append((score, path, header))

candidates.sort(key=lambda x: (-x[0], str(x[1])))

print("Candidate final-results CSV files:", len(candidates))

for score, path, header in candidates[:35]:
    print()
    print("Score:", score)
    print("File:", path.relative_to(ORIGINAL))
    print("Bytes:", path.stat().st_size)
    print("Header:", header[:300])

# Show likely top-level research output folders.
print("\n========== RESEARCH OUTPUT DIRECTORIES ==========")

study = ORIGINAL / "research_horizon_study"

if study.is_dir():
    for item in sorted(study.iterdir()):
        if item.is_dir():
            print("DIR:", item.name)
        elif item.suffix in (".csv", ".json"):
            print("FILE:", item.name)

print("\n========== STEP 28B AUDIT ==========")
print("PASS: Figure 20 generated in PNG and PDF")
print("PASS: Original result-file discovery completed")
print("PASS: No experiments or models modified")
