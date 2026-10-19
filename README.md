# CareerMatch AI

A personal career assistant that runs on your own computer. It searches permitted job sources, ranks every
job against your CV with the evidence behind each score, researches employers from attributed public
sources, prepares you for interviews and tracks your applications.

Every score is produced by transparent, explainable rules — you can see exactly why a job scored as it did.
Nothing is simulated or invented: unknown information is shown as "not provided", and suggestions only ever
ask you to state what is genuinely true. The core app needs no paid AI service.

> **Status:** the original plan (milestones 1–21) is complete. See [CHANGELOG.md](CHANGELOG.md) for what
> changed in each milestone and the [roadmap](#roadmap) for what comes next.

## Contents

- [Quick start](#quick-start)
- [What you can do](#what-you-can-do)
- [How scores and recommendations work](#how-scores-and-recommendations-work)
- [Job sources](#job-sources)
- [Privacy and data](#privacy-and-data)
- [Configuration](#configuration)
- [Testing](#testing)
- [Architecture](#architecture)
- [Roadmap](#roadmap)
- [Troubleshooting](#troubleshooting)

## Quick start

Requires Python 3.11+ (developed and tested on Python 3.13, Windows 11).

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env   # optional — the defaults work without it
streamlit run app.py
```

On macOS or Linux use `source .venv/bin/activate` and `cp .env.example .env`. The app opens at
<http://localhost:8501> and is reachable only from your own computer.

## What you can do

A typical journey: **upload your CV → search for jobs → review ranked matches → research the employer →
prepare for the interview → track the application.**

| Page | What it does |
| --- | --- |
| **Dashboard** | Quick search, getting-started progress, and metrics and charts built only from your real activity: searches, strong matches, applications, follow-ups due. |
| **Find Jobs** | Searches the job sources you have enabled, with filters for location, country, work arrangement, experience level, employment type, date posted, skills and salary. Duplicates across sources are merged; every result links to its original listing. Recent searches can be run again. |
| **CV Analysis** | Upload a PDF or DOCX CV. Shows a transparent ATS compatibility score, section and contact detection, recognised skills and prioritised improvements. Paste any job description to compare it with your CV and get an improvement plan. |
| **Job Matches** | Every search result ranked against your CV, with a score breakdown, recommendation, essential requirements not found and the evidence behind each component. Filter, sort, compare up to three jobs side by side, and act on any job (improve your CV for it, research the company, prepare for the interview, save it to the tracker). |
| **Company Intelligence** | Looks up an employer on Wikidata and Wikipedia. You confirm which entry is meant; every fact links to its source and shows the date the source gives. Shows the employer's roles in your results. |
| **Interview Preparation** | Likely questions for a chosen job, each with why it may come up, the lines of your CV to draw on and how to prepare. A study plan covers the gaps, with Not started / Preparing / Prepared tracking. Plans can be downloaded as Markdown. |
| **Application Tracker** | Track applications from Saved to Offer with notes, applied date and follow-up dates. Every status change is recorded. Opening a link never changes a status — only you do. |
| **CV Versions** | Save tailored CVs (only with your consent), switch between them, compare two versions and see which one fits your latest results best. |
| **Settings** | Current scoring weights and thresholds, job-source status, stored data, and buttons to clear cached data and search history. |

## How scores and recommendations work

### Match score (0–100)

The match score estimates how well your CV **evidences** the requirements stated in a job description. It is
not a probability of being shortlisted or hired. It is a weighted average of six components:

| Component | Default weight | How it is assessed |
| --- | ---: | --- |
| CV readability (ATS) | 20% | Your general ATS compatibility score (below). |
| Required skills | 25% | Required skills found in your CV (85%) and preferred skills (15%). |
| Experience | 20% | Years from the dated roles in your CV against the years the job asks for (60%), and how closely your experience relates to the job title (40%). |
| Responsibilities | 15% | How many key words of each listed responsibility appear in your CV. |
| Education | 10% | The degree level the job asks for against the highest level in your CV. "Or equivalent experience" earns partial credit. |
| Job keywords | 10% | Terms the description repeats, other than recognised skills. |

Two rules keep the score fair:

- **Missing job information never counts against you.** If the job states no degree requirement, education is
  "not assessed" and its weight is shared among the other components.
- **Missing CV evidence is worded honestly.** Something the job asks for that your CV does not show scores zero
  and is described as "not found in your CV" — never as something you lack.

Each match also has a **confidence** level (High, Medium, Low) based on how detailed the job description is and
how much of the scoring weight could be assessed. Low-confidence matches are listed after the others and their
score is shown in a neutral colour.

### Recommendations

| Label | When |
| --- | --- |
| **APPLY** | Score at or above the APPLY threshold (default 80) and no essential requirement missing. |
| **APPLY AFTER IMPROVEMENT** | Score between the thresholds (default 70–79), or above 80 with an essential requirement your CV does not show. |
| **DON'T PRIORITIZE** | Score below the improvement threshold, or the listing has expired. |

Every label comes with its reasons, caveats (for example a possibly stale listing, or requirements such as right
to work that a CV cannot prove) and suggested actions built only from the detected gaps. Recommendations are
guidance for where to spend your effort, not a prediction.

### ATS compatibility score (0–100)

A rule-based estimate of how reliably software can read your CV. Every point comes from a named check shown in
the app.

| Component | Points | What is checked |
| --- | ---: | --- |
| Text readability | 20 | Text can be extracted, no scanned pages, clean characters, natural line breaks |
| Section organisation | 20 | Experience, Education, Skills and Summary sections; standard heading names |
| Contact information | 10 | Email, phone, optional profile link |
| Experience detail | 15 | Dated roles, one consistent date format, most recent role first |
| Content quality | 20 | Bullet points, action verbs, quantified results, no first-person pronouns, concise bullets |
| Length and formatting | 15 | 350–1,100 words, page count, little table layout, identifiable skills |

Bands: **Strong** (85+), **Good** (70–84), **Needs improvement** (50–69), **Significant issues** (below 50).
Applicant tracking systems differ between products and employers, so no score can predict a specific
employer's system. Scanned, image-only PDFs are detected and explained; OCR is not included.

## Job sources

Jobs come only from official APIs or public feeds whose terms permit it. Every result shows its source and
links to the original listing; a direct application link is shown only when the source provides one.

| Source | Status | Access | Notes |
| --- | --- | --- | --- |
| [Adzuna](https://www.adzuna.com) | ✅ Supported (free key) | Official API ([terms](https://developer.adzuna.com/docs/terms_of_service)) | On-site, hybrid and remote jobs in 19 countries; needs a country. Short description snippets. 25 requests/min, 250/day. Personal use permitted; commercial use needs Adzuna's consent. |
| [Himalayas](https://himalayas.app) | ✅ Supported | Public API ([terms](https://himalayas.app/api)) | Remote jobs worldwide with salaries and location restrictions. |
| [Jobicy](https://jobicy.com) | ✅ Supported | Public API ([terms](https://jobicy.com/jobs-rss-feed)) | Remote jobs from the last 7 days. |
| [Remote OK](https://remoteok.com) | ✅ Supported | Public API (terms in the response) | About 100 recent remote jobs, searched locally. |
| [Remotive](https://remotive.com) | ✅ Supported | Public API ([terms](https://github.com/remotive-io/remote-jobs-api)) | Remote jobs with a 24-hour delay. At most 4 new searches per day; results reused for 6 hours. |
| LinkedIn Jobs, Indeed, Glassdoor, Google Jobs, Bayt, GulfTalent, Naukrigulf, Rozee.pk, Mustakbil, Wellfound | ❌ Not supported | — | No public job-search API is available; automated scraping would breach their terms. |
| Arbeitnow, Jooble | ❌ Not integrated | — | Terms of use or official API documentation could not be verified. |

To enable Adzuna, register at <https://developer.adzuna.com/signup> and set `CAREERMATCH_ADZUNA_APP_ID` and
`CAREERMATCH_ADZUNA_APP_KEY` in `.env`. Any source can be switched off with `CAREERMATCH_<SOURCE>_ENABLED=false`.

- Each source is searched independently with timeouts, retries and back-off; one failing source never hides
  the others, and failed sources can be retried.
- Responses and daily request counts are stored locally, so restarting the app never repeats requests or
  resets a source's daily limit. Cached results are labelled with the time they were retrieved.
- Filters a source cannot apply are listed per source rather than silently ignored.
- The same vacancy from several sources is shown once, with links to every source. Freshness labels (Recent,
  Older, Possibly stale, Expired, Date not provided) rely only on dates the source supplies.

**Company research** uses [Wikidata](https://www.wikidata.org) (CC0) and [Wikipedia](https://en.wikipedia.org)
(CC BY-SA 4.0) through their public APIs, with attribution and a link for every fact. Only the company name is
sent.

### Adding a job source

1. Create `src/providers/adapters/<name>.py` with a `JobProvider` subclass: fill in `ProviderInfo` (coverage,
   access, terms URL, attribution, supported filters), implement `missing_configuration()` and `search()`
   returning normalised `JobPosting` objects.
2. Make every request through `ProviderHttp` with a `RequestPolicy` that respects the source's limits.
3. Read credentials from `CAREERMATCH_*` settings and document them in `.env.example`.
4. Register the class in `PROVIDER_CLASSES` (`src/providers/registry.py`) and add tests with mocked responses.

## Privacy and data

| Data | Where | When |
| --- | --- | --- |
| Uploaded CV file | Nowhere — processed in memory and discarded | Never stored |
| CV text | Browser session | Until you delete it, refresh or close the page |
| CV versions (text only) | Local database | Only if you save them, with consent; until you delete them |
| Applications, notes, study progress | Local database | Until you delete them |
| Search history, cached job data | Local database | Clearable in Settings |

- The database is at `data/careermatch.db` by default and is **not encrypted** — use disk encryption if others
  can access your computer. `.env`, `data/` and `*.db` are git-ignored.
- Only search terms (to job sources) and company names (to Wikidata and Wikipedia) leave your computer. CV
  content is never sent anywhere, and never logged.
- The app listens on `localhost` only. It is a single-user local application: do not expose it on a network
  without authentication and hardening. See [SECURITY.md](SECURITY.md) for the threat model and controls.

## Configuration

All settings use the `CAREERMATCH_` prefix and can be set in `.env` (see `.env.example`). Invalid values stop
the app at start-up with a clear error.

| Variable | Default | Meaning |
| --- | --- | --- |
| `CAREERMATCH_DATABASE_URL` | `sqlite:///data/careermatch.db` | Local database location |
| `CAREERMATCH_MAX_UPLOAD_MB` | `5` | Maximum CV upload size |
| `CAREERMATCH_THRESHOLD_APPLY` | `80` | Minimum score for **APPLY** |
| `CAREERMATCH_THRESHOLD_IMPROVE` | `70` | Minimum score for **APPLY AFTER IMPROVEMENT** |
| `CAREERMATCH_WEIGHT_ATS`, `_REQUIRED_SKILLS`, `_EXPERIENCE`, `_RESPONSIBILITIES`, `_EDUCATION`, `_KEYWORDS` | 20, 25, 20, 15, 10, 10 | Match-score weights (must be ≥ 0 and sum to 100) |
| `CAREERMATCH_OFFLINE_MODE` | `false` | Block every external request |
| `CAREERMATCH_HTTP_TIMEOUT_S` | `15` | Timeout per request to a source |
| `CAREERMATCH_<SOURCE>_ENABLED` | `true` | Switch a source off (`REMOTIVE`, `HIMALAYAS`, `JOBICY`, `REMOTEOK`, `ADZUNA`) |
| `CAREERMATCH_ADZUNA_APP_ID`, `CAREERMATCH_ADZUNA_APP_KEY` | — | Adzuna credentials |
| `CAREERMATCH_ADZUNA_DEFAULT_COUNTRY` | — | Two-letter country code used when a search gives none |

## Testing

```powershell
python -m pytest                     # unit and integration tests — offline, no credentials needed
```

The default suite never contacts the internet (HTTP is mocked and offline mode is forced) and always uses a
temporary database, never your real one. It includes security regression tests that pass hostile content
through every HTML builder.

**End-to-end browser journeys** (optional) start the real app in offline mode with a temporary database and
drive it with Playwright:

```powershell
pip install -r requirements-dev.txt
python -m playwright install chromium
$env:CAREERMATCH_RUN_E2E = "1"; python -m pytest tests/e2e
```

## Architecture

```text
app.py                 Streamlit entry point (theme, logo, navigation)
config/settings.py     Typed, validated configuration (environment variables / .env)
src/cv/                Upload validation and extraction, parsing, ATS scoring, session, saved versions
src/jobs/              Job models, normalisation, deduplication, freshness, local filtering
src/providers/         Job-source interface, HTTP layer (timeouts, retries, budgets, cache), registry, adapters
src/matching/          Skill taxonomy, requirement extraction, matching engine, recommendations,
                       filtering and comparison, CV improvement plan
src/company/           Company lookup (Wikidata, Wikipedia) and relevance to your search
src/interview/         Interview questions and study plans
src/tracker/           Application tracker operations
src/analytics/         Dashboard figures from real activity
src/db/                SQLAlchemy models and engine, persistent HTTP cache
src/services/          Search, matching cache, search history, shared runtime resources
src/pages/             One module per page, each exposing render()
src/ui/                Design tokens, theme, HTML-escaped components, cards, charts
tests/                 Unit, integration (headless Streamlit) and optional end-to-end tests
data/                  Local, git-ignored storage for the database
```

Presentation code builds HTML through small, pure `*_html` functions that escape all content, so they can be
unit-tested; Streamlit widgets are themed through `.streamlit/config.toml`, and custom CSS targets only the
app's own `cm-*` classes. Colours meet WCAG 2.2 AA contrast (checked by tests), and status is always shown with
a text label, never colour alone.

## Roadmap

The original plan (milestones 1–21) is complete. Planned next:

| Milestone | Area |
| --- | --- |
| 22 | Job-specific CV tailoring: preview suggested edits, accept or reject each, download DOCX and PDF, apply from the app, keep tailored versions |
| 23 | Chrome browser extension (Manifest V3) |
| 24 | Freemium plan: one free full job workflow, then a paid subscription with server-side entitlements |
| 25 | Integration, security and verification for the extension and subscription (needs a backend API with authentication) |
| 26 | Multi-language support: CV and job content in several languages, and an interface in English, Arabic, Urdu, Hindi, Spanish, French, German, Portuguese and Chinese (with right-to-left layouts) |
| — | Optional AI layer: only with your explicit consent and data minimisation; the app keeps working without it |

## Troubleshooting

| Problem | What to do |
| --- | --- |
| "Needs OCR" after uploading a PDF | The PDF is a scanned image. Export your CV from its original editor as a text-based PDF or DOCX. |
| A source shows "Not searched" | It is switched off, needs configuration (Adzuna), or offline mode is on — see Settings. |
| Remotive reports its daily limit | Remotive allows about four searches a day; results are reused for six hours. Try again tomorrow. |
| Very few jobs found | Use broader keywords, remove filters, or enable Adzuna for on-site jobs in your country. |
| A company is not found | Smaller or private employers are often not on Wikidata. Try the name without its legal suffix, or check the company's website. |
| The app is not reachable from another device | By design — it listens on `localhost` only. See [SECURITY.md](SECURITY.md) before changing this. |

## Licence

To be decided by the repository owner.
