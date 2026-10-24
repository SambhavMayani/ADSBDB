"""Offline tests: subprocess, MinIO, external APIs, Chroma, and models are all mocked."""

import json
import sys
from pathlib import Path

import pytest

from orchestration import pipeline


def s(stage='storage', name='sample', target='demo.py', arguments=(), module=False):
    return pipeline.Step(stage, name, target, tuple(arguments), module)


def fixture_tree(tmp_path, steps):
    for step in steps:
        relative = step.target.replace('.', '/') + '.py' if step.module else step.target
        file = tmp_path / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('# dummy script\n', encoding='utf-8')
    return tmp_path


def test_default_plan_has_sixteen_steps():
    assert len(pipeline.build_plan()) == 16


def test_default_does_not_download_from_internet():
    assert not any(item.name.startswith('download-') for item in pipeline.build_plan())


def test_opted_in_acquisition_has_nineteen_steps():
    assert len(pipeline.build_plan(with_acquisition=True)) == 19


def test_acquisition_runs_before_ingestion():
    names = [x.name for x in pipeline.build_plan(with_acquisition=True)]
    assert names.index('download-images') < names.index('temporal-ingest')
    assert names.index('download-audio') < names.index('temporal-ingest')
    assert names.index('download-texts') < names.index('temporal-ingest')


def test_storage_checks_before_bucket_initialization():
    assert [s.name for s in pipeline.build_plan()[:2]] == ['minio-connection', 'initialize-buckets']


def test_landing_ingest_precedes_persistent_promotion():
    names = [s.name for s in pipeline.build_plan()]
    assert names.index('temporal-ingest') < names.index('persistent-promote')


def test_formatted_precedes_trusted():
    names = [s.stage for s in pipeline.build_plan()]
    assert max(i for i, stage in enumerate(names) if stage == 'formatted') < min(
        i for i, stage in enumerate(names) if stage == 'trusted'
    )


def test_trusted_precedes_exploitation():
    names = [s.stage for s in pipeline.build_plan()]
    assert max(i for i, stage in enumerate(names) if stage == 'trusted') < min(
        i for i, stage in enumerate(names) if stage == 'exploitation'
    )


def test_five_vector_spaces_in_expected_order():
    assert [s.arguments[1] for s in pipeline.build_plan() if s.stage == 'exploitation'] == list(
        pipeline.SPACES
    )


def test_one_vector_space_per_process():
    assert all(s.module for s in pipeline.build_plan() if s.stage == 'exploitation')


def test_default_cpu():
    assert all(s.arguments[-1] == 'cpu' for s in pipeline.build_plan() if s.stage == 'exploitation')


def test_cuda_is_opt_in():
    assert all(
        s.arguments[-1] == 'cuda'
        for s in pipeline.build_plan(device='cuda')
        if s.stage == 'exploitation'
    )


def test_from_stage_exploitation_includes_final_verification():
    steps = pipeline.build_plan(from_stage='exploitation')
    assert len(steps) == 6
    assert [x.stage for x in steps] == ['exploitation'] * 5 + ['verification']


def test_from_to_formatted_trusted():
    steps = pipeline.build_plan(from_stage='formatted', through_stage='trusted')
    assert len(steps) == 6
    assert {step.stage for step in steps} == {'formatted', 'trusted'}


def test_storage_only_plan():
    assert len(pipeline.build_plan(through_stage='storage')) == 2


def test_reverse_stages_rejected():
    with pytest.raises(ValueError, match='--from-stage'):
        pipeline.build_plan(from_stage='trusted', through_stage='landing')


def test_invalid_stage_rejected():
    with pytest.raises(ValueError, match='Unknown stage'):
        pipeline.build_plan(from_stage='bogus')


def test_invalid_device_rejected():
    with pytest.raises(ValueError, match='Unknown device'):
        pipeline.build_plan(device='tpu')


def test_acquisition_requires_landing():
    with pytest.raises(ValueError, match='landing'):
        pipeline.build_plan(with_acquisition=True, from_stage='formatted')


def test_script_argv_uses_given_interpreter():
    step = s(arguments=['--dry-run'])
    assert step.argv('python.exe') == ['python.exe', 'demo.py', '--dry-run']


def test_module_argv_uses_m():
    step = s(
        'exploitation', 'index', 'exploitation_zone.indexer', ['--space', 'images'], module=True
    )
    assert step.argv('python.exe') == [
        'python.exe',
        '-m',
        'exploitation_zone.indexer',
        '--space',
        'images',
    ]


def test_validate_targets_reports_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError, match='Missing step'):
        pipeline.validate_targets(tmp_path, [s()])


def test_validate_targets_accepts_file(tmp_path):
    steps = [s()]
    fixture_tree(tmp_path, steps)
    pipeline.validate_targets(tmp_path, steps)


