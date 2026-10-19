# Changelog

All notable changes to CareerMatch AI are recorded here, newest first. Each milestone is one
entry; the format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Sections used in each entry: **Added**, **Changed**, **Fixed**, **Security**, **Notes** (limitations
and decisions worth knowing).

## [Unreleased]

### Planned

- Milestones 23–25 — Chrome extension, freemium plan and their integration and security verification. These
  need a backend API with user accounts.
- Milestone 26 — multi-language support.

## Adzuna removed — 2026-10-19

### Removed

- The Adzuna job source, its settings and its tests: its API needs paid access, and CareerMatch AI uses only
  free sources. It is listed under unsupported sources with the reason.

### Notes

- The remaining sources (Himalayas, Jobicy, Remote OK, Remotive) list remote jobs; an on-site search skips them
  and says why. Remove any `CAREERMATCH_ADZUNA_*` lines from your `.env` (they are ignored if left in).

## Email-based application tracking — 2026-10-19 (`d6a8d13`, `2f4d7d6`, `d0e0acb`, `9e32d2b`)

### Added

- Recruitment statuses: Application Submitted, Application Received, Under Review, Assessment, Interview
  Invitation, Interview Scheduled, Interview Completed, Offer Received, Rejected, Withdrawn, and a derived
  No Response after a configurable period without activity.
- A dated timeline for every application, interview and offer counts with corrections, interview date and
  notes, and the address and subject an application was emailed to (also recorded from Tailor CV).
- Tracker dashboard with nine summary cards and documented counting rules, and a searchable, filterable,
  sortable, paginated table with a details panel.
- Email Tracking page: connect Gmail or Outlook with read-only OAuth, sync now or automatically, review queue,
  sync history, disconnect and delete. `python -m src.mail sync` for scheduled syncs.
- Rule-based email classifier and reply matcher with confidence scores; uncertain results wait for review.

### Changed

- Older databases are migrated automatically: new columns are added, Applied / Interview / Offer become
  Application Submitted / Interview Scheduled / Offer Received, and the timeline is built from the existing
  status history.

### Security

- OAuth with PKCE and state checking; read-only scopes; tokens encrypted with a key held in the OS credential
  store; only job-related email details are kept, other emails only by id.

### Notes

- Live Gmail and Outlook access needs your own free OAuth app registration (see README). The sync was tested
  against simulated Gmail, Graph and OAuth services; it has not yet been run against a real mailbox.

## Design refresh — 2026-10-19

### Changed

- New palette: deep navy and slate with one crisp blue accent; every text pair still meets WCAG 2.2 AA.
- Dark navy navigation sidebar with a light logo.
- Dashboard opens with a welcome band holding the quick search.
- Each job on Job Matches is one card, with its details and actions inside it, and lifts on hover.
- Refined headers, metric cards, step numbers and chart cards; primary actions stand out on Tailor CV.

### Fixed

- A test now guards against anything tag-like in the stylesheet, which would make Streamlit drop it.

## Milestone 23a — Backend API with accounts — 2026-10-19

### Added

- A local backend API (`python -m src.api`, docs at `/api/docs`) with accounts: register, sign in, sign out,
  account summary and account deletion.
- Per-account CV upload (with consent; only the text is kept), job analysis with the full explainable match,
  recommendation and improvement suggestions, saved jobs, interview preparation, tailoring suggestions and
  tailored CVs as text, DOCX or PDF.
- New settings for the API database, host, port, sign-in duration and lockout.

### Security

- scrypt password hashing, hashed 256-bit bearer tokens with expiry, lockout after repeated failures and
  identical answers for wrong passwords and unknown emails.
- Every query is scoped to the signed-in account; CORS only for Chrome extensions and listed origins;
  security headers on every response; loopback-only by default.

### Notes

- Account data lives in its own database so the single-user app's data is never mixed with it.
- This is the groundwork for the Chrome extension (milestone 23) and the paid plan (milestone 24).

## Milestone 22 — Job-specific CV tailoring — 2026-10-19 (`d19f967`)

### Added

- **Tailor CV** page, also reachable from a "Tailor CV" button on every job in Job Matches.
- Suggested changes for the chosen job, each shown before and after and accepted or rejected individually:
  the job's skills first in your skills list, the most relevant achievements first within each role, and a
  summary line naming required skills your CV already shows (or a short summary if the CV has none).
