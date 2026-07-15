"""
main.py
-------
QuickCap "Request To Login" automation — entry point.

WHAT THIS SCRIPT DOES
  - Filters the request list to Status=Pending, opens each request via the
    edit icon, checks whether the email already exists in the Organization
    User Details table, and either approves (with a generated username) or
    rejects with a note. Everything is logged to CSV with screenshots.

WHAT THIS SCRIPT NEVER DOES
  - It never logs in for you, never touches MFA/CAPTCHA, never calls backend
    APIs, and never sends emails unless you pass --send-email AND confirm.
  - Default mode is DRY RUN: fields are filled but Save is NOT clicked
    unless you confirm at the prompt.

MODES
  python main.py --mode demo              -> 3 bundled static HTML pages
  python main.py --mode local             -> local carbon-copy dashboard
                                              (run_webapp.py); always confirms
                                              before Save, no commit variant
  python main.py --mode dry-run           -> real pages, no saves w/o confirm
  python main.py --mode commit            -> real saves
  python main.py --mode commit --send-email
  python main.py --debug-selectors        -> print page elements, then exit

RECOMMENDED ORDER while validating against the real system for the first
time: demo -> local (import samples, watch the CSV/screenshots match what
you'd expect) -> --debug-selectors on the real pages -> dry-run on the real
pages -> commit.

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

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="QuickCap 'Request To Login' UI automation (safe, "
                    "UI-only, dry-run by default).")
    parser.add_argument(
        "--mode", choices=["dry-run", "commit", "demo", "local"],
        default="dry-run",
        help="dry-run (default): fill fields but confirm before any Save "
             "on the real QuickCap system. commit: actually save on the "
             "real system. demo: run against 3 bundled static HTML pages "
             "— no server, no real system touched. local: run against the "
             "local carbon-copy dashboard (python run_webapp.py) — always "
             "confirms before Save, same as dry-run; there is no 'local "
             "commit', by design, until the local model is proven "
             "accurate.")
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
             "launch/demo navigates to the configured URL. current: start "
             "from the tab that is already open. goto: navigate to "
             "QUICKCAP_REQUEST_LIST_URL first.")
    parser.add_argument(
        "--debug-selectors", action="store_true",
        help="Open the list page, print all inputs/selects/buttons, and "
             "pause so you can navigate and dump other pages too.")
    parser.add_argument(
        "--max-requests", type=int, default=0,
        help="Stop after N requests (0 = process all pending).")
    return parser.parse_args()


# ===========================================================================
# Chrome connection (Option A: launch, Option B: connect)
# ===========================================================================

def get_page(pw, chrome_mode: str, mode: str) -> tuple[Page, object]:
    """
    Returns (page, closable) where closable is the context/browser we should
    close on exit. In 'connect' mode we deliberately do NOT close the user's
    own Chrome — we only disconnect.
    """
    use_bundled_chromium = mode in ("demo", "local")
    if use_bundled_chromium or chrome_mode == "launch":
        # Option A — persistent profile. demo/local modes use Playwright's
        # bundled Chromium so they work even without Chrome installed.
        context: BrowserContext = pw.chromium.launch_persistent_context(
            user_data_dir=config.CHROME_PROFILE_DIR,
            channel=None if use_bundled_chromium else "chrome",
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

def process_request(page: Page, token_hint: str, mode: str,
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
        handle_duplicate(page, detail, d, mode, send_email_enabled)
    else:
        handle_new_user(page, detail, d, mode)


def handle_duplicate(page: Page, detail: RequestDetailPage,
                     d, mode: str, send_email_enabled: bool) -> None:
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

    if mode in ("dry-run", "demo", "local"):
        if not utils.confirm(f"DRY RUN: set status '{chosen}' + note. "
                             f"Click Save for token {d.token_number}?"):
            utils.log_result(d.token_number, d.full_name, d.email,
                             d.organization_name, "dry_run_rejected",
                             notes="Fields filled; save skipped (dry run)")
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
                    d, mode: str) -> None:
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

    utils.take_screenshot(page, d.token_number, "before_save")

    if mode in ("dry-run", "demo", "local"):
        if not utils.confirm(f"DRY RUN: status Approved, username "
                             f"'{username}'. Click Save & Next for token "
                             f"{d.token_number}?"):
            utils.log_result(d.token_number, d.full_name, d.email,
                             d.organization_name, "dry_run_approved",
                             generated_username=username,
                             notes="Fields filled; save skipped (dry run)")
            return

    if not detail.click_save():
        utils.manual_pause("Save & Next button not found. Save manually, "
                           "then")
    utils.take_screenshot(page, d.token_number, "after_save")

    utils.log_result(d.token_number, d.full_name, d.email,
                     d.organization_name, action,
                     generated_username=username)


# ===========================================================================
# Main loop
# ===========================================================================

def should_use_current_page(chrome_mode: str, start_page: str) -> bool:
    if start_page == "current":
        return True
    if start_page == "goto":
        return False
    return chrome_mode == "connect"


def return_to_list(page: Page, list_page: RequestListPage,
                   mode: str, start_url: str) -> None:
    if mode == "demo":
        page.goto((config.DEMO_DIR / "list.html").resolve().as_uri())
    elif mode == "local":
        page.goto(config.LOCAL_WEBAPP_REQUEST_LIST_URL)
    elif start_url:
        page.goto(start_url, timeout=config.DEFAULT_TIMEOUT_MS * 2)
        page.wait_for_load_state("domcontentloaded")
        list_page.ensure_logged_in()
    else:
        list_page.goto()
        list_page.ensure_logged_in()


def run(page: Page, mode: str, send_email_enabled: bool,
        debug_selectors: bool, max_requests: int,
        use_current_page: bool) -> None:
    list_page = RequestListPage(page)
    start_url = ""

    if mode == "demo":
        demo_url = (config.DEMO_DIR / "list.html").resolve().as_uri()
        print(f"\nDEMO MODE — loading local sample pages ({demo_url}).")
        print("Nothing outside these local HTML files is touched.\n")
        page.goto(demo_url)
    elif mode == "local":
        local_url = config.LOCAL_WEBAPP_REQUEST_LIST_URL
        print(f"\nLOCAL MODE — loading the local carbon-copy dashboard "
              f"({local_url}).")
        print("Nothing outside your own machine is touched. This mode "
              "always confirms before Save (same as dry-run).\n")
        if not utils.url_is_reachable(config.LOCAL_WEBAPP_URL):
            print(f"Could not reach {config.LOCAL_WEBAPP_URL}.\n"
                  "Start the local dashboard first, in another terminal:\n"
                  "  python run_webapp.py\n"
                  "Then re-run this command.")
            sys.exit(1)
        page.goto(local_url)
    else:
        if use_current_page:
            start_url = page.url if page.url != "about:blank" else ""
            print("\nUsing the existing Chrome tab.")
            print(f"Current page: {start_url or '(blank tab)'}")
            page.wait_for_load_state("domcontentloaded")
            list_page.ensure_logged_in()
            start_url = page.url if page.url != "about:blank" else start_url
        elif not config.QUICKCAP_REQUEST_LIST_URL:
            print("QUICKCAP_REQUEST_LIST_URL is not set in .env.\n"
                  "Tip: try the demo first:  python main.py --mode demo")
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

    # In commit mode a saved request leaves the pending list, so we always
    # open row 0. In dry-run/demo, skipped saves mean the same rows stay in
    # the list — so we advance through rows by index instead.
    non_persisting = mode in ("dry-run", "demo", "local")
    processed = 0
    row_index = 0

    while True:
        pending = list_page.count_pending_rows()
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
        if max_requests and processed >= max_requests:
            print(f"\nReached --max-requests={max_requests}. Stopping.")
            break

        idx = row_index if non_persisting else 0
        if idx >= pending:
            print("\nOne full pass over the visible pending rows is "
                  "complete. Nothing was permanently changed."
                  + ("" if mode == "demo" else
                     " Re-run with --mode commit when the fills look "
                     "correct."))
            break

        summary = list_page.peek_row_summary(idx)
        print(f"\n[{processed + 1}] Pending rows visible: {pending}. "
              f"Row {idx + 1}: {summary}")

        # Grab the token from the row before we leave the list page
        # (cell 0 is the edit icon, cell 1 is Token No.).
        token_hint = ""
        if summary:
            parts = [p.strip() for p in summary.split("|")]
            token_hint = parts[1] if len(parts) > 1 else parts[0]

        if mode != "commit" and not utils.confirm(
                f"Open row {idx + 1} (token {token_hint or '?'})?"):
            print("Skipped — not opened.")
            break

        try:
            list_page.open_request(idx)
            process_request(page, token_hint, mode, send_email_enabled)
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

        processed += 1
        row_index += 1

        # Resume: go back to the list and re-filter for the next pending
        # request. (After Save & Next, some QuickCap versions already show
        # the next request — in that case this simply re-syncs the list.)
        return_to_list(page, list_page, mode, start_url)
        list_page.filter_pending_and_search()


def main() -> None:
    args = parse_args()

    print("=" * 70)
    print("QuickCap Request-To-Login automation")
    print(f"  mode          : {args.mode.upper()}"
          + ("  (no saves without confirmation)"
             if args.mode in ("dry-run", "local") else ""))
    print(f"  send email    : {'ENABLED (still confirms each time)' if args.send_email else 'disabled'}")
    print(f"  chrome        : {args.chrome}")
    use_current_page = should_use_current_page(args.chrome, args.start_page)
    print(f"  start page    : {args.start_page}"
          + (" (existing tab)"
             if use_current_page and args.mode not in ("demo", "local")
             else ""))
    print("  Safeguards    : no login/MFA/CAPTCHA automation, UI only,")
    print("                  no backend requests, no stored credentials.")
    print("=" * 70)

    with sync_playwright() as pw:
        page, closable = get_page(pw, args.chrome, mode=args.mode)
        page.set_default_timeout(config.DEFAULT_TIMEOUT_MS)
        try:
            run(page, args.mode, args.send_email,
                args.debug_selectors, args.max_requests, use_current_page)
        finally:
            log = utils.get_log_path()
            if log.exists():
                print(f"\nLog file: {log}")
            print(f"Screenshots: {config.SCREENSHOTS_DIR}")
            if args.chrome == "connect" and args.mode not in ("demo", "local"):
                # Only disconnect; never close the user's own Chrome.
                pass
            else:
                try:
                    closable.close()
                except Exception:
                    pass


if __name__ == "__main__":
    main()
