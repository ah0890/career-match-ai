# Changelog

All notable changes to CareerMatch AI are recorded here, newest first. Each milestone is one
entry; the format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Sections used in each entry: **Added**, **Changed**, **Fixed**, **Security**, **Notes** (limitations
and decisions worth knowing).

## [Unreleased]

### Planned
- Milestone 11 — keyword gaps and CV improvement suggestions for a chosen job, based only on what the
  CV already contains.

## Milestone 10 — Match filters, sorting and comparison — 2026-10-19 (`ac1afdd`)

### Added
- Filters on Job Matches: recommendation, minimum score, source, work arrangement, only jobs with no
  essential gaps, limited-information jobs and expired listings (hidden by default).
- Sorting by recommendation, score or posting date.
- Side-by-side comparison of two or three jobs: score components, essential gaps, missing and found
  skills, location, work arrangement, salary, posting date, freshness and source.
- Full job description with its original line breaks.
- Results are paged, 15 jobs per page.

### Notes
- Jobs without a posting date sort after dated ones (their age is unknown, not new), and
  low-confidence matches always stay after the others.
- Unknown values in the comparison are shown as "Not provided", never estimated.
- 360 offline tests.

## Milestone 9 — Recommendations — 2026-10-19 (`07cdaff`)

### Added
- APPLY, APPLY AFTER IMPROVEMENT and DON'T PRIORITIZE for every match, from the configured
  thresholds (defaults 80 and 70).
- Reasons for each label, and caveats for possibly stale listings, limited job information and
  requirements to confirm yourself (for example, right to work).
- Suggested actions built from the detected gaps, highest priority first.
- Counts per recommendation on the Job Matches page; results ordered by recommendation, then score.

### Notes
- A job with an essential requirement the CV does not show is never marked APPLY, whatever its score.
- Expired listings are always DON'T PRIORITIZE.
- Actions only ask you to make explicit what you genuinely have ("if you have used any of them…");
  a years-of-experience gap is described honestly as something editing a CV cannot change.
- Recommendations are prioritisation guidance, not a prediction of being shortlisted or hired.
- 351 offline tests.

## Milestone 8 — Explainable CV-to-job matching — 2026-10-19 (`5f43e24`)

### Added
- Job requirement extraction from descriptions: required, preferred and essential skills, years of
  experience, degree level and responsibilities, using the ad's section headings ("Requirements",
  "Nice to have", "Responsibilities" and common variants) and wording ("must", "is a plus").
- Requirements a CV cannot prove (right to work, security clearance, driving licence, travel or
  relocation, shifts) listed as "Check these yourself"; they do not affect the score.
- Match score out of 100 from six weighted components: CV readability (ATS), required skills,
  experience, responsibilities, education and job keywords (weights from settings).
- Essential requirements not found in the CV are flagged with the job's own sentence, even when the
  overall score is high.
- Confidence level (High, Medium, Low) based on how detailed the description is and how much of the
  scoring weight could be assessed.
- Job Matches page: search results ranked against the active CV, with score, confidence, skills found
  and missing, and a per-job score breakdown with evidence and gaps.

### Changed
- Job cards can show a match summary while keeping source attribution and original-listing links.
- Deleting the CV also clears its match results.

### Notes
- Information the job does not state (for example, no degree requirement) is "not assessed" and its
  weight is shared among the other components; it never counts against the candidate.
- Something the job asks for that the CV does not show scores zero and is worded "not found in your
  CV", never "you lack it".
- Jobs with too little information are ranked after the others, and their score is shown neutrally.
- Matching is keyword- and word-form-based; responsibilities described in different words may not be
  credited. Only the degree level is compared, not its subject.
- 337 offline tests.

## Milestone 7 — Normalisation, deduplication and freshness — 2026-10-18 (`c86b5a7`)

### Added
- Company and title normalisation (legal suffixes, remote markers, Sr/Jr) and canonical URLs without
  tracking parameters.
- Conservative cross-source deduplication; other sources of the same vacancy shown as "Also listed on".
- Evidence-based freshness labels: Recent, Older, Possibly stale, Expired, Date not provided.
- Expiry dates from Himalayas.

