import logging
import os

from flask import abort, redirect, render_template, request, send_file, send_from_directory, session, url_for

logger = logging.getLogger(__name__)

_ADMIN_MESSAGE_VIEW_SESSION_KEY = "admin_message_views"


def require_superuser():
    return bool(session.get("admin_is_superuser"))


def _with_query(base_url, query_string):
    if query_string:
        return f"{base_url}?{query_string}"
    return base_url


def _get_last_viewed_message_id(application_id):
    viewed_messages = session.get(_ADMIN_MESSAGE_VIEW_SESSION_KEY, {})
    try:
        return int(viewed_messages.get(str(application_id), 0) or 0)
    except (TypeError, ValueError):
        return 0


def _mark_messages_viewed(application_id, latest_message_id):
    viewed_messages = dict(session.get(_ADMIN_MESSAGE_VIEW_SESSION_KEY, {}))
    viewed_messages[str(application_id)] = int(latest_message_id or 0)
    session[_ADMIN_MESSAGE_VIEW_SESSION_KEY] = viewed_messages


def _load_contact_messages(cursor):
    cursor.execute(
        """
        SELECT
            cm.contact_message_id,
            cm.sender_mode,
            cm.sender_name,
            cm.sender_email,
            cm.message_body,
            cm.created_at,
            cu.organisation_id,
            o.organisation_name
        FROM contact_messages cm
        LEFT JOIN customer_users cu
          ON cm.customer_user_id = cu.customer_user_id
        LEFT JOIN organisations o
          ON cu.organisation_id = o.organisation_id
        ORDER BY cm.created_at DESC, cm.contact_message_id DESC
        """
    )
    return cursor.fetchall()


def _load_admin_record(cursor, admin_id: int):
    cursor.execute(
        """
        SELECT admin_id, full_name, email, password_hash, is_active, is_superuser, created_at
        FROM admins
        WHERE admin_id = %s
        """,
        (admin_id,),
    )
    return cursor.fetchone()


def _load_application_detail(cursor, application_id):
    cursor.execute(
        """
        SELECT
            a.application_id,
            a.status,
            a.notes,
            a.created_at,
            cu.customer_user_id,
            COALESCE(a.contact_name, cu.contact_name) AS contact_name,
            COALESCE(a.contact_email, cu.email) AS contact_email,
            cu.organisation_id,
            COALESCE(a.organisation_name, o.organisation_name) AS organisation_name,
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
        SELECT message_id, sender_role, sender_name, message_body, created_at
        FROM application_messages
        WHERE application_id = %s
        ORDER BY created_at ASC, message_id ASC
        """,
        (application_id,),
    )
    app_row["messages"] = cursor.fetchall()
    latest_message = app_row["messages"][-1] if app_row["messages"] else None
    latest_message_id = latest_message.get("message_id", 0) if latest_message else 0
    app_row["last_message_role"] = latest_message.get("sender_role") if latest_message else None
    app_row["needs_admin_reply"] = bool(
        latest_message
        and latest_message["sender_role"] == "customer"
        and latest_message_id > _get_last_viewed_message_id(application_id)
    )
    app_row["latest_message_id"] = latest_message_id
    return app_row