def test_validate_targets_accepts_module(tmp_path):
    steps = [s('exploitation', 'index', 'exploitation_zone.indexer', module=True)]
    fixture_tree(tmp_path, steps)
    pipeline.validate_targets(tmp_path, steps)


def test_print_plan_no_processes(capsys):
    pipeline.print_plan([s()])
    output = capsys.readouterr().out
    assert 'NO stages executed' in output and 'python demo.py' in output


def test_main_plan_is_offline(capsys):
    assert pipeline.main(['--plan', '--from-stage', 'exploitation']) == 0
    output = capsys.readouterr().out
    assert '6 steps' in output


def test_main_requires_explicit_plan_or_run():
    with pytest.raises(SystemExit) as exc:
        pipeline.main([])
    assert exc.value.code == 2


def test_run_rejects_empty_plan(tmp_path):
    with pytest.raises(ValueError, match='No steps'):
        pipeline.run_pipeline([], root=tmp_path)


def test_run_fails_before_writing_when_script_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        pipeline.run_pipeline([s()], root=tmp_path)
    assert not (tmp_path / 'reports').exists()


def test_run_success_creates_json_report(tmp_path):
    steps = [s(name='one'), s('landing', 'two')]
    fixture_tree(tmp_path, steps)
    commands = []

    def runner(args, root, log):
        commands.append((list(args), root, log))
        return 0

    code, report_file = pipeline.run_pipeline(
        steps, root=tmp_path, runner=runner, executable='python-test'
    )
    data = json.loads(report_file.read_text(encoding='utf-8'))
    assert code == 0 and data['status'] == 'completed'
    assert len(data['steps']) == 2
    assert all(x['status'] == 'success' for x in data['steps'])
    assert len(commands) == 2 and commands[0][0][0] == 'python-test'
    assert all(root == tmp_path for _, root, _ in commands)


def test_failure_stops_remaining_steps(tmp_path):
    steps = [s(name='one'), s(name='two'), s(name='three')]
    fixture_tree(tmp_path, steps)
    called = []

    def runner(args, root, log):
        called.append(str(log))
        return 7 if len(called) == 2 else 0

    code, path = pipeline.run_pipeline(steps, root=tmp_path, runner=runner)
    report = json.loads(path.read_text(encoding='utf-8'))
    assert code == 7
    assert len(called) == 2
    assert [x['status'] for x in report['steps']] == ['success', 'failed', 'skipped']
    assert report['status'] == 'failed'


def test_exception_stops_remaining_steps(tmp_path):
    steps = [s(name='one'), s(name='two')]
    fixture_tree(tmp_path, steps)
    calls = []

    def runner(args, root, log):
        calls.append(1)
        raise RuntimeError('storage unavailable')

    code, path = pipeline.run_pipeline(steps, root=tmp_path, runner=runner)
    report = json.loads(path.read_text(encoding='utf-8'))
    assert code == 1 and calls == [1]
    assert report['steps'][0]['error'] == 'RuntimeError: storage unavailable'
    assert report['steps'][1]['status'] == 'skipped'


def test_ctrl_c_stops_and_records_interruption(tmp_path):
    steps = [s(name='one'), s(name='two')]
    fixture_tree(tmp_path, steps)

    def runner(args, root, log):
        raise KeyboardInterrupt

    code, path = pipeline.run_pipeline(steps, root=tmp_path, runner=runner)
    report = json.loads(path.read_text(encoding='utf-8'))
    assert code == 130 and report['status'] == 'interrupted'
    assert [step['status'] for step in report['steps']] == ['interrupted', 'skipped']


def test_bad_runner_exit_type_fails(tmp_path):
    steps = [s()]
    fixture_tree(tmp_path, steps)
    code, path = pipeline.run_pipeline(steps, root=tmp_path, runner=lambda *a: None)
    assert code == 1 and json.loads(path.read_text())['steps'][0]['status'] == 'failed'


def test_logs_have_distinct_names(tmp_path):
    steps = [s(name='first'), s(name='second')]
    fixture_tree(tmp_path, steps)
    code, path = pipeline.run_pipeline(steps, root=tmp_path, runner=lambda *a: 0)
    logs = [x['log'] for x in json.loads(path.read_text())['steps']]
    assert len(set(logs)) == 2 and all(log.endswith('.log') for log in logs)


def test_reports_use_new_names_for_separate_runs(tmp_path):
    steps = [s()]
    fixture_tree(tmp_path, steps)
    _, first = pipeline.run_pipeline(steps, root=tmp_path, runner=lambda *a: 0)
    _, second = pipeline.run_pipeline(steps, root=tmp_path, runner=lambda *a: 0)
    assert first != second and first.exists() and second.exists()


def test_custom_relative_report_dir_resolves_from_root(tmp_path):
    steps = [s()]
    fixture_tree(tmp_path, steps)
    _, output = pipeline.run_pipeline(
        steps, root=tmp_path, report_dir=Path('my-reports'), runner=lambda *a: 0
    )
    assert output.parent == tmp_path / 'my-reports'


