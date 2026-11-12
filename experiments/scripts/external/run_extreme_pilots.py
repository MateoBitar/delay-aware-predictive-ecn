from pathlib import Path
import csv
import hashlib
import math
import shutil
import subprocess
import sys

root = Path.home() / "ns3-external-validation"
binary = (
    root / "ns3.47-not-used"
)
binary = (
    root / "ns-3.47/build/examples/tcp/"
    "ns3.47-bursty-dctcp-baseline-default"
)

conditions = [
    ("WebSearch", 95),
    ("FB_Hadoop", 95),
]

def check_run(folder, manifest):
    with manifest.open(newline="") as f:
        rows = list(csv.DictReader(f))

    expected = {
        int(r["flow_id"]): r
        for r in rows
    }

    assert len(expected) == len(rows) == 240

    fct_path = folder / "bursty-short-fct.dat"
    assert fct_path.is_file(), "FCT trace missing"

    fcts = {}

    for line in fct_path.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue

        fid, start, finish, fct, received = line.split()
        fid = int(fid)

        assert fid in expected and fid not in fcts
        assert int(received) == int(expected[fid]["size_bytes"])
        assert abs(
            float(start) - float(expected[fid]["start_s"])
        ) <= 0.000002
        assert math.isclose(
            (float(finish) - float(start)) * 1000,
            float(fct),
            abs_tol=0.002
        )

        fcts[fid] = float(fct)

    assert set(fcts) == set(expected), (
        f"Only {len(fcts)}/240 flows completed"
    )

    short = sorted(
        fcts[fid]
        for fid, row in expected.items()
        if row["traffic_class"] == "short"
    )

    large = [
        fid for fid, row in expected.items()
        if row["traffic_class"] == "large"
    ]

    def pct(q):
        x = (len(short) - 1) * q
        low, high = math.floor(x), math.ceil(x)
        return short[low] + (
            short[high] - short[low]
        ) * (x - low)

    print("PASS: 240/240 flows verified", flush=True)
    print("Short flows:", len(short), flush=True)
    print("Large flows:", len(large), flush=True)
    print("Short P95 (ms):", round(pct(.95), 3), flush=True)
    print("Short P99 (ms):", round(pct(.99), 3), flush=True)
    print(
        "Payload bytes:",
        sum(int(r["size_bytes"]) for r in rows),
        flush=True
    )

try:
    assert binary.is_file(), f"Missing simulator: {binary}"

    # Preflight every directory before starting either run.
    prepared = []

    for dataset, load in conditions:
        source = (
            root / "workload_manifests" / dataset
            / f"load_{load}/seed_230.csv"
        )

        folder = (
            root / "pilot"
            / f"{dataset.lower()}_{load}_seed230_baseline_extreme"
        )

        assert source.is_file(), f"Missing manifest: {source}"
        assert not folder.exists(), (
            f"STOP: Existing output directory: {folder}"
        )

        prepared.append((dataset, load, source, folder))

    for dataset, load, source, folder in prepared:
        print(
            f"\n========== {dataset} {load}% BASELINE ==========",
            flush=True
        )

        folder.mkdir(parents=True)
        manifest = folder / "input_manifest.csv"
        shutil.copyfile(source, manifest)

        assert (
            hashlib.sha256(manifest.read_bytes()).digest()
            ==
            hashlib.sha256(source.read_bytes()).digest()
        )

        command = [
            str(binary),
            f"--externalManifestPath={manifest}",
            "--controllerMode=baseline",
            "--minTh=20",
            "--maxTh=60",
            "--workloadMode=intermittent",
            "--burstSchedule=original",
            "--workloadVariation=none",
            "--delAckTimeoutMs=20",
            "--RngSeed=1",
            "--RngRun=101",
        ]

        with (folder / "run.log").open("w") as log:
            result = subprocess.run(
                command,
                cwd=folder,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False
            )

        print("Exit code:", result.returncode, flush=True)

        if result.returncode != 0:
            print(
                "\n".join(
                    (folder / "run.log")
                    .read_text(errors="replace")
                    .splitlines()[-20:]
                ),
                flush=True
            )
            raise RuntimeError(
                f"{dataset} {load}% simulation failed"
            )

        check_run(folder, manifest)

    print("\nPASS: Both extreme-load pilots validated", flush=True)

except Exception as error:
    print(f"\nSTOP: {error}", file=sys.stderr, flush=True)
    sys.exit(1)
