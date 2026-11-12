from pathlib import Path
import tempfile
import subprocess
import shutil
import hashlib
import numpy as np
import sys

ROOT = Path.cwd()
OUT = ROOT / "research_horizon_study/horizon_models"

MODEL_NAMES = [
    f"predictor_{h}ms.model"
    for h in (1, 2, 5, 10, 20)
]

RESULT_NAMES = [
    "horizon_comparison.csv",
    *[f"results_{h}ms.json" for h in (1, 2, 5, 10, 20)]
]

NAMES = MODEL_NAMES + RESULT_NAMES

for name in NAMES:
    if not (OUT / name).is_file():
        sys.exit(f"ERROR: Missing frozen file: {name}")

def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def read_model(path):
    lines = path.read_text().splitlines()
    if len(lines) != 5 or lines[0] != "NS3_LOGISTIC_V1":
        raise ValueError(f"Unexpected model format: {path}")

    return np.concatenate([
        np.fromstring(line, sep=" ")
        for line in lines[1:]
    ])

with tempfile.TemporaryDirectory() as tmp:
    backup = Path(tmp)

    for name in NAMES:
        shutil.copy2(OUT / name, backup / name)

    try:
        print("========== MODEL RETRAINING ==========", flush=True)

        with (backup / "training.log").open("w") as log:
            result = subprocess.run(
                [sys.executable, "train_horizon_models.py"],
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT
            )

        print((backup / "training.log").read_text()[-7000:])

        if result.returncode != 0:
            raise RuntimeError("Training failed; see output above.")

        print("\n========== MODEL COMPARISON ==========")

        exact_count = 0
        numeric_count = 0

        for name in MODEL_NAMES:
            original = backup / name
            reproduced = OUT / name

            exact = sha256(original) == sha256(reproduced)

            a = read_model(original)
            b = read_model(reproduced)

            if a.shape != b.shape:
                raise RuntimeError(f"Parameter count differs: {name}")

            max_diff = float(np.max(np.abs(a - b)))
            numerical_match = np.allclose(
                a, b, rtol=1e-10, atol=1e-12
            )

            exact_count += int(exact)
            numeric_count += int(numerical_match)

            print(
                f"{name}: "
                f"byte_identical={exact}, "
                f"numerically_identical={numerical_match}, "
                f"max_abs_difference={max_diff:.12g}"
            )

        print("\n========== RESULT FILE COMPARISON ==========")

        for name in RESULT_NAMES:
            exact = sha256(backup / name) == sha256(OUT / name)
            print(f"{name}: {'IDENTICAL' if exact else 'DIFFERENT'}")

        print("\n========== TRAINING REPRODUCIBILITY ==========")
        print(f"Byte-identical models: {exact_count}/5")
        print(f"Numerically matching models: {numeric_count}/5")

        if exact_count == 5:
            print("PASS: All five exported models are byte-identical.")
        elif numeric_count == 5:
            print("PARTIAL PASS: All models match numerically.")
        else:
            print("ATTENTION: Model parameter differences detected.")

    finally:
        for name in NAMES:
            shutil.copy2(backup / name, OUT / name)

        print("\nOriginal frozen models and results restored.")
