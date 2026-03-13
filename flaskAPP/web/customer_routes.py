import logging
import os

from flask import abort, render_template, send_from_directory, session

logger = logging.getLogger(__name__)


def register_customer_routes(app, state):
    @app.get("/customer/dashboard")
    @state.customer_login_required
    def customer_dashboard():
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
                    o.onboarding_id,
                    o.aws_region,
                    o.report_frequency
                FROM applications a
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

            return render_template("customer_dashboard.html", applications=applications)
        finally:
            cursor.close()
            conn.close()

    @app.get("/customer/download-bundle/<int:application_id>")
    @state.customer_login_required
    def download_bundle(application_id):
        conn = state.get_db_connection()
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
