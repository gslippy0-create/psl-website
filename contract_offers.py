
from datetime import date
from functools import wraps
from flask import request, session, redirect, url_for, render_template_string
import sqlite3

from app import app, db

def _ensure_offer_table():
    c = db()
    c.execute("""
        CREATE TABLE IF NOT EXISTS contract_offers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER NOT NULL,
            team_id INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            duration_months INTEGER NOT NULL,
            fee REAL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            responded_at TEXT,
            offered_by_user_id INTEGER
        )
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_contract_offers_player
        ON contract_offers(player_id, status)
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_contract_offers_team
        ON contract_offers(team_id, status)
    """)
    c.commit()
    c.close()

def _is_admin():
    return bool(session.get("admin") or session.get("is_admin"))

def _current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    c = db()
    user = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    c.close()
    return user

def _manager_team():
    user = _current_user()
    if not user:
        return None, None
    username = (user["username"] or "").strip()
    c = db()
    team = c.execute(
        "SELECT * FROM teams WHERE lower(trim(manager))=lower(trim(?)) LIMIT 1",
        (username,)
    ).fetchone()
    if not team and user["team_id"]:
        team = c.execute(
            "SELECT * FROM teams WHERE id=? LIMIT 1", (user["team_id"],)
        ).fetchone()
    c.close()
    return user, team

def _login_redirect():
    return redirect(url_for("login", next=request.path))

def _manager_or_admin_team():
    if _is_admin():
        return None, None
    return _manager_team()

def _months_end(start_text, months):
    y, m, d = [int(x) for x in start_text.split("-")]
    # Month arithmetic without external dependencies.
    total = (m - 1) + int(months)
    ny = y + total // 12
    nm = total % 12 + 1
    # Clamp day to target month.
    import calendar
    nd = min(d, calendar.monthrange(ny, nm)[1])
    return f"{ny:04d}-{nm:02d}-{nd:02d}"

def _contract_columns(c):
    try:
        return {row[1] for row in c.execute("PRAGMA table_info(contracts)").fetchall()}
    except Exception:
        return set()

def _create_active_contract(c, player_id, team_id, start_date, end_date, fee):
    cols = _contract_columns(c)
    values = {
        "player_id": player_id,
        "team_id": team_id,
        "start_date": start_date,
        "end_date": end_date,
        "status": "active",
        "fee": fee,
        "created_at": "CURRENT_TIMESTAMP",
    }
    usable = [k for k in values if k in cols]
    if not usable:
        raise RuntimeError("The contracts table exists but its columns could not be recognised.")
    placeholders = []
    params = []
    for k in usable:
        if k == "created_at":
            placeholders.append("CURRENT_TIMESTAMP")
        else:
            placeholders.append("?")
            params.append(values[k])
    c.execute(
        f"INSERT INTO contracts ({','.join(usable)}) VALUES ({','.join(placeholders)})",
        params
    )

def _player_user_id(c, player_id):
    row = c.execute(
        "SELECT id FROM users WHERE player_id=? LIMIT 1", (player_id,)
    ).fetchone()
    return row["id"] if row else None

