# AGENTS.md

## Project architecture

- `src/letterboxd_rss_aggregator/cli.py`: command-line entrypoint with `run` and `validate` commands.
- `src/letterboxd_rss_aggregator/aggregator.py`: feed fetching, parsing, normalization, historical merge logic, JSON writing, and status-page rendering.
- `tests/fixtures/`: saved RSS XML used for deterministic parsing tests.
- `tests/test_aggregator.py`: unit coverage for normalization, deduplication, sorting, HTML generation, and JSON validation.
- `docs/`: published GitHub Pages artifacts.
- `.github/workflows/update-archive.yml`: scheduled archive refresh workflow.
- `.github/workflows/deploy-pages.yml`: Pages deployment workflow using the `docs/` directory.

## Safety and operating requirements

- Only read public Letterboxd RSS feeds.
- Always send an explicit user agent and a finite timeout with each HTTP request.
- Never fabricate missing RSS fields. Persist `null` when data is absent.
- Preserve historical entries indefinitely unless the project requirements change.
- Deduplicate by GUID first. If GUID is missing, fall back to `username + letterboxd_entry_url`.
- One failed feed must not stop the rest of the update run.
- Validate `docs/entries.json` and `docs/status.json` before committing them.
- Do not introduce API keys, secrets, paid services, or external databases.
- Keep tests fixture-based. Do not make CI depend on live Letterboxd availability.
- Treat `docs/` as the public artifact surface. Any schema changes there should be deliberate and documented.
