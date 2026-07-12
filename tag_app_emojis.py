#!/usr/bin/env python3
"""
用视觉模型给应用专属表情（emoji_N 等）自动打情绪标签。

依赖 .env：DISCORD_TOKEN、OPENAI_API_BASE、OPENAI_API_KEY、OPENAI_MODEL_NAME
输出：emotion_emojis.json（可重复运行，已标注的会跳过）

用法：
  python tag_app_emojis.py              # 标注全部未处理的
  python tag_app_emojis.py --limit 10   # 先试 10 个
  python tag_app_emojis.py --force      # 全部重新标注
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "emotion_emojis.json"
DISCORD_API = "https://discord.com/api/v10"

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
API_BASE = os.getenv("OPENAI_API_BASE", "").strip()
API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
MODEL_NAME = os.getenv("OPENAI_MODEL_NAME", "").strip()
PROXY_URL = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY")

EMOTION_LABELS = (
    "happy",
    "sad",
    "angry",
    "love",
    "surprised",
    "thinking",
    "neutral",
    "funny",
    "support",
    "other",
)

SYSTEM_PROMPT = (
    "你是 Discord 自定义表情分类器。根据表情图案判断其主要情绪/用途。\n"
    "只能从以下选一个主分类："
    + ", ".join(EMOTION_LABELS)
    + "。\n"
    "分类参考：\n"
    "- happy: 开心、笑、庆祝、兴奋\n"
    "- sad: 难过、哭、失望\n"
    "- angry: 生气、怒、吐槽\n"
    "- love: 喜欢、心动、抱抱、亲亲\n"
    "- surprised: 震惊、哇、愣住\n"
    "- thinking: 思考、疑惑、无语\n"
    "- neutral: 平淡、打招呼、无强烈情绪\n"
    "- funny: 搞怪、沙雕、玩梗\n"
    "- support: 加油、点赞、安慰、认同\n"
    "- other: 以上都不合适\n"
    "只返回 JSON，不要 markdown："
    '{"emotion":"happy","confidence":0.9,"description":"简短中文描述"}'
)


@dataclass(frozen=True)
class AppEmoji:
    name: str
    id: int
    animated: bool

    @property
    def url(self) -> str:
        ext = "gif" if self.animated else "png"
        return f"https://cdn.discordapp.com/emojis/{self.id}.{ext}"


def _parse_llm_json(text: str) -> dict:
    raw = (text or "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    block = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL | re.IGNORECASE)
    if block:
        return json.loads(block.group(1).strip())
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        return json.loads(raw[start : end + 1])
    raise ValueError(f"无法解析 JSON: {raw[:200]}")


def _load_state() -> dict:
    if not OUTPUT.is_file():
        return {
            "meta": {},
            "emotions": {k: [] for k in EMOTION_LABELS},
            "details": {},
        }
    data = json.loads(OUTPUT.read_text(encoding="utf-8"))
    data.setdefault("emotions", {k: [] for k in EMOTION_LABELS})
    data.setdefault("details", {})
    for label in EMOTION_LABELS:
        data["emotions"].setdefault(label, [])
    return data


def _rebuild_emotion_index(state: dict) -> None:
    pools: dict[str, list[str]] = {k: [] for k in EMOTION_LABELS}
    for name, detail in state["details"].items():
        emotion = (detail.get("emotion") or "other").lower()
        if emotion not in pools:
            emotion = "other"
        pools[emotion].append(name)
    for label in EMOTION_LABELS:
        state["emotions"][label] = sorted(
            set(pools[label]),
            key=lambda n: state["details"][n].get("id", 0),
        )


def _save_state(state: dict) -> None:
    _rebuild_emotion_index(state)
    OUTPUT.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


async def _discord_get(http: httpx.AsyncClient, path: str) -> dict | list:
    headers = {"Authorization": f"Bot {DISCORD_TOKEN}"}
    resp = await http.get(f"{DISCORD_API}{path}", headers=headers)
    resp.raise_for_status()
    return resp.json()


async def fetch_application_emojis(http: httpx.AsyncClient) -> list[AppEmoji]:
    app = await _discord_get(http, "/oauth2/applications/@me")
    app_id = app["id"]
    raw = await _discord_get(http, f"/applications/{app_id}/emojis")
    items = raw["items"] if isinstance(raw, dict) and "items" in raw else raw
    emojis: list[AppEmoji] = []
    for item in items:
        name = (item.get("name") or "").strip()
        eid = item.get("id")
        if not name or eid is None:
            continue
        emojis.append(
            AppEmoji(
                name=name,
                id=int(eid),
                animated=bool(item.get("animated")),
            )
        )
    return sorted(emojis, key=lambda e: e.name)


async def _classify_one(
    client: AsyncOpenAI,
    *,
    emoji: AppEmoji,
) -> dict:
    user_text = f"表情名：{emoji.name}（Discord 应用表情，{'动态' if emoji.animated else '静态'}）"
    response = await client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": emoji.url}},
                ],
            },
        ],
        response_format={"type": "json_object"},
        max_tokens=120,
    )
    raw = response.choices[0].message.content or ""
    parsed = _parse_llm_json(raw)
    emotion = str(parsed.get("emotion", "other")).lower().strip()
    if emotion not in EMOTION_LABELS:
        emotion = "other"
    confidence = parsed.get("confidence", 0)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.0
    description = str(parsed.get("description") or "").strip()
    return {
        "emotion": emotion,
        "confidence": round(confidence, 3),
        "description": description,
        "id": emoji.id,
        "animated": emoji.animated,
        "url": emoji.url,
        "tagged_at": datetime.now(timezone.utc).isoformat(),
        "model": MODEL_NAME,
    }


async def run(*, limit: int | None, force: bool, concurrency: int) -> int:
    missing = [k for k, v in {
        "DISCORD_TOKEN": DISCORD_TOKEN,
        "OPENAI_API_BASE": API_BASE,
        "OPENAI_API_KEY": API_KEY,
        "OPENAI_MODEL_NAME": MODEL_NAME,
    }.items() if not v]
    if missing:
        print(f"❌ 请在 .env 中配置: {', '.join(missing)}", file=sys.stderr)
        return 1

    state = _load_state()
    sem = asyncio.Semaphore(max(1, concurrency))
    done_count = 0
    skip_count = 0
    err_count = 0

    async with httpx.AsyncClient(proxy=PROXY_URL, timeout=90.0) as http_client:
        openai_client = AsyncOpenAI(
            base_url=API_BASE,
            api_key=API_KEY,
            http_client=http_client,
        )
        try:
            emojis = await fetch_application_emojis(http_client)
        except httpx.HTTPError as exc:
            hint = "（若在国内，请在 .env 配置 HTTP_PROXY / HTTPS_PROXY）" if not PROXY_URL else ""
            print(f"❌ 拉取应用表情失败: {exc}{hint}", file=sys.stderr)
            return 1

        print(f"📦 应用表情共 {len(emojis)} 个", flush=True)
        if PROXY_URL:
            print(f"🌐 代理: {PROXY_URL}", flush=True)

        pending: list[AppEmoji] = []
        for em in emojis:
            if not force and em.name in state["details"]:
                skip_count += 1
                continue
            pending.append(em)
        if limit is not None:
            pending = pending[:limit]

        print(f"⏭️  跳过已标注 {skip_count} 个，待处理 {len(pending)} 个", flush=True)
        if not pending:
            print(f"✅ 无需处理，结果见 {OUTPUT}", flush=True)
            return 0

        state["meta"] = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "model": MODEL_NAME,
            "total_app_emojis": len(emojis),
            "tagged_count": len(state["details"]),
        }

        async def _one(emoji: AppEmoji) -> None:
            nonlocal done_count, err_count
            async with sem:
                try:
                    detail = await _classify_one(openai_client, emoji=emoji)
                    state["details"][emoji.name] = detail
                    _save_state(state)
                    done_count += 1
                    desc = detail["description"][:30]
                    print(
                        f"  [{done_count}/{len(pending)}] {emoji.name} → {detail['emotion']} "
                        f"({detail['confidence']}) {desc}",
                        flush=True,
                    )
                except Exception as exc:
                    err_count += 1
                    print(f"  ⚠️ {emoji.name} 失败: {exc}", flush=True)

        await asyncio.gather(*[_one(em) for em in pending])

    state["meta"]["updated_at"] = datetime.now(timezone.utc).isoformat()
    state["meta"]["tagged_count"] = len(state["details"])
    _save_state(state)
    print(
        f"\n✅ 完成：新标注 {done_count}，跳过 {skip_count}，失败 {err_count}\n"
        f"   输出 → {OUTPUT}",
        flush=True,
    )
    return 0 if err_count == 0 else 2


def main() -> None:
    parser = argparse.ArgumentParser(description="AI 批量标注 Discord 应用表情情绪")
    parser.add_argument("--limit", type=int, default=None, help="最多处理 N 个（试跑）")
    parser.add_argument("--force", action="store_true", help="重新标注已有条目")
    parser.add_argument("--concurrency", type=int, default=3, help="并发请求数（默认 3）")
    args = parser.parse_args()
    try:
        code = asyncio.run(run(limit=args.limit, force=args.force, concurrency=args.concurrency))
    except KeyboardInterrupt:
        print("\n⏹ 已中断；已保存的进度在 emotion_emojis.json", flush=True)
        code = 130
    raise SystemExit(code)


if __name__ == "__main__":
    main()
