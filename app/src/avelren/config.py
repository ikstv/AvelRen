from urllib.parse import quote

from pydantic_settings import BaseSettings, SettingsConfigDict

ECHERHA_COLLECTOR_BASE_URL = "https://back.echerha.gov.ua/api"


class CollectorConfigurationError(RuntimeError):
    pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str | None = None
    postgres_host: str = "db"
    postgres_port: int = 5432
    postgres_user: str = "avelren"
    postgres_password: str = ""
    postgres_db: str = "avelren"

    @property
    def database_dsn(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"postgresql://{quote(self.postgres_user, safe='')}:"
            f"{quote(self.postgres_password, safe='')}"
            f"@{self.postgres_host}:{self.postgres_port}/{quote(self.postgres_db, safe='')}"
        )

    echerha_base_url: str = ECHERHA_COLLECTOR_BASE_URL
    # Public-source contract v5 (proven by canary on prod). The version is a
    # separate setting so the URL and headers stay in one place; a fallback to
    # v4 is forbidden (validate_collector_settings pins this at startup).
    echerha_api_version: int = 5
    echerha_client_version: str = "3.9.0"
    # Persistent installation id of the guest client. The operator generates a
    # UUIDv4 once and puts it in .env; the code neither creates nor rotates it
    # (see echerha.py).
    echerha_device_id: str = ""
    echerha_device_name: str = "AvelRen collector"
    echerha_vehicle_type: int = 1  # 1 — trucks, 2 — buses
    poll_interval_seconds: int = 60
    http_timeout_seconds: int = 15

    contact_email: str = ""
    log_level: str = "INFO"

    # --- Public API resource limits (#16) ---
    # statement_timeout only for the API process pool (not a global server policy).
    api_statement_timeout_ms: int = 5000
    # How many CONCURRENT expensive reads (history/forecast/quality) we allow.
    # MUST be less than db.POOL_MAX_SIZE to leave connections for cheap
    # health/workload under load (otherwise expensive reads exhaust the pool).
    api_max_concurrent_expensive: int = 3
    # Maximum request body size; all our bodies are small JSON.
    api_max_body_bytes: int = 16 * 1024

    # Firebase service key. Kept on the server outside git, mode 600.
    fcm_credentials_path: str = ""

    # The notification repeats until the user taps "OK".
    alert_resend_seconds: int = 300
    # Re-arm after acknowledgement: the queue must fall below the threshold with
    # a margin, otherwise a 49<->51 flicker would wake the user every minute.
    rearm_factor: float = 0.9

    @property
    def workload_url(self) -> str:
        return (
            f"{self.echerha_base_url}/v{self.echerha_api_version}"
            f"/workload/{self.echerha_vehicle_type}"
        )

    @property
    def user_agent(self) -> str:
        """Introduce ourselves honestly: the government service should see who is calling it."""
        contact = f" (+{self.contact_email})" if self.contact_email else ""
        return f"AvelRen/0.1.0{contact}"


def validate_collector_settings(candidate: Settings) -> None:
    if candidate.echerha_base_url != ECHERHA_COLLECTOR_BASE_URL:
        raise CollectorConfigurationError("invalid collector setting: echerha_base_url")
    if candidate.echerha_api_version != 5:
        raise CollectorConfigurationError("invalid collector setting: echerha_api_version")
    if candidate.echerha_vehicle_type != 1:
        raise CollectorConfigurationError("invalid collector setting: echerha_vehicle_type")
    if candidate.poll_interval_seconds != 60:
        raise CollectorConfigurationError("invalid collector setting: poll_interval_seconds")
    if not 1 <= candidate.http_timeout_seconds <= 30:
        raise CollectorConfigurationError("invalid collector setting: http_timeout_seconds")


settings = Settings()
