import sqlite3
from datetime import datetime
import streamlit as st

DB_PATH = "safeline.db"

CATEGORIES = ["Dolandırıcılık", "Bahis", "Şüpheli", "Güvenli", "Bilinmiyor"]
REPORT_TYPES = ["Dolandırıcılık", "Bahis", "Şüpheli", "Güvenli"]
CHANNELS = ["Arama", "SMS", "WhatsApp", "Diğer"]


# -------------------- DB --------------------
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
    """
    TR odaklı normalize:
    - Tüm boşluk/()- gibi karakterleri siler
    - 0 ile başlıyorsa +90 ekler
    - 90 ile başlıyorsa + ekler
    - +90 ile başlıyorsa aynen bırakır
    - 10 haneli ise (5xx...) +90 ekler
    """
    if not p:
        return ""

    s = p.strip()
    # sadece rakamları ve + işaretini tut
    s2 = []
    for ch in s:
        if ch.isdigit() or ch == "+":
            s2.append(ch)
    s = "".join(s2)

    # baştaki + haricindeki + ları temizle (garip kopyalamalar için)
    if s.count("+") > 1:
        s = "+" + s.replace("+", "")

    # +90 ile
    if s.startswith("+90"):
        digits = s[1:]  # '90...'
        digits = "".join([c for c in digits if c.isdigit()])
        return "+" + digits

    # 90 ile
    if s.startswith("90"):
        digits = "".join([c for c in s if c.isdigit()])
        return "+" + digits

    # 0 ile (0532...)
    if s.startswith("0"):
        digits = "".join([c for c in s if c.isdigit()])
        # 0'ı at
        digits = digits[1:]
        # TR GSM 10 hane beklenir
        if len(digits) == 10:
            return "+90" + digits
        return "+90" + digits  # MVP: uzun/kısa olsa da +90 ekleyip döndür

    # 10 haneli direkt (532...)
    digits = "".join([c for c in s if c.isdigit()])
    if len(digits) == 10 and digits.startswith("5"):
        return "+90" + digits

    # fallback: + koymadan gelen farklı şeyler
    if digits:
        return "+" + digits if not s.startswith("+") else s

    return ""


def upsert_number(phone_number: str):
    """
    1) Girilen numarayı normalize eder (kanonik: +90xxxxxxxxxx)
    2) DB'de birebir eşleşme yoksa, mevcut kayıtları da normalize edip eşleştirmeye çalışır
    3) Eşleşme bulursa o kaydı döndürür ve phone_number'ı kanonik formata günceller
    4) Hiç yoksa yeni kayıt açar (kanonik formatla)
    """
    canonical = normalize_phone(phone_number)
    if not canonical:
        return None

    conn = get_conn()
    cur = conn.cursor()

    # 1) Birebir (kanonik) eşleşme
    cur.execute("SELECT id, phone_number, category, last_reported_at FROM numbers WHERE phone_number = ?", (canonical,))
    row = cur.fetchone()
    if row:
        conn.close()
        return row

    # 2) Eski kayıtlar arasında normalize ederek eşleşme ara
    cur.execute("SELECT id, phone_number, category, last_reported_at FROM numbers")
    all_rows = cur.fetchall()

    for r in all_rows:
        rid, rphone, rcat, rlast = r
        if normalize_phone(rphone) == canonical:
            # Bulduk: bu kaydı kanonik hale getir (ileride tekrar ayrışmasın)
            cur.execute("UPDATE numbers SET phone_number = ? WHERE id = ?", (canonical, rid))
            conn.commit()
            conn.close()
            return (rid, canonical, rcat, rlast)

    # 3) Yoksa yeni kayıt aç
    cur.execute(
        "INSERT INTO numbers (phone_number, category, last_reported_at) VALUES (?, ?, ?)",
        (canonical, "Bilinmiyor", None)
    )
    conn.commit()
    cur.execute("SELECT id, phone_number, category, last_reported_at FROM numbers WHERE phone_number = ?", (canonical,))
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
    cur.execute("UPDATE numbers SET last_reported_at = ? WHERE id = ?", (now, number_id))
    conn.commit()
    conn.close()

