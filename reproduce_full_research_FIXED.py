#!/usr/bin/env python3
"""Reproduce all 360 accepted ns-3.47 experiments from the researcher-ready ZIP.

FIXED: RED source digest is checked against the authenticated ZIP manifest.

Standalone standard-library orchestrator; original metrics require NumPy,
ns-3 builds require CMake/Ninja/C++ and Python. No accepted files are written.

Invocation:
  python3 reproduce_full_research.py \
    --zip ~/Downloads/Delay_Aware_Predictive_ECN_RESEARCHER_READY.zip \
    --workspace ~/ecn-independent-reproduction

The final report only claims a full PASS after all 360 independently executed
simulations, matching archived traces and accepted metrics, and the external
analysis verifier have completed successfully.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import importlib
import importlib.util
import json
import math
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import shlex
import stat
import subprocess
import sys
import tempfile
import time
import traceback
import zipfile

# Never let imported archived Python modules create __pycache__ inside the package.
sys.dont_write_bytecode = True

ARCHIVE_NAME = 'Delay_Aware_Predictive_ECN_RESEARCHER_READY.zip'
EXPECTED_ZIP_SHA256 = 'b26bfb7bcb26702ef88a6d29e3515e48d188988e31db7ad8edd243712304194c'
EXPECTED_FILES = 11010
EXPECTED_RUNS = {'original': 180, 'external': 180}
MODELS = {
    'predictor_2ms.model': '981eef1fc45c51f1f0adf3778d032bdfbbb9eedbdff14f6dbace49734356d85b',
    'predictor_5ms.model': '30372baf1843d5b9aec84bf95644a731637f5d3bcb5e8bcbd4fcd9e7555a7146',
    'predictor_20ms.model': '6df31cff964d2a4712e718c52aaae7cd9ee5c3a84bc2a8219be9dc9118640caf',
}
SOURCE_HASHES = {
    'original': '88808776304afbd77766cf0f870f8220eb86464388065b6188af47157163dea4',
    'external': '80f507d3fdd9fb4519c0dc772f91b6387bc9716c7323c0fe16c9a053c5293a93',
}
ANALYSIS_HASHES = {
    'six_metrics_180_runs.csv': 'd074f1918a122ac6a617eb86985ae5b2f0b8f393cfe45e3736e46dc7f9a267f7',
    'six_metric_controller_summary.csv': '9060224d1a6c87d1afb28691a726c25370aa15f835cb7055beb1bb8fbd6cf8f6',
    'all_paired_metric_comparisons.csv': '08df8efe41fb937c2928d96b753ab0c9b4bf9cd3c488e90ec24314066d14f913',
    'controller_summary_all_metrics.csv': '4e757bd0cbedfe4615047a409a49aa2c2b9445048edadb5e553189e2dca9b98c',
}
MANIFEST_FILE = 'MANIFEST_SHA256.json'
MARKER = '.ecn_full_reproduction_workspace.json'
BUFFER = 4 * 1024 * 1024


def say(message):
    print(message, flush=True)


def ensure(test, message):
    if not test:
        raise RuntimeError(message)


def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for part in iter(lambda: f.read(BUFFER), b''):
            h.update(part)
    return h.hexdigest()


def safe_name(name):
    if not isinstance(name, str) or not name or '\\' in name or '\x00' in name:
        return False
    parsed = PurePosixPath(name)
    return (not parsed.is_absolute() and '..' not in parsed.parts
            and str(parsed) == name and not name.endswith('/'))


def json_atomic(path, value):
    path = Path(path)
    ensure(not path.is_symlink(), f'Refusing symlink: {path}')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.report-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(value, f, indent=2, sort_keys=True)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.lexists(temp):
            os.unlink(temp)


def command_run(args, *, cwd, log_file, timeout=None):
    """Run a subprocess safely, with captured output and no shell."""
    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    say(f'  Running: {" ".join(shlex.quote(str(a)) for a in args)}')
    with log_file.open('w', encoding='utf-8') as out:
        try:
            env = os.environ.copy()
            env['PYTHONDONTWRITEBYTECODE'] = '1'
            run = subprocess.run(
                [str(a) for a in args], cwd=cwd, stdout=out,
                stderr=subprocess.STDOUT, check=False, timeout=timeout, env=env,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f'Timed out; see {log_file}') from None
    if run.returncode != 0:
        tail = log_file.read_text(errors='replace').splitlines()[-25:]
        for line in tail:
            say('    ' + line[:300])
        raise RuntimeError(f'Command exited {run.returncode}; see {log_file}')


def preflight(zip_path, workspace, expected_sha):
    ensure(sys.version_info >= (3, 9), 'Requires Python 3.9 or later')
    ensure(zip_path.is_file() and not zip_path.is_symlink(), f'ZIP missing: {zip_path}')
    ensure(zip_path.resolve() != workspace.resolve(), 'ZIP and workspace paths conflict')
    for executable in ('cmake', 'ninja', 'g++'):
        ensure(shutil.which(executable), f'Missing required tool: {executable}')
    try:
        import numpy
        say(f'PASS: Python NumPy {numpy.__version__} available')
    except ImportError:
        raise RuntimeError('NumPy not installed for this Python interpreter; install python3-numpy or use a virtual environment with NumPy') from None
    ensure(shutil.disk_usage(workspace.parent).free >= 30 * 1024**3,
           'At least 30 GiB free disk space required for isolated extraction, two source copies, builds and reruns')
    say('Checking complete ZIP SHA-256...')
    actual = sha256_file(zip_path)
    ensure(actual == expected_sha, f'ZIP checksum mismatch: {actual}\nExpected: {expected_sha}')
    say(f'PASS: ZIP SHA-256 {actual}')
    return actual


def init_workspace(workspace, zip_sha, zip_path):
    # Never initialize inside or above the source ZIP directory if the source
    # resides inside that workspace: creation would obscure the original.
    ensure(not zip_path.resolve().is_relative_to(workspace.resolve()),
           'Refusing workspace that contains the source ZIP')
    marker = workspace / MARKER
    if workspace.exists() or workspace.is_symlink():
        ensure(workspace.is_dir() and not workspace.is_symlink(),
               'Existing workspace is not a regular directory')
        ensure(marker.is_file() and not marker.is_symlink(),
               f'Existing unmarked workspace refused: {workspace}')
        data = json.loads(marker.read_text())
        ensure(data.get('zip_sha256') == zip_sha and data.get('format') == 1,
               'Existing workspace belongs to a different ZIP or format')
        say(f'PASS: Resuming verified owned workspace: {workspace}')
    else:
        workspace.mkdir(parents=True, exist_ok=False)
        json_atomic(marker, {'format': 1, 'zip_sha256': zip_sha,
                             'source_zip_name': zip_path.name,
                             'created_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})
        say(f'PASS: Created new isolated workspace: {workspace}')


def load_zip_inventory(z):
    infos = z.infolist()
    names = [i.filename for i in infos]
    ensure(len(infos) == EXPECTED_FILES + 1, f'Wrong ZIP member count: {len(infos)}')
    ensure(len(names) == len(set(names)), 'ZIP contains duplicate members')
    ensure(all(safe_name(n) for n in names), 'ZIP contains unsafe path')
    for info in infos:
        mode = info.external_attr >> 16
        kind = stat.S_IFMT(mode)
        ensure(kind in (0, stat.S_IFREG), f'ZIP contains non-regular member: {info.filename}')
    manifest = json.loads(z.read(MANIFEST_FILE).decode('utf-8'))
    ensure(isinstance(manifest, dict) and len(manifest.get('files', [])) == EXPECTED_FILES,
           'Embedded manifest has unexpected structure or file count')
    items = manifest['files']
    expected = {}
    total = 0
    for item in items:
        name = item['path']
        ensure(safe_name(name) and name not in expected, f'Invalid manifest path: {name}')
        size = item['size_bytes']
        digest = item['sha256']
        ensure(type(size) is int and size >= 0 and isinstance(digest, str)
               and len(digest) == 64 and all(c in '0123456789abcdef' for c in digest),
               f'Invalid manifest metadata: {name}')
        expected[name] = item
        total += size
        ensure(z.getinfo(name).file_size == size, f'ZIP member size mismatch: {name}')
    ensure(set(names) == set(expected) | {MANIFEST_FILE}, 'ZIP/manifest inventory differs')
    ensure(manifest['total_files'] == EXPECTED_FILES and manifest['total_size_bytes'] == total,
           'Embedded manifest totals inconsistent')
    return expected


def extract_verify(zip_path, extract_root):
    say('\n[1/6] Extracting and checking all 11,010 research files...')
    extract_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        records = load_zip_inventory(z)
        for i, (name, record) in enumerate(records.items(), 1):
            destination = extract_root.joinpath(*PurePosixPath(name).parts)
            # The package tree is workspace-owned; never follow symlinks.
            ensure(not destination.is_symlink(), f'Symlink at extraction destination: {destination}')
            if destination.exists():
                ensure(destination.is_file() and destination.stat().st_size == record['size_bytes']
                       and sha256_file(destination) == record['sha256'],
                       f'Previously extracted file changed: {destination}')
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                ensure(not any(p.is_symlink() for p in destination.parents if p == extract_root or extract_root in p.parents),
                       f'Symlink in extraction parent: {destination.parent}')
                fd, temp = tempfile.mkstemp(prefix='.extract-', dir=destination.parent)
                h = hashlib.sha256()
                size = 0
                try:
                    with os.fdopen(fd, 'wb') as out, z.open(name) as inp:
                        for chunk in iter(lambda: inp.read(BUFFER), b''):
                            out.write(chunk)
                            h.update(chunk)
                            size += len(chunk)
                    ensure(size == record['size_bytes'] and h.hexdigest() == record['sha256'],
                           f'Extracted checksum mismatch: {name}')
                    os.replace(temp, destination)
                finally:
                    if os.path.lexists(temp):
                        os.unlink(temp)
            if i % 2000 == 0 or i == EXPECTED_FILES:
                say(f'  Verified {i}/{EXPECTED_FILES} files')
        # Embedded manifest is recreated from exactly the ZIP bytes.
        manifest_dest = extract_root / MANIFEST_FILE
        embedded_data = z.read(MANIFEST_FILE)
        if manifest_dest.exists():
            ensure(manifest_dest.read_bytes() == embedded_data, 'Existing embedded manifest differs')
        else:
            manifest_dest.write_bytes(embedded_data)
    say('PASS: Complete ZIP extracted and SHA-256 verified')


def case_catalog(root):
    original = root / 'simulator/ns-3.47/research_horizon_study'
    external = root / 'external_validation/external_evaluation_180'
    models_root = original / 'horizon_models'
    for name, digest in MODELS.items():
        m = models_root / name
        ensure(m.is_file() and sha256_file(m) == digest, f'Archived model mismatch: {m}')
    cases = []
    counts = collections.Counter()
    for kind, base in [('original', original), ('external', external)]:
        ensure(base.is_dir(), f'Missing campaign: {base}')
        for recorded in sorted(base.rglob('command.json')):
            folder = recorded.parent
            relative = folder.relative_to(base)
            reference = json.loads((folder / 'validated_result.json').read_text())
            command = json.loads(recorded.read_text())
            ensure(reference['controller'] == folder.name, f'Controller mismatch: {folder}')
            seed = int(folder.parent.name.split('_')[-1])
            ensure(reference['seed'] == seed, f'Accepted seed mismatch: {folder}')
            if kind == 'original':
                ensure(isinstance(command, list) and len(command) == 3 and command[:2] == ['./ns3', 'run'],
                       f'Original launcher mismatch: {folder}')
                parts = shlex.split(command[2])
                ensure(parts and parts.pop(0) == 'bursty-dctcp-baseline', f'Target mismatch: {folder}')
            else:
                ensure(isinstance(command, list) and len(command) > 1 and
                       Path(command[0]).name == 'ns3.47-bursty-dctcp-baseline-default',
                       f'External launcher mismatch: {folder}')
                parts = command[1:]
            opts = {}
            for arg in parts:
                ensure(arg.startswith('--') and '=' in arg, f'Unknown argument: {folder}: {arg}')
                key, val = arg[2:].split('=', 1)
                ensure(key not in opts, f'Duplicate argument: {folder}: {key}')
                opts[key] = val
            ensure(opts.get('RngSeed') == '1', f'RngSeed differs: {folder}')
            ensure(opts.get('RngRun') == ('101' if kind == 'original' else str(seed)),
                   f'RngRun differs: {folder}')
            ensure(('mlModelPath' in opts) == folder.name.startswith('ml_'),
                   f'ML model/controller mismatch: {folder}')
            if 'mlModelPath' in opts:
                model_name = Path(opts['mlModelPath']).name
                ensure(model_name in MODELS, f'Unexpected ML model: {folder}')
                ensure(model_name == f'predictor_{folder.name[3:]}.model', f'Model horizon mismatch: {folder}')
            if kind == 'original':
                ensure(opts.get('workloadSeed') == str(seed) and 'externalManifestPath' not in opts,
                       f'Original workload arguments differ: {folder}')
            else:
                accepted_manifest = folder / 'input_manifest.csv'
                ensure(accepted_manifest.is_file() and
                       sha256_file(accepted_manifest) == reference['manifest_sha256'],
                       f'External input manifest mismatch: {folder}')
                expected_suffix = '/external_evaluation_180/' + relative.as_posix() + '/input_manifest.csv'
                ensure(opts.get('externalManifestPath', '').endswith(expected_suffix),
                       f'External historical manifest path differs: {folder}')
            traces = sorted(p.name for p in folder.glob('bursty-*') if p.is_file())
            ensure(len(traces) >= 8 and 'bursty-short-fct.dat' in traces,
                   f'Accepted trace inventory incomplete: {folder}')
            cases.append({'kind': kind, 'relative': relative, 'reference': folder,
                          'accepted': reference, 'options': parts, 'traces': traces})
            counts[kind] += 1
    ensure(dict(counts) == EXPECTED_RUNS, f'Expected 180+180 runs, got {counts}')
    say('PASS: 360 recorded commands, original/external models, and external input manifests prevalidated')
    return cases


def copy_source_if_needed(source, destination):
    expected = SOURCE_HASHES['original']
    rel = 'examples/tcp/bursty-dctcp-baseline.cc'
    if destination.exists() or destination.is_symlink():
        ensure(destination.is_dir() and not destination.is_symlink(),
               f'Build directory malformed: {destination}')
        ensure((destination / rel).is_file() and sha256_file(destination / rel) == expected,
               f'Existing copied source changed: {destination}')
    else:
        say(f'  Copying simulator source to {destination}')
        shutil.copytree(source, destination, symlinks=False)
        ensure(sha256_file(destination / rel) == expected, 'Copied simulator source checksum mismatch')


def build_sources(root, work, jobs):
    say('\n[2/6] Clean-building original and external ns-3.47 simulators...')
    archived_ns3 = root / 'simulator/ns-3.47'
    archived_original = archived_ns3 / 'examples/tcp/bursty-dctcp-baseline.cc'
    override = root / 'simulator/external_override/bursty-dctcp-baseline.cc'
    red_relative = 'simulator/ns-3.47/src/traffic-control/model/red-queue-disc.cc'
    red = root / red_relative
    # The complete ZIP was already authenticated and its payloads checked.
    # Use that validated manifest as the source of truth, rather than an
    # incorrectly transcribed, non-64-character historical RED digest.
    embedded_manifest = json.loads((root / MANIFEST_FILE).read_text())
    red_entries = [item for item in embedded_manifest['files']
                   if item['path'] == red_relative]
    ensure(len(red_entries) == 1, 'RED source absent or duplicated in archive manifest')
    red_hash = red_entries[0]['sha256']
    ensure(len(red_hash) == 64 and sha256_file(red) == red_hash,
           'RED source does not match independently verified ZIP manifest')
    ensure(sha256_file(archived_original) == SOURCE_HASHES['original'], 'Original source hash mismatch')
    ensure(sha256_file(override) == SOURCE_HASHES['external'], 'External source hash mismatch')
    say(f'PASS: RED source verified against archived SHA-256 {red_hash}')
    builds = {}
    for kind in ('original', 'external'):
        destination = work / 'builds' / kind / 'ns-3.47'
        destination.parent.mkdir(parents=True, exist_ok=True)
        copy_source_if_needed(archived_ns3, destination) if kind == 'original' else None
        if kind == 'external':
            if destination.exists() or destination.is_symlink():
                ensure(destination.is_dir() and not destination.is_symlink() and
                       sha256_file(destination / 'examples/tcp/bursty-dctcp-baseline.cc') == SOURCE_HASHES['external'],
                       'Existing external source is invalid')
            else:
                say(f'  Copying and installing external source in {destination}')
                shutil.copytree(archived_ns3, destination, symlinks=False)
                shutil.copyfile(override, destination / 'examples/tcp/bursty-dctcp-baseline.cc')
                ensure(sha256_file(destination / 'examples/tcp/bursty-dctcp-baseline.cc') == SOURCE_HASHES['external'],
                       'External override installation failed')
        ensure(sha256_file(destination / 'src/traffic-control/model/red-queue-disc.cc') == red_hash,
               f'Copied RED source mismatch: {kind}')
        exe = destination / 'build/examples/tcp/ns3.47-bursty-dctcp-baseline-optimized'
        if not exe.is_file():
            say(f'  Configuring {kind}...')
            command_run([sys.executable, './ns3', 'configure', '--enable-examples', '--disable-tests',
                         '--build-profile=optimized', '-G', 'Ninja'],
                        cwd=destination, log_file=work / 'logs' / f'{kind}-configure.log')
            say(f'  Compiling {kind}, jobs={jobs}...')
            command_run(['ninja', '-C', 'cmake-cache', '-j', str(jobs), 'bursty-dctcp-baseline'],
                        cwd=destination, log_file=work / 'logs' / f'{kind}-build.log')
        ensure(exe.is_file(), f'Build failed to produce executable: {exe}')
        command_run([exe, '--PrintHelp'], cwd=destination,
                    log_file=work / 'logs' / f'{kind}-help.log', timeout=60)
        if kind == 'external':
            ensure('--externalManifestPath' in (work / 'logs' / 'external-help.log').read_text(),
                   'External binary lacks external manifest support')
        builds[kind] = exe
        say(f'PASS: {kind} simulator compiled and executable: {exe.name}')
    return builds


def verify_archived_traces(case, output):
    counts = 0
    for name in case['traces']:
        reference = case['reference'] / name
        reproduced = output / name
        ensure(reproduced.is_file() and not reproduced.is_symlink(),
               f'Missing new trace: {reproduced}')
        ensure(reference.stat().st_size == reproduced.stat().st_size and
               sha256_file(reference) == sha256_file(reproduced),
               f'Raw trace mismatch: {case["kind"]}/{case["relative"]}/{name}')
        counts += 1
    return counts


def load_validators(root):
    sys.path.insert(0, str(root / 'simulator/ns-3.47'))
    pilot = importlib.import_module('run_v2_pilot')
    accounting = importlib.import_module('analyze_goodput_fairness')
    script = root / 'external_validation/scripts/run_external_180.py'
    spec = importlib.util.spec_from_file_location('portable_run_external_180', script)
    ensure(spec is not None and spec.loader is not None, 'Historical external validator unavailable')
    external = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(external)
    return pilot, accounting, external


def verify_metrics(case, output, validators):
    pilot, accounting, external = validators
    expected = case['accepted']
    if case['kind'] == 'original':
        metrics = pilot.calculate_original_metrics(output)
        goodput, sessions = accounting.analyze(output, 5.0)
        ensure(goodput['receiver_reconciliation'] == 'PASS' and len(sessions) == 9,
               f'Original receiver accounting mismatch: {case["relative"]}')
        measured = {
            **metrics,
            'short_goodput_mbps': goodput['short_goodput_mbps'],
            'background1_goodput_mbps': goodput['background1_goodput_mbps'],
            'background2_goodput_mbps': goodput['background2_goodput_mbps'],
            'aggregate_goodput_mbps': goodput['aggregate_goodput_mbps'],
            'background_runwide_jain': goodput['background_runwide_jain'],
        }
    else:
        input_hash = sha256_file(output / 'input_manifest.csv')
        ensure(input_hash == expected['manifest_sha256'],
               f'External input manifest hash mismatch: {case["relative"]}')
        manifest = external.read_manifest(output / 'input_manifest.csv')
        measured = external.validate(output, manifest, expected['controller'], input_hash)
    ensure(len(measured) == 12, f'Unexpected validated scientific metric count: {len(measured)}')
    for key, value in measured.items():
        ensure(key in expected, f'Accepted metric missing: {key} {case["relative"]}')
        recorded = expected[key]
        if isinstance(value, float):
            matched = (math.isfinite(value) and math.isfinite(float(recorded))
                       and abs(value - float(recorded)) <= 1e-9)
        else:
            matched = value == recorded
        ensure(matched,
               f'ACCEPTED METRIC MISMATCH {case["kind"]}/{case["relative"]} '
               f'{key}: reproduced {value!r}, accepted {recorded!r}')
    return len(measured)


def per_run_command(case, binary, output, root):
    options = []
    for value in case['options']:
        if value.startswith('--mlModelPath='):
            name = Path(value.split('=', 1)[1]).name
            model = root / 'simulator/ns-3.47/research_horizon_study/horizon_models' / name
            ensure(sha256_file(model) == MODELS[name], 'Model modified')
            options.append(f'--mlModelPath={model}')
        elif value.startswith('--externalManifestPath='):
            source = case['reference'] / 'input_manifest.csv'
            dest = output / 'input_manifest.csv'
            if dest.exists():
                ensure(dest.is_file() and sha256_file(dest) == case['accepted']['manifest_sha256'],
                       f'Copied external manifest was changed: {dest}')
            else:
                shutil.copyfile(source, dest)
            ensure(sha256_file(dest) == case['accepted']['manifest_sha256'], 'External manifest copy mismatch')
            options.append(f'--externalManifestPath={dest}')
        else:
            options.append(value)
    return [str(binary), *options]


def replay_cases(cases, builds, root, workspace, max_cases, timeout):
    say('\n[3/6] Re-executing all archived experiment configurations...')
    validators = load_validators(root)
    reports = workspace / 'reports' / 'runs'
    counts = collections.Counter()
    matches = 0
    sample_total = len(cases) if max_cases is None else max_cases
    for case in cases[:sample_total]:
        kind = case['kind']
        key = f'{kind}/{case["relative"].as_posix()}'
        output = workspace / 'runs' / kind / case['relative']
        passed = reports / kind / case['relative'] / 'PASS.json'
        if output.exists() or output.is_symlink():
            ensure(output.is_dir() and not output.is_symlink(), f'Output path invalid: {output}')
            ensure(passed.is_file() and not passed.is_symlink(),
                   f'Incomplete run exists; refusing overwrite: {output}\n'
                   'Inspect its simulation.log before resetting that single disposable run.')
            old = json.loads(passed.read_text())
            ensure(old.get('status') == 'PASS' and old.get('case') == key,
                   f'Invalid previous PASS report: {passed}')
            ntraces = verify_archived_traces(case, output)
            nmetrics = verify_metrics(case, output, validators)
            ensure(old.get('trace_count') == ntraces and old.get('metric_count') == nmetrics,
                   f'Previous run report changed: {key}')
            counts['resumed_verified'] += 1
        else:
            output.mkdir(parents=True, exist_ok=False)
            command = per_run_command(case, builds[kind], output, root)
            json_atomic(output / 'reproduction_command.json', command)
            say(f'  [{sum(counts.values()) + 1}/{sample_total}] {key}')
            command_run(command, cwd=output, log_file=output / 'simulation.log', timeout=timeout)
            ntraces = verify_archived_traces(case, output)
            nmetrics = verify_metrics(case, output, validators)
            json_atomic(passed, {'status': 'PASS', 'case': key,
                                 'trace_count': ntraces, 'metric_count': nmetrics,
                                 'binary_sha256': sha256_file(builds[kind]),
                                 'accepted_files_unmodified': True})
            counts['newly_executed'] += 1
        counts[kind] += 1
        matches += ntraces
        if sum(counts[k] for k in ('original', 'external')) % 10 == 0 or sample_total < 10:
            say(f'  PASS: {counts["original"] + counts["external"]}/{sample_total} runs; '
                f'{matches} trace matches; original {counts["original"]}, external {counts["external"]}')
    result = {'run_count': sum(counts[k] for k in ('original', 'external')),
              'original': counts['original'], 'external': counts['external'],
              'previously_verified': counts['resumed_verified'],
              'newly_executed': counts['newly_executed'],
              'archived_trace_matches': matches, 'metric_checks_per_run': 12}
    json_atomic(workspace / 'reports' / 'simulation_summary.json', result)
    return result


def external_analysis(root, workspace):
    say('\n[4/6] Regenerating accepted external analysis from complete archived traces...')
    output_parent = workspace / 'analysis_outputs'
    output_parent.mkdir(parents=True, exist_ok=True)
    verified = workspace / 'reports' / 'external_analysis_pass.json'
    if verified.exists():
        data = json.loads(verified.read_text())
        ensure(data.get('status') == 'PASS' and data.get('expected_csv_hashes') == ANALYSIS_HASHES,
               'Previous external analysis report invalid')
        for name, expected_hash in ANALYSIS_HASHES.items():
            rel = data.get('generated_csv_paths', {}).get(name)
            ensure(isinstance(rel, str) and rel, f'Previous external CSV path missing: {name}')
            path = workspace / rel
            ensure(path.is_file() and not path.is_symlink() and sha256_file(path) == expected_hash,
                   f'Previously verified external analysis output changed: {path}')
        say('PASS: Previously verified external analysis outputs rechecked')
        return data
    command_run([sys.executable, str(root / 'reproduction/verify_external_analysis.py'),
                 '--external-root', 'external_validation',
                 '--output-parent', str(output_parent)],
                cwd=root, log_file=workspace / 'logs' / 'external-analysis.log')
    # The supplied portable verifier compares four new CSV results byte-for-byte
    # to accepted scientific files and fails with a nonzero exit on mismatches.
    # Independently locate newly generated CSVs and verify all four hashes.
    found = {}
    for name, digest in ANALYSIS_HASHES.items():
        candidates = [p for p in output_parent.rglob(name) if p.is_file()]
        ensure(candidates, f'External verifier did not generate {name}')
        matched = [p for p in candidates if sha256_file(p) == digest]
        ensure(matched, f'External generated CSV mismatch: {name}')
        found[name] = str(matched[0].relative_to(workspace))
    report = {'status': 'PASS', 'expected_csv_hashes': ANALYSIS_HASHES,
              'generated_csv_paths': found}
    json_atomic(verified, report)
    say('PASS: All four external scientific tables independently regenerated byte-for-byte')
    return report


def final_report(workspace, zip_sha, cases, summary, analysis, started):
    report = {
        'status': 'PASS',
        'claim': '360 fresh/existing-verified isolated run reproductions; all archived traces and run metrics matched; full external analysis regenerated',
        'archive_sha256': zip_sha,
        'archive_name': ARCHIVE_NAME,
        'experiments_expected': 360,
        'experiments_verified': summary['run_count'],
        'original_runs_verified': summary['original'],
        'external_runs_verified': summary['external'],
        'archived_trace_matches': summary['archived_trace_matches'],
        'run_metric_fields_checked': summary['run_count'] * 12,
        'external_analysis_csv_hashes': analysis['expected_csv_hashes'],
        'environment': {'platform': platform.platform(), 'python': sys.version,
                        'machine': platform.machine()},
        'elapsed_seconds': round(time.monotonic() - started, 2),
        'scientific_scope_note': 'Frozen models reused; model training is not rerun. Raw archived traces are not modified.',
    }
    json_atomic(workspace / 'FINAL_REPRODUCTION_REPORT.json', report)
    say('\n' + '=' * 68)
    say('SUCCESS: FULL 360-EXPERIMENT REPRODUCTION PASSED')
    say(f'Original accepted runs reproduced: {summary["original"]}/180')
    say(f'External accepted runs reproduced: {summary["external"]}/180')
    say(f'Preserved raw traces matched: {summary["archived_trace_matches"]}')
    say(f'Accepted per-run metric fields matched: {summary["run_count"] * 12}')
    say('Regenerated external scientific CSVs: 4/4 exact SHA-256')
    say(f'FINAL REPORT: {workspace / "FINAL_REPRODUCTION_REPORT.json"}')
    say('The source ZIP and all accepted archived data remain untouched.')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    default_zip = Path('/mnt/c/Users/Mateo/Downloads') / ARCHIVE_NAME
    if not default_zip.is_file():
        default_zip = Path.home() / 'Downloads' / ARCHIVE_NAME
    p.add_argument('--zip', type=Path, default=default_zip,
                   help='Full path to RESEARCHER_READY ZIP; Windows Downloads auto-detected on WSL')
    p.add_argument('--workspace', type=Path,
                   default=Path.home() / 'ECN_FULL_360_INDEPENDENT_REPRODUCTION',
                   help='Fresh, separate workspace; existing marked workspace can be resumed')
    p.add_argument('--jobs', type=int, default=2, help='Parallel Ninja compile jobs (default 2)')
    p.add_argument('--run-timeout', type=int, default=600, help='Per-simulation timeout seconds')
    p.add_argument('--expected-sha256', default=EXPECTED_ZIP_SHA256,
                   help='Pin exact trusted ZIP SHA-256 (default is the verified RESEARCHER_READY ZIP)')
    p.add_argument('--max-cases', type=int, default=None,
                   help='Diagnostic partial test only; never reports full PASS')
    args = p.parse_args()
    ensure(1 <= args.jobs <= 16, '--jobs must be in 1..16')
    ensure(args.run_timeout > 0, '--run-timeout must be positive')
    ensure(args.max_cases is None or 1 <= args.max_cases <= 360, '--max-cases must be 1..360')
    zip_path = args.zip.expanduser().resolve()
    work = args.workspace.expanduser().absolute()
    ensure(work != Path('/') and work != Path.home(), 'Unsafe workspace path')
    start = time.monotonic()
    say('========== INDEPENDENT FULL RESEARCH REPRODUCTION ==========')
    say(f'Archive: {zip_path}')
    say(f'Clean workspace: {work}')
    say('No existing scientific data will be changed.')
    ensure(work.parent.is_dir(), f'Workspace parent does not exist: {work.parent}')
    try:
        zip_sha = preflight(zip_path, work, args.expected_sha256)
        init_workspace(work, zip_sha, zip_path)
        root = work / 'package'
        extract_verify(zip_path, root)
        cases = case_catalog(root)
        builds = build_sources(root, work, args.jobs)
        summary = replay_cases(cases, builds, root, work, args.max_cases, args.run_timeout)
        if args.max_cases is not None:
            say('\nPARTIAL TEST COMPLETED: Not a full 360-run verification.')
            say(f'Partial summary: {work / "reports/simulation_summary.json"}')
            return 0
        ensure(summary['original'] == 180 and summary['external'] == 180,
               'Full campaign not completed')
        analysis = external_analysis(root, work)
        say('\n[5/6] Auditing final reproduction status...')
        final_report(work, zip_sha, cases, summary, analysis, start)
        say('[6/6] PASS — original ZIP never modified')
        return 0
    except Exception as exc:
        say('\nFAILED / INCOMPLETE: ' + str(exc))
        say('Accepted files and source ZIP were not intentionally modified.')
        say(f'Logs and partial run evidence, if any: {work}')
        # Do not emit a misleading final PASS report on failure.
        return 1


if __name__ == '__main__':
    sys.exit(main())
