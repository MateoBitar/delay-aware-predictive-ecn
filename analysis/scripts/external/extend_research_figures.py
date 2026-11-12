from pathlib import Path
import csv
import json
import os
import re
import hashlib

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HOME = Path.home()
ROOT = HOME / "ns3-external-validation"
FIG = ROOT / "research_figures/external_comprehensive"

COMPARISONS = (
    ROOT / "external_analysis/six_metric_comparisons"
    / "all_paired_metric_comparisons.csv"
)

ORIGINALS = [
    HOME / "ns3-research-v2/ns-3.47",
    HOME / "ns3-reproduction-test/ns-3.47",
]

HORIZONS = [2, 5, 20]

CONDITIONS = [
    ("WebSearch", 60, "WebSearch 60%"),
    ("WebSearch", 80, "WebSearch 80%"),
    ("WebSearch", 95, "WebSearch 95%"),
    ("FB_Hadoop", 60, "FB_Hadoop 60%"),
    ("FB_Hadoop", 95, "FB_Hadoop 95%"),
]

COLORS = [
    "#2563eb",
    "#059669",
    "#9333ea",
    "#d97706",
    "#dc2626",
]

def require(ok, msg):
    if not ok:
        raise RuntimeError(msg)

def hash_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def show_json_structure(path):
    try:
        data = json.loads(path.read_text())
        print("FILE:", path)
        print("SHA256:", hash_file(path))

        if isinstance(data, dict):
            print("TOP-LEVEL KEYS:", list(data.keys())[:35])

            for key, value in data.items():
                if isinstance(value, dict):
                    print(
                        f"  {key}: nested keys",
                        list(value.keys())[:22]
                    )
                elif isinstance(value, list):
                    print(f"  {key}: list length {len(value)}")
                else:
                    print(f"  {key}: {str(value)[:130]}")

        elif isinstance(data, list):
            print("LIST LENGTH:", len(data))
            if data:
                print("FIRST ITEM:", str(data[0])[:400])

    except Exception as exc:
        print("REVIEW:", path, exc)

def audit_csv(path):
    try:
        with path.open(newline="", errors="replace") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            first = next(reader, None)

        print("\nFILE:", path)
        print("HEADER:", header[:35])
        if first:
            print("FIRST ROW:", str(first)[:600])

    except Exception as exc:
        print("REVIEW:", path, exc)

# ======================================================
# FIGURE 19 — ML HORIZON SENSITIVITY
# ======================================================

require(COMPARISONS.is_file(), "Missing external comparisons")
require(FIG.is_dir(), "Missing figure directory")

data = pd.read_csv(COMPARISONS)

require(len(data) == 935, "Expected 935 comparison records")

name = "figure_19_prediction_horizon_sensitivity"

for ext in ("png", "pdf"):
    require(
        not (FIG / f"{name}.{ext}").exists(),
        f"STOP: Figure already exists: {name}.{ext}"
    )

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 11,
    "pdf.fonttype": 42,
    "axes.spines.top": False,
    "axes.spines.right": False,
})

fig, axes = plt.subplots(
    1, 2,
    figsize=(15, 6),
    sharex=True,
    sharey=False
)

for ax, metric, title in [
    (axes[0], "p95_short_fct_ms", "P95 FCT"),
    (axes[1], "p99_short_fct_ms", "P99 FCT"),
]:
    for (dataset, load, label), color in zip(
        CONDITIONS, COLORS
    ):
        y = []

        for horizon in HORIZONS:
            matches = data[
                (data["dataset"] == dataset)
                & (data["load_percent"] == load)
                & (
                    data["controller"]
                    == f"ml_{horizon}ms"
                )
                & (data["reference"] == "baseline")
                & (data["metric"] == metric)
            ]

            require(
                len(matches) == 1,
                f"Missing {dataset} {load} {horizon} {metric}"
            )

            y.append(
                float(
                    matches.iloc[0][
                        "mean_paired_change_pct"
                    ]
                )
            )

        ax.plot(
            HORIZONS,
            y,
            marker="o",
            linewidth=2,
            markersize=7,
            color=color,
            label=label
        )

    ax.axhline(
        0,
        color="#374151",
        linestyle="--",
        linewidth=1
    )

    ax.set_xticks(HORIZONS)
    ax.set_xlabel("Prediction horizon (ms)")
    ax.set_ylabel(
        "Mean paired FCT change vs standard ECN (%)"
    )
    ax.set_title(title)
    ax.grid(alpha=0.2)

