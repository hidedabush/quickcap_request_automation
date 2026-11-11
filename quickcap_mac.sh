#!/bin/bash
# =============================================================================
#  quickcap.sh -- QuickCap "Request To Login" automation, macOS edition.
#  Everything is in this ONE file: settings, dependency setup, the Python
#  automation code, and the run itself. No other file is needed.
# =============================================================================
# HELP-START
# QuickCap "Request To Login" automation (macOS Terminal)
#
# HOW TO RUN (Terminal, in the folder holding this file)
#   bash quickcap.sh                  asks which mode, then runs
#   bash quickcap.sh --help           shows this help
#   (Or once: chmod +x quickcap.sh, then ./quickcap.sh)
#
# WHAT IT DOES
#   - Filters the Request To Login list to Status=Pending, opens each request,
#     checks whether its email already exists in "Organization User Details",
#     and either APPROVES it (generated username, e.g. jsmith01) or REJECTS it
#     with the note "Account already exists for this email address."
#   - Only acts on requests whose Req. Date is TODAY. When those run out it
#     asks whether to continue with older ones.
#
# WHAT IT NEVER DOES
#   - Never logs in for you, never touches MFA/CAPTCHA, never calls backend
#     APIs, never stores credentials.
#   - Never sends emails unless you pass --send-email AND confirm each one.
#   - Never records anything: no log files, no CSVs, no screenshots. Results
#     are printed to this Terminal window only.
#
# FIRST RUN
#   1. Finds Python 3.10+ (offers to install it with Homebrew, or the
#      python.org installer, which asks for your Mac password).
#   2. Installs Playwright into a private environment (needs internet once).
#   3. Checks that Google Chrome is installed (offers Homebrew if not).
#   4. Opens Chrome: log in to QuickCap by hand. The script then opens the
#      Request To Login list through the side menu. Your login is kept in
#      the chrome-profile folder next to this script for later runs.
#
# OPTIONS
#   --mode manual|assisted|auto
#         manual   : fills the form; you click Save yourself (type "a" at the
#                    prompt to switch to fully automatic).
#         assisted : fills the form; asks y/n before every Save & Next.
#         auto     : fills and saves without asking each time.
#         If omitted, you are asked at startup.
#   --send-email        Allow "Click to Send Email" (still asks each time).
#   --chrome connect|launch
#         connect (default): new tab in the automation Chrome (started on the
#                  debug port if needed; it stays open afterwards).
#         launch : Playwright opens a separate Chrome window and closes it.
#   --start-page auto|goto|current
#         auto/goto (default): open a new tab on the QuickCap URL.
#         current : reuse an already-open QuickCap tab as-is.
#   --debug-selectors   Print the page's inputs/selects/buttons; changes nothing.
#   --max-requests N    Stop after N requests (0 = all of today's pending).
#   --self-test         Set up, then run offline checks (no website contacted).
#   --setup-only        Install/check dependencies, then exit.
#   --reinstall         Delete and rebuild the Python environment.
#   -h, --help          Show this help.
#
# RECOMMENDED ORDER on a new machine
#   bash quickcap.sh --self-test
#   bash quickcap.sh --debug-selectors
#   bash quickcap.sh --mode assisted --max-requests 2
#   bash quickcap.sh --mode auto
#
# FILES THIS SCRIPT CREATES
#   ~/.quickcap-automation/        Python environment + the extracted code.
#                                  Safe to delete; rebuilt automatically.
#   <script folder>/chrome-profile The automation Chrome profile (keeps your
#                                  QuickCap login). Delete it to log out.
# HELP-END

set -euo pipefail

# =============================================================================
# 1. SETTINGS  (non-sensitive only -- NEVER put passwords or tokens here)
# =============================================================================
# Edit the values below to change them. No .env or other file is read. An
# environment variable with the same name, if set in the shell, overrides the
# value here (handy for a one-off test).

# Main QuickCap URL (home/login page).
QUICKCAP_URL="${QUICKCAP_URL:-https://payer.tecqpartners.com/php/general/index.php}"

# Page the run starts on. If it isn't the Request To Login list itself, the
# script opens the list through the side-menu link after you log in. A direct
# list URL (...index.php?file=meds_request_login_list&...) also works here.
QUICKCAP_REQUEST_LIST_URL="${QUICKCAP_REQUEST_LIST_URL:-https://payer.tecqpartners.com/php/general/index.php}"

# Chrome DevTools endpoint used by --chrome connect.
CHROME_DEBUG_URL="${CHROME_DEBUG_URL:-http://localhost:9222}"

# Automation Chrome profile folder (keeps your QuickCap login).
# Blank = "chrome-profile" next to this script.
CHROME_PROFILE_DIR="${CHROME_PROFILE_DIR:-}"

# Full path to the Chrome binary. Blank = auto-detect
# (/Applications/Google Chrome.app/Contents/MacOS/Google Chrome).
CHROME_PATH="${CHROME_PATH:-}"

# Element wait timeout in milliseconds.
DEFAULT_TIMEOUT_MS="${DEFAULT_TIMEOUT_MS:-15000}"

# Python package the automation needs (only Playwright; it drives the Chrome
# that's already installed, so no extra browser download is needed).
PYTHON_PACKAGES="playwright>=1.44,<2"
# Used only if Python 3.10+ is missing AND Homebrew isn't available.
PYTHON_PKG_URL="https://www.python.org/ftp/python/3.12.10/python-3.12.10-macos11.pkg"
# Set QUICKCAP_PYTHON=/path/to/python3 to force a specific interpreter.

# =============================================================================
# Paths
# =============================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="$HOME/.quickcap-automation"
VENV_DIR="$RUNTIME_DIR/venv"
APP_DIR="$RUNTIME_DIR/app"
DEPS_STAMP="$RUNTIME_DIR/deps.stamp"
VENV_PY=""

# =============================================================================
# Helpers
# =============================================================================

step() { printf '\033[36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m!!  %s\033[0m\n' "$*"; }
die()  { printf '\033[31mXX  %s\033[0m\n' "$*" >&2; exit 1; }

confirm() {
    # Plain y/N prompt. Only "y"/"yes" counts as yes.
    local answer=""
    read -r -p "$1 [y/N] " answer || answer=""
    case "$answer" in
        y|Y|yes|YES|Yes) return 0 ;;
        *) return 1 ;;
    esac
}

usage() {
    # Prints the HELP-START..HELP-END block above, without the "# ".
    sed -n '/^# HELP-START/,/^# HELP-END/p' "${BASH_SOURCE[0]}" |
        sed -e '1d' -e '$d' -e 's/^# \{0,1\}//'
}

# =============================================================================
# 2. DEPENDENCIES
# =============================================================================

python_ok() {
    # True if "$1" runs and is Python 3.10 or newer.
    [ -n "$1" ] && [ -x "$1" ] || command -v "$1" >/dev/null 2>&1 || return 1
    "$1" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)' \
        >/dev/null 2>&1
}

find_python() {
    # Prints the first usable interpreter: QUICKCAP_PYTHON, Homebrew,
    # python.org installs, versioned python3.X on PATH, then python3.
    if [ -n "${QUICKCAP_PYTHON:-}" ]; then
        python_ok "$QUICKCAP_PYTHON" && { echo "$QUICKCAP_PYTHON"; return 0; }
        die "QUICKCAP_PYTHON=$QUICKCAP_PYTHON is not a working Python 3.10+."
    fi
    local c v
    for v in 3.14 3.13 3.12 3.11 3.10; do
        for c in "/opt/homebrew/bin/python$v" "/usr/local/bin/python$v" \
                 "/Library/Frameworks/Python.framework/Versions/$v/bin/python3"; do
            python_ok "$c" && { echo "$c"; return 0; }
        done
        c="$(command -v "python$v" 2>/dev/null || true)"
        python_ok "$c" && { echo "$c"; return 0; }
    done
    for c in /opt/homebrew/bin/python3 /usr/local/bin/python3; do
        python_ok "$c" && { echo "$c"; return 0; }
    done
    c="$(command -v python3 2>/dev/null || true)"
    # /usr/bin/python3 is a stub that pops up an Xcode install dialog when the
    # Command Line Tools are missing -- only try it when they're installed.
    if [ "$c" = "/usr/bin/python3" ] && ! xcode-select -p >/dev/null 2>&1; then
        c=""
    fi
    python_ok "$c" && { echo "$c"; return 0; }
    return 1
}

install_python() {
    # Homebrew if present (no password), otherwise the official python.org
    # installer package (macOS asks for an administrator password).
    if command -v brew >/dev/null 2>&1; then
        step "Installing Python 3.12 with Homebrew..."
        if brew install python@3.12; then return 0; fi
        warn "Homebrew failed; trying the python.org installer."
    fi
    local tmp
    tmp="$(mktemp -d)"
    step "Downloading $PYTHON_PKG_URL ..."
    curl -fL --progress-bar -o "$tmp/python.pkg" "$PYTHON_PKG_URL" ||
        die "Download failed. Check the internet connection and run again."
    step "Installing Python (macOS will ask for your password)..."
    sudo installer -pkg "$tmp/python.pkg" -target / ||
        die "The Python installer failed."
    rm -rf "$tmp"
}

venv_python() {
    # Path of the virtual environment's interpreter, or "" if none yet.
    # (Scripts/python.exe only exists when testing under Git Bash on Windows.)
    if [ -x "$VENV_DIR/bin/python" ]; then echo "$VENV_DIR/bin/python"
    elif [ -x "$VENV_DIR/Scripts/python.exe" ]; then echo "$VENV_DIR/Scripts/python.exe"
    else echo ""
    fi
}

init_python_env() {
    # Creates ~/.quickcap-automation/venv and installs Playwright into it.
    # Skipped on later runs while the stamp file still matches.
    if [ "$REINSTALL" = 1 ] && [ -d "$RUNTIME_DIR" ]; then
        step "Removing the old runtime (--reinstall)..."
        rm -rf "$RUNTIME_DIR"
    fi
    mkdir -p "$RUNTIME_DIR"

    VENV_PY="$(venv_python)"
    # A venv whose base Python was uninstalled/upgraded no longer runs.
    if [ -n "$VENV_PY" ] && ! python_ok "$VENV_PY"; then
        warn "The existing Python environment is broken; rebuilding it."
        rm -rf "$VENV_DIR" "$DEPS_STAMP"
        VENV_PY=""
    fi

    if [ -z "$VENV_PY" ]; then
        local base=""
        step "Looking for Python 3.10 or newer..."
        if ! base="$(find_python)"; then
            warn "Python 3.10+ was not found on this Mac."
            confirm "Install Python 3.12 now?" ||
                die "Python is required. Install it from https://www.python.org/downloads/ and run again."
            install_python
            hash -r
            base="$(find_python)" ||
                die "Python was installed but could not be found. Open a new Terminal window and run again."
        fi
        step "Creating the Python environment with $base ..."
        "$base" -m venv "$VENV_DIR" || die "Could not create the Python environment."
        VENV_PY="$(venv_python)"
        [ -n "$VENV_PY" ] || die "The Python environment was created but has no interpreter."
    fi

    local wanted have
    wanted="$PYTHON_PACKAGES | $("$VENV_PY" --version 2>&1)"
    have="$(cat "$DEPS_STAMP" 2>/dev/null || true)"
    if [ "$wanted" != "$have" ]; then
        step "Installing Python packages: $PYTHON_PACKAGES ..."
        "$VENV_PY" -m pip install --disable-pip-version-check --quiet --upgrade \
            "$PYTHON_PACKAGES" ||
            die "pip install failed (see the message above). Usually the internet/proxy connection; run again once fixed."
        printf '%s' "$wanted" > "$DEPS_STAMP"
    else
        step "Python packages already installed."
    fi
}

