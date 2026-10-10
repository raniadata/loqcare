"""
غلاف بسيط فوق Twilio باش الكود ديال الـ Views يبقى نظيف.

ملاحظة مهمة: هاد الملف ماخدامش حالياً لأن معندناش بعد Twilio Access
(Account SID / Auth Token / WhatsApp number) من لقمان. ملي توصل،
غير عمري .env وهاد الكود غادي يخدم بلا ما تحتاجي تبدلي والو فالـ routes.
"""

import os
from app import db
from app.models import WhatsAppMessage


def _get_twilio_client():
    from twilio.rest import Client

    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    if not account_sid or not auth_token:
        return None
    return Client(account_sid, auth_token)


def send_whatsapp_offer(case):
    """كتبعث رسالة العرض الأولية للمريض بعد ما الطبيب يسجل الإحالة."""
    client = _get_twilio_client()
    from_number = os.getenv("TWILIO_WHATSAPP_NUMBER")

    body = (
        f"مرحباً {case.patient.full_name}، "
        f"تم تسجيلك في برنامج {case.program.name} مع LOQ CARE. "
        "هل توافق على المتابعة؟ (نعم / لا)"
    )

    provider_sid = None
    if client and from_number:
        message = client.messages.create(
            from_=from_number,
            to=f"whatsapp:{case.patient.whatsapp_number}",
            body=body,
        )
        provider_sid = message.sid

    db.session.add(
        WhatsAppMessage(
            case_id=case.id,
            direction="outbound",
            body=body,
            provider_sid=provider_sid,
        )
    )
    db.session.commit()
