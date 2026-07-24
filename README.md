# Content Nexora

Content Nexora is a local Python API and browser console for discovering and testing video streams from supported third-party providers.

The current integration exposes two providers:

- French-Stream
- Anime-Sama

The project does not host, store, or redistribute media. It only retrieves metadata and stream links from third-party websites. Use it only where permitted by applicable law and by the provider's terms.

## Features

- Flask JSON API built on top of the original AutoFlix scrapers.
- Search for films and series.
- Explicit content types: `movie`, `series`, `season`, and `episode`.
- Series navigation by season, language, episode, and player.
- HLS and direct video playback in a local browser console.
- Player URL resolution with clear errors for expired or unavailable sources.
- Local-only server by default.

## Requirements

- Python 3.10 or newer
- Internet access for third-party provider requests

## Installation

```bash
git clone https://github.com/ibrahimdinzambou/Content-Nexora.git
cd Content-Nexora
python -m pip install -e .
```

## Start the API and player

```bash
autoflix-api
```

Open <http://127.0.0.1:8787> in a browser.

The host and port can be changed with:

```powershell
$env:AUTOFLIX_HOST="127.0.0.1"
$env:AUTOFLIX_PORT="8787"
autoflix-api
```

## API endpoints

| Endpoint | Description |
| --- | --- |
| `GET /api/health` | Service health check |
| `GET /api/providers` | Enabled providers |
| `GET /api/search?provider=french-stream&q=...` | Search titles |
| `GET /api/content?provider=anime-sama&url=...` | Normalized film or series |
| `GET /api/series?provider=anime-sama&url=...` | Series details and seasons |
| `GET /api/season?provider=anime-sama&url=...` | Episodes grouped by language |
| `GET /api/episode?provider=french-stream&url=...` | Episode players |
| `POST /api/resolve` | Resolve a player URL into a stream URL |

Example request:

```json
{
  "player_url": "https://example.invalid/embed/example.html",
  "referer": "https://french-stream.one/"
}
```

## Content response model

Films return `type: "movie"` with their players. Series return `type: "series"` with a list of seasons. Seasons expose episodes grouped by language, and each episode exposes its available players.

```json
{
  "type": "series",
  "title": "Example",
  "seasons": [
    {
      "type": "season",
      "title": "Season 1",
      "episodes": {
        "vf": [
          {
            "type": "episode",
            "title": "Episode 1",
            "players": []
          }
        ]
      }
    }
  ]
}
```

## Development checks

```bash
python -m compileall -q src
python -c "from autoflix_api.app import app; print(app.test_client().get('/api/health').json)"
```

## License

The project retains the GPL-3 license from the original AutoFlix-CLI codebase. See [LICENSE](LICENSE).
