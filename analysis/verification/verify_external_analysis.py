#!/usr/bin/env python3
"""Reproduce the accepted external six-metric analysis without modifying it."""

from pathlib import Path
from collections import Counter, defaultdict
import argparse
import contextlib
import csv
import hashlib
import importlib.util
import json
import statistics
import tempfile


EXPECTED_HASHES = {
    "six_metrics/six_metrics_180_runs.csv":
        "d074f1918a122ac6a617eb86985ae5b2f0b8f393cfe45e3736e46dc7f9a267f7",
    "six_metrics/six_metric_controller_summary.csv":
        "9060224d1a6c87d1afb28691a726c25370aa15f835cb7055beb1bb8fbd6cf8f6",
    "six_metric_comparisons/all_paired_metric_comparisons.csv":
        "08df8efe41fb937c2928d96b753ab0c9b4bf9cd3c488e90ec24314066d14f913",
    "six_metric_comparisons/controller_summary_all_metrics.csv":
        "4e757bd0cbedfe4615047a409a49aa2c2b9445048edadb5e553189e2dca9b98c",
}


def require(ok, message):
    if not ok:
        raise RuntimeError("STOP: " + message)


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_csv(path):
    require(path.is_file(), f"Missing CSV: {path}")
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames), list(reader)


def write_csv(path, columns, rows):
    require(not path.exists(), f"Output already exists: {path}")
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def import_script(path, name):
    require(path.is_file(), f"Missing script: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None,
            f"Cannot import: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def group_key(row):
    return (
        row["dataset"],
        int(row["load_percent"]),
        row["controller"],
    )


def extend_summary(columns, rows, groups, suffix):
    columns = list(columns)

    for metric in ("ecn_forced_marks", "ecn_unforced_marks"):
        if metric not in columns:
            columns.append(metric)

    for metric in ("ecn_forced_marks", "ecn_unforced_marks"):
        if metric + suffix not in columns:
            columns.append(metric + suffix)

    for row in rows:
        group = groups.get(group_key(row))
        require(group is not None and len(group) == 6,
                f"Invalid summary group: {group_key(row)}")

        for metric in ("ecn_forced_marks", "ecn_unforced_marks"):
            row[metric] = statistics.mean(
                int(item[metric]) for item in group
            )
            row[metric + suffix] = 6

    return columns


def main():
    parser = argparse.ArgumentParser(
        description="Verify the corrected external analysis."
    )
    parser.add_argument(
        "--external-root",
        type=Path,
        default=(
            Path(__file__).resolve().parents[1]
            / "external_validation"
        ),
        help="External-validation directory; defaults to packaged layout",
    )
    parser.add_argument(
        "--output-parent",
        type=Path,
        required=True,
        help="Existing independent directory for verification outputs",
    )
    args = parser.parse_args()

    root = args.external_root.resolve()
    output_parent = args.output_parent.resolve()

    require(root.is_dir(), "External-validation root missing")
    require(output_parent.is_dir(), "Output parent missing")
    require(not args.output_parent.is_symlink(),
            "Output parent must not be a symbolic link")
    require(
        not output_parent.is_relative_to(root)
        and not root.is_relative_to(output_parent),
        "Verification output must be separate from research inputs"
    )

    # Original workspace: scripts are in ROOT.
    # Extracted ZIP: scripts are in ROOT/scripts.
    scripts = root / "scripts"
    if not scripts.is_dir():
        scripts = root

    campaign = root / "external_evaluation_180"
    accepted = root / "external_analysis"

    require(campaign.is_dir(), "External campaign missing")
    require(accepted.is_dir(), "Accepted analysis missing")

    analysis_path = scripts / "analyze_six_metrics.py"
    comparison_path = scripts / "compare_six_metrics.py"

    require(
        analysis_path.is_file() and comparison_path.is_file(),
        "Historical analysis scripts missing"
    )

    work = Path(tempfile.mkdtemp(
        prefix="portable-external-verification-",
        dir=output_parent,
    )).resolve()

    six = work / "six_metrics"
    comparison_out = work / "six_metric_comparisons"

    print("========== PORTABLE EXTERNAL VERIFICATION ==========")
    print("Research inputs:", root)
    print("Independent outputs:", work, flush=True)

    analysis = import_script(analysis_path, "historical_six_metrics")
    analysis.ROOT = root
    analysis.CAMPAIGN = campaign
    analysis.SOURCE = campaign / "results_180_runs.csv"
    analysis.OUT = six

    require(not six.exists(), "Verification output exists")

    log = work / "execution.log"

    print("Recalculating 180 runs with original analysis...", flush=True)
    with log.open("w") as f:
        with contextlib.redirect_stdout(f):
            analysis.main()

    run_file = six / "six_metrics_180_runs.csv"
    summary_file = six / "six_metric_controller_summary.csv"

    run_columns, runs = read_csv(run_file)
    summary_columns, summaries = read_csv(summary_file)

    require(len(runs) == 180, "Expected 180 run rows")
    require(len(summaries) == 30, "Expected 30 summary rows")

    groups = defaultdict(list)
    marks = Counter()
    identities = set()

    print("Reclassifying ECN events from raw traces...", flush=True)

    for index, row in enumerate(runs, 1):
        identity = (
            row["dataset"],
            int(row["load_percent"]),
            int(row["seed"]),
            row["controller"],
        )
        require(identity not in identities,
                f"Duplicate run: {identity}")
        identities.add(identity)

        dataset, load, seed, controller = identity
        trace = (
            campaign / dataset / f"load_{load}"
            / f"seed_{seed}" / controller / "bursty-ecn.dat"
        )
        require(trace.is_file() and not trace.is_symlink(),
                f"Missing or linked ECN trace: {trace}")

        counts = Counter()

        with trace.open() as f:
            for number, line in enumerate(f, 1):
                if not line.strip() or line.startswith("#"):
                    continue
                parts = line.split(maxsplit=5)
                require(len(parts) == 6,
                        f"Invalid ECN row: {trace}:{number}")
                reason = parts[5].strip()
                require(reason in ("Forced mark", "Unforced mark"),
                        f"Unknown ECN reason: {reason!r}")
                counts[reason] += 1

        forced = counts["Forced mark"]
        unforced = counts["Unforced mark"]

        require(
            forced + unforced == int(row["ecn_marks_total"]),
            f"ECN total mismatch: {identity}"
        )

        row["ecn_forced_marks"] = str(forced)
        row["ecn_unforced_marks"] = str(unforced)

        groups[group_key(row)].append(row)
        marks["forced"] += forced
        marks["unforced"] += unforced

        if index % 30 == 0:
            print(f"  Verified {index}/180", flush=True)

    require(len(identities) == 180, "Expected 180 unique runs")
    require(len(groups) == 30, "Expected 30 controller groups")
    require(marks["forced"] == 312946, "Forced ECN total mismatch")
    require(marks["unforced"] == 1776902,
            "Unforced ECN total mismatch")

    # Replace only the newly generated verification CSVs.
    staging_runs = work / "corrected_runs.csv"
    write_csv(staging_runs, run_columns, runs)
    staging_runs.replace(run_file)

    summary_columns = extend_summary(
        summary_columns, summaries, groups, "_seeds_available"
    )
    staging_summary = work / "corrected_summary.csv"
    write_csv(staging_summary, summary_columns, summaries)
    staging_summary.replace(summary_file)

    # Original deterministic bootstrap/statistical implementation.
    compare = import_script(
        comparison_path, "historical_six_metric_comparison"
    )
    compare.SOURCE = run_file
    compare.OUT = comparison_out

    require(not comparison_out.exists(),
            "Comparison output already exists")

    print("Regenerating 935 original paired comparisons...", flush=True)
    with log.open("a") as f:
        with contextlib.redirect_stdout(f):
            compare.main()

    controller_file = (
        comparison_out / "controller_summary_all_metrics.csv"
    )
    columns, rows = read_csv(controller_file)
    require(len(rows) == 30, "Expected 30 controller summary rows")

    columns = extend_summary(columns, rows, groups, "_n")
    staged = work / "corrected_controller_summary.csv"
    write_csv(staged, columns, rows)
    staged.replace(controller_file)

    print("\n========== SCIENTIFIC OUTPUT VERIFICATION ==========")

    checks = []
    for relative, expected_hash in EXPECTED_HASHES.items():
        generated = work / relative
        reference = accepted / relative

        require(generated.is_file(), f"Missing generated: {relative}")
        require(reference.is_file(), f"Missing accepted: {relative}")

        generated_hash = digest(generated)
        reference_hash = digest(reference)
        identical = (
            generated_hash == reference_hash == expected_hash
        )

        print(
            ("PASS" if identical else "FAIL")
            + ": " + relative,
            flush=True
        )

        checks.append({
            "file": relative,
            "expected_sha256": expected_hash,
            "generated_sha256": generated_hash,
            "accepted_sha256": reference_hash,
            "byte_identical": identical,
        })

    passed = all(item["byte_identical"] for item in checks)

    report = {
        "status": "PASS" if passed else "REVIEW_REQUIRED",
        "runs_analyzed": 180,
        "forced_ecn_marks": marks["forced"],
        "unforced_ecn_marks": marks["unforced"],
        "analysis_script_sha256": digest(analysis_path),
        "comparison_script_sha256": digest(comparison_path),
        "scientific_outputs": checks,
        "original_simulations_modified": False,
        "original_analyses_modified": False,
    }

    report_path = work / "PORTABLE_VERIFICATION_REPORT.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")

    print("\nByte-identical CSVs:",
          sum(item["byte_identical"] for item in checks), "/4")
    print("Report:", report_path)
    print("Log:", log)
    print("Status:", report["status"])

    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
