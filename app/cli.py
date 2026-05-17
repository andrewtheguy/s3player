import argparse


def main() -> None:
    parser = argparse.ArgumentParser(prog="s3player")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("server", help="Run the FastAPI server on :8000")
    index_parser = sub.add_parser("index", help="Index audio files from S3 into Postgres")
    index_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing episode rows (show_id, aired_on, time_slot, chapters) "
        "from S3 metadata. Default leaves already-indexed episodes untouched.",
    )
    args = parser.parse_args()

    if args.cmd == "server":
        from app.server import run

        run()
    elif args.cmd == "index":
        from app.indexer import run

        run(overwrite=args.overwrite)