find_chrome() {
    # Same search order as the Python side: CHROME_PATH, then the usual app
    # locations, then PATH.
    if [ -n "$CHROME_PATH" ]; then
        [ -f "$CHROME_PATH" ] && { echo "$CHROME_PATH"; return 0; }
        return 1
    fi
    local c
    for c in "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
             "$HOME/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; do
        [ -x "$c" ] && { echo "$c"; return 0; }
    done
    c="$(command -v google-chrome 2>/dev/null || command -v chrome 2>/dev/null || true)"
    [ -n "$c" ] && { echo "$c"; return 0; }
    return 1
}

check_chrome() {
    local exe=""
    if exe="$(find_chrome)"; then
        step "Google Chrome: $exe"
        return 0
    fi
    [ -z "$CHROME_PATH" ] || die "CHROME_PATH is set to '$CHROME_PATH' but that file doesn't exist."
    warn "Google Chrome was not found."
    if command -v brew >/dev/null 2>&1 && confirm "Install Google Chrome with Homebrew now?"; then
        if brew install --cask google-chrome && find_chrome >/dev/null; then
            step "Google Chrome installed."
            return 0
        fi
    fi
    die "Google Chrome is required. Install it from https://www.google.com/chrome/ (or set CHROME_PATH) and run again."
}

# =============================================================================
# 3. CODE  -- the embedded Python automation (written to ~/.quickcap-automation/app)
# =============================================================================
# Each module is a quoted heredoc, so the shell copies it byte-for-byte (no
# variable expansion). It is rewritten on every run, so this file is always
# the single source of truth.

