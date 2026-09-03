# -*- coding: utf-8 -*-
"""
ArdFx Panel — Tüm Botların İşlemlerini Tek Yerden Takip Etme (Bulut Sürümü)
=============================================================================
Bu sürüm, Render.com gibi bir bulut sunucuda 7/24 çalışacak ve verilerini
Supabase (ücretsiz Postgres veritabanı) üzerinde KALICI olarak saklayacak
şekilde hazırlandı - artık yerel SQLite kullanmıyor.

Yerel bilgisayarda TEST etmek için:
    pip install -r requirements.txt
    set DATABASE_URL=postgresql://postgres.xxxxx:SIFREN@aws-0-xxxxx.pooler.supabase.com:5432/postgres
    python ardfx_dashboard.py

Render'a deploy ederken DATABASE_URL, Render panelinde "Environment
Variable" olarak (gizli) girilecek - koda hiç yazılmıyor.
"""

import os
import psycopg2
import psycopg2.extras
from datetime import datetime
from flask import Flask, request, jsonify, Response

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "")


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    if not DATABASE_URL:
        print("UYARI: DATABASE_URL ayarlanmamış, veritabanına bağlanılamıyor.")
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id SERIAL PRIMARY KEY,
            bot_name TEXT,
            ticket TEXT,
            symbol TEXT,
            action TEXT,
            lot REAL,
            open_price REAL,
            sl REAL,
            tp REAL,
            open_time TEXT,
            status TEXT DEFAULT 'AÇIK',
            close_price REAL,
            profit REAL,
            close_reason TEXT,
            close_time TEXT,
            kaynak TEXT
        )
    """)
    conn.commit()
    cur.close()
    conn.close()


# ❗ DÜZELTİLDİ: Bu çağrı eskiden sadece "if __name__ == '__main__':" içindeydi.
# Render'da uygulamayı GUNICORN başlatıyor (Start Command: gunicorn
# ardfx_dashboard:app) - gunicorn dosyayı DOĞRUDAN ÇALIŞTIRMAZ, sadece "app"
# nesnesini İÇİNDEN ALIR - bu yüzden __main__ bloğu hiç tetiklenmiyordu ve
# tablo bir kere bile oluşturulmamıştı. Şimdi modül YÜKLENİR YÜKLENMEZ
# (hem "python ardfx_dashboard.py" ile hem gunicorn ile) çalışacak.
init_db()


@app.route("/api/trade_open", methods=["POST"])
def trade_open():
    data = request.get_json(force=True)
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO trades (bot_name, ticket, symbol, action, lot, open_price, sl, tp, open_time, status, kaynak)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'AÇIK', %s)""",
            (
                data.get("bot_name", "Bilinmiyor"),
                str(data.get("ticket", "")),
                data.get("symbol", ""),
                data.get("action", ""),
                data.get("lot", 0),
                data.get("open_price", 0),
                data.get("sl", 0),
                data.get("tp", 0),
                datetime.now().isoformat(timespec="seconds"),
                data.get("kaynak", ""),
            ),
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()  # ❗ hata olsa bile bağlantı MUTLAKA kapatılır - havuz sızıntısını önler
    return jsonify({"status": "ok"})


@app.route("/api/trade_close", methods=["POST"])
def trade_close():
    data = request.get_json(force=True)
    ticket = str(data.get("ticket", ""))
    bot_name = data.get("bot_name", "Bilinmiyor")
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """UPDATE trades SET status=%s, close_price=%s, profit=%s, close_reason=%s, close_time=%s
               WHERE ticket=%s AND bot_name=%s AND status='AÇIK'""",
            (
                data.get("close_reason", "KAPANDI"),
                data.get("close_price", 0),
                data.get("profit", 0),
                data.get("close_reason", ""),
                datetime.now().isoformat(timespec="seconds"),
                ticket,
                bot_name,
            ),
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()
    return jsonify({"status": "ok"})


@app.route("/api/trades", methods=["GET"])
def api_trades():
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 300")
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/trades/<int:trade_id>", methods=["DELETE"])
def delete_trade(trade_id):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM trades WHERE id=%s", (trade_id,))
        conn.commit()
        cur.close()
    finally:
        conn.close()
    return jsonify({"status": "ok"})


