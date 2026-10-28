"""Offline tests for the audio Formatted Zone using synthetic recordings."""

import importlib.util
import io
import math
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

import soundfile

SCRIPT = Path(__file__).resolve().parents[1] / 'formatted_zone/format_audio.py'
spec = importlib.util.spec_from_file_location('format_audio', SCRIPT)
fa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fa)

FFMPEG = fa.resolve_ffmpeg()


def make_wav(sample_rate=44100, channels=2, seconds=0.5, sample_width=2):
    frames = int(sample_rate * seconds)
    peak = 2 ** (8 * sample_width - 1) - 1
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(sample_width)
        wav.setframerate(sample_rate)
        samples = bytearray()
        for i in range(frames):
            value = int(peak * 0.3 * math.sin(2 * math.pi * 440 * i / sample_rate))
            packed = value.to_bytes(sample_width, 'little', signed=True)
            samples += packed * channels
        wav.writeframes(bytes(samples))
    return buffer.getvalue()


def encode_with_ffmpeg(wav_bytes, extension, *extra_args):
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / 'source.wav'
        target = Path(tmp) / f'encoded{extension}'
        source.write_bytes(wav_bytes)
        subprocess.run(
            [FFMPEG, '-loglevel', 'error', '-y', '-i', str(source), *extra_args, str(target)],
            check=True,
            capture_output=True,
        )
        return target.read_bytes()


class FakeBody:
    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data

    def close(self):
        # format_object always closes the S3 streaming body, like boto3's StreamingBody.
        pass


class FakeClient:
    def __init__(self, data, metadata):
        self.data = data
        self.metadata = metadata
        self.stored = {}

    def get_object(self, Bucket, Key):
        return {'Body': FakeBody(self.data), 'Metadata': dict(self.metadata)}

    def put_object(self, Bucket, Key, Body, ContentType, Metadata):
        self.stored[(Bucket, Key)] = {
            'Body': Body,
            'ContentType': ContentType,
            'Metadata': Metadata,
        }

    def head_object(self, Bucket, Key):
        return {'ContentLength': len(self.stored[(Bucket, Key)]['Body'])}


class KeyAndDetectionTests(unittest.TestCase):
    def test_formatted_key_replicates_persistent_layout(self):
        key = 'persistent_landing/audio/bubo_bubo/xeno_canto$bubo_bubo$01-10-2026_10-00-00$abc.mp3'
        self.assertEqual(
            fa.build_formatted_key(key),
            'audio/bubo_bubo/xeno_canto$bubo_bubo$01-10-2026_10-00-00$abc.flac',
        )

    def test_formatted_key_rejects_other_layouts(self):
        with self.assertRaises(ValueError):
            fa.build_formatted_key('persistent_landing/text/bubo_bubo/a.txt')
        with self.assertRaises(ValueError):
            fa.build_formatted_key('persistent_landing/audio/a.mp3')

    def test_magic_bytes(self):
        cases = {
            b'ID3\x04' + b'\x00' * 20: 'mp3',
            b'\xff\xfb\x90\x00': 'mp3',
            b'\xff\xf1\x50\x80': 'aac',
            b'RIFF\x00\x00\x00\x00WAVEfmt ': 'wav',
            b'fLaC\x00\x00\x00\x22': 'flac',
            b'OggS\x00\x02' + b'\x00' * 22 + b'OpusHead': 'opus',
            b'OggS\x00\x02' + b'\x00' * 22 + b'\x01vorbis': 'ogg',
            b'\x00\x00\x00\x20ftypM4A ': 'm4a',
            b'FORM\x00\x00\x00\x00AIFF': 'aiff',
            b'\x1a\x45\xdf\xa3\x01': 'matroska',
            b'#!AMR\n': 'amr',
        }
        for header, expected in cases.items():
            self.assertEqual(fa.sniff_audio_format(header), expected, header)

    def test_content_wins_over_wrong_extension(self):
        self.assertEqual(fa.detect_source_format(make_wav(), '.mp3'), 'wav')

    def test_unknown_format_is_rejected(self):
        with self.assertRaises(ValueError):
            fa.detect_source_format(b'not audio at all', '.xyz')


