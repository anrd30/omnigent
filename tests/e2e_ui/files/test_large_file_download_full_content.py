"""E2E: downloading a large workspace file must deliver its full content.

The filesystem file-content API returns the whole file as one inline JSON
payload and truncates large files (2,000-line / 10 MiB read caps) instead of
streaming them. The FileViewer's truncation banner tells users to download
the file "to view or edit the full content", but the Download action reuses
the same truncated payload, so the saved file silently loses everything past
the cap — there is no way to retrieve the full file through the app.

Journey pinned here: seed a 3,000-line file into the session workspace →
open it in the file viewer → trigger "Download file" from the viewer
toolbar → the downloaded file must contain all 3,000 lines.

Seeded via the filesystem PUT endpoint (no agent run).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Locator, Page, expect

# The repo root is three levels up (``<repo>/tests/e2e_ui/files/...``).
_REPO_ROOT = Path(__file__).resolve().parents[3]

_FILE_PATH = "large_download_journey.txt"
_TOTAL_LINES = 3_000
_LINE_TEMPLATE = "LINE {index:05d}: filesystem content that must survive a download"
_FILE_CONTENT = (
    "\n".join(_LINE_TEMPLATE.format(index=i) for i in range(1, _TOTAL_LINES + 1)) + "\n"
)
_FIRST_LINE = _LINE_TEMPLATE.format(index=1)
_LAST_LINE = _LINE_TEMPLATE.format(index=_TOTAL_LINES)


@pytest.fixture
def seeded_large_file_session(
    seeded_session: tuple[str, str],
) -> Iterator[tuple[str, str]]:
    """Seed the large text file and yield ``(base_url, session_id)``.

    :param seeded_session: Runner-bound ``(base_url, session_id)`` pair.
    :returns: The same pair, with the large file present in the workspace.
    """
    base_url, session_id = seeded_session
    resp = httpx.put(
        f"{base_url}/v1/sessions/{session_id}"
        f"/resources/environments/default/filesystem/{_FILE_PATH}",
        json={"content": _FILE_CONTENT, "encoding": "utf-8"},
        timeout=30.0,
    )
    resp.raise_for_status()
    try:
        yield (base_url, session_id)
    finally:
        # The spawned runner's workspace is the repo root, so the seeded
        # file lands there; remove it so reruns start clean.
        (_REPO_ROOT / _FILE_PATH).unlink(missing_ok=True)


def _open_viewer_settings_menu(file_viewer: Locator) -> None:
    """Open the viewer toolbar menu that carries the Download action.

    The toolbar renders inline icon buttons ("View settings") while they
    fit and folds everything into a single "More actions" menu when the
    pane is narrow, so try the inline trigger first and fall back.

    :param file_viewer: The visible FileViewer locator.
    """
    inline = file_viewer.get_by_role("button", name="View settings")
    if inline.count() > 0 and inline.first.is_visible():
        inline.first.click()
        return
    file_viewer.get_by_role("button", name="More actions").first.click()


def test_download_of_large_file_delivers_full_content(
    page: Page,
    seeded_large_file_session: tuple[str, str],
) -> None:
    """Downloading a file larger than the read caps must not lose content."""
    base_url, session_id = seeded_large_file_session
    page.goto(f"{base_url}/c/{session_id}?file={_FILE_PATH}")

    file_viewer = page.locator('[data-testid="file-viewer"]:visible')
    expect(file_viewer).to_be_visible(timeout=30_000)
    # The open file is identified by its tab; the tab's close button proves
    # the viewer opened the seeded file (not some other panel state).
    expect(page.get_by_role("button", name=f"Close {_FILE_PATH}", exact=True).first).to_be_visible(
        timeout=30_000
    )
    # Content rendered — the Download action only appears in the toolbar
    # menu once the file-content query has resolved.
    expect(file_viewer.get_by_text("LINE 00001").first).to_be_visible(timeout=30_000)

    _open_viewer_settings_menu(file_viewer)
    download_item = page.get_by_role("menuitem", name="Download file")
    expect(download_item).to_be_visible()

    with page.expect_download() as download_info:
        download_item.click()
    download = download_info.value
    assert download.suggested_filename == _FILE_PATH

    saved = Path(str(download.path())).read_text(encoding="utf-8")
    lines = saved.splitlines()
    assert lines and lines[0] == _FIRST_LINE
    # The whole point of the download affordance (and the truncation banner
    # that points users at it) is retrieving the file in full; a capped,
    # non-streamed read silently drops everything past the cap.
    assert len(lines) == _TOTAL_LINES, (
        f"downloaded file is truncated: got {len(lines)} of {_TOTAL_LINES} lines"
    )
    assert lines[-1] == _LAST_LINE
