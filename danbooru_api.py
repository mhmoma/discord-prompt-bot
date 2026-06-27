import asyncio
import os
import re
import time
from typing import Dict, List, Optional
from urllib.parse import quote

import aiohttp

DANBOORU_BASE = os.getenv("DANBOORU_API_BASE", os.getenv("DANBOORU_BASE_URL", "https://danbooru.donmai.us")).rstrip("/")
DANBOORU_API_USER = os.getenv("DANBOORU_API_USER", "").strip()
DANBOORU_API_KEY = os.getenv("DANBOORU_API_KEY", "").strip()
DANBOORU_CACHE_TTL = int(os.getenv("DANBOORU_CACHE_TTL", "3600"))
PROXY_URL = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY")

_group_cache = {}  # tag_group -> {"tags": [...], "fetched_at": float}
_wiki_cache = {}   # tag_name -> {"body": str, "fetched_at": float}
_post_preview_cache = {}  # tag_name -> {"data": dict, "fetched_at": float}

CATEGORY_NAMES = {
    0: "general",
    1: "artist",
    3: "copyright",
    4: "character",
    5: "meta",
}


def _cache_get(store: dict, key: str):
    entry = store.get(key)
    if not entry:
        return None
    if time.time() - entry["fetched_at"] > DANBOORU_CACHE_TTL:
        store.pop(key, None)
        return None
    return entry.get("data") or entry.get("tags")


def _cache_set(store: dict, key: str, data, field="data"):
    store[key] = {"fetched_at": time.time(), field: data}


def _danbooru_auth():
    user = os.getenv("DANBOORU_API_USER", "").strip()
    key = os.getenv("DANBOORU_API_KEY", "").strip()
    if user and key:
        return aiohttp.BasicAuth(user, key)
    return None


async def _get_json(session: aiohttp.ClientSession, path: str, params: dict | None = None):
    url = f"{DANBOORU_BASE}{path}"
    async with session.get(url, params=params, proxy=PROXY_URL, auth=_danbooru_auth(), timeout=aiohttp.ClientTimeout(total=20)) as resp:
        if resp.status != 200:
            text = await resp.text()
            raise RuntimeError(f"Danbooru HTTP {resp.status}: {text[:200]}")
        return await resp.json()


async def fetch_tag_group_members(session: aiohttp.ClientSession, tag_group: str) -> List[str]:
    cached = _cache_get(_group_cache, tag_group)
    if cached is not None:
        return [t["name"] for t in cached]

    names = set()
    page = 1
    while page <= 20:
        params = {
            "search[antecedent_name]": tag_group,
            "search[status]": "active",
            "limit": 1000,
            "page": page,
        }
        batch = await _get_json(session, "/tag_implications.json", params)
        if not batch:
            break
        for row in batch:
            name = (row.get("consequent_name") or row.get("name") or "").strip()
            if name and not name.startswith("tag_group:"):
                names.add(name)
        if len(batch) < 1000:
            break
        page += 1

    if not names:
        wiki_names = await _parse_wiki_tag_links(session, tag_group)
        names.update(wiki_names)

    tag_list = sorted(names)
    if not tag_list:
        return []

    infos = await fetch_tags_info(session, tag_list)
    infos.sort(key=lambda x: x.get("post_count", 0), reverse=True)
    _cache_set(_group_cache, tag_group, infos, field="tags")
    return [t["name"] for t in infos]


async def _parse_wiki_tag_links(session: aiohttp.ClientSession, tag_group: str) -> set[str]:
    slug = tag_group.replace("tag_group:", "tag_group:")
    try:
        data = await _get_json(session, f"/wiki_pages/{quote(slug, safe='')}.json")
    except Exception:
        return set()
    body = data.get("body") or ""
    found = set(re.findall(r"\[\[([^\]|#]+?)(?:\|[^\]]+)?\]\]", body))
    return {n.strip() for n in found if n.strip() and not n.startswith("tag_group:") and not n.startswith("help:")}


