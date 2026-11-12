"""Controlled DM/local/replay owners plus production indicator batch API."""
from tests.synthetic_pinned_browser_server import app
from app.api.v1.indicators import router
app.include_router(router, prefix='/api/v1')
