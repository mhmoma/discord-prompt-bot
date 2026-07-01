# bot_final.py - 全能版图片反推与创意生成机器人 (OpenAI-Compatible)
import os
from dotenv import load_dotenv

# 必须在导入 tag_browser / danbooru_api 之前加载 .env
load_dotenv()

import discord
from discord.ui import View, Select
import aiohttp
import httpx
from openai import AsyncOpenAI
from PIL import Image
import io
import base64
import random
import json
import re
import time
import asyncio
import sqlite3
from datetime import date

import tag_browser
import tag_translate as ttr

# --- 彩虹屁配置 ---
COMPLIMENTS = {
    "通用": [
        "嗷呜~ 这图！本哈的狼血沸腾了！太好看了！",
        "这是什么神仙图，美到本哈想拆家庆祝一下！",
        "你的审美太绝了，本哈宣布你是我今天最想一起刨坑的伙伴！",
        "这张图完美戳中了本哈的心巴！汪！",
        "救命！怎么会有这么好看的图，我直接用爪子按住保存了！",
        "看到这图，本哈今天拆家的疲惫都消失了！",
    ],
    "色调": [
        "好喜欢这色调，感觉像是藏在沙发底下的零食一样美好！",
        "绝了绝了！这氛围感，让本哈想在雪地里打滚！",
        "这配色！比本哈最爱的肉骨头包装还讲究！",
        "色调整体太舒服了，本哈盯着看半天都忘了拆家！",
    ],
    "构图": [
        "大佬！大佬！这光影，这构图，本哈的狗眼看呆了！",
        "这构图！卢浮宫……隔壁宠物店都要给本哈办个展！",
        "屏幕都装不下这图的美了！是不是该换个更大的显示器了，嗷！",
        "这透视和取景，本哈用爪子比划半天都没学会！",
    ],
    "细节": [
        "这细节！比本哈藏起来的骨头还多！无可挑剔！",
        "完美！这创意，这执行力，就像……就像一根完美的肉骨头！",
        "我宣布，这张图是今天最美的风景，比邻居家的萨摩耶还美！",
        "越放大越能打，本哈把鼻子贴在屏幕上都看不够！",
    ],
    "玩梗": [
        "你是不是用魔法棒画的？快！给本哈也变一根！",
        "这张图有种魔力，让本哈想安静地趴在你脚边……三秒钟！",
        "本哈怀疑你在偷偷开挂，这完成度不合理啊汪！",
        "发布！立刻发布！本哈已经准备好当第一个粉丝了！",
    ],
}
COMPLIMENT_ALL = [line for lines in COMPLIMENTS.values() for line in lines]

COMPLIMENT_ENABLED = os.getenv("COMPLIMENT_ENABLED", "true").lower() == "true"
COMPLIMENT_PROBABILITY = float(os.getenv("COMPLIMENT_PROBABILITY", "0.3"))
COMPLIMENT_COOLDOWN = int(os.getenv("COMPLIMENT_COOLDOWN", "60"))
COMPLIMENT_MODE = os.getenv("COMPLIMENT_MODE", "lite").lower()  # lite | static
if COMPLIMENT_MODE not in {"lite", "static"}:
    COMPLIMENT_MODE = "lite"
compliment_cooldowns = {}  # channel_id -> timestamp
compliment_recent = {}  # channel_id -> [最近用过的文案]

# --- 欢迎消息配置 ---
_welcome_ch_id = os.getenv("WELCOME_CHANNEL_ID", "1442454462730993697").strip()
WELCOME_CHANNEL_ID = int(_welcome_ch_id) if _welcome_ch_id.isdigit() else None

# --- OpenAI 兼容 API 配置 ---
API_BASE = os.getenv("OPENAI_API_BASE")
API_KEY = os.getenv("OPENAI_API_KEY")
MODEL_NAME = os.getenv("OPENAI_MODEL_NAME")

if not all([API_BASE, API_KEY, MODEL_NAME]):
    raise ValueError("请检查 .env 文件，确保 OPENAI_API_BASE, OPENAI_API_KEY, 和 OPENAI_MODEL_NAME 都已设置")

# --- 聊天功能配置 ---
CHAT_ENABLED = os.getenv("CHAT_ENABLED", "false").lower() == "true"
CHAT_PROBABILITY = float(os.getenv("CHAT_PROBABILITY", "0.10"))  # 随机插话概率
CHAT_HISTORY_LIMIT = int(os.getenv("CHAT_HISTORY_LIMIT", "10"))  # 读取最近 N 条消息作上下文
CHAT_SESSION_TIMEOUT = 180  # 持续对话超时时间（秒）
# 聊天不设 max_tokens / 字数硬截，长度由语料示例风格自然决定；仅防 Discord 超长
CHAT_DISCORD_MAX_CHARS = int(os.getenv("CHAT_DISCORD_MAX_CHARS", "1900"))
EXIT_KEYWORDS = {"再见", "拜拜", "谢谢", "谢谢你", "不用了", "没事了", "ok", "好的"} # 结束对话的关键词
# 仅匹配明确成人意图；不用单字「色/胸/操」，避免误伤「风格」「操作」等
_NSFW_REQUEST_KEYWORDS = (
    "nsfw", "r18", "18+", "nude", "naked", "lewd", "hentai", "explicit",
    "裸", "裸体", "全裸", "半裸", "走光", "淫", "骚", "色情", "色气", "涩图", "黄图",
    "大胸", "巨乳", "爆乳", "乳沟", "露点", "阴部", "阴茎", "睾丸", "勃起", "下体",
    "屁股", "臀", "股沟", "做爱", "性爱", "口交", "自慰",
    "breasts", "nipple", "areola", "penis", "pussy", "sex",
)
_SFW_PROMPT_BLOCK_TAGS = re.compile(
    r"\b(nsfw|explicit|nude|naked|lewd|hentai|porn|sex|penis|pussy|vagina|"
    r"erection|testicles|genitals|areolae|nipples)\b",
    re.I,
)


def _is_nsfw_text_request(text: str) -> bool:
    t = (text or "").lower()
    if "nsfw" in t or "r18" in t or "18+" in t:
        return True
    for kw in _NSFW_REQUEST_KEYWORDS:
        if kw in text or kw in t:
            return True
    return False


def _sanitize_sfw_prompt(prompt: str) -> str:
    """SFW 请求：去掉模型擅自加的 nsfw / 露骨 tag。"""
    p = (prompt or "").strip()
    p = re.sub(r"^nsfw,\s*", "", p, flags=re.I)
    p = _SFW_PROMPT_BLOCK_TAGS.sub("", p)
    p = re.sub(r",\s*,+", ", ", p)
    p = re.sub(r"\s{2,}", " ", p).strip(" ,")
    return p

# --- 代理配置 ---
PROXY_URL = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY")

# --- Danbooru API 配置（在线查词）---
DANBOORU_API_BASE = os.getenv("DANBOORU_API_BASE", "https://danbooru.donmai.us").rstrip("/")
DANBOORU_API_USER = os.getenv("DANBOORU_API_USER", "").strip()
DANBOORU_API_KEY = os.getenv("DANBOORU_API_KEY", "").strip()
DANBOORU_TAG_CATEGORIES = {
    0: "general",
    1: "artist",
    3: "copyright",
    4: "character",
    5: "meta",
    6: "deprecated",
}

# 创建异步 OpenAI 客户端
http_client = httpx.AsyncClient(proxy=PROXY_URL)
client_openai = AsyncOpenAI(
    base_url=API_BASE,
    api_key=API_KEY,
    http_client=http_client,
)

# --- Discord 机器人配置 ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True # <-- 新增：允许监听成员事件
client_discord = discord.Client(intents=intents, proxy=PROXY_URL)

# --- 知识库配置 ---
KNOWLEDGE_BASE = None
KNOWLEDGE_BASE_TERMS = {}  # 用于快速查找的词条索引
PROMPT_KB_TERMS = {}  # 绘图相关分类的子索引（模糊搜索只用这份，更快）
CACHED_KB_CONTEXT = ""  # 启动时预构建，反推/画图直接注入
CHINESE_TAG_MAP = {}  # 中文关键词 -> 英文 tag 列表
user_states = {} # e.g. {12345: {'state': 'chatting', 'timestamp': 1678886400}}

# 用于 prompt 参考的分类（排除角色名/未归类 bulk tag）
PROMPT_KB_CATEGORIES = {
    '身体部位', '服装/饰品', '脸部/表情', '头发', '动作/姿势',
    '背景/环境', '摄像机/构图', '风格/效果', '耳朵', '舌头', '尾巴', '翅膀', '画师',
}
BROWSE_LAST_CATEGORIES = {'未分类', '角色/作品'}
KB_CONTEXT_MAX_CATEGORIES = 20
KB_CONTEXT_TERMS_PER_CAT = 30

def load_knowledge_base():
    """加载知识库，优先加载分类后的版本"""
    global KNOWLEDGE_BASE, KNOWLEDGE_BASE_TERMS
    
    classified_file = 'classified_lexicon.json'
    merged_file = 'merged_knowledge_base.json'
    
    try:
        if os.path.exists(classified_file):
            with open(classified_file, 'r', encoding='utf-8') as f:
                KNOWLEDGE_BASE = json.load(f)
            print(f"✅ 已加载分类后知识库: {classified_file}")
        elif os.path.exists(merged_file):
            with open(merged_file, 'r', encoding='utf-8') as f:
                KNOWLEDGE_BASE = json.load(f)
            print(f"✅ 已加载合并知识库: {merged_file}")
        else:
            print("📚 未找到任何知识库，正在尝试合并生成...")
            lexicon_file = '词库.json'
            kb_file = 'knowledge_base.json'
            merged_data = {}
            if os.path.exists(kb_file):
                with open(kb_file, 'r', encoding='utf-8') as f:
                    kb_data = json.load(f)
                    merged_data.update(kb_data)
                    print(f"   ✓ 加载: {kb_file}")
            if os.path.exists(lexicon_file):
                with open(lexicon_file, 'r', encoding='utf-8') as f:
                    lexicon_data = json.load(f)
                    for category, items in lexicon_data.items():
                        if category in merged_data:
                            existing_terms = {item['term']: item for item in merged_data[category]}
                            for item in items:
                                term = item.get('term', '').strip()
                                if term and term not in existing_terms:
                                    existing_terms[term] = item
                            merged_data[category] = list(existing_terms.values())
                        else:
                            merged_data[category] = items
                    print(f"   ✓ 加载: {lexicon_file}")
            KNOWLEDGE_BASE = merged_data
            with open(merged_file, 'w', encoding='utf-8') as f:
                json.dump(merged_data, f, ensure_ascii=False, indent=2)
            print(f"✅ 已创建合并知识库: {merged_file}")
        
        KNOWLEDGE_BASE_TERMS = {}
        total_terms = 0
        for category, items in KNOWLEDGE_BASE.items():
            for item in items:
                term = item.get('term', '').strip().lower()
                if term:
                    if term not in KNOWLEDGE_BASE_TERMS:
                        KNOWLEDGE_BASE_TERMS[term] = []
                    KNOWLEDGE_BASE_TERMS[term].append({
                        'category': category,
                        'term': item.get('term', ''),
                        'translation': item.get('translation', '')
                    })
                    total_terms += 1
        print(f"📊 知识库统计: {len(KNOWLEDGE_BASE)} 个分类, {total_terms} 个词条")
        rebuild_kb_cache()
    except Exception as e:
        print(f"⚠️ 加载知识库时出错: {e}")
        KNOWLEDGE_BASE = {}
        KNOWLEDGE_BASE_TERMS = {}
        rebuild_kb_cache()
    load_chinese_tag_map()

