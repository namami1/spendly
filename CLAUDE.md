# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**Spendly** — a personal expense tracker built with Flask, Jinja2 templates, vanilla JS, and SQLite. This is a **teaching scaffold**: the landing/auth-page UI is built out, but most functionality is stubbed for a student to implement in numbered steps. Placeholder routes in [app.py](app.py) (logout, profile, expenses add/edit/delete) return literal "coming in Step N" strings, and [database/db.py](database/db.py) is an empty spec to be filled in (Step 1). When asked to add features, follow the step the route/file points to rather than inventing a new architecture.

## Commands

```powershell
# Set up (Windows venv already exists at .venv)
pip install -r requirements.txt

# Run the dev server — note the non-default port
python app.py            # serves on http://127.0.0.1:5001 with debug=True

# Tests (pytest + pytest-flask are installed; no test files exist yet)
pytest                   # run all
pytest path/to/test_x.py::test_name   # run a single test
```

## Architecture

- **[app.py](app.py)** — the entire Flask app: one module, route functions only, each rendering a template via `render_template`. No blueprints. Real routes: `/`, `/register`, `/login`, `/terms`, `/privacy`. Everything else is a placeholder.
- **[database/db.py](database/db.py)** — intended to expose `get_db()` (SQLite connection with `row_factory` + foreign keys on), `init_db()` (CREATE TABLE IF NOT EXISTS), and `seed_db()`. Currently unwritten. The DB file `expense_tracker.db` is gitignored.
- **templates/** — Jinja2. [base.html](templates/base.html) defines the shell (navbar, footer, `{% block title %}`, `{% block head %}`, `{% block content %}`); all pages extend it. Brand mark is the `◈` glyph; product name "Spendly".
- **static/css/** — `style.css` is the global/base stylesheet (loaded by base.html); `landing.css` is page-specific. Fonts: DM Serif Display (headings) + DM Sans (body), loaded from Google Fonts in base.html.
- **static/js/main.js** — single shared JS file, currently empty.

## Conventions

- **Vanilla JS only** — no frameworks or front-end build step. Interactive features (e.g. the landing-page video modal) are hand-written JS inline in the template or in main.js.
- **Page-scoped changes** — feature requests here are typically surgical ("modify only the hero section", "do not touch any other part of the page"). Prefer minimal, contained edits over refactors.
- **Commit message style** — `area: imperative summary`, e.g. `landing: add privacy policy page and route`.
- `.claude/plans/` is gitignored.
