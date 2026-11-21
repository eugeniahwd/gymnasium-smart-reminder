"""CRUD jadwal kelas (grup dan private). Waktu dikirim ke API sebagai WIB tanpa zona."""
from __future__ import annotations

from datetime import time, timedelta

import streamlit as st

from components import call, flash, get_client, page_header
from helpers import CLASS_TYPE_LABEL, combine_wib, format_dt, parse_dt, today_wib

client = get_client()
TYPES = list(CLASS_TYPE_LABEL)


def schedule_form(key: str, current: dict | None = None) -> dict | None:
    """Form jadwal; mengembalikan payload saat disubmit."""
    start = parse_dt(current["waktu_mulai"]) if current else None
    with st.form(key, border=True):
        nama = st.text_input("Nama kelas", value=current["nama_kelas"] if current else "")
        tipe = st.selectbox("Tipe", TYPES, index=TYPES.index(current["tipe"]) if current else 0,
                            format_func=CLASS_TYPE_LABEL.get)
        col_d, col_t = st.columns(2)
        tanggal = col_d.date_input("Tanggal", value=start.date() if start else today_wib(), format="DD/MM/YYYY")
        jam = col_t.time_input("Jam mulai (WIB)", value=start.time() if start else time(9, 0), step=900)
        pelatih = st.text_input("Pelatih", value=current["pelatih"] if current else "")
        kapasitas = st.number_input("Kapasitas", min_value=1, max_value=500, step=1,
                                    value=int(current["kapasitas"]) if current else 15)
        submitted = st.form_submit_button("Simpan jadwal" if current else "Tambah jadwal", icon=":material/save:")
    if not submitted:
        return None
    return {"nama_kelas": nama.strip(), "tipe": tipe, "waktu_mulai": combine_wib(tanggal, jam.hour, jam.minute),
            "pelatih": pelatih.strip(), "kapasitas": int(kapasitas)}


page_header("Jadwal", "Jadwal kelas dikelola di aplikasi ini. Kelas grup berlangsung Senin-Sabtu.")
today = today_wib()
period = st.date_input("Rentang tanggal", value=(today, today + timedelta(days=6)), format="DD/MM/YYYY")
if len(period) < 2:
    st.info("Pilih tanggal akhir rentang.")
    st.stop()
date_from, date_to = period
ok, schedules = call("Memuat jadwal", client.list_schedules, date_from.isoformat(), date_to.isoformat())
schedules = sorted(schedules or [], key=lambda s: s["waktu_mulai"])
if ok:
    st.caption(f"{len(schedules)} jadwal")
    st.dataframe([{"ID": s["id"], "Kelas": s["nama_kelas"], "Tipe": CLASS_TYPE_LABEL.get(s["tipe"], s["tipe"]),
                   "Waktu (WIB)": format_dt(s["waktu_mulai"]), "Pelatih": s["pelatih"], "Kapasitas": s["kapasitas"]}
                  for s in schedules], hide_index=True)

tab_add, tab_edit = st.tabs(["Tambah jadwal", "Ubah / hapus jadwal"])

with tab_add:
    payload = schedule_form("add_schedule")
    if payload:
        ok_add, created = call("Menyimpan jadwal", client.create_schedule, payload)
        if ok_add:
            flash(f"Jadwal {created['nama_kelas']} (#{created['id']}) {format_dt(created['waktu_mulai'])} ditambahkan.")
            st.rerun()

with tab_edit:
    if not schedules:
        st.info("Tidak ada jadwal pada rentang ini.")
    else:
        by_id = {s["id"]: s for s in schedules}
        sid = st.selectbox("Pilih jadwal", list(by_id), index=None, key="edit_schedule_id",
                           format_func=lambda i: f"{by_id[i]['nama_kelas']} · {format_dt(by_id[i]['waktu_mulai'])} "
                                                 f"· {by_id[i]['pelatih']} (#{i})")
        if sid is not None:
            payload = schedule_form(f"edit_schedule_{sid}", by_id[sid])
            if payload:
                ok_upd, _ = call("Menyimpan perubahan", client.update_schedule, sid, payload)
                if ok_upd:
                    flash(f"Jadwal #{sid} diperbarui.")
                    st.rerun()
            with st.container(border=True):
                st.markdown("**Hapus jadwal**")
                sure = st.checkbox("Saya paham data kehadiran kelas ini ikut terhapus; reminder tetap ada tanpa "
                                   "jadwal.", key=f"confirm_delete_schedule_{sid}")
                if st.button("Hapus jadwal", key=f"delete_schedule_{sid}", disabled=not sure, type="primary",
                             icon=":material/delete:"):
                    ok_del, _ = call("Menghapus jadwal", client.delete_schedule, sid)
                    if ok_del:
                        st.session_state.pop("edit_schedule_id", None)
                        flash(f"Jadwal #{sid} dihapus.")
                        st.rerun()
