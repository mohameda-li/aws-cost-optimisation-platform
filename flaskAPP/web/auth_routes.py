import secrets
from datetime import timedelta

from flask import redirect, render_template, request, session, url_for


RESET_SESSION_KEY = "password_reset"
RESET_VERIFY_SESSION_KEY = "password_reset_verification"
RESET_TTL_MINUTES = 15


def register_auth_routes(app, state):
    @app.get("/login")
    def login_page():
        if session.get("user_role") == "admin":
            return redirect(url_for("admin_dashboard"))
        if session.get("user_role") == "customer":
            return redirect(url_for("customer_dashboard"))
        return render_template("login.html", error=None, email="", success=None)

    @app.post("/login")
    def login_submit():
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        if not email or not password:
            return render_template("login.html", error="Email and password are required.", email=email, success=None), 400

        conn = state.get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            state.ensure_admin_superuser_support(conn)
            account = state.find_account_by_email(cursor, email)
            if account and account["user_role"] == "admin":
                if not account["is_active"]:
                    return render_template("login.html", error="This admin account is inactive.", email=email, success=None), 403
                if state.verify_password(account.get("password_hash"), password):
                    session.clear()
                    session["user_role"] = "admin"
                    session["admin_id"] = account["account_id"]
                    session["admin_email"] = account["email"]
                    session["admin_name"] = account["display_name"]
                    session["admin_is_superuser"] = bool(account.get("is_superuser"))
                    return redirect(url_for("admin_dashboard"))

            if account and account["user_role"] == "customer" and state.verify_password(account.get("password_hash"), password):
                session.clear()
                session["user_role"] = "customer"
                session["customer_user_id"] = account["account_id"]
                session["customer_email"] = account["email"]
                session["customer_name"] = account["display_name"]
                session["organisation_id"] = account["organisation_id"]
                return redirect(url_for("customer_dashboard"))

            return render_template("login.html", error="Invalid email or password.", email=email, success=None), 401
        finally:
            cursor.close()
            conn.close()

    @app.get("/forgot-password")
    def forgot_password_page():
        if session.get("user_role") == "admin":
            return redirect(url_for("admin_dashboard"))
        if session.get("user_role") == "customer":
            return redirect(url_for("customer_dashboard"))
        session.pop(RESET_SESSION_KEY, None)
        session.pop(RESET_VERIFY_SESSION_KEY, None)
        return render_template("forgot_password.html", error=None, success=None, email="", account=None)

    @app.post("/forgot-password")
    def forgot_password_submit():
        email = (request.form.get("email") or "").strip().lower()
        if not email:
            return render_template("forgot_password.html", error="Email is required.", success=None, email="", account=None), 400

        conn = state.get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            state.ensure_admin_superuser_support(conn)
            account = state.find_account_by_email(cursor, email)
            if not account:
                session.pop(RESET_SESSION_KEY, None)
                return render_template(
                    "forgot_password.html",
                    error="Cannot find an account with this email.",
                    success=None,
                    email="",
                    account=None,
                ), 404

            verification_code = state.generate_verification_code()
            state.send_verification_code(app, state.app_config, email, "Password reset", verification_code)
            session[RESET_VERIFY_SESSION_KEY] = {
                "email": email,
                "code": verification_code,
                "expires_at": (state.utc_now() + timedelta(minutes=RESET_TTL_MINUTES)).isoformat(),
            }
            return redirect(url_for("forgot_password_verify_page"))
        finally:
            cursor.close()
            conn.close()

    @app.get("/forgot-password/verify")
    def forgot_password_verify_page():
        verification_state = session.get(RESET_VERIFY_SESSION_KEY)
        if not verification_state:
            return redirect(url_for("forgot_password_page"))
        debug_code = None if state.app_config.is_production else verification_state.get("code")
        return render_template(
            "verify_code.html",
            title="Verify Reset Request",
            heading="Verify your reset request",
            subtitle="Enter the verification code sent to your email before you reset your password.",
            email=verification_state.get("email", ""),
            action_url=url_for("forgot_password_verify_submit"),
            back_url=url_for("forgot_password_page"),
            debug_code=debug_code,
            error=None,
            purpose_label="password reset",
        )

    @app.post("/forgot-password/verify")
    def forgot_password_verify_submit():
        verification_state = session.get(RESET_VERIFY_SESSION_KEY)
        if not verification_state or state.utc_now().isoformat() > str(verification_state.get("expires_at", "")):
            session.pop(RESET_VERIFY_SESSION_KEY, None)
            return redirect(url_for("forgot_password_page"))

        verification_code = (request.form.get("verification_code") or "").strip()
        valid = verification_code == verification_state.get("code")
        error = "Verification code is incorrect."

        if not valid:
            debug_code = None if state.app_config.is_production else verification_state.get("code")
            return render_template(
                "verify_code.html",
                title="Verify Reset Request",
                heading="Verify your reset request",
                subtitle="Enter the verification code sent to your email before you reset your password.",
                email=verification_state.get("email", ""),
                action_url=url_for("forgot_password_verify_submit"),
                back_url=url_for("forgot_password_page"),
                debug_code=debug_code,
                error=error,
                purpose_label="password reset",
            ), 400

        reset_token = secrets.token_urlsafe(24)
        session[RESET_SESSION_KEY] = {
            "email": verification_state["email"],
            "token": reset_token,
            "expires_at": (state.utc_now() + timedelta(minutes=RESET_TTL_MINUTES)).isoformat(),
        }
        session.pop(RESET_VERIFY_SESSION_KEY, None)
        return redirect(url_for("forgot_password_reset_page"))

    @app.get("/forgot-password/reset")
    def forgot_password_reset_page():
        reset_state = session.get(RESET_SESSION_KEY) or {}
        email = reset_state.get("email", "")
        if not email:
            return redirect(url_for("forgot_password_page"))

        conn = state.get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            state.ensure_admin_superuser_support(conn)
            account = state.find_account_by_email(cursor, email)
        finally:
            cursor.close()
            conn.close()

        if not account:
            session.pop(RESET_SESSION_KEY, None)
            return redirect(url_for("forgot_password_page"))

        return render_template("forgot_password.html", error=None, success=None, email=email, account=account, reset_token=reset_state.get("token"))

    @app.post("/forgot-password/reset")
    def forgot_password_reset_submit():
        email = (request.form.get("email") or "").strip().lower()
        new_password = request.form.get("password") or ""
        confirm_password = request.form.get("confirm_password") or ""
        reset_token = request.form.get("reset_token") or ""
        reset_state = session.get(RESET_SESSION_KEY) or {}

        conn = state.get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            state.ensure_admin_superuser_support(conn)
            account = state.find_account_by_email(cursor, email)
            if (
                not account
                or not reset_state
                or reset_state.get("email") != email
                or reset_state.get("token") != reset_token
                or state.utc_now().isoformat() > str(reset_state.get("expires_at", ""))
            ):
                session.pop(RESET_SESSION_KEY, None)
                return render_template(
                    "forgot_password.html",
                    error="Your reset session has expired. Please start again.",
                    success=None,
                    email="",
                    account=None,
                ), 400
            if len(new_password) < 8:
                return render_template("forgot_password.html", error="Password must be at least 8 characters long.", success=None, email=email, account=account, reset_token=reset_token), 400
            if new_password != confirm_password:
                return render_template("forgot_password.html", error="Passwords do not match.", success=None, email=email, account=account, reset_token=reset_token), 400

            state.update_account_password(cursor, account, new_password)
            conn.commit()
            session.pop(RESET_SESSION_KEY, None)
            return render_template("login.html", error=None, email=email, success="Password updated. You can now sign in with your new password.")
        finally:
            cursor.close()
            conn.close()

    @app.get("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login_page"))

    @app.get("/admin/login")
    def admin_login():
        return redirect(url_for("login_page"))

    @app.post("/admin/login")
    def admin_login_submit():
        return login_submit()

    @app.get("/admin/logout")
    def admin_logout():
        return redirect(url_for("logout"))
