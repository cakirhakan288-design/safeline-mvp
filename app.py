import sqlite3
from datetime import datetime
import streamlit as st

DB_PATH = "safeline.db"

CATEGORIES = ["Dolandırıcılık", "Bahis", "Şüpheli", "Güvenli", "Bilinmiyor"]
CHANNELS = ["Arama", "SMS", "WhatsApp", "Diğer"]

def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS numbers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone_number TEXT UNIQUE NOT NULL,
        category TEXT NOT NULL DEFAULT 'Bilinmiyor',
        last_reported_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        number_id INTEGER NOT NULL,
        report_type TEXT NOT NULL,
        channel TEXT NOT NULL,
        message_excerpt TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(number_id) REFERENCES numbers(id)
    )
    """)

    conn.commit()
    conn.close()

def normalize_phone(p: str) -> str:
    # MVP normalize: trim spaces. (İstersen daha sonra +90/0 düzenleyebiliriz)
    return (p or "").strip()

def upsert_number(phone_number: str):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id, phone_number, category, last_reported_at FROM numbers WHERE phone_number = ?", (phone_number,))
    row = cur.fetchone()
    if row:
        conn.close()
        return row  # (id, phone_number, category, last_reported_at)

    cur.execute(
        "INSERT INTO numbers (phone_number, category, last_reported_at) VALUES (?, ?, ?)",
        (phone_number, "Bilinmiyor", None)
    )
    conn.commit()
    cur.execute("SELECT id, phone_number, category, last_reported_at FROM numbers WHERE phone_number = ?", (phone_number,))
    row = cur.fetchone()
    conn.close()
    return row

def add_report(number_id: int, report_type: str, channel: str, message_excerpt: str | None):
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    cur.execute(
        "INSERT INTO reports (number_id, report_type, channel, message_excerpt, created_at) VALUES (?, ?, ?, ?, ?)",
        (number_id, report_type, channel, message_excerpt or None, now)
    )
    # last_reported_at güncelle
    cur.execute("UPDATE numbers SET last_reported_at = ? WHERE id = ?", (now, number_id))
    conn.commit()
    conn.close()

def get_stats(number_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM reports WHERE number_id = ?", (number_id,))
    reports_count = cur.fetchone()[0]
    score = min(100, reports_count * 15)
    conn.close()
    return reports_count, score

def set_category(number_id: int, category: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE numbers SET category = ? WHERE id = ?", (category, number_id))
    conn.commit()
    conn.close()

def get_reports(number_id: int, limit: int = 50):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT report_type, channel, message_excerpt, created_at
        FROM reports
        WHERE number_id = ?
        ORDER BY created_at DESC
        LIMIT ?
    """, (number_id, limit))
    rows = cur.fetchall()
    conn.close()
    return rows

def list_numbers(limit: int = 50):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT n.id, n.phone_number, n.category, n.last_reported_at,
               (SELECT COUNT(*) FROM reports r WHERE r.number_id = n.id) AS reports_count
        FROM numbers n
        ORDER BY reports_count DESC, n.last_reported_at DESC
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    conn.close()
    return rows

def risk_badge(score: int) -> str:
    if score >= 61:
        return "🔴 Yüksek Risk"
    if score >= 31:
        return "🟡 Şüpheli"
    return "🟢 Düşük Risk"

# ---------- UI ----------
st.set_page_config(page_title="SafeLine AI MVP", page_icon="🛡️", layout="centered")
init_db()

st.title("🛡️ SafeLine AI — MVP (Python)")
st.caption("Numara sorgula → risk gör → şikayet ekle. (Veriler SQLite’da yerel saklanır)")

tab1, tab2 = st.tabs(["🔎 Sorgula", "📊 Admin / Liste"])

with tab1:
    phone_input = st.text_input("Telefon numarası", placeholder="0532... veya +90...")
    colA, colB = st.columns([1, 1])
    with colA:
        do_lookup = st.button("Sorgula", use_container_width=True)
    with colB:
        st.write("")  # spacer

    if do_lookup:
        phone = normalize_phone(phone_input)
        if not phone:
            st.error("Lütfen bir numara gir.")
        else:
            num_row = upsert_number(phone)
            st.session_state["current_number_id"] = num_row[0]

    number_id = st.session_state.get("current_number_id")

    if number_id:
        # Fetch number row
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT id, phone_number, category, last_reported_at FROM numbers WHERE id = ?", (number_id,))
        row = cur.fetchone()
        conn.close()

        if not row:
            st.warning("Kayıt bulunamadı. Tekrar sorgula.")
        else:
            _id, phone_number, category, last_reported_at = row
            reports_count, score = get_stats(_id)

            st.subheader(f"📞 {phone_number}")
            st.markdown(f"**Risk Skoru:** `{score}` — {risk_badge(score)}")
            st.markdown(f"**Kategori:** `{category}`")
            st.markdown(f"**Şikayet Sayısı:** `{reports_count}`")
            st.markdown(f"**Son Şikayet:** `{last_reported_at or '-'}`")

            st.divider()

            # Category update
            st.write("### Kategori güncelle")
            new_cat = st.selectbox("Kategori seç", CATEGORIES, index=CATEGORIES.index(category) if category in CATEGORIES else 4)
            if st.button("Kategoriyi Kaydet"):
                set_category(_id, new_cat)
                st.success("Kategori güncellendi.")

            st.divider()

            # Add report
            st.write("### Şikayet ekle")
            rcol1, rcol2 = st.columns(2)
            with rcol1:
                report_type = st.selectbox("Şikayet türü", CATEGORIES[:-1], index=0)  # Bilinmiyor hariç
            with rcol2:
                channel = st.selectbox("Kanal", CHANNELS, index=0)

            message_excerpt = st.text_area("Mesajdan kısa parça (opsiyonel)", placeholder="Örn: 'Bonus için şu linke tıkla...'")
            if st.button("Şikayeti Kaydet", type="primary"):
                add_report(_id, report_type, channel, message_excerpt)
                st.success("Şikayet kaydedildi. Skor otomatik güncellendi.")

            st.divider()

            # Show reports
            st.write("### Son şikayetler")
            reps = get_reports(_id, limit=20)
            if not reps:
                st.info("Henüz şikayet yok.")
            else:
                for rt, ch, msg, ts in reps:
                    st.markdown(f"- **{rt}** / {ch} — {ts}")
                    if msg:
                        st.caption(msg)

with tab2:
    st.write("### En çok şikayet alan numaralar")
    rows = list_numbers(limit=100)
    if not rows:
        st.info("Henüz kayıt yok.")
    else:
        for _id, phone, cat, last_ts, cnt in rows:
            score = min(100, cnt * 15)
            st.markdown(f"**{phone}** — `{cat}` — Şikayet: `{cnt}` — Skor: `{score}` {risk_badge(score)}")
            st.caption(f"Son: {last_ts or '-'}")
            if st.button(f"Bu numarayı aç → {phone}", key=f"open_{_id}"):
                st.session_state["current_number_id"] = _id
                st.rerun()
