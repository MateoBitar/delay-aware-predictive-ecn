#!/usr/bin/env python3
import csv
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import run_v2_pilot as pilot
from analyze_goodput_fairness import analyze

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "research_horizon_study/v2_delay_sensitivity"
ORIGINAL = (
    ROOT / "research_horizon_study"
    / "v2_full_evaluation/results_36_runs.csv"
)

DELAYS = {"medium": 250, "high": 1000}
SEEDS = range(224, 230)
CONTROLLERS = pilot.CONFIGS
TRACES = list(dict.fromkeys(pilot.TRACE_FILES))

def require(ok, message):
    if not ok:
        raise RuntimeError(message)

def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def read_csv(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))

def save_csv(rows, path):
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

def validate(dest, label, delay, seed, controller, expected_hash):
    for name in TRACES:
        require(
            (dest / name).is_file(),
            f"{label}: missing {name}"
        )

    metrics = pilot.calculate_original_metrics(dest)
    goodput, sessions = analyze(dest, 5.0)

    manifest = read_csv(
        dest / "bursty-workload-manifest.csv"
    )
    shorts = [
        r for r in manifest
        if r["record_type"] == "short_flow"
    ]
    backgrounds = [
        r for r in manifest
        if r["record_type"] == "background"
    ]

    require(len(shorts) == 24, f"{label}: short-flow count")
    require(len(backgrounds) == 18, f"{label}: background count")
    require(
        int(metrics["completed_flows"]) == 24,
        f"{label}: incomplete short flows"
    )

    offered = sum(int(r["max_bytes"]) for r in shorts)

    require(
        int(goodput["short_received_bytes"]) == offered,
        f"{label}: short-flow byte mismatch"
    )
    require(
        goodput["receiver_reconciliation"] == "PASS",
        f"{label}: background receiver reconciliation failed"
    )
    require(
        len(sessions) == 9,
        f"{label}: expected nine background session pairs"
    )
    require(
        0.5 <= float(goodput["background_runwide_jain"]) <= 1.0,
        f"{label}: invalid Jain index"
    )
    require(
        metrics["manifest_hash"] == expected_hash,
        f"{label}: workload differs from original seed {seed}"
    )

    save_csv(
        sessions,
        dest / "background_session_fairness.csv"
    )

    return {
        "delay_condition": label,
        "link_delay_us": delay,
        "seed": seed,
        "controller": controller,
        **metrics,
        "offered_short_bytes": offered,
        "short_goodput_mbps": goodput["short_goodput_mbps"],
        "background1_goodput_mbps":
            goodput["background1_goodput_mbps"],
        "background2_goodput_mbps":
            goodput["background2_goodput_mbps"],
        "aggregate_goodput_mbps":
            goodput["aggregate_goodput_mbps"],
        "background_runwide_jain":
            goodput["background_runwide_jain"],
    }

