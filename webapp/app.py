"""
webapp/app.py
-------------
Flask app for the local QuickCap "Request To Login" carbon-copy dashboard.

This is NOT the real QuickCap system. It is a local, fake stand-in used to
(a) let a human visually verify the automation's field-filling logic, and
(b) give the Playwright automation (main.py --mode local) a safe target
that reproduces the parts of the real UI the automation depends on: the
pending list, the edit form, the Organization Details / Organization User
Details tables, and the Organization search popup for multi-org Tax IDs.

Run with:  python run_webapp.py
"""

from __future__ import annotations

from flask import Flask, abort, redirect, render_template, request, url_for

from webapp import store

STATUS_OPTIONS = ["Pending", "Approved", "Rejected"]
ROLE_OPTIONS = ["Vendor", "Provider", "Admin"]


def create_app() -> Flask:
    app = Flask(__name__)

    # -- list page ----------------------------------------------------------

    @app.get("/")
    def index():
        return redirect(url_for("list_requests"))

    @app.get("/requests")
    def list_requests():
        filters = {
            "token_no": request.args.get("token_no", ""),
            "full_name": request.args.get("full_name", ""),
            "address": request.args.get("address", ""),
            "phone": request.args.get("phone", ""),
            "city": request.args.get("city", ""),
            "state": request.args.get("state", ""),
            "email": request.args.get("email", ""),
            "status": request.args.get("status", "Pending"),
            "followup_from": request.args.get("followup_from", ""),
            "followup_to": request.args.get("followup_to", ""),
            "keyword": request.args.get("keyword", ""),
        }
        try:
            page = int(request.args.get("page", 1))
        except ValueError:
            page = 1
        try:
            show = int(request.args.get("show", 20) or 20)
        except ValueError:
            show = 20

        rows, total, total_pages, page = store.filter_requests(filters, page, show)
        total_all = len(store.get_requests())
        return render_template(
            "list.html",
            rows=rows, filters=filters, status_options=["All"] + STATUS_OPTIONS,
            page=page, show=show, total=total, total_pages=total_pages,
            total_all=total_all,
        )

    # -- detail / edit page ---------------------------------------------------

    @app.route("/requests/<token>/edit", methods=["GET", "POST"])
    def edit_request(token):
        req = store.get_request(token)
        if req is None:
            abort(404, f"No request with token {token!r} in the local sandbox.")

        if request.method == "POST":
            updates = {f: request.form.get(f, "") for f in store.REQUEST_FIELDS
                       if f != "create_virtual_group"}
            updates["create_virtual_group"] = request.form.get("create_virtual_group") == "on"
            if updates.get("status") == "Approved" and not req.get("approved_date"):
                import datetime
                updates["approved_date"] = datetime.date.today().strftime("%m-%d-%Y")
            store.save_request(token, updates)

            action = request.form.get("action", "save_next")
            if action == "save_next":
                return redirect(url_for("list_requests"))
            if action in ("save_prev", "save_stay"):
                return redirect(url_for("edit_request", token=token))
            return redirect(url_for("list_requests"))

        orgs = store.organizations_for_tax_id(req.get("organization_tax_id", ""))
        org_users = store.org_users_for_tax_id(req.get("organization_tax_id", ""))
        distinct_org_ids = {o["org_id"] for o in orgs}
        needs_org_pick = bool(not req.get("organization_id") and len(distinct_org_ids) > 1)

        # Prev/Next among all tokens currently in the sandbox, ascending.
        all_tokens = sorted(r["token_no"] for r in store.get_requests())
        idx = all_tokens.index(token) if token in all_tokens else -1
        prev_token = all_tokens[idx - 1] if idx > 0 else None
        next_token = (all_tokens[idx + 1]
                      if 0 <= idx < len(all_tokens) - 1 else None)

        return render_template(
            "detail.html",
            req=req, orgs=orgs, org_users=org_users,
            needs_org_pick=needs_org_pick,
            status_options=STATUS_OPTIONS, role_options=ROLE_OPTIONS,
            prev_token=prev_token, next_token=next_token,
        )

    # -- popups ---------------------------------------------------------------

    @app.get("/popup/organizations")
    def popup_organizations():
        token = request.args.get("token", "")
        name_q = request.args.get("name", "")
        tax_q = request.args.get("tax_id", "")
        req = store.get_request(token)
        tax_id = req.get("organization_tax_id", "") if req else ""
        results = store.search_organizations(tax_id, name_q, tax_q)
        return render_template(
            "org_popup.html", token=token, name_q=name_q, tax_q=tax_q,
            results=results,
        )

    @app.get("/popup/groups")
    def popup_groups():
        token = request.args.get("token", "")
        name_q = request.args.get("name", "")
        desc_q = request.args.get("description", "")
        results = store.search_groups(name_q, desc_q)
        return render_template(
            "group_popup.html", token=token, name_q=name_q, desc_q=desc_q,
            results=results,
        )

    # -- sandbox admin (used by import_requests.py's --reset and the toolbar) -

    @app.post("/api/reset")
    def api_reset():
        store.reset_sandbox()
        return redirect(url_for("list_requests"))

    return app


app = create_app()

# Run this app via `python run_webapp.py` from the project root (it wires up
# sys.path and reads the port/host from config.py / .env). Running this file
# directly won't find the project's config module.