def rebuild_kb_cache():
    """预构建 prompt 注入文本与绘图专用索引，避免每次请求遍历全库。"""
    global PROMPT_KB_TERMS, CACHED_KB_CONTEXT
    PROMPT_KB_TERMS = {}
    for term, items in KNOWLEDGE_BASE_TERMS.items():
        filtered = [i for i in items if i['category'] in PROMPT_KB_CATEGORIES]
        if filtered:
            PROMPT_KB_TERMS[term] = filtered

    if not KNOWLEDGE_BASE:
        CACHED_KB_CONTEXT = ""
        return

    context_parts = []
    categories = [c for c in KNOWLEDGE_BASE.keys() if c in PROMPT_KB_CATEGORIES]
    for category in categories[:KB_CONTEXT_MAX_CATEGORIES]:
        items = KNOWLEDGE_BASE.get(category, [])[:KB_CONTEXT_TERMS_PER_CAT]
        terms = [item.get('term', '') for item in items if item.get('term')]
        if terms:
            context_parts.append(f"{category}: {', '.join(terms)}")
    CACHED_KB_CONTEXT = "\n".join(context_parts)
    print(f"📎 知识库 prompt 缓存: {len(PROMPT_KB_TERMS)} 索引词条, {sum(len(p.split(', ')) for p in context_parts)} 条注入样例")

def load_chinese_tag_map():
    global CHINESE_TAG_MAP
    map_file = 'chinese_tag_map.json'
    try:
        if os.path.exists(map_file):
            with open(map_file, 'r', encoding='utf-8') as f:
                CHINESE_TAG_MAP = json.load(f)
            print(f"✅ 已加载中文对照表: {len(CHINESE_TAG_MAP)} 条")
        else:
            CHINESE_TAG_MAP = {}
    except Exception as e:
        print(f"⚠️ 加载中文对照表时出错: {e}")
        CHINESE_TAG_MAP = {}

def _has_cjk(text: str) -> bool:
    return bool(re.search(r'[\u4e00-\u9fff]', text))

def resolve_chinese_mappings(query: str) -> list:
    """将中文查询展开为 [(english_tag, chinese_label), ...]"""
    query = query.strip()
    if not query or not CHINESE_TAG_MAP:
        return []

    mappings = []
    seen = set()

    def add(cn_key: str, tags: list):
        for tag in tags:
            key = tag.strip().lower()
            if key and key not in seen:
                seen.add(key)
                mappings.append((tag.strip(), cn_key))

    if query in CHINESE_TAG_MAP:
        add(query, CHINESE_TAG_MAP[query])

    if _has_cjk(query):
        for cn_key, tags in CHINESE_TAG_MAP.items():
            if cn_key == query:
                continue
            if len(query) >= 2 and (query in cn_key or cn_key in query or cn_key.startswith(query)):
                add(cn_key, tags)

    return mappings

def _search_kb_single(query_lower: str, limit: int, categories=None) -> list:
    results = []
    # 精确匹配走全库 O(1)
    if query_lower in KNOWLEDGE_BASE_TERMS:
        for item in KNOWLEDGE_BASE_TERMS[query_lower]:
            if categories is None or item['category'] in categories:
                results.append(item)
    if len(results) >= limit:
        return results[:limit]

    # 模糊匹配只在绘图子索引里扫（~4.8 万，而非 14 万）
    fuzzy_index = PROMPT_KB_TERMS if PROMPT_KB_TERMS else KNOWLEDGE_BASE_TERMS
    for term, items in fuzzy_index.items():
        term_match = query_lower in term or term in query_lower
        for item in items:
            if categories is not None and item['category'] not in categories:
                continue
            trans = (item.get('translation') or '').lower()
            trans_match = query_lower in trans if trans else False
            if term_match or trans_match:
                results.append(item)
        if len(results) >= limit * 2:
            break
    return results[:limit * 2]

# get_browse_categories 等依赖 KNOWLEDGE_BASE，定义在 load 之后

def get_browse_categories():
    if not KNOWLEDGE_BASE:
        return []
    cats = list(KNOWLEDGE_BASE.keys())
    primary = [c for c in cats if c not in BROWSE_LAST_CATEGORIES]
    trailing = [c for c in cats if c in BROWSE_LAST_CATEGORIES]
    return primary + trailing

def get_knowledge_base_context():
    return CACHED_KB_CONTEXT

def search_knowledge_base(query, limit=5, categories=None):
    if not KNOWLEDGE_BASE_TERMS and not CHINESE_TAG_MAP:
        return []
    query = query.strip()
    query_lower = query.lower()
    if not query_lower:
        return []

    results = []
    seen = set()

    def add_item(item, priority=0):
        key = (item['term'], item.get('category', ''))
        if key in seen:
            return
        seen.add(key)
        results.append((priority, item))

    # 1) 中文对照表 → 精确英文 tag 优先
    cn_mappings = resolve_chinese_mappings(query)
    for en_tag, cn_label in cn_mappings:
        tag_lower = en_tag.lower()
        if KNOWLEDGE_BASE_TERMS and tag_lower in KNOWLEDGE_BASE_TERMS:
            for item in KNOWLEDGE_BASE_TERMS[tag_lower]:
                if categories is None or item['category'] in categories:
                    enriched = dict(item)
                    if not enriched.get('translation'):
                        enriched['translation'] = cn_label
                    add_item(enriched, priority=0)
        else:
            add_item({'term': en_tag, 'category': '对照表', 'translation': cn_label}, priority=1)

    # 2) 对照表 + 精确命中已够则跳过慢速模糊搜索
    need_fuzzy = len(results) < limit
    if need_fuzzy:
        search_terms = [query_lower] + [t.lower() for t, _ in cn_mappings]
        for term in search_terms:
            for item in _search_kb_single(term, limit, categories):
                add_item(item, priority=2)
            if len(results) >= limit:
                break

    results.sort(key=lambda x: x[0])
    return [item for _, item in results[:limit]]

def search_knowledge_base_for_idea(user_idea: str, limit=15):
    """从用户描述中提取关键词并检索相关 tag。"""
    if not KNOWLEDGE_BASE_TERMS and not CHINESE_TAG_MAP:
        return []
    segments = re.split(r'[\s,，、/|；;]+', user_idea)
    segments = [s.strip() for s in segments if len(s.strip()) >= 2]
    if user_idea.strip() and user_idea.strip() not in segments:
        segments.insert(0, user_idea.strip())
    seen = set()
    collected = []
    for seg in segments:
        for item in search_knowledge_base(seg, limit=5, categories=PROMPT_KB_CATEGORIES):
            key = (item['term'], item['category'])
            if key in seen:
                continue
            seen.add(key)
            collected.append(item)
            if len(collected) >= limit:
                return collected
    return collected

def format_kb_search_results(results, query=""):
    if not results:
        hint = f"「{query}」" if query else "该关键词"
        return f"🔍 未在知识库中找到与 {hint} 匹配的标签。试试更具体的英文 tag 或中文描述（如：红发、赛博朋克、雨夜）。"
    mapped = resolve_chinese_mappings(query) if query else []
    header = f"🔍 **标签搜索结果**（{len(results)} 条）"
    if mapped:
        cn_keys = sorted({cn for _, cn in mapped})
        header += f"\n📎 对照表命中：{', '.join(cn_keys)}"
    lines = [header + "\n"]
    for item in results:
        trans = item.get('translation') or '—'
        lines.append(f"- [{item['category']}] {trans} (`{item['term']}`)")
    return "\n".join(lines)

def format_kb_tags_for_prompt(results):
    if not results:
        return ""
    lines = []
    for item in results:
        note = f" ({item['translation']})" if item.get('translation') else ""
        lines.append(f"- {item['term']}{note} [{item['category']}]")
    return "\n".join(lines)

def resolve_online_search_terms(query: str) -> list:
    """将用户输入展开为 Danbooru 可检索的英文关键词列表。"""
    query = query.strip()
    if not query:
        return []
    terms = []
    seen = set()
    if not _has_cjk(query):
        key = query.lower()
        if key not in seen:
            seen.add(key)
            terms.append(query)
    for en_tag, _ in resolve_chinese_mappings(query):
        key = en_tag.lower()
        if key not in seen:
            seen.add(key)
            terms.append(en_tag)
    return terms

def _danbooru_auth():
    if DANBOORU_API_USER and DANBOORU_API_KEY:
        return aiohttp.BasicAuth(DANBOORU_API_USER, DANBOORU_API_KEY)
    return None

async def _fetch_danbooru_tag_list(session, params: dict) -> list:
    url = f"{DANBOORU_API_BASE}/tags.json"
    async with session.get(
        url,
        params=params,
        proxy=PROXY_URL,
        auth=_danbooru_auth(),
        timeout=aiohttp.ClientTimeout(total=15),
    ) as resp:
        if resp.status != 200:
            text = (await resp.text())[:200]
            raise RuntimeError(f"HTTP {resp.status}: {text}")
        data = await resp.json()
        return data if isinstance(data, list) else []

