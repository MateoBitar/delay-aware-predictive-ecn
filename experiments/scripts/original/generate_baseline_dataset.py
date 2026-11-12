from pathlib import Path
import subprocess
import shutil
import csv
import hashlib
import json
import numpy as np

root = Path.cwd()
output = root / "research_horizon_study" / "baseline_dataset"
output.mkdir(parents=True, exist_ok=True)

required = [
    "bursty-queue.dat",
    "bursty-ecn.dat",
    "bursty-short-fct.dat",
    "bursty-workload-manifest.csv"
]

records = []

for seed in range(200, 230):

    if seed <= 217:
        split = "train"
    elif seed <= 223:
        split = "validation"
    else:
        split = "test"

    destination = output / split / f"workload_{seed}"

    if destination.exists():
        print(f"STOP: {destination} already exists.")
        raise SystemExit(
            "Refusing to overwrite an existing experiment."
        )

    destination.mkdir(parents=True)

    flags = (
        "--controllerMode=baseline "
        "--minTh=20 --maxTh=60 "
        "--workloadMode=intermittent "
        "--burstSchedule=aligned "
        "--workloadVariation=controlled "
        f"--workloadSeed={seed} "
        "--backgroundJitterMs=10 "
        "--shortFlowJitterMs=5 "
        "--shortFlowSizeVariation=0.30 "
        "--delAckTimeoutMs=20 "
        "--RngSeed=1 "
        "--RngRun=101"
    )

    print(f"Running {split} workload {seed}...", flush=True)

    result = subprocess.run(
        ["./ns3", "run", f"bursty-dctcp-baseline {flags}"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    (destination / "run.log").write_text(result.stdout)

    if result.returncode != 0:
        raise SystemExit(
            f"Simulation failed for seed {seed}. "
            f"Inspect {destination / 'run.log'}"
        )

    for name in required:
        source = root / name
        if not source.exists():
            raise SystemExit(f"Missing output: {name}")
        shutil.copy2(source, destination / name)

    queue = np.atleast_2d(
        np.loadtxt(destination / "bursty-queue.dat", comments="#")
    )

    fct = np.atleast_2d(
        np.loadtxt(destination / "bursty-short-fct.dat", comments="#")
    )

    with (destination / "bursty-workload-manifest.csv").open() as f:
        manifest = list(csv.DictReader(f))

    targets = {
        int(r["id"]): int(r["max_bytes"])
        for r in manifest
        if r["record_type"] == "short_flow"
    }

    completed = {
        int(r[0]): int(r[4])
        for r in fct
    }

    if len(manifest) != 42 or len(fct) != 24 or targets != completed:
        raise SystemExit(
            f"Workload or FCT validation failed: seed {seed}"
        )

    times = queue[:, 0]
    values = queue[:, 1]

    crossings = np.flatnonzero(
        (values[:-1] < 20) &
        (values[1:] >= 20)
    ) + 1

    eligible = (np.arange(len(values)) >= 5) & (values < 20)

    positive = np.zeros(len(values), dtype=bool)

    for i in np.flatnonzero(eligible):
        future = crossings[
            (times[crossings] > times[i]) &
            (times[crossings] <= times[i] + 0.005 + 1e-9)
        ]
        positive[i] = len(future) > 0

    record = {
        "seed": seed,
        "split": split,
        "queue_samples": len(values),
        "eligible_samples": int(eligible.sum()),
        "positive_samples_5ms": int(positive.sum()),
        "raw_crossings": len(crossings),
        "completed_flows": len(fct),
        "mean_queue": round(float(values.mean()), 4),
        "peak_queue": int(values.max()),
        "mean_fct_ms": round(float(fct[:, 3].mean()), 4),
        "queue_sha256": hashlib.sha256(
            (destination / "bursty-queue.dat").read_bytes()
        ).hexdigest(),
        "manifest_sha256": hashlib.sha256(
            (destination / "bursty-workload-manifest.csv").read_bytes()
        ).hexdigest()
    }

    records.append(record)

    (destination / "metadata.json").write_text(
        json.dumps(record, indent=2)
    )

    print(
        f"  crossings={record['raw_crossings']} "
        f"positives={record['positive_samples_5ms']} "
        f"peakQ={record['peak_queue']} "
        f"FCT={record['mean_fct_ms']:.2f}ms",
        flush=True
    )

summary = output / "dataset_summary.csv"

with summary.open("w", newline="") as f:
    writer = csv.DictWriter(
        f, fieldnames=list(records[0].keys())
    )
    writer.writeheader()
    writer.writerows(records)

print("\n========== DATASET COMPLETE ==========")
print("Scenarios:", len(records))
print("Unique workloads:", len(set(r["manifest_sha256"] for r in records)))
print("Unique queue traces:", len(set(r["queue_sha256"] for r in records)))
print("Train / validation / test: 18 / 6 / 6")
print("Summary:", summary)
