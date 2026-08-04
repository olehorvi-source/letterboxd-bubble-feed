from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from typing import Any

import feedparser
import requests
from bs4 import BeautifulSoup

FEEDS: list[dict[str, str]] = [
    {"username": "thejoshl", "critic_tier": "primary"},
    {"username": "jlalibs", "critic_tier": "primary"},
    {"username": "brofromanother", "critic_tier": "primary"},
    {"username": "bdgrabinski", "critic_tier": "primary"},
    {"username": "SeanFennessey", "critic_tier": "secondary"},
    {"username": "SilentDawnLB", "critic_tier": "secondary"},
    {"username": "davidlsims", "critic_tier": "secondary"},
    {"username": "gemko", "critic_tier": "secondary"},
    {"username": "BrianDuffield", "critic_tier": "secondary"},
    {"username": "judysquirrels", "critic_tier": "secondary"},
    {"username": "davidehrlich", "critic_tier": "secondary"},
    {"username": "theolejake", "critic_tier": "my_account"},
]

DEFAULT_STATUS: dict[str, Any] = {
    "last_successful_update": None,
    "individual_feed_status": {},
    "last_successful_fetch_per_username": {},
    "errors": [],
    "entries_fetched": 0,
}

DATE_PATTERNS = (
    "%Y-%m-%d",
    "%B %d, %Y",
    "%b %d, %Y",
    "%A %B %d, %Y",
    "%A %b %d, %Y",
)

LABEL_PATTERNS = {
    "film_title": re.compile(r"film\s*title", re.IGNORECASE),
    "film_year": re.compile(r"film\s*year", re.IGNORECASE),
    "tmdb_movie_id": re.compile(r"tmdb", re.IGNORECASE),
    "poster_url": re.compile(r"poster", re.IGNORECASE),
    "watched_date": re.compile(r"watched", re.IGNORECASE),
    "rating": re.compile(r"rating", re.IGNORECASE),
    "liked": re.compile(r"liked", re.IGNORECASE),
    "rewatch": re.compile(r"rewatch", re.IGNORECASE),
}


