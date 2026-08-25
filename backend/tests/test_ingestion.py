"""Ingestion: cleaning, metadata extraction, chunking, and pipeline behaviour."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.retrieval.chunking import chunk_segments
from app.retrieval.cleaning import CleanedSegment, clean_json, clean_text, clean_transcript, clean_vtt
from app.retrieval.metadata import extract_metadata, from_filename, parse_front_matter

VTT = """WEBVTT

00:00:01.000 --> 00:00:04.000
<v Lenny>Welcome back to the podcast.

00:00:04.500 --> 00:00:09.000
<v Ada>The clearest PMF signal is retention.

00:00:09.000 --> 00:00:12.000
The clearest PMF signal is retention.
"""

JSON_TRANSCRIPT = """
{
  "title": "How to find product-market fit",
  "guest": "Ada Lovelace",
  "url": "https://example.com/pmf",
  "segments": [
    {"start": 1.0, "speaker": "Lenny", "text": "Welcome back."},
    {"start": 12.5, "speaker": "Ada", "text": "Retention is the signal."}
  ]
}
"""


# --- cleaning -------------------------------------------------------------


def test_vtt_cleaning_extracts_timestamps_and_speakers():
    cleaned = clean_vtt(VTT)
    assert "WEBVTT" not in cleaned.text
    assert "-->" not in cleaned.text
    assert cleaned.segments[0].speaker == "Lenny"
    assert cleaned.segments[0].timestamp.startswith("00:00:01")
    assert "Welcome back to the podcast." in cleaned.text


def test_vtt_cleaning_drops_consecutive_duplicate_captions():
    cleaned = clean_vtt(VTT)
    texts = [segment.text for segment in cleaned.segments]
    assert texts.count("The clearest PMF signal is retention.") == 1


def test_json_cleaning_reads_segments_and_metadata():
    cleaned = clean_json(JSON_TRANSCRIPT)
    assert len(cleaned.segments) == 2
    assert cleaned.segments[1].speaker == "Ada"
    assert cleaned.raw_metadata["guest"] == "Ada Lovelace"
    assert "Retention is the signal." in cleaned.text


def test_plain_text_cleaning_keeps_paragraphs():
    cleaned = clean_text("Lenny: Welcome.\n\nAda: Retention matters.\n\n\n")
    assert len(cleaned.segments) == 2
    assert cleaned.text.count("Retention matters") == 1


def test_clean_transcript_dispatches_on_suffix():
    assert clean_transcript(VTT, ".vtt").segments[0].speaker == "Lenny"
    assert clean_transcript(JSON_TRANSCRIPT, ".json").raw_metadata["title"]
    assert clean_transcript("Just prose.", ".txt").text == "Just prose."


def test_unreadable_transcript_yields_no_text():
    assert clean_transcript("", ".txt").text.strip() == ""


# --- metadata -------------------------------------------------------------


def test_front_matter_is_parsed_and_removed():
    raw = "---\ntitle: Growth loops\nguest: Grace Hopper\npublished_at: 2024-05-01\n---\nBody text"
    front_matter, body = parse_front_matter(raw)
    assert front_matter["title"] == "Growth loops"
    assert body.strip() == "Body text"


def test_filename_metadata_fallback():
    metadata = from_filename(Path("2024-05-01_Ada-Lovelace_how-to-find-pmf.vtt"))
    assert metadata.episode_title
    assert "pmf" in metadata.episode_title.lower() or "Ada" in (metadata.guest or "")


def test_front_matter_wins_over_filename():
    metadata = extract_metadata(
        Path("whatever.vtt"),
        {"title": "Real title", "guest": "Ada Lovelace", "url": "https://example.com/x"},
        None,
    )
    assert metadata.episode_title == "Real title"
    assert metadata.guest == "Ada Lovelace"
    assert metadata.source_url == "https://example.com/x"


def test_embedded_json_metadata_is_used():
    metadata = extract_metadata(Path("x.json"), {}, {"title": "Embedded title", "guest": "Grace"})
    assert metadata.episode_title == "Embedded title"


# --- chunking -------------------------------------------------------------


def _segments(count: int, size: int = 200) -> list[CleanedSegment]:
    return [
        CleanedSegment(text=f"Sentence {i}. " + ("filler " * (size // 7)), timestamp=f"00:0{i%10}:00", speaker="Ada")
        for i in range(count)
    ]


def test_chunking_respects_target_size():
    chunks = chunk_segments(_segments(30), target_chars=1400, overlap_chars=200)
    assert chunks
    assert all(len(chunk.content) <= 1400 * 2 for chunk in chunks)
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))


def test_chunking_carries_timestamps_and_speakers():
    chunk = chunk_segments(_segments(10), target_chars=1400, overlap_chars=100)[0]
    assert chunk.start_timestamp
    assert chunk.speaker


def test_chunking_adds_overlap_between_chunks():
    chunks = chunk_segments(_segments(40), target_chars=800, overlap_chars=200)
    assert len(chunks) > 1
    tail = chunks[0].content[-80:]
    assert any(word in chunks[1].content for word in tail.split()[:5])


def test_chunking_handles_empty_and_invalid_input():
    assert chunk_segments([]) == []
    assert chunk_segments([CleanedSegment(text="   ", timestamp=None, speaker=None)]) == []
    with pytest.raises(ValueError):
        chunk_segments(_segments(2), target_chars=0)


def test_a_single_oversized_segment_is_split():
    chunks = chunk_segments(
        [CleanedSegment(text="word " * 2000, timestamp="00:00:01", speaker="Ada")],
        target_chars=1000,
        overlap_chars=100,
    )
    assert len(chunks) > 1


# --- pipeline -------------------------------------------------------------


def test_discover_files_finds_supported_transcripts(tmp_path: Path):
    from app.ingestion.pipeline import discover_files

    (tmp_path / "a.vtt").write_text(VTT, encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "b.txt").write_text("Body", encoding="utf-8")
    (tmp_path / "notes.pdf").write_bytes(b"%PDF")
    (tmp_path / "README.md").write_text("docs", encoding="utf-8")

    found = {path.name for path in discover_files(tmp_path)}
    assert {"a.vtt", "b.txt"} <= found
    assert "notes.pdf" not in found


def test_ingest_file_persists_chunks_and_is_idempotent(db, tmp_path: Path):
    from app.config import get_settings
    from app.db.models import Transcript, TranscriptChunk
    from app.ingestion.pipeline import ingest_file
    from app.retrieval.embedder import Embedder

    from .conftest import FakeProvider

    path = tmp_path / "2024-05-01_Ada-Lovelace_pmf.vtt"
    path.write_text(VTT, encoding="utf-8")
    embedder = Embedder(FakeProvider())
    settings = get_settings()

    first = ingest_file(db, path, embedder=embedder, settings=settings, root=tmp_path)
    db.commit()
    assert first.status == "ingested"
    assert first.chunks > 0
    assert db.query(Transcript).count() == 1
    assert db.query(TranscriptChunk).count() == first.chunks

    second = ingest_file(db, path, embedder=embedder, settings=settings, root=tmp_path)
    db.commit()
    assert second.status == "skipped"
    assert db.query(TranscriptChunk).count() == first.chunks


def test_changed_file_is_reindexed_without_duplicates(db, tmp_path: Path):
    from app.config import get_settings
    from app.db.models import Transcript, TranscriptChunk
    from app.ingestion.pipeline import ingest_file
    from app.retrieval.embedder import Embedder

    from .conftest import FakeProvider

    path = tmp_path / "episode.vtt"
    path.write_text(VTT, encoding="utf-8")
    embedder, settings = Embedder(FakeProvider()), get_settings()
    ingest_file(db, path, embedder=embedder, settings=settings, root=tmp_path)
    db.commit()

    path.write_text(VTT + "\n00:00:20.000 --> 00:00:25.000\n<v Ada>New material here.\n", encoding="utf-8")
    outcome = ingest_file(db, path, embedder=embedder, settings=settings, root=tmp_path)
    db.commit()

    assert outcome.status == "reindexed"
    assert db.query(Transcript).count() == 1
    assert db.query(TranscriptChunk).count() == outcome.chunks


def test_unreadable_file_is_reported_not_raised(db, tmp_path: Path):
    from app.config import get_settings
    from app.ingestion.pipeline import ingest_file
    from app.retrieval.embedder import Embedder

    from .conftest import FakeProvider

    path = tmp_path / "empty.txt"
    path.write_text("   \n\n", encoding="utf-8")
    outcome = ingest_file(
        db, path, embedder=Embedder(FakeProvider()), settings=get_settings(), root=tmp_path
    )
    assert outcome.status == "failed"
    assert outcome.detail
