"""Orchestrate EcoSentinel without changing existing zone implementations.

Run from repository root:
  python -m orchestration.pipeline --plan
  python -m orchestration.pipeline --run
  python -m orchestration.pipeline --plan --with-acquisition
  python -m orchestration.pipeline --run --from-stage exploitation

A real run is always explicit. Acquisition from external APIs is opt-in.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import signal
import threading
import uuid
from dataclasses import dataclass
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STAGES = ('storage', 'landing', 'formatted', 'trusted', 'exploitation', 'verification')
SPACES = ('images', 'text', 'audio', 'image_text', 'audio_text')


@dataclass(frozen=True)
class Step:
    stage: str
    name: str
    target: str
    arguments: tuple[str, ...] = ()
    module: bool = False

    def argv(self, executable: str = sys.executable) -> list[str]:
        return ([executable, '-m', self.target, *self.arguments] if self.module
                else [executable, self.target, *self.arguments])


def build_plan(*, with_acquisition: bool = False, device: str = 'cpu',
               from_stage: str = 'storage', through_stage: str = 'verification') -> list[Step]:
    """Build a deterministic plan; no file I/O, model imports, or network access."""
    if from_stage not in STAGES or through_stage not in STAGES:
        raise ValueError('Unknown stage')
    if STAGES.index(from_stage) > STAGES.index(through_stage):
        raise ValueError('--from-stage must come before --through-stage')
    if device not in ('cpu', 'cuda', 'auto'):
        raise ValueError('Unknown device')
    if with_acquisition and not (STAGES.index(from_stage) <= 1 <= STAGES.index(through_stage)):
        raise ValueError('--with-acquisition requires including the landing stage')

    steps = [
        Step('storage', 'minio-connection', 'orchestration/check_minio_connection.py'),
        Step('storage', 'initialize-buckets', 'orchestration/initialize_storage.py'),
    ]
    if with_acquisition:
        steps.extend([
            Step('landing', 'download-images', 'landing_zone/data_acquisition/download_wikimedia_images.py'),
            Step('landing', 'download-audio', 'landing_zone/data_acquisition/download_xeno_canto_audio.py'),
            Step('landing', 'download-texts', 'landing_zone/data_acquisition/download_species_texts.py'),
        ])
    steps.extend([
        Step('landing', 'temporal-ingest', 'landing_zone/temporal_landing/ingest_local_data.py'),
        Step('landing', 'persistent-promote', 'landing_zone/persistent_landing/process_to_persistent.py'),
        Step('formatted', 'format-images', 'formatted_zone/format_images.py'),
        Step('formatted', 'format-audio', 'formatted_zone/format_audio.py'),
        Step('formatted', 'format-text', 'formatted_zone/format_text.py'),
        Step('trusted', 'validate-images', 'trusted_zone/validate_images.py'),
        Step('trusted', 'validate-audio', 'trusted_zone/validate_audio.py'),
        Step('trusted', 'validate-text', 'trusted_zone/validate_text.py'),
    ])
    steps.extend(Step('exploitation', f'index-{space}', 'exploitation_zone.indexer',
                      ('--space', space, '--device', device), module=True)
                 for space in SPACES)
    steps.append(Step('verification', 'reconcile', 'orchestration.reconcile', module=True))
    return [step for step in steps if STAGES.index(from_stage) <= STAGES.index(step.stage) <= STAGES.index(through_stage)]


def validate_targets(root: Path, steps: Sequence[Step]) -> None:
    """Refuse to run if a script/package required by the plan is absent."""
    for step in steps:
        target = (step.target.replace('.', '/') + '.py') if step.module else step.target
        if not (root / target).is_file():
            raise FileNotFoundError(f'Missing step entry point: {root / target}')


def print_plan(steps: Sequence[Step]) -> None:
    print(f'EcoSentinel plan: {len(steps)} steps; NO stages executed')
    for index, step in enumerate(steps, 1):
        command = ' '.join(['python', '-m'] + [step.target, *step.arguments]) if step.module else ' '.join(['python', step.target, *step.arguments])
        print(f'  {index:02d}. [{step.stage:12}] {step.name:20} {command}')
    print('External downloads occur only with --with-acquisition.')
    print('Execute explicitly with --run; results are persisted by their respective zones.')


def _atomic_json_write(path: Path, obj: dict) -> None:
    """Persist an audit report atomically without replacing any older run report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    try:
        tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _run_process(argv: Sequence[str], root: Path, output_path: Path) -> int:
    """Run in an isolated process, tee output live to screen and a per-step log."""
    proc = None
    timer = None
    expired = threading.Event()
    timeout = float(os.getenv('ECOSENTINEL_STEP_TIMEOUT', '3600'))
    if timeout <= 0:
        raise ValueError('Step timeout must be positive')
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1',
           'PYTHONUNBUFFERED': '1', 'HF_HUB_OFFLINE': os.getenv('HF_HUB_OFFLINE', '1'),
           'TRANSFORMERS_OFFLINE': os.getenv('TRANSFORMERS_OFFLINE', '1')}
    try:
        with output_path.open('w', encoding='utf-8') as logfile:
            proc = subprocess.Popen(list(argv), cwd=str(root), stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                                    errors='replace', bufsize=1, env=env,
                                    start_new_session=os.name != 'nt',
                                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0)
            def stop_on_timeout():
                expired.set()
                _stop_process(proc)
            timer = threading.Timer(timeout, stop_on_timeout)
            timer.daemon = True
            timer.start()
            assert proc.stdout is not None
            secrets = [value for key, value in env.items()
                       if any(word in key.upper() for word in ('PASSWORD', 'SECRET', 'TOKEN', 'API_KEY', 'WEBHOOK')) and len(value) >= 6]
            try:
                from dotenv import dotenv_values
                secrets += [value for key, value in dotenv_values(root / '.env').items()
                            if value and len(value) >= 6 and any(word in key.upper() for word in ('PASSWORD', 'SECRET', 'TOKEN', 'API_KEY', 'WEBHOOK'))]
            except ImportError:
                pass
            for line in proc.stdout:
                for value in secrets:
                    line = line.replace(value, '[REDACTED]')
                print(line, end='', flush=True)
                logfile.write(line)
                logfile.flush()
            code = proc.wait()
            if expired.is_set():
                raise TimeoutError(f'Step exceeded {timeout:g} seconds')
            return code
    except BaseException:
        if proc is not None and proc.poll() is None:
            _stop_process(proc)
        raise
    finally:
        if timer is not None:
            timer.cancel()
        if proc is not None and proc.stdout is not None:
            proc.stdout.close()