def run_aggregation(output_dir: Path, user_agent: str, timeout: float) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    entries_path = output_dir / "entries.json"
    status_path = output_dir / "status.json"
    index_path = output_dir / "index.html"
    nojekyll_path = output_dir / ".nojekyll"

    previous_entries = load_json_file(entries_path, default=[])
    previous_status = load_json_file(status_path, default=DEFAULT_STATUS)

    run_started_at = now_iso()
    individual_status: dict[str, Any] = {}
    last_successful_fetch = dict(previous_status.get("last_successful_fetch_per_username", {}))
    errors: list[dict[str, str]] = []
    fetched_count = 0
    parsed_entries: list[dict[str, Any]] = []
    successful_feeds = 0

    session = requests.Session()
    session.headers.update({"User-Agent": user_agent})

    for feed_config in FEEDS:
        username = feed_config["username"]
        critic_tier = feed_config["critic_tier"]
        feed_url = f"https://letterboxd.com/{username}/rss/"

        try:
            response = session.get(feed_url, timeout=timeout)
            response.raise_for_status()
            entries = parse_feed_document(response.text, username=username, critic_tier=critic_tier)
            parsed_entries.extend(entries)
            fetched_count += len(entries)
            successful_feeds += 1
            last_successful_fetch[username] = run_started_at
            individual_status[username] = {
                "username": username,
                "critic_tier": critic_tier,
                "feed_url": feed_url,
                "state": "ok",
                "http_status": response.status_code,
                "entries_fetched": len(entries),
                "last_attempted_at": run_started_at,
                "last_successful_fetch": run_started_at,
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            error_message = str(exc)
            errors.append({"username": username, "feed_url": feed_url, "error": error_message})
            individual_status[username] = {
                "username": username,
                "critic_tier": critic_tier,
                "feed_url": feed_url,
                "state": "error",
                "http_status": getattr(getattr(exc, "response", None), "status_code", None),
                "entries_fetched": 0,
                "last_attempted_at": run_started_at,
                "last_successful_fetch": last_successful_fetch.get(username),
                "error": error_message,
            }

    merged_entries = merge_entries(previous_entries, parsed_entries)
    sorted_entries = sort_entries(merged_entries)

    status_payload = {
        "last_successful_update": run_started_at if successful_feeds else previous_status.get("last_successful_update"),
        "individual_feed_status": individual_status,
        "last_successful_fetch_per_username": last_successful_fetch,
        "errors": errors,
        "entries_fetched": fetched_count,
        "total_archived_entries": len(sorted_entries),
    }

    write_json(entries_path, sorted_entries)
    write_json(status_path, status_payload)
    index_path.write_text(render_index_html(sorted_entries, status_payload), encoding="utf-8")
    nojekyll_path.write_text("", encoding="utf-8")
    validate_json_files([entries_path, status_path])

    return 0 if successful_feeds else 1


def parse_feed_document(document: str, username: str, critic_tier: str) -> list[dict[str, Any]]:
    parsed = feedparser.parse(document)
    feed_info = getattr(parsed, "feed", {})
    results: list[dict[str, Any]] = []

    for entry in parsed.entries:
        html_source = pick_first(
            entry,
            [
                "content",
                "summary",
                "description",
                "subtitle",
            ],
        )
        html_value = extract_content_value(html_source)
        soup = BeautifulSoup(html_value or "", "html.parser")
        text_lines = extract_clean_lines(soup)
        metadata_map = build_metadata_map(text_lines)

        entry_url = pick_first(entry, ["link", "id"])
        guid = extract_guid(entry, entry_url)
        title = pick_first(entry, ["title"])
        film_title, film_year = extract_film_identity(entry, metadata_map, title)
        rating = extract_rating(entry, metadata_map, title)
        liked = extract_bool(entry, metadata_map, field_name="liked")
        rewatch = extract_bool(entry, metadata_map, field_name="rewatch")
        tmdb_movie_id = extract_tmdb_movie_id(entry, metadata_map, html_value, entry_url)
        poster_url = extract_poster_url(entry, metadata_map, html_value)
        watched_date = extract_watched_date(entry, metadata_map, text_lines)
        publication_date = extract_publication_date(entry)
        creator_display_name = extract_creator_display_name(feed_info, entry)
        review_text = extract_review_text(text_lines, metadata_map)

        normalized_entry = {
            "id": build_entry_id(username=username, guid=guid, entry_url=entry_url),
            "guid": guid or None,
            "username": username,
            "critic_tier": critic_tier,
            "creator_display_name": creator_display_name,
            "film_title": film_title,
            "film_year": film_year,
            "tmdb_movie_id": tmdb_movie_id,
            "letterboxd_entry_url": entry_url,
            "watched_date": watched_date,
            "publication_date": publication_date,
            "rating": rating,
            "liked": liked,
            "rewatch": rewatch,
            "review_text": review_text,
            "poster_url": poster_url,
        }
        results.append(normalized_entry)

    return results


def load_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Any) -> None:
    serialized = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=False)
    json.loads(serialized)
    path.write_text(f"{serialized}\n", encoding="utf-8")


def validate_json_files(paths: list[Path]) -> None:
    for path in paths:
        with path.open("r", encoding="utf-8") as handle:
            json.load(handle)


def merge_entries(previous_entries: list[dict[str, Any]], new_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}

    for entry in previous_entries:
        merged[dedupe_key(entry)] = entry

    for entry in new_entries:
        key = dedupe_key(entry)
        merged[key] = merge_entry_record(merged.get(key), entry)

    return list(merged.values())


def merge_entry_record(existing: dict[str, Any] | None, incoming: dict[str, Any]) -> dict[str, Any]:
    if existing is None:
        return incoming

    merged = dict(existing)
    for key, value in incoming.items():
        if value is not None and value != "":
            merged[key] = value
    return merged


def dedupe_key(entry: dict[str, Any]) -> str:
    guid = entry.get("guid")
    if guid:
        return f"guid:{guid}"
    return f"fallback:{entry.get('username', '')}:{entry.get('letterboxd_entry_url', '')}"


