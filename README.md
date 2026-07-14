# QuickCap "Request To Login" Automation

Safe, UI-only browser automation for the authorized QuickCap admin workflow: filter pending login requests, open each one, check for duplicate emails against the Organization User Details table, resolve ambiguous organizations via the search popup, then approve (with an auto-generated username) or reject (with a note) — with logging, screenshots, and a dry-run-first design.

**What it never does:** it never logs in for you, never touches MFA or CAPTCHA, never calls backend APIs, never stores credentials, and never sends emails unless you pass `--send-email` and confirm each one. Every mode either fills fields without saving, or asks for explicit confirmation before each Save.

**Right now the automation only runs in dry-run-equivalent modes** (`demo`, `local`, `dry-run` all confirm before every Save). `--mode commit` against the real system still exists in the code for when you're ready, but the recommended path below is: prove the logic locally first.

---

## 0. The two things this project gives you

1. **A local carbon-copy dashboard** (`webapp/`) — a small Flask app that reproduces the parts of the real QuickCap "Request To Login" screens the automation touches: the pending list with filters, the edit form (including the Status dropdown and the Approved-only fields), the Organization Details / Organization User Details tables, and the Organization search popup used when a Tax ID maps to more than one Organization ID. You run it locally (`python run_webapp.py`), open it in a browser, import your own JSON test data into it, and visually check that the automation fills in the right things.
2. **The automation** (`main.py`), which can now target that local dashboard (`--mode local`) instead of — or before — the real system.

The local dashboard is **not** the real QuickCap system and never talks to it. Everything lives in one file on your machine, `webapp/data/sandbox_state.json`, which is gitignored.

---

## 1. Prerequisites (Windows)

