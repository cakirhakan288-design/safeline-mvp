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
    TR odaklı normalize (hedef çıktı: +905xxxxxxxxx)
    """
    if not p:
        return ""

    s = p.strip()

    # sadece rakamları ve + tut
    s2 = []
    for ch in s:
        if ch.isdigit() or ch == "+":
            s2.append(ch)
    s = "".join(s2)

    # birden fazla + varsa temizle
    if s.count("+") > 1:
        s = "+" + s.replace("+", "")

    # +90xxxx
    if s.startswith("+90"):
        digits = "".join([c for c in s if c.isdigit()])
        return "+" + digits

    # 90xxxx
    if s.startswith("90"):
        digits = "".join([c for c in s if c.isdigit()])
        return "+" + digits

    # 0xxxx
    if s.startswith("0"):
        digits = "".join([c for c in s if c.isdigit()])
        digits = digits[1:]
        return "+90" + digits

    # 10 hane 5xx...
    digits = "".join([c for c in s if c.isdigit()])
    if len(digits) == 10 and digits.startswith("5"):
        return "+90" + digits

    # fallback
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
        (number_id, report_type, channel, message_excerpt or None, now)
    )
    cur.execute("UPDATE numbers SET last_reported_at = ? WHERE id = ?", (now, number_id))
    conn.commit()
    conn.close()


def has_recent_report(number_id: int, hours: int = 24) -> bool:
    """
    B1: aynı numaraya son X saat içinde şikayet var mı?
    """
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
    """
    Normalize + aynı numarayı tek kayda eşleme
    """
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

    # 2) eski kayıtlar içinde normalize ederek eşleşme ara
    cur.execute("SELECT id, phone_number, category, last_reported_at FROM numbers")
    all_rows = cur.fetchall()
    for rid, rphone, rcat, rlast in all_rows:
        if normalize_phone(rphone) == canonical:
            cur.execute("UPDATE numbers SET phone_number = ? WHERE id = ?", (canonical, rid))
            conn.commit()
            conn.close()
            return (rid, canonical, rcat, rlast)

    # 3) yoksa yeni kayıt
    cur.execute(
        "INSERT INTO numbers (phone_number, category, last_reported_at) VALUES (?, ?, ?)",
        (canonical, "Bilinmiyor", None)
    )
    conn.commit()
    cur.execute("SELECT id, phone_number, category, last_reported_at FROM numbers WHERE phone_number = ?", (canonical,))
    row = cur.fetchone()
    conn.close()
    return row


# -------------------- Auto category (A) + Notification (D) --------------------
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
    """
    row = get_number(number_id)
    if not row:
        return None

    _, _, current_category, _ = row

    # "Güvenli" otomatik bozulmasın (manuel karar)
    if current_category == "Güvenli":
        return None

    counts = get_type_counts(number_id)
    total_reports, _score = get_stats(number_id)
    new_cat = decide_auto_category(counts, total_reports)

    if new_cat != current_category:
        set_category(number_id, new_cat)
        return new_cat

    return None


# -------------------- Admin list (C) --------------------
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


# -------------------- Dashboard (G) --------------------
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


def get_top_category() -> tuple