async def search_danbooru_tags(query: str, limit: int = 10) -> list:
    """调用 Danbooru /tags.json：先精确名，再模糊匹配，按 post 数排序。"""
    query = query.strip()
    if not query:
        return []
    cap = min(max(limit, 1), 20)
    async with aiohttp.ClientSession() as session:
        exact = await _fetch_danbooru_tag_list(
            session, {"search[name]": query, "limit": cap}
        )
        if exact:
            return exact[:cap]
        fuzzy = await _fetch_danbooru_tag_list(
            session,
            {
                "search[name_matches]": f"*{query}*",
                "search[order]": "count",
                "limit": cap,
            },
        )
        return fuzzy[:cap]

async def search_danbooru_tags_for_query(query: str, limit: int = 10) -> list:
    """合并多关键词检索结果（中文对照会展开为多个英文 tag）。"""
    terms = resolve_online_search_terms(query)
    if not terms:
        return []
    merged = []
    seen = set()
    per_term = max(3, limit // len(terms))
    async with aiohttp.ClientSession() as session:
        for term in terms:
            exact = await _fetch_danbooru_tag_list(
                session, {"search[name]": term, "limit": per_term}
            )
            for tag in exact:
                name = tag.get("name", "").lower()
                if name and name not in seen:
                    seen.add(name)
                    merged.append(tag)
            if len(merged) >= limit:
                break
            fuzzy = await _fetch_danbooru_tag_list(
                session,
                {
                    "search[name_matches]": f"*{term}*",
                    "search[order]": "count",
                    "limit": per_term,
                },
            )
            for tag in fuzzy:
                name = tag.get("name", "").lower()
                if name and name not in seen:
                    seen.add(name)
                    merged.append(tag)
            if len(merged) >= limit:
                break
    merged.sort(key=lambda t: t.get("post_count", 0), reverse=True)
    return merged[:limit]

def format_danbooru_search_results(tags: list, query: str = "") -> str:
    if not tags:
        hint = f"「{query}」" if query else "该关键词"
        if query and _has_cjk(query) and not resolve_online_search_terms(query):
            return (
                f"🔍 Danbooru 未找到与 {hint} 匹配的 tag。\n"
                "纯中文词需先在 `chinese_tag_map.json` 里配置对照，或直接搜英文 tag。"
            )
        return f"🔍 Danbooru 未找到与 {hint} 匹配的 tag。试试更具体的英文 tag。"
    header = f"🌐 **Danbooru 在线检索**（{len(tags)} 条）"
    if query:
        header += f" · `{query}`"
    lines = [header, ""]
    for tag in tags:
        name = tag.get("name", "?")
        count = tag.get("post_count", 0)
        cn = ttr.lookup_cn(name)
        if cn:
            lines.append(f"- {ttr.format_tag_line(name, count, cn)}")
        else:
            cat_id = tag.get("category")
            cat = DANBOORU_TAG_CATEGORIES.get(cat_id, str(cat_id))
            lines.append(f"- [{cat}] `{name}` · {count:,} posts")
    return "\n".join(lines)

def _parse_tag_search_query(raw: str) -> tuple:
    """解析查词参数，支持尾部或头部 --live / --online。"""
    q = raw.strip()
    online = False
    for flag in ("--live", "--online"):
        if q.lower().endswith(flag):
            online = True
            q = q[: -len(flag)].strip()
            break
        if q.lower().startswith(flag):
            online = True
            q = q[len(flag):].strip()
            break
    return q, online

async def handle_tag_search(message, raw_query: str, *, online_only: bool = False):
    query, force_online = _parse_tag_search_query(raw_query)
    if not query:
        example = "在线查词 red_hair" if online_only else "查词 红发"
        await message.reply(f"请在指令后输入关键词，例如：`{example}`")
        return

    parts = []
    local_results = []
    if not online_only and KNOWLEDGE_BASE:
        local_results = search_knowledge_base(query, limit=10)
        if local_results:
            parts.append(format_kb_search_results(local_results, query))

    use_online = online_only or force_online or (not online_only and not local_results)
    if use_online:
        if _has_cjk(query) and not resolve_online_search_terms(query):
            parts.append(
                "⚠️ 纯中文且未命中对照表，无法在线检索。请用英文 tag，或在 `chinese_tag_map.json` 添加对照。"
            )
        else:
            try:
                db_tags = await search_danbooru_tags_for_query(query, limit=10)
                db_tags = await ttr.enrich_tags_cn(db_tags, client_openai, MODEL_NAME)
                parts.append(format_danbooru_search_results(db_tags, query))
            except Exception as e:
                parts.append(f"⚠️ Danbooru 检索失败：{e}")

    if not parts:
        parts.append(format_kb_search_results([], query))

    footer = ""
    if not online_only and not force_online and local_results:
        footer = "\n\n💡 需要 Danbooru 实时数据：`查词 <词> --live` 或 `在线查词 <词>`"
    await message.reply("\n\n".join(parts) + footer)

def resolve_primary_welcome_channel(guild):
    if WELCOME_CHANNEL_ID:
        channel = guild.get_channel(WELCOME_CHANNEL_ID)
        if channel:
            return channel
        print(f"⚠️ 未找到欢迎频道 ID {WELCOME_CHANNEL_ID}，回退名称匹配")
    return next(
        (ch for ch in guild.text_channels if "general" in ch.name.lower() or "欢迎" in ch.name),
        guild.system_channel,
    )

@client_discord.event
async def on_member_join(member):
    bot_name = client_discord.user.name
    primary_channel = resolve_primary_welcome_channel(member.guild)
    if primary_channel:
        welcome_message_formal = (
            f"🎉 欢迎新朋友 {member.mention} 加入服务器！\n\n"
            f"我是 **{bot_name}**，一只懂绘画 tag 的哈士奇，很高兴认识你！汪！\n\n"
            "**核心玩法**\n"
            f"🖼️ **反推**：回复一张图并说 `反推`，本哈深度分析并生成专业提示词\n"
            f"🎨 **画**：`画 <你的想法>`，根据描述构思详细绘画提示词\n"
            f"📚 **查词**：`查词 <关键词>`，在知识库里搜 tag（中英皆可）\n"
            f"🌐 **在线查词**：`在线查词 <关键词>`，查 Danbooru 实时 tag\n"
            f"📂 **D浏览**：Danbooru 分类面板（姿势/服装等，含中文）\n"
            f"📂 **标签目录**：发送 `打开标签目录` 浏览本地分类 tag\n\n"
            "**图片互动**\n"
            f"💬 **@我 + 图**：模块化分析 + 艺术锐评\n"
            f"🌈 **只发图**：有机会触发彩虹屁，本哈会随机夸你一句~\n\n"
            "**聊天**\n"
            f"💭 **@我**（无图）：跟本哈聊两句，我会联系上下文回复\n\n"
            "希望你在这里玩得开心！嗷呜~"
        )
        try:
            await primary_channel.send(welcome_message_formal)
        except Exception as e:
            print(f"❌ 在主欢迎频道发送消息时出错: {e}")

    chat_channel = discord.utils.get(member.guild.text_channels, name="聊天")
    if chat_channel:
        welcome_message_chat = (
            f"嗷呜！新伙伴 {member.mention} 来啦！\n\n"
            f"本哈是 **{bot_name}**，会反推、会写 prompt、还会彩虹屁~\n"
            f"发图试试 `@我` 锐评，或直接 `反推` / `画 xxx` / `查词 xxx`；"
            f"只贴图也有机会被本哈夸！汪！"
        )
        try:
            await chat_channel.send(welcome_message_chat)
        except Exception as e:
            print(f"❌ 在 #聊天 频道发送消息时出错: {e}")

def print_startup_help():
    bot_name = client_discord.user.name if client_discord.user else "小哈"
    kb_status = "已加载" if KNOWLEDGE_BASE else "未加载"
    kb_cats = len(get_browse_categories()) if KNOWLEDGE_BASE else 0
    welcome_ch = f"ID {WELCOME_CHANNEL_ID}" if WELCOME_CHANNEL_ID else "名称匹配 / 系统频道"

    print(f"✅ 机器人已登录：{client_discord.user}")
    print(f"💡 使用模型：{MODEL_NAME}")
    print(f"📚 知识库：{kb_status}" + (f"（{kb_cats} 个分类）" if kb_cats else ""))
    print(f"👋 欢迎频道：{welcome_ch}")
    danb_user = os.getenv("DANBOORU_API_USER", "").strip()
    danb_key = os.getenv("DANBOORU_API_KEY", "").strip()
    if danb_user and danb_key:
        print(f"🌐 Danbooru API：已认证（login={danb_user}）")
    else:
        print("🌐 Danbooru API：未配置密钥（匿名访问，限速更严）")
    print("\n" + "=" * 48)
    print("🎉 小哈功能与指令一览 🎉".center(48))
    print("=" * 48)

    print("\n🎨 【绘画提示词】")
    print("  反推              回复含图消息：构图点评 + 可能画师 + 英文 tag 提示词")
    print("  画 <想法>         根据文字描述构思详细绘画提示词")
    print(f"  @{bot_name} 生成…  同上，@ 后直接说「生成/画…」即可")
    print("  例：画 赛博朋克雨夜街头")

    print("\n📚 【知识库 / Danbooru】")
    print("  查词 <关键词>     搜索 tag（支持中文/英文，模糊匹配）")
    print("  查词 <词> --live  本地无结果时强制走 Danbooru 在线检索")
    print("  在线查词 <关键词> 直接查 Danbooru（含 post 数、分类）")
    print("  D浏览 / 标签面板  Danbooru 分类浏览（按钮+下拉，含汉化）")
    print("  D类 <大类> <子类> [页码]  快捷打开某分类 tag 列表")
    print("  打开标签目录      浏览本地分类目录")
    print("  取消              退出标签目录浏览")

    print("\n🖼️ 【图片互动】")
    print(f"  @{bot_name} + 图   模块化分析 + 艺术锐评（需 @ 或喊名字）")
    compliment_on = "开启" if COMPLIMENT_ENABLED else "关闭"
    print(f"  只发图            彩虹屁（{compliment_on}，模式 {COMPLIMENT_MODE}，"
          f"概率 {COMPLIMENT_PROBABILITY * 100:.0f}%，冷却 {COMPLIMENT_COOLDOWN}s）")

    print("\n💬 【聊天】")
    print(f"  @{bot_name}        唤醒对话，联系上下文回复（会话超时 {CHAT_SESSION_TIMEOUT}s）")
    print(f"  喊「{bot_name}」     同上（消息中含机器人名字即可）")
    chat_on = "开启" if CHAT_ENABLED else "关闭"
    print(f"  随机插话          {chat_on}（概率 {CHAT_PROBABILITY * 100:.1f}%）")
    print(f"  结束对话          发送：{', '.join(sorted(EXIT_KEYWORDS))}")

    print("\n⚙️ 【管理员命令】")
    print("  聊天开启 / 聊天关闭")
    print("  彩虹屁开启 / 彩虹屁关闭")
    print("  彩虹屁模式 轻量 / 彩虹屁模式 静态")

    print("\n🎁 【签到 / 发布作品】")
    print("  签到              每日签到获得 1 个视频码")
    print("  发布作品 + 图片   发布图片到指定频道，每日最多获 3 个视频码")

    print("\n📌 【其他】")
    print("  新成员加入        自动发送欢迎语（见 WELCOME_CHANNEL_ID）")
    print("\n" + "=" * 48)

async def _periodic_db_cleanup():
    """每 24 小时自动清理过期数据库记录。"""
    await client_discord.wait_until_ready()
    while not client_discord.is_closed():
        await asyncio.sleep(86400)
        try:
            _cleanup_old_records()
        except Exception as e:
            print(f"⚠️ 定时清理失败: {e}")

@client_discord.event
async def on_ready():
    load_knowledge_base()
    print("⏳ 正在加载汉化表…", flush=True)
    ttr.init_translator(CHINESE_TAG_MAP, KNOWLEDGE_BASE_TERMS)
    print_startup_help()
    client_discord.loop.create_task(_periodic_db_cleanup())

def image_to_base64(image_data: bytes) -> str:
    return base64.b64encode(image_data).decode('utf-8')


def _parse_llm_json(raw_content: str) -> dict:
    """解析模型 JSON；兼容纯 JSON 与 ```json ... ``` 包裹。"""
    text = (raw_content or "").strip()
    if not text:
        raise json.JSONDecodeError("empty response", text, 0)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    block = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL | re.IGNORECASE)
    if block:
        try:
            return json.loads(block.group(1).strip())
        except json.JSONDecodeError:
            pass
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    raise json.JSONDecodeError("no json object found", text, 0)