### Changed
- The richest posting is kept as the primary one; a missing posting date is filled from another
  source of the same vacancy.
- The results header reports how many duplicates were merged.

### Notes
- A listing being online never implies the job is open; listing pages are never presented as
  application links.
- 282 offline tests.

## Milestone 6 — Multi-source job discovery — 2026-10-18 (`1814d78`)

### Added
- Job sources with verified terms: Himalayas, Jobicy and Remote OK (public APIs) and Adzuna (official
  API with a free key, 19 countries).
- Country filter, salary period support and per-source enable switches.
- Notes on every search for filters a source cannot apply.

### Security
- Adzuna credentials are read from the environment as secrets and never shown in errors.

### Notes
- Source attribution links are followed link-backs where the terms require it; the Adzuna label is
  sized as its terms specify.
- Arbeitnow and Jooble are not integrated because their terms or documentation could not be verified.
- 249 offline tests.

## Milestone 5 — Job search provider architecture — 2026-10-18 (`29be188`)

### Added
- Shared search and job models with safe URL validation; unknown fields stay empty.
- Provider interface, error types and registry, including a documented list of unsupported sources
  (LinkedIn, Indeed, Glassdoor, Google Jobs, Bayt and others without a permitted API).
- HTTP layer with timeouts, retries, per-source pacing, daily request budgets, caching and offline
  mode.
- Remotive source (public API) within its limit of 4 requests per day and a 6-hour cache.
- Find Jobs runs real searches and shows each source's status (live, cached, failed, not searched).

### Security
- Error messages never include URLs or credentials.

### Notes
- Tests never reach the network (forced offline mode, mocked transports). 226 offline tests.

## Milestone 4 — CV parsing and ATS analysis — 2026-10-18 (`9eedf43`)

### Added
- Skill taxonomy (technical, tools, methods, standards, business, professional skills, languages)
  with boundary-aware matching.
- CV parser: sections, contact details, date ranges, estimated experience and bullet statistics.
- Transparent 100-point ATS compatibility score across six components, with explanations and
  prioritised recommendations.
- Keyword comparison against a pasted job description, flagged as unreliable for short descriptions.
- CV Analysis report tabs: ATS compatibility, structure and details, skills, job comparison.

### Notes
- 170 offline tests.

## Milestone 3 — Secure CV upload and text extraction — 2026-10-18 (`451812f`)

### Added
- PDF and DOCX upload with in-memory text extraction, keeping sections, bullets, DOCX tables and
  header contact details.
- Detection of scanned or partly scanned PDFs, with guidance instead of treating them as empty.
- CV Analysis page: upload, replace, extraction summary, text preview and confirmed deletion.

### Security
- Uploads validated by extension, size and file signature; legacy .doc, empty, damaged, disguised,
  encrypted and oversized files are rejected.
- No temporary files; raw bytes are discarded after extraction and CV content is never logged.

### Notes
- 104 offline tests using fictional CV fixtures.

## Milestone 2 — UI design system and navigation — 2026-10-18 (`48c288a`)

### Added
- Brand logo and grouped sidebar navigation (Overview, Discover, Prepare, Track, Account).
- Reusable, HTML-escaped components: headers, badges, notices, metric and feature grids, step lists,
  key-value cards and empty states with next actions.
- Dashboard quick search, Find Jobs form with validation, and a Settings page showing the configured
  weights and thresholds.
- Honest empty states for pages not yet backed by data; responsive layouts.

### Notes
- 65 offline tests.

## Milestone 1 — Foundation — 2026-10-18 (`34d5bbf`)

### Added
- Typed, validated configuration (scoring weights must sum to 100; thresholds must be ordered).
- Design tokens, stylesheet and Streamlit theme.
- Application shell with navigation for all nine sections.
- Pinned dependencies, `.env.example` and a privacy-focused `.gitignore`.
- README with setup, configuration and scoring method.

### Notes
- 25 offline tests, including WCAG contrast checks.
