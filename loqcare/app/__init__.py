import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
from flask_migrate import Migrate
from dotenv import load_dotenv

load_dotenv()

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "يجب تسجيل الدخول أولاً."
limiter = Limiter(key_func=get_remote_address)
csrf = CSRFProtect()
migrate = Migrate()


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-change-me")
    database_url = os.getenv("DATABASE_URL", "sqlite:///loqcare.db")
    # Render (وبعض المزودين) كيعطيو الرابط بصيغة "postgres://" القديمة،
    # بينما SQLAlchemy الحديث كيقبل غير "postgresql://". كنصلحوها أوتوماتيكياً.
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    login_manager.init_app(app)
    limiter.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db)

    from app.models import User

    from app.auth.routes import auth_bp
    from app.main.routes import main_bp
    from app.admin.routes import admin_bp
    from app.doctor.routes import doctor_bp
    from app.webhook.routes import webhook_bp
    from app.public.routes import public_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(doctor_bp)
    app.register_blueprint(webhook_bp)
    app.register_blueprint(public_bp)

    # Twilio كيبعت POST من سيرفر خارجي، فما يقدرش يحمل CSRF token.
    # الحماية ديالو كتكون عبر signature validation فـ webhook/routes.py
    csrf.exempt(webhook_bp)

    @login_manager.user_loader
    def load_user(user_id):
        user = db.session.get(User, int(user_id))
        # حساب ملغى التفعيل كيخرج من الجلسة فوراً (مثلاً Admin ألغاه الحساب الرئيسي)
        if user is not None and not user.is_active_account:
            return None
        return user

    @app.context_processor
    def inject_default_country_code():
        """رمز الدولة الافتراضي فقوائم الهاتف، حسب موقع الزائر (يقدر يبدلو يدوياً)."""
        from flask import request
        from app.utils import detect_country_code

        return {"default_country_code": detect_country_code(request.headers)}

    @app.context_processor
    def inject_sidebar_counters():
        """عدادات الشريط الجانبي: إشعارات الطبيب غير المقروءة + طلبات الموافقة المعلقة للـ Admin."""
        from flask_login import current_user
        from app.models import Notification, User as _User

        unread = 0
        pending = 0
        if getattr(current_user, "is_authenticated", False):
            if current_user.is_doctor:
                unread = db.session.scalar(
                    db.select(db.func.count())
                    .select_from(Notification)
                    .where(Notification.recipient_id == current_user.id, Notification.is_read == False)
                ) or 0
            elif current_user.is_admin:
                pending = db.session.scalar(
                    db.select(db.func.count())
                    .select_from(_User)
                    .where(_User.role == "doctor", _User.account_status == "pending")
                ) or 0
        return {"unread_notifications_count": unread, "pending_approvals_count": pending}

    with app.app_context():
        db.create_all()
        _ensure_schema_updates()
        _ensure_admin_account()
        _seed_default_programs()
        _seed_case_numbering()

    return app


def _ensure_schema_updates():
    """كيزيد الأعمدة الجديدة فجدول users إلا كان موجود من قبل (create_all ما كيعدلش الجداول القديمة).

    آمن للتشغيل أكثر من مرة وعلى SQLite و PostgreSQL. فالدفعة 3 غادي نمشيو لـ Flask-Migrate.
    """
    from sqlalchemy import inspect, text
    from app.models import User

    insp = inspect(db.engine)
    if "users" not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns("users")}
    wanted = {"member_type": "VARCHAR(30)", "member_rank": "VARCHAR(100)"}
    for name, ddl in wanted.items():
        if name in existing:
            continue
        try:
            with db.engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {ddl}"))
        except Exception:
            # ممكن worker آخر سبقنا وزاد العمود فنفس اللحظة
            pass

    # أعضاء الفريق القدام: نستنتجو النوع من التخصص (مرة وحدة، فقط للفارغين)
    legacy = db.session.scalars(
        db.select(User).where(User.role == "medical_team", User.member_type.is_(None))
    ).all()
    for m in legacy:
        m.member_type = "nutritionist" if "تغذية" in (m.specialty or "") else "doctor"
    if legacy:
        db.session.commit()


def _seed_case_numbering():
    """كيبدا ترقيم الحالات من 115 على SQLite (PostgreSQL كيحترم الـ Sequence بوحدو).

    كنبذرو جدول sqlite_sequence بالقيمة 114 مرة وحدة، فأول حالة كتاخد الرقم 115.
    ما كيتدخلش إلا كان الجدول فارغ ولا ما بدأش الترقيم بعد.
    """
    from sqlalchemy import text
    from app.models import Case

    if db.engine.dialect.name != "sqlite":
        return

    start = Case.CASE_ID_START
    has_cases = db.session.scalar(db.select(db.func.count()).select_from(Case))
    if has_cases:
        return

    with db.engine.begin() as conn:
        existing = conn.execute(
            text("SELECT seq FROM sqlite_sequence WHERE name = 'cases'")
        ).fetchone()
        if existing is None:
            conn.execute(
                text("INSERT INTO sqlite_sequence (name, seq) VALUES ('cases', :seq)"),
                {"seq": start - 1},
            )
        elif existing[0] < start - 1:
            conn.execute(
                text("UPDATE sqlite_sequence SET seq = :seq WHERE name = 'cases'"),
                {"seq": start - 1},
            )


def _ensure_admin_account():
    """كيصاوب حساب Admin أولي مرة وحدة، بلا ما تحتاجي تدخليه يدوياً من phpMyAdmin أو شي حاجة بحالها."""
    from app.models import User

    admin_email = os.getenv("ADMIN_EMAIL", "admin@loqcare.com")
    if db.session.scalar(db.select(User).where(User.email == admin_email)):
        return

    admin = User(
        full_name="LOQ CARE Admin",
        email=admin_email,
        role="admin",
        account_status="approved",
        is_active_account=True,
    )
    admin.set_password(os.getenv("ADMIN_PASSWORD", "change-this-password"))
    db.session.add(admin)
    db.session.commit()


def _seed_default_programs():
    """البرامج الأساسية المأخوذة من loqcare.com - Admin يقدر يزيد/يبدل من الداشبورد من بعد."""
    from app.models import Program

    if db.session.scalar(db.select(Program)):
        return

    defaults = [
        ("ضبط السكري", True),
        ("إدارة الوزن", False),
        ("صحة القلب", False),
        ("صحة الجهاز الهضمي", False),
        ("اضطرابات الغدة الدرقية", False),
    ]
    for name, is_active in defaults:
        db.session.add(Program(name=name, is_active=is_active))
    db.session.commit()
