#!/usr/bin/env python3
"""Read-only size attribution for the exact v1.0.0 research ZIP (stdlib only)."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import zipfile

EXPECTED = "b26bfb7bcb26702ef88a6d29e3515e48d188988e31db7ad8edd243712304194c"

def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def new_stats():
    return {"files": 0, "expanded_bytes": 0, "zip_data_bytes": 0}

def add(table, key, info):
    row = table[key]
    row["files"] += 1
    row["expanded_bytes"] += info.file_size
    row["zip_data_bytes"] += info.compress_size

def display(title, table, limit=25):
    print("\n" + title)
    print(f"{'Group':55} {'Files':>7} {'Expanded MiB':>14} {'ZIP data MiB':>14}")
    for name, row in sorted(table.items(), key=lambda e: e[1]["zip_data_bytes"], reverse=True)[:limit]:
        print(f"{name[:55]:55} {row['files']:7,d} {row['expanded_bytes']/2**20:14,.2f} {row['zip_data_bytes']/2**20:14,.2f}")

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive", type=Path)
    p.add_argument("--json", type=Path, help="Write size audit to a JSON file")
    args = p.parse_args()
    path = args.archive.expanduser().resolve()
    if not path.is_file():
        p.error(f"Archive not found: {path}")
    digest = sha256(path)
    print("Archive SHA-256:", digest)
    if digest != EXPECTED:
        p.error("STOP: does not match the published v1.0.0 ZIP checksum")
    tables = {key: defaultdict(new_stats) for key in ("top", "subdir", "extension", "method")}
    largest, candidate_keys, encrypted = [], defaultdict(int), 0
    with zipfile.ZipFile(path) as z:
        entries = [item for item in z.infolist() if not item.is_dir()]
        for info in entries:
            parts = info.filename.split("/")
            add(tables["top"], parts[0], info)
            add(tables["subdir"], "/".join(parts[:2]) if len(parts) > 1 else "(root)", info)
            add(tables["extension"], Path(info.filename).suffix.lower() or "(no extension)", info)
            add(tables["method"], str(info.compress_type), info)
            largest.append((info.compress_size, info.file_size, info.filename))
            if info.file_size:
                candidate_keys[(info.file_size, info.CRC)] += 1
            encrypted += bool(info.flag_bits & 1)
    for key, title in (("top", "Top-level folders"), ("subdir", "Second-level paths"),
                       ("extension", "File extensions"), ("method", "ZIP methods (0=stored, 8=deflate, 14=LZMA)")):
        display(title, tables[key])
    print("\nLargest members (ZIP MiB / expanded MiB)")
    for compressed, expanded, name in sorted(largest, reverse=True)[:25]:
        print(f"{compressed/2**20:9.2f} / {expanded/2**20:9.2f}  {name}")
    compressed_total = sum(row["zip_data_bytes"] for row in tables["top"].values())
    expanded_total = sum(row["expanded_bytes"] for row in tables["top"].values())
    candidates = sum(n > 1 for n in candidate_keys.values())
    print("\nZIP bytes:", path.stat().st_size)
    print("Compressed member bytes:", compressed_total)
    print("Expanded member bytes:", expanded_total)
    print("Number of file members:", len(entries))
    print("Encrypted file members:", encrypted)
    print("Same size/CRC candidate groups (NOT proven duplicates):", candidates)
    print("PASS: read-only audit; archive SHA-256 matched")
    if args.json:
        payload = {"archive_sha256": digest, "archive_bytes": path.stat().st_size,
                   "member_count": len(entries), "compressed_member_bytes": compressed_total,
                   "expanded_member_bytes": expanded_total, "encrypted_members": encrypted,
                   "same_size_crc_candidates": candidates,
                   **{key: dict(rows) for key, rows in tables.items()},
                   "largest_members": [
                       {"path": name, "compressed_bytes": compressed, "expanded_bytes": expanded}
                       for compressed, expanded, name in sorted(largest, reverse=True)[:50]
                   ]}
        args.json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print("JSON report:", args.json)

if __name__ == "__main__":
    main()
