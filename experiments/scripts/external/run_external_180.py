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
SOURCE = NS3 / "examples/tcp/bursty-dctcp-baseline.cc"
OUT = ROOT / "external_evaluation_180"

CONDITIONS = [
    ("WebSearch", 60),
    ("WebSearch", 80),
    ("WebSearch", 95),
    ("FB_Hadoop", 60),
    ("FB_Hadoop", 95),
]

SEEDS = range(230, 236)

COMMON = [
    "--workloadMode=intermittent",
    "--burstSchedule=original",
    "--workloadVariation=none",
    "--delAckTimeoutMs=20",
    "--RngSeed=1",
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

MODELS = {}

for horizon in (2, 5, 20):
    model = (
        NS3 / "research_horizon_study/horizon_models"
        / f"predictor_{horizon}ms.model"
    )
    MODELS[f"ml_{horizon}ms"] = model

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

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def percentile(values, q):
    values = sorted(values)
    pos = (len(values) - 1) * q
    low, high = math.floor(pos), math.ceil(pos)
    return values[low] + (values[high] - values[low]) * (pos - low)

def read_manifest(path):
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))

    require(len(rows) == 240, f"{path}: expected 240 flows")

    by_id = {}
    for row in rows:
        fid = int(row["flow_id"])
        require(fid not in by_id, f"Duplicate flow {fid}: {path}")
        require(row["traffic_class"] in ("short", "large"),
                f"Invalid traffic class: {path}")
        require(int(row["size_bytes"]) > 0,
                f"Invalid flow size: {path}")
        require(float(row["start_s"]) >= 0,
                f"Invalid flow start: {path}")
        require(
            (int(row["size_bytes"]) <= 250000)
            == (row["traffic_class"] == "short"),
            f"Traffic-class mismatch: {path}"
        )
        by_id[fid] = row

    require(set(by_id) == set(range(240)),
            f"Invalid flow IDs: {path}")
    return by_id

def validate(folder, manifest, controller, manifest_hash):
    require(
        sha(folder / "input_manifest.csv") == manifest_hash,
        "Workload manifest hash mismatch"
    )

    trace = folder / "bursty-short-fct.dat"
    require(trace.is_file(), "Missing FCT trace")

    fcts = {}

    for line in trace.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue

        fields = line.split()
        require(len(fields) == 5, f"Invalid FCT row: {line}")

        fid = int(fields[0])
        start = float(fields[1])
        finish = float(fields[2])
        fct = float(fields[3])
        received = int(fields[4])

        require(fid in manifest, f"Unexpected flow {fid}")
        require(fid not in fcts, f"Duplicate flow {fid}")
        require(received == int(manifest[fid]["size_bytes"]),
                f"Flow {fid}: received-byte mismatch")
        require(
            abs(start - float(manifest[fid]["start_s"])) <= 0.000002,
            f"Flow {fid}: start-time mismatch"
        )
        require(finish >= start, f"Flow {fid}: invalid finish")
        require(
            math.isclose(
                (finish - start) * 1000,
                fct,
                abs_tol=0.002
            ),
            f"Flow {fid}: FCT mismatch"
        )

        fcts[fid] = fct

    require(set(fcts) == set(manifest),
            f"Only {len(fcts)}/240 flows completed")

    short = [
        fcts[fid] for fid, row in manifest.items()
        if row["traffic_class"] == "short"
    ]
    large = [
        fcts[fid] for fid, row in manifest.items()
        if row["traffic_class"] == "large"
    ]

    require(short and large, "Missing short or large flows")

    for name in (
        "bursty-queue.dat",
        "bursty-ecn.dat",
        "bursty-ml-inference.dat",
        "bursty-controller-actions.dat",
        "bursty-short-flow-state.dat",
    ):
        require((folder / name).is_file(), f"Missing {name}")

    inference = folder / "bursty-ml-inference.dat"
    inference_rows = sum(
        1 for line in inference.open()
        if line.strip() and not line.startswith("#")
    )

    if controller.startswith("ml_"):
        require(inference_rows > 0, "ML inference trace empty")

    activations = 0
    releases = 0

    with (folder / "bursty-controller-actions.dat").open() as f:
        for line in f:
            if not line.strip() or line.startswith("#"):
                continue
            fields = line.split()
            require(len(fields) >= 2, "Malformed action record")
            if fields[1] == "1":
                activations += 1
            elif fields[1] == "0":
                releases += 1

    return {
        "controller": controller,
        "completed_flows": len(fcts),
        "short_flows": len(short),
        "large_flows": len(large),
        "mean_short_fct_ms": statistics.mean(short),
        "p95_short_fct_ms": percentile(short, .95),
        "p99_short_fct_ms": percentile(short, .99),
        "mean_large_fct_ms": statistics.mean(large),
        "ml_inference_records": inference_rows,
        "early_activations": activations,
        "early_releases": releases,
        "manifest_sha256": manifest_hash,
    }

