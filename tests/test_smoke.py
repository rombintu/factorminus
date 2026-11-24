import socket

import pytest

import factorminus


def test_version():
    assert factorminus.__version__ == "0.1.0"


def test_network_guard():
    with pytest.raises(RuntimeError, match="network disabled"):
        socket.create_connection(("example.com", 80))
