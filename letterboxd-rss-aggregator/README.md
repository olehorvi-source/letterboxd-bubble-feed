# Letterboxd RSS Aggregator

Small public Letterboxd RSS archive for GitHub Actions and GitHub Pages. It fetches a fixed set of public Letterboxd RSS feeds, normalizes the entries, preserves historical items after they disappear from RSS, and publishes machine-readable JSON for downstream consumers.

## Tracked accounts

### Primary

- `thejoshl`
- `jlalibs`
- `brofromanother`
- `bdgrabinski`

### Secondary

- `SeanFennessey`
- `SilentDawnLB`
- `davidlsims`
- `gemko`
- `BrianDuffield`
- `judysquirrels`
- `davidehrlich`

### My account

- `theolejake`

## Published outputs

After GitHub Pages is enabled, the public outputs live at:

- `https://YOUR_GITHUB_USERNAME.github.io/letterboxd-rss-aggregator/`
- `https://YOUR_GITHUB_USERNAME.github.io/letterboxd-rss-aggregator/entries.json`
- `https://YOUR_GITHUB_USERNAME.github.io/letterboxd-rss-aggregator/status.json`

Replace `YOUR_GITHUB_USERNAME` with the GitHub account that owns the repository.

## Local setup

1. Create a new GitHub repository named `letterboxd-rss-aggregator`.
2. Copy this project into that repository.
3. Use Python 3.12 in GitHub Actions. Local development also works on an older interpreter as long as the dependencies install.
4. Install dependencies:

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
```

5. Run tests:

```bash
PYTHONPATH=src python -m pytest
```

6. Run the aggregator:

```bash
PYTHONPATH=src python -m letterboxd_rss_aggregator run --output-dir docs
```

7. Validate the JSON artifacts:

```bash
PYTHONPATH=src python -m letterboxd_rss_aggregator validate docs/entries.json docs/status.json
```

## GitHub Actions

`/.github/workflows/update-archive.yml`:

- runs every 6 hours
- supports manual runs
- installs dependencies
- runs `pytest`
- updates `docs/entries.json`, `docs/status.json`, and `docs/index.html`
- validates JSON before any commit
- commits only when files under `docs/` changed

`/.github/workflows/deploy-pages.yml`:

- deploys the `docs/` folder to GitHub Pages on every push to `main`
- can also be triggered manually

## GitHub Pages setup

1. Push the repository to GitHub.
2. Open `Settings -> Pages`.
3. Set the source to `GitHub Actions`.
4. Let the `Deploy GitHub Pages` workflow publish the `docs/` directory artifact.

The deployed site serves:

- `/index.html`
- `/entries.json`
- `/status.json`

## Data model

Each normalized entry contains these fields when Letterboxd exposes them:

- `id`
- `guid`
- `username`
- `critic_tier`
- `creator_display_name`
- `film_title`
- `film_year`
- `tmdb_movie_id`
- `letterboxd_entry_url`
- `watched_date`
- `publication_date`
- `rating`
- `liked`
- `rewatch`
- `review_text`
- `poster_url`

Missing RSS values stay `null`. The aggregator never fabricates absent fields.

## Historical retention and deduplication

- GUID is the primary stable identifier when present.
- If GUID is missing, the fallback dedupe key is `username + letterboxd_entry_url`.
- Old entries remain in `docs/entries.json` even after they disappear from RSS.
- Entries are sorted newest first by publication date, then watched date.

## Testing

Tests use saved XML fixtures in [`tests/fixtures`](/Users/olehorvi/letterboxd-rss-aggregator/tests/fixtures) and never depend on live Letterboxd availability.

## Notes

- No paid services, databases, API keys, or secrets are required.
- Individual feed failures are recorded in `docs/status.json` and do not stop the remaining feeds from updating.
- If every feed fails in one run, the CLI exits non-zero so the workflow surfaces the outage.
