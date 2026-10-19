"""Start the API: ``python -m src.api`` (http://127.0.0.1:8600/api/docs)."""

import uvicorn

from config.settings import get_settings
from src.api.app import create_app

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(create_app(), host=settings.api_host, port=settings.api_port, proxy_headers=False,
                server_header=False)
