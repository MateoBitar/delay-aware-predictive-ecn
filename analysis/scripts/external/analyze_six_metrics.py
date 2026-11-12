from pathlib import Path
from collections import defaultdict
import csv
import hashlib
import json
import math
import statistics
import sys

ROOT = Path.home() / "ns3-external-validation"
CAMPAIGN = ROOT / "external_evaluation_180"
SOURCE = CAMPAIGN / "results_180_runs.csv"
OUT = ROOT / "external_analysis/six_metrics"

CONTROLLERS = (
    "baseline", "lower_fixed", "trend",
    "ml_2ms", "ml_5ms", "ml_20ms"
)

CONDITIONS = (
    ("WebSearch", 60),
    ("WebSearch", 80),
    ("WebSearch", 95),
    ("FB_Hadoop", 60),
    ("FB_Hadoop", 95),
)

SEEDS = tuple(range(230, 236))
BIN_SECONDS = 0.100

def require(ok, message):
    if not ok:
        raise ValueError(message)

def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def percentile(values, q):
    values = sorted(values)
    x = (len(values) - 1) * q
    a, b = math.floor(x), math.ceil(x)
    return values[a] + (values[b] - values[a]) * (x - a)

def mean(values):
    return statistics.mean(values) if values else float("nan")

def jain(values):
    n = len(values)
    s = sum(values)
    ss = sum(v * v for v in values)
    return s * s / (n * ss) if n >= 2 and ss > 0 else None

def read_manifest(folder, expected_hash):
    path = folder / "input_manifest.csv"
    require(sha256(path) == expected_hash,
            f"Manifest checksum mismatch: {folder}")

    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))

    require(len(rows) == 240, "Expected 240 manifest rows")

    flows = {}
    for row in rows:
        fid = int(row["flow_id"])
        require(fid not in flows, "Duplicate manifest flow ID")
        flows[fid] = {
            "start": float(row["start_s"]),
            "bytes": int(row["size_bytes"]),
            "class": row["traffic_class"],
            "sender": fid % 3,
        }

    require(set(flows) == set(range(240)),
            "Unexpected manifest flow IDs")
    return flows

def read_fct(folder, flows):
    result = {}

    with (folder / "bursty-short-fct.dat").open() as f:
        for line in f:
            if not line.strip() or line.startswith("#"):
                continue

            parts = line.split()
            require(len(parts) == 5, "Invalid FCT trace row")

            fid = int(parts[0])
            start = float(parts[1])
            finish = float(parts[2])
            fct_ms = float(parts[3])
            received = int(parts[4])

            require(fid in flows and fid not in result,
                    "Unexpected or duplicate FCT flow")
            require(received == flows[fid]["bytes"],
                    f"FCT payload mismatch: {fid}")
            require(abs(start - flows[fid]["start"]) <= 0.000002,
                    f"Start-time mismatch: {fid}")
            require(math.isclose(
                (finish - start) * 1000,
                fct_ms, abs_tol=0.002
            ), f"FCT timestamp mismatch: {fid}")

            result[fid] = {
                "finish": finish,
                "fct_ms": fct_ms,
                "bytes": received,
            }

    require(set(result) == set(flows),
            f"Only {len(result)} flows have FCT records")
    return result

