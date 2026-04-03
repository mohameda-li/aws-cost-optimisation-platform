import logging
import os
from dataclasses import dataclass


DEFAULT_SECRET_KEY = "dev-secret-change-later"


@dataclass(frozen=True)
class AppConfig:
    app_env: str
    secret_key: str
    app_base_url: str
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_sender: str
    smtp_use_tls: bool
    db_host: str
    db_port: int
    db_user: str
    db_password: str
    db_name: str

    @classmethod
    def from_env(cls) -> "AppConfig":
        return cls(
            app_env=(os.getenv("APP_ENV") or os.getenv("FLASK_ENV") or "development").strip().lower(),
            secret_key=os.getenv("FLASK_SECRET_KEY", DEFAULT_SECRET_KEY),
            app_base_url=(os.getenv("APP_BASE_URL") or "http://127.0.0.1:5050").rstrip("/"),
            smtp_host=os.getenv("SMTP_HOST", "").strip(),
            smtp_port=int(os.getenv("SMTP_PORT", "587")),
            smtp_username=os.getenv("SMTP_USERNAME", "").strip(),
            smtp_password=os.getenv("SMTP_PASSWORD", ""),
            smtp_sender=(os.getenv("SMTP_SENDER") or os.getenv("SMTP_USERNAME") or "").strip(),
            smtp_use_tls=(os.getenv("SMTP_USE_TLS", "true").strip().lower() not in {"0", "false", "no"}),
            db_host=os.getenv("DB_HOST", "127.0.0.1"),
            db_port=int(os.getenv("DB_PORT", "3306")),
            db_user=os.getenv("DB_USER", "finops_app"),
            db_password=os.getenv("DB_PASSWORD", ""),
            db_name=os.getenv("DB_NAME", "finops"),
        )

    @property
    def is_production(self) -> bool:
        return self.app_env in {"prod", "production"}


def configure_logging(app, config: AppConfig):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app.logger.setLevel(logging.INFO)
    if config.is_production and app.secret_key == DEFAULT_SECRET_KEY:
        raise RuntimeError("FLASK_SECRET_KEY must be set for production deployments.")
    if app.secret_key == DEFAULT_SECRET_KEY:
        app.logger.warning("Using default Flask secret key. Set FLASK_SECRET_KEY for non-local environments.")
