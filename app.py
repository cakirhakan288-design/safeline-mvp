import sqlite3
from datetime import datetime, timezone
import pandas as pd
import streamlit as st

# ================= CONFIG =================
DB_PATH = "whooops.db"
ADMIN_PIN = "2468"  # değiştir

APP_NAME = "WhoOops"

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

def now_utc_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def normalize_phone(p: str) -> str:
    if not p:
        return ""
    digits = "".join(c for c in p if c.isdigit())
    if not digits:
        return ""
    if digits.startswith("0"):
        digits = digits[1:]
    # TR odaklı basit normalize
    if len(digits) == 10:
        return "+90" + digits
    if digits.startswith("90"):
        return "+" + digits
    return "+" + digits

def upsert_number(phone_number: str):
    canonical = normalize_phone(phone_number)
    if not canonical:
        return None

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, phone_number, category, last_reported_at FROM numbers WHERE phone_number = ?", (canonical,))
    row = cur.fetchone()
    if row:
        conn.close()
        return row

    cur.execute(
        "INSERT INTO numbers (phone_number, category) VALUES (?, ?)",
        (canonical, "Bilinmiyor")
    )
    conn.commit()
    cur.execute("SELECT id, phone_number, category, last_reported_at FROM numbers WHERE phone_number = ?", (canonical,))
    row = cur.fetchone()
    conn.close()
    return row

