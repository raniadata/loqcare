from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, current_user
from app import db, limiter
from app.models import User
from app.utils import (
    is_valid_email,
    validate_password,
    validate_full_name,
    normalize_whatsapp_number,
    is_valid_whatsapp_number,
    combine_country_code_and_local,
    clean_digits,
    validate_digits_only,
)

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


# ---------------------------------------------------------
# تسجيل حساب طبيب جديد (Self-registration)
# الحساب كيتصاوب بحالة pending، وما يقدرش يدخل حتى الـAdmin يوافق
# ---------------------------------------------------------


@auth_bp.get("/register")
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return render_template("auth/register.html")


@auth_bp.post("/register")
@limiter.limit("5 per hour")  # حماية بسيطة ضد التسجيلات الوهمية المتكررة
def register_post():
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    country_code = request.form.get("country_code", "").strip()
    local_number = clean_digits(request.form.get("local_number", "").strip())
    phone = combine_country_code_and_local(country_code, local_number) if local_number else ""
    specialty = request.form.get("specialty", "").strip()
    specialty_other = request.form.get("specialty_other", "").strip()
    if specialty == "أخرى" and specialty_other:
        specialty = specialty_other
    hospital_name = request.form.get("hospital_name", "").strip()
    department = request.form.get("department", "").strip()
    license_number = clean_digits(request.form.get("license_number", "").strip())
    country = request.form.get("country", "").strip()
    city = request.form.get("city", "").strip()
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")

    # الحقول الاختيارية
    years_experience = request.form.get("years_experience", "").strip()
    certificates = request.form.get("certificates", "").strip()
    bio = request.form.get("bio", "").strip()

    required_fields = {
        "الاسم الكامل": full_name,
        "التخصص": specialty,
        "اسم المستشفى": hospital_name,
        "القسم": department,
        "رقم الترخيص الطبي": license_number,
        "الدولة": country,
        "المدينة": city,
        "رقم الهاتف": local_number,
        "البريد الإلكتروني": email,
        "كلمة المرور": password,
    }
    missing = [label for label, value in required_fields.items() if not value]
    if missing:
        return _register_error("الحقول التالية إلزامية: " + "، ".join(missing))

    if request.form.get("specialty") == "أخرى" and not specialty_other:
        return _register_error("يرجى كتابة التخصص في الحقل المخصص لذلك.", focus="specialty_other")

    # رقم الترخيص ورقم الهاتف: أرقام فقط (تحقق من جهة الخادم، بالإضافة للتحقق فالواجهة)
    license_error = validate_digits_only(license_number, "رقم الترخيص الطبي", min_len=3, max_len=20)
    if license_error:
        return _register_error(license_error, focus="license_number")

    phone_error = validate_digits_only(local_number, "رقم الهاتف", min_len=6, max_len=14)
    if phone_error:
        return _register_error(phone_error, focus="local_number")
    if not is_valid_whatsapp_number(normalize_whatsapp_number(phone)):
        return _register_error("رقم الهاتف غير صالح، تأكد من رمز الدولة والرقم.", focus="local_number")

    name_error = validate_full_name(full_name)
    if name_error:
        return _register_error(name_error, focus="full_name")

    if not is_valid_email(email):
        return _register_error("صيغة البريد الإلكتروني غير صحيحة.", focus="email")

    password_error = validate_password(password)
    if password_error:
        return _register_error(password_error, focus="password")

    if password != confirm_password:
        return _register_error("كلمة المرور وتأكيدها غير متطابقتين.", focus="password")

    if db.session.scalar(db.select(User).where(User.email == email)):
        return _register_error("هذا البريد الإلكتروني مسجل من قبل.", focus="email")

    user = User(
        full_name=full_name,
        email=email,
        phone=normalize_whatsapp_number(phone),
        specialty=specialty,
        hospital_name=hospital_name,
        department=department,
        license_number=license_number,
        country=country,
        city=city,
        years_experience=int(years_experience) if years_experience.isdigit() else None,
        certificates=certificates or None,
        bio=bio or None,
        role="doctor",
        account_status="pending",  # في انتظار موافقة الإدارة
        is_active_account=False,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    flash(
        "تم إرسال طلب التسجيل بنجاح. حسابك الآن في انتظار موافقة الإدارة، وستصلك رسالة عند تفعيله.",
        "success",
    )
    return redirect(url_for("auth.login"))


def _register_error(message, focus=None):
    """كنرجعو نفس الصفحة بنفس البيانات المدخلة (بدون redirect) باش ما يضيعش الفورم.

    كلمات المرور ما كنرجعوهاش للمتصفح لأسباب أمنية، فالمستخدم كيعاود يكتبها هي فقط.
    """
    flash(message, "error")
    form = {k: v for k, v in request.form.items() if k not in ("password", "confirm_password", "csrf_token")}
    return render_template("auth/register.html", form=form, focus=focus), 400


# ---------------------------------------------------------
# تسجيل الدخول
# ---------------------------------------------------------


@auth_bp.get("/login")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return render_template("auth/login.html")


@auth_bp.post("/login")
@limiter.limit("10 per hour")
def login_post():
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    user = db.session.scalar(db.select(User).where(User.email == email))

    if not user or not user.check_password(password):
        flash("بيانات الدخول غير صحيحة.", "error")
        return redirect(url_for("auth.login"))

    if user.account_status == "rejected":
        flash("تم رفض طلب التسجيل الخاص بك. يرجى التواصل مع الإدارة.", "error")
        return redirect(url_for("auth.login"))

    if user.account_status == "deactivated":
        flash("تم إلغاء تفعيل حسابك من طرف الإدارة. يرجى التواصل معها لمزيد من التفاصيل.", "error")
        return redirect(url_for("auth.login"))

    if not user.is_active_account:
        flash("حسابك لا يزال في انتظار موافقة الإدارة.", "error")
        return redirect(url_for("auth.login"))

    login_user(user)
    return redirect(url_for("main.dashboard"))


@auth_bp.post("/logout")
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
