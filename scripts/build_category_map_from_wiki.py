"""从 Danbooru tag_groups wiki 生成 danbooru_category_map.json"""
import asyncio
import json
import os
import re

import aiohttp
from dotenv import load_dotenv

load_dotenv()

WIKI_URL = "https://danbooru.donmai.us/wiki_pages/tag_groups.json"
OUT_FILE = "danbooru_category_map.json"

# h6 小节 → 大类（与 wiki 目录一致）
SECTION_TO_CATEGORY = {
    "image-style": ("visual", "画面与风格", "🎨"),
    "body": ("body", "身体", "👤"),
    "attire-accessories": ("attire", "服装与配饰", "👗"),
    "sex": ("sex", "Sex", "🔞"),
    "objects": ("objects", "物体", "📦"),
    "creatures": ("creatures", "生物", "🐾"),
    "plants": ("plants", "植物", "🌿"),
    "games": ("games", "游戏", "🎮"),
    "real-world": ("real_world", "现实", "🌍"),
    "more-1": ("more", "其他", "📎"),
    "genres": ("game_genres", "游戏类型", "🕹️"),
    "artists": ("artists", "画师与项目", "✏️"),
    "characters": ("characters", "角色列表", "👥"),
    "more-2": ("copyright_more", "版权与其他", "📋"),
    "metatags": ("metatags", "元标签", "🏷️"),
}

LINK_RE = re.compile(r"\[\[([^\]|#]+?)(?:\|[^\]]+)?\]\]")
SECTION_RE = re.compile(r"h6#([a-z0-9-]+)\.", re.I)


def wiki_title_to_slug(title: str) -> str:
    title = title.strip()
    lower = title.lower()
    if lower.startswith("tag group:"):
        slug = title.split(":", 1)[1].strip()
        return "tag_group:" + slug.replace(" ", "_").lower()
    if lower.startswith("list of "):
        slug = title[8:].strip().replace(" ", "_").lower()
        return "list_of_" + slug
    # 独立 tag/wiki 页（如 Eyebrows, Computer）
    return title.replace(" ", "_").lower()


def display_label(title: str) -> str:
    title = title.strip()
    if "|" in title:
        title = title.split("|", 1)[1]
    if title.lower().startswith("tag group:"):
        return title.split(":", 1)[1].strip()
    if title.lower().startswith("list of "):
        return title[8:].strip()
    return title


def slug_to_id(slug: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", slug.lower()).strip("_")[:48]


async def verify_wiki(session: aiohttp.ClientSession, slug: str, auth) -> bool:
    from urllib.parse import quote

    try:
        async with session.get(
            f"https://danbooru.donmai.us/wiki_pages/{quote(slug, safe='')}.json",
            auth=auth,
            proxy=os.getenv("HTTP_PROXY"),
            timeout=aiohttp.ClientTimeout(total=12),
        ) as r:
            return r.status == 200
    except Exception:
        return False


async def main():
    auth = None
    user = os.getenv("DANBOORU_API_USER", "").strip()
    key = os.getenv("DANBOORU_API_KEY", "").strip()
    if user and key:
        auth = aiohttp.BasicAuth(user, key)

    async with aiohttp.ClientSession() as session:
        async with session.get(WIKI_URL, auth=auth, proxy=os.getenv("HTTP_PROXY")) as r:
            data = await r.json()
        body = data.get("body", "")

    categories: dict[str, dict] = {}
    current_section = None

    for line in body.splitlines():
        sec = SECTION_RE.search(line)
        if sec:
            current_section = sec.group(1).lower()
            continue
        if current_section not in SECTION_TO_CATEGORY:
            continue
        for raw in LINK_RE.findall(line):
            raw = raw.strip()
            if raw.lower().startswith("see "):
                continue
            cat_id, cat_label, cat_icon = SECTION_TO_CATEGORY[current_section]
            slug = wiki_title_to_slug(raw)
            if cat_id not in categories:
                categories[cat_id] = {
                    "id": cat_id,
                    "label": cat_label,
                    "icon": cat_icon,
                    "children": [],
                }
            child_id = slug_to_id(slug)
            entry = {
                "id": child_id,
                "label": display_label(raw),
                "tag_group": slug if slug.startswith("tag_group:") else slug,
                "wiki_type": "tag_group" if slug.startswith("tag_group:") else (
                    "list" if slug.startswith("list_of_") else "wiki"
                ),
            }
            # 去重
            if any(c["id"] == child_id for c in categories[cat_id]["children"]):
                continue
            categories[cat_id]["children"].append(entry)

    # 按 wiki 目录顺序输出
    order = [v[0] for v in SECTION_TO_CATEGORY.values()]
    seen = set()
    cat_list = []
    for cid in order:
        if cid in categories and cid not in seen:
            cat_list.append(categories[cid])
            seen.add(cid)

    result = {"version": 3, "source": "danbooru wiki tag_groups", "categories": cat_list}
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    total = sum(len(c["children"]) for c in cat_list)
    print(f"Wrote {OUT_FILE}: {len(cat_list)} categories, {total} entries")


if __name__ == "__main__":
    asyncio.run(main())
