from pathlib import Path
import csv
import json
import numpy as np

ROOT = Path("research_validation_background_tracing")
DATA = ROOT / "baseline_101"
OUT = ROOT / "offline_validation_5ms"
OUT.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------
# Load frozen model
# ---------------------------------------------------------
tokens = Path("ml_reference.model").read_text().split()

assert tokens[0] == "NS3_LOGISTIC_V1"

horizon = float(tokens[1])
threshold = float(tokens[2])
cutoff = float(tokens[3])
bias = float(tokens[4])

means = np.array([float(x) for x in tokens[5:11]])
stds = np.array([float(x) for x in tokens[11:17]])
coef = np.array([float(x) for x in tokens[17:23]])

assert len(tokens) == 23
assert horizon == 5
assert threshold == 20
assert np.all(stds > 0)

# ---------------------------------------------------------
# Load uncontrolled baseline queue and trend alerts
# ---------------------------------------------------------
queue = np.atleast_2d(
    np.loadtxt(DATA / "bursty-queue.dat", comments="#")
)

trend = np.atleast_2d(
    np.loadtxt(DATA / "bursty-predictions.dat", comments="#")
)

t = queue[:, 0]
q = queue[:, 1]

assert len(queue) == len(trend)
assert np.allclose(t, trend[:, 0], atol=1e-9, rtol=0)
assert np.all(np.diff(t) > 0)

# The C++ code requires six samples.
eligible = (np.arange(len(q)) >= 5) & (q < threshold)

# ---------------------------------------------------------
# Ground truth: future upward threshold crossings
# ---------------------------------------------------------
crossing_indices = np.flatnonzero(
    (q[:-1] < threshold) &
    (q[1:] >= threshold)
) + 1

crossings = t[crossing_indices]

y = np.zeros(len(q), dtype=bool)

for i in np.flatnonzero(eligible):
    future = crossings[
        (crossings > t[i]) &
        (crossings <= t[i] + horizon / 1000 + 1e-9)
    ]
    y[i] = len(future) > 0

# Check against previously saved reference labels.
saved = np.load(DATA / "offline_labels_5ms.npz")

assert np.allclose(t, saved["time"])
assert np.array_equal(
    y[eligible].astype(int),
    saved["label"][eligible].astype(int)
), "Ground-truth labels do not match the saved reference"

# ---------------------------------------------------------
# Reproduce exact C++ logistic-regression features
# ---------------------------------------------------------
prob = np.full(len(q), np.nan)

for i in range(5, len(q)):
    window = q[i-5:i+1]

    features = np.array([
        q[i],
        q[i] - q[i-1],
        (q[i] - q[i-3]) / 3.0,
        (q[i] - q[i-5]) / 5.0,
        np.mean(window),
        np.max(window) - np.min(window)
    ])

    logit = bias + np.dot(
        coef,
        (features - means) / stds
    )

    # Numerically stable sigmoid.
    if logit >= 0:
        prob[i] = 1.0 / (1.0 + np.exp(-logit))
    else:
        z = np.exp(logit)
        prob[i] = z / (1.0 + z)

ml_alert = eligible & (prob >= cutoff)

# Trend alerts from the SAME uncontrolled baseline trace.
# Column 4 (zero-based) is the C++ "Alert" field.
trend_alert = eligible & (trend[:, 4] > 0.5)

# ---------------------------------------------------------
# Sample-level evaluation
# ---------------------------------------------------------
def metrics(pred):
    actual = y[eligible]
    predicted = pred[eligible]

    tp = int(np.sum(predicted & actual))
    fp = int(np.sum(predicted & ~actual))
    fn = int(np.sum(~predicted & actual))
    tn = int(np.sum(~predicted & ~actual))

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    specificity = tn / (tn + fp) if tn + fp else 0.0
    f1 = (
        2 * tp / (2 * tp + fp + fn)
        if 2 * tp + fp + fn else 0.0
    )

    return {
        "eligible_samples": int(eligible.sum()),
        "positive_samples": int(y[eligible].sum()),
        "TP": tp,
        "FP": fp,
        "FN": fn,
        "TN": tn,
        "precision": precision,
        "recall": recall,
        "specificity": specificity,
        "f1": f1,
        "false_positive_rate": (
            fp / (fp + tn) if fp + tn else 0.0
        )
    }

# ---------------------------------------------------------
# Group threshold crossings into congestion episodes
# ---------------------------------------------------------
episodes = []

for event in crossings:
    if not episodes or event - episodes[-1][-1] > 0.030:
        episodes.append([float(event)])
    else:
        episodes[-1].append(float(event))

