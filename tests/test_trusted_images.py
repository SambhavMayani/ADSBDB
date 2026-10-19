"""Fast, isolated tests. No Docker, network or live MinIO are required."""

from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pytest
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "trusted_zone"))
sys.path.insert(0, str(PROJECT_ROOT / "landing_zone" / "temporal_landing"))

from quality.image_quality import analyze, confirm_duplicate, image_rejection  # noqa: E402
from quality.duplicate_index import DuplicateIndex  # noqa: E402
from reporting.generate_image_report import aggregate, generate  # noqa: E402
from security_gate import inspect_file, read_config  # noqa: E402
from validate_images import run, load_policy  # noqa: E402


class FakeBody:
    def __init__(self, data):
        self.data = data
    def read(self):
        return self.data
    def close(self):
        pass


class FakeS3:
    """Tiny S3-compatible in-memory implementation of only operations used."""
    def __init__(self):
        self.objects = {}
        self.buckets = {"formatted-zone", "trusted-zone"}

    def put_object(self, *, Bucket, Key, Body, Metadata=None, ContentType=None, ContentLength=None):
        assert Bucket in self.buckets
        data = bytes(Body)
        self.objects[(Bucket, Key)] = {"body": data, "meta": Metadata or {}, "type": ContentType or "application/octet-stream"}
    def get_object(self, *, Bucket, Key):
        obj = self.objects[(Bucket, Key)]
        return {"Body": FakeBody(obj["body"]), "Metadata": obj["meta"]}
    def head_object(self, *, Bucket, Key):
        from botocore.exceptions import ClientError
        obj = self.objects.get((Bucket, Key))
        if obj is None:
            raise ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
        return {"ContentLength": len(obj["body"]), "ContentType": obj["type"],
                "ETag": f'"{hashlib.md5(obj["body"], usedforsecurity=False).hexdigest()}"', "Metadata": obj["meta"]}
    def head_bucket(self, *, Bucket):
        if Bucket not in self.buckets:
            from botocore.exceptions import ClientError
            raise ClientError({"Error": {"Code": "404"}}, "HeadBucket")
    def create_bucket(self, *, Bucket):
        self.buckets.add(Bucket)
    def delete_object(self, *, Bucket, Key):
        self.objects.pop((Bucket, Key), None)
    def get_paginator(self, command):
        assert command == "list_objects_v2"
        client = self
        class Paginator:
            def paginate(self, *, Bucket, Prefix):
                yield {"Contents": [{"Key": key} for bucket, key in sorted(client.objects)
                                    if bucket == Bucket and key.startswith(Prefix)]}
        return Paginator()


def make_jpeg(seed: int = 3, size=(320, 240)) -> bytes:
    rng = np.random.default_rng(seed)
    noise = rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8)
    buf = io.BytesIO()
    Image.fromarray(noise, "RGB").save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def upload_formatted(client, species, name, data):
    key = f"images/{species}/{name}.jpg"
    client.put_object(Bucket="formatted-zone", Key=key, Body=data,
                      ContentType="image/jpeg", Metadata={
                          "modality": "images", "species_id": species, "source_name": "test",
                          "source_persistent_key_encoded": quote(f"persistent_landing/images/{species}/{name}.jpg", safe=""),
                      })
    return key


@pytest.fixture
def config():
    return load_policy()[1]


def test_security_rejects_executables_disguised_as_images(tmp_path):
    policy = read_config()
    forged = tmp_path / "fox.jpg"
    forged.write_bytes(b"MZ" + b"\x00" * 100)
    result = inspect_file(forged, "images", policy)
    assert not result.allowed
    assert result.reason == "executable_or_active_binary_detected"


def test_security_rejects_executable_extension(tmp_path):
    path = tmp_path / "fox.exe"
    path.write_bytes(b"MZfake")
    assert inspect_file(path, "images", read_config()).reason == "extension_not_allowed"


def test_security_rejects_extreme_resource_limits(tmp_path):
    path = tmp_path / "lynx.jpg"
    path.write_bytes(make_jpeg())
    policy = read_config()
    policy["max_image_mb"] = 1
    policy["max_image_megapixels"] = 1
    assert inspect_file(path, "images", policy).allowed
    policy["max_image_mb"] = 0
    assert inspect_file(path, "images", policy).reason == "safety_size_limit_exceeded"


def test_jpeg_integrity_and_metrics(config):
    metrics, features = analyze(make_jpeg(), config)
    assert metrics["width"] == 320
    assert metrics["height"] == 240
    assert len(metrics["phash"]) == 16
    assert isinstance(features.phash, int)


