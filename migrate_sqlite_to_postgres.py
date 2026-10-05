import os
import sqlite3

import psycopg
from dotenv import load_dotenv

load_dotenv()

import app
app.init_db()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing")

src = sqlite3.connect("psl.db")
src.row_factory = sqlite3.Row
dst = psycopg.connect(DATABASE_URL)

def insert_rows(table, columns, rows):
    if not rows:
        return
    placeholders = ",".join(["%s"] * len(columns))
    sql = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})"
    with dst.cursor() as cur:
        for row in rows:
            cur.execute(sql, tuple(row[col] for col in columns))

with dst.cursor() as cur:
    cur.execute("TRUNCATE TABLE totw, transfers, fixtures, players, teams RESTART IDENTITY CASCADE")

teams = src.execute("SELECT id,name,manager,logo,discord_id FROM teams ORDER BY id").fetchall()
players = src.execute("SELECT id,name,position,team_id,appearances,goals,assists,discord_id FROM players ORDER BY id").fetchall()
fixtures = src.execute("SELECT id,home_id,away_id,scheduled,status,home_score,away_score,round_no FROM fixtures ORDER BY id").fetchall()
transfers = src.execute("SELECT id,player_id,from_team,to_team,created_at FROM transfers ORDER BY id").fetchall()
totw = src.execute("SELECT id,week,player_id,position,created_at FROM totw ORDER BY id").fetchall()

insert_rows("teams", ["id","name","manager","logo","discord_id"], teams)
insert_rows("players", ["id","name","position","team_id","appearances","goals","assists","discord_id"], players)
insert_rows("fixtures", ["id","home_id","away_id","scheduled","status","home_score","away_score","round_no"], fixtures)
insert_rows("transfers", ["id","player_id","from_team","to_team","created_at"], transfers)
insert_rows("totw", ["id","week","player_id","position","created_at"], totw)

with dst.cursor() as cur:
    for table in ("teams","players","fixtures","transfers","totw"):
        cur.execute(
            f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
            f"COALESCE((SELECT MAX(id) FROM {table}), 1), true)"
        )

dst.commit()
src.close()
dst.close()

print("SQLite -> PostgreSQL migration complete.")
print(f"Teams: {len(teams)}")
print(f"Players: {len(players)}")
print(f"Fixtures: {len(fixtures)}")
print(f"Transfers: {len(transfers)}")
print(f"TOTW: {len(totw)}")