- Windows 10/11
- Python 3.11 or newer — check with `python --version`
- Google Chrome installed (only needed once you point the automation at the real system; local/demo modes use Playwright's bundled Chromium)
- VS Code (recommended) with the Python extension

## 2. Setup — step by step

Open a terminal in VS Code (`Terminal > New Terminal`, use PowerShell) inside the `quickcap_request_automation` folder, then:

**Step 1 — Create and activate a virtual environment**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then try again. Your prompt should now start with `(.venv)`.

**Step 2 — Install dependencies**

```powershell
pip install -r requirements.txt
playwright install chromium
```

This installs Playwright, python-dotenv, pandas, and Flask (Flask powers the local carbon-copy dashboard; nothing else needs it). `playwright install chromium` downloads the bundled browser used by demo/local modes.

**Step 3 — Create your .env file**

```powershell
copy .env.example .env
```

Open `.env` in VS Code. You don't need to change anything to use the local dashboard — `LOCAL_WEBAPP_PORT` defaults to `5050`. Set `QUICKCAP_URL` / `QUICKCAP_REQUEST_LIST_URL` later, only when you're ready to point at the real system. Do **not** put any password in this file — there is no field for one, on purpose.

---

## 3. The local carbon-copy dashboard

### 3.1 Start it

```powershell
python run_webapp.py
```

This starts a Flask dev server at `http://127.0.0.1:5050/requests` and prints that URL. Leave this terminal running; open a **second** terminal for the next steps. Stop it any time with `Ctrl+C`.

The dashboard starts with an **empty** pending queue on purpose (see the "No requests in the local sandbox yet" message on the list page) — you decide what test data goes in.

### 3.2 Import test data

```powershell
python import_requests.py samples\sample_pending_requests.json
```

This loads 3 pending requests into `webapp/data/sandbox_state.json`, each exercising a different branch of the automation's logic:

| token_no | Scenario | What should happen |
|---|---|---|
| `20260714-3501` Jordan Lee | Tax ID `74-5551000` has 4 candidate Organization IDs and `organization_id` is blank | Automation opens the search popup, picks the org by name, status → Approved, username `jlee01` |
| `20260714-3502` Dana Brooks | `organization_id` already resolved, but the email exactly matches an existing Organization User Details row | No popup needed; status → Rejected, note "Account already exists for this email address." |
| `20260714-3503` Casey Nguyen | Single organization for its Tax ID, brand-new email | No popup needed; status → Approved, username `cnguyen01` |

You can re-run `import_requests.py` with your own JSON files (see the field list in `samples/sample_pending_requests.json` — any file with the same shape works). Records are merged by `token_no`; pass `--reset` to clear the sandbox first. `import_requests.py` (with no arguments) also picks up every `*.json` file dropped into `data\import\` (gitignored — safe to drop exports there without risking a commit).

### 3.3 Look around manually

Open `http://127.0.0.1:5050/requests` in a browser. Filter by Status=Pending, click the ✎ edit icon on a row, and try things by hand before trusting the automation to do them:

- Change Status to **Approved** — the User Name / Name / Role / Organization Group fields should appear (this is the "make Status a dropdown that reveals more fields" behavior from the real screens).
- On Jordan Lee's request, click the 🔍 next to Organization ID — a popup opens, search by name, click a row, and watch the Organization ID / Name / NPI fields on the form behind it fill in and the popup close itself.
- The Organization Group field (inside the Approved section) has the same kind of 🔍 popup, searching a small set of fake groups.
- **Reset sandbox** (top banner) wipes the queue back to empty if you want a clean slate.

The "banner"/"Reset sandbox" link, the Organization Details table headers, and the popup title text are deliberately **not** pixel-identical to the real QuickCap screens — they were rebuilt from your screenshots into a simpler, DOM-parseable structure so the automation's generic label/table-scraping helpers (`utils.py`) can find things reliably. The workflow (search icon → popup → search by name → click a row → parent field fills in) is the same.

### 3.4 Privacy note on the seed data

`webapp/data/organizations.json`, `org_users.json`, and `groups.json` (checked into git) are entirely **fabricated** — fake org names ("Riverside Medical Group", "Cedar Valley Pulmonary Services"), fake people, fake emails. They mirror the *structure* seen in the screenshots you shared (one Tax ID with several slightly-different Organization ID rows, an Organization User Details table used for duplicate-email checks) without reusing any of the real organization or employee data. `data/` and `webapp/data/sandbox_state.json` are gitignored, so anything you personally import stays local.

---

## 4. Run the automation against the local dashboard

With `python run_webapp.py` running in one terminal, and test data imported:

```powershell
python main.py --mode local
```

This launches a bundled Chromium window, goes to `http://127.0.0.1:5050/requests`, filters Status=Pending, and processes each row exactly like it would on the real system — including opening the Organization search popup when needed — but it **always pauses and asks for confirmation before clicking Save**. Type `y` to watch it save (this only writes to your local `sandbox_state.json`), or press Enter to skip. There is no `--mode` that commits automatically against the local dashboard — that's intentional, so this stays a safe place to iterate on the logic.

Afterwards check:

- `logs/run_YYYY-MM-DD.csv` — one row per request: token, name, email, org, action, generated username, notes. Compare the `action` column against the table in §3.2.
- `screenshots/` — before/after images named by token, so you can see exactly what the form looked like when it decided to approve/reject.

Useful flags: `--max-requests 1` to process just one request at a time while you're checking behavior; `--send-email` to also exercise the (still-confirmed, still-fake) "Click to Send Email" button.

### 4.1 Also still available: the bundled static demo

```powershell
python main.py --mode demo
```

Three hand-written HTML files (`demo/list.html` + 3 detail pages) with no server needed — a 10-second smoke test that the script and your Python environment work at all, kept from the original version of this project. It does **not** exercise the multi-organization popup (those fixtures don't have one) — use `--mode local` for that.

---

## 5. Connect to Chrome for the REAL system (two options)

Only do this once you're happy with what `--mode local` produced.

### Option A — Let the script launch Chrome (simplest)

```powershell
python main.py --mode dry-run --chrome launch
```

Playwright launches your installed Chrome with a persistent profile stored in `chrome-profile/` (configurable via `CHROME_PROFILE_DIR`). The first time, the script will detect the QuickCap login screen and pause — log in manually in that window (including MFA if any), navigate to the Request To Login list, then press Enter in the terminal. The session is remembered for future runs.

### Option B — Attach to a Chrome you started yourself (CDP)

1. Close **all** Chrome windows (check the system tray too).
2. Start Chrome from PowerShell with remote debugging:

   ```powershell
   & "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\quickcap-automation-profile"
   ```

3. In that Chrome window, log in to QuickCap manually and open the Request To Login page. Leave that tab open.
4. Run the script from VS Code:

   ```powershell
   python main.py --mode dry-run --chrome connect
   ```

5. The script connects to `http://localhost:9222` (configurable via `CHROME_DEBUG_URL` in `.env`) and starts from that existing QuickCap tab. It will not navigate away first unless you pass `--start-page goto`. When the script exits, it disconnects but never closes your Chrome.

If connection fails, confirm nothing else is using port 9222 and that you used a **separate** `--user-data-dir` (Chrome refuses debugging on your default profile).

## 6. Running against the real system

Always in this order:

**Step 1 — Map the selectors on your pages**

```powershell
python main.py --debug-selectors --chrome connect
```

This prints every input (name/id/placeholder), every dropdown with its exact option texts, every button/link caption, and the visible section headings on the current page. Answer `y` at the prompt to navigate to the detail page in the browser and dump that too. Compare the output with the `UPDATE ME` constants at the top of `quickcap_pages.py` — they currently match the **local carbon-copy dashboard's** exact field labels (e.g. `"Name of the Organization"`, `"Organization Tax ID"`, `"User Name"`), which will very likely differ from the real system's wording (e.g. is the reject option called "Rejected" or "Denied"? Is the org-name field called "Organization Name" or "Name of the Organization"?). Also re-check `ORG_SEARCH_ICON_SELECTOR` — the real popup trigger almost certainly isn't `#orgSearchBtn`.

**Step 2 — Dry run on the real pages**

```powershell
python main.py --mode dry-run --chrome connect --max-requests 2
```

The script fills the status/username/note fields on real requests but stops before every Save and asks for confirmation. Press Enter (i.e., answer "no") to skip saving — nothing is changed. Visually verify in the browser that the right fields got the right values, and check the CSV log (`dry_run_approved` / `dry_run_rejected` rows).

**Step 3 — Commit for real**

```powershell
python main.py --mode commit --chrome connect
```

Now Save / Save & Next is actually clicked. Start with `--max-requests 1` if you want to commit one request and inspect the result.

**Step 4 — (Optional) allow sending emails**

```powershell
python main.py --mode commit --chrome connect --send-email
```

Even with the flag, the script asks you to confirm before clicking "Click to Send Email" on each request. Without the flag, the button is never clicked.

## 7. All CLI options

```text
python main.py --mode local              # local carbon-copy dashboard; always confirms
python main.py --mode demo               # bundled static local sample pages
python main.py --mode dry-run            # real pages; confirm before any Save
python main.py --mode commit             # actually save on the real system
python main.py --mode commit --send-email
python main.py --debug-selectors         # dump page elements and exit
python main.py --chrome launch|connect   # Option A (default) or Option B
python main.py --start-page auto|current|goto
python main.py --max-requests N          # stop after N requests
```

`--start-page auto` is the default. With `--chrome connect`, auto means "use the existing Chrome tab I already opened." With `--chrome launch`, auto keeps the older behavior and navigates to `QUICKCAP_REQUEST_LIST_URL`. Neither applies to `--mode demo`/`--mode local`, which always navigate to their own fixed URL.

## 8. How to customize selectors

All page-specific text lives in the constants at the top of `quickcap_pages.py`, each marked `UPDATE ME`:

- **Labels** (`FIRST_NAME_LABEL`, `EMAIL_LABEL`, `STATUS_DROPDOWN_LABEL`, ...) — the helpers find the input/select next to that visible text, which works for both modern label markup and old `<td>Label</td><td><input></td>` layouts. Change the text to match what you see on screen. Watch for one label being a substring of another (e.g. an old "NPI" constant would also match "Organization NPI") — `find_input_by_label` takes the first DOM match, so an ambiguous substring can silently fill the wrong field. `NOTE_LABEL` is deliberately `"Note:"` (with the colon) so it doesn't also match "External User Notes".
- **Button captions** (`SEARCH_BUTTON_TEXT`, `SAVE_BUTTON_TEXTS`, `SEND_EMAIL_BUTTON_TEXT`) — matched against button text, link text, or an input's `value`.
- **`EDIT_ICON_SELECTOR`** — a CSS selector for the edit icon column. Run `--debug-selectors` on the list page; if your edit links have a different `title`/`alt`/`href` pattern, adjust it.
- **`ORG_DETAILS_TABLE_TITLE`** / **`ORG_USER_TABLE_TITLE`** and the column hints — used to locate and parse the Organization Details / Organization User Details tables by their heading and header row text.
- **`ORG_SEARCH_ICON_SELECTOR`**, **`ORG_POPUP_NAME_LABEL`**, **`ORG_POPUP_SEARCH_BUTTON_TEXT`**, **`ORG_POPUP_RESULT_ROW_SELECTOR`** — drive the multi-organization popup (see §9). Inspect the real popup with `--debug-selectors` (answer `y` to the "navigate to another page" prompt after opening it) and update these to match.

If a label-based lookup can't work for some field, you can replace the call in `quickcap_pages.py` with a direct locator, e.g. `self.page.locator("#txtUserName")`, using the id/name printed by `--debug-selectors`. XPath is available as a fallback (`page.locator("xpath=...")`) but prefer ids, names, and visible text — they survive layout changes better.

## 9. How the multi-organization popup automation works

`RequestDetailPage.detect_organization_count()` reads the Organization Details table on the currently open request: if Organization ID is already filled in, it assumes the org is resolved (count = 1). Otherwise it counts distinct Organization IDs listed for that Tax ID.

If that count is `> 1`, `handle_new_user()` in `main.py` calls `RequestDetailPage.pick_organization_via_popup(organization_name)`, which:

1. Clicks the search icon (`ORG_SEARCH_ICON_SELECTOR`) and waits for the popup window (`page.context.expect_page()`).
2. Fills the popup's Name filter with the request's organization name and clicks Search.
3. Clicks the first result row.
4. Waits for the popup to close (it's expected to write the picked values back onto the parent page itself, then call `window.close()` — that's exactly what `org_popup.html`'s `selectOrg()` does against the local dashboard, and is a common pattern for these older ASP/PHP-style popups).
5. Re-reads Organization ID from the parent page to confirm it actually changed, and logs the picked organization.

If any step fails (icon not found, popup never opens, no result row) it falls back to the old behavior: pause and ask you to pick the organization manually in the browser. This has been validated end-to-end against the local dashboard's Jordan Lee scenario (§3.2); re-verify it against the real popup with `--debug-selectors` before trusting it in `--mode commit`.

## 10. Testing safely

1. Run the demo (`--mode demo`) until you understand the flow.
2. Run the local dashboard (`--mode local`) with the sample data, and check all 3 scenarios in §3.2 land correctly.
3. Import your own realistic (but not sensitive) test cases into the local dashboard and repeat.
4. Run `--debug-selectors` on the real system and fix the constants (including the popup ones in §9).
5. Dry-run on the real system with `--max-requests 1`, then a few more.
6. Commit with `--max-requests 1`, verify the saved request in QuickCap, then run without the cap.
7. Only add `--send-email` once approvals/rejections are proven correct.
8. Review `logs/run_*.csv` and the before/after screenshots after every session.
9. If anything looks wrong mid-run, press `Ctrl+C` — the script stops immediately, and any request currently open in the browser is left for you to finish manually.

## 11. What gets logged

Each processed request appends a row to `logs/run_YYYY-MM-DD.csv`:

`timestamp, token_number, full_name, email, organization_name, action, generated_username, notes`

where `action` is one of `approved`, `approved_after_popup_pick`, `approved_after_manual`, `rejected`, `dry_run_approved`, `dry_run_rejected`, or `error`. Screenshots are saved as `screenshots/<token>_<before_save|after_save|error>_<time>.png`. Note that logs and screenshots may contain names, emails, and Tax IDs — treat these folders as sensitive, keep them on an approved machine, and don't commit them to source control.

## 12. Known limitations

- **Selectors are text-based guesses until you tune them for the real system.** They currently match the local carbon-copy dashboard exactly (by construction); the `--debug-selectors` + constant-update pass in §6 Step 1 is not optional on a real installation.
- **The organization popup automation (§9) assumes a window.opener-style popup** (new window, fills the parent form, closes itself). If the real QuickCap popup instead reloads the *same* tab, or is an in-page modal (`<dialog>`/overlay `<div>`) rather than a new window, `pick_organization_via_popup` needs a different approach — `page.context.expect_page()` won't fire for those. `--debug-selectors` on the opened popup will show you which case you're in.
- **Framesets/iframes:** if your QuickCap renders inside an iframe, the helpers need a frame handle instead of `page` (e.g. `page.frame_locator("iframe").locator(...)` or pass `page.frames[n]`). The debug dump printing almost nothing on a page that clearly has fields is the telltale sign.
- **Pagination:** the script processes the rows visible in the current results page. If pending requests span multiple pages, in commit mode they will surface as earlier ones are saved; in dry-run you may need to page manually.
- **Token numbers** are read from the second column of the list row (and the detail page as fallback); if your column order differs, adjust `peek_row_summary` usage in `main.py`.
- **No CAPTCHA/MFA/session handling by design.** If the session expires mid-run, the script detects the login page, pauses, and waits for you to log back in manually.
- Usernames are capped at 99 collisions (`jsmith01`–`jsmith99`) before falling back to a time-based suffix.
- The local dashboard's filter/pagination logic is a best-effort approximation (plain string comparisons, no real date parsing for Followup From/To) — it's meant for small hand-picked test sets, not load-testing.

## 13. Project structure

```text
quickcap_request_automation/
├── main.py                    # CLI, Chrome connection, main processing loop
├── config.py                  # .env loading, folders, tunable option texts
├── quickcap_pages.py          # Page Object Model + UPDATE ME selector constants
├── utils.py                   # DOM helpers, username generator, logging, screenshots
├── run_webapp.py              # starts the local carbon-copy dashboard (Flask)
├── import_requests.py         # loads JSON files into the dashboard's pending queue
├── requirements.txt
├── .env.example                # copy to .env and edit (no secrets!)
├── webapp/                    # the local carbon-copy dashboard
│   ├── app.py                  # Flask routes: list, detail, org/group popups
│   ├── store.py                 # JSON-file "database" + filtering/import logic
│   ├── templates/               # list.html, detail.html, org_popup.html, group_popup.html
│   ├── static/                  # style.css, app.js
│   └── data/
│       ├── organizations.json    # fabricated seed orgs (tracked)
│       ├── org_users.json        # fabricated seed org users (tracked)
│       ├── groups.json           # fabricated seed virtual groups (tracked)
│       └── sandbox_state.json    # your imported pending queue (gitignored)
├── samples/
│   └── sample_pending_requests.json   # 3 worked scenarios (tracked)
├── demo/                      # bundled static sample pages for --mode demo
├── data/import/                # drop your own JSON exports here (gitignored)
├── logs/                      # CSV run logs (created automatically)
├── screenshots/                # before/after screenshots (created automatically)
└── data/                       # reserved for exports (created automatically)
```