
from __future__ import annotations
import os
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional

from flask import (
    Flask, render_template, request, redirect, url_for, session, flash, jsonify, make_response
)
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import (
    create_engine, Column, Integer, String, DateTime, Float, ForeignKey, Boolean, Text
)
from sqlalchemy.orm import sessionmaker, declarative_base, relationship, scoped_session
from sqlalchemy.exc import IntegrityError

# -------------------------
# App & Database
# -------------------------
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
DB_URL = os.environ.get("DATABASE_URL", "sqlite:///app.db")

engine = create_engine(DB_URL, future=True, echo=False)
SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False))
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# -------------------------
# Models
# -------------------------
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    balance = Column(Float, default=0.0)
    referral_code = Column(String(12), unique=True, nullable=False)
    referred_by = Column(String(12), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_claim_at = Column(DateTime, nullable=True)

    transactions = relationship("Transaction", back_populates="user", cascade="all, delete-orphan")
    purchases = relationship("Purchase", back_populates="user", cascade="all, delete-orphan")

class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    type = Column(String(30), nullable=False)  # recharge/topup/buy/sell/bonus/mining
    amount = Column(Float, default=0.0)
    details = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="transactions")

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    slug = Column(String(140), unique=True, nullable=False)
    price = Column(Float, nullable=False)
    hourly_rate = Column(Float, nullable=False)  # mining earning per hour credited when user claims
    active = Column(Boolean, default=True)
    description = Column(Text, default="")

class Purchase(Base):
    __tablename__ = "purchases"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    product_id = Column(Integer, ForeignKey("products.id"))
    purchased_at = Column(DateTime, default=datetime.utcnow)
    last_mined_at = Column(DateTime, default=datetime.utcnow)
    accrued = Column(Float, default=0.0)  # unclaimed earnings

    user = relationship("User", back_populates="purchases")
    product = relationship("Product")

def init_db():
    Base.metadata.create_all(engine)
    # Seed some mining products if not present
    db = SessionLocal()
    try:
        if db.query(Product).count() == 0:
            items = [
                ("Starter Rig", "starter-rig", 100.0, 0.02, "Entry mining product. Earns 0.02 per hour."),
                ("Pro Miner", "pro-miner", 250.0, 0.06, "Mid-tier mining. Earns 0.06 per hour."),
                ("Mega Farm", "mega-farm", 500.0, 0.14, "High yield. Earns 0.14 per hour."),
            ]
            for (name, slug, price, rate, desc) in items:
                db.add(Product(name=name, slug=slug, price=price, hourly_rate=rate, description=desc))
            db.commit()
    finally:
        db.close()

def gen_ref_code():
    import random, string
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

# -------------------------
# Auth helpers
# -------------------------
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

def current_user():
    if "user_id" not in session:
        return None
    db = SessionLocal()
    try:
        user = db.get(User, session["user_id"])
        return user
    finally:
        db.close()

# -------------------------
# Routes
# -------------------------
@app.route("/")
def index():
    db = SessionLocal()
    try:
        products = db.query(Product).filter_by(active=True).all()
        return render_template("index.html", products=products)
    finally:
        db.close()

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/support")
def support():
    return render_template("support.html")

@app.route("/r/<code>")
def referral_entry(code):
    # Store ref code in cookie and session until registration
    resp = make_response(redirect(url_for("register")))
    session["ref"] = code
    resp.set_cookie("ref", code, max_age=7*24*3600)
    return resp

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or not password:
            flash("Username and password required.", "danger")
            return redirect(url_for("register"))

        db = SessionLocal()
        try:
            user = User(
                username=username,
                password_hash=generate_password_hash(password),
                referral_code=gen_ref_code(),
                referred_by=session.get("ref")
            )
            db.add(user)
            db.commit()
            session.pop("ref", None)
            flash("Registration successful. Please log in.", "success")
            return redirect(url_for("login"))
        except IntegrityError:
            db.rollback()
            flash("Username already taken.", "danger")
            return redirect(url_for("register"))
        finally:
            db.close()
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(username=username).first()
            if user and check_password_hash(user.password_hash, password):
                session["user_id"] = user.id
                flash("Logged in!", "success")
                return redirect(url_for("dashboard"))
            flash("Invalid credentials.", "danger")
            return redirect(url_for("login"))
        finally:
            db.close()
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("index"))

@app.route("/dashboard")
@login_required
def dashboard():
    db = SessionLocal()
    try:
        user = db.get(User, session["user_id"])
        products = db.query(Product).filter_by(active=True).all()
        # count referrals
        refs = db.query(User).filter_by(referred_by=user.referral_code).count()
        return render_template("dashboard.html", user=user, products=products, ref_count=refs)
    finally:
        db.close()

# --------- Money actions (demo only; no real payment integration) ---------
@app.route("/recharge", methods=["GET", "POST"])
@login_required
def recharge():
    db = SessionLocal()
    user = db.get(User, session["user_id"])
    if request.method == "POST":
        amount = float(request.form.get("amount", 0) or 0)
        if amount > 0:
            user.balance += amount
            db.add(Transaction(user_id=user.id, type="recharge", amount=amount, details="Mobile recharge (demo credit)"))
            db.commit()
            flash(f"Recharged {amount:.2f} (demo).", "success")
            return redirect(url_for("balance"))
        flash("Invalid amount.", "danger")
    return render_template("recharge.html", user=user)

