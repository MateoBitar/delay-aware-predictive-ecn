from pathlib import Path
import csv
import numpy as np
import pandas as pd

ROOT = Path("research_horizon_study/closed_loop_test")
OUT = Path("research_horizon_study/mechanism_analysis")
OUT.mkdir(parents=True, exist_ok=True)

CONTROLLERS = [
    "baseline", "lower_fixed", "trend",
    "ml_2ms", "ml_5ms", "ml_20ms"
]

def read_numeric(path):
    return np.atleast_2d(np.loadtxt(path, comments="#"))

def manifest_bursts(path):
    with path.open(newline="") as f:
        records = list(csv.DictReader(f))

    bursts = {}
    for r in records:
        if r["record_type"] != "background":
            continue

        burst_id = int(r["id"])
        sender = int(r["sender"])
        start = float(r["start_s"])
        stop = float(r["stop_s"])

        if burst_id not in bursts:
            bursts[burst_id] = {
                "start": start,
                "stop": stop,
                "senders": set()
            }
        else:
            assert abs(bursts[burst_id]["start"] - start) < 1e-8
            assert abs(bursts[burst_id]["stop"] - stop) < 1e-8

        bursts[burst_id]["senders"].add(sender)

    assert len(bursts) == 9
    assert all(v["senders"] == {1, 2} for v in bursts.values())
    return bursts

def read_ecn(path):
    times = []
    with path.open() as f:
        for line in f:
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split()
            times.append(float(parts[0]))
    return np.asarray(times, dtype=float)

def read_cwnd_decreases(path):
    events = []
    with path.open() as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue

            parts = line.split()
            if len(parts) < 5 or parts[2] != "BG_CWND":
                continue

            old, new = float(parts[3]), float(parts[4])
            if old > 0 and new < old:
                events.append({
                    "time": float(parts[0]),
                    "session": parts[1],
                    "old": old,
                    "new": new
                })
    return events

def read_ecn_received(path):
    events = []
    with path.open() as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 6 and parts[2] == "BG_ECN_STATE":
                if (
                    "ECN_IDLE" in parts[3] and
                    "ECN_ECE_RCVD" in parts[5]
                ):
                    events.append({
                        "time": float(parts[0]),
                        "session": parts[1]
                    })
    return events

def read_actions(path):
    array = read_numeric(path)
    # A header-only file yields an empty array with an
    # implementation-dependent shape.
    if array.size == 0:
        return []
    return [
        {"time": float(r[0]), "active": int(r[1]) == 1}
        for r in array
    ]

def first_event(times, start, stop):
    matches = [t for t in times if start <= t < stop]
    return min(matches) if matches else np.nan

records = []

