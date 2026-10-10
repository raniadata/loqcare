from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, abort
from flask_login import login_required, current_user
from app import db
from app.decorators import role_required
from app.models import Program, Patient, Case, Notification
from app.utils import (
    normalize_whatsapp_number,
    is_valid_whatsapp_number,
    validate_full_name,
    combine_country_code_and_local,
    clean_digits,
    validate_digits_only,
)

doctor_bp = Blueprint("doctor", __name__, url_prefix="/doctor")

# حالة "pending" كتعتبر محتاجة إجراء إلا مرت عليها هاد المدة بلا رد من المريض
NEEDS_ACTION_PENDING_DAYS = 3


def _needs_action(case, now):
    """استفسار من المريض، أو حالة بلا رد منذ NEEDS_ACTION_PENDING_DAYS أيام أو أكثر."""
    if case.status == "inquiry":
        return True
    return case.status == "pending" and (now - case.created_at).days >= NEEDS_ACTION_PENDING_DAYS


@doctor_bp.before_request
@login_required
@role_required("doctor")
def _guard():
    pass


@doctor_bp.get("/")
def dashboard():
    my_cases = db.session.scalars(
        db.select(Case)
        .where(Case.doctor_id == current_user.id)
        .order_by(Case.created_at.desc())
    ).all()

    # --- المؤشرات الرئيسية (3 مؤشرات بتعريف واضح لكل واحد) ---
    from datetime import datetime as _dt

    now = _dt.utcnow()
    stats = {
        # كل مريض أحلته (بأي حالة)
        "total": len(my_cases),
        # المرضى اللي أكدوا وبدأوا البرنامج (confirmed)
        "started": sum(1 for c in my_cases if c.status == "confirmed"),
        # إحالات محتاجة متابعة: استفسارات المرضى + حالات بلا رد منذ 3 أيام أو أكثر
        "needs_action": sum(1 for c in my_cases if _needs_action(c, now)),
        "pending_days": NEEDS_ACTION_PENDING_DAYS,
    }

    # --- نشاط آخر 6 أشهر (لعرضه كرسم بياني بسيط بالأعمدة) ---
    from datetime import datetime, timedelta
    import calendar

    today = datetime.utcnow().replace(day=1)
    months = []
    for i in range(5, -1, -1):
        year = today.year
        month = today.month - i
        while month <= 0:
            month += 12
            year -= 1
        months.append((year, month))

    monthly_counts = []
    for year, month in months:
        count = sum(
            1 for c in my_cases if c.created_at.year == year and c.created_at.month == month
        )
        monthly_counts.append({"label": calendar.month_abbr[month], "count": count})

    max_count = max((m["count"] for m in monthly_counts), default=0) or 1

    # --- رسم بياني دائري لتوزيع الحالات حسب الوضع ---
    from app.utils import build_pie_chart

    status_counts = {
        "pending": sum(1 for c in my_cases if c.status == "pending"),
        "confirmed": sum(1 for c in my_cases if c.status == "confirmed"),
        "declined": sum(1 for c in my_cases if c.status == "declined"),
        "inquiry": sum(1 for c in my_cases if c.status == "inquiry"),
    }
    pie_gradient, pie_legend = build_pie_chart(status_counts)

    return render_template(
        "doctor/dashboard.html", cases=my_cases[:20], stats=stats,
        monthly_counts=monthly_counts, max_count=max_count,
        pie_gradient=pie_gradient, pie_legend=pie_legend,
    )


@doctor_bp.get("/referrals/new")
def new_referral():
    active_programs = db.session.scalars(
        db.select(Program).where(Program.is_active == True)
    ).all()
    return render_template("doctor/new_referral.html", programs=active_programs)


