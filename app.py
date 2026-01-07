import sqlite3
from datetime import datetime
import streamlit as st

DB_PATH = "safeline.db"

# -------- ADMIN PIN (buradan değiştir) --------
ADMIN_PIN = "2468"
# --------------------------------------------

CATEGORIES = ["Dolandırıcılık", "Bahis", "Şüpheli", "Güvenli", "Bilinmiyor"]
REPORT_TYPES = ["Dolandırıcılık", "Bahis", "Şüpheli", "Güvenli"]
CHANNELS = ["Arama", "SMS", "WhatsApp", "Diğer"]


# ======================= DB =======================
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
    """TR odaklı normalize (hedef: +905xxxxxxxxx)"""
    if not p:
        return ""
    s = p.strip()
    s2 = []
    for ch in s:
        if ch.isdigit() or ch == "+":
            s2.append(ch)
    s = "".join(s2)

    if s.count("+") > 1:
        s = "+" + s.replace("+", "")

    if s.startswith("+90"):
        digits = "".join(c for c in s if c.isdigit())
        return "+" + digits

    if s.startswith("90"):
        digits = "".join(c for c in s if c.isdigit())
        return "+" + digits

    if s.startswith("0"):
        digits = "".join(c for c in s if c.isdigit())[1:]
        return "+90" + digits

    digits = "".join(c for c in s if c.isdigit())
    if len(digits) == 10 and digits.startswith("5"):
        return "+90" + digits

    if digits:
        return "+" + digits if not s.startswith("+") else s
    return ""


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


def add_report(number_id: int, report_type: str, channel: str, message_excerpt: str | None):
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    cur.execute(
        "INSERT INTO reports (number_id, report_type, channel, message_excerpt, created_at) VALUES (?, ?, ?, ?, ?)",
        (number_id, report_type, channel, (message_excerpt or None), now)
    )
    cur.execute("UPDATE numbers SET last_reported_at = ? WHERE id = ?", (now, number_id))
    conn.commit()
    conn.close()


def has_recent_report(number_id: int, hours: int = 24) -> bool:
    """B1: aynı numaraya son X saat içinde şikayet var mı?"""
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


def upsert_number(phone_number: str):
    """Normalize + aynı numarayı tek kayda eşleme"""
    canonical = normalize_phone(phone_number)
    if not canonical:
        return None

    conn = get_conn()
    cur = conn.cursor()

    # 1) birebir eşleşme
    cur.execute("SELECT id, phone_number, category, last_reported_at FROM numbers WHERE phone_number = ?", (canonical,))
    row = cur.fetchone()
    if row:
        conn.close()
        return row

    # 2) normalize ederek eşleştir
    cur.execute("SELECT id, phone_number, category, last_reported_at FROM numbers")
    all_rows = cur.fetchall()
    for rid, rphone, rcat, rlast in all_rows:
        if normalize_phone(rphone) == canonical:
            cur.execute("UPDATE numbers SET phone_number = ? WHERE id = ?", (canonical, rid))
            conn.commit()
            conn.close()
            return (rid, canonical, rcat, rlast)

    # 3) yoksa ekle
    cur.execute(
        "INSERT INTO numbers (phone_number, category, last_reported_at) VALUES (?, ?, ?)",
        (canonical, "Bilinmiyor", None)
    )
    conn.commit()
    cur.execute("SELECT id, phone_number, category, last_reported_at FROM numbers WHERE phone_number = ?", (canonical,))
    row = cur.fetchone()
    conn.close()
    return row


# ======================= A + D (AUTO CATEGORY) =======================
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
    """
    Kategori değişirse yeni kategoriyi döndürür, değişmezse None döndürür.
    'Güvenli' manuel kaldığı için otomatik bozulmaz.
    """
    row = get_number(number_id)
    if not row:
        return None

    _, _, current_category, _ = row
    if current_category == "Güvenli":
        return None

    counts = get_type_counts(number_id)
    total_reports, _score = get_stats(number_id)
    new_cat = decide_auto_category(counts, total_reports)

    if new_cat != current_category:
        set_category(number_id, new_cat)
        return new_cat
    return None


# ======================= C (ADMIN LIST) =======================
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


# ======================= G (DASHBOARD) =======================
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


def get_top_category():
    """Reports türüne göre en çok şikayet alan tür (report_type, adet)"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT report_type, COUNT(*) AS c
        FROM reports
        GROUP BY report_type
        ORDER BY c DESC
        LIMIT 1
    """)
    row = cur.fetchone()
    conn.close()
    if not row:
        return ("-", 0)
    return (row[0], row[1])


def get_top_risky(limit: int = 5):
    """En riskli ilk N numara (şikayet sayısı desc)"""
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