def test_near_duplicates_match_and_different_images_survive(tmp_path, config):
    first = make_jpeg(seed=9)
    second = make_jpeg(seed=9)  # byte-identical
    third = make_jpeg(seed=111)
    _, a = analyze(first, config)
    _, b = analyze(second, config)
    _, c = analyze(third, config)
    with DuplicateIndex(tmp_path / "index.db", config) as index:
        index.add("a", "lynx_pardinus", hashlib.sha256(first).hexdigest(), a)
        found = index.find("b", "lynx_pardinus", hashlib.sha256(second).hexdigest(), b)
        assert found and found["method"] == "sha256"
        assert index.find("c", "lynx_pardinus", hashlib.sha256(third).hexdigest(), c) is None


def test_small_image_rejected(config):
    metrics, _ = analyze(make_jpeg(size=(100, 100)), config)
    assert image_rejection(metrics, config) == "dimensions_too_small"


def test_dark_image_is_not_rejected(config):
    image = Image.new("RGB", (256, 256), (2, 2, 2))
    buf = io.BytesIO()
    image.save(buf, "JPEG")
    metrics, _ = analyze(buf.getvalue(), config)
    assert "low_brightness" in metrics["flags"]
    assert image_rejection(metrics, config) is None


def test_end_to_end_dedup_and_idempotency(config):
    client = FakeS3()
    data = make_jpeg(seed=77)
    upload_formatted(client, "lynx_pardinus", "a", data)
    upload_formatted(client, "lynx_pardinus", "b", data)
    upload_formatted(client, "canis_lupus", "c", make_jpeg(seed=44))
    stats = run(client, config, "1", report=False)
    assert stats["accepted"] == 2
    assert stats["rejected"] == 1
    assert ("trusted-zone", "images/lynx_pardinus/b.jpg") not in client.objects
    assert ("trusted-zone", "_quality/images/lynx_pardinus/b.json") in client.objects
    again = run(client, config, "1", report=False)
    assert again["accepted"] == 2
    assert again["unchanged_objects"] == 2
    assert again["unchanged_manifests"] == 3


def test_cross_species_conflict_is_reported(config):
    client = FakeS3()
    data = make_jpeg(seed=13)
    upload_formatted(client, "alcedo_atthis", "same", data)
    upload_formatted(client, "aquila_chrysaetos", "same", data)
    result = run(client, config, "1", report=False)
    assert result["accepted"] == 1 and result["rejected"] == 1
    obj = json.loads(client.objects[("trusted-zone", "_quality/images/aquila_chrysaetos/same.json")]["body"])
    assert obj["reason"] == "cross_species_duplicate"


def test_full_html_report(tmp_path, config):
    client = FakeS3()
    upload_formatted(client, "bubo_bubo", "a", make_jpeg())
    run(client, config, "1", report=False)
    generated = generate(client, "1", config, output=tmp_path / "report")
    assert generated.exists()
    assert "Quality" in generated.read_text(encoding="utf-8")
    assert (generated.parent / "metrics.csv").exists()
    assert (generated.parent / "species_before_after.png").exists()
    summary = json.loads((generated.parent / "summary.json").read_text(encoding="utf-8"))
    assert summary["accepted"] == 1


def test_ingestor_blocks_before_hashing_or_upload(tmp_path, monkeypatch):
    import ingest_local_data
    forbidden = tmp_path / "evil.jpg"
    forbidden.write_bytes(b"MZ" + b"\x00" * 300)
    entry = {"path": forbidden, "modality": "images", "relative_path": Path("images/lynx_pardinus/evil.jpg")}
    monkeypatch.setattr(ingest_local_data, "discover_local_files", lambda: [entry])
    monkeypatch.setattr(ingest_local_data, "build_object_key", lambda e: pytest.fail("Hashing a blocked input"))
    monkeypatch.setattr(ingest_local_data, "upload_file", lambda *a: pytest.fail("Upload of blocked input"))
    monkeypatch.setattr(ingest_local_data, "record_incident", lambda *a: None)
    assert ingest_local_data.ingest_dataset() == 1


def test_expected_quality_rejections_are_not_operational_errors(config):
    client = FakeS3()
    upload_formatted(client, "bubo_bubo", "thumbnail", make_jpeg(size=(80, 80)))
    result = run(client, config, "1", report=False)
    assert result["rejected"] == 1
    assert result.get("errors", 0) == 0
    assert ("trusted-zone", "images/bubo_bubo/thumbnail.jpg") not in client.objects
