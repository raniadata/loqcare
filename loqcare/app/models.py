from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db

# =========================================================
#  User: Admin / Doctor / Medical Team - كلهم فنفس الجدول
#  (أسهل للـ Login والصلاحيات، ماشي محتاجين 3 جداول منفصلة)
# =========================================================


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(30))
    password_hash = db.Column(db.String(255), nullable=False)

    # admin | doctor | medical_team
    role = db.Column(db.String(30), nullable=False, default="doctor")

    # نوع العضو داخل الفريق الطبي - نص حر باش الـAdmin يقدر يزيد أنواع جدد
    # بلا ما نبدلو الكود (مثال: "طبيب باطنية"، "أخصائي تغذية إكلينيكية"...)
    specialty = db.Column(db.String(150))
    profile_photo = db.Column(db.String(255))  # اسم الملف فـ static/uploads/profiles/
    sub_specialty = db.Column(db.String(150))  # التخصص الدقيق (لأطباء LOQ CARE)

    # نوع عضو الفريق الطبي: doctor | nutritionist (فارغ لغير medical_team)
    member_type = db.Column(db.String(30))
    # الرتبة/الدرجة (القائمة كتختلف حسب النوع - انظر app/constants.py)
    member_rank = db.Column(db.String(100))

    # --- بيانات مهنية إضافية (حسب وثيقة حقول التسجيل) ---
    hospital_name = db.Column(db.String(200))  # اسم المستشفى (الطبيب المحيل)
    department = db.Column(db.String(150))  # القسم
    license_number = db.Column(db.String(100))  # رقم الترخيص الطبي
    country = db.Column(db.String(100))
    city = db.Column(db.String(100))
    years_experience = db.Column(db.Integer)
    certificates = db.Column(db.Text)  # الشهادات / التراخيص الإضافية
    bio = db.Column(db.Text)  # نبذة تعريفية / مهنية
    languages = db.Column(db.String(200))
    workplace = db.Column(db.String(200))  # مكان العمل (لأعضاء الفريق)
    additional_interests = db.Column(db.Text)  # اهتمامات/تخصصات إضافية
    professional_links = db.Column(db.String(300))  # روابط مهنية (LinkedIn...)

    # الحساب الأولي كيكون pending حتى الـAdmin يوافق عليه
    # pending | approved | rejected
    account_status = db.Column(db.String(20), nullable=False, default="pending")
    is_active_account = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def is_principal_admin(self):
        """الحساب الرئيسي = الـ Admin اللي إيميله هو ADMIN_EMAIL فـ .env (الوحيد اللي يدير باقي المسؤولين)."""
        import os

        principal = os.getenv("ADMIN_EMAIL", "admin@loqcare.com").strip().lower()
        return self.role == "admin" and (self.email or "").lower() == principal

    @property
    def is_doctor(self):
        return self.role == "doctor"

    @property
    def is_medical_team(self):
        return self.role == "medical_team"

    @property
    def member_type_label(self):
        from app.constants import MEMBER_TYPES

        return MEMBER_TYPES.get(self.member_type, "عضو فريق")


# =========================================================
#  Program: البرامج (ضبط السكري، إدارة الوزن...)
#  فجدول منفصل بلا ما تكون الأسماء مكتوبة فالكود مباشرة
# =========================================================


class Program(db.Model):
    __tablename__ = "programs"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False, unique=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


# =========================================================
#  Patient: المريض (بيانات بسيطة، الباقي غادي يزاد فـ Phase 2)
# =========================================================


class Patient(db.Model):
    __tablename__ = "patients"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    whatsapp_number = db.Column(db.String(30), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


# =========================================================
#  Case (Referral): الحالة اللي كيبعثها الطبيب أو كتجي من B2C
# =========================================================


class Case(db.Model):
    __tablename__ = "cases"
    # SQLite: كنفعّلو AUTOINCREMENT باش نقدرو نبداو الترقيم من 115
    __table_args__ = {"sqlite_autoincrement": True}

    # أرقام الحالات كتبدا من 115 (PostgreSQL كيحترم الـ Sequence؛
    # SQLite كنبذرو ليها القيمة فـ _seed_case_numbering داخل app/__init__.py)
    CASE_ID_START = 115
    id = db.Column(
        db.Integer,
        db.Sequence("cases_id_seq", start=CASE_ID_START),
        primary_key=True,
    )

    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False)
    patient = db.relationship("Patient", backref="cases")

    program_id = db.Column(db.Integer, db.ForeignKey("programs.id"), nullable=False)
    program = db.relationship("Program")

    # الطبيب اللي دخل الحالة (null إذا جات من B2C مباشرة)
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    doctor = db.relationship("User", foreign_keys=[doctor_id])

    # doctor_referral | b2c
    source = db.Column(db.String(20), nullable=False, default="doctor_referral")

    # pending | confirmed | declined | inquiry
    status = db.Column(db.String(20), nullable=False, default="pending")

    notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


# =========================================================
#  CaseAssignment: تعيين عضو (أو عدة أعضاء) من الفريق لكل حالة
#  Many-to-Many بين Case وUser (طبيب أو أخصائي)
# =========================================================


class CaseAssignment(db.Model):
    __tablename__ = "case_assignments"

    id = db.Column(db.Integer, primary_key=True)

    case_id = db.Column(db.Integer, db.ForeignKey("cases.id"), nullable=False)
    case = db.relationship("Case", backref="assignments")

    team_member_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    team_member = db.relationship("User")

    assigned_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("case_id", "team_member_id", name="uq_case_member"),
    )


# =========================================================
#  WhatsAppMessage: سجل بسيط للرسائل الصادرة/الواردة (Twilio)
# =========================================================


class WhatsAppMessage(db.Model):
    __tablename__ = "whatsapp_messages"

    id = db.Column(db.Integer, primary_key=True)

    case_id = db.Column(db.Integer, db.ForeignKey("cases.id"), nullable=True)
    case = db.relationship("Case", backref="whatsapp_messages")

    # outbound | inbound
    direction = db.Column(db.String(10), nullable=False)
    body = db.Column(db.Text, nullable=False)
    provider_sid = db.Column(db.String(100))  # Twilio Message SID

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


# =========================================================
#  ActivityLog: سجل النشاطات - شكون (أي Admin) دار شنو وعلى أي ملف/طبيب
#  كيتسجل فيه كل قرار مهم باش يبقى عندنا مرجع واضح لكل عملية
# =========================================================


class ActivityLog(db.Model):
    __tablename__ = "activity_logs"

    id = db.Column(db.Integer, primary_key=True)

    # الـ Admin اللي دار العملية
    admin_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    admin = db.relationship("User", foreign_keys=[admin_id])

    # نوع العملية: approve_doctor | reject_doctor | deactivate_doctor |
    # create_team_member | create_admin | change_status | assign_team |
    # add_program | toggle_program | delete_program
    action = db.Column(db.String(50), nullable=False)

    # على شنو تدارت: case | doctor | team_member | admin | program
    target_type = db.Column(db.String(30), nullable=False)
    target_id = db.Column(db.Integer)  # رقم الحالة (مثلاً 115) أو رقم المستخدم
    details = db.Column(db.Text)  # وصف مقروء (مثلاً: "pending → confirmed")

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)


# =========================================================
#  Notification: إشعارات بسيطة من Admin لطبيب معين
# =========================================================


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)

    recipient_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    recipient = db.relationship("User", foreign_keys=[recipient_id])

    sender_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    sender = db.relationship("User", foreign_keys=[sender_id])

    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
