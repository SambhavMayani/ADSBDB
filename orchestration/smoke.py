"""Real CLI end-to-end acceptance on a disposable S3 server and synthetic assets.

Run docker-compose.test.yml first. Never targets the production endpoint/volume.
Repeating --run reuses the same fixture and verifies incremental behavior.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from exploitation_zone.contracts import ROOT


def seed(path):
    import numpy as np
    from PIL import Image
    import soundfile as sf

    for kind in ('images', 'audio', 'text'):
        folder = path / kind / 'lynx_pardinus'
        folder.mkdir(parents=True)
        if kind == 'images':
            file = folder / 'sample.png'
            rng = np.random.default_rng(42)
            Image.fromarray(rng.integers(0, 255, (200, 200, 3), dtype=np.uint8)).save(file)
        elif kind == 'audio':
            file = folder / 'sample.wav'
            sf.write(file, 0.1 * np.sin(np.arange(8000) * 0.1), 32000, subtype='PCM_16')
        else:
            file = folder / 'sample.html'
            file.write_text(
                '<p>The Iberian lynx lives in Mediterranean forests and hunts rabbits.</p>',
                encoding='utf-8',
            )
        (folder / '_metadata.json').write_text(
            json.dumps(
                [
                    {
                        'local_filename': file.name,
                        'source_name': 'synthetic_fixture',
                        'species_id': 'lynx_pardinus',
                    }
                ]
            ),
            encoding='utf-8',
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', required=True)
    parser.add_argument('--workdir', type=Path, default=ROOT / 'data/smoke')
    args = parser.parse_args(argv)
    work = args.workdir.resolve()
    marker = work / '.ecosentinel-smoke'
    if work.exists() and not marker.is_file():
        raise ValueError('Refuse to reuse a directory without the smoke fixture marker')
    if not work.exists():
        work.mkdir(parents=True)
        marker.write_text('synthetic-fixture-v1', encoding='utf-8')
        seed(work / 'raw')
    env = {
        **os.environ,
        'PYTHONUTF8': '1',
        'PYTHONIOENCODING': 'utf-8',
        'S3_ENDPOINT_URL': 'http://127.0.0.1:19000',
        'MINIO_ROOT_USER': 'ecosentinel_test',
        'MINIO_ROOT_PASSWORD': 'only_for_isolated_tests',
        'ECOSENTINEL_LANDING_BUCKET': 'eco-smoke-landing',
        'ECOSENTINEL_FORMATTED_BUCKET': 'eco-smoke-formatted',
        'ECOSENTINEL_TRUSTED_BUCKET': 'eco-smoke-trusted',
        'ECOSENTINEL_RAW_ROOT': str(work / 'raw'),
        'ECOSENTINEL_CHROMA_PATH': str(work / 'index'),
        'ECOSENTINEL_REPORT_ROOT': str(work / 'reports'),
        'HF_HUB_OFFLINE': '1',
        'TRANSFORMERS_OFFLINE': '1',
        'SECURITY_ALERT_WEBHOOK_URL': '',
    }
    return subprocess.call(
        [
            sys.executable,
            '-B',
            '-m',
            'orchestration.pipeline',
            '--run',
            '--report-dir',
            str(work / 'reports/orchestration'),
        ],
        cwd=ROOT,
        env=env,
    )


if __name__ == '__main__':
    raise SystemExit(main())