def _stop_process(proc):
    """End an owned process tree, including decoder children, on both platforms."""
    if proc.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


@contextmanager
def _exclusive_run_lock(folder: Path):
    """Process-level nonblocking file lock, automatically released on exit/crash.

    OS locks, unlike exclusive-file creation, do not leave permanent stale locks.
    """
    lock_path = folder / '.pipeline.lock'
    with lock_path.open('a+b') as stream:
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError(f'Another EcoSentinel pipeline may already be running ({lock_path})') from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def run_pipeline(steps: Sequence[Step], *, root: Path = PROJECT_ROOT,
                 report_dir: Path | None = None,
                 runner: Callable[[Sequence[str], Path, Path], int] = _run_process,
                 executable: str = sys.executable) -> tuple[int, Path]:
    """Fail-fast pipeline with an exclusive OS lock to prevent concurrent writes."""
    root = Path(root).resolve()
    if not steps:
        raise ValueError('No steps selected')
    validate_targets(root, steps)
    folder = Path(report_dir) if report_dir is not None else root / 'reports' / 'orchestration'
    folder = folder if folder.is_absolute() else root / folder
    folder.mkdir(parents=True, exist_ok=True)
    # Resource lock is independent of where the user sends logs.
    lock_folder = root / 'reports' / 'orchestration'
    lock_folder.mkdir(parents=True, exist_ok=True)
    with _exclusive_run_lock(lock_folder):
        return _run_pipeline_impl(steps, root=root, report_dir=folder,
                                  runner=runner, executable=executable)


