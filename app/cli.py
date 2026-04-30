import argparse


def main() -> None:
    parser = argparse.ArgumentParser(prog="s3player")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("server", help="Run the FastAPI server on :8000")
    sub.add_parser("index", help="Index audio files from S3 into Postgres")
    args = parser.parse_args()

    if args.cmd == "server":
        from app.server import run

        run()
    elif args.cmd == "index":
        from app.indexer import run

        run()
