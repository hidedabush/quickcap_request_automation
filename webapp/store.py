"""
webapp/store.py
----------------
Tiny JSON-file "database" behind the local QuickCap carbon-copy dashboard.

Everything here is local, fake, dry-run-only data:
  - organizations.json / org_users.json / groups.json are seed reference
    data (fabricated, not real organizations or people).
  - sandbox_state.json is the mutable "pending queue" that the dashboard
    reads and writes. It starts empty; use import_requests.py to load
    JSON files into it. It is gitignored because it may end up holding
    whatever data you import.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

DATA_DIR = Path(__file__).resolve().parent / "data"
ORGANIZATIONS_PATH = DATA_DIR / "organizations.json"
ORG_USERS_PATH = DATA_DIR / "org_users.json"
GROUPS_PATH = DATA_DIR / "groups.json"
SANDBOX_PATH = DATA_DIR / "sandbox_state.json"

REQUEST_FIELDS = [
    "token_no", "req_date", "title", "first_name", "last_name",
    "organization_tax_id", "organization_id", "organization_name",
    "organization_npi", "office_phone", "cell_no", "date_of_birth", "fax",
    "email", "address", "city", "state", "zip", "external_user_notes",
    "status", "company", "note", "followup_date", "approved_date",
    "user_name", "name", "role", "create_virtual_group", "organization_group",
]


def normalize_tax_id(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(value, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Reference data (organizations / org users / virtual groups)
# ---------------------------------------------------------------------------

def load_organizations() -> list[dict]:
    return _load_json(ORGANIZATIONS_PATH, [])


def load_org_users() -> dict:
    return _load_json(ORG_USERS_PATH, {})


def load_groups() -> list[dict]:
    return _load_json(GROUPS_PATH, [])


def organizations_for_tax_id(tax_id: str) -> list[dict]:
    norm = normalize_tax_id(tax_id)
    if not norm:
        return []
    return [o for o in load_organizations()
            if normalize_tax_id(o.get("tax_id", "")) == norm]


def org_users_for_tax_id(tax_id: str) -> list[dict]:
    return load_org_users().get(normalize_tax_id(tax_id), [])


def search_organizations(tax_id: str, name_query: str = "",
                          tax_id_query: str = "") -> list[dict]:
    """Used by the Organization search popup. Scoped to the request's own
    Tax ID (that's the whole point of the popup: picking among candidates
    that share one Tax ID), further filtered by name / tax id text."""
    candidates = organizations_for_tax_id(tax_id) if tax_id else load_organizations()
    nq = (name_query or "").strip().lower()
    tq = normalize_tax_id(tax_id_query)
    out = []
    for o in candidates:
        if nq and nq not in o.get("name", "").lower():
            continue
        if tq and tq not in normalize_tax_id(o.get("tax_id", "")):
            continue
        out.append(o)
    return out


def search_groups(name_query: str = "", description_query: str = "") -> list[dict]:
    nq = (name_query or "").strip().lower()
    dq = (description_query or "").strip().lower()
    out = []
    for g in load_groups():
        if nq and nq not in g.get("name", "").lower():
            continue
        if dq and dq not in g.get("description", "").lower():
            continue
        out.append(g)
    return out


# ---------------------------------------------------------------------------
# Sandbox (mutable) request queue
# ---------------------------------------------------------------------------

def _blank_request() -> dict:
    return {field: (False if field == "create_virtual_group" else "")
            for field in REQUEST_FIELDS}


def get_requests() -> list[dict]:
    return _load_json(SANDBOX_PATH, [])


def _save_requests(rows: list[dict]) -> None:
    _save_json(SANDBOX_PATH, rows)


def get_request(token_no: str) -> Optional[dict]:
    for r in get_requests():
        if r.get("token_no") == token_no:
            return r
    return None


def save_request(token_no: str, updates: dict) -> Optional[dict]:
    rows = get_requests()
    for r in rows:
        if r.get("token_no") == token_no:
            r.update(updates)
            _save_requests(rows)
            return r
    return None


def import_requests(records: list[dict], replace: bool = False) -> int:
    """
    Merge (default) or replace the sandbox queue with `records`, keyed by
    token_no. Unknown/extra keys in each record (e.g. "_scenario" notes in
    the sample file) are ignored. Returns the number of records imported.
    """
    existing = [] if replace else get_requests()
    by_token = {r["token_no"]: r for r in existing if r.get("token_no")}
    count = 0
    for rec in records:
        token = str(rec.get("token_no") or "").strip()
        if not token:
            continue
        row = _blank_request()
        row.update(by_token.get(token, {}))
        for field in REQUEST_FIELDS:
            if field in rec:
                row[field] = rec[field]
        row["token_no"] = token
        if not row.get("status"):
            row["status"] = "Pending"
        by_token[token] = row
        count += 1
    _save_requests(list(by_token.values()))
    return count


def reset_sandbox() -> None:
    _save_requests([])


# ---------------------------------------------------------------------------
# Filtering / pagination for the list page
# ---------------------------------------------------------------------------

def filter_requests(filters: dict, page: int = 1, show: int = 20):
    """Returns (page_rows, total, total_pages, page)."""
    rows = get_requests()

    def full_name(r: dict) -> str:
        return f"{r.get('first_name', '')} {r.get('last_name', '')}".strip()

    token = (filters.get("token_no") or "").strip().lower()
    name = (filters.get("full_name") or "").strip().lower()
    address = (filters.get("address") or "").strip().lower()
    phone = (filters.get("phone") or "").strip().lower()
    city = (filters.get("city") or "").strip().lower()
    state = (filters.get("state") or "").strip().lower()
    email = (filters.get("email") or "").strip().lower()
    status = (filters.get("status") or "All").strip()
    keyword = (filters.get("keyword") or "").strip().lower()
    followup_from = (filters.get("followup_from") or "").strip()
    followup_to = (filters.get("followup_to") or "").strip()

    def matches(r: dict) -> bool:
        if token and token not in r.get("token_no", "").lower():
            return False
        if name and name not in full_name(r).lower():
            return False
        if address and address not in r.get("address", "").lower():
            return False
        if phone and phone not in r.get("office_phone", "").lower():
            return False
        if city and city not in r.get("city", "").lower():
            return False
        if state and state not in r.get("state", "").lower():
            return False
        if email and email not in r.get("email", "").lower():
            return False
        if status and status != "All" and r.get("status", "") != status:
            return False
        if followup_from and (r.get("followup_date") or "") < followup_from:
            return False
        if followup_to and (r.get("followup_date") or "") > followup_to:
            return False
        if keyword:
            haystack = " ".join(str(r.get(f, "")) for f in REQUEST_FIELDS).lower()
            if keyword not in haystack:
                return False
        return True

    filtered = [r for r in rows if matches(r)]
    filtered.sort(key=lambda r: r.get("token_no", ""), reverse=True)

    total = len(filtered)
    show = show or 20
    total_pages = max(1, (total + show - 1) // show)
    page = min(max(page, 1), total_pages)
    start = (page - 1) * show
    page_rows = filtered[start:start + show]
    return page_rows, total, total_pages, page