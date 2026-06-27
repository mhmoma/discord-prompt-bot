#!/usr/bin/env python3
"""增强 classified_lexicon.json：解析银月佬词库、去重、补分类与翻译。"""
import json
import os
import re
import shutil
from collections import defaultdict

LEXICON_FILE = 'classified_lexicon.json'
MD_FILE = '银月佬的词库 v0.3.md'
BACKUP_FILE = 'classified_lexicon.json.bak'

SECTION_TO_CATEGORY = {
    'Body Parts': '身体部位',
    'Bottomwear': '服装/饰品',
    'Breasts': '身体部位',
    'Dresses': '服装/饰品',
    'Eyes': '脸部/表情',
    'Facial Expressions': '脸部/表情',
    'Focus': '摄像机/构图',
    'Footwear': '服装/饰品',
    'Format': '风格/效果',
    'Full Body Outfits': '服装/饰品',
    'Hair Color & Style': '头发',
    'Headwear': '服装/饰品',
    'Locations': '背景/环境',
    'Neckwear': '服装/饰品',
    'Posture': '动作/姿势',
    'Sex Acts': '动作/姿势',
    'Sexual Attire': '服装/饰品',
    'Sexual Positions': '动作/姿势',
    'Sleeves': '服装/饰品',
    'Styles and Techniques': '风格/效果',
    'Swimsuits and Bodysuits': '服装/饰品',
    'Tails': '尾巴',
    'Topwear': '服装/饰品',
    'Wings': '翅膀',
    'View Angle': '摄像机/构图',
    '画师串': '画师',
}

# 对「未分类」bulk tag 做启发式归类（按顺序匹配，先匹配先生效）
HEURISTIC_RULES = [
    (re.compile(r'\(artist\)\s*$', re.I), '画师'),
    (re.compile(r'\(style\)\s*$', re.I), '画师'),
    (re.compile(r'\(company\)\s*$', re.I), '角色/作品'),
    (re.compile(r'\(series\)\s*$', re.I), '角色/作品'),
    (re.compile(r'\([^)]+\)\s*$'), '角色/作品'),
    (re.compile(r'\btail\b|_tail\b|tails\b|tail_|\btail pull\b|\btail grab\b', re.I), '尾巴'),
    (re.compile(r'\btongue\b|tongue_', re.I), '舌头'),
    (re.compile(r'\bear\b|\bears\b|_ear\b|ear_', re.I), '耳朵'),
    (re.compile(r'hair|ponytail|twintails|twintail|ahoge|bun\b|braid|sideburns|bangs\b|fringe\b', re.I), '头发'),
    (re.compile(r'shot\b|pov\b|close-?up|from above|from below|from behind|from side|perspective|dutch angle|wide shot|cowboy shot|full body|bust\b|portrait\b|zoom layer|letterbox', re.I), '摄像机/构图'),
    (re.compile(r'background|outdoors|indoors|sky\b|cityscape|landscape|scenery|beach|forest|bedroom|classroom|night sky|cloud|rain\b|snow\b|water\b|ocean\b|river\b|mountain\b|field\b|garden\b|street\b|road\b', re.I), '背景/环境'),
    (re.compile(r'standing|sitting|lying|kneeling|squatting|leaning|crouching|walking|running|jumping|stretching|pose\b|holding\b|hug\b|grabbing\b|arm around|leg up|spread legs|on back|on stomach|all fours', re.I), '动作/姿势'),
    (re.compile(r'dress\b|skirt\b|shirt\b|pants\b|shorts\b|sock|thighhigh|glove|hat\b|uniform|bikini|swimsuit|jacket|coat\b|ribbon|necktie|apron|armor|helmet|boots\b|shoes\b|panties|bra\b|lingerie|kimono|sweater|hoodie|scarf\b|belt\b|collar\b', re.I), '服装/饰品'),
    (re.compile(r'\beye\b|eyes\b|pupil|eyelash|eyebrow|mouth\b|smile|blush|expression|face\b|lips\b|nose\b|frown|grin\b|open mouth|closed mouth|looking at', re.I), '脸部/表情'),
    (re.compile(r'glow|monochrome|sketch|watercolor|realistic|cel shading|lineart|silhouette|film grain|motion blur|depth of field|bokeh|lens flare|vignette', re.I), '风格/效果'),
    (re.compile(r'breast|nipple|areola|ass\b|thigh|navel|penis|pussy|anus\b|armpit|foot\b|feet\b|hand\b|hands\b|finger|belly|hip\b|groin|shoulder|collarbone|nape|neck\b|lips\b|abs\b|muscle|nude\b|naked\b|topless\b|bottomless\b', re.I), '身体部位'),
    (re.compile(r'\bwing\b|wings\b|winged\b', re.I), '翅膀'),
]

CATEGORY_ORDER = [
    '身体部位', '服装/饰品', '脸部/表情', '头发', '动作/姿势',
    '背景/环境', '摄像机/构图', '风格/效果', '耳朵', '舌头', '尾巴', '翅膀',
    '画师', '角色/作品', '未分类',
]


def normalize_term(term: str) -> str:
    return term.strip().lower().replace('\\(', '(').replace('\\)', ')')


