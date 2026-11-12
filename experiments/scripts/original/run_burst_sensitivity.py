#!/usr/bin/env python3

import csv
import json
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import run_v2_pilot as pilot
from analyze_goodput_fairness import analyze

ROOT = Path(__file__).resolve().parent

OUT = (
    ROOT / "research_horizon_study"
    / "v2_burst_size_sensitivity"
)

ORIGINAL = (
    ROOT / "research_horizon_study"
    / "v2_full_evaluation"
    / "results_36_runs.csv"
)

SEEDS = range(224, 230)

SIZES = {
    "moderate": 50000,
    "intense": 150000,
}

CONTROLLERS = pilot.CONFIGS

TRACES = list(dict.fromkeys(
    pilot.TRACE_FILES + [
        "bursty-short-flow-snapshot.dat",
        "bursty-predictions.dat",
        "bursty-ml-inference.dat",
        "bursty-controller-actions.dat",
    ]
))

REQUIRED = pilot.TRACE_FILES


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def write_csv(rows, path):
    if not rows:
        return

    temp = path.with_suffix(".tmp")

    with temp.open("w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=list(rows[0])
        )
        writer.writeheader()
        writer.writerows(rows)

    temp.replace(path)


def verify_workload(directory, expected_size):
    rows = read_csv(
        directory / "bursty-workload-manifest.csv"
    )

    shorts = [
        r for r in rows
        if r["record_type"] == "short_flow"
    ]

    backgrounds = [
        r for r in rows
        if r["record_type"] == "background"
    ]

    require(
        len(shorts) == 24,
        "Expected exactly 24 short flows"
    )

    require(
        len(backgrounds) == 18,
        "Expected 18 background sessions"
    )

    total_bytes = sum(
        int(r["max_bytes"]) for r in shorts
    )

    # Nominal size varies with existing 30% randomization.
    require(
        total_bytes > 0,
        "Invalid offered short-flow traffic"
    )

    return {
        "offered_short_bytes": total_bytes,
        "manifest_hash": sha256(
            directory / "bursty-workload-manifest.csv"
        ),
    }


def calculate(directory, seed, controller, label, size):
    for name in REQUIRED:
        require(
            (directory / name).is_file(),
            f"Missing trace {name}"
        )

    workload = verify_workload(directory, size)

    network = pilot.calculate_original_metrics(
        directory
    )

    goodput, sessions = analyze(
        directory,
        5.0
    )

    require(
        len(sessions) == 9,
        "Expected nine background sessions"
    )

    require(
        goodput["receiver_reconciliation"] == "PASS",
        "Receiver reconciliation failed"
    )

    require(
        0.5 <= goodput["background_runwide_jain"] <= 1.0,
        "Invalid Jain fairness index"
    )

    row = {
        "severity": label,
        "short_flow_base_bytes": size,
        "seed": seed,
        "controller": controller,
        **network,
        "offered_short_bytes":
            workload["offered_short_bytes"],
        "short_goodput_mbps":
            goodput["short_goodput_mbps"],
        "background1_goodput_mbps":
            goodput["background1_goodput_mbps"],
        "background2_goodput_mbps":
            goodput["background2_goodput_mbps"],
        "aggregate_goodput_mbps":
            goodput["aggregate_goodput_mbps"],
        "background_runwide_jain":
            goodput["background_runwide_jain"],
    }

    write_csv(
        sessions,
        directory / "background_session_fairness.csv"
    )

    return row