@app.route("/topup", methods=["GET", "POST"])
@login_required
def topup():
    db = SessionLocal()
    user = db.get(User, session["user_id"])
    if request.method == "POST":
        amount = float(request.form.get("amount", 0) or 0)
        if amount > 0 and user.balance >= amount:
            user.balance -= amount
            db.add(Transaction(user_id=user.id, type="topup", amount=-amount, details="Diamond top-up (demo spend)"))
            db.commit()
            flash(f"Diamond top-up of {amount:.2f} successful (demo).", "success")
            return redirect(url_for("balance"))
        flash("Insufficient balance or invalid amount.", "danger")
    return render_template("topup.html", user=user)

@app.route("/dollar", methods=["GET", "POST"])
@login_required
def dollar():
    db = SessionLocal()
    user = db.get(User, session["user_id"])
    if request.method == "POST":
        action = request.form.get("action")
        amount = float(request.form.get("amount", 0) or 0)
        if amount <= 0:
            flash("Enter a positive amount.", "danger")
            return redirect(url_for("dollar"))
        if action == "buy" and user.balance >= amount:
            user.balance -= amount
            db.add(Transaction(user_id=user.id, type="buy", amount=-amount, details="Bought dollars (demo)"))
        elif action == "sell":
            user.balance += amount
            db.add(Transaction(user_id=user.id, type="sell", amount=amount, details="Sold dollars (demo)"))
        else:
            flash("Invalid action or insufficient balance.", "danger")
            db.close()
            return redirect(url_for("dollar"))
        db.commit()
        flash(f"{action.title()} {amount:.2f} (demo).", "success")
        return redirect(url_for("balance"))
    return render_template("dollar.html", user=user)

@app.route("/daily-claim")
@login_required
def daily_claim():
    db = SessionLocal()
    user = db.get(User, session["user_id"])
    now = datetime.utcnow()
    if user.last_claim_at and now - user.last_claim_at < timedelta(hours=24):
        remaining = timedelta(hours=24) - (now - user.last_claim_at)
        flash(f"Next claim available in {remaining}.", "warning")
        db.close()
        return redirect(url_for("dashboard"))
    bonus = 5.0
    user.balance += bonus
    user.last_claim_at = now
    db.add(Transaction(user_id=user.id, type="bonus", amount=bonus, details="Daily claim bonus"))
    # Referral bonus: give referrer small bonus on first claim (one-time)
    if user.referred_by:
        referrer = db.query(User).filter_by(referral_code=user.referred_by).first()
        if referrer:
            db.add(Transaction(user_id=referrer.id, type="bonus", amount=1.0, details=f"Referral bonus from {user.username}"))
            referrer.balance += 1.0
            # clear referred_by so it doesn't trigger repeatedly
            user.referred_by = None
    db.commit()
    db.close()
    flash("Daily bonus claimed!", "success")
    return redirect(url_for("balance"))

@app.route("/balance")
@login_required
def balance():
    db = SessionLocal()
    try:
        user = db.get(User, session["user_id"])
        txs = db.query(Transaction).filter_by(user_id=user.id).order_by(Transaction.created_at.desc()).limit(50).all()
        return render_template("balance.html", user=user, txs=txs)
    finally:
        db.close()

@app.route("/profile")
@login_required
def profile():
    db = SessionLocal()
    try:
        user = db.get(User, session["user_id"])
        refs = db.query(User).filter_by(referred_by=user.referral_code).count()
        return render_template("profile.html", user=user, ref_count=refs)
    finally:
        db.close()

@app.route("/p/<slug>")
def product_page(slug):
    db = SessionLocal()
    try:
        product = db.query(Product).filter_by(slug=slug, active=True).first()
        if not product:
            flash("Product not found.", "danger")
            return redirect(url_for("index"))
        return render_template("product.html", product=product)
    finally:
        db.close()

@app.route("/buy/<slug>", methods=["POST"])
@login_required
def buy(slug):
    db = SessionLocal()
    try:
        user = db.get(User, session["user_id"])
        product = db.query(Product).filter_by(slug=slug, active=True).first()
        if not product:
            flash("Product not found.", "danger")
            return redirect(url_for("index"))
        if user.balance < product.price:
            flash("Insufficient balance to buy this product.", "danger")
            return redirect(url_for("product_page", slug=slug))
        user.balance -= product.price
        purchase = Purchase(user_id=user.id, product_id=product.id)
        db.add(purchase)
        db.add(Transaction(user_id=user.id, type="buy_product", amount=-product.price, details=f"Bought {product.name}"))
        db.commit()
        flash("Product purchased! Mining started.", "success")
        return redirect(url_for("mining"))
    finally:
        db.close()

@app.route("/mining")
@login_required
def mining():
    db = SessionLocal()
    user = db.get(User, session["user_id"])
    # Update accrued for each purchase
    now = datetime.utcnow()
    for p in user.purchases:
        hrs = (now - (p.last_mined_at or p.purchased_at)).total_seconds() / 3600.0
        if hrs > 0:
            p.accrued += p.product.hourly_rate * hrs
            p.last_mined_at = now
    db.commit()
    return render_template("mining.html", purchases=user.purchases, user=user)

@app.route("/mining/claim", methods=["POST"])
@login_required
def mining_claim():
    db = SessionLocal()
    user = db.get(User, session["user_id"])
    total = 0.0
    for p in user.purchases:
        if p.accrued > 0:
            total += p.accrued
            p.accrued = 0.0
    if total > 0:
        user.balance += total
        db.add(Transaction(user_id=user.id, type="mining", amount=total, details="Claimed mining earnings"))
    db.commit()
    flash(f"Claimed {total:.4f} from mining.", "success")
    return redirect(url_for("balance"))

# -------------------------
# CLI helper
# -------------------------
@app.cli.command("create-db")
def create_db_cmd():
    init_db()
    print("Database initialized.")

# -------------------------
# Main
# -------------------------
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
