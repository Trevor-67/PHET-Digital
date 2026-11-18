import json
import os
import re
import sqlite3
from contextlib import closing
from datetime import timedelta
from hmac import compare_digest
from pathlib import Path
from secrets import token_urlsafe
from urllib.parse import urlencode, urlsplit

import click
from flask import (
    Blueprint, abort, current_app, redirect, render_template, request, session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from feedback import get_or_create_order_invitation, moderate_review, order_feedback_status, pending_reviews

admin = Blueprint("admin", __name__, url_prefix="/admin")
PAGE_SIZE = 30
ORDER_STATUSES = {
    "new": "New",
    "deposit_confirmed": "Deposit confirmed",
    "in_progress": "In progress",
    "delivered": "Delivered",
    "cancelled": "Cancelled",
}


def configure_admin(app, packages):
    settings_file = Path(app.instance_path) / "admin-config.json"
    app.config.update(
        ADMIN_SETTINGS_FILE=settings_file,
        ADMIN_PACKAGES=packages,
        SESSION_COOKIE_NAME="phet_admin",
        SESSION_COOKIE_PATH="/admin",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=os.getenv("PHET_ADMIN_HTTPS", "0") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
    )
    if settings_file.is_file():
        settings = json.loads(settings_file.read_text(encoding="utf-8"))
        app.secret_key = settings["session_key"]
        app.config["ADMIN_PASSWORD_HASH"] = settings["password_hash"]
    app.register_blueprint(admin)


@admin.cli.command("setup")
def setup():
    """Create the private admin login and print its generated password."""
    path = current_app.config["ADMIN_SETTINGS_FILE"]
    path.parent.mkdir(parents=True, exist_ok=True)
    password = token_urlsafe(24)
    settings = {
        "session_key": token_urlsafe(48),
        "password_hash": generate_password_hash(password),
    }
    try:
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as file:
            json.dump(settings, file)
    except FileExistsError as error:
        raise click.ClickException("Admin is already set up. Your existing login was preserved.") from error
    click.echo(f"Admin password: {password}")
    click.echo("Save it somewhere private, then restart Flask and open /admin.")


@admin.before_request
def protect_orders():
    if not current_app.config.get("ADMIN_PASSWORD_HASH"):
        abort(404)
    if request.endpoint != "admin.login" and not session.get("admin_signed_in"):
        return redirect(url_for("admin.login"), code=303)


@admin.after_request
def protect_cache(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


def csrf_token():
    if "admin_csrf" not in session:
        session["admin_csrf"] = token_urlsafe(32)
    return session["admin_csrf"]


def check_csrf():
    expected = session.get("admin_csrf")
    provided = request.form.get("csrf", "")
    if not expected or not compare_digest(expected.encode(), provided.encode()):
        abort(400)


@admin.route("/login", methods=["GET", "POST"])
def login():
    if session.get("admin_signed_in"):
        return redirect(url_for("admin.orders"))
    if request.method == "POST":
        check_csrf()
        password = request.form.get("password", "")
        if len(password) <= 128 and check_password_hash(current_app.config["ADMIN_PASSWORD_HASH"], password):
            session.clear()
            session.permanent = True
            session["admin_signed_in"] = True
            return redirect(url_for("admin.orders"), code=303)
        return render_template("admin_login.html", csrf=csrf_token(), error="The password was incorrect."), 401
    return render_template("admin_login.html", csrf=csrf_token())


@admin.post("/logout")
def logout():
    check_csrf()
    session.clear()
    return redirect(url_for("admin.login"), code=303)


def read_orders(query, parameters):
    path = Path(current_app.config["DATABASE"])
    if not path.is_file():
        return []
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True)) as db, db:
        db.row_factory = sqlite3.Row
        columns = {row["name"] for row in db.execute("PRAGMA table_info(orders)")}
        if not columns:
            return []
        if "status" not in columns:
            db.execute("BEGIN IMMEDIATE")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(orders)")}
            if "status" not in columns:
                db.execute("ALTER TABLE orders ADD COLUMN status TEXT NOT NULL DEFAULT 'new'")
            db.commit()
        return db.execute(query, parameters).fetchall()


@admin.app_template_filter("package_label")
def package_label(key):
    package = current_app.config["ADMIN_PACKAGES"].get(key)
    return f"{package[0]} ({package[1]})" if package else key


@admin.get("/")
def orders():
    page = request.args.get("page", 1, type=int)
    if not 1 <= page <= 100_000_000:
        abort(404)
    search = request.args.get("q", "").strip()[:80]
    status = request.args.get("status", "")
    if status not in ORDER_STATUSES:
        status = ""
    phone_search = re.sub(r"[ ()+-]", "", search)
    if not phone_search.isdecimal():
        phone_search = search
    elif phone_search.startswith("27") and len(phone_search) == 11:
        phone_search = phone_search[2:]
    elif phone_search.startswith("0") and len(phone_search) == 10:
        phone_search = phone_search[1:]
    rows = read_orders(
        """
        SELECT id, name, package, price_rand, created_at, status FROM orders
        WHERE (? = '' OR status = ?)
          AND (? = '' OR CAST(id AS TEXT) = ? OR instr(lower(name), lower(?)) > 0 OR instr(phone, ?) > 0)
        ORDER BY id DESC LIMIT ? OFFSET ?
        """,
        (status, status, search, search.lstrip("#"), search, phone_search,
         PAGE_SIZE + 1, (page - 1) * PAGE_SIZE),
    )
    return render_template("admin_orders.html", orders=rows[:PAGE_SIZE], page=page,
                           has_next=len(rows) > PAGE_SIZE, csrf=csrf_token(),
                           search=search, status=status, statuses=ORDER_STATUSES)


@admin.get("/orders/<int:order_id>")
def order_details(order_id):
    rows = read_orders("SELECT * FROM orders WHERE id = ?", (order_id,))
    if not rows:
        abort(404)
    return render_template("admin_order.html", order=rows[0], csrf=csrf_token(),
                           feedback_status=order_feedback_status(order_id), statuses=ORDER_STATUSES,
                           customer_chat=customer_whatsapp(rows[0]["phone"], f"Hello, this is PHET-Digital following up on order #{order_id}."))


@admin.post("/orders/<int:order_id>/status")
def update_order_status(order_id):
    check_csrf()
    status = request.form.get("status", "")
    if status not in ORDER_STATUSES:
        abort(400, description="Choose a valid order status.")
    updated = read_orders(
        "UPDATE orders SET status = ? WHERE id = ? RETURNING id",
        (status, order_id),
    )
    if not updated:
        abort(404)
    return redirect(url_for("admin.order_details", order_id=order_id), code=303)


def customer_whatsapp(phone, message):
    number = "27" + phone[1:] if phone.startswith("0") else phone.lstrip("+")
    return f"https://wa.me/{number}?{urlencode({'text': message})}"


@admin.post("/orders/<int:order_id>/feedback")
def request_feedback(order_id):
    check_csrf()
    rows = read_orders("SELECT phone FROM orders WHERE id = ?", (order_id,))
    if not rows:
        abort(404)

    configured_url = os.getenv("PHET_PUBLIC_URL", "").rstrip("/")
    public_url = urlsplit(configured_url)
    if configured_url and (
        public_url.scheme != "https" or not public_url.hostname
        or public_url.username or public_url.query or public_url.fragment
    ):
        abort(503, description="PHET_PUBLIC_URL must be your public HTTPS website address.")

    token = get_or_create_order_invitation(order_id)
    if token is None:
        return redirect(url_for("admin.order_details", order_id=order_id), code=303)
    if configured_url:
        feedback_url = f"{configured_url}/feedback/{token}"
    else:
        scheme = "https" if current_app.config["SESSION_COOKIE_SECURE"] else request.scheme
        feedback_url = url_for("feedback.leave", token=token, _external=True, _scheme=scheme)

    message = (
        "Hello, thank you for choosing PHET-Digital. "
        f"We would appreciate your feedback on order #{order_id}. "
        "If you would like to share a short testimonial, please use this link:\n"
        f"{feedback_url}\n\nKind regards,\nPHET-Digital"
    )
    whatsapp_url = customer_whatsapp(rows[0]["phone"], message)
    local_link = urlsplit(feedback_url).hostname in ("localhost", "127.0.0.1", "::1")
    return render_template("admin_feedback_invite.html", order_id=order_id, feedback_url=feedback_url,
                           whatsapp_url=whatsapp_url, local_link=local_link)


@admin.get("/feedback")
def reviews():
    return render_template("admin_feedback.html", reviews=pending_reviews(), csrf=csrf_token())


@admin.post("/feedback/<int:feedback_id>/<decision>")
def moderate_feedback(feedback_id, decision):
    check_csrf()
    decisions = {"approve": "approved", "reject": "rejected"}
    if decision not in decisions or not moderate_review(feedback_id, decisions[decision]):
        abort(404)
    return redirect(url_for("admin.reviews"), code=303)
