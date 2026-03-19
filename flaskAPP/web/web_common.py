from datetime import datetime, timezone
from functools import wraps
from email.message import EmailMessage
import json
import re
import secrets
import smtplib

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


def generate_verification_code() -> str:
    return f"{secrets.randbelow(1000000):06d}"


def send_verification_code(app, config, recipient: str, purpose: str, code: str) -> bool:
    subject = f"{purpose} verification code"
    body = (
        f"Your verification code for {purpose.lower()} is {code}.\n\n"
        "If you did not request this code, you can ignore this message."
    )

    if not config.smtp_host or not config.smtp_sender:
        app.logger.info("Verification code for %s sent to %s: %s", purpose.lower(), recipient, code)
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.smtp_sender
    message["To"] = recipient
    message.set_content(body)

    with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=10) as smtp:
        if config.smtp_use_tls:
            smtp.starttls()
        if config.smtp_username:
            smtp.login(config.smtp_username, config.smtp_password)
        smtp.send_message(message)
    return True


def ensure_application_messages_table(conn):
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS application_messages (
              message_id INT AUTO_INCREMENT PRIMARY KEY,
              application_id INT NOT NULL,
              customer_user_id INT NULL,
              admin_id INT NULL,
              sender_role ENUM('customer','admin') NOT NULL,
              sender_name VARCHAR(255) NOT NULL,
              message_body TEXT NOT NULL,
              created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
              CONSTRAINT fk_application_messages_application
                FOREIGN KEY (application_id) REFERENCES applications(application_id)
                ON DELETE CASCADE
                ON UPDATE CASCADE,
              CONSTRAINT fk_application_messages_customer
                FOREIGN KEY (customer_user_id) REFERENCES customer_users(customer_user_id)
                ON DELETE SET NULL
                ON UPDATE CASCADE,
              CONSTRAINT fk_application_messages_admin
                FOREIGN KEY (admin_id) REFERENCES admins(admin_id)
                ON DELETE SET NULL
                ON UPDATE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
            """
        )
        conn.commit()
    finally:
        cursor.close()


def ensure_admin_superuser_support(conn):
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SHOW COLUMNS FROM admins LIKE 'is_superuser'")
        column = cursor.fetchone()
        if not column:
            cursor.close()
            cursor = conn.cursor()
            cursor.execute(
                """
                ALTER TABLE admins
                ADD COLUMN is_superuser TINYINT(1) NOT NULL DEFAULT 0
                """
            )
            cursor.execute(
                """
                UPDATE admins
                SET is_superuser = 1
                WHERE email = 'admin@finops.local'
                """
            )
            conn.commit()
    finally:
        cursor.close()


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
             , is_superuser
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
            "is_superuser": bool(admin.get("is_superuser")),
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
