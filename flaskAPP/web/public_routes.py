import os
from datetime import timedelta

from flask import render_template, request, send_from_directory, session, url_for, redirect


APPLICATION_VERIFY_SESSION_KEY = "pending_application_verification"
APPLICATION_VERIFY_TTL_MINUTES = 15


def register_public_routes(app, state):
    def _redirect_admin_from_contact():
        if session.get("user_role") == "admin":
            return redirect(url_for("admin_dashboard"))
        return None

    def render_contact_page(*, errors=None, success_message=None, form=None):
        form = form or {}
        logged_in_customer = session.get("user_role") == "customer"
        default_mode = "customer" if logged_in_customer else "guest"
        selected_mode = (form.get("contact_mode") or default_mode).strip().lower()
        if logged_in_customer:
            selected_mode = "customer"
        elif selected_mode not in {"guest", "login"}:
            selected_mode = "guest"

        return render_template(
            "contact.html",
            errors=errors or [],
            success_message=success_message,
            form={
                "contact_mode": selected_mode,
                "guest_email": (form.get("guest_email") or "").strip().lower(),
                "message_body": (form.get("message_body") or "").strip(),
            },
            is_customer_logged_in=logged_in_customer,
            current_customer_email=(session.get("customer_email") or "").strip().lower(),
            current_customer_name=(session.get("customer_name") or "").strip(),
        )

    @app.get("/")
    def index():
        return render_template("home.html")

    @app.get("/platform")
    def platform():
        return render_template("platform.html")

    @app.get("/security")
    def security():
        return render_template("security.html")

    @app.get("/contact")
    def contact():
        redirect_response = _redirect_admin_from_contact()
        if redirect_response is not None:
            return redirect_response
        return render_contact_page()

    @app.post("/contact")
    def contact_submit():
        redirect_response = _redirect_admin_from_contact()
        if redirect_response is not None:
            return redirect_response

        message_body = (request.form.get("message_body") or "").strip()
        logged_in_customer = session.get("user_role") == "customer"
        contact_mode = "customer" if logged_in_customer else (request.form.get("contact_mode") or "guest").strip().lower()
        guest_email = (request.form.get("guest_email") or "").strip().lower()

        if contact_mode == "login" and not logged_in_customer:
            return redirect(url_for("login_page", next=url_for("contact")))

        errors = []
        if not message_body:
            errors.append("Enter a message before sending.")

        sender_mode = "guest"
        sender_email = guest_email
        sender_name = ""
        customer_user_id = None

        if logged_in_customer:
            sender_mode = "customer"
            sender_email = (session.get("customer_email") or "").strip().lower()
            sender_name = (session.get("customer_name") or "").strip()
            customer_user_id = session.get("customer_user_id")
            if not state.is_valid_email(sender_email):
                errors.append("Your signed-in account does not have a valid email address.")
        else:
            if contact_mode != "guest":
                errors.append("Choose guest access or sign in before sending a message.")
            if not state.is_valid_email(guest_email):
                errors.append("Enter a valid email address to continue as a guest.")

        if errors:
            return render_contact_page(
                errors=errors,
                form={
                    "contact_mode": contact_mode,
                    "guest_email": guest_email,
                    "message_body": message_body,
                },
            ), 400

        conn = state.get_db_connection()
        state.ensure_application_snapshot_columns(conn)
        cursor = conn.cursor(dictionary=True)
        admin_rows = []
        try:
            state.ensure_contact_messages_table(conn)
            cursor.execute(
                """
                INSERT INTO contact_messages (
                    customer_user_id,
                    sender_mode,
                    sender_name,
                    sender_email,
                    message_body
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (customer_user_id, sender_mode, sender_name or None, sender_email, message_body),
            )
            conn.commit()
            cursor.execute(
                """
                SELECT email
                FROM admins
                WHERE is_active = 1
                ORDER BY admin_id ASC
                """
            )
            admin_rows = cursor.fetchall() or []
        finally:
            cursor.close()
            conn.close()

        admin_emails = [(row or {}).get("email", "") for row in admin_rows]
        state.send_contact_message_notification(
            app,
            state.app_config,
            admin_emails,
            sender_name or "Guest visitor",
            sender_email,
            message_body,
            sender_mode=sender_mode,
        )

        return render_contact_page(
            success_message="Your message has been sent to the admin team.",
            form={"contact_mode": contact_mode},
        )

    @app.get("/apply")
    def apply_form():
        return render_template("apply.html")

    @app.get("/info")
    def info():
        return redirect(url_for("platform"))

    @app.route("/favicon.ico")
    def favicon():
        return send_from_directory(
            os.path.join(app.root_path, "static"),
            "favicon.ico",
            mimetype="image/vnd.microsoft.icon",
        )

    @app.post("/apply")
    def apply_submit():
        organisation_name = request.form.get("organisation_name", "").strip()
        contact_name = request.form.get("contact_name", "").strip()
        contact_email = request.form.get("contact_email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        report_email = request.form.get("report_email", "").strip().lower()
        aws_region = request.form.get("aws_region", "").strip() or "eu-west-2"
        report_frequency = (request.form.get("report_frequency", "") or "").strip() or "weekly"
        notes = request.form.get("notes", "").strip()
        services = [s.strip().lower() for s in request.form.getlist("services") if s.strip()]

        errors = []
        if not organisation_name:
            errors.append("Company name is required.")
        if not contact_name:
            errors.append("Contact name is required.")
        if not contact_email or "@" not in contact_email or "." not in contact_email:
            errors.append("A valid contact email is required.")
        if len(password) < 8:
            errors.append("Password must be at least 8 characters long.")
        if password != confirm_password:
            errors.append("Passwords do not match.")
        if not report_email or "@" not in report_email or "." not in report_email:
            errors.append("A valid report recipient email is required.")
        if not aws_region:
            errors.append("AWS region is required.")
        if report_frequency not in {"daily", "weekly", "monthly"}:
            errors.append("Please select a valid report frequency.")
        allowed_services = {"s3", "rds", "ecs", "eks", "spot"}
        if not services:
            errors.append("Select at least one service to enable.")
        elif any(s not in allowed_services for s in services):
            errors.append("One or more selected services are invalid.")

        if errors:
            return render_template(
                "apply.html",
                errors=errors,
                form={
                    "organisation_name": organisation_name,
                    "contact_name": contact_name,
                    "contact_email": contact_email,
                    "report_email": report_email,
                    "aws_region": aws_region,
                    "report_frequency": report_frequency,
                    "notes": notes,
                    "services": services,
                },
            ), 400

        conn = state.get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT customer_user_id FROM customer_users WHERE email = %s", (contact_email,))
            existing_user = cursor.fetchone()
            if existing_user:
                return render_template(
                    "apply.html",
                    errors=["An account with that email already exists."],
                    form={
                        "organisation_name": organisation_name,
                        "contact_name": contact_name,
                        "contact_email": contact_email,
                        "report_email": report_email,
                        "aws_region": aws_region,
                        "report_frequency": report_frequency,
                        "notes": notes,
                        "services": services,
                    },
                ), 400
        finally:
            cursor.close()
            conn.close()

        verification_code = state.generate_verification_code()
        state.send_verification_code(app, state.app_config, contact_email, "Application", verification_code)
        session[APPLICATION_VERIFY_SESSION_KEY] = {
            "code": verification_code,
            "email": contact_email,
            "expires_at": (state.utc_now() + timedelta(minutes=APPLICATION_VERIFY_TTL_MINUTES)).isoformat(),
            "form": {
                "organisation_name": organisation_name,
                "contact_name": contact_name,
                "contact_email": contact_email,
                "password": password,
                "report_email": report_email,
                "aws_region": aws_region,
                "report_frequency": report_frequency,
                "notes": notes,
                "services": services,
            },
        }
        return redirect(url_for("apply_verify_page"))

    @app.get("/apply/verify")
    def apply_verify_page():
        verification_state = session.get(APPLICATION_VERIFY_SESSION_KEY)
        if not verification_state:
            return redirect(url_for("apply_form"))
        debug_code = None if state.app_config.is_production else verification_state.get("code")
        return render_template(
            "verify_code.html",
            title="Verify Email",
            heading="Verify your email",
            subtitle="Enter the verification code sent to your email to complete your application.",
            email=verification_state.get("email", ""),
            action_url=url_for("apply_verify_submit"),
            back_url=url_for("apply_form"),
            debug_code=debug_code,
            error=None,
            purpose_label="application",
        )

    @app.post("/apply/verify")
    def apply_verify_submit():
        verification_state = session.get(APPLICATION_VERIFY_SESSION_KEY)
        if not verification_state or state.utc_now().isoformat() > str(verification_state.get("expires_at", "")):
            session.pop(APPLICATION_VERIFY_SESSION_KEY, None)
            return redirect(url_for("apply_form"))

        verification_code = (request.form.get("verification_code") or "").strip()
        valid = verification_code == verification_state.get("code")
        error = "Verification code is incorrect."

        if not valid:
            debug_code = None if state.app_config.is_production else verification_state.get("code")
            return render_template(
                "verify_code.html",
                title="Verify Email",
                heading="Verify your email",
                subtitle="Enter the verification code sent to your email to complete your application.",
                email=verification_state.get("email", ""),
                action_url=url_for("apply_verify_submit"),
                back_url=url_for("apply_form"),
                debug_code=debug_code,
                error=error,
                purpose_label="application",
            ), 400

        form = verification_state["form"]
        conn = state.get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            state.ensure_application_snapshot_columns(conn)
            cursor.execute("SELECT organisation_id FROM organisations WHERE organisation_name = %s", (form["organisation_name"],))
            org = cursor.fetchone()
            if org:
                organisation_id = org["organisation_id"]
            else:
                cursor.execute("INSERT INTO organisations (organisation_name) VALUES (%s)", (form["organisation_name"],))
                organisation_id = cursor.lastrowid

            cursor.execute("SELECT customer_user_id FROM customer_users WHERE email = %s", (form["contact_email"],))
            existing_user = cursor.fetchone()
            if existing_user:
                conn.rollback()
                session.pop(APPLICATION_VERIFY_SESSION_KEY, None)
                return render_template(
                    "apply.html",
                    errors=["An account with that email already exists."],
                    form=form,
                ), 400

            cursor.execute(
                """
                INSERT INTO customer_users (organisation_id, contact_name, email, password_hash)
                VALUES (%s, %s, %s, %s)
                """,
                (organisation_id, form["contact_name"], form["contact_email"], state.hash_password(form["password"])),
            )
            customer_user_id = cursor.lastrowid
            cursor.execute(
                """
                INSERT INTO applications (
                    customer_user_id,
                    organisation_name,
                    contact_name,
                    contact_email,
                    notes,
                    status
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    customer_user_id,
                    form["organisation_name"],
                    form["contact_name"],
                    form["contact_email"],
                    form["notes"] or None,
                    "pending",
                ),
            )
            application_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO onboardings (application_id, aws_region, report_frequency) VALUES (%s, %s, %s)",
                (application_id, form["aws_region"], form["report_frequency"]),
            )
            onboarding_id = cursor.lastrowid
            for service_code in form["services"]:
                cursor.execute(
                    "INSERT INTO onboarding_services (onboarding_id, service_code) VALUES (%s, %s)",
                    (onboarding_id, service_code),
                )
            cursor.execute(
                """
                INSERT INTO onboarding_report_recipients (onboarding_id, report_email)
                VALUES (%s, %s)
                """,
                (onboarding_id, form["report_email"]),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()

        session.pop(APPLICATION_VERIFY_SESSION_KEY, None)
        session.clear()
        session["user_role"] = "customer"
        session["customer_user_id"] = customer_user_id
        session["customer_email"] = form["contact_email"]
        session["customer_name"] = form["contact_name"]
        session["organisation_id"] = organisation_id
        return redirect(url_for("customer_dashboard", banner="submitted"))

    @app.get("/thanks/<int:application_id>")
    @state.customer_login_required
    def thanks(application_id):
        return redirect(url_for("customer_dashboard", banner="submitted"))

    @app.get("/onboarding")
    def onboarding():
        return render_template("onboarding.html")
