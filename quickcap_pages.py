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
FIRST_NAME_LABEL = "First Name"
LAST_NAME_LABEL = "Last Name"
TITLE_LABEL = "Title"
EMAIL_LABEL = "Email"
ORG_ID_LABEL = "Organization ID"
ORG_TAX_ID_LABEL = "Tax ID"
ORG_NAME_LABEL = "Organization Name"
ORG_NPI_LABEL = "NPI"
USERNAME_LABEL = "Username"
STATUS_DROPDOWN_LABEL = "Status"
NOTE_LABEL = "Note"                     # or "Message" / "Comments"
NOTE_LABEL_ALTERNATIVES = ["Note", "Notes", "Message", "Comments"]

ORG_USER_TABLE_TITLE = "Organization User Details"
ORG_USER_EMAIL_COLUMN_HINTS = ["email"]      # substrings to find email column
ORG_USER_USERNAME_COLUMN_HINTS = ["user"]    # substrings for username column

SAVE_BUTTON_TEXTS = ["Save & Next", "Save and Next", "Save"]
SEND_EMAIL_BUTTON_TEXT = "Click to Send Email"

# Text that indicates we landed on a LOGIN page instead of the app.
LOGIN_PAGE_HINTS = ["password", "sign in", "log in", "login"]


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
        """Heuristic: if the page has a password field, we are logged out."""
        if self.page.locator("input[type=password]").count() > 0:
            return True
        title = (self.page.title() or "").lower()
        return any(h in title for h in LOGIN_PAGE_HINTS)

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

    def count_pending_rows(self) -> int:
        """Count edit icons in the results (one per pending request row)."""
        return self.page.locator(EDIT_ICON_SELECTOR).count()

    def peek_row_summary(self, index: int) -> str:
        """Best-effort text of row N (for console output only)."""
        icons = self.page.locator(EDIT_ICON_SELECTOR)
        if index >= icons.count():
            return ""
        try:
            row = icons.nth(index).locator("xpath=ancestor::tr[1]")
            cells = row.locator("td")
            texts = [cells.nth(i).inner_text().strip()
                     for i in range(min(cells.count(), 6))]
            return " | ".join(texts)
        except Exception:
            return ""

    def open_request(self, index: int) -> None:
        """
        Click the edit icon of row `index` (0-based) and wait for the
        detail page. We re-locate icons each time because the list reloads
        after every Save & Next.
        """
        icons = self.page.locator(EDIT_ICON_SELECTOR)
        if index >= icons.count():
            raise IndexError(f"No edit icon at row index {index}")
        icons.nth(index).click()
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
        Read a labeled field's value. Tries the input's value first; if the
        input isn't found or is empty (common for read-only fields rendered
        as plain text), falls back to the text of the table cell next to
        the label.
        """
        value = ""
        loc = utils.find_input_by_label(self.page, label)
        if loc is not None:
            try:
                value = (loc.input_value() or "").strip()
            except Exception:
                value = ""
        if value:
            return value
        # Read-only fields are often plain text in the next table cell.
        lit_loc = self.page.locator(
            f"xpath=//td[contains(normalize-space(.), "
            f"{utils._xpath_literal(label)})]/following-sibling::td[1]"
        )
        if lit_loc.count() > 0:
            try:
                return lit_loc.first.inner_text().strip()
            except Exception:
                pass
        return value

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
        Heuristic: if there is an org-selection table/list with multiple
        rows, or a 'Select Organization' popup trigger with >1 candidate,
        return that count. Default: 1 (single matched org).

        TODO: implement the multi-organization popup workflow once you have
        inspected that popup with --debug-selectors. For now, any ambiguity
        should be resolved manually (the script pauses).
        """
        rows = utils.read_table_by_section_title(
            self.page, "Organization")  # crude hint; refine per your HTML
        # Only treat it as multi-org if the table clearly lists organizations
        # with more than one row AND is not the user-details table.
        if rows and len(rows) > 1 and any(
                "organization" in k.lower() for k in rows[0].keys()):
            return len(rows)
        return 1

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
