"""Offline contract tests for the source-first runner; no ns-3 download/build."""
import hashlib
import json
from pathlib import Path
import shlex
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "original": "88808776304afbd77766cf0f870f8220eb86464388065b6188af47157163dea4",
    "external": "80f507d3fdd9fb4519c0dc772f91b6387bc9716c7323c0fe16c9a053c5293a93",
    "predictor_2ms.model": "981eef1fc45c51f1f0adf3778d032bdfbbb9eedbdff14f6dbace49734356d85b",
    "predictor_5ms.model": "30372baf1843d5b9aec84bf95644a731637f5d3bcb5e8bcbd4fcd9e7555a7146",
    "predictor_20ms.model": "6df31cff964d2a4712e718c52aaae7cd9ee5c3a84bc2a8219be9dc9118640caf",
}
CONTROLLERS = ("baseline", "lower_fixed", "trend", "ml_2ms", "ml_5ms", "ml_20ms")


def hashfile(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SourceContract(unittest.TestCase):
    def test_source_hashes(self):
        paths = {"original": "src/ns3/examples/tcp/bursty-dctcp-baseline.cc",
                 "external": "src/external_override/bursty-dctcp-baseline.cc"}
        for key, rel in paths.items():
            with self.subTest(key=key):
                self.assertEqual(hashfile(ROOT / rel), EXPECTED[key])
        for name in EXPECTED:
            if name.endswith(".model"):
                with self.subTest(model=name):
                    self.assertEqual(hashfile(ROOT / "models" / name), EXPECTED[name])

    def test_build_registration(self):
        cmake = (ROOT / "src/ns3/examples/tcp/CMakeLists.txt").read_text()
        self.assertIn("NAME bursty-dctcp-baseline", cmake)
        for rel in ("src/ns3/src/traffic-control/model/red-queue-disc.cc",
                    "src/ns3/src/traffic-control/model/red-queue-disc.h"):
            self.assertTrue((ROOT / rel).is_file())

    def test_reference_original_commands(self):
        for controller in CONTROLLERS:
            file = (ROOT / "experiments/configurations/original/v2_full_evaluation" /
                    "seed_224" / controller / "command.json")
            with self.subTest(controller=controller):
                command = json.loads(file.read_text())
                self.assertEqual(command[:2], ["./ns3", "run"])
                self.assertEqual(len(command), 3)
                args = shlex.split(command[2])
                self.assertEqual(args[0], "bursty-dctcp-baseline")
                self.assertIn("--workloadSeed=224", args)
                self.assertIn("--RngRun=101", args)

    def test_reference_external_commands(self):
        base = (ROOT / "experiments/configurations/external/WebSearch" /
                "load_60/seed_230")
        for controller in CONTROLLERS:
            with self.subTest(controller=controller):
                folder = base / controller
                command = json.loads((folder / "command.json").read_text())
                self.assertIn("bursty-dctcp-baseline", command[0])
                self.assertIn("--RngRun=230", command)
                self.assertTrue(any(f.startswith("--externalManifestPath=") for f in command))
                self.assertTrue((folder / "input_manifest.csv").is_file())


if __name__ == "__main__":
    unittest.main()
