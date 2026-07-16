"""
main.py
-------
QuickCap "Request To Login" automation — entry point.

WHAT THIS SCRIPT DOES
  - Filters the request list to Status=Pending, opens each request via the
    edit icon, checks whether the email already exists in the Organization
    User Details table, and either approves (with a generated username) or
    rejects with a note. Everything is logged to CSV with screenshots.
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
  --chrome launch   (Option A) Playwright launches Chrome with a persistent
                    profile folder. Log in once; the session is remembered.
  --chrome connect  (Option B) Attach to a Chrome YOU started with
                    --remote-debugging-port=9222 (see README).

START PAGE OPTIONS
  --start-page auto     connect uses your existing tab; launch navigates
  --start-page current  always use the already-open tab
  --start-page goto     navigate to QUICKCAP_REQUEST_LIST_URL first
"""

from __future__ import annotations

import argparse
import sys
import traceback
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
        "--chrome", choices=["launch", "connect"], default="launch",
        help="launch: Playwright opens Chrome with a persistent profile "
             "(Option A). connect: attach to your already-running Chrome "
             "on the DevTools port (Option B).")
    parser.add_argument(
        "--start-page", choices=["auto", "current", "goto"], default="auto",
        help="auto (default): connect mode uses the existing Chrome tab; "
             "launch navigates to the configured URL. current: start from "
             "the tab that is already open. goto: navigate to "
             "QUICKCAP_REQUEST_LIST_URL first.")
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
    """

    def __init__(self, mode: str):
        self.mode = mode


def offer_switch_to_auto(state: ModeState) -> None:
    """
    In manual mode, let the user upgrade to fully-automatic for the rest
    of the run instead of clicking Save themselves for every request.
    Only called from the manual branch, so this never fires in
    assisted/auto. Mutates `state.mode` in place -- callers re-check
    `state.mode` immediately after to decide whether to still treat this
    request as manual (return) or fall through to the auto save path.
    """
    answer = input(
        "\n>>> Fields filled. Press Enter once you've clicked Save "
        "yourself, or type 'a' to switch to FULLY AUTOMATIC for the rest "
        "of this run: ").strip().lower()
    if answer == "a":
        state.mode = "auto"
        print("    Switched to FULLY AUTOMATIC for the rest of this run.")


def prompt_for_mode() -> str:
    """
    Ask which of the three modes to run in. Only called when --mode wasn't
    passed on the command line, so scripted/CI invocations can still pass
    --mode explicitly and skip this prompt entirely.
    """
    print("\nChoose a mode:")
    print("  1) Manual autofill   - fill fields only; you click Save yourself")
    print("  2) Auto (confirm)    - fills and asks y/n before every Save & Next")
    print("  3) Fully automatic   - fills and saves without asking each time")
    choices = {"1": "manual", "2": "assisted", "3": "auto"}
    while True:
        answer = input("Enter 1, 2, or 3: ").strip()
        if answer in choices:
            return choices[answer]
        print("Please enter 1, 2, or 3.")


# ===========================================================================
# Chrome connection (Option A: launch, Option B: connect)
# ===========================================================================

def get_page(pw, chrome_mode: str) -> tuple[Page, object]:
    """
    Returns (page, closable) where closable is the context/browser we should
    close on exit. In 'connect' mode we deliberately do NOT close the user's
    own Chrome — we only disconnect.
    """
    if chrome_mode == "launch":
        # Option A — persistent profile.
        context: BrowserContext = pw.chromium.launch_persistent_context(
            user_data_dir=config.CHROME_PROFILE_DIR,
            channel="chrome",
            headless=False,
            viewport=None,
            args=["--start-maximized"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        return page, context

    # Option B — attach over CDP to Chrome you started yourself.
    print(f"Connecting to Chrome at {config.CHROME_DEBUG_URL} ...")
    try:
        browser: Browser = pw.chromium.connect_over_cdp(
            config.CHROME_DEBUG_URL)
    except Exception as exc:
        print(
            "\nCould not connect to Chrome. Make sure you started it with\n"
            '  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" '
            '--remote-debugging-port=9222 '
            '--user-data-dir="C:\\quickcap-automation-profile"\n'
            f"Details: {exc}")
        sys.exit(1)
    context = (browser.contexts[0] if browser.contexts
               else browser.new_context())
    page = (choose_existing_quickcap_page(context.pages)
            if context.pages else context.new_page())
    return page, browser


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

    if not d.email:
        utils.take_screenshot(page, d.token_number, "error_no_email")
        utils.log_result(d.token_number, d.full_name, d.email,
                         d.organization_name, "error",
                         notes="Email field not found/empty")
        utils.manual_pause("Could not read the Email field. Review the page "
                           "manually, then")
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
        utils.manual_pause("Could not set Status to Rejected/Denied. Please "
                           "set it manually, then")
        chosen = "Rejected (manual)"
    if not detail.fill_note(config.DUPLICATE_EMAIL_NOTE):
        print("    (No note field found — add the note manually if needed.)")

    utils.take_screenshot(page, d.token_number, "before_save")

    if state.mode == "manual":
        offer_switch_to_auto(state)
        if state.mode != "auto":
            utils.log_result(d.token_number, d.full_name, d.email,
                             d.organization_name, "manual_filled_reject",
                             notes="Fields filled; save left to the user")
            return
        # else: just switched to auto -- fall through to the save below.

    if state.mode == "assisted":
        if not utils.confirm(f"Set status '{chosen}' + note. Click Save "
                             f"for token {d.token_number}?"):
            utils.log_result(d.token_number, d.full_name, d.email,
                             d.organization_name, "assisted_declined_reject",
                             notes="Fields filled; save declined")
            return

    if not detail.click_save():
        utils.manual_pause("Save button not found. Save manually, then")
    utils.take_screenshot(page, d.token_number, "after_save")

    # Send-email is opt-in twice: the flag AND a per-request confirmation.
    if detail.has_send_email_button():
        if send_email_enabled and utils.confirm(
                f"Click '{SEND_EMAIL_BUTTON_TEXT}' for {d.email}?"):
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
        utils.manual_pause("Could not set Status to Approved. Set it "
                           "manually, then")

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
                "Could not resolve the organization automatically via the "
                "search popup. Please pick it manually in the browser, then")
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
        if utils.confirm(
                f"An Organization Group search icon was found. Search for "
                f"and select a group matching '{group_query}'?"):
            picked_group = detail.pick_organization_group_via_popup(
                group_query)
            resolved_group = detail.read_organization_group()
            if picked_group and resolved_group:
                print(f"    -> Selected organization group: {picked_group} "
                      f"(Organization Group now {resolved_group!r})")
            else:
                utils.manual_pause(
                    "Could not find a matching organization group "
                    "automatically. Pick it manually in the popup window, "
                    "then")

    utils.take_screenshot(page, d.token_number, "before_save")

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
        if not utils.confirm(f"Status Approved, username '{username}'. "
                             f"Click Save & Next for token "
                             f"{d.token_number}?"):
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
        utils.manual_pause("Save & Next button not found. Save manually, "
                           "then")
    elif not saved:
        utils.manual_pause(
            f"Save still hasn't advanced after {max_username_attempts} "
            f"username attempts. Please resolve manually, then")

    utils.take_screenshot(page, d.token_number, "after_save")

    utils.log_result(d.token_number, d.full_name, d.email,
                     d.organization_name, action,
                     generated_username=username)


# ===========================================================================
# Main loop
# ===========================================================================

def should_use_current_page(chrome_mode: str, start_page: str) -> bool:
    """Whether to resume from the tab already open, vs. navigating fresh."""
    if start_page == "current":
        return True
    if start_page == "goto":
        return False
    return chrome_mode == "connect"


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
    list_page: RequestListPage, pending_count: int, handled_tokens: set[str]
) -> tuple[int | None, str, list[tuple[str, str]]]:
    """
    Scan pending rows from index 0 for the first one whose token isn't
    already in `handled_tokens` and whose Req. Date is today -- the
    same-day guard: a request submitted on any other day is treated as
    permanently out of scope for this run and never opened, only logged
    once. Returns (index, token, skipped), where `skipped` lists every
    (token, req_date_text) pair passed over on the way (including ones
    already logged in an earlier pass -- the caller dedupes against
    `handled_tokens` before logging). `index` is None once every pending
    row has either been handled or found not-today.
    """
    skipped: list[tuple[str, str]] = []
    for i in range(pending_count):
        token = _extract_token(list_page.peek_row_summary(i))
        if token and token in handled_tokens:
            continue
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
        while utils.confirm("Navigate to another page in the browser and "
                            "dump its selectors too?"):
            utils.debug_dump_selectors(page)
        return

    list_page.filter_pending_and_search()

    handled_tokens: set[str] = set()
    processed = 0

    while True:
        if max_requests and processed >= max_requests:
            print(f"\nReached --max-requests={max_requests}. Stopping.")
            break

        pending = list_page.count_pending_rows()
        idx, token_hint, skipped = _find_next_target(
            list_page, pending, handled_tokens)

        for token, req_date_text in skipped:
            if token in handled_tokens:
                continue
            handled_tokens.add(token)
            print(f"  [skip] token {token or '?'} — Req. Date "
                  f"{req_date_text or '(unreadable)'} is not today; "
                  "leaving it pending for a later run.")
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
            else:
                print("\nNo more of TODAY's pending requests found. Older "
                      "pending requests were left untouched by design -- "
                      "re-run the script on their date to process them.")
            break

        summary = list_page.peek_row_summary(idx)
        print(f"\n[{processed + 1}] Pending rows visible: {pending}. "
              f"Row {idx + 1}: {summary}")

        if state.mode != "auto" and not utils.confirm(
                f"Open row {idx + 1} (token {token_hint or '?'})?"):
            print("Skipped — not opened.")
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
            utils.take_screenshot(page, token_hint, "error")
            utils.log_result(token_hint, "", "", "", "error", notes=str(exc))
            utils.manual_pause("Fix the state in the browser if needed, "
                               "then")

        if token_hint:
            handled_tokens.add(token_hint)
        processed += 1

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
    use_current_page = should_use_current_page(args.chrome, args.start_page)
    print(f"  start page    : {args.start_page}"
          + (" (existing tab)" if use_current_page else ""))
    print("  Safeguards    : no login/MFA/CAPTCHA automation, UI only,")
    print("                  no backend requests, no stored credentials,")
    print("                  only today's Req. Date requests are touched.")
    print("=" * 70)

    with sync_playwright() as pw:
        page, closable = get_page(pw, args.chrome)
        page.set_default_timeout(config.DEFAULT_TIMEOUT_MS)
        try:
            run(page, mode, args.send_email,
                args.debug_selectors, args.max_requests, use_current_page)
        finally:
            log = utils.get_log_path()
            if log.exists():
                print(f"\nLog file: {log}")
            print(f"Screenshots: {config.SCREENSHOTS_DIR}")
            if args.chrome == "connect":
                # Only disconnect; never close the user's own Chrome.
                pass
            else:
                try:
                    closable.close()
                except Exception:
                    pass


if __name__ == "__main__":
    main()