def set_category(number_id: int, category: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE numbers SET category=? WHERE id=?", (category, number_id))
    conn.commit()
    conn.close()

def add_report(number_id: int, report_type: str, channel: str, message: str | None):
    conn = get_conn()
    cur = conn.cursor()
    ts = now_utc_iso()
    cur.execute("""
        INSERT INTO reports (number_id, report_type, channel, message_excerpt, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (number_id, report_type, channel, message, ts))
    cur.execute("UPDATE numbers SET last_reported_at=? WHERE id=?", (ts, number_id))
    conn.commit()
    conn.close()

def has_recent_report(number_id: int, hours: int = 24):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM reports
        WHERE number_id=? AND datetime(created_at) >= datetime('now', ?)
    """, (number_id, f"-{hours} hours"))
    c = cur.fetchone()[0]
    conn.close()
    return c > 0

def get_reports(number_id: int, limit: int = 15):
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

def get_stats(number_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM reports WHERE number_id=?", (number_id,))
    cnt = cur.fetchone()[0]
    conn.close()
    score = min(100, cnt * 15)
    return cnt, score

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
    n = cur.fetchone()[0]
    conn.close()
    return n

def get_total_reports():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM reports")
    n = cur.fetchone()[0]
    conn.close()
    return n


# ================= UI HELPERS =================
def risk_label(score):
    if score >= 61:
        return "Yüksek Risk"
    if score >= 31:
        return "Şüpheli"
    return "Düşük Risk"

def risk_color(score):
    if score >= 61:
        return "#ef4444"
    if score >= 31:
        return "#f59e0b"
    return "#22c55e"

def badge(text, color):
    return f"""
    <span style="
    background:{color};
    color:white;
    padding:6px 12px;
    border-radius:999px;
    font-weight:900;
    font-size:13px;
    ">
    {text}
    </span>
    """


# ================= PAGE =================
st.set_page_config(page_title=APP_NAME, page_icon="🛡️", layout="centered")
init_db()

st.markdown(
    """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}

    .block-container { padding-top: 0.8rem; max-width: 880px; }

    .card {
        border-radius:18px;
        padding:16px;
        background:rgba(255,255,255,0.04);
        margin-bottom:14px;
        border:1px solid rgba(255,255,255,0.08);
    }

    /* input daha bariz olsun */
    .stTextInput input {
        border-radius: 14px !important;
        padding: 0.9rem 1rem !important;
        font-size: 1.05rem !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# ✅ Logo benzeri üst başlık (kalkan)
st.markdown(f"## 🛡️ {APP_NAME}")
st.caption("Oops demeden önce kontrol et.")

# Tab seçimi (buradaki label boşluğu da kafa karıştırmasın diye label verdim)
tab = st.radio("Menü", ["🔍 Sorgula", "📊 Admin"], horizontal=True, label_visibility="collapsed")


# ================= SORGULA =================
if tab == "🔍 Sorgula":
    st.markdown("<div class='card'>", unsafe_allow_html=True)

    # ✅ Başlığı ayrı gösteriyoruz (araya “tıklanabilir bar” hissi veren label boşluğu kalmasın)
    st.markdown("### Telefon numarası")
    phone = st.text_input(
        label="Telefon numarası",
        placeholder="0532... veya +90...",
        label_visibility="collapsed"
    )

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Numarayı kontrol et", use_container_width=True):
            row = upsert_number(phone)
            if row:
                st.session_state["nid"] = row[0]
            else:
                st.error("Lütfen geçerli bir numara gir.")
    with col2:
        if st.button("Temizle", use_container_width=True):
            st.session_state.pop("nid", None)
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

    if "nid" in st.session_state:
        nid = st.session_state["nid"]
        cnt, score = get_stats(nid)

        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown(badge(f"{score}/100 • {risk_label(score)}", risk_color(score)), unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("### 🚨 Şikayet ekle")
        rtype = st.selectbox("Şikayet türü", REPORT_TYPES)
        channel = st.selectbox("Kanal", CHANNELS)
        cat_mode = st.selectbox("Kategori", ["Otomatik (Tür ile aynı)"] + CATEGORIES)
        msg = st.text_area("Açıklama (opsiyonel)", placeholder="Örn: Bonus linki attı / IBAN istedi / vb.")

        if st.button("Şikayet ekle", type="primary", use_container_width=True):
            if has_recent_report(nid):
                st.warning("Bu numara için son 24 saatte zaten şikayet var.")
            else:
                add_report(nid, rtype, channel, msg)
                set_category(nid, rtype if cat_mode.startswith("Otomatik") else cat_mode)
                st.success("Şikayet eklendi.")
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("### Son şikayetler")
        reps = get_reports(nid)
        if not reps:
            st.info("Henüz şikayet yok.")
        else:
            for rt, ch, m, ts in reps:
                st.markdown(f"- **{rt}** / {ch} — {ts}")
                if m:
                    st.caption(m)
        st.markdown("</div>", unsafe_allow_html=True)


# ================= ADMIN =================
else:
    if "admin" not in st.session_state:
        st.session_state["admin"] = False

    if not st.session_state["admin"]:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("### 🔐 Admin girişi")
        pin = st.text_input("Admin PIN", type="password", label_visibility="collapsed", placeholder="PIN")
        if st.button("Giriş", type="primary", use_container_width=True):
            if pin == ADMIN_PIN:
                st.session_state["admin"] = True
                st.success("Hoş geldin 👋")
                st.rerun()
            else:
                st.error("Yanlış PIN")
        st.markdown("</div>", unsafe_allow_html=True)
    else:
        colA, colB = st.columns([2, 1])
        with colA:
            st.markdown("### 📊 Admin paneli")
        with colB:
            if st.button("🚪 Çıkış", use_container_width=True):
                st.session_state["admin"] = False
                st.rerun()

        st.metric("Toplam numara", get_total_numbers())
        st.metric("Toplam şikayet", get_total_reports())

        rows = list_numbers()

        csv = "phone,category,count\n"
        for r in rows:
            csv += f"{r[1]},{r[2]},{r[3]}\n"

        st.download_button(
            "⬇️ CSV indir",
            csv,
            "whooops_data.csv",
            mime="text/csv",
            use_container_width=True
        )

        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("### Liste")
        for r in rows:
            st.write(r)
        st.markdown("</div>", unsafe_allow_html=True)