write_python_sources() {
mkdir -p "$APP_DIR"

# ---- config.py ---------------------------------------------------
cat > "$APP_DIR/config.py" <<'QUICKCAP_EOF_CONFIG_PY'
"""
config.py
---------
Central configuration for the QuickCap "Request To Login" automation.

Settings arrive as environment variables set by quickcap.sh (from its
SETTINGS block, or the shell if overridden). Only NON-SENSITIVE values
(URLs, folders, timeouts) -- never passwords: you log in to QuickCap
yourself in Chrome; the script only drives the UI.

Nothing is recorded: there is no log folder and no screenshots.
"""

import os
from pathlib import Path

# Folder holding these extracted .py files (~/.quickcap-automation/app).
BASE_DIR = Path(__file__).resolve().parent

# Main QuickCap URL (login/home page).
QUICKCAP_URL = os.getenv("QUICKCAP_URL", "").strip()

# Direct URL of the "Request To Login" list page; falls back to QUICKCAP_URL
# (then navigate to the list manually when the script pauses).
QUICKCAP_REQUEST_LIST_URL = (
    os.getenv("QUICKCAP_REQUEST_LIST_URL", "").strip() or QUICKCAP_URL)

# Chrome DevTools debug endpoint. "connect" mode attaches here and opens a
# new tab; if nothing is listening, it starts Chrome itself on this port.
CHROME_DEBUG_URL = (os.getenv("CHROME_DEBUG_URL", "").strip()
                    or "http://localhost:9222")

# Chrome profile folder (keeps your QuickCap login between runs).
# quickcap.sh always sets this (default: chrome-profile next to the script).
CHROME_PROFILE_DIR = (os.getenv("CHROME_PROFILE_DIR", "").strip()
                      or str(BASE_DIR / "chrome-profile"))

# Full path to chrome.exe. Optional -- blank means auto-detect.
CHROME_PATH = os.getenv("CHROME_PATH", "").strip()

# Default timeout (milliseconds) for waiting on elements/pages.
DEFAULT_TIMEOUT_MS = int(os.getenv("DEFAULT_TIMEOUT_MS", "").strip() or "15000")

# ---------------------------------------------------------------------------
# Behavior settings
# ---------------------------------------------------------------------------

# The exact text QuickCap uses in the Status dropdown may vary. The script
# tries these, in order, when rejecting a duplicate-email request.
REJECT_STATUS_OPTIONS = ["Rejected", "Denied"]

# Status value used when approving.
APPROVE_STATUS_OPTION = "Approved"

# Status filter value on the list page.
PENDING_STATUS_OPTION = "Pending"

# Note added to duplicate-email requests.
DUPLICATE_EMAIL_NOTE = "Account already exists for this email address."
QUICKCAP_EOF_CONFIG_PY

# ---- utils.py ----------------------------------------------------
cat > "$APP_DIR/utils.py" <<'QUICKCAP_EOF_UTILS_PY'
"""
utils.py
--------
Reusable helper functions:

- DOM helpers that tolerate old table-based HTML (find input by nearby label,
  select dropdown option by visible text, read a table under a section title,
  click a button by its visible text).
- Username generation and normalization (jsmith01, jsmith02, ...).
- Console-only result reporting (nothing is written to disk).
- Human-input prompts (manual pause, yes/no, numbered choice), all printed
  in one clearly framed format.
- Selector debug dump (prints inputs, selects, buttons found on the page).

All DOM helpers take a Playwright `page` (or frame) as the first argument.
None of them assume exact selectors -- they search by visible text, so they
survive minor HTML changes. If something is not found, they return None and
the caller decides whether to pause for manual review.
"""

from __future__ import annotations

import re
import string
import textwrap
from datetime import date, datetime
from typing import Optional

from playwright.sync_api import Locator, Page

import config


# ===========================================================================
# 1. Username generation
# ===========================================================================

def normalize_username(raw: str) -> str:
    """Lowercase, remove spaces and punctuation/special characters."""
    lowered = raw.lower()
    allowed = set(string.ascii_lowercase + string.digits)
    return "".join(ch for ch in lowered if ch in allowed)


def generate_username(first_name: str, last_name: str,
                      existing_usernames: list[str]) -> str:
    """
    Build a username: first initial + last name + two-digit number.

    Example: John Smith -> jsmith01. If jsmith01 already exists in the
    Organization User Details table, try jsmith02, jsmith03, ...
    """
    base = normalize_username((first_name.strip()[:1] + last_name.strip()))
    if not base:
        base = "user"

    existing = {u.strip().lower() for u in existing_usernames if u}

    for n in range(1, 100):
        candidate = f"{base}{n:02d}"
        if candidate not in existing:
            return candidate

    # Extremely unlikely fallback: 100+ collisions.
    return f"{base}{datetime.now().strftime('%H%M%S')}"


def bump_username(username: str) -> str:
    """
    Increment a generated username's trailing number by one (jsmith01 ->
    jsmith02, ...), preserving its digit width. Used to retry Save when a
    username collides system-wide with an account that isn't visible in
    the request's own Organization User Details table -- confirmed live,
    the real system doesn't show any error for this; Save just silently
    fails to advance to a new/next request. generate_username() already
    avoids collisions against locally-known usernames, so this only
    fires for that gap.

    Falls back to a time-based suffix once the trailing number rolls over
    its digit width (e.g. 99 -> "00" would collide with nothing sensible),
    matching generate_username()'s own 100+-collision fallback. If
    `username` has no trailing digits at all, starts one at "01".
    """
    m = re.match(r"^(.*?)(\d+)$", username)
    if not m:
        return f"{username}01"
    base, digits = m.group(1), m.group(2)
    n = int(digits) + 1
    width = len(digits)
    if n >= 10 ** width:
        return f"{base}{datetime.now().strftime('%H%M%S')}"
    return f"{base}{n:0{width}d}"


def emails_match(email_a: str, email_b: str) -> bool:
    """Exact, case-insensitive email comparison."""
    return email_a.strip().lower() == email_b.strip().lower()


# ===========================================================================
# 1b. Req. Date guard -- only ever act on today's requests
# ===========================================================================

_REQ_DATE_FORMATS = ("%m-%d-%Y", "%m/%d/%Y")


def parse_request_date(text: str) -> Optional[date]:
    """Parse a list row's Req. Date cell text (MM-DD-YYYY or MM/DD/YYYY)."""
    text = (text or "").strip()
    for fmt in _REQ_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def is_today(text: str) -> bool:
    """Whether a Req. Date cell's text parses to today's date."""
    parsed = parse_request_date(text)
    return parsed is not None and parsed == date.today()


# ===========================================================================
# 2. DOM helpers for old table-based HTML
# ===========================================================================

def _xpath_literal(text: str) -> str:
    """Safely embed text in an XPath string literal (handles quotes)."""
    if "'" not in text:
        return f"'{text}'"
    if '"' not in text:
        return f'"{text}"'
    parts = text.split("'")
    return "concat('" + "', \"'\", '".join(parts) + "')"


def find_input_by_label(page: Page, label_text: str) -> Optional[Locator]:
    """
    Find a text input (or textarea) whose label text is nearby.

    Tries, in order:
      1. A real <label> association (Playwright's get_by_label).
      2. Old-school table layout: <td>Label</td><td><input></td>.
      3. Any element containing the label text, then the next input after it.

    Returns a Locator or None.
    """
    # 1) Proper <label for=...> markup
    try:
        loc = page.get_by_label(label_text, exact=False)
        if loc.count() > 0 and loc.first.is_visible():
            return loc.first
    except Exception:
        pass

    lit = _xpath_literal(label_text)

    # 2) Table layout: label cell -> input in the next cell
    xpaths = [
        f"//td[contains(normalize-space(.), {lit})]"
        f"/following-sibling::td[1]//input[not(@type='hidden')]",
        f"//td[contains(normalize-space(.), {lit})]"
        f"/following-sibling::td[1]//textarea",
        # 3) Generic: first input that appears after the label text
        f"//*[contains(normalize-space(text()), {lit})]"
        f"/following::input[not(@type='hidden')][1]",
        f"//*[contains(normalize-space(text()), {lit})]"
        f"/following::textarea[1]",
    ]
    for xp in xpaths:
        loc = page.locator(f"xpath={xp}")
        if loc.count() > 0 and loc.first.is_visible():
            return loc.first
    return None


def find_select_by_label(page: Page, label_text: str) -> Optional[Locator]:
    """Same idea as find_input_by_label, but for <select> dropdowns."""
    try:
        loc = page.get_by_label(label_text, exact=False)
        if loc.count() > 0:
            first = loc.first
            if first.evaluate("el => el.tagName") == "SELECT":
                return first
    except Exception:
        pass

    lit = _xpath_literal(label_text)
    xpaths = [
        f"//td[contains(normalize-space(.), {lit})]"
        f"/following-sibling::td[1]//select",
        f"//*[contains(normalize-space(text()), {lit})]/following::select[1]",
    ]
    for xp in xpaths:
        loc = page.locator(f"xpath={xp}")
        if loc.count() > 0 and loc.first.is_visible():
            return loc.first
    return None


def select_option_by_visible_text(select_locator: Locator,
                                  option_texts: list[str]) -> Optional[str]:
    """
    Select the first option whose visible text matches one of option_texts
    (case-insensitive). Returns the matched option text, or None.
    """
    options = select_locator.locator("option")
    available = [options.nth(i).inner_text().strip()
                 for i in range(options.count())]

    for wanted in option_texts:
        for actual in available:
            if actual.lower() == wanted.lower():
                select_locator.select_option(label=actual)
                return actual
    return None


def read_table_by_section_title(page: Page, section_title: str) -> list[dict]:
    """
    Find the first table that appears AFTER an element containing
    `section_title` (e.g. "Organization User Details") and return its rows
    as a list of dicts keyed by header text.

    Reads the DOM directly (no screenshots/OCR).
    """
    lit = _xpath_literal(section_title)
    table = page.locator(
        f"xpath=//*[contains(normalize-space(text()), {lit})]"
        f"/following::table[1]"
    )
    if table.count() == 0:
        return []
    table = table.first

    rows = table.locator("tr")
    if rows.count() == 0:
        return []

    # Headers: prefer <th>, fall back to first row's <td>s.
    header_cells = rows.nth(0).locator("th")
    if header_cells.count() == 0:
        header_cells = rows.nth(0).locator("td")
    headers = [header_cells.nth(i).inner_text().strip()
               for i in range(header_cells.count())]

    data: list[dict] = []
    for r in range(1, rows.count()):
        cells = rows.nth(r).locator("td")
        if cells.count() == 0:
            continue
        row: dict[str, str] = {}
        for c in range(cells.count()):
            key = headers[c] if c < len(headers) else f"col_{c}"
            row[key] = cells.nth(c).inner_text().strip()
        data.append(row)
    return data


def click_button_by_text(container, button_text: str,
                         timeout_ms: int = 5000) -> bool:
    """
    Click a button/link/input whose visible text (or value) matches.
    Returns True if something was clicked.

    `container` is normally a Page (searches the whole document), but can
    be a Locator to scope the search to that element's descendants only --
    important on pages that host more than one module/tab in the same DOM
    at once, where an unscoped text match can land on an unrelated control
    (e.g. a global icon-only "Search" button) instead of the one next to
    the form actually being filled in. Note the XPath candidates below use
    a leading "." when scoped (".//button...") -- a bare "//button..." is
    anchored to the document root even when queried from a Locator, per
    XPath semantics, and would silently defeat the scoping.
    """
    lit = _xpath_literal(button_text)
    xp = ".//" if isinstance(container, Locator) else "//"
    candidates = [
        container.get_by_role("button", name=button_text, exact=False),
        container.get_by_role("link", name=button_text, exact=False),
        container.locator(f"xpath={xp}input[@type='button' or @type='submit']"
                          f"[contains(@value, {lit})]"),
        container.locator(f"xpath={xp}button[contains(normalize-space(.), {lit})]"),
        container.locator(f"xpath={xp}a[contains(normalize-space(.), {lit})]"),
    ]
    for loc in candidates:
        try:
            if loc.count() > 0 and loc.first.is_visible():
                loc.first.click(timeout=timeout_ms)
                return True
        except Exception:
            continue
    return False


def button_exists(page: Page, button_text: str) -> bool:
    """Check whether a button/link with this visible text exists."""
    lit = _xpath_literal(button_text)
    candidates = [
        page.get_by_role("button", name=button_text, exact=False),
        page.get_by_role("link", name=button_text, exact=False),
        page.locator(f"xpath=//input[@type='button' or @type='submit']"
                     f"[contains(@value, {lit})]"),
        page.locator(f"xpath=//button[contains(normalize-space(.), {lit})]"),
    ]
    return any(loc.count() > 0 for loc in candidates)


# ===========================================================================
# 3. Selector debug mode
# ===========================================================================

def debug_dump_selectors(page: Page) -> None:
    """
    Print every input, select (with options), and button found on the page.
    Run `quickcap.sh --debug-selectors` on any QuickCap page, then use the
    printed names/ids to update the SELECTOR constants in quickcap_pages.py.
    """
    print("\n" + "=" * 70)
    print("SELECTOR DEBUG DUMP:", page.url)
    print("=" * 70)

    print("\n--- INPUT FIELDS ---")
    inputs = page.locator("input")
    for i in range(inputs.count()):
        el = inputs.nth(i)
        info = el.evaluate(
            "el => ({type: el.type, name: el.name, id: el.id, "
            "value: el.value, placeholder: el.placeholder})"
        )
        if info.get("type") == "hidden":
            continue
        print(f"  input  type={info['type']!r:12} name={info['name']!r:30} "
              f"id={info['id']!r:25} placeholder={info['placeholder']!r}")

    print("\n--- TEXTAREAS ---")
    areas = page.locator("textarea")
    for i in range(areas.count()):
        info = areas.nth(i).evaluate("el => ({name: el.name, id: el.id})")
        print(f"  textarea name={info['name']!r} id={info['id']!r}")

    print("\n--- SELECT DROPDOWNS ---")
    selects = page.locator("select")
    for i in range(selects.count()):
        el = selects.nth(i)
        info = el.evaluate("el => ({name: el.name, id: el.id})")
        opts = el.locator("option")
        texts = [opts.nth(j).inner_text().strip() for j in range(opts.count())]
        print(f"  select name={info['name']!r} id={info['id']!r} "
              f"options={texts}")

    print("\n--- BUTTONS / LINKS ---")
    buttons = page.locator(
        "button, input[type=button], input[type=submit], a")
    for i in range(min(buttons.count(), 80)):
        el = buttons.nth(i)
        try:
            tag = el.evaluate("el => el.tagName").lower()
            text = (el.inner_text().strip()
                    if tag != "input"
                    else el.get_attribute("value") or "")
            if text:
                print(f"  {tag:6} text={text!r}")
        except Exception:
            continue

    print("\n--- TABLE SECTION TITLES (headings & bold text) ---")
    heads = page.locator("h1, h2, h3, h4, b, strong, legend")
    for i in range(min(heads.count(), 40)):
        try:
            t = heads.nth(i).inner_text().strip()
            if t:
                print(f"  heading: {t!r}")
        except Exception:
            continue
    print("=" * 70 + "\n")


# ===========================================================================
# 4. Result reporting (console only -- nothing is recorded to disk)
# ===========================================================================

def log_result(token_number: str, full_name: str, email: str,
               organization_name: str, action: str,
               generated_username: str = "", notes: str = "") -> None:
    """
    Print one result line to the console. Deliberately writes NO file:
    runs are not recorded (no CSV, no screenshots).

    `action` values: approved, approved_after_popup_pick,
    approved_after_manual, rejected, manual_filled_approve,
    manual_filled_reject, assisted_declined_approve,
    assisted_declined_reject, skipped_old_request, error.
    """
    parts = [f"token={token_number or '?'}"]
    if full_name:
        parts.append(full_name)
    if email:
        parts.append(f"<{email}>")
    if organization_name:
        parts.append(f"@ {organization_name}")
    if generated_username:
        parts.append(f"username={generated_username}")
    if notes:
        parts.append(f"({notes})")
    print(f"  [result] {action}: " + " ".join(parts))


# ===========================================================================
# 5. Human-input prompts
# ===========================================================================
#
# Every place the script waits for the user goes through ask(), so each one
# looks the same in the terminal and answers the same three things at a
# glance: WHAT kind of input is needed (the banner label), WHICH request it
# is about (the "Request:" line), and EXACTLY what to type (the ">>>" line).
#
#   ======================================================================
#     ACTION NEEDED IN BROWSER: Set Status to Approved
#     Request: 20260728-3467 | John Smith <jsmith@example.com>
#   ----------------------------------------------------------------------
#     The script couldn't set the Status dropdown automatically.
#     In the browser: set Status to 'Approved'.
#   ======================================================================
#   >>> Press Enter here once done to continue...

PROMPT_WIDTH = 70

# "token | name <email>" of the request currently being processed, shown on
# every prompt so it's always clear which request a question is about. Set
# and cleared by main.process_request(); empty for run-level prompts.
_current_request = ""


def set_current_request(label: str) -> None:
    """Set (or clear, with "") the request label shown on every prompt."""
    global _current_request
    _current_request = label


def ask(kind: str, title: str, details: list[str], answer_hint: str) -> str:
    """
    Print one framed prompt block and return the user's raw (stripped)
    answer. `kind` is the banner label (e.g. "QUESTION"), `title` a short
    headline, `details` the explanation lines (wrapped to PROMPT_WIDTH),
    and `answer_hint` the final ">>>" line telling the user what to type.
    """
    print("\n" + "=" * PROMPT_WIDTH)
    print(f"  {kind}: {title}")
    if _current_request:
        print(f"  Request: {_current_request}")
    if details:
        print("-" * PROMPT_WIDTH)
        for line in details:
            print(textwrap.fill(line, width=PROMPT_WIDTH,
                                initial_indent="  ", subsequent_indent="     "))
    print("=" * PROMPT_WIDTH)
    return input(f">>> {answer_hint} ").strip()


def manual_pause(title: str, *steps: str) -> None:
    """Block until the user has done something by hand in the browser."""
    ask("ACTION NEEDED IN BROWSER", title, list(steps),
        "Press Enter here once done to continue...")


def confirm(question: str, *details: str) -> bool:
    """Ask a yes/no question. Only 'y' or 'yes' returns True."""
    answer = ask("QUESTION", question, list(details),
                 "Type y + Enter for YES, or just Enter for NO [y/N]:")
    return answer.lower() in ("y", "yes")


def choose(title: str, options: dict[str, str], *details: str) -> str:
    """
    Numbered-menu prompt: `options` maps each accepted answer (e.g. "1")
    to its description. Re-asks until a valid key is typed; returns it.
    """
    keys = list(options)
    hint = f"Type {', '.join(keys[:-1])} or {keys[-1]}, then Enter:"
    lines = list(details) + [f"{k}) {desc}" for k, desc in options.items()]
    answer = ask("CHOOSE", title, lines, hint)
    while answer not in options:
        answer = input(f">>> '{answer}' isn't one of the options. "
                       f"{hint} ").strip()
    return answer
QUICKCAP_EOF_UTILS_PY

# ---- quickcap_pages.py -------------------------------------------
cat > "$APP_DIR/quickcap_pages.py" <<'QUICKCAP_EOF_QUICKCAP_PAGES_PY'
"""
quickcap_pages.py
-----------------
Page Object Model for the QuickCap "Request To Login" area.

Two page objects:
  - RequestListPage : the search filters + results table.
  - RequestDetailPage : the edit form opened via the edit icon.

IMPORTANT -- SELECTORS:
QuickCap installations differ. All the guessable text labels and button
captions live in the CONSTANTS below, clearly marked with "UPDATE ME".
Run `quickcap.sh --debug-selectors` on each page, look at the printed
names/ids/labels, and adjust these constants. The helper functions in
utils.py search by visible text, so in many cases they will work as-is.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from urllib.parse import urljoin

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
# (only ever act on a request submitted today -- see main.py's row-selection
# loop). Located the same way as the Status column, by exact header text.
REQ_DATE_COLUMN_HEADER_TEXT = "Req. Date"

# --- Detail page -----------------------------------------------------------
# These are placeholder defaults -- run --debug-selectors against the real
# QuickCap system and re-check each one before relying on them. In
# particular, watch for a label being a *substring* of another label (e.g.
# the old "NPI" constant would also match "Organization NPI") or a shorter
# label appearing later in the DOM than a longer one that contains it (e.g.
# "Note" vs "External User Notes") -- find_input_by_label() takes the FIRST
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
# QuickCap deployments -- it must be filled with the requester's own first
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
# their own <tbody id="orgTableBody"> -- confirmed live, more precise than
# ORG_DETAILS_TABLE_TITLE's heading-based search for reading a specific
# row's name (see read_organization_details_name()). Each row's first
# <td> is "<b>{Organization ID}</b><br>{Organization Name}".
ORG_DETAILS_TABLE_BODY_ID = "orgTableBody"

SAVE_BUTTON_TEXTS = ["Save & Next", "Save and Next", "Save"]
SEND_EMAIL_BUTTON_TEXT = "Click to Send Email"
BACK_LINK_TEXT = "Back"

# The side-menu link to the Request To Login list. Its href is a direct URL
# to the list module (index.php?file=meds_request_login_list&...) -- see
# RequestListPage.goto() for why that's needed.
REQUEST_LIST_LINK_SELECTOR = "a[href*='file=meds_request_login_list']"

# --- Detail page: real-system element ids (preferred over label search) ---
# The real detail form nests tables several levels deep for layout, so a
# generic "find the <td> containing this label text" search matches an
# OUTER wrapper cell instead of the specific label cell -- confirmed live:
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
# matches nothing there) -- Organization ID is a plain <select> (#slt_OrgId)
# listing every Organization ID that shares this request's Tax ID, and it
# always has SOME option selected by default regardless of which one the
# request is actually for. Confirmed live against a real 3-candidate
# request: the "Organization NPI" field (ORG_NPI_FIELD_ID) holds the exact
# target Organization ID for this request, not a separate NPI number, and
# it matches one of the select's option values directly -- see
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
# organization belongs to (e.g. a health system) -- a separate concept from
# Organization ID/NPI resolution above, and NOT something derivable from
# the request's own data the way NPI-matching is, so this is opt-in via an
# explicit confirmation prompt rather than run automatically. Confirmed
# live: the icon's id is stable regardless of which request is open,
# clicking a result row (`a[onclick^='selectOnlyOneGroup']`) writes the
# picked name/id back onto the parent page via window.opener same as the
# Organization ID popup, but -- unlike that popup -- does NOT close itself
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
        """
        Navigate to the configured Request To Login list URL, if set.

        A URL copied from the address bar can have ANOTHER module as its
        base (e.g. "?file=meds_cpticd_virtual_group...#meds_request_login_list")
        with Request To Login only in the #hash. Confirmed live: a fresh
        load of such a URL in a new tab ignores the hash and lands on that
        other module (title "Virtual Group"), which has no Status filter.
        So if the loaded page isn't Request To Login, follow the side
        menu's own Request To Login link, whose href loads the list module
        directly.
        """
        url = config.QUICKCAP_REQUEST_LIST_URL
        if url:
            self.page.goto(url, timeout=config.DEFAULT_TIMEOUT_MS * 2)
        self.page.wait_for_load_state("domcontentloaded")
        self.open_list_via_menu_if_needed()

    def open_list_via_menu_if_needed(self) -> None:
        """
        If the current page isn't Request To Login (e.g. the QuickCap home
        page, or another module), follow the side menu's Request To Login
        link. Also called by main.run() right after a manual login, since a
        login page has no such link -- so a home-page URL in SETTINGS still
        ends up on the list without any manual navigation.
        """
        title = " ".join((self.page.title() or "").lower().split())
        if any(hint in title for hint in APP_PAGE_TITLE_HINTS):
            return
        link = self.page.locator(REQUEST_LIST_LINK_SELECTOR)
        if link.count() == 0:
            return  # e.g. a login page -- ensure_logged_in() handles that
        href = link.first.get_attribute("href") or ""
        print("    Opening Request To Login via the side-menu link.")
        self.page.goto(urljoin(self.page.url, href),
                       timeout=config.DEFAULT_TIMEOUT_MS * 2)
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
                "Log in to QuickCap",
                "A login screen was detected. The script never logs in for "
                "you.",
                "In the Chrome window: log in (including any MFA/CAPTCHA), "
                "then press Enter here. The script opens the Request "
                "To Login list itself.")
            self.page.wait_for_load_state("domcontentloaded")

    # -- filtering ----------------------------------------------------------

    def filter_pending_and_search(self) -> None:
        """
        Set Status filter = Pending and click Search, scoped to the Status
        select's own <form> (or nearest ancestor <table>, for older
        layouts with no <form>) rather than the whole page.

        This QuickCap installation hosts more than one module in the same
        DOM at once (reached via link_module/link_id + URL-hash routing --
        "Request To Login" is one, "Virtual Group" another). A page-wide
        text match for "Search" can land on an unrelated control, such as
        a global icon-only search button, which silently navigates the
        SPA away from the list entirely instead of searching it -- the
        script then finds 0 pending rows because it's no longer looking
        at the Request To Login list at all. Scoping to the filter form
        avoids that ambiguity.
        """
        status = utils.find_select_by_label(self.page, STATUS_FILTER_LABEL)
        if status is None:
            utils.manual_pause(
                "Filter the list to Pending",
                f"Couldn't find the '{STATUS_FILTER_LABEL}' filter dropdown "
                "on the list page.",
                f"In the browser: set {STATUS_FILTER_LABEL} = "
                f"{config.PENDING_STATUS_OPTION} and click "
                f"{SEARCH_BUTTON_TEXT}.")
        else:
            chosen = utils.select_option_by_visible_text(
                status, [config.PENDING_STATUS_OPTION])
            if chosen is None:
                utils.manual_pause(
                    "Filter the list to Pending",
                    f"The '{config.PENDING_STATUS_OPTION}' option wasn't "
                    "found in the Status filter dropdown.",
                    f"In the browser: set {STATUS_FILTER_LABEL} = "
                    f"{config.PENDING_STATUS_OPTION}.")

            search_scope = status.locator("xpath=ancestor::form[1]")
            if search_scope.count() == 0:
                search_scope = status.locator("xpath=ancestor::table[1]")
            search_target = (search_scope.first if search_scope.count() > 0
                             else self.page)

            if not utils.click_button_by_text(search_target, SEARCH_BUTTON_TEXT):
                utils.manual_pause(
                    f"Click {SEARCH_BUTTON_TEXT}",
                    f"Couldn't find the '{SEARCH_BUTTON_TEXT}' button next "
                    "to the Status filter.",
                    f"In the browser: click {SEARCH_BUTTON_TEXT} on the "
                    "list page.")
        self.page.wait_for_load_state("domcontentloaded")
        self._wait_for_results_to_settle()

    def _wait_for_results_to_settle(self, timeout_ms: int = 5000) -> None:
        """
        Search reloads the results grid via AJAX on the real system -- no
        real navigation happens, so wait_for_load_state("domcontentloaded")
        above is a no-op (the document already finished loading once, long
        before Search was clicked). Confirmed live: right after the click,
        the grid briefly has zero edit icons while old rows are cleared and
        new ones are inserted (~0.3-0.6s), so counting immediately reports
        0 pending even though the real count is non-zero moments later.
        Poll until the edit-icon count is non-zero and identical across two
        consecutive checks (i.e. no longer mid-refresh), or give up after
        `timeout_ms` -- a genuinely empty result list also reads as 0 the
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

        Counting edit icons alone is not reliable: every row -- Approved and
        Rejected included -- has one, so if the Status filter silently fails
        to apply (wrong label match, a slow reload, etc.) every visible row
        would get treated as matching. Reading the Status cell by its known
        column index is what actually distinguishes rows, and an exact
        match on that single cell avoids the false positives a substring
        search anywhere in the row could hit (e.g. an organization name or
        note that happens to contain "Pending").

        Falls back to the previous whole-row substring match (Playwright's
        accessible-name search) when the Status column's position can't be
        determined -- e.g. an installation with no discoverable header row.

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
        list has rows but none are being recognized as Pending -- a mismatch
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
                "quickcap.sh --debug-selectors and update EDIT_ICON_SELECTOR in "
                "the quickcap_pages.py section of quickcap.sh.")
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
        `timeout_ms`. A no-op if it never appears -- e.g. an installation
        whose detail page doesn't expose this id at all -- since that
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
        label-based fallback below -- which looks for the <td> containing
        `label`'s text -- can match an outer wrapper cell several levels up
        instead of the specific label cell, and read nothing at all;
        confirmed live, this broke EVERY field, not just one. Direct ids
        are immune to that because they don't depend on DOM nesting.
        Falls back to label search when no id is given or it's not found.

        If an <input>/<textarea>/<select> was found, its value is
        authoritative -- including an empty string, e.g. an Organization ID
        left blank pending a popup pick -- so a genuinely empty input must
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
        it ALWAYS has some option selected by default -- so "is
        Organization ID filled in" can't signal single-vs-multi-org here;
        the select's option COUNT is what matters, checked first.

        Falls back to a blank-means-unresolved model -- Organization ID
        empty means unresolved, then count distinct ids in the
        "Organization Details" table -- when no such select exists.
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
        table's row for `organization_id` -- the canonical per-row name as
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
        -- there's no popup to disambiguate (ORG_SEARCH_ICON_SELECTOR
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
        ID/Name/NPI on this page itself via window.opener -- see
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
        the confirmation prompt at all -- see pick_organization_group_via_popup.
        """
        icon = self.page.locator(ORG_GROUP_ICON_SELECTOR)
        return icon.count() > 0 and icon.first.is_visible()

    def read_organization_group(self) -> str:
        """Current value of the Organization Group field."""
        return self._read_field("Organization Group", ORG_GROUP_INPUT_ID)

    def pick_organization_group_via_popup(
            self, name_queries: list[str]) -> str | None:
        """
        Click the Organization Group search icon, wait for the popup
        window, and try each of `name_queries` in order (normally the full
        organization name, then its first two words -- see
        main.handle_new_user) until one finds a matching row:

          - First query: an exact case-insensitive match, else the first
            result containing the query as a substring.
          - Later (shorter, broader) queries: an exact match, else a
            substring match ONLY if exactly one result contains it. A
            two-word query like "Advanced Home" can easily match several
            unrelated groups, so an ambiguous result is left for the user.

        Unlike pick_organization_via_popup (Organization ID), there's no
        reliable field on the request itself (like NPI) to confirm which
        Virtual Group is correct -- it's a business grouping (e.g. a health
        system), not something derivable from the request's own data. So
        this only auto-picks when a search actually returns a name-matching
        row; if none does, it deliberately leaves the popup OPEN (showing
        the last search's results) and returns None, so the caller can
        pause for a manual pick instead of guessing on a real approval.
        Also unlike that popup, this one does not close itself after a row
        is clicked -- confirmed live, selectOnlyOneGroup(...) only writes
        the value back via window.opener -- so a successful pick closes it
        explicitly here.
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
        queries = [q.strip() for q in name_queries if q.strip()]
        if name_input is None:
            queries = queries[:1]  # can't type a different query anyway

        picked_link, picked_text = None, None
        for attempt, query in enumerate(queries):
            if attempt > 0:
                print(f"    No group matched; searching again for "
                      f"'{query}'...")
            self._search_group_popup(popup, name_input, query)
            picked_link, picked_text = self._match_group_result(
                popup, query, allow_ambiguous=(attempt == 0))
            if picked_link is not None:
                break
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

    def _search_group_popup(self, popup: Page, name_input, query: str) -> None:
        """
        Type `query` into the Organization Group popup's Name filter and
        click Search. When results from an earlier search are on screen,
        waits for them to be replaced first, so a second search never reads
        the previous search's stale rows.
        """
        links = popup.locator(ORG_GROUP_POPUP_RESULT_LINK_SELECTOR)
        stale = links.first.element_handle() if links.count() > 0 else None
        if name_input is not None:
            name_input.fill(query)
        utils.click_button_by_text(popup, ORG_GROUP_POPUP_SEARCH_BUTTON_TEXT)
        if stale is not None:
            try:
                popup.wait_for_function("el => !el.isConnected", arg=stale,
                                        timeout=5000)
            except Exception:
                pass  # page navigated (handle gone) or rows unchanged
        popup.wait_for_load_state("domcontentloaded")

    @staticmethod
    def _match_group_result(popup: Page, query: str, allow_ambiguous: bool):
        """
        (link, text) of the popup result matching `query`, or (None, None).
        Exact case-insensitive match wins; otherwise a substring match --
        the first one if `allow_ambiguous`, else only when it's unique.
        """
        query_l = query.lower()
        rows = popup.locator(ORG_GROUP_POPUP_RESULT_LINK_SELECTOR)
        partial: list[tuple] = []
        for i in range(rows.count()):
            link = rows.nth(i)
            try:
                text = link.inner_text().strip()
            except Exception:
                continue
            if text.lower() == query_l:
                return link, text
            if query_l and query_l in text.lower():
                partial.append((link, text))
        if partial and (allow_ambiguous or len(partial) == 1):
            return partial[0]
        if len(partial) > 1:
            print(f"    '{query}' matches {len(partial)} groups: "
                  + ", ".join(t for _, t in partial))
        return None, None

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
        constants) -- try whichever one is currently visible first, since
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
        Details table, but shows no visible error when that check fails --
        confirmed live, Save just silently leaves the exact same request's
        detail form displayed, unchanged. There's no error text to key
        off; the only observable signal is whether the page moved on at
        all.

        Polls the Email field for up to `timeout_ms`: if it becomes
        something other than `email_before` at any point (a new/next
        request loaded) -- or the field disappears entirely (e.g. back at
        the list) -- Save advanced and this returns True. If it still
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
        view -- the server session can keep showing whatever sub-view
        (e.g. this same detail form) was last open instead of the list,
        and a full reload also risks landing on a different module
        entirely if the base URL's file= parameter doesn't point at this
        one (see filter_pending_and_search's docstring). Returns False if
        no 'Back' control was found, so the caller can fall back.

        Like Search (see _wait_for_results_to_settle), this swaps content
        client-side rather than triggering a real navigation, so briefly
        after the click the list still isn't in the DOM yet -- confirmed
        live, an immediate check right after the click can still see the
        detail form. Poll briefly until the detail form is gone AND the
        list's header row is present before returning, so callers don't
        query mid-transition (where the detail form's own Status select can
        be the only "Status" element around and get mistaken for the list's
        filter). A header row alone isn't enough: confirmed live, the
        detail form itself contains four `tr.hdr` rows (its Organization /
        User / Email Logs / Upload tables).
        """
        if not utils.click_button_by_text(self.page, BACK_LINK_TEXT):
            return False
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if (not self.is_open()
                    and self.page.locator(HEADER_ROW_SELECTOR).count() > 0):
                break
            self.page.wait_for_timeout(150)
        return True

    def is_open(self) -> bool:
        """Whether a request's detail form is currently displayed."""
        return self.page.locator(f"#{EMAIL_INPUT_ID}").count() > 0
QUICKCAP_EOF_QUICKCAP_PAGES_PY

# ---- main.py -----------------------------------------------------
cat > "$APP_DIR/main.py" <<'QUICKCAP_EOF_MAIN_PY'
"""
main.py
-------
QuickCap "Request To Login" automation -- entry point.

WHAT THIS SCRIPT DOES
  - Filters the request list to Status=Pending, opens each request via the
    edit icon, checks whether the email already exists in the Organization
    User Details table, and either approves (with a generated username) or
    rejects with a note. Results are printed to the console only --
    nothing is recorded (no log files, no screenshots).
  - Only ever acts on a request whose Req. Date is TODAY -- anything older
    is left pending untouched (see utils.is_today / the row-selection loop
    in run()). Re-run the script another day to pick those up.

WHAT THIS SCRIPT NEVER DOES
  - It never logs in for you, never touches MFA/CAPTCHA, never calls backend
    APIs, and never sends emails unless you pass --send-email AND confirm.
  - It never touches a pending request that wasn't submitted today.

MODES  (prompted interactively at startup if --mode is omitted)
  manual    -> fill the form, never click Save -- you save it yourself in
               the browser.
  assisted  -> fill the form, ask y/n before every Save & Next.
  auto      -> fill the form and save without asking each time.
  quickcap.sh --debug-selectors           -> print page elements, then exit

RECOMMENDED ORDER while validating against a new QuickCap installation:
--debug-selectors first, then a few requests in "assisted" mode with
--max-requests set low, then "auto" once you trust the fills.

CHROME OPTIONS
  --chrome connect  (default) Attach to the automation Chrome that's already
                    running and open a NEW TAB in it. If it isn't running,
                    start it once (debugging port + the chrome-profile
                    folder, so your login is remembered) and leave it open
                    for the next run.
  --chrome launch   (legacy) Playwright opens a separate Chrome window with
                    the same profile folder and closes it when done.

START PAGE OPTIONS
  --start-page auto     (default) open a new tab on QUICKCAP_REQUEST_LIST_URL
  --start-page goto     same as auto
  --start-page current  reuse an already-open QuickCap tab, without
                        navigating it
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import traceback
import urllib.request
from urllib.parse import urlparse

# Windows terminals often default to a legacy codepage (e.g. cp1252) that
# can't encode characters like the pending-row edit icon (U+270E) captured
# from the page text. Force UTF-8 so a print() never crashes the run.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

import config
import utils
from quickcap_pages import (RequestDetailPage, RequestListPage,
                            SEND_EMAIL_BUTTON_TEXT)


# ===========================================================================
# CLI
# ===========================================================================

MODE_LABELS = {
    "manual": "MANUAL AUTOFILL  (fills fields; you click Save yourself)",
    "assisted": "ASSISTED  (fills fields; confirms before every Save & Next)",
    "auto": "FULLY AUTOMATIC  (fills and saves without asking each time)",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="QuickCap 'Request To Login' UI automation (safe, "
                    "UI-only). Only acts on requests submitted today.")
    parser.add_argument(
        "--mode", choices=["manual", "assisted", "auto"], default=None,
        help="manual: fill fields but never click Save -- you save it "
             "yourself in the browser. assisted: fill fields and ask y/n "
             "before every Save & Next. auto: fill and save without asking "
             "each time. If omitted, you're prompted to choose "
             "interactively at startup.")
    parser.add_argument(
        "--send-email", action="store_true",
        help="Allow clicking 'Click to Send Email' (still asks per request). "
             "Without this flag the button is NEVER clicked.")
    parser.add_argument(
        "--chrome", choices=["connect", "launch"], default="connect",
        help="connect (default): open a new tab in the already-running "
             "automation Chrome, starting it first if needed (it stays "
             "open afterwards). launch: legacy -- Playwright opens a "
             "separate Chrome window and closes it when done.")
    parser.add_argument(
        "--start-page", choices=["auto", "current", "goto"], default="auto",
        help="auto/goto (default): open a new tab on "
             "QUICKCAP_REQUEST_LIST_URL. current: reuse an already-open "
             "QuickCap tab as-is.")
    parser.add_argument(
        "--debug-selectors", action="store_true",
        help="Open the list page, print all inputs/selects/buttons, and "
             "pause so you can navigate and dump other pages too.")
    parser.add_argument(
        "--max-requests", type=int, default=0,
        help="Stop after N requests (0 = process all of today's pending).")
    return parser.parse_args()


class ModeState:
    """
    Mutable holder for the current mode. A plain string can't be changed
    from inside handle_duplicate()/handle_new_user() and have that change
    seen by run()'s loop on the next iteration -- this small wrapper is
    passed around by reference instead, so manual mode can upgrade itself
    to auto mid-run (see offer_switch_to_auto()) without restarting.

    `locked_manual` is set once the user opts, after today's pending
    requests run out, to continue with older ones too (see run()) -- that
    batch is manual-only by the user's explicit choice, so
    offer_switch_to_auto() stops offering the auto upgrade once it's set.
    """

    def __init__(self, mode: str):
        self.mode = mode
        self.locked_manual = False


def offer_switch_to_auto(state: ModeState) -> None:
    """
    In manual mode, let the user upgrade to fully-automatic for the rest
    of the run instead of clicking Save themselves for every request.
    Only called from the manual branch, so this never fires in
    assisted/auto. Mutates `state.mode` in place -- callers re-check
    `state.mode` immediately after to decide whether to still treat this
    request as manual (return) or fall through to the auto save path.

    No-ops into a plain pause once `state.locked_manual` is set: the
    older-pending-requests batch (see run()) is manual-only by the user's
    own choice, so no upgrade is offered there.
    """
    review = ("The form is filled in. Check it in the browser, then click "
              "Save yourself.")
    if state.locked_manual:
        utils.manual_pause("Review the form and click Save", review)
        return
    answer = utils.ask(
        "ACTION NEEDED IN BROWSER", "Review the form and click Save",
        [review,
         "Or type a to let the script save this one and every request "
         "after it (FULLY AUTOMATIC for the rest of this run)."],
        "Press Enter after you've clicked Save, or type a + Enter for "
        "FULLY AUTOMATIC:").lower()
    if answer == "a":
        state.mode = "auto"
        print("    Switched to FULLY AUTOMATIC for the rest of this run.")


def prompt_for_mode() -> str:
    """
    Ask which of the three modes to run in. Only called when --mode wasn't
    passed on the command line, so scripted/CI invocations can still pass
    --mode explicitly and skip this prompt entirely.
    """
    answer = utils.choose("How should this run work?", {
        "1": "Manual autofill - fills the form; you click Save yourself",
        "2": "Auto (confirm) - fills the form and asks y/n before every "
             "Save & Next",
        "3": "Fully automatic - fills the form and saves without asking",
    })
    return {"1": "manual", "2": "assisted", "3": "auto"}[answer]


def prompt_for_older_batch_choice(remaining: int) -> str:
    """
    Ask how to proceed once today's pending requests run out but older
    (not-today) ones still remain -- see run(). Returns "no" (leave them
    pending, stop the run), "manual" (fill only, confirm each one), or
    "auto" (fill and save automatically -- caller must then also ask
    prompt_for_request_count() since auto here always needs an explicit
    cap, unlike the main --max-requests which is optional).
    """
    answer = utils.choose(
        "Process the older pending requests too?", {
            "1": "No - stop here and leave them pending",
            "2": "Manual - fill each one; you click Save yourself, one at "
                 "a time",
            "3": "Auto - fill and save automatically, for a number of "
                 "requests you choose next",
        },
        f"All of TODAY's pending requests are done. {remaining} older "
        f"(not today's) pending request(s) remain.")
    return {"1": "no", "2": "manual", "3": "auto"}[answer]


def prompt_for_request_count(title: str) -> int:
    """Ask for a positive integer, reprompting until one is given."""
    answer = utils.ask("ENTER A NUMBER", title, [],
                       "Type a whole number (1 or more), then Enter:")
    while True:
        try:
            value = int(answer)
            if value > 0:
                return value
        except ValueError:
            pass
        answer = input(f">>> '{answer}' isn't a whole number above 0. "
                       "Try again: ").strip()


# ===========================================================================
# Chrome connection (default: connect + new tab; legacy: launch)
# ===========================================================================

def get_page(pw, chrome_mode: str,
             reuse_tab: bool) -> tuple[Page, BrowserContext | None]:
    """
    Returns (page, closable) where closable is the context to close on exit
    ('launch' mode only). In 'connect' mode it's None: we only disconnect,
    and Chrome -- including the tab we opened -- deliberately stays running
    so the next run can attach to it straight away instead of starting a
    fresh browser.

    'connect' opens a NEW TAB in the running automation Chrome (starting
    Chrome first if nothing is listening on CHROME_DEBUG_URL), unless
    `reuse_tab` (--start-page current) asks to take over an existing
    QuickCap tab instead.
    """
    if chrome_mode == "launch":
        # Legacy: Playwright-managed window with the persistent profile.
        context: BrowserContext = pw.chromium.launch_persistent_context(
            user_data_dir=config.CHROME_PROFILE_DIR,
            channel="chrome",
            headless=False,
            viewport=None,
            args=["--start-maximized"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        return page, context

    started = False
    if not _chrome_debug_port_open():
        _start_chrome_with_debugging()
        started = True

    print(f"Connecting to Chrome at {config.CHROME_DEBUG_URL} ...")
    try:
        browser: Browser = pw.chromium.connect_over_cdp(
            config.CHROME_DEBUG_URL)
    except Exception as exc:
        print(f"\nCould not connect to Chrome at {config.CHROME_DEBUG_URL}."
              f"\nDetails: {exc}")
        sys.exit(1)
    context = (browser.contexts[0] if browser.contexts
               else browser.new_context())
    if reuse_tab and context.pages:
        page = choose_existing_quickcap_page(context.pages)
    elif started and context.pages:
        # Chrome just opened with its own first tab -- use it rather than
        # leaving an empty tab next to ours.
        page = context.pages[0]
    else:
        page = context.new_page()
        print("Opened a new tab in the running Chrome.")
    page.bring_to_front()
    return page, None


def _chrome_debug_port_open() -> bool:
    """Whether a Chrome is already listening on CHROME_DEBUG_URL."""
    # Bypass any system/corporate proxy -- this is always a local port.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"{config.CHROME_DEBUG_URL.rstrip('/')}/json/version",
                         timeout=1):
            return True
    except Exception:
        return False


def _find_chrome_exe() -> str | None:
    """CHROME_PATH from quickcap.sh SETTINGS, else Chrome's usual install locations."""
    if config.CHROME_PATH:
        return config.CHROME_PATH if os.path.isfile(config.CHROME_PATH) else None
    for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        root = os.environ.get(var)
        if not root:
            continue
        path = os.path.join(root, "Google", "Chrome", "Application",
                            "chrome.exe")
        if os.path.isfile(path):
            return path
    # macOS: the binary inside the app bundle (system-wide, then per-user).
    for path in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                 os.path.expanduser("~/Applications/Google Chrome.app/"
                                    "Contents/MacOS/Google Chrome")):
        if os.path.isfile(path):
            return path
    return shutil.which("chrome") or shutil.which("google-chrome")


