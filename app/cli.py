import argparse


def main() -> None:
    parser = argparse.ArgumentParser(prog="s3player")
    sub = parser.add_subparsers(dest="cmd", required=True)
    server_parser = sub.add_parser("server", help="Run the FastAPI server")
    server_parser.add_argument(
        "--host",
        default=None,
        help="Bind address (default: $SERVER_HOST, else 127.0.0.1)",
    )
    server_parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Bind port (default: $SERVER_PORT, else 8000)",
    )
    server_parser.add_argument(
        "--reload",
        action="store_true",
        help="Reload on code changes (development only)",
    )
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

        run(host=args.host, port=args.port, reload=args.reload)
    elif args.cmd == "index":
        from app.indexer import run

        run(overwrite=args.overwrite)
