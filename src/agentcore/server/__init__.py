"""Optional HTTP server (``pip install 'agentcore[server]'``)."""

from agentcore.server.app import create_app, dashboard_html

__all__ = ["create_app", "dashboard_html"]