def _start_chrome_with_debugging(timeout_s: float = 20) -> None:
    """
    Start the real, installed Chrome on CHROME_DEBUG_URL's port with the
    CHROME_PROFILE_DIR profile (so an earlier QuickCap login is kept), as
    a detached process that outlives this script. Later runs then find it
    already listening and just open a new tab in it.
    """
    exe = _find_chrome_exe()
    if not exe:
        print("\nCouldn't find Google Chrome. Set CHROME_PATH in quickcap.sh's SETTINGS to its "
              "full path and run again.")
        sys.exit(1)
    port = urlparse(config.CHROME_DEBUG_URL).port or 9222
    print(f"Chrome isn't running for automation yet -- starting it on port "
          f"{port} (it stays open after this run)...")
    flags: dict = {}
    if sys.platform == "win32":
        flags["creationflags"] = (subprocess.DETACHED_PROCESS
                                  | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        flags["start_new_session"] = True
    subprocess.Popen(
        [exe, f"--remote-debugging-port={port}",
         f"--user-data-dir={config.CHROME_PROFILE_DIR}",
         "--no-first-run", "--no-default-browser-check", "--start-maximized"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, close_fds=True, **flags)

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _chrome_debug_port_open():
            return
        time.sleep(0.5)
    print(
        "\nChrome started, but its debugging port never opened. This "
        "usually means a Chrome window using the same profile folder\n"
        f"  {config.CHROME_PROFILE_DIR}\n"
        "is already open WITHOUT remote debugging (e.g. one left over from "
        "an older run). Close that window and run again.")
    sys.exit(1)


def choose_existing_quickcap_page(pages: list[Page]) -> Page:
    """
    Pick the most likely QuickCap tab from an already-running Chrome.

    CDP does not reliably expose the active tab in every environment, so use
    configured QuickCap URLs first. If nothing matches, use the last open tab.
    """
    if not pages:
        raise RuntimeError("Connected to Chrome, but no tabs were available.")

    url_hints = [
        config.QUICKCAP_REQUEST_LIST_URL,
        config.QUICKCAP_URL,
    ]
    normalized_hints = [hint.rstrip("/") for hint in url_hints if hint]
    hint_hosts = {
        urlparse(hint).netloc.lower()
        for hint in normalized_hints
        if urlparse(hint).netloc
    }

    for page in reversed(pages):
        current = (page.url or "").rstrip("/")
        if any(current.startswith(hint) for hint in normalized_hints):
            return page
        host = urlparse(current).netloc.lower()
        if host and host in hint_hosts:
            return page

    return pages[-1]


# ===========================================================================
# Processing one request
# ===========================================================================

def process_request(page: Page, token_hint: str, state: ModeState,
                    send_email_enabled: bool) -> None:
    """Handle the detail page currently open in `page`."""
    detail = RequestDetailPage(page)
    d = detail.extract_details(token_number=token_hint)

    # If token wasn't visible on the list, try the detail page.
    if not d.token_number:
        d.token_number = detail._read_field("Token")

    print(f"\n--- Request {d.token_number or '?'} : {d.full_name} "
          f"<{d.email}> @ {d.organization_name}")
    print(f"    Existing org user emails: {d.existing_user_emails or '(none)'}")
    utils.set_current_request(
        f"{d.token_number or '?'} | {d.full_name or '(no name)'} "
        f"<{d.email or 'no email'}>")

    if not d.email:
        utils.log_result(d.token_number, d.full_name, d.email,
                         d.organization_name, "error",
                         notes="Email field not found/empty")
        utils.manual_pause(
            "Handle this request yourself",
            "The Email field is missing or empty, so the script can't tell "
            "whether this is a duplicate.",
            "In the browser: approve/reject this request yourself, or leave "
            "it. The script then moves on to the next request.")
        return

    duplicate = RequestDetailPage.email_already_exists(d)

    if duplicate:
        handle_duplicate(page, detail, d, state, send_email_enabled)
    else:
        handle_new_user(page, detail, d, state)


def handle_duplicate(page: Page, detail: RequestDetailPage,
                     d, state: ModeState, send_email_enabled: bool) -> None:
    """Duplicate email -> Rejected/Denied + note."""
    print("    -> DUPLICATE email found in Organization User Details.")

    chosen = detail.set_status(config.REJECT_STATUS_OPTIONS)
    if chosen is None:
        utils.manual_pause(
            "Set Status to Rejected",
            "The script couldn't set the Status dropdown automatically.",
            "In the browser: set Status to "
            + " or ".join(f"'{s}'" for s in config.REJECT_STATUS_OPTIONS)
            + ".")
        chosen = "Rejected (manual)"
    if not detail.fill_note(config.DUPLICATE_EMAIL_NOTE):
        print("    (No note field found -- add the note manually if needed.)")

    if state.mode == "manual":
        offer_switch_to_auto(state)
        if state.mode != "auto":
            utils.log_result(d.token_number, d.full_name, d.email,
                             d.organization_name, "manual_filled_reject",
                             notes="Fields filled; save left to the user")
            return
        # else: just switched to auto -- fall through to the save below.

    if state.mode == "assisted":
        if not utils.confirm(
                f"Save this request as '{chosen}'?",
                f"Duplicate: {d.email} already has an account in this "
                "organization.",
                f"Status: {chosen}  |  Note: {config.DUPLICATE_EMAIL_NOTE}",
                "YES = click Save now.  NO = leave it filled but unsaved "
                "and move on."):
            utils.log_result(d.token_number, d.full_name, d.email,
                             d.organization_name, "assisted_declined_reject",
                             notes="Fields filled; save declined")
            return

    if not detail.click_save():
        utils.manual_pause(
            "Click Save yourself",
            "The Save button wasn't found on the page.",
            "In the browser: click Save (or Save & Next).")

    # Send-email is opt-in twice: the flag AND a per-request confirmation.
    if detail.has_send_email_button():
        if send_email_enabled and utils.confirm(
                f"Send the rejection email to {d.email}?",
                f"YES = click '{SEND_EMAIL_BUTTON_TEXT}'.  NO = don't "
                "send it."):
            detail.click_send_email()
            print("    Email button clicked.")
        else:
            print(f"    '{SEND_EMAIL_BUTTON_TEXT}' present but NOT clicked "
                  "(run with --send-email to enable).")

    utils.log_result(d.token_number, d.full_name, d.email,
                     d.organization_name, "rejected",
                     notes=config.DUPLICATE_EMAIL_NOTE)


def handle_new_user(page: Page, detail: RequestDetailPage,
                    d, state: ModeState) -> None:
    """New email -> Approved + generated username."""
    username = utils.generate_username(
        d.first_name, d.last_name, d.existing_usernames)
    print(f"    -> NEW user. Generated username: {username}")

    chosen = detail.set_status([config.APPROVE_STATUS_OPTION])
    if chosen is None:
        utils.manual_pause(
            f"Set Status to {config.APPROVE_STATUS_OPTION}",
            "The script couldn't set the Status dropdown automatically.",
            f"In the browser: set Status to "
            f"'{config.APPROVE_STATUS_OPTION}'.")

    if not detail.fill_username(username):
        print("    (No username field found -- enter it manually if needed.)")
    detail.confirm_name_fields(d)

    if not detail.fill_approval_name(d.full_name):
        print("    (No approval 'Name' field found -- enter the requester's "
              "full name manually if needed.)")

    # Organization handling: if the Tax ID maps to more than one
    # Organization ID, use the search popup to resolve it before approving.
    if d.organization_count > 1:
        print(f"    Multiple organizations detected "
              f"({d.organization_count}). Opening the organization search "
              f"popup...")
        picked = detail.pick_organization_via_popup(d.organization_name)
        resolved_id = detail.read_organization_id()
        if picked and resolved_id:
            print(f"    -> Selected via popup: {picked} "
                  f"(Organization ID now {resolved_id})")
            d.organization_id = resolved_id
            action = "approved_after_popup_pick"
        else:
            utils.manual_pause(
                "Pick the Organization ID",
                f"This Tax ID maps to {d.organization_count} organizations "
                "and the script couldn't tell which one this request is "
                "for.",
                f"In the browser: select the Organization ID for "
                f"'{d.organization_name}'.")
            action = "approved_after_manual"
    else:
        action = "approved"

    # Organization Group: optional, only appears once Status=Approved.
    # Not something the automation can resolve on its own (it's a business
    # grouping, not derivable from the request's own data the way
    # Organization ID/NPI is), so it's gated behind an explicit prompt
    # rather than attempted automatically. Search query comes from the
    # Organization Details table's own row for the resolved Organization
    # ID (the real system's canonical per-row name), not d.organization_name
    # (the top "*Name of the Organization" field) -- the two can differ in
    # formatting (e.g. a trailing comma). Falls back to d.organization_name
    # if that row lookup finds nothing.
    if detail.has_organization_group_icon():
        group_query = (detail.read_organization_details_name(
            d.organization_id) or d.organization_name)
        # Organization names here often carry a trailing corporate suffix
        # after a comma (e.g. "AeroCare Home Medical, Inc") that virtual
        # group names don't use at all -- strip it so the search box gets
        # just the base name. A no-op when there's no comma.
        group_query = group_query.split(",")[0].strip()
        # If the full name finds nothing, retry with just its first two
        # words (e.g. "AeroCare Home Medical" -> "AeroCare Home") before
        # falling back to asking the user.
        short_query = " ".join(group_query.split()[:2])
        queries = [group_query]
        if short_query.lower() != group_query.lower():
            queries.append(short_query)
        if utils.confirm(
                "Fill in the Organization Group?",
                "The script will search the Organization Group popup for "
                + " then ".join(f"'{q}'" for q in queries)
                + " and pick the matching group.",
                "YES = search and pick.  NO = skip; leave Organization "
                "Group blank."):
            picked_group = detail.pick_organization_group_via_popup(queries)
            resolved_group = detail.read_organization_group()
            if picked_group and resolved_group:
                print(f"    -> Selected organization group: {picked_group} "
                      f"(Organization Group now {resolved_group!r})")
            else:
                utils.manual_pause(
                    "Pick the Organization Group",
                    "No single group matched "
                    + " or ".join(f"'{q}'" for q in queries) + ".",
                    "In the Organization Group popup window (click the "
                    "search icon next to Organization Group if it's not "
                    "open): search for and click the correct group, or "
                    "close the popup to leave it blank.")

    if state.mode == "manual":
        offer_switch_to_auto(state)
        if state.mode != "auto":
            utils.log_result(d.token_number, d.full_name, d.email,
                             d.organization_name, "manual_filled_approve",
                             generated_username=username,
                             notes="Fields filled; save left to the user")
            return
        # else: just switched to auto -- fall through to the save below.

    if state.mode == "assisted":
        if not utils.confirm(
                f"Save this request as Approved, username '{username}'?",
                f"New user: {d.email} has no account in this organization "
                "yet.",
                "YES = click Save & Next now.  NO = leave it filled but "
                "unsaved and move on."):
            utils.log_result(d.token_number, d.full_name, d.email,
                             d.organization_name, "assisted_declined_approve",
                             generated_username=username,
                             notes="Fields filled; save declined")
            return

    # Retry Save with the next username on a silent failure. The real
    # system checks username uniqueness system-wide, not just against the
    # accounts visible in this org's Organization User Details table (what
    # generate_username() already checked), and shows no error when that
    # wider check fails -- Save just leaves the same request displayed,
    # unchanged (see RequestDetailPage.save_advanced). Detected via
    # before/after comparison rather than any error message, since there
    # isn't one to key off.
    max_username_attempts = 10
    saved = False
    save_button_found = True
    for attempt in range(max_username_attempts):
        if not detail.click_save():
            save_button_found = False
            break
        if detail.save_advanced(d.email):
            saved = True
            break
        username = utils.bump_username(username)
        print(f"    Save did not advance -- likely a username collision "
              f"not visible in this org's user list. Retrying with "
              f"{username!r}...")
        detail.fill_username(username)

    if not save_button_found:
        utils.manual_pause(
            "Click Save & Next yourself",
            "The Save & Next button wasn't found on the page.",
            "In the browser: click Save & Next (or Save).")
    elif not saved:
        utils.manual_pause(
            "Fix the username and save",
            f"Save didn't go through after {max_username_attempts} "
            f"usernames (last tried: '{username}'), probably because each "
            "one is already taken elsewhere in QuickCap.",
            "In the browser: enter a free User Name and click Save & Next.")

    utils.log_result(d.token_number, d.full_name, d.email,
                     d.organization_name, action,
                     generated_username=username)


# ===========================================================================
# Main loop
# ===========================================================================

def should_use_current_page(start_page: str) -> bool:
    """Whether to resume from a tab already open, vs. navigating fresh."""
    return start_page == "current"


def return_to_list(page: Page, list_page: RequestListPage,
                   start_url: str) -> None:
    """
    Get back to the Pending list after processing one request. Prefers the
    detail page's own 'Back' link over reloading the list URL: confirmed
    live that a page.goto() to the exact same URL doesn't reliably reset
    the view -- the server session can keep showing whatever sub-view (e.g.
    the detail form just processed) was last open instead of the list, and
    a hard reload also risks landing on a different module entirely if the
    base URL's file= parameter doesn't point at this one. Falls back to the
    last known list URL, then a fresh goto(), when no 'Back' control exists.
    """
    if RequestDetailPage(page).go_back_to_list():
        page.wait_for_load_state("domcontentloaded")
        list_page.ensure_logged_in()
    elif start_url:
        page.goto(start_url, timeout=config.DEFAULT_TIMEOUT_MS * 2)
        page.wait_for_load_state("domcontentloaded")
        list_page.ensure_logged_in()
    else:
        list_page.goto()
        list_page.ensure_logged_in()


def _extract_token(row_summary: str) -> str:
    """Pull the Token No. out of peek_row_summary's '|'-joined cell text
    (cell 0 is the edit icon, cell 1 is Token No.)."""
    if not row_summary:
        return ""
    parts = [p.strip() for p in row_summary.split("|")]
    return parts[1] if len(parts) > 1 else parts[0]


def _find_next_target(
    list_page: RequestListPage, pending_count: int, handled_tokens: set[str],
    today_only: bool
) -> tuple[int | None, str, list[tuple[str, str]]]:
    """
    Scan pending rows from index 0 for the first one whose token isn't
    already in `handled_tokens`. While `today_only` is True (the default
    for the whole run, until the user opts otherwise -- see run()), a row
    whose Req. Date isn't today is skipped rather than returned: the
    same-day guard. Returns (index, token, skipped), where `skipped` lists
    every (token, req_date_text) pair passed over on the way (including
    ones already logged in an earlier pass -- the caller dedupes before
    logging). `index` is None once every pending row has either been
    handled or (while today_only) found not-today.

    Once `today_only` is False, the Req. Date check is skipped entirely
    and every not-yet-handled row is eligible, in list order.
    """
    skipped: list[tuple[str, str]] = []
    for i in range(pending_count):
        token = _extract_token(list_page.peek_row_summary(i))
        if token and token in handled_tokens:
            continue
        if today_only:
            req_date_text = list_page.pending_row_req_date(i)
            if not utils.is_today(req_date_text):
                skipped.append((token, req_date_text))
                continue
        return i, token, skipped
    return None, "", skipped


def run(page: Page, mode: str, send_email_enabled: bool,
        debug_selectors: bool, max_requests: int,
        use_current_page: bool) -> None:
    """
    Log in, filter the list to Pending, then repeatedly find and handle the
    next eligible pending request (submitted today, not already handled
    this run) until none remain or --max-requests is hit. `mode` is the
    starting mode only -- it's wrapped in a ModeState so manual mode can
    upgrade itself to auto mid-run (see offer_switch_to_auto()).

    Once today's requests run out, offers to continue into the older
    (not-today) ones too, either manually (locked -- no auto upgrade for
    that batch, state.locked_manual) or automatically for an explicit,
    mandatory number of requests (older_auto_limit) -- see the
    `today_only` local and prompt_for_older_batch_choice().
    """
    state = ModeState(mode)
    list_page = RequestListPage(page)
    start_url = ""

    if use_current_page:
        start_url = page.url if page.url != "about:blank" else ""
        print("\nUsing the existing Chrome tab.")
        print(f"Current page: {start_url or '(blank tab)'}")
        page.wait_for_load_state("domcontentloaded")
        list_page.ensure_logged_in()
        detail = RequestDetailPage(page)
        if detail.is_open():
            # A request's form is still open (e.g. one just saved). Go back
            # first, or the Pending filter step would find this form's own
            # Status dropdown instead of the list's filter.
            print("A request form is open -- going back to the list first.")
            detail.go_back_to_list()
        start_url = page.url if page.url != "about:blank" else start_url
    elif not config.QUICKCAP_REQUEST_LIST_URL:
        print("QUICKCAP_REQUEST_LIST_URL is not set (quickcap.sh "
              "SETTINGS).")
        sys.exit(1)
    else:
        list_page.goto()
        list_page.ensure_logged_in()
        # The configured URL may be the QuickCap home page, which has no
        # Request To Login menu link until you've logged in -- try it again.
        list_page.open_list_via_menu_if_needed()
        start_url = page.url

    if debug_selectors:
        utils.debug_dump_selectors(page)
        while utils.confirm(
                "Dump another page's elements too?",
                "First navigate to that page in the browser, then answer "
                "YES to print its elements.  NO = finish."):
            utils.debug_dump_selectors(page)
        return

    list_page.filter_pending_and_search()

    handled_tokens: set[str] = set()
    skip_logged_tokens: set[str] = set()
    today_only = True
    processed = 0
    # Only set once the user opts into the older-pending-requests batch
    # with "auto" (see prompt_for_older_batch_choice) -- an explicit,
    # mandatory cap on how many of THOSE get auto-saved, separate from
    # --max-requests (which bounds the whole run, today's requests
    # included, and is optional).
    older_auto_limit: int | None = None
    older_auto_processed = 0

    while True:
        if max_requests and processed >= max_requests:
            print(f"\nReached --max-requests={max_requests}. Stopping.")
            break
        if older_auto_limit is not None and older_auto_processed >= older_auto_limit:
            print(f"\nReached the {older_auto_limit} older pending "
                  f"request(s) you asked for. Stopping.")
            break

        pending = list_page.count_pending_rows()
        idx, token_hint, skipped = _find_next_target(
            list_page, pending, handled_tokens, today_only)

        for token, req_date_text in skipped:
            if token in skip_logged_tokens:
                continue
            skip_logged_tokens.add(token)
            print(f"  [skip] token {token or '?'} -- Req. Date "
                  f"{req_date_text or '(unreadable)'} is not today; "
                  "leaving it pending for now.")
            utils.log_result(token, "", "", "", "skipped_old_request",
                             notes=f"Req. Date {req_date_text!r} is not "
                                   "today")

        if idx is None:
            if pending == 0:
                print("\nNo more pending requests found. Done.")
                if list_page.count_edit_icons() > 0:
                    print(
                        "  NOTE: the list still has rows with edit icons, but "
                        "none were recognized as Pending. The Status cell text "
                        f"probably doesn't match config.PENDING_STATUS_OPTION "
                        f"({config.PENDING_STATUS_OPTION!r}). Run "
                        "quickcap.sh --debug-selectors, or right-click a Pending row's "
                        "Status cell -> Inspect, and compare its exact text.")
                break

            if today_only:
                # Every remaining pending row failed the same-day check
                # (handled ones are excluded from `skipped` by
                # _find_next_target) -- offer to keep going into them
                # instead of just stopping here.
                remaining = {t for t, _ in skipped}
                choice = prompt_for_older_batch_choice(len(remaining))
                if choice == "no":
                    print("Done. Older pending requests were left untouched.")
                    break

                today_only = False
                if choice == "manual":
                    state.mode = "manual"
                    state.locked_manual = True
                    print("Continuing in MANUAL mode for the remaining "
                          "older pending requests. (No option to switch "
                          "to auto for this batch.)")
                else:  # "auto"
                    state.mode = "auto"
                    older_auto_limit = prompt_for_request_count(
                        "How many older pending requests should be "
                        "processed automatically?")
                    print(f"Continuing in FULLY AUTOMATIC mode for up to "
                          f"{older_auto_limit} older pending request(s).")
                continue

            print("\nNo more pending requests left to handle. Done.")
            break

        summary = list_page.peek_row_summary(idx)
        print(f"\n[{processed + 1}] Pending rows visible: {pending}. "
              f"Row {idx + 1}: {summary}")

        if state.mode != "auto" and not utils.confirm(
                f"Open the next pending request (token "
                f"{token_hint or '?'})?",
                f"Row {idx + 1}: {summary}",
                "YES = open it and fill the form.  NO = stop the run here."):
            print("Stopped: you chose not to open the next request.")
            break

        try:
            list_page.open_request(idx)
            process_request(page, token_hint, state, send_email_enabled)
        except KeyboardInterrupt:
            print("\nInterrupted by user. Exiting.")
            raise
        except Exception as exc:
            print(f"\n!! Unexpected error: {exc}")
            traceback.print_exc()
            utils.log_result(token_hint, "", "", "", "error", notes=str(exc))
            utils.manual_pause(
                "Unexpected error - check the browser",
                f"Error: {exc}",
                "In the browser: fix or finish this request if needed. The "
                "script then goes back to the list and continues.")
        finally:
            utils.set_current_request("")

        if token_hint:
            handled_tokens.add(token_hint)
        processed += 1
        if older_auto_limit is not None:
            older_auto_processed += 1

        # Resume: go back to the list and re-filter for the next pending
        # request. (After Save & Next, some QuickCap versions already show
        # the next request -- in that case this simply re-syncs the list.)
        return_to_list(page, list_page, start_url)
        list_page.filter_pending_and_search()


def main() -> None:
    """CLI entry point: parse args, pick a mode, drive the browser."""
    args = parse_args()
    # --debug-selectors only reads the page, so the mode never matters.
    mode = args.mode or ("manual" if args.debug_selectors
                         else prompt_for_mode())

    print("=" * 70)
    print("QuickCap Request-To-Login automation")
    print(f"  mode          : {MODE_LABELS[mode]}")
    print(f"  send email    : {'ENABLED (still confirms each time)' if args.send_email else 'disabled'}")
    print(f"  chrome        : {args.chrome}")
    use_current_page = should_use_current_page(args.start_page)
    print(f"  start page    : {args.start_page}"
          + (" (existing tab)" if use_current_page else " (new tab)"))
    print("  Safeguards    : no login/MFA/CAPTCHA automation, UI only,")
    print("                  no backend requests, no stored credentials,")
    print("                  only today's Req. Date requests are touched.")
    print("=" * 70)

    with sync_playwright() as pw:
        page, closable = get_page(pw, args.chrome, use_current_page)
        page.set_default_timeout(config.DEFAULT_TIMEOUT_MS)
        try:
            run(page, mode, args.send_email,
                args.debug_selectors, args.max_requests, use_current_page)
        finally:
            if closable is None:
                # connect mode: only disconnect; Chrome stays open so the
                # next run just opens a new tab in it.
                print("Chrome stays open -- the next run reuses it.")
            else:
                try:
                    closable.close()
                except Exception:
                    pass


if __name__ == "__main__":
    main()
QUICKCAP_EOF_MAIN_PY

# ---- selftest.py -------------------------------------------------
cat > "$APP_DIR/selftest.py" <<'QUICKCAP_EOF_SELFTEST_PY'
"""
selftest.py -- offline checks run by `quickcap.sh --self-test`.
Contacts no website and changes nothing in QuickCap.
"""
import os
import sys
from datetime import date

failures = []


def check(name, condition):
    print(("  PASS  " if condition else "  FAIL  ") + name)
    if not condition:
        failures.append(name)


print("Self-test: importing modules...")
import config          # noqa: E402
import utils           # noqa: E402
import quickcap_pages  # noqa: E402
import main            # noqa: E402
check("all modules import", True)

print("Self-test: settings from quickcap.sh...")
check("QuickCap URL set: " + (config.QUICKCAP_REQUEST_LIST_URL or "(empty)"),
      config.QUICKCAP_REQUEST_LIST_URL.startswith(("http://", "https://")))
check("list-page menu step present",
      hasattr(quickcap_pages.RequestListPage, "open_list_via_menu_if_needed"))

print("Self-test: username rules...")
check("John Smith -> jsmith01",
      utils.generate_username("John", "Smith", []) == "jsmith01")
check("skips taken jsmith01 (case-insensitive)",
      utils.generate_username("John", "Smith", ["JSmith01"]) == "jsmith02")
check("strips punctuation (Mary-Ann O'Neil -> moneil01)",
      utils.generate_username("Mary-Ann", "O'Neil", []) == "moneil01")
check("bump jsmith09 -> jsmith10", utils.bump_username("jsmith09") == "jsmith10")
check("bump without digits -> abc01", utils.bump_username("abc") == "abc01")
check("email match ignores case/space",
      utils.emails_match(" A@b.com", "a@B.com "))

print("Self-test: same-day guard...")
today = date.today()
check("today (MM-DD-YYYY) is today", utils.is_today(today.strftime("%m-%d-%Y")))
check("today (MM/DD/YYYY) is today", utils.is_today(today.strftime("%m/%d/%Y")))
check("01-01-2000 is not today", not utils.is_today("01-01-2000"))
check("blank date is not today", not utils.is_today(""))
check("token parsed from row text",
      main._extract_token("\u270e | 20260728-3467 | x") == "20260728-3467")
check("xpath literal with apostrophe",
      utils._xpath_literal("it's") == '"it\'s"')

print("Self-test: nothing is recorded...")
before = set(os.listdir(config.BASE_DIR))
utils.log_result("T-1", "Test User", "t@example.com", "Org", "selftest")
after = set(os.listdir(config.BASE_DIR))
check("log_result writes no files", before == after)
check("no LOGS_DIR / log path in config or utils",
      not hasattr(config, "LOGS_DIR") and not hasattr(utils, "get_log_path"))

print("Self-test: command line...")
sys.argv = ["main.py", "--mode", "assisted", "--max-requests", "2",
            "--chrome", "connect", "--start-page", "auto"]
args = main.parse_args()
check("arguments parse", args.mode == "assisted" and args.max_requests == 2)

print("Self-test: Playwright driver...")
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        check("Playwright driver starts", pw.chromium.name == "chromium")
except Exception as exc:  # pragma: no cover
    check(f"Playwright driver starts ({exc})", False)

print()
if failures:
    print(f"SELF-TEST FAILED: {len(failures)} check(s) failed.")
    sys.exit(1)
print("SELF-TEST PASSED.")
QUICKCAP_EOF_SELFTEST_PY
}

# =============================================================================
# 4. RUN
# =============================================================================

SETUP_ONLY=0
SELF_TEST=0
REINSTALL=0
START_PAGE="auto"
PY_ARGS=()

# Options this script handles itself, or passes on to the Python code (which
# validates their values).
while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --setup-only) SETUP_ONLY=1 ;;
        --self-test) SELF_TEST=1 ;;
        --reinstall) REINSTALL=1 ;;
        --send-email|--debug-selectors) PY_ARGS+=("$1") ;;
        --mode|--chrome|--start-page|--max-requests)
            [ $# -ge 2 ] || die "$1 needs a value (see --help)."
            if [ "$1" = "--start-page" ]; then START_PAGE="$2"; fi
            PY_ARGS+=("$1" "$2")
            shift ;;
        --mode=*|--chrome=*|--max-requests=*) PY_ARGS+=("$1") ;;
        --start-page=*) START_PAGE="${1#*=}"; PY_ARGS+=("$1") ;;
        *) die "Unknown option: $1 (see --help)." ;;
    esac
    shift