def analyze_run(folder, row):
    flows = read_manifest(folder, row["manifest_sha256"])
    fcts = read_fct(folder, flows)

    first_start = min(v["start"] for v in flows.values())
    last_start = max(v["start"] for v in flows.values())
    last_finish = max(v["finish"] for v in fcts.values())

    arrival_window = last_start - first_start
    require(arrival_window > 0, "Invalid arrival window")

    # ----------------------------------------------------
    # Receiver goodput and byte-level trace verification
    # ----------------------------------------------------
    rx_total = defaultdict(int)
    rx_last_cumulative = {}
    within_arrival_window_bytes = 0
    sender_bin_bytes = defaultdict(int)

    with (folder / "bursty-short-flow-rx.dat").open() as f:
        for line in f:
            if not line.strip() or line.startswith("#"):
                continue

            fields = line.split()
            require(len(fields) == 4, "Invalid RX trace row")

            t = float(fields[0])
            fid = int(fields[1])
            packet_bytes = int(fields[2])
            cumulative = int(fields[3])

            require(fid in flows, "Unknown flow in RX trace")
            require(packet_bytes > 0, "Invalid RX packet size")
            require(
                first_start - 0.000002 <= t <=
                fcts[fid]["finish"] + 0.000002,
                f"RX timestamp outside flow lifetime: {fid}"
            )

            rx_total[fid] += packet_bytes
            rx_last_cumulative[fid] = cumulative

            require(rx_total[fid] == cumulative,
                    f"RX cumulative counter mismatch: {fid}")

            if t <= last_start:
                within_arrival_window_bytes += packet_bytes

            bin_id = max(
                0, int((t - first_start) / BIN_SECONDS)
            )

            sender_bin_bytes[
                (bin_id, flows[fid]["sender"])
            ] += packet_bytes

    for fid in flows:
        require(rx_total[fid] == flows[fid]["bytes"],
                f"RX byte mismatch: {fid}")
        require(
            rx_last_cumulative[fid] == flows[fid]["bytes"],
            f"Final cumulative RX mismatch: {fid}"
        )

    # Jain fairness proxy: compare senders in 100-ms bins
    # when at least two have active flow demand for
    # at least half the bin.
    sender_active = defaultdict(set)

    for fid, flow in flows.items():
        start = flow["start"]
        finish = fcts[fid]["finish"]
        sender = flow["sender"]

        first_bin = max(
            0, int((start - first_start) / BIN_SECONDS)
        )
        last_bin = max(
            first_bin,
            int((finish - first_start) / BIN_SECONDS)
        )

        for b in range(first_bin, last_bin + 1):
            left = first_start + b * BIN_SECONDS
            right = left + BIN_SECONDS

            overlap = max(
                0.0,
                min(right, finish) - max(left, start)
            )

            if overlap >= BIN_SECONDS / 2 - 1e-9:
                sender_active[b].add(sender)

    fairness_values = []

    for b, active in sender_active.items():
        if len(active) < 2:
            continue

        amounts = [
            sender_bin_bytes.get((b, sender), 0)
            for sender in sorted(active)
        ]

        score = jain(amounts)

        if score is not None:
            fairness_values.append(score)

    # ----------------------------------------------------
    # Queue occupancy (sampled at simulator intervals)
    # ----------------------------------------------------
    queue_values = []
    delay_values = []
    queue_timestamps = []
    at_20 = 0
    at_60 = 0

    with (folder / "bursty-queue.dat").open() as f:
        for line in f:
            if not line.strip() or line.startswith("#"):
                continue

            fields = line.split()
            require(len(fields) >= 3, "Invalid queue trace")

            t = float(fields[0])
            packets = float(fields[1])
            delay_us = float(fields[2])

            queue_timestamps.append(t)
            queue_values.append(packets)
            delay_values.append(delay_us)

            at_20 += int(packets >= 20)
            at_60 += int(packets >= 60)

    require(queue_values, "Empty queue trace")
    require(all(
        b > a for a, b in zip(
            queue_timestamps, queue_timestamps[1:]
        )
    ), "Non-increasing queue timestamps")

    # ----------------------------------------------------
    # ECN, inference and controller action activity
    # ----------------------------------------------------
    marks = defaultdict(int)

    with (folder / "bursty-ecn.dat").open() as f:
        for line in f:
            if not line.strip() or line.startswith("#"):
                continue

            fields = line.split(maxsplit=5)
            require(len(fields) == 6, "Invalid ECN row")
            marks[fields[5]] += 1

    inference_samples = 0
    alert_samples = 0

    with (folder / "bursty-ml-inference.dat").open() as f:
        for line in f:
            if not line.strip() or line.startswith("#"):
                continue

            fields = line.split()
            require(len(fields) >= 4, "Invalid inference row")
            inference_samples += 1
            alert_samples += int(fields[3] == "1")

    activations = 0
    releases = 0

    with (folder / "bursty-controller-actions.dat").open() as f:
        for line in f:
            if not line.strip() or line.startswith("#"):
                continue

            fields = line.split()
            require(len(fields) >= 5, "Invalid action row")

            if fields[1] == "1":
                activations += 1
            elif fields[1] == "0":
                releases += 1
            else:
                raise ValueError("Unknown controller action")

    short = [
        fid for fid, f in flows.items()
        if f["class"] == "short"
    ]
    large = [
        fid for fid, f in flows.items()
        if f["class"] == "large"
    ]

    def flow_goodput(fid):
        duration_s = fcts[fid]["fct_ms"] / 1000
        return (
            fcts[fid]["bytes"] * 8 /
            duration_s / 1e6
        )

    # Receiver payload delivered no later than the
    # final scheduled arrival, over a common time window.
    window_goodput_mbps = (
        within_arrival_window_bytes * 8 /
        arrival_window / 1e6
    )

    duration = queue_timestamps[-1] - queue_timestamps[0]
    require(duration > 0, "Invalid queue observation duration")

    result = {
        "dataset": row["dataset"],
        "load_percent": int(row["load_percent"]),
        "seed": int(row["seed"]),
        "controller": row["controller"],
        "manifest_sha256": row["manifest_sha256"],
        "flows_verified": 240,
        "short_flows": len(short),
        "large_flows": len(large),

        "mean_short_fct_ms":
            float(row["mean_short_fct_ms"]),
        "p95_short_fct_ms":
            float(row["p95_short_fct_ms"]),
        "p99_short_fct_ms":
            float(row["p99_short_fct_ms"]),

        "mean_short_flow_goodput_mbps":
            mean([flow_goodput(fid) for fid in short]),
        "mean_large_flow_goodput_mbps":
            mean([flow_goodput(fid) for fid in large]),
        "arrival_window_goodput_mbps":
            window_goodput_mbps,
        "arrival_window_delivered_fraction":
            within_arrival_window_bytes /
            sum(v["bytes"] for v in flows.values()),

        "sender_fairness_jain_100ms":
            mean(fairness_values),
        "fairness_eligible_bins":
            len(fairness_values),

        "mean_queue_packets": mean(queue_values),
        "p95_queue_packets":
            percentile(queue_values, 0.95),
        "max_queue_packets": max(queue_values),
        "mean_queue_delay_us": mean(delay_values),
        "p95_queue_delay_us":
            percentile(delay_values, 0.95),
        "fraction_queue_ge_20": at_20 / len(queue_values),
        "fraction_queue_ge_60": at_60 / len(queue_values),
        "queue_samples": len(queue_values),
        "queue_start_s": queue_timestamps[0],
        "queue_end_s": queue_timestamps[-1],

        "inference_samples": inference_samples,
        "alert_samples": alert_samples,
        "inference_per_simulated_second":
            inference_samples / duration,
        "early_activations": activations,
        "early_releases": releases,
        "ecn_marks_total": sum(marks.values()),
        "ecn_unforced_marks":
            marks.get("Unforced mark", 0),
        "ecn_forced_marks":
            marks.get("Forced mark", 0),

        "total_payload_bytes":
            sum(v["bytes"] for v in flows.values()),
        "first_arrival_s": first_start,
        "last_arrival_s": last_start,
        "last_completion_s": last_finish,
    }

    for key, original in (
        ("p95_short_fct_ms", "p95_short_fct_ms"),
        ("p99_short_fct_ms", "p99_short_fct_ms"),
    ):
        require(math.isfinite(result[key]),
                f"Invalid {key}")

    return result