- Adding a required skill your CV does not mention is off by default and needs you to confirm you genuinely
  have it.
- Editable final text with the match score before and after tailoring.
- DOCX and PDF downloads in a single-column, ATS-friendly layout with real, selectable text.
- Save the tailored CV as a CV version (with consent), open the verified application link, and mark the job
  as Applied in the tracker only when you confirm you submitted it.

### Notes

- Edits never reword bullets, move them between roles, or add employers, dates, projects or achievements.
  Your original CV is never changed.

## Milestone 21 — Documentation — 2026-10-19 (`60a844c`)

### Changed

- README rewritten as a complete guide: quick start, what each page does, how match scores, recommendations
  and the ATS score work, job and company sources, privacy and data, every configuration setting, testing
  (including end-to-end journeys), architecture, roadmap and troubleshooting.
- The README no longer describes the app as AI-powered: every score comes from transparent rules, and the
  optional AI layer is listed on the roadmap.

### Notes

- This completes the original plan (milestones 1–21).

## Milestone 20 — End-to-end testing and polish — 2026-10-19 (`4fbed70`)

### Added

- Optional end-to-end browser journeys (Playwright) against the real app in offline mode with a temporary
  database: every page opens without errors; upload, analyse, compare with a job and save a CV version with
  consent; add a tracked application and see it on the dashboard. Run with `CAREERMATCH_RUN_E2E=1`.

### Fixed

- Company search now retries without legal suffixes such as Corp or Ltd when the full name finds nothing
  (found while testing with live job data), and says which name was searched.
- Recommendation filter labels no longer truncate on narrower screens.
- Thinner bars on the applications-by-status chart.

### Notes

- The complete journey was verified against live job sources and Wikidata. Pages were checked at phone width
  with no horizontal scrolling.
- 463 offline tests, plus 3 end-to-end journeys.

## Milestone 19 — Security review — 2026-10-19 (`6446217`)

### Security

- The app now listens on `localhost` only, so other devices on the network cannot open your data;
  XSRF and CORS protection are set explicitly.
- Cross-source listing links ("Also listed on") are validated like every other link, and tracker links
  are re-checked when read from the database.
- Job-source responses larger than 10 MB are refused.
- The CV filename on CV Versions is shown as escaped text.
- Dependencies audited with `pip-audit`: no known vulnerabilities.

### Added

- `SECURITY.md`: threat model, what is stored and where, controls, known limitations and how to report
  issues.
- Security regression tests: hostile content through every HTML builder, unsafe URL schemes, tampered
  database rows, oversized responses, credentials in errors and settings, server binding.

### Notes

- 456 offline tests.

## Milestone 18 — CV versions — 2026-10-19 (`a0699bd`)

### Added

- Save the active CV as a named version with an optional purpose — only after you tick a consent box.
- Use any version as your active CV, rename it, or delete one or all versions with confirmation (up to 20).
- Compare two versions: ATS score by component, skills added or removed, sections, word count and a
  line-by-line diff.
- Score every version against your latest search results to see which fits best.

### Changed

- Privacy wording on CV Analysis, Settings and the README now states exactly when CV text is stored.

### Notes

- Only the extracted text is stored, never the original file. The local database is not encrypted.
- 435 offline tests.

## Milestone 17 — Dashboard analytics — 2026-10-19 (`269a208`)

### Added

- Getting-started steps marked done from the real state of your CV, searches, matches and applications.
- Metrics: searches in the last 30 days, strong matches in your latest results, active applications,
  interviews and offers.
- Follow-ups due and your top APPLY matches.
- Charts for applications by status, applications submitted per week and the match-score distribution,
  each with hover details and a table view.

### Notes

- Nothing is shown until it is based on your real data. Low-confidence scores are left out of the score
  chart. Charts use one colour validated for contrast.
- 426 offline tests.

## Milestone 16 — Caching and search history — 2026-10-19 (`2005bb6`)

### Added

- Recent searches on Find Jobs with result counts; "Search again" restores every filter.
- Settings shows stored job data, with buttons to clear cached responses and search history.

### Changed

- Job-source responses and daily request counts are now stored in the local database, so restarting
  the app neither repeats requests nor resets a source's daily limit.
- Cached responses are served within each source's cache period, including in offline mode.

