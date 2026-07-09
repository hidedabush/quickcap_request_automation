# QuickCap "Request To Login" Automation

Safe, UI-only browser automation for the authorized QuickCap admin workflow: filter pending login requests, open each one, check for duplicate emails against the Organization User Details table, then approve (with an auto-generated username) or reject (with a note) — with logging, screenshots, and a dry-run-first design.

**What it never does:** it never logs in for you, never touches MFA or CAPTCHA, never calls backend APIs, never stores credentials, and never sends emails unless you pass `--send-email` and confirm each one. The default mode is a dry run that fills fields but does not click Save without your confirmation.

---

## 1. Prerequisites (Windows)

- Windows 10/11
- Python 3.11 or newer — check with `python --version`
- Google Chrome installed (only needed for live runs; the demo uses Playwright's bundled Chromium)
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

`playwright install chromium` downloads the bundled browser used by demo mode. Live runs use your installed Google Chrome.

**Step 3 — Create your .env file**

```powershell
copy .env.example .env
```

Open `.env` in VS Code and set `QUICKCAP_URL` and `QUICKCAP_REQUEST_LIST_URL` to your real QuickCap URLs. Do **not** put any password in this file — there is no field for one, on purpose.

**Step 4 — Verify the install with the demo (do this first!)**

```powershell
python main.py --mode demo
```

## 3. Run the dry-run DEMO first (no real system touched)

Demo mode opens three bundled local HTML pages (`demo/list.html` and three detail pages) that mimic the QuickCap layout. It exercises every branch of the logic:

| Demo request | Scenario | Expected result |
|---|---|---|
| TK-1001 John Smith | Email already exists in Organization User Details (case-insensitive match) | Status → Rejected, note "Account already exists for this email address.", the "Click to Send Email" button is present but **not** clicked |
| TK-1002 Mary O'Neil | New email, but username `moneil01` already taken | Status → Approved, username `moneil02` |
| TK-1003 Bob Lee | New email, no conflicts | Status → Approved, username `blee01` |

What you'll see: a Chromium window opens, the script selects Status=Pending, clicks Search, opens each request, fills the fields, takes a `before_save` screenshot, and then **pauses in the terminal** asking you to confirm before clicking Save — exactly like a real dry run. Type `y` to watch it save, or press Enter to skip. Afterwards check:

- `logs/run_YYYY-MM-DD.csv` — one row per request with token, name, email, org, action, generated username, timestamp, notes
- `screenshots/` — before/after images named by token

When the demo behaves as expected, move on to the real system — still in dry-run mode.

## 4. Connect to Chrome (two options)

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

3. In that Chrome window, log in to QuickCap manually and open the Request To Login page.
4. Run the script from VS Code:

   ```powershell
   python main.py --mode dry-run --chrome connect
   ```

5. The script connects to `http://localhost:9222` (configurable via `CHROME_DEBUG_URL` in `.env`) and drives that same browser. When the script exits, it disconnects but never closes your Chrome.

If connection fails, confirm nothing else is using port 9222 and that you used a **separate** `--user-data-dir` (Chrome refuses debugging on your default profile).

## 5. Running against the real system

Always in this order:

**Step 1 — Map the selectors on your pages**

```powershell
python main.py --debug-selectors --chrome connect
```

This prints every input (name/id/placeholder), every dropdown with its exact option texts, every button/link caption, and the visible section headings on the current page. Answer `y` at the prompt to navigate to the detail page in the browser and dump that too. Compare the output with the `UPDATE ME` constants at the top of `quickcap_pages.py` (e.g. is the reject option called "Rejected" or "Denied"? Is the note field "Note", "Message", or "Comments"?) and adjust the constants.

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

## 6. All CLI options

```text
python main.py --mode dry-run            # default; confirm before any Save
python main.py --mode commit             # actually save
python main.py --mode commit --send-email
python main.py --mode demo               # bundled local sample pages
python main.py --debug-selectors         # dump page elements and exit
python main.py --chrome launch|connect   # Option A (default) or Option B
python main.py --max-requests N          # stop after N requests
```

## 7. How to customize selectors

All page-specific text lives in the constants at the top of `quickcap_pages.py`, each marked `UPDATE ME`:

- **Labels** (`FIRST_NAME_LABEL`, `EMAIL_LABEL`, `STATUS_DROPDOWN_LABEL`, ...) — the helpers find the input/select next to that visible text, which works for both modern label markup and old `<td>Label</td><td><input></td>` layouts. Change the text to match what you see on screen.
- **Button captions** (`SEARCH_BUTTON_TEXT`, `SAVE_BUTTON_TEXTS`, `SEND_EMAIL_BUTTON_TEXT`) — matched against button text, link text, or an input's `value`.
- **`EDIT_ICON_SELECTOR`** — a CSS selector for the edit icon column. Run `--debug-selectors` on the list page; if your edit links have a different `title`/`alt`/`href` pattern, adjust it. As a last resort you can hardcode something like `table.grid tr td:first-child a`.
- **`ORG_USER_TABLE_TITLE`** and the column hints — used to locate and parse the Organization User Details table by its heading and header row text.

If a label-based lookup can't work for some field, you can replace the call in `quickcap_pages.py` with a direct locator, e.g. `self.page.locator("#txtUserName")`, using the id/name printed by `--debug-selectors`. XPath is available as a fallback (`page.locator("xpath=...")`) but prefer ids, names, and visible text — they survive layout changes better.

## 8. Testing safely

1. Run the demo (`--mode demo`) until you understand the flow.
2. Run `--debug-selectors` and fix the constants.
3. Dry-run with `--max-requests 1`, then a few more.
4. Commit with `--max-requests 1`, verify the saved request in QuickCap, then run without the cap.
5. Only add `--send-email` once approvals/rejections are proven correct.
6. Review `logs/run_*.csv` and the before/after screenshots after every session.
7. If anything looks wrong mid-run, press `Ctrl+C` — the script stops immediately, and any request currently open in the browser is left for you to finish manually.

## 9. What gets logged

Each processed request appends a row to `logs/run_YYYY-MM-DD.csv`:

`timestamp, token_number, full_name, email, organization_name, action, generated_username, notes`

where `action` is one of `approved`, `approved_after_manual`, `rejected`, `dry_run_approved`, `dry_run_rejected`, or `error`. Screenshots are saved as `screenshots/<token>_<before_save|after_save|error>_<time>.png`. Note that logs and screenshots may contain names, emails, and Tax IDs — treat these folders as sensitive, keep them on an approved machine, and don't commit them to source control.

## 10. Known limitations

- **Multiple-organization popup is not automated yet.** If the script detects (or suspects) more than one candidate organization, it pauses and asks you to pick the organization manually in the browser; there is a `TODO` marker in `quickcap_pages.py` / `main.py` where the popup workflow can be added after you inspect that popup with `--debug-selectors`. Detection itself is a heuristic and defaults to "single org" — if your multi-org cases aren't being caught, tighten `detect_organization_count()` for your HTML.
- **Selectors are text-based guesses until you tune them.** The first `--debug-selectors` + constant-update pass is not optional on a real installation.
- **Framesets/iframes:** if your QuickCap renders inside an iframe, the helpers need a frame handle instead of `page` (e.g. `page.frame_locator("iframe").locator(...)` or pass `page.frames[n]`). The debug dump printing almost nothing on a page that clearly has fields is the telltale sign.
- **Pagination:** the script processes the rows visible in the current results page. If pending requests span multiple pages, in commit mode they will surface as earlier ones are saved; in dry-run you may need to page manually.
- **Token numbers** are read from the second column of the list row (and the detail page as fallback); if your column order differs, adjust `peek_row_summary` usage in `main.py`.
- **No CAPTCHA/MFA/session handling by design.** If the session expires mid-run, the script detects the login page, pauses, and waits for you to log back in manually.
- Usernames are capped at 99 collisions (`jsmith01`–`jsmith99`) before falling back to a time-based suffix.

## 11. Project structure

```text
quickcap_request_automation/
├── main.py              # CLI, Chrome connection, main processing loop
├── config.py            # .env loading, folders, tunable option texts
├── quickcap_pages.py    # Page Object Model + UPDATE ME selector constants
├── utils.py             # DOM helpers, username generator, logging, screenshots
├── requirements.txt
├── .env.example         # copy to .env and edit (no secrets!)
├── demo/                # local sample pages for --mode demo
├── logs/                # CSV run logs (created automatically)
├── screenshots/         # before/after screenshots (created automatically)
└── data/                # reserved for exports (created automatically)
```