async def fetch_tags_info(session: aiohttp.ClientSession, names: List[str]) -> List[dict]:
    results = []
    chunk_size = 20
    for i in range(0, len(names), chunk_size):
        chunk = names[i:i + chunk_size]
        tasks = [_fetch_single_tag(session, name) for name in chunk]
        batch = await asyncio.gather(*tasks, return_exceptions=True)
        for item in batch:
            if isinstance(item, dict):
                results.append(item)
        await asyncio.sleep(0.15)
    return results


async def _fetch_single_tag(session: aiohttp.ClientSession, name: str) -> Optional[dict]:
    try:
        data = await _get_json(session, "/tags.json", {"search[name]": name, "limit": 1})
        if not data:
            return {"name": name, "post_count": 0, "category": 0}
        tag = data[0]
        return {
            "name": tag.get("name", name),
            "post_count": tag.get("post_count", 0),
            "category": tag.get("category", 0),
        }
    except Exception:
        return {"name": name, "post_count": 0, "category": 0}


async def get_group_tags_sorted(session: aiohttp.ClientSession, tag_group: str) -> List[dict]:
    cached = _cache_get(_group_cache, tag_group)
    if cached is not None:
        return cached

    await fetch_tag_group_members(session, tag_group)
    return _cache_get(_group_cache, tag_group) or []


async def fetch_wiki_summary(session: aiohttp.ClientSession, tag_name: str, max_len: int = 300) -> str:
    cached = _cache_get(_wiki_cache, tag_name)
    if cached is not None:
        return cached

    body = ""
    try:
        data = await _get_json(session, f"/wiki_pages/{quote(tag_name, safe='')}.json")
        body = (data.get("body") or "").strip()
        body = re.sub(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", r"\1", body)
        body = re.sub(r"\[section=([^\]]+)\]", r"\1: ", body)
        body = re.sub(r"\s+", " ", body)
    except Exception:
        body = ""

    if len(body) > max_len:
        body = body[: max_len - 1] + "…"
    _cache_set(_wiki_cache, tag_name, body)
    return body


def danbooru_post_url(tag_name: str) -> str:
    return f"{DANBOORU_BASE}/posts?tags={quote(tag_name.replace(' ', '_'))}"


def danbooru_wiki_url(tag_name: str) -> str:
    return f"{DANBOORU_BASE}/wiki_pages/{quote(tag_name.replace(' ', '_'))}"


async def fetch_sample_post(session: aiohttp.ClientSession, tag_name: str) -> Optional[dict]:
    """取该 tag 下一条代表性帖子，用于预览图。"""
    cache_key = tag_name.lower()
    cached = _cache_get(_post_preview_cache, cache_key)
    if cached is not None:
        return cached

    params = {
        "tags": tag_name.replace(" ", "_"),
        "limit": 1,
        "search[parent]": "false",
        "search[order]": "score",
    }
    try:
        posts = await _get_json(session, "/posts.json", params)
        if not posts:
            return None
        post = posts[0]
        info = {
            "id": post.get("id"),
            "preview_url": post.get("preview_file_url") or post.get("large_file_url") or post.get("file_url"),
            "post_url": f"{DANBOORU_BASE}/posts/{post.get('id')}",
        }
        if info.get("preview_url"):
            _cache_set(_post_preview_cache, cache_key, info)
        return info
    except Exception as e:
        print(f"⚠️ 获取 tag 预览图失败 ({tag_name}): {e}")
        return None


async def fetch_sample_posts_batch(session: aiohttp.ClientSession, tag_names: List[str]) -> Dict[str, dict]:
    if not tag_names:
        return {}
    results = await asyncio.gather(
        *[fetch_sample_post(session, name) for name in tag_names],
        return_exceptions=True,
    )
    out: Dict[str, dict] = {}
    for name, res in zip(tag_names, results):
        if isinstance(res, dict) and res.get("preview_url"):
            out[name] = res
    return out