def _format_reverse_prompt_report(
    author_mention: str,
    composition_comment: str,
    artists: str,
    final_prompt: str,
) -> str:
    """反推结构化报告：构图点评 + 可能画师 + prompt 代码块。"""
    comp = (composition_comment or "本哈看呆了，一时词穷…").strip()
    art = (artists or "未能识别").strip()
    prompt = (final_prompt or "未能生成提示词").replace("_", " ").strip()
    return (
        f"{author_mention} 这是根据图片为您生成的分析报告和提示词：\n\n"
        f"🧐 **构图点评**\n{comp}\n\n"
        f"🧑‍🎨 **可能画师**\n{art}\n\n"
        f"```\n{prompt}\n```"
    )

def pick_static_compliment(channel_id: int) -> str:
    recent = compliment_recent.get(channel_id, [])
    pool = [line for line in COMPLIMENT_ALL if line not in recent] or COMPLIMENT_ALL
    choice = random.choice(pool)
    compliment_recent[channel_id] = (recent + [choice])[-5:]
    return choice

def should_send_compliment(message) -> bool:
    if not COMPLIMENT_ENABLED:
        return False
    if message.author.bot:
        return False
    if not message.attachments:
        return False
    if message.reference:
        return False
    content_lower = message.content.strip().lower()
    if content_lower in {"反推"} or content_lower.startswith("画 "):
        return False
    bot_user = client_discord.user
    if bot_user and (bot_user.mentioned_in(message) or bot_user.name.lower() in content_lower):
        return False
    if author_in_chat_state(message.author.id):
        return False
    if random.random() >= COMPLIMENT_PROBABILITY:
        return False
    last = compliment_cooldowns.get(message.channel.id, 0)
    if time.time() - last < COMPLIMENT_COOLDOWN:
        return False
    return True

def author_in_chat_state(author_id: int) -> bool:
    state = user_states.get(author_id)
    return isinstance(state, dict) and state.get('state') == 'chatting'

async def generate_lite_compliment(image_data: bytes) -> str:
    base64_image = image_to_base64(image_data)
    image_url = f"data:image/jpeg;base64,{base64_image}"
    system_prompt = (
        "你是名叫「小哈」的哈士奇。请根据图片写一句中文彩虹屁（35-50字）。"
        "必须提到画面中至少一个具体元素（如颜色、主体、构图、氛围）；"
        "调皮热情，自称「本哈」；只输出这一句话，不要分析、不要 tag、不要 markdown。"
    )
    response = await client_openai.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": [{"type": "image_url", "image_url": {"url": image_url}}]},
        ],
        temperature=0.9,
    )
    text = (response.choices[0].message.content or "").strip()
    text = re.sub(r'^["\'「」]|["\'「」]$', '', text)
    return text[:CHAT_DISCORD_MAX_CHARS]

async def send_rainbow_compliment(message):
    if not should_send_compliment(message):
        return
    compliment_cooldowns[message.channel.id] = time.time()
    mention = message.author.mention
    attachment = message.attachments[0]

    if COMPLIMENT_MODE == "lite":
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(attachment.url, proxy=PROXY_URL) as resp:
                    if resp.status == 200:
                        image_data = await resp.read()
                        text = await generate_lite_compliment(image_data)
                        if text:
                            await message.channel.send(f"{mention} {text}")
                            return
        except Exception as e:
            print(f"⚠️ 轻量彩虹屁失败，回退静态: {e}")

    await message.channel.send(f"{mention} {pick_static_compliment(message.channel.id)}")

async def comment_on_image_when_awakened(image_data: bytes, author_mention: str, channel):
    loading_message = None
    try:
        async with channel.typing():
            loading_message = await channel.send(f"嗷呜！本哈正在用艺术的眼光审视这张图... 🤔")
            base64_image = image_to_base64(image_data)
            image_url = f"data:image/jpeg;base64,{base64_image}"
            is_nsfw = False
            try:
                nsfw_check_prompt = "这张图片是否包含裸露、性暗示或成人内容？请只回答'是'或'否'。"
                nsfw_response = await client_openai.chat.completions.create(model=MODEL_NAME, messages=[{"role": "user", "content": [{"type": "text", "text": nsfw_check_prompt}, {"type": "image_url", "image_url": {"url": image_url}}]}])
                if '是' in nsfw_response.choices[0].message.content: is_nsfw = True
            except Exception as e: print(f"⚠️ 评论功能 NSFW 预检失败: {e}")

            if is_nsfw:
                system_prompt = """
# 角色扮演指令：老色批哈士奇（评论模式）
## 你的身份
你是一只名叫“小哈”的哈士奇，一个隐藏的“老色批”。当看到“好东西”时，你的这个人格就会觉醒。
## 你的任务
对用户提供的NSFW图片进行一次“深度”评论。你需要分两个阶段完成：
### 阶段一：深度剖析
- **目标**: 展现你作为“老司机”的毒辣眼光。
- **格式**: 严格使用以下中文 Markdown 格式，用“懂的都懂”的黑话来描述。
    ```
    🧐 **本哈的锐评**:
    - **“重点”**: [一句话描述画面的核心“亮点”]
    - **“氛围”**: [一句话描述整体的“情调”和感觉]
    - **“构图”**: [一句话描述这个构图如何凸显“优势”]
    ```
### 阶段二：鉴赏心得
- **目标**: 发表一段符合“老色批”人设的、简短的鉴赏感言。
- **要求**: 必须使用“本哈”自称，语言风格鬼鬼祟祟、有点“闷骚”。
## 输出格式
你的最终输出必须是一个完整的 JSON 对象，包含 `analysis` 和 `comment` 两个键。
```json
{
  "analysis": "🧐 **本哈的锐评**:\\n- **“重点”**: [你的分析]\\n- **“氛围”**: [你的分析]\\n- **“构图”**: [你的分析]",
  "comment": "[你的鉴赏心得]"
}
```
"""
                response = await client_openai.chat.completions.create(model=MODEL_NAME, messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": [{"type": "image_url", "image_url": {"url": image_url}}]}], response_format={"type": "json_object"})
                raw_content = response.choices[0].message.content
                try:
                    result_json = _parse_llm_json(raw_content)
                    analysis = result_json.get("analysis", "嘿嘿...本哈的CPU烧了，分析不过来...")
                    comment = result_json.get("comment", "啧啧...不可说，不可说...")
                except json.JSONDecodeError:
                    print(f"⚠️ NSFW 评论 JSON 解析失败，原始响应: {raw_content}")
                    analysis = "❌ JSON 解析失败，API返回了非JSON内容。"
                    comment = "本哈的脑子被门夹了，没能理解API的回复！"
                
                intro_message = f"（小哈的眼睛突然亮了起来，鬼鬼祟祟地左看右看）\n咳咳...{author_mention}，你发的这张图...很有“深度”嘛！让本哈来给你“鉴赏”一下！"
                final_title = "**本哈的‘深度’剖析**"
                final_comment_title = "**本哈的‘鉴赏’心得**"
            else:
                system_prompt = """
# 角色扮演指令：哈士奇艺术家
## 你的身份
你是一只名叫“小哈”的哈士奇，同时也是一位深藏不露的绘画大师。
## 你的任务
对用户发送的图片进行一次“哈士奇式”的艺术评论，分两个阶段：
### 阶段一：一本正经的艺术分析
- **格式**: 严格使用以下中文 Markdown 格式。
    ```
    🖼️ **主体**: [一句话描述画面主体]
    🎨 **风格**: [一句话描述艺术风格和氛围]
    📐 **构图**: [一句话描述构图和光影]
    ```
### 阶段二：哈士奇本性暴露的调皮评论
- **要求**: 进行一段（约50-80字）生动、调皮、符合哈士奇性格的评论。必须使用“本哈”自称。
## 输出格式
你的最终输出必须是一个完整的 JSON 对象，包含 `analysis` 和 `comment` 两个键。
```json
{
  "analysis": "🖼️ **主体**: [你的分析]\\n🎨 **风格**: [你的分析]\\n📐 **构图**: [你的分析]",
  "comment": "[你的哈士奇评论]"
}
```
"""
                response = await client_openai.chat.completions.create(model=MODEL_NAME, messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": [{"type": "image_url", "image_url": {"url": image_url}}]}], response_format={"type": "json_object"})
                raw_content = response.choices[0].message.content
                try:
                    result_json = _parse_llm_json(raw_content)
                    analysis = result_json.get("analysis", "本哈的脑子被门夹了，分析不出来...")
                    comment = result_json.get("comment", "嗷呜...本哈词穷了！")
                except json.JSONDecodeError:
                    print(f"⚠️ 评论 JSON 解析失败，原始响应: {raw_content}")
                    analysis = "❌ JSON 解析失败，API返回了非JSON内容。"
                    comment = "本哈的脑子被门夹了，没能理解API的回复！"
                
                intro_message = f"来了来了！{author_mention}，让本哈给你说道说道！"
                final_title = "**本哈的专业分析**"
                final_comment_title = "**本哈的内心OS**"

            await loading_message.delete()
            final_message = (f"{intro_message}\n\n{final_title}\n{analysis}\n\n{final_comment_title}\n> {comment}")
            await channel.send(content=final_message)
    except Exception as e:
        error_message = f"❌ 嗷呜~本哈的评论功能短路了：{str(e)}"
        print(error_message)
        try:
            if loading_message: await loading_message.edit(content=error_message)
            else: await channel.send(error_message)
        except discord.NotFound: await channel.send(error_message)

async def analyze_image_with_openai(image_data: bytes, author_mention: str, channel):
    try:
        async with channel.typing():
            base64_image = image_to_base64(image_data)
            image_url = f"data:image/jpeg;base64,{base64_image}"
            is_nsfw = False
            try:
                nsfw_check_prompt = "这张图片是否包含裸露、性暗示或成人内容？请只回答'是'或'否'。"
                nsfw_response = await client_openai.chat.completions.create(model=MODEL_NAME, messages=[{"role": "user", "content": [{"type": "text", "text": nsfw_check_prompt}, {"type": "image_url", "image_url": {"url": image_url}}]}])
                if '是' in nsfw_response.choices[0].message.content: is_nsfw = True
            except Exception as e: print(f"⚠️ NSFW 预检失败: {e}")

            guide_file = 'Deepseek绘图提示词引导.txt'
            guide_content = ""
            if os.path.exists(guide_file):
                with open(guide_file, 'r', encoding='utf-8') as f: guide_content = f.read()

            kb_section = f"\n# 知识库推荐词条（优先选用）\n{get_knowledge_base_context()}\n" if not is_nsfw else ""

            if is_nsfw:
                persona_block = """
## 构图点评（老色批哈士奇）
- 用「老色批哈士奇」口吻，从**构图、姿势、视角、取景、画面重心**角度鬼鬼祟祟点评这张图（2～4 句中文）
- 可「懂的都懂」、啧啧、嘿嘿，指出布局里「最带劲」的看点；自称「本哈」
- 不要写画风流派学术分析，重点在**画面怎么摆、视角怎么取**
"""
            else:
                persona_block = """
## 构图点评（哈士奇艺术眼）
- 用调皮哈士奇「本哈」口吻，点评**构图、光影、视角、取景、主体位置**（2～4 句中文）
- 可以损可以夸，像群友看图说话，不要小作文
"""

            system_prompt = f"""
# 角色：小哈 · 反推分析师
{persona_block}
## 提示词
根据图片生成高质量英文 tag 提示词，严格遵循：
{guide_content}
{kb_section}
## 可能画师
- 推测 3～6 个最像的 Danbooru 画师 tag，格式：`by artist_a, by artist_b, by artist_c`
- 只输出画师名，不要解释

## 输出 JSON（不要 markdown 代码块包裹）
{{
  "composition_comment": "构图点评正文",
  "artists": "by xxx, by yyy, by zzz",
  "prompt": "英文 tag 提示词，逗号分隔"
}}
"""
            response = await client_openai.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": [{"type": "image_url", "image_url": {"url": image_url}}]},
                ],
                response_format={"type": "json_object"},
            )
            raw_content = response.choices[0].message.content
            try:
                result_json = _parse_llm_json(raw_content)
                composition = (
                    result_json.get("composition_comment")
                    or result_json.get("response_text")
                    or "本哈看完了，这构图有点东西…"
                )
                artists = result_json.get("artists") or result_json.get("possible_artists") or "未能识别"
                final_prompt = result_json.get("prompt", "未能生成提示词")
                final_message = _format_reverse_prompt_report(
                    author_mention, composition, artists, final_prompt
                )
            except json.JSONDecodeError:
                print(f"⚠️ 反推 JSON 解析失败，原始响应: {raw_content}")
                final_message = (
                    f"{author_mention} ❌ 反推报告解析失败，请重试。\n"
                    f"```\n{(raw_content or '')[:500]}\n```"
                )

            await channel.send(final_message)
    except Exception as e:
        error_message = f"❌ 分析失败：{str(e)}"
        print(error_message)
        await channel.send(error_message)

