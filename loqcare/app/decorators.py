from functools import wraps
from flask import abort
from flask_login import current_user


def role_required(*roles):
    """كيمنع أي مستخدم ماشي عندو الدور المطلوب من الوصول للـ route.
    الاستعمال: @role_required("admin")  أو  @role_required("doctor", "medical_team")
    """

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role not in roles:
                abort(403)
            return view_func(*args, **kwargs)

        return wrapped

    return decorator
