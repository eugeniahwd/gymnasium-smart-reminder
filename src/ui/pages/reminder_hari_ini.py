"""Halaman inti: reminder untuk kelas pada satu tanggal -> draft -> edit -> kirim manual -> update status."""
from __future__ import annotations

import streamlit as st

from components import call, flash, get_client, page_header, priority_badge, status_badge
from helpers import (CLASS_TYPE_LABEL, DRAFT_SOURCE_LABEL, MESSAGE_TYPE_LABEL, PERSONA_LABEL, empty_day_message,
                     format_dt, format_probabilities, format_time, message_for_editor, priority_label,
                     reminder_option_label, reminder_rows, today_wib, wa_url)

client = get_client()


def _clear_editor_state(rid: int) -> None:
    for key in (f"msg_{rid}", f"warn_{rid}", f"confirm_{rid}", f"why_{rid}_result"):
        st.session_state.pop(key, None)


def render_reason(rid: int, customer_id: int, reminder_priority: str | None) -> None:
    if st.button("Lihat alasan prioritas", key=f"why_{rid}", icon=":material/insights:"):
        ok, pred = call("Menghitung alasan prioritas", client.predict, customer_id)
        if ok:
            st.session_state[f"why_{rid}_result"] = pred
    pred = st.session_state.get(f"why_{rid}_result")
    if not pred:
        return
    with st.container(border=True):
        st.caption("Hanya untuk admin. Jangan menyalin alasan ini ke pesan customer.")
        st.write(f"Prediksi terbaru: **{priority_label(pred['priority'])}** "
                 f"({format_probabilities(pred['probabilities'])}) · model `{pred['model_version']}`")
        if pred.get("top_factors"):
            st.markdown("\n".join(f"- {factor}" for factor in pred["top_factors"]))
        else:
            st.write(pred.get("note") or "Tidak ada faktor yang menonjol.")
        if pred["priority"] != reminder_priority:
            st.caption("Prioritas reminder dihitung saat reminder dibuat, jadi bisa berbeda dari prediksi terbaru.")


def render_editor(rem: dict) -> None:
    """Status Scheduled: generate draft, edit, simpan, buka WhatsApp, tandai terkirim."""
    rid, number = rem["id"], rem["customer"]["no_whatsapp"]
    msg_key = f"msg_{rid}"
    has_draft = bool(rem.get("draft_message"))
    label = "Generate ulang draft" if has_draft else "Generate Draft"
    if st.button(label, key=f"gen_{rid}", type="primary", icon=":material/auto_awesome:",
                 help="Generate ulang akan mengganti isi kotak pesan di bawah." if has_draft else None):
        ok, res = call("Membuat draft (Gemini)", client.generate_draft, rid, regenerate=has_draft)
        if ok:
            st.session_state[msg_key] = res["draft_message"]
            st.session_state[f"warn_{rid}"] = res.get("warning")
            flash(f"Draft dibuat dari {DRAFT_SOURCE_LABEL.get(res['draft_source'], res['draft_source'])}. "
                  "Periksa dan edit sebelum dikirim.")
            st.rerun()
    if rem.get("draft_source"):
        st.caption(f"Sumber draft tersimpan: {DRAFT_SOURCE_LABEL.get(rem['draft_source'], rem['draft_source'])}")
    if st.session_state.get(f"warn_{rid}"):
        st.warning(st.session_state[f"warn_{rid}"], icon=":material/warning:")

    if msg_key not in st.session_state:
        st.session_state[msg_key] = message_for_editor(rem)
    text = st.text_area("Pesan (boleh diedit sebelum dikirim)", key=msg_key, height=180,
                        placeholder="Klik Generate Draft atau tulis pesan sendiri.")

    col_save, col_wa = st.columns(2)
    if col_save.button("Simpan pesan", key=f"save_{rid}", icon=":material/save:", width="stretch"):
        if not text.strip():
            st.error("Pesan masih kosong.")
        else:
            ok, _ = call("Menyimpan pesan", client.update_message, rid, text.strip())
            if ok:
                flash("Pesan disimpan.")
                st.rerun()
    col_wa.link_button("Buka WhatsApp (teks terisi)", wa_url(number, text), icon=":material/chat:",
                       width="stretch")
    st.caption("WhatsApp terbuka dengan teks terisi; Anda tetap menekan kirim sendiri di WhatsApp.")

    confirmed = st.checkbox("Saya sudah mengirim pesan ini lewat WhatsApp", key=f"confirm_{rid}")
    if st.button("Tandai Terkirim", key=f"sent_{rid}", disabled=not confirmed, icon=":material/send:",
                 help="Pesan di kotak di atas disimpan sebagai pesan akhir lalu status menjadi Sent (terkunci)."):
        if not text.strip():
            st.error("Pesan masih kosong. Isi pesan yang Anda kirim sebelum menandai terkirim.")
        else:
            ok, _ = call("Menandai terkirim", client.mark_sent, rid, text.strip())
            if ok:
                _clear_editor_state(rid)
                flash("Status diubah menjadi Sent. Tandai Responded atau No Response setelah ada kabar.")
                st.rerun()


