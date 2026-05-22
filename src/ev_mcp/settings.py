"""Runtime configuration loaded from env vars or .env file."""

from __future__ import annotations

from pathlib import Path

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
    db_path: Path = Field(
        default=Path("data/chargers.db"),
        description="SQLite charger inventory store; populated by scripts/sync_chargers.py",
    )

    # Phase 10 — DuckDB 분석 사이드카 (ADR-001).
    # Stage 10.2 는 로컬 Parquet only. Stage 10.1 진입 시 R2 자격증명 4개 채우면
    # snapshot_source="r2" 로 전환.
    snapshot_path: Path = Field(
        default=Path("scratch/chargers_snapshot.parquet"),
        description="로컬 Parquet 스냅샷 경로 (snapshot_source='local' 일 때 사용)",
    )
    snapshot_dir: Path = Field(
        default=Path("data/snapshots"),
        description="날짜별 Parquet 스냅샷 디렉터리 (snapshot_source='local' 일 때 glob 대상)",
    )
    snapshot_source: str = Field(
        default="local",
        description="분석 데이터 소스: 'local' (snapshot_path) 또는 'r2' (Cloudflare R2)",
    )
    r2_account_id: SecretStr | None = Field(default=None, description="Cloudflare R2 account ID")
    r2_access_key_id: SecretStr | None = Field(default=None, description="R2 S3-compatible key ID")
    r2_secret_access_key: SecretStr | None = Field(default=None, description="R2 S3-compatible secret")
    r2_bucket: str | None = Field(default=None, description="R2 bucket name (예: ev-mcp-snapshots)")

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
