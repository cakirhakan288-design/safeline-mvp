import sqlite3
from datetime import datetime, timedelta, timezone
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

# ================= CONFIG =================
DB_PATH = "safeline.db"
ADMIN_PIN = "2468"  # değiştir

# 🔗 Buraya kendi Streamlit linkini yaz:
APP_PUBLIC_URL = "https://safeline-mvp-idev9dt6u55ne4hfzejhxu.streamlit.app/"

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
    s = "".join(ch for ch in p.strip() if ch.isdigit() or ch == "+")
    if s.count("+") > 1:
        s = "+" + s.replace("+", "")

    digits = "".join(c for c in s if c.isdigit())
    if s.startswith("+90"):
        return "+90" + digits[2:]
    if digits.startswith("90"):
        return "+" + digits
    if digits.startswith("0"):
        digits = digits[1:]
        return "+90" + digits
    if len(digits) == 10 and digits.startswith("5"):
        return "+90" + digits
    if digits:
        return "+" + digits
    return ""

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

    cur.execute("INSERT INTO numbers (phone_number, category, last_reported_at) VALUES (?, ?, ?)",
                (canonical, "Bilinmiyor", None))
    conn.commit()
    cur.execute("SELECT id, phone_number, category, last_reported_at FROM numbers WHERE phone_number = ?", (canonical,))
    row = cur.fetchone()
    conn.close()
    return row

