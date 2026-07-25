from __future__ import annotations

import os
from typing import Any

from curl_cffi import requests


TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMAGE = "https://image.tmdb.org/t/p"
PLAYBACK_PROVIDER = "content-nexora"
PLAYBACK_PROVIDER_NAME = "Content-Nexora"
FALLBACK_PLAYBACK_PROVIDER = "videasy"
FALLBACK_PLAYBACK_PROVIDER_NAME = "Videasy"


def _request(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    api_key = os.getenv("TMDB_API_KEY", "").strip()
    read_token = os.getenv("TMDB_READ_ACCESS_TOKEN", "").strip()
    if not api_key and not read_token:
        raise RuntimeError("TMDB_API_KEY or TMDB_READ_ACCESS_TOKEN is not configured")
    request_params = dict(params or {})
    headers = {"Accept": "application/json"}
    if read_token:
        headers["Authorization"] = f"Bearer {read_token}"
    else:
        request_params["api_key"] = api_key
    request_params.setdefault("language", os.getenv("TMDB_LANGUAGE", "fr-FR"))
    response = requests.get(
        f"{os.getenv('TMDB_API_BASE_URL', TMDB_API).rstrip('/')}{path}",
        params=request_params,
        headers=headers,
        impersonate="chrome",
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def _image(path: str | None, size: str = "w500") -> str:
    if not path:
        return ""
    if path.startswith(("http://", "https://")):
        return path
    base = os.getenv("TMDB_IMAGE_BASE_URL", TMDB_IMAGE).rstrip("/")
    return f"{base}/{size}/{path.lstrip('/')}"


def public_id(tmdb_id: int, media_type: str) -> str:
    normalized_type = "series" if media_type in {"tv", "series"} else "movie"
    return f"tmdb~{normalized_type}~{tmdb_id}"


def parse_public_id(value: str) -> tuple[int, str]:
    """Accept the current Nexora ID and the former colon-separated ID."""
    separator = "~" if "~" in value else ":"
    parts = value.split(separator)
    if len(parts) < 3 or parts[0].lower() != "tmdb" or not parts[2].isdigit():
        raise ValueError("Expected a TMDB item id (tmdb~movie~123 or tmdb~series~123)")
    if parts[1].lower() not in {"movie", "tv", "series"}:
        raise ValueError("TMDB item type must be movie or series")
    media_type = "series" if parts[1].lower() in {"tv", "series"} else "movie"
    return int(parts[2]), media_type


def _category(media_type: str, search_result: bool = False) -> tuple[str, str]:
    normalized_type = "series" if media_type in {"tv", "series"} else "movie"
    suffix = "search" if search_result else "trending"
    label = "Séries" if normalized_type == "series" else "Films"
    return f"tmdb-{normalized_type}-{suffix}", f"TMDB - {label}"


def _playback_fields() -> dict[str, Any]:
    return {
        "source": "TMDB",
        "sourceCode": "tmdb",
        "provider": "tmdb",
        "playbackProvider": PLAYBACK_PROVIDER,
        "playbackProviderName": PLAYBACK_PROVIDER_NAME,
        "fallbackPlaybackProvider": FALLBACK_PLAYBACK_PROVIDER,
        "fallbackPlaybackProviderName": FALLBACK_PLAYBACK_PROVIDER_NAME,
        "availableProviders": [PLAYBACK_PROVIDER, FALLBACK_PLAYBACK_PROVIDER],
        "metadataAvailable": True,
        "streamAvailable": True,
        "externalPlayback": True,
    }


def _item(raw: dict[str, Any], media_type: str, *, search_result: bool = False) -> dict[str, Any]:
    normalized_type = "series" if media_type in {"tv", "series"} else "movie"
    tmdb_id = int(raw.get("id") or 0)
    title = raw.get("title") or raw.get("name") or "Sans titre"
    date = raw.get("release_date") or raw.get("first_air_date") or ""
    poster = _image(raw.get("poster_path"))
    backdrop = _image(raw.get("backdrop_path"), "w1280")
    category_id, category_name = _category(normalized_type, search_result)
    vote_average = raw.get("vote_average")
    item = {
        "id": public_id(tmdb_id, normalized_type),
        "catalogId": public_id(tmdb_id, normalized_type),
        "tmdbId": tmdb_id,
        "type": normalized_type,
        "name": title,
        "title": title,
        "originalTitle": raw.get("original_title") or raw.get("original_name") or title,
        "overview": raw.get("overview", ""),
        "summary": raw.get("overview", ""),
        "poster": poster,
        "image": poster,
        "logo": poster,
        "backdrop": backdrop or poster,
        "releaseDate": date or None,
        "releaseYear": date[:4] if date else None,
        "voteAverage": vote_average,
        "rating": vote_average,
        "genres": raw.get("genres") or raw.get("genre_ids", []),
        "genreIds": raw.get("genre_ids", []),
        "categoryId": category_id,
        "categoryName": category_name,
        "isSeries": normalized_type == "series",
        **_playback_fields(),
    }
    return item


def search(query: str, media_type: str, limit: int = 24) -> list[dict[str, Any]]:
    if media_type == "movie":
        path = "/search/movie"
    elif media_type == "series":
        path = "/search/tv"
    else:
        raise ValueError("media_type must be movie or series")
    data = _request(path, {"query": query, "page": 1, "include_adult": "false"})
    tmdb_type = "tv" if media_type == "series" else "movie"
    return [_item(row, tmdb_type, search_result=True) for row in data.get("results", [])[:limit]]


def popular(media_type: str, limit: int = 24) -> list[dict[str, Any]]:
    tmdb_type = "tv" if media_type == "series" else "movie"
    data = _request(f"/trending/{tmdb_type}/week")
    return [_item(row, tmdb_type) for row in data.get("results", [])[:limit]]


def details(tmdb_id: int, media_type: str) -> dict[str, Any]:
    tmdb_type = "tv" if media_type == "series" else "movie"
    data = _request(f"/{tmdb_type}/{tmdb_id}")
    item = _item(data, tmdb_type)
    item["genres"] = [genre.get("name") for genre in data.get("genres", []) if genre.get("name")]
    item["duration"] = data.get("runtime") or (
        data.get("episode_run_time") or [None]
    )[0]
    if media_type == "series":
        item.update(_series_fields(item, data))
    else:
        item["seasons"] = []
    return item


def _episode(tmdb_id: int, season_number: int, episode_number: int, parent: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"{public_id(tmdb_id, 'series')}~s~{season_number}~e~{episode_number}",
        "tmdbId": tmdb_id,
        "name": f"Épisode {episode_number}",
        "title": f"Épisode {episode_number}",
        "type": "series",
        "isEpisode": True,
        "season": season_number,
        "episode": episode_number,
        "poster": parent.get("poster", ""),
        "image": parent.get("backdrop") or parent.get("poster", ""),
        "backdrop": parent.get("backdrop") or parent.get("poster", ""),
        "categoryId": "tmdb-series-trending",
        "categoryName": "TMDB - Séries",
        **_playback_fields(),
    }


def _series_fields(item: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    tmdb_id = int(item["tmdbId"])
    seasons = []
    for remote_season in raw.get("seasons", []):
        season_number = int(remote_season.get("season_number") or 0)
        # The Nexora/Videasy TV route requires positive season numbers.
        if season_number < 1:
            continue
        episode_count = max(int(remote_season.get("episode_count") or 0), 0)
        season_poster = _image(remote_season.get("poster_path")) or item.get("poster", "")
        episodes = [
            {
                **_episode(tmdb_id, season_number, episode_number, item),
                "poster": season_poster,
            }
            for episode_number in range(1, episode_count + 1)
        ]
        seasons.append(
            {
                "id": remote_season.get("id"),
                "season": season_number,
                "name": remote_season.get("name") or f"Saison {season_number}",
                "title": remote_season.get("name") or f"Saison {season_number}",
                "overview": remote_season.get("overview", ""),
                "poster": season_poster,
                "episodeCount": episode_count,
                "episodes": episodes,
            }
        )
    return {
        "seasons": seasons,
        "seasonCount": len(seasons),
        "episodeCount": sum(season["episodeCount"] for season in seasons),
        "isSeries": True,
        "streamAvailable": any(season["episodes"] for season in seasons),
    }


def series(tmdb_id: int) -> dict[str, Any]:
    return details(tmdb_id, "series")
