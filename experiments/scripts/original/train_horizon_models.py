from pathlib import Path
import csv
import json
import numpy as np
from sklearn.linear_model import LogisticRegression

ROOT = Path("research_horizon_study")
DATA = ROOT / "baseline_dataset"
OUT = ROOT / "horizon_models"
OUT.mkdir(parents=True, exist_ok=True)

HORIZONS = (1, 2, 5, 10, 20)
THRESHOLD = 20.0
EPISODE_GAP_S = 0.030
CUTOFFS = np.arange(0.10, 0.901, 0.05)

SPLITS = {
    "train": range(200, 218),
    "validation": range(218, 224),
    "test": range(224, 230),
}

def load_queue(split, seed):
    path = (
        DATA / split / f"workload_{seed}" /
        "bursty-queue.dat"
    )
    q = np.atleast_2d(np.loadtxt(path, comments="#"))
    assert q.shape[1] >= 2
    assert np.all(np.diff(q[:, 0]) > 0)
    return q[:, 0], q[:, 1]

def features_and_labels(t, q, horizon_ms):
    X, y, indices = [], [], []
    horizon_s = horizon_ms / 1000.0

    # Match C++ feature order exactly.
    for i in range(5, len(q)):
        if q[i] >= THRESHOLD:
            continue

        window = q[i-5:i+1]

        features = [
            q[i],
            q[i] - q[i-1],
            (q[i] - q[i-3]) / 3.0,
            (q[i] - q[i-5]) / 5.0,
            float(np.mean(window)),
            float(np.max(window) - np.min(window))
        ]

        # Future observations only. Exclude samples without
        # a complete forecast window at the end of the run.
        if t[-1] < t[i] + horizon_s - 1e-9:
            continue

        future = (
            (t > t[i]) &
            (t <= t[i] + horizon_s + 1e-9)
        )

        label = int(
            np.any(q[future] >= THRESHOLD)
        )

        X.append(features)
        y.append(label)
        indices.append(i)

    return (
        np.asarray(X, dtype=float).reshape(-1, 6),
        np.asarray(y, dtype=int),
        np.asarray(indices, dtype=int)
    )

def build_split(split, horizon):
    datasets = []
    for seed in SPLITS[split]:
        t, q = load_queue(split, seed)
        X, y, indices = features_and_labels(t, q, horizon)
        datasets.append({
            "seed": seed, "time": t, "queue": q,
            "X": X, "y": y, "indices": indices
        })
    return datasets

def pooled(datasets):
    return (
        np.concatenate([d["X"] for d in datasets]),
        np.concatenate([d["y"] for d in datasets])
    )

def probabilities(model, X, mean, scale):
    return model.predict_proba((X - mean) / scale)[:, 1]

def evaluate(y, p, cutoff):
    pred = p >= cutoff
    positive = y == 1

    tp = int(np.sum(pred & positive))
    fp = int(np.sum(pred & ~positive))
    fn = int(np.sum(~pred & positive))
    tn = int(np.sum(~pred & ~positive))

    return {
        "TP": tp, "FP": fp, "FN": fn, "TN": tn,
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / (tp + fn) if tp + fn else 0.0,
        "f1": 2 * tp / (2 * tp + fp + fn)
              if 2 * tp + fp + fn else 0.0,
        "false_positive_rate":
            fp / (fp + tn) if fp + tn else 0.0
    }

def event_evaluation(datasets, model, mean, scale,
                     cutoff, horizon):
    detected = 0
    total = 0
    leads = []
    per_run = []

    for d in datasets:
        t, q = d["time"], d["queue"]

        crossings = np.flatnonzero(
            (q[:-1] < THRESHOLD) &
            (q[1:] >= THRESHOLD)
        ) + 1

        # Group crossings separated by <=30 ms.
        episodes = []
        previous = None

        for index in crossings:
            onset = float(t[index])
            if previous is None or onset - previous > EPISODE_GAP_S:
                episodes.append(onset)
            previous = onset

        probs = probabilities(
            model, d["X"], mean, scale
        )

        alerts = d["indices"][probs >= cutoff]
        alert_times = t[alerts]

        run_detected = 0
        run_leads = []

        for onset in episodes:
            candidates = alert_times[
                (alert_times < onset) &
                (alert_times >=
                 onset - horizon / 1000.0 - 1e-9)
            ]

            total += 1

            if len(candidates):
                # Earliest warning in the forecast window.
                lead = float((onset - candidates.min()) * 1000)
                detected += 1
                run_detected += 1
                leads.append(lead)
                run_leads.append(lead)

        per_run.append({
            "seed": d["seed"],
            "episodes": len(episodes),
            "detected": run_detected,
            "event_recall":
                run_detected / len(episodes)
                if episodes else None,
            "mean_lead_ms":
                float(np.mean(run_leads))
                if run_leads else None
        })

    return {
        "episodes": total,
        "detected": detected,
        "event_recall": detected / total if total else None,
        "mean_lead_ms":
            float(np.mean(leads)) if leads else None,
        "median_lead_ms":
            float(np.median(leads)) if leads else None,
        "per_run": per_run
    }