@doctor_bp.post("/referrals/new")
def new_referral_post():
    patient_name = request.form.get("patient_name", "").strip()
    country_code = request.form.get("country_code", "").strip()
    local_number = clean_digits(request.form.get("local_number", "").strip())
    raw_number = combine_country_code_and_local(country_code, local_number)
    program_id = request.form.get("program_id")
    notes = request.form.get("notes", "").strip()

    if not patient_name or not local_number or not program_id:
        flash("يجب إدخال اسم المريض، رقم الواتساب، والبرنامج.", "error")
        return redirect(url_for("doctor.new_referral"))

    name_error = validate_full_name(patient_name)
    if name_error:
        flash(name_error, "error")
        return redirect(url_for("doctor.new_referral"))

    digits_error = validate_digits_only(local_number, "رقم الواتساب", min_len=6, max_len=14)
    if digits_error:
        flash(digits_error, "error")
        return redirect(url_for("doctor.new_referral"))

    whatsapp_number = normalize_whatsapp_number(raw_number)
    if not is_valid_whatsapp_number(whatsapp_number):
        flash("رقم الواتساب غير صالح. مثال صحيح: 0703040506 أو +212703040506", "error")
        return redirect(url_for("doctor.new_referral"))

    patient = Patient(full_name=patient_name, whatsapp_number=whatsapp_number)
    db.session.add(patient)
    db.session.flush()  # باش يكون عندنا patient.id قبل الـcommit

    case = Case(
        patient_id=patient.id,
        program_id=int(program_id),
        doctor_id=current_user.id,
        source="doctor_referral",
        status="pending",
        notes=notes,
    )
    db.session.add(case)
    db.session.commit()

    # إرسال رسالة العرض للمريض عبر واتساب (Twilio).
    # إلا ماكانش Twilio معمّر فـ .env، الرسالة كتتسجل فقط فقاعدة البيانات
    # بلا إرسال فعلي — باش التجربة المحلية تبقى خدامة.
    try:
        from app.webhook.twilio_client import send_whatsapp_offer

        send_whatsapp_offer(case)
    except Exception as exc:
        current_app.logger.error("فشل إرسال رسالة الواتساب: %s", exc)
        flash(
            "تم تسجيل الإحالة، لكن تعذّر إرسال رسالة الواتساب. تحقق من إعدادات Twilio.",
            "error",
        )
        return redirect(url_for("doctor.dashboard"))

    flash("تم تسجيل الإحالة بنجاح وإرسال الرسالة للمريض.", "success")
    return redirect(url_for("doctor.dashboard"))


# ---------------------------------------------------------
# حسابي: الطبيب يشوف بياناته الشخصية، ويقدر يبدل رقم الهاتف
# (باقي البيانات المهنية للحين read-only - أي تعديل عليها
# يحتاج مراجعة من الإدارة لأنها بيانات ترخيص/مستشفى حساسة)
# ---------------------------------------------------------


@doctor_bp.get("/account")
def account():
    return render_template("doctor/account.html", doctor=current_user)


@doctor_bp.post("/account/change_password")
def change_password():
    from app.utils import validate_password

    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not current_user.check_password(current_password):
        flash("كلمة المرور الحالية غير صحيحة.", "error")
        return redirect(url_for("doctor.account"))

    password_error = validate_password(new_password)
    if password_error:
        flash(password_error, "error")
        return redirect(url_for("doctor.account"))

    if new_password != confirm_password:
        flash("كلمة المرور الجديدة وتأكيدها غير متطابقتين.", "error")
        return redirect(url_for("doctor.account"))

    current_user.set_password(new_password)
    db.session.commit()
    flash("تم تحديث كلمة المرور بنجاح.", "success")
    return redirect(url_for("doctor.account"))


ALLOWED_PHOTO_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
MAX_PHOTO_SIZE_BYTES = 3 * 1024 * 1024  # 3MB


@doctor_bp.post("/account/photo")
def upload_photo():
    import os
    import uuid
    from werkzeug.utils import secure_filename

    file = request.files.get("photo")
    if not file or not file.filename:
        flash("يجب اختيار صورة.", "error")
        return redirect(url_for("doctor.account"))

    ext = secure_filename(file.filename).rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_PHOTO_EXTENSIONS:
        flash("صيغة الصورة غير مدعومة. استعملي JPG أو PNG أو WEBP.", "error")
        return redirect(url_for("doctor.account"))

    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > MAX_PHOTO_SIZE_BYTES:
        flash("حجم الصورة كبير بزاف (الحد الأقصى 3 ميغا).", "error")
        return redirect(url_for("doctor.account"))

    upload_dir = os.path.join(current_app.root_path, "static", "uploads", "profiles")
    os.makedirs(upload_dir, exist_ok=True)

    filename = f"{current_user.id}_{uuid.uuid4().hex[:8]}.{ext}"
    file.save(os.path.join(upload_dir, filename))

    # كنحيدو الصورة القديمة إلا كانت، باش ما تتراكمش الملفات
    if current_user.profile_photo:
        old_path = os.path.join(upload_dir, current_user.profile_photo)
        if os.path.exists(old_path):
            os.remove(old_path)

    current_user.profile_photo = filename
    db.session.commit()

    flash("تم تحديث صورتك الشخصية بنجاح.", "success")
    return redirect(url_for("doctor.account"))


