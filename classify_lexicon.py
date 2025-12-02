import json
import os
from collections import defaultdict

# --- 分类规则定义 ---
# 您可以根据需要随时修改或添加这里的规则。
# 键是新的中文目录名，值是用于匹配的英文关键词列表。
CLASSIFICATION_RULES = {
    "脸部/表情": ["face", "expression", "eyes", "mouth", "nose", "blush", "smile", "frown", "tears", "wink", "sad", "happy"],
    "耳朵": ["ears", "animal ears", "elf ears", "fox ears", "cat ears"],
    "舌头": ["tongue", "tongue out"],
    "头发": ["hair", "hairstyle", "bangs", "ponytail", "twintails", "blonde hair", "brown hair", "black hair", "red hair"],
    "身体部位": ["hands", "legs", "feet", "breasts", "ass", "navel", "thighs", "armpits", "belly"],
    "服装/饰品": ["dress", "skirt", "shirt", "pants", "bikini", "uniform", "hat", "shoes", "gloves", "ribbon", "jewelry", "necklace"],
    "背景/环境": ["outdoors", "indoors", "sky", "city", "forest", "beach", "water", "room", "street"],
    "动作/姿势": ["standing", "sitting", "lying", "looking at viewer", "posing", "dancing", "stretching", "holding"],
    "风格/效果": ["monochrome", "realistic", "sketch", "lineart", "blur", "cinematic", "glowing"],
    "摄像机/构图": ["from behind", "from above", "from below", "close-up", "full body", "wide shot", "cowboy shot"],
}

SOURCE_FILE = 'merged_knowledge_base.json'
OUTPUT_FILE = 'classified_lexicon.json'

def classify_lexicon():
    """
    读取合并后的知识库，并根据规则进行更详细的分类。
    """
    if not os.path.exists(SOURCE_FILE):
        print(f"❌ 错误：源文件 '{SOURCE_FILE}' 不存在。请先确保机器人已运行并生成该文件。")
        return

    print(f"📖 正在读取源知识库: {SOURCE_FILE}")
    with open(SOURCE_FILE, 'r', encoding='utf-8') as f:
        source_data = json.load(f)

    # 使用 defaultdict 方便地添加新分类
    classified_data = defaultdict(list)
    
    # 创建一个集合来跟踪已经处理过的词条，以避免重复
    processed_terms = set()

    print("⚙️ 正在进行分类...")

    # 将所有标签扁平化到一个列表中，并去重
    all_tags = []
    for category in source_data.values():
        for tag in category:
            term = tag.get('term')
            if term and term.lower() not in processed_terms:
                all_tags.append(tag)
                processed_terms.add(term.lower())
    
    print(f"去重后共找到 {len(all_tags)} 个独立标签。")

    # 对所有标签进行分类
    for tag in all_tags:
        term_lower = tag.get('term', '').lower()
        assigned = False
        for category, keywords in CLASSIFICATION_RULES.items():
            for keyword in keywords:
                # 为了更精确的匹配，我们检查关键词是否是标签的一部分
                # 例如 'hair' 会匹配 'long hair'
                if f" {keyword} " in f" {term_lower} " or term_lower.startswith(keyword) or term_lower.endswith(keyword):
                    classified_data[category].append(tag)
                    assigned = True
                    break  # 找到分类后，跳出内部关键词循环
            if assigned:
                break  # 跳出外部自分类循环
        
        if not assigned:
            classified_data["未分类"].append(tag)

    print(f"💾 正在将分类结果写入: {OUTPUT_FILE}")
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(classified_data, f, ensure_ascii=False, indent=2)

    print("\n🎉 分类完成！ 🎉")
    print("="*30)
    print("📊 分类统计:")
    for category, tags in classified_data.items():
        print(f"  - {category}: {len(tags)} 个标签")
    print("="*30)

if __name__ == "__main__":
    classify_lexicon()