class SoundfileConversionTests(unittest.TestCase):
    def test_wav_to_flac_is_lossless_and_preserves_layout(self):
        wav = make_wav(sample_rate=22050, channels=2)
        flac, source_format, decoder = fa.convert_audio(wav, '.wav', decoder='soundfile')
        info = fa.inspect_canonical_audio(flac)
        self.assertEqual((source_format, decoder), ('wav', 'soundfile'))
        self.assertEqual((info['sample_rate'], info['channels']), (22050, 2))
        original, _ = soundfile.read(io.BytesIO(wav), dtype='int16')
        converted, _ = soundfile.read(io.BytesIO(flac), dtype='int16')
        self.assertTrue((original == converted).all())

    def test_24_bit_input_becomes_16_bit(self):
        flac, _, _ = fa.convert_audio(make_wav(sample_width=3), '.wav', decoder='soundfile')
        self.assertEqual(soundfile.info(io.BytesIO(flac)).subtype, 'PCM_16')

    def test_inspect_rejects_non_canonical_audio(self):
        with self.assertRaises(RuntimeError):
            fa.inspect_canonical_audio(make_wav())


@unittest.skipUnless(FFMPEG, 'ffmpeg not available')
class FfmpegConversionTests(unittest.TestCase):
    def assert_canonical(self, data, extension, expected_format, sample_rate=44100):
        flac, source_format, decoder = fa.convert_audio(
            data, extension, decoder='ffmpeg', ffmpeg=FFMPEG
        )
        info = fa.inspect_canonical_audio(flac)
        self.assertEqual((source_format, decoder), (expected_format, 'ffmpeg'))
        self.assertEqual(info['sample_rate'], sample_rate)
        self.assertGreater(info['duration_seconds'], 0.3)
        return flac

    def test_common_formats(self):
        wav = make_wav()
        self.assert_canonical(wav, '.wav', 'wav')
        self.assert_canonical(encode_with_ffmpeg(wav, '.mp3'), '.mp3', 'mp3')
        self.assert_canonical(encode_with_ffmpeg(wav, '.m4a', '-c:a', 'aac'), '.m4a', 'm4a')
        self.assert_canonical(encode_with_ffmpeg(wav, '.ogg', '-c:a', 'libvorbis'), '.ogg', 'ogg')
        self.assert_canonical(
            encode_with_ffmpeg(wav, '.opus', '-c:a', 'libopus'), '.opus', 'opus', 48000
        )
        self.assert_canonical(encode_with_ffmpeg(wav, '.aiff'), '.aiff', 'aiff')
        self.assert_canonical(
            encode_with_ffmpeg(wav, '.flac', '-sample_fmt', 's32'), '.flac', 'flac'
        )

    def test_tags_are_removed_and_output_is_deterministic(self):
        mp3 = encode_with_ffmpeg(
            make_wav(), '.mp3', '-metadata', 'title=Recordist name', '-metadata', 'artist=XC'
        )
        first = self.assert_canonical(mp3, '.mp3', 'mp3')
        second = self.assert_canonical(mp3, '.mp3', 'mp3')
        self.assertEqual(first, second)
        self.assertNotIn(b'Recordist name', first)


class FormatObjectTests(unittest.TestCase):
    def test_upload_contains_canonical_audio_and_ascii_metadata(self):
        metadata = {
            'modality': 'audio',
            'species_id': 'bubo_bubo',
            'source_name': 'xeno_canto',
            'asset_hash': 'abc',
            'original_filename_encoded': 'XC%C3%A9.wav',
        }
        client = FakeClient(make_wav(), metadata)
        persistent_key = 'persistent_landing/audio/bubo_bubo/xeno_canto$bubo_bubo$t$abc.wav'
        formatted_key = fa.build_formatted_key(persistent_key)
        fa.format_object(client, persistent_key, formatted_key, 'soundfile', None)
        stored = client.stored[(fa.FORMATTED_BUCKET, formatted_key)]
        self.assertEqual(stored['ContentType'], 'audio/flac')
        self.assertEqual(soundfile.info(io.BytesIO(stored['Body'])).format, 'FLAC')
        self.assertEqual(stored['Metadata']['species_id'], 'bubo_bubo')
        self.assertEqual(stored['Metadata']['source_format'], 'wav')
        self.assertTrue(all(value.isascii() for value in stored['Metadata'].values()))

    def test_wrong_modality_is_rejected(self):
        # Complete lineage, so the rejection is caused by the wrong modality only.
        client = FakeClient(
            make_wav(),
            {'modality': 'text', 'species_id': 'x', 'source_name': 'y', 'asset_hash': 'abc'},
        )
        with self.assertRaisesRegex(ValueError, 'modality'):
            fa.format_object(
                client, 'persistent_landing/audio/x/a.wav', 'audio/x/a.flac', 'soundfile', None
            )


if __name__ == '__main__':
    unittest.main()
