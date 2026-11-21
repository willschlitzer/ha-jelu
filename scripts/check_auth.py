"""Check that a Jelu API token works as a Bearer token.

Reads JELU_URL and JELU_TOKEN from .env in the repo root (git-ignored) and never prints the token.
Run with: uv run python scripts/check_auth.py
"""

import json
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def load_env() -> dict[str, str]:
    """Parse KEY=VALUE lines from the repo's .env file."""
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if not env_file.exists():
        sys.exit(f"Missing {env_file}: add JELU_URL=... and JELU_TOKEN=...")
    env = {}
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip("\"'")
    return env


def get(base: str, path: str, token: str | None) -> None:
    """GET an API path and report the status plus a short summary of the body."""
    request = Request(f"{base}/api/v1{path}")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urlopen(request, timeout=10) as response:
            body = json.loads(response.read() or b"null")
            status = response.status
    except HTTPError as err:
        print(f"{path:<30} HTTP {err.code}")
        return
    summary = sorted(body) if isinstance(body, dict) else type(body).__name__
    print(f"{path:<30} HTTP {status}  keys: {summary}")


def main() -> None:
    """Run the checks."""
    env = load_env()
    base = env["JELU_URL"].rstrip("/")
    token = env["JELU_TOKEN"]
    print("Without auth:")
    get(base, "/server-settings", None)
    get(base, "/users/me", None)
    print("With Bearer token:")
    get(base, "/users/me", token)
    get(base, "/stats/total", token)
    get(base, "/reading-events/me?eventTypes=CURRENTLY_READING&size=1", token)


if __name__ == "__main__":
    main()
