import mysql.connector
from config import AppConfig

def get_db_connection():
    config = AppConfig.from_env()
    return mysql.connector.connect(
        host=config.db_host,
        port=config.db_port,
        user=config.db_user,
        password=config.db_password,
        database=config.db_name,
    )
