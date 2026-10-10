# LOQ CARE — Phase 1 MVP

تطبيق Flask يغطي المرحلة الأولى المتفق عليها مع لقمان:

```
Doctor (self-register → Pending → Admin approval)
   → Referral / Case
   → Admin assigns team (أكثر من عضو لنفس الحالة)
   → WhatsApp (Twilio) — outbound offer + inbound keyword-based intent

B2C (public form, no login)
   → Case (source="b2c")
   → نفس قاعدة البيانات المركزية
```

## الحماية المطبقة

- **CSRF Protection** (Flask-WTF) على كل الـ POST forms
- **Twilio webhook signature validation** — رفض أي طلب ماشي من Twilio
- **Honeypot** + **Rate Limiting** على الفورم العمومي (B2C)
- **Rate Limiting** على التسجيل والدخول
- **WhatsApp number normalization** — توحيد الأرقام لصيغة E.164 (+212...)
- **Input validation** — الاسم، البريد، كلمة المرور (8 أحرف minimum)، رقم الواتساب
- كلمات المرور مشفرة، صلاحيات محمية فالـ Backend (`role_required`)

## النشر على Render

1. ادفعي المشروع لـ GitHub repo
2. فـ Render: New → Web Service → اختاري الـ repo
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `gunicorn run:app` (موجود جاهز فـ `Procfile`)
5. زيدي Environment Variables (نفس محتوى `.env`): `SECRET_KEY`, `DATABASE_URL` (PostgreSQL من Render)، `ADMIN_EMAIL`, `ADMIN_PASSWORD`، `TWILIO_*` ملي توصلو
6. صاوبي PostgreSQL database من Render وربطيها بـ `DATABASE_URL`

## التشغيل محلياً

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python run.py
```

كيتفتح على http://127.0.0.1:5000

عند أول تشغيل، كيتصاوب حساب Admin أوتوماتيكياً بالإيميل وكلمة السر
اللي حطيتيهم فـ `.env` (`ADMIN_EMAIL` / `ADMIN_PASSWORD`).

## البنية

```
app/
  models.py            # User, Program, Patient, Case, CaseAssignment, WhatsAppMessage
  auth/routes.py        # تسجيل الطبيب (self-service) + login/logout
  admin/routes.py        # موافقة الأطباء، إضافة فريق طبي، البرامج، تعيين الحالات
  doctor/routes.py       # لوحة الطبيب + تسجيل إحالة جديدة
  webhook/
    routes.py            # /webhook/whatsapp — استقبال ردود Twilio
    twilio_client.py      # إرسال رسالة العرض الأولية (send_whatsapp_offer)
  templates/             # كلها RTL بالعربية
  static/css/style.css    # الألوان placeholder، بدليها بألوان LOQ CARE الرسمية
```

## نقاط باقي محتاجين نعمروها من لقمان (ماشي كود ناقص، معلومات ناقصة)

- [ ] Twilio Account SID / Auth Token / WhatsApp number → `.env`
- [ ] Message Template (نص رسالة العرض بالضبط) — دابا مكتوبة generic فـ `twilio_client.py`
- [ ] الألوان والخط الرسمي لـ LOQ CARE → `static/css/style.css` (فوق فـ `:root`)
- [ ] هل خاص تأكيد إضافي على حقول الـ Referral (غير الاسم/الواتساب/البرنامج/ملاحظات)

## اللي ماشي داخل هاد الـ MVP (Phase 2 أو خارج النطاق)

- لوحة الفريق الطبي (Medical Team Dashboard) والمتابعة السريرية (القياسات، HbA1c...)
- Internal Notifications و Internal Case Chat
- تشخيص آلي أو قرار طبي مستقل (ممنوع نهائياً حسب الـ Scope)

## الحماية الأساسية المطبقة

- Rate limiting بسيط على التسجيل والدخول (`Flask-Limiter`)
- كلمات المرور مشفرة (`Werkzeug` / bcrypt-style hashing)
- صلاحيات محمية على مستوى الـ Backend (`role_required`)، ماشي غير إخفاء زر فالواجهة

## الدفعة 2 (فلاتر ووضوح)

- **فلاتر الأعمدة** (`static/js/app.js`): أي جدول فيه `data-filterable` وأعمدته فيها `data-filter="text|select|date"` كيتزاد ليه تلقائياً لوحة فلاتر (أكثر من فلتر فنفس الوقت + بحث عام + مسح). الفلاتر كتنحفظ فـ sessionStorage.
- **نافذة التأكيد**: أي `<form data-confirm="...">` كيطلع ليه تأكيد قبل الإرسال.
- **حذف البرنامج**: ممنوع إلا كانت عندو حالات (كنقترحو الإيقاف).
- **زر الإشعار**: أي عنصر فيه `data-notify-url` كيفتح نافذة الإرسال.
- **الأطباء المحيلون ≠ الفريق الطبي**: `/admin/doctors` و `/admin/team`.
- **نوع العضو**: `User.member_type` (`doctor` | `nutritionist`) و `User.member_rank`. الأعمدة الجديدة كتتزاد تلقائياً فـ `_ensure_schema_updates()` على DB القديمة (SQLite/PostgreSQL)، والأعضاء القدام كيتصنفو من التخصص.
- **مؤشرات الطبيب**: إجمالي المرضى المُحالين / بدأوا البرنامج (confirmed) / تحتاج إجراء (inquiry أو pending لـ 3 أيام فأكثر، الثابت `NEEDS_ACTION_PENDING_DAYS` فـ `doctor/routes.py`).
