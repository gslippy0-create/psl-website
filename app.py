import os, sqlite3
from functools import wraps
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, abort
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
load_dotenv()
from discord_oauth import discord_login, discord_callback

app = Flask(__name__)
app.secret_key = os.getenv("PSL_SECRET_KEY", "change-this-secret-key")
DB = Path("psl.db")
ADMIN_USER = os.getenv("PSL_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("PSL_ADMIN_PASSWORD", "changeme")
API_KEY = os.getenv("PSL_API_KEY", "change-api-key")

def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c

def init_db():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS teams (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL UNIQUE, manager TEXT DEFAULT '', logo TEXT DEFAULT '', discord_id TEXT
    );
    CREATE TABLE IF NOT EXISTS players (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL, position TEXT DEFAULT '', team_id INTEGER,
      appearances INTEGER DEFAULT 0, goals INTEGER DEFAULT 0, assists INTEGER DEFAULT 0,
      FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE SET NULL
    );
    CREATE TABLE IF NOT EXISTS fixtures (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      home_id INTEGER NOT NULL, away_id INTEGER NOT NULL,
      scheduled TEXT DEFAULT '', status TEXT DEFAULT 'scheduled',
      home_score INTEGER, away_score INTEGER,
      round_no INTEGER DEFAULT NULL,
      FOREIGN KEY(home_id) REFERENCES teams(id), FOREIGN KEY(away_id) REFERENCES teams(id)
    );
    CREATE TABLE IF NOT EXISTS transfers (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      player_id INTEGER NOT NULL, from_team TEXT DEFAULT 'Free Agent',
      to_team TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(player_id) REFERENCES players(id)
    );
    CREATE TABLE IF NOT EXISTS totw (
      id INTEGER PRIMARY KEY AUTOINCREMENT, week TEXT NOT NULL,
      player_id INTEGER NOT NULL, position TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(player_id) REFERENCES players(id)
    );
    """)
    # Upgrade databases created by older PSL versions.
    cols = {r[1] for r in c.execute("PRAGMA table_info(fixtures)").fetchall()}
    player_cols = {r[1] for r in c.execute("PRAGMA table_info(players)").fetchall()}
    if "discord_id" not in player_cols:
        c.execute("ALTER TABLE players ADD COLUMN discord_id TEXT")
    team_cols = {r[1] for r in c.execute("PRAGMA table_info(teams)").fetchall()}
    if "discord_id" not in team_cols:
        c.execute("ALTER TABLE teams ADD COLUMN discord_id TEXT")
    if "round_no" not in cols:
        c.execute("ALTER TABLE fixtures ADD COLUMN round_no INTEGER DEFAULT NULL")

    team_cols = {r[1] for r in c.execute("PRAGMA table_info(teams)").fetchall()}
    if "discord_id" not in team_cols:
        c.execute("ALTER TABLE teams ADD COLUMN discord_id TEXT")

    c.commit(); c.close()

def admin_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("admin"):
            return redirect(url_for("login", next=request.path))
        return fn(*a, **kw)
    return wrapper

def standings():
    c = db()
    teams = c.execute("SELECT * FROM teams ORDER BY name").fetchall()
    out = {t["id"]: dict(team=t["name"], played=0,wins=0,draws=0,losses=0,gf=0,ga=0,gd=0,points=0) for t in teams}
    for r in c.execute("SELECT * FROM fixtures WHERE status='played'").fetchall():
        h,a=out[r["home_id"]],out[r["away_id"]]
        hs,as_=r["home_score"],r["away_score"]
        h["played"]+=1;a["played"]+=1;h["gf"]+=hs;h["ga"]+=as_;a["gf"]+=as_;a["ga"]+=hs
        if hs>as_: h["wins"]+=1;h["points"]+=3;a["losses"]+=1
        elif hs<as_: a["wins"]+=1;a["points"]+=3;h["losses"]+=1
        else: h["draws"]+=1;a["draws"]+=1;h["points"]+=1;a["points"]+=1
    for x in out.values(): x["gd"]=x["gf"]-x["ga"]
    c.close()
    return sorted(out.values(), key=lambda x:(-x["points"],-x["gd"],-x["gf"],x["team"]))

@app.context_processor
def globals_():
    return {
        "logged_in": bool(session.get("admin")),
        "discord_logged_in": bool(session.get("discord_id")),
    }

@app.route("/")
def home():
    c=db()
    recent=c.execute("""SELECT f.*,h.name home,a.name away FROM fixtures f
      JOIN teams h ON h.id=f.home_id JOIN teams a ON a.id=f.away_id
      WHERE f.status='played' ORDER BY f.id DESC LIMIT 5""").fetchall()
    upcoming=c.execute("""SELECT f.*,h.name home,a.name away FROM fixtures f
      JOIN teams h ON h.id=f.home_id JOIN teams a ON a.id=f.away_id
      WHERE f.status='scheduled' ORDER BY f.scheduled,f.id LIMIT 5""").fetchall()
    top=c.execute("""SELECT p.*,COALESCE(t.name,'Free Agent') team FROM players p
      LEFT JOIN teams t ON t.id=p.team_id ORDER BY p.goals DESC,p.assists DESC LIMIT 5""").fetchall()
    counts=[c.execute("SELECT COUNT(*) n FROM teams").fetchone()["n"],
            c.execute("SELECT COUNT(*) n FROM players").fetchone()["n"],
            c.execute("SELECT COUNT(*) n FROM fixtures WHERE status='played'").fetchone()["n"]]
    c.close()
    return render_template("home.html",table=standings()[:6],recent=recent,upcoming=upcoming,top=top,counts=counts)

@app.route("/table")
def table(): return render_template("table.html", table=standings())

@app.route("/teams")
def teams():
    c=db(); rows=c.execute("SELECT * FROM teams ORDER BY name").fetchall(); c.close()
    return render_template("teams.html",teams=rows)

@app.route("/team/<int:team_id>")
def team(team_id):
    c=db(); t=c.execute("SELECT * FROM teams WHERE id=?",(team_id,)).fetchone()
    if not t: abort(404)
    players=c.execute("SELECT * FROM players WHERE team_id=? ORDER BY name",(team_id,)).fetchall()
    fixtures=c.execute("""SELECT f.*,h.name home,a.name away FROM fixtures f
      JOIN teams h ON h.id=f.home_id JOIN teams a ON a.id=f.away_id
      WHERE h.id=? OR a.id=? ORDER BY f.id DESC LIMIT 20""",(team_id,team_id)).fetchall()
    c.close(); return render_template("team.html",team=t,players=players,fixtures=fixtures)

@app.route("/players")
def players():
    c=db(); rows=c.execute("""SELECT p.*,COALESCE(t.name,'Free Agent') team FROM players p
      LEFT JOIN teams t ON t.id=p.team_id ORDER BY p.goals DESC,p.assists DESC,p.name""").fetchall(); c.close()
    return render_template("players.html",players=rows)

@app.route("/player/<int:player_id>")
def player(player_id):
    c=db(); p=c.execute("""SELECT p.*,COALESCE(t.name,'Free Agent') team FROM players p
      LEFT JOIN teams t ON t.id=p.team_id WHERE p.id=?""",(player_id,)).fetchone()
    if not p: abort(404)
    transfers=c.execute("SELECT * FROM transfers WHERE player_id=? ORDER BY id DESC",(player_id,)).fetchall()
    c.close(); return render_template("player.html",player=p,transfers=transfers)

@app.route("/fixtures", methods=["GET","POST"])
def fixtures():
    c=db()
    if request.method == "POST":
        if not session.get("admin"):
            return redirect(url_for("login", next=url_for("fixtures")))
        fixture_id = request.form.get("fixture_id")
        home_score = request.form.get("home_score")
        away_score = request.form.get("away_score")
        if fixture_id and home_score is not None and away_score is not None:
            try:
                hs, as_ = int(home_score), int(away_score)
                if hs >= 0 and as_ >= 0:
                    c.execute("UPDATE fixtures SET status='played',home_score=?,away_score=? WHERE id=?", (hs, as_, int(fixture_id)))
                    c.commit()
            except ValueError:
                pass
        c.close()
        return redirect(url_for("fixtures"))
    rows=c.execute("""SELECT f.*,h.name home,a.name away FROM fixtures f
      JOIN teams h ON h.id=f.home_id JOIN teams a ON a.id=f.away_id
      ORDER BY COALESCE(f.round_no, 999999), f.id""").fetchall(); c.close()
    return render_template("fixtures.html",fixtures=rows)

@app.route("/transfers")
def transfers():
    c=db(); rows=c.execute("""SELECT tr.*,p.name player FROM transfers tr JOIN players p ON p.id=tr.player_id
      ORDER BY tr.id DESC""").fetchall(); c.close(); return render_template("transfers.html",transfers=rows)

@app.route("/totw")
def totw():
    c=db(); rows=c.execute("""SELECT t.week,p.id player_id,p.name,p.position,COALESCE(te.name,'Free Agent') team
      FROM totw t JOIN players p ON p.id=t.player_id LEFT JOIN teams te ON te.id=p.team_id
      ORDER BY t.id DESC""").fetchall(); c.close(); return render_template("totw.html",rows=rows)

@app.route("/auth/discord")
def auth_discord(): return discord_login()

@app.route("/auth/discord/callback")
def auth_discord_callback(): return discord_callback()


def manager_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        discord_id = session.get("discord_id")
        if not discord_id:
            return redirect(url_for("login", next=request.path))
        c = db()
        team = c.execute("SELECT * FROM teams WHERE discord_id=?", (discord_id,)).fetchone()
        c.close()
        if not team:
            return "Your Discord account is not linked to a PSL team yet. Ask the admin to link your Discord ID.", 403
        return fn(team, *a, **kw)
    return wrapper


@app.route("/manager", methods=["GET", "POST"])
@manager_required
def manager_dashboard(team):
    c = db()

    if request.method == "POST":
        action = request.form.get("action")
        if action == "sign_player":
            player_id = request.form.get("player_id")
            if player_id:
                player = c.execute(
                    "SELECT * FROM players WHERE id=?",
                    (player_id,)
                ).fetchone()

                if not player:
                    c.close()
                    return "Player not found.", 404

                if player["team_id"] is not None:
                    c.close()
                    return "That player is already signed.", 400

                c.execute(
                    "INSERT INTO transfers(player_id,from_team,to_team) VALUES(?,?,?)",
                    (player["id"], "Free Agent", team["name"])
                )
                c.execute(
                    "UPDATE players SET team_id=? WHERE id=?",
                    (team["id"], player["id"])
                )
                c.commit()

    my_players = c.execute(
        "SELECT * FROM players WHERE team_id=? ORDER BY position,name",
        (team["id"],)
    ).fetchall()

    free_agents = c.execute(
        "SELECT * FROM players WHERE team_id IS NULL ORDER BY position,name"
    ).fetchall()

    c.close()

    return render_template(
        "manager.html",
        team=team,
        players=my_players,
        free_agents=free_agents,
        discord_id=session.get("discord_id"),
    )


def player_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        discord_id = session.get("discord_id")
        if not discord_id:
            return redirect(url_for("login", next=request.path))

        c = db()
        player = c.execute(
            """SELECT p.*,COALESCE(t.name,'Free Agent') team, t.manager, t.logo
               FROM players p
               LEFT JOIN teams t ON t.id=p.team_id
               WHERE p.discord_id=?""",
            (discord_id,)
        ).fetchone()

        if not player:
            c.close()
            return "Your Discord account is not linked to a PSL player yet. Ask the admin to link your Discord ID.", 403

        return fn(player, *a, **kw)
    return wrapper


@app.route("/player-dashboard", methods=["GET"])
@player_required
def player_dashboard(player):
    c = db()
    transfers = c.execute(
        "SELECT * FROM transfers WHERE player_id=? ORDER BY id DESC",
        (player["id"],)
    ).fetchall()
    c.close()

    return render_template(
        "player_dashboard.html",
        player=player,
        transfers=transfers,
        discord_id=session.get("discord_id"),
    )



@app.route("/dashboard")
def dashboard():
    if session.get("admin"):
        return redirect(url_for("admin"))

    discord_id = session.get("discord_id")
    if not discord_id:
        return redirect(url_for("login", next=url_for("dashboard")))

    c = db()
    team = c.execute(
        "SELECT id FROM teams WHERE discord_id=?",
        (discord_id,)
    ).fetchone()

    if team:
        c.close()
        return redirect(url_for("manager_dashboard"))

    player = c.execute(
        "SELECT id FROM players WHERE discord_id=?",
        (discord_id,)
    ).fetchone()
    c.close()

    if player:
        return redirect(url_for("player_dashboard"))

    return "Your Discord account is not linked to a PSL manager or player yet. Ask the admin to link your Discord ID.", 403


@app.route("/login",methods=["GET","POST"])
def login():
    if request.method=="POST":
        if request.form.get("username")==ADMIN_USER and request.form.get("password")==ADMIN_PASSWORD:
            session["admin"]=True
            return redirect(request.args.get("next") or url_for("admin"))
        return render_template("login.html",error="Incorrect username or password.")
    return render_template("login.html")

@app.route("/logout")
def logout(): session.clear(); return redirect(url_for("home"))

@app.route("/admin",methods=["GET","POST"])
@admin_required
def admin():
    c=db()
    if request.method=="POST":
        a=request.form["action"]
        if a=="team":
            c.execute("INSERT OR IGNORE INTO teams(name,manager,logo) VALUES(?,?,?)",
                      (request.form["name"].strip(),request.form.get("manager","").strip(),request.form.get("logo","").strip()))
        elif a=="player":
            c.execute("INSERT INTO players(name,position,team_id) VALUES(?,?,?)",
                      (request.form["name"].strip(),request.form.get("position","").strip(),request.form.get("team_id") or None))
        elif a=="fixture":
            home_raw = request.form.get("home_id")
            away_raw = request.form.get("away_id")
            if home_raw and away_raw:
                home_id = int(home_raw)
                away_id = int(away_raw)
                if home_id != away_id:
                    exists = c.execute("SELECT 1 FROM fixtures WHERE home_id=? AND away_id=?", (home_id, away_id)).fetchone()
                    if not exists:
                        c.execute("INSERT INTO fixtures(home_id,away_id,scheduled) VALUES(?,?,?)",
                                  (home_id, away_id, request.form.get("scheduled", "")))
        elif a=="generate_fixtures":
            teams_for_schedule = c.execute("SELECT id, name FROM teams ORDER BY id").fetchall()
            if len(teams_for_schedule) == 10:
                # Circle method: 9 rounds, then repeat with home/away reversed = 90 games.
                ids = [t["id"] for t in teams_for_schedule]
                fixed = ids[0]
                rotating = ids[1:]
                rounds = []
                arr = rotating[:]
                for rnd in range(9):
                    current = [fixed] + arr
                    pairings = []
                    for i in range(5):
                        pairings.append((current[i], current[-1-i]))
                    rounds.append(pairings)
                    arr = [arr[-1]] + arr[:-1]

                created = 0
                for rnd, pairings in enumerate(rounds, start=1):
                    for home_id, away_id in pairings:
                        if not c.execute("SELECT 1 FROM fixtures WHERE home_id=? AND away_id=?", (home_id, away_id)).fetchone():
                            c.execute("INSERT INTO fixtures(home_id,away_id,scheduled,round_no) VALUES(?,?,?,?)",
                                      (home_id, away_id, f"Round {rnd}", rnd))
                            created += 1
                for rnd, pairings in enumerate(rounds, start=10):
                    original_rnd = rnd - 9
                    for home_id, away_id in pairings:
                        if not c.execute("SELECT 1 FROM fixtures WHERE home_id=? AND away_id=?", (away_id, home_id)).fetchone():
                            c.execute("INSERT INTO fixtures(home_id,away_id,scheduled,round_no) VALUES(?,?,?,?)",
                                      (away_id, home_id, f"Round {rnd}", rnd))
                            created += 1
        elif a=="result":
            c.execute("UPDATE fixtures SET status='played',home_score=?,away_score=? WHERE id=?",
                      (request.form["home_score"],request.form["away_score"],request.form["fixture_id"]))
        elif a=="transfer":
            p=c.execute("SELECT * FROM players WHERE id=?",(request.form["player_id"],)).fetchone()
            to_id=int(request.form["to_team"])
            to=c.execute("SELECT name FROM teams WHERE id=?",(to_id,)).fetchone()["name"]
            old=c.execute("SELECT name FROM teams WHERE id IS ?",(p["team_id"],)).fetchone()
            old_name=old["name"] if old else "Free Agent"
            c.execute("INSERT INTO transfers(player_id,from_team,to_team) VALUES(?,?,?)",(p["id"],old_name,to))
            c.execute("UPDATE players SET team_id=? WHERE id=?",(to_id,p["id"]))
        elif a=="totw":
            c.execute("INSERT INTO totw(week,player_id,position) VALUES(?,?,?)",
                      (request.form["week"],request.form["player_id"],request.form.get("position","")))
        elif a=="link_discord":
            team_id = int(request.form["team_id"])
            discord_id = request.form["discord_id"].strip()
            c.execute("UPDATE teams SET discord_id=? WHERE id=?", (discord_id, team_id))
        elif a=="link_player_discord":
            player_id = int(request.form["player_id"])
            discord_id = request.form["discord_id"].strip()
            c.execute("UPDATE players SET discord_id=? WHERE id=?", (discord_id, player_id))
        c.commit()
    teams=c.execute("SELECT * FROM teams ORDER BY name").fetchall()
    players=c.execute("SELECT * FROM players ORDER BY name").fetchall()
    fixtures_=c.execute("""SELECT f.*,h.name home,a.name away FROM fixtures f
      JOIN teams h ON h.id=f.home_id JOIN teams a ON a.id=f.away_id ORDER BY f.id DESC""").fetchall()
    c.close(); return render_template("admin.html",teams=teams,players=players,fixtures=fixtures_)

# Simple endpoint for your Discord bot. Send JSON with an API key.
@app.post("/api/results")
def api_result():
    if request.headers.get("X-PSL-API-KEY") != API_KEY: return jsonify(error="Unauthorized"),401
    data=request.get_json(silent=True) or {}
    required=("home","away","home_score","away_score")
    if any(k not in data for k in required): return jsonify(error="Missing fields"),400
    c=db()
    h=c.execute("SELECT id FROM teams WHERE lower(name)=lower(?)",(data["home"],)).fetchone()
    a=c.execute("SELECT id FROM teams WHERE lower(name)=lower(?)",(data["away"],)).fetchone()
    if not h or not a: c.close(); return jsonify(error="Team not found"),404
    fixture=c.execute("""SELECT id FROM fixtures WHERE status='scheduled' AND home_id=? AND away_id=?
                         ORDER BY id LIMIT 1""",(h["id"],a["id"])).fetchone()
    if fixture:
        fid=fixture["id"]; c.execute("UPDATE fixtures SET status='played',home_score=?,away_score=? WHERE id=?",
                                     (int(data["home_score"]),int(data["away_score"]),fid))
    else:
        c.execute("""INSERT INTO fixtures(home_id,away_id,status,home_score,away_score) VALUES(?,?,?,?,?)""",
                  (h["id"],a["id"],"played",int(data["home_score"]),int(data["away_score"])))
        fid=c.execute("SELECT last_insert_rowid()").fetchone()[0]
    c.commit(); c.close()
    return jsonify(ok=True,fixture_id=fid)

if __name__=="__main__":
    init_db()
    app.run(debug=True)
