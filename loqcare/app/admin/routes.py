from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db
from app.decorators import role_required
from app.models import User, Program, Case, CaseAssignment, WhatsAppMessage, ActivityLog, Notification
from app.utils import (
    normalize_whatsapp_number,
    combine_country_code_and_local,
    classify_whatsapp_reply,
    log_activity,
    is_valid_email,
    validate_password,
    validate_full_name,
    build_pie_chart,
    clean_digits,
    validate_digits_only,
)

from app.constants import (
    MEMBER_TYPES,
    MEMBER_RANKS,
    MEMBER_SPECIALTIES,
    OTHER_SPECIALTY,
    SECTION_LABELS,
)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.before_request
@login_required
@role_required("admin")
def _guard():
    """كل route فهاد الـ blueprint خاصو يكون Admin - سطر وحد كافي بدل ما نكرروها فكل route."""
    pass


# ---------------------------------------------------------
# لوحة التحكم الرئيسية
# ---------------------------------------------------------


@admin_bp.get("/")
def dashboard():
    pending_doctors = db.session.scalars(
        db.select(User).where(User.role == "doctor", User.account_status == "pending")
    ).all()

    # --- فلتر الحالات: بالتاريخ وباسم الطبيب المحيل ---
    from datetime import datetime as _dt

    filter_date = request.args.get("date", "").strip()
    filter_doctor = request.args.get("doctor_name", "").strip()

    cases_query = db.select(Case).order_by(Case.created_at.desc())
    if filter_date:
        try:
            day = _dt.strptime(filter_date, "%Y-%m-%d").date()
            cases_query = cases_query.where(db.func.date(Case.created_at) == day)
        except ValueError:
            flash("صيغة التاريخ غير صحيحة (YYYY-MM-DD).", "error")
    if filter_doctor:
        cases_query = cases_query.join(User, Case.doctor_id == User.id).where(
            User.full_name.ilike(f"%{filter_doctor}%")
        )
    if not filter_date and not filter_doctor:
        cases_query = cases_query.limit(20)

    open_cases = db.session.scalars(cases_query).all()

    # إحصائيات بسيطة للوحة التحكم (Admin overview)
    total_doctors = db.session.scalar(
        db.select(db.func.count()).select_from(User).where(
            User.role == "doctor", User.is_active_account == True
        )
    )
    total_team = db.session.scalar(
        db.select(db.func.count()).select_from(User).where(
            User.role == "medical_team", User.is_active_account == True
        )
    )
    total_cases = db.session.scalar(db.select(db.func.count()).select_from(Case))

    status_counts = {}
    for status in ["pending", "confirmed", "declined", "inquiry"]:
        status_counts[status] = db.session.scalar(
            db.select(db.func.count()).select_from(Case).where(Case.status == status)
        )

    stats = {
        "total_doctors": total_doctors,
        "total_team": total_team,
        "total_cases": total_cases,
        "pending_approvals": len(pending_doctors),
        "status_counts": status_counts,
    }

    pie_gradient, pie_legend = build_pie_chart(status_counts)

    return render_template(
        "admin/dashboard.html",
        pending_doctors=pending_doctors,
        cases=open_cases,
        stats=stats,
        pie_gradient=pie_gradient,
        pie_legend=pie_legend,
    )


# ---------------------------------------------------------
# الموافقة/الرفض على تسجيل الأطباء
# ---------------------------------------------------------


def _safe_next(default_url):
    """كنرجعو للصفحة اللي جا منها الـ Admin، بشرط تكون صفحة داخلية فنفس الموقع
    (حماية من open-redirect)."""
    from urllib.parse import urlparse

    nxt = request.form.get("next", "")
    parsed = urlparse(nxt)
    if nxt.startswith("/") and not nxt.startswith("//") and not parsed.netloc and "\\" not in nxt:
        return nxt
    return default_url


def _back_target(default_endpoint):
    """بعد الموافقة/الرفض كنرجعو للصفحة اللي جا منها الـ Admin (قائمة الموافقات أو لوحة التحكم)."""
    return _safe_next(url_for(default_endpoint))


