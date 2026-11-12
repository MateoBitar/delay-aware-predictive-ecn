from pathlib import Path
import subprocess
import shutil
import csv
import json
import hashlib
import numpy as np

ROOT = Path.cwd()
OUT = ROOT / "research_horizon_study" / "closed_loop_validation"
PILOT = ROOT / "research_horizon_study" / "closed_loop_pilot_218"

OUT.mkdir(parents=True, exist_ok=True)

CONFIGS = {
    "baseline": "--controllerMode=baseline --minTh=20 --maxTh=60",
    "lower_fixed": "--controllerMode=baseline --minTh=10 --maxTh=30",
    "trend": (
        "--controllerMode=trend-prediction-release "
        "--minTh=20 --maxTh=60 --earlyMinTh=10 --earlyMaxTh=30 "
        "--predictorHorizonMs=5 --minActiveMs=10 "
        "--negativeReleaseSamples=5"
    )
}

for h in (2, 5, 20):
    CONFIGS[f"ml_{h}ms"] = (
        "--controllerMode=ml-prediction-release "
        f"--mlModelPath=research_horizon_study/horizon_models/predictor_{h}ms.model "
        f"--predictorHorizonMs={h} "
        "--minTh=20 --maxTh=60 --earlyMinTh=10 --earlyMaxTh=30 "
        "--minActiveMs=10 --negativeReleaseSamples=5"
    )

def validate(directory):
    manifest = directory / "bursty-workload-manifest.csv"
    queue_file = directory / "bursty-queue.dat"
    fct_file = directory / "bursty-short-fct.dat"

    with manifest.open(newline="") as f:
        records = list(csv.DictReader(f))

    assert len(records) == 42

    targets = {
        int(r["id"]): int(r["max_bytes"])
        for r in records if r["record_type"] == "short_flow"
    }
    assert len(targets) == 24

    fct = np.atleast_2d(np.loadtxt(fct_file, comments="#"))
    queue = np.atleast_2d(np.loadtxt(queue_file, comments="#"))

    completed = {int(r[0]): int(r[4]) for r in fct}
    assert len(fct) == 24 and completed == targets
    assert len(queue) == 5000

    return {
        "mean_fct_ms": float(np.mean(fct[:, 3])),
        "p95_fct_ms": float(np.percentile(fct[:, 3], 95)),
        "p99_fct_ms": float(np.percentile(fct[:, 3], 99)),
        "mean_queue_packets": float(np.mean(queue[:, 1])),
        "peak_queue_packets": float(np.max(queue[:, 1])),
        "completed_flows": len(fct),
        "manifest_hash": hashlib.sha256(manifest.read_bytes()).hexdigest()
    }

rows = []

for seed in range(218, 224):
    expected_manifest = None

    for mode, flags in CONFIGS.items():
        dest = OUT / f"seed_{seed}" / mode
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Reuse the previously validated seed-218 ML pilots.
        pilot = PILOT / mode if seed == 218 else None

        if not dest.exists() and pilot is not None and pilot.exists():
            shutil.copytree(pilot, dest)
            print(f"REUSED: seed {seed} {mode}", flush=True)

        if not dest.exists():
            dest.mkdir()

            common = (
                "--workloadMode=intermittent "
                "--burstSchedule=aligned "
                "--workloadVariation=controlled "
                f"--workloadSeed={seed} "
                "--backgroundJitterMs=10 "
                "--shortFlowJitterMs=5 "
                "--shortFlowSizeVariation=0.30 "
                "--delAckTimeoutMs=20 "
                "--RngSeed=1 --RngRun=101"
            )

            command = [
                "./ns3", "run",
                f"bursty-dctcp-baseline {common} {flags}"
            ]

            (dest / "command.json").write_text(
                json.dumps(command, indent=2)
            )

            print(f"RUNNING: seed {seed} {mode}", flush=True)

            with (dest / "run.log").open("w") as log:
                result = subprocess.run(
                    command,
                    cwd=ROOT,
                    stdout=log,
                    stderr=subprocess.STDOUT
                )

            if result.returncode:
                raise SystemExit(
                    f"Simulation failed: seed {seed} {mode}. "
                    f"Inspect {dest / 'run.log'}"
                )

            for file in ROOT.glob("bursty-*.dat"):
                shutil.copy2(file, dest / file.name)

            shutil.copy2(
                ROOT / "bursty-workload-manifest.csv",
                dest / "bursty-workload-manifest.csv"
            )

        metrics = validate(dest)

        if expected_manifest is None:
            expected_manifest = metrics["manifest_hash"]
        else:
            assert metrics["manifest_hash"] == expected_manifest, (
                f"Workload mismatch: seed {seed}, {mode}"
            )

        rows.append({
            "seed": seed,
            "controller": mode,
            **metrics
        })

        # Preserve progress after each successfully validated run.
        summary = OUT / "validation_results.csv"
        temporary = OUT / "validation_results.csv.tmp"

        with temporary.open("w", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=list(rows[0])
            )
            writer.writeheader()
            writer.writerows(rows)

        temporary.replace(summary)

        print(
            f"PASS: {seed} {mode} | "
            f"FCT={metrics['mean_fct_ms']:.3f} ms | "
            f"PeakQ={metrics['peak_queue_packets']:.0f}",
            flush=True
        )

print("\nVALIDATION COMPLETE")
print(f"Validated controller-scenario pairs: {len(rows)}/36")
print("Results:", OUT / "validation_results.csv")
