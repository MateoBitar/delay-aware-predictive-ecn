#!/usr/bin/env python3
"""Code-first ns-3.47 setup and one-case execution using recorded study inputs.

Separate from reproduce_full_research_FIXED.py: this does NOT assert exact
360-run archival trace reproduction. Never modifies release assets.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
EXPECTED = {
    "original": "88808776304afbd77766cf0f870f8220eb86464388065b6188af47157163dea4",
    "external": "80f507d3fdd9fb4519c0dc772f91b6387bc9716c7323c0fe16c9a053c5293a93",
    "predictor_2ms.model": "981eef1fc45c51f1f0adf3778d032bdfbbb9eedbdff14f6dbace49734356d85b",
    "predictor_5ms.model": "30372baf1843d5b9aec84bf95644a731637f5d3bcb5e8bcbd4fcd9e7555a7146",
    "predictor_20ms.model": "6df31cff964d2a4712e718c52aaae7cd9ee5c3a84bc2a8219be9dc9118640caf",
}
ORIGINAL_TRACES = (
    "bursty-background-rx.csv", "bursty-receiver.dat",
    "bursty-short-flow-rx.dat", "bursty-short-fct.dat",
    "bursty-workload-manifest.csv", "bursty-queue.dat",
    "bursty-ecn.dat", "bursty-cc-response.dat",
)
SETUP_RECORD = ".source_setup.json"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as src:
        for block in iter(lambda: src.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verified_copy(src, dst, expected=None):
    require(src.is_file() and not src.is_symlink(), f"Missing regular source file: {src}")
    if expected:
        require(sha256(src) == expected, f"Repository file digest mismatch: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    require(sha256(dst) == sha256(src), f"Copied file changed: {dst}")


def checked_call(command, cwd, log=None):
    print("+", shlex.join(map(str, command)), flush=True)
    if log:
        with log.open("w", encoding="utf-8") as f:
            r = subprocess.run(command, cwd=cwd, stdout=f, stderr=subprocess.STDOUT, check=False)
        require(r.returncode == 0, f"Command failed ({r.returncode}). Read {log}")
    else:
        subprocess.run(command, cwd=cwd, check=True)


def prepare(args):
    ns3_source = Path(args.ns3_source).expanduser().resolve()
    workspace = Path(args.workspace).expanduser().resolve()
    require(ns3_source.is_dir() and ns3_source.name == "ns-3.47",
            "Provide the root of an extracted, clean ns-3.47 release directory")
    require((ns3_source / "ns3").is_file() and
            (ns3_source / "src/traffic-control/model/red-queue-disc.cc").is_file() and
            (ns3_source / "examples/tcp/CMakeLists.txt").is_file(),
            "Not an ns-3.47 source tree")
    require(workspace != ns3_source and not workspace.exists(),
            "Workspace already exists or is source itself. Choose a new empty path.")
    require(not (ns3_source / "examples/tcp/bursty-dctcp-baseline.cc").exists(),
            "Input already contains the research example; use a CLEAN upstream ns-3.47 source tree")
    require(shutil.which("cmake") and shutil.which("ninja") and shutil.which("g++"),
            "CMake, Ninja and g++ are required (sudo apt install build-essential cmake ninja-build)")
    source_rel = ("src/ns3/examples/tcp/bursty-dctcp-baseline.cc" if args.variant == "original"
                  else "src/external_override/bursty-dctcp-baseline.cc")
    source = ROOT / source_rel
    require(source.is_file() and sha256(source) == EXPECTED[args.variant],
            "Experiment C++ file does not match the original verified research SHA-256")
    for name in ("predictor_2ms.model", "predictor_5ms.model", "predictor_20ms.model"):
        require(sha256(ROOT / "models" / name) == EXPECTED[name],
                f"Frozen model digest mismatch: {name}")
    require((ROOT / "src/ns3/examples/tcp/CMakeLists.txt").is_file(),
            "Missing archived CMake registration")
    require((ROOT / "src/ns3/src/traffic-control/model/red-queue-disc.cc").is_file() and
            (ROOT / "src/ns3/src/traffic-control/model/red-queue-disc.h").is_file(),
            "Missing modified RED/ECN source")

    print(f"Creating a separate {args.variant} workspace: {workspace}", flush=True)
    try:
        workspace.mkdir(parents=True)
        target = workspace / "ns-3.47"
        shutil.copytree(ns3_source, target, symlinks=False)
        # The source files are the same research-specific copies as the
        # manifest-verified release; no source code is invented or patched ad hoc.
        for rel in ("src/traffic-control/model/red-queue-disc.cc",
                    "src/traffic-control/model/red-queue-disc.h",
                    "examples/tcp/CMakeLists.txt"):
            verified_copy(ROOT / "src/ns3" / rel, target / rel)
        verified_copy(source, target / "examples/tcp/bursty-dctcp-baseline.cc",
                      EXPECTED[args.variant])
        models_dst = target / "research_horizon_study/horizon_models"
        for name in ("predictor_2ms.model", "predictor_5ms.model", "predictor_20ms.model"):
            verified_copy(ROOT / "models" / name, models_dst / name, EXPECTED[name])
        (workspace / SETUP_RECORD).write_text(json.dumps({
            "variant": args.variant, "ns3_version": "3.47",
            "source_sha256": EXPECTED[args.variant],
            "models": {n: EXPECTED[n] for n in EXPECTED if n.endswith(".model")},
            "setup_method": "upstream ns-3.47 + archived research sources",
            "build": "optimized, examples enabled, Ninja",
        }, indent=2) + "\n", encoding="utf-8")
        if not args.skip_build:
            checked_call(["./ns3", "configure", "--enable-examples",
                          "--build-profile=optimized", "-G", "Ninja"], target,
                         workspace / "configure.log")
            checked_call(["./ns3", "build"], target, workspace / "build.log")
        print("SETUP COMPLETE. Variant:", args.variant)
        if args.skip_build:
            print("Build intentionally skipped; configure and build ns-3.47 before running.")
    except Exception:
        print(f"SETUP INCOMPLETE: inspect {workspace}; do not reuse as a clean workspace.",
              file=sys.stderr)
        raise


def case_path(variant, campaign, seed, controller, dataset, load):
    base = ROOT / "experiments/configurations"
    if variant == "original":
        require(campaign in ("v2_full_evaluation", "v2_burst_size_sensitivity",
                             "v2_delay_sensitivity"),
                "Unknown original campaign")
        return base / "original" / campaign / f"seed_{seed}" / controller
    require(dataset in ("WebSearch", "FB_Hadoop") and load in (60, 80, 95),
            "Specify a valid external dataset/load combination")
    require(not (dataset == "FB_Hadoop" and load == 80),
            "FB_Hadoop 80% load was not in the accepted campaign")
    return base / "external" / dataset / f"load_{load}" / f"seed_{seed}" / controller


def run_case(args):
    workspace = Path(args.workspace).expanduser().resolve()
    setup = workspace / SETUP_RECORD
    require(setup.is_file(), f"Not a prepared source workspace: {workspace}")
    metadata = json.loads(setup.read_text())
    variant = metadata["variant"]
    require((224 <= args.seed <= 229) if variant == "original" else
            (230 <= args.seed <= 235), "Seed not in the accepted campaign")
    require(args.controller in ("baseline", "lower_fixed", "trend",
                               "ml_2ms", "ml_5ms", "ml_20ms"),
            "Unknown controller")
    original_case = case_path(variant, args.campaign, args.seed, args.controller,
                              args.dataset, args.load)
    command_file = original_case / "command.json"
    require(command_file.is_file(), f"Recorded case does not exist: {command_file}")
    recorded = json.loads(command_file.read_text(encoding="utf-8"))
    require(isinstance(recorded, list) and all(isinstance(x, str) for x in recorded),
            "Invalid recorded command JSON")
    ns3 = workspace / "ns-3.47"
    require((ns3 / "ns3").is_file(), "Missing ns-3 launcher")
    require(sha256(ns3 / "examples/tcp/bursty-dctcp-baseline.cc") ==
            EXPECTED[variant], "Prepared simulation source changed")
    output = workspace / "runs" / original_case.relative_to(
        ROOT / "experiments/configurations")
    require(not output.exists(), "Output already exists; refusing to overwrite an experiment")
    require(not any(ns3.glob("bursty-*")),
            "Research output files already exist in ns-3 root; refusing stale-data ambiguity")

    if variant == "original":
        require(recorded[:2] == ["./ns3", "run"] and len(recorded) == 3,
                "Unexpected original recorded command shape")
        parts = shlex.split(recorded[2])
        require(parts and parts[0] == "bursty-dctcp-baseline", "Unknown recorded executable")
        run_flags = parts[1:]
    else:
        require(recorded and "bursty-dctcp-baseline" in recorded[0],
                "Unexpected external recorded command shape")
        run_flags = recorded[1:]
        manifest_source = original_case / "input_manifest.csv"
        require(manifest_source.is_file(), "External input manifest is missing")
    # The archived configurations contain machine-specific absolute paths.
    # Only model and external-manifest locations are relocated.
    normalized = []
    output.mkdir(parents=True)
    if variant == "external":
        verified_copy(manifest_source, output / "input_manifest.csv")
    for flag in run_flags:
        if flag.startswith("--mlModelPath="):
            name = Path(flag.split("=", 1)[1]).name
            require(name in EXPECTED and name.endswith(".model"),
                    f"Unrecognized frozen model: {name}")
            model = ns3 / "research_horizon_study/horizon_models" / name
            require(sha256(model) == EXPECTED[name], f"Frozen model changed: {name}")
            flag = "--mlModelPath=" + str(model)
        elif flag.startswith("--externalManifestPath="):
            require(variant == "external", "Unexpected external manifest")
            flag = "--externalManifestPath=" + str(output / "input_manifest.csv")
        normalized.append(flag)
    require(variant == "original" or
            any(f.startswith("--externalManifestPath=") for f in normalized),
            "External run is missing its manifest")
    run_spec = "bursty-dctcp-baseline " + shlex.join(normalized)
    command = ["./ns3", "run", run_spec]
    (output / "source_command.json").write_text(
        json.dumps({"archived_command": recorded, "local_command": command,
                    "case": str(original_case.relative_to(ROOT)),
                    "source_sha256": EXPECTED[variant]}, indent=2) + "\n")
    print("Running archived", variant, "case in its own prepared ns-3 tree")
    checked_call(command, ns3, output / "simulation.log")
    files = sorted(p for p in ns3.glob("bursty-*") if p.is_file())
    require(files and any(p.name == "bursty-short-fct.dat" for p in files),
            "Simulator did not generate FCT output; see simulation.log")
    if variant == "original":
        require(set(ORIGINAL_TRACES).issubset({p.name for p in files}),
                "Original run is missing recorded core trace files")
    # Move generated outputs only after the simulator completes successfully.
    for path in files:
        shutil.move(str(path), output / path.name)
    fct = output / "bursty-short-fct.dat"
    data_lines = [line for line in fct.read_text().splitlines()
                  if line.strip() and not line.lstrip().startswith("#")]
    expected_flows = 24 if variant == "original" else 240
    require(len(data_lines) == expected_flows,
            f"Expected {expected_flows} completed-flow records; found {len(data_lines)}")
    print(f"SMOKE TEST PASS: {len(data_lines)} completed-flow records, "
          f"{len(files)} research output files.")
    print("Outputs:", output)
    print("This proves the case executed; it does NOT prove exact historical "
          "hashes or full-campaign reproducibility.")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="action", required=True)
    a = sub.add_parser("setup", help="Prepare one fresh ns-3.47 variant from clean upstream")
    a.add_argument("--ns3-source", required=True, help="Path to CLEAN upstream ns-3.47")
    a.add_argument("--workspace", required=True, help="New, nonexistent output directory")
    a.add_argument("--variant", choices=("original", "external"), default="original")
    a.add_argument("--skip-build", action="store_true", help="For manual configuration only")
    b = sub.add_parser("run", help="Run one exact recorded case with remapped paths")
    b.add_argument("--workspace", required=True)
    b.add_argument("--controller", choices=("baseline", "lower_fixed", "trend",
                     "ml_2ms", "ml_5ms", "ml_20ms"), default="baseline")
    b.add_argument("--seed", type=int, default=224,
                   help="Original: 224–229; external: 230–235")
    b.add_argument("--campaign", default="v2_full_evaluation",
                   help="Original campaign (defaults to reference 36-run campaign)")
    b.add_argument("--dataset", choices=("WebSearch", "FB_Hadoop"),
                   default="WebSearch", help="External campaign only")
    b.add_argument("--load", type=int, default=60, help="External nominal load (percent)")
    args = p.parse_args()
    try:
        prepare(args) if args.action == "setup" else run_case(args)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print("STOP:", exc, file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
