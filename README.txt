PSL WEBSITE V2

Features:
- Real calculated league table
- Fixtures and results
- Teams and squad pages
- Player profiles and statistics
- Transfers
- Team of the Week
- Admin login
- JSON API endpoint for Discord result integration
- PSL logo included

WINDOWS:
1. python -m venv .venv
2. .venv\Scripts\activate
3. pip install -r requirements.txt
4. Set your environment variables (or use the defaults for local testing).
5. python app.py
6. Open http://127.0.0.1:5000

IMPORTANT:
Change PSL_ADMIN_PASSWORD, PSL_SECRET_KEY and PSL_API_KEY before putting the site online.

DISCORD INTEGRATION:
POST JSON to /api/results with header X-PSL-API-KEY.
Example JSON:
{"home":"Arsenal","away":"Wrexham","home_score":3,"away_score":1}

For a public deployment, use HTTPS and a production WSGI server.
