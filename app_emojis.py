"""应用专属表情：启动加载 + 按情绪池随机取用 + 对话装饰。"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

import discord

APP_EMOJIS: dict[str, discord.Emoji] = {}
EMOTION_POOLS: dict[str, list[str]] = {}
EMOJI_META: dict[str, dict] = {}

EMOTION_JSON = Path(__file__).resolve().parent / "emotion_emojis.json"

SCENARIO_EMOTION: dict[str, str] = {
    "compliment": "happy",
    "welcome": "happy",
    "signin_ok": "happy",
    "signin_dup": "thinking",
    "signin_fail": "sad",
    "publish_ok": "happy",
    "publish_info": "neutral",
    "goodbye": "support",
    "help": "neutral",
    "error": "sad",
    "success": "support",
    "loading": "thinking",
    "reverse": "thinking",
    "art": "thinking",
    "info": "neutral",
    "toggle_on": "happy",
    "toggle_off": "neutral",
    "search": "neutral",
    "cancel": "neutral",
}

TONE_EMOTION: dict[str, str] = {
    "warm": "love",
    "roast": "funny",
    "neutral": "neutral",
    "art": "thinking",
}

_TEXT_EMOTION_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("angry", ("生气", "怒", "烦", "滚", "讨厌", "失败", "错误", "❌", "不可用", "找不到")),
    ("sad", ("难过", "哭", "抱歉", "遗憾", "失败", "不可用")),
    ("love", ("谢谢", "感谢", "抱抱", "喜欢", "爱", "恭喜", "生日")),
    ("surprised", ("哇", "震惊", "?!", "！！", "omg")),
    ("thinking", ("思考", "加载", "审视", "正在", "稍等", "?", "吗")),
    ("funny", ("哈哈", "离谱", "沙雕", "损", "皮", "汪", "嗷呜", "哈士奇")),
    ("support", ("加油", "成功", "✅", "好的", "可以", "指路", "欢迎", "签到成功", "已发布")),
    ("happy", ("太好了", "好看", "绝了", "开心", "庆祝", "🎉", "🎬")),
]

_CUSTOM_EMOJI_RE = re.compile(r"^(\s*<a?:\w+:\d+>\s*)+")


async def load_app_emojis(client: discord.Client) -> int:
    """从 Discord API 拉取全部应用表情，按名字索引。"""
    global APP_EMOJIS
    items = await client.fetch_application_emojis()
    APP_EMOJIS = {e.name: e for e in items if e.name}
    return len(APP_EMOJIS)


def load_emotion_pools(path: Path | None = None) -> int:
    """读取 emotion_emojis.json 情绪分组。"""
    global EMOTION_POOLS, EMOJI_META
    p = path or EMOTION_JSON
    if not p.is_file():
        EMOTION_POOLS = {}
        EMOJI_META = {}
        return 0

    data = json.loads(p.read_text(encoding="utf-8"))
    EMOTION_POOLS = {k: list(v) for k, v in (data.get("emotions") or {}).items()}
    EMOJI_META = dict(data.get("details") or {})
    return sum(len(v) for v in EMOTION_POOLS.values())


def get(name: str) -> discord.Emoji | None:
    return APP_EMOJIS.get(name)


def pick_emotion(emotion: str, *, fallback: str = "") -> discord.Emoji | str:
    """从情绪池随机取一个表情；池空则返回 fallback。"""
    names = EMOTION_POOLS.get(emotion) or []
    valid = [APP_EMOJIS[n] for n in names if n in APP_EMOJIS]
    if not valid:
        return fallback
    return random.choice(valid)


def format_emotion(emotion: str, *, fallback: str = "") -> str:
    em = pick_emotion(emotion, fallback=fallback)
    return str(em) if isinstance(em, discord.Emoji) else (em or fallback)


def guess_emotion_from_text(text: str) -> str:
    t = (text or "").lower()
    for emotion, keywords in _TEXT_EMOTION_RULES:
        for kw in keywords:
            if kw.lower() in t:
                return emotion
    return "neutral"


def resolve_emotion(
    *,
    scenario: str | None = None,
    emotion: str | None = None,
    tone: str | None = None,
    text: str = "",
) -> str:
    if emotion:
        return emotion
    if tone and tone in TONE_EMOTION:
        return TONE_EMOTION[tone]
    if scenario and scenario in SCENARIO_EMOTION:
        return SCENARIO_EMOTION[scenario]
    return guess_emotion_from_text(text)


def decorate(
    text: str,
    *,
    scenario: str | None = None,
    emotion: str | None = None,
    tone: str | None = None,
) -> str:
    """在文案前加应用表情（池空则原样返回）。"""
    if not text:
        return text
    stripped = text.strip()
    if stripped.upper() in {"SKIP", "跳过", "无", "NONE"}:
        return text
    if _CUSTOM_EMOJI_RE.match(text):
        return text
    emo = resolve_emotion(scenario=scenario, emotion=emotion, tone=tone, text=text)
    prefix = format_emotion(emo)
    if not prefix:
        return text
    return f"{prefix} {text}"
