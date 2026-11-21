"""Riwayat reminder per customer beserta riwayat perubahan statusnya (read-only)."""
from __future__ import annotations

import streamlit as st

from components import call, get_client, page_header, priority_badge, status_badge
from helpers import (DRAFT_SOURCE_LABEL, MESSAGE_TYPE_LABEL, PERSONA_LABEL, format_dt, priority_label,
                     reminder_option_label)

client = get_client()

page_header("Riwayat Reminder", "Semua reminder satu customer (terbaru dulu) dan riwayat perubahan statusnya.")
ok, customers = call("Memuat customer", client.list_customers)
if not ok:
    st.stop()
by_id = {c["id"]: c for c in customers}
cid = st.selectbox("Customer", list(by_id), index=None, placeholder="Ketik nama untuk mencari",
                   format_func=lambda i: f"{by_id[i]['nama']} · {PERSONA_LABEL.get(by_id[i]['persona'], '')} (#{i})")
if cid is None:
    st.info("Pilih customer untuk melihat riwayat reminder-nya.")
    st.stop()

ok, reminders = call("Memuat riwayat reminder", client.customer_reminders, cid)
if not ok:
    st.stop()
if not reminders:
    st.info("Customer ini belum punya reminder.")
    st.stop()

counts = {s: sum(r["status"] == s for r in reminders) for s in ("Scheduled", "Sent", "Responded", "No Response")}
st.caption(f"{len(reminders)} reminder · " + " · ".join(f"{s} {n}" for s, n in counts.items()))
st.dataframe([{
    "No": r["id"], "Dibuat": format_dt(r["created_at"], with_day=False),
    "Kelas": (r.get("schedule") or {}).get("nama_kelas", "-"),
    "Waktu kelas": format_dt((r.get("schedule") or {}).get("waktu_mulai"), with_day=False),
    "Jenis pesan": MESSAGE_TYPE_LABEL.get(r["message_type"], r["message_type"]),
    "Prioritas": priority_label(r.get("priority")), "Status": r["status"],
    "Dikirim": format_dt(r.get("sent_at"), with_day=False), "Dibalas": format_dt(r.get("responded_at"), with_day=False),
    "Sumber draft": DRAFT_SOURCE_LABEL.get(r.get("draft_source"), "-"),
} for r in reminders], hide_index=True)

labels = {r["id"]: reminder_option_label(r) for r in reminders}
rid = st.selectbox("Lihat detail reminder", list(labels), format_func=labels.get, key=f"history_reminder_{cid}")
rem = next(r for r in reminders if r["id"] == rid)
with st.container(border=True):
    priority_badge(rem.get("priority"))
    status_badge(rem["status"])
    text = rem.get("final_message") or rem.get("draft_message")
    label = "Pesan akhir" if rem.get("final_message") else "Draft (belum ada pesan akhir)"
    st.text_area(label, value=text or "(belum ada pesan)", disabled=True, height=150, key=f"history_msg_{rid}")
    ok, history = call("Memuat riwayat status", client.reminder_history, rid)
    if ok:
        st.markdown("**Riwayat status**")
        st.dataframe([{"Waktu": format_dt(h["changed_at"]), "Dari": h.get("from_status") or "-", "Ke": h["to_status"]}
                      for h in history], hide_index=True)
