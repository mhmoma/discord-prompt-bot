#!/usr/bin/env python3
"""
批量上传 emoji_library 到 Discord 应用专属表情。

依赖 .env：DISCORD_TOKEN
用法：
  python upload_app_emojis.py           # 上传全部（跳过已存在同名）
  python upload_app_emojis.py --dry-run   # 仅预览
  python upload_app_emojis.py --limit 10  # 试传 10 个
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv
from PIL import Image

load_dotenv()

ROOT = Path(__file__).resolve().parent
LIB_DIR = ROOT / "emoji_library"
LOG_FILE = ROOT / "upload_emojis_log.json"
DISCORD_API = "https://discord.com/api/v10"
MAX_EMOJIS = 2000
MAX_BYTES = 256 * 1024

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
PROXY_URL = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY")


def _image_data_uri(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".webp":
        with Image.open(path) as img:
            if getattr(img, "is_animated", False):
                raw = path.read_bytes()
                b64 = base64.b64encode(raw).decode("ascii")
                return f"data:image/gif;base64,{b64}"
            buf = io.BytesIO()
            img.convert("RGBA").save(buf, format="PNG", optimize=True)
            raw = buf.getvalue()
        mime = "image/png"
    elif ext == ".gif":
        raw = path.read_bytes()
        mime = "image/gif"
    else:
        raw = path.read_bytes()
        mime = "image/png"
    if len(raw) > MAX_BYTES:
        raise ValueError(f"file too large ({len(raw)} bytes)")
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _collect_files() -> list[Path]:
    files: list[Path] = []
    for ext in ("*.webp", "*.png", "*.gif", "*.jpg", "*.jpeg"):
        files.extend(LIB_DIR.rglob(ext))
    return sorted({p.resolve() for p in files if p.is_file()})


def _valid_name(name: str) -> bool:
    return 2 <= len(name) <= 32 and bool(re.fullmatch(r"[a-zA-Z0-9_]+", name))


async def _api_get(http: httpx.AsyncClient, path: str) -> dict | list:
    headers = {"Authorization": f"Bot {DISCORD_TOKEN}"}
    resp = await http.get(f"{DISCORD_API}{path}", headers=headers)
    resp.raise_for_status()
    return resp.json()


async def _api_post(http: httpx.AsyncClient, path: str, body: dict) -> dict:
    headers = {"Authorization": f"Bot {DISCORD_TOKEN}", "Content-Type": "application/json"}
    resp = await http.post(f"{DISCORD_API}{path}", headers=headers, json=body)
    if resp.status_code == 429:
        data = resp.json()
        retry = float(data.get("retry_after", 5))
        await asyncio.sleep(retry + 0.5)
        resp = await http.post(f"{DISCORD_API}{path}", headers=headers, json=body)
    resp.raise_for_status()
    return resp.json()


async def run(*, dry_run: bool, limit: int | None) -> int:
    if not DISCORD_TOKEN:
        print("[ERR] set DISCORD_TOKEN in .env", file=sys.stderr)
        return 1
    if not LIB_DIR.is_dir():
        print(f"[ERR] missing {LIB_DIR}", file=sys.stderr)
        return 1

    files = _collect_files()
    if limit is not None:
        files = files[:limit]
    print(f"[LIB] {len(files)} files in {LIB_DIR}", flush=True)

    log = {"uploaded": {}, "skipped": {}, "failed": {}}
    if LOG_FILE.is_file():
        try:
            log = json.loads(LOG_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    async with httpx.AsyncClient(proxy=PROXY_URL, timeout=120.0) as http:
        app = await _api_get(http, "/oauth2/applications/@me")
        app_id = app["id"]
        raw = await _api_get(http, f"/applications/{app_id}/emojis")
        items = raw["items"] if isinstance(raw, dict) and "items" in raw else raw
        existing = {e["name"]: int(e["id"]) for e in items if e.get("name")}
        print(f"[APP] existing emojis: {len(existing)}", flush=True)

        slots = MAX_EMOJIS - len(existing)
        if slots <= 0:
            print("[ERR] application emoji slots full (2000)", file=sys.stderr)
            return 1

        uploaded = 0
        skipped = 0
        failed = 0

        for path in files:
            name = path.stem
            if not _valid_name(name):
                print(f"  [skip] bad name: {name}", flush=True)
                log["failed"][name] = "invalid name"
                failed += 1
                continue
            if name in existing or name in log.get("uploaded", {}):
                skipped += 1
                continue
            if uploaded >= slots:
                print(f"[STOP] no slots left ({MAX_EMOJIS} max)", flush=True)
                break

            if dry_run:
                print(f"  [dry] would upload {name} <- {path.relative_to(LIB_DIR)}", flush=True)
                continue

            try:
                image = _image_data_uri(path)
                body = {"name": name, "image": image}
                result = await _api_post(http, f"/applications/{app_id}/emojis", body)
                eid = int(result["id"])
                existing[name] = eid
                log.setdefault("uploaded", {})[name] = {
                    "id": eid,
                    "source": str(path.relative_to(LIB_DIR)),
                    "at": datetime.now(timezone.utc).isoformat(),
                }
                uploaded += 1
                LOG_FILE.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"  [{uploaded}] {name} -> {eid}", flush=True)
                await asyncio.sleep(1.2)
            except Exception as exc:
                failed += 1
                log.setdefault("failed", {})[name] = str(exc)
                LOG_FILE.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"  [FAIL] {name}: {exc}", flush=True)

    print(
        f"\n[DONE] uploaded={uploaded}, skipped={skipped}, failed={failed}, "
        f"app_total~={len(existing)}",
        flush=True,
    )
    if not dry_run:
        print(f"   log -> {LOG_FILE}", flush=True)
    return 0 if failed == 0 else 2


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload emoji_library to Discord application emojis")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(dry_run=args.dry_run, limit=args.limit)))


if __name__ == "__main__":
    main()
