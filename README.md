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
- **`HEADER_ROW_SELECTOR`** / **`STATUS_COLUMN_HEADER_TEXT`** — drive column-position-based status detection on the list page (see §10). Change these only if your header row isn't `tr.hdr` and isn't the table's first row either, or if the Status column header text isn't literally "Status".
- **`ORG_DETAILS_TABLE_TITLE`** / **`ORG_USER_TABLE_TITLE`** and the column hints — used to locate and parse the Organization Details / Organization User Details tables by their heading and header row text.
- **`ORG_SEARCH_ICON_SELECTOR`**, **`ORG_POPUP_NAME_LABEL`**, **`ORG_POPUP_SEARCH_BUTTON_TEXT`**, **`ORG_POPUP_RESULT_ROW_SELECTOR`**, **`ORG_ID_SELECT_ID`** — drive multi-organization resolution (see §9): the real system's plain `<select>` and the local dashboard's popup, respectively.
- **Detail-page element ids** (`FIRST_NAME_INPUT_ID`, `EMAIL_INPUT_ID`, `ORG_NAME_INPUT_ID`, `USERNAME_INPUT_ID`, `APPROVAL_NAME_INPUT_ID`, `STATUS_SELECT_ID`, `NOTE_TEXTAREA_ID` and its `REJECTED_`/`ADDITIONAL_INFO_` siblings, `BACK_LINK_TEXT`, ...) — grouped just above `class RequestDetailPage` in `quickcap_pages.py`. Preferred over the label constants above on the real system, whose detail page nests tables deeply enough that label-text matching can silently grab an unrelated wrapper cell (see §10.2) — `_read_field()` tries the id first and only falls back to label search when it's blank or not found. Leave any of these as `""` to skip straight to label search for that field. Find the real ids with `--debug-selectors` on an open request.
- **`ORG_GROUP_ICON_SELECTOR`**, **`ORG_GROUP_INPUT_ID`**, **`ORG_GROUP_POPUP_NAME_LABEL`**, **`ORG_GROUP_POPUP_SEARCH_BUTTON_TEXT`**, **`ORG_GROUP_POPUP_RESULT_LINK_SELECTOR`**, **`ORG_DETAILS_TABLE_BODY_ID`** — drive the optional Organization Group popup (see §9.1). Only relevant on the real system; the local dashboard has no equivalent.

If a label-based lookup can't work for some field and there's no id constant for it yet, you can replace the call in `quickcap_pages.py` with a direct locator, e.g. `self.page.locator("#txtUserName")`, using the id/name printed by `--debug-selectors`. XPath is available as a fallback (`page.locator("xpath=...")`) but prefer ids, names, and visible text — they survive layout changes better.

## 9. How the multi-organization popup automation works

`RequestDetailPage.detect_organization_count()` figures out whether this request's Tax ID maps to more than one Organization ID. On the real system, Organization ID is a plain `<select>` (`ORG_ID_SELECT_ID`, `#slt_OrgId`) that always has some option selected by default — so the count comes from the select's own option count. On the local carbon-copy dashboard (no such select), it falls back to: if Organization ID is already filled in, assume it's resolved (count = 1); otherwise count distinct Organization IDs in the Organization Details table.

If that count is `> 1`, `handle_new_user()` in `main.py` calls `RequestDetailPage.pick_organization_via_popup(organization_name)`, which now tries two different mechanisms depending on what the installation actually has:

1. **Real system — plain `<select>`, no popup at all** (`_pick_organization_via_select()`, tried first): `ORG_SEARCH_ICON_SELECTOR` matches nothing on the real system — there is no popup. The select's default option is not necessarily the right one for this specific request. Confirmed live against a real 3-candidate request: the "Organization NPI" field (`ORG_NPI_FIELD_ID`, `#Taara_OrganizationNPI`) holds the *exact target Organization ID* for this request, not a separate NPI number, and it matches one of the select's option values directly — `select_option(value=npi)` picks it. Returns `None` (falling through to the popup flow, which will also find nothing and fail cleanly) if the NPI field is blank or matches no option.
2. **Local dashboard — search-icon popup** (used only when no `#slt_OrgId` select exists): clicks the search icon (`ORG_SEARCH_ICON_SELECTOR`), waits for the popup window (`page.context.expect_page()`), fills the popup's Name filter with the request's organization name, clicks Search, clicks the first result row, and waits for the popup to close (it writes the picked values back onto the parent page itself via `window.opener`, then calls `window.close()` — see `org_popup.html`'s `selectOrg()`). Re-reads Organization ID from the parent page to confirm it actually changed.

If both mechanisms fail (no select, and popup icon/popup/result not found) it falls back to the old behavior: pause and ask you to pick the organization manually in the browser. Validated end-to-end against both the local dashboard's Jordan Lee scenario (§3.2, popup path) and a real pending request (§10.2, select path).

### 9.1 Organization Group (optional, real system only)

Once Status is set to Approved, the real detail form reveals a separate "Organization Group" field with its own search icon (`ORG_GROUP_ICON_SELECTOR`, `#img_for_organization_group` — a stable id, not tied to any specific request). This is a different concept from Organization ID/NPI resolution above: it assigns the org to a business-level *Virtual Group* (e.g. a health system like "Memorial Hermann System" or "Houston Methodist"), and there's no field on the request itself — no NPI-style exact signal — that reliably says which group is correct. Because of that, this step is opt-in rather than automatic:

1. `RequestDetailPage.has_organization_group_icon()` checks whether the icon is present and visible (i.e. Status=Approved was just set).
2. If so, `handle_new_user()` in `main.py` prompts: *"An Organization Group search icon was found. Search for and select a group matching '`\<name>`'? [y/N]"*. Answering "no" (or Enter) skips this step entirely, leaving Organization Group blank, same as if the icon didn't exist.
3. The `<name>` searched is **not** `d.organization_name` (the top "*Name of the Organization" field) — it's read fresh from the *Organization Details table's own row* for the resolved Organization ID, via `RequestDetailPage.read_organization_details_name(organization_id)`, reading the real system's `<tbody id="orgTableBody">` directly. Confirmed live the two can differ in formatting (e.g. "AeroCare Home Medical, Inc" in the table vs. "AeroCare Home Medical Inc" in the top field). Falls back to `d.organization_name` if that row lookup finds nothing.
4. Before searching, any trailing corporate suffix after a comma is stripped (`"AeroCare Home Medical, Inc"` → `"AeroCare Home Medical"`) — confirmed live that virtual group names don't carry that suffix, so leaving it in caused an exact-match search to come back empty on a group that did, in fact, exist ("Aerocare Home Medical").
5. `pick_organization_group_via_popup(name_query)` clicks the icon, waits for the popup window, fills its Name filter, clicks Search, and picks a result: an exact case-insensitive match first, else the first result whose name *contains* the query as a substring. If answered "yes" but no match is found either way, it deliberately does **not** guess — the popup is left open and `main.py` pauses for you to pick manually, since assigning the wrong business group on a real approval is a real data-integrity concern, not just a cosmetic miss.
6. Unlike the Organization ID popup, this one does **not** close itself after a row is picked (confirmed live: `selectOnlyOneGroup(...)` only writes the value back via `window.opener`) — `pick_organization_group_via_popup` closes it explicitly on a successful pick, and leaves it open on the no-match path described above.

Validated end-to-end against a real pending request: with the comma-suffix stripped, the search correctly found and selected the matching "Aerocare Home Medical" virtual group, visible in a `before_save` screenshot, with the Save confirmation declined so nothing was written.

### 9.2 Retrying Save on a silent username collision

`generate_username()` avoids collisions against the usernames visible in *this org's* Organization User Details table (`jsmith01`, `jsmith02`, ...). But username uniqueness on the real system is checked **system-wide** — against every organization, not just this one — and a system-wide collision produces no visible error: clicking Save just leaves the exact same request's detail form displayed, unchanged, with no indication why. There's no error text to detect.

`RequestDetailPage.save_advanced(email_before)` works around that by comparing the Email field's value before and after the click: if it's now different (a new/next request loaded) or the field is gone entirely (back at the list), Save went through. If it still reads the same email for the whole poll window (up to 5s), Save silently did not go through.

In `handle_new_user()`, clicking Save is now a bounded retry loop (up to 10 attempts): on a detected non-advance, `utils.bump_username()` increments the username's trailing number (`jsmith02` → `jsmith03`, preserving digit width; rolls over to a time-based suffix past the same 99-collision point `generate_username()` itself falls back at), refills the Username field, and retries. The final username actually used — not necessarily the first one generated — is what gets logged and what appears in the after-save screenshot. If all attempts are exhausted, or the Save button itself can't be found, it falls back to the existing `manual_pause()` behavior.

This has been regression-tested for the *happy path* (a real confirmed save on the local dashboard's Casey Nguyen scenario succeeds on the first attempt, no spurious retries — `save_advanced` returns immediately there since the local dashboard has no `Tatxt_email_address` id to poll). The actual silent-collision retry path has **not** yet been exercised against a real duplicate on the live system — that needs a real request that happens to generate a colliding username to confirm end-to-end; watch for the "Save did not advance — likely a username collision..." message on a real run.

## 10. How pending-row status is detected

The results table on the real system is a plain HTML grid: a header row (`<tr class="hdr">`) followed by data rows (`<tr id="tr_list<reportId>_<n>" class="data1">` / `class="data2">`, alternating) and a trailing pager row (`<tr class="pgr">`). Each data row's cells line up 1-to-1 with the header row's cells — the header's Status column has a sortable link (`<a href="javascript:QL_Submit(...)">Status</a>`), and the row below it holds the plain-text status ("Pending", "Approved", "Rejected", ...) at that exact same `<td>` position.

`RequestListPage` uses that structure instead of guessing:

1. `_status_column_index()` reads the header row once per call — `tr.hdr` if present, otherwise the table's first `<tr>` (the local demo/dashboard fixtures have no `hdr` class, so this keeps them working too) — and returns the 0-based position of the cell whose text is exactly `STATUS_COLUMN_HEADER_TEXT` ("Status").
2. `_rows_by_status(text)` reads each data row's `<td>` at that exact position and compares it to `text`, case-insensitively. Rows are still found via the edit-icon column (the header and pager rows have no edit icon), so the header/pager rows are never mistaken for data.
3. `count_pending_rows()`, `_pending_rows()`, and `open_request()` all go through `_rows_by_status(config.PENDING_STATUS_OPTION)`.

This replaced an earlier version that matched "Pending" as a substring anywhere in the row's accessible name (any cell, not just the Status cell) — which could misfire on an organization name or note that happened to contain the word "Pending" (or "Approved"/"Rejected"), and which offered no way to check a specific row's status on demand. `read_row_status(row)` exposes that per-row lookup directly, by the same column position, for logging/diagnostics.

If the header row can't be found or has no cell matching `STATUS_COLUMN_HEADER_TEXT` (e.g. an installation with a genuinely different markup shape), `_rows_by_status` falls back to the old whole-row substring match rather than matching zero rows silently. Run `--debug-selectors` and, if needed, adjust `HEADER_ROW_SELECTOR` / `STATUS_COLUMN_HEADER_TEXT` at the top of `quickcap_pages.py` to match what you see.

### 10.1 Two more things that can make Pending rows read as zero even when the table itself is correct

Both of these were found by attaching read-only to a real, already-logged-in session (`--chrome connect`) and comparing `count_pending_rows()` before/after each step of `filter_pending_and_search()` — worth repeating if `count_pending_rows()` reports 0 while the browser clearly shows pending rows.

- **The Search click can land on the wrong control.** `filter_pending_and_search()` used to click "Search" with a page-wide text match (`utils.click_button_by_text(self.page, ...)`). On an installation where the QuickCap page hosts more than one module in the same DOM (this one reaches "Request To Login" via `link_module`/`link_id` + a URL hash, alongside other modules like "Virtual Group" that stay present off-screen), a page-wide match can hit an unrelated control first — e.g. a global icon-only "Search" button — and silently navigate the SPA away from the list instead of searching it. `count_pending_rows()` then correctly reports 0, because the page genuinely isn't showing the list anymore. Fixed by scoping the click to the Status select's own `<form>` (or nearest ancestor `<table>`) via `utils.click_button_by_text(container, ...)`, which now accepts a `Locator` to search only its descendants instead of the whole page — note it deliberately uses `.//` (not `//`) for the scoped XPath candidates, since a bare `//` is anchored to the document root even inside a scoped `Locator.locator()` call and would silently defeat the scoping.
- **The results grid refreshes over AJAX, not a real page load.** Even once Search reliably hits the right button, `wait_for_load_state("domcontentloaded")` afterward is a no-op on the real system — the underlying document already finished loading once, long before Search was clicked, and the grid updates without a real navigation. Confirmed live: right after the click, the grid briefly has **zero** edit icons for a few hundred milliseconds while old rows are cleared and new ones inserted, so counting immediately after the click reports 0 pending even though the true count (e.g. 30) shows up moments later. `RequestListPage._wait_for_results_to_settle()` now polls the edit-icon count after Search and waits for it to be non-zero and stable across two consecutive checks (bounded by a timeout, since a genuinely empty result list also reads as 0 the whole time and the two cases can't be told apart from row count alone).

### 10.2 The detail page: nested-table markup, id-based fields, and two more AJAX transitions

Opening a real pending request surfaced a second, larger set of issues — every field on the detail page read back blank (`--- Request 20260715-3445 :  <> @`), not just Email. Root-caused the same way as §10.1: attach read-only via `--chrome connect` to an already-open request and inspect the live DOM/values directly rather than guessing from the local dashboard's markup.

- **The detail form nests tables several levels deep for layout.** `_read_field()`'s old fallback path looks for the `<td>` whose text *contains* the label (e.g. "First Name"), then reads the next sibling `<td>`. On the real detail page that same substring match hits an *outer wrapper* `<td>` several nesting levels up just as often as the actual label cell — Playwright's `.first` takes whichever comes first in document order, which is usually the outer one — so `following-sibling::td[1]` lands on an unrelated cell and every field reads empty. Fixed by reading real, stable element ids first (`FIRST_NAME_INPUT_ID`, `EMAIL_INPUT_ID`, `ORG_NAME_INPUT_ID`, etc. — the full list is in `quickcap_pages.py` just above `RequestListPage`, found via `--debug-selectors` against a real request), falling back to label search only when an id is blank or not found (keeps the local demo/dashboard fixtures, which don't share these ids, working exactly as before).
- **Organization ID is a `<select>`, not a search-icon popup — see §9.** Confirmed live: `#slt_OrgId` lists every Organization ID sharing the request's Tax ID and defaults to its first option regardless of correctness; the "Organization NPI" field holds the actual target Organization ID and is used to pick the right option.
- **Three separate Note fields, each shown only for its own Status.** `Taara_note` ("Note:") is the generic/default one, `Taara_rejected_note` ("Reject Note:") only appears once Status=Rejected, and `Taara_additional_info_note` ("Additional Information Required:") only for that status — all three contain the substring "Note:" in their label, so label search alone can't tell them apart once more than one exists in the DOM. `fill_note()` now fills whichever of the three is currently *visible*, which automatically matches whatever `set_status()` just selected.
- **Opening a row is a third AJAX transition, on top of Search (§10.1) and the new "Back" navigation below.** `open_request()` used to click the edit icon and only wait for `domcontentloaded` — a no-op here too, since the real system swaps the detail form into the exact same URL/page instead of navigating. Confirmed live: `extract_details()` ran before the swap finished and read every field as blank, reproducing the original bug even with the id-based fields in place. Fixed by comparing `page.url` before/after the click — if it's unchanged (the AJAX case), `_wait_for_detail_page()` polls briefly for a detail-page field id to appear before returning. Demo/local modes navigate to a genuinely different URL, so this poll is skipped there entirely (no added latency).
- **Getting back to the list also can't rely on `page.goto(list_url)`.** After processing (or erroring on) a request, the old `return_to_list()` reloaded the list URL. Confirmed live this doesn't reliably work on the real system: the server session can keep showing whatever sub-view (e.g. the same detail form) was last open instead of resetting to the list, and a hard reload also risks landing on a different module entirely if the base URL's `file=` parameter doesn't point at "Request To Login" (the exact failure in §10.1's Search bug, triggered a different way). The detail page has its own `Back` link (`BACK_LINK_TEXT`); `RequestDetailPage.go_back_to_list()` clicks it and polls for the list's header row to reappear (same AJAX-settle reasoning as above), and `return_to_list()` in `main.py` now tries this first, falling back to the old goto-based approach only when no `Back` control is found.

All of the above were verified against a real pending request end-to-end: `python main.py --mode dry-run --chrome connect` correctly read every field, generated a collision-free username, resolved the correct Organization ID among 3 candidates via NPI matching, set Status=Approved, and filled the approval Name field — all visible in a `before_save` screenshot — with the Save confirmation declined so nothing was written.

## 11. Testing safely

1. Run the demo (`--mode demo`) until you understand the flow.
2. Run the local dashboard (`--mode local`) with the sample data, and check all 3 scenarios in §3.2 land correctly.
3. Import your own realistic (but not sensitive) test cases into the local dashboard and repeat.
4. Run `--debug-selectors` on the real system and fix the constants (including the popup ones in §9 and the status-column ones in §10).
5. Dry-run on the real system with `--max-requests 1`, then a few more.
6. Commit with `--max-requests 1`, verify the saved request in QuickCap, then run without the cap.
7. Only add `--send-email` once approvals/rejections are proven correct.
8. Review `logs/run_*.csv` and the before/after screenshots after every session.
9. If anything looks wrong mid-run, press `Ctrl+C` — the script stops immediately, and any request currently open in the browser is left for you to finish manually.

## 12. What gets logged

Each processed request appends a row to `logs/run_YYYY-MM-DD.csv`:

`timestamp, token_number, full_name, email, organization_name, action, generated_username, notes`

where `action` is one of `approved`, `approved_after_popup_pick`, `approved_after_manual`, `rejected`, `dry_run_approved`, `dry_run_rejected`, or `error`. Screenshots are saved as `screenshots/<token>_<before_save|after_save|error>_<time>.png`. Note that logs and screenshots may contain names, emails, and Tax IDs — treat these folders as sensitive, keep them on an approved machine, and don't commit them to source control.

## 13. Known limitations

- **Selectors are text-based guesses until you tune them for the real system.** They currently match the local carbon-copy dashboard exactly (by construction); the `--debug-selectors` + constant-update pass in §6 Step 1 is not optional on a real installation.
- **The organization popup automation (§9) assumes a window.opener-style popup** (new window, fills the parent form, closes itself). If the real QuickCap popup instead reloads the *same* tab, or is an in-page modal (`<dialog>`/overlay `<div>`) rather than a new window, `pick_organization_via_popup` needs a different approach — `page.context.expect_page()` won't fire for those. `--debug-selectors` on the opened popup will show you which case you're in.
- **Framesets/iframes:** if your QuickCap renders inside an iframe, the helpers need a frame handle instead of `page` (e.g. `page.frame_locator("iframe").locator(...)` or pass `page.frames[n]`). The debug dump printing almost nothing on a page that clearly has fields is the telltale sign.
- **Pagination:** the script processes the rows visible in the current results page. If pending requests span multiple pages, in commit mode they will surface as earlier ones are saved; in dry-run you may need to page manually.
- **Token numbers** are read from the second column of the list row (and the detail page as fallback); if your column order differs, adjust `peek_row_summary` usage in `main.py`.
- **No CAPTCHA/MFA/session handling by design.** If the session expires mid-run, the script detects the login page, pauses, and waits for you to log back in manually.
- Usernames are capped at 99 collisions (`jsmith01`–`jsmith99`) before falling back to a time-based suffix.
- The local dashboard's filter/pagination logic is a best-effort approximation (plain string comparisons, no real date parsing for Followup From/To) — it's meant for small hand-picked test sets, not load-testing.
- **Organization Group substring matching (§9.1) can pick a plausible-but-wrong group** if more than one virtual group name happens to contain the searched (comma-stripped) organization name as a substring — it takes the *first* such result, not necessarily the best one. It's gated behind a per-request "yes/no" prompt for exactly this reason; check the popup/screenshot before confirming Save if the organization name is generic or short.

## 14. Project structure

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