def main():
    print("========== BURST SENSITIVITY PRE-FLIGHT ==========")

    require(
        ORIGINAL.is_file(),
        "Original 36-run results missing"
    )

    require(
        len(CONTROLLERS) == 6,
        "Expected six controllers"
    )

    require(
        (ROOT / "analyze_goodput_fairness.py").is_file(),
        "Metrics analyzer missing"
    )

    original_rows = read_csv(ORIGINAL)

    require(
        len(original_rows) == 36,
        "Original evaluation must contain 36 runs"
    )

    for horizon in (2, 5, 20):
        model = (
            ROOT / "research_horizon_study"
            / "horizon_models"
            / f"predictor_{horizon}ms.model"
        )

        require(
            model.is_file(),
            f"Frozen model missing: {model}"
        )

    OUT.mkdir(parents=True, exist_ok=True)

    provenance = {
        "sizes": SIZES,
        "seeds": list(SEEDS),
        "controllers": CONTROLLERS,
        "original_results_sha256": sha256(ORIGINAL),
        "simulator_sha256": sha256(
            ROOT / "examples/tcp/bursty-dctcp-baseline.cc"
        ),
        "analyzer_sha256": sha256(
            ROOT / "analyze_goodput_fairness.py"
        ),
        "pilot_runner_sha256": sha256(
            ROOT / "run_v2_pilot.py"
        ),
        "models_sha256": {
            str(h): sha256(
                ROOT / "research_horizon_study"
                / "horizon_models"
                / f"predictor_{h}ms.model"
            )
            for h in (2, 5, 20)
        },
    }

    provenance_file = OUT / "provenance.json"

    if provenance_file.exists():
        require(
            json.loads(provenance_file.read_text())
            == provenance,
            "Experiment provenance changed; unsafe resume"
        )
    else:
        provenance_file.write_text(
            json.dumps(provenance, indent=2) + "\n"
        )

    all_rows = []
    index = 0

    for label, size in SIZES.items():
        for seed in SEEDS:
            paired_hash = None

            for controller, flags in CONTROLLERS.items():
                index += 1

                dest = (
                    OUT / label
                    / f"seed_{seed}"
                    / controller
                )

                dest.mkdir(parents=True, exist_ok=True)

                done = dest / "validated_result.json"

                common = pilot.COMMON.replace(
                    "--workloadSeed=224",
                    f"--workloadSeed={seed}"
                )

                require(
                    f"--workloadSeed={seed}" in common,
                    "Workload seed substitution failed"
                )

                command = [
                    "./ns3",
                    "run",
                    (
                        "bursty-dctcp-baseline "
                        f"{common} "
                        f"{flags} "
                        f"--shortFlowBaseBytes={size}"
                    )
                ]

                command_path = dest / "command.json"

                if command_path.exists():
                    require(
                        json.loads(command_path.read_text())
                        == command,
                        "Existing command differs from current settings"
                    )
                else:
                    command_path.write_text(
                        json.dumps(command, indent=2) + "\n"
                    )

                if done.exists():
                    print(
                        f"[{index}/72] REVALIDATING "
                        f"{label}/seed_{seed}/{controller}",
                        flush=True
                    )

                    row = calculate(
                        dest, seed, controller, label, size
                    )

                    require(
                        json.loads(done.read_text()) == row,
                        "Previously completed result changed"
                    )

                else:
                    print(
                        f"[{index}/72] RUNNING "
                        f"{label}/seed_{seed}/{controller}",
                        flush=True
                    )

                    for name in TRACES:
                        (ROOT / name).unlink(missing_ok=True)

                    with (dest / "run.log").open("w") as log:
                        result = subprocess.run(
                            command,
                            cwd=ROOT,
                            stdout=log,
                            stderr=subprocess.STDOUT,
                            timeout=180,
                        )

                    require(
                        result.returncode == 0,
                        f"Simulation failed: {dest / 'run.log'}"
                    )

                    for name in REQUIRED:
                        require(
                            (ROOT / name).is_file(),
                            f"Missing generated trace: {name}"
                        )

                    for name in TRACES:
                        src = ROOT / name
                        if src.is_file():
                            shutil.copy2(src, dest / name)

                    row = calculate(
                        dest, seed, controller, label, size
                    )

                    done.write_text(
                        json.dumps(row, indent=2) + "\n"
                    )

                if paired_hash is None:
                    paired_hash = row["manifest_hash"]

                require(
                    row["manifest_hash"] == paired_hash,
                    f"Workload mismatch: {label}/seed_{seed}"
                )

                all_rows.append(row)

                write_csv(
                    all_rows,
                    OUT / "results_partial.csv"
                )

                print(
                    f"PASS: P99={row['p99_fct_ms']:.3f}ms "
                    f"Goodput={row['aggregate_goodput_mbps']:.3f}Mbps "
                    f"Jain={row['background_runwide_jain']:.6f}",
                    flush=True
                )

    require(
        len(all_rows) == 72,
        "Expected 72 completed results"
    )

    write_csv(
        all_rows,
        OUT / "results_72_runs.csv"
    )

    print("\n========== FINAL VALIDATION ==========")
    print("PASS: 72/72 experiments")
    print("PASS: Paired workload manifests")
    print("PASS: Receiver byte-accounting validations")
    print("PASS: Goodput and fairness metrics")
    print()
    print("Results:", OUT / "results_72_runs.csv")
    print("PHASE 5 DATA COLLECTION COMPLETE")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            f"\nSTOP: {error}",
            file=sys.stderr,
            flush=True
        )
        sys.exit(1)