def sort_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        entries,
        key=lambda item: (
            parse_iso_date(item.get("publication_date")),
            parse_iso_date(item.get("watched_date")),
            item.get("id", ""),
        ),
        reverse=True,
    )


def build_entry_id(username: str, guid: str | None, entry_url: str | None) -> str:
    if guid:
        return f"guid:{guid}"
    return f"fallback:{username}:{entry_url or ''}"


def extract_content_value(raw_value: Any) -> str:
    if isinstance(raw_value, list) and raw_value:
        first_item = raw_value[0]
        if isinstance(first_item, dict):
            return str(first_item.get("value", ""))
        return str(first_item)
    if isinstance(raw_value, dict):
        return str(raw_value.get("value", ""))
    if raw_value is None:
        return ""
    return str(raw_value)


def pick_first(mapping: Any, candidates: list[str]) -> Any:
    if hasattr(mapping, "get"):
        for candidate in candidates:
            value = mapping.get(candidate)
            if value not in (None, "", []):
                return value
    return None


def extract_clean_lines(soup: BeautifulSoup) -> list[str]:
    lines: list[str] = []

    for text in soup.stripped_strings:
        cleaned = normalize_whitespace(text)
        if cleaned:
            lines.append(cleaned)

    return lines


def build_metadata_map(lines: list[str]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}

    for line in lines:
        normalized_line = normalize_token(line)
        if ":" in line:
            label, raw_value = [segment.strip() for segment in line.split(":", 1)]
            for field_name, pattern in LABEL_PATTERNS.items():
                if pattern.search(label):
                    metadata[field_name] = raw_value
        else:
            lowered = normalized_line.casefold()
            if lowered == "liked":
                metadata["liked"] = True
            elif lowered == "rewatch":
                metadata["rewatch"] = True

    return metadata


def extract_film_identity(entry: Any, metadata_map: dict[str, Any], title: str | None) -> tuple[str | None, int | None]:
    explicit_title = pick_first(
        entry,
        [
            "letterboxd_filmtitle",
            "film_title",
        ],
    )
    explicit_year = pick_first(
        entry,
        [
            "letterboxd_filmyear",
            "film_year",
        ],
    )

    if explicit_title is None:
        explicit_title = metadata_map.get("film_title")
    if explicit_year is None:
        explicit_year = metadata_map.get("film_year")

    if explicit_title:
        return normalize_whitespace(str(explicit_title)), safe_int(explicit_year)

    if not title:
        return None, safe_int(explicit_year)

    match = re.match(r"^(?P<title>.+?),\s*(?P<year>\d{4})(?:\s*[-\u2013\u2014]\s*(?P<rest>.*))?$", title)
    if match:
        return normalize_whitespace(match.group("title")), safe_int(match.group("year"))

    return normalize_whitespace(title), safe_int(explicit_year)


def extract_rating(entry: Any, metadata_map: dict[str, Any], title: str | None) -> float | None:
    numeric_candidate = pick_first(entry, ["letterboxd_rating", "rating"])
    if numeric_candidate not in (None, ""):
        try:
            return float(numeric_candidate)
        except (TypeError, ValueError):
            pass

    metadata_rating = metadata_map.get("rating")
    if metadata_rating not in (None, ""):
        star_rating = stars_to_rating(str(metadata_rating))
        if star_rating is not None:
            return star_rating
        try:
            return float(metadata_rating)
        except (TypeError, ValueError):
            pass

    if title:
        return stars_to_rating(title)

    return None


def extract_bool(entry: Any, metadata_map: dict[str, Any], field_name: str) -> bool | None:
    candidate = pick_first(
        entry,
        [
            f"letterboxd_{field_name}",
            field_name,
        ],
    )
    parsed_candidate = parse_bool(candidate)
    if parsed_candidate is not None:
        return parsed_candidate

    metadata_value = metadata_map.get(field_name)
    parsed_metadata = parse_bool(metadata_value)
    if parsed_metadata is not None:
        return parsed_metadata

    return None


