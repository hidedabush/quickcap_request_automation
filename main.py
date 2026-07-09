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
  python main.py                          -> demo is suggested if no URL set
  python main.py --mode demo              -> safe local demo (bundled HTML)
  python main.py --mode dry-run           -> real pages, no saves w/o confirm
  python main.py --mode commit            -> real saves
  python main.py --mode commit --send-email
  python main.py --debug-selectors        -> print page elements, then exit

CHROME OPTIONS
  --chrome launch   (Option A) Playwright launches Chrome with a persistent
                    profile folder. Log in once; the session is remembered.
  --chrome connect  (Option B) Attach to a Chrome YOU started with
                    --remote-debugging-port=9222 (see README).
"""

from __future__ import annotations

import argparse
import sys
import traceback

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
        "--mode", choices=["dry-run", "commit", "demo"], default="dry-run",
        help="dry-run (default): fill fields but confirm before any Save. "
             "commit: actually save. demo: run against bundled local demo "
             "pages — no real system touched.")
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

def get_page(pw, chrome_mode: str, demo: bool) -> tuple[Page, object]:
    """
    Returns (page, closable) where closable is the context/browser we should
    close on exit. In 'connect' mode we deliberately do NOT close the user's
    own Chrome — we only disconnect.
    """
    if demo or chrome_mode == "launch":
        # Option A — persistent profile. In demo mode we use Playwright's
        # bundled Chromium so it works even without Chrome installed.
        context: BrowserContext = pw.chromium.launch_persistent_context(
            user_data_dir=config.CHROME_PROFILE_DIR,
            channel=None if demo else "chrome",   # real Chrome for live runs
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
    page = context.pages[0] if context.pages else context.new_page()
    return page, browser


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

    if mode in ("dry-run", "demo"):
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

    # Organization handling
    if d.organization_count > 1:
        print(f"    Multiple organizations detected "
              f"({d.organization_count}).")
        # TODO: implement the organization-selection popup workflow here
        # after inspecting it with --debug-selectors.
        utils.manual_pause("Please pick the correct organization manually "
                           "in the browser, then")
        action = "approved_after_manual"
    else:
        action = "approved"

    utils.take_screenshot(page, d.token_number, "before_save")

    if mode in ("dry-run", "demo"):
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

def run(page: Page, mode: str, send_email_enabled: bool,
        debug_selectors: bool, max_requests: int) -> None:
    list_page = RequestListPage(page)

    if mode == "demo":
        demo_url = (config.DEMO_DIR / "list.html").resolve().as_uri()
        print(f"\nDEMO MODE — loading local sample pages ({demo_url}).")
        print("Nothing outside these local HTML files is touched.\n")
        page.goto(demo_url)
    else:
        if not config.QUICKCAP_REQUEST_LIST_URL:
            print("QUICKCAP_REQUEST_LIST_URL is not set in .env.\n"
                  "Tip: try the demo first:  python main.py --mode demo")
            sys.exit(1)
        list_page.goto()
        list_page.ensure_logged_in()

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
    non_persisting = mode in ("dry-run", "demo")
    processed = 0
    row_index = 0

    while True:
        pending = list_page.count_pending_rows()
        if pending == 0:
            print("\nNo more pending requests found. Done.")
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
              f"Opening row {idx + 1}: {summary}")

        # Grab the token from the row before we leave the list page
        # (cell 0 is the edit icon, cell 1 is Token No.).
        token_hint = ""
        if summary:
            parts = [p.strip() for p in summary.split("|")]
            token_hint = parts[1] if len(parts) > 1 else parts[0]

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
        if mode == "demo":
            page.goto((config.DEMO_DIR / "list.html").resolve().as_uri())
        else:
            list_page.goto()
            list_page.ensure_logged_in()
        list_page.filter_pending_and_search()


def main() -> None:
    args = parse_args()

    print("=" * 70)
    print("QuickCap Request-To-Login automation")
    print(f"  mode          : {args.mode.upper()}"
          + ("  (no saves without confirmation)" if args.mode == "dry-run"
             else ""))
    print(f"  send email    : {'ENABLED (still confirms each time)' if args.send_email else 'disabled'}")
    print(f"  chrome        : {args.chrome}")
    print("  Safeguards    : no login/MFA/CAPTCHA automation, UI only,")
    print("                  no backend requests, no stored credentials.")
    print("=" * 70)

    with sync_playwright() as pw:
        page, closable = get_page(pw, args.chrome, demo=(args.mode == "demo"))
        page.set_default_timeout(config.DEFAULT_TIMEOUT_MS)
        try:
            run(page, args.mode, args.send_email,
                args.debug_selectors, args.max_requests)
        finally:
            log = utils.get_log_path()
            if log.exists():
                print(f"\nLog file: {log}")
            print(f"Screenshots: {config.SCREENSHOTS_DIR}")
            if args.chrome == "connect" and args.mode != "demo":
                # Only disconnect; never close the user's own Chrome.
                pass
            else:
                try:
                    closable.close()
                except Exception:
                    pass


if __name__ == "__main__":
    main()