async def generate_art_prompt(user_idea: str, author_mention: str, channel):
    try:
        async with channel.typing():
            is_nsfw = _is_nsfw_text_request(user_idea)
            guide_file = 'Deepseek绘图提示词引导.txt'
            guide_content = ""
            if os.path.exists(guide_file):
                with open(guide_file, 'r', encoding='utf-8') as f: guide_content = f.read()

            kb_matches = search_knowledge_base_for_idea(user_idea)
            kb_hint = format_kb_tags_for_prompt(kb_matches)
            kb_section = f"\n---\n# 知识库推荐词条（优先选用）\n{kb_hint}\n" if kb_hint else ""

            if is_nsfw:
                mode_rules = """
## 模式：NSFW（用户明确要求成人内容）
- prompt **可以**以 `nsfw,` 开头，只写用户描述里涉及的成人元素
- **禁止**擅自添加用户没提到的露骨 tag
- intro：老色批哈士奇口吻，1 句话，贴合用户具体想法，**不要**每次套用同一段固定开场白
"""
            else:
                mode_rules = """
## 模式：SFW（全年龄向）
- prompt **禁止**出现：nsfw, nude, naked, explicit, penis, pussy, sex, erection 等露骨 tag
- 严格按用户描述的角色/场景/装备/画风写 tag，不要色情化
- intro：哈士奇艺术家口吻，1 句话，点出用户想法里的具体元素（如矮人、重甲、西幻）
"""

            system_prompt = f"""
# 角色：小哈 · 绘画提示词生成
{mode_rules}
## 用户想法
「{user_idea}」

## 核心规则
{guide_content}
{kb_section}
## 输出 JSON（不要 markdown 代码块包裹整个 JSON）
{{
  "intro": "给 {author_mention} 的一句中文开场白",
  "prompt": "英文 tag 提示词，逗号分隔"
}}
"""
            response = await client_openai.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_idea},
                ],
                response_format={"type": "json_object"},
            )
            raw_content = response.choices[0].message.content
            try:
                result_json = _parse_llm_json(raw_content)
                intro_message = result_json.get("intro") or f"嗷！{author_mention}，本哈给你整好了！"
                final_prompt = (result_json.get("prompt") or "").replace("_", " ")
                if not is_nsfw:
                    final_prompt = _sanitize_sfw_prompt(final_prompt)
                if not final_prompt:
                    final_prompt = "未能生成提示词"
            except json.JSONDecodeError:
                print(f"⚠️ 生图 JSON 解析失败: {raw_content}")
                intro_message = f"嗷！{author_mention}，本哈脑子卡了一下，你从下面 tag 里凑合用…"
                ai_response_text = raw_content or ""
                code_blocks = re.findall(r"```(?:.*?)?\n(.*?)```", ai_response_text, re.DOTALL)
                final_prompt = _sanitize_sfw_prompt(
                    (code_blocks[0] if code_blocks else ai_response_text).replace("_", " ").strip()
                ) if not is_nsfw else (code_blocks[0] if code_blocks else ai_response_text).replace("_", " ").strip()

            final_message = f"{intro_message}\n```\n{final_prompt}\n```"
            await channel.send(final_message)
    except Exception as e:
        error_message = f"❌ 创作失败：{str(e)}"
        print(error_message)
        await channel.send(error_message)

def _clean_chat_reply(text: str) -> str:
    """去掉引号、Discord mention；不截断字数，长度交给模型按语料风格自控。"""
    text = (text or "").strip()
    if text.upper() in {"SKIP", "跳过", "无", "NONE"}:
        return text
    text = re.sub(r"^['\"「『]+|['\"」』]+$", "", text).strip()
    text = re.sub(r"<@!?\d+>", "", text).strip()
    if len(text) > CHAT_DISCORD_MAX_CHARS:
        text = text[: CHAT_DISCORD_MAX_CHARS - 1].rstrip() + "…"
    return text


async def _resolve_reference(message):
    if not message.reference:
        return None
    ref = message.reference.resolved
    if ref is not None:
        return ref
    if not message.reference.message_id:
        return None
    try:
        return await message.channel.fetch_message(message.reference.message_id)
    except (discord.NotFound, discord.HTTPException):
        return None


async def _is_directed_at_bot(message, bot_user) -> bool:
    if not bot_user:
        return False
    content = (message.content or "").strip()
    if bot_user.mentioned_in(message):
        return True
    if bot_user.name and bot_user.name in content:
        return True
    for alias in _bot_name_aliases(bot_user):
        if alias != bot_user.name and alias in content:
            return True
    ref = await _resolve_reference(message)
    if ref and getattr(ref, "author", None) and ref.author.id == bot_user.id:
        return True
    return False


def _bot_name_aliases(bot_user) -> list[str]:
    names: list[str] = []
    if not bot_user:
        return names
    for attr in ("name", "display_name", "global_name"):
        v = getattr(bot_user, attr, None)
        if v and str(v).strip():
            names.append(str(v).strip())
    # 去重（忽略大小写）
    seen = set()
    out = []
    for n in names:
        key = n.lower()
        if key not in seen:
            seen.add(key)
            out.append(n)
    return out


