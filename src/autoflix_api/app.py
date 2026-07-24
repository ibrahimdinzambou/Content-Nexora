from __future__ import annotations

import os
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from flask import Flask, Response, jsonify, render_template, request

from autoflix_cli.scraping import anime_sama, arkanime, coflix, french_stream, player, wiflix


ROOT = Path(__file__).parent
app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))

DEFAULT_ALLOWED_ORIGINS = {
    "https://nexoragabon.com",
    "https://www.nexoragabon.com",
}
ALLOWED_ORIGINS = {
    origin.strip().rstrip("/")
    for origin in os.getenv("AUTOFLIX_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
} or DEFAULT_ALLOWED_ORIGINS


@app.after_request
def add_cors_headers(response):
    """Allow the production site and its www variant to call the API."""
    origin = request.headers.get("Origin", "").rstrip("/")
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
        response.headers["Access-Control-Max-Age"] = "86400"
        response.headers["Vary"] = "Origin"
    return response

PROVIDERS = {
    "french-stream": {"label": "French-Stream", "module": french_stream, "languages": ["fr"]},
    "anime-sama": {"label": "Anime-Sama", "module": anime_sama, "languages": ["fr"]},
}


def serialize(value: Any) -> Any:
    """Turn the CLI's lightweight objects into JSON-safe data."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set)):
        return [serialize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): serialize(item) for key, item in value.items()}
    if is_dataclass(value):
        return serialize(asdict(value))
    if hasattr(value, "__dict__"):
        return {key: serialize(item) for key, item in vars(value).items() if not key.startswith("_")}
    return str(value)


def _players(value: Any) -> list[dict]:
    if not value:
        return []
    return [{"name": item.name, "url": item.url} for item in value]


def normalize_content(value: Any) -> dict:
    """Expose a stable media tree regardless of the scraper's internal class."""
    kind = value.__class__.__name__
    if kind in {"FrenchStreamMovie", "CoflixMovie", "WiflixMovie"}:
        return {"type": "movie", "title": value.title, "url": value.url, "img": getattr(value, "img", ""), "genres": getattr(value, "genres", []), "players": _players(value.players)}
    if kind == "FrenchStreamSeason":
        return {"type": "series", "title": value.title, "url": value.url, "img": "", "genres": [], "seasons": [{"type": "season", "title": "Episodes", "url": value.url, "episodes": normalize_episodes(value.episodes)}]}
    if kind in {"SamaSeries", "CoflixSeries", "ArkSeries"}:
        seasons = []
        for season in getattr(value, "seasons", []):
            seasons.append({"type": "season", "title": season.title, "url": getattr(season, "url", getattr(season, "id", "")), "episodes": normalize_episodes(getattr(season, "episodes", {})) if hasattr(season, "episodes") else {}})
        return {"type": "series", "title": value.title, "url": getattr(value, "url", getattr(value, "id", "")), "img": getattr(value, "img", ""), "genres": getattr(value, "genres", []), "seasons": seasons}
    if kind in {"SamaSeason", "CoflixSeason", "WiflixSeriesSeason"}:
        return {"type": "season", "title": value.title, "url": value.url, "episodes": normalize_episodes(value.episodes)}
    if kind == "Episode":
        return {"type": "episode", "title": value.title, "players": _players(value.players)}
    return serialize(value)


def normalize_episodes(episodes: Any) -> dict:
    if isinstance(episodes, dict):
        return {str(language): [normalize_content(item) for item in items] for language, items in episodes.items()}
    if isinstance(episodes, list):
        return {"default": [normalize_content(item) for item in episodes]}
    return {}


def provider_or_error(name: str):
    provider = PROVIDERS.get(name.lower())
    if not provider:
        raise ValueError(f"Unknown provider. Choose one of: {', '.join(PROVIDERS)}")
    return provider


def call_provider(provider_name: str, operation: str, url: str | None = None, query: str | None = None):
    provider = provider_or_error(provider_name)
    module = provider["module"]
    # These scrapers intentionally initialize their origin in the CLI flow.
    # The HTTP API has no interactive provider menu, so initialize it here.
    if provider_name.lower() in {"anime-sama"}:
        module.get_website_url()
    if operation == "search":
        return module.search(query or "")
    if operation == "content":
        if hasattr(module, "get_content"):
            return module.get_content(url or "")
        return module.get_series(url or "")
    if operation == "series":
        return module.get_series(url or "")
    if operation == "season":
        return module.get_season(url or "")
    if operation == "episode":
        return module.get_episode(url or "")
    raise ValueError("Unsupported operation")


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/favicon.ico")
def favicon():
    return Response(status=204)


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "service": "autoflix-api"})


@app.get("/api/providers")
def providers():
    return jsonify({"providers": [{"id": key, **{k: v for k, v in value.items() if k != "module"}} for key, value in PROVIDERS.items()]})


@app.get("/api/search")
def search():
    try:
        query = request.args.get("q", "").strip()
        if len(query) < 2:
            return jsonify({"error": "q must contain at least 2 characters"}), 400
        result = call_provider(request.args.get("provider", ""), "search", query=query)
        return jsonify({"results": serialize(result)})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


@app.get("/api/content")
def content():
    try:
        return jsonify({"content": normalize_content(call_provider(request.args["provider"], "content", url=request.args["url"]))})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


@app.get("/api/series")
def series():
    try:
        return jsonify({"content": normalize_content(call_provider(request.args["provider"], "series", url=request.args["url"]))})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


@app.get("/api/season")
def season():
    try:
        return jsonify({"season": normalize_content(call_provider(request.args["provider"], "season", url=request.args["url"]))})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


@app.get("/api/episode")
def episode():
    try:
        return jsonify({"episode": normalize_content(call_provider(request.args["provider"], "episode", url=request.args["url"]))})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


@app.post("/api/resolve")
def resolve():
    payload = request.get_json(silent=True) or {}
    player_url = str(payload.get("player_url", "")).strip()
    if urlparse(player_url).scheme not in {"http", "https"}:
        return jsonify({"error": "player_url must be an HTTP(S) URL"}), 400
    try:
        referer = str(payload.get("referer", "https://autoflix.local/"))
        stream_url, subtitle_url = player.get_hls_link(player_url, headers={"Referer": referer}, return_subs=True)
        if not stream_url:
            return jsonify({"error": "No compatible stream found for this player URL"}), 404
        return jsonify({"stream_url": stream_url, "subtitle_url": subtitle_url, "kind": "hls" if ".m3u8" in stream_url.lower() else "video"})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


def main():
    app.run(host=os.getenv("AUTOFLIX_HOST", "127.0.0.1"), port=int(os.getenv("AUTOFLIX_PORT", "8787")), debug=False)


if __name__ == "__main__":
    main()