BASE = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ title }} | PSL</title>
<link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
<style>
.contract-wrap{max-width:1100px;margin:auto}
.offer-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px}
.offer-card{padding:20px;border:1px solid #333;border-radius:12px;background:rgba(255,255,255,.03)}
.offer-card h3{margin-top:0}.muted{opacity:.7}.success{color:#61d095}.error{color:#ff7272}
.form-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
.form-grid label{display:block}.form-grid input,.form-grid select{width:100%;box-sizing:border-box}
.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}
a.button,button{display:inline-block;padding:10px 14px;border-radius:8px;text-decoration:none;cursor:pointer}
</style>
</head>
<body>
<header class="nav">
<a class="brand" href="/"><span>PSL</span></a>
<nav>
<a href="/">Home</a><a href="/table">League</a><a href="/fixtures">Fixtures</a>
<a href="/teams">Teams</a><a href="/players">Players</a><a href="/transfers">Transfers</a>
<a href="/totw">TOTW</a><a href="/contracts">Contracts</a>
{% if session.get('user_id') or session.get('admin') or session.get('is_admin') %}
<a href="/contract-offers">Offers</a><a href="/logout">Logout</a>
{% else %}<a href="/login">Login</a>{% endif %}
</nav>
</header>
<main><div class="contract-wrap">{{ body|safe }}</div></main>
<footer>PSL • FC27 Pro Clubs League</footer>
</body>
</html>
"""

def _page(title, body):
    return render_template_string(BASE, title=title, body=body)

_ensure_offer_table()

@app.route("/manager/contracts/offers", methods=["GET", "POST"])
def manager_contract_offers():
    _ensure_offer_table()
    if _is_admin():
        return redirect(url_for("admin_contract_offer"))
    user, team = _manager_team()
    if not user:
        return _login_redirect()
    if not team:
        return _page("Manager Contract Offers",
            "<div class='offer-card'><h1>No manager team found</h1>"
            "<p>Your website username must match the team's Manager name, or your account must be linked to that team.</p></div>"), 403

    c = db()
    message = ""
    error = ""
    if request.method == "POST":
        try:
            player_id = int(request.form.get("player_id", "0"))
            duration = int(request.form.get("duration_months", "0"))
            start = request.form.get("start_date", "").strip()
            fee = float(request.form.get("fee", "0") or 0)
            if duration not in (1,3,6,12):
                raise ValueError("Choose 1, 3, 6 or 12 months.")
            date.fromisoformat(start)
            end = _months_end(start, duration)
            player = c.execute("SELECT * FROM players WHERE id=? AND team_id IS NULL", (player_id,)).fetchone()
            if not player:
                raise ValueError("That player is no longer a Free Agent.")
            c.execute("""
                INSERT INTO contract_offers
                (player_id,team_id,start_date,end_date,duration_months,fee,status,offered_by_user_id)
                VALUES (?,?,?,?,?,?, 'pending', ?)
            """, (player_id,team["id"],start,end,duration,fee,user["id"]))
            c.commit()
            message = "Contract offer sent."
        except Exception as e:
            c.rollback()
            error = str(e)

    free_agents = c.execute("""
        SELECT id,name,position FROM players
        WHERE team_id IS NULL
        ORDER BY name
    """).fetchall()
    offers = c.execute("""
        SELECT o.*,p.name player_name,p.position,t.name team_name
        FROM contract_offers o
        JOIN players p ON p.id=o.player_id
        JOIN teams t ON t.id=o.team_id
        WHERE o.team_id=? AND o.status='pending'
        ORDER BY o.created_at DESC
    """, (team["id"],)).fetchall()
    c.close()

    options = "".join(
        f"<option value='{p['id']}'>{p['name']} ({p['position'] or 'N/A'})</option>"
        for p in free_agents
    )
    rows = "".join(
        f"<div class='offer-card'><h3>{o['player_name']}</h3>"
        f"<p>{o['duration_months']} months • £{o['fee']:.2f} • {o['start_date']} → {o['end_date']}</p>"
        f"<p class='muted'>Status: {o['status']}</p></div>"
        for o in offers
    ) or "<p class='muted'>No pending offers from your team.</p>"

    body = f"""
    <h1>Offer Contract</h1>
    <p>Team: <strong>{team['name']}</strong></p>
    <form method='post' class='offer-card'>
      <div class='form-grid'>
        <label>Free Agent<select name='player_id' required>{options}</select></label>
        <label>Length<select name='duration_months' required>
          <option value='1'>1 month</option><option value='3'>3 months</option>
          <option value='6'>6 months</option><option value='12'>12 months</option>
        </select></label>
        <label>Start date<input type='date' name='start_date' value='{date.today().isoformat()}' required></label>
        <label>Transfer fee<input type='number' name='fee' value='0' min='0' step='0.01'></label>
      </div>
      <div class='actions'><button type='submit'>Send Contract Offer</button></div>
      {f"<p class='success'>{message}</p>" if message else ""}
      {f"<p class='error'>{error}</p>" if error else ""}
    </form>
    <h2>Pending Offers</h2><div class='offer-grid'>{rows}</div>
    """
    return _page("Manager Contract Offers", body)

@app.route("/admin/contracts/offers", methods=["GET", "POST"])
def admin_contract_offer():
    if not _is_admin():
        return _login_redirect()
    _ensure_offer_table()
    c = db()
    message = ""
    error = ""
    if request.method == "POST":
        try:
            team_id = int(request.form.get("team_id", "0"))
            player_id = int(request.form.get("player_id", "0"))
            duration = int(request.form.get("duration_months", "0"))
            start = request.form.get("start_date", "").strip()
            fee = float(request.form.get("fee", "0") or 0)
            if duration not in (1,3,6,12):
                raise ValueError("Choose 1, 3, 6 or 12 months.")
            date.fromisoformat(start)
            end = _months_end(start, duration)
            player = c.execute("SELECT * FROM players WHERE id=? AND team_id IS NULL", (player_id,)).fetchone()
            team = c.execute("SELECT * FROM teams WHERE id=?", (team_id,)).fetchone()
            if not player or not team:
                raise ValueError("Player or team not found.")
            c.execute("""
                INSERT INTO contract_offers
                (player_id,team_id,start_date,end_date,duration_months,fee,status,offered_by_user_id)
                VALUES (?,?,?,?,?,?, 'pending', NULL)
            """, (player_id,team_id,start,end,duration,fee))
            c.commit()
            message = "Contract offer sent."
        except Exception as e:
            c.rollback()
            error = str(e)

    players = c.execute("""
        SELECT id,name,position FROM players WHERE team_id IS NULL ORDER BY name
    """).fetchall()
    teams = c.execute("SELECT id,name FROM teams ORDER BY name").fetchall()
    offers = c.execute("""
        SELECT o.*,p.name player_name,t.name team_name
        FROM contract_offers o
        JOIN players p ON p.id=o.player_id JOIN teams t ON t.id=o.team_id
        WHERE o.status='pending' ORDER BY o.created_at DESC
    """).fetchall()
    c.close()

    p_opts = "".join(f"<option value='{p['id']}'>{p['name']} ({p['position'] or 'N/A'})</option>" for p in players)
    t_opts = "".join(f"<option value='{t['id']}'>{t['name']}</option>" for t in teams)
    rows = "".join(
        f"<div class='offer-card'><h3>{o['player_name']}</h3><p>Offer from {o['team_name']}</p>"
        f"<p>{o['duration_months']} months • £{o['fee']:.2f} • {o['start_date']} → {o['end_date']}</p></div>"
        for o in offers
    ) or "<p class='muted'>No pending offers.</p>"
    body = f"""
    <h1>Admin Contract Offers</h1>
    <form method='post' class='offer-card'>
      <div class='form-grid'>
        <label>Free Agent<select name='player_id' required>{p_opts}</select></label>
        <label>Team<select name='team_id' required>{t_opts}</select></label>
        <label>Length<select name='duration_months' required>
          <option value='1'>1 month</option><option value='3'>3 months</option>
          <option value='6'>6 months</option><option value='12'>12 months</option>
        </select></label>
        <label>Start date<input type='date' name='start_date' value='{date.today().isoformat()}' required></label>
        <label>Transfer fee<input type='number' name='fee' value='0' min='0' step='0.01'></label>
      </div>
      <div class='actions'><button type='submit'>Send Contract Offer</button></div>
      {f"<p class='success'>{message}</p>" if message else ""}
      {f"<p class='error'>{error}</p>" if error else ""}
    </form>
    <h2>All Pending Offers</h2><div class='offer-grid'>{rows}</div>
    """
    return _page("Admin Contract Offers", body)

@app.route("/contract-offers", methods=["GET"])
def player_contract_offers():
    if not session.get("user_id"):
        return _login_redirect()
    _ensure_offer_table()
    user = _current_user()
    if not user or not user["player_id"]:
        return _page("Contract Offers",
            "<div class='offer-card'><h1>No player profile linked</h1>"
            "<p>Your PSL account does not have a player profile yet.</p></div>"), 403

    c = db()
    offers = c.execute("""
        SELECT o.*,t.name team_name,p.name player_name
        FROM contract_offers o
        JOIN teams t ON t.id=o.team_id
        JOIN players p ON p.id=o.player_id
        WHERE o.player_id=? AND o.status='pending'
        ORDER BY o.created_at DESC
    """, (user["player_id"],)).fetchall()
    c.close()

    if not offers:
        body = "<div class='offer-card'><h1>Contract Offers</h1><p class='muted'>You have no pending contract offers.</p></div>"
        return _page("Contract Offers", body)

    cards = []
    for o in offers:
        cards.append(f"""
        <div class='offer-card'>
          <h2>{o['team_name']}</h2>
          <p><strong>{o['duration_months']} months</strong> • £{o['fee']:.2f}</p>
          <p>{o['start_date']} → {o['end_date']}</p>
          <div class='actions'>
            <form method='post' action='/contract-offers/{o["id"]}/accept'><button type='submit'>Accept Offer</button></form>
            <form method='post' action='/contract-offers/{o["id"]}/reject'><button type='submit'>Reject Offer</button></form>
          </div>
        </div>
        """)
    return _page("Contract Offers", "<h1>Contract Offers</h1><div class='offer-grid'>" + "".join(cards) + "</div>")

@app.route("/contract-offers/<int:offer_id>/reject", methods=["POST"])
def reject_contract_offer(offer_id):
    if not session.get("user_id"):
        return _login_redirect()
    _ensure_offer_table()
    user = _current_user()
    if not user or not user["player_id"]:
        return "Your account has no player profile linked.", 403
    c = db()
    offer = c.execute(
        "SELECT * FROM contract_offers WHERE id=? AND player_id=? AND status='pending'",
        (offer_id, user["player_id"])
    ).fetchone()
    if not offer:
        c.close()
        return "Offer not found.", 404
    c.execute(
        "UPDATE contract_offers SET status='rejected',responded_at=CURRENT_TIMESTAMP WHERE id=?",
        (offer_id,)
    )
    c.commit()
    c.close()
    return redirect(url_for("player_contract_offers"))

@app.route("/contract-offers/<int:offer_id>/accept", methods=["POST"])
def accept_contract_offer(offer_id):
    if not session.get("user_id"):
        return _login_redirect()
    _ensure_offer_table()
    user = _current_user()
    if not user or not user["player_id"]:
        return "Your account has no player profile linked.", 403

    c = db()
    try:
        c.execute("BEGIN IMMEDIATE")
        offer = c.execute("""
            SELECT o.*,p.team_id player_team_id,t.name team_name
            FROM contract_offers o
            JOIN players p ON p.id=o.player_id
            JOIN teams t ON t.id=o.team_id
            WHERE o.id=? AND o.player_id=? AND o.status='pending'
        """, (offer_id, user["player_id"])).fetchone()
        if not offer:
            raise ValueError("Offer not found or already responded to.")
        if offer["player_team_id"] is not None:
            raise ValueError("You are already assigned to a team.")
        # Only one active contract is permitted.
        cols = _contract_columns(c)
        if cols:
            active = c.execute(
                "SELECT 1 FROM contracts WHERE player_id=? AND status='active' LIMIT 1",
                (offer["player_id"],)
            ).fetchone()
            if active:
                raise ValueError("You already have an active contract.")
        _create_active_contract(
            c, offer["player_id"], offer["team_id"],
            offer["start_date"], offer["end_date"], offer["fee"]
        )
        c.execute(
            "UPDATE players SET team_id=? WHERE id=?",
            (offer["team_id"], offer["player_id"])
        )
        c.execute(
            "INSERT INTO transfers(player_id,from_team,to_team) VALUES(?,?,?)",
            (offer["player_id"], "Free Agent", offer["team_name"])
        )
        c.execute(
            "UPDATE contract_offers SET status='accepted',responded_at=CURRENT_TIMESTAMP WHERE id=?",
            (offer_id,)
        )
        c.execute("""
            UPDATE contract_offers
            SET status='rejected',responded_at=CURRENT_TIMESTAMP
            WHERE player_id=? AND status='pending' AND id<>?
        """, (offer["player_id"], offer_id))
        c.commit()
    except Exception as e:
        c.rollback()
        c.close()
        return _page("Contract Offer Error", f"<div class='offer-card'><h1>Could not accept offer</h1><p class='error'>{e}</p><p><a href='/contract-offers'>Back to offers</a></p></div>"), 400
    c.close()
    return redirect(url_for("player_contract_offers"))

@app.route("/admin/contracts/offers/reject/<int:offer_id>", methods=["POST"])
def admin_reject_contract_offer(offer_id):
    if not _is_admin():
        return _login_redirect()
    _ensure_offer_table()
    c = db()
    c.execute("UPDATE contract_offers SET status='rejected',responded_at=CURRENT_TIMESTAMP WHERE id=? AND status='pending'", (offer_id,))
    c.commit()
    c.close()
    return redirect(url_for("admin_contract_offer"))
