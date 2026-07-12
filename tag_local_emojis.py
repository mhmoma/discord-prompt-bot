#!/usr/bin/env python3
"""
本地表情文件夹：情绪打标 + Discord 合规命名 + 复制到 emoji_library/

用法：
  python tag_local_emojis.py "D:\\迅雷下载"
  python tag_local_emojis.py "D:\\迅雷下载" --ai          # 对无法从文件名判断的用视觉模型
  python tag_local_emojis.py "D:\\迅雷下载" --ai --limit 50
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "emoji_library"
MANIFEST = ROOT / "emotion_emojis.json"

API_BASE = os.getenv("OPENAI_API_BASE", "").strip()
API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
MODEL_NAME = os.getenv("OPENAI_MODEL_NAME", "").strip()
PROXY_URL = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY")

IMAGE_EXTS = {".webp", ".png", ".gif", ".jpg", ".jpeg", ".avif"}
SKIP_NAMES = {"state.vscdb"}
MAX_FILE_BYTES = 512 * 1024  # 跳过异常大文件

EMOTION_LABELS = (
    "happy", "sad", "angry", "love", "surprised",
    "thinking", "neutral", "funny", "support", "other",
)

# 文件名关键词 → 情绪
FILENAME_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("angry", ("angry", "rage", "mad", "sheng_qi", "生气", "anti", "attack", "slap", "pout", "xiba", "yinluan")),
    ("sad", ("sad", "cry", "kuku", "tears", "emo", "nooo", "委屈", "哭", "tang")),
    ("love", ("love", "heart", "hug", "kiss", "blush", "aini", "喜欢", "亲", "slove")),
    ("surprised", ("shock", "surprise", "aaah", "scream", "zhenjing", "震惊", "omg", "wtf", "jiong")),
    ("thinking", ("think", "thonk", "pensive", "wuyu", "confused", "无语", "疑惑", "loading", "zenmezheyang", "zhenwuyu")),
    ("funny", ("rofl", "laugh", "laught", "meme", "rickroll", "boioio", "silly", "搞怪", "沙雕", "hegao", "chi_gua", "gua", "xuanzhuan", "zhuan")),
    ("support", ("support", "salute", "thumbsup", "agree", "cheer", "clap", "yes", "点赞", "加油", "bangni", "kefu")),
    ("happy", ("happy", "smile", "joy", "party", "celebrate", "hooray", "笑", "开心", "gaoxiao", "tou_xiao", "xiao")),
]

_HASH_NAME = re.compile(r"^[0-9a-f]{16,}$", re.I)
_RANDOM_NAME = re.compile(r"^[a-z0-9_]{10,}$", re.I)

AI_PROMPT = (
    "看 Discord 表情图，判断主情绪并起短英文名。\n"
    "情绪只能是："
    + ", ".join(EMOTION_LABELS)
    + "\n只回复一行，格式：emotion|short_name\n"
    "示例：happy|cat_smile  funny|spin_dance\n"
    "short_name 2-16字符，小写字母数字下划线，不要用emoji_数字。"
)


def _image_data_url(path: Path) -> str:
    import base64
    import io

    from PIL import Image

    with Image.open(path) as img:
        if getattr(img, "is_animated", False):
            img.seek(0)
        frame = img.convert("RGBA")
        frame.thumbnail((128, 128), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        frame.save(buf, format="PNG", optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _sanitize_discord_name(name: str, *, max_len: int = 32) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9_]", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    if len(s) < 2:
        s = f"em_{s or 'x'}"
    if len(s) > max_len:
        s = s[:max_len].rstrip("_")
    return s


def _classify_by_filename(stem: str) -> str | None:
    low = stem.lower()
    for emotion, keywords in FILENAME_RULES:
        for kw in keywords:
            if kw in low:
                return emotion
    return None


def _needs_ai(stem: str) -> bool:
    """仅对无意义文件名用 AI（emoji_数字、纯数字、hash）。"""
    low = stem.lower()
    if re.fullmatch(r"emoji_\d+(_\d+)?", low):
        return True
    if re.fullmatch(r"\d+(_\d+)?", low):
        return True
    if _HASH_NAME.fullmatch(low):
        return True
    # 长串乱码且几乎无英文单词
    if len(low) >= 12 and _RANDOM_NAME.fullmatch(low):
        vowels = sum(1 for c in low if c in "aeiou")
        if vowels <= 2:
            return True
    return False


def _guess_short_name(stem: str) -> str:
    s = _sanitize_discord_name(stem)
    if re.fullmatch(r"emoji_\d+", s) or _HASH_NAME.fullmatch(s) or re.fullmatch(r"\d+", s):
        return ""
    return s


def _fallback_short(stem: str) -> str:
    short = _guess_short_name(stem)
    if short:
        return short
    s = _sanitize_discord_name(stem)
    if re.fullmatch(r"emoji_\d+", s) or len(s) < 3:
        return f"item_{stem[-6:]}" if stem else "unknown"
    return s


def _parse_llm_json(text: str) -> dict:
    raw = (text or "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    block = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL | re.IGNORECASE)
    if block:
        try:
            return json.loads(block.group(1).strip())
        except json.JSONDecodeError:
            raw = block.group(1).strip()
    else:
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                raw = raw[start:]
    em = re.search(r'"emotion"\s*:\s*"([a-z_]+)', raw, re.I)
    if em:
        sn = re.search(r'"short_name"\s*:\s*"([a-z0-9_]+)', raw, re.I)
        desc = re.search(r'"description"\s*:\s*"([^"]*)', raw)
        return {
            "emotion": em.group(1).lower(),
            "short_name": sn.group(1).lower() if sn else "",
            "description": desc.group(1) if desc else "",
        }
    pipe = re.search(
        r"\b(happy|sad|angry|love|surprised|thinking|neutral|funny|support|other)\b\s*\|\s*([a-z0-9_]{2,16})",
        raw,
        re.I,
    )
    if pipe:
        return {
            "emotion": pipe.group(1).lower(),
            "short_name": pipe.group(2).lower(),
            "description": "",
        }
    word = re.search(
        r"\b(happy|sad|angry|love|surprised|thinking|neutral|funny|support|other)\b",
        raw,
        re.I,
    )
    if word:
        return {"emotion": word.group(1).lower(), "short_name": "", "description": ""}
    raise ValueError(f"bad json: {raw[:160]}")


def _unique_name(base: str, used: set[str]) -> str:
    name = base
    i = 2
    while name in used:
        suffix = f"_{i}"
        name = base[: 32 - len(suffix)] + suffix
        i += 1
    used.add(name)
    return name


def _collect_images(src: Path) -> list[Path]:
    files: list[Path] = []
    for p in sorted(src.iterdir()):
        if not p.is_file():
            continue
        if p.name in SKIP_NAMES:
            continue
        if p.suffix.lower() not in IMAGE_EXTS:
            continue
        try:
            if p.stat().st_size > MAX_FILE_BYTES:
                print(f"  [skip] too large: {p.name}", flush=True)
                continue
        except OSError:
            continue
        files.append(p)
    return files


async def _ai_classify(client: AsyncOpenAI, path: Path) -> dict:
    url = _image_data_url(path)
    last_err: Exception | None = None
    for attempt in range(6):
        try:
            resp = await client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": AI_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": f"文件名：{path.stem}"},
                            {"type": "image_url", "image_url": {"url": url}},
                        ],
                    },
                ],
                max_tokens=40,
                temperature=0.2,
            )
            break
        except Exception as exc:
            last_err = exc
            msg = str(exc).lower()
            if any(x in msg for x in ("429", "rate", "connection", "invalid_json", "timeout")):
                await asyncio.sleep(min(45, 4 * (2 ** attempt)))
                continue
            raise
    else:
        raise last_err or RuntimeError("ai classify failed")

    parsed = _parse_llm_json(resp.choices[0].message.content or "")
    emotion = str(parsed.get("emotion", "other")).lower()
    if emotion not in EMOTION_LABELS:
        emotion = "other"
    short = _sanitize_discord_name(str(parsed.get("short_name") or ""))
    desc = str(parsed.get("description") or "").strip()
    return {"emotion": emotion, "short_name": short, "description": desc}


async def run(
    src: Path,
    *,
    use_ai: bool,
    ai_retag: bool,
    limit: int | None,
    concurrency: int,
) -> int:
    if not src.is_dir():
        print(f"[ERR] not found: {src}", file=sys.stderr)
        return 1

    files = _collect_images(src)
    if limit is not None:
        files = files[:limit]
    print(f"[DIR] {src} -> {len(files)} emoji files", flush=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    used_names: set[str] = set()
    state = {
        "meta": {
            "source_dir": str(src),
            "output_dir": str(OUT_DIR),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "total": len(files),
        },
        "emotions": {k: [] for k in EMOTION_LABELS},
        "details": {},
    }

    ready: list[tuple[Path, str, str]] = []
    ai_queue: list[Path] = []

    if ai_retag and MANIFEST.is_file():
        prev = json.loads(MANIFEST.read_text(encoding="utf-8"))
        keep = 0
        for name, detail in prev.get("details", {}).items():
            if detail.get("tagged_via") == "filename":
                state["details"][name] = detail
                used_names.add(name)
                lib = OUT_DIR / detail.get("library_file", f"{name}.webp")
                if not lib.is_file():
                    src_file = src / detail["source_file"]
                    if src_file.is_file():
                        shutil.copy2(src_file, lib)
                keep += 1
            elif detail.get("tagged_via") in ("fallback", "ai"):
                old_lib = OUT_DIR / detail.get("library_file", "")
                if old_lib.is_file():
                    old_lib.unlink()
                state["details"].pop(name, None)
                used_names.discard(name)
                src_file = src / detail["source_file"]
                if src_file.is_file():
                    ai_queue.append(src_file)
        if limit is not None:
            ai_queue = ai_queue[:limit]
        print(f"[RETAG] keep filename={keep}, ai_queue={len(ai_queue)}", flush=True)
    else:
        for path in files:
            stem = path.stem
            if _needs_ai(stem):
                ai_queue.append(path)
            else:
                emotion = _classify_by_filename(stem) or "neutral"
                short = _fallback_short(stem)
                ready.append((path, emotion, short))
        if limit is not None:
            ai_queue = ai_queue[:limit]
        print(f"[RULE] filename/neutral: {len(ready)} | need AI: {len(ai_queue)}", flush=True)

    sem = asyncio.Semaphore(max(1, concurrency))
    openai_client = None
    if ai_queue and use_ai:
        if not all([API_BASE, API_KEY, MODEL_NAME]):
            print("[WARN] no OpenAI config; using fallback tags", flush=True)
            use_ai = False
        else:
            http = httpx.AsyncClient(proxy=PROXY_URL, timeout=120.0)
            openai_client = AsyncOpenAI(base_url=API_BASE, api_key=API_KEY, http_client=http)

    async def process_one(path: Path, emotion: str, short: str, desc: str, via: str) -> None:
        discord_name = _unique_name(_sanitize_discord_name(f"{emotion}_{short}"), used_names)
        ext = path.suffix.lower()
        dest = OUT_DIR / f"{discord_name}{ext}"
        shutil.copy2(path, dest)
        state["details"][discord_name] = {
            "emotion": emotion,
            "description": desc,
            "source_file": path.name,
            "library_file": dest.name,
            "tagged_via": via,
            "tagged_at": datetime.now(timezone.utc).isoformat(),
        }

    for path, emotion, short in ready:
        await process_one(path, emotion, short, "由文件名推断", "filename")

    err = 0
    done_ai = 0

    def _save() -> None:
        pools: dict[str, list[str]] = {k: [] for k in EMOTION_LABELS}
        for name, d in state["details"].items():
            e = d.get("emotion", "other")
            if e not in pools:
                e = "other"
            pools[e].append(name)
        for k in EMOTION_LABELS:
            state["emotions"][k] = sorted(pools[k])
        state["meta"]["updated_at"] = datetime.now(timezone.utc).isoformat()
        state["meta"]["tagged_count"] = len(state["details"])
        MANIFEST.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    if ai_queue:
        async def ai_one(path: Path) -> None:
            nonlocal err, done_ai
            stem = path.stem
            emotion = _classify_by_filename(stem)
            short = _guess_short_name(stem)
            desc = ""
            via = "fallback"
            if use_ai and openai_client:
                async with sem:
                    try:
                        r = await _ai_classify(openai_client, path)
                        emotion = emotion or r["emotion"]
                        short = short or r["short_name"]
                        desc = r["description"]
                        via = "ai"
                    except Exception as exc:
                        err += 1
                        print(f"  [WARN] AI failed {path.name}: {exc}", flush=True)
            if not emotion:
                emotion = "other"
            if not short:
                short = _fallback_short(stem)
            await process_one(path, emotion, short, desc or "auto", via)
            done_ai += 1
            await asyncio.sleep(3.0)
            if done_ai % 20 == 0:
                _save()
                print(f"  [progress] {done_ai}/{len(ai_queue)}", flush=True)

        for path in ai_queue:
            await ai_one(path)

    _save()
    print(
        f"\n[DONE] {len(state['details'])} files -> {OUT_DIR}\n"
        f"   manifest -> {MANIFEST}\n"
        f"   emotions: " + ", ".join(f"{k}={len(v)}" for k, v in state["emotions"].items() if v),
        flush=True,
    )
    return 1 if err else 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", nargs="?", default=r"D:\迅雷下载")
    parser.add_argument("--ai", action="store_true", help="对无法从文件名判断的使用视觉模型")
    parser.add_argument("--ai-retag", action="store_true", help="仅对上次 fallback 的条目重新 AI 标注")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=1)
    args = parser.parse_args()
    code = asyncio.run(
        run(
            Path(args.source),
            use_ai=args.ai or args.ai_retag,
            ai_retag=args.ai_retag,
            limit=args.limit,
            concurrency=args.concurrency,
        )
    )
    raise SystemExit(code)


if __name__ == "__main__":
    main()
