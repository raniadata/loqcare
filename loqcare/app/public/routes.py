"""الفورم العمومي (B2C) — المريض كيسجل راسو مباشرة بلا ما يمر عبر طبيب.

الحماية المطبقة (كيفما متفق عليه فالـ Scope):
  1. Honeypot — حقل مخفي، إلا تعمر معناها bot
  2. Rate Limiting — تحديد عدد المحاولات من نفس الـ IP
  3. Input validation — التحقق من الاسم ورقم الواتساب
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from app import db, limiter
from app.models import Program, Patient, Case
from app.utils import (
    normalize_whatsapp_number,
    is_valid_whatsapp_number,
    validate_full_name,
    combine_country_code_and_local,
    clean_digits,
    validate_digits_only,
)

public_bp = Blueprint("public", __name__, url_prefix="/register-patient")


@public_bp.get("/")
def patient_form():
    active_programs = db.session.scalars(
        db.select(Program).where(Program.is_active == True)
    ).all()
    return render_template("public/patient_form.html", programs=active_programs)


@public_bp.post("/")
@limiter.limit("3 per hour; 10 per day")  # حماية ضد الـ Spam
def patient_form_post():
    # --- 1. Honeypot: حقل مخفي، المستخدم العادي ما كيشوفوش ---
    if request.form.get("website", "").strip():
        current_app.logger.warning("محاولة spam محجوبة عبر honeypot")
        # كنرجعو نفس رسالة النجاح باش الـ bot ما يعرفش أنه تحجب
        flash("تم استلام طلبك بنجاح. سنتواصل معك قريباً.", "success")
        return redirect(url_for("public.patient_form"))

    full_name = request.form.get("full_name", "").strip()
    country_code = request.form.get("country_code", "").strip()
    local_number = clean_digits(request.form.get("local_number", "").strip())
    raw_number = combine_country_code_and_local(country_code, local_number)
    program_id = request.form.get("program_id")
    notes = request.form.get("notes", "").strip()

    # --- 2. Validation ---
    if not full_name or not local_number or not program_id:
        flash("يرجى تعبئة الاسم، رقم الواتساب، والبرنامج.", "error")
        return redirect(url_for("public.patient_form"))

    name_error = validate_full_name(full_name)
    if name_error:
        flash(name_error, "error")
        return redirect(url_for("public.patient_form"))

    digits_error = validate_digits_only(local_number, "رقم الواتساب", min_len=6, max_len=14)
    if digits_error:
        flash(digits_error, "error")
        return redirect(url_for("public.patient_form"))

    whatsapp_number = normalize_whatsapp_number(raw_number)
    if not is_valid_whatsapp_number(whatsapp_number):
        flash("رقم الواتساب غير صالح. مثال صحيح: 0703040506", "error")
        return redirect(url_for("public.patient_form"))

    program = db.session.get(Program, int(program_id))
    if not program or not program.is_active:
        flash("البرنامج المختار غير متاح حالياً.", "error")
        return redirect(url_for("public.patient_form"))

    # --- 3. التسجيل فنفس قاعدة البيانات المركزية ---
    patient = Patient(full_name=full_name, whatsapp_number=whatsapp_number)
    db.session.add(patient)
    db.session.flush()

    case = Case(
        patient_id=patient.id,
        program_id=program.id,
        doctor_id=None,  # ماكاينش طبيب، جا مباشرة من الموقع
        source="b2c",
        status="pending",
        notes=notes,
    )
    db.session.add(case)
    db.session.commit()

    flash("تم استلام طلبك بنجاح. سنتواصل معك قريباً عبر الواتساب.", "success")
    return redirect(url_for("public.patient_form"))
