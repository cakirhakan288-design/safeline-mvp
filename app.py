import sqlite3
from datetime import datetime
import streamlit as st

# ================= CONFIG =================
DB_PATH = "safeline.db"
ADMIN_PIN = "2468"

CATEGORIES = ["Dolandırıcılık", "Bahis", "Şüpheli", "Güvenli", "Bilinmiyor"]
REPORT_TYPES = ["Dolandırıcılık", "Bahis", "Şüpheli", "Güvenli"]
CHANNELS = ["Arama", "SMS", "WhatsApp", "Diğer"]

# ================= DB =================
def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS numbers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT UNIQUE,
            category TEXT DEFAULT 'Bilinmiyor',
            last_reported_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            number_id INTEGER,
            report_type TEXT,
            channel TEXT,
            message_excerpt TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

# ================= HELPERS =================
def normalize_phone(p):
    if not p:
        return ""
    d = "".join(c for c in p if c.isdigit())
    if d.startswith("0"):
        d = d[1:]
    if len(d) == 10:
        return "+90" + d
    if d.startswith("90"):
        return "+" + d
    return "+" + d

def upsert_number(phone):
    phone = normalize_phone(phone)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM numbers WHERE phone_number=?", (phone,))
    row = cur.fetchone()
    if row:
        conn.close()
        return row
    cur.execute(
        "INSERT INTO numbers (phone_number, category) VALUES (?,?)",
        (phone, "Bilinmiyor")
    )
    conn.commit()
    cur.execute("SELECT * FROM numbers WHERE phone_number=?", (phone,))
    row = cur.fetchone()
    conn.close()
    return row

def has_recent_report(number_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM reports
        WHERE number_id=?
        AND datetime(created_at) >= datetime('now','-24 hours')
    """, (number_id,))
    r = cur.fetchone()[0]
    conn.close()
    return r > 0

def add_report(number_id, report_type, channel, msg):
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO reports (number_id, report_type, channel, message_excerpt, created_at)
        VALUES (?,?,?,?,?)
    """, (number_id, report_type, channel, msg, now))
    cur.execute("UPDATE numbers SET last_reported_at=? WHERE id=?", (now, number_id))
    conn.commit()
    conn.close()

def get_stats(number_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM reports WHERE number_id=?", (number_id,))
    cnt = cur.fetchone()[0]
    conn.close()
    return cnt, min(100, cnt * 15)

def get_reports(number_id, limit=15):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT report_type, channel, message_excerpt, created_at
        FROM reports
        WHERE number_id=?
        ORDER BY created_at DESC
        LIMIT ?
    """, (number_id, limit))
    rows = cur.fetchall()
    conn.close()
    return rows

def set_category(number_id, category):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE numbers SET category=? WHERE id=?", (category, number_id))
    conn.commit()
    conn.close()

# ================= ADMIN =================
def list_numbers():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT n.id, n.phone_number, n.category,
        (SELECT COUNT(*) FROM reports r WHERE r.number_id=n.id) cnt
        FROM numbers n
        ORDER BY cnt DESC
    """)
    rows = cur.fetchall()
    conn.close()
    return rows

def get_total_numbers():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM numbers")
    r = cur.fetchone()[0]
    conn.close()
    return r

def get_total_reports():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM reports")
    r = cur.fetchone()[0]
    conn.close()
    return r

# ================= PAGE =================
st.set_page_config(page_title="SafeLine AI", page_icon="🛡️", layout="centered")
init_db()

# -------- Query param ile sekme seçimi --------
params = st.query_params
default_tab = params.get("tab", ["query"])[0]

if "active_tab" not in st.session_state:
    st.session_state.active_tab = default_tab

st.title("🛡️ SafeLine AI")

tab_query, tab_admin = st.tabs(["🔍 Sorgula", "📊 Admin"])

# ================= TAB: SORGULA =================
with tab_query:
    if st.session_state.active_tab != "query":
        st.session_state.active_tab = "query"

    phone = st.text_input("Telefon numarası", placeholder="0532... veya +90...")
    if st.button("Sorgula"):
        row = upsert_number(phone)
        st.session_state.num_id = row[0]

    if "num_id" in st.session_state:
        num_id = st.session_state.num_id
        cnt, score = get_stats(num_id)
        st.metric("Risk Skoru", score)

        st.subheader("🚨 Şikayet ekle")
        report_type = st.selectbox("Şikayet türü", REPORT_TYPES)
        channel = st.selectbox("Kanal", CHANNELS)
        category_mode = st.selectbox(
            "Kategori",
            ["Otomatik (Tür ile aynı)"] + CATEGORIES
        )
        msg = st.text_area("Açıklama (opsiyonel)")

        if st.button("Şikayeti Kaydet"):
            if has_recent_report(num_id):
                st.warning("24 saat içinde zaten şikayet var")
            else:
                add_report(num_id, report_type, channel, msg)
                if category_mode == "Otomatik (Tür ile aynı)":
                    set_category(num_id, report_type)
                else:
                    set_category(num_id, category_mode)
                st.success("Şikayet kaydedildi")

        st.subheader("Son şikayetler")
        for r in get_reports(num_id):
            st.write(r)

# ================= TAB: ADMIN =================
with tab_admin:
    if st.session_state.active_tab != "admin":
        st.session_state.active_tab = "admin"

    if "admin" not in st.session_state:
        st.session_state.admin = False

    if not st.session_state.admin:
        pin = st.text_input("Admin PIN", type="password")
        if st.button("Giriş"):
            if pin == ADMIN_PIN:
                st.session_state.admin = True
                st.success("Giriş başarılı")
            else:
                st.error("Yanlış PIN")
    else:
        if st.button("🚪 Çıkış"):
            st.session_state.admin = False
            st.rerun()

        st.metric("Toplam numara", get_total_numbers())
        st.metric("Toplam şikayet", get_total_reports())

        rows = list_numbers()
        csv = "phone,category,count\n"
        for r in rows:
            csv += f"{r[1]},{r[2]},{r[3]}\n"

        st.download_button("CSV indir", csv, "safeline.csv")

        for r in rows:
            st.write(r)
