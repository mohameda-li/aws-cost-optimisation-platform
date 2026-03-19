import logging
import os

from flask import abort, redirect, render_template, request, send_from_directory, session, url_for

logger = logging.getLogger(__name__)


def register_customer_routes(app, state):
    @app.get("/customer/dashboard")
    @state.customer_login_required
    def customer_dashboard():
        banner = request.args.get("banner")
        conn = state.get_db_connection()
        state.ensure_application_messages_table(conn)
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
                    org.organisation_name,
                    o.onboarding_id,
                    o.aws_region,
                    o.report_frequency
                FROM applications a
                JOIN customer_users cu
                  ON a.customer_user_id = cu.customer_user_id
                JOIN organisations org
                  ON cu.organisation_id = org.organisation_id
                LEFT JOIN onboardings o
                  ON o.application_id = a.application_id
                WHERE a.customer_user_id = %s
                ORDER BY a.created_at DESC
                """,
                (session["customer_user_id"],),
            )
            applications = cursor.fetchall()

            for app_row in applications:
                onboarding_id = app_row.get("onboarding_id")
                if onboarding_id:
                    cursor.execute(
                        """
                        SELECT s.service_name, os.service_code
                        FROM onboarding_services os
                        JOIN services s
                          ON os.service_code = s.service_code
                        WHERE os.onboarding_id = %s
                        ORDER BY s.service_name
                        """,
                        (onboarding_id,),
                    )
                    app_row["services"] = cursor.fetchall()
                    cursor.execute(
                        """
                        SELECT report_email
                        FROM onboarding_report_recipients
                        WHERE onboarding_id = %s
                        ORDER BY report_email
                        """,
                        (onboarding_id,),
                    )
                    app_row["report_recipients"] = cursor.fetchall()
                else:
                    app_row["services"] = []
                    app_row["report_recipients"] = []
                cursor.execute(
                    "SELECT COUNT(*) AS count FROM application_messages WHERE application_id = %s",
                    (app_row["application_id"],),
                )
                count_row = cursor.fetchone()
                app_row["message_count"] = count_row["count"] if count_row else 0
                cursor.execute(
                    """
                    SELECT sender_role
                    FROM application_messages
                    WHERE application_id = %s
                    ORDER BY created_at DESC, message_id DESC
                    LIMIT 1
                    """,
                    (app_row["application_id"],),
                )
                latest_message = cursor.fetchone()
                app_row["has_new_admin_message"] = bool(
                    latest_message
                    and latest_message.get("sender_role") == "admin"
                )

            return render_template("customer_dashboard.html", applications=applications, banner=banner)
        finally:
            cursor.close()
            conn.close()

    @app.get("/customer/applications/<int:application_id>/edit")
    @state.customer_login_required
    def edit_application(application_id):
        conn = state.get_db_connection()
        state.ensure_application_messages_table(conn)
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT
                    a.application_id,
                    a.status,
                    a.notes,
                    cu.contact_name,
                    cu.email AS contact_email,
                    cu.organisation_id,
                    org.organisation_name,
                    o.onboarding_id,
                    o.aws_region,
                    o.report_frequency
                FROM applications a
                JOIN customer_users cu
                  ON a.customer_user_id = cu.customer_user_id
                JOIN organisations org
                  ON cu.organisation_id = org.organisation_id
                JOIN onboardings o
                  ON o.application_id = a.application_id
                WHERE a.application_id = %s
                  AND a.customer_user_id = %s
                """,
                (application_id, session["customer_user_id"]),
            )
            app_row = cursor.fetchone()
            if not app_row:
                abort(404)
            if app_row["status"] not in {"pending", "approved"}:
                return redirect(url_for("customer_dashboard", banner="editing-unavailable"))

            cursor.execute(
                """
                SELECT service_code
                FROM onboarding_services
                WHERE onboarding_id = %s
                ORDER BY service_code
                """,
                (app_row["onboarding_id"],),
            )
            service_rows = cursor.fetchall()
            cursor.execute(
                """
                SELECT report_email
                FROM onboarding_report_recipients
                WHERE onboarding_id = %s
                ORDER BY report_email
                LIMIT 1
                """,
                (app_row["onboarding_id"],),
            )
            report_row = cursor.fetchone()
        finally:
            cursor.close()
            conn.close()

        form = {
            "organisation_name": app_row["organisation_name"],
            "contact_name": app_row["contact_name"],
            "contact_email": app_row["contact_email"],
            "report_email": report_row["report_email"] if report_row else "",
            "aws_region": app_row["aws_region"] or "eu-west-2",
            "report_frequency": app_row["report_frequency"] or "weekly",
            "notes": app_row["notes"] or "",
            "services": [row["service_code"] for row in service_rows],
        }
        return render_template("edit_application.html", application=app_row, form=form, errors=None)

    @app.post("/customer/applications/<int:application_id>/edit")
    @state.customer_login_required
    def update_application(application_id):
        organisation_name = request.form.get("organisation_name", "").strip()
        contact_name = request.form.get("contact_name", "").strip()
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

        conn = state.get_db_connection()
        state.ensure_application_messages_table(conn)
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT
                    a.application_id,
                    a.status,
                    cu.organisation_id,
                    cu.email AS contact_email,
                    o.onboarding_id
                FROM applications a
                JOIN customer_users cu
                  ON a.customer_user_id = cu.customer_user_id
                JOIN onboardings o
                  ON o.application_id = a.application_id
                WHERE a.application_id = %s
                  AND a.customer_user_id = %s
                """,
                (application_id, session["customer_user_id"]),
            )
            app_row = cursor.fetchone()
            if not app_row:
                abort(404)
            if app_row["status"] not in {"pending", "approved"}:
                return redirect(url_for("customer_dashboard", banner="editing-unavailable"))

            if errors:
                return render_template(
                    "edit_application.html",
                    application={"application_id": application_id, "status": app_row["status"]},
                    form={
                        "organisation_name": organisation_name,
                        "contact_name": contact_name,
                        "contact_email": app_row["contact_email"],
                        "report_email": report_email,
                        "aws_region": aws_region,
                        "report_frequency": report_frequency,
                        "notes": notes,
                        "services": services,
                    },
                    errors=errors,
                ), 400

            cursor.execute(
                "UPDATE organisations SET organisation_name = %s WHERE organisation_id = %s",
                (organisation_name, app_row["organisation_id"]),
            )
            cursor.execute(
                "UPDATE customer_users SET contact_name = %s WHERE customer_user_id = %s",
                (contact_name, session["customer_user_id"]),
            )
            cursor.execute(
                "UPDATE applications SET notes = %s WHERE application_id = %s",
                (notes or None, application_id),
            )
            if app_row["status"] == "approved":
                cursor.execute(
                    "UPDATE applications SET status = 'pending' WHERE application_id = %s",
                    (application_id,),
                )
            cursor.execute(
                """
                UPDATE onboardings
                SET aws_region = %s, report_frequency = %s
                WHERE onboarding_id = %s
                """,
                (aws_region, report_frequency, app_row["onboarding_id"]),
            )
            cursor.execute("DELETE FROM onboarding_services WHERE onboarding_id = %s", (app_row["onboarding_id"],))
            for service_code in services:
                cursor.execute(
                    "INSERT INTO onboarding_services (onboarding_id, service_code) VALUES (%s, %s)",
                    (app_row["onboarding_id"], service_code),
                )
            cursor.execute(
                "DELETE FROM onboarding_report_recipients WHERE onboarding_id = %s",
                (app_row["onboarding_id"],),
            )
            cursor.execute(
                """
                INSERT INTO onboarding_report_recipients (onboarding_id, report_email)
                VALUES (%s, %s)
                """,
                (app_row["onboarding_id"], report_email),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()

        session["customer_name"] = contact_name
        banner = "resubmitted" if app_row["status"] == "approved" else "updated"
        return redirect(url_for("customer_dashboard", banner=banner))

    @app.post("/customer/applications/<int:application_id>/withdraw")
    @state.customer_login_required
    def withdraw_application(application_id):
        conn = state.get_db_connection()
        state.ensure_application_messages_table(conn)
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT application_id, status
                FROM applications
                WHERE application_id = %s
                  AND customer_user_id = %s
                """,
                (application_id, session["customer_user_id"]),
            )
            app_row = cursor.fetchone()
            if not app_row:
                abort(404)
            if app_row["status"] != "pending":
                return redirect(url_for("customer_dashboard", banner="withdraw-unavailable"))

            cursor.execute("DELETE FROM applications WHERE application_id = %s", (application_id,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()

        return redirect(url_for("customer_dashboard", banner="withdrawn"))

    @app.get("/customer/applications/<int:application_id>/messages")
    @state.customer_login_required
    def customer_application_messages(application_id):
        conn = state.get_db_connection()
        state.ensure_application_messages_table(conn)
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT
                    a.application_id,
                    a.status,
                    o.organisation_name,
                    cu.contact_name,
                    cu.email AS contact_email
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
            if not app_row:
                abort(404)

            cursor.execute(
                """
                SELECT sender_role, sender_name, message_body, created_at
                FROM application_messages
                WHERE application_id = %s
                ORDER BY created_at ASC, message_id ASC
                """,
                (application_id,),
            )
            messages = cursor.fetchall()
        finally:
            cursor.close()
            conn.close()

        return render_template(
            "application_messages.html",
            application=app_row,
            messages=messages,
            role_label="Customer Conversation",
            page_title="Contact an Admin",
            page_subtitle="Use this thread to ask questions or discuss changes with the admin team.",
            post_url=url_for("customer_post_application_message", application_id=application_id),
            back_url=url_for("customer_dashboard"),
            back_label="Back to dashboard",
        )

    @app.post("/customer/applications/<int:application_id>/messages")
    @state.customer_login_required
    def customer_post_application_message(application_id):
        message_body = (request.form.get("message_body") or "").strip()
        if not message_body:
            return redirect(url_for("customer_application_messages", application_id=application_id))

        conn = state.get_db_connection()
        state.ensure_application_messages_table(conn)
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT application_id
                FROM applications
                WHERE application_id = %s
                  AND customer_user_id = %s
                """,
                (application_id, session["customer_user_id"]),
            )
            app_row = cursor.fetchone()
            if not app_row:
                abort(404)

            cursor.execute(
                """
                INSERT INTO application_messages (
                    application_id,
                    customer_user_id,
                    admin_id,
                    sender_role,
                    sender_name,
                    message_body
                ) VALUES (%s, %s, NULL, 'customer', %s, %s)
                """,
                (
                    application_id,
                    session["customer_user_id"],
                    session.get("customer_name") or "Customer",
                    message_body,
                ),
            )
            conn.commit()
        finally:
            cursor.close()
            conn.close()

        return redirect(url_for("customer_application_messages", application_id=application_id))

    @app.get("/customer/download-bundle/<int:application_id>")
    @state.customer_login_required
    def download_bundle(application_id):
        conn = state.get_db_connection()
        state.ensure_application_messages_table(conn)
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT
                    a.application_id,
                    a.status,
                    cu.organisation_id,
                    cu.contact_name,
                    cu.email AS contact_email,
                    o.organisation_name,
                    ob.onboarding_id,
                    ob.aws_region,
                    ob.report_frequency
                FROM applications a
                JOIN customer_users cu
                  ON a.customer_user_id = cu.customer_user_id
                JOIN organisations o
                  ON cu.organisation_id = o.organisation_id
                LEFT JOIN onboardings ob
                  ON ob.application_id = a.application_id
                WHERE a.application_id = %s
                  AND a.customer_user_id = %s
                """,
                (application_id, session["customer_user_id"]),
            )
            data = cursor.fetchone()

            if not data:
                return render_template("bundle_error.html", title="Application not found", message="We could not find this application or its deployment bundle."), 404
            if data["status"] == "pending":
                return render_template("bundle_error.html", title="Bundle not available yet", message="Your deployment bundle is not available yet because your application is still under review."), 403
            if data["status"] == "rejected":
                return render_template("bundle_error.html", title="Bundle unavailable", message="Your application was not approved, so a deployment bundle is not available."), 403
            if data["status"] != "approved":
                return render_template("bundle_error.html", title="Bundle unavailable", message="This deployment bundle is not available for the current application status."), 403
            if not data["onboarding_id"]:
                return render_template("bundle_error.html", title="Onboarding data missing", message="We could not generate your deployment bundle because the onboarding configuration is incomplete."), 500

            cursor.execute("SELECT service_code FROM onboarding_services WHERE onboarding_id = %s", (data["onboarding_id"],))
            service_rows = cursor.fetchall()
            enabled_service_codes = [row["service_code"] for row in service_rows]

            cursor.execute(
                """
                SELECT report_email
                FROM onboarding_report_recipients
                WHERE onboarding_id = %s
                ORDER BY report_email
                LIMIT 1
                """,
                (data["onboarding_id"],),
            )
            report_row = cursor.fetchone()
        finally:
            cursor.close()
            conn.close()

        customer_data = state.build_customer_bundle_data(data, enabled_service_codes, report_row)
        try:
            bundle_info = state.create_customer_bundle(customer_data)
        except Exception:
            logger.exception("Bundle generation failed for application_id=%s", application_id)
            return render_template("bundle_error.html", title="Bundle generation failed", message="We could not generate your deployment bundle right now. Please try again later or contact support."), 500

        bundles_root = os.path.join(app.root_path, "generated_bundles")
        zip_path = os.path.join(bundles_root, bundle_info["zip_filename"])
        if not os.path.exists(zip_path):
            return render_template("bundle_error.html", title="Bundle file missing", message="The deployment bundle could not be found after generation. Please try again."), 404

        return send_from_directory(bundles_root, bundle_info["zip_filename"], as_attachment=True)
