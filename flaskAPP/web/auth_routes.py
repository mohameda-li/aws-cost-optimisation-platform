from flask import redirect, render_template, request, session, url_for


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
        return render_template("forgot_password.html", error=None, success=None, email="", account=None)

    @app.post("/forgot-password")
    def forgot_password_submit():
        email = (request.form.get("email") or "").strip().lower()
        form_step = (request.form.get("step") or "lookup").strip().lower()

        if not email:
            return render_template("forgot_password.html", error="Email is required.", success=None, email="", account=None), 400

        conn = state.get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            account = state.find_account_by_email(cursor, email)
            if not account:
                return render_template("forgot_password.html", error="No account was found for that email address.", success=None, email=email, account=None), 404

            if form_step != "reset":
                return render_template("forgot_password.html", error=None, success=None, email=email, account=account)

            new_password = request.form.get("password") or ""
            confirm_password = request.form.get("confirm_password") or ""
            if len(new_password) < 8:
                return render_template("forgot_password.html", error="Password must be at least 8 characters long.", success=None, email=email, account=account), 400
            if new_password != confirm_password:
                return render_template("forgot_password.html", error="Passwords do not match.", success=None, email=email, account=account), 400

            state.update_account_password(cursor, account, new_password)
            conn.commit()
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
