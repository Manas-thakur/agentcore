"""Optional HTTP server (the ``server`` extra).

Install: ``pip install "agentcore[server] @ git+https://github.com/Manas-thakur/agentcore"``
(the ``agentcore`` package on PyPI is a different project).
"""

from agentcore.server.app import create_app, dashboard_html

__all__ = ["create_app", "dashboard_html"]
