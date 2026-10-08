# Personal research digest

This fork adds a private, single-user reading room and a local Codex subscription runner.
The upstream license and attribution are retained. The original public-data workflow is removed;
GitHub Actions builds and publishes only `personal/site/`.

## What runs where

- GitHub Pages: public login page and UI code, including bundled KaTeX.
- Supabase: private papers, research profile, and favorites/read/dislike states, enforced with RLS and an owner allowlist.
- Your computer: arXiv collection, GPT-5.6 Sol / High analysis, PDF extraction, SMTP delivery.
- ChatGPT login is required. The local runner removes API-key environment overrides and has no paid API fallback.

## Initial configuration

1. Install Python 3.12+, Node 22+, pnpm, and Codex CLI. Sign in to Codex with ChatGPT.
2. Inside `personal/`, create `.venv`, install `requirements.txt`, and run `pnpm install`.
3. Copy `config.example.json` to `config.local.json`. Set your research directions, recipient and site URL.
4. Create a free Supabase project. Run `supabase/schema.sql` once in its SQL editor.
5. In Supabase Auth, create your own user and set the **website** password yourself. This is not your mailbox password.
   Disable public signups. Insert that Auth user's UUID into `public.digest_owners` using the statement at the end of the SQL file.
6. Run `.venv/bin/python -m digest setup` in a local terminal. Supply the project URL, anon/publishable key,
   service-role key, owner UUID and SMTP settings. Secrets are saved to `.env` with mode 0600 and ignored by Git.
   For a 163 sender, verify SMTP is enabled and use the mailbox's SMTP authorization code, not its normal login password.
   To add or replace only the mail authorization code later, run `.venv/bin/python -m digest setup-mail` in your own interactive terminal. Input is hidden and no email is sent by this setup command.
7. Run `.venv/bin/python -m digest doctor`, then `.venv/bin/python -m digest sync-profile`.
8. Set repository **Variables**, `SUPABASE_URL` and `SUPABASE_ANON_KEY` (public values only).
   Set Pages source to GitHub Actions, then run “Private digest website”.
9. Test anonymous access, another account, your own login, a saved state on two devices, and one email delivery before enabling unattended runs.

Do not upload `.env`, `config.local.json`, `runtime/`, Codex auth files, email authorization codes,
service-role keys, chat excerpts, or private research notes. A private source repository alone does not make Pages private.

## Daily operation

Run from `personal/` with `.venv/bin/python -m digest COMMAND`:

- `collect --date YYYY-MM-DD`: fetch and validate public announcements only; no model usage.
- `prepare`: first run backfills seven calendar days; later runs prepare yesterday (Beijing time).
- `publish --date YYYY-MM-DD`: publish a prepared digest to the private database.
- `send`: publish and send yesterday's digest, normally after 09:00 Beijing time.
- `run`: prepare, publish and send; intended for a manual end-to-end run after 09:00.
- `doctor`: configuration status only; never prints keys.

Suggested schedule after a successful manual test: prepare before 09:00, deliver at 09:00.
The computer must be awake, online, with the required local credentials available.
Model/runtime delays can make a digest late; this implementation does not promise exact delivery time.
No scheduled job is installed by these commands. Configure it in the Codex desktop app after the manual run succeeds.

No fixed recommendation count is used. All abstracts are screened in batches. Related papers get source-grounded cards;
method-related extensions and eligible revisions trigger emails even with no direct papers. Disliked papers do not trigger mail.
On initial seven-day backfill, all days are placed on the website and only the latest day is emailed.
Incomplete full-text analysis is visibly marked. Model failures do not silently become unrelated-paper decisions.

## Dates, cross-lists and revisions

The dated primary-category announcement list determines the first announcement date; API `published` is only a submission timestamp.
Cross-listed papers are deduplicated and their primary categories checked. Unresolved cross-list dates are retained and marked as unverified.
Version-pinned metadata and PDFs are used. RSS announcements are archived locally to identify replacements accurately.
Historical revisions cannot be reconstructed completely before feed archiving starts; coverage gaps are displayed in each digest.
The recent list supports a short backfill, not arbitrary historical dates. A date not present in available archives is not proof of no papers.

## Manual research-interest updates

Set only the explicitly approved local directories in `context_directories` and exported chat files in `chat_exports`.
`propose-interests` extracts bounded excerpts and asks Codex for suggestions; it does not change active directions.
Review the proposal in the website, or in local `runtime/interest-proposal.json`.
Accept through the website, or explicitly run `accept-interests`. Do not schedule interest scans.
No arbitrary local directories or hidden chat databases are scanned automatically.

## Verification

Run Python tests with `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`.
Run `pnpm test` for actual PostgreSQL RLS tests in PGlite, ownership restrictions and atomic reading-state updates.
Run `pnpm build`; `site/` is the only publishable directory.
Serve `site/` locally and append `?demo` for fictional UI examples. Demo mode is restricted to localhost.
The SQL tests do not replace a live Supabase authentication and authorization check.

`runtime/model/*.usage.json` contains per-call usage reported by Codex. These values and API prices do not directly determine
subscription weekly percentage. Measure account limits before/after an isolated model run, accounting for other tasks and display precision.
