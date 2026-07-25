# Content Nexora

Content Nexora is a local Python API and browser console for discovering and testing video streams from supported third-party providers.

The current integration exposes two discovery providers:

- French-Stream
- Anime-Sama

It can also aggregate the providers exposed by the optional French Nexora Node API. Configure its base URL to load their film and series sources alongside Content-Nexora:

```bash
export FRENCH_NEXORA_API_BASE_URL="http://127.0.0.1:3000"
```

The project does not host, store, or redistribute media. It only retrieves metadata and stream links from third-party websites. Use it only where permitted by applicable law and by the provider's terms.

## Features

- Flask JSON API built on top of the original AutoFlix scrapers.
- Search for films and series.
- Explicit content types: `movie`, `series`, `season`, and `episode`.
- Series navigation by season, language, episode, and player.
- HLS and direct video playback in a local browser console.
- Player URL resolution with an embed fallback when direct HLS extraction is unavailable.
- Local-only server by default.

## Requirements

- Python 3.10 or newer
- Internet access for third-party provider requests
- A TMDB API key or read access token for the public catalog

## Installation

```bash
git clone https://github.com/ibrahimdinzambou/Content-Nexora.git
cd Content-Nexora
python -m pip install -e .
```

Configure TMDB on the VPS:

```bash
export TMDB_API_KEY="your_tmdb_api_key"
# or: export TMDB_READ_ACCESS_TOKEN="your_tmdb_v4_read_token"
```

The catalog endpoint uses TMDB for films and series metadata, posters, backdrops, years, genres, and overviews. Playback is attempted through Content-Nexora and the optional Node providers first; Videasy remains a fallback.

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

By default, the API accepts browser requests from `https://nexoragabon.com` and `https://www.nexoragabon.com`. For another deployment, configure the comma-separated `AUTOFLIX_ALLOWED_ORIGINS` variable. If Nginx already emits the CORS headers, set `AUTOFLIX_CORS_MODE=nginx` so only one layer adds them.

## API endpoints

| Endpoint | Description |
| --- | --- |
| `GET /api/health` | Service health check |
| `GET /api/providers` | Enabled providers |
| `GET /api/catalog/items?type=movie` | TMDB films or series using the Nexora front contract |
| `GET /api/catalog/items/<tmdb-id>` | TMDB film or series details |
| `GET /api/catalog/series/<tmdb-id>` | TMDB seasons and clickable episodes |
| `GET /api/search?provider=french-stream&q=...` | Search titles |
| `GET /api/content?provider=french-stream&q=...&type=...` | Resolve a title or TMDB title through Content-Nexora |
| `GET /api/content?provider=anime-sama&url=...` | Normalized film or series by provider URL |
| `GET /api/series?provider=french-stream&q=...&season=...` | Series details, episodes, and players by title |
| `GET /api/series?provider=anime-sama&url=...` | Series details and seasons by provider URL |
| `GET /api/season?provider=anime-sama&url=...` | Episodes grouped by language |
| `GET /api/episode?provider=french-stream&url=...` | Episode players |
| `GET /api/node/providers` | French Nexora Node providers |
| `GET /api/node/streams?tmdbId=...&mediaType=...` | Normalized Node provider streams |
| `POST /api/resolve` | Resolve a player URL into a stream URL |

The Node routes are also available below `/node-fr/api/...` for older Nexora front builds. For TV series, pass both `season` and `episode`; `/api/content` and `/api/series` accept a provider URL or a `q`/`title`, plus `tmdbId`, and merge the Node sources into the selected episode.

Apply the companion patches in this order:

1. [`nexoragabon-front.patch`](nexoragabon-front.patch) fixes the series click order and Anime-Nexora artwork.
2. [`nexoragabon-front-episode-title.patch`](nexoragabon-front-episode-title.patch) keeps the parent series title during episode playback.
3. [`nexoragabon-front-content-tmdb-playback.patch`](nexoragabon-front-content-tmdb-playback.patch) routes TMDB and Content series through Content-Nexora first and keeps valid embed players when direct extraction is unavailable.

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
