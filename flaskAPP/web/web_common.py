from datetime import datetime, timezone
from functools import wraps
from email.message import EmailMessage
import os
import re
import secrets
import smtplib

from flask import redirect, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


ALLOWED_SERVICES = ["s3", "rds", "ecs", "eks", "spot"]
ALLOWED_REPORT_FREQUENCIES = {"daily", "weekly", "monthly"}
AWS_REGION_PATTERN = re.compile(r"^[a-z]{2}-[a-z]+-\d+$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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


def send_application_message_notification(
    app,
    config,
    recipient: str,
    customer_name: str,
    organisation_name: str,
    application_id: int,
    sender_name: str,
) -> bool:
    if not config.smtp_host or not config.smtp_sender or not is_valid_email(recipient):
        return False

    recipient_name = (customer_name or "there").strip()
    organisation_label = (organisation_name or "your application").strip()
    conversation_url = f"{config.app_base_url}/customer/applications/{application_id}/messages"

    subject = f"New message about your FinOps application"
    body = (
        f"Hello {recipient_name},\n\n"
        f"{sender_name or 'An admin'} has sent you a new message about {organisation_label}.\n\n"
        f"Open your conversation here:\n{conversation_url}\n\n"
        "If you need to reply, sign in to your customer dashboard and open the conversation thread.\n\n"
        "This is an automated notification from FinOps Automation."
    )

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


def send_application_status_notification(
    app,
    config,
    recipient: str,
    customer_name: str,
    organisation_name: str,
    application_id: int,
    new_status: str,
) -> bool:
    if not config.smtp_host or not config.smtp_sender or not is_valid_email(recipient):
        return False

    recipient_name = (customer_name or "there").strip()
    organisation_label = (organisation_name or "your application").strip()
    dashboard_url = f"{config.app_base_url}/customer/dashboard"
    status_label = (new_status or "updated").strip().capitalize()

    subject = "Your FinOps application status has been updated"
    body = (
        f"Hello {recipient_name},\n\n"
        f"The status of your FinOps application for {organisation_label} has been updated to {status_label}.\n\n"
        f"You can review the latest details here:\n{dashboard_url}\n\n"
        f"Application reference: #{application_id}\n\n"
        "This is an automated notification from FinOps Automation."
    )

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


def send_contact_message_notification(
    app,
    config,
    recipients,
    sender_label: str,
    sender_email: str,
    message_body: str,
    sender_mode: str = "guest",
) -> bool:
    valid_recipients = []
    for recipient in recipients or []:
        recipient = (recipient or "").strip().lower()
        if is_valid_email(recipient) and recipient not in valid_recipients:
            valid_recipients.append(recipient)

    if not config.smtp_host or not config.smtp_sender or not valid_recipients:
        return False

    sender_label = (sender_label or "Guest visitor").strip()
    sender_email = (sender_email or "").strip().lower()
    message_body = (message_body or "").strip()
    contact_url = f"{config.app_base_url}/contact"
    reply_hint = (
        "The sender is signed in and can be followed up through the platform."
        if sender_mode == "customer"
        else "Reply to the sender email below if you want to continue the conversation."
    )

    subject = "New contact message for FinOps Automation"
    body = (
        "Hello,\n\n"
        "A new contact message has been submitted through the FinOps Automation website.\n\n"
        f"Sender: {sender_label}\n"
        f"Email: {sender_email or 'Not provided'}\n"
        f"Mode: {sender_mode.capitalize()}\n\n"
        "Message:\n"
        f"{message_body}\n\n"
        f"{reply_hint}\n"
        f"Contact page: {contact_url}\n\n"
        "This is an automated notification from FinOps Automation."
    )

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.smtp_sender
    message["To"] = ", ".join(valid_recipients)
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
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS application_message_state (
              application_id INT PRIMARY KEY,
              customer_last_read_admin_message_id INT NOT NULL DEFAULT 0,
              customer_last_notified_admin_message_id INT NOT NULL DEFAULT 0,
              created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              CONSTRAINT fk_application_message_state_application
                FOREIGN KEY (application_id) REFERENCES applications(application_id)
                ON DELETE CASCADE
                ON UPDATE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
            """
        )
        conn.commit()
    finally:
        cursor.close()


def ensure_application_snapshot_columns(conn):
    cursor = conn.cursor()
    try:
        cursor.execute("SHOW COLUMNS FROM applications LIKE 'organisation_name'")
        has_organisation_name = bool(cursor.fetchone())
        cursor.execute("SHOW COLUMNS FROM applications LIKE 'contact_name'")
        has_contact_name = bool(cursor.fetchone())
        cursor.execute("SHOW COLUMNS FROM applications LIKE 'contact_email'")
        has_contact_email = bool(cursor.fetchone())

        if not has_organisation_name:
            cursor.execute("ALTER TABLE applications ADD COLUMN organisation_name VARCHAR(255) NULL AFTER customer_user_id")
        if not has_contact_name:
            cursor.execute("ALTER TABLE applications ADD COLUMN contact_name VARCHAR(255) NULL AFTER organisation_name")
        if not has_contact_email:
            cursor.execute("ALTER TABLE applications ADD COLUMN contact_email VARCHAR(255) NULL AFTER contact_name")

        if not has_organisation_name or not has_contact_name or not has_contact_email:
            cursor.execute(
                """
                UPDATE applications a
                JOIN customer_users cu
                  ON a.customer_user_id = cu.customer_user_id
                JOIN organisations o
                  ON cu.organisation_id = o.organisation_id
                SET
                  a.organisation_name = COALESCE(a.organisation_name, o.organisation_name),
                  a.contact_name = COALESCE(a.contact_name, cu.contact_name),
                  a.contact_email = COALESCE(a.contact_email, cu.email)
                """
            )
        conn.commit()
    finally:
        cursor.close()


def ensure_contact_messages_table(conn):
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS contact_messages (
              contact_message_id INT AUTO_INCREMENT PRIMARY KEY,
              customer_user_id INT NULL,
              sender_mode ENUM('guest','customer') NOT NULL,
              sender_name VARCHAR(255) NULL,
              sender_email VARCHAR(255) NOT NULL,
              message_body TEXT NOT NULL,
              created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
              CONSTRAINT fk_contact_messages_customer
                FOREIGN KEY (customer_user_id) REFERENCES customer_users(customer_user_id)
                ON DELETE SET NULL
                ON UPDATE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
            """
        )
        conn.commit()
    finally:
        cursor.close()


def get_customer_admin_message_state(cursor, application_id: int):
    cursor.execute(
        """
        SELECT
            customer_last_read_admin_message_id,
            customer_last_notified_admin_message_id
        FROM application_message_state
        WHERE application_id = %s
        """,
        (application_id,),
    )
    state = cursor.fetchone()
    if not state:
        return {
            "customer_last_read_admin_message_id": 0,
            "customer_last_notified_admin_message_id": 0,
        }
    return state


def mark_customer_admin_messages_read(conn, application_id: int, message_id: int):
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO application_message_state (
                application_id,
                customer_last_read_admin_message_id,
                customer_last_notified_admin_message_id
            ) VALUES (%s, %s, 0)
            ON DUPLICATE KEY UPDATE
                customer_last_read_admin_message_id = GREATEST(
                    customer_last_read_admin_message_id,
                    VALUES(customer_last_read_admin_message_id)
                )
            """,
            (application_id, int(message_id or 0)),
        )
        conn.commit()
    finally:
        cursor.close()


def mark_customer_admin_messages_notified(conn, application_id: int, message_id: int):
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO application_message_state (
                application_id,
                customer_last_read_admin_message_id,
                customer_last_notified_admin_message_id
            ) VALUES (%s, 0, %s)
            ON DUPLICATE KEY UPDATE
                customer_last_notified_admin_message_id = GREATEST(
                    customer_last_notified_admin_message_id,
                    VALUES(customer_last_notified_admin_message_id)
                )
            """,
            (application_id, int(message_id or 0)),
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


def is_valid_email(value: str) -> bool:
    value = (value or "").strip().lower()
    return bool(value and EMAIL_PATTERN.match(value))


def _normalise_aws_region(value: str) -> str:
    value = (value or "").strip()
    if value and AWS_REGION_PATTERN.match(value):
        return value
    return "eu-west-2"


def _normalise_report_frequency(value: str) -> str:
    value = (value or "").strip().lower()
    return value if value in ALLOWED_REPORT_FREQUENCIES else "weekly"


def _normalise_smtp_port(value: str) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return 587
    return port if 1 <= port <= 65535 else 587


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


def build_customer_bundle_data(data, enabled_service_codes, report_rows):
    frequency_map = {
        "daily": "rate(1 day)",
        "weekly": "rate(7 days)",
        "monthly": "rate(30 days)",
    }

    organisation_name = (data.get("organisation_name") or "").strip()
    if not organisation_name:
        raise ValueError("Organisation name is required for bundle generation")

    organisation_id = data.get("organisation_id")
    try:
        organisation_id = int(organisation_id)
    except (TypeError, ValueError):
        raise ValueError("Organisation id is required for bundle generation")

    contact_email = (data.get("contact_email") or "").strip().lower()
    if not is_valid_email(contact_email):
        raise ValueError("A valid contact email is required for bundle generation")

    enabled_services = {service_code: True for service_code in enabled_service_codes}
    org_slug = slugify(organisation_name)
    recipient_emails = []
    for row in report_rows or []:
        email = (row or {}).get("report_email", "").strip().lower()
        if not is_valid_email(email):
            continue
        if email and email not in recipient_emails:
            recipient_emails.append(email)

    report_bucket_name = f"{org_slug}-{organisation_id}-finops-reports"
    report_frequency = _normalise_report_frequency(data.get("report_frequency"))

    return {
        "aws_region": _normalise_aws_region(data.get("aws_region")),
        "customer_id": f"org_{organisation_id}",
        "company_name": organisation_name,
        "report_bucket_name": report_bucket_name,
        "notification_email": ",".join(recipient_emails) if recipient_emails else contact_email,
        "schedule_expression": frequency_map[report_frequency],
        "smtp_host": os.getenv("SMTP_HOST", "").strip(),
        "smtp_port": _normalise_smtp_port(os.getenv("SMTP_PORT", "587")),
        "smtp_username": os.getenv("SMTP_USERNAME", "").strip(),
        "smtp_password": os.getenv("SMTP_PASSWORD", ""),
        "smtp_sender": (os.getenv("SMTP_SENDER") or os.getenv("SMTP_USERNAME") or "").strip(),
        "smtp_use_tls": (os.getenv("SMTP_USE_TLS", "true").strip().lower() not in {"0", "false", "no"}),
        "run_initial_report_on_apply": True,
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