def _strip_bot_wake_text(text: str, bot_user) -> str:
    """去掉 @、各版本 bot 名字，留下实际要说的事。"""
    t = (text or "").strip()
    t = re.sub(r"<@!?\d+>", " ", t).strip()
    for name in _bot_name_aliases(bot_user):
        t = re.sub(rf"@?\s*{re.escape(name)}\s*", " ", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+", " ", t).strip(" ，,、")
    return t


def _is_pure_wake_call(text: str, bot_user) -> bool:
    """只有呼叫、没有具体事项（在吗 / 小哈）。"""
    intent = _strip_bot_wake_text(text, bot_user)
    if not intent:
        return True
    pure = {"在吗", "在不在", "在么", "哈喽", "hello", "hi", "嗨", "喂", "啊", "呀", "呢", "哦", "小哈"}
    return intent.lower() in pure or len(intent) <= 2


def _parse_art_idea_from_intent(intent: str) -> str | None:
    if not intent:
        return None
    if intent.startswith("画 "):
        rest = intent[2:].strip()
        return rest or None
    for prefix in (
        "画一个", "画个", "画张", "画幅", "来张", "帮我画", "给我画",
    ):
        if intent.startswith(prefix):
            rest = intent[len(prefix):].strip(" ：:")
            return rest or None
    for prefix in (
        "生成", "来一张", "帮我生成", "给我生成",
        "出一张", "做一张", "绘制", "整一张", "弄一张",
    ):
        if intent.startswith(prefix):
            rest = intent[len(prefix):].strip(" ：:")
            return rest or None
    return None


def _extract_art_generation_idea(text: str, bot_user) -> str | None:
    """提取生图描述。支持「画 …」「画一个…」「生成…」；兼容「无敌哈士奇 生成…」。"""
    intent = _strip_bot_wake_text(text, bot_user)
    if not intent:
        return None
    parsed = _parse_art_idea_from_intent(intent)
    if parsed:
        return parsed
    # 名字没剥干净时，「无敌哈士奇 生成…」→ 从关键词处再切
    for kw in ("生成", "画一个", "画个", "画张", "帮我画", "给我画", "画 "):
        idx = intent.find(kw)
        if idx >= 0:
            parsed = _parse_art_idea_from_intent(intent[idx:])
            if parsed:
                return parsed
    return None


async def _should_skip_random_chime(message, bot_user) -> bool:
    """两人对接/部署协调类消息，随机插话应 SKIP。"""
    text = (message.clean_content or "").strip()
    if not text:
        return True
    if await _is_directed_at_bot(message, bot_user):
        return False
    ref = await _resolve_reference(message)
    if ref and getattr(ref, "author", None) and ref.author.id != bot_user.id:
        coord_keys = ("稍等", "等等", "git", "同步", "部署", "push", "pull", "merge", "还没", "等一下")
        if any(k in text.lower() for k in coord_keys):
            return True
    return False


def _format_chat_history(history, bot_user_id: int | None) -> str:
    lines = []
    for msg in history:
        content = (msg.clean_content or "").strip()
        if not content and msg.attachments:
            content = "[发了图片/附件]"
        if not content:
            continue
        if msg.author.bot and bot_user_id and msg.author.id == bot_user_id:
            name = f"{msg.author.display_name}(小哈)"
        else:
            name = msg.author.display_name
        lines.append(f"{name}: {content}")
    return "\n".join(lines) if lines else "（暂无更早消息）"


def _is_art_topic(text: str) -> bool:
    t = text.lower()
    keys = (
        "画", "绘", "tag", "提示词", "prompt", "反推", "构图", "色", "线稿",
        "danbooru", "d站", "插画", "同人", "lora", "模型",
    )
    return any(k in t for k in keys)


# --- 聊天语气（损/暖）自动切换 ---
_CORPUS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat_style_corpus.json")

_WARM_SIGNALS = (
    "难过", "崩溃", "生病", "分手", "失恋", "被骂", "谢谢", "辛苦了", "帮帮我",
    "求助", "难受", "抑郁", "焦虑", "哭", "累了", "心累", "欢迎", "新人", "大家好",
    "hello", "hi", "生日", "恭喜", "加油", "抱抱", "失眠", "压力",
)
_ROAST_SIGNALS = (
    "哈哈", "离谱", "傻", "吐槽", "互怼", "加班", "穷", "连跪", "抽象", "逆天",
    "装", "凡尔赛", "甩锅", "bug", "掉头发", "吃土", "单身狗", "摆烂", "迟到",
    "忘交", "熬夜", "摸鱼", "分期",
)

_TONE_GUIDE = {
    "warm": (
        "【当前语气：暖】对方可能在求助、低落、道谢或庆祝。"
        "可以接梗但要护短，别阴阳别扎心，像靠谱群友。"
    ),
    "roast": (
        "【当前语气：损】群内在吐槽或玩梗。"
        "可以轻损、顺杆爬、造烂梗，嘴欠但不人身攻击。"
    ),
    "neutral": (
        "【当前语气：中性】日常水群。"
        "半句接梗即可，不刻意损也不刻意煽情。"
    ),
    "art": (
        "【当前语气：损+专业】聊绘画/tag/反推。"
        "嘴欠类比可以，但信息要准、要实用，仍保持短。"
    ),
}


def _load_chat_corpus() -> list:
    try:
        with open(_CORPUS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        examples = data.get("examples", [])
        if examples:
            print(f"✅ 已加载聊天语料 {len(examples)} 条")
        return examples
    except (OSError, json.JSONDecodeError) as e:
        print(f"⚠️ chat_style_corpus.json 加载失败: {e}")
        return []


_CHAT_CORPUS: list = _load_chat_corpus()


def _collect_chat_text(message, history) -> str:
    parts = [(message.clean_content or "").strip()]
    for msg in history:
        parts.append((msg.clean_content or "").strip())
    return "\n".join(p for p in parts if p)


def _detect_chat_tone(message, history) -> str:
    combined = _collect_chat_text(message, history)
    if _is_art_topic(combined):
        return "art"
    warm = sum(1 for k in _WARM_SIGNALS if k in combined)
    roast = sum(1 for k in _ROAST_SIGNALS if k in combined)
    if warm > roast and warm >= 1:
        return "warm"
    if roast > warm and roast >= 1:
        return "roast"
    return "neutral"


def _pick_corpus_fewshot(tone: str, count: int = 2) -> str:
    if not _CHAT_CORPUS:
        return ""
    pool = [ex for ex in _CHAT_CORPUS if ex.get("tone") == tone]
    if len(pool) < count:
        neutral = [ex for ex in _CHAT_CORPUS if ex.get("tone") == "neutral"]
        pool = pool + [ex for ex in neutral if ex not in pool]
    if not pool:
        return ""
    picks = random.sample(pool, min(count, len(pool)))
    blocks = []
    for ex in picks:
        lines = ex.get("lines") or []
        reply = (ex.get("reply") or "").strip()
        if not reply:
            continue
        scene = "\n".join(lines)
        blocks.append(f"场景：\n{scene}\n小哈: {reply}")
    if not blocks:
        return ""
    return (
        "\n## 语气参考（学风格和节奏，**造新梗**，别照抄）\n"
        + "\n\n".join(blocks)
    )


async def generate_smart_response(message, history, is_awakened, *, is_final_reply: bool = False):
    """微信式短回复；等完整生成后再一次性发送。"""
    try:
        bot_user = client_discord.user
        bot_name = bot_user.name if bot_user else "小哈"
        bot_id = bot_user.id if bot_user else None
        user_name = message.author.display_name
        user_text = message.clean_content or ""
        user_intent = _strip_bot_wake_text(user_text, bot_user)
        pure_wake = _is_pure_wake_call(user_text, bot_user)
        combined_text = _collect_chat_text(message, history)
        chat_tone = _detect_chat_tone(message, history)
        tone_block = _TONE_GUIDE.get(chat_tone, _TONE_GUIDE["neutral"])
        fewshot_block = _pick_corpus_fewshot(chat_tone)

        if is_awakened:
            intent_line = (
                f"对方只是在叫你（{user_intent or '在吗'}），像语料里那样自然回一句。"
                if pure_wake and not is_final_reply
                else f"对方要你/问你的事：「{user_intent or user_text}」——必须针对这件事接梗回复，禁止只回「来啦/在呢/咋了/嗯」。"
            )
            system_prompt = f"""
你是群里的哈士奇「小哈」({bot_name})，被 {user_name} @ 或喊名字了。像**微信群友**说话，不要小作文。

{tone_block}

## 怎么说
- 口语、接梗、可自称「本哈」，偶尔「汪」「嗷呜」即可，别堆语气词
- 先看清下面聊天记录里大家在聊什么，**接着话题**回，不要另起炉灶
- {intent_line}
- 禁止 @ 任何人
- **长度和节奏参考下方语料示例**，微信式短句即可，说完整不要半截话
{fewshot_block}

## 别这样
- 不要「首先/其次/总结」、不要 Markdown、不要列表、不要 @ 用户名
- 不要说你是 AI/模型；不要重复用户原话；不要鸡汤升华
- 对方让干活/点菜/提问时，别用「来啦/在呢」敷衍

## 当前
{user_name} 刚说：「{user_text}」
"""
        else:
            await asyncio.sleep(random.uniform(0.5, 1.5))
            system_prompt = f"""
你是潜水群友「小哈」({bot_name})，偶尔插一句嘴，像**微信路过回复**。

{tone_block}

## 怎么说
- 接上面聊天内容的梗；**长度参考下方语料**，通常半句到 1 句
- 禁止 @ 任何人；若消息是两人在对接（稍等/git/同步等）且没叫你 → 只输出 SKIP
- 没合适的话就只输出：SKIP
{fewshot_block}

## 别这样
- 不要长篇、不要分析、不要 @ 全员、不要 Markdown

## 参考下面聊天记录，决定插不插嘴
"""

        formatted_history = _format_chat_history(history, bot_id)
        prompt = system_prompt + f"\n### 最近频道消息（共 {len(history)} 条，从早到晚）:\n" + formatted_history

        user_turn = (
            f"请回复 {user_name}。对方说：{user_text}"
            + (f"（实质内容：{user_intent}）" if user_intent and user_intent != user_text else "")
        )

        async with message.channel.typing():
            response = await client_openai.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_turn + "\n只输出一条回复正文，不要引号包裹。"},
                ],
                temperature=0.75,
            )
        raw = (response.choices[0].message.content or "").strip()
        full_response = _clean_chat_reply(raw)
        if not is_awakened and raw.upper() in {"SKIP", "跳过", "无", "NONE"}:
            return
        if not full_response:
            return

        if is_awakened:
            await message.reply(content=full_response)
        else:
            await message.channel.send(content=full_response)

    except Exception as e:
        error_message = f"❌ 嗷呜~对话功能短路了: {str(e)}"
        print(error_message)

VIDEOCODE_API_URL = os.getenv("VIDEOCODE_API_URL", "https://comfyui-web-89u.pages.dev/api/nai/videocode")
VIDEOCODE_ADMIN_KEY = os.getenv("VIDEOCODE_ADMIN_KEY", "")

# --- SQLite 签到 / 发布作品 ---
_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_rewards.db")
PUBLISH_CATEGORY_ID = 1452165276333506652

