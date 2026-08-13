from hmanga.desktop.pairing_dialog import choose_pairing_ip


def test_pairing_prefers_bridged_lan_address() -> None:
    assert choose_pairing_ip(["10.0.2.15", "192.168.3.120", "198.18.0.1"]) == "192.168.3.120"


def test_pairing_rejects_virtual_benchmark_network() -> None:
    assert choose_pairing_ip(["127.0.0.1", "198.18.0.1"]) == "127.0.0.1"