def main():
    print("========== DELAY SENSITIVITY PRE-FLIGHT ==========",
          flush=True)

    require(ORIGINAL.is_file(), "Original 36-run CSV missing")
    require(len(CONTROLLERS) == 6, "Expected six controllers")
    require(len(TRACES) > 0, "Trace list is empty")

    original = read_csv(ORIGINAL)
    require(len(original) == 36, "Expected 36 reference results")

    reference_hashes = {}
    for row in original:
        key = (int(row["seed"]), row["controller"])
        require(key not in reference_hashes, "Duplicate reference row")
        reference_hashes[key] = row["manifest_hash"]

    for seed in SEEDS:
        hashes = {
            reference_hashes[(seed, controller)]
            for controller in CONTROLLERS
        }
        require(
            len(hashes) == 1,
            f"Unpaired original workload for seed {seed}"
        )

    models = {
        horizon: (
            ROOT / "research_horizon_study/horizon_models"
            / f"predictor_{horizon}ms.model"
        )
        for horizon in (2, 5, 20)
    }

    for model in models.values():
        require(model.is_file(), f"Missing model: {model}")

    source = ROOT / "examples/tcp/bursty-dctcp-baseline.cc"
    require(
        "uint32_t linkDelayUs = 10;" in source.read_text(),
        "Delay extension missing"
    )

    provenance = {
        "delays_us": DELAYS,
        "seeds": list(SEEDS),
        "controllers": CONTROLLERS,
        "common_flags": pilot.COMMON,
        "original_sha256": sha256(ORIGINAL),
        "simulator_sha256": sha256(source),
        "analyzer_sha256": sha256(
            ROOT / "analyze_goodput_fairness.py"
        ),
        "pilot_sha256": sha256(ROOT / "run_v2_pilot.py"),
        "models_sha256": {
            str(h): sha256(p)
            for h, p in models.items()
        },
    }

    OUT.mkdir(parents=True, exist_ok=True)
    provenance_file = OUT / "provenance.json"

    if provenance_file.exists():
        require(
            json.loads(provenance_file.read_text()) == provenance,
            "Provenance changed; refusing unsafe resume"
        )
    else:
        provenance_file.write_text(
            json.dumps(provenance, indent=2) + "\n"
        )

    print("PASS: Reference workload hashes verified")
    print("PASS: Frozen models verified")
    print("PASS: Experiment provenance verified", flush=True)

    rows = []
    total = len(DELAYS) * len(SEEDS) * len(CONTROLLERS)
    count = 0

    for condition, delay in DELAYS.items():
        for seed in SEEDS:
            expected_hash = reference_hashes[(seed, "baseline")]

            for controller, flags in CONTROLLERS.items():
                count += 1

                name = f"{condition}/seed_{seed}/{controller}"
                dest = OUT / condition / f"seed_{seed}" / controller
                dest.mkdir(parents=True, exist_ok=True)

                common = pilot.COMMON.replace(
                    "--workloadSeed=224",
                    f"--workloadSeed={seed}"
                )

                require(
                    common != pilot.COMMON or seed == 224,
                    "Workload seed substitution failed"
                )
                require(
                    f"--workloadSeed={seed}" in common,
                    "Incorrect workload seed"
                )

                command = [
                    "./ns3",
                    "run",
                    (
                        f"bursty-dctcp-baseline {common} "
                        f"{flags} --linkDelayUs={delay}"
                    )
                ]

                command_file = dest / "command.json"
                done = dest / "validated_result.json"

                if command_file.exists():
                    require(
                        json.loads(command_file.read_text()) == command,
                        f"{name}: command changed"
                    )
                else:
                    command_file.write_text(
                        json.dumps(command, indent=2) + "\n"
                    )

                if done.exists():
                    print(
                        f"[{count}/{total}] REVALIDATING {name}",
                        flush=True
                    )
                    row = validate(
                        dest, condition, delay, seed,
                        controller, expected_hash
                    )
                    require(
                        json.loads(done.read_text()) == row,
                        f"{name}: saved result changed"
                    )
                else:
                    print(
                        f"[{count}/{total}] RUNNING {name}",
                        flush=True
                    )

                    for trace in TRACES:
                        (ROOT / trace).unlink(missing_ok=True)

                    try:
                        with (dest / "run.log").open("w") as log:
                            process = subprocess.run(
                                command,
                                cwd=ROOT,
                                stdout=log,
                                stderr=subprocess.STDOUT,
                                timeout=180
                            )
                    except subprocess.TimeoutExpired:
                        raise RuntimeError(
                            f"{name}: timeout; inspect {dest / 'run.log'}"
                        )

                    require(
                        process.returncode == 0,
                        f"{name}: simulator error; "
                        f"inspect {dest / 'run.log'}"
                    )

                    for trace in TRACES:
                        src = ROOT / trace
                        require(
                            src.is_file(),
                            f"{name}: missing generated {trace}"
                        )
                        shutil.copy2(src, dest / trace)

                    row = validate(
                        dest, condition, delay, seed,
                        controller, expected_hash
                    )

                    # Only mark a run complete after every check passes.
                    done.write_text(
                        json.dumps(row, indent=2) + "\n"
                    )

                rows.append(row)
                save_csv(rows, OUT / "results_partial.csv")

                print(
                    f"PASS: P99={float(row['p99_fct_ms']):.3f}ms "
                    f"Goodput={float(row['aggregate_goodput_mbps']):.3f}Mbps "
                    f"Jain={float(row['background_runwide_jain']):.6f}",
                    flush=True
                )

    require(len(rows) == 72, "Expected 72 validated runs")

    save_csv(rows, OUT / "results_72_runs.csv")

    print("\n========== FINAL VALIDATION ==========")
    print("PASS: 72/72 new delay experiments")
    print("PASS: Original workload matching per seed")
    print("PASS: All short flows completed")
    print("PASS: Receiver byte reconciliation")
    print("PASS: Goodput and fairness calculations")
    print()
    print("Results:", OUT / "results_72_runs.csv")
    print("PHASE 6 DATA COLLECTION COMPLETE")

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"\nSTOP: {error}", file=sys.stderr, flush=True)
        sys.exit(1)
