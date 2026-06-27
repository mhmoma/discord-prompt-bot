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
# 拉取逻辑变更时递增，避免旧错误缓存（如 post_count 全为 0）
_CACHE_VER = "v5"
TAGS_BULK_CHUNK = 100


def _normalize_tag_key(name: str) -> str:
    n = name.strip().lower()
    n = re.sub(r"\s+\(", "_(", n)
    return n.replace(" ", "_")


def _tag_name_candidates(wiki_label: str) -> List[str]:
    raw = wiki_label.strip()
    if not raw:
        return []
    seen: set[str] = set()
    out: List[str] = []

    def add(value: str):
        v = value.strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)

    add(raw)
    add(raw.replace(" ", "_"))
    add(re.sub(r"\s+\(", "_(", raw))
    add(_normalize_tag_key(raw))
    return out


def _tag_from_api_row(tag: dict) -> dict:
    return {
        "name": tag.get("name", ""),
        "post_count": tag.get("post_count", 0),
        "category": tag.get("category", 0),
    }


def _pick_best_tag_match(want: str, candidates: List[str], rows: List[dict]) -> Optional[dict]:
    if not rows:
        return None
    cand_lower = {c.lower() for c in candidates}
    cand_norm = {_normalize_tag_key(c) for c in candidates}
    exact: List[dict] = []
    normalized: List[dict] = []
    for tag in rows:
        tn = tag.get("name") or ""
        if tn.lower() in cand_lower:
            exact.append(tag)
        elif _normalize_tag_key(tn) in cand_norm:
            normalized.append(tag)
    pool = exact or normalized or rows
    artists = [t for t in pool if t.get("category") == 1]
    best = max(artists or pool, key=lambda t: t.get("post_count", 0))
    return _tag_from_api_row(best)

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
    key = f"{_CACHE_VER}:{key}"
    entry = store.get(key)
    if not entry:
        return None
    if time.time() - entry["fetched_at"] > DANBOORU_CACHE_TTL:
        store.pop(key, None)
        return None
    return entry.get("data") or entry.get("tags")


def _cache_set(store: dict, key: str, data, field="data"):
    key = f"{_CACHE_VER}:{key}"
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