# Use earliest warning within 5 ms before each episode.
# This avoids selecting only the last alert before onset.
def episode_metrics(alert):
    results = []

    for group in episodes:
        onset = group[0]

        candidates = np.flatnonzero(
            alert &
            (t < onset) &
            (t >= onset - horizon / 1000 - 1e-9)
        )

        if len(candidates):
            warning = float(t[candidates[0]])
            lead = (onset - warning) * 1000
        else:
            warning = None
            lead = None

        results.append({
            "episode_onset_s": onset,
            "crossings_in_group": len(group),
            "warning_s": warning,
            "lead_ms": lead,
            "detected": warning is not None
        })

    detected = sum(row["detected"] for row in results)

    leads = [
        row["lead_ms"]
        for row in results
        if row["lead_ms"] is not None
    ]

    summary = {
        "episodes": len(results),
        "detected": detected,
        "missed": len(results) - detected,
        "event_recall": detected / len(results) if results else 0,
        "mean_lead_ms": float(np.mean(leads)) if leads else None,
        "median_lead_ms": float(np.median(leads)) if leads else None
    }

    return summary, results

ml_metrics = metrics(ml_alert)
trend_metrics = metrics(trend_alert)

ml_episode, ml_events = episode_metrics(ml_alert)
trend_episode, trend_events = episode_metrics(trend_alert)

# ---------------------------------------------------------
# Save per-sample predictions
# ---------------------------------------------------------
with (OUT / "predictions.csv").open("w", newline="") as f:
    writer = csv.writer(f)

    writer.writerow([
        "time_s",
        "queue_packets",
        "eligible",
        "future_crossing_5ms",
        "ml_probability",
        "ml_alert",
        "trend_alert"
    ])

    for i in range(len(q)):
        writer.writerow([
            f"{t[i]:.6f}",
            int(q[i]),
            int(eligible[i]),
            int(y[i]),
            "" if np.isnan(prob[i]) else f"{prob[i]:.9f}",
            int(ml_alert[i]),
            int(trend_alert[i])
        ])

with (OUT / "episode_results.csv").open("w", newline="") as f:
    writer = csv.writer(f)

    writer.writerow([
        "episode",
        "onset_s",
        "ml_detected",
        "ml_lead_ms",
        "trend_detected",
        "trend_lead_ms"
    ])

    for i, (m, tr) in enumerate(zip(ml_events, trend_events)):
        writer.writerow([
            i,
            f"{m['episode_onset_s']:.6f}",
            int(m["detected"]),
            "" if m["lead_ms"] is None else f"{m['lead_ms']:.3f}",
            int(tr["detected"]),
            "" if tr["lead_ms"] is None else f"{tr['lead_ms']:.3f}"
        ])

summary = {
    "model": "ml_reference.model",
    "horizon_ms": horizon,
    "threshold_packets": threshold,
    "ml_cutoff": cutoff,
    "trace": str(DATA),
    "sample_level": {
        "ml": ml_metrics,
        "trend": trend_metrics
    },
    "episode_level": {
        "ml": ml_episode,
        "trend": trend_episode
    },
    "limitations": [
        "Single baseline trace; not an independent multi-run evaluation",
        "Adjacent 1-ms prediction samples are correlated",
        "Episode grouping uses a 30-ms gap heuristic",
        "Warnings are evaluated against uncontrolled baseline congestion",
        "The predictor was trained on a different workload distribution"
    ]
}

(OUT / "summary.json").write_text(
    json.dumps(summary, indent=2)
)

# ---------------------------------------------------------
# Print interpretable results
# ---------------------------------------------------------
print("\n========== SAMPLE-LEVEL EVALUATION ==========")
print(f"Eligible samples: {eligible.sum()}")
print(f"Positive labels: {y[eligible].sum()}")

print(
    f"{'Predictor':10} {'TP':>5} {'FP':>5} "
    f"{'FN':>5} {'TN':>6} "
    f"{'Precision':>11} {'Recall':>9} {'F1':>9}"
)

for name, result in (
    ("ML", ml_metrics),
    ("Trend", trend_metrics)
):
    print(
        f"{name:10} "
        f"{result['TP']:5d} "
        f"{result['FP']:5d} "
        f"{result['FN']:5d} "
        f"{result['TN']:6d} "
        f"{result['precision']:11.3f} "
        f"{result['recall']:9.3f} "
        f"{result['f1']:9.3f}"
    )

print("\n========== EPISODE-LEVEL EVALUATION ==========")

for name, result in (
    ("ML", ml_episode),
    ("Trend", trend_episode)
):
    print(f"\n{name}:")
    print(f"  Episodes detected: {result['detected']}/{result['episodes']}")
    print(f"  Episodes missed: {result['missed']}")
    print(f"  Mean lead time: {result['mean_lead_ms']}")
    print(f"  Median lead time: {result['median_lead_ms']}")

print("\n========== SAVED OUTPUTS ==========")
for name in ("summary.json", "predictions.csv", "episode_results.csv"):
    print(OUT / name)

print("\nOffline validation completed.")
