# CareerMatch AI

AI-powered job discovery and career assistant that searches relevant job listings, matches them against uploaded CVs, evaluates ATS compatibility, researches companies, generates tailored interview preparation plans, and tracks job applications.

> **Status:** early development (Milestone 16 — caching and search history). CVs can be uploaded, parsed and analysed, real jobs can be searched across several permitted job sources at once, and results are ranked against your CV with the evidence behind every score, a recommendation (APPLY, APPLY AFTER IMPROVEMENT or DON'T PRIORITIZE), filters and side-by-side comparison. Each job also gets a CV improvement plan, sourced company research, interview preparation with a study plan, and can be saved to a local application tracker. Features that are not built yet show honest empty states; nothing in the app is simulated or fabricated. See [CHANGELOG.md](CHANGELOG.md) for what changed in each milestone.

## Planned features

| Area | Status |
| --- | --- |
| Application shell, navigation, design tokens | ✅ Done |
| Design system (cards, badges, notices, metrics, steps) | ✅ Done |
| CV upload & extraction (PDF, DOCX) | ✅ Done |
| CV parsing & ATS compatibility analysis | ✅ Done |
| Job provider architecture | ✅ Done |
| Multi-source discovery (Adzuna, Himalayas, Jobicy, Remote OK, Remotive) | ✅ Done |
| Normalisation, cross-source deduplication, freshness labels | ✅ Done |
| Explainable CV-to-job matching | ✅ Done |
| Recommendations (APPLY / IMPROVE / DON'T PRIORITIZE) | ✅ Done |
| Match filters, sorting and side-by-side comparison | ✅ Done |
| Keyword gaps and CV improvement suggestions | ✅ Done |
| Company intelligence with source attribution (Wikidata, Wikipedia) | ✅ Done |
| Interview preparation | ✅ Done |
| Study plans with progress tracking | ✅ Done |
| Application tracker (local SQLite) | ✅ Done |
| Persistent source caches, request budgets and search history | ✅ Done |
| Dashboard analytics | Planned |
| CV version management | Planned |

Job sources are integrated only through official APIs, authorised search providers, or public feeds whose terms permit it. A source is listed as supported only once an adapter genuinely returns results.

## Architecture

```text
app.py                 Streamlit entry point (theme, logo, navigation)
assets/                Brand logo and icon (SVG)
config/settings.py     Typed, validated configuration (env vars / .env)
src/cv/extraction.py   CV validation and in-memory PDF/DOCX text extraction
src/cv/session.py      The active CV for the current browser session
src/cv/parsing.py      Section, contact, date, bullet and skill parsing
src/cv/ats.py          Transparent ATS scoring and job keyword alignment
src/matching/skills.py Skill taxonomy and boundary-aware skill extraction
src/matching/          Requirement extraction, matching engine, recommendations, filtering/comparison, CV improvement plan
src/company/           Company lookup (Wikidata, Wikipedia) and relevance to your search
src/interview/         Interview preparation and study plans
src/db/                Local database (SQLAlchemy models, engine, persistent HTTP cache)
src/tracker/           Application tracker operations
src/jobs/              Job models, normalisation and local filtering
src/providers/         Provider interface, HTTP layer (timeouts, retries, budgets, cache), registry, adapters
src/services/          Multi-source search service and shared runtime resources
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

## Job sources

Jobs are retrieved only through official APIs or public feeds whose terms permit it. Every result shows the source it came from and links to the original listing. A "direct application" link is shown only when a source explicitly provides one — a listing page is never labelled as an application link.

| Source | Status | Access | Notes |
| --- | --- | --- | --- |
| [Adzuna](https://www.adzuna.com) | ✅ Supported (needs a free key) | Official API ([terms](https://developer.adzuna.com/docs/terms_of_service)) | On-site, hybrid and remote jobs in 19 countries (UK, US, Australia, Canada, Germany, France, India, and more). Requires a country. Descriptions are short snippets. Free keys: 25 requests/min, 250/day. Results are labelled "Adzuna" and linked as its terms require. Personal use is permitted; commercial use needs Adzuna's written consent. |
| [Himalayas](https://himalayas.app) | ✅ Supported | Public API, no key ([terms](https://himalayas.app/api)) | Remote jobs worldwide with salary and location restrictions. Results link back to Himalayas, and the listing link is the one it supplies for applying. |
| [Jobicy](https://jobicy.com) | ✅ Supported | Public API, no key ([terms](https://jobicy.com/jobs-rss-feed)) | Remote jobs from the last 7 days. Credited with a link; buttons use the original job URL. |
| [Remote OK](https://remoteok.com) | ✅ Supported | Public API, no key (terms in the API response) | Its current feed (about 100 recent remote jobs) is searched locally. Followed link-backs, as its terms require. |
| [Remotive](https://remotive.com) | ✅ Supported | Public API, no key ([terms](https://github.com/remotive-io/remote-jobs-api)) | Remote jobs, 24-hour listing delay. At most 4 new searches per day are sent; repeated searches reuse results for 6 hours. |
| LinkedIn Jobs, Indeed, Glassdoor, Google Jobs, Bayt, GulfTalent, Naukrigulf, Rozee.pk, Mustakbil, Wellfound | ❌ Not supported | — | No public job-search API is available to this app; automated scraping would breach their terms or bypass access controls. |
| Arbeitnow, Jooble | ❌ Not integrated | — | Their terms of use or official API documentation could not be verified. |

To enable Adzuna, register at <https://developer.adzuna.com/signup> and set `CAREERMATCH_ADZUNA_APP_ID` and `CAREERMATCH_ADZUNA_APP_KEY` in `.env`. Any source can be switched off with `CAREERMATCH_<SOURCE>_ENABLED=false`.

Behaviour:

- Each source is searched independently with timeouts, limited retries and back-off; one failing source never hides results from the others, and failed sources can be retried.
- Cached results are labelled as cached, with the time they were retrieved.
- Filters a source cannot apply (for example minimum salary) are listed per source rather than silently ignored. Remote-only sources are skipped for on-site or hybrid searches.
- Jobs with missing information (no location, type or date) are kept and labelled, not discarded or guessed.
- `CAREERMATCH_OFFLINE_MODE=true` blocks every external request.
- The automated tests never contact the internet: they use mocked HTTP transports, and offline mode is forced for every test.

### Duplicates and freshness

- **Duplicates:** the same vacancy from several sources is shown once, with links to every source that listed it. Postings are merged only on strong evidence — the same listing URL (ignoring tracking parameters), or the same employer with near-identical titles, matching seniority, compatible locations and similar descriptions. Similar but different roles (for example "Senior Data Analyst" and "Data Analyst") are kept separate.
- **Freshness:** *Recent* (posted 7 days ago or less), *Older* (8–30 days), *Possibly stale* (over 30 days), *Expired* (past an expiry date given by the source) and *Date not provided*. Labels rely only on dates supplied by the source. A listing being online does not confirm the job is still open.
- **Links:** the original listing and a direct application link are kept separate; a listing page is never presented as an application link.

### Adding a provider

1. Create `src/providers/adapters/<name>.py` with a `JobProvider` subclass: fill in `ProviderInfo` (coverage, access, terms URL, attribution, supported filters), implement `missing_configuration()` for required credentials, and `search()` returning a `SearchPage` of normalised `JobPosting` objects.
2. Use `ProviderHttp` for every request with a `RequestPolicy` that respects the source's rate limits.
3. Read credentials from settings (`CAREERMATCH_*` environment variables) and document them in `.env.example`.
4. Register the class in `PROVIDER_CLASSES` in `src/providers/registry.py` and add tests with mocked responses.

## ATS compatibility score

The general ATS score (0–100) is a transparent, rule-based estimate of how reliably software can read your CV. Every point comes from a named check that is shown in the app.

| Component | Points | What is checked |
| --- | ---: | --- |
| Text readability | 20 | Text can be extracted, no scanned pages, clean characters, natural line breaks |
| Section organisation | 20 | Experience, Education, Skills and Summary sections; standard heading names |
| Contact information | 10 | Email, phone, optional profile link |
| Experience detail | 15 | Dated roles, one consistent date format, most recent role first |
| Content quality | 20 | Bullet points, action verbs, quantified results, no first-person pronouns, concise bullets |
| Length and formatting | 15 | 350–1,100 words, page count, little table layout, identifiable skills |

Bands: **Strong** (85+), **Good** (70–84), **Needs improvement** (50–69), **Significant issues** (below 50).

**Limitations.** Applicant tracking systems differ between products and employer configurations, so this is not the score any real ATS will produce. Parsing is heuristic: anything shown as "Not found" was not detected in the text — it does not mean the candidate lacks it. Name and years of experience are labelled as estimates.

**Job keyword alignment** is reported separately: paste a job description to see which of its recognised skills and frequently repeated terms appear in your CV (70% skills, 30% other terms). Short descriptions are flagged as unreliable. Only add a missing term if it genuinely reflects your experience.

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

The match score is an **estimated CV-to-job compatibility score**. Components the job gives no information about are not assessed, and their weight is shared among the others. A job with an essential requirement your CV does not show is never marked APPLY. It is not a probability of being shortlisted or hired, and recommendation thresholds are prioritisation guidance only.

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
- CV text is kept only for the browser session, unless you explicitly save a CV version. Saved versions hold the extracted text (never the file) in the local, unencrypted database until you delete them.
- `.env`, databases, uploaded documents and everything under `data/` are git-ignored.
- The local database holds tracked applications, study progress, search history, cached job-source responses and — only if you save them — CV versions.
- No CV content is sent to external services unless an optional integration is added later and you explicitly consent.
- Company research sends only the company name to Wikidata and Wikipedia.

This is a single-user local application. A shared or public deployment would need authentication, access control, secure hosting and production hardening first.

## Licence

To be decided by the repository owner.
