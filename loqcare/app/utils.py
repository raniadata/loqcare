"""دوال مساعدة مشتركة: توحيد أرقام الواتساب والتحقق من المدخلات."""

import re

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")

MIN_PASSWORD_LENGTH = 8


def normalize_whatsapp_number(raw):
    """تنظيف رقم الواتساب بدون افتراض أي رمز دولة معيّن.

    بما أن عملاء العيادة ممكن يكونوا من دول مختلفة (ماشي المغرب فقط)،
    كنحتفظو بالرقم كيفما دخّله المستخدم، وكنشيلو فقط المسافات والشرطات.
    كنوحدو غير صيغة "00" الدولية إلى "+".

    مهم: لضمان تطابق صحيح مع Twilio (اللي كيرجع الرقم بصيغة دولية كاملة
    دائماً)، يُفضَّل أن يُدخِل المستخدم الرقم مع رمز الدولة (+212...، +971...).
    """
    if not raw:
        return ""

    cleaned = re.sub(r"[^\d+]", "", str(raw))
    if not cleaned:
        return ""

    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]

    return cleaned


def is_valid_whatsapp_number(number):
    """تحقق بسيط: بين 8 و15 رقم (مع أو بدون + فالبداية)."""
    if not number:
        return False
    digits = number[1:] if number.startswith("+") else number
    return digits.isdigit() and 8 <= len(digits) <= 15


def combine_country_code_and_local(country_code, local_number):
    """كتجمع رمز الدولة مع الرقم المحلي، وكتحيد أي صفر زائد فبداية الرقم المحلي.

    مثال: +212 + "0612345678" → "+212612345678" (كتحيد الصفر تلقائياً)
           +212 + "612345678"  → "+212612345678" (بلا تغيير)

    هادشي كيحمي من غلطة شائعة: المستخدم كيختار رمز الدولة من القائمة
    وكيكتب الرقم المحلي بصيغته العادية (بالصفر)، فالنتيجة كانت كتولي
    +21206... (خطأ) بدل +2126... (صحيح).
    """
    country_code = (country_code or "").strip()
    local_number = (local_number or "").strip()
    # نحيدو صفر واحد أو أكثر من البداية (بعض المستخدمين كيكتبو 00 بالغلط)
    local_number = re.sub(r"^0+", "", local_number)
    return f"{country_code}{local_number}"


_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def clean_digits(value):
    """كتحول الأرقام العربية-الهندية (٠١٢...) إلى 0123... وكتحيد الفراغات والشرطات.

    كترجع النص المنظف؛ التحقق من أنه أرقام فقط كيتدار فـ validate_digits_only.
    """
    value = (value or "").translate(_ARABIC_DIGITS)
    return re.sub(r"[\s\-]", "", value)


def validate_digits_only(value, label, min_len=None, max_len=None):
    """كترجع رسالة الخطأ (بالعربية) إلا كانت القيمة فيها حروف أو طولها غير مناسب، وإلا None.

    كتستعمل لرقم الهاتف ورقم الترخيص الطبي (أرقام فقط).
    """
    cleaned = clean_digits(value)
    if not cleaned.isascii() or not cleaned.isdigit():
        return f"{label} يجب أن يحتوي على أرقام فقط (بدون حروف أو رموز)."
    if min_len and len(cleaned) < min_len:
        return f"{label} قصير جداً (الحد الأدنى {min_len} أرقام)."
    if max_len and len(cleaned) > max_len:
        return f"{label} طويل جداً (الحد الأقصى {max_len} رقماً)."
    return None


def is_valid_email(email):
    return bool(EMAIL_RE.match(email or ""))


def validate_password(password):
    """كترجع رسالة الخطأ، أو None إلا كانت كلمة المرور صالحة."""
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        return f"كلمة المرور يجب أن تكون {MIN_PASSWORD_LENGTH} أحرف على الأقل."
    return None


def validate_full_name(name):
    """كترجع رسالة الخطأ، أو None إلا كان الاسم صالح."""
    cleaned = (name or "").strip()
    if len(cleaned) < 3:
        return "الاسم الكامل يجب أن يكون 3 أحرف على الأقل."
    return None


# ---------------------------------------------------------
# تصنيف رد المريض على واتساب (Keyword-based، ماشي AI)
# مستعملة كـ "اقتراح" فقط - ماشي لتغيير الحالة تلقائياً
# ---------------------------------------------------------

CONFIRM_KEYWORDS = {"نعم", "موافق", "أوافق", "ok", "okay", "yes"}
DECLINE_KEYWORDS = {"لا", "غير مهتم", "لا شكرا", "لا شكراً", "no"}


def classify_whatsapp_reply(body):
    """كترجع الاقتراح: confirmed / declined / inquiry - بناءً على كلمات مفتاحية بسيطة."""
    normalized = (body or "").strip().lower()
    if normalized in CONFIRM_KEYWORDS:
        return "confirmed"
    if normalized in DECLINE_KEYWORDS:
        return "declined"
    return "inquiry"