done

echo ""
printf '\033[32m%s\033[0m\n' "QuickCap Request-To-Login automation (single-file macOS edition)"
echo "Folder: $SCRIPT_DIR"
echo ""

# --- Settings -----------------------------------------------------------------
[ -n "$CHROME_PROFILE_DIR" ] || CHROME_PROFILE_DIR="$SCRIPT_DIR/chrome-profile"
case "$DEFAULT_TIMEOUT_MS" in
    ''|*[!0-9]*) die "DEFAULT_TIMEOUT_MS must be a whole number of milliseconds (got '$DEFAULT_TIMEOUT_MS')." ;;
esac
if [ "$START_PAGE" != "current" ]; then
    case "$QUICKCAP_REQUEST_LIST_URL" in
        http://*|https://*) ;;
        *) die "QUICKCAP_REQUEST_LIST_URL in the SETTINGS block must be a web address (http:// or https://)." ;;
    esac
fi

# Hand the settings to Python through environment variables (this process
# only -- nothing is written to disk or to your shell profile).
export QUICKCAP_URL QUICKCAP_REQUEST_LIST_URL CHROME_DEBUG_URL \
       CHROME_PROFILE_DIR CHROME_PATH DEFAULT_TIMEOUT_MS
export PYTHONDONTWRITEBYTECODE=1   # leave no __pycache__ behind
export PYTHONUTF8=1

# --- Dependencies ---------------------------------------------------------------
init_python_env
write_python_sources

if [ "$SELF_TEST" = 1 ]; then
    step "Running offline self-test (no website is contacted)..."
    exec "$VENV_PY" -u "$APP_DIR/selftest.py"
fi

check_chrome

if [ "$SETUP_ONLY" = 1 ]; then
    step "Setup complete. Run the script again without --setup-only to start."
    exit 0
fi

step "Starting the automation (Ctrl+C to stop at any time)..."
exec "$VENV_PY" -u "$APP_DIR/main.py" ${PY_ARGS[@]+"${PY_ARGS[@]}"}