@app.route("/", methods=["GET"])
def dashboard():
    html = """
<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ArdFx Panel</title>
<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="#0f1117">
<style>
    body { background:#0f1117; color:#e6e6e6; font-family: Segoe UI, Arial, sans-serif; margin:0; padding:20px; }
    h1 { color:#4da3ff; }
    .stats { display:flex; gap:20px; margin-bottom:20px; flex-wrap:wrap; }
    .stat-box { background:#1a1d29; border-radius:8px; padding:14px 20px; min-width:140px; }
    .stat-box .label { color:#999; font-size:12px; }
    .stat-box .value { font-size:22px; font-weight:bold; }
    .green { color:#2ecc71; }
    .red { color:#e74c3c; }
    .blue { color:#4da3ff; }
    table { width:100%; border-collapse: collapse; background:#1a1d29; border-radius:8px; overflow:hidden; }
    th, td { padding:8px 12px; text-align:left; border-bottom:1px solid #2a2e3d; font-size:13px; }
    th { background:#22263a; color:#4da3ff; position:sticky; top:0; }
    tr:hover { background:#22263a; }
    .badge { padding:2px 8px; border-radius:10px; font-size:11px; font-weight:bold; }
    .badge-open { background:#2d3a5c; color:#4da3ff; }
    .badge-tp { background:#1e4d2b; color:#2ecc71; }
    .badge-sl { background:#4d1e1e; color:#e74c3c; }
    .badge-other { background:#3a3a3a; color:#ccc; }
    select, input { background:#1a1d29; color:#e6e6e6; border:1px solid #2a2e3d; border-radius:4px; padding:6px; margin-right:10px; }
    .tablewrap { overflow-x:auto; }
    th.sortable { cursor:pointer; user-select:none; }
    th.sortable:hover { color:#7cb8ff; }
    .sort-arrow { font-size:10px; margin-left:4px; opacity:0.6; }
    .del-btn { background:none; border:none; color:#e74c3c; cursor:pointer; font-size:15px; font-weight:bold; padding:0 6px; }
    .del-btn:hover { color:#ff6b6b; }
    .filter-row { display:flex; align-items:center; gap:6px; flex-wrap:wrap; }
    .filter-row label { font-size:12px; color:#999; }
</style>
</head>
<body>
    <h1>ArdFx Panel</h1>
    <div class="stats" id="stats"></div>
    <div class="filter-row">
        <select id="botFilter"><option value="">Tum Botlar</option></select>
        <select id="statusFilter">
            <option value="">Tum Durumlar</option>
            <option value="ACIK">Acik</option>
            <option value="TP">TP</option>
            <option value="SL">SL</option>
        </select>
        <input type="text" id="symbolFilter" placeholder="Sembol ara...">
        <label>Baslangic:</label>
        <input type="date" id="dateFrom">
        <label>Bitis:</label>
        <input type="date" id="dateTo">
        <button id="clearDates" style="padding:6px 10px; background:#2a2e3d; color:#e6e6e6; border:1px solid #3a3e4d; border-radius:4px; cursor:pointer;">Tarihi Temizle</button>
    </div>
    <br>
    <div class="tablewrap">
    <table id="tradesTable">
        <thead>
            <tr>
                <th></th>
                <th class="sortable" data-col="bot_name">Bot<span class="sort-arrow" id="arrow-bot_name"></span></th>
                <th class="sortable" data-col="kaynak">Kaynak<span class="sort-arrow" id="arrow-kaynak"></span></th>
                <th class="sortable" data-col="symbol">Sembol<span class="sort-arrow" id="arrow-symbol"></span></th>
                <th class="sortable" data-col="action">Yon<span class="sort-arrow" id="arrow-action"></span></th>
                <th class="sortable" data-col="lot">Lot<span class="sort-arrow" id="arrow-lot"></span></th>
                <th>Acilis</th><th>SL</th><th>TP</th><th>Durum</th><th>Kapanis Fiyati</th>
                <th>Kar/Zarar</th><th>Acilis Zamani</th><th>Kapanis Zamani</th>
            </tr>
        </thead>
        <tbody id="tradesBody"></tbody>
    </table>
    </div>

<script>
let allTrades = [];
let sortCol = null;
let sortDir = 1; // 1 = artan, -1 = azalan

function badgeClass(status) {
    if (status === 'ACIK' || status === 'AÇIK') return 'badge-open';
    if (status.includes('TP')) return 'badge-tp';
    if (status.includes('SL')) return 'badge-sl';
    return 'badge-other';
}

async function deleteTrade(id) {
    if (!confirm('Bu kaydı silmek istediğine emin misin?')) return;
    await fetch('/api/trades/' + id, { method: 'DELETE' });
    allTrades = allTrades.filter(t => t.id !== id);
    render();
}

function updateSortArrows() {
    document.querySelectorAll('.sort-arrow').forEach(el => el.textContent = '');
    if (sortCol) {
        const el = document.getElementById('arrow-' + sortCol);
        if (el) el.textContent = sortDir === 1 ? '▲' : '▼';
    }
}

function render() {
    const botFilter = document.getElementById('botFilter').value;
    const statusFilter = document.getElementById('statusFilter').value;
    const symbolFilter = document.getElementById('symbolFilter').value.toUpperCase();
    const dateFrom = document.getElementById('dateFrom').value;
    const dateTo = document.getElementById('dateTo').value;

    let filtered = allTrades.filter(t => {
        if (botFilter && t.bot_name !== botFilter) return false;
        if (statusFilter && !(t.status || '').includes(statusFilter)) return false;
        if (symbolFilter && !(t.symbol || '').toUpperCase().includes(symbolFilter)) return false;
        if (dateFrom || dateTo) {
            const openDate = (t.open_time || '').substring(0, 10); // YYYY-MM-DD
            if (dateFrom && openDate < dateFrom) return false;
            if (dateTo && openDate > dateTo) return false;
        }
        return true;
    });

    if (sortCol) {
        filtered = filtered.slice().sort((a, b) => {
            let va = a[sortCol], vb = b[sortCol];
            if (typeof va === 'string') va = va.toUpperCase();
            if (typeof vb === 'string') vb = vb.toUpperCase();
            if (va === null || va === undefined) va = '';
            if (vb === null || vb === undefined) vb = '';
            if (va < vb) return -1 * sortDir;
            if (va > vb) return 1 * sortDir;
            return 0;
        });
    }
    updateSortArrows();

    let totalProfit = 0, openCount = 0, tpCount = 0, slCount = 0;
    filtered.forEach(t => {
        totalProfit += t.profit || 0;
        if ((t.status || '').includes('AÇIK') || (t.status || '') === 'ACIK') openCount++;
        if (t.status && t.status.includes('TP')) tpCount++;
        if (t.status && t.status.includes('SL')) slCount++;
    });

    document.getElementById('stats').innerHTML =
        '<div class="stat-box"><div class="label">Toplam Islem</div><div class="value blue">' + filtered.length + '</div></div>' +
        '<div class="stat-box"><div class="label">Acik Pozisyon</div><div class="value blue">' + openCount + '</div></div>' +
        '<div class="stat-box"><div class="label">TP Sayisi</div><div class="value green">' + tpCount + '</div></div>' +
        '<div class="stat-box"><div class="label">SL Sayisi</div><div class="value red">' + slCount + '</div></div>' +
        '<div class="stat-box"><div class="label">Toplam Kar/Zarar</div><div class="value ' + (totalProfit >= 0 ? 'green' : 'red') + '">' + totalProfit.toFixed(2) + '</div></div>';

    const tbody = document.getElementById('tradesBody');
    tbody.innerHTML = filtered.map(function(t) {
        return '<tr>' +
            '<td><button class="del-btn" onclick="deleteTrade(' + t.id + ')" title="Sil">✕</button></td>' +
            '<td>' + (t.bot_name || '-') + '</td>' +
            '<td>' + (t.kaynak || '-') + '</td>' +
            '<td>' + (t.symbol || '-') + '</td>' +
            '<td>' + (t.action || '-') + '</td>' +
            '<td>' + (t.lot || '-') + '</td>' +
            '<td>' + (t.open_price || 0).toFixed(5) + '</td>' +
            '<td>' + (t.sl || 0).toFixed(5) + '</td>' +
            '<td>' + (t.tp || 0).toFixed(5) + '</td>' +
            '<td><span class="badge ' + badgeClass(t.status || '') + '">' + (t.status || '-') + '</span></td>' +
            '<td>' + (t.close_price ? t.close_price.toFixed(5) : '-') + '</td>' +
            '<td class="' + ((t.profit || 0) >= 0 ? 'green' : 'red') + '">' + (t.profit !== null && t.profit !== undefined ? t.profit.toFixed(2) : '-') + '</td>' +
            '<td>' + (t.open_time || '-') + '</td>' +
            '<td>' + (t.close_time || '-') + '</td>' +
            '</tr>';
    }).join('');
}

function updateBotFilterOptions() {
    const sel = document.getElementById('botFilter');
    const current = sel.value;
    const bots = [...new Set(allTrades.map(function(t) { return t.bot_name; }))].filter(Boolean);
    sel.innerHTML = '<option value="">Tum Botlar</option>' + bots.map(function(b) { return '<option value="' + b + '">' + b + '</option>'; }).join('');
    sel.value = current;
}

async function fetchTrades() {
    const res = await fetch('/api/trades');
    allTrades = await res.json();
    updateBotFilterOptions();
    render();
}

document.getElementById('botFilter').addEventListener('change', render);
document.getElementById('statusFilter').addEventListener('change', render);
document.getElementById('symbolFilter').addEventListener('input', render);
document.getElementById('dateFrom').addEventListener('change', render);
document.getElementById('dateTo').addEventListener('change', render);
document.getElementById('clearDates').addEventListener('click', function() {
    document.getElementById('dateFrom').value = '';
    document.getElementById('dateTo').value = '';
    render();
});

document.querySelectorAll('th.sortable').forEach(function(th) {
    th.addEventListener('click', function() {
        const col = th.getAttribute('data-col');
        if (sortCol === col) {
            sortDir *= -1;
        } else {
            sortCol = col;
            sortDir = 1;
        }
        render();
    });
});

fetchTrades();
setInterval(fetchTrades, 10000);

if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(function(){});
}
</script>
</body>
</html>
"""
    return Response(html, mimetype="text/html")


@app.route("/manifest.json")
def manifest():
    data = {
        "name": "ArdFx Panel",
        "short_name": "ArdFx",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0f1117",
        "theme_color": "#0f1117",
        "icons": [
            {"src": "https://cdn-icons-png.flaticon.com/512/2331/2331941.png", "sizes": "512x512", "type": "image/png"}
        ]
    }
    return jsonify(data)


@app.route("/sw.js")
def service_worker():
    js = "self.addEventListener('fetch', function(e) {});"
    return Response(js, mimetype="application/javascript")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 9090))
    print(f"ArdFx Panel basliyor... port {port}")
    app.run(host="0.0.0.0", port=port)
