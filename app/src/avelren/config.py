from urllib.parse import quote

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    echerha_base_url: str = "https://back.echerha.gov.ua/api"
    echerha_vehicle_type: int = 1  # 1 — вантажівки, 2 — автобуси
    poll_interval_seconds: int = 60
    http_timeout_seconds: int = 15

    contact_email: str = ""
    log_level: str = "INFO"

    # Службовий ключ Firebase. Лежить на сервері повз git, права 600.
    fcm_credentials_path: str = ""

    # Сповіщення повторюється, доки користувач не натисне «ОК».
    alert_resend_seconds: int = 300
    # Перезарядка після підтвердження: черга має впасти нижче порога із запасом,
    # інакше коливання 49<->51 будили б щохвилини.
    rearm_factor: float = 0.9

    @property
    def workload_url(self) -> str:
        return f"{self.echerha_base_url}/v4/workload/{self.echerha_vehicle_type}"

    @property
    def user_agent(self) -> str:
        """Чесно представляємось: держсервіс має бачити, хто до нього ходить."""
        contact = f" (+{self.contact_email})" if self.contact_email else ""
        return f"AvelRen/0.1.0{contact}"


settings = Settings()
