# CareerMatch AI

AI-powered job discovery and career assistant that searches relevant job listings, matches them against uploaded CVs, evaluates ATS compatibility, researches companies, generates tailored interview preparation plans, and tracks job applications.

> **Status:** early development (Milestone 1 — foundation). The application shell, configuration and design tokens are in place. Feature pages show an honest "not available yet" state until each feature is built and tested. Nothing in the app is simulated or fabricated.

## Planned features

| Area | Status |
| --- | --- |
| Application shell, navigation, design tokens | ✅ Foundation |
| Premium design system | Planned (Milestone 2) |
| CV upload & extraction (PDF, DOCX) | Planned |
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
app.py                 Streamlit entry point (theme + navigation)
config/settings.py     Typed, validated configuration (env vars / .env)
src/ui/tokens.py       Design tokens — colours, type scale, spacing, radii
src/ui/theme.py        Global stylesheet generated from tokens
src/ui/components.py   Reusable, HTML-escaped UI helpers
src/ui/navigation.py   Page registry and sidebar navigation
.streamlit/config.toml Streamlit theme (mirrors tokens; enforced by tests)
tests/                 pytest suite (unit + offline integration)
data/                  Local, git-ignored storage for the database and private files
```

Business logic, provider integrations, persistence and presentation will live in separate packages under `src/` as they are implemented.

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
- `.env`, databases, uploaded documents and everything under `data/` are git-ignored.
- No CV content is sent to external services unless an optional integration is added later and you explicitly consent.

This is a single-user local application. A shared or public deployment would need authentication, access control, secure hosting and production hardening first.

## Licence

To be decided by the repository owner.
