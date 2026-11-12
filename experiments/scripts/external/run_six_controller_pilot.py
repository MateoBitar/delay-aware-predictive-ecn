from pathlib import Path
import csv
import hashlib
import json
import math
import shutil
import statistics
import subprocess
import sys

ROOT = Path.home() / "ns3-external-validation"
NS3 = ROOT / "ns-3.47"
BINARY = NS3 / "build/examples/tcp/ns3.47-bursty-dctcp-baseline-default"
SOURCE_MANIFEST = ROOT / "workload_manifests/WebSearch/load_60/seed_230.csv"
OUT = ROOT / "pilot/websearch_60_seed230_matched_six"

COMMON = [
    "--workloadMode=intermittent",
    "--burstSchedule=original",
    "--workloadVariation=none",
    "--delAckTimeoutMs=20",
    "--RngSeed=1",
    "--RngRun=101",
]

CONTROLLERS = {
    "baseline": [
        "--controllerMode=baseline",
        "--minTh=20", "--maxTh=60",
    ],
    "lower_fixed": [
        "--controllerMode=baseline",
        "--minTh=10", "--maxTh=30",
    ],
    "trend": [
        "--controllerMode=trend-prediction-release",
        "--minTh=20", "--maxTh=60",
        "--earlyMinTh=10", "--earlyMaxTh=30",
        "--predictorHorizonMs=5",
        "--minActiveMs=10",
        "--negativeReleaseSamples=5",
    ],
}

for horizon in (2, 5, 20):
    model = (
        NS3 / "research_horizon_study/horizon_models"
        / f"predictor_{horizon}ms.model"
    )

    CONTROLLERS[f"ml_{horizon}ms"] = [
        "--controllerMode=ml-prediction-release",
        f"--mlModelPath={model}",
        f"--predictorHorizonMs={horizon}",
        "--minTh=20", "--maxTh=60",
        "--earlyMinTh=10", "--earlyMaxTh=30",
        "--minActiveMs=10",
        "--negativeReleaseSamples=5",
    ]

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def percentile(values, q):
    values = sorted(values)
    x = (len(values) - 1) * q
    lower = math.floor(x)
    upper = math.ceil(x)
    return values[lower] + (
        values[upper] - values[lower]
    ) * (x - lower)

def parse_fct(folder, manifest):
    result = {}

    path = folder / "bursty-short-fct.dat"
    require(path.is_file(), f"Missing FCT trace: {path}")

    for line in path.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue

        fields = line.split()
        require(len(fields) == 5, f"Invalid FCT row: {line}")

        fid = int(fields[0])
        start = float(fields[1])
        finish = float(fields[2])
        fct = float(fields[3])
        received = int(fields[4])

        require(fid in manifest, f"Unexpected flow ID: {fid}")
        require(fid not in result, f"Duplicate flow ID: {fid}")
        require(
            received == int(manifest[fid]["size_bytes"]),
            f"Flow {fid}: payload mismatch"
        )
        require(
            abs(start - float(manifest[fid]["start_s"])) <= 0.000002,
            f"Flow {fid}: start-time mismatch"
        )
        require(
            math.isclose(
                (finish - start) * 1000,
                fct,
                abs_tol=0.002
            ),
            f"Flow {fid}: FCT timestamp mismatch"
        )
        result[fid] = fct

    require(
        set(result) == set(manifest),
        f"Only {len(result)}/{len(manifest)} flows completed"
    )
    return result

def count_trace(path):
    require(path.is_file(), f"Missing trace: {path}")

    return sum(
        1 for line in path.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    )

def validate_run(folder, controller, expected_hash, manifest):
    require(
        sha256(folder / "input_manifest.csv") == expected_hash,
        f"{controller}: input manifest hash mismatch"
    )

    fcts = parse_fct(folder, manifest)

    short = [
        fcts[fid]
        for fid, entry in manifest.items()
        if entry["traffic_class"] == "short"
    ]

    large = [
        fcts[fid]
        for fid, entry in manifest.items()
        if entry["traffic_class"] == "large"
    ]

    require(len(short) > 0, "No short flows")
    require(len(large) > 0, "No large flows")

    actions = folder / "bursty-controller-actions.dat"

    activations = 0
    releases = 0

    if actions.is_file():
        for line in actions.read_text().splitlines():
            if not line.strip() or line.startswith("#"):
                continue

            fields = line.split()
            require(len(fields) >= 2, "Invalid action trace row")

            if fields[1] == "1":
                activations += 1
            elif fields[1] == "0":
                releases += 1

    inference_count = count_trace(
        folder / "bursty-ml-inference.dat"
    )

    if controller.startswith("ml_"):
        require(
            inference_count > 0,
            f"{controller}: no ML inference records"
        )
        require(
            activations > 0,
            f"{controller}: no early-marking activation"
        )

    require(
        count_trace(folder / "bursty-queue.dat") > 0,
        f"{controller}: empty queue trace"
    )

    require(
        count_trace(folder / "bursty-short-flow-state.dat") > 0,
        f"{controller}: empty TCP state trace"
    )

    return {
        "controller": controller,
        "completed_flows": len(fcts),
        "short_flows": len(short),
        "large_flows": len(large),
        "mean_short_fct_ms": statistics.mean(short),
        "p95_short_fct_ms": percentile(short, .95),
        "p99_short_fct_ms": percentile(short, .99),
        "mean_large_fct_ms": statistics.mean(large),
        "ml_inference_records": inference_count,
        "early_activations": activations,
        "early_releases": releases,
        "ecn_records": count_trace(
            folder / "bursty-ecn.dat"
        ),
        "manifest_sha256": expected_hash,
    }

