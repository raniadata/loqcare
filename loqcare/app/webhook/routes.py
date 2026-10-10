import os
from flask import Blueprint, request, Response, current_app
from app import db
from app.models import Case, Patient, WhatsAppMessage
from app.utils import normalize_whatsapp_number

webhook_bp = Blueprint("webhook", __name__, url_prefix="/webhook")


def _is_valid_twilio_request():
    """التحقق من أن الطلب جاي فعلاً من Twilio عبر التوقيع (X-Twilio-Signature).

    إلا ماكانش TWILIO_AUTH_TOKEN معمّر (تجربة محلية)، كنسمحو بالطلب
    باش نقدرو نختبرو الـ workflow بلا Twilio حقيقي.
    """
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    if not auth_token:
        current_app.logger.warning(
            "TWILIO_AUTH_TOKEN غير معرّف — تخطي التحقق من التوقيع (وضع التطوير فقط)"
        )
        return True

    try:
        from twilio.request_validator import RequestValidator
    except ImportError:
        return False

    validator = RequestValidator(auth_token)
    signature = request.headers.get("X-Twilio-Signature", "")
    return validator.validate(request.url, request.form.to_dict(), signature)


@webhook_bp.post("/whatsapp")
def whatsapp_incoming():
    """
    Endpoint اللي كنعمروه فـ Twilio كـ Webhook URL ديال الرقم.
    Twilio كيبعت POST فيه From وBody فكل مرة يرد المريض.

    مهم: هاد الـ endpoint ما كيبدلش حالة الملف (Case.status) تلقائياً.
    كيسجل غير الرسالة فقط. تصنيف الرد (نعم/لا/استفسار) كيبان فلوحة
    الإدارة كـ "اقتراح" فقط - الإدارة هي لي كتبدل الحالة يدوياً بعد
    ما تتأكد مع المريض (عادة من رقم آخر للتأكيد).
    """
    if not _is_valid_twilio_request():
        current_app.logger.warning("طلب webhook مرفوض: توقيع Twilio غير صالح")
        return Response("Forbidden", status=403)

    raw_from = request.form.get("From", "").replace("whatsapp:", "")
    from_number = normalize_whatsapp_number(raw_from)
    body = request.form.get("Body", "").strip()

    patient = db.session.scalar(
        db.select(Patient).where(Patient.whatsapp_number == from_number)
    )

    if patient:
        case = db.session.scalar(
            db.select(Case)
            .where(Case.patient_id == patient.id)
            .order_by(Case.created_at.desc())
        )

        if case:
            # كنسجلو الرسالة فقط - بلا ما نبدلو case.status
            db.session.add(
                WhatsAppMessage(case_id=case.id, direction="inbound", body=body)
            )
            db.session.commit()
    else:
        current_app.logger.info("رسالة واردة من رقم غير مسجل: %s", from_number)

    # TwiML رد فارغ — كافي حتى نبنيو رد تلقائي فمرحلة لاحقة
    return Response("<Response></Response>", mimetype="text/xml")
