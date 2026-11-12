#!/usr/bin/env python3

import csv
import json
import hashlib
import shutil
import subprocess
import statistics
import sys
from pathlib import Path

from analyze_goodput_fairness import analyze
import run_v2_pilot as pilot

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "research_horizon_study" / "v2_full_evaluation"
REFERENCE = pilot.ORIGINAL

SEEDS = range(224, 230)
CONTROLLERS = pilot.CONFIGS
TRACE_FILES = pilot.TRACE_FILES
METRICS = pilot.REPRO_METRICS

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

    temporary = path.with_suffix(".tmp")

    with temporary.open("w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=list(rows[0])
        )
        writer.writeheader()
        writer.writerows(rows)

    temporary.replace(path)

def check_original(metrics, reference, label):
    require(
        metrics["manifest_hash"] == reference["manifest_hash"],
        f"{label}: original workload hash mismatch"
    )

    for key in METRICS:
        measured = float(metrics[key])
        expected = float(reference[key])

        require(
            abs(measured - expected) <= 1e-9,
            f"{label}: regression mismatch in {key}: "
            f"{measured} versus {expected}"
        )

def collect(dest, seed, controller, reference):
    for name in TRACE_FILES:
        require(
            (dest / name).is_file(),
            f"Missing trace: {dest / name}"
        )

    metrics = pilot.calculate_original_metrics(dest)
    check_original(
        metrics, reference, f"seed {seed}/{controller}"
    )

    goodput, sessions = analyze(dest, 5.0)

    require(
        goodput["receiver_reconciliation"] == "PASS",
        "Receiver reconciliation failed"
    )

    require(
        len(sessions) == 9,
        "Background session count mismatch"
    )

    require(
        0.5 <= goodput["background_runwide_jain"] <= 1.0,
        "Invalid background Jain index"
    )

    row = {
        "seed": seed,
        "controller": controller,
        **metrics,
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
        dest / "background_session_fairness.csv"
    )

    return row