@admin_bp.post("/doctors/<int:user_id>/approve")
def approve_doctor(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash("المستخدم غير موجود.", "error")
        return redirect(url_for("admin.dashboard"))
    user.is_active_account = True
    user.account_status = "approved"
    log_activity("approve_doctor", "doctor", user.id, f"قبول الطبيب: {user.full_name}")
    db.session.commit()
    flash(f"تم تفعيل حساب الطبيب {user.full_name}.", "success")
    return redirect(_back_target("admin.dashboard"))


@admin_bp.post("/doctors/<int:user_id>/reject")
def reject_doctor(user_id):
    """رفض ناعم: كنحتافظو بالسجل بدل ما نمسحوه نهائياً،
    باش يبقى عندنا أثر لكل طلب تسجيل."""
    user = db.session.get(User, user_id)
    if user:
        user.account_status = "rejected"
        user.is_active_account = False
        log_activity("reject_doctor", "doctor", user.id, f"رفض الطبيب: {user.full_name}")
        db.session.commit()
        flash("تم رفض طلب التسجيل.", "success")
    return redirect(_back_target("admin.dashboard"))


@admin_bp.post("/doctors/<int:user_id>/deactivate")
def deactivate_doctor(user_id):
    """إزالة طبيب نشط من القائمة (بدون حذف السجل) - يمكن إعادة تفعيله لاحقاً بالموافقة عليه من جديد."""
    user = db.session.get(User, user_id)
    if not user or user.role != "doctor":
        flash("المستخدم غير موجود.", "error")
        return redirect(url_for("admin.doctors_list"))
    user.is_active_account = False
    user.account_status = "deactivated"
    log_activity("deactivate_doctor", "doctor", user.id, f"إلغاء تفعيل الطبيب: {user.full_name}")
    db.session.commit()
    flash(f"تم إلغاء تفعيل حساب الطبيب {user.full_name}.", "success")
    return redirect(url_for("admin.doctors_list"))


# ---------------------------------------------------------
# الحالات: لائحة كاملة لكل الحالات بلا حد أقصى، مع نفس الفلتر
# (خلاف لوحة الرئيسية اللي كتبين آخر 20 فقط بلا فلتر)
# ---------------------------------------------------------


@admin_bp.get("/cases")
def all_cases():
    from datetime import datetime as _dt

    filter_date = request.args.get("date", "").strip()
    filter_doctor = request.args.get("doctor_name", "").strip()

    cases_query = db.select(Case).order_by(Case.created_at.desc())
    if filter_date:
        try:
            day = _dt.strptime(filter_date, "%Y-%m-%d").date()
            cases_query = cases_query.where(db.func.date(Case.created_at) == day)
        except ValueError:
            flash("صيغة التاريخ غير صحيحة (YYYY-MM-DD).", "error")
    if filter_doctor:
        cases_query = cases_query.join(User, Case.doctor_id == User.id).where(
            User.full_name.ilike(f"%{filter_doctor}%")
        )

    cases = db.session.scalars(cases_query).all()
    return render_template("admin/all_cases.html", cases=cases)


# ---------------------------------------------------------
# المرضى: لائحة عامة لكل المرضى المؤكدين (Confirmed) من جميع
# الأطباء وحالات B2C
# ---------------------------------------------------------


@admin_bp.get("/patients")
def patients():
    confirmed_cases = db.session.scalars(
        db.select(Case).where(Case.status == "confirmed").order_by(Case.updated_at.desc())
    ).all()
    return render_template("admin/patients.html", cases=confirmed_cases)


# ---------------------------------------------------------
# بيانات الطبيب الكاملة + تبديل كلمة المرور من طرف الإدارة
# ---------------------------------------------------------


@admin_bp.get("/doctors/<int:user_id>")
def doctor_detail(user_id):
    doctor = db.session.get(User, user_id)
    if not doctor or doctor.role != "doctor":
        flash("الطبيب غير موجود.", "error")
        return redirect(url_for("admin.doctors_list"))

    doctor_cases = db.session.scalars(
        db.select(Case).where(Case.doctor_id == doctor.id).order_by(Case.created_at.desc())
    ).all()
    recent_notifications = db.session.scalars(
        db.select(Notification)
        .where(Notification.recipient_id == doctor.id)
        .order_by(Notification.created_at.desc())
        .limit(5)
    ).all()
    return render_template(
        "admin/doctor_detail.html",
        doctor=doctor,
        doctor_cases=doctor_cases,
        recent_notifications=recent_notifications,
    )


@admin_bp.post("/doctors/<int:user_id>/notify")
def notify_doctor(user_id):
    doctor = db.session.get(User, user_id)
    if not doctor or doctor.role != "doctor":
        flash("الطبيب غير موجود.", "error")
        return redirect(url_for("admin.doctors_list"))

    back = _safe_next(url_for("admin.doctor_detail", user_id=doctor.id))
    message = request.form.get("message", "").strip()
    if not message:
        flash("يجب كتابة نص الإشعار.", "error")
        return redirect(back)
    if len(message) > 1000:
        flash("نص الإشعار طويل جداً (الحد الأقصى 1000 حرف).", "error")
        return redirect(back)

    db.session.add(
        Notification(recipient_id=doctor.id, sender_id=current_user.id, message=message)
    )
    log_activity("send_notification", "doctor", doctor.id, f"إشعار إلى {doctor.full_name}: {message[:60]}")
    db.session.commit()

    flash(f"تم إرسال الإشعار إلى {doctor.full_name}.", "success")
    return redirect(back)


@admin_bp.post("/doctors/<int:user_id>/reset_password")
def reset_doctor_password(user_id):
    """كتصاوب كلمة مرور مؤقتة جديدة وكتبينها مرة وحدة للـ Admin
    باش يبعتها للطبيب يدوياً (بالإيميل أو الواتساب)."""
    import secrets

    doctor = db.session.get(User, user_id)
    if not doctor or doctor.role != "doctor":
        flash("الطبيب غير موجود.", "error")
        return redirect(url_for("admin.doctors_list"))

    new_password = secrets.token_urlsafe(9)  # كلمة مرور عشوائية آمنة (~12 حرف)
    doctor.set_password(new_password)
    log_activity("reset_password", "doctor", doctor.id, f"إعادة تعيين كلمة مرور: {doctor.full_name}")
    db.session.commit()

    flash(
        f'تم تعيين كلمة مرور جديدة لـ {doctor.full_name}: "{new_password}" — '
        "انسخها وابعثها له الآن، لأنها لن تظهر مرة أخرى.",
        "success",
    )
    return redirect(url_for("admin.doctor_detail", user_id=doctor.id))


# ---------------------------------------------------------
# قائمة الموافقات: كل طلبات تسجيل الأطباء المعلقة فصفحة وحدة
# ---------------------------------------------------------


@admin_bp.get("/approvals")
def approvals():
    pending_doctors = db.session.scalars(
        db.select(User)
        .where(User.role == "doctor", User.account_status == "pending")
        .order_by(User.created_at.desc())
    ).all()
    return render_template("admin/approvals.html", pending_doctors=pending_doctors)


# ---------------------------------------------------------
# عضو الفريق الطبي: صفحة التفاصيل + الإجراءات المسموحة
# (إعادة تعيين كلمة المرور، إلغاء التفعيل)
# ---------------------------------------------------------


def _get_team_member_or_none(user_id):
    member = db.session.get(User, user_id)
    if not member or member.role != "medical_team":
        return None
    return member


@admin_bp.get("/members/<int:user_id>")
def member_detail(user_id):
    member = _get_team_member_or_none(user_id)
    if not member:
        flash("عضو الفريق غير موجود.", "error")
        return redirect(url_for("admin.team_directory"))

    assigned_cases = db.session.scalars(
        db.select(Case)
        .join(CaseAssignment, CaseAssignment.case_id == Case.id)
        .where(CaseAssignment.team_member_id == member.id)
        .order_by(Case.created_at.desc())
    ).all()
    return render_template("admin/member_detail.html", member=member, assigned_cases=assigned_cases)


@admin_bp.post("/members/<int:user_id>/deactivate")
def deactivate_member(user_id):
    member = _get_team_member_or_none(user_id)
    if not member:
        flash("عضو الفريق غير موجود.", "error")
        return redirect(url_for("admin.team_directory"))
    member.is_active_account = False
    member.account_status = "deactivated"
    log_activity("deactivate_member", "team_member", member.id, f"إلغاء تفعيل عضو الفريق: {member.full_name}")
    db.session.commit()
    flash(f"تم إلغاء تفعيل حساب {member.full_name}.", "success")
    return redirect(url_for("admin.team_directory"))


@admin_bp.post("/members/<int:user_id>/reset_password")
def reset_member_password(user_id):
    import secrets

    member = _get_team_member_or_none(user_id)
    if not member:
        flash("عضو الفريق غير موجود.", "error")
        return redirect(url_for("admin.team_directory"))

    new_password = secrets.token_urlsafe(9)
    member.set_password(new_password)
    log_activity("reset_password", "team_member", member.id, f"إعادة تعيين كلمة مرور: {member.full_name}")
    db.session.commit()
    flash(
        f'تم تعيين كلمة مرور جديدة لـ {member.full_name}: "{new_password}" — '
        "انسخها وابعثها له الآن، لأنها لن تظهر مرة أخرى.",
        "success",
    )
    return redirect(url_for("admin.member_detail", user_id=member.id))


# ---------------------------------------------------------
# إنشاء أعضاء الفريق الطبي (Admin هو لي كيصاوب الحساب مباشرة، Active)
# ---------------------------------------------------------


# ---------------------------------------------------------
# الفريق: لائحة الأطباء النشطين + أعضاء الفريق الطبي
# ---------------------------------------------------------


def _people_counts():
    """أعداد التبويبين (الأطباء المحيلون / الفريق الطبي) للشريط العلوي المشترك."""
    doctors = db.session.scalar(
        db.select(db.func.count()).select_from(User).where(
            User.role == "doctor", User.account_status == "approved"
        )
    )
    team = db.session.scalar(
        db.select(db.func.count()).select_from(User).where(
            User.role == "medical_team", User.is_active_account == True
        )
    )
    return {"doctors": doctors, "team": team}


@admin_bp.get("/doctors")
def doctors_list():
    """الأطباء المحيلون النشطون (صفحة مستقلة عن الفريق الطبي)."""
    active_doctors = db.session.scalars(
        db.select(User)
        .where(User.role == "doctor", User.account_status == "approved")
        .order_by(User.full_name)
    ).all()
    return render_template(
        "admin/doctors.html", active_doctors=active_doctors, counts=_people_counts()
    )


@admin_bp.get("/team")
def team_directory():
    """أعضاء الفريق الطبي (أطباء LOQ CARE + أخصائيو التغذية) فقط."""
    team_members = db.session.scalars(
        db.select(User)
        .where(User.role == "medical_team", User.is_active_account == True)
        .order_by(User.full_name)
    ).all()
    return render_template(
        "admin/team.html", team_members=team_members, counts=_people_counts()
    )


def _render_new_member(form=None, focus=None, status=200):
    return (
        render_template(
            "admin/new_team_member.html",
            form=form or {},
            focus=focus,
            member_types=MEMBER_TYPES,
            member_ranks=MEMBER_RANKS,
            member_specialties=MEMBER_SPECIALTIES,
            other_specialty=OTHER_SPECIALTY,
        ),
        status,
    )


@admin_bp.get("/team/new")
def new_team_member():
    return _render_new_member()


def _member_form_error(message, focus=None):
    """كنرجعو نفس الصفحة بنفس البيانات (بدون كلمة المرور) باش ما يضيعش اللي كتب الـ Admin."""
    flash(message, "error")
    form = {
        k: v
        for k, v in request.form.items()
        if k not in ("password", "csrf_token")
    }
    return _render_new_member(form=form, focus=focus, status=400)


@admin_bp.post("/team/new")
def new_team_member_post():
    member_type = request.form.get("member_type", "").strip()
    if member_type not in MEMBER_TYPES:
        return _member_form_error("اختر نوع العضو أولاً (طبيب أو أخصائي تغذية).", focus="member_type")

    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    specialty = request.form.get("specialty", "").strip()
    specialty_other = request.form.get("specialty_other", "").strip()
    member_rank = request.form.get("member_rank", "").strip()
    sub_specialty = request.form.get("sub_specialty", "").strip()
    license_number = clean_digits(request.form.get("license_number", "").strip())
    country = request.form.get("country", "").strip()
    city = request.form.get("city", "").strip()
    country_code = request.form.get("country_code", "").strip()
    local_number = clean_digits(request.form.get("local_number", "").strip())
    years_experience = request.form.get("years_experience", "").strip()
    certificates = request.form.get("certificates", "").strip()
    bio = request.form.get("bio", "").strip()
    password = request.form.get("password", "")

    # اختياري
    languages = request.form.get("languages", "").strip()
    workplace = request.form.get("workplace", "").strip()
    additional_interests = request.form.get("additional_interests", "").strip()
    professional_links = request.form.get("professional_links", "").strip()

    # التخصص: من قائمة النوع المختار، أو "أخرى" + نص حر
    if specialty == OTHER_SPECIALTY:
        if not specialty_other:
            return _member_form_error("يرجى كتابة التخصص في الحقل المخصص لذلك.", focus="specialty_other")
        specialty = specialty_other
    elif specialty and specialty not in MEMBER_SPECIALTIES[member_type]:
        return _member_form_error("التخصص المختار لا يناسب نوع العضو.", focus="specialty")

    if member_rank and member_rank not in MEMBER_RANKS[member_type]:
        return _member_form_error("الرتبة المختارة لا تناسب نوع العضو.", focus="member_rank")

    required_fields = {
        "الاسم الكامل": full_name,
        "البريد الإلكتروني": email,
        "التخصص": specialty,
        "الرتبة": member_rank,
        "الدولة": country,
        "المدينة": city,
        "رقم الهاتف": local_number,
        "سنوات الخبرة": years_experience,
        "الشهادات / التراخيص": certificates,
        "نبذة مهنية": bio,
        "كلمة المرور": password,
    }
    # رقم الترخيص إلزامي للأطباء، واختياري لأخصائيي التغذية (رقم القيد المهني)
    if member_type == "doctor":
        required_fields["رقم الترخيص الطبي"] = license_number
    missing = [label for label, value in required_fields.items() if not value]
    if missing:
        return _member_form_error("الحقول التالية إلزامية: " + "، ".join(missing))

    for error, focus in (
        (validate_digits_only(local_number, "رقم الهاتف", min_len=6, max_len=14), "local_number"),
        (
            validate_digits_only(license_number, "رقم الترخيص", min_len=3, max_len=20) if license_number else None,
            "license_number",
        ),
        (validate_full_name(full_name), "full_name"),
        (None if is_valid_email(email) else "صيغة البريد الإلكتروني غير صحيحة.", "email"),
        (validate_password(password), "password"),
    ):
        if error:
            return _member_form_error(error, focus=focus)

    if db.session.scalar(db.select(User).where(User.email == email)):
        return _member_form_error("هذا البريد الإلكتروني مستخدم من قبل.", focus="email")

    member = User(
        full_name=full_name,
        email=email,
        phone=normalize_whatsapp_number(combine_country_code_and_local(country_code, local_number)),
        specialty=specialty,
        sub_specialty=sub_specialty or None,
        member_type=member_type,
        member_rank=member_rank,
        license_number=license_number or None,
        country=country,
        city=city,
        years_experience=int(years_experience) if years_experience.isdigit() else None,
        certificates=certificates,
        bio=bio,
        languages=languages or None,
        workplace=workplace or None,
        additional_interests=additional_interests or None,
        professional_links=professional_links or None,
        role="medical_team",
        account_status="approved",
        is_active_account=True,  # كيتفعل مباشرة، Admin هو لي صاوبه
    )
    member.set_password(password)
    db.session.add(member)
    db.session.flush()  # باش يكون عندنا member.id قبل التسجيل فالسجل
    log_activity(
        "create_team_member",
        "team_member",
        member.id,
        f"إنشاء عضو فريق ({MEMBER_TYPES[member_type]}): {full_name} — {specialty}",
    )
    db.session.commit()

    flash(f"تم إنشاء حساب {full_name} ({MEMBER_TYPES[member_type]}) في الفريق الطبي.", "success")
    return redirect(url_for("admin.team_directory"))


# ---------------------------------------------------------
# إدارة البرامج (Programs) - إضافة/تفعيل بلا لمس الكود
# ---------------------------------------------------------


@admin_bp.get("/programs")
def programs():
    all_programs = db.session.scalars(db.select(Program).order_by(Program.id)).all()
    # عدد الحالات المرتبطة بكل برنامج (باش الـ Admin يعرف واش يقدر يحذفو)
    rows = db.session.execute(
        db.select(Case.program_id, db.func.count()).group_by(Case.program_id)
    ).all()
    case_counts = {program_id: count for program_id, count in rows}
    return render_template("admin/programs.html", programs=all_programs, case_counts=case_counts)


@admin_bp.post("/programs")
def programs_post():
    name = request.form.get("name", "").strip()
    if not name:
        flash("يجب إدخال اسم البرنامج.", "error")
        return redirect(url_for("admin.programs"))
    if db.session.scalar(db.select(Program).where(Program.name == name)):
        flash("هذا البرنامج موجود من قبل.", "error")
        return redirect(url_for("admin.programs"))
    new_program = Program(name=name, is_active=True)
    db.session.add(new_program)
    db.session.flush()
    log_activity("add_program", "program", new_program.id, f"إضافة برنامج: {name}")
    db.session.commit()
    flash("تم إضافة البرنامج.", "success")
    return redirect(url_for("admin.programs"))


@admin_bp.post("/programs/<int:program_id>/toggle")
def toggle_program(program_id):
    program = db.session.get(Program, program_id)
    if program:
        program.is_active = not program.is_active
        state = "تفعيل" if program.is_active else "إيقاف"
        log_activity("toggle_program", "program", program.id, f"{state} البرنامج: {program.name}")
        db.session.commit()
    return redirect(url_for("admin.programs"))


@admin_bp.post("/programs/<int:program_id>/delete")
def delete_program(program_id):
    """حذف نهائي لبرنامج. ممنوع إلا كانت عندو حالات (باش ما نضيعوش بيانات)، وقتها كنقترحو الإيقاف."""
    program = db.session.get(Program, program_id)
    if not program:
        flash("البرنامج غير موجود.", "error")
        return redirect(url_for("admin.programs"))

    case_count = db.session.scalar(
        db.select(db.func.count()).select_from(Case).where(Case.program_id == program.id)
    )
    if case_count:
        flash(
            f"لا يمكن حذف البرنامج «{program.name}» لأنه مرتبط بـ {case_count} حالة. "
            "يمكنك إيقافه بدلاً من حذفه.",
            "error",
        )
        return redirect(url_for("admin.programs"))

    name = program.name
    program_pk = program.id
    db.session.delete(program)
    log_activity("delete_program", "program", program_pk, f"حذف برنامج: {name}")
    db.session.commit()
    flash(f"تم حذف البرنامج «{name}».", "success")
    return redirect(url_for("admin.programs"))


# ---------------------------------------------------------
# الحالات: عرض + تعيين فريق (Case Assignment)
# نقدر نعينو أكثر من عضو لنفس الحالة (بحال طبيبين)
# ---------------------------------------------------------


@admin_bp.get("/cases/<int:case_id>")
def case_detail(case_id):
    case = db.session.get(Case, case_id)
    if not case:
        flash("الحالة غير موجودة.", "error")
        return redirect(url_for("admin.dashboard"))

    # هنا فقط أعضاء الفريق الطبي (medical_team) - ماشي الأطباء
    # الطبيب اللي سجّل الحالة لا يظهر في لائحة التعيين
    team_members = db.session.scalars(
        db.select(User).where(
            User.role == "medical_team", User.is_active_account == True
        )
    ).all()
    assigned_ids = {a.team_member_id for a in case.assignments}
    assigned_members = [
        a.team_member
        for a in sorted(case.assignments, key=lambda a: a.assigned_at)
        if a.team_member
    ]
    last_assigned_at = max((a.assigned_at for a in case.assignments), default=None)

    # آخر رسالة واردة من المريض + اقتراح النظام (بناءً على كلمات مفتاحية)
    # هادشي اقتراح فقط - الحالة الفعلية (case.status) كتبقى يدوية بالكامل
    last_inbound = db.session.scalar(
        db.select(WhatsAppMessage)
        .where(WhatsAppMessage.case_id == case.id, WhatsAppMessage.direction == "inbound")
        .order_by(WhatsAppMessage.created_at.desc())
    )
    suggested_status = classify_whatsapp_reply(last_inbound.body) if last_inbound else None

    return render_template(
        "admin/case_detail.html",
        case=case,
        team_members=team_members,
        assigned_ids=assigned_ids,
        assigned_members=assigned_members,
        last_assigned_at=last_assigned_at,
        saved=request.args.get("saved"),
        last_inbound=last_inbound,
        suggested_status=suggested_status,
        case_history=db.session.scalars(
            db.select(ActivityLog)
            .where(ActivityLog.target_type == "case", ActivityLog.target_id == case.id)
            .order_by(ActivityLog.created_at.desc())
        ).all(),
    )


@admin_bp.post("/cases/<int:case_id>/assign")
def assign_case(case_id):
    case = db.session.get(Case, case_id)
    if not case:
        flash("الحالة غير موجودة.", "error")
        return redirect(url_for("admin.dashboard"))

    # كنقبلو غير أعضاء الفريق الطبي النشطين (حماية من معرفات غير صالحة أو مزورة)
    valid_members = {
        m.id: m
        for m in db.session.scalars(
            db.select(User).where(User.role == "medical_team", User.is_active_account == True)
        ).all()
    }
    selected = []
    for raw in request.form.getlist("team_member_ids"):
        try:
            member_id = int(raw)
        except ValueError:
            continue
        if member_id in valid_members and member_id not in selected:
            selected.append(member_id)

    # كنمسحو التعيينات القديمة ونعاودو نصاوبوهم بحسب الاختيار الجديد
    CaseAssignment.query.filter_by(case_id=case.id).delete()
    for member_id in selected:
        db.session.add(CaseAssignment(case_id=case.id, team_member_id=member_id))
    names = "، ".join(valid_members[i].full_name for i in selected)
    log_activity(
        "assign_team",
        "case",
        case.id,
        f"تعيين الفريق: {names}" if selected else "إزالة كل التعيينات من الحالة",
    )
    db.session.commit()

    flash("تم حفظ تعيين الفريق لهذه الحالة.", "success")
    return redirect(url_for("admin.case_detail", case_id=case.id, saved="team", _anchor="team-assignment"))


# ---------------------------------------------------------
# تغيير الحالة يدوياً (للاختبار المحلي بدون Twilio، أو تدخل
# يدوي من الإدارة عند الحاجة)
# ---------------------------------------------------------


@admin_bp.post("/cases/<int:case_id>/status")
def update_case_status(case_id):
    case = db.session.get(Case, case_id)
    if not case:
        flash("الحالة غير موجودة.", "error")
        return redirect(url_for("admin.dashboard"))

    new_status = request.form.get("status")
    if new_status not in {"pending", "confirmed", "declined", "inquiry"}:
        flash("حالة غير صالحة.", "error")
        return redirect(url_for("admin.case_detail", case_id=case.id))

    old_status = case.status
    case.status = new_status
    log_activity("change_status", "case", case.id, f"{old_status} → {new_status}")
    db.session.commit()
    flash("تم تحديث حالة الملف.", "success")
    return redirect(url_for("admin.case_detail", case_id=case.id, saved="status", _anchor="case-status"))



# ---------------------------------------------------------
# المسؤولون (Admins): لائحة + إنشاء Admin ثاني
# كل Admin عندو حساب مستقل، وكل عملية كتتسجل باسمو فسجل النشاطات
# ---------------------------------------------------------


@admin_bp.get("/admins")
def admins_list():
    admins = db.session.scalars(
        db.select(User).where(User.role == "admin").order_by(User.created_at)
    ).all()
    return render_template("admin/admins.html", admins=admins)


@admin_bp.post("/admins/new")
def new_admin_post():
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if not full_name or not email or not password:
        flash("يجب تعبئة الاسم والبريد وكلمة المرور.", "error")
        return redirect(url_for("admin.admins_list"))

    for error in (validate_full_name(full_name), validate_password(password)):
        if error:
            flash(error, "error")
            return redirect(url_for("admin.admins_list"))

    if not is_valid_email(email):
        flash("صيغة البريد الإلكتروني غير صحيحة.", "error")
        return redirect(url_for("admin.admins_list"))

    if db.session.scalar(db.select(User).where(User.email == email)):
        flash("هذا البريد الإلكتروني مستخدم من قبل.", "error")
        return redirect(url_for("admin.admins_list"))

    new_admin = User(
        full_name=full_name,
        email=email,
        role="admin",
        account_status="approved",
        is_active_account=True,
    )
    new_admin.set_password(password)
    db.session.add(new_admin)
    db.session.flush()
    log_activity("create_admin", "admin", new_admin.id, f"إنشاء حساب Admin جديد: {full_name}")
    db.session.commit()

    flash(f"تم إنشاء حساب الـ Admin: {full_name}.", "success")
    return redirect(url_for("admin.admins_list"))


# ---------------------------------------------------------
# إدارة المسؤولين: فقط للحساب الرئيسي (ADMIN_EMAIL)
# تعديل البيانات / إلغاء / إعادة تفعيل — وكل عملية كتتسجل فسجل النشاطات
# ---------------------------------------------------------


def _principal_target(user_id):
    """كترجع (admin_المستهدف, رد_الخطأ). رد الخطأ None إلا كان كل شي مسموح."""
    if not current_user.is_principal_admin:
        flash("هذا الإجراء مسموح فقط للحساب الرئيسي.", "error")
        return None, redirect(url_for("admin.admins_list"))
    target = db.session.get(User, user_id)
    if not target or target.role != "admin":
        flash("الـ Admin غير موجود.", "error")
        return None, redirect(url_for("admin.admins_list"))
    if target.is_principal_admin:
        flash("لا يمكن تعديل أو إلغاء الحساب الرئيسي من هنا.", "error")
        return None, redirect(url_for("admin.admins_list"))
    return target, None


@admin_bp.post("/admins/<int:user_id>/edit")
def edit_admin(user_id):
    target, error = _principal_target(user_id)
    if error:
        return error
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    new_password = request.form.get("password", "")

    for err in (validate_full_name(full_name), None if is_valid_email(email) else "صيغة البريد الإلكتروني غير صحيحة."):
        if err:
            flash(err, "error")
            return redirect(url_for("admin.admins_list"))
    if new_password:
        pw_error = validate_password(new_password)
        if pw_error:
            flash(pw_error, "error")
            return redirect(url_for("admin.admins_list"))
    taken = db.session.scalar(db.select(User).where(User.email == email, User.id != target.id))
    if taken:
        flash("هذا البريد الإلكتروني مستخدم من قبل.", "error")
        return redirect(url_for("admin.admins_list"))

    changes = []
    if full_name != target.full_name:
        changes.append(f"الاسم: {target.full_name} ← {full_name}")
        target.full_name = full_name
    if email != target.email:
        changes.append(f"البريد: {target.email} ← {email}")
        target.email = email
    if new_password:
        target.set_password(new_password)
        changes.append("كلمة المرور")
    if not changes:
        flash("لم يتغير شيء.", "success")
        return redirect(url_for("admin.admins_list"))
    log_activity("update_admin", "admin", target.id, "تعديل: " + "، ".join(changes))
    db.session.commit()
    flash(f"تم تحديث بيانات {target.full_name}.", "success")
    return redirect(url_for("admin.admins_list"))


@admin_bp.post("/admins/<int:user_id>/deactivate")
def deactivate_admin(user_id):
    target, error = _principal_target(user_id)
    if error:
        return error
    target.is_active_account = False
    target.account_status = "deactivated"
    log_activity("deactivate_admin", "admin", target.id, f"إلغاء حساب Admin: {target.full_name}")
    db.session.commit()
    flash(f"تم إلغاء حساب {target.full_name}.", "success")
    return redirect(url_for("admin.admins_list"))


@admin_bp.post("/admins/<int:user_id>/reactivate")
def reactivate_admin(user_id):
    target, error = _principal_target(user_id)
    if error:
        return error
    target.is_active_account = True
    target.account_status = "approved"
    log_activity("reactivate_admin", "admin", target.id, f"إعادة تفعيل Admin: {target.full_name}")
    db.session.commit()
    flash(f"تمت إعادة تفعيل {target.full_name}.", "success")
    return redirect(url_for("admin.admins_list"))


# ---------------------------------------------------------
# سجل النشاطات: شكون دار شنو ووقتاش (الأحدث أولاً) + فلتر بالـ Admin
# ---------------------------------------------------------

ACTION_LABELS = {
    "update_admin": "تعديل بيانات Admin",
    "deactivate_admin": "إلغاء Admin",
    "reactivate_admin": "إعادة تفعيل Admin",
    "approve_doctor": "قبول طبيب",
    "reject_doctor": "رفض طبيب",
    "deactivate_doctor": "إلغاء تفعيل طبيب",
    "create_team_member": "إنشاء عضو فريق",
    "create_admin": "إنشاء Admin",
    "change_status": "تغيير حالة ملف",
    "assign_team": "تعيين فريق",
    "add_program": "إضافة برنامج",
    "toggle_program": "تفعيل/إيقاف برنامج",
    "deactivate_member": "إلغاء تفعيل عضو فريق",
    "reset_password": "إعادة تعيين كلمة مرور",
    "send_notification": "إرسال إشعار",
    "delete_program": "حذف برنامج",
}

ACTIVITY_LIMIT = 1000


@admin_bp.get("/activity")
def activity_log():
    admin_filter = request.args.get("admin_id", type=int)

    query = db.select(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(ACTIVITY_LIMIT)
    if admin_filter:
        query = query.where(ActivityLog.admin_id == admin_filter)

    logs = db.session.scalars(query).all()
    admins = db.session.scalars(db.select(User).where(User.role == "admin")).all()
    return render_template(
        "admin/activity.html",
        logs=logs,
        admins=admins,
        admin_filter=admin_filter,
        action_labels=ACTION_LABELS,
        section_labels=SECTION_LABELS,
        activity_limit=ACTIVITY_LIMIT,
    )