def _run_pipeline_impl(steps: Sequence[Step], *, root: Path = PROJECT_ROOT,
                 report_dir: Path | None = None,
                 runner: Callable[[Sequence[str], Path, Path], int] = _run_process,
                 executable: str = sys.executable) -> tuple[int, Path]:
    """Sequential fail-fast execution with a JSON audit trail written after every step.

    The runner is injectable for offline tests; no MinIO/ML dependency in this module.
    """
    root = Path(root).resolve()
    if not steps:
        raise ValueError('No steps selected')
    validate_targets(root, steps)
    folder = Path(report_dir) if report_dir is not None else root / 'reports' / 'orchestration'
    folder = folder if folder.is_absolute() else root / folder
    folder.mkdir(parents=True, exist_ok=True)
    # One run report per execution; never overwrite previous report.
    identifier = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ') + '_' + uuid.uuid4().hex[:8]
    report_file = folder / f'pipeline_{identifier}.json'
    report: dict = {
        'schema_version': 1, 'started_at_utc': datetime.now(timezone.utc).isoformat(),
        'finished_at_utc': None, 'status': 'running',
        'python': executable, 'root': str(root),
        'steps': [{'stage': s.stage, 'name': s.name, 'status': 'pending',
                   'argv': s.argv(executable)} for s in steps],
    }
    _atomic_json_write(report_file, report)
    final_exit_code = 0
    try:
        for number, step in enumerate(steps, 1):
            entry = report['steps'][number - 1]
            entry['status'] = 'running'
            entry['started_at_utc'] = datetime.now(timezone.utc).isoformat()
            entry['log'] = f'{report_file.stem}_{number:02d}_{step.name}.log'
            _atomic_json_write(report_file, report)
            print(f'\n[{number}/{len(steps)}] {step.stage} / {step.name}', flush=True)
            start = time.perf_counter()
            try:
                code = runner(step.argv(executable), root, folder / entry['log'])
                if not isinstance(code, int):
                    raise TypeError('Process runner must return integer exit status')
                entry['returncode'] = code
                entry['status'] = 'success' if code == 0 else 'failed'
                if code != 0:
                    final_exit_code = code if code > 0 else 1
            except KeyboardInterrupt:
                entry['status'] = 'interrupted'
                entry['returncode'] = 130
                final_exit_code = 130
                raise
            except Exception as exc:
                entry['status'] = 'failed'
                entry['error'] = f'{type(exc).__name__}: {exc}'
                final_exit_code = 1
            finally:
                entry['duration_seconds'] = round(time.perf_counter() - start, 3)
                entry['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
                _atomic_json_write(report_file, report)
            if final_exit_code:
                print(f'ERROR: stopped at {step.name} (see {report_file})', flush=True)
                break
    except KeyboardInterrupt:
        print('Interrupted; no subsequent step was started.', flush=True)
    finally:
        for entry in report['steps']:
            if entry['status'] == 'pending':
                entry['status'] = 'skipped'
        report['status'] = 'completed' if final_exit_code == 0 else ('interrupted' if final_exit_code == 130 else 'failed')
        report['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        _atomic_json_write(report_file, report)
        print(f'\nPipeline status: {report["status"]}\nAudit report: {report_file}', flush=True)
    return final_exit_code, report_file


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--plan', action='store_true', help='Print commands without doing I/O or modifying anything')
    mode.add_argument('--run', action='store_true', help='Execute the planned stages, fail-fast')
    parser.add_argument('--with-acquisition', action='store_true', help='Opt in to external data downloads (requires API credentials)')
    parser.add_argument('--from-stage', choices=STAGES, default='storage')
    parser.add_argument('--through-stage', choices=STAGES, default='verification')
    parser.add_argument('--device', choices=('cpu', 'cuda', 'auto'), default='cpu')
    parser.add_argument('--report-dir', type=Path, help='Directory for JSON audit reports and per-step logs')
    args = parser.parse_args(argv)
    try:
        plan = build_plan(with_acquisition=args.with_acquisition, device=args.device,
                          from_stage=args.from_stage, through_stage=args.through_stage)
    except ValueError as exc:
        parser.error(str(exc))
    if args.plan:
        print_plan(plan)
        return 0
    exit_code, _ = run_pipeline(plan, report_dir=args.report_dir)
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
