import json
import os
import re
from typing import Dict, List, Optional

TAG_CN_CACHE_FILE = os.getenv("TAG_CN_CACHE_FILE", "tag_cn_cache.json")
TAG_TRANSLATE_AI = os.getenv("TAG_TRANSLATE_AI", "true").lower() == "true"

_cn_cache: Dict[str, str] = {}
_reverse_cn_map: Dict[str, str] = {}
_initialized = False


def init_translator(chinese_tag_map: dict, knowledge_base_terms: dict):
    global _initialized, _reverse_cn_map
    _reverse_cn_map = {}
    for cn_label, en_tags in (chinese_tag_map or {}).items():
        for tag in en_tags:
            key = tag.strip().lower()
            if key and key not in _reverse_cn_map:
                _reverse_cn_map[key] = cn_label
    for term_lower, items in (knowledge_base_terms or {}).items():
        for item in items:
            trans = (item.get("translation") or "").strip()
            if trans:
                _reverse_cn_map.setdefault(term_lower, trans)
    _load_cache_file()
    _initialized = True


def _load_cache_file():
    global _cn_cache
    if not os.path.exists(TAG_CN_CACHE_FILE):
        _cn_cache = {}
        return
    try:
        with open(TAG_CN_CACHE_FILE, "r", encoding="utf-8") as f:
            _cn_cache = json.load(f)
    except Exception:
        _cn_cache = {}


def _save_cache_file():
    try:
        with open(TAG_CN_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_cn_cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ 无法写入 tag 汉化缓存: {e}")


def _normalize_key(tag_name: str) -> str:
    return tag_name.strip().lower().replace("_", " ")


def lookup_cn(tag_name: str) -> Optional[str]:
    key = _normalize_key(tag_name)
    if key in _cn_cache:
        return _cn_cache[key]
    if key in _reverse_cn_map:
        return _reverse_cn_map[key]
    alt = key.replace(" ", "_")
    if alt in _reverse_cn_map:
        return _reverse_cn_map[alt]
    return None


def format_tag_line(tag_name: str, post_count: int = 0, cn: Optional[str] = None) -> str:
    cn = cn or lookup_cn(tag_name)
    count_str = f"{post_count:,}" if post_count else "—"
    if cn:
        return f"**{cn}** · `{tag_name}` · {count_str} 帖"
    return f"`{tag_name}` · {count_str} 帖"


def format_tag_title(tag_name: str, cn: Optional[str] = None) -> str:
    cn = cn or lookup_cn(tag_name)
    if cn:
        return f"{cn} (`{tag_name}`)"
    return f"`{tag_name}`"


async def enrich_tags_cn(session_tags: List[dict], openai_client=None, model_name: Optional[str] = None) -> List[dict]:
    """为 tag 列表补充 cn 字段；缺译时可批量 AI 翻译并写入缓存。"""
    missing = []
    for tag in session_tags:
        name = tag.get("name", "")
        cn = lookup_cn(name)
        tag["cn"] = cn
        if not cn:
            missing.append(name)

    if not missing or not TAG_TRANSLATE_AI or not openai_client or not model_name:
        return session_tags

    chunk_size = 25
    for i in range(0, len(missing), chunk_size):
        chunk = missing[i:i + chunk_size]
        translated = await _ai_translate_batch(openai_client, model_name, chunk)
        for name, cn in translated.items():
            if cn:
                _cn_cache[_normalize_key(name)] = cn
        _save_cache_file()

    for tag in session_tags:
        if not tag.get("cn"):
            tag["cn"] = lookup_cn(tag.get("name", ""))
    return session_tags


async def _ai_translate_batch(client, model_name: str, tag_names: List[str]) -> Dict[str, str]:
    if not tag_names:
        return {}
    numbered = "\n".join(f"{i+1}. {n}" for i, n in enumerate(tag_names))
    prompt = (
        "你是 Danbooru 绘画 tag 汉化助手。把下列英文 tag 翻成简短中文释义（2-8 字为主，短语可用 4-12 字）。\n"
        "只输出 JSON 对象，键为原始英文 tag（与输入完全一致），值为中文。\n"
        f"Tag 列表：\n{numbered}"
    )
    try:
        resp = await client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
        if isinstance(data, dict) and "tags" in data and isinstance(data["tags"], dict):
            data = data["tags"]
        result = {}
        for name in tag_names:
            cn = data.get(name) or data.get(name.replace("_", " "))
            if isinstance(cn, str) and cn.strip():
                result[name] = cn.strip()
        return result
    except Exception as e:
        print(f"⚠️ tag AI 汉化失败: {e}")
        return {}
