from hlibrary import __version__
from hlibrary.__main__ import main


def test_version_smoke_path_does_not_start_gui() -> None:
    assert __version__ == "1.0.0"
    assert main(["--version"]) == 0