def render_locked(rem: dict) -> None:
    """Status Sent/Responded/No Response: pesan read-only, tombol status lanjutan bila Sent."""
    rid = rem["id"]
    st.text_area("Pesan yang dikirim (terkunci)", value=rem.get("final_message") or "", disabled=True,
                 key=f"locked_{rid}", height=160)
    st.caption(f"Dikirim: {format_dt(rem.get('sent_at'))} WIB"
               + (f" · Dibalas: {format_dt(rem['responded_at'])} WIB" if rem.get("responded_at") else ""))
    if rem["status"] != "Sent":
        st.caption("Status sudah final.")
        return
    col_yes, col_no = st.columns(2)
    for col, status, icon in ((col_yes, "Responded", ":material/mark_chat_read:"),
                              (col_no, "No Response", ":material/do_not_disturb_on:")):
        if col.button(status, key=f"{status}_{rid}", icon=icon, width="stretch"):
            ok, _ = call(f"Mengubah status ke {status}", client.update_status, rid, status)
            if ok:
                flash(f"Status diubah menjadi {status}.")
                st.rerun()


def render_detail(rid: int) -> None:
    ok, rem = call("Memuat detail reminder", client.get_reminder, rid)
    if not ok:
        return
    cust, sch = rem["customer"], rem.get("schedule")
    with st.container(border=True):
        left, right = st.columns([3, 2])
        with left:
            st.subheader(cust["nama"])
            st.caption(f"{PERSONA_LABEL.get(cust['persona'], cust['persona'])} · WhatsApp {cust['no_whatsapp']}")
            if sch:
                st.write(f"**{sch['nama_kelas']}** ({CLASS_TYPE_LABEL.get(sch['tipe'], sch['tipe'])}) · "
                         f"{format_dt(sch['waktu_mulai'])} WIB · {sch['pelatih']}")
            else:
                st.write("Tanpa jadwal kelas")
            st.write(f"Jenis pesan: {MESSAGE_TYPE_LABEL.get(rem['message_type'], rem['message_type'])}")
        with right:
            priority_badge(rem.get("priority"))
            status_badge(rem["status"])
            st.caption(f"Peluang: {format_probabilities(rem.get('priority_probabilities'))}")
        render_reason(rid, cust["id"], rem.get("priority"))
        st.divider()
        if rem["status"] == "Scheduled":
            render_editor(rem)
        else:
            render_locked(rem)
        with st.expander("Riwayat status"):
            ok, history = call("Memuat riwayat", client.reminder_history, rid)
            if ok:
                st.dataframe([{"Waktu": format_dt(h["changed_at"]), "Dari": h.get("from_status") or "-",
                               "Ke": h["to_status"]} for h in history], hide_index=True)


def render_create_form(class_date) -> None:
    if not st.toggle("Buat reminder baru", key="show_create"):
        return
    ok_c, customers = call("Memuat customer", client.list_customers)
    ok_s, schedules = call("Memuat jadwal", client.list_schedules, class_date.isoformat(), class_date.isoformat())
    if not (ok_c and ok_s):
        return
    cust_label = {c["id"]: f"{c['nama']} · {PERSONA_LABEL.get(c['persona'], c['persona'])} (#{c['id']})"
                  for c in customers}
    sch_label = {s["id"]: f"{s['nama_kelas']} {format_time(s['waktu_mulai'])} · {s['pelatih']} (#{s['id']})"
                 for s in schedules}
    with st.form("create_reminder", border=True):
        customer_id = st.selectbox("Customer", list(cust_label), format_func=cust_label.get, index=None,
                                   placeholder="Ketik nama untuk mencari")
        schedule_id = st.selectbox(f"Kelas pada {class_date:%d/%m/%Y}", [None, *sch_label],
                                   format_func=lambda s: "Tanpa jadwal" if s is None else sch_label[s])
        mtype = st.selectbox("Jenis pesan", list(MESSAGE_TYPE_LABEL), format_func=MESSAGE_TYPE_LABEL.get)
        submitted = st.form_submit_button("Buat reminder", icon=":material/add:")
    st.caption("Reminder tanpa jadwal tidak muncul di daftar per tanggal; lihat di halaman Riwayat Reminder.")
    if submitted:
        if customer_id is None:
            st.error("Pilih customer dulu.")
            return
        ok, rem = call("Membuat reminder", client.create_reminder, customer_id, schedule_id, mtype)
        if ok:
            flash(f"Reminder #{rem['id']} dibuat (status Scheduled, prioritas {rem.get('priority') or 'belum ada'}).")
            st.rerun()


# ------------------------------------------------------------------ halaman
page_header("Reminder Hari Ini", "Reminder untuk kelas pada tanggal yang dipilih. Prioritas tertinggi tampil "
                                 "lebih dulu, lalu kelas yang paling dekat waktunya.")
class_date = st.date_input("Tanggal kelas", value=today_wib(), format="DD/MM/YYYY", key="class_date")
ok, reminders = call("Memuat reminder", client.list_reminders, class_date.isoformat())
if ok and not reminders:
    st.info(empty_day_message(class_date), icon=":material/event_busy:")
elif ok:
    count = {p: sum(r.get("priority") == p for r in reminders) for p in ("High", "Medium", "Low")}
    pending = sum(r["status"] == "Scheduled" for r in reminders)
    st.caption(f"{len(reminders)} reminder · {priority_label('High')} {count['High']} · "
               f"{priority_label('Medium')} {count['Medium']} · {priority_label('Low')} {count['Low']} · "
               f"belum dikirim {pending}")
    st.dataframe(reminder_rows(reminders), hide_index=True)
    labels = {r["id"]: reminder_option_label(r) for r in reminders}
    selected = st.selectbox("Pilih reminder untuk diproses", list(labels), format_func=labels.get,
                            key=f"selected_{class_date.isoformat()}")
    if selected is not None:
        render_detail(selected)
st.divider()
render_create_form(class_date)
