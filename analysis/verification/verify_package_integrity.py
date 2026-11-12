#!/usr/bin/env python3
"""Verify all files extracted from the research reproducibility ZIP."""

from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import os
import sys


MANIFEST_NAME = "MANIFEST_SHA256.json"
FORMAT = "Delay_Aware_Predictive_ECN_SHA256_v1"


def fail(message):
    raise ValueError(message)


def hash_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_relative(value):
    if not isinstance(value, str) or not value:
        fail("Empty or invalid manifest path")

    if "\\" in value:
        fail(f"Backslash in manifest path: {value}")

    path = PurePosixPath(value)

    if (
        path.is_absolute()
        or ".." in path.parts
        or "." in path.parts
        or str(path) != value
    ):
        fail(f"Unsafe or noncanonical manifest path: {value}")

    if value == MANIFEST_NAME:
        fail("Manifest must not list itself")

    return path


def verify(root, allow_extra=False):
    if not root.is_dir() or root.is_symlink():
        fail(f"Invalid package root: {root}")

    root = root.resolve()
    manifest_file = root / MANIFEST_NAME

    if not manifest_file.is_file() or manifest_file.is_symlink():
        fail(f"Missing or linked manifest: {manifest_file}")

    manifest = json.loads(manifest_file.read_text())

    if manifest.get("format") != FORMAT:
        fail("Unsupported manifest format")

    records = manifest.get("files")

    if not isinstance(records, list) or not records:
        fail("Manifest must contain a nonempty file list")

    if manifest.get("total_files") != len(records):
        fail("Manifest file count mismatch")

    declared_bytes = manifest.get("total_size_bytes")

    if type(declared_bytes) is not int or declared_bytes < 0:
        fail("Invalid declared total size")

    seen = set()
    total_bytes = 0

    for record in records:
        if not isinstance(record, dict):
            fail("Invalid file record")

        relative = safe_relative(record.get("path"))
        name = str(relative)

        if name in seen:
            fail(f"Duplicate manifest path: {name}")

        seen.add(name)

        size = record.get("size_bytes")
        expected_hash = record.get("sha256")

        if type(size) is not int or size < 0:
            fail(f"Invalid file size: {name}")

        if (
            not isinstance(expected_hash, str)
            or len(expected_hash) != 64
            or any(c not in "0123456789abcdef"
                   for c in expected_hash)
        ):
            fail(f"Invalid SHA-256: {name}")

        total_bytes += size

    if total_bytes != declared_bytes:
        fail("Manifest total byte count mismatch")

    print("========== PACKAGE SHA-256 VERIFICATION ==========")
    print("Root:", root)
    print("Files expected:", len(records))
    print("Bytes expected:", total_bytes)
    print(flush=True)

    # Verify the directory structure before opening any payload.
    for current, directories, filenames in os.walk(
        root, followlinks=False
    ):
        current = Path(current)

        for name in directories:
            entry = current / name
            if entry.is_symlink():
                fail(f"Symbolic-link directory: {entry}")

        for name in filenames:
            entry = current / name
            if entry.is_symlink() or not entry.is_file():
                fail(f"Unsafe file entry: {entry}")

            relative = entry.relative_to(root).as_posix()

            if (
                relative != MANIFEST_NAME
                and relative not in seen
                and not allow_extra
            ):
                fail(f"Unexpected package file: {relative}")

    checked_bytes = 0

    for index, record in enumerate(records, 1):
        relative = safe_relative(record["path"])
        path = root.joinpath(*relative.parts)

        # Reject symlinks in every component.
        current = root

        for component in relative.parts:
            current = current / component
            if current.is_symlink():
                fail(f"Symbolic-link path: {relative}")

        if not path.is_file():
            fail(f"Missing file: {relative}")

        actual_size = path.stat().st_size

        if actual_size != record["size_bytes"]:
            fail(
                f"Size mismatch: {relative}: "
                f"{actual_size} != {record['size_bytes']}"
            )

        actual_hash = hash_file(path)

        if actual_hash != record["sha256"]:
            fail(f"SHA-256 mismatch: {relative}")

        checked_bytes += actual_size

        if index % 250 == 0 or index == len(records):
            print(
                f"Verified {index}/{len(records)} files; "
                f"{checked_bytes / 1024**3:.3f} GiB",
                flush=True
            )

    print("\nPASS: Every archived file matches its SHA-256")
    print("PASS: All expected files present")
    print("PASS: No unsafe paths or unexpected files")
    print("PASS: Total bytes verified:", checked_bytes)


def main():
    parser = argparse.ArgumentParser(
        description="Verify an extracted research archive."
    )
    parser.add_argument(
        "--package-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Extracted package root",
    )
    parser.add_argument(
        "--allow-extra",
        action="store_true",
        help="Permit files created after extraction",
    )

    args = parser.parse_args()

    try:
        verify(args.package_root, args.allow_extra)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("FAIL:", exc, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