results = []

for horizon in HORIZONS:
    print(f"\n========== HORIZON {horizon} ms ==========",
          flush=True)

    train = build_split("train", horizon)
    val = build_split("validation", horizon)
    test = build_split("test", horizon)

    Xtrain, ytrain = pooled(train)
    Xval, yval = pooled(val)
    Xtest, ytest = pooled(test)

    print(
        "Positive labels — "
        f"Train: {ytrain.sum()}, "
        f"Validation: {yval.sum()}, "
        f"Test: {ytest.sum()}"
    )

    assert len(np.unique(ytrain)) == 2, (
        f"Training horizon {horizon} has only one class"
    )

    mean = Xtrain.mean(axis=0)
    scale = Xtrain.std(axis=0)
    scale[scale == 0] = 1.0

    model = LogisticRegression(
        max_iter=2000,
        class_weight="balanced",
        random_state=42
    )
    model.fit((Xtrain - mean) / scale, ytrain)

    pval = probabilities(model, Xval, mean, scale)

    # Cutoff selection uses validation data ONLY.
    # Tie-breaking prefers the higher cutoff.
    cutoff = max(
        CUTOFFS,
        key=lambda c: (evaluate(yval, pval, c)["f1"], c)
    )
    cutoff = float(round(cutoff, 6))

    validation = evaluate(yval, pval, cutoff)

    # Single final evaluation on the held-out test set.
    ptest = probabilities(model, Xtest, mean, scale)
    testing = evaluate(ytest, ptest, cutoff)

    events = event_evaluation(
        test, model, mean, scale, cutoff, horizon
    )

    model_path = OUT / f"predictor_{horizon}ms.model"

    with model_path.open("w") as f:
        f.write("NS3_LOGISTIC_V1\n")
        f.write(
            f"{horizon} {THRESHOLD:.12g} "
            f"{cutoff:.17g} "
            f"{model.intercept_[0]:.17g}\n"
        )
        f.write(" ".join(f"{x:.17g}" for x in mean) + "\n")
        f.write(" ".join(f"{x:.17g}" for x in scale) + "\n")
        f.write(
            " ".join(f"{x:.17g}" for x in model.coef_[0])
            + "\n"
        )

    result = {
        "horizon_ms": horizon,
        "cutoff": cutoff,
        "train_samples": len(ytrain),
        "train_positives": int(ytrain.sum()),
        "validation_samples": len(yval),
        "validation_positives": int(yval.sum()),
        "test_samples": len(ytest),
        "test_positives": int(ytest.sum()),
        "validation": validation,
        "test": testing,
        "events": events,
        "model_path": str(model_path)
    }

    (OUT / f"results_{horizon}ms.json").write_text(
        json.dumps(result, indent=2)
    )
    results.append(result)

    print(
        f"Cutoff={cutoff:.2f} | "
        f"Test precision={testing['precision']:.3f} | "
        f"Recall={testing['recall']:.3f} | "
        f"F1={testing['f1']:.3f}"
    )
    print(
        f"Episodes detected={events['detected']}/"
        f"{events['episodes']} | "
        f"Mean lead={events['mean_lead_ms']} ms"
    )

with (OUT / "horizon_comparison.csv").open(
    "w", newline=""
) as f:
    writer = csv.writer(f)
    writer.writerow([
        "horizon_ms", "cutoff", "test_precision",
        "test_recall", "test_f1", "test_fpr",
        "episodes", "detected", "event_recall",
        "mean_lead_ms", "median_lead_ms"
    ])

    for r in results:
        m = r["test"]
        e = r["events"]
        writer.writerow([
            r["horizon_ms"], r["cutoff"],
            m["precision"], m["recall"], m["f1"],
            m["false_positive_rate"],
            e["episodes"], e["detected"],
            e["event_recall"], e["mean_lead_ms"],
            e["median_lead_ms"]
        ])

print("\nALL FIVE HORIZON MODELS TRAINED.")
print("Output:", OUT / "horizon_comparison.csv")
