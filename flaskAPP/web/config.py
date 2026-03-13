import logging
import os
from dataclasses import dataclass


DEFAULT_SECRET_KEY = "dev-secret-change-later"


@dataclass(frozen=True)
class AppConfig:
    secret_key: str
    db_host: str
    db_port: int
    db_user: str
    db_password: str
    db_name: str

    @classmethod
    def from_env(cls) -> "AppConfig":
        return cls(
            secret_key=os.getenv("FLASK_SECRET_KEY", DEFAULT_SECRET_KEY),
            db_host=os.getenv("DB_HOST", "127.0.0.1"),
            db_port=int(os.getenv("DB_PORT", "3306")),
            db_user=os.getenv("DB_USER", "finops_app"),
            db_password=os.getenv("DB_PASSWORD", ""),
            db_name=os.getenv("DB_NAME", "finops"),
        )


def configure_logging(app):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app.logger.setLevel(logging.INFO)
    if app.secret_key == DEFAULT_SECRET_KEY:
        app.logger.warning("Using default Flask secret key. Set FLASK_SECRET_KEY for non-local environments.")
