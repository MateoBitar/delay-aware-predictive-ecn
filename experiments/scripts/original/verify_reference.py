from pathlib import Path
import subprocess
import tempfile
import hashlib
import shutil
import sys

root = Path.cwd()
fixture = root / "fixtures/seed224_baseline"

# Also support execution from a working ns-3 installation.
if not fixture.exists():
    fixture = root / "repro_package/fixtures/seed224_baseline"

names = [
    "bursty-queue.dat",
    "bursty-ecn.dat",
    "bursty-short-fct.dat",
    "bursty-workload-manifest.csv",
    "bursty-cc-response.dat",
]

if not fixture.exists():
    sys.exit("ERROR: Reference fixture not found.")

if not (root / "ns3").exists():
    sys.exit("ERROR: Run from the ns-3.47 directory.")

command = [
    "./ns3",
    "run",
    "bursty-dctcp-baseline "
    "--controllerMode=baseline "
    "--minTh=20 --maxTh=60 "
    "--workloadMode=intermittent "
    "--burstSchedule=aligned "
    "--workloadVariation=controlled "
    "--workloadSeed=224 "
    "--backgroundJitterMs=10 "
    "--shortFlowJitterMs=5 "
    "--shortFlowSizeVariation=0.30 "
    "--delAckTimeoutMs=20 "
    "--RngSeed=1 --RngRun=101",
]

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

with tempfile.TemporaryDirectory() as tmp:
    backup = Path(tmp)
    existing = [
        p for p in root.glob("bursty-*.dat") if p.is_file()
    ]
    manifest = root / "bursty-workload-manifest.csv"
    if manifest.exists():
        existing.append(manifest)

    saved_names = {p.name for p in existing}

    for p in existing:
        shutil.copy2(p, backup / p.name)

    passed = False

    try:
        result = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True
        )

        if result.returncode:
            print(result.stdout[-2000:])
            print(result.stderr[-2000:])
            raise RuntimeError("ns-3 simulation failed.")

        print("========== REFERENCE VERIFICATION ==========")

        differences = []

        for name in names:
            actual = root / name
            expected = fixture / name

            if not actual.is_file() or not expected.is_file():
                status = "MISSING"
                differences.append(name)
            elif digest(actual) == digest(expected):
                status = "IDENTICAL"
            else:
                status = "DIFFERENT"
                differences.append(name)

            print(f"{name}: {status}")

        passed = not differences

    finally:
        for p in existing:
            shutil.copy2(backup / p.name, p)

        for p in root.glob("bursty-*.dat"):
            if p.name not in saved_names:
                p.unlink()

        if manifest.name not in saved_names:
            manifest.unlink(missing_ok=True)

print("\nRESULT:", "PASS" if passed else "FAIL")
sys.exit(0 if passed else 1)