def main():
    print("========== PRE-FLIGHT ==========", flush=True)

    require(
        (ROOT / "ns3").is_file(),
        "ns3 launcher not found"
    )

    require(
        REFERENCE.is_file(),
        "Original test_results.csv not found"
    )

    require(
        len(CONTROLLERS) == 6,
        "Expected six controllers"
    )

    reference_rows = read_csv(REFERENCE)

    reference = {
        (int(row["seed"]), row["controller"]): row
        for row in reference_rows
    }

    for seed in SEEDS:
        for controller in CONTROLLERS:
            require(
                (seed, controller) in reference,
                f"Missing original result: {seed}/{controller}"
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

    print("PASS: Original results located")
    print("PASS: Six controller configurations located")
    print("PASS: Frozen models located")
    print("PASS: Resumable output directory available")

    # Preserve command and source provenance.
    provenance = {
        "seeds": list(SEEDS),
        "controllers": CONTROLLERS,
        "common_flags_template": pilot.COMMON,
        "reference_sha256": sha256(REFERENCE),
        "simulator_source_sha256": sha256(
            ROOT / "examples/tcp/bursty-dctcp-baseline.cc"
        ),
        "analysis_source_sha256": sha256(
            ROOT / "analyze_goodput_fairness.py"
        ),
        "pilot_runner_sha256": sha256(
            ROOT / "run_v2_pilot.py"
        ),
    }

    provenance_file = OUT / "provenance.json"

    if provenance_file.exists():
        saved = json.loads(provenance_file.read_text())

        require(
            saved == provenance,
            "Experiment configuration changed since "
            "the previous run. Refusing unsafe resume."
        )
    else:
        provenance_file.write_text(
            json.dumps(provenance, indent=2) + "\n"
        )

    all_rows = []
    completed = 0
    total = len(SEEDS) * len(CONTROLLERS)

    for seed in SEEDS:
        expected_hash = None

        for controller, flags in CONTROLLERS.items():
            completed += 1
            label = f"seed_{seed}/{controller}"

            dest = OUT / f"seed_{seed}" / controller
            dest.mkdir(parents=True, exist_ok=True)

            done = dest / "validated_result.json"

            if done.exists():
                print(
                    f"[{completed}/{total}] "
                    f"REVALIDATING {label}",
                    flush=True
                )

                row = collect(
                    dest,
                    seed,
                    controller,
                    reference[(seed, controller)]
                )

                saved_row = json.loads(done.read_text())

                require(
                    row == saved_row,
                    f"{label}: completed result changed"
                )

            else:
                common = pilot.COMMON.replace(
                    "--workloadSeed=224",
                    f"--workloadSeed={seed}"
                )

                require(
                    f"--workloadSeed={seed}" in common,
                    "Failed to substitute workload seed"
                )

                command = [
                    "./ns3",
                    "run",
                    f"bursty-dctcp-baseline {common} {flags}"
                ]

                command_file = dest / "command.json"

                if command_file.exists():
                    previous_command = json.loads(
                        command_file.read_text()
                    )

                    require(
                        previous_command == command,
                        f"{label}: saved command differs"
                    )

                command_file.write_text(
                    json.dumps(command, indent=2) + "\n"
                )

                print(
                    f"[{completed}/{total}] RUNNING {label}",
                    flush=True
                )

                # ns3 writes traces in the project root.
                # Remove only known generated trace files,
                # never source files or reference datasets.
                for name in TRACE_FILES:
                    (ROOT / name).unlink(missing_ok=True)

                with (dest / "run.log").open("w") as log:
                    try:
                        result = subprocess.run(
                            command,
                            cwd=ROOT,
                            stdout=log,
                            stderr=subprocess.STDOUT,
                            timeout=180
                        )
                    except subprocess.TimeoutExpired:
                        raise RuntimeError(
                            f"{label}: simulation timeout; "
                            f"inspect {dest / 'run.log'}"
                        )

                require(
                    result.returncode == 0,
                    f"{label}: simulator failed; "
                    f"inspect {dest / 'run.log'}"
                )

                for name in TRACE_FILES:
                    source = ROOT / name

                    require(
                        source.is_file(),
                        f"{label}: missing {name}"
                    )

                    shutil.copy2(source, dest / name)

                row = collect(
                    dest,
                    seed,
                    controller,
                    reference[(seed, controller)]
                )

                # Mark complete only AFTER validation.
                done.write_text(
                    json.dumps(row, indent=2) + "\n"
                )

            if expected_hash is None:
                expected_hash = row["manifest_hash"]

            require(
                row["manifest_hash"] == expected_hash,
                f"Paired workload mismatch for seed {seed}"
            )

            all_rows.append(row)

            write_csv(
                all_rows,
                OUT / "results_partial.csv"
            )

            print(
                f"PASS {label}: "
                f"P99={row['p99_fct_ms']:.3f}ms, "
                f"goodput={row['aggregate_goodput_mbps']:.3f}Mbps, "
                f"fairness={row['background_runwide_jain']:.6f}",
                flush=True
            )

    require(len(all_rows) == 36, "Expected 36 complete runs")

    write_csv(all_rows, OUT / "results_36_runs.csv")

    # Descriptive statistics, not significance claims.
    grouped = []

    for controller in CONTROLLERS:
        subset = [
            r for r in all_rows
            if r["controller"] == controller
        ]

        require(len(subset) == 6, "Incomplete controller group")

        result = {"controller": controller, "seeds": 6}

        for metric in (
            "mean_fct_ms",
            "p95_fct_ms",
            "p99_fct_ms",
            "aggregate_goodput_mbps",
            "background_runwide_jain",
        ):
            values = [float(r[metric]) for r in subset]

            result[f"{metric}_mean"] = statistics.mean(values)
            result[f"{metric}_sd"] = statistics.stdev(values)

        grouped.append(result)

    write_csv(grouped, OUT / "controller_summary.csv")

    print("\n========== FULL VALIDATION ==========")
    print("PASS: 36/36 controller runs")
    print("PASS: All original FCT/queue regressions")
    print("PASS: All receiver-accounting checks")
    print("PASS: Paired workload manifests per seed")
    print("PASS: Goodput and fairness summaries")
    print()
    print("Outputs:")
    print(OUT / "results_36_runs.csv")
    print(OUT / "controller_summary.csv")
    print()
    print("PHASE 4 DATA COLLECTION COMPLETE")

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
