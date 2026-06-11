from pathlib import Path

from pydantic_settings import BaseSettings

APP_DIR = Path(__file__).parent.resolve()


class Settings(BaseSettings):
    app_name: str = "Braze Codes"
    database_url: str = "sqlite:///./barcoding.db"
    host: str = "127.0.0.1"
    port: int = 8000
    allowed_browse_roots: list[str] = []
    default_module_size_mm: float = 0.50
    default_quiet_zone_mm: float = 6.5
    default_dpi: int = 600
    overflow_threshold: int = 6
    # Hard ceiling for detected doc size — docs above this abort detection
    # (likely two recipients merged). Must not exceed the 9-sheet barcode field.
    max_sheets_per_doc: int = 9
    # Clear-zone inspection of pages before stamping: "off", "warn", or "abort"
    clear_zone_mode: str = "warn"
    # Watched intake directories (per-template input_dir auto-processing)
    watch_enabled: bool = True
    watch_poll_seconds: float = 5.0
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    uploads_dir: str = str(APP_DIR / "static" / "uploads")

    model_config = {"env_prefix": "BARCODE_"}


settings = Settings()
