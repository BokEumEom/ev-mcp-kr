"""Runtime configuration loaded from env vars or .env file."""

from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    service_key: SecretStr = Field(..., description="data.go.kr issued service key")
    vworld_key: SecretStr | None = Field(default=None, description="Optional VWorld geocoder key")

    # Default to loopback. Containers / Render set HOST=0.0.0.0 explicitly.
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"

    station_info_ttl: int = 86_400
    status_ttl: int = 60

    cors_origins: str = "https://claude.ai,https://claude.com,http://localhost:6274"

    # data.go.kr supports HTTPS — never default to http (serviceKey would be in
    # the cleartext query string).
    api_base_url: str = "https://apis.data.go.kr/B552584/EvCharger"
    # data.go.kr 의 getChargerInfo 가 numOfRows 와 무관하게 응답 자체가 느림 —
    # 측정 결과 urllib 20s, httpx 50~60s. 15s 는 모든 attempt 가 timeout 으로
    # 끝나는 원인. 90s 로 잡고 retry 3번이면 워밍 한 페이지가 최악 4~5분.
    request_timeout_s: float = 90.0
    max_retries: int = 3

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


def load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
