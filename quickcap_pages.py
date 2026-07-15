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

# --- Detail page -----------------------------------------------------------
# These match the field labels used by the local carbon-copy dashboard
# (webapp/templates/detail.html) exactly. When pointing this at the real
# QuickCap system, run --debug-selectors there and re-check each one — in
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

SAVE_BUTTON_TEXTS = ["Save & Next", "Save and Next", "Save"]
SEND_EMAIL_BUTTON_TEXT = "Click to Send Email"

# --- Organization search popup (multi-organization Tax IDs) ----------------
# Opened by clicking the search icon next to Organization ID when a Tax ID
# maps to more than one Organization ID (see detect_organization_count()).
ORG_SEARCH_ICON_SELECTOR = "#orgSearchBtn"
ORG_POPUP_NAME_LABEL = "Name"
ORG_POPUP_SEARCH_BUTTON_TEXT = "Search"
ORG_POPUP_RESULT_ROW_SELECTOR = "tr.pick-row"

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
        """Set Status filter = Pending and click Search."""
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
            if not utils.click_button_by_text(self.page, SEARCH_BUTTON_TEXT):
                utils.manual_pause(
                    f"Could not find the '{SEARCH_BUTTON_TEXT}' button. "
                    "Please click Search manually, then")
        self.page.wait_for_load_state("domcontentloaded")

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

    def _pending_rows(self):
        """
        <tr> elements in the results table whose Status column shows
        config.PENDING_STATUS_OPTION (e.g. "Pending"). Counting edit icons
        alone is not reliable: every row — Approved and Rejected included —
        has one, so if the Status=Pending filter silently fails to apply
        (wrong label match, a slow reload, etc.) every visible row gets
        treated as pending. Matching on the Status cell's own text is what
        actually distinguishes a pending row.

        Uses Playwright's role/name matching (accessible-name substring,
        case-insensitive) rather than a hand-rolled XPath string compare —
        an exact XPath normalize-space() match previously matched zero rows
        on the real system, most likely because the cell's text includes
        whitespace normalize-space() doesn't collapse (e.g. "&nbsp;"
        padding, which this system's markup is known to use in other
        cells).

        Scoped to the results table only (see _results_table): searching
        the whole page also matches the filter form's Status <select>,
        whose enclosing <td> computes an accessible name that includes all
        of its option text ("All Pending Approved Rejected..."), which
        falsely matched as a "pending row" with no edit icon in it.
        """
        table = self._results_table()
        if table is None:
            return self.page.locator("tr.__no_results_table_found__")
        cells = table.get_by_role(
            "cell", name=config.PENDING_STATUS_OPTION, exact=False)
        return cells.locator("xpath=ancestor::tr[1]")

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
        icon.first.click()
        self.page.wait_for_load_state("domcontentloaded")


# ===========================================================================
# Detail page
# ===========================================================================

class RequestDetailPage:
    """The edit form for a single login request."""

    def __init__(self, page: Page):
        self.page = page

    # -- extraction -----------------------------------------------------------

    def _read_field(self, label: str) -> str:
        """
        Read a labeled field's value. If an <input>/<textarea> was found,
        its value is authoritative — including an empty string, e.g. an
        Organization ID left blank pending a popup pick — so a genuinely
        empty input must NOT fall through to the plain-text fallback below
        (that cell may also contain a search-icon button whose visible
        text would otherwise be mistaken for the field's value). Only when
        no input/textarea element exists at all (fully read-only fields
        rendered as plain text) do we read the next table cell's text.
        """
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
        d.first_name = self._read_field(FIRST_NAME_LABEL)
        d.last_name = self._read_field(LAST_NAME_LABEL)
        d.title = self._read_field(TITLE_LABEL)
        d.email = self._read_field(EMAIL_LABEL)
        d.organization_id = self._read_field(ORG_ID_LABEL)
        d.organization_tax_id = self._read_field(ORG_TAX_ID_LABEL)
        d.organization_name = self._read_field(ORG_NAME_LABEL)
        d.organization_npi = self._read_field(ORG_NPI_LABEL)

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
        If Organization ID is already filled in, the org is resolved —
        nothing to pick. Otherwise, read the "Organization Details" table
        (all organizations sharing this request's Tax ID) and count how
        many distinct Organization IDs it lists. >1 means the popup-based
        picker (pick_organization_via_popup) needs to run before approving.
        """
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
        return self._read_field(ORG_ID_LABEL)

    def pick_organization_via_popup(self, name_query: str) -> str | None:
        """
        Click the Organization ID search icon, wait for the popup window,
        search it by organization name, click the first result row, and
        wait for the popup to close (it fills Organization ID/Name/NPI on
        this page itself via window.opener — see org_popup.html). Returns
        the picked row's first-column text (for logging), or None if the
        icon/popup/result couldn't be found.
        """
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

    # -- duplicate email check -------------------------------------------------

    @staticmethod
    def email_already_exists(details: RequestDetails) -> bool:
        """Exact case-insensitive match against Organization User Details."""
        return any(utils.emails_match(details.email, existing)
                   for existing in details.existing_user_emails)

    # -- form actions ------------------------------------------------------------

    def set_status(self, option_texts: list[str]) -> str | None:
        """Set the Status dropdown; returns the option actually selected."""
        select = utils.find_select_by_label(
            self.page, STATUS_DROPDOWN_LABEL)
        if select is None:
            return None
        return utils.select_option_by_visible_text(select, option_texts)

    def fill_note(self, text: str) -> bool:
        """Fill the note/message/comments field, whatever it is called."""
        for label in NOTE_LABEL_ALTERNATIVES:
            loc = utils.find_input_by_label(self.page, label)
            if loc is not None:
                loc.fill(text)
                return True
        return False

    def fill_username(self, username: str) -> bool:
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
        for label in APPROVAL_NAME_LABEL_ALTERNATIVES:
            loc = utils.find_input_by_label(self.page, label)
            if loc is not None:
                loc.fill(full_name)
                return True
        return False

    def confirm_name_fields(self, details: RequestDetails) -> None:
        """If first/last name inputs exist and are empty, fill them."""
        for label, value in ((FIRST_NAME_LABEL, details.first_name),
                             (LAST_NAME_LABEL, details.last_name)):
            loc = utils.find_input_by_label(self.page, label)
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

    def has_send_email_button(self) -> bool:
        return utils.button_exists(self.page, SEND_EMAIL_BUTTON_TEXT)

    def click_send_email(self) -> bool:
        """Only called when the user explicitly enabled --send-email."""
        return utils.click_button_by_text(self.page, SEND_EMAIL_BUTTON_TEXT)