async def fetch_tag_group_members(session: aiohttp.ClientSession, wiki_slug: str) -> List[str]:
    cached = _cache_get(_group_cache, wiki_slug)
    if cached is not None:
        return [t["name"] for t in cached]

    names = set()
    if wiki_slug.startswith("tag_group:"):
        page = 1
        while page <= 20:
            params = {
                "search[antecedent_name]": wiki_slug,
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
        wiki_names = await _parse_wiki_tag_links(session, wiki_slug)
        names.update(wiki_names)

    tag_list = sorted(names)
    if not tag_list:
        return []

    if wiki_slug.startswith("tag_group:") and names:
        infos = await _fetch_tags_bulk(session, tag_list)
    else:
        infos = await _fetch_tags_info_wiki(session, tag_list)
    infos.sort(key=lambda x: x.get("post_count", 0), reverse=True)
    _cache_set(_group_cache, wiki_slug, infos, field="tags")
    return [t["name"] for t in infos]


async def _parse_wiki_tag_links(session: aiohttp.ClientSession, wiki_slug: str) -> set[str]:
    try:
        data = await _get_json(session, f"/wiki_pages/{quote(wiki_slug, safe='')}.json")
    except Exception:
        return set()
    body = data.get("body") or ""
    found = set(re.findall(r"\[\[([^\]|#]+?)(?:\|[^\]]+)?\]\]", body))
    return {n.strip() for n in found if n.strip() and not n.startswith("tag_group:") and not n.startswith("help:")}


async def _fetch_tags_bulk(session: aiohttp.ClientSession, names: List[str]) -> List[dict]:
    """Danbooru 正式 tag 名批量查询（一次最多百条）。"""
    by_key: Dict[str, dict] = {}
    for i in range(0, len(names), TAGS_BULK_CHUNK):
        chunk = names[i:i + TAGS_BULK_CHUNK]
        comma = ",".join(chunk)
        try:
            data = await _get_json(
                session,
                "/tags.json",
                {"search[name_comma]": comma, "limit": len(chunk)},
            )
            for tag in data or []:
                row = _tag_from_api_row(tag)
                by_key[row["name"].lower()] = row
        except Exception as e:
            print(f"⚠️ 批量查 tag 失败 ({len(chunk)} 条): {e}")
        if i + TAGS_BULK_CHUNK < len(names):
            await asyncio.sleep(0.08)
    out: List[dict] = []
    for name in names:
        hit = by_key.get(name.lower())
        out.append(hit if hit else {"name": name, "post_count": 0, "category": 0})
    return out


async def _fetch_tags_info_wiki(session: aiohttp.ClientSession, names: List[str]) -> List[dict]:
    """wiki 可读名：先批量查归一化名，未命中再单条解析。"""
    norm_to_orig: Dict[str, str] = {}
    norm_names: List[str] = []
    for name in names:
        norm = _normalize_tag_key(name)
        if norm and norm not in norm_to_orig:
            norm_to_orig[norm] = name
            norm_names.append(norm)
    bulk_map = {t["name"].lower(): t for t in await _fetch_tags_bulk(session, norm_names)}

    out: List[dict] = []
    for name in names:
        norm = _normalize_tag_key(name)
        hit = bulk_map.get(norm)
        if hit and (hit.get("post_count", 0) > 0 or hit.get("category") == 1):
            out.append(hit)
            continue
        out.append(await _fetch_single_tag(session, name))
        await asyncio.sleep(0.05)
    return out


async def fetch_tags_info(session: aiohttp.ClientSession, names: List[str]) -> List[dict]:
    if not names:
        return []
    if _looks_canonical_tag_list(names):
        return await _fetch_tags_bulk(session, names)
    return await _fetch_tags_info_wiki(session, names)


def _looks_canonical_tag_list(names: List[str]) -> bool:
    """tag_group 成员多为下划线正式名，无空格。"""
    sample = names[: min(20, len(names))]
    if not sample:
        return True
    spaced = sum(1 for n in sample if " " in n)
    return spaced <= max(1, len(sample) // 10)


async def _fetch_single_tag(session: aiohttp.ClientSession, name: str) -> Optional[dict]:
    want = name.strip()
    if not want:
        return {"name": name, "post_count": 0, "category": 0}
    candidates = _tag_name_candidates(want)
    for query in candidates:
        try:
            data = await _get_json(
                session,
                "/tags.json",
                {"search[name_matches]": query, "limit": 20},
            )
            picked = _pick_best_tag_match(want, candidates, data or [])
            if picked and picked.get("name"):
                return picked
        except Exception:
            continue
    return {"name": want, "post_count": 0, "category": 0}


async def resolve_tag(session: aiohttp.ClientSession, name: str) -> dict:
    """wiki 显示名 → Danbooru 正式 tag 名 + post_count。"""
    return await _fetch_single_tag(session, name)


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


def _is_embeddable_image_url(url: str) -> bool:
    if not url:
        return False
    lower = url.lower().split("?")[0]
    return not lower.endswith((".mp4", ".webm", ".zip", ".swf"))


def _pick_post_image_url(post: dict) -> Optional[str]:
    """静图用 sample（约 850px）；视频/动图用预览帧 JPG。"""
    ext = (post.get("file_ext") or "").lower()
    if ext in ("webm", "mp4", "zip", "swf"):
        return post.get("preview_file_url")
    return post.get("large_file_url") or post.get("preview_file_url") or post.get("file_url")


def _post_to_preview_info(post: dict) -> Optional[dict]:
    image_url = _pick_post_image_url(post)
    if not image_url or not _is_embeddable_image_url(image_url):
        return None
    return {
        "id": post.get("id"),
        "score": post.get("score", 0),
        "fav_count": post.get("fav_count", 0),
        "tag_string": (post.get("tag_string") or "").strip(),
        "preview_url": image_url,
        "image_url": image_url,
        "post_url": f"{DANBOORU_BASE}/posts/{post.get('id')}",
    }


async def fetch_sample_post(session: aiohttp.ClientSession, tag_name: str) -> Optional[dict]:
    """取该 tag 下热度最高（score）帖：优先静图 sample，视频帖用预览帧。"""
    resolved = await _fetch_single_tag(session, tag_name)
    canonical = (resolved.get("name") or tag_name).strip()
    cache_key = canonical.lower()
    cached = _cache_get(_post_preview_cache, cache_key)
    if cached is not None:
        return cached

    safe_tag = canonical
    # Danbooru 非 Gold 最多 2 个 tag：词条 + order:score（不能再加 -parent）
    queries = [f"{safe_tag} order:score", safe_tag]
    try:
        for q in queries:
            try:
                posts = await _get_json(session, "/posts.json", {"tags": q, "limit": 10})
            except RuntimeError:
                continue
            if not posts:
                continue
            # 优先 score 最高的静图帖；全是视频则取第一条的预览帧
            fallback = None
            for post in posts:
                info = _post_to_preview_info(post)
                if not info:
                    continue
                ext = (post.get("file_ext") or "").lower()
                if ext not in ("webm", "mp4", "zip", "swf"):
                    _cache_set(_post_preview_cache, cache_key, info)
                    return info
                if fallback is None:
                    fallback = info
            if fallback:
                _cache_set(_post_preview_cache, cache_key, fallback)
                return fallback
        return None
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