def save_summary(results):
    path = OUT / "results_partial.csv"
    temporary = OUT / "results_partial.csv.tmp"

    fields = [
        "dataset", "load_percent", "seed",
        "controller", "completed_flows",
        "short_flows", "large_flows",
        "mean_short_fct_ms",
        "p95_short_fct_ms",
        "p99_short_fct_ms",
        "mean_large_fct_ms",
        "ml_inference_records",
        "early_activations", "early_releases",
        "manifest_sha256",
    ]

    with temporary.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(results)

    temporary.replace(path)

def main():
    for p in (BINARY, SOURCE, *MODELS.values()):
        require(p.is_file(), f"Missing required file: {p}")

    jobs = []
    manifest_hashes = {}

    # Verify all inputs before running anything.
    for dataset, load in CONDITIONS:
        for seed in SEEDS:
            manifest = (
                ROOT / "workload_manifests" / dataset
                / f"load_{load}" / f"seed_{seed}.csv"
            )
            require(manifest.is_file(), f"Missing: {manifest}")
            read_manifest(manifest)

            key = f"{dataset}/load_{load}/seed_{seed}"
            manifest_hashes[key] = sha(manifest)

            for controller in CONTROLLERS:
                jobs.append(
                    (dataset, load, seed, controller, manifest)
                )

    require(len(jobs) == 180, "Expected 180 jobs")
    require(len(manifest_hashes) == 30,
            "Expected 30 workload manifests")

    config = {
        "study": "external_flow_size_distribution_evaluation",
        "status_description": "Frozen-model evaluation",
        "planned_runs": 180,
        "flows_per_run": 240,
        "conditions": CONDITIONS,
        "seeds": list(SEEDS),
        "rng_seed": 1,
        "rng_run_rule": "RngRun equals workload seed",
        "common_flags": COMMON,
        "controllers": CONTROLLERS,
        "source_sha256": sha(SOURCE),
        "binary_sha256": sha(BINARY),
        "model_sha256": {
            name: sha(path) for name, path in MODELS.items()
        },
        "manifests": manifest_hashes,
        "short_flow_definition": "size_bytes <= 250000",
        "load_definition": (
            "Nominal payload offered load over generated "
            "arrival window; not measured link utilization"
        ),
        "workload_description": (
            "Trace-derived flow-size CDFs with "
            "synthetically generated burst arrival times"
        ),
    }

    OUT.mkdir(parents=True, exist_ok=True)
    config_path = OUT / "campaign_config.json"

    if config_path.exists():
        saved = json.loads(config_path.read_text())
        require(
            saved == config,
            "STOP: Source, binary, models, manifests, or "
            "campaign settings changed since campaign began"
        )
    else:
        require(
            not any(OUT.iterdir()),
            "STOP: Campaign directory contains unknown files"
        )
        config_path.write_text(
            json.dumps(config, indent=2) + "\n"
        )

    results = []

    print("========== FORMAL EXTERNAL EVALUATION ==========",
          flush=True)
    print("Validated manifests: 30", flush=True)
    print("Planned runs: 180", flush=True)
    print("Evaluation seeds: 230-235", flush=True)
    print("Frozen models: 2, 5, 20 ms", flush=True)
    print("Original experiments: untouched", flush=True)

    for number, job in enumerate(jobs, 1):
        dataset, load, seed, controller, source_manifest = job

        condition = f"{dataset}/load_{load}/seed_{seed}"
        folder = OUT / condition / controller
        result_file = folder / "validated_result.json"
        expected_hash = manifest_hashes[condition]

        if result_file.is_file():
            saved = json.loads(result_file.read_text())
            require(
                saved["manifest_sha256"] == expected_hash,
                f"Manifest mismatch in {folder}"
            )
            require(
                saved["controller"] == controller
                and saved["dataset"] == dataset
                and saved["load_percent"] == load
                and saved["seed"] == seed
                and saved["completed_flows"] == 240,
                f"Invalid saved result in {folder}"
            )
            results.append(saved)
            print(f"[{number}/180] SKIP verified {condition}/{controller}",
                  flush=True)
            continue

        require(
            not folder.exists(),
            f"STOP: Incomplete run directory: {folder}. "
            "Preserve it for diagnosis before restarting."
        )

        folder.mkdir(parents=True)

        manifest_copy = folder / "input_manifest.csv"
        shutil.copyfile(source_manifest, manifest_copy)
        require(
            sha(manifest_copy) == expected_hash,
            "Copied manifest does not match source"
        )

        command = [
            str(BINARY),
            f"--externalManifestPath={manifest_copy}",
            *COMMON,
            f"--RngRun={seed}",
            *CONTROLLERS[controller],
        ]

        (folder / "command.json").write_text(
            json.dumps(command, indent=2) + "\n"
        )

        print(
            f"[{number}/180] RUN {condition}/{controller}",
            flush=True
        )

        with (folder / "run.log").open("w") as log:
            completed = subprocess.run(
                command,
                cwd=folder,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )

        require(
            completed.returncode == 0,
            f"Simulator exit {completed.returncode}; "
            f"inspect {folder / 'run.log'}"
        )

        log_tail = (
            folder / "run.log"
        ).read_text(errors="replace").splitlines()[-8:]

        require(
            "PASS: external replay completed 240 flows"
            in log_tail,
            f"Missing simulator completion confirmation: {folder}"
        )

        manifest_rows = read_manifest(manifest_copy)

        metrics = validate(
            folder,
            manifest_rows,
            controller,
            expected_hash,
        )

        metrics.update({
            "dataset": dataset,
            "load_percent": load,
            "seed": seed,
        })

        result_file.write_text(
            json.dumps(metrics, indent=2) + "\n"
        )
        results.append(metrics)
        save_summary(results)

        print(
            f"  PASS: P95={metrics['p95_short_fct_ms']:.3f} ms, "
            f"P99={metrics['p99_short_fct_ms']:.3f} ms",
            flush=True
        )

    require(len(results) == 180, "Incomplete campaign")

    save_summary(results)
    shutil.copyfile(
        OUT / "results_partial.csv",
        OUT / "results_180_runs.csv"
    )

    print("\n========== FINAL CAMPAIGN AUDIT ==========")
    print("PASS: 180/180 runs validated")
    print("PASS: 43,200/43,200 flow completions verified")
    print("PASS: All 30 workload manifests accounted for")
    print("PASS: All 6 controllers evaluated per manifest")
    print("PASS: Source, binary and model hashes preserved")
    print("RESULTS:", OUT / "results_180_runs.csv")

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"\nSTOP: {error}", file=sys.stderr, flush=True)
        sys.exit(1)
