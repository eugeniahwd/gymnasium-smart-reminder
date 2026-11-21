"""Klien HTTP UI -> FastAPI. Satu-satunya jalur UI ke data (UI tidak mengakses DB atau Gemini langsung).

`session` bisa disuntik: di aplikasi memakai `requests.Session`, di tes memakai `fastapi.testclient.TestClient`
(antarmuka `request(method, url, params=, json=, timeout=)` yang sama), sehingga tes tidak memakai jaringan.
"""
from __future__ import annotations

from typing import Any

import requests

# (connect, read) dalam detik. Read panjang karena Render free tier bisa "tidur" dan butuh ~1 menit untuk bangun.
DEFAULT_TIMEOUT = (10, 90)
DRAFT_TIMEOUT = (10, 150)  # Gemini + retry + 1 regenerasi
PAGE_SIZE = 200  # batas maksimum `limit` di API
MAX_ROWS = 5000  # pengaman agar paginasi tidak berjalan tanpa akhir
COLD_START_HINT = "API sedang bangun, bisa memakan sekitar 1 menit."


class ApiError(Exception):
    """Error dari API (format {"detail","code"}) atau dari koneksi (status None)."""

    def __init__(self, status: int | None, code: str, detail: str):
        self.status, self.code, self.detail = status, code, detail
        super().__init__(f"{status} {code}: {detail}")


def error_message(err: ApiError) -> str:
    """Pesan untuk ditampilkan ke admin. Pesan backend (sudah berbahasa Indonesia) ditampilkan apa adanya."""
    if err.code == "timeout":
        return (f"API tidak merespons tepat waktu. {COLD_START_HINT} Jika baru pertama dibuka, tunggu sebentar lalu "
                "coba lagi.")
    if err.code == "connection":
        return f"Tidak dapat terhubung ke API ({err.detail}). Periksa API_BASE_URL atau apakah server API berjalan."
    return err.detail


class ApiClient:
    def __init__(self, base_url: str, session: Any = None, timeout: tuple[float, float] = DEFAULT_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = session if session is not None else requests.Session()
        if session is None:
            self._session.headers.update({"User-Agent": "GymnasiumAdminUI/1.0", "Accept": "application/json"})

    # ------------------------------------------------------------------ inti
    def request(self, method: str, path: str, *, params: dict | None = None, json: Any = None,
                timeout: tuple[float, float] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        params = {k: v for k, v in (params or {}).items() if v is not None}
        try:
            resp = self._session.request(method, url, params=params or None, json=json,
                                         timeout=timeout or self.timeout)
        except requests.exceptions.Timeout:
            raise ApiError(None, "timeout", f"Waktu tunggu habis saat menghubungi {self.base_url}") from None
        except requests.exceptions.RequestException:
            raise ApiError(None, "connection", self.base_url) from None
        if resp.status_code == 204:
            return None
        try:
            body = resp.json()
        except ValueError:
            body = None
        if resp.status_code >= 400:
            if isinstance(body, dict) and "detail" in body:
                detail = body["detail"] if isinstance(body["detail"], str) else str(body["detail"])
                raise ApiError(resp.status_code, str(body.get("code") or f"http_{resp.status_code}"), detail)
            raise ApiError(resp.status_code, f"http_{resp.status_code}",
                           f"Server API membalas HTTP {resp.status_code}. Coba lagi beberapa saat.")
        if body is None:
            raise ApiError(resp.status_code, "invalid_response", "Respons API bukan JSON yang valid.")
        return body

    def paginate(self, path: str, params: dict | None = None) -> list[dict]:
        """Ambil semua halaman dari endpoint berpaginasi ({items,total,limit,offset})."""
        items: list[dict] = []
        offset = 0
        while True:
            page = self.request("GET", path, params={**(params or {}), "limit": PAGE_SIZE, "offset": offset})
            items += page["items"]
            offset += len(page["items"])
            if not page["items"] or offset >= page["total"] or offset >= MAX_ROWS:
                return items

    # ------------------------------------------------------------------ sistem
    def health(self, timeout: tuple[float, float] | None = None) -> dict:
        return self.request("GET", "/health", timeout=timeout)

    # ------------------------------------------------------------------ customer
    def list_customers(self) -> list[dict]:
        return self.paginate("/customers")

    def create_customer(self, data: dict) -> dict:
        return self.request("POST", "/customers", json=data)

    def update_customer(self, customer_id: int, data: dict) -> dict:
        return self.request("PATCH", f"/customers/{customer_id}", json=data)

    def delete_customer(self, customer_id: int) -> None:
        self.request("DELETE", f"/customers/{customer_id}")

    def customer_reminders(self, customer_id: int) -> list[dict]:
        return self.paginate(f"/customers/{customer_id}/reminders")

    # ------------------------------------------------------------------ jadwal
    def list_schedules(self, date_from: str | None = None, date_to: str | None = None) -> list[dict]:
        return self.paginate("/schedules", {"date_from": date_from, "date_to": date_to})

    def create_schedule(self, data: dict) -> dict:
        return self.request("POST", "/schedules", json=data)

    def update_schedule(self, schedule_id: int, data: dict) -> dict:
        return self.request("PATCH", f"/schedules/{schedule_id}", json=data)

    def delete_schedule(self, schedule_id: int) -> None:
        self.request("DELETE", f"/schedules/{schedule_id}")

    # ------------------------------------------------------------------ reminder
    def list_reminders(self, class_date: str) -> list[dict]:
        """Semua reminder untuk TANGGAL KELAS (urutan dari API: High dulu, lalu kelas terdekat)."""
        return self.paginate("/reminders", {"date": class_date})

    def get_reminder(self, reminder_id: int) -> dict:
        return self.request("GET", f"/reminders/{reminder_id}")

    def reminder_history(self, reminder_id: int) -> list[dict]:
        return self.request("GET", f"/reminders/{reminder_id}/history")

    def create_reminder(self, customer_id: int, schedule_id: int | None, message_type: str) -> dict:
        return self.request("POST", "/reminders", json={"customer_id": customer_id, "schedule_id": schedule_id,
                                                        "message_type": message_type})

    def update_message(self, reminder_id: int, final_message: str) -> dict:
        return self.request("PATCH", f"/reminders/{reminder_id}/message", json={"final_message": final_message})

    def update_status(self, reminder_id: int, status: str) -> dict:
        return self.request("PATCH", f"/reminders/{reminder_id}/status", json={"status": status})

    def mark_sent(self, reminder_id: int, final_message: str) -> dict:
        """Simpan pesan yang benar-benar dikirim admin, lalu ubah status ke Sent."""
        self.update_message(reminder_id, final_message)
        return self.update_status(reminder_id, "Sent")

    # ------------------------------------------------------------------ AI
    def predict(self, customer_id: int) -> dict:
        return self.request("POST", "/predict", json={"customer_id": customer_id})

    def generate_draft(self, reminder_id: int, regenerate: bool = False) -> dict:
        return self.request("POST", "/generate-draft", json={"reminder_id": reminder_id, "regenerate": regenerate},
                            timeout=DRAFT_TIMEOUT)
