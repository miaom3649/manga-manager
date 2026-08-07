import argparse

from hlibrary import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="HLibrary", description=f"H库 {__version__}")
    parser.add_argument("--version", action="store_true", help="检查程序是否可以正常启动")
    args = parser.parse_args(argv)
    if args.version:
        return 0

    # 延迟导入 Qt，让 Windows 构建流水线可以无窗口启动成品做冒烟检查。
    from hlibrary.app import run

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
