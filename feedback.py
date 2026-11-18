import hashlib
import hmac
import secrets
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import click
from flask import Blueprint, current_app, make_response, render_template, request

feedback = Blueprint("feedback", __name__)


@contextmanager
def feedback_db():
    path = Path(current_app.config["DATABASE"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY,
                token_hash TEXT NOT NULL UNIQUE,
                order_id INTEGER,
                display_name TEXT NOT NULL DEFAULT '',
                quote TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'invited'
                    CHECK (status IN ('invited', 'pending', 'approved', 'rejected'))
            )
        """)
        yield db


def approved_testimonials():
    if not Path(current_app.config["DATABASE"]).is_file():
        return []
    try:
        with feedback_db() as db:
            return db.execute("""
                SELECT display_name, quote FROM feedback
                WHERE status = 'approved' ORDER BY id DESC
            """).fetchall()
    except (OSError, sqlite3.Error):
        current_app.logger.exception("Could not load testimonials")
        return []


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def feedback_page(status=200, **context):
    response = make_response(render_template("feedback.html", **context), status)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@feedback.route("/feedback/<token>", methods=["GET", "POST"])
def leave(token):
    try:
        with feedback_db() as db:
            invitation = db.execute(
                "SELECT id, order_id, status FROM feedback WHERE token_hash = ?", (token_hash(token),)
            ).fetchone()

            if invitation is None:
                return feedback_page(404, unavailable=True)
            if invitation["status"] != "invited":
                return feedback_page(submitted=True)
            if request.method == "GET":
                return feedback_page()

            name = request.form.get("display_name", "").strip()
            quote = request.form.get("quote", "").strip()
            consent = request.form.get("consent") == "yes"
            if len(name) > 40 or not 1 <= len(quote) <= 500 or not consent:
                return feedback_page(400, name=name, quote=quote, consent=consent,
                                     error="Enter feedback up to 500 characters, a display name up to 40 characters, and give permission to publish.")
            db.execute("""
                UPDATE feedback SET display_name = ?, quote = ?, status = 'pending'
                WHERE id = ? AND status = 'invited'
                  AND NOT EXISTS (
                      SELECT 1 FROM feedback AS existing
                      WHERE existing.order_id = ? AND existing.status IN ('pending', 'approved')
                  )
            """, (name or "Anonymous", quote, invitation["id"], invitation["order_id"]))
        return feedback_page(submitted=True)
    except (OSError, sqlite3.Error):
        current_app.logger.exception("Could not process feedback")
        return feedback_page(503, retry=True)


def latest_order_feedback(db, order_id):
    return db.execute("""
        SELECT id, status FROM feedback WHERE order_id = ?
        ORDER BY CASE status WHEN 'approved' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END,
                 id DESC LIMIT 1
    """, (order_id,)).fetchone()


def order_feedback_status(order_id):
    with feedback_db() as db:
        row = latest_order_feedback(db, order_id)
    return row["status"] if row else None


def get_or_create_order_invitation(order_id):
    with feedback_db() as db:
        db.execute("BEGIN IMMEDIATE")
        latest = latest_order_feedback(db, order_id)
        if latest and latest["status"] in ("pending", "approved"):
            return None

        # A new link becomes available if the previous review was declined.
        previous_review = db.execute(
            "SELECT MAX(id) FROM feedback WHERE order_id = ? AND status = 'rejected'",
            (order_id,),
        ).fetchone()[0]
        key = current_app.secret_key.encode()
        message = f"phet-order-feedback:{order_id}:{previous_review or 0}".encode()
        token = hmac.new(key, message, "sha256").hexdigest()
        db.execute(
            "INSERT OR IGNORE INTO feedback (token_hash, order_id) VALUES (?, ?)",
            (token_hash(token), order_id),
        )
    return token


def create_invitation(order_id):
    token = secrets.token_urlsafe(32)
    with feedback_db() as db:
        db.execute(
            "INSERT INTO feedback (token_hash, order_id) VALUES (?, ?)",
            (token_hash(token), order_id),
        )
    return token


def pending_reviews():
    with feedback_db() as db:
        return db.execute("""
            SELECT id, order_id, display_name, quote FROM feedback
            WHERE status = 'pending' ORDER BY id
        """).fetchall()


def moderate_review(feedback_id, status):
    with feedback_db() as db:
        return db.execute(
            "UPDATE feedback SET status = ? WHERE id = ? AND status = 'pending'",
            (status, feedback_id),
        ).rowcount == 1


@feedback.cli.command("invite")
@click.option("--base-url", required=True, help="The URL customers use to reach your site.")
@click.option("--order-id", type=click.IntRange(min=1), help="An existing order number, if applicable.")
def invite(base_url, order_id):
    """Create a single-use customer feedback link."""
    base_url = base_url.rstrip("/")
    url = urlsplit(base_url)
    if url.scheme not in ("http", "https") or not url.hostname or url.query or url.fragment:
        raise click.ClickException("Provide a site URL such as https://your-site.example.")
    if order_id is not None:
        with feedback_db() as db:
            orders_exist = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'orders'"
            ).fetchone()
            if not orders_exist or not db.execute(
                "SELECT 1 FROM orders WHERE id = ?", (order_id,)
            ).fetchone():
                raise click.ClickException(f"Order #{order_id} was not found.")
    token = create_invitation(order_id)
    click.echo(f"{base_url}/feedback/{token}")


@feedback.cli.command("pending")
def pending():
    """Show customer feedback waiting for approval."""
    rows = pending_reviews()
    if not rows:
        click.echo("No pending feedback.")
    for row in rows:
        order = f" · order #{row['order_id']}" if row["order_id"] else ""
        click.echo(f"#{row['id']}{order} · {row['display_name']!r}\n{row['quote']!r}\n")


@feedback.cli.command("moderate")
@click.argument("feedback_id", type=click.IntRange(min=1))
@click.argument("decision", type=click.Choice(["approve", "reject"]))
def moderate(feedback_id, decision):
    """Approve or reject a pending testimonial by its feedback ID."""
    status = "approved" if decision == "approve" else "rejected"
    if not moderate_review(feedback_id, status):
        raise click.ClickException(f"No pending feedback with ID #{feedback_id}.")
    click.echo(f"Feedback #{feedback_id} {status}.")
