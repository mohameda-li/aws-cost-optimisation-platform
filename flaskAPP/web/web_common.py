from datetime import datetime, timezone
from functools import wraps
import json
import re

from flask import redirect, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


ALLOWED_SERVICES = ["s3", "rds", "ecs", "eks", "spot"]


def utc_now():
    return datetime.now(timezone.utc)


def verify_password(stored_hash: str, password: str) -> bool:
    if not stored_hash:
        return False
    try:
        return check_password_hash(stored_hash, password)
    except (ValueError, TypeError):
        return False


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def slugify(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value


def get_enabled_service_codes(customer_data):
    explicit = customer_data.get("enabled_service_codes")
    if explicit:
        cleaned = []
        for service in explicit:
            service = (service or "").strip().lower()
            if service in ALLOWED_SERVICES and service not in cleaned:
                cleaned.append(service)
        return cleaned

    derived = []
    services_dict = customer_data.get("services", {})
    for service in ALLOWED_SERVICES:
        if services_dict.get(service):
            derived.append(service)
    return derived


def admin_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_role") != "admin":
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)

    return decorated_function


def customer_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_role") != "customer":
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)

    return decorated_function


def find_account_by_email(cursor, email: str):
    cursor.execute(
        """
        SELECT admin_id, full_name, email, password_hash, is_active
        FROM admins
        WHERE email = %s
        """,
        (email,),
    )
    admin = cursor.fetchone()
    if admin:
        return {
            "user_role": "admin",
            "account_id": admin["admin_id"],
            "email": admin["email"],
            "display_name": admin["full_name"],
            "password_hash": admin.get("password_hash"),
            "is_active": bool(admin.get("is_active")),
        }

    cursor.execute(
        """
        SELECT customer_user_id, organisation_id, contact_name, email, password_hash
        FROM customer_users
        WHERE email = %s
        """,
        (email,),
    )
    customer = cursor.fetchone()
    if customer:
        return {
            "user_role": "customer",
            "account_id": customer["customer_user_id"],
            "organisation_id": customer["organisation_id"],
            "email": customer["email"],
            "display_name": customer["contact_name"],
            "password_hash": customer.get("password_hash"),
            "is_active": True,
        }

    return None


def update_account_password(cursor, account, new_password: str):
    password_hash = hash_password(new_password)

    if account["user_role"] == "admin":
        cursor.execute(
            "UPDATE admins SET password_hash = %s WHERE admin_id = %s",
            (password_hash, int(account["account_id"])),
        )
        return

    cursor.execute(
        "UPDATE customer_users SET password_hash = %s WHERE customer_user_id = %s",
        (password_hash, int(account["account_id"])),
    )


def build_customer_bundle_data(data, enabled_service_codes, report_row):
    frequency_map = {
        "daily": "rate(1 day)",
        "weekly": "rate(7 days)",
        "monthly": "rate(30 days)",
    }

    enabled_services = {service_code: True for service_code in enabled_service_codes}
    org_slug = slugify(data["organisation_name"])

    return {
        "aws_region": data["aws_region"] or "eu-west-2",
        "customer_id": f"org_{data['organisation_id']}",
        "company_name": data["organisation_name"],
        "report_bucket_name": f"{org_slug}-finops-reports",
        "notification_email": (
            report_row["report_email"]
            if report_row and report_row.get("report_email")
            else data["contact_email"]
        ),
        "schedule_expression": frequency_map.get(data["report_frequency"], "rate(7 days)"),
        "enabled_service_codes": enabled_service_codes,
        "services": {
            "s3": enabled_services.get("s3", False),
            "rds": enabled_services.get("rds", False),
            "ecs": enabled_services.get("ecs", False),
            "eks": enabled_services.get("eks", False),
            "spot": enabled_services.get("spot", False),
        },
        "s3_target_buckets": [],
        "s3_default_days_since_access": 60,
    }
