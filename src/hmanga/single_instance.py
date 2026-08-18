from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from hmanga.config import APP_ID

INSTANCE_SERVER_NAME = f"{APP_ID}-desktop-instance"


def notify_running_instance(timeout_ms: int = 500) -> bool:
    """Ask the existing desktop process to show its main window."""
    socket = QLocalSocket()
    socket.connectToServer(INSTANCE_SERVER_NAME)
    if not socket.waitForConnected(timeout_ms):
        return False
    socket.write(b"show")
    socket.flush()
    if socket.bytesToWrite() > 0 and socket.state() == QLocalSocket.LocalSocketState.ConnectedState:
        socket.waitForBytesWritten(timeout_ms)
    if socket.state() != QLocalSocket.LocalSocketState.UnconnectedState:
        socket.disconnectFromServer()
    return True


def create_instance_server(parent: QObject) -> QLocalServer | None:
    """Return the primary instance listener, or notify the primary and return None."""
    if notify_running_instance():
        return None

    server = QLocalServer(parent)
    if server.listen(INSTANCE_SERVER_NAME):
        return server

    # A process may have won the startup race after our first connection try.
    if notify_running_instance():
        return None

    # On Unix, an abnormal termination can leave a stale local socket file.
    QLocalServer.removeServer(INSTANCE_SERVER_NAME)
    if server.listen(INSTANCE_SERVER_NAME):
        return server
    if notify_running_instance():
        return None
    raise RuntimeError(server.errorString())


def close_instance_server(server: QLocalServer) -> None:
    server.close()
    QLocalServer.removeServer(INSTANCE_SERVER_NAME)
