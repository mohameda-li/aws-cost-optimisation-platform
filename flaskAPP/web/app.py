import sys

from flask import Flask

from auth_routes import register_auth_routes
from admin_routes import register_admin_routes
from bundle_builder import create_customer_bundle as _create_customer_bundle
from bundle_builder import generate_customer_config, generate_terraform_tfvars
from config import AppConfig, configure_logging
from customer_routes import register_customer_routes
from db import get_db_connection
from public_routes import register_public_routes
from web_common import (
    admin_login_required,
    build_customer_bundle_data,
    customer_login_required,
    ensure_admin_superuser_support,
    ensure_application_messages_table,
    find_account_by_email,
    generate_verification_code,
    get_enabled_service_codes,
    hash_password,
    send_verification_code,
    slugify,
    update_account_password,
    utc_now,
    verify_password,
)


app = Flask(__name__)
app_config = AppConfig.from_env()
app.secret_key = app_config.secret_key
configure_logging(app, app_config)
create_customer_bundle = lambda customer_data: _create_customer_bundle(app.root_path, customer_data)

register_public_routes(app, sys.modules[__name__])
register_auth_routes(app, sys.modules[__name__])
register_customer_routes(app, sys.modules[__name__])
register_admin_routes(app, sys.modules[__name__])


# ---------------------------
# Entry
# ---------------------------

if __name__ == "__main__":
    app.run(debug=True)