for seed in range(224, 230):
    reference_bursts = None

    for controller in CONTROLLERS:
        folder = ROOT / f"seed_{seed}" / controller

        bursts = manifest_bursts(
            folder / "bursty-workload-manifest.csv"
        )

        if reference_bursts is None:
            reference_bursts = bursts
        else:
            assert bursts == reference_bursts, (
                f"Manifest mismatch: {seed}, {controller}"
            )

        q = read_numeric(folder / "bursty-queue.dat")
        ecn = read_ecn(folder / "bursty-ecn.dat")
        cwnd = read_cwnd_decreases(
            folder / "bursty-cc-response.dat"
        )
        received = read_ecn_received(
            folder / "bursty-sender.dat"
        )
        actions = read_actions(
            folder / "bursty-controller-actions.dat"
        )

        for burst_id, burst in sorted(bursts.items()):
            start = burst["start"]
            stop = burst["stop"]

            queue_mask = (q[:, 0] >= start) & (q[:, 0] < stop)
            queue_window = q[queue_mask]

            assert len(queue_window) > 0

            # Match CWND and sender ECN events to the two
            # background TCP sessions for this burst.
            session_names = {
                f"S1_{burst_id}",
                f"S2_{burst_id}"
            }

            cwnd_times = [
                e["time"] for e in cwnd
                if e["session"] in session_names
            ]
            recv_times = [
                e["time"] for e in received
                if e["session"] in session_names
            ]

            first_mark = first_event(ecn, start, stop)
            first_cwnd = first_event(cwnd_times, start, stop)
            first_recv = first_event(recv_times, start, stop)

            # Determine controller state at burst start and
            # identify the first activation during this burst.
            prior_actions = [
                a for a in actions if a["time"] <= start
            ]
            active_at_start = (
                prior_actions[-1]["active"]
                if prior_actions else False
            )

            activations = [
                a["time"] for a in actions
                if a["active"] and start <= a["time"] < stop
            ]

            if active_at_start:
                first_activation = start
            elif activations:
                first_activation = min(activations)
            else:
                first_activation = np.nan

            def relative_ms(value):
                return (
                    (value - start) * 1000
                    if np.isfinite(value) else np.nan
                )

            records.append({
                "seed": seed,
                "controller": controller,
                "burst_id": burst_id,
                "burst_type": (
                    "long_initial" if burst_id == 0
                    else "short"
                ),
                "burst_start_s": start,
                "burst_stop_s": stop,
                "burst_duration_ms": (stop - start) * 1000,
                "active_at_start": int(active_at_start),
                "first_activation_ms": relative_ms(first_activation),
                "first_ecn_mark_ms": relative_ms(first_mark),
                "first_sender_ecn_ms": relative_ms(first_recv),
                "first_cwnd_reduction_ms": relative_ms(first_cwnd),
                "peak_queue_packets": float(queue_window[:, 1].max()),
                "mean_queue_packets": float(queue_window[:, 1].mean()),
                "ecn_marks": int(
                    np.sum((ecn >= start) & (ecn < stop))
                ),
                "cwnd_decrease_events": len([
                    t for t in cwnd_times if start <= t < stop
                ])
            })

events = pd.DataFrame(records)

assert len(events) == 6 * 6 * 9
assert events.groupby(["seed", "controller"]).size().eq(9).all()

events.to_csv(OUT / "burst_event_metrics.csv", index=False)

print("\n========== EVENT EXTRACTION ==========")
print("Controller-burst observations:", len(events))
print("Expected:", 324)

print("\n========== SHORT-BURST TIMELINE ==========")

short = events[events.burst_type == "short"]

summary = short.groupby("controller").agg(
    burst_observations=("burst_id", "count"),
    activation_ms=("first_activation_ms", "mean"),
    first_mark_ms=("first_ecn_mark_ms", "mean"),
    sender_ecn_ms=("first_sender_ecn_ms", "mean"),
    cwnd_reduction_ms=("first_cwnd_reduction_ms", "mean"),
    peak_queue=("peak_queue_packets", "mean"),
    ecn_marks=("ecn_marks", "mean")
)

summary = summary.reindex(CONTROLLERS)
summary.to_csv(OUT / "short_burst_summary.csv")

print(summary.round(3).to_string())

print("\n========== OBSERVATION COVERAGE ==========")

for controller in CONTROLLERS:
    subset = short[short.controller == controller]
    print(
        f"{controller:12} | "
        f"mark={subset.first_ecn_mark_ms.notna().sum()}/48 | "
        f"senderECN={subset.first_sender_ecn_ms.notna().sum()}/48 | "
        f"CWND={subset.first_cwnd_reduction_ms.notna().sum()}/48 | "
        f"activation={subset.first_activation_ms.notna().sum()}/48"
    )

print("\n========== PER-SEED AGGREGATES ==========")

per_seed = short.groupby(["seed", "controller"]).agg(
    mean_peak_queue=("peak_queue_packets", "mean"),
    mean_marks=("ecn_marks", "mean"),
    mean_first_mark_ms=("first_ecn_mark_ms", "mean"),
    mean_first_cwnd_ms=("first_cwnd_reduction_ms", "mean")
).reset_index()

per_seed.to_csv(OUT / "per_seed_mechanisms.csv", index=False)

print("Saved:")
print(" ", OUT / "burst_event_metrics.csv")
print(" ", OUT / "short_burst_summary.csv")
print(" ", OUT / "per_seed_mechanisms.csv")
