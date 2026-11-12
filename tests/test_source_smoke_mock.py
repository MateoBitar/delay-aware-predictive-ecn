"""Mocked integration contract: exercise setup and run without compiling ns-3.

This is NOT a scientific simulation test. It verifies the orchestration,
workspace safety, archived commands, path mapping, and outputs directory.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "run_from_source.py"
TRACES = [
    "bursty-background-rx.csv", "bursty-receiver.dat",
    "bursty-short-flow-rx.dat", "bursty-short-fct.dat",
    "bursty-workload-manifest.csv", "bursty-queue.dat",
    "bursty-ecn.dat", "bursty-cc-response.dat",
]
FAKE_LAUNCHER = """#!/usr/bin/env python3
from pathlib import Path
import shlex
import sys
assert len(sys.argv) >= 3 and sys.argv[1] == "run"
argv = shlex.split(sys.argv[2])
assert argv[0] == "bursty-dctcp-baseline"
external = any(x.startswith("--externalManifestPath=") for x in argv)
for name in FILES:
    Path(name).write_text("mock\\n")
Path("bursty-short-fct.dat").write_text(
    "".join(f"{i} 0 0 0 1\\n" for i in range(240 if external else 24)))
""".replace("FILES", repr(TRACES))


class SourceSetupMockTest(unittest.TestCase):
    def test_original_and_external_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clean = root / "clean" / "ns-3.47"
            (clean / "src/traffic-control/model").mkdir(parents=True)
            (clean / "examples/tcp").mkdir(parents=True)
            (clean / "src/traffic-control/model/red-queue-disc.cc").write_text("// upstream placeholder\n")
            (clean / "src/traffic-control/model/red-queue-disc.h").write_text("// upstream placeholder\n")
            (clean / "examples/tcp/CMakeLists.txt").write_text("# upstream placeholder\n")
            launcher = clean / "ns3"
            launcher.write_text(FAKE_LAUNCHER)
            launcher.chmod(0o755)
            for variant, seed in (("original", 224), ("external", 230)):
                with self.subTest(variant=variant):
                    ws = root / variant
                    setup = subprocess.run([
                        sys.executable, str(RUNNER), "setup",
                        "--ns3-source", str(clean), "--workspace", str(ws),
                        "--variant", variant, "--skip-build",
                    ], cwd=ROOT, capture_output=True, text=True)
                    self.assertEqual(setup.returncode, 0, setup.stdout + setup.stderr)
                    run = subprocess.run([
                        sys.executable, str(RUNNER), "run",
                        "--workspace", str(ws), "--controller", "baseline",
                        "--seed", str(seed),
                    ], cwd=ROOT, capture_output=True, text=True)
                    self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                    self.assertIn("SMOKE TEST PASS", run.stdout)
                    output = (ws / "runs" / variant /
                              ("v2_full_evaluation/seed_224/baseline" if variant == "original"
                               else "WebSearch/load_60/seed_230/baseline"))
                    self.assertTrue((output / "source_command.json").is_file())
                    self.assertTrue((output / "simulation.log").is_file())
                    self.assertTrue((output / "bursty-short-fct.dat").is_file())
                    self.assertFalse((ws / "ns-3.47/bursty-short-fct.dat").exists())
                    # Ensure accidental repeat cannot overwrite existing results.
                    again = subprocess.run([
                        sys.executable, str(RUNNER), "run",
                        "--workspace", str(ws), "--controller", "baseline",
                        "--seed", str(seed),
                    ], cwd=ROOT, capture_output=True, text=True)
                    self.assertNotEqual(again.returncode, 0)
                    self.assertIn("refusing to overwrite", again.stderr)


if __name__ == "__main__":
    unittest.main()
