"""Offline regression tests using a mock Xeno-canto API and fake audio bytes."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'landing_zone/data_acquisition/download_xeno_canto_audio.py'
spec = importlib.util.spec_from_file_location('xc_downloader', SCRIPT)
xc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xc)


class FakeResponse:
    def __init__(self, data=None, content=None):
        self.data = data
        self.content = content
    def raise_for_status(self):
        pass
    def json(self):
        return self.data
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def iter_content(self, chunk_size=65536):
        yield self.content


class FakeSession:
    def __init__(self):
        self.audio_downloads = 0
        self.api_queries = []
    def get(self, url, **kwargs):
        if url == xc.API_URL:
            self.api_queries.append(kwargs["params"]["query"])
            records = [{'id': str(i), 'gen': 'Erithacus', 'sp': 'rubecula',
                        'file': f'https://xeno-canto.org/{i}/download',
                        'file-name': f'XC{i}.mp3', 'cnt': 'Spain'} for i in range(1, 6)]
            records.append({'id': '99', 'gen': 'Canis', 'sp': 'lupus',
                            'file': 'https://xeno-canto.org/99/download'})
            return FakeResponse(data={'recordings': records, 'numPages': 1})
        self.audio_downloads += 1
        return FakeResponse(content=b'ID3' + b'\x00' * 2048)


class AcquisitionTests(unittest.TestCase):
    def test_incremental_contract_and_species_matching(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(xc, 'OUTPUT_ROOT', Path(tmp)), patch.object(xc.time, 'sleep'):
                session = FakeSession()
                species = {'id': 'erithacus_rubecula', 'scientific_name': 'Erithacus rubecula'}
                self.assertEqual(xc.process_species(session, 'test', species, 4, 1), 4)
                self.assertEqual(session.audio_downloads, 4)
                self.assertEqual(session.api_queries, ['gen:"Erithacus" sp:"rubecula"'])
                folder = Path(tmp) / species['id']
                data = json.loads((folder / '_metadata.json').read_text())
                self.assertEqual(len(data), 4)
                self.assertTrue(all(d['source_name'] == 'xeno_canto' and d['species_id'] == species['id'] for d in data))
                self.assertTrue(all((folder / d['local_filename']).exists() for d in data))
                self.assertEqual(xc.process_species(session, 'test', species, 4, 1), 4)
                self.assertEqual(session.audio_downloads, 4)

    def test_no_metadata_overwrite_on_wrong_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / '_metadata.json').write_text('{"wrong":"format"}')
            with self.assertRaises(ValueError):
                xc.read_metadata(folder / '_metadata.json', folder, 'erithacus_rubecula')


if __name__ == '__main__':
    unittest.main()
