# Security and privacy

CareerMatch AI is a **single-user application that runs on your own computer**. It handles personal
career data (your CV, applications and notes), so it is designed to keep that data local and to treat
everything it receives from job sources and public data sources as untrusted.

## Threat model

| In scope | Out of scope |
| --- | --- |
| Malicious or malformed content in job listings and company data (script injection, unsafe links, oversized responses) | Attackers with access to your computer account or disk |
| Malformed or hostile uploaded files (disguised types, encrypted PDFs, zip bombs, huge documents) | Shared or public hosting (see [Deployment](#deployment)) |
| Leaking CV content or credentials through logs, error messages or the network | Compromise of the job sources or Wikimedia themselves |
| Other devices on the same network opening the app | |

## What is stored, and where

| Data | Where | When |
| --- | --- | --- |
| Uploaded CV file | Nowhere — processed in memory, bytes discarded after text extraction | Never stored |
| CV text | Browser session memory | Until you delete it, refresh or close the page |
| CV versions (extracted text only) | Local SQLite database | Only after you tick the consent box; until you delete them |
| Tracked applications, notes, study progress | Local SQLite database | Until you delete them |
| Search history (terms and counts) | Local SQLite database | The 50 most recent; can be cleared in Settings |
| Job-source responses and daily request counts | Local SQLite database | Cached within each source's limits; clearable in Settings |
| Backend API accounts: email, scrypt password hash, hashed sign-in tokens | Separate local database (`data/careermatch_api.db`) | Until the account is deleted |
| Backend API CV text and analysed jobs | Same database, linked to the account | Only after consent; deleted with the CV or account |
| Adzuna credentials | `.env` / environment variables | Never written to the database, logs or error messages |

The database lives at `data/careermatch.db` by default. It is **not encrypted** — use full-disk encryption
(BitLocker, FileVault, LUKS) if other people can access your computer. `.env`, `data/` and `*.db` are
git-ignored.

**What leaves your computer:** search terms and filters (to the job sources you enable) and company names
(to Wikidata and Wikipedia). CV content is never sent anywhere.

## Controls in place

- **Injection:** all dynamic content is HTML-escaped by dedicated builders before rendering. Job
  descriptions are converted from HTML to plain text with scripts, styles and embedded objects removed.
- **Links:** every URL is validated (`http`/`https` with a host, no embedded credentials) when a job is
  created, and again when links are displayed from the database. Links open with `rel="noopener"`.
- **Uploads:** checked by extension, size and file signature; legacy `.doc`, encrypted, damaged and disguised
  files are rejected; PDFs are limited to 30 pages and DOCX archives to 50 MB uncompressed.
- **Network:** the app binds to `localhost` only, with Streamlit's XSRF protection on and static file serving
  off. Outgoing requests use timeouts, retries with back-off, per-source pacing, daily budgets and a 10 MB
  response limit.
- **Errors and logs:** error messages never include request URLs or parameters, so credentials cannot leak
  through them. The app does not log CV content.
- **Backend API:** listens on `127.0.0.1` only by default. Passwords use scrypt with a per-user salt and a
  10-character minimum; tokens are random 256-bit values stored only as SHA-256 hashes and expire after 30 days;
  five wrong passwords lock the account for 15 minutes, and wrong passwords and unknown emails give the same
  answer. Every query is scoped to the signed-in account, so another account's job behaves as if it does not
  exist. Cross-origin requests are accepted only from Chrome extensions and origins you list. Responses carry
  `nosniff`, `DENY` framing and `no-store` headers, and validation errors never echo submitted values.
- **Database:** all queries go through SQLAlchemy with bound parameters.
- **Dependencies:** pinned versions, checked with `pip-audit` (no known vulnerabilities at the time of the
  last review).
- **Tests:** a security regression suite runs hostile content through every HTML builder and checks unsafe
  URLs, oversized responses, credential handling and the server binding. Tests never use the network or
  your real database.

## Known limitations

- The local database is not encrypted at the application level.
- Anyone who can use your computer account can open the app and its data.
- Wikidata and Wikipedia are volunteer-edited; facts are attributed and dated but may be out of date.

## Deployment

The app is built for local use. Do **not** expose the Streamlit app on a network or the internet as it is: it
has no authentication, no per-user data separation and stores data unencrypted. The backend API has accounts
and per-user separation but serves plain HTTP; put it behind HTTPS before making it reachable from another device. A shared deployment would need
authentication, access control, encrypted storage, HTTPS and a hardened host first.

## Reporting a vulnerability

Please report security issues privately to the repository owner through GitHub rather than opening a public
issue, with steps to reproduce. Never include real CVs or personal data in a report.