def extract_tmdb_movie_id(
    entry: Any,
    metadata_map: dict[str, Any],
    html_value: str,
    entry_url: str | None,
) -> int | None:
    candidate = pick_first(
        entry,
        [
            "letterboxd_tmdbmovieid",
            "tmdb_movie_id",
            "tmdbid",
        ],
    )
    if candidate is None:
        candidate = metadata_map.get("tmdb_movie_id")
    if candidate is not None:
        direct_match = re.search(r"\d+", str(candidate))
        if direct_match:
            return int(direct_match.group(0))

    for source in (html_value or "", entry_url or ""):
        match = re.search(r"(?:themoviedb\.org/movie/|tmdb/)(\d+)", source)
        if match:
            return int(match.group(1))

    return None


def extract_poster_url(entry: Any, metadata_map: dict[str, Any], html_value: str) -> str | None:
    for key in ("media_content", "media_thumbnail"):
        value = entry.get(key) if hasattr(entry, "get") else None
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    url = item.get("url")
                    if url:
                        return str(url)

    if metadata_map.get("poster_url"):
        return str(metadata_map["poster_url"])

    soup = BeautifulSoup(html_value or "", "html.parser")
    image = soup.find("img")
    if image and image.get("src"):
        return str(image.get("src"))

    return None


def extract_watched_date(entry: Any, metadata_map: dict[str, Any], lines: list[str]) -> str | None:
    candidate = pick_first(
        entry,
        [
            "letterboxd_watcheddate",
            "watched_date",
        ],
    )
    watched_date = parse_date_string(candidate)
    if watched_date:
        return watched_date

    watched_date = parse_date_string(metadata_map.get("watched_date"))
    if watched_date:
        return watched_date

    for line in lines:
        if "watched" not in line.casefold():
            continue
        line_match = re.search(r"watched(?:\s+on)?\s+(.+?)(?:\.$|$)", line, re.IGNORECASE)
        if line_match:
            watched_date = parse_date_string(line_match.group(1).strip())
            if watched_date:
                return watched_date

    return None


def extract_publication_date(entry: Any) -> str | None:
    struct_time = pick_first(entry, ["published_parsed", "updated_parsed"])
    if struct_time:
        return datetime(*struct_time[:6], tzinfo=timezone.utc).date().isoformat()

    for key in ("published", "updated", "pubDate"):
        raw_value = entry.get(key) if hasattr(entry, "get") else None
        iso_value = parse_date_string(raw_value)
        if iso_value:
            return iso_value

    return None


def extract_creator_display_name(feed_info: Any, entry: Any) -> str | None:
    candidate = pick_first(entry, ["author", "dc_creator", "creator"])
    if candidate:
        return normalize_whitespace(str(candidate))

    author_detail = entry.get("author_detail") if hasattr(entry, "get") else None
    if isinstance(author_detail, dict) and author_detail.get("name"):
        return normalize_whitespace(str(author_detail["name"]))

    title = feed_info.get("title") if hasattr(feed_info, "get") else None
    if isinstance(title, str):
        match = re.search(r"by\s+(.+)$", title)
        if match:
            return normalize_whitespace(match.group(1))

    return None


def extract_review_text(lines: list[str], metadata_map: dict[str, Any]) -> str | None:
    filtered: list[str] = []

    metadata_values = {normalize_whitespace(str(value)).casefold() for value in metadata_map.values() if value not in (None, "")}

    for line in lines:
        lowered = normalize_token(line).casefold()
        if lowered in {"liked", "rewatch"}:
            continue
        if lowered == "tmdb":
            continue
        if lowered in metadata_values:
            continue
        if re.match(r"^(watched(?:\s+on)?\s+).+", line, re.IGNORECASE):
            continue
        if re.match(r"^(film\s*title|film\s*year|rating|tmdb|poster|liked|rewatch)\s*:", line, re.IGNORECASE):
            continue
        filtered.append(line)

    if not filtered:
        return None

    review_text = "\n".join(filtered)
    return review_text or None


def parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None

    normalized = normalize_whitespace(str(value)).casefold()
    if normalized in {"true", "yes", "y", "1", "liked", "rewatch"}:
        return True
    if normalized in {"false", "no", "n", "0", "not liked", "not rewatch"}:
        return False
    return None


def stars_to_rating(text: str) -> float | None:
    match = re.search(r"([★½]+)", text)
    if not match:
        return None

    value = 0.0
    for symbol in match.group(1):
        if symbol == "★":
            value += 1.0
        elif symbol == "½":
            value += 0.5
    return value


def parse_date_string(value: Any) -> str | None:
    if value in (None, ""):
        return None

    raw_value = normalize_whitespace(str(value))
    if not raw_value:
        return None

    iso_match = re.match(r"^\d{4}-\d{2}-\d{2}$", raw_value)
    if iso_match:
        return raw_value

    try:
        parsed = parsedate_to_datetime(raw_value)
    except (TypeError, ValueError, IndexError, OverflowError):
        parsed = None
    if parsed is not None:
        return parsed.date().isoformat()

    for pattern in DATE_PATTERNS:
        try:
            parsed = datetime.strptime(raw_value, pattern)
            return parsed.date().isoformat()
        except ValueError:
            continue

    return None


def safe_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value)).strip()


def normalize_token(value: str) -> str:
    return normalize_whitespace(value).strip(" .!?:;")


def parse_iso_date(value: Any) -> str:
    parsed = parse_date_string(value)
    return parsed or ""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def extract_guid(entry: Any, entry_url: str | None) -> str | None:
    guid = entry.get("guid") if hasattr(entry, "get") else None
    if guid:
        return str(guid)

    fallback_id = entry.get("id") if hasattr(entry, "get") else None
    if fallback_id and fallback_id != entry_url:
        return str(fallback_id)

    return None


