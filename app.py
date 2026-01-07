import sqlite3
from datetime import datetime
import streamlit as st

DB_PATH = "safeline.db"

# ========= ADMIN =========
ADMIN_PIN = "2468"

# ========= CONSTANTS =========
CATEGORIES = ["Dolandırıcılık", "Bahis", "Şüpheli", "Güvenli", "Bilinmiyor"]
REPORT_TYPES = ["Dolandırıcılık", "Bahis", "Şüpheli", "Güvenli"]
CHANNELS = ["Arama", "SMS", "WhatsApp", "Diğer"]


# ========= DB =========
def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS numbers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone_number TEXT UNIQUE,
        category TEXT,
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


# ========= HELPERS =========
def normalize_phone(p):
    digits = "".join(c for c in p if c.isdigit())
    if digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10:
        return "+90" + digits
    if digits.startswith("90"):
        return "+" + digits
    if p.startswith("+"):
        return p
    return "+" + digits


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


def get_stats(number_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM reports WHERE number_id=?", (number_id,))
    cnt = cur.fetchone()[0]
    conn.close()
    return cnt, min(100, cnt * 15)


def get_reports(number_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT report_type, channel, message_excerpt, created_at
        FROM reports WHERE number_id=?
        ORDER BY created_at DESC
    """, (number_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


# ========= AUTO CATEGORY =========
def auto_update_category(number_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT report_type, COUNT(*) FROM reports
        WHERE number_id=?
        GROUP BY report_type
    """, (number_id,))
    counts = dict(cur.fetchall())

    if counts.get("Dolandırıcılık", 0) >= 2:
        cat = "Dolandırıcılık"
    elif counts.get("Bahis", 0) >= 2:
        cat = "Bahis"
    elif counts.get("Şüpheli", 0) >= 2:
        cat = "Şüpheli"
    else:
        conn.close()
        return None

    cur.execute("UPDATE numbers SET category=? WHERE id=?", (cat, number_id))
    conn.commit()
    conn.close()
    return cat


# ========= ADMIN DASHBOARD =========
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


def get_reports_24h():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM reports
        WHERE datetime(created_at) >= datetime('now','-24 hours')
    """)
    r = cur.fetchone()[0]
    conn.close()
    return r


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


# ========= UI =========
st.set_page_config(page_title="SafeLine AI", layout="centered")
init_db()

if "admin" not in st.session_state:
    st.session_state.admin = False

st.title("🛡️ SafeLine AI")

tab1, tab2 = st.tabs(["🔍 Sorgula", "📊 Admin"])

# ===== USER TAB =====
with tab1:
    phone = st.text_input("Telefon numarası")
    if st.button("Sorgula"):
        row = upsert_number(phone)
        st.session_state.num_id = row[0]

    if "num_id" in st.session_state:
        num_id = st.session_state.num_id
        cnt, score = get_stats(num_id)
        st.metric("Risk Skoru", score)

        if st.button("🚨 Şikayet Ekle"):
            if has_recent_report(num_id):
                st.warning("24 saat kuralı")
            else:
                add_report(num_id, "Bahis", "SMS", "")
                new_cat = auto_update_category(num_id)
                if new_cat:
                    st.info(f"Kategori güncellendi: {new_cat}")

        for r in get_reports(num_id):
            st.write(r)

# ===== ADMIN TAB =====
with tab2:
    if not st.session_state.admin:
        pin = st.text_input("Admin PIN", type="password")
        if st.button("Giriş"):
            if pin == ADMIN_PIN:
                st.session_state.admin = True
                st.success("Giriş başarılı")
            else:
                st.error("Yanlış PIN")
    else:
        if st.button("🚪 Admin çıkış"):
            st.session_state.admin = False
            st.experimental_rerun()

        c1, c2, c3 = st.columns(3)
        c1.metric("Numaralar", get_total_numbers())
        c2.metric("Şikayetler", get_total_reports())
        c3.metric("Son 24s", get_reports_24h())

        rows = list_numbers()

        csv = "phone,category,count\n"
        for r in rows:
            csv += f"{r[1]},{r[2]},{r[3]}\n"

        st.download_button("CSV indir", csv, "safeline.csv")

        for r in rows:
            st.write(r)
