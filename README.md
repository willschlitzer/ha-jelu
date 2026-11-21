# ha-jelu

A [Home Assistant](https://www.home-assistant.io/) integration for [Jelu](https://github.com/bayang/jelu),
a self-hosted book and reading tracker. It adds sensors for what you're reading and how many books you've finished.

## Sensors

| Entity | State | Notes |
|---|---|---|
| `sensor.jelu_currently_reading` | Books in progress | The `books` attribute lists each one (title, authors, start date), up to 50 |
| `sensor.jelu_finished_this_year` | Books finished since 1 January | Resets each year |
| `sensor.jelu_finished_total` | Books finished overall | |

A reread counts as another finished book, the same way Jelu counts it. The integration checks Jelu every 5 minutes.

## Requirements

- Home Assistant 2026.10 or newer.
- A Jelu server with API tokens. Tested with Jelu 0.88.4.
- A Jelu API token with the **`reading:read`** scope. No other scope is needed.

## Installation

### HACS (custom repository)

1. In Home Assistant, open **HACS** (the **Marketplace** from Home Assistant 2026.11).
2. Open the menu (⋮) → **Custom repositories**.
3. Add `https://github.com/willschlitzer/ha-jelu` with the type **Integration**.
4. Find **Jelu** in the list, download it, then restart Home Assistant.

### Manual

Copy `custom_components/jelu` into the `custom_components` folder of your Home Assistant configuration directory, then
restart Home Assistant.

## Setup

1. In Jelu, go to **Settings → API tokens** and create a token with the `reading:read` scope.
2. In Home Assistant, go to **Settings → Devices & services → Add integration** and search for **Jelu**.
3. Enter the URL you use to open Jelu (for example `https://jelu.example.com`) and the token.
   Turn off **Verify SSL certificate** only if your server uses a self-signed certificate.

If the token is later revoked or expires, Home Assistant asks you for a new one.

## Troubleshooting

| Message | Meaning |
|---|---|
| Jelu rejected the API token | The token is mistyped, expired or revoked. |
| The API token is valid but lacks permission | The token doesn't have the `reading:read` scope. |
| The server answered, but not like a Jelu server | The URL points at something else, such as a proxy's error page. |
| Failed to connect | Home Assistant can't reach the server at that URL. |

## Development

This project uses [uv](https://docs.astral.sh/uv/).

```sh
uv sync                # create .venv with Home Assistant and the test tools
scripts/lint           # ruff format --check, ruff check, ty check (never modifies files)
uv run pytest          # tests
uv run ruff format .   # fix formatting
```

`scripts/check_auth.py` checks a token against a real server. It reads `JELU_URL` and `JELU_TOKEN` from a
git-ignored `.env` file and never prints the token.

## License

[MIT](LICENSE)

The icons in `custom_components/jelu/brand/` are the Jelu logo (`src/jelu-ui/src/assets/jelu_logo.svg` in
[bayang/jelu](https://github.com/bayang/jelu), MIT License), rendered to PNG, plus a dark-theme version with the
colours swapped. This integration is not affiliated with the Jelu project.
