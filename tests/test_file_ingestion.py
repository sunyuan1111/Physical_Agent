from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

import physical_agent.cli as cli_module
from physical_agent.cli import app
from physical_agent.config import write_default_config
from physical_agent.ingest.files import (
    FileIngestionError,
    MAX_INLINE_BYTES,
    ingest_file,
)
from physical_agent.protocol.schemas import Action
from physical_agent.state import open_state_store


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_sqlite_file_ingestion_copies_text_records_metadata_memory_and_audit(tmp_path):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    store = open_state_store(config_path=config_path)
    store.initialize()
    source = tmp_path / "brief.md"
    source.write_text("# Brief\n\nUse this as context only.\n", encoding="utf-8")

    result = ingest_file(source, store, tags=["brief"], importance=4)

    metadata = result["metadata"]
    stored_path = Path(metadata["stored_path"])
    assert stored_path.parent == store.uploads_path
    assert stored_path.exists()
    assert stored_path.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert metadata["original_name"] == "brief.md"
    assert metadata["stored_name"].endswith("-brief.md")
    assert metadata["sha256"]
    assert metadata["size_bytes"] == source.stat().st_size
    assert metadata["suffix"] == ".md"
    assert metadata["status"] == "stored"
    assert metadata["preview"].startswith("# Brief")
    assert metadata["truncated"] is False
    assert metadata["memory_note_created"] is True

    uploads = store.read_uploads()["uploads"]
    assert uploads[0]["sha256"] == metadata["sha256"]
    memory = store.read_memory(source="upload")["notes"][0]
    assert memory["kind"] == "upload_excerpt"
    assert memory["tags"] == ["upload", ".md", "brief"]
    assert "UNTRUSTED UPLOAD EXCERPT" in memory["content"]
    assert "Use this as context only." in memory["content"]

    audit = store.export_human_view()
    audit_dir = Path(audit["out_dir"])
    assert _read_json(audit_dir / "uploads.json")["uploads"][0]["sha256"] == metadata["sha256"]
    assert _read_json(audit_dir / "memory.json")["notes"][0]["source"] == "upload"


def test_text_file_ingestion_records_manifest_and_memory(tmp_path):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    store = open_state_store(config_path=config_path)
    store.initialize()
    source = tmp_path / "notes.txt"
    source.write_text("sqlite backend upload note", encoding="utf-8")

    result = ingest_file(source, store, tags="sqlite-backend")

    metadata = result["metadata"]
    assert store.read_uploads()["uploads"][0]["sha256"] == metadata["sha256"]
    assert Path(metadata["stored_path"]).exists()
    memory = store.read_memory(source="upload")["notes"][0]
    assert memory["tags"] == ["upload", ".txt", "sqlite-backend"]
    assert "UNTRUSTED UPLOAD EXCERPT" in memory["content"]

    audit_dir = Path(store.export_human_view()["out_dir"])
    assert _read_json(audit_dir / "uploads.json")["uploads"][0]["stored_name"] == metadata["stored_name"]


def test_file_ingestion_rejects_unsupported_and_binary_and_limits_large_text(tmp_path):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    store = open_state_store(config_path=config_path)
    store.initialize()

    unsupported = tmp_path / "manual.pdf"
    unsupported.write_bytes(b"%PDF-1.7\n")
    with pytest.raises(FileIngestionError, match="Unsupported file type"):
        ingest_file(unsupported, store)

    binary = tmp_path / "payload.txt"
    binary.write_bytes(b"hello\x00world")
    with pytest.raises(FileIngestionError, match="Binary or non-UTF-8"):
        ingest_file(binary, store)

    large = tmp_path / "large.log"
    large.write_text("a" * (MAX_INLINE_BYTES + 1), encoding="utf-8")
    result = ingest_file(large, store)

    statuses = [item["status"] for item in store.read_uploads()["uploads"]]
    assert statuses == [
        "rejected_unsupported_type",
        "rejected_binary",
        "stored_metadata_only",
    ]
    large_metadata = result["metadata"]
    assert Path(large_metadata["stored_path"]).exists()
    assert large_metadata["preview"] == ""
    assert large_metadata["truncated"] is True
    assert large_metadata["memory_note_created"] is False
    assert store.read_memory(source="upload")["notes"] == []


def test_file_ingestion_sanitizes_weird_names(tmp_path):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    store = open_state_store(config_path=config_path)
    store.initialize()
    source = tmp_path / ".. evil üpload.md"
    source.write_text("sanitize me", encoding="utf-8")

    result = ingest_file(source, store)

    stored_name = result["metadata"]["stored_name"]
    assert stored_name.endswith("-evil_upload.md")
    assert "/" not in stored_name
    assert "\\" not in stored_name
    assert ".." not in stored_name
    assert Path(result["metadata"]["stored_path"]).parent == store.uploads_path


def test_ingest_file_cli_is_state_only_and_preserves_backend(tmp_path, monkeypatch):
    config_path = write_default_config(tmp_path / "physical-agent.yaml", overwrite=True)
    store = open_state_store(config_path=config_path)
    store.initialize()
    store.write_actions([Action(id="act_cli", robot="arm_1", capability="observe")])
    source = tmp_path / "cli.md"
    source.write_text("cli upload", encoding="utf-8")
    before_config = config_path.read_text(encoding="utf-8")

    class ExplodingWatchRuntime:
        def __init__(self, *args, **kwargs):
            raise AssertionError("ingest-file must not instantiate WatchRuntime")

    monkeypatch.setattr(cli_module, "WatchRuntime", ExplodingWatchRuntime)

    result = CliRunner().invoke(
        app,
        [
            "ingest-file",
            str(source),
            "--config",
            str(config_path),
            "--tag",
            "cli",
            "--importance",
            "2",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "File ingested." in result.output
    assert "Memory written: yes" in result.output
    assert config_path.read_text(encoding="utf-8") == before_config
    assert yaml.safe_load(before_config)["workspace"]["backend"] == "sqlite"
    assert [action.id for action in store.read_actions()["pending"]] == ["act_cli"]
    assert store.read_uploads()["uploads"][0]["tags"] == ["cli"]