def parse_markdown_lexicon(path: str) -> dict:
    """返回 {term_lower: {term, translation, category}}"""
    if not os.path.exists(path):
        return {}

    with open(path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    result = {}
    current_section = None
    current_category = None
    section_re = re.compile(r'^##\s+(.+?)(?:\s*\((.+?)\))?\s*$')
    item_re = re.compile(r'^-\s+(.+)$')
    artist_re = re.compile(r'^-\s+\*\*(.+?)\*\*:\s*(.+)$')

    for line in lines:
        line = line.rstrip('\n')
        m_sec = section_re.match(line)
        if m_sec:
            current_section = m_sec.group(1).strip()
            current_category = SECTION_TO_CATEGORY.get(current_section, '未分类')
            continue

        m_art = artist_re.match(line)
        if m_art and current_category == '画师':
            term = m_art.group(1).strip()
            translation = m_art.group(2).strip()
            key = normalize_term(term)
            result[key] = {'term': term, 'translation': translation, 'category': '画师'}
            continue

        m_item = item_re.match(line)
        if not m_item or not current_category:
            continue

        raw = m_item.group(1).strip()
        translation = ''
        term = raw

        # **term**: note
        bold_match = re.match(r'\*\*(.+?)\*\*:\s*(.+)', raw)
        if bold_match:
            term = bold_match.group(1).strip()
            translation = bold_match.group(2).strip()
        else:
            # term (中文说明)
            paren_match = re.match(r'^(.+?)\s*\(([^)]+)\)\s*$', raw)
            if paren_match:
                term = paren_match.group(1).strip()
                note = paren_match.group(2).strip()
                if re.search(r'[\u4e00-\u9fff]', note):
                    translation = note

        term = term.replace('\\(', '(').replace('\\)', ')')
        key = normalize_term(term)
        entry = {'term': term, 'category': current_category}
        if translation:
            entry['translation'] = translation
        result[key] = entry

    return result


def classify_heuristic(term: str) -> str | None:
    for pattern, category in HEURISTIC_RULES:
        if pattern.search(term):
            return category
    return None


def merge_entry(existing: dict | None, new: dict) -> dict:
    if not existing:
        out = {'term': new['term']}
        if new.get('translation'):
            out['translation'] = new['translation']
        out['_category'] = new.get('category', '未分类')
        return out

    out = dict(existing)
    out['term'] = existing.get('term') or new['term']
    if new.get('translation') and not out.get('translation'):
        out['translation'] = new['translation']
    # 优先：有翻译 > 非未分类
    new_cat = new.get('category', '未分类')
    old_cat = out.get('_category', '未分类')
    if new_cat != '未分类' and (old_cat == '未分类' or new.get('translation')):
        out['_category'] = new_cat
    return out


def item_score(item: dict) -> tuple:
    return (
        1 if item.get('translation') else 0,
        0 if item.get('_category', '未分类') == '未分类' else 1,
    )


def main():
    md_map = parse_markdown_lexicon(MD_FILE)
    print(f'[md] parsed: {len(md_map)} terms')

    existing = {}
    if os.path.exists(LEXICON_FILE):
        with open(LEXICON_FILE, 'r', encoding='utf-8') as f:
            existing = json.load(f)
        shutil.copy2(LEXICON_FILE, BACKUP_FILE)
        print(f'[backup] {BACKUP_FILE}')

    merged: dict[str, dict] = {}

    # 1) 现有 JSON（保留已有分类与翻译）
    for category, items in existing.items():
        for item in items:
            term = item.get('term', '').strip()
            if not term:
                continue
            key = normalize_term(term)
            entry = merge_entry(merged.get(key), {
                'term': term,
                'translation': item.get('translation', ''),
                'category': category if category != '未分类' else '未分类',
            })
            merged[key] = entry

    print(f'[merge] existing json: {len(merged)} unique terms')

    # 2) 银月佬词库覆盖/补充（高优先级：带翻译与精确分类）
    for key, md_entry in md_map.items():
        merged[key] = merge_entry(merged.get(key), md_entry)

    # 3) 对仍为未分类的词条做启发式归类
    reclassified = 0
    for key, item in merged.items():
        if item.get('_category', '未分类') != '未分类':
            continue
        cat = classify_heuristic(item['term'])
        if cat:
            item['_category'] = cat
            reclassified += 1

    print(f'[heuristic] reclassified: {reclassified}')

    # 4) 按分类输出，分类内去重并排序
    buckets: dict[str, list] = defaultdict(list)
    for item in merged.values():
        cat = item.pop('_category', '未分类')
        out = {'term': item['term']}
        if item.get('translation'):
            out['translation'] = item['translation']
        buckets[cat].append(out)

    for cat in buckets:
        seen = set()
        unique = []
        for it in buckets[cat]:
            k = normalize_term(it['term'])
            if k in seen:
                continue
            seen.add(k)
            unique.append(it)
        unique.sort(key=lambda x: normalize_term(x['term']))
        buckets[cat] = unique

    output = {}
    for cat in CATEGORY_ORDER:
        if cat in buckets and buckets[cat]:
            output[cat] = buckets[cat]
    for cat in sorted(buckets.keys()):
        if cat not in output and buckets[cat]:
            output[cat] = buckets[cat]

    total = sum(len(v) for v in output.values())
    trans = sum(1 for items in output.values() for it in items if it.get('translation'))
    uncat = len(output.get('未分类', []))

    with open(LEXICON_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f'[done] wrote {LEXICON_FILE}')
    print(f'[stats] categories={len(output)} terms={total} translated={trans} unclassified={uncat}')
    for cat, items in sorted(output.items(), key=lambda x: -len(x[1])):
        t = sum(1 for i in items if i.get('translation'))
        print(f'   {cat}: {len(items)} ({t} translated)')


if __name__ == '__main__':
    main()
