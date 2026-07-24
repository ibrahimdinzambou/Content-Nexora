from __future__ import annotations

import os
from typing import Any

from curl_cffi import requests


TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMAGE = "https://image.tmdb.org/t/p"


def _request(path: str, params: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("TMDB_API_KEY", "").strip()
    read_token = os.getenv("TMDB_READ_ACCESS_TOKEN", "").strip()
    if not api_key and not read_token:
        raise RuntimeError("TMDB_API_KEY or TMDB_READ_ACCESS_TOKEN is not configured")
    headers = {"Accept": "application/json"}
    if read_token:
        headers["Authorization"] = f"Bearer {read_token}"
    else:
        params["api_key"] = api_key
    params.setdefault("language", os.getenv("TMDB_LANGUAGE", "fr-FR"))
    response = requests.get(f"{TMDB_API}{path}", params=params, headers=headers, impersonate="chrome", timeout=15)
    response.raise_for_status()
    return response.json()


def _image(path: str | None, size: str = "w500") -> str:
    return f"{TMDB_IMAGE}/{size}{path}" if path else ""


def _item(raw: dict[str, Any], media_type: str) -> dict[str, Any]:
    title = raw.get("title") or raw.get("name") or "Untitled"
    date = raw.get("release_date") or raw.get("first_air_date") or ""
    return {
        "id": f"tmdb:{media_type}:{raw.get('id')}",
        "tmdbId": raw.get("id"),
        "type": "series" if media_type in {"tv", "series"} else "movie",
        "name": title,
        "title": title,
        "originalTitle": raw.get("original_title") or raw.get("original_name") or title,
        "overview": raw.get("overview", ""),
        "poster": _image(raw.get("poster_path")),
        "image": _image(raw.get("poster_path")),
        "backdrop": _image(raw.get("backdrop_path"), "w1280"),
        "releaseYear": date[:4] if date else None,
        "voteAverage": raw.get("vote_average"),
        "genres": raw.get("genre_ids", []),
        "source": "tmdb",
        "metadataAvailable": True,
        "streamAvailable": True,
    }


def search(query: str, media_type: str, limit: int = 24) -> list[dict[str, Any]]:
    if media_type == "movie":
        path = "/search/movie"
    elif media_type == "series":
        path = "/search/tv"
    else:
        raise ValueError("media_type must be movie or series")
    data = _request(path, {"query": query, "page": 1, "include_adult": "false"})
    return [_item(row, "tv" if media_type == "series" else "movie") for row in data.get("results", [])[:limit]]


def popular(media_type: str, limit: int = 24) -> list[dict[str, Any]]:
    data = _request(f"/trending/{'tv' if media_type == 'series' else 'movie'}/week", {})
    return [_item(row, "tv" if media_type == "series" else "movie") for row in data.get("results", [])[:limit]]


def details(tmdb_id: int, media_type: str) -> dict[str, Any]:
    data = _request(f"/{'tv' if media_type == 'series' else 'movie'}/{tmdb_id}", {})
    item = _item(data, "tv" if media_type == "series" else "movie")
    item["genres"] = [genre.get("name") for genre in data.get("genres", []) if genre.get("name")]
    item["seasons"] = [{"season": season.get("season_number"), "name": season.get("name"), "episodes": season.get("episode_count", 0)} for season in data.get("seasons", [])] if media_type == "series" else []
    return item