# ======================= UI HELPERS =======================
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
        font-weight:800;
        font-size:14px;
        line-height:1;
        vertical-align:middle;
    ">{text}</span>
    """


def card_start():
    st.markdown("<div class='card'>", unsafe_allow_html=True)


def card_end():
    st.markdown("</div>", unsafe_allow_html=True)


# ======================= PAGE SETUP =======================
st.set_page_config(page_title="SafeLine AI", page_icon="🛡️", layout="centered")
init_db()

# Mobil-app hissi + Streamlit chrome gizleme + büyük dokunma alanları
st.markdown("""
<style>
html, body { -webkit-font-smoothing: antialiased; }
.block-container { padding-top: .8rem; padding-bottom: 5.0rem; max-width: 760px; }

#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}

.card {
  border: 1px solid rgba(49, 51, 63, 0.14);
  border-radius: 18px;
  padding: 14px 14px 12px 14px;
  margin-bottom: 12px;
  background: rgba(255,255,255,0.03);
}

.subtle { opacity: .82; font-size: .95rem; line-height: 1.35; }

h1 { font-size: 1.45rem !important; margin-bottom: .25rem !important; }
h2 { font-size: 1.15rem !important; }
h3 { font-size: 1.05rem !important; }

.stButton>button {
  width: 100%;
  border-radius: 16px;
  padding: 0.90rem 1.0rem;
  font-weight: 800;
  font-size: 1.00rem;
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

[data-baseweb="select"] > div {
  border-radius: 16px !important;
}

.stTabs [data-baseweb="tab-list"] {
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 6px;
}
.stTabs [data-baseweb="tab"] {
  border-radius: 999px;
  padding: 10px 14px;
  font-weight: 800;
  white-space: nowrap;
}

@media (max-width: 640px) {
  .block-container { padding-left: 0.75rem; padding-right: 0.75rem; max-width: 100%; }
  [data-testid="stHorizontalBlock"] { gap: 10px; }
  [data-testid="column"] { width: 100% !important; flex: 1 1 100% !important; }
  .card { border-radius: 16px; padding: 12px; }
  .stButton>button { padding: 0.95rem 1.0rem; border-radius: 16px; }
}

*::-webkit-scrollbar { width: 0px; height: 0px; }
</style>
""", unsafe_allow_html=True)

if "is_admin" not in st.session_state:
    st.session_state["is_admin"] = False
if "pin_tries" not in st.session_state:
    st.session_state["pin_tries"] = 0

st.title("🛡️ SafeLine AI")
st.caption("Numara sorgula → risk gör → şikayet ekle. (MVP)")

tab_query, tab_admin = st.tabs(["🔎 Sorgula", "📊 Liste (Admin)"])


# ======================= TAB: Sorgula =======================
with tab_query:
    card_start()
    st.markdown("### Telefon numarası")

    # Form: Enter ile sorgula (mobilde daha rahat)
    with st.form("lookup_form", clear_on_submit=False):
        phone_input = st.text_input("", placeholder="0532... veya +90...", label_visibility="collapsed")
        c1, c2 = st.columns(2)
        with c1:
            do_lookup = st.form_submit_button("Sorgula")
        with c2:
            clear = st.form_submit_button("Temizle")

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
            st.markdown(badge_html(f"{score}/100 • {risk_label(score)}", risk_color(score)), unsafe_allow_html=True)
            st.markdown(
                f"<div class='subtle' style='margin-top:10px'>Kategori: <b>{category}</b> • Şikayet: <b>{reports_count}</b></div>",
                unsafe_allow_html=True
            )
            st.markdown(
                f"<div class='subtle'>Son şikayet: <b>{last_reported_at or '-'}</b></div>",
                unsafe_allow_html=True
            )
            card_end()

            # Kategori güncelleme (manuel)
            card_start()
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
                st.toast("✅ Kategori güncellendi", icon="✅")
                st.rerun()
            card_end()

            # Şikayet ekleme (B1 + yeni otomatik kategori davranışı)
            card_start()
            st.markdown("### 🚨 Şikayet ekle")

            rcol1, rcol2 = st.columns(2)
            with rcol1:
                report_type = st.selectbox("Şikayet Türü", REPORT_TYPES, index=0, key="report_type_select")
            with rcol2:
                channel = st.selectbox("Kanal", CHANNELS, index=0, key="channel_select")

            # ✅ Yeni: Şikayetle birlikte kategori seçimi (varsayılan otomatik)
            category_options = ["Otomatik (Tür ile aynı)"] + CATEGORIES
            default_idx = 0
            chosen_category_mode = st.selectbox(
                "Kategori (şikayetle birlikte)",
                category_options,
                index=default_idx,
                help="Varsayılan: seçtiğin şikayet türü kategoriye otomatik yazılır. İstersen farklı seçebilirsin.",
                key="report_category_mode"
            )

            message_excerpt = st.text_area("Açıklama (opsiyonel)", placeholder="Örn: 'Bonus için linke tıkla...'", key="msg")

            if st.button("Şikayeti Kaydet", type="primary"):
                if has_recent_report(_id, hours=24):
                    st.warning("⚠️ Bu numara için son 24 saat içinde zaten şikayet eklenmiş.")
                else:
                    add_report(_id, report_type, channel, message_excerpt)

                    # ✅ İstenen davranış:
                    # - Varsayılan: kategori = şikayet türü
                    # - Kullanıcı farklı kategori seçtiyse onu yaz
                    if chosen_category_mode == "Otomatik (Tür ile aynı)":
                        set_category(_id, report_type)
                        st.info(f"📌 Kategori şikayet türüne göre güncellendi: **{report_type}**")
                    else:
                        set_category(_id, chosen_category_mode)
                        st.info(f"📌 Kategori manuel seçime göre güncellendi: **{chosen_category_mode}**")

                    # (İstersen auto_update_category'yi tamamen kaldırabilirdik,
                    # ama senin senaryonda artık kategori zaten belirleniyor.)
                    # Yine de ekstra kural çalışsın istersen aşağıdaki satırı açabilirsin:
                    # auto_update_category(_id)

                    st.success("Şikayet kaydedildi. Skor güncellendi.")
                    st.toast("✅ Şikayet kaydedildi", icon="✅")
                    st.rerun()
            card_end()

            # Son şikayetler
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


# ======================= TAB: Admin =======================
with tab_admin:
    if not st.session_state.get("is_admin", False):
        card_start()
        st.markdown("### 🔐 Admin girişi")
        st.caption("Liste, dashboard ve CSV sadece admin için açık.")

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
                st.success("Admin girişi başarılı.")
                st.rerun()
            else:
                st.session_state["pin_tries"] += 1
                st.error("Yanlış PIN.")
                if st.session_state["pin_tries"] >= 5:
                    st.warning("Çok fazla deneme yaptın. Bir süre sonra tekrar dene.")
        card_end()

    else:
        top_l, top_r = st.columns([3, 1])
        with top_l:
            st.markdown("### 📊 Admin Panel")
        with top_r:
            if st.button("🚪 Admin çıkış", use_container_width=True):
                st.session_state["is_admin"] = False
                st.rerun()

        # Dashboard (G)
        total_numbers = get_total_numbers()
        total_reports = get_total_reports()
        reports_24h = get_reports_last_hours(24)
        top_cat, top_cat_cnt = get_top_category()
        top_risky = get_top_risky(5)

        c1, c2, c3 = st.columns(3)
        with c1:
            card_start()
            st.markdown("**Toplam numara**")
            st.markdown(f"## {total_numbers}")
            card_end()
        with c2:
            card_start()
            st.markdown("**Toplam şikayet**")
            st.markdown(f"## {total_reports}")
            card_end()
        with c3:
            card_start()
            st.markdown("**Son 24 saat**")
            st.markdown(f"## {reports_24h}")
            card_end()

        card_start()
        st.markdown(f"**En çok şikayet alan tür:** {top_cat}  \n**Adet:** {top_cat_cnt}")
        card_end()

        card_start()
        st.markdown("**En riskli 5 numara**")
        if not top_risky:
            st.info("Henüz kayıt yok.")
        else:
            for _id, phone, cat, last_ts, cnt in top_risky:
                score = min(100, cnt * 15)
                st.markdown(f"- **{phone}** — {cnt} şikayet — {score}/100 — {cat}")
        card_end()

        st.markdown("---")
        st.markdown("### 🔎 Filtreli liste (CSV bu filtrelere göre iner)")

        # Filtreler (C) — CSV indirmeden önce
        q = st.text_input("Telefonla ara", placeholder="örn: 532 veya +90532")
        category_filter = st.selectbox("Kategori filtresi", ["Hepsi"] + CATEGORIES)
        sort_by = st.selectbox(
            "Sıralama",
            ["Şikayet (Azalan)", "Şikayet (Artan)", "Son Şikayet (Yeni)", "Son Şikayet (Eski)"]
        )
        limit = st.slider("Kaç kayıt gösterilsin?", min_value=10, max_value=200, value=50, step=10)

        rows = list_top_numbers(limit=limit, q=q.strip(), category=category_filter, sort_by=sort_by)

        # CSV export (E) — filtreli listeye göre
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

        if not rows:
            st.info("Kriterlere uygun kayıt yok.")
        else:
            for _id, phone, cat, last_ts, cnt in rows:
                score = min(100, cnt * 15)
                card_start()
                st.markdown(f"**{phone}**")
                st.markdown(
                    badge_html(f"{score}/100 • {risk_label(score)}", risk_color(score)),
                    unsafe_allow_html=True
                )
                st.markdown(
                    f"<div class='subtle'>Kategori: <b>{cat}</b> • Şikayet: <b>{cnt}</b> • Son: <b>{last_ts or '-'}</b></div>",
                    unsafe_allow_html=True
                )
                if st.button(f"Bu numarayı aç → {phone}", key=f"open_{_id}"):
                    st.session_state["current_number_id"] = _id
                    st.rerun()
                card_end()