def get_number(number_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, phone_number, category, last_reported_at FROM numbers WHERE id = ?", (number_id,))
    row = cur.fetchone()
    conn.close()
    return row

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

def get_type_counts(number_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT report_type, COUNT(*) 
        FROM reports
        WHERE number_id = ?
        GROUP BY report_type
    """, (number_id,))
    rows = cur.fetchall()
    conn.close()
    return {rt: cnt for rt, cnt in rows}

def decide_auto_category(counts: dict, total_reports: int) -> str:
    # Öncelik: Dolandırıcılık > Bahis > Şüpheli
    if counts.get("Dolandırıcılık", 0) >= 2:
        return "Dolandırıcılık"
    if counts.get("Bahis", 0) >= 2:
        return "Bahis"
    if counts.get("Şüpheli", 0) >= 2:
        return "Şüpheli"
    if total_reports >= 3:
        return "Şüpheli"
    return "Bilinmiyor"

def auto_update_category(number_id: int):
    # mevcut kategori Güvenli ise otomatik bozma
    row = get_number(number_id)
    if not row:
        return
    _, _, current_category, _ = row
    if current_category == "Güvenli":
        return

    counts = get_type_counts(number_id)
    total, score = get_stats(number_id)  # total_reports burada
    new_cat = decide_auto_category(counts, total)

    if new_cat != current_category:
        set_category(number_id, new_cat)


def get_reports(number_id: int, limit: int = 20):
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
def has_recent_report(number_id: int, hours: int = 24) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*)
        FROM reports
        WHERE number_id = ?
          AND datetime(created_at) >= datetime('now', ?)
    """, (number_id, f'-{hours} hours'))
    cnt = cur.fetchone()[0]
    conn.close()
    return cnt > 0

def list_top_numbers(limit: int = 30):
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


# -------------------- UI Helpers --------------------
def risk_label(score: int) -> str:
    if score >= 61:
        return "Yüksek Risk"
    if score >= 31:
        return "Şüpheli"
    return "Düşük Risk"

def risk_color(score: int) -> str:
    if score >= 61:
        return "#ef4444"  # red
    if score >= 31:
        return "#f59e0b"  # amber
    return "#22c55e"      # green

def badge_html(text: str, bg: str) -> str:
    return f"""
    <span style="
        display:inline-block;
        padding:6px 10px;
        border-radius:999px;
        background:{bg};
        color:white;
        font-weight:700;
        font-size:14px;
        line-height:1;
        vertical-align:middle;
    ">{text}</span>
    """

def card_start():
    st.markdown("""<div class="card">""", unsafe_allow_html=True)

def card_end():
    st.markdown("""</div>""", unsafe_allow_html=True)


# -------------------- Page config + CSS --------------------
st.set_page_config(page_title="SafeLine AI", page_icon="🛡️", layout="centered")

st.markdown("""
<style>
/* Make it feel like a mobile app */
.block-container { padding-top: 1.1rem; padding-bottom: 2.5rem; max-width: 720px; }
h1 { font-size: 1.55rem !important; }
h2, h3 { letter-spacing: -0.2px; }

.card {
  border: 1px solid rgba(49, 51, 63, 0.12);
  border-radius: 16px;
  padding: 14px 14px 10px 14px;
  margin-bottom: 12px;
  background: rgba(255,255,255,0.03);
}

.big {
  font-size: 2.0rem;
  font-weight: 800;
  margin: 0;
}

.subtle {
  opacity: 0.78;
  font-size: 0.95rem;
}

.stButton>button {
  width: 100%;
  border-radius: 14px;
  padding: 0.75rem 0.9rem;
  font-weight: 700;
}

.stTextInput>div>div>input {
  border-radius: 14px;
  padding: 0.75rem 0.9rem;
  font-size: 1.05rem;
}

.stTextArea textarea {
  border-radius: 14px;
}

small { opacity: 0.8; }
</style>
""", unsafe_allow_html=True)

init_db()

# -------------------- App --------------------
st.title("🛡️ SafeLine AI")
st.caption("Numara sorgula → risk gör → şikayet ekle. (MVP)")

tab_query, tab_admin = st.tabs(["🔎 Sorgula", "📊 Liste"])

with tab_query:
    card_start()
    st.markdown("### Telefon numarası")
    phone_input = st.text_input("", placeholder="0532... veya +90...", label_visibility="collapsed")
    col1, col2 = st.columns([1, 1])
    with col1:
        do_lookup = st.button("Sorgula")
    with col2:
        clear = st.button("Temizle")

    if clear:
        st.session_state.pop("current_number_id", None)
        st.rerun()

    if do_lookup:
        phone = normalize_phone(phone_input)
        if not phone:
            st.error("Lütfen bir numara gir.")
        else:
            row = upsert_number(phone)
            st.session_state["current_number_id"] = row[0]
    card_end()

    number_id = st.session_state.get("current_number_id")
    if number_id:
        row = get_number(number_id)
        if not row:
            st.warning("Kayıt bulunamadı. Tekrar sorgula.")
        else:
            _id, phone_number, category, last_reported_at = row
            reports_count, score = get_stats(_id)

            card_start()
            st.markdown(f"### 📞 {phone_number}")
            st.markdown(
                badge_html(f"{score}/100 • {risk_label(score)}", risk_color(score)),
                unsafe_allow_html=True
            )
            st.markdown(f"<div class='subtle' style='margin-top:10px'>Kategori: <b>{category}</b> • Şikayet: <b>{reports_count}</b></div>", unsafe_allow_html=True)
            st.markdown(f"<div class='subtle'>Son şikayet: <b>{last_reported_at or '-'}</b></div>", unsafe_allow_html=True)
            card_end()

            # Category update
            card_start()
            st.markdown("### Kategori güncelle")
            new_cat = st.selectbox("Kategori", CATEGORIES, index=CATEGORIES.index(category) if category in CATEGORIES else 4)
            if st.button("Kategoriyi Kaydet"):
                set_category(_id, new_cat)
                st.success("Kategori güncellendi.")
            card_end()

            # Add report
            card_start()
            st.markdown("### 🚨 Şikayet ekle")
            rcol1, rcol2 = st.columns(2)
            with rcol1:
                report_type = st.selectbox("Tür", REPORT_TYPES, index=0)
            with rcol2:
                channel = st.selectbox("Kanal", CHANNELS, index=0)

            message_excerpt = st.text_area("Açıklama (opsiyonel)", placeholder="Örn: 'Bonus için linke tıkla...'")
if st.button("Şikayeti Kaydet", type="primary"):
    # B1: aynı numaraya 24 saatte 1 şikayet
    if has_recent_report(_id, hours=24):
        st.warning("⚠️ Bu numara için son 24 saat içinde zaten şikayet eklenmiş.")
    else:
        add_report(_id, report_type, channel, message_excerpt)
        auto_update_category(_id)
        st.success("Şikayet kaydedildi. Skor ve kategori güncellendi.")


card_end()


# Latest reports
if number_id:
    row = get_number(number_id)
    if row:
        _id, phone_number, category, last_reported_at = row

        reps = get_reports(_id, limit=15)

        card_start()
        st.markdown("### Son şikayetler")

        if not reps:
            st.info("Henüz şikayet yok.")
        else:
            for rt, ch, msg, ts in reps:
                st.markdown(f"- **{rt}** / {ch}  \n  <small>{ts}</small>", unsafe_allow_html=True)
                if msg:
                    st.markdown(f"<div class='subtle'>{msg}</div>", unsafe_allow_html=True)

        card_end()


card_start()
st.markdown("### Son şikayetler")
reps = []

if not reps:
    st.info("Henüz şikayet yok.")
else:
    for rt, ch, msg, ts in reps:
        st.markdown(f"- **{rt}** / {ch}  \n  <small>{ts}</small>", unsafe_allow_html=True)
        if msg:
            st.markdown(f"<div class='subtle'>{msg}</div>", unsafe_allow_html=True)

card_end()


with tab_admin:
    st.markdown("### En çok şikayet alan numaralar")
    rows = list_top_numbers(limit=50)
    if not rows:
        st.info("Henüz kayıt yok.")
    else:
        for _id, phone, cat, last_ts, cnt in rows:
            score = min(100, cnt * 15)
            card_start()
            st.markdown(f"**{phone}**")
            st.markdown(
                badge_html(f"{score}/100 • {risk_label(score)}", risk_color(score)),
                unsafe_allow_html=True
            )
            st.markdown(f"<div class='subtle'>Kategori: <b>{cat}</b> • Şikayet: <b>{cnt}</b> • Son: <b>{last_ts or '-'}</b></div>", unsafe_allow_html=True)
            if st.button(f"Bu numarayı aç → {phone}", key=f"open_{_id}"):
                st.session_state["current_number_id"] = _id
                st.rerun()
            card_end()