@doctor_bp.post("/account/update")
def account_update():
    country_code = request.form.get("country_code", "").strip()
    local_number = clean_digits(request.form.get("local_number", "").strip())

    if not local_number:
        flash("يجب إدخال رقم الهاتف.", "error")
        return redirect(url_for("doctor.account"))

    digits_error = validate_digits_only(local_number, "رقم الهاتف", min_len=6, max_len=14)
    if digits_error:
        flash(digits_error, "error")
        return redirect(url_for("doctor.account"))

    raw_number = combine_country_code_and_local(country_code, local_number)
    new_phone = normalize_whatsapp_number(raw_number)
    if not is_valid_whatsapp_number(new_phone):
        flash("رقم الهاتف غير صالح.", "error")
        return redirect(url_for("doctor.account"))

    current_user.phone = new_phone
    db.session.commit()
    flash("تم تحديث رقم الهاتف بنجاح.", "success")
    return redirect(url_for("doctor.account"))


# ---------------------------------------------------------
# المرضى: لائحة المرضى اللي أصبحوا "مؤكدين" (Confirmed) من
# إحالات هذا الطبيب بالذات
# ---------------------------------------------------------


@doctor_bp.get("/cases")
def cases():
    """كل الإحالات ديال هاد الطبيب، بلا حد أقصى (خلاف لوحة الرئيسية اللي كتبين آخر 20 فقط)."""
    from datetime import datetime as _dt

    all_cases = db.session.scalars(
        db.select(Case)
        .where(Case.doctor_id == current_user.id)
        .order_by(Case.created_at.desc())
    ).all()

    # الوصول من بطاقات المؤشرات: ?view=started (بدأوا البرنامج) | ?view=action (تحتاج إجراء)
    view = request.args.get("view", "")
    view_label = None
    if view == "started":
        all_cases = [c for c in all_cases if c.status == "confirmed"]
        view_label = "المرضى الذين بدأوا البرنامج"
    elif view == "action":
        now = _dt.utcnow()
        all_cases = [c for c in all_cases if _needs_action(c, now)]
        view_label = "الإحالات التي تحتاج إلى إجراء"
    else:
        view = ""
    return render_template(
        "doctor/cases.html", cases=all_cases, view=view, view_label=view_label
    )


@doctor_bp.get("/cases/<int:case_id>")
def case_detail(case_id):
    """تفاصيل إحالة (للقراءة فقط) — الطبيب يشوف غير الإحالات ديالو."""
    case = db.session.get(Case, case_id)
    if not case or case.doctor_id != current_user.id:
        abort(404)
    return render_template("doctor/case_detail.html", case=case)


@doctor_bp.get("/patients")
def patients():
    confirmed_cases = db.session.scalars(
        db.select(Case)
        .where(Case.doctor_id == current_user.id, Case.status == "confirmed")
        .order_by(Case.updated_at.desc())
    ).all()
    return render_template("doctor/patients.html", cases=confirmed_cases)


# ---------------------------------------------------------
# الإشعارات: الطبيب كيشوف الإشعارات اللي بعثها ليه الـ Admin
# ---------------------------------------------------------


@doctor_bp.get("/notifications")
def notifications():
    my_notifications = db.session.scalars(
        db.select(Notification)
        .where(Notification.recipient_id == current_user.id)
        .order_by(Notification.created_at.desc())
    ).all()

    # كنحفظو أرقام غير المقروء قبل ما نعلمو الكل "مقروء"، باش نبينو شارة "جديد" فهاد الزيارة
    unread = [n for n in my_notifications if not n.is_read]
    new_ids = {n.id for n in unread}
    for n in unread:
        n.is_read = True
    if unread:
        db.session.commit()

    return render_template(
        "doctor/notifications.html", notifications=my_notifications, new_ids=new_ids
    )
