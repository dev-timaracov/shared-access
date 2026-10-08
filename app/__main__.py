"""Run the REST and MCP server."""

import argparse

import uvicorn

from app.config import Settings
from app.main import create_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--no-auth",
        action="store_true",
        help="Allow REST/MCP without a token as local-admin with full project access",
    )
    args = parser.parse_args()
    overrides = {"auth_disabled": True} if args.no_auth else {}
    uvicorn.run(create_app(Settings(**overrides)), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
