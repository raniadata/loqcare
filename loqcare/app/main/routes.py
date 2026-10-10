from flask import Blueprint, render_template, redirect, url_for
from flask_login import login_required, current_user

main_bp = Blueprint("main", __name__)


@main_bp.get("/")
def index():
    return render_template("landing.html")


@main_bp.get("/dashboard")
@login_required
def dashboard():
    """كل دور عندو الداشبورد ديالو - هنا غير كنوجهو للبلاصة الصحيحة."""
    if current_user.is_admin:
        return redirect(url_for("admin.dashboard"))
    if current_user.is_doctor:
        return redirect(url_for("doctor.dashboard"))
    # medical_team غادي يتزاد فـ Phase 2
    return render_template("dashboard.html", user=current_user)
