"""Tests for WorkspaceReader.download_bytes (fix for issue #5793).

The 10 MiB cap in _read_file / _MAX_READ_BYTES is intentional for the
preview/viewer path.  download_bytes must bypass it so "Download file"
returns the complete file.
"""

from __future__ import annotations

import pytest

from omnigent.workspace_fs import WorkspaceReader, WorkspaceReaderError


def _make_workspace(tmp_path):
    return WorkspaceReader(tmp_path)


def test_download_bytes_small_file(tmp_path):
    content = b"hello world"
    f = tmp_path / "hello.txt"
    f.write_bytes(content)

    reader = _make_workspace(tmp_path)
    name, data = reader.download_bytes("hello.txt")

    assert name == "hello.txt"
    assert data == content


def test_download_bytes_exceeds_preview_cap(tmp_path, monkeypatch):
    """download_bytes must return the full file even when it exceeds _MAX_READ_BYTES."""
    import omnigent.workspace_fs as ws_mod

    # Temporarily shrink the cap so we can test with a small file.
    monkeypatch.setattr(ws_mod, "_MAX_READ_BYTES", 5)

    content = b"A" * 20  # 20 bytes > cap of 5
    f = tmp_path / "big.bin"
    f.write_bytes(content)

    reader = _make_workspace(tmp_path)

    # _read_file with the shrunken cap would truncate to 5 bytes.
    payload = reader._read_file("big.bin", tmp_path / "big.bin")
    assert payload["truncated"] is True

    # download_bytes must return all 20 bytes regardless of the cap.
    name, data = reader.download_bytes("big.bin")
    assert name == "big.bin"
    assert data == content
    assert len(data) == 20


def test_download_bytes_missing_file(tmp_path):
    reader = _make_workspace(tmp_path)
    with pytest.raises(WorkspaceReaderError) as exc_info:
        reader.download_bytes("nonexistent.txt")
    assert exc_info.value.status == 404
    assert exc_info.value.code == "not_found"


def test_download_bytes_directory_raises(tmp_path):
    subdir = tmp_path / "subdir"
    subdir.mkdir()

    reader = _make_workspace(tmp_path)
    with pytest.raises(WorkspaceReaderError) as exc_info:
        reader.download_bytes("subdir")
    assert exc_info.value.status == 400
    assert exc_info.value.code == "not_a_file"


def test_download_bytes_path_traversal_rejected(tmp_path):
    reader = _make_workspace(tmp_path)
    with pytest.raises(WorkspaceReaderError):
        reader.download_bytes("../../../etc/passwd")


def test_download_bytes_binary_file_intact(tmp_path):
    content = bytes(range(256)) * 100  # 25 600 bytes of binary
    f = tmp_path / "data.bin"
    f.write_bytes(content)

    reader = _make_workspace(tmp_path)
    name, data = reader.download_bytes("data.bin")

    assert name == "data.bin"
    assert data == content