### Notes

- Clearing cached data keeps the daily request counts, so source limits are always respected.
- Only search terms and counts are kept in history (the 50 most recent), never CV data.
- 421 offline tests.

## Milestone 15 — Application tracker — 2026-10-19 (`499aaf1`)

### Added

- Local SQLite database (under `data/`, git-ignored), created on first use.
- Application tracker: Saved, To Apply, Applied, Interview, Offer, Rejected and Withdrawn, with notes,
  applied date, next action and follow-up date. Every status change is recorded with its date.
- "Save to tracker" on Job Matches stores a snapshot of the match score and recommendation; the same
  job is never saved twice. Jobs can also be added manually, with validated links.
- Counts per status and a warning for follow-ups due within a week; confirmed deletion.

### Changed

- Study plan progress is now saved in the database instead of the browser session.

### Notes

- Only you change a status — opening a link never marks a job as applied. No CV text is stored.
- Tests always use a temporary database, never the real one.
- 411 offline tests.

## Milestone 14 — Study plans — 2026-10-19 (`0035a17`)

### Added

- Study plan tab on Interview Preparation: essential and required skills your CV does not show,
  listed skills that need a worked example, responsibilities your CV does not reflect, optional
  preferred skills and answer practice, ordered by priority.
- Optional interview date orders the plan around the days left.
- Not started, Preparing and Prepared status per topic with a progress bar.

### Notes

- Effort is shown as Short, Medium or Long — a relative suggestion, not an invented time estimate.
- Links point only to official documentation for well-known tools; other topics have no link rather
  than a guessed one.
- 403 offline tests.

## Milestone 13 — Interview preparation — 2026-10-19 (`c5d533f`)

### Added

- Likely interview questions for a chosen job: opening and motivation, technical questions for the
  skills your CV shows, behavioural questions for soft skills, questions about the role's
  responsibilities and honest questions about gaps.
- For every question: why it may come up (quoting the job), the lines of your CV to draw on, and how to
  prepare (STAR structure for behavioural answers).
- "Why this company?" uses researched company facts only when they belong to the same employer.
- Questions to ask the interviewer, including requirements to confirm (for example, right to work),
  and a pre-interview checklist.
- Filter by question type; download the plan as a Markdown file.
- "Prepare for interview" and "Research company" buttons on every job in Job Matches.

### Notes

- Questions are predictions from the job description, not the employer's actual questions. Answers
  are never written for you.
- 397 offline tests.

## Milestone 12 — Company intelligence — 2026-10-19 (`3cd2391`)

### Added

- Company lookup on Wikidata. Matching entries are listed for you to confirm, with likely
  organisations first; nothing is assumed.
- Company profile: Wikipedia summary with attribution and licence; key facts (industry, founding date,
  headquarters, country, employees, products, stock exchange, ownership); current leadership. Every
  fact links to its source and shows the date the source gives.
- Relevance to your search: roles at the company in your results, with their match score and
  recommendation, labelled as analysis rather than fact.
- Companies from your search results can be picked directly.

### Changed

- Requests identify the app with a contact URL, as the Wikimedia API policy asks.

### Notes

- Former office holders and deprecated statements are excluded; missing facts are listed as "not
  available".
- Wikidata and Wikipedia are volunteer-edited, so profiles recommend checking important facts on the
  company's website.
- Only the company name is sent; requests are spaced, cached for a day and capped daily.
- Employer names must match after removing suffixes such as Ltd or AG; subsidiaries are not merged.
- 385 offline tests.

## Milestone 11 — Keyword gaps and CV improvement plan — 2026-10-19 (`6d52ee8`)

### Added

- For each job: how your CV evidences each required skill — in experience, in education, listed
  without context, or not found — with the job's own sentence.
- Prioritised suggestions: essential and required skills not found, skills listed but not shown in a
  role, preferred skills, the job's repeated terms your CV does not use, and summary focus.
- Tips for your CV bullets most relevant to the job: measurable results, action verbs, first person,
  length.
- Available as "Improve your CV for this job" on Job Matches and on the CV Analysis "Compare with a
  job" tab, which now also accepts an optional job title.

### Notes

- Suggestions never supply content; they ask you to state only what is true. Bullet tips never
  borrow figures from elsewhere in your CV.
- 368 offline tests.

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
