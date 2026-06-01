from pathlib import Path

from pydantic_settings import BaseSettings

APP_DIR = Path(__file__).parent.resolve()


class Settings(BaseSettings):
    app_name: str = "BrazeBars"
    database_url: str = "sqlite:///./barcoding.db"
    host: str = "127.0.0.1"
    port: int = 8000
    allowed_browse_roots: list[str] = []
    default_module_size_mm: float = 0.50
    default_quiet_zone_mm: float = 6.5
    default_dpi: int = 600
    overflow_threshold: int = 6
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    uploads_dir: str = str(APP_DIR / "static" / "uploads")

    model_config = {"env_prefix": "BARCODE_"}


settings = Settings()
