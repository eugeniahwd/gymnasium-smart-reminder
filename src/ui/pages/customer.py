"""CRUD customer (tabel + form). Validasi nomor WhatsApp dilakukan di backend."""
from __future__ import annotations

import streamlit as st

from components import call, flash, get_client, page_header
from helpers import PERSONA_LABEL, format_dt

client = get_client()
PERSONAS = list(PERSONA_LABEL)
NAME_HELP = ("Tulis gelar di depan nama, misalnya 'Bapak Bambang Hartono' atau 'Ibu Sari Wijaya', agar sapaan di "
             "draft pesan tepat. Tanpa gelar, persona selain ibu-ibu disapa 'Bapak/Ibu'.")


def _clean(text: str | None) -> str | None:
    text = (text or "").strip()
    return text or None


page_header("Customer", "Data member Gymnasium. Customer tidak login; hanya admin yang mengelola data ini.")
ok, customers = call("Memuat customer", client.list_customers)
if ok:
    st.caption(f"{len(customers)} customer")
    st.dataframe([{"ID": c["id"], "Nama": c["nama"], "Persona": PERSONA_LABEL.get(c["persona"], c["persona"]),
                   "WhatsApp": c["no_whatsapp"], "Catatan": c.get("catatan") or "", "Bergabung": c["join_date"]}
                  for c in customers], hide_index=True)

tab_add, tab_edit = st.tabs(["Tambah customer", "Ubah / hapus customer"])

with tab_add:
    with st.form("add_customer", border=True):
        nama = st.text_input("Nama", help=NAME_HELP)
        wa = st.text_input("Nomor WhatsApp", placeholder="081234567890 atau 6281234567890")
        persona = st.selectbox("Persona", PERSONAS, format_func=PERSONA_LABEL.get)
        catatan = st.text_area("Catatan (opsional)", max_chars=500)
        join_date = st.date_input("Tanggal bergabung (kosong = hari ini)", value=None, format="DD/MM/YYYY")
        submitted = st.form_submit_button("Tambah customer", icon=":material/person_add:")
    if submitted:
        payload = {"nama": nama, "no_whatsapp": wa, "persona": persona, "catatan": _clean(catatan),
                   "join_date": join_date.isoformat() if join_date else None}
        ok_add, created = call("Menyimpan customer", client.create_customer, payload)
        if ok_add:
            flash(f"Customer {created['nama']} (#{created['id']}) ditambahkan.")
            st.rerun()

with tab_edit:
    if not ok or not customers:
        st.info("Belum ada customer.")
    else:
        by_id = {c["id"]: c for c in customers}
        cid = st.selectbox("Pilih customer", list(by_id), index=None, placeholder="Ketik nama untuk mencari",
                           format_func=lambda i: f"{by_id[i]['nama']} (#{i})", key="edit_customer_id")
        if cid is not None:
            cust = by_id[cid]
            with st.form(f"edit_customer_{cid}", border=True):
                nama = st.text_input("Nama", value=cust["nama"], help=NAME_HELP)
                wa = st.text_input("Nomor WhatsApp", value=cust["no_whatsapp"])
                persona = st.selectbox("Persona", PERSONAS, index=PERSONAS.index(cust["persona"]),
                                       format_func=PERSONA_LABEL.get)
                catatan = st.text_area("Catatan", value=cust.get("catatan") or "", max_chars=500)
                saved = st.form_submit_button("Simpan perubahan", icon=":material/save:")
            st.caption(f"Bergabung {cust['join_date']} · dibuat {format_dt(cust['created_at'])}")
            if saved:
                payload = {"nama": nama, "no_whatsapp": wa, "persona": persona, "catatan": _clean(catatan)}
                ok_upd, _ = call("Menyimpan perubahan", client.update_customer, cid, payload)
                if ok_upd:
                    flash(f"Data customer #{cid} diperbarui.")
                    st.rerun()

            with st.container(border=True):
                st.markdown("**Hapus customer**")
                sure = st.checkbox("Saya paham semua reminder, riwayat status, prediksi, dan kehadiran customer ini "
                                   "ikut terhapus permanen.", key=f"confirm_delete_customer_{cid}")
                if st.button("Hapus customer", key=f"delete_customer_{cid}", disabled=not sure, type="primary",
                             icon=":material/delete:"):
                    ok_del, _ = call("Menghapus customer", client.delete_customer, cid)
                    if ok_del:
                        st.session_state.pop("edit_customer_id", None)
                        flash(f"Customer #{cid} dihapus.")
                        st.rerun()
