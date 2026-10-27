from __future__ import annotations

from pathlib import Path

BATCH = Path(__file__).resolve().parents[1] / ".github/workflows/cflite_batch.yml"
PR = Path(__file__).resolve().parents[1] / ".github/workflows/cflite_pr.yml"


def test_batch_scanning_covers_each_new_main_commit() -> None:
    text = BATCH.read_text(encoding="utf-8")

    assert "  push:\n    branches: [main]" in text
    assert "  schedule:" in text
    assert "  workflow_dispatch:" in text
    assert "      security-events: write" in text
    assert "          output-sarif: true" in text
    assert "        if: always() && steps.build.outcome == 'success'" in text
    assert "github/codeql-action/upload-sarif@6f2ac81f5cd81fe351a197ba0b00d91d03cd2aee" in text
    assert "          sarif_file: cifuzz-sarif/results.sarif" in text
    assert "          checkout_path: cifuzz-sarif" in text
    assert "          keep-unaffected-fuzz-targets: true" in text


def test_batch_preserves_weekly_depth_and_bounded_push_runtime() -> None:
    text = BATCH.read_text(encoding="utf-8")

    assert '    - cron: "0 3 * * 1"' in text
    assert "          mode: batch" in text
    assert "fuzz-seconds: ${{ github.event_name == 'push' && 300 || 1800 }}" in text


def test_pr_upload_matches_protected_main_analysis_category() -> None:
    batch = BATCH.read_text(encoding="utf-8")
    pr = PR.read_text(encoding="utf-8")

    assert "  batch-fuzzing:" in batch
    assert "        sanitizer: [address]" in batch
    assert (
        '          category: ".github/workflows/cflite_batch.yml:batch-fuzzing/sanitizer:address"'
        in pr
    )
