import os

from flask import abort, render_template, request, send_from_directory, session, url_for, redirect


def register_public_routes(app, state):
    @app.get("/")
    def index():
        return render_template("home.html")

    @app.get("/apply")
    def apply_form():
        return render_template("apply.html")

    @app.get("/info")
    def info():
        return render_template("info.html")

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
        if not password:
            errors.append("Password is required.")
        elif len(password) < 8:
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
            cursor.execute("SELECT organisation_id FROM organisations WHERE organisation_name = %s", (organisation_name,))
            org = cursor.fetchone()
            if org:
                organisation_id = org["organisation_id"]
            else:
                cursor.execute("INSERT INTO organisations (organisation_name) VALUES (%s)", (organisation_name,))
                organisation_id = cursor.lastrowid

            cursor.execute("SELECT customer_user_id FROM customer_users WHERE email = %s", (contact_email,))
            existing_user = cursor.fetchone()
            if existing_user:
                conn.rollback()
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

            cursor.execute(
                """
                INSERT INTO customer_users (organisation_id, contact_name, email, password_hash)
                VALUES (%s, %s, %s, %s)
                """,
                (organisation_id, contact_name, contact_email, state.hash_password(password)),
            )
            customer_user_id = cursor.lastrowid

            cursor.execute(
                "INSERT INTO applications (customer_user_id, notes, status) VALUES (%s, %s, %s)",
                (customer_user_id, notes or None, "pending"),
            )
            application_id = cursor.lastrowid

            cursor.execute(
                "INSERT INTO onboardings (application_id, aws_region, report_frequency) VALUES (%s, %s, %s)",
                (application_id, aws_region, report_frequency),
            )
            onboarding_id = cursor.lastrowid

            for service_code in services:
                cursor.execute(
                    "INSERT INTO onboarding_services (onboarding_id, service_code) VALUES (%s, %s)",
                    (onboarding_id, service_code),
                )

            cursor.execute(
                """
                INSERT INTO onboarding_report_recipients (onboarding_id, report_email)
                VALUES (%s, %s)
                """,
                (onboarding_id, report_email),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()

        session.clear()
        session["user_role"] = "customer"
        session["customer_user_id"] = customer_user_id
        session["customer_email"] = contact_email
        session["customer_name"] = contact_name
        session["organisation_id"] = organisation_id
        return redirect(url_for("thanks", application_id=application_id))

    @app.get("/thanks/<int:application_id>")
    @state.customer_login_required
    def thanks(application_id):
        conn = state.get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT
                    a.application_id,
                    a.status,
                    a.notes,
                    a.created_at,
                    cu.contact_name,
                    cu.email AS contact_email,
                    o.organisation_name
                FROM applications a
                JOIN customer_users cu
                  ON a.customer_user_id = cu.customer_user_id
                JOIN organisations o
                  ON cu.organisation_id = o.organisation_id
                WHERE a.application_id = %s
                  AND a.customer_user_id = %s
                """,
                (application_id, session["customer_user_id"]),
            )
            app_row = cursor.fetchone()
        finally:
            cursor.close()
            conn.close()

        if not app_row:
            abort(404)
        return render_template("thanks.html", app_row=app_row)

    @app.get("/onboarding")
    def onboarding():
        return render_template("onboarding.html")