# ---------------------------------------------------------
# سجل النشاطات: كيسجل شكون (الـ Admin الحالي) دار شنو
# ---------------------------------------------------------


def log_activity(action, target_type, target_id=None, details=None):
    """كيسجل عملية فسجل النشاطات باسم الـ Admin المسجّل دخولو دابا.

    الاستعمال: log_activity("change_status", "case", case.id, "pending → confirmed")
    كنستوردو المكتبات هنا (داخل الدالة) باش نتفاداو الـ circular imports.
    """
    from flask_login import current_user
    from app import db
    from app.models import ActivityLog

    if not getattr(current_user, "is_authenticated", False):
        return

    db.session.add(
        ActivityLog(
            admin_id=current_user.id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details,
        )
    )
    # ما كنديروش commit هنا: الـ route هو اللي كيدير commit وحدة لكل العملية


# ---------------------------------------------------------
# رسم بياني دائري (Pie Chart) بسيط بـ CSS فقط (conic-gradient)
# بلا أي مكتبة JS خارجية
# ---------------------------------------------------------

PIE_CHART_COLORS = {
    "pending": "#d97706",
    "confirmed": "#16a34a",
    "declined": "#D24E42",
    "inquiry": "#2563eb",
}

PIE_CHART_LABELS = {
    "pending": "قيد الانتظار",
    "confirmed": "مؤكدة",
    "declined": "مرفوضة",
    "inquiry": "استفسار",
}


def build_pie_chart(status_counts):
    """كتبني CSS conic-gradient style + legend data لتوزيع حالات الإحالات.

    status_counts: dict بحال {"pending": 5, "confirmed": 3, "declined": 1, "inquiry": 2}
    كترجع: (gradient_css_string, legend_list)
    """
    total = sum(status_counts.values()) or 1
    order = ["pending", "confirmed", "declined", "inquiry"]

    segments = []
    legend = []
    angle = 0.0
    for key in order:
        count = status_counts.get(key, 0)
        percent = (count / total) * 100
        start = angle
        end = angle + percent * 3.6  # درجة من 360
        if count > 0:
            segments.append(f"{PIE_CHART_COLORS[key]} {start:.2f}deg {end:.2f}deg")
        angle = end
        legend.append(
            {
                "key": key,
                "label": PIE_CHART_LABELS[key],
                "count": count,
                "percent": round(percent, 1),
                "color": PIE_CHART_COLORS[key],
            }
        )

    if not segments:
        gradient = "#e5e7eb 0deg 360deg"
    else:
        gradient = ", ".join(segments)

    return f"conic-gradient({gradient})", legend


# ---------------------------------------------------------
# رمز الدولة الافتراضي حسب موقع الزائر (#1 / #21)
# كنقراو رمز الدولة (ISO) من header كيحطو الـ hosting/CDN (Render كيستعمل Cloudflare:
# CF-IPCountry). ما كنعتمدوش على خدمة خارجية، وإلا ما لقيناش header كنرجعو للمغرب.
# المستخدم يقدر دايماً يبدل الرمز يدوياً من القائمة.
# ---------------------------------------------------------

DEFAULT_COUNTRY_CODE = "+212"

# ISO-3166 alpha-2 → رمز الاتصال (نفس الدول الموجودة فقائمة _macros.html)
ISO_TO_DIAL = {
    "MA": "+212", "SA": "+966", "AE": "+971", "EG": "+20", "DZ": "+213", "TN": "+216",
    "LY": "+218", "SD": "+249", "IQ": "+964", "JO": "+962", "LB": "+961", "SY": "+963",
    "PS": "+970", "KW": "+965", "QA": "+974", "BH": "+973", "OM": "+968", "YE": "+967",
    "MR": "+222", "SO": "+252", "DJ": "+253", "KM": "+269", "TR": "+90", "US": "+1",
    "GB": "+44", "FR": "+33", "DE": "+49", "ES": "+34", "IT": "+39", "NL": "+31",
    "BE": "+32", "CH": "+41", "SE": "+46", "CA": "+1", "PK": "+92", "IN": "+91",
    "BD": "+880", "ID": "+62", "MY": "+60", "CN": "+86", "SN": "+221", "ML": "+223",
    "NG": "+234", "ZA": "+27", "AU": "+61",
}

# الـ headers اللي كتعطي رمز الدولة (بالترتيب)
_COUNTRY_HEADERS = ("CF-IPCountry", "X-Country-Code", "X-AppEngine-Country", "CloudFront-Viewer-Country")


def detect_country_code(headers):
    """كترجع رمز الاتصال (مثلاً "+90") حسب header الدولة، وإلا DEFAULT_COUNTRY_CODE."""
    for name in _COUNTRY_HEADERS:
        iso = (headers.get(name) or "").strip().upper()
        if iso in ISO_TO_DIAL:
            return ISO_TO_DIAL[iso]
    return DEFAULT_COUNTRY_CODE
