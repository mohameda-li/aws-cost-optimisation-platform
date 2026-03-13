import logging

from flask import abort, redirect, render_template, request, session, url_for

logger = logging.getLogger(__name__)


def register_admin_routes(app, state):
    @app.get("/admin")
    @state.admin_login_required
    def admin_dashboard():
        conn = state.get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT COUNT(*) AS count FROM admins")
        admins_count = cursor.fetchone()["count"]
        cursor.execute("SELECT COUNT(*) AS count FROM applications")
        applications_count = cursor.fetchone()["count"]
        cursor.execute("SELECT COUNT(*) AS count FROM onboardings")
        onboardings_count = cursor.fetchone()["count"]
        cursor.execute(
            """
            SELECT
                a.application_id,
                o.organisation_name,
                cu.contact_name,
                cu.email AS contact_email,
                a.status,
                a.created_at
            FROM applications a
            JOIN customer_users cu
              ON a.customer_user_id = cu.customer_user_id
            JOIN organisations o
              ON cu.organisation_id = o.organisation_id
            ORDER BY a.created_at DESC
            """
        )
        apps = cursor.fetchall()
        cursor.close()
        conn.close()
        return render_template(
            "admin_dashboard.html",
            admins=admins_count,
            applications=applications_count,
            onboardings=onboardings_count,
            apps=apps,
        )

    @app.get("/admin/applications")
    @state.admin_login_required
    def admin_applications():
        conn = state.get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT
                a.application_id,
                o.organisation_name,
                cu.contact_name,
                cu.email AS contact_email,
                a.notes,
                a.status,
                a.created_at,
                ob.onboarding_id,
                ob.aws_region,
                ob.report_frequency,
                ob.updated_at AS onboarding_updated_at
            FROM applications a
            JOIN customer_users cu
              ON a.customer_user_id = cu.customer_user_id
            JOIN organisations o
              ON cu.organisation_id = o.organisation_id
            LEFT JOIN onboardings ob
              ON ob.application_id = a.application_id
            ORDER BY a.created_at DESC
            """
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
        cursor.close()
        conn.close()
        return render_template("admin_applications.html", applications=applications)

    @app.post("/admin/update-status")
    @state.admin_login_required
    def admin_update_status():
        application_id = (request.form.get("application_id") or "").strip()
        new_status = (request.form.get("status") or "").strip()
        allowed = {"pending", "approved", "rejected"}
        if new_status not in allowed or not application_id.isdigit():
            abort(400)

        application_id_int = int(application_id)
        conn = state.get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "UPDATE applications SET status = %s WHERE application_id = %s",
                (new_status, application_id_int),
            )
            conn.commit()

            if new_status == "approved":
                cursor = conn.cursor(dictionary=True)
                cursor.execute(
                    """
                    SELECT
                        a.application_id,
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
                    JOIN onboardings ob
                      ON ob.application_id = a.application_id
                    WHERE a.application_id = %s
                    """,
                    (application_id_int,),
                )
                data = cursor.fetchone()
                logger.info("Approval query returned onboarding data for application_id=%s", application_id_int)
                if not data:
                    raise ValueError(f"No onboarding data found for application_id={application_id_int}")

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
                customer_data = state.build_customer_bundle_data(data, enabled_service_codes, report_row)
                bundle_info = state.create_customer_bundle(customer_data)
                logger.info(
                    "Customer bundle created for application_id=%s as %s",
                    application_id_int,
                    bundle_info.get("zip_filename"),
                )
        finally:
            cursor.close()
            conn.close()

        return redirect(url_for("admin_applications"))

    @app.get("/admin/admins")
    @state.admin_login_required
    def admin_manage_admins():
        conn = state.get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT admin_id, full_name, email, password_hash, is_active, created_at
            FROM admins
            ORDER BY created_at DESC
            """
        )
        admins_list = cursor.fetchall()
        cursor.close()
        conn.close()
        return render_template("admin_admins.html", admins_list=admins_list)

    @app.post("/admin/admins/create")
    @state.admin_login_required
    def admin_create_admin():
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm_password") or ""
        if not email or "@" not in email:
            return redirect(url_for("admin_manage_admins"))
        if len(password) < 8:
            return redirect(url_for("admin_manage_admins"))
        if password != confirm:
            return redirect(url_for("admin_manage_admins"))

        conn = state.get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO admins (full_name, email, password_hash)
                VALUES (%s, %s, %s)
                """,
                ("Admin", email, state.hash_password(password)),
            )
            conn.commit()
        except Exception:
            conn.rollback()
        finally:
            cursor.close()
            conn.close()
        return redirect(url_for("admin_manage_admins"))

    @app.post("/admin/admins/update-password")
    @state.admin_login_required
    def admin_update_admin_password():
        admin_id = (request.form.get("admin_id") or "").strip()
        new_password = request.form.get("new_password") or ""
        confirm_password = request.form.get("confirm_password") or ""
        if not admin_id.isdigit():
            abort(400)
        if len(new_password) < 8:
            return redirect(url_for("admin_manage_admins"))
        if new_password != confirm_password:
            return redirect(url_for("admin_manage_admins"))

        conn = state.get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE admins SET password_hash = %s WHERE admin_id = %s",
            (state.hash_password(new_password), int(admin_id)),
        )
        conn.commit()
        cursor.close()
        conn.close()
        return redirect(url_for("admin_manage_admins"))

    @app.post("/admin/admins/delete")
    @state.admin_login_required
    def admin_delete_admin():
        admin_id = (request.form.get("admin_id") or "").strip()
        if not admin_id.isdigit():
            abort(400)
        admin_id_int = int(admin_id)
        if session.get("admin_id") == admin_id_int:
            return redirect(url_for("admin_manage_admins"))

        conn = state.get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT COUNT(*) AS count FROM admins")
        total_admins = cursor.fetchone()["count"]
        if total_admins <= 1:
            cursor.close()
            conn.close()
            return redirect(url_for("admin_manage_admins"))
        cursor.close()

        cursor2 = conn.cursor()
        cursor2.execute("DELETE FROM admins WHERE admin_id = %s", (admin_id_int,))
        conn.commit()
        cursor2.close()
        conn.close()
        return redirect(url_for("admin_manage_admins"))