def write_csv(path, records):
    tmp = path.with_suffix(path.suffix + ".tmp")

    with tmp.open("w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=list(records[0])
        )
        writer.writeheader()
        writer.writerows(records)

    tmp.replace(path)

def main():
    require(SOURCE.is_file(), "Missing campaign results")
    require(not OUT.exists(),
            f"STOP: Analysis directory exists: {OUT}")

    with SOURCE.open(newline="") as f:
        rows = list(csv.DictReader(f))

    require(len(rows) == 180, "Expected 180 campaign rows")

    expected_keys = {
        (dataset, load, seed, controller)
        for dataset, load in CONDITIONS
        for seed in SEEDS
        for controller in CONTROLLERS
    }

    actual_keys = {
        (
            r["dataset"],
            int(r["load_percent"]),
            int(r["seed"]),
            r["controller"],
        )
        for r in rows
    }

    require(actual_keys == expected_keys,
            "Unexpected or missing run identities")

    OUT.mkdir(parents=True)

    print("========== SIX-METRIC ANALYSIS ==========",
          flush=True)
    print("Expected runs: 180", flush=True)
    print("All RX and queue traces processed read-only",
          flush=True)

    results = []

    for index, row in enumerate(rows, 1):
        folder = (
            CAMPAIGN / row["dataset"]
            / f"load_{row['load_percent']}"
            / f"seed_{row['seed']}"
            / row["controller"]
        )

        require(folder.is_dir(), f"Missing run: {folder}")

        result = analyze_run(folder, row)
        results.append(result)

        # Preserve partial analyses without overwriting
        # any experiment output.
        write_csv(OUT / "six_metrics_partial.csv", results)

        print(
            f"[{index}/180] PASS "
            f"{row['dataset']} {row['load_percent']}% "
            f"seed={row['seed']} {row['controller']} "
            f"fairness_bins={result['fairness_eligible_bins']}",
            flush=True
        )

    require(len(results) == 180, "Incomplete analysis")

    # Fairness windows can be absent in some workloads.
    # Keep those values as unavailable, never as zero.
    for r in results:
        if r["fairness_eligible_bins"] == 0:
            r["sender_fairness_jain_100ms"] = float("nan")

    write_csv(OUT / "six_metrics_180_runs.csv", results)

    groups = defaultdict(list)
    for result in results:
        groups[(
            result["dataset"],
            result["load_percent"],
            result["controller"]
        )].append(result)

    metrics = (
        "p95_short_fct_ms",
        "p99_short_fct_ms",
        "mean_short_flow_goodput_mbps",
        "mean_large_flow_goodput_mbps",
        "arrival_window_goodput_mbps",
        "sender_fairness_jain_100ms",
        "mean_queue_packets",
        "p95_queue_packets",
        "max_queue_packets",
        "mean_queue_delay_us",
        "p95_queue_delay_us",
        "fraction_queue_ge_20",
        "fraction_queue_ge_60",
        "inference_per_simulated_second",
        "early_activations",
        "ecn_marks_total",
    )

    summary = []

    for (dataset, load, controller), group in sorted(
        groups.items()
    ):
        require(len(group) == 6,
                "Expected six seeds in every group")

        item = {
            "dataset": dataset,
            "load_percent": load,
            "controller": controller,
            "seeds": 6,
        }

        for metric in metrics:
            finite = [
                float(r[metric]) for r in group
                if math.isfinite(float(r[metric]))
            ]

            item[metric] = mean(finite)
            item[metric + "_seeds_available"] = len(finite)

        summary.append(item)

    require(len(summary) == 30,
            "Expected 30 condition-controller summaries")

    write_csv(OUT / "six_metric_controller_summary.csv",
              summary)

    provenance = {
        "input_results_file": str(SOURCE),
        "input_results_sha256": sha256(SOURCE),
        "campaign_config_sha256":
            sha256(CAMPAIGN / "campaign_config.json"),
        "runs_analyzed": 180,
        "summary_rows": 30,
        "fairness_bin_seconds": BIN_SECONDS,
        "short_flow_cutoff_bytes": 250000,
        "definitions": {
            "fct": "Previously validated short-flow FCT",
            "flow_goodput": (
                "Payload bytes * 8 / individual flow FCT"
            ),
            "arrival_window_goodput": (
                "Payload received between first and last "
                "scheduled flow arrival, divided by this "
                "fixed per-manifest interval"
            ),
            "fairness": (
                "Mean Jain index of per-sender delivered "
                "bytes in 100 ms bins with at least two "
                "senders each active for at least 50 ms. "
                "Descriptive proxy, demand-sensitive."
            ),
            "queue": (
                "Sample-based occupancy and delay from "
                "1 ms simulator traces"
            ),
            "overhead": (
                "Inference and control activity counts; "
                "not measured CPU time or network overhead"
            ),
        },
    }

    (OUT / "analysis_provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )

    print("\n========== FINAL METRIC AUDIT ==========")
    print("PASS: 180 runs analyzed")
    print("PASS: 43,200 receiver payload totals verified")
    print("PASS: P95/P99 retained")
    print("PASS: Application goodput calculated")
    print("PASS: Sender fairness proxy calculated")
    print("PASS: Queue occupancy and delay calculated")
    print("PASS: Prediction and control activity counted")
    print("PASS: 30 summary rows created")
    print("RESULTS:", OUT / "six_metrics_180_runs.csv")
    print("SUMMARY:", OUT / "six_metric_controller_summary.csv")

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"\nSTOP: {error}", file=sys.stderr, flush=True)
        sys.exit(1)
