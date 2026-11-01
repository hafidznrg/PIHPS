"""HTTP client untuk endpoint JSON internal PIHPS.

Endpoint ini dipakai oleh halaman Tabel Harga di bi.go.id/hargapangan (DevExtreme grid).
Lihat docs/api-notes.md untuk dokumentasi parameter dan bentuk respons.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import httpx

from pihps.config import API_PREFIX, BASE_URL, USER_AGENT

log = logging.getLogger(__name__)


class PihpsError(RuntimeError):
    def __init__(
        self, message: str, *, status_code: int | None = None, url: str | None = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.url = url


_RETRYABLE_STATUS = (429, 500, 502, 503, 504)


@dataclass(frozen=True)
class RawResponse:
    """Respons mentah apa adanya, plus metadata untuk manifest."""

    endpoint: str
    url: str  # URL lengkap termasuk query string
    params: dict[str, Any]
    status_code: int
    body: bytes  # byte respons persis seperti dari server
    payload: dict[str, Any]  # hasil json.loads(body), hanya untuk validasi/hitung
    fetched_at: datetime  # UTC, saat respons diterima
    elapsed_s: float


class PihpsClient:
    def __init__(
        self,
        *,
        timeout: float = 60.0,
        min_interval: float = 1.5,
        max_retries: int = 4,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._http = httpx.Client(
            timeout=timeout,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{BASE_URL}/TabelHarga/PasarTradisionalDaerah",
            },
            follow_redirects=False,
            transport=transport,
        )
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._last_call = 0.0
        self.n_requests = 0  # termasuk retry

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> PihpsClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ core
    def fetch(self, endpoint: str, params: dict[str, Any] | None = None) -> RawResponse:
        """GET dengan jeda minimum antar-request dan retry ber-backoff.

        Mengembalikan byte respons apa adanya. Melempar PihpsError (dengan status_code
        bila ada) kalau gagal setelah semua retry atau bentuk respons bukan {"data": ...}.
        """
        url = f"{API_PREFIX}/{endpoint}"
        params = {k: ("" if v is None else v) for k, v in (params or {}).items()}
        for attempt in range(1, self._max_retries + 1):
            wait = self._min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()
            self.n_requests += 1
            try:
                t0 = time.monotonic()
                resp = self._http.get(url, params=params)
                elapsed = time.monotonic() - t0
                full_url = str(resp.request.url)
                if resp.status_code in _RETRYABLE_STATUS:
                    raise PihpsError(
                        f"HTTP {resp.status_code}", status_code=resp.status_code, url=full_url
                    )
                if resp.status_code != 200:
                    # 3xx biasanya redirect ke halaman error, jangan di-retry.
                    raise PihpsError(
                        f"HTTP {resp.status_code} untuk {endpoint} "
                        f"(location={resp.headers.get('location')})",
                        status_code=resp.status_code,
                        url=full_url,
                    )
                body = resp.content
                try:
                    payload = json.loads(body)
                except ValueError as exc:
                    raise PihpsError(
                        f"Respons {endpoint} bukan JSON: {body[:200]!r}",
                        status_code=resp.status_code,
                        url=full_url,
                    ) from exc
                if not isinstance(payload, dict) or "data" not in payload:
                    raise PihpsError(
                        f"Bentuk respons tak terduga dari {endpoint}: {str(payload)[:200]}",
                        status_code=resp.status_code,
                        url=full_url,
                    )
                return RawResponse(
                    endpoint=endpoint,
                    url=full_url,
                    params=params,
                    status_code=resp.status_code,
                    body=body,
                    payload=payload,
                    fetched_at=datetime.now(UTC),
                    elapsed_s=round(elapsed, 3),
                )
            except (httpx.TransportError, PihpsError) as exc:
                retryable = isinstance(exc, httpx.TransportError) or (
                    isinstance(exc, PihpsError) and exc.status_code in _RETRYABLE_STATUS
                )
                if not retryable or attempt == self._max_retries:
                    if isinstance(exc, httpx.TransportError):
                        raise PihpsError(
                            f"{type(exc).__name__}: {exc}", url=str(exc.request.url)
                        ) from exc
                    raise
                backoff = 2**attempt
                log.warning("%s gagal (%s), retry %d dalam %ds", endpoint, exc, attempt, backoff)
                time.sleep(backoff)
        raise AssertionError("unreachable")

    def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.fetch(endpoint, params).payload

    # ------------------------------------------------------------- referensi
    def ref_price_types(self) -> dict[str, Any]:
        return self._get("GetRefPriceType")

    def ref_commodities(self) -> dict[str, Any]:
        return self._get("GetRefCommodityAndCategory")

    def ref_provinces(self) -> dict[str, Any]:
        return self._get("GetRefProvince")

    def ref_regencies(self, price_type_id: int, province_id: int | str) -> dict[str, Any]:
        return self._get(
            "GetRefRegency", {"price_type_id": price_type_id, "ref_prov_id": province_id}
        )

    def ref_markets(self, price_type_id: int, regency_id: int | str) -> dict[str, Any]:
        return self._get(
            "GetRefMarket", {"price_type_id": price_type_id, "ref_regency_id": regency_id}
        )

    # ------------------------------------------------------------------ harga
    def grid_daerah(
        self,
        *,
        price_type_id: int,
        start_date: date,
        end_date: date,
        province_id: int | str = "",
        regency_id: int | str = "",
        market_id: int | str = "",
        comcat_id: str = "",
        tipe_laporan: int = 1,
    ) -> dict[str, Any]:
        """Tabel harga berdasarkan daerah (format lebar: satu kolom per tanggal).

        province_id/regency_id/market_id kosong = agregat nasional.
        """
        return self._get(
            "GetGridDataDaerah",
            grid_daerah_params(
                price_type_id=price_type_id,
                start_date=start_date,
                end_date=end_date,
                province_id=province_id,
                regency_id=regency_id,
                market_id=market_id,
                comcat_id=comcat_id,
                tipe_laporan=tipe_laporan,
            ),
        )


def grid_daerah_params(
    *,
    price_type_id: int,
    start_date: date,
    end_date: date,
    province_id: int | str = "",
    regency_id: int | str = "",
    market_id: int | str = "",
    comcat_id: str = "",
    tipe_laporan: int = 1,
) -> dict[str, Any]:
    """Parameter query GetGridDataDaerah, urutan sama seperti yang dikirim browser."""
    return {
        "price_type_id": price_type_id,
        "comcat_id": comcat_id,
        "province_id": province_id,
        "regency_id": regency_id,
        "market_id": market_id,
        "tipe_laporan": tipe_laporan,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }
