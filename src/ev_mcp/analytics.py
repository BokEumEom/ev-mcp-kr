"""DuckDB 분석 사이드카 — Phase 10 (ADR-001), view layer Phase 11.

분석 MCP 툴이 사용하는 단일 입구. SQLite 영속 store (Phase 6) 와는 독립.
운영 lookup 워크로드는 영향 받지 않는다 — 이 모듈은 read-only sidepath.

소스 추상화
-----------
``Settings.snapshot_source`` 가 결정:

- ``"local"``  → ``Settings.snapshot_dir`` 내 glob 으로 Parquet 파일 탐색
- ``"r2"``     → ``s3://{r2_bucket}/chargers_*.parquet`` + httpfs 자격증명

Named views
-----------
연결 시점에 두 view 를 생성한다 (소스 경로/자격증명은 여기서만 참조):

- ``v_all``    — 전체 스냅샷 관측값 (모든 snapshot_date)
- ``v_latest`` — 가장 최신 snapshot_date 의 행만

호출부 SQL 은 ``FROM v_latest`` / ``FROM v_all`` 을 직접 쓴다.
``{source}`` 플레이스홀더 기반 방식은 Phase 11 에서 제거됨.

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
from .snapshot import SNAPSHOT_GLOB


class AnalyticsError(RuntimeError):
    """분석 사이드카 일반 에러. 자격증명 마스킹 후 raise."""


class AnalyticsClient:
    """DuckDB in-memory + Parquet source. lazy connection."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._conn: Any | None = None  # duckdb.DuckDBPyConnection — lazy import
        self._redaction_values: list[str] = self._collect_secrets()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _ensure_connected(self) -> Any:
        if self._conn is not None:
            return self._conn
        conn = duckdb.connect(":memory:")
        self._create_views(conn)
        self._conn = conn
        return conn

    def _create_views(self, conn: Any) -> None:
        """소스(local glob / R2 s3 glob)에 따라 v_all·v_latest view 생성.

        호출부 SQL 에 소스 문자열이 들어가지 않도록, read_parquet 호출은
        view 정의 단 한 곳에만 존재한다.
        """
        src = self._settings.snapshot_source.lower()
        if src == "local":
            snapshot_dir = self._settings.snapshot_dir
            files = (
                sorted(snapshot_dir.glob(SNAPSHOT_GLOB))
                if snapshot_dir.exists()
                else []
            )
            if not files:
                raise AnalyticsError(
                    f"스냅샷이 없습니다: {snapshot_dir}. "
                    "ev-mcp-sync 후 ev-mcp-snapshot 을 한 번 실행하세요."
                )
            glob_path = (snapshot_dir / SNAPSHOT_GLOB).resolve()
            source = f"read_parquet('{glob_path}')"
        elif src == "r2":
            bucket = self._settings.r2_bucket
            if not bucket:
                raise AnalyticsError(
                    "snapshot_source='r2' 인데 R2_BUCKET 이 설정되지 않았습니다. "
                    ".env 의 R2_* 필드를 채우거나 SNAPSHOT_SOURCE=local 로 두세요."
                )
            self._configure_r2(conn)
            source = f"read_parquet('s3://{bucket}/chargers_*.parquet')"
        else:
            raise AnalyticsError(
                f"알 수 없는 snapshot_source: '{src}'. 'local' 또는 'r2' 만 허용."
            )
        try:
            conn.execute(f"CREATE VIEW v_all AS SELECT * FROM {source}")
            conn.execute(
                "CREATE VIEW v_latest AS SELECT * FROM v_all "
                "WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM v_all)"
            )
        except AnalyticsError:
            raise
        except Exception as e:
            raise AnalyticsError(self._redact(f"view 생성 실패: {e}")) from None

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
        sql: str,
        params: list[Any] | None = None,
    ) -> list[tuple[Any, ...]]:
        """v_all / v_latest view 에 대한 SELECT 실행.

        호출부는 평범한 SQL 을 쓴다 — ``FROM v_latest`` (최신 스냅샷) 또는
        ``FROM v_all`` (전체 관측열). 소스 경로/자격증명은 view 정의에만 있다.
        """
        conn = self._ensure_connected()
        try:
            cursor = conn.execute(sql, params or [])
            return cast(list[tuple[Any, ...]], cursor.fetchall())
        except AnalyticsError:
            raise
        except Exception as e:
            raise AnalyticsError(
                self._redact(f"query failed: {type(e).__name__}: {e}")
            ) from None

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
