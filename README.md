# CareerMatch AI

A personal career assistant that runs on your own computer. It searches permitted job sources, ranks every
job against your CV with the evidence behind each score, researches employers from attributed public
sources, prepares you for interviews and tracks your applications.

Every score is produced by transparent, explainable rules — you can see exactly why a job scored as it did.
Nothing is simulated or invented: unknown information is shown as "not provided", and suggestions only ever
ask you to state what is genuinely true. The core app needs no paid AI service.

> **Status:** the original plan (milestones 1–21), CV Studio (review, approval, tailoring, versions and
> PDF/DOCX export) and email-based application tracking are complete. See [CHANGELOG.md](CHANGELOG.md) for what
> changed in each milestone and the [roadmap](#roadmap) for what comes next.

## Contents

- [Quick start](#quick-start)
- [What you can do](#what-you-can-do)
- [How scores and recommendations work](#how-scores-and-recommendations-work)
- [Job sources](#job-sources)
- [Privacy and data](#privacy-and-data)
- [CV Studio](#cv-studio)
- [Email tracking](#email-tracking)
- [Configuration](#configuration)
- [Backend API](#backend-api)
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
streamlit run app.py      # the defaults work without any configuration
```

On macOS or Linux use `source .venv/bin/activate`. To change a setting, create a file named `.env` in the project
folder (it is never committed) with lines such as `CAREERMATCH_OFFLINE_MODE=true`. The app opens at
<http://localhost:8501> and is reachable only from your own computer.

## What you can do

A typical journey: **upload your CV → search for jobs → review ranked matches → tailor your CV for a job → research the employer →
prepare for the interview → track the application.**

| Page | What it does |
| --- | --- |
| **Dashboard** | Quick search, getting-started progress, and metrics and charts built only from your real activity: searches, strong matches, applications, follow-ups due. |
| **Find Jobs** | Searches the job sources you have enabled, with filters for location, country, work arrangement, experience level, employment type, date posted, skills and salary. Duplicates across sources are merged; every result links to its original listing. Recent searches can be run again. |
| **CV Analysis** | Upload a PDF or DOCX CV. Shows a transparent ATS compatibility score, section and contact detection, recognised skills and prioritised improvements. Paste any job description to compare it with your CV and get an improvement plan. |
| **Job Matches** | Every search result ranked against your CV, with a score breakdown, recommendation, essential requirements not found and the evidence behind each component. Filter, sort, compare up to three jobs side by side, and act on any job (improve your CV for it, research the company, prepare for the interview, save it to the tracker). |
| **Company Intelligence** | Looks up an employer on Wikidata and Wikipedia. You confirm which entry is meant; every fact links to its source and shows the date the source gives. Shows the employer's roles in your results. |
| **Interview Preparation** | Likely questions for a chosen job, each with why it may come up, the lines of your CV to draw on and how to prepare. A study plan covers the gaps, with Not started / Preparing / Prepared tracking. Plans can be downloaded as Markdown. |
| **Application Tracker** | Every application from Saved to Offer: nine summary cards (applied, active, pending, under review, interviews received and scheduled, offers, rejections, no response), a searchable, sortable table, and for each application a dated timeline, linked emails, status, interview date and notes, reminders and corrections of the interview and offer counts. Opening a link never changes a status. |
| **Email Tracking** | Optional: connect Gmail or Outlook (read-only) so replies to your applications update the tracker automatically, with a review queue for anything uncertain. See [Email tracking](#email-tracking). |
| **CV Studio** | Your CVs in one place: the untouched Original Master CV, a Revised Master CV with the improvements you approve, and a separate tailored CV per job. Review scores, recommended changes you accept, edit or reject, questions for missing information, side-by-side comparison, version history, and a checked PDF and editable Word file. See [CV Studio](#cv-studio). |
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
| [Himalayas](https://himalayas.app) | ✅ Supported | Public API ([terms](https://himalayas.app/api)) | Remote jobs worldwide with salaries and location restrictions. |
| [Jobicy](https://jobicy.com) | ✅ Supported | Public API ([terms](https://jobicy.com/jobs-rss-feed)) | Remote jobs from the last 7 days. |
| [Remote OK](https://remoteok.com) | ✅ Supported | Public API (terms in the response) | About 100 recent remote jobs, searched locally. |
| [Remotive](https://remotive.com) | ✅ Supported | Public API ([terms](https://github.com/remotive-io/remote-jobs-api)) | Remote jobs with a 24-hour delay. At most 4 new searches per day; results reused for 6 hours. |
| LinkedIn Jobs, Indeed, Glassdoor, Google Jobs, Bayt, GulfTalent, Naukrigulf, Rozee.pk, Mustakbil, Wellfound | ❌ Not supported | — | No public job-search API is available; automated scraping would breach their terms. |
| Arbeitnow, Jooble | ❌ Not integrated | — | Terms of use or official API documentation could not be verified. |
| Adzuna | ❌ Removed | — | Its API needs paid access; CareerMatch AI uses only free sources. |

All supported sources focus on **remote** jobs; an on-site search skips them and explains why. Any source can be
switched off with `CAREERMATCH_<SOURCE>_ENABLED=false`.

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
3. Read credentials from `CAREERMATCH_*` settings and document them in the Configuration table below.
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

## CV Studio

**Your CVs**

| CV | What it is |
| --- | --- |
| **Original Master CV** | The CV you uploaded, structured into sections. It is never changed. Uploading a new CV archives the old one instead of overwriting it. |
| **Revised Master CV** | A copy where the general improvements you approve go. It is labelled *Draft* until you approve it (*User Approved*). New tailored CVs start from it once approved. |
| **Tailored CV — <job>** | A separate copy for one job, linked to that job in the tracker. Changing one tailored CV never changes another. |

Every CV keeps its full revision history (each accepted change, answer, edit or layout change is a revision).
You can compare any two CVs or revisions, restore an old revision as a new one, and generate a PDF of any
revision. When you mark an application as submitted, the exact revision you sent is kept with it.

**Review and approval**

- *Review & scores* gives an overall score out of 100 and category scores: language and grammar, structure and
  ATS readability, professional summary, experience and achievements, skills/education/certifications, and
  relevance to your target roles. The scores come from transparent rules. They are guidance, not a prediction
  of how an employer will rank you.
- *Recommended changes* shows each suggestion with the current text, the suggested text, why it matters and
  how it helps. You can accept, edit or reject each one, undo it later, or accept/reject all at once.
  "Accept all" skips any change that needs you to confirm a fact.
- Suggestions only reword, reformat or reorder what your CV already says: spelling, “Responsible for
  managing” → “Managed”, filler words, pronouns, consistent dates, duplicates.
- Anything that would need a new fact (a figure, a date, a missing skill) becomes a question under *Missing
  information*. Unanswered questions stay out of your CV.
- *Tailor for a job* compares the CV with a job (from your search, your tracker or pasted). It suggests putting
  the job's skills and most relevant achievements first, a focused summary, a section order, and the job's own
  wording for skills you already show. Skills you lack are listed as gaps. Adding one needs your confirmation
  that it is true.

**Export.** *Preview & download* offers four templates (like my original, classic professional, modern minimal,
technical & engineering), A4 or Letter, and font, size and margin choices. You can also choose to fit the CV
onto one page within readable limits.

- **The PDF** is single-column with real, selectable text and page numbers. Headings are never left alone at
  the bottom of a page, and bullets are never split across pages.
- **The DOCX** uses Word headings, paragraphs and bullet lists, with no text boxes or tables.
- **Checks before download:** each file is opened again and checked for page count, every visible line
  present, reading order, nothing clipped or overlapping, and characters intact. A file that fails a check is
  not offered for download.
- **File names** follow the pattern `First_Last_Title_CV.pdf`.

### Claude (optional)

The built-in rules work without any account. With an Anthropic API key, CV Studio can also ask Claude for
suggestions (*Ask Claude for suggestions* on the Review tab, *Ask Claude to tailor it* for a job).

1. Create a key at <https://console.anthropic.com/settings/keys>.
2. Open the `.env` file in the project folder and paste it after `ANTHROPIC_API_KEY=` (no quotes or spaces).
3. Restart the app. Settings shows “Claude for CV review: On”.

**What is sent and when:** only after you tick the consent box for that request. Your name, email, phone,
location and links are removed first. Claude's suggestions go through the same approval workflow. A
suggestion that adds a figure, skill or name your CV does not contain is flagged, and you must confirm it
before it can be accepted.

**Cost control:** the default model is `claude-sonnet-5-5` at medium effort with an 8,000-token answer limit,
about US$0.04 per review. Each request shows what it cost. For the lowest cost set
`CAREERMATCH_CV_AI_MODEL=claude-haiku-5-5`, about US$0.003 per review with simpler writing.

## Email tracking

Connect Gmail or Outlook once, and the Application Tracker updates itself from your email: your sent
application, the employer's confirmation, assessments, interview invitations and confirmations, offers and
rejections each become a dated step on the application's timeline.

**How it decides.** Each job-related email is classified by transparent phrase rules (for example "we regret to
inform you", "we would like to invite you to an interview", "we are delighted to offer you") with a confidence
score, and matched to an application by the email conversation, the address you applied to, the company's domain
or name (including applicant-tracking systems such as Greenhouse, Lever or Workday) and the job title. Quoted
earlier messages and job-alert newsletters are ignored.

**What happens automatically, and what waits for you.**

- A confident match and classification updates the timeline and moves the status forward — never backwards,
  never over a change you made yourself afterwards, and never on a closed application.
- Interviews, offers and rejections need a higher confidence than other updates.
- Anything uncertain goes to **Needs your review** on the Email Tracking page: confirm it, change what it is,
  link it to another application, create a new application from it, or mark it as not job-related. Your
  decisions are final — later syncs never change them.
- Each application's **Emails** tab lets you reclassify or unlink any email afterwards.

**When it syncs.** When you open the Application Tracker or Email Tracking page (every 30 minutes at most, by
default), when you press **Sync emails now**, or on a schedule with `python -m src.mail sync` (for example an
hourly Windows Task Scheduler task) — so the app does not need to stay open. The first sync reads the last 60
days. Every email is processed once; a failed sync is retried next time from the same point.

### Set up Gmail (one time, about 5 minutes)

1. Open [Google Cloud Console](https://console.cloud.google.com/) and create a project.
2. **APIs & Services → Library**: enable the **Gmail API**.
3. **OAuth consent screen**: choose *External*, fill in the app name and your email, and add **your own
   address as a test user**. (While the app is in *testing*, only test users can connect; this is enough for
   personal use. Google asks for verification only if you publish it for other people.)
4. **Credentials → Create credentials → OAuth client ID**: application type **Desktop app**.
5. Copy the client ID and secret into `.env`, then restart CareerMatch:

   ```
   CAREERMATCH_GMAIL_CLIENT_ID=1234-abc.apps.googleusercontent.com
   CAREERMATCH_GMAIL_CLIENT_SECRET=GOCSPX-...
   ```

6. On **Email Tracking**, press **Connect Gmail**, sign in on Google's page and allow read-only access.

### Set up Outlook / Microsoft 365 (one time)

1. Open [Microsoft Entra admin center](https://entra.microsoft.com/) → **App registrations → New
   registration**. Supported account types: *any organisational directory and personal Microsoft accounts*.
2. **Authentication → Add a platform → Mobile and desktop applications**, redirect URI `http://127.0.0.1`.
3. **API permissions → Microsoft Graph → Delegated**: `Mail.Read` and `User.Read`.
4. Copy the **Application (client) ID** into `.env` (no secret is needed) and restart CareerMatch:

   ```
   CAREERMATCH_OUTLOOK_CLIENT_ID=00000000-0000-0000-0000-000000000000
   ```

5. On **Email Tracking**, press **Connect Outlook / Microsoft 365** and sign in.

Work or school accounts may need an administrator to approve the app.

### Privacy

- **Read-only access** (`gmail.readonly`, or Graph `Mail.Read`): CareerMatch can never send, delete or change
  email. Your password is entered only on Google's or Microsoft's own page.
- Gmail is asked only for messages that look job-related; Outlook messages are filtered on your computer.
  Message text is analysed in memory and never stored in full.
- For job emails CareerMatch keeps the sender, subject, date, a 300-character snippet and a link to open the
  original. For any other email it keeps only an id, so it is never read again.
- The sign-in token is encrypted; the key is kept in your system's credential store (Windows Credential
  Manager), not in the database.
- **Disconnect** removes the token and every synchronised email, and optionally the timeline events that came
  from it.

## Configuration

All settings use the `CAREERMATCH_` prefix and can be set in a `.env` file in the project folder (git-ignored). Invalid values stop
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
| `ANTHROPIC_API_KEY` | — | Optional: enables Claude suggestions in CV Studio |
| `CAREERMATCH_CV_AI_ENABLED` | `true` | Set to `false` to never use Claude, even with a key |
| `CAREERMATCH_CV_AI_MODEL` | `claude-sonnet-5-5` | `claude-haiku-5-5` is the cheapest option |
| `CAREERMATCH_CV_AI_EFFORT` | `medium` | `low` / `medium` / `high` — higher costs more |
| `CAREERMATCH_CV_AI_MAX_TOKENS` | `8000` | Upper limit of one Claude answer (caps the cost of a request) |
| `CAREERMATCH_CV_STORAGE_DIR` | `data/cv_files` | Encrypted original CVs and generated PDF/DOCX files |
| `CAREERMATCH_<SOURCE>_ENABLED` | `true` | Switch a source off (`REMOTIVE`, `HIMALAYAS`, `JOBICY`, `REMOTEOK`) |
| `CAREERMATCH_TRACKER_NO_RESPONSE_DAYS` | `21` | Days without activity before an application shows as No Response |
| `CAREERMATCH_GMAIL_CLIENT_ID`, `CAREERMATCH_GMAIL_CLIENT_SECRET` | — | Your Google OAuth *Desktop app* client (email tracking) |
| `CAREERMATCH_OUTLOOK_CLIENT_ID` | — | Your Microsoft app registration (email tracking) |
| `CAREERMATCH_MAIL_INITIAL_DAYS` | `60` | Days of email read on the first sync |
| `CAREERMATCH_MAIL_AUTO_SYNC_MINUTES` | `30` | Minutes between automatic syncs while the app is open (0 = only on request) |
| `CAREERMATCH_MAIL_MAX_PER_SYNC` | `300` | Most emails read in one sync |
| `CAREERMATCH_API_DATABASE_URL` | `sqlite:///data/careermatch_api.db` | Account database for the backend API |
| `CAREERMATCH_API_HOST`, `CAREERMATCH_API_PORT` | `127.0.0.1`, `8600` | Where the backend API listens |
| `CAREERMATCH_API_TOKEN_DAYS` | `30` | How long a sign-in lasts |
| `CAREERMATCH_API_MAX_FAILED_LOGINS`, `CAREERMATCH_API_LOCKOUT_MINUTES` | `5`, `15` | Sign-in lockout after repeated wrong passwords |

## Backend API

A local API with user accounts. The Chrome extension (next milestone) uses it, and it lets several people use one
installation with their data kept apart. The Streamlit app does not need it.

```powershell
.venv\Scripts\python -m src.api
```

Open <http://127.0.0.1:8600/api/docs> to try every endpoint in the browser: register, sign in (copy the token
into **Authorize**), upload a CV, analyse a job, then get interview questions, tailoring suggestions and a
tailored DOCX or PDF.

| Endpoint | What it does |
| --- | --- |
| `POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/logout` | Create an account, sign in (returns a bearer token), sign out |
| `GET /api/me`, `DELETE /api/me` | Account summary; delete the account and all its data |
| `PUT /api/cv`, `GET /api/cv`, `DELETE /api/cv` | Upload a CV (needs `consent=true`; only the text is kept), see its ATS summary, delete it |
| `POST /api/jobs/analyze` | Match a job (title, description, optional company, location and links) against your CV and save it |
| `GET /api/jobs`, `GET /api/jobs/{id}`, `DELETE /api/jobs/{id}` | Your saved jobs and their full analysis |
| `GET /api/jobs/{id}/interview` | Interview preparation for the job |
| `GET /api/jobs/{id}/tailoring`, `POST /api/jobs/{id}/tailored-cv` | Tailoring suggestions; the tailored CV as text, DOCX or PDF |

Passwords are hashed with scrypt; sign-in tokens are stored only as hashes; repeated wrong passwords lock the
account for a few minutes; each account sees only its own CV and jobs. See [SECURITY.md](SECURITY.md).

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
src/tailoring/         Job-specific CV edits and DOCX/PDF export (used by the backend API)
src/workspace/         CV Studio: structured CV, import, master/revised/tailored versions and revisions,
                       review rules, approval workflow, job tailoring, PDF/DOCX rendering and checks,
                       encrypted file storage, optional Claude provider
src/api/               Backend API: accounts, tokens and per-account CV, jobs, preparation and tailoring
src/tracker/           Application tracker: statuses, timeline, counting rules, safe automatic updates
src/mail/              Email tracking: OAuth, encrypted tokens, Gmail/Graph adapters, classifier, matcher,
                       sync and review actions (`python -m src.mail sync`)
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

The original plan (milestones 1–21) and CV tailoring (milestone 22) are complete. Planned next:

| Milestone | Area |
| --- | --- |
| 23 | Chrome browser extension (Manifest V3), using the backend API |
| 24 | Freemium plan: one free full job workflow, then $9/month (Stripe, test mode first) with server-side entitlements |
| 25 | Integration, security and verification for the extension and subscription |
| 26 | Multi-language support, starting with English, Arabic and Urdu (with right-to-left layouts) |

## Troubleshooting

| Problem | What to do |
| --- | --- |
| "Needs OCR" after uploading a PDF | The PDF is a scanned image. Export your CV from its original editor as a text-based PDF or DOCX. |
| A source shows "Not searched" | It is switched off, does not cover the filters you chose (e.g. on-site), or offline mode is on — see Settings. |
| Remotive reports its daily limit | Remotive allows about four searches a day; results are reused for six hours. Try again tomorrow. |
| Very few jobs found | Use broader keywords and remove filters. The supported sources list remote jobs; for on-site roles, add jobs you find elsewhere to the tracker manually. |
| A company is not found | Smaller or private employers are often not on Wikidata. Try the name without its legal suffix, or check the company's website. |
| The app is not reachable from another device | By design — it listens on `localhost` only. See [SECURITY.md](SECURITY.md) before changing this. |

## Licence

To be decided by the repository owner.