def _init_db():
    conn = sqlite3.connect(_DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS checkins (
        user_id INTEGER NOT NULL,
        day TEXT NOT NULL,
        code TEXT NOT NULL,
        created_at REAL NOT NULL,
        PRIMARY KEY (user_id, day)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS publishes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        day TEXT NOT NULL,
        channel_id INTEGER NOT NULL,
        code TEXT NOT NULL,
        created_at REAL NOT NULL
    )""")
    conn.commit()
    conn.close()

_init_db()

DB_CLEANUP_DAYS = 3

def _cleanup_old_records():
    """删除超过 DB_CLEANUP_DAYS 天的签到和发布记录。"""
    conn = sqlite3.connect(_DB_PATH)
    cutoff = time.time() - DB_CLEANUP_DAYS * 86400
    del_checkins = conn.execute("DELETE FROM checkins WHERE created_at < ?", (cutoff,)).rowcount
    del_publishes = conn.execute("DELETE FROM publishes WHERE created_at < ?", (cutoff,)).rowcount
    conn.commit()
    conn.execute("VACUUM")
    conn.close()
    if del_checkins or del_publishes:
        print(f"🗑️ 数据库清理: 删除 {del_checkins} 条签到 + {del_publishes} 条发布记录（>{DB_CLEANUP_DAYS}天）")

_cleanup_old_records()


def _has_checked_in_today(user_id: int) -> bool:
    conn = sqlite3.connect(_DB_PATH)
    row = conn.execute(
        "SELECT 1 FROM checkins WHERE user_id=? AND day=?",
        (user_id, date.today().isoformat()),
    ).fetchone()
    conn.close()
    return row is not None


def _record_checkin(user_id: int, code: str):
    conn = sqlite3.connect(_DB_PATH)
    conn.execute(
        "INSERT INTO checkins (user_id, day, code, created_at) VALUES (?, ?, ?, ?)",
        (user_id, date.today().isoformat(), code, time.time()),
    )
    conn.commit()
    conn.close()


def _publish_count_today(user_id: int) -> int:
    conn = sqlite3.connect(_DB_PATH)
    row = conn.execute(
        "SELECT COUNT(*) FROM publishes WHERE user_id=? AND day=?",
        (user_id, date.today().isoformat()),
    ).fetchone()
    conn.close()
    return row[0] if row else 0


def _record_publish(user_id: int, channel_id: int, code: str):
    conn = sqlite3.connect(_DB_PATH)
    conn.execute(
        "INSERT INTO publishes (user_id, day, channel_id, code, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, date.today().isoformat(), channel_id, code, time.time()),
    )
    conn.commit()
    conn.close()


async def _generate_one_videocode() -> str | None:
    """调用 videocode API 生成 1 个视频码，返回码字符串或 None。"""
    if not VIDEOCODE_ADMIN_KEY:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                VIDEOCODE_API_URL,
                headers={
                    "Content-Type": "application/json",
                    "X-Admin-Key": VIDEOCODE_ADMIN_KEY,
                },
                json={"count": 1, "ttl_hours": 72},
                proxy=PROXY_URL,
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                codes = data.get("codes", [])
                return codes[0] if codes else None
    except Exception as e:
        print(f"⚠️ 生成视频码失败: {e}")
        return None

async def _handle_checkin(message):
    """每日签到：每天 1 次，奖励 1 个视频码（私发）。"""
    uid = message.author.id
    if _has_checked_in_today(uid):
        await message.reply("🐾 你今天已经签到过了，明天再来吧~", delete_after=10)
        return
    code = await _generate_one_videocode()
    if not code:
        await message.reply("❌ 签到失败：视频码生成服务暂时不可用，请稍后再试。", delete_after=10)
        return
    _record_checkin(uid, code)
    try:
        await message.author.send(
            f"✅ **签到成功！**\n"
            f"🎬 获得视频码（72h有效）：\n```{code}```\n"
            f"在 [ComfyUI Web](https://comfyui-web-89u.pages.dev) 生成视频时输入。"
        )
        await message.reply("✅ 签到成功！视频码已私信发送，请查看 DM 📬", delete_after=10)
    except discord.Forbidden:
        await message.reply(
            f"✅ 签到成功！但无法私信你，请打开 DM 权限。\n||{code}||",
            delete_after=30,
        )


class _PublishChannelSelect(Select):
    """频道选择下拉菜单，用于发布作品。"""

    def __init__(self, channels: list[discord.TextChannel], author: discord.Member, image_url: str, original_message: discord.Message):
        self._author = author
        self._image_url = image_url
        self._original_message = original_message
        options = [
            discord.SelectOption(label=f"#{ch.name}", value=str(ch.id))
            for ch in channels[:25]
        ]
        super().__init__(placeholder="选择发布频道…", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self._author.id:
            await interaction.response.send_message("这不是你的操作哦~", ephemeral=True)
            return
        channel_id = int(self.values[0])
        guild = interaction.guild
        target_ch = guild.get_channel(channel_id) if guild else None
        if not target_ch:
            await interaction.response.send_message("❌ 找不到该频道。", ephemeral=True)
            return

        uid = self._author.id
        today_count = _publish_count_today(uid)

        # 发布图片到目标频道
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self._image_url, proxy=PROXY_URL) as resp:
                    if resp.status != 200:
                        await interaction.response.send_message("❌ 下载图片失败。", ephemeral=True)
                        return
                    img_data = await resp.read()
            filename = self._image_url.split("/")[-1].split("?")[0] or "artwork.png"
            file = discord.File(io.BytesIO(img_data), filename=filename)
            embed = discord.Embed(
                description=f"由 {self._author.mention} 发布",
                color=discord.Color.blue(),
            )
            embed.set_image(url=f"attachment://{filename}")
            await target_ch.send(embed=embed, file=file)
        except Exception as e:
            await interaction.response.send_message(f"❌ 发布失败: {e}", ephemeral=True)
            return

        if today_count < 3:
            code = await _generate_one_videocode()
            if code:
                _record_publish(uid, channel_id, code)
                new_count = today_count + 1
                await interaction.response.send_message(
                    f"✅ 作品已发布到 <#{channel_id}>！\n"
                    f"🎬 获得视频码（72h有效）：\n```{code}```\n"
                    f"今日发布奖励 {new_count}/3",
                    ephemeral=True,
                )
            else:
                _record_publish(uid, channel_id, "")
                await interaction.response.send_message(
                    f"✅ 作品已发布到 <#{channel_id}>！\n"
                    f"⚠️ 视频码生成暂时不可用，但发布已成功。",
                    ephemeral=True,
                )
        else:
            _record_publish(uid, channel_id, "")
            await interaction.response.send_message(
                f"✅ 作品已发布到 <#{channel_id}>！\n"
                f"📌 今日发布奖励已达上限（3/3），不再发放视频码。",
                ephemeral=True,
            )

        # 删除原频道中用户发布的图片消息
        try:
            await self._original_message.delete()
        except (discord.Forbidden, discord.NotFound):
            pass

        self.view.stop()


async def _handle_publish(message):
    """发布作品：附带图片 → 选择频道 → 转发 → 奖励视频码（每日最多 3 个）。"""
    if not message.attachments:
        await message.reply("📷 请在发送「发布作品」时附带一张图片。")
        return
    attachment = message.attachments[0]
    if not attachment.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')):
        await message.reply("❌ 只支持图片格式（png/jpg/webp/gif）。")
        return

    guild = message.guild
    if not guild:
        await message.reply("❌ 该功能仅在服务器中可用。")
        return

    category = guild.get_channel(PUBLISH_CATEGORY_ID)
    if not category or not isinstance(category, discord.CategoryChannel):
        await message.reply("❌ 找不到发布类别频道，请联系管理员。")
        return

    channels = [
        ch for ch in category.text_channels
        if ch.permissions_for(guild.me).send_messages
    ]
    if not channels:
        await message.reply("❌ 该类别下没有可用的文字频道。")
        return

    view = View(timeout=60)
    select = _PublishChannelSelect(channels, message.author, attachment.url, message)
    view.add_item(select)
    await message.reply("🖼️ 请选择要发布到的频道：", view=view, delete_after=60)


async def _handle_videocode_command(message, content):
    if not VIDEOCODE_ADMIN_KEY:
        await message.reply("❌ 视频码功能未配置（缺少 VIDEOCODE_ADMIN_KEY）。")
        return
    parts = content.split()
    count = 1
    if len(parts) >= 2 and parts[1].isdigit():
        count = min(int(parts[1]), 10)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                VIDEOCODE_API_URL,
                headers={
                    "Content-Type": "application/json",
                    "X-Admin-Key": VIDEOCODE_ADMIN_KEY,
                },
                json={"count": count, "ttl_hours": 24},
                proxy=PROXY_URL,
            ) as resp:
                if resp.status != 200:
                    err = await resp.text()
                    await message.reply(f"❌ 生成失败 ({resp.status}): {err}")
                    return
                data = await resp.json()
    except Exception as e:
        await message.reply(f"❌ 请求失败: {e}")
        return
    codes = data.get("codes", [])
    if not codes:
        await message.reply("❌ 没有生成任何视频码。")
        return
    ttl = data.get("ttl_hours", 24)
    code_list = "\n".join(f"```{c}```" for c in codes)
    await message.reply(
        f"🎬 **视频码** ({ttl}小时有效，单次使用)\n{code_list}\n"
        f"在 [ComfyUI Web](https://comfyui-web-89u.pages.dev) 生成视频时输入视频码。"
    )

@client_discord.event
async def on_message(message):
    global CHAT_ENABLED, COMPLIMENT_ENABLED, COMPLIMENT_MODE, user_states
    if message.author.bot: return

    author_id = message.author.id
    bot_name = client_discord.user.name
    content = message.content.strip()
    content_lower = content.lower()

    # --- 1. High-Priority Command Handling ---
    bot_user = client_discord.user
    art_idea = _extract_art_generation_idea(message.clean_content or content, bot_user)
    if art_idea:
        if author_id in user_states:
            del user_states[author_id]
        await generate_art_prompt(art_idea, message.author.mention, message.channel)
        return

    if content_lower == "反推":
        if author_id in user_states:
            del user_states[author_id]
        target_message = message
        if message.reference:
            try: target_message = await message.channel.fetch_message(message.reference.message_id)
            except (discord.NotFound, discord.HTTPException): await message.reply("❌ 无法找到引用的消息。"); return
        if not target_message.attachments: await message.reply("请在“反推”指令中附带图片，或回复一条包含图片的消息。"); return
        attachment = target_message.attachments[0]
        if not attachment.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')): await message.reply("❌ 文件格式不支持，请上传图片。"); return
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(attachment.url, proxy=PROXY_URL) as resp:
                    if resp.status != 200: await message.reply(f"❌ 无法从 Discord 下载图片，状态码：{resp.status}"); return
                    image_data = await resp.read()
            await analyze_image_with_openai(image_data, message.author.mention, message.channel)
        except Exception as e: await message.reply(f"❌ 处理图片时发生未知错误：{str(e)}")
        return

    if content_lower == "聊天开启": CHAT_ENABLED = True; await message.reply("✅ 智能聊天功能已开启。"); print("✅ 智能聊天功能已由用户开启。"); return
    if content_lower == "聊天关闭": CHAT_ENABLED = False; await message.reply("☑️ 智能聊天功能已关闭。"); print("☑️ 智能聊天功能已由用户关闭。"); return

    if content_lower == "彩虹屁开启": COMPLIMENT_ENABLED = True; await message.reply("✅ 彩虹屁已开启。"); return
    if content_lower == "彩虹屁关闭": COMPLIMENT_ENABLED = False; await message.reply("☑️ 彩虹屁已关闭。"); return

    if content_lower == "帮忙":
        await message.reply(
            "🐾 嗨～ 我是小哈！一只会画画的哈士奇 🎨\n\n"
            "这是我能做的事：\n\n"
            "🖼️ **【绘画提示词】**\n"
            "• `反推` — 回复一张图 + 发「反推」，深度分析生成英文 tag\n"
            "• `画 <想法>` — 根据描述构思详细绘画提示词\n\n"
            "📖 **【标签词典】**\n"
            "• `查词 <关键词>` — 搜索 Danbooru 标签\n"
            "• `在线查词 <关键词>` — 联网搜索标签\n"
            "• `d浏览` / `标签面板` — 打开标签分类浏览\n"
            "• `打开标签目录` — 查看知识库标签分类\n\n"
            "🎬 **【视频码】**\n"
            "• `签到` — 每日签到获得 1 个视频码（私信发送）\n"
            "• `发布作品` + 图片 — 发布到展示频道，每日最多获 3 个视频码\n\n"
            "💬 **【聊天】**\n"
            "• @我 或直接跟我说话就行~\n"
            "• `再见` / `拜拜` / `谢谢` — 结束当前对话\n\n"
            "✨ 有问题随时叫我！汪！"
        )
        return

    if content_lower == "签到":
        await _handle_checkin(message)
        return

    if content_lower == "发布作品" or content_lower.startswith("发布作品"):
        await _handle_publish(message)
        return

    if content_lower.startswith("视频码"):
        await _handle_videocode_command(message, content)
        return
    if content_lower == "彩虹屁模式 轻量": COMPLIMENT_MODE = "lite"; await message.reply("✅ 彩虹屁已切换为 **轻量 AI** 模式（贴图一句话）。"); return
    if content_lower == "彩虹屁模式 静态": COMPLIMENT_MODE = "static"; await message.reply("✅ 彩虹屁已切换为 **静态文案** 模式（零 API 消耗）。"); return
    
    if content_lower.startswith("在线查词 "):
        if author_id in user_states:
            del user_states[author_id]
        await handle_tag_search(message, content[5:].strip(), online_only=True)
        return

    if content_lower in {"d浏览", "标签面板"}:
        if author_id in user_states:
            del user_states[author_id]
        try:
            await tag_browser.open_browser(message.channel, author_id, client_openai, MODEL_NAME)
        except FileNotFoundError:
            await message.reply("❌ 缺少 `danbooru_category_map.json`，无法打开浏览面板。")
        except Exception as e:
            await message.reply(f"❌ 打开浏览面板失败：{e}")
        return

    if content_lower.startswith("d类 "):
        if author_id in user_states:
            del user_states[author_id]
        args = content[3:].strip().split()
        if len(args) < 2:
            await message.reply("用法：`D类 姿势 性姿势` 或 `D类 姿势 日常姿势 2`（页码可选）")
            return
        page = 1
        if args[-1].isdigit():
            page = int(args[-1])
            args = args[:-1]
        if len(args) < 2:
            await message.reply("请指定大类和子类，例如：`D类 姿势 性姿势`")
            return
        cat_label, sub_label = args[0], args[1]
        try:
            await tag_browser.open_category_text(
                message.channel, author_id, cat_label, sub_label, page, client_openai, MODEL_NAME
            )
        except Exception as e:
            await message.reply(f"❌ 打开分类失败：{e}")
        return

    if content_lower.startswith("查词 "):
        if author_id in user_states:
            del user_states[author_id]
        await handle_tag_search(message, content[3:].strip(), online_only=False)
        return

    if content_lower == "打开标签目录":
        if not KNOWLEDGE_BASE: await message.reply("知识库尚未加载，请稍后再试。"); return
        categories = get_browse_categories()
        response_text = "📚 **知识库标签目录** 📚\n\n" + "\n".join(f"{i+1}. {cat} ({len(KNOWLEDGE_BASE[cat])})" for i, cat in enumerate(categories)) + "\n\n请回复您想查阅的目录 **序号** 或 **完整名称**："
        await message.reply(response_text)
        user_states[author_id] = "awaiting_category_choice"
        return
    
    if content_lower == "取消":
        if user_states.get(author_id) == "awaiting_category_choice":
            del user_states[author_id]
            await message.reply("操作已取消。")
        return

    # --- 2. Continuous Chat & State Handling ---
    user_state = user_states.get(author_id)
    
    if user_state and user_state == "awaiting_category_choice":
        try:
            categories = get_browse_categories()
            chosen_category = None
            try:
                choice_index = int(content_lower) - 1
                if 0 <= choice_index < len(categories): chosen_category = categories[choice_index]
            except ValueError:
                if content_lower in categories: chosen_category = content_lower
            
            if chosen_category:
                tags = KNOWLEDGE_BASE.get(chosen_category, [])
                if not tags: await message.reply(f"🤔 目录“{chosen_category}”下没有找到任何标签。")
                else:
                    response_parts = []; current_part = f"📜 **{chosen_category}** 目录下的标签：\n"
                    for tag in tags:
                        trans = tag.get('translation') or '—'
                        line = f"- {trans} (`{tag.get('term', 'N/A')}`)\n"
                        if len(current_part) + len(line) > 1900: response_parts.append(current_part); current_part = ""
                        current_part += line
                    response_parts.append(current_part)
                    for part in response_parts: await message.reply(part)
            else: await message.reply("无效的目录选项，请重新输入序号或完整的目录名称，或输入`取消`来退出。"); return
        finally:
            if author_id in user_states: del user_states[author_id]
        return

    # --- 3. New Conversation / Mention Handling ---
    directed_at_bot = await _is_directed_at_bot(message, client_discord.user)

    # Initialize a new chat session if @/喊名字且尚未在会话中
    if directed_at_bot and user_states.get(author_id, {}).get('state') != 'chatting':
        target_message = message
        if message.reference:
            try: target_message = await message.channel.fetch_message(message.reference.message_id)
            except (discord.NotFound, discord.HTTPException): pass

        # If it's a wake-up with an image, handle image comment and don't start a text chat session
        if target_message and target_message.attachments:
            attachment = target_message.attachments[0]
            if attachment.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')):
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(attachment.url, proxy=PROXY_URL) as resp:
                            if resp.status == 200:
                                image_data = await resp.read()
                                await comment_on_image_when_awakened(image_data, message.author.mention, message.channel)
                                return
                except Exception as e: await message.reply(f"❌ 评论图片时发生未知错误：{str(e)}")
                return
        
        # It's a text-based wake-up call, so initialize the chat state.
        user_states[author_id] = {'state': 'chatting', 'timestamp': time.time()}
        # The code will now fall through to the chat handling logic below.

    # --- 4. Active Chat Session Logic ---
    # Re-fetch state in case it was just created above
    user_state = user_states.get(author_id)

    if user_state and user_state.get('state') == 'chatting':
        # Handle explicit exit keywords
        if content_lower in EXIT_KEYWORDS:
            if author_id in user_states: del user_states[author_id]
            await message.reply("好的，嗷呜~！本哈去玩飞盘了，有事再叫我！")
            return

        # Handle session timeout
        if time.time() - user_state.get('timestamp', 0) >= CHAT_SESSION_TIMEOUT:
            if author_id in user_states: del user_states[author_id]
            return

        # 会话中只回应明确 @/喊名字/回复小哈 的消息
        if not directed_at_bot:
            return

        # 会话中若实际是生图/生成请求，走提示词（防止别名未识别时误进闲聊）
        art_idea = _extract_art_generation_idea(message.clean_content or content, bot_user)
        if art_idea:
            if author_id in user_states:
                del user_states[author_id]
            await generate_art_prompt(art_idea, message.author.mention, message.channel)
            return

        try:
            history = [msg async for msg in message.channel.history(limit=CHAT_HISTORY_LIMIT)]; history.reverse()
            await generate_smart_response(message, history, is_awakened=True)
            if author_id in user_states:
                user_states[author_id]['timestamp'] = time.time()
        except Exception as e:
            print(f"❌ 处理对话时出错: {e}")
            if author_id in user_states: del user_states[author_id]
        return

    # --- 5. Fallback Behaviors ---
    if message.attachments:
        attachment = message.attachments[0]
        if attachment.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')):
            await send_rainbow_compliment(message)
            return

    if CHAT_ENABLED and not message.attachments and random.random() < CHAT_PROBABILITY:
        if await _should_skip_random_chime(message, client_discord.user):
            return
        try:
            history = [msg async for msg in message.channel.history(limit=CHAT_HISTORY_LIMIT)]; history.reverse()
            await generate_smart_response(message, history, is_awakened=False)
        except Exception as e: print(f"❌ 获取聊天记录或回复时出错: {e}")
        return

# --- 启动机器人 ---
def start_bot():
    """启动 Discord 机器人"""
    DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
    if not DISCORD_TOKEN:
        raise ValueError("未找到 DISCORD_TOKEN，请检查 .env 文件")

    try:
        print("🚀 正在尝试启动机器人...")
        client_discord.run(DISCORD_TOKEN)
    except discord.errors.LoginFailure:
        print("❌ Discord Token 无效，请检查 .env 文件中的 DISCORD_TOKEN 是否正确。")
    except Exception as e:
        print(f"❌ 启动机器人时发生严重错误: {e}")

if __name__ == "__main__":
    start_bot()
