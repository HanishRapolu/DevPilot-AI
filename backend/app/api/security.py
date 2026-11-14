import secrets
from fastapi import HTTPException, Request


def authorize(request: Request):
    expected = request.app.state.settings.dashboard_api_token.get_secret_value()
    supplied = request.headers.get("authorization", "").removeprefix("Bearer ")
    if not expected:
        raise HTTPException(503, "Configure DASHBOARD_API_TOKEN locally before using the dashboard.")
    if not secrets.compare_digest(supplied, expected):
        raise HTTPException(401, "Enter the dashboard access token.")
