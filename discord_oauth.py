import os
import requests
from flask import redirect, request, session, url_for


def discord_login():
    client_id = os.getenv("DISCORD_CLIENT_ID")
    redirect_uri = os.getenv(
        "DISCORD_REDIRECT_URI",
        "http://127.0.0.1:5000/auth/discord/callback",
    )

    if not client_id:
        return "DISCORD_CLIENT_ID is missing from .env", 500

    url = (
        "https://discord.com/oauth2/authorize"
        "?client_id=" + client_id
        + "&response_type=code"
        + "&redirect_uri=" + requests.utils.quote(redirect_uri, safe="")
        + "&scope=identify"
    )

    return redirect(url)


def discord_callback():
    code = request.args.get("code")

    print(
        "OAUTH CODE RECEIVED:",
        bool(code),
        "LENGTH:",
        len(code) if code else 0,
    )

    if not code:
        return "Discord login was cancelled or failed.", 400

    client_id = os.getenv("DISCORD_CLIENT_ID")
    client_secret = os.getenv("DISCORD_CLIENT_SECRET")
    redirect_uri = os.getenv(
        "DISCORD_REDIRECT_URI",
        "http://127.0.0.1:5000/auth/discord/callback",
    )

    if not client_id or not client_secret:
        return "Discord OAuth settings are missing from .env", 500

    token = requests.post(
        "https://discord.com/api/oauth2/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
        timeout=10,
    )

    if not token.ok:
        return "Discord token exchange failed: " + token.text, 500

    access_token = token.json().get("access_token")

    if not access_token:
        return "Discord token exchange did not return an access token.", 500

    user = requests.get(
        "https://discord.com/api/users/@me",
        headers={"Authorization": "Bearer " + access_token},
        timeout=10,
    )

    if not user.ok:
        return "Could not retrieve your Discord account.", 500

    discord_user = user.json()
    session["discord_user"] = discord_user
    session["discord_id"] = discord_user.get("id")

    return redirect(url_for("dashboard"))
