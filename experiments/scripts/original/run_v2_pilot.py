#!/usr/bin/env python3

from pathlib import Path
import subprocess
import shutil
import hashlib
import json
import csv
import sys

import numpy as np

from analyze_goodput_fairness import analyze

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "research_horizon_study" / "v2_six_controller_pilot"
ORIGINAL = ROOT / "research_horizon_study" / "closed_loop_test" / "test_results.csv"

SEED = 224

# Exact settings from the archived reproduce_closed_loop.py.
CONFIGS = {
    "baseline":
        "--controllerMode=baseline --minTh=20 --maxTh=60",

    "lower_fixed":
        "--controllerMode=baseline --minTh=10 --maxTh=30",

    "trend":
        "--controllerMode=trend-prediction-release "
        "--minTh=20 --maxTh=60 "
        "--earlyMinTh=10 --earlyMaxTh=30 "
        "--predictorHorizonMs=5 "
        "--minActiveMs=10 "
        "--negativeReleaseSamples=5",
}

for horizon in (2, 5, 20):
    CONFIGS[f"ml_{horizon}ms"] = (
        "--controllerMode=ml-prediction-release "
        "--mlModelPath="
        f"research_horizon_study/horizon_models/predictor_{horizon}ms.model "
        f"--predictorHorizonMs={horizon} "
        "--minTh=20 --maxTh=60 "
        "--earlyMinTh=10 --earlyMaxTh=30 "
        "--minActiveMs=10 "
        "--negativeReleaseSamples=5"
    )

COMMON = (
    "--workloadMode=intermittent "
    "--burstSchedule=aligned "
    "--workloadVariation=controlled "
    f"--workloadSeed={SEED} "
    "--backgroundJitterMs=10 "
    "--shortFlowJitterMs=5 "
    "--shortFlowSizeVariation=0.30 "
    "--delAckTimeoutMs=20 "
    "--RngSeed=1 --RngRun=101"
)

TRACE_FILES = [
    "bursty-background-rx.csv",
    "bursty-receiver.dat",
    "bursty-short-flow-rx.dat",
    "bursty-short-fct.dat",
    "bursty-workload-manifest.csv",
    "bursty-queue.dat",
    "bursty-ecn.dat",
    "bursty-cc-response.dat",
]

REPRO_METRICS = [
    "mean_fct_ms",
    "p95_fct_ms",
    "p99_fct_ms",
    "mean_queue_packets",
    "peak_queue_packets",
]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def load_original():
    require(ORIGINAL.is_file(), f"Missing original results: {ORIGINAL}")

    with ORIGINAL.open(newline="") as f:
        rows = list(csv.DictReader(f))

    matches = {
        r["controller"]: r
        for r in rows if int(r["seed"]) == SEED
    }

    require(
        set(matches) == set(CONFIGS),
        "Original seed-224 controller configurations do not match"
    )

    return matches


def calculate_original_metrics(dest):
    with (dest / "bursty-workload-manifest.csv").open(newline="") as f:
        manifest = list(csv.DictReader(f))

    require(len(manifest) == 42, "Expected 42 manifest records")

    targets = {
        int(r["id"]): int(r["max_bytes"])
        for r in manifest if r["record_type"] == "short_flow"
    }

    require(len(targets) == 24, "Expected 24 short-flow entries")

    fct = np.atleast_2d(
        np.loadtxt(dest / "bursty-short-fct.dat", comments="#")
    )

    queue = np.atleast_2d(
        np.loadtxt(dest / "bursty-queue.dat", comments="#")
    )

    completed = {int(r[0]): int(r[4]) for r in fct}

    require(
        len(fct) == 24 and completed == targets,
        "Flow completion validation failed"
    )

    require(len(queue) == 5000, "Expected 5000 queue samples")

    return {
        "mean_fct_ms": float(np.mean(fct[:, 3])),
        "p95_fct_ms": float(np.percentile(fct[:, 3], 95)),
        "p99_fct_ms": float(np.percentile(fct[:, 3], 99)),
        "mean_queue_packets": float(np.mean(queue[:, 1])),
        "peak_queue_packets": float(np.max(queue[:, 1])),
        "completed_flows": len(fct),
        "manifest_hash": hashlib.sha256(
            (dest / "bursty-workload-manifest.csv").read_bytes()
        ).hexdigest(),
    }


def write_csv(rows, path):
    temporary = path.with_suffix(".tmp")

    with temporary.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    temporary.replace(path)


