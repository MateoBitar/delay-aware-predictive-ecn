#!/usr/bin/env python3
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


def jain(a, b):
    if a == 0 and b == 0:
        return None
    return (a + b) ** 2 / (2 * (a*a + b*b))


def read_csv(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def analyze(directory, duration):
    background = read_csv(directory / "bursty-background-rx.csv")
    manifest = read_csv(directory / "bursty-workload-manifest.csv")

    if not background:
        raise ValueError("Background receiver trace is empty")

    windows = {
        (int(r["id"]), int(r["sender"])):
        (float(r["start_s"]), float(r["stop_s"]))
        for r in manifest
        if r["record_type"] == "background"
    }

    if len(windows) != 18:
        raise ValueError(
            f"Expected 18 background windows, found {len(windows)}"
        )

    sessions = defaultdict(int)
    sender_totals = defaultdict(int)
    last_cumulative = {}

    # Match each sender's nine TCP source ports to the nine
    # installed background sessions.
    sender_ports = {}

    for sender in (1, 2):
        ports = sorted({
            int(r["source_port"])
            for r in background
            if int(r["sender_id"]) == sender
        })

        if len(ports) != 9:
            raise ValueError(
                f"Sender {sender}: expected 9 source ports, "
                f"found {len(ports)}"
            )

        sender_ports[sender] = {
            port: index for index, port in enumerate(ports)
        }

    previous_cumulative = {1: 0, 2: 0}

    for row in background:
        sender = int(row["sender_id"])
        port = int(row["source_port"])
        timestamp = float(row["time_s"])
        payload = int(row["payload_bytes"])
        cumulative = int(row["cumulative_sender_bytes"])

        if sender not in (1, 2):
            raise ValueError("Unknown background sender")

        if payload <= 0:
            raise ValueError("Invalid payload size")

        if timestamp < 0 or timestamp > duration:
            raise ValueError("Receiver event outside observation interval")

        if cumulative != previous_cumulative[sender] + payload:
            raise ValueError(
                f"Sender {sender}: cumulative counter mismatch"
            )

        previous_cumulative[sender] = cumulative

        session = sender_ports[sender][port]
        start, stop = windows[(session, sender)]

        # Packets may arrive after the sending application stops.
        # Only validate ordering, not an arbitrary post-stop cutoff.
        if timestamp < start - 1e-6:
            raise ValueError(
                f"Session {session}: received before scheduled start"
            )

        sessions[(session, sender)] += payload
        sender_totals[sender] += payload
        last_cumulative[sender] = cumulative

    for sender in (1, 2):
        if sender_totals[sender] != last_cumulative[sender]:
            raise ValueError(
                f"Sender {sender}: final cumulative mismatch"
            )

    # Independently reconcile with the original receiver trace.
    original_payloads = []

    with (directory / "bursty-receiver.dat").open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) != 2:
                raise ValueError("Invalid original receiver row")
            original_payloads.append(int(parts[1]))

    new_payloads = [
        int(r["payload_bytes"]) for r in background
    ]

    if original_payloads != new_payloads:
        raise ValueError(
            "Original/new receiver payload sequences differ"
        )

    # Flow completion records: FlowId, start, finish, FCT, RxBytes.
    short_flow_bytes = {}
    short_fct = {}

    with (directory / "bursty-short-fct.dat").open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            parts = line.split()

            if len(parts) != 5:
                raise ValueError("Unexpected short-FCT format")

            flow_id = int(parts[0])

            if flow_id in short_flow_bytes:
                raise ValueError("Duplicate short-flow ID")

            short_flow_bytes[flow_id] = int(parts[4])
            short_fct[flow_id] = float(parts[3])

    if len(short_flow_bytes) != 24:
        raise ValueError(
            f"Expected 24 completed short flows, "
            f"found {len(short_flow_bytes)}"
        )

    # Verify the actual per-flow receiver trace against FCT totals.
    received_per_flow = defaultdict(int)

    with (directory / "bursty-short-flow-rx.dat").open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            parts = line.split()

            if len(parts) < 3:
                raise ValueError("Invalid short-flow receiver row")

            flow_id = int(parts[1])
            payload = int(parts[2])
            received_per_flow[flow_id] += payload

    if dict(received_per_flow) != short_flow_bytes:
        raise ValueError(
            "Short-flow receiver bytes do not match FCT records"
        )

    short_bytes = sum(short_flow_bytes.values())
    background_bytes = sum(sender_totals.values())

    mbps = lambda byte_count: byte_count * 8 / duration / 1e6

    runwide_fairness = jain(
        sender_totals[1],
        sender_totals[2]
    )

    session_results = []

    for session in range(9):
        b1 = sessions[(session, 1)]
        b2 = sessions[(session, 2)]

        start1, stop1 = windows[(session, 1)]
        start2, stop2 = windows[(session, 2)]

        if abs(start1-start2) > 1e-9 or abs(stop1-stop2) > 1e-9:
            raise ValueError("Background windows are not paired")

        active_duration = stop1 - start1

        session_results.append({
            "session": session,
            "start_s": start1,
            "stop_s": stop1,
            "scheduled_duration_s": active_duration,
            "sender1_bytes": b1,
            "sender2_bytes": b2,
            "sender1_normalized_mbps": mbps(b1) * duration / active_duration,
            "sender2_normalized_mbps": mbps(b2) * duration / active_duration,
            "jain_fairness": jain(b1, b2),
        })

    result = {
        "observation_duration_s": duration,
        "completed_short_flows": len(short_flow_bytes),
        "short_received_bytes": short_bytes,
        "background1_received_bytes": sender_totals[1],
        "background2_received_bytes": sender_totals[2],
        "total_received_bytes": short_bytes + background_bytes,
        "short_goodput_mbps": mbps(short_bytes),
        "background1_goodput_mbps": mbps(sender_totals[1]),
        "background2_goodput_mbps": mbps(sender_totals[2]),
        "aggregate_goodput_mbps": mbps(
            short_bytes + background_bytes
        ),
        "background_runwide_jain": runwide_fairness,
        "receiver_reconciliation": "PASS",
        "session_port_mapping": "Port creation order, verified for reference run",
    }

    return result, session_results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(".")
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=5.0
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("research_v2_metrics")
    )

    args = parser.parse_args()

    if args.duration <= 0:
        raise ValueError("Duration must be positive")

    args.output.mkdir(parents=True, exist_ok=True)

    summary, sessions = analyze(
        args.input,
        args.duration
    )

    with (args.output / "goodput_fairness_summary.json").open("w") as f:
        json.dump(summary, f, indent=2)

    with (args.output / "goodput_fairness_summary.csv").open(
        "w", newline=""
    ) as f:
        writer = csv.DictWriter(
            f, fieldnames=list(summary)
        )
        writer.writeheader()
        writer.writerow(summary)

    with (args.output / "background_session_fairness.csv").open(
        "w", newline=""
    ) as f:
        writer = csv.DictWriter(
            f, fieldnames=list(sessions[0])
        )
        writer.writeheader()
        writer.writerows(sessions)

    print("========== GOODPUT / FAIRNESS ==========")

    for key, value in summary.items():
        print(f"{key}: {value}")

    print()
    print("PASS: Original/new background receiver reconciliation")
    print("PASS: Short-flow receiver/FCT byte reconciliation")
    print("PASS: Per-sender cumulative accounting")
    print("PASS: Nine paired background sessions")

    print()
    print("Output:", args.output.resolve())


if __name__ == "__main__":
    main()
