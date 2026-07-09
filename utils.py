"""
utils.py
--------
Reusable helper functions:

- DOM helpers that tolerate old table-based HTML (find input by nearby label,
  select dropdown option by visible text, read a table under a section title,
  click a button by its visible text).
- Username generation and normalization (jsmith01, jsmith02, ...).
- CSV logging of every processed request.
- Screenshots and manual-pause helpers.
- Selector debug dump (prints inputs, selects, buttons found on the page).

All DOM helpers take a Playwright `page` (or frame) as the first argument.
None of them assume exact selectors — they search by visible text, so they
survive minor HTML changes. If something is not found, they return None and
the caller decides whether to pause for manual review.
"""

from __future__ import annotations

import csv
import re
import string
from datetime import datetime
from pathlib import Path
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


def emails_match(email_a: str, email_b: str) -> bool:
    """Exact, case-insensitive email comparison."""
    return email_a.strip().lower() == email_b.strip().lower()


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


def click_button_by_text(page: Page, button_text: str,
                         timeout_ms: int = 5000) -> bool:
    """
    Click a button/link/input whose visible text (or value) matches.
    Returns True if something was clicked.
    """
    lit = _xpath_literal(button_text)
    candidates = [
        page.get_by_role("button", name=button_text, exact=False),
        page.get_by_role("link", name=button_text, exact=False),
        page.locator(f"xpath=//input[@type='button' or @type='submit']"
                     f"[contains(@value, {lit})]"),
        page.locator(f"xpath=//button[contains(normalize-space(.), {lit})]"),
        page.locator(f"xpath=//a[contains(normalize-space(.), {lit})]"),
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
    Run `python main.py --debug-selectors` on any QuickCap page, then use the
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
# 4. Logging, screenshots, pauses
# ===========================================================================

LOG_FIELDS = [
    "timestamp", "token_number", "full_name", "email",
    "organization_name", "action", "generated_username", "notes",
]


def get_log_path() -> Path:
    """One CSV log file per day, e.g. logs/run_2026-07-09.csv."""
    return config.LOGS_DIR / f"run_{datetime.now():%Y-%m-%d}.csv"


def log_result(token_number: str, full_name: str, email: str,
               organization_name: str, action: str,
               generated_username: str = "", notes: str = "") -> None:
    """
    Append one row to today's CSV log.
    `action` should be one of: approved / rejected / manual_review / error
    (plus dry_run_ prefixed variants).
    """
    path = get_log_path()
    is_new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "token_number": token_number,
            "full_name": full_name,
            "email": email,
            "organization_name": organization_name,
            "action": action,
            "generated_username": generated_username,
            "notes": notes,
        })
    print(f"  [log] {action}: token={token_number} -> {path.name}")


def take_screenshot(page: Page, token_number: str, label: str) -> Path:
    """Save a full-page screenshot, e.g. screenshots/TK1001_before_save_143210.png."""
    safe_token = re.sub(r"[^A-Za-z0-9_-]", "_", token_number or "unknown")
    name = f"{safe_token}_{label}_{datetime.now():%H%M%S}.png"
    path = config.SCREENSHOTS_DIR / name
    try:
        page.screenshot(path=str(path), full_page=True)
        print(f"  [screenshot] {path.name}")
    except Exception as exc:  # Never let a screenshot failure stop the run.
        print(f"  [screenshot] FAILED: {exc}")
    return path


def manual_pause(message: str = "Manual review needed.") -> None:
    """Block until the user presses Enter. Used for anything unexpected."""
    input(f"\n>>> {message} Press Enter to continue... ")


def confirm(prompt: str) -> bool:
    """Ask a yes/no question. Only 'y' or 'yes' returns True."""
    answer = input(f"\n>>> {prompt} [y/N]: ").strip().lower()
    return answer in ("y", "yes")