def render_index_html(entries: list[dict[str, Any]], status_payload: dict[str, Any]) -> str:
    latest_entries = entries[:25]
    last_update = status_payload.get("last_successful_update") or "Never"
    total_entries = status_payload.get("total_archived_entries", len(entries))
    feed_status_rows = []

    for username, feed_status in status_payload.get("individual_feed_status", {}).items():
        state = feed_status.get("state", "unknown")
        error = feed_status.get("error") or ""
        feed_status_rows.append(
            f"""
            <tr>
              <td><a href="https://letterboxd.com/{username}/">{username}</a></td>
              <td>{escape_html(feed_status.get("critic_tier"))}</td>
              <td class="{escape_html(state)}">{escape_html(state)}</td>
              <td>{escape_html(feed_status.get("entries_fetched"))}</td>
              <td>{escape_html(feed_status.get("last_successful_fetch") or "Never")}</td>
              <td>{escape_html(error)}</td>
            </tr>
            """
        )

    entry_rows = []
    for entry in latest_entries:
        film_label = entry.get("film_title") or "Untitled"
        if entry.get("film_year"):
            film_label = f"{film_label} ({entry['film_year']})"
        rating = entry.get("rating")
        rating_label = rating if rating is not None else ""
        review = escape_html(entry.get("review_text") or "")
        entry_rows.append(
            f"""
            <tr>
              <td>{escape_html(entry.get("publication_date") or "")}</td>
              <td><a href="{escape_html(entry.get("letterboxd_entry_url"))}">{escape_html(film_label)}</a></td>
              <td>{escape_html(entry.get("username"))}</td>
              <td>{escape_html(entry.get("critic_tier"))}</td>
              <td>{escape_html(rating_label)}</td>
              <td>{escape_html("yes" if entry.get("liked") else "no" if entry.get("liked") is False else "")}</td>
              <td>{escape_html("yes" if entry.get("rewatch") else "no" if entry.get("rewatch") is False else "")}</td>
              <td>{review}</td>
            </tr>
            """
        )

    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Letterboxd RSS Aggregator</title>
    <style>
      :root {{
        color-scheme: light;
        --bg: #f6f1e8;
        --card: #fff9f0;
        --ink: #1d1a17;
        --muted: #695f56;
        --line: #d9ccb9;
        --ok: #1f7a4d;
        --error: #b63e2a;
        --accent: #d65a31;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        font-family: Georgia, "Iowan Old Style", serif;
        color: var(--ink);
        background:
          radial-gradient(circle at top right, rgba(214, 90, 49, 0.18), transparent 32%),
          linear-gradient(180deg, #fefbf6 0%, var(--bg) 100%);
      }}
      main {{
        max-width: 1100px;
        margin: 0 auto;
        padding: 40px 20px 64px;
      }}
      h1, h2 {{
        font-family: "Avenir Next Condensed", "Arial Narrow", sans-serif;
        letter-spacing: 0.04em;
        text-transform: uppercase;
      }}
      .hero {{
        padding: 28px;
        border: 1px solid var(--line);
        background: rgba(255, 249, 240, 0.92);
        box-shadow: 0 20px 60px rgba(29, 26, 23, 0.08);
      }}
      .stats {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 12px;
        margin-top: 18px;
      }}
      .stat {{
        padding: 16px;
        border: 1px solid var(--line);
        background: var(--card);
      }}
      .stat strong {{
        display: block;
        font-size: 1.5rem;
        margin-top: 6px;
      }}
      table {{
        width: 100%;
        border-collapse: collapse;
        margin-top: 18px;
        background: rgba(255, 255, 255, 0.82);
      }}
      th, td {{
        padding: 12px;
        border-bottom: 1px solid var(--line);
        text-align: left;
        vertical-align: top;
      }}
      th {{
        font-family: "Avenir Next Condensed", "Arial Narrow", sans-serif;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        font-size: 0.85rem;
      }}
      .ok {{
        color: var(--ok);
        font-weight: 700;
      }}
      .error {{
        color: var(--error);
        font-weight: 700;
      }}
      a {{
        color: var(--accent);
      }}
      .section {{
        margin-top: 28px;
        padding: 24px;
        border: 1px solid var(--line);
        background: rgba(255, 249, 240, 0.92);
      }}
      .muted {{
        color: var(--muted);
      }}
      @media (max-width: 720px) {{
        main {{
          padding: 20px 12px 40px;
        }}
        table, thead, tbody, th, td, tr {{
          display: block;
        }}
        thead {{
          display: none;
        }}
        td {{
          padding: 10px 12px;
        }}
      }}
    </style>
  </head>
  <body>
    <main>
      <section class="hero">
        <h1>Letterboxd RSS Aggregator</h1>
        <p class="muted">Public archive for recent activity across the configured Letterboxd accounts.</p>
        <div class="stats">
          <div class="stat">
            Last Update
            <strong>{escape_html(last_update)}</strong>
          </div>
          <div class="stat">
            Feeds Checked
            <strong>{escape_html(len(status_payload.get("individual_feed_status", {})))}</strong>
          </div>
          <div class="stat">
            Entries Fetched This Run
            <strong>{escape_html(status_payload.get("entries_fetched", 0))}</strong>
          </div>
          <div class="stat">
            Total Archived Entries
            <strong>{escape_html(total_entries)}</strong>
          </div>
        </div>
      </section>

      <section class="section">
        <h2>Feed Health</h2>
        <table>
          <thead>
            <tr>
              <th>Username</th>
              <th>Tier</th>
              <th>Status</th>
              <th>Fetched</th>
              <th>Last Success</th>
              <th>Error</th>
            </tr>
          </thead>
          <tbody>
            {''.join(feed_status_rows)}
          </tbody>
        </table>
      </section>

      <section class="section">
        <h2>Latest 25 Entries</h2>
        <table>
          <thead>
            <tr>
              <th>Published</th>
              <th>Film</th>
              <th>User</th>
              <th>Tier</th>
              <th>Rating</th>
              <th>Liked</th>
              <th>Rewatch</th>
              <th>Review</th>
            </tr>
          </thead>
          <tbody>
            {''.join(entry_rows)}
          </tbody>
        </table>
      </section>
    </main>
  </body>
</html>
"""


def escape_html(value: Any) -> str:
    text = "" if value is None else str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
