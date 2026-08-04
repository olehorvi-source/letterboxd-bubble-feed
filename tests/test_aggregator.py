from __future__ import annotations

import json
from pathlib import Path

from letterboxd_rss_aggregator.aggregator import (
    dedupe_key,
    merge_entries,
    parse_feed_document,
    render_index_html,
    sort_entries,
    validate_json_files,
    write_json,
)


FIXTURES = Path(__file__).parent / "fixtures"


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_feed_document_extracts_expected_fields() -> None:
    entries = parse_feed_document(read_fixture("thejoshl.xml"), username="thejoshl", critic_tier="primary")

    assert len(entries) == 2

    first = entries[0]
    assert first["id"] == "guid:tag:letterboxd.com,2026-08-03:/thejoshl/film/heat/"
    assert first["guid"] == "tag:letterboxd.com,2026-08-03:/thejoshl/film/heat/"
    assert first["username"] == "thejoshl"
    assert first["critic_tier"] == "primary"
    assert first["creator_display_name"] == "Josh Lewis"
    assert first["film_title"] == "Heat"
    assert first["film_year"] == 1995
    assert first["tmdb_movie_id"] == 949
    assert first["letterboxd_entry_url"] == "https://letterboxd.com/thejoshl/film/heat/"
    assert first["watched_date"] == "2026-08-02"
    assert first["publication_date"] == "2026-08-03"
    assert first["rating"] == 4.5
    assert first["liked"] is True
    assert first["rewatch"] is None
    assert first["poster_url"] == "https://a.ltrbxd.com/resized/poster-heat.jpg"
    assert first["review_text"] == "One of the great Los Angeles movies.\nStill feels impossibly big and precise."

    second = entries[1]
    assert second["guid"] is None
    assert second["id"] == "fallback:thejoshl:https://letterboxd.com/thejoshl/film/thief/"
    assert second["film_title"] == "Thief"
    assert second["film_year"] == 1981
    assert second["rating"] == 4.0
    assert second["rewatch"] is True


def test_merge_entries_deduplicates_guid_and_fallback_records() -> None:
    older_entries = parse_feed_document(read_fixture("thejoshl.xml"), username="thejoshl", critic_tier="primary")
    newer_entries = parse_feed_document(read_fixture("thejoshl.xml"), username="thejoshl", critic_tier="primary")
    newer_entries[1]["review_text"] = "Updated text"

    merged = merge_entries(older_entries, newer_entries)

    assert len(merged) == 2
    thief = next(entry for entry in merged if "thief" in entry["letterboxd_entry_url"])
    assert thief["review_text"] == "Updated text"
    assert dedupe_key(thief) == "fallback:thejoshl:https://letterboxd.com/thejoshl/film/thief/"


def test_sort_and_render_outputs() -> None:
    combined_entries = parse_feed_document(read_fixture("thejoshl.xml"), username="thejoshl", critic_tier="primary")
    combined_entries += parse_feed_document(read_fixture("theolejake.xml"), username="theolejake", critic_tier="my_account")
    sorted_entries = sort_entries(combined_entries)

    assert sorted_entries[0]["film_title"] == "Heat"
    assert sorted_entries[-1]["film_title"] == "Blue Collar"

    status_payload = {
        "last_successful_update": "2026-08-04T00:00:00Z",
        "individual_feed_status": {
            "thejoshl": {
                "critic_tier": "primary",
                "state": "ok",
                "entries_fetched": 2,
                "last_successful_fetch": "2026-08-04T00:00:00Z",
                "error": None,
            },
            "theolejake": {
                "critic_tier": "my_account",
                "state": "error",
                "entries_fetched": 0,
                "last_successful_fetch": "2026-08-03T00:00:00Z",
                "error": "timeout",
            },
        },
        "entries_fetched": 3,
        "total_archived_entries": 3,
    }

    html = render_index_html(sorted_entries, status_payload)

    assert "Letterboxd RSS Aggregator" in html
    assert "Heat (1995)" in html
    assert "timeout" in html


def test_write_json_and_validate_json_files(tmp_path: Path) -> None:
    payload = {"hello": "world", "count": 1}
    json_path = tmp_path / "sample.json"

    write_json(json_path, payload)
    validate_json_files([json_path])

    with json_path.open("r", encoding="utf-8") as handle:
        assert json.load(handle) == payload
