import logging
import os

from flask import abort, redirect, render_template, request, send_from_directory, session, url_for

logger = logging.getLogger(__name__)


def require_superuser():
    return bool(session.get("admin_is_superuser"))


def _with_query(base_url, query_string):
    if query_string:
        return f"{base_url}?{query_string}"
    return base_url


def _load_application_detail(cursor, application_id):
    cursor.execute(
        """
        SELECT
            a.application_id,
            a.status,
            a.notes,
            a.created_at,
            cu.customer_user_id,
            cu.contact_name,
            cu.email AS contact_email,
            cu.organisation_id,
            o.organisation_name,
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
        WHERE a.application_id = %s
        """,
        (application_id,),
    )
    app_row = cursor.fetchone()
    if not app_row:
        return None

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
        (application_id,),
    )
    count_row = cursor.fetchone()
    app_row["message_count"] = count_row["count"] if count_row else 0

    cursor.execute(
        """
        SELECT sender_role, sender_name, message_body, created_at
        FROM application_messages
        WHERE application_id = %s
        ORDER BY created_at ASC, message_id ASC
        """,
        (application_id,),
    )
    app_row["messages"] = cursor.fetchall()
    app_row["last_message_role"] = app_row["messages"][-1]["sender_role"] if app_row["messages"] else None
    app_row["needs_admin_reply"] = app_row["last_message_role"] == "customer"
    return app_row


