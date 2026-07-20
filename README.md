# QuickCap "Request To Login" Automation

Safe, UI-only browser automation for the authorized QuickCap admin workflow: filter pending login requests, open each one, check for duplicate emails against the Organization User Details table, resolve ambiguous organizations via the search popup, then approve (with an auto-generated username) or reject (with a note) — with logging and screenshots.

**What it never does:** it never logs in for you, never touches MFA or CAPTCHA, never calls backend APIs, never stores credentials, and never sends emails unless you pass `--send-email` and confirm each one. It also never opens a request that wasn't submitted **today** — see §9 below.

---

## Quick Start

Already set up once before? Open **any** terminal — a plain Windows PowerShell window from the Start menu, `cmd.exe`, or VS Code — and run:

```powershell
& "c:\Users\nguyen.hang_tecqpart\Downloads\quickcap_request_automation\quickcap_request_automation\quickcap.bat"
```

(or double-click `quickcap.bat` in File Explorer). That's the whole command — it finds its own venv and runs the automation, no `Activate.ps1` step needed. If you `cd` into the project folder first, it's just `.\quickcap.bat`.

Then pick a mode when prompted (`1` manual, `2` assisted, `3` auto). **While in manual mode**, at any "Fields filled..." pause you can type `a` instead of pressing Enter to switch to fully-automatic for the rest of the run — see §3.1.

Prefer the venv-activation style instead? That still works the same as before:

```powershell
cd "c:\Users\nguyen.hang_tecqpart\Downloads\quickcap_request_automation\quickcap_request_automation"
.\.venv\Scripts\Activate.ps1
quickcap
```

(This one only works from a shell whose PowerShell execution policy allows running scripts — see the note in §2 if it's blocked. `quickcap.bat` above avoids that entirely, which is why it's the default recommendation.)

**First time ever?** Run these once, in order, then use `quickcap.bat` (or the block above) from now on:

```powershell
cd "c:\Users\nguyen.hang_tecqpart\Downloads\quickcap_request_automation\quickcap_request_automation"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
playwright install chromium
copy .env.example .env
```

Then open `.env` and set `QUICKCAP_URL` / `QUICKCAP_REQUEST_LIST_URL` to your real QuickCap address (already done if `.env` exists and has these filled in). Full details, all flags, and troubleshooting are in the numbered sections below.

---

## 1. Prerequisites (Windows)

- Windows 10/11
- Python 3.11 or newer — check with `python --version`
- Google Chrome installed
- VS Code (recommended) with the Python extension

## 2. Setup — step by step

Open a terminal in VS Code (`Terminal > New Terminal`, use PowerShell) inside the `quickcap_request_automation` folder, then:

**Step 1 — Create and activate a virtual environment**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then try again. Your prompt should now start with `(.venv)`. Note that Windows PowerShell 5.1 (`powershell.exe`, opened from the Start menu) and PowerShell 7 (`pwsh.exe`, sometimes what VS Code's integrated terminal uses) track this policy **separately** — fixing it in one doesn't fix it in the other. `quickcap.bat` (§3) sidesteps this entirely by never calling `Activate.ps1` at all, so it's the more reliable option if you use more than one kind of terminal.

**Step 2 — Install dependencies**

```powershell
pip install -r requirements.txt
pip install -e .
playwright install chromium
```

The first command installs Playwright and python-dotenv. The second (`pip install -e .`) registers a `quickcap` command on your `PATH` (inside the venv) — see §3. `playwright install chromium` downloads a bundled browser used by `--debug-selectors` sanity checks; day-to-day runs drive your real, installed Chrome instead (see §4).

**Step 3 — Create your .env file**

```powershell
copy .env.example .env
```

Open `.env` in VS Code and set `QUICKCAP_URL` / `QUICKCAP_REQUEST_LIST_URL` to your QuickCap installation. Do **not** put any password in this file — there is no field for one, on purpose.

---

## 3. Running it

Three equivalent ways to start the automation — pick whichever fits where you're typing:

| Command | Needs venv activated? | Works from |
|---|---|---|
| `quickcap.bat` | No | any terminal, or double-click in File Explorer |
| `quickcap` | Yes (`pip install -e .` done once, §2) | any terminal, once activated |
| `python main.py` | Yes | any terminal, once activated |

All three accept the same flags and land in the same code. `quickcap.bat` (§Quick Start) is the one to reach for from a plain Windows PowerShell/`cmd.exe` window where you haven't activated the venv.

With no arguments, it prompts you to choose a mode:

```text
Choose a mode:
  1) Manual autofill   - fill fields only; you click Save yourself
  2) Auto (confirm)    - fills and asks y/n before every Save & Next
  3) Fully automatic   - fills and saves without asking each time
Enter 1, 2, or 3:
```

- **Manual autofill** (`--mode manual`) — the script fills every field (status, username, note, organization resolution) but never clicks Save. It pauses so you can review the request and click Save yourself in the browser.
- **Auto, confirm each save** (`--mode assisted`) — fills the fields, then asks `y/N` before every Save & Next. Answering `n`/Enter skips that Save (nothing changes) and stops the run.
- **Fully automatic** (`--mode auto`) — fills and saves without asking each time. Use once you trust the fills (see §6's recommended order).

Pass `--mode manual|assisted|auto` on the command line to skip the interactive prompt (useful for scripting).

### 3.1 Switching from manual to fully-automatic mid-run

You don't have to restart the script to change your mind about manual mode. Every time it pauses in manual mode, it asks:

```text
>>> Fields filled. Press Enter once you've clicked Save yourself, or type
'a' to switch to FULLY AUTOMATIC for the rest of this run:
```

- Press **Enter** (or anything other than `a`) — behaves exactly as before: fields stay filled, you click Save yourself, the script waits for the next request.
- Type **`a`** — the *current* request is saved automatically right away (fields are already filled, so it just proceeds through the normal auto save/retry logic), and every request after it for the rest of this run is handled in fully-automatic mode too, with no further prompts.

There's no prompt to switch back down to manual or to assisted mid-run — if you want that, stop the script (`Ctrl+C`) and start a new run in the mode you want. This is one-way by design: manual → auto is a deliberate "take over from here," not a toggle.

This upgrade prompt is *not* offered if you chose **Manual** for the older, not-today pending requests batch (§9) — that batch stays manual-only for the rest of the run, deliberately, since reaching past today is itself an explicit, per-run opt-in. (If you instead chose **Auto** for that batch, it's already running automatically, bounded by the request count you gave — see §9.)

---

## 4. Connect to Chrome (two options)

### Option A — Let the script launch Chrome (simplest)

```powershell
quickcap --mode assisted --chrome launch
```

Playwright launches your installed Chrome with a persistent profile stored in `chrome-profile/` (configurable via `CHROME_PROFILE_DIR`). The first time, the script will detect the QuickCap login screen and pause — log in manually in that window (including MFA if any), navigate to the Request To Login list, then press Enter in the terminal. The session is remembered for future runs.

### Option B — Attach to a Chrome you started yourself (CDP)

1. Close **all** Chrome windows (check the system tray too).
2. Start Chrome from PowerShell with remote debugging:

   ```powershell
   & "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\quickcap-automation-profile"
   ```

3. In that Chrome window, log in to QuickCap manually and open the Request To Login page. Leave that tab open.
4. Run the script:

   ```powershell
   quickcap --mode assisted --chrome connect
   ```

5. The script connects to `http://localhost:9222` (configurable via `CHROME_DEBUG_URL` in `.env`) and starts from that existing QuickCap tab. It will not navigate away first unless you pass `--start-page goto`. When the script exits, it disconnects but never closes your Chrome.

If connection fails, confirm nothing else is using port 9222 and that you used a **separate** `--user-data-dir` (Chrome refuses debugging on your default profile).

## 5. Recommended order for a new QuickCap installation

**Step 1 — Map the selectors on your pages**

```powershell
quickcap --debug-selectors --chrome connect
```

This prints every input (name/id/placeholder), every dropdown with its exact option texts, every button/link caption, and the visible section headings on the current page. Answer `y` at the prompt to navigate to the detail page in the browser and dump that too. Compare the output with the `UPDATE ME` constants at the top of `quickcap_pages.py` — they're placeholder guesses (is the reject option called "Rejected" or "Denied"? Is the org-name field called "Organization Name" or "Name of the Organization"? What's the exact "Req. Date" column header text?). Also re-check `ORG_SEARCH_ICON_SELECTOR` — your installation's popup trigger (if it has one) almost certainly isn't `#orgSearchBtn`.

**Step 2 — A few requests in assisted mode**

```powershell
quickcap --mode assisted --chrome connect --max-requests 2
```

The script fills the status/username/note fields and stops before every Save and asks for confirmation. Press Enter (i.e., answer "no") to skip saving — nothing is changed. Visually verify in the browser that the right fields got the right values, and check the CSV log (`assisted_declined_approve` / `assisted_declined_reject` rows).

**Step 3 — Commit for real**

```powershell
quickcap --mode auto --chrome connect
```

Now Save / Save & Next is actually clicked. Start with `--max-requests 1` if you want to save one request and inspect the result.

**Step 4 — (Optional) allow sending emails**

```powershell
quickcap --mode auto --chrome connect --send-email
```

Even with the flag, the script asks you to confirm before clicking "Click to Send Email" on each request. Without the flag, the button is never clicked.

## 6. All CLI options

```text
quickcap                                 # prompts for manual/assisted/auto
quickcap --mode manual                   # fill only, you click Save yourself
quickcap --mode assisted                 # fill + confirm before every Save
quickcap --mode auto                     # fill + save, no per-request prompt
quickcap --mode auto --send-email
quickcap --debug-selectors               # dump page elements and exit
quickcap --chrome launch|connect         # Option A (default) or Option B
quickcap --start-page auto|current|goto
quickcap --max-requests N                # stop after N requests
```

`--start-page auto` is the default. With `--chrome connect`, auto means "use the existing Chrome tab I already opened." With `--chrome launch`, auto navigates to `QUICKCAP_REQUEST_LIST_URL`.

## 7. How to customize selectors

All page-specific text lives in the constants at the top of `quickcap_pages.py`, each marked `UPDATE ME`:

- **Labels** (`FIRST_NAME_LABEL`, `EMAIL_LABEL`, `STATUS_DROPDOWN_LABEL`, ...) — the helpers find the input/select next to that visible text, which works for both modern label markup and old `<td>Label</td><td><input></td>` layouts. Change the text to match what you see on screen. Watch for one label being a substring of another (e.g. an old "NPI" constant would also match "Organization NPI") — `find_input_by_label` takes the first DOM match, so an ambiguous substring can silently fill the wrong field. `NOTE_LABEL` is deliberately `"Note:"` (with the colon) so it doesn't also match "External User Notes".
- **Button captions** (`SEARCH_BUTTON_TEXT`, `SAVE_BUTTON_TEXTS`, `SEND_EMAIL_BUTTON_TEXT`) — matched against button text, link text, or an input's `value`.
- **`EDIT_ICON_SELECTOR`** — a CSS selector for the edit icon column. Run `--debug-selectors` on the list page; if your edit links have a different `title`/`alt`/`href` pattern, adjust it.
- **`HEADER_ROW_SELECTOR`** / **`STATUS_COLUMN_HEADER_TEXT`** / **`REQ_DATE_COLUMN_HEADER_TEXT`** — drive column-position-based status and same-day-guard detection on the list page (see §9 and §10). Change these only if your header row isn't `tr.hdr` and isn't the table's first row either, or if the Status/Req. Date column header text differs from "Status"/"Req. Date".
- **`ORG_DETAILS_TABLE_TITLE`** / **`ORG_USER_TABLE_TITLE`** and the column hints — used to locate and parse the Organization Details / Organization User Details tables by their heading and header row text.
- **`ORG_SEARCH_ICON_SELECTOR`**, **`ORG_POPUP_NAME_LABEL`**, **`ORG_POPUP_SEARCH_BUTTON_TEXT`**, **`ORG_POPUP_RESULT_ROW_SELECTOR`**, **`ORG_ID_SELECT_ID`** — drive multi-organization resolution (see §8).
- **Detail-page element ids** (`FIRST_NAME_INPUT_ID`, `EMAIL_INPUT_ID`, `ORG_NAME_INPUT_ID`, `USERNAME_INPUT_ID`, `APPROVAL_NAME_INPUT_ID`, `STATUS_SELECT_ID`, `NOTE_TEXTAREA_ID` and its `REJECTED_`/`ADDITIONAL_INFO_` siblings, `BACK_LINK_TEXT`, ...) — grouped just above `class RequestDetailPage` in `quickcap_pages.py`. Preferred over the label constants above on detail pages that nest tables deeply enough that label-text matching can silently grab an unrelated wrapper cell — `_read_field()` tries the id first and only falls back to label search when it's blank or not found. Leave any of these as `""` to skip straight to label search for that field. Find the real ids with `--debug-selectors` on an open request.
- **`ORG_GROUP_ICON_SELECTOR`**, **`ORG_GROUP_INPUT_ID`**, **`ORG_GROUP_POPUP_NAME_LABEL`**, **`ORG_GROUP_POPUP_SEARCH_BUTTON_TEXT`**, **`ORG_GROUP_POPUP_RESULT_LINK_SELECTOR`**, **`ORG_DETAILS_TABLE_BODY_ID`** — drive the optional Organization Group popup (see §8.1).

If a label-based lookup can't work for some field and there's no id constant for it yet, you can replace the call in `quickcap_pages.py` with a direct locator, e.g. `self.page.locator("#txtUserName")`, using the id/name printed by `--debug-selectors`. XPath is available as a fallback (`page.locator("xpath=...")`) but prefer ids, names, and visible text — they survive layout changes better.

## 8. How the multi-organization popup automation works

`RequestDetailPage.detect_organization_count()` figures out whether this request's Tax ID maps to more than one Organization ID. When Organization ID is a plain `<select>` (`ORG_ID_SELECT_ID`, `#slt_OrgId`) that always has some option selected by default, the count comes from the select's own option count. Otherwise it falls back to: if Organization ID is already filled in, assume it's resolved (count = 1); otherwise count distinct Organization IDs in the Organization Details table.

If that count is `> 1`, `handle_new_user()` in `main.py` calls `RequestDetailPage.pick_organization_via_popup(organization_name)`, which tries two different mechanisms:

1. **Plain `<select>`, no popup** (`_pick_organization_via_select()`, tried first): if `ORG_SEARCH_ICON_SELECTOR` matches nothing, there is no popup — the select's default option is not necessarily the right one for this specific request. Confirmed live against a real 3-candidate request: the "Organization NPI" field (`ORG_NPI_FIELD_ID`, `#Taara_OrganizationNPI`) holds the *exact target Organization ID* for this request, not a separate NPI number, and it matches one of the select's option values directly — `select_option(value=npi)` picks it. Returns `None` (falling through to the popup flow, which will also find nothing and fail cleanly) if the NPI field is blank or matches no option.
2. **Search-icon popup** (used only when no `#slt_OrgId` select exists): clicks the search icon (`ORG_SEARCH_ICON_SELECTOR`), waits for the popup window (`page.context.expect_page()`), fills the popup's Name filter with the request's organization name, clicks Search, clicks the first result row, and waits for the popup to close (it's expected to write the picked values back onto the parent page via `window.opener`, then call `window.close()`). Re-reads Organization ID from the parent page to confirm it actually changed.

If both mechanisms fail (no select, and popup icon/popup/result not found) it falls back to the old behavior: pause and ask you to pick the organization manually in the browser.

### 8.1 Organization Group (optional)

Once Status is set to Approved, some detail forms reveal a separate "Organization Group" field with its own search icon (`ORG_GROUP_ICON_SELECTOR`, `#img_for_organization_group` — a stable id, not tied to any specific request). This is a different concept from Organization ID/NPI resolution above: it assigns the org to a business-level *Virtual Group* (e.g. a health system), and there's no field on the request itself — no NPI-style exact signal — that reliably says which group is correct. Because of that, this step is opt-in rather than automatic:

1. `RequestDetailPage.has_organization_group_icon()` checks whether the icon is present and visible (i.e. Status=Approved was just set).
2. If so, `handle_new_user()` in `main.py` prompts: *"An Organization Group search icon was found. Search for and select a group matching '`\<name>`'? [y/N]"*. Answering "no" (or Enter) skips this step entirely, leaving Organization Group blank, same as if the icon didn't exist.
3. The `<name>` searched is **not** `d.organization_name` (the top "*Name of the Organization" field) — it's read fresh from the *Organization Details table's own row* for the resolved Organization ID, via `RequestDetailPage.read_organization_details_name(organization_id)`, reading `<tbody id="orgTableBody">` directly. Confirmed live the two can differ in formatting (e.g. "AeroCare Home Medical, Inc" in the table vs. "AeroCare Home Medical Inc" in the top field). Falls back to `d.organization_name` if that row lookup finds nothing.
4. Before searching, any trailing corporate suffix after a comma is stripped (`"AeroCare Home Medical, Inc"` → `"AeroCare Home Medical"`) — confirmed live that virtual group names don't carry that suffix.
5. `pick_organization_group_via_popup(name_query)` clicks the icon, waits for the popup window, fills its Name filter, clicks Search, and picks a result: an exact case-insensitive match first, else the first result whose name *contains* the query as a substring. If answered "yes" but no match is found either way, it deliberately does **not** guess — the popup is left open and `main.py` pauses for you to pick manually, since assigning the wrong business group on a real approval is a real data-integrity concern, not just a cosmetic miss.
6. Unlike the Organization ID popup, this one does **not** close itself after a row is picked — `pick_organization_group_via_popup` closes it explicitly on a successful pick, and leaves it open on the no-match path described above.

### 8.2 Retrying Save on a silent username collision

`generate_username()` avoids collisions against the usernames visible in *this org's* Organization User Details table (`jsmith01`, `jsmith02`, ...). But username uniqueness is typically checked **system-wide** — against every organization, not just this one — and a system-wide collision can produce no visible error: clicking Save just leaves the exact same request's detail form displayed, unchanged, with no indication why.

`RequestDetailPage.save_advanced(email_before)` works around that by comparing the Email field's value before and after the click: if it's now different (a new/next request loaded) or the field is gone entirely (back at the list), Save went through. If it still reads the same email for the whole poll window (up to 5s), Save silently did not go through.

In `handle_new_user()`, clicking Save (in `auto`/`assisted` modes) is a bounded retry loop (up to 10 attempts): on a detected non-advance, `utils.bump_username()` increments the username's trailing number (`jsmith02` → `jsmith03`, preserving digit width; rolls over to a time-based suffix past the same 99-collision point `generate_username()` itself falls back at), refills the Username field, and retries. The final username actually used — not necessarily the first one generated — is what gets logged and what appears in the after-save screenshot. If all attempts are exhausted, or the Save button itself can't be found, it falls back to `manual_pause()`.

## 9. Only today's requests are touched by default — with an opt-in to go further

Every mode enforces the same rule before opening any pending row: its **Req. Date** column must match today's date. This is deliberate — the automation should never reach back and modify a request that's been sitting pending from an earlier day without a human deciding to, explicitly, on the spot.

How it works (`main.py`'s `_find_next_target()` / `run()`):

1. Each pass, pending rows are scanned from the top. A row whose Req. Date doesn't parse to today (`utils.is_today()`, via `RequestListPage.pending_row_req_date()`) is **skipped and logged once** (`skipped_old_request` in the CSV) — it stays in the Pending list, untouched, while today's requests are being worked through.
2. The first row whose Req. Date *is* today becomes the target: opened, processed, and — regardless of outcome — marked "handled" for the rest of this run, so it's never re-offered even if a Save is declined (`assisted`) or deliberately left unsaved (`manual`).
3. This scan repeats every pass (the list is re-filtered after each request), so it also naturally handles the case where saved rows disappear from the list (`auto` mode) while skipped older rows remain in place.
4. **Once today's requests run out**, if any older pending requests remain, you're asked once:
   ```text
   No more of TODAY's pending requests found. 3 older pending request(s) remain.

   Process the older (not today's) pending requests too?
     1) No       - stop here; leave them pending
     2) Manual   - fill only, you click Save yourself, one at a time
     3) Auto     - fill and save automatically, for a number of requests you specify
   Enter 1, 2, or 3:
   ```
   - **1) No** — stops the run there; those older requests stay pending, untouched, exactly like today.
   - **2) Manual** — switches to **manual mode for the rest of the run, with no option to switch back to auto** for that batch (see §3.1) — every older request from here on is filled in and left for you to review and Save yourself, one at a time, no matter what mode the run started in.
   - **3) Auto** — asks a follow-up question, *"How many older pending requests do you want to process automatically?"* — a plain number, re-prompted until you give a positive integer. That count is a hard cap on this older/auto batch specifically (separate from, and on top of, `--max-requests` for the run overall): once that many older requests have been auto-saved, the run stops itself even if more remain pending. There's no "unlimited" option here on purpose — auto-processing requests from before today always requires you to say exactly how many, on the spot.

   Either way, this choice is asked **once** — after that, the run either stays in manual for the rest of the older batch, or keeps auto-processing older requests up to the number you gave, with no further prompts about it.

`REQ_DATE_COLUMN_HEADER_TEXT` in `quickcap_pages.py` (default `"Req. Date"`) is an `UPDATE ME` constant like `STATUS_COLUMN_HEADER_TEXT` — verify the exact header text with `--debug-selectors` / by inspecting the list page, same as §10 below.

## 10. How pending-row status is detected

The results table is a plain HTML grid: a header row (`<tr class="hdr">`, or the table's first row if that class isn't present) followed by data rows, each with an edit-icon column identifying it as a real row (as opposed to the header or a trailing pager row). Each data row's cells line up 1-to-1 with the header row's cells.

`RequestListPage` uses that structure instead of guessing:

1. `_column_index(table, header_text)` reads the header row once per call and returns the 0-based position of the cell whose text exactly matches `header_text` (case-insensitive) — used for both `STATUS_COLUMN_HEADER_TEXT` and `REQ_DATE_COLUMN_HEADER_TEXT` (§9).
2. `_rows_by_status(text)` reads each data row's `<td>` at the Status column's position and compares it to `text`, case-insensitively. Rows are found via the edit-icon column, so header/pager rows are never mistaken for data.
3. `count_pending_rows()`, `_pending_rows()`, and `open_request()` all go through `_rows_by_status(config.PENDING_STATUS_OPTION)`.

This avoids matching "Pending" as a substring anywhere in the row's accessible name (any cell, not just the Status cell), which could misfire on an organization name or note that happens to contain the word "Pending" (or "Approved"/"Rejected"). `read_row_status(row)` / `read_row_req_date(row)` expose per-row lookups directly, by column position, for logging/diagnostics. If the header row can't be found or has no matching cell, `_rows_by_status` falls back to a whole-row substring match rather than matching zero rows silently.

### 10.1 Two more things that can make Pending rows read as zero even when the table itself is correct

- **The Search click can land on the wrong control.** On an installation where the QuickCap page hosts more than one module in the same DOM, a page-wide text match for "Search" can hit an unrelated control first and silently navigate away from the list. `filter_pending_and_search()` scopes the click to the Status select's own `<form>` (or nearest ancestor `<table>`) instead.
- **The results grid can refresh over AJAX, not a real page load**, meaning `wait_for_load_state("domcontentloaded")` after Search is a no-op and briefly reports 0 rows mid-refresh. `RequestListPage._wait_for_results_to_settle()` polls the edit-icon count until it's non-zero and stable across two consecutive checks.

### 10.2 The detail page: nested-table markup, id-based fields, and AJAX transitions

- **Deeply nested layout tables** can make a generic "find the `<td>` containing this label text" search match an outer wrapper cell instead of the actual label cell. `_read_field()` tries a real element id first (the `*_INPUT_ID` constants) and only falls back to label search when the id is blank or not found.
- **Organization ID may be a `<select>`, not a search-icon popup** — see §8.
- **Multiple Note fields, each shown only for its own Status.** `fill_note()` fills whichever of the note fields is currently *visible*, matching whatever `set_status()` just selected.
- **Opening a row, searching, and clicking Back can each be AJAX transitions** rather than real navigations. `open_request()`, `filter_pending_and_search()`, and `go_back_to_list()` each poll briefly for the expected content to actually appear rather than trusting `wait_for_load_state` alone.

## 11. Testing safely

1. Run `--debug-selectors` against your real system and fix the constants in `quickcap_pages.py` (including the popup ones in §8, the status/date column ones in §10, and `REQ_DATE_COLUMN_HEADER_TEXT` in §9).
2. Run `--mode assisted` with `--max-requests 1`, then a few more, declining every Save and checking the browser + `logs/run_*.csv` match what you expect.
3. Run `--mode auto` with `--max-requests 1`, verify the saved request in QuickCap, then run without the cap.
4. Only add `--send-email` once approvals/rejections are proven correct.
5. Review `logs/run_*.csv` and the before/after screenshots after every session.
6. If anything looks wrong mid-run, press `Ctrl+C` — the script stops immediately, and any request currently open in the browser is left for you to finish manually.

## 12. What gets logged

Each processed (or skipped) request appends a row to `logs/run_YYYY-MM-DD.csv`:

`timestamp, token_number, full_name, email, organization_name, action, generated_username, notes`

where `action` is one of `approved`, `approved_after_popup_pick`, `approved_after_manual`, `rejected`, `manual_filled_approve`, `manual_filled_reject`, `assisted_declined_approve`, `assisted_declined_reject`, `skipped_old_request`, or `error`. Screenshots are saved as `screenshots/<token>_<before_save|after_save|filled|error>_<time>.png`. Note that logs and screenshots may contain names, emails, and Tax IDs — treat these folders as sensitive, keep them on an approved machine, and don't commit them to source control.

## 13. Known limitations

- **Selectors are text-based guesses until you tune them for your installation.** The `--debug-selectors` + constant-update pass in §5 Step 1 is not optional.
- **The organization popup automation (§8) assumes a window.opener-style popup** (new window, fills the parent form, closes itself). If your QuickCap popup instead reloads the *same* tab, or is an in-page modal (`<dialog>`/overlay `<div>`) rather than a new window, `pick_organization_via_popup` needs a different approach — `page.context.expect_page()` won't fire for those. `--debug-selectors` on the opened popup will show you which case you're in.
- **Framesets/iframes:** if your QuickCap renders inside an iframe, the helpers need a frame handle instead of `page` (e.g. `page.frame_locator("iframe").locator(...)` or pass `page.frames[n]`). The debug dump printing almost nothing on a page that clearly has fields is the telltale sign.
- **Pagination:** the script processes the rows visible in the current results page. If pending requests span multiple pages, in `auto` mode they will surface as earlier ones are saved; in `assisted`/`manual` you may need to page manually.
- **Token numbers** are read from the second column of the list row (and the detail page as fallback); if your column order differs, adjust `_extract_token` in `main.py`.
- **No CAPTCHA/MFA/session handling by design.** If the session expires mid-run, the script detects the login page, pauses, and waits for you to log back in manually.
- Usernames are capped at 99 collisions (`jsmith01`–`jsmith99`) before falling back to a time-based suffix.
- **The Req. Date guard (§9) depends on `REQ_DATE_COLUMN_HEADER_TEXT` matching your installation's exact column header**, and on the cell text parsing as `MM-DD-YYYY` or `MM/DD/YYYY` — verify both with `--debug-selectors` before your first `auto`/`assisted` run.
- **Organization Group substring matching (§8.1) can pick a plausible-but-wrong group** if more than one virtual group name happens to contain the searched (comma-stripped) organization name as a substring — it takes the *first* such result, not necessarily the best one. It's gated behind a per-request "yes/no" prompt for exactly this reason; check the popup/screenshot before confirming Save if the organization name is generic or short.

## 14. Project structure

```text
quickcap_request_automation/
├── main.py                    # CLI, mode selection, Chrome connection, main processing loop
├── config.py                  # .env loading, folders, tunable option texts
├── quickcap_pages.py          # Page Object Model + UPDATE ME selector constants
├── utils.py                   # DOM helpers, username generator, date guard, logging, screenshots
├── quickcap.bat                # run from any terminal without activating the venv
├── pyproject.toml             # packaging — registers the `quickcap` console command
├── requirements.txt
├── .env.example                # copy to .env and edit (no secrets!)
├── logs/                      # CSV run logs (created automatically)
├── screenshots/                # before/after screenshots (created automatically)
└── chrome-profile/             # persistent Chrome profile for --chrome launch (created automatically)
```
