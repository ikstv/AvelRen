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
    # Public-source контракт v5 (доведений canary на проді). Версія — окреме
    # налаштування, щоб URL і заголовки лишалися в одному місці; fallback на v4
    # заборонений (validate_collector_settings пінить це на старті).
    echerha_api_version: int = 5
    echerha_client_version: str = "3.9.0"
    # Persistent installation-id гостьового клієнта. Оператор генерує UUIDv4
    # один раз і кладе в .env; код його не створює й не ротує (див. echerha.py).
    echerha_device_id: str = ""
    echerha_device_name: str = "AvelRen collector"
    echerha_vehicle_type: int = 1  # 1 — вантажівки, 2 — автобуси
    poll_interval_seconds: int = 60
    http_timeout_seconds: int = 15

    contact_email: str = ""
    log_level: str = "INFO"

    # --- Обмеження ресурсів public API (#16) ---
    # statement_timeout лише для пулу API-процесу (не глобальна політика сервера).
    api_statement_timeout_ms: int = 5000
    # Скільки ОДНОЧАСНИХ дорогих читань (history/forecast/quality) дозволяємо.
    # МУСИТЬ бути менше за db.POOL_MAX_SIZE, щоб лишити конекшени для дешевих
    # health/workload під навантаженням (інакше дорогі читання вичерпають пул).
    api_max_concurrent_expensive: int = 3
    # Максимальний розмір тіла запиту; усі наші тіла — малий JSON.
    api_max_body_bytes: int = 16 * 1024

    # Службовий ключ Firebase. Лежить на сервері повз git, права 600.
    fcm_credentials_path: str = ""

    # Сповіщення повторюється, доки користувач не натисне «ОК».
    alert_resend_seconds: int = 300
    # Перезарядка після підтвердження: черга має впасти нижче порога із запасом,
    # інакше коливання 49<->51 будили б щохвилини.
    rearm_factor: float = 0.9

    @property
    def workload_url(self) -> str:
        return (
            f"{self.echerha_base_url}/v{self.echerha_api_version}"
            f"/workload/{self.echerha_vehicle_type}"
        )

    @property
    def user_agent(self) -> str:
        """Чесно представляємось: держсервіс має бачити, хто до нього ходить."""
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