def register_admin_routes(app, state):
    @app.get("/admin")
    @state.admin_login_required
    def admin_dashboard():
        conn = state.get_db_connection()
        state.ensure_application_messages_table(conn)
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
        pending_count = sum(1 for app_row in apps if app_row["status"] == "pending")
        approved_count = sum(1 for app_row in apps if app_row["status"] == "approved")
        rejected_count = sum(1 for app_row in apps if app_row["status"] == "rejected")
        pending_apps = [app_row for app_row in apps if app_row["status"] == "pending"][:5]
        return render_template(
            "admin_dashboard.html",
            admins=admins_count,
            applications=applications_count,
            onboardings=onboardings_count,
            apps=apps,
            pending_apps=pending_apps,
            pending_count=pending_count,
            approved_count=approved_count,
            rejected_count=rejected_count,
        )

    @app.get("/admin/applications")
    @state.admin_login_required
    def admin_applications():
        search_query = (request.args.get("q") or "").strip()
        status_filter = (request.args.get("status") or "all").strip().lower() or "all"
        service_filter = (request.args.get("service") or "all").strip().lower() or "all"
        region_filter = (request.args.get("region") or "all").strip().lower() or "all"
        frequency_filter = (request.args.get("frequency") or "all").strip().lower() or "all"
        sort_by = (request.args.get("sort") or "newest").strip().lower() or "newest"

        conn = state.get_db_connection()
        state.ensure_application_messages_table(conn)
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
            app_row["needs_admin_reply"] = bool(
                latest_message
                and latest_message.get("sender_role") == "customer"
            )
        cursor.close()
        conn.close()

        available_services = sorted(
            {
                service["service_code"]
                for app_row in applications
                for service in app_row.get("services", [])
                if service.get("service_code")
            }
        )
        available_regions = sorted({app_row["aws_region"] for app_row in applications if app_row.get("aws_region")})
        available_frequencies = sorted(
            {app_row["report_frequency"] for app_row in applications if app_row.get("report_frequency")}
        )

        filtered_applications = []
        query_text = search_query.lower()
        for app_row in applications:
            service_names = [service.get("service_name", "") for service in app_row.get("services", [])]
            service_codes = [service.get("service_code", "") for service in app_row.get("services", [])]
            recipient_emails = [recipient.get("report_email", "") for recipient in app_row.get("report_recipients", [])]

            if status_filter != "all" and app_row.get("status", "").lower() != status_filter:
                continue
            if service_filter != "all" and service_filter not in {code.lower() for code in service_codes}:
                continue
            if region_filter != "all" and (app_row.get("aws_region") or "").lower() != region_filter:
                continue
            if frequency_filter != "all" and (app_row.get("report_frequency") or "").lower() != frequency_filter:
                continue

            if query_text:
                searchable_parts = [
                    str(app_row.get("application_id", "")),
                    app_row.get("organisation_name", ""),
                    app_row.get("contact_name", ""),
                    app_row.get("contact_email", ""),
                    app_row.get("notes", ""),
                    app_row.get("status", ""),
                    app_row.get("aws_region", ""),
                    app_row.get("report_frequency", ""),
                    *service_names,
                    *service_codes,
                    *recipient_emails,
                ]
                haystack = " ".join(part for part in searchable_parts if part).lower()
                if query_text not in haystack:
                    continue

            filtered_applications.append(app_row)

        def sort_key_created(app_row):
            return app_row.get("created_at") or ""

        if sort_by == "oldest":
            filtered_applications.sort(key=sort_key_created)
        elif sort_by == "company_az":
            filtered_applications.sort(key=lambda app_row: (app_row.get("organisation_name") or "").lower())
        elif sort_by == "company_za":
            filtered_applications.sort(key=lambda app_row: (app_row.get("organisation_name") or "").lower(), reverse=True)
        elif sort_by == "status":
            order = {"pending": 0, "approved": 1, "rejected": 2}
            filtered_applications.sort(
                key=lambda app_row: (
                    order.get((app_row.get("status") or "").lower(), 99),
                    -app_row.get("message_count", 0),
                )
            )
        elif sort_by == "messages":
            filtered_applications.sort(
                key=lambda app_row: (app_row.get("message_count", 0), sort_key_created(app_row)),
                reverse=True,
            )
        else:
            filtered_applications.sort(key=sort_key_created, reverse=True)

        return_query = request.query_string.decode("utf-8")
        return render_template(
            "admin_applications.html",
            applications=filtered_applications,
            total_applications=len(applications),
            available_services=available_services,
            available_regions=available_regions,
            available_frequencies=available_frequencies,
            filters={
                "q": search_query,
                "status": status_filter,
                "service": service_filter,
                "region": region_filter,
                "frequency": frequency_filter,
                "sort": sort_by,
            },
            has_filters=any(
                value not in {"", "all", "newest"} for value in [
                    search_query,
                    status_filter,
                    service_filter,
                    region_filter,
                    frequency_filter,
                    sort_by,
                ]
            ),
            return_query=return_query,
        )

    @app.post("/admin/update-status")
    @state.admin_login_required
    def admin_update_status():
        application_id = (request.form.get("application_id") or "").strip()
        new_status = (request.form.get("status") or "").strip()
        return_query = (request.form.get("return_query") or "").strip()
        return_to = (request.form.get("return_to") or "").strip()
        allowed = {"pending", "approved", "rejected"}
        if new_status not in allowed or not application_id.isdigit():
            abort(400)

        application_id_int = int(application_id)
        conn = state.get_db_connection()
        state.ensure_application_messages_table(conn)
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

        if return_to == "detail":
            return redirect(_with_query(url_for("admin_application_detail", application_id=application_id_int), return_query))
        return redirect(_with_query(url_for("admin_applications"), return_query))

    @app.get("/admin/applications/<int:application_id>")
    @state.admin_login_required
    def admin_application_detail(application_id):
        return_query = (request.args.get("return_query") or "").strip()
        conn = state.get_db_connection()
        state.ensure_application_messages_table(conn)
        cursor = conn.cursor(dictionary=True)
        try:
            application = _load_application_detail(cursor, application_id)
            if not application:
                abort(404)
        finally:
            cursor.close()
            conn.close()

        return render_template(
            "admin_application_detail.html",
            application=application,
            return_query=return_query,
            back_url=_with_query(url_for("admin_applications"), return_query),
        )

    @app.get("/admin/applications/<int:application_id>/messages")
    @state.admin_login_required
    def admin_application_messages(application_id):
        return_query = (request.args.get("return_query") or "").strip()
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
                """,
                (application_id,),
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
            role_label="Admin Conversation",
            page_title=f"Application #{application_id} Conversation",
            page_subtitle="View and reply to customer messages from the shared application thread.",
            post_url=url_for("admin_post_application_message", application_id=application_id, return_query=return_query),
            back_url=_with_query(url_for("admin_applications"), return_query),
            back_label="Back to applications",
            return_query=return_query,
        )

    @app.post("/admin/applications/<int:application_id>/messages")
    @state.admin_login_required
    def admin_post_application_message(application_id):
        return_query = (request.args.get("return_query") or request.form.get("return_query") or "").strip()
        return_to = (request.args.get("return_to") or request.form.get("return_to") or "").strip()
        message_body = (request.form.get("message_body") or "").strip()
        if not message_body:
            target = "admin_application_detail" if return_to == "detail" else "admin_application_messages"
            return redirect(_with_query(url_for(target, application_id=application_id), return_query))

        conn = state.get_db_connection()
        state.ensure_application_messages_table(conn)
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                "SELECT application_id FROM applications WHERE application_id = %s",
                (application_id,),
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
                ) VALUES (%s, NULL, %s, 'admin', %s, %s)
                """,
                (
                    application_id,
                    session.get("admin_id"),
                    session.get("admin_email") or "Admin",
                    message_body,
                ),
            )
            conn.commit()
        finally:
            cursor.close()
            conn.close()

        target = "admin_application_detail" if return_to == "detail" else "admin_application_messages"
        return redirect(_with_query(url_for(target, application_id=application_id), return_query))

    @app.get("/admin/download-bundle/<int:application_id>")
    @state.admin_login_required
    def admin_download_bundle(application_id):
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
                """,
                (application_id,),
            )
            data = cursor.fetchone()

            if not data:
                return render_template("bundle_error.html", title="Application not found", message="We could not find this application or its deployment bundle."), 404
            if data["status"] == "pending":
                return render_template("bundle_error.html", title="Bundle not available yet", message="This deployment bundle is not available yet because the application is still under review."), 403
            if data["status"] == "rejected":
                return render_template("bundle_error.html", title="Bundle unavailable", message="This application was not approved, so a deployment bundle is not available."), 403
            if data["status"] != "approved":
                return render_template("bundle_error.html", title="Bundle unavailable", message="This deployment bundle is not available for the current application status."), 403
            if not data["onboarding_id"]:
                return render_template("bundle_error.html", title="Onboarding data missing", message="We could not generate the deployment bundle because the onboarding configuration is incomplete."), 500

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
            logger.exception("Bundle generation failed for admin download, application_id=%s", application_id)
            return render_template("bundle_error.html", title="Bundle generation failed", message="We could not generate the deployment bundle right now. Please try again later."), 500

        bundles_root = os.path.join(app.root_path, "generated_bundles")
        zip_path = os.path.join(bundles_root, bundle_info["zip_filename"])
        if not os.path.exists(zip_path):
            return render_template("bundle_error.html", title="Bundle file missing", message="The deployment bundle could not be found after generation. Please try again."), 404

        return send_from_directory(bundles_root, bundle_info["zip_filename"], as_attachment=True)

    @app.get("/admin/admins")
    @state.admin_login_required
    def admin_manage_admins():
        if not require_superuser():
            return redirect(url_for("admin_dashboard"))
        conn = state.get_db_connection()
        state.ensure_admin_superuser_support(conn)
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT admin_id, full_name, email, password_hash, is_active, is_superuser, created_at
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
        if not require_superuser():
            return redirect(url_for("admin_dashboard"))
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
        state.ensure_admin_superuser_support(conn)
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO admins (full_name, email, password_hash, is_superuser)
                VALUES (%s, %s, %s, 0)
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
        if not require_superuser():
            return redirect(url_for("admin_dashboard"))
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
        state.ensure_admin_superuser_support(conn)
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
        if not require_superuser():
            return redirect(url_for("admin_dashboard"))
        admin_id = (request.form.get("admin_id") or "").strip()
        if not admin_id.isdigit():
            abort(400)
        admin_id_int = int(admin_id)
        if session.get("admin_id") == admin_id_int:
            return redirect(url_for("admin_manage_admins"))

        conn = state.get_db_connection()
        state.ensure_admin_superuser_support(conn)
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