axes[1].legend(
    loc="best",
    fontsize=9,
    title="Workload condition"
)

fig.suptitle(
    "Sensitivity of Short-Flow Tail Latency "
    "to Logistic-Regression Prediction Horizon",
    fontsize=14
)

fig.text(
    0.5, 0.015,
    "Negative = lower FCT. "
    "Each point averages six paired seed-level percentages. "
    "Horizons are fixed models, not dynamically selected.",
    ha="center",
    fontsize=9
)

fig.tight_layout(rect=[0, 0.05, 1, 0.93])

fig.savefig(
    FIG / f"{name}.png",
    dpi=300,
    bbox_inches="tight",
    facecolor="white"
)
fig.savefig(
    FIG / f"{name}.pdf",
    bbox_inches="tight",
    facecolor="white"
)
plt.close(fig)

print("========== FIGURE 19 ==========")
print("PASS: Prediction-horizon sensitivity generated")
print("PNG:", FIG / f"{name}.png")
print("PDF:", FIG / f"{name}.pdf")

# ======================================================
# ORIGINAL STUDY — DISCOVER REAL DATA FILES
# ======================================================

print("\n========== ORIGINAL STUDY FILE AUDIT ==========")

keywords = re.compile(
    r"result|summary|metric|experiment|"
    r"comparison|validation|horizon|analysis",
    re.IGNORECASE
)

for workspace in ORIGINALS:
    print("\nWORKSPACE:", workspace)

    if not workspace.is_dir():
        print("NOT FOUND")
        continue

    candidates = []

    # Search metadata and result files, avoiding source
    # trees, build outputs and very large trace directories.
    for directory, dirs, filenames in os.walk(workspace):
        current = Path(directory)
        depth = len(current.relative_to(workspace).parts)

        dirs[:] = [
            d for d in dirs
            if d not in (
                "build", ".git", "__pycache__",
                ".venv", "venv", "node_modules"
            )
            and (depth < 6)
        ]

        for filename in filenames:
            path = current / filename

            if (
                path.suffix.lower() in (".csv", ".json")
                and keywords.search(
                    filename + " " + str(current)
                )
            ):
                candidates.append(path)

    print("Candidate CSV/JSON files:", len(candidates))

    for path in sorted(candidates)[:35]:
        print(
            " ",
            path.relative_to(workspace),
            f"({path.stat().st_size:,} bytes)"
        )

    print("\nORIGINAL RESULT SCHEMA SAMPLES:")

    csvs = [
        p for p in candidates
        if p.suffix.lower() == ".csv"
        and p.stat().st_size < 20_000_000
    ]

    for path in sorted(csvs)[:5]:
        audit_csv(path)

# ======================================================
# PREDICTION QUALITY — VERIFY MODEL VALIDATION FILES
# ======================================================

print("\n========== FROZEN PREDICTOR QUALITY AUDIT ==========")

model_folder = (
    ROOT / "ns-3.47/research_horizon_study"
    / "horizon_models"
)

for horizon in HORIZONS:
    path = model_folder / f"results_{horizon}ms.json"

    if path.is_file():
        show_json_structure(path)
    else:
        print("NOT FOUND:", path)

print("\n========== STEP 28A AUDIT ==========")
print("PASS: Figure 19 generated from validated comparisons")
print("PASS: Original-workspace discovery completed")
print("PASS: Predictor-validation schema inspection completed")
print("NOTE: Original and external metrics remain separate")
print("NOTE: No simulations or models were modified")