def get_number(number_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, phone_number, category, last_reported_at FROM numbers WHERE id=?", (number_id,))
    row = cur.fetchone()
    conn.close()
    return row

def set_category(number_id: int, category: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE numbers SET category=? WHERE id=?", (category, number_id))
    conn.commit()
    conn.close()

def add_report(number_id: int, report_type: str, channel: str, message_excerpt: str | None):
    conn = get_conn()
    cur = conn.cursor()
    ts = now_utc_iso()
    cur.execute("""
        INSERT INTO reports (number_id, report_type, channel, message_excerpt, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (number_id, report_type, channel, (message_excerpt or None), ts))
    cur.execute("UPDATE numbers SET last_reported_at=? WHERE id=?", (ts, number_id))
    conn.commit()
    conn.close()

def has_recent_report(number_id: int, hours: int = 24) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*)
        FROM reports
        WHERE number_id = ?
          AND datetime(created_at) >= datetime('now', ?)
    """, (number_id, f"-{hours} hours"))
    cnt = cur.fetchone()[0]
    conn.close()
    return cnt > 0

def get_reports(number_id: int, limit: int = 20):
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
    reports_count = cur.fetchone()[0]
    conn.close()
    score = min(100, reports_count * 15)
    return reports_count, score


# ================= ADMIN QUERIES =================
def list_top_numbers(limit: int = 50, q: str = "", category: str = "Hepsi", sort_by: str = "Şikayet (Azalan)"):
    conn = get_conn()
    cur = conn.cursor()

    where = []
    params = []

    if q:
        where.append("n.phone_number LIKE ?")
        params.append(f"%{q}%")
    if category != "Hepsi":
        where.append("n.category = ?")
        params.append(category)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    if sort_by == "Son Şikayet (Yeni)":
        order_sql = "ORDER BY n.last_reported_at DESC"
    elif sort_by == "Son Şikayet (Eski)":
        order_sql = "ORDER BY n.last_reported_at ASC"
    elif sort_by == "Şikayet (Artan)":
        order_sql = "ORDER BY reports_count ASC, n.last_reported_at DESC"
    else:
        order_sql = "ORDER BY reports_count DESC, n.last_reported_at DESC"

    sql = f"""
        SELECT n.id, n.phone_number, n.category, n.last_reported_at,
               (SELECT COUNT(*) FROM reports r WHERE r.number_id = n.id) AS reports_count
        FROM numbers n
        {where_sql}
        {order_sql}
        LIMIT ?
    """
    params.append(limit)
    cur.execute(sql, tuple(params))
    rows = cur.fetchall()
    conn.close()
    return rows

def get_total_numbers() -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM numbers")
    n = cur.fetchone()[0]
    conn.close()
    return n

def get_total_reports() -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM reports")
    n = cur.fetchone()[0]
    conn.close()
    return n

def get_reports_last_hours(hours: int = 24) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*)
        FROM reports
        WHERE datetime(created_at) >= datetime('now', ?)
    """, (f"-{hours} hours",))
    n = cur.fetchone()[0]
    conn.close()
    return n

def get_reports_by_day(days: int = 30) -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query(f"""
        SELECT date(created_at) AS day, COUNT(*) AS reports
        FROM reports
        WHERE datetime(created_at) >= datetime('now', '-{days} days')
        GROUP BY date(created_at)
        ORDER BY day ASC
    """, conn)
    conn.close()
    if df.empty:
        return pd.DataFrame({"day": [], "reports": []})
    df["day"] = pd.to_datetime(df["day"])
    df = df.set_index("day")
    return df

def get_distribution(field: str, days: int = 30) -> pd.DataFrame:
    if field not in ("report_type", "channel"):
        return pd.DataFrame({"name": [], "count": []})
    conn = get_conn()
    df = pd.read_sql_query(f"""
        SELECT {field} AS name, COUNT(*) AS count
        FROM reports
        WHERE datetime(created_at) >= datetime('now', '-{days} days')
        GROUP BY {field}
        ORDER BY count DESC
    """, conn)
    conn.close()
    return df


# ================= UI HELPERS =================
def risk_label(score: int) -> str:
    if score >= 61:
        return "Yüksek Risk"
    if score >= 31:
        return "Şüpheli"
    return "Düşük Risk"

def risk_color(score: int) -> str:
    if score >= 61:
        return "#ef4444"
    if score >= 31:
        return "#f59e0b"
    return "#22c55e"

def badge_html(text: str, bg: str) -> str:
    return f"""
    <span style="
      display:inline-block;
      padding:6px 10px;
      border-radius:999px;
      background:{bg};
      color:white;
      font-weight:900;
      font-size:13px;
      line-height:1;
      vertical-align:middle;
    ">{text}</span>
    """

def post_admin_verified_to_wrapper():
    components.html(
        """<script>try{window.parent.postMessage("ADMIN_VERIFIED","*");}catch(e){}</script>""",
        height=0,
    )

def copy_to_clipboard_js(text: str):
    safe = text.replace("\\", "\\\\").replace("`", "\\`").replace('"', '\\"')
    components.html(
        f"""
        <script>
        (async function() {{
          try {{
            await navigator.clipboard.writeText("{safe}");
          }} catch(e) {{
            // fallback
            const t = document.createElement('textarea');
            t.value = "{safe}";
            document.body.appendChild(t);
            t.select();
            document.execCommand('copy');
            document.body.removeChild(t);
          }}
        }})();
        </script>
        """,
        height=0,
    )


# ================= PAGE SETUP =================
st.set_page_config(page_title="SafeLine AI", page_icon="🛡️", layout="centered")
init_db()

if "is_admin" not in st.session_state:
    st.session_state["is_admin"] = False
if "pin_tries" not in st.session_state:
    st.session_state["pin_tries"] = 0

# ✅ Header açık kalır (Streamlit’in Share düğmesi görünsün diye)
st.markdown("""
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
.block-container { padding-top: .5rem; padding-bottom: 4.0rem; max-width: 860px; }
.card {
  border: 1px solid rgba(49, 51, 63, 0.14);
  border-radius: 18px;
  padding: 14px;
  margin-bottom: 12px;
  background: rgba(255,255,255,0.03);
}
.subtle { opacity: .82; font-size: .95rem; line-height: 1.35; }
.smallbtn button{
  border-radius: 14px !important;
  padding: 0.55rem 0.7rem !important;
  font-weight: 900 !important;
}
.stTextInput>div>div>input {
  border-radius: 16px;
  padding: 0.95rem 1.0rem;
  font-size: 1.05rem;
}
.stTextArea textarea {
  border-radius: 16px;
  padding: 0.85rem 1.0rem;
  font-size: 1.00rem;
}
[data-baseweb="select"] > div { border-radius: 16px !important; }
</style>
""", unsafe_allow_html=True)

# ---------------- TOP ICON BAR ----------------
st.markdown("### 🛡️ SafeLine AI")
top_l, top_m, top_r = st.columns([1.3, 1.3, 1.6])
with top_l:
    st.markdown("<div class='smallbtn'>", unsafe_allow_html=True)
    if st.button("🔗 Linki kopyala"):
        # Streamlit URL + aktif tab paramı
        current_tab = st.query_params.get("tab", "query")
        current_tab = current_tab[0] if isinstance(current_tab, list) else current_tab
        url = f"{APP_PUBLIC_URL}?tab={current_tab}"
        copy_to_clipboard_js(url)
        st.toast("Link kopyalandı ✅", icon="✅")
    st.markdown("</div>", unsafe_allow_html=True)

with top_m:
    st.markdown("<div class='smallbtn'>", unsafe_allow_html=True)
    if st.button("🔄 Yenile"):
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

with top_r:
    # Paylaş için: link açtırıyoruz (Streamlit Share yerine kendi)
    st.link_button("↗️ Paylaş / Aç", APP_PUBLIC_URL, use_container_width=True)

st.caption("Numara sorgula → risk gör → şikayet ekle (MVP)")

# -------- Navigation --------
tab_param = st.query_params.get("tab", "query")
tab_param = tab_param[0] if isinstance(tab_param, list) else tab_param
default_nav = "Sorgula" if tab_param != "admin" else "Admin"

nav = st.radio(
    "Menü",
    ["Sorgula", "Admin"],
    index=0 if default_nav == "Sorgula" else 1,
    horizontal=True,
    label_visibility="collapsed"
)
st.query_params["tab"] = "query" if nav == "Sorgula" else "admin"


# ================= VIEW: SORGULA =================
if nav == "Sorgula":
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.markdown("### Telefon numarası")
    with st.form("lookup_form", clear_on_submit=False):
        phone_input = st.text_input("", placeholder="0532... veya +90...", label_visibility="collapsed")
        c1, c2 = st.columns(2)
        with c1:
            do_lookup = st.form_submit_button("Sorgula")
        with c2:
            clear = st.form_submit_button("Temizle")
    st.markdown("</div>", unsafe_allow_html=True)

    if clear:
        st.session_state.pop("current_number_id", None)
        st.rerun()

    if do_lookup:
        phone = normalize_phone(phone_input)
        if not phone:
            st.error("Lütfen bir numara gir.")
        else:
            row = upsert_number(phone)
            if row:
                st.session_state["current_number_id"] = row[0]

    number_id = st.session_state.get("current_number_id")
    if number_id:
        row = get_number(number_id)
        if row:
            _id, phone_number, category, last_reported_at = row
            reports_count, score = get_stats(_id)

            st.markdown("<div class='card'>", unsafe_allow_html=True)
            st.markdown(f"### 📞 {phone_number}")
            st.markdown(badge_html(f"{score}/100 • {risk_label(score)}", risk_color(score)), unsafe_allow_html=True)
            st.markdown(
                f"<div class='subtle' style='margin-top:10px'>Kategori: <b>{category}</b> • Şikayet: <b>{reports_count}</b></div>",
                unsafe_allow_html=True
            )
            st.markdown(f"<div class='subtle'>Son şikayet: <b>{last_reported_at or '-'}</b></div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

            st.markdown("<div class='card'>", unsafe_allow_html=True)
            st.markdown("### Kategori güncelle (manuel)")
            new_cat = st.selectbox(
                "Kategori",
                CATEGORIES,
                index=CATEGORIES.index(category) if category in CATEGORIES else (len(CATEGORIES) - 1),
                key="manual_category_select"
            )
            if st.button("Kategoriyi Kaydet"):
                set_category(_id, new_cat)
                st.success("Kategori güncellendi.")
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

            st.markdown("<div class='card'>", unsafe_allow_html=True)
            st.markdown("### 🚨 Şikayet ekle")
            rcol1, rcol2 = st.columns(2)
            with rcol1:
                report_type = st.selectbox("Şikayet Türü", REPORT_TYPES, index=0, key="report_type_select")
            with rcol2:
                channel = st.selectbox("Kanal", CHANNELS, index=0, key="channel_select")

            category_options = ["Otomatik (Tür ile aynı)"] + CATEGORIES
            chosen_category_mode = st.selectbox(
                "Kategori (şikayetle birlikte)",
                category_options,
                index=0,
                help="Varsayılan: seçtiğin şikayet türü kategoriye otomatik yazılır. İstersen farklı seçebilirsin.",
                key="report_category_mode"
            )
            message_excerpt = st.text_area("Açıklama (opsiyonel)", placeholder="Örn: 'Bonus için linke tıkla...'", key="msg")

            if st.button("Şikayeti Kaydet", type="primary"):
                if has_recent_report(_id, hours=24):
                    st.warning("⚠️ Bu numara için son 24 saat içinde zaten şikayet eklenmiş.")
                else:
                    add_report(_id, report_type, channel, message_excerpt)
                    set_category(_id, report_type if chosen_category_mode == "Otomatik (Tür ile aynı)" else chosen_category_mode)
                    st.success("Şikayet kaydedildi. Skor güncellendi.")
                    st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

            reps = get_reports(_id, limit=15)
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            st.markdown("### Son şikayetler")
            if not reps:
                st.info("Henüz şikayet yok.")
            else:
                for rt, ch, msg, ts in reps:
                    st.markdown(f"- **{rt}** / {ch}  \n  <small>{ts}</small>", unsafe_allow_html=True)
                    if msg:
                        st.markdown(f"<div class='subtle'>{msg}</div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)


# ================= VIEW: ADMIN + DASHBOARD =================
else:
    if not st.session_state.get("is_admin", False):
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("### 🔐 Admin girişi")
        pin = st.text_input("PIN", type="password", placeholder="4 haneli PIN")
        col_a, col_b = st.columns(2)
        with col_a:
            login = st.button("Giriş Yap", type="primary")
        with col_b:
            reset = st.button("Sıfırla")

        if reset:
            st.session_state["pin_tries"] = 0
            st.rerun()

        if login:
            if pin == ADMIN_PIN:
                st.session_state["is_admin"] = True
                st.session_state["pin_tries"] = 0
                post_admin_verified_to_wrapper()
                st.success("Admin girişi başarılı.")
                st.rerun()
            else:
                st.session_state["pin_tries"] += 1
                st.error("Yanlış PIN.")
        st.markdown("</div>", unsafe_allow_html=True)

    else:
        top_l, top_r = st.columns([3, 1])
        with top_l:
            st.markdown("### 📊 Admin Dashboard")
        with top_r:
            if st.button("🚪 Admin çıkış", use_container_width=True):
                st.session_state["is_admin"] = False
                st.rerun()

        total_numbers = get_total_numbers()
        total_reports = get_total_reports()
        reports_24h = get_reports_last_hours(24)
        reports_7d = get_reports_last_hours(24 * 7)

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Toplam Numara", total_numbers)
        k2.metric("Toplam Şikayet", total_reports)
        k3.metric("Son 24 Saat", reports_24h)
        k4.metric("Son 7 Gün", reports_7d)

        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("#### Şikayet Trend (Son 30 gün)")
        df30 = get_reports_by_day(30)
        if df30.empty:
            st.info("Henüz yeterli veri yok.")
        else:
            start = (datetime.now(timezone.utc) - timedelta(days=29)).date()
            idx = pd.date_range(start=start, periods=30, freq="D")
            df30 = df30.reindex(idx, fill_value=0)
            st.line_chart(df30, height=220)
        st.markdown("</div>", unsafe_allow_html=True)

        cL, cR = st.columns(2)
        with cL:
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            st.markdown("#### Tür Dağılımı (Son 30 gün)")
            dist_type = get_distribution("report_type", 30)
            st.bar_chart(dist_type.set_index("name"), height=220) if not dist_type.empty else st.info("Veri yok.")
            st.markdown("</div>", unsafe_allow_html=True)

        with cR:
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            st.markdown("#### Kanal Dağılımı (Son 30 gün)")
            dist_ch = get_distribution("channel", 30)
            st.bar_chart(dist_ch.set_index("name"), height=220) if not dist_ch.empty else st.info("Veri yok.")
            st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("### 🔎 Filtreli liste (CSV bu filtrelere göre iner)")

        q = st.text_input("Telefonla ara", placeholder="örn: 532 veya +90532")
        category_filter = st.selectbox("Kategori filtresi", ["Hepsi"] + CATEGORIES)
        sort_by = st.selectbox("Sıralama", ["Şikayet (Azalan)", "Şikayet (Artan)", "Son Şikayet (Yeni)", "Son Şikayet (Eski)"])
        limit = st.slider("Kaç kayıt gösterilsin?", min_value=10, max_value=200, value=50, step=10)

        rows = list_top_numbers(limit=limit, q=q.strip(), category=category_filter, sort_by=sort_by)

        csv_header = "id,phone_number,category,last_reported_at,reports_count,score,risk_label\n"
        csv_lines = [csv_header]
        for _id, phone, cat, last_ts, cnt in rows:
            score = min(100, cnt * 15)
            label = risk_label(score)
            last_ts_safe = (last_ts or "").replace(",", " ")
            csv_lines.append(f"{_id},{phone},{cat},{last_ts_safe},{cnt},{score},{label}\n")
        csv_data = "".join(csv_lines)

        st.download_button(
            label="⬇️ CSV indir (filtreli liste)",
            data=csv_data.encode("utf-8"),
            file_name="safeline_numbers.csv",
            mime="text/csv",
            use_container_width=True
        )
