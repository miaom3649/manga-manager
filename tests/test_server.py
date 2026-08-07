from __future__ import annotations

import sys

from hlibrary.server import ApiServer


def test_server_can_be_created_without_console(monkeypatch) -> None:
    """PyInstaller windowed executables expose no stdout or stderr on Windows."""
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    server = ApiServer("127.0.0.1", 18459)

    assert server._server.config.log_config is None
