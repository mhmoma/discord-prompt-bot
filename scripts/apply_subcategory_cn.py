"""将 subcategory_cn_map.json 合并进 danbooru_category_map.json"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAP_FILE = ROOT / "danbooru_category_map.json"
CN_FILE = Path(__file__).resolve().parent / "subcategory_cn_map.json"


def apply_cn_map(data: dict, cn_map: dict) -> tuple[int, list[str]]:
    applied = 0
    missing = []
    for cat in data.get("categories", []):
        for child in cat.get("children", []):
            cid = child.get("id", "")
            cn = cn_map.get(cid)
            if cn:
                child["label_cn"] = cn
                applied += 1
            else:
                missing.append(cid)
    return applied, missing


def main():
    cn_map = json.loads(CN_FILE.read_text(encoding="utf-8"))
    data = json.loads(MAP_FILE.read_text(encoding="utf-8"))
    applied, missing = apply_cn_map(data, cn_map)
    MAP_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Applied {applied} label_cn entries")
    if missing:
        print(f"Missing CN ({len(missing)}):", ", ".join(missing[:10]), "..." if len(missing) > 10 else "")


if __name__ == "__main__":
    main()
