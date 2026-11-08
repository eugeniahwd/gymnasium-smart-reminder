"""Verifikasi kondisi kode terhadap baseline serah-terima (Fase 3, termasuk perbaikan ketahanan koneksi).

Jalankan dari root repo:  python tools/verify_state.py
Status per file:
  OK      identik dengan baseline
  FORMAT  isi sama, hanya beda format (spasi di ujung baris, baris kosong akhir, BOM, CRLF) - aman
  BEDA    isi kode berbeda dari baseline
  HILANG  file baseline tidak ada
  BARU    file tidak ada di baseline
Hanya file .py di src/ dan tests/.
"""
import hashlib
import pathlib

EXPECTED = {  # path: (jumlah baris, sha256 ketat, sha256 longgar)
    "src/__init__.py": (0, "e3b0c44298", "e3b0c44298"),
    "src/api/__init__.py": (0, "e3b0c44298", "e3b0c44298"),
    "src/api/config.py": (36, "e772b7a66b", "b21945f83e"),
    "src/api/db/__init__.py": (0, "e3b0c44298", "e3b0c44298"),
    "src/api/db/models.py": (99, "855494c269", "2ede93a3dd"),
    "src/api/db/session.py": (31, "710e166f6a", "2c5279abae"),
    "src/api/deps.py": (25, "f0e2b42513", "8d5de35877"),
    "src/api/errors.py": (49, "b52189e946", "f660151622"),
    "src/api/main.py": (97, "550c304a49", "3f1db91c2d"),
    "src/api/routers/__init__.py": (0, "e3b0c44298", "e3b0c44298"),
    "src/api/routers/customers.py": (93, "4aedcd92c8", "3a7ae580a9"),
    "src/api/routers/drafts.py": (14, "b7dcbc74dc", "36c7b1e4d8"),
    "src/api/routers/health.py": (27, "5ace533edd", "e6c65a4429"),
    "src/api/routers/predict.py": (25, "6c204163f8", "00ec480be9"),
    "src/api/routers/reminders.py": (169, "c062202567", "6a576025f5"),
    "src/api/routers/schedules.py": (80, "e69e78d106", "d8587db864"),
    "src/api/schemas/__init__.py": (0, "e3b0c44298", "e3b0c44298"),
    "src/api/schemas/common.py": (25, "808eb6f776", "5f27fae8cc"),
    "src/api/schemas/customer.py": (69, "6f2c141b23", "bbdfd433ef"),
    "src/api/schemas/predict.py": (31, "db6b4a1a7c", "31a10ae9c8"),
    "src/api/schemas/reminder.py": (75, "e861862eac", "7c05264a06"),
    "src/api/schemas/schedule.py": (49, "cb78ca4121", "a5fb4a0238"),
    "src/api/services/__init__.py": (0, "e3b0c44298", "e3b0c44298"),
    "src/api/services/prediction_service.py": (57, "3d31914eb9", "865ba14fe0"),
    "src/api/services/status_flow.py": (46, "298541714f", "68ecc67921"),
    "src/api/timeutil.py": (34, "fb5db558a1", "e0234956ce"),
    "src/data_generation/__init__.py": (0, "e3b0c44298", "e3b0c44298"),
    "src/data_generation/check_db.py": (66, "38c5553a94", "500059e46e"),
    "src/data_generation/generate.py": (451, "5cfb6cea86", "8c11747594"),
    "src/data_generation/seed_db.py": (156, "09c9ef6d04", "a19b310ca0"),
    "src/data_generation/seed_demo.py": (366, "6517dffe9f", "d0015ad2d2"),
    "src/ml/__init__.py": (0, "e3b0c44298", "e3b0c44298"),
    "src/ml/baseline.py": (41, "2b01ee0c1c", "1b109f6f61"),
    "src/ml/eda.py": (90, "756595e5dd", "ec6651f0d6"),
    "src/ml/evaluate.py": (147, "ccbd6c25e5", "fa3f15cdf0"),
    "src/ml/feature_engineering.py": (231, "4caf88caa3", "d6a12d9772"),
    "src/ml/predict.py": (128, "c918324a89", "d7f3fd6e66"),
    "src/ml/train.py": (375, "89263404b7", "fd39d3bc84"),
    "tests/test_api.py": (423, "7dcc3f0b0e", "b906dd37e7"),
    "tests/test_data_generation.py": (134, "21e0c59092", "802263ba86"),
    "tests/test_ml.py": (124, "69ded9a06a", "7b7101daad"),
    "tests/test_seed_demo.py": (195, "8354340352", "97ffba2b59"),
}


def _norm(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def _lenient(data: bytes) -> bytes:
    lines = [ln.rstrip() for ln in _norm(data).decode("utf-8-sig").split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines).encode()


def _h(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:10]


def _why(data: bytes) -> str:
    text = data.decode("utf-8", errors="replace")
    notes = []
    if not data.endswith(b"\n"):
        notes.append("tidak diakhiri newline")
    if data.endswith(b"\n\n"):
        notes.append("ada baris kosong berlebih di akhir")
    if data.startswith(b"\xef\xbb\xbf"):
        notes.append("ada BOM")
    ws = sum(1 for ln in text.splitlines() if ln != ln.rstrip())
    if ws:
        notes.append(f"{ws} baris punya spasi di ujung")
    odd = sorted({c for c in text if ord(c) > 127})
    if odd:
        notes.append("karakter non-ASCII: " + "".join(odd))
    return "; ".join(notes) or "-"


def main() -> None:
    root = pathlib.Path(__file__).resolve().parents[1]
    found = {str(p.relative_to(root)).replace("\\", "/") for base in ("src", "tests")
             for p in (root / base).rglob("*.py") if "__pycache__" not in p.parts}
    counts = {"OK": 0, "FORMAT": 0, "BEDA": 0, "HILANG": 0, "BARU": 0}
    for f in sorted(set(EXPECTED) | found):
        if f not in EXPECTED:
            status, info = "BARU", f"{len((root / f).read_bytes().splitlines())} baris"
        elif f not in found:
            status, info = "HILANG", ""
        else:
            data = (root / f).read_bytes()
            lines, strict, loose = EXPECTED[f]
            if _h(_norm(data)) == strict:
                status, info = "OK", ""
            elif _h(_lenient(data)) == loose:
                status, info = "FORMAT", _why(data)
            else:
                status, info = "BEDA", f"baris {len(_norm(data).splitlines())} (baseline {lines}); {_why(data)}"
        counts[status] += 1
        if status != "OK":
            print(f"{status:<7}{f}  {info}")
    print("\nRINGKASAN:", counts, f"| total baseline: {len(EXPECTED)} file")


if __name__ == "__main__":
    main()
