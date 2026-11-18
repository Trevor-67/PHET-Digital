import re
import sqlite3
from os import getenv
from contextlib import closing
from pathlib import Path
from urllib.parse import urlencode

import click
from flask import Flask, redirect, render_template, request

from admin import configure_admin
from feedback import approved_testimonials, feedback

app = Flask(__name__, instance_relative_config=True)
app.config.update(DATABASE=Path(app.instance_path) / "orders.sqlite3", MAX_CONTENT_LENGTH=16_384)

app.register_blueprint(feedback)

WHATSAPP_NUMBER = getenv("WHATSAPP_NUMBER", "27655065477").strip()
if not re.fullmatch(r"[1-9][0-9]{7,14}", WHATSAPP_NUMBER):
    raise ValueError("WHATSAPP_NUMBER must include the country code and use digits only.")
WHATSAPP = f"https://wa.me/{WHATSAPP_NUMBER}"
CV_PROMO_ACTIVE = True
CV_REGULAR_PRICES = {"cv-basic": 100, "cv-premium": 200}
PACKAGES = {
    "cv-basic": ("CV Revamp", "Basic", CV_REGULAR_PRICES["cv-basic"] // (2 if CV_PROMO_ACTIVE else 1), "A revamp of your existing CV."),
    "cv-premium": ("CV Revamp", "Premium", CV_REGULAR_PRICES["cv-premium"] // (2 if CV_PROMO_ACTIVE else 1), "CV revamp, cover letter and LinkedIn profile update guidance."),
    "web-starter": ("Business Website", "Starter", 1500, "A one-page website for your business."),
    "web-business": ("Business Website", "Business", 3500, "A business website with up to five pages."),
    "flyer-design": ("Flyer Design", "Digital flyer", 50, "One digital flyer for a promotion, price list or event, delivered as a shareable image."),
    "web-maintenance": ("Website Maintenance", "One-off", 350, "One small text, image or link update, up to 30 minutes. Extra work is quoted separately."),
    "db-maintenance": ("Database Maintenance", "Health check", 500, "A read-only check for one database. Get a summary of findings and next steps. Fixes are quoted separately."),
    "shop-starter": ("E-commerce Starter", "Starter", 5500, "A product catalogue with WhatsApp ordering."),
}
configure_admin(app, PACKAGES)

SERVICES = [
    {
        "id": "cv-basic",
        "name": "CV Revamp",
        "summary": "Refresh your CV for your next job, internship or graduate programme.",
        "image": "cv-revamp.webp",
        "alt": "A graduate reviewing a printed CV at a desk",
        "delivery": "Ready in 48 hours",
        "packages": ("cv-basic", "cv-premium"),
    },
    {
        "id": "web-starter",
        "name": "Business Website",
        "summary": "Help people find your shop, salon or business and see what you offer.",
        "image": "business-website.webp",
        "alt": "A salon owner working on a laptop that displays a website",
        "delivery": "Ready in 3–5 days",
        "packages": ("web-starter", "web-business"),
    },
    {
        "id": "shop-starter",
        "name": "E-commerce Starter",
        "summary": "Show your products in a catalogue so customers can order on WhatsApp.",
        "image": "ecommerce.webp",
        "alt": "A phone showing a product catalogue beside packaged goods",
        "delivery": "Agree on a delivery date on WhatsApp",
        "packages": ("shop-starter",),
    },
    {
        "id": "flyer-design",
        "name": "Flyer Design",
        "summary": "Get a digital flyer to share on WhatsApp or social media. See the braid promo for an example.",
        "image": "braids-flyer-sample.webp",
        "alt": "Pink Knotless Braids Bestie Combo promotional flyer design sample",
        "delivery": "Confirm delivery timing on WhatsApp",
        "packages": ("flyer-design",),
    },
    {
        "id": "web-maintenance",
        "name": "Website Maintenance",
        "summary": "Keep your existing website up to date with a small content change.",
        "image": "website-maintenance.webp",
        "alt": "A woman wearing headphones reviewing a website at her workstation",
        "delivery": "Confirm availability on WhatsApp",
        "packages": ("web-maintenance",),
    },
    {
        "id": "db-maintenance",
        "name": "Database Maintenance",
        "summary": "Find out what needs attention with a read-only database health check.",
        "image": "database-maintenance.webp",
        "home_image": "database-workstation.webp",
        "home_alt": "A developer working at a laptop in a cream and plum workspace",
        "alt": "A technician reviewing a database dashboard on a laptop",
        "delivery": "Confirm availability on WhatsApp",
        "packages": ("db-maintenance",),
    },
]
INTAKE = {
    "cv": [
        ("qualification", "Highest qualification or current studies", "e.g. Diploma in ICT, completed or in progress"),
        ("target_roles", "Roles you want to apply for", "e.g. Junior Developer or IT Support"),
        ("experience", "Experience or skills to highlight", "e.g. Internship, projects or certifications"),
    ],
    "website": [
        ("business", "Business name and what you do", "e.g. A salon offering braids and styling"),
        ("design", "Style, colours or websites you like", "e.g. Clean and colourful, or a reference URL"),
        ("features", "Pages, features or products you need", "e.g. Services, gallery and WhatsApp booking"),
    ],
    "flyer": [
        ("flyer_purpose", "What are you promoting?", "e.g. A salon special, price list or event"),
        ("flyer_copy", "What details should appear?", "e.g. Business name, offer, price and date"),
        ("flyer_style", "Preferred colours or style", "e.g. Pink and black, or a reference flyer"),
    ],
    "maintenance": [
        ("system", "Website address or database platform", "e.g. yoursite.co.za or MySQL"),
        ("issue", "What needs updating or checking?", "Describe the change or issue in a sentence"),
        ("urgency", "When do you need it?", "e.g. This week or a specific date"),
    ],
}
PACKAGE_INTAKE = {
    "cv-basic": "cv", "cv-premium": "cv",
    "web-starter": "website", "web-business": "website", "shop-starter": "website",
    "flyer-design": "flyer",
    "web-maintenance": "maintenance", "db-maintenance": "maintenance",
}
PORTFOLIO_URL = "https://trevor-67.github.io/Personal_Portfolio/#experience"
PROJECTS = [
    ("SmartTrain", "Python · Flask · SQLite", "An AI-assisted prototype that assigns trainers and schedules customer training requests."),
    ("Ticketing System", "Coursework", "A system for tracking support tickets from creation to resolution."),
    ("SME Support System", "Hackathon prototype", "A prototype built during a 48-hour hackathon focused on small-business needs."),
    ("POS Sales Analytics", "SQL · BigQuery · Looker Studio", "Reporting exercises covering store turnover, payment methods and top-selling products."),
]


@app.cli.group("orders")
def orders_cli():
    """Look up submitted website orders."""


@orders_cli.command("show")
@click.argument("order_id", type=click.IntRange(min=1))
def show_order(order_id):
    """Show the full form for an order reference."""
    database = Path(app.config["DATABASE"])
    if not database.is_file():
        raise click.ClickException("No orders database exists in this installation.")

    try:
        with closing(sqlite3.connect(database)) as db:
            db.row_factory = sqlite3.Row
            if not db.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'orders'"
            ).fetchone():
                raise click.ClickException("No orders have been saved in this installation.")
            order_details = db.execute(
                "SELECT * FROM orders WHERE id = ?", (order_id,)
            ).fetchone()
    except sqlite3.Error as error:
        raise click.ClickException("Could not read the orders database.") from error

    if order_details is None:
        raise click.ClickException(f"Order #{order_id} was not found in this installation.")

    package_key = order_details["package"]
    package = PACKAGES.get(package_key)
    package_label = f"{package[0]} ({package[1]})" if package else package_key
    click.echo(f"Order #{order_id}")
    click.echo(f"Submitted (UTC): {order_details['created_at']}")
    click.echo(f"Customer: {order_details['name']}")
    click.echo(f"WhatsApp number: {order_details['phone']}")
    click.echo(f"Package: {package_label}")
    click.echo(f"Order total: {format_rand(order_details['price_rand'])}")
    click.echo("\nForm answers and additional notes:")
    click.echo(order_details["notes"] or "No additional details were entered.")


@app.template_filter("rand")
def format_rand(amount):
    return f"R{amount:,.2f}" if amount % 1 else f"R{amount:,.0f}"


@app.context_processor
def site_links():
    return {"whatsapp": WHATSAPP, "whatsapp_number": f"+{WHATSAPP_NUMBER}", "portfolio_url": PORTFOLIO_URL,
            "cv_regular_prices": CV_REGULAR_PRICES if CV_PROMO_ACTIVE else {}}


@app.get("/")
def home():
    return render_template("home.html", projects=PROJECTS, services=SERVICES,
                           packages=PACKAGES, testimonials=approved_testimonials())


@app.get("/services")
def services():
    return render_template("services.html", services=SERVICES, packages=PACKAGES)


@app.get("/privacy")
def privacy():
    return render_template("privacy.html")


@app.get("/portfolio")
def portfolio():
    return render_template("portfolio.html", projects=PROJECTS)


def order_page(values, status=200, **context):
    return render_template("order.html", packages=PACKAGES, values=values,
                           intake=INTAKE, package_intake=PACKAGE_INTAKE, **context), status


@app.route("/order", methods=["GET", "POST"])
def order():
    if request.method == "GET":
        return order_page({"package": request.args.get("package", "")})

    values = {field: request.form.get(field, "").strip()
              for field in ("name", "phone", "package", "notes")}
    phone = re.sub(r"[ ()-]", "", values["phone"])
    package = PACKAGES.get(values["package"])
    fields = INTAKE.get(PACKAGE_INTAKE.get(values["package"]), [])
    for key, _, _ in fields:
        values[key] = request.form.get(key, "").strip()
    errors = {}
    if any(len(values[key]) > 200 for key, _, _ in fields):
        errors["intake"] = "Use up to 200 characters for each requirement."
    if not 1 <= len(values["name"]) <= 80:
        errors["name"] = "Enter your name using up to 80 characters."
    if not re.fullmatch(r"(?:0[0-9]{9}|\+[1-9][0-9]{7,14})", phone):
        errors["phone"] = "Enter a number like 082 123 4567 or +27 82 123 4567."
    if package is None:
        errors["package"] = "Choose a package from the list."
    if len(values["notes"]) > 500:
        errors["notes"] = "Use up to 500 characters."
    if errors:
        return order_page(values, 400, errors=errors)

    service, tier, price, _ = package
    notes = [f"{label}: {values[key]}" for key, label, _ in fields if values[key]]
    if values["notes"]:
        notes.append(values["notes"])
    try:
        Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(app.config["DATABASE"])) as db, db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    package TEXT NOT NULL,
                    price_rand INTEGER NOT NULL,
                    notes TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'new',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor = db.execute("""
                INSERT INTO orders (name, phone, package, price_rand, notes)
                VALUES (?, ?, ?, ?, ?)
            """, (values["name"], phone, values["package"], price, "\n".join(notes)))
            order_id = cursor.lastrowid
    except (OSError, sqlite3.Error):
        app.logger.exception("Could not save order")
        return order_page(values, 503,
                          problem="Your order could not be saved. Try again or contact us on WhatsApp.")

    message = (
        "Dear PHET-Digital,\n\n"
        "I have submitted an order through your website.\n\n"
        f"Order reference: #{order_id}\n"
        f"Service: {service} ({tier})\n"
        f"Order total: {format_rand(price)}\n\n"
        "Please confirm receipt of my order and advise me on the next steps.\n\n"
        "Kind regards"
    )
    return redirect(f"{WHATSAPP}?{urlencode({'text': message})}", code=303)
