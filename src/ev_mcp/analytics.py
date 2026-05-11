"""DuckDB 분석 사이드카 — Phase 10 (ADR-001).

분석 MCP 툴이 사용하는 단일 입구. SQLite 영속 store (Phase 6) 와는 독립.
운영 lookup 워크로드는 영향 받지 않는다 — 이 모듈은 read-only sidepath.

소스 추상화
-----------
``Settings.snapshot_source`` 가 결정:

- ``"local"``  → ``Settings.snapshot_path`` 의 Parquet 파일 직접 read_parquet
- ``"r2"``     → ``s3://{r2_bucket}/chargers_*.parquet`` + httpfs 자격증명

ATTACH mode 는 의도적으로 쓰지 않는다 — PoC 에서 분석 워크로드 일관성 부족
확인 (ADR-001 Alt-3). 분석 쿼리는 Parquet 위에서만 돈다.

시크릿 위생
-----------
DuckDB 예외 메시지가 자격증명 또는 URL 을 포함할 수 있어 모든 에러를
``AnalyticsError`` 로 감싸고 ``_redact`` 통과시킨다.
"""

from __future__ import annotations

from typing import Any, cast

import duckdb

from .settings import Settings


class AnalyticsError(RuntimeError):
    """분석 사이드카 일반 에러. 자격증명 마스킹 후 raise."""


class AnalyticsClient:
    """DuckDB in-memory + Parquet source. lazy connection."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._conn: Any | None = None  # duckdb.DuckDBPyConnection — lazy import
        self._redaction_values: list[str] = self._collect_secrets()

    # ------------------------------------------------------------------
    # Source resolution
    # ------------------------------------------------------------------

    def _source_expr(self) -> str:
        """SQL fragment that points read_parquet at the right source.

        Returns a complete ``read_parquet('...')`` call ready to interpolate
        into a SELECT.
        """
        src = self._settings.snapshot_source.lower()
        if src == "local":
            path = self._settings.snapshot_path
            if not path.exists():
                raise AnalyticsError(
                    f"snapshot_path 가 존재하지 않습니다: {path}. "
                    "scratch/duckdb_poc.py 를 한 번 실행해 스냅샷을 만들거나 "
                    "snapshot_source 를 'r2' 로 전환하세요."
                )
            return f"read_parquet('{path.resolve()}')"

        if src == "r2":
            bucket = self._settings.r2_bucket
            if not bucket:
                raise AnalyticsError(
                    "snapshot_source='r2' 인데 R2_BUCKET 이 설정되지 않았습니다. "
                    ".env 의 R2_* 4개 필드를 채우거나 SNAPSHOT_SOURCE=local 로 두세요."
                )
            return f"read_parquet('s3://{bucket}/chargers_*.parquet')"

        raise AnalyticsError(
            f"알 수 없는 snapshot_source: '{src}'. 'local' 또는 'r2' 만 허용."
        )

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _ensure_connected(self) -> Any:
        if self._conn is not None:
            return self._conn
        conn = duckdb.connect(":memory:")
        if self._settings.snapshot_source.lower() == "r2":
            self._configure_r2(conn)
        self._conn = conn
        return conn

    def _configure_r2(self, conn: Any) -> None:
        """Install + load httpfs and set S3-compatible credentials for R2.

        Cloudflare R2 exposes an S3 API at https://{account}.r2.cloudflarestorage.com.
        DuckDB's httpfs uses ``s3_endpoint``/``s3_access_key_id``/``s3_secret_access_key``.
        """
        account = self._settings.r2_account_id
        access_id = self._settings.r2_access_key_id
        access_secret = self._settings.r2_secret_access_key
        if account is None or access_id is None or access_secret is None:
            raise AnalyticsError(
                "snapshot_source='r2' 인데 R2 자격증명이 비어있습니다 "
                "(R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY)."
            )

        endpoint = f"{account.get_secret_value()}.r2.cloudflarestorage.com"
        try:
            conn.execute("INSTALL httpfs")
            conn.execute("LOAD httpfs")
            conn.execute(f"SET s3_endpoint='{endpoint}'")
            conn.execute(f"SET s3_access_key_id='{access_id.get_secret_value()}'")
            conn.execute(f"SET s3_secret_access_key='{access_secret.get_secret_value()}'")
            conn.execute("SET s3_url_style='path'")  # R2 path-style 권장
            conn.execute("SET s3_region='auto'")
        except Exception as e:
            raise AnalyticsError(self._redact(f"R2 설정 실패: {e}")) from None

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def query(
        self,
        sql_template: str,
        params: list[Any] | None = None,
    ) -> list[tuple[Any, ...]]:
        """Run a SELECT against the current source.

        ``sql_template`` MUST contain the literal ``{source}`` placeholder where
        the FROM clause table reference goes. We render that to the correct
        ``read_parquet('...')`` call here — callers never construct the source
        string themselves (so credentials and paths can't leak into SQL via
        accidental f-string interpolation in the caller).
        """
        if "{source}" not in sql_template:
            raise AnalyticsError(
                "sql_template must contain '{source}' placeholder for the FROM clause"
            )
        # Resolve source FIRST so config errors (missing bucket, bad source name)
        # surface before we install httpfs / set S3 creds.
        source = self._source_expr()
        conn = self._ensure_connected()
        rendered = sql_template.replace("{source}", source)
        try:
            cursor = conn.execute(rendered, params or [])
            return cast(list[tuple[Any, ...]], cursor.fetchall())
        except AnalyticsError:
            raise
        except Exception as e:
            raise AnalyticsError(self._redact(f"query failed: {type(e).__name__}: {e}")) from None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        if self._conn is not None:
            with _suppress():
                self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Secret hygiene
    # ------------------------------------------------------------------

    def _collect_secrets(self) -> list[str]:
        """모든 시크릿의 raw 값을 모아 마스킹용 사전 구축. 길이 순 정렬."""
        values: set[str] = set()
        for sec in (
            self._settings.r2_account_id,
            self._settings.r2_access_key_id,
            self._settings.r2_secret_access_key,
        ):
            if sec is None:
                continue
            raw = sec.get_secret_value()
            if raw:
                values.add(raw)
        # 길이 긴 것부터 — 짧은 substring 이 먼저 매치되는 걸 막음
        return sorted(values, key=len, reverse=True)

    def _redact(self, text: str) -> str:
        for v in self._redaction_values:
            if v in text:
                text = text.replace(v, "***")
        return text


class _suppress:
    """contextlib.suppress without importing the module — tiny."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, *_: object) -> bool:
        return True


def build_analytics_client(settings: Settings) -> AnalyticsClient:
    """Factory — kept for symmetry with ``build_caches`` / ``open_store``."""
    return AnalyticsClient(settings)
