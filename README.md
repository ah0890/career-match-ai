# CareerMatch AI

AI-powered job discovery and career assistant that searches relevant job listings, matches them against uploaded CVs, evaluates ATS compatibility, researches companies, generates tailored interview preparation plans, and tracks job applications.

> **Status:** early development (Milestone 3 — CV upload and extraction). All nine sections are navigable with a consistent design system, and CVs can be uploaded and their text extracted. Features that are not built yet show honest empty states; nothing in the app is simulated or fabricated.

## Planned features

| Area | Status |
| --- | --- |
| Application shell, navigation, design tokens | ✅ Done |
| Design system (cards, badges, notices, metrics, steps) | ✅ Done |
| CV upload & extraction (PDF, DOCX) | ✅ Done |
| CV parsing & ATS compatibility analysis | Planned |
| Multi-source job search via authorised providers | Planned |
| Explainable CV-to-job matching & recommendations | Planned |
| Company intelligence with source attribution | Planned |
| Interview preparation & study plans | Planned |
| Application tracker & dashboard | Planned |
| CV version management | Planned |

Job sources are integrated only through official APIs, authorised search providers, or public feeds whose terms permit it. A source is listed as supported only once an adapter genuinely returns results.

## Architecture

```text
app.py                 Streamlit entry point (theme, logo, navigation)
assets/                Brand logo and icon (SVG)
config/settings.py     Typed, validated configuration (env vars / .env)
src/cv/extraction.py   CV validation and in-memory PDF/DOCX text extraction
src/cv/session.py      The active CV for the current browser session
src/pages/             One module per page, each exposing render()
src/ui/tokens.py       Design tokens — colours, type scale, spacing, radii
src/ui/theme.py        Stylesheet generated from tokens (targets only cm-* classes)
src/ui/components.py   Reusable, HTML-escaped components (cards, badges, notices…)
src/ui/layouts.py      Shared page patterns (empty states with next actions)
src/ui/navigation.py   Grouped page registry, sidebar navigation, page switching
.streamlit/config.toml Streamlit theme (mirrors tokens; enforced by tests)
tests/                 pytest suite (unit + offline integration)
data/                  Local, git-ignored storage for the database and private files
```

Business logic, provider integrations, persistence and presentation will live in separate packages under `src/` as they are implemented.

## CV upload and extraction

- Accepted formats: **PDF** and **DOCX** (legacy `.doc` is rejected with a conversion hint). Default size limit 5 MB (`CAREERMATCH_MAX_UPLOAD_MB`).
- Files are checked by extension **and** by content signature; damaged, empty, password-protected, oversized (more than 30 pages) and disguised files are rejected with a clear explanation.
- Text is extracted **in memory** with PyMuPDF (PDF) and python-docx (DOCX). No temporary files are written, and the original file bytes are discarded after extraction.
- DOCX extraction keeps document order, including tables, list bullets and contact details placed in the page header.
- **Scanned / image-only PDFs** are detected and reported — never treated as an empty CV. Partially scanned PDFs list the pages that could not be read. OCR is not included; export a text-based PDF or DOCX instead.
- The extracted text is held only in the current browser session and is removed when you delete the CV, refresh or close the page.

## Design system

- **Colours:** navy primary, restrained indigo accent, soft neutral surfaces. Status colours (success, warning, danger) are always paired with a text label and meet WCAG 2.2 AA contrast (checked by tests).
- **Type:** system sans-serif stack (Inter or Manrope when installed locally — no web fonts are downloaded).
- **Spacing:** 8px rhythm; consistent radii and subtle shadows.
- **Icons:** Material Symbols, rendered by Streamlit, used as the single icon family.
- **Styling approach:** Streamlit widgets are themed through `.streamlit/config.toml`; custom CSS targets only CareerMatch's own `cm-*` classes, so it does not depend on Streamlit's internal DOM.

## Requirements

- Python 3.11+ (developed and tested on Python 3.13, Windows 11)
- Dependencies pinned in `requirements.txt`

## Installation (Windows / PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env   # optional — defaults work without it
streamlit run app.py
```

macOS / Linux: use `source .venv/bin/activate` and `cp .env.example .env`.

## Configuration

All settings use the `CAREERMATCH_` prefix and can be set in `.env` (see `.env.example`). Invalid values stop the app at start-up with a clear error.

| Variable | Default | Meaning |
| --- | --- | --- |
| `CAREERMATCH_DATABASE_URL` | `sqlite:///data/careermatch.db` | Local database location |
| `CAREERMATCH_MAX_UPLOAD_MB` | `5` | Maximum CV upload size |
| `CAREERMATCH_THRESHOLD_APPLY` | `80` | Minimum score for **APPLY** |
| `CAREERMATCH_THRESHOLD_IMPROVE` | `70` | Minimum score for **APPLY AFTER IMPROVEMENT** |
| `CAREERMATCH_WEIGHT_*` | see below | Match-score weights (must be ≥ 0 and sum to 100) |

### Default match-score weights

| Component | Weight |
| --- | ---: |
| ATS and CV compatibility | 20% |
| Required skills | 25% |
| Relevant experience | 20% |
| Job responsibilities | 15% |
| Education and certifications | 10% |
| Keywords and semantic relevance | 10% |

The match score will be an **estimated CV-to-job compatibility score**. It is not a probability of being shortlisted or hired, and recommendation thresholds are prioritisation guidance only.

## Running tests

```powershell
python -m pytest
```

Tests run offline and need no credentials or paid APIs.

### Visual QA (optional, development only)

Rendered-UI screenshots are taken with Playwright, which is not needed to run the app:

```powershell
pip install -r requirements-dev.txt
python -m playwright install chromium
```

## Privacy

- CVs and career data are treated as sensitive personal data and stay on your machine by default.
- Uploaded CVs are processed in memory; the original file is not stored and CV content is never logged.
- `.env`, databases, uploaded documents and everything under `data/` are git-ignored.
- No CV content is sent to external services unless an optional integration is added later and you explicitly consent.

This is a single-user local application. A shared or public deployment would need authentication, access control, secure hosting and production hardening first.

## Licence

To be decided by the repository owner.
