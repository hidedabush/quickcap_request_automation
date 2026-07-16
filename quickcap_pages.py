"""
quickcap_pages.py
-----------------
Page Object Model for the QuickCap "Request To Login" area.

Two page objects:
  - RequestListPage : the search filters + results table.
  - RequestDetailPage : the edit form opened via the edit icon.

IMPORTANT — SELECTORS:
QuickCap installations differ. All the guessable text labels and button
captions live in the CONSTANTS below, clearly marked with "UPDATE ME".
Run `python main.py --debug-selectors` on each page, look at the printed
names/ids/labels, and adjust these constants. The helper functions in
utils.py search by visible text, so in many cases they will work as-is.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from playwright.sync_api import Page

import config
import utils


# ===========================================================================
# UPDATE ME: visible text used to locate things on YOUR QuickCap pages.
# Run --debug-selectors and adjust as needed.
# ===========================================================================

# --- List page -------------------------------------------------------------
STATUS_FILTER_LABEL = "Status"          # label next to the status dropdown
SEARCH_BUTTON_TEXT = "Search"           # search button caption
RESULTS_TABLE_HINT = "Token"            # a word that appears in the results
                                        # table header row (used to find it)
EDIT_ICON_SELECTOR = (                  # how edit icons/links are marked;
    "a[title*='Edit' i], img[alt*='Edit' i], a:has(img[alt*='Edit' i]), "
    "a[href*='edit' i]"
)

# The results table's header row. The real system marks it `<tr class="hdr">`
# (data rows below it are `<tr id="tr_list<reportId>_<n>" class="data1">` /
# `class="data2">` alternating, with a trailing `<tr class="pgr">` pager row).
# Some installations don't use a "hdr" class at all, so this selector is
# tried first and _column_index() falls back to "first row of the table"
# when it matches nothing.
HEADER_ROW_SELECTOR = "tr.hdr"
STATUS_COLUMN_HEADER_TEXT = "Status"    # exact (case-insensitive) header text

# The request's submission-date column, used to enforce the same-day guard
# (only ever act on a request submitted today — see main.py's row-selection
# loop). Located the same way as the Status column, by exact header text.
REQ_DATE_COLUMN_HEADER_TEXT = "Req. Date"

# --- Detail page -----------------------------------------------------------
# These are placeholder defaults — run --debug-selectors against the real
# QuickCap system and re-check each one before relying on them. In
# particular, watch for a label being a *substring* of another label (e.g.
# the old "NPI" constant would also match "Organization NPI") or a shorter
# label appearing later in the DOM than a longer one that contains it (e.g.
# "Note" vs "External User Notes") — find_input_by_label() takes the FIRST
# DOM match, so ambiguous substrings can silently fill the wrong field.
FIRST_NAME_LABEL = "First Name"
LAST_NAME_LABEL = "Last Name"
TITLE_LABEL = "Title"
EMAIL_LABEL = "Email"
ORG_ID_LABEL = "Organization ID"
ORG_TAX_ID_LABEL = "Organization Tax ID"
ORG_NAME_LABEL = "Name of the Organization"
ORG_NPI_LABEL = "Organization NPI"
USERNAME_LABEL = "User Name"
# The "Name" field inside the Approval-details section (only visible once
# Status=Approved). Left alone it defaults to the organization name in some
# QuickCap deployments — it must be filled with the requester's own first
# + last name instead. "*Name:" (asterisk + trailing colon) avoids matching
# "*First Name:" / "*Last Name:" / "*User Name:" / "*Name of the
# Organization:", all of which contain "Name" but not the "*Name:" substring.
APPROVAL_NAME_LABEL = "*Name:"
APPROVAL_NAME_LABEL_ALTERNATIVES = ["*Name:", "Name:"]
STATUS_DROPDOWN_LABEL = "Status"
NOTE_LABEL = "Note:"                    # trailing ":" avoids matching
                                        # "External User Notes"
NOTE_LABEL_ALTERNATIVES = ["Note:", "Note", "Message", "Comments"]

ORG_DETAILS_TABLE_TITLE = "Organization Details"
ORG_USER_TABLE_TITLE = "Organization User Details"
ORG_USER_EMAIL_COLUMN_HINTS = ["email"]      # substrings to find email column
ORG_USER_USERNAME_COLUMN_HINTS = ["user"]    # substrings for username column
# The Organization Details table's data rows, on the real system, live in
# their own <tbody id="orgTableBody"> — confirmed live, more precise than
# ORG_DETAILS_TABLE_TITLE's heading-based search for reading a specific
# row's name (see read_organization_details_name()). Each row's first
# <td> is "<b>{Organization ID}</b><br>{Organization Name}".
ORG_DETAILS_TABLE_BODY_ID = "orgTableBody"

SAVE_BUTTON_TEXTS = ["Save & Next", "Save and Next", "Save"]
SEND_EMAIL_BUTTON_TEXT = "Click to Send Email"
BACK_LINK_TEXT = "Back"

# --- Detail page: real-system element ids (preferred over label search) ---
# The real detail form nests tables several levels deep for layout, so a
# generic "find the <td> containing this label text" search matches an
# OUTER wrapper cell instead of the specific label cell — confirmed live:
# every label-based field read came back empty on the real system, not
# just Email. These ids, read via --debug-selectors against a real
# request, are stable and unambiguous regardless of nesting; _read_field()
# tries the id first and only falls back to label search when it's blank
# or not found. Leave blank ("") for any field your installation doesn't
# expose by id, to fall back to the label constants above.
FIRST_NAME_INPUT_ID = "Tatxt_first_name"
LAST_NAME_INPUT_ID = "Tatxt_last_name"
TITLE_INPUT_ID = "Tatxt_title"
EMAIL_INPUT_ID = "Tatxt_email_address"
ORG_TAX_ID_INPUT_ID = "Tatxt_OrgTaxId"
ORG_NAME_INPUT_ID = "Tatxt_OrgName"
ORG_NPI_FIELD_ID = "Taara_OrganizationNPI"      # <textarea>, not <input>
USERNAME_INPUT_ID = "txt_user_name"
APPROVAL_NAME_INPUT_ID = "txt_name"
STATUS_SELECT_ID = "Taslt_status"

# --- Organization ID resolution (multi-organization Tax IDs) ---------------
# The real system has no search-icon popup at all (ORG_SEARCH_ICON_SELECTOR
# matches nothing there) — Organization ID is a plain <select> (#slt_OrgId)
# listing every Organization ID that shares this request's Tax ID, and it
# always has SOME option selected by default regardless of which one the
# request is actually for. Confirmed live against a real 3-candidate
# request: the "Organization NPI" field (ORG_NPI_FIELD_ID) holds the exact
# target Organization ID for this request, not a separate NPI number, and
# it matches one of the select's option values directly — see
# _pick_organization_via_select(). The popup-based constants below are a
# fallback for an installation whose Organization ID resolution genuinely
# uses a search-icon popup instead of a plain <select>.
ORG_ID_SELECT_ID = "slt_OrgId"
ORG_SEARCH_ICON_SELECTOR = "#orgSearchBtn"
ORG_POPUP_NAME_LABEL = "Name"
ORG_POPUP_SEARCH_BUTTON_TEXT = "Search"
ORG_POPUP_RESULT_ROW_SELECTOR = "tr.pick-row"

# --- Organization Group popup (optional, real system only) -----------------
# Only appears once Status=Approved: an icon next to "Organization Group:"
# opens a popup to search/pick which business-level Virtual Group this
# organization belongs to (e.g. a health system) — a separate concept from
# Organization ID/NPI resolution above, and NOT something derivable from
# the request's own data the way NPI-matching is, so this is opt-in via an
# explicit confirmation prompt rather than run automatically. Confirmed
# live: the icon's id is stable regardless of which request is open,
# clicking a result row (`a[onclick^='selectOnlyOneGroup']`) writes the
# picked name/id back onto the parent page via window.opener same as the
# Organization ID popup, but — unlike that popup — does NOT close itself
# afterward, so pick_organization_group_via_popup() closes it explicitly.
ORG_GROUP_ICON_SELECTOR = "#img_for_organization_group"
ORG_GROUP_INPUT_ID = "txtVirtualOrg"
ORG_GROUP_POPUP_NAME_LABEL = "Name"
ORG_GROUP_POPUP_SEARCH_BUTTON_TEXT = "Search"
ORG_GROUP_POPUP_RESULT_LINK_SELECTOR = "a[onclick^='selectOnlyOneGroup']"

# --- Note fields (real system) ---------------------------------------------
# Three separate note textareas exist, each revealed only for its matching
# Status: "Reject Note:" (REJECTED_NOTE_TEXTAREA_ID) only when
# Status=Rejected, "Additional Information Required:"
# (ADDITIONAL_INFO_NOTE_TEXTAREA_ID) only for that status, and a generic
# "Note:" (NOTE_TEXTAREA_ID) otherwise. fill_note() fills whichever one is
# currently visible, so it automatically matches whatever set_status() just
# selected instead of guessing by label text alone (all three labels
# contain the substring "Note:", so a plain label search can't tell them
# apart once more than one exists in the DOM).
NOTE_TEXTAREA_ID = "Taara_note"
REJECTED_NOTE_TEXTAREA_ID = "Taara_rejected_note"
ADDITIONAL_INFO_NOTE_TEXTAREA_ID = "Taara_additional_info_note"

# Page-title text that indicates we landed on a login page instead of the app.
# Do not use a bare "login" substring here: the legitimate page title
# "Request To Login" contains it.
LOGIN_PAGE_TITLE_HINTS = [
    "sign in",
    "log in",
    "login page",
    "quickcap login",
    "member login",
]
APP_PAGE_TITLE_HINTS = ["request to login"]


# ===========================================================================
# Data container for one request
# ===========================================================================

@dataclass
class RequestDetails:
    token_number: str = ""
    first_name: str = ""
    last_name: str = ""
    title: str = ""
    email: str = ""
    organization_id: str = ""
    organization_tax_id: str = ""
    organization_name: str = ""
    organization_npi: str = ""
    existing_user_emails: list[str] = field(default_factory=list)
    existing_usernames: list[str] = field(default_factory=list)
    organization_count: int = 1     # >1 triggers manual org selection

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


# ===========================================================================
# List page
# ===========================================================================

class RequestListPage:
    """The 'Request To Login' list: filters on top, results table below."""

    def __init__(self, page: Page):
        self.page = page

    # -- navigation ---------------------------------------------------------

    def goto(self) -> None:
        """Navigate to the configured Request To Login list URL, if set."""
        url = config.QUICKCAP_REQUEST_LIST_URL
        if url:
            self.page.goto(url, timeout=config.DEFAULT_TIMEOUT_MS * 2)
        self.page.wait_for_load_state("domcontentloaded")

    def looks_like_login_page(self) -> bool:
        """Return True only when the current page looks like an actual login."""
        # Hidden/stale login controls can remain in an authenticated page's
        # markup, so only a visible password input is decisive.
        if self.page.locator("input[type=password]:visible").count() > 0:
            return True
        # QuickCap keeps checklogin=1 in authenticated URLs. The route/hash,
        # not that query parameter, identifies the Request To Login screen.
        if "meds_request_login" in (self.page.url or "").lower():
            return False
        title = " ".join((self.page.title() or "").lower().split())
        if any(hint in title for hint in APP_PAGE_TITLE_HINTS):
            return False
        return title == "login" or any(
            hint in title for hint in LOGIN_PAGE_TITLE_HINTS
        )

    def ensure_logged_in(self) -> None:
        """
        NEVER automates login. If a login screen is detected, pause and let
        the user log in manually in the visible Chrome window.
        """
        while self.looks_like_login_page():
            utils.manual_pause(
                "Login screen detected. Please log in to QuickCap manually "
                "in the Chrome window (including any MFA/CAPTCHA), navigate "
                "to the Request To Login list, then"
            )
            self.page.wait_for_load_state("domcontentloaded")

    # -- filtering ----------------------------------------------------------

    def filter_pending_and_search(self) -> None:
        """
        Set Status filter = Pending and click Search, scoped to the Status
        select's own <form> (or nearest ancestor <table>, for older
        layouts with no <form>) rather than the whole page.

        This QuickCap installation hosts more than one module in the same
        DOM at once (reached via link_module/link_id + URL-hash routing —
        "Request To Login" is one, "Virtual Group" another). A page-wide
        text match for "Search" can land on an unrelated control, such as
        a global icon-only search button, which silently navigates the
        SPA away from the list entirely instead of searching it — the
        script then finds 0 pending rows because it's no longer looking
        at the Request To Login list at all. Scoping to the filter form
        avoids that ambiguity.
        """
        status = utils.find_select_by_label(self.page, STATUS_FILTER_LABEL)
        if status is None:
            utils.manual_pause(
                f"Could not find the '{STATUS_FILTER_LABEL}' filter dropdown. "
                "Please set Status=Pending and click Search manually, then"
            )
        else:
            chosen = utils.select_option_by_visible_text(
                status, [config.PENDING_STATUS_OPTION])
            if chosen is None:
                utils.manual_pause(
                    "'Pending' option not found in the Status filter. "
                    "Please set the filter manually, then")

            search_scope = status.locator("xpath=ancestor::form[1]")
            if search_scope.count() == 0:
                search_scope = status.locator("xpath=ancestor::table[1]")
            search_target = (search_scope.first if search_scope.count() > 0
                             else self.page)

            if not utils.click_button_by_text(search_target, SEARCH_BUTTON_TEXT):
                utils.manual_pause(
                    f"Could not find the '{SEARCH_BUTTON_TEXT}' button near "
                    "the Status filter. Please click Search manually, then")
        self.page.wait_for_load_state("domcontentloaded")
        self._wait_for_results_to_settle()

    def _wait_for_results_to_settle(self, timeout_ms: int = 5000) -> None:
        """
        Search reloads the results grid via AJAX on the real system — no
        real navigation happens, so wait_for_load_state("domcontentloaded")
        above is a no-op (the document already finished loading once, long
        before Search was clicked). Confirmed live: right after the click,
        the grid briefly has zero edit icons while old rows are cleared and
        new ones are inserted (~0.3-0.6s), so counting immediately reports
        0 pending even though the real count is non-zero moments later.
        Poll until the edit-icon count is non-zero and identical across two
        consecutive checks (i.e. no longer mid-refresh), or give up after
        `timeout_ms` — a genuinely empty result list also reads as 0 the
        whole time, so this can't distinguish "still loading" from "really
        empty" and intentionally errs toward waiting the full timeout for
        that case rather than guessing.
        """
        icons = self.page.locator(EDIT_ICON_SELECTOR)
        deadline = time.monotonic() + timeout_ms / 1000
        last_count = -1
        while time.monotonic() < deadline:
            try:
                count = icons.count()
            except Exception:
                count = 0
            if count > 0 and count == last_count:
                return
            last_count = count
            self.page.wait_for_timeout(150)

    # -- reading the results table -------------------------------------------

    def _results_table(self):
        """
        The results grid table, identified as the nearest ancestor <table>
        of the first edit icon on the page. The filter/search form above
        the grid has no edit icons, so this reliably distinguishes the two
        tables without guessing at header markup (<th> vs <td>) that may
        differ between QuickCap installations. Returns None if no edit
        icons are found at all (list is genuinely empty).
        """
        icons = self.page.locator(EDIT_ICON_SELECTOR)
        if icons.count() == 0:
            return None
        return icons.first.locator("xpath=ancestor::table[1]")

    def _column_index(self, table, header_text: str) -> int | None:
        """
        0-based <td> position of the column whose header cell text exactly
        matches `header_text` (case-insensitive), read from the header row
        rather than assumed. Tries the real system's `tr.hdr` header row
        first; if that class isn't present, falls back to the table's
        first <tr>. An exact match (not substring) avoids e.g. a
        hypothetical "Status Date" column being mistaken for "Status".
        Returns None if no header row or no matching cell is found.
        """
        header = table.locator(HEADER_ROW_SELECTOR)
        if header.count() == 0:
            header = table.locator("tr").first
        else:
            header = header.first
        cells = header.locator("th, td")
        wanted = header_text.strip().lower()
        for i in range(cells.count()):
            try:
                text = cells.nth(i).inner_text().strip().lower()
            except Exception:
                continue
            if text == wanted:
                return i
        return None

    def _status_column_index(self, table) -> int | None:
        """0-based position of the Status column (see _column_index)."""
        return self._column_index(table, STATUS_COLUMN_HEADER_TEXT)

    def _req_date_column_index(self, table) -> int | None:
        """0-based position of the Req. Date column (see _column_index)."""
        return self._column_index(table, REQ_DATE_COLUMN_HEADER_TEXT)

    def _rows_by_status(self, status_text: str):
        """
        <tr> elements in the results table whose Status column (found by
        position via _status_column_index, not by guessing) reads
        `status_text` exactly (case-insensitive).

        Counting edit icons alone is not reliable: every row — Approved and
        Rejected included — has one, so if the Status filter silently fails
        to apply (wrong label match, a slow reload, etc.) every visible row
        would get treated as matching. Reading the Status cell by its known
        column index is what actually distinguishes rows, and an exact
        match on that single cell avoids the false positives a substring
        search anywhere in the row could hit (e.g. an organization name or
        note that happens to contain "Pending").

        Falls back to the previous whole-row substring match (Playwright's
        accessible-name search) when the Status column's position can't be
        determined — e.g. an installation with no discoverable header row.

        Scoped to the results table only (see _results_table): searching
        the whole page also matches the filter form's Status <select>,
        whose enclosing <td> computes an accessible name that includes all
        of its option text ("All Pending Approved Rejected..."), which
        falsely matched as a "pending row" with no edit icon in it.
        """
        table = self._results_table()
        if table is None:
            return self.page.locator("tr.__no_results_table_found__")

        status_col = self._status_column_index(table)
        if status_col is None:
            cells = table.get_by_role("cell", name=status_text, exact=False)
            return cells.locator("xpath=ancestor::tr[1]")

        lower_lit = utils._xpath_literal(status_text.strip().lower())
        icons = table.locator(EDIT_ICON_SELECTOR)
        return icons.locator(
            f"xpath=ancestor::tr[1]"
            f"[td[{status_col + 1}]"
            f"[translate(normalize-space(.), "
            f"'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')"
            f"={lower_lit}]]"
        )

    def _pending_rows(self):
        """<tr> elements whose Status column shows config.PENDING_STATUS_OPTION."""
        return self._rows_by_status(config.PENDING_STATUS_OPTION)

    def read_row_status(self, row) -> str:
        """
        Text of one row's Status cell, read by the same column position
        _rows_by_status uses. Returns "" if the column can't be located.
        Useful for logging/diagnostics without re-deriving the index.
        """
        return self._read_row_cell(row, self._status_column_index)

    def read_row_req_date(self, row) -> str:
        """Text of one row's Req. Date cell. Returns "" if not found."""
        return self._read_row_cell(row, self._req_date_column_index)

    def _read_row_cell(self, row, column_index_fn) -> str:
        """Shared by read_row_status/read_row_req_date: text of the cell
        at the column position `column_index_fn` locates."""
        table = self._results_table()
        if table is None:
            return ""
        col = column_index_fn(table)
        if col is None:
            return ""
        cells = row.locator("td")
        if col >= cells.count():
            return ""
        try:
            return cells.nth(col).inner_text().strip()
        except Exception:
            return ""

    def pending_row_req_date(self, index: int) -> str:
        """Req. Date text of pending row `index` (0-based). "" if out of range."""
        rows = self._pending_rows()
        if index >= rows.count():
            return ""
        return self.read_row_req_date(rows.nth(index))

    def count_pending_rows(self) -> int:
        """Count rows whose Status column reads 'Pending'."""
        return self._pending_rows().count()

    def count_edit_icons(self) -> int:
        """
        Raw count of edit icons on the page, regardless of status. Used only
        as a diagnostic: if this is >0 while count_pending_rows() is 0, the
        list has rows but none are being recognized as Pending — a mismatch
        between config.PENDING_STATUS_OPTION and the real Status cell text,
        not an empty list.
        """
        return self.page.locator(EDIT_ICON_SELECTOR).count()

    def peek_row_summary(self, index: int) -> str:
        """Best-effort text of pending row N (for console output only)."""
        rows = self._pending_rows()
        if index >= rows.count():
            return ""
        try:
            cells = rows.nth(index).locator("td")
            texts = [cells.nth(i).inner_text().strip()
                     for i in range(min(cells.count(), 6))]
            return " | ".join(texts)
        except Exception:
            return ""

    def open_request(self, index: int) -> None:
        """
        Click the edit icon inside pending row `index` (0-based) and wait
        for the detail page. Rows/icons are re-located each time because the
        list reloads after every Save & Next.
        """
        rows = self._pending_rows()
        if index >= rows.count():
            raise IndexError(f"No pending row at index {index}")
        row = rows.nth(index)
        icon = row.locator(EDIT_ICON_SELECTOR)
        if icon.count() == 0:
            raise RuntimeError(
                f"Pending row {index} has no edit icon matching "
                f"EDIT_ICON_SELECTOR ({EDIT_ICON_SELECTOR!r}). Run "
                "--debug-selectors and update EDIT_ICON_SELECTOR in "
                "quickcap_pages.py.")
        url_before = self.page.url
        icon.first.click()
        self.page.wait_for_load_state("domcontentloaded")
        if self.page.url == url_before:
            # No real navigation happened -- on the real system, opening a
            # row swaps the detail form into the SAME page via AJAX rather
            # than a normal page load (confirmed live: identical URL/title
            # before and after), the same pattern as Search and Back (see
            # filter_pending_and_search / go_back_to_list). Right after the
            # click the detail form's fields don't exist in the DOM yet;
            # confirmed live this made extract_details() read every field
            # as blank because it ran before the swap finished. Installations
            # that navigate to a genuinely different URL when opening a row
            # skip this poll entirely (url_before != page.url already).
            self._wait_for_detail_page(FIRST_NAME_INPUT_ID)

    def _wait_for_detail_page(self, marker_id: str,
                              timeout_ms: int = 5000) -> None:
        """
        Poll for `marker_id` (a detail-page field id) to appear, bounded by
        `timeout_ms`. A no-op if it never appears — e.g. an installation
        whose detail page doesn't expose this id at all — since that
        should surface as a normal "field not found" error downstream
        rather than a silent multi-second pause on every single request.
        """
        if not marker_id:
            return
        deadline = time.monotonic() + timeout_ms / 1000
        marker = self.page.locator(f"#{marker_id}")
        while time.monotonic() < deadline:
            if marker.count() > 0:
                return
            self.page.wait_for_timeout(150)