def test_atomic_json_no_tmp_after_save(tmp_path):
    target = tmp_path / 'x.json'
    pipeline._atomic_json_write(target, {'ok': True})
    assert json.loads(target.read_text()) == {'ok': True}
    assert not (tmp_path / 'x.json.tmp').exists()


def test_plan_main_with_acquisition_shows_explicit_commands(capsys):
    pipeline.main(['--plan', '--with-acquisition'])
    output = capsys.readouterr().out
    assert 'download_xeno_canto_audio.py' in output
    assert '19 steps' in output


def test_cli_reverse_stages_exits_with_usage_error():
    with pytest.raises(SystemExit) as exc:
        pipeline.main(['--plan', '--from-stage', 'trusted', '--through-stage', 'formatted'])
    assert exc.value.code == 2


def test_cli_run_calls_pipeline_with_mock(monkeypatch):
    calls = []

    def fake_run(plan, *, report_dir):
        calls.append((plan, report_dir))
        return (0, Path('some_report.json'))

    monkeypatch.setattr(pipeline, 'run_pipeline', fake_run)
    assert pipeline.main(['--run', '--from-stage', 'exploitation']) == 0
    assert len(calls) == 1 and len(calls[0][0]) == 6


def test_lock_prevents_concurrent_run(tmp_path):
    steps = [s()]
    fixture_tree(tmp_path, steps)
    output_folder = tmp_path / 'reports' / 'orchestration'
    output_folder.mkdir(parents=True)
    with pipeline._exclusive_run_lock(output_folder):
        with pytest.raises(RuntimeError, match='already be running'):
            pipeline.run_pipeline(steps, root=tmp_path, runner=lambda *a: 0)


def test_lock_released_after_exit(tmp_path):
    folder = tmp_path / 'logs'
    folder.mkdir()
    with pipeline._exclusive_run_lock(folder):
        pass
    with pipeline._exclusive_run_lock(folder):
        pass


def test_process_runner_streams_and_captures(tmp_path, capsys):
    script = tmp_path / 'sample.py'
    script.write_text("print('hello from child', flush=True)\n", encoding='utf-8')
    output = tmp_path / 'child.log'
    exit_code = pipeline._run_process([sys.executable, str(script)], tmp_path, output)
    assert exit_code == 0
    assert 'hello from child' in output.read_text(encoding='utf-8')
    assert 'hello from child' in capsys.readouterr().out


def test_process_runner_propagates_failure(tmp_path):
    script = tmp_path / 'failure.py'
    script.write_text('raise SystemExit(3)\n', encoding='utf-8')
    assert pipeline._run_process([sys.executable, str(script)], tmp_path, tmp_path / 'log.txt') == 3


def test_end_to_end_mock_pipeline_runs_all_stages_without_external_services(tmp_path):
    """Integration smoke: real subprocesses, fake scripts, no MinIO or model loading."""
    steps = pipeline.build_plan()
    fixture_tree(tmp_path, steps)
    for step in steps:
        location = step.target.replace('.', '/') + '.py' if step.module else step.target
        mock_content = (
            "import sys\nprint('MOCK index-' + sys.argv[2], flush=True)\n"
            if step.target == 'exploitation_zone.indexer'
            else f"print('MOCK {step.name}', flush=True)\n"
        )
        (tmp_path / location).write_text(mock_content, encoding='utf-8')
    code, report_file = pipeline.run_pipeline(steps, root=tmp_path)
    data = json.loads(report_file.read_text(encoding='utf-8'))
    assert code == 0
    assert len(data['steps']) == 16
    assert [x['status'] for x in data['steps']] == ['success'] * 16
    for x in data['steps']:
        log = report_file.parent / x['log']
        assert log.is_file()
        assert f'MOCK {x["name"]}' in log.read_text(encoding='utf-8')


def test_report_survives_subprocess_failure_with_real_runner(tmp_path):
    steps = [
        s(name='okay', target='okay.py'),
        s('landing', 'bad', 'bad.py'),
        s('trusted', 'never', 'never.py'),
    ]
    fixture_tree(tmp_path, steps)
    (tmp_path / 'okay.py').write_text("print('ok')\n", encoding='utf-8')
    (tmp_path / 'bad.py').write_text("print('failure')\nraise SystemExit(4)\n", encoding='utf-8')
    (tmp_path / 'never.py').write_text(
        "raise RuntimeError('should not be called')\n", encoding='utf-8'
    )
    exit_code, report_file = pipeline.run_pipeline(steps, root=tmp_path)
    data = json.loads(report_file.read_text(encoding='utf-8'))
    assert exit_code == 4
    assert [x['status'] for x in data['steps']] == ['success', 'failed', 'skipped']
    assert 'failure' in (report_file.parent / data['steps'][1]['log']).read_text(encoding='utf-8')
