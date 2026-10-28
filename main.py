"""
main.py
-------
QuickCap "Request To Login" automation — entry point.

WHAT THIS SCRIPT DOES
  - Filters the request list to Status=Pending, opens each request via the
    edit icon, checks whether the email already exists in the Organization
    User Details table, and either approves (with a generated username) or
    rejects with a note. Everything is logged to CSV (no screenshots).
  - Only ever acts on a request whose Req. Date is TODAY — anything older
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
  python main.py --debug-selectors        -> print page elements, then exit

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
    """CHROME_PATH from .env, else Chrome's usual install locations."""
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
        print("\nCouldn't find chrome.exe. Set CHROME_PATH in .env to its "
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
        print("    (No note field found — add the note manually if needed.)")

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
        print("    (No username field found — enter it manually if needed.)")
    detail.confirm_name_fields(d)

    if not detail.fill_approval_name(d.full_name):
        print("    (No approval 'Name' field found — enter the requester's "
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
    # (the top "*Name of the Organization" field) — the two can differ in
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
        print(f"    Save did not advance — likely a username collision "
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
    the view — the server session can keep showing whatever sub-view (e.g.
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
        start_url = page.url if page.url != "about:blank" else start_url
    elif not config.QUICKCAP_REQUEST_LIST_URL:
        print("QUICKCAP_REQUEST_LIST_URL is not set in .env.")
        sys.exit(1)
    else:
        list_page.goto()
        list_page.ensure_logged_in()
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
            print(f"  [skip] token {token or '?'} — Req. Date "
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
                        "--debug-selectors, or right-click a Pending row's "
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
        # the next request — in that case this simply re-syncs the list.)
        return_to_list(page, list_page, start_url)
        list_page.filter_pending_and_search()


def main() -> None:
    """CLI entry point: parse args, pick a mode, drive the browser."""
    args = parse_args()
    mode = args.mode or prompt_for_mode()

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
            log = utils.get_log_path()
            if log.exists():
                print(f"\nLog file: {log}")
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
