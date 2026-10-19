"""Lossless audio integrity and acoustic profiling: never alter samples."""

from __future__ import annotations

import hashlib
import io
import math

import numpy as np
import soundfile as sf

from trusted_zone.pipeline_common import QualityFailure


def audio_metrics(raw: bytes, config: dict) -> dict:
    if not raw.startswith(b"fLaC"):
        raise QualityFailure("not_flac_container")
    try:
        with sf.SoundFile(io.BytesIO(raw)) as audio:
            if audio.format != "FLAC" or audio.subtype != "PCM_16":
                raise QualityFailure("not_canonical_flac_pcm16")
            rate, channels, frames = audio.samplerate, audio.channels, audio.frames
            if rate <= 0 or channels <= 0 or frames <= 0:
                raise QualityFailure("empty_or_invalid_audio")
            duration = frames / rate
            if duration < config["min_duration_seconds"]:
                raise QualityFailure("duration_below_minimum")
            pcm_hash = hashlib.sha256(f"pcm16|{rate}|{channels}|".encode("ascii"))
            sample_count = 0
            sum_squares = 0.0
            signed_sum = 0.0
            peak = 0.0
            clipping = 0
            quiet_windows = 0
            windows = 0
            limit = float(config["clipping_amplitude_threshold"])
            quiet = 10 ** (float(config["low_energy_dbfs_threshold"]) / 20)
            window_frames = max(1, round(rate * 0.05))  # 50 ms; time-based across sampling rates
            while True:
                block = audio.read(window_frames, dtype="int16", always_2d=True)
                if block.size == 0:
                    break
                pcm_hash.update(block.tobytes())
                values = block.astype(np.float64) / 32768.0
                count = values.size
                sample_count += count
                sum_squares += float(np.sum(values * values))
                signed_sum += float(np.sum(values))
                peak = max(peak, float(np.max(np.abs(values))))
                clipping += int(np.count_nonzero(np.abs(values) >= limit))
                window_rms = math.sqrt(float(np.mean(values * values)))
                quiet_windows += int(window_rms < quiet)
                windows += 1
            if sample_count == 0 or sample_count != frames * channels:
                raise QualityFailure("incomplete_audio_decode")
    except QualityFailure:
        raise
    except (RuntimeError, ValueError, OSError) as exc:
        raise QualityFailure("flac_decoding_failed") from exc
    rms = math.sqrt(sum_squares / sample_count)
    rms_db = 20 * math.log10(rms) if rms > 0 else None
    peak_db = 20 * math.log10(peak) if peak > 0 else None
    flags = []
    if rms == 0:
        # Never silently reject a file because it might contain intentional silence.
        flags.append("digital_silence")
    elif rms_db < config["low_rms_dbfs_warning"]:
        flags.append("low_rms")
    clipping_pct = 100 * clipping / sample_count
    if clipping_pct >= config["clipping_pct_warning"]:
        flags.append("possible_clipping")
    quiet_pct = 100 * quiet_windows / windows
    if quiet_pct >= config["low_energy_window_pct_warning"]:
        flags.append("many_low_energy_windows")
    dc = abs(signed_sum / sample_count)
    if dc >= config["dc_offset_warning"]:
        flags.append("dc_offset")
    if duration < config["short_duration_warning_seconds"]:
        flags.append("short_recording")
    return {
        "file_size_mb": round(len(raw) / 1_000_000, 5),
        "sample_rate_hz": rate,
        "channels": channels,
        "frames": frames,
        "duration_seconds": round(duration, 5),
        "rms_dbfs": round(rms_db, 3) if rms_db is not None else None,
        "peak_dbfs": round(peak_db, 3) if peak_db is not None else None,
        "clipping_sample_pct": round(clipping_pct, 4),
        "low_energy_window_pct": round(quiet_pct, 3),
        "dc_offset_abs": round(dc, 6),
        "decoded_pcm_sha256": pcm_hash.hexdigest(),
        "flags": flags,
    }
