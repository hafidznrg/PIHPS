"""HTTP client untuk endpoint JSON internal PIHPS.

Endpoint ini dipakai oleh halaman Tabel Harga di bi.go.id/hargapangan (DevExtreme grid).
Lihat docs/api-notes.md untuk dokumentasi parameter dan bentuk respons.
"""

from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any

import httpx

from pihps.config import API_PREFIX, BASE_URL, USER_AGENT

log = logging.getLogger(__name__)


class PihpsError(RuntimeError):
    pass


class PihpsClient:
    def __init__(
        self,
        *,
        timeout: float = 60.0,
        min_interval: float = 1.0,
        max_retries: int = 4,
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
        )
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._last_call = 0.0

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> PihpsClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ core
    def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{API_PREFIX}/{endpoint}"
        params = {k: ("" if v is None else v) for k, v in (params or {}).items()}
        for attempt in range(1, self._max_retries + 1):
            wait = self._min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()
            try:
                resp = self._http.get(url, params=params)
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise PihpsError(f"HTTP {resp.status_code}")
                if resp.status_code != 200:
                    # 3xx biasanya redirect ke halaman error, jangan di-retry.
                    raise PihpsError(
                        f"HTTP {resp.status_code} untuk {endpoint} "
                        f"(location={resp.headers.get('location')})"
                    )
                payload = resp.json()
                if not isinstance(payload, dict) or "data" not in payload:
                    raise PihpsError(
                        f"Bentuk respons tak terduga dari {endpoint}: {str(payload)[:200]}"
                    )
                return payload
            except (httpx.TransportError, PihpsError, ValueError) as exc:
                retryable = (
                    isinstance(exc, httpx.TransportError)
                    or "HTTP 5" in str(exc)
                    or "429" in str(exc)
                )
                if not retryable or attempt == self._max_retries:
                    raise
                backoff = 2**attempt
                log.warning("%s gagal (%s), retry %d dalam %ds", endpoint, exc, attempt, backoff)
                time.sleep(backoff)
        raise AssertionError("unreachable")

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
            {
                "price_type_id": price_type_id,
                "comcat_id": comcat_id,
                "province_id": province_id,
                "regency_id": regency_id,
                "market_id": market_id,
                "tipe_laporan": tipe_laporan,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
        )
