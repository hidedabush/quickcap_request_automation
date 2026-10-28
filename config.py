"""
config.py
---------
Central configuration for the QuickCap "Request To Login" automation.

- Loads NON-SENSITIVE settings from a .env file (URLs, folder paths).
- Never put passwords or credentials in .env or anywhere in this project.
  You log in to QuickCap manually in Chrome; the script only drives the UI.
- Automatically creates the logs/ folder.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Base paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent

# Load .env from the project folder (silently does nothing if missing).
load_dotenv(BASE_DIR / ".env")

# ---------------------------------------------------------------------------
# Non-sensitive settings from .env (see .env.example)
# ---------------------------------------------------------------------------

# Main QuickCap URL (login/home page).
QUICKCAP_URL = os.getenv("QUICKCAP_URL", "").strip()

# Direct URL of the "Request To Login" list page. If your QuickCap does not
# have a stable direct URL, leave this equal to QUICKCAP_URL and navigate
# to the list page manually before running (the script will pause for you).
QUICKCAP_REQUEST_LIST_URL = os.getenv(
    "QUICKCAP_REQUEST_LIST_URL", QUICKCAP_URL
).strip()

# Chrome DevTools debug endpoint. The default "connect" mode attaches here
# and opens a new tab; if nothing is listening, it starts Chrome itself on
# this port (see main.get_page).
CHROME_DEBUG_URL = os.getenv("CHROME_DEBUG_URL", "http://localhost:9222").strip()

# Chrome profile folder (keeps your QuickCap login between runs). Used both
# when "connect" mode has to start Chrome and by the legacy "launch" mode.
CHROME_PROFILE_DIR = os.getenv(
    "CHROME_PROFILE_DIR", str(BASE_DIR / "chrome-profile")
).strip()

# Full path to chrome.exe. Optional — leave unset to auto-detect the usual
# install locations.
CHROME_PATH = os.getenv("CHROME_PATH", "").strip()

# ---------------------------------------------------------------------------
# Project folders (created automatically)
# ---------------------------------------------------------------------------
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Behavior settings
# ---------------------------------------------------------------------------

# Default timeout (milliseconds) for waiting on elements/pages.
DEFAULT_TIMEOUT_MS = int(os.getenv("DEFAULT_TIMEOUT_MS", "15000"))

# The exact text QuickCap uses in the Status dropdown may vary. The script
# tries these, in order, when rejecting a duplicate-email request.
REJECT_STATUS_OPTIONS = ["Rejected", "Denied"]

# Status value used when approving.
APPROVE_STATUS_OPTION = "Approved"

# Status filter value on the list page.
PENDING_STATUS_OPTION = "Pending"

# Note added to duplicate-email requests.
DUPLICATE_EMAIL_NOTE = "Account already exists for this email address."