def register_admin_routes(app, state):
    @app.get("/admin")
    @state.admin_login_required
    def admin_dashboard():
        conn = state.get_db_connection()
        state.ensure_application_snapshot_columns(conn)
        state.ensure_application_messages_table(conn)
        state.ensure_contact_messages_table(conn)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT COUNT(*) AS count FROM admins")
        admins_count = cursor.fetchone()["count"]
        cursor.execute("SELECT COUNT(*) AS count FROM applications")
        applications_count = cursor.fetchone()["count"]
        cursor.execute("SELECT COUNT(*) AS count FROM onboardings")
        onboardings_count = cursor.fetchone()["count"]
        cursor.execute("SELECT COUNT(*) AS count FROM contact_messages")
        contact_messages_count = cursor.fetchone()["count"]
        cursor.execute(
            """
            SELECT
                a.application_id,
                COALESCE(a.organisation_name, o.organisation_name) AS organisation_name,
                COALESCE(a.contact_name, cu.contact_name) AS contact_name,
                COALESCE(a.contact_email, cu.email) AS contact_email,
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
        cursor.execute(
            """
            SELECT
                am.message_id,
                am.application_id,
                am.sender_role,
                am.sender_name,
                am.message_body,
                am.created_at,
                a.status,
                COALESCE(a.organisation_name, o.organisation_name) AS organisation_name,
                COALESCE(a.contact_name, cu.contact_name) AS contact_name,
                COALESCE(a.contact_email, cu.email) AS contact_email
            FROM application_messages am
            JOIN applications a
              ON am.application_id = a.application_id
            JOIN customer_users cu
              ON a.customer_user_id = cu.customer_user_id
            JOIN organisations o
              ON cu.organisation_id = o.organisation_id
            WHERE am.sender_role = 'customer'
            ORDER BY am.created_at DESC, am.message_id DESC
            LIMIT 5
            """
        )
        recent_messages = cursor.fetchall()
        contact_preview = _load_contact_messages(cursor)[:4]
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
            contact_messages_count=contact_messages_count,
            contact_preview=contact_preview,
            apps=apps,
            recent_messages=recent_messages,
            pending_apps=pending_apps,
            pending_count=pending_count,
            approved_count=approved_count,
            rejected_count=rejected_count,
        )

    @app.get("/admin/contact-messages")
    @state.admin_login_required
    def admin_contact_messages():
        conn = state.get_db_connection()
        state.ensure_contact_messages_table(conn)
        cursor = conn.cursor(dictionary=True)
        try:
            messages = _load_contact_messages(cursor)
        finally:
            cursor.close()
            conn.close()

        return render_template(
            "admin_contact_messages.html",
            messages=messages,
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
        state.ensure_application_snapshot_columns(conn)
        state.ensure_application_messages_table(conn)
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT
                a.application_id,
                COALESCE(a.organisation_name, o.organisation_name) AS organisation_name,
                COALESCE(a.contact_name, cu.contact_name) AS contact_name,
                COALESCE(a.contact_email, cu.email) AS contact_email,
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
                SELECT message_id, sender_role
                FROM application_messages
                WHERE application_id = %s
                ORDER BY created_at DESC, message_id DESC
                LIMIT 1
                """,
                (app_row["application_id"],),
            )
            latest_message = cursor.fetchone()
            latest_message_id = latest_message.get("message_id", 0) if latest_message else 0
            app_row["needs_admin_reply"] = bool(
                latest_message
                and latest_message.get("sender_role") == "customer"
                and latest_message_id > _get_last_viewed_message_id(app_row["application_id"])
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
        state.ensure_application_snapshot_columns(conn)
        state.ensure_application_messages_table(conn)
        cursor = conn.cursor(dictionary=True)
        notification_target = None
        try:
            cursor.execute(
                """
                SELECT
                    a.application_id,
                    a.status,
                    cu.organisation_id,
                    COALESCE(a.contact_name, cu.contact_name) AS contact_name,
                    COALESCE(a.contact_email, cu.email) AS contact_email,
                    COALESCE(a.organisation_name, o.organisation_name) AS organisation_name
                FROM applications a
                JOIN customer_users cu
                  ON a.customer_user_id = cu.customer_user_id
                JOIN organisations o
                  ON cu.organisation_id = o.organisation_id
                WHERE a.application_id = %s
                """,
                (application_id_int,),
            )
            current_row = cursor.fetchone()
            if not current_row:
                abort(404)

            previous_status = (current_row.get("status") or "").strip()

            if new_status == "approved":
                approval_cursor = conn.cursor(dictionary=True)
                approval_cursor.execute(
                    """
                    SELECT
                        a.application_id,
                        cu.organisation_id,
                        COALESCE(a.contact_name, cu.contact_name) AS contact_name,
                        COALESCE(a.contact_email, cu.email) AS contact_email,
                        COALESCE(a.organisation_name, o.organisation_name) AS organisation_name,
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
                    (application_id_int,),
                )
                data = approval_cursor.fetchone()
                logger.info("Approval query returned onboarding data for application_id=%s", application_id_int)
                if not data:
                    raise ValueError(f"No onboarding data found for application_id={application_id_int}")

                if data["onboarding_id"]:
                    approval_cursor.execute("SELECT service_code FROM onboarding_services WHERE onboarding_id = %s", (data["onboarding_id"],))
                    service_rows = approval_cursor.fetchall()
                    enabled_service_codes = [row["service_code"] for row in service_rows]

                    approval_cursor.execute(
                        """
                        SELECT report_email
                        FROM onboarding_report_recipients
                        WHERE onboarding_id = %s
                        ORDER BY report_email
                        """,
                        (data["onboarding_id"],),
                    )
                    report_rows = approval_cursor.fetchall()
                else:
                    enabled_service_codes = []
                    report_rows = []
                customer_data = state.build_customer_bundle_data(data, enabled_service_codes, report_rows)
                bundle_info = state.create_customer_bundle(customer_data)
                logger.info(
                    "Customer bundle created for application_id=%s as %s",
                    application_id_int,
                    bundle_info.get("zip_filename"),
                )
                approval_cursor.close()

            update_cursor = conn.cursor()
            update_cursor.execute(
                "UPDATE applications SET status = %s WHERE application_id = %s",
                (new_status, application_id_int),
            )
            conn.commit()
            update_cursor.close()

            if previous_status != new_status:
                notification_target = current_row
        finally:
            cursor.close()
            conn.close()

        if notification_target:
            try:
                state.send_application_status_notification(
                    app,
                    state.app_config,
                    notification_target.get("contact_email", ""),
                    notification_target.get("contact_name", ""),
                    notification_target.get("organisation_name", ""),
                    application_id_int,
                    new_status,
                )
            except Exception:
                logger.exception("Status notification email failed for application_id=%s", application_id_int)

        if return_to == "detail":
            return redirect(_with_query(url_for("admin_application_detail", application_id=application_id_int), return_query))
        return redirect(_with_query(url_for("admin_applications"), return_query))

    @app.get("/admin/applications/<int:application_id>")
    @state.admin_login_required
    def admin_application_detail(application_id):
        return_query = (request.args.get("return_query") or "").strip()
        conn = state.get_db_connection()
        state.ensure_application_snapshot_columns(conn)
        state.ensure_application_messages_table(conn)
        cursor = conn.cursor(dictionary=True)
        try:
            application = _load_application_detail(cursor, application_id)
            if not application:
                abort(404)
        finally:
            cursor.close()
            conn.close()

        if application.get("latest_message_id"):
            _mark_messages_viewed(application_id, application["latest_message_id"])
            application["needs_admin_reply"] = False

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
        state.ensure_application_snapshot_columns(conn)
        state.ensure_application_messages_table(conn)
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT
                    a.application_id,
                    a.status,
                    COALESCE(a.organisation_name, o.organisation_name) AS organisation_name,
                    COALESCE(a.contact_name, cu.contact_name) AS contact_name,
                    COALESCE(a.contact_email, cu.email) AS contact_email
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
                SELECT message_id, sender_role, sender_name, message_body, created_at
                FROM application_messages
                WHERE application_id = %s
                ORDER BY created_at ASC, message_id ASC
                """,
                (application_id,),
            )
            messages = cursor.fetchall()
            latest_message_id = messages[-1].get("message_id", 0) if messages else 0
        finally:
            cursor.close()
            conn.close()

        if latest_message_id:
            _mark_messages_viewed(application_id, latest_message_id)

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
        state.ensure_application_snapshot_columns(conn)
        state.ensure_application_messages_table(conn)
        cursor = conn.cursor(dictionary=True)
        inserted_message_id = 0
        try:
            cursor.execute(
                """
                SELECT
                    a.application_id,
                    COALESCE(a.organisation_name, o.organisation_name) AS organisation_name,
                    COALESCE(a.contact_name, cu.contact_name) AS contact_name,
                    COALESCE(a.contact_email, cu.email) AS contact_email
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
            inserted_message_id = int(getattr(cursor, "lastrowid", 0) or 0)
            if not inserted_message_id:
                cursor.execute(
                    """
                    SELECT message_id
                    FROM application_messages
                    WHERE application_id = %s AND sender_role = 'admin'
                    ORDER BY created_at DESC, message_id DESC
                    LIMIT 1
                    """,
                    (application_id,),
                )
                latest_admin_message = cursor.fetchone()
                inserted_message_id = int((latest_admin_message or {}).get("message_id") or 0)

            notification_state = state.get_customer_admin_message_state(cursor, application_id)
            should_send_notification = (
                inserted_message_id
                and int(notification_state.get("customer_last_notified_admin_message_id", 0) or 0)
                <= int(notification_state.get("customer_last_read_admin_message_id", 0) or 0)
            )
        finally:
            cursor.close()
            conn.close()

        if should_send_notification:
            try:
                sent = state.send_application_message_notification(
                    app,
                    state.app_config,
                    app_row.get("contact_email", ""),
                    app_row.get("contact_name", ""),
                    app_row.get("organisation_name", ""),
                    application_id,
                    session.get("admin_email") or "Admin",
                )
                if sent and inserted_message_id:
                    notify_conn = state.get_db_connection()
                    state.ensure_application_messages_table(notify_conn)
                    try:
                        state.mark_customer_admin_messages_notified(notify_conn, application_id, inserted_message_id)
                    finally:
                        notify_conn.close()
            except Exception:
                logger.exception("Message notification email failed for application_id=%s", application_id)

        target = "admin_application_detail" if return_to == "detail" else "admin_application_messages"
        return redirect(_with_query(url_for(target, application_id=application_id), return_query))

    @app.get("/admin/download-bundle/<int:application_id>")
    @state.admin_login_required
    def admin_download_bundle(application_id):
        conn = state.get_db_connection()
        state.ensure_application_snapshot_columns(conn)
        state.ensure_application_messages_table(conn)
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT
                    a.application_id,
                    a.status,
                    cu.organisation_id,
                    COALESCE(a.contact_name, cu.contact_name) AS contact_name,
                    COALESCE(a.contact_email, cu.email) AS contact_email,
                    COALESCE(a.organisation_name, o.organisation_name) AS organisation_name,
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
            if data["onboarding_id"]:
                cursor.execute("SELECT service_code FROM onboarding_services WHERE onboarding_id = %s", (data["onboarding_id"],))
                service_rows = cursor.fetchall()
                enabled_service_codes = [row["service_code"] for row in service_rows]

                cursor.execute(
                    """
                    SELECT report_email
                    FROM onboarding_report_recipients
                    WHERE onboarding_id = %s
                    ORDER BY report_email
                    """,
                    (data["onboarding_id"],),
                )
                report_rows = cursor.fetchall()
            else:
                enabled_service_codes = []
                report_rows = []
        finally:
            cursor.close()
            conn.close()

        try:
            customer_data = state.build_customer_bundle_data(data, enabled_service_codes, report_rows)
            bundle_info = state.create_customer_bundle(customer_data)
        except Exception:
            logger.exception("Bundle generation failed for admin download, application_id=%s", application_id)
            return render_template("bundle_error.html", title="Bundle generation failed", message="We could not generate the deployment bundle right now. Please try again later."), 500

        bundles_root = os.path.join(app.root_path, "generated_bundles")
        zip_path = os.path.join(bundles_root, bundle_info["zip_filename"])
        if not os.path.exists(zip_path):
            return render_template("bundle_error.html", title="Bundle file missing", message="The deployment bundle could not be found after generation. Please try again."), 404

        return send_file(
            zip_path,
            as_attachment=True,
            download_name=bundle_info["zip_filename"],
            mimetype="application/zip",
        )

    @app.get("/admin/admins")
    @state.admin_login_required
    def admin_manage_admins():
        if not require_superuser():
            return redirect(url_for("admin_dashboard"))
        banner = (request.args.get("banner") or "").strip()
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
        return render_template("admin_admins.html", admins_list=admins_list, banner=banner)

    @app.get("/admin/admins/new")
    @state.admin_login_required
    def admin_new_admin():
        if not require_superuser():
            return redirect(url_for("admin_dashboard"))
        status = (request.args.get("status") or "").strip()
        error = None
        success = None
        if status == "invalid-email":
            error = "Enter a valid admin email address."
        elif status == "short-password":
            error = "Password must be at least 8 characters long."
        elif status == "password-mismatch":
            error = "Passwords do not match."
        elif status == "create-failed":
            error = "We could not create that admin account right now."
        elif status == "created":
            success = "Admin account created successfully."
        return render_template("admin_add_admin.html", error=error, success=success)

    @app.get("/admin/admins/<int:admin_id>/edit")
    @state.admin_login_required
    def admin_edit_admin(admin_id):
        if not require_superuser():
            return redirect(url_for("admin_dashboard"))

        status = (request.args.get("status") or "").strip()
        error = None
        success = None
        if status == "invalid-email":
            error = "Enter a valid admin email address."
        elif status == "short-password":
            error = "Password must be at least 8 characters long."
        elif status == "password-mismatch":
            error = "Passwords do not match."
        elif status == "update-failed":
            error = "We could not update that admin account right now."
        elif status == "updated":
            success = "Admin account updated successfully."

        conn = state.get_db_connection()
        state.ensure_admin_superuser_support(conn)
        cursor = conn.cursor(dictionary=True)
        try:
            admin_record = _load_admin_record(cursor, admin_id)
            if not admin_record:
                abort(404)
        finally:
            cursor.close()
            conn.close()

        return render_template(
            "admin_edit_admin.html",
            admin_record=admin_record,
            error=error,
            success=success,
        )

    @app.post("/admin/admins/create")
    @state.admin_login_required
    def admin_create_admin():
        if not require_superuser():
            return redirect(url_for("admin_dashboard"))
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm_password") or ""
        if not email or "@" not in email:
            return redirect(url_for("admin_new_admin", status="invalid-email"))
        if len(password) < 8:
            return redirect(url_for("admin_new_admin", status="short-password"))
        if password != confirm:
            return redirect(url_for("admin_new_admin", status="password-mismatch"))

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
            return redirect(url_for("admin_new_admin", status="create-failed"))
        finally:
            cursor.close()
            conn.close()
        return redirect(url_for("admin_new_admin", status="created"))

    @app.post("/admin/admins/update")
    @state.admin_login_required
    def admin_update_admin():
        if not require_superuser():
            return redirect(url_for("admin_dashboard"))

        admin_id = (request.form.get("admin_id") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        new_password = request.form.get("new_password") or ""
        confirm_password = request.form.get("confirm_password") or ""

        if not admin_id.isdigit():
            abort(400)

        admin_id_int = int(admin_id)
        if not state.is_valid_email(email):
            return redirect(url_for("admin_edit_admin", admin_id=admin_id_int, status="invalid-email"))
        if new_password and len(new_password) < 8:
            return redirect(url_for("admin_edit_admin", admin_id=admin_id_int, status="short-password"))
        if new_password != confirm_password:
            return redirect(url_for("admin_edit_admin", admin_id=admin_id_int, status="password-mismatch"))

        conn = state.get_db_connection()
        state.ensure_admin_superuser_support(conn)
        cursor = conn.cursor(dictionary=True)
        try:
            admin_record = _load_admin_record(cursor, admin_id_int)
            if not admin_record:
                abort(404)

            if new_password:
                cursor.close()
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE admins SET email = %s, password_hash = %s WHERE admin_id = %s",
                    (email, state.hash_password(new_password), admin_id_int),
                )
            else:
                cursor.close()
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE admins SET email = %s WHERE admin_id = %s",
                    (email, admin_id_int),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            return redirect(url_for("admin_edit_admin", admin_id=admin_id_int, status="update-failed"))
        finally:
            cursor.close()
            conn.close()

        return redirect(url_for("admin_edit_admin", admin_id=admin_id_int, status="updated"))

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
            return redirect(url_for("admin_manage_admins", banner="password-invalid"))
        if new_password != confirm_password:
            return redirect(url_for("admin_manage_admins", banner="password-mismatch"))

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
        return redirect(url_for("admin_manage_admins", banner="password-updated"))

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
            return redirect(url_for("admin_manage_admins", banner="delete-blocked"))

        conn = state.get_db_connection()
        state.ensure_admin_superuser_support(conn)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT COUNT(*) AS count FROM admins")
        total_admins = cursor.fetchone()["count"]
        if total_admins <= 1:
            cursor.close()
            conn.close()
            return redirect(url_for("admin_manage_admins", banner="delete-blocked"))
        cursor.close()

        cursor2 = conn.cursor()
        cursor2.execute("DELETE FROM admins WHERE admin_id = %s", (admin_id_int,))
        conn.commit()
        cursor2.close()
        conn.close()
        return redirect(url_for("admin_manage_admins", banner="deleted"))