def main():
    for path in (BINARY, SOURCE_MANIFEST):
        require(path.is_file(), f"Missing input: {path}")

    for horizon in (2, 5, 20):
        model = (
            NS3 / "research_horizon_study/horizon_models"
            / f"predictor_{horizon}ms.model"
        )
        require(model.is_file(), f"Missing model: {model}")

    require(
        not OUT.exists(),
        f"STOP: output directory already exists: {OUT}"
    )

    with SOURCE_MANIFEST.open(newline="") as file:
        rows = list(csv.DictReader(file))

    manifest = {
        int(row["flow_id"]): row
        for row in rows
    }

    require(
        len(rows) == len(manifest) == 240,
        "Expected 240 unique flows"
    )

    expected_hash = sha256(SOURCE_MANIFEST)
    OUT.mkdir(parents=True)

    print("========== MATCHED PILOT ==========", flush=True)
    print("Dataset: WebSearch", flush=True)
    print("Load target: 60%", flush=True)
    print("Seed: 230", flush=True)
    print("Controllers: 6", flush=True)
    print("Flows per controller: 240", flush=True)
    print("RngSeed: 1, RngRun: 101", flush=True)
    print("Manifest SHA256:", expected_hash, flush=True)

    source_hash = sha256(
        NS3 / "examples/tcp/bursty-dctcp-baseline.cc"
    )

    provenance = {
        "dataset": "WebSearch",
        "load_target": 0.60,
        "workload_seed": 230,
        "manifest_sha256": expected_hash,
        "simulator_source_sha256": source_hash,
        "rng_seed": 1,
        "rng_run": 101,
        "controller_flags": CONTROLLERS,
        "common_flags": COMMON,
        "status": "pilot",
    }

    (OUT / "provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )

    results = []

    for index, (controller, flags) in enumerate(
        CONTROLLERS.items(), 1
    ):
        folder = OUT / controller
        folder.mkdir()

        manifest_copy = folder / "input_manifest.csv"
        shutil.copyfile(SOURCE_MANIFEST, manifest_copy)

        command = [
            str(BINARY),
            f"--externalManifestPath={manifest_copy}",
            *COMMON,
            *flags,
        ]

        (folder / "command.json").write_text(
            json.dumps(command, indent=2) + "\n"
        )

        print(
            f"\n[{index}/6] RUNNING {controller}",
            flush=True
        )

        with (folder / "run.log").open("w") as log:
            result = subprocess.run(
                command,
                cwd=folder,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )

        require(
            result.returncode == 0,
            f"{controller}: simulator exit code "
            f"{result.returncode}; inspect {folder / 'run.log'}"
        )

        require(
            "PASS: external replay completed 240 flows"
            in (folder / "run.log").read_text(
                errors="replace"
            ),
            f"{controller}: completion message missing"
        )

        metrics = validate_run(
            folder, controller, expected_hash, manifest
        )
        results.append(metrics)

        (folder / "validated_result.json").write_text(
            json.dumps(metrics, indent=2) + "\n"
        )

        print(
            f"PASS {controller}: "
            f"mean={metrics['mean_short_fct_ms']:.3f} ms, "
            f"P95={metrics['p95_short_fct_ms']:.3f} ms, "
            f"P99={metrics['p99_short_fct_ms']:.3f} ms, "
            f"activations={metrics['early_activations']}",
            flush=True
        )

    output = OUT / "pilot_results.csv"

    with output.open("w", newline="") as file:
        writer = csv.DictWriter(
            file, fieldnames=list(results[0])
        )
        writer.writeheader()
        writer.writerows(results)

    require(len(results) == 6, "Expected six results")
    require(
        len({r["manifest_sha256"] for r in results}) == 1,
        "Workload hashes differ"
    )

    print("\n========== SIX-CONTROLLER AUDIT ==========")
    print("PASS: Six controllers completed")
    print("PASS: All 1,440 flow completions verified")
    print("PASS: Identical workload manifests")
    print("PASS: Identical ns-3 RNG settings")
    print("PASS: ML inference and activations verified")
    print("PASS: Controller metrics saved")
    print("RESULTS:", output)

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"\nSTOP: {error}", file=sys.stderr)
        sys.exit(1)