def main():
    print("========== PRE-FLIGHT ==========", flush=True)

    require((ROOT / "ns3").is_file(), "ns3 launcher missing")
    require(
        (ROOT / "analyze_goodput_fairness.py").is_file(),
        "Validated goodput/fairness analyzer missing"
    )

    for horizon in (2, 5, 20):
        model = (
            ROOT / "research_horizon_study" /
            "horizon_models" / f"predictor_{horizon}ms.model"
        )
        require(model.is_file(), f"Missing model: {model}")

    expected = load_original()

    # Never overwrite a previous pilot.
    require(
        not OUT.exists(),
        f"Pilot directory already exists: {OUT}"
    )

    OUT.mkdir(parents=True)

    rows = []
    reference_hash = None

    print("PASS: Original results and models found")
    print("PASS: Separate pilot output directory created")

    for index, (controller, flags) in enumerate(CONFIGS.items(), 1):
        print(
            f"\n========== RUN {index}/6: {controller} ==========",
            flush=True
        )

        dest = OUT / controller
        dest.mkdir()

        command = [
            "./ns3",
            "run",
            f"bursty-dctcp-baseline {COMMON} {flags}"
        ]

        (dest / "command.json").write_text(
            json.dumps(command, indent=2) + "\n"
        )

        # Remove previous run's generated traces from the extension
        # root only, preventing stale output from passing validation.
        for filename in TRACE_FILES:
            (ROOT / filename).unlink(missing_ok=True)

        with (dest / "run.log").open("w") as log:
            result = subprocess.run(
                command,
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=120
            )

        require(
            result.returncode == 0,
            f"{controller} simulation failed. See {dest / 'run.log'}"
        )

        for filename in TRACE_FILES:
            source = ROOT / filename
            require(source.is_file(), f"Missing output: {filename}")
            shutil.copy2(source, dest / filename)

        # Check original experiment metrics and manifest hash.
        metrics = calculate_original_metrics(dest)
        reference = expected[controller]

        require(
            metrics["manifest_hash"] == reference["manifest_hash"],
            f"{controller}: original workload hash mismatch"
        )

        for metric in REPRO_METRICS:
            difference = abs(
                metrics[metric] - float(reference[metric])
            )
            require(
                difference <= 1e-9,
                f"{controller}: {metric} differs from original "
                f"by {difference}"
            )

        if reference_hash is None:
            reference_hash = metrics["manifest_hash"]

        require(
            metrics["manifest_hash"] == reference_hash,
            f"{controller}: paired workload mismatch"
        )

        # Use the existing, validated receiver-accounting analyzer.
        goodput, sessions = analyze(dest, 5.0)

        require(
            goodput["receiver_reconciliation"] == "PASS",
            "Receiver accounting validation failed"
        )

        require(
            0.5 <= goodput["background_runwide_jain"] <= 1.0,
            "Invalid Jain fairness value"
        )

        require(
            len(sessions) == 9,
            "Expected nine background sessions"
        )

        row = {
            "seed": SEED,
            "controller": controller,
            **metrics,
            **{
                k: goodput[k]
                for k in (
                    "short_goodput_mbps",
                    "background1_goodput_mbps",
                    "background2_goodput_mbps",
                    "aggregate_goodput_mbps",
                    "background_runwide_jain",
                )
            }
        }

        rows.append(row)

        write_csv(rows, OUT / "pilot_results.csv")

        with (dest / "background_session_fairness.csv").open(
            "w", newline=""
        ) as f:
            writer = csv.DictWriter(
                f, fieldnames=list(sessions[0])
            )
            writer.writeheader()
            writer.writerows(sessions)

        print(
            f"PASS: original FCT/queue results reproduced\n"
            f"PASS: workload hash matched\n"
            f"PASS: receiver byte reconciliation\n"
            f"Mean FCT: {metrics['mean_fct_ms']:.3f} ms\n"
            f"P99 FCT: {metrics['p99_fct_ms']:.3f} ms\n"
            f"Goodput: {goodput['aggregate_goodput_mbps']:.3f} Mbps\n"
            f"Fairness: {goodput['background_runwide_jain']:.6f}",
            flush=True
        )

    print("\n========== FINAL VALIDATION ==========")

    require(len(rows) == 6, "Incomplete six-controller pilot")
    require(
        len({r["manifest_hash"] for r in rows}) == 1,
        "Controller workloads differ"
    )

    print("PASS: 6/6 controllers")
    print("PASS: 6/6 original metric regressions")
    print("PASS: 6/6 workload manifest comparisons")
    print("PASS: 6/6 receiver-accounting validations")
    print("PASS: Goodput and background fairness calculated")

    print("\nRESULTS:")
    print(OUT / "pilot_results.csv")
    print("\nPHASE 3 PILOT COMPLETE")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nSTOP: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