# ===========================================================================
# Detail page
# ===========================================================================

class RequestDetailPage:
    """The edit form for a single login request."""

    def __init__(self, page: Page):
        self.page = page

    # -- extraction -----------------------------------------------------------

    def _read_field(self, label: str, input_id: str = "") -> str:
        """
        Read a labeled field's value. `input_id`, when given, is tried
        FIRST via a direct #id locator. On the real system the detail form
        nests tables several levels deep purely for layout, so the
        label-based fallback below — which looks for the <td> containing
        `label`'s text — can match an outer wrapper cell several levels up
        instead of the specific label cell, and read nothing at all;
        confirmed live, this broke EVERY field, not just one. Direct ids
        are immune to that because they don't depend on DOM nesting.
        Falls back to label search when no id is given or it's not found.

        If an <input>/<textarea>/<select> was found, its value is
        authoritative — including an empty string, e.g. an Organization ID
        left blank pending a popup pick — so a genuinely empty input must
        NOT fall through to the plain-text fallback (that cell may also
        contain a search-icon button whose visible text would otherwise be
        mistaken for the field's value). Only when no such element exists
        at all (fully read-only fields rendered as plain text) do we read
        the next table cell's text.
        """
        if input_id:
            loc = self.page.locator(f"#{input_id}")
            if loc.count() > 0:
                try:
                    return (loc.first.input_value() or "").strip()
                except Exception:
                    return ""

        loc = utils.find_input_by_label(self.page, label)
        if loc is not None:
            try:
                return (loc.input_value() or "").strip()
            except Exception:
                return ""
        lit_loc = self.page.locator(
            f"xpath=//td[contains(normalize-space(.), "
            f"{utils._xpath_literal(label)})]/following-sibling::td[1]"
        )
        if lit_loc.count() > 0:
            try:
                return lit_loc.first.inner_text().strip()
            except Exception:
                pass
        return ""

    def extract_details(self, token_number: str = "") -> RequestDetails:
        """Pull all needed values from the form + the org-user table."""
        d = RequestDetails(token_number=token_number)
        d.first_name = self._read_field(FIRST_NAME_LABEL, FIRST_NAME_INPUT_ID)
        d.last_name = self._read_field(LAST_NAME_LABEL, LAST_NAME_INPUT_ID)
        d.title = self._read_field(TITLE_LABEL, TITLE_INPUT_ID)
        d.email = self._read_field(EMAIL_LABEL, EMAIL_INPUT_ID)
        d.organization_id = self._read_field(ORG_ID_LABEL, ORG_ID_SELECT_ID)
        d.organization_tax_id = self._read_field(
            ORG_TAX_ID_LABEL, ORG_TAX_ID_INPUT_ID)
        d.organization_name = self._read_field(
            ORG_NAME_LABEL, ORG_NAME_INPUT_ID)
        d.organization_npi = self._read_field(ORG_NPI_LABEL, ORG_NPI_FIELD_ID)

        # Read the Organization User Details table from the DOM (not pixels).
        rows = utils.read_table_by_section_title(
            self.page, ORG_USER_TABLE_TITLE)
        for row in rows:
            for key, value in row.items():
                key_l = key.lower()
                if any(h in key_l for h in ORG_USER_EMAIL_COLUMN_HINTS):
                    if value:
                        d.existing_user_emails.append(value)
                if any(h in key_l for h in ORG_USER_USERNAME_COLUMN_HINTS):
                    # avoid matching the email column twice ("user email")
                    if "mail" not in key_l and value:
                        d.existing_usernames.append(value)

        d.organization_count = self.detect_organization_count()
        return d

    def detect_organization_count(self) -> int:
        """
        On the real system, Organization ID is a <select> (#slt_OrgId)
        listing every Organization ID sharing this request's Tax ID, and
        it ALWAYS has some option selected by default — so "is
        Organization ID filled in" can't signal single-vs-multi-org here;
        the select's option COUNT is what matters, checked first.

        Falls back to a blank-means-unresolved model — Organization ID
        empty means unresolved, then count distinct ids in the
        "Organization Details" table — when no such select exists.
        """
        select = self.page.locator(f"#{ORG_ID_SELECT_ID}")
        if select.count() > 0:
            return max(select.locator("option").count(), 1)

        if self._read_field(ORG_ID_LABEL).strip():
            return 1

        rows = utils.read_table_by_section_title(
            self.page, ORG_DETAILS_TABLE_TITLE)
        if not rows:
            return 1

        id_col = next(
            (k for k in rows[0].keys() if "organization id" in k.lower()),
            None)
        if not id_col:
            return 1

        distinct_ids = {row.get(id_col, "").strip() for row in rows
                        if row.get(id_col, "").strip()}
        return max(len(distinct_ids), 1)

    def read_organization_id(self) -> str:
        """Current value of the Organization ID field/select."""
        return self._read_field(ORG_ID_LABEL, ORG_ID_SELECT_ID)

    def read_organization_details_name(self, organization_id: str) -> str:
        """
        Read the Organization Name shown in the Organization Details
        table's row for `organization_id` — the canonical per-row name as
        the real system itself displays it, which can differ in
        formatting from the top "*Name of the Organization" field (e.g. a
        trailing comma: "AeroCare Home Medical, Inc" there vs "AeroCare
        Home Medical Inc" in Tatxt_OrgName). Used as the Organization
        Group search query instead of d.organization_name. Returns "" if
        the table or a matching row isn't found.
        """
        if not organization_id:
            return ""
        body = self.page.locator(f"#{ORG_DETAILS_TABLE_BODY_ID}")
        if body.count() == 0:
            return ""
        rows = body.locator("tr")
        for i in range(rows.count()):
            cells = rows.nth(i).locator("td")
            if cells.count() == 0:
                continue
            try:
                lines = [ln.strip() for ln in
                        cells.nth(0).inner_text().split("\n") if ln.strip()]
            except Exception:
                continue
            if lines and lines[0] == organization_id:
                return lines[1] if len(lines) > 1 else ""
        return ""

    def _pick_organization_via_select(self) -> str | None:
        """
        Real-system multi-org resolution: #slt_OrgId lists every
        Organization ID sharing this request's Tax ID but defaults to its
        first option regardless of which one the request is actually for
        — there's no popup to disambiguate (ORG_SEARCH_ICON_SELECTOR
        matches nothing on the real system). Confirmed live against a real
        3-candidate request: the "Organization NPI" field
        (ORG_NPI_FIELD_ID) holds the exact target Organization ID for this
        request, not a separate NPI number, and it matches one of the
        select's option values directly. Selects that option and returns
        it, or None if the NPI field is blank or matches no option.
        """
        select = self.page.locator(f"#{ORG_ID_SELECT_ID}")
        if select.count() == 0:
            return None
        npi = self._read_field(ORG_NPI_LABEL, ORG_NPI_FIELD_ID).strip()
        if not npi:
            return None
        options = select.locator("option")
        for i in range(options.count()):
            opt = options.nth(i)
            if (opt.get_attribute("value") or "").strip() == npi:
                select.first.select_option(value=npi)
                return npi
        return None

    def pick_organization_via_popup(self, name_query: str) -> str | None:
        """
        Resolve Organization ID when more than one candidate shares this
        request's Tax ID. Tries the real system's plain <select> first
        (_pick_organization_via_select) since it has no search-icon popup
        at all; only falls back to the popup flow below when no such
        select exists.

        Popup flow: click the Organization ID search icon, wait for the
        popup window, search it by organization name, click the first
        result row, and wait for the popup to close (it fills Organization
        ID/Name/NPI on this page itself via window.opener — see
        org_popup.html). Returns the picked row's first-column text (for
        logging), or None if the icon/popup/result couldn't be found.
        """
        picked = self._pick_organization_via_select()
        if picked is not None:
            return picked

        icon = self.page.locator(ORG_SEARCH_ICON_SELECTOR)
        if icon.count() == 0:
            return None

        try:
            with self.page.context.expect_page(
                    timeout=config.DEFAULT_TIMEOUT_MS) as popup_info:
                icon.first.click()
            popup = popup_info.value
            popup.wait_for_load_state("domcontentloaded")
        except Exception:
            return None

        name_input = utils.find_input_by_label(popup, ORG_POPUP_NAME_LABEL)
        if name_input is not None and name_query:
            name_input.fill(name_query)
            utils.click_button_by_text(popup, ORG_POPUP_SEARCH_BUTTON_TEXT)
            popup.wait_for_load_state("domcontentloaded")

        rows = popup.locator(ORG_POPUP_RESULT_ROW_SELECTOR)
        picked_text = None
        for i in range(rows.count()):
            row = rows.nth(i)
            cells = row.locator("td")
            if cells.count() == 0:
                continue
            try:
                cell_texts = [cells.nth(c).inner_text().strip()
                             for c in range(min(cells.count(), 2))]
                picked_text = " - ".join(t for t in cell_texts if t)
                row.click(timeout=3000)
                break
            except Exception:
                continue

        try:
            popup.wait_for_event("close", timeout=5000)
        except Exception:
            try:
                if not popup.is_closed():
                    popup.close()
            except Exception:
                pass

        return picked_text

    # -- organization group (optional, real system) ----------------------------

    def has_organization_group_icon(self) -> bool:
        """
        Whether the Organization Group search icon is present and visible.
        Only shown once Status=Approved. Used to decide whether to offer
        the confirmation prompt at all — see pick_organization_group_via_popup.
        """
        icon = self.page.locator(ORG_GROUP_ICON_SELECTOR)
        return icon.count() > 0 and icon.first.is_visible()

    def read_organization_group(self) -> str:
        """Current value of the Organization Group field."""
        return self._read_field("Organization Group", ORG_GROUP_INPUT_ID)

    def pick_organization_group_via_popup(self, name_query: str) -> str | None:
        """
        Click the Organization Group search icon, wait for the popup
        window, search it by name, and select the row whose name matches
        `name_query`: an exact case-insensitive match first, else the
        first result containing it as a substring.

        Unlike pick_organization_via_popup (Organization ID), there's no
        reliable field on the request itself (like NPI) to confirm which
        Virtual Group is correct — it's a business grouping (e.g. a health
        system), not something derivable from the request's own data. So
        this only auto-picks when the search actually returns a
        name-matching row; if nothing matches, it deliberately leaves the
        popup OPEN (rather than closing it) and returns None, so the
        caller can pause for a manual pick instead of guessing on a real
        approval. Also unlike that popup, this one does not close itself
        after a row is clicked — confirmed live, selectOnlyOneGroup(...)
        only writes the value back via window.opener — so a successful
        pick closes it explicitly here.
        """
        icon = self.page.locator(ORG_GROUP_ICON_SELECTOR)
        if icon.count() == 0 or not icon.first.is_visible():
            return None

        try:
            with self.page.context.expect_page(
                    timeout=config.DEFAULT_TIMEOUT_MS) as popup_info:
                icon.first.click()
            popup = popup_info.value
            popup.wait_for_load_state("domcontentloaded")
        except Exception:
            return None

        name_input = utils.find_input_by_label(
            popup, ORG_GROUP_POPUP_NAME_LABEL)
        if name_input is not None and name_query:
            name_input.fill(name_query)
        utils.click_button_by_text(popup, ORG_GROUP_POPUP_SEARCH_BUTTON_TEXT)
        popup.wait_for_load_state("domcontentloaded")

        query_l = name_query.strip().lower()
        rows = popup.locator(ORG_GROUP_POPUP_RESULT_LINK_SELECTOR)
        exact_link, exact_text = None, None
        fallback_link, fallback_text = None, None
        for i in range(rows.count()):
            link = rows.nth(i)
            try:
                text = link.inner_text().strip()
            except Exception:
                continue
            if text.lower() == query_l:
                exact_link, exact_text = link, text
                break
            if fallback_link is None and query_l and query_l in text.lower():
                fallback_link, fallback_text = link, text

        picked_link, picked_text = (
            (exact_link, exact_text) if exact_link is not None
            else (fallback_link, fallback_text))
        if picked_link is None:
            return None  # left open for the caller's manual-pick fallback

        try:
            picked_link.click(timeout=3000)
        except Exception:
            return None

        try:
            if not popup.is_closed():
                popup.close()
        except Exception:
            pass

        return picked_text

    # -- duplicate email check -------------------------------------------------

    @staticmethod
    def email_already_exists(details: RequestDetails) -> bool:
        """Exact case-insensitive match against Organization User Details."""
        return any(utils.emails_match(details.email, existing)
                   for existing in details.existing_user_emails)

    # -- form actions ------------------------------------------------------------

    def set_status(self, option_texts: list[str]) -> str | None:
        """Set the Status dropdown; returns the option actually selected."""
        select = self.page.locator(f"#{STATUS_SELECT_ID}")
        if select.count() == 0:
            select = utils.find_select_by_label(
                self.page, STATUS_DROPDOWN_LABEL)
            if select is None:
                return None
        return utils.select_option_by_visible_text(select, option_texts)

    def fill_note(self, text: str) -> bool:
        """
        Fill the note/message/comments field, whatever it is called. On
        the real system three separate note textareas exist, each shown
        only for its matching Status (see the NOTE_TEXTAREA_ID group of
        constants) — try whichever one is currently visible first, since
        that automatically matches whatever set_status() just selected
        instead of guessing by label text (all three labels contain the
        substring "Note:", so label search alone can't tell them apart).
        """
        for field_id in (REJECTED_NOTE_TEXTAREA_ID,
                         ADDITIONAL_INFO_NOTE_TEXTAREA_ID, NOTE_TEXTAREA_ID):
            loc = self.page.locator(f"#{field_id}")
            if loc.count() > 0 and loc.first.is_visible():
                loc.first.fill(text)
                return True
        for label in NOTE_LABEL_ALTERNATIVES:
            loc = utils.find_input_by_label(self.page, label)
            if loc is not None:
                loc.fill(text)
                return True
        return False

    def fill_username(self, username: str) -> bool:
        """Fill the User Name field. Returns False if it can't be found."""
        loc = self.page.locator(f"#{USERNAME_INPUT_ID}")
        if loc.count() > 0:
            loc.first.fill(username)
            return True
        loc = utils.find_input_by_label(self.page, USERNAME_LABEL)
        if loc is None:
            return False
        loc.fill(username)
        return True

    def fill_approval_name(self, full_name: str) -> bool:
        """
        Fill the Approval-details "Name" field with the requester's full
        (first + last) name. Only meaningful once Status=Approved, since
        that section only renders then.
        """
        loc = self.page.locator(f"#{APPROVAL_NAME_INPUT_ID}")
        if loc.count() > 0:
            loc.first.fill(full_name)
            return True
        for label in APPROVAL_NAME_LABEL_ALTERNATIVES:
            loc = utils.find_input_by_label(self.page, label)
            if loc is not None:
                loc.fill(full_name)
                return True
        return False

    def confirm_name_fields(self, details: RequestDetails) -> None:
        """If first/last name inputs exist and are empty, fill them."""
        for label, input_id, value in (
                (FIRST_NAME_LABEL, FIRST_NAME_INPUT_ID, details.first_name),
                (LAST_NAME_LABEL, LAST_NAME_INPUT_ID, details.last_name)):
            loc = self.page.locator(f"#{input_id}") if input_id else None
            if loc is None or loc.count() == 0:
                loc = utils.find_input_by_label(self.page, label)
            else:
                loc = loc.first
            if loc is not None and value:
                try:
                    if not (loc.input_value() or "").strip():
                        loc.fill(value)
                except Exception:
                    pass

    def click_save(self) -> bool:
        """Click 'Save & Next' (preferred) or 'Save'."""
        for text in SAVE_BUTTON_TEXTS:
            if utils.click_button_by_text(self.page, text):
                self.page.wait_for_load_state("domcontentloaded")
                return True
        return False

    def save_advanced(self, email_before: str, timeout_ms: int = 5000) -> bool:
        """
        Tell whether a just-clicked Save actually went through. The real
        system checks username uniqueness system-wide, not just against
        the accounts visible in this request's own Organization User
        Details table, but shows no visible error when that check fails —
        confirmed live, Save just silently leaves the exact same request's
        detail form displayed, unchanged. There's no error text to key
        off; the only observable signal is whether the page moved on at
        all.

        Polls the Email field for up to `timeout_ms`: if it becomes
        something other than `email_before` at any point (a new/next
        request loaded) — or the field disappears entirely (e.g. back at
        the list) — Save advanced and this returns True. If it still
        reads `email_before` for the whole window, Save did not go
        through and this returns False, so the caller can retry with a
        different username.
        """
        deadline = time.monotonic() + timeout_ms / 1000
        before_l = email_before.strip().lower()
        email_field = self.page.locator(f"#{EMAIL_INPUT_ID}")
        while time.monotonic() < deadline:
            if email_field.count() == 0:
                return True
            try:
                current = (email_field.first.input_value() or "").strip().lower()
            except Exception:
                current = ""
            if current != before_l:
                return True
            self.page.wait_for_timeout(200)
        return False

    def has_send_email_button(self) -> bool:
        """Whether a 'Click to Send Email' button is present on the page."""
        return utils.button_exists(self.page, SEND_EMAIL_BUTTON_TEXT)

    def click_send_email(self) -> bool:
        """Only called when the user explicitly enabled --send-email."""
        return utils.click_button_by_text(self.page, SEND_EMAIL_BUTTON_TEXT)

    def go_back_to_list(self) -> bool:
        """
        Click 'Back' to return to the results list. Preferred over a hard
        reload to the list URL on the real system: confirmed live that a
        page.goto() to the exact same URL does not reliably reset the
        view — the server session can keep showing whatever sub-view
        (e.g. this same detail form) was last open instead of the list,
        and a full reload also risks landing on a different module
        entirely if the base URL's file= parameter doesn't point at this
        one (see filter_pending_and_search's docstring). Returns False if
        no 'Back' control was found, so the caller can fall back.

        Like Search (see _wait_for_results_to_settle), this swaps content
        client-side rather than triggering a real navigation, so briefly
        after the click the list still isn't in the DOM yet — confirmed
        live, an immediate check right after the click can still see the
        detail form. Poll briefly for the list's header row to show up
        before returning, so callers don't query mid-transition (where the
        detail form's own Status select can be the only "Status" element
        around and get mistaken for the list's filter).
        """
        if not utils.click_button_by_text(self.page, BACK_LINK_TEXT):
            return False
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.page.locator(HEADER_ROW_SELECTOR).count() > 0:
                break
            self.page.wait_for_timeout(150)
        return True
