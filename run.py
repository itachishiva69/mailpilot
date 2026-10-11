"""Hosted entry point for Render or another ASGI host."""
from __future__ import annotations

import os
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.oauth_server:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        log_level="info",
        access_log=False,
    )
