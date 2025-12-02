# -*- coding: utf-8 -*-
"""
分类词库文件中的词条，然后与knowledge_base.json合并
"""
import json
import os
import re

# 分类规则：基于关键词匹配
CLASSIFICATION_RULES = {
    "Body Parts": [
        r'\b(ear|eye|nose|mouth|lip|tongue|neck|shoulder|arm|hand|finger|leg|foot|toe|breast|nipple|areola|butt|thigh|knee|ankle|wrist|elbow|hip|waist|chest|back|stomach|belly|abs|muscle|bone|skeleton)\b',
        r'\b(long|short|large|small|big|tiny|thick|thin)\s+(ear|eye|nose|mouth|lip|tongue|neck|arm|hand|leg|foot|breast|butt|thigh)\b',
    ],
    "Eyes": [
        r'\b(eye|pupil|iris|eyelid|eyelash|eyebrow)\b',
        r'\b(blue|green|brown|red|yellow|purple|pink|black|white|gray|grey)\s+eye\b',
        r'\b(heterochromia|monoeye|closed\s+eye|open\s+eye|wide\s+eye)\b',
    ],
    "Hair Color & Style": [
        r'\b(hair|ponytail|braid|twintail|bun|bangs|fringe|curly|straight|wavy|spiky|messy|neat|long|short|medium)\s+hair\b',
        r'\b(blue|green|brown|red|yellow|purple|pink|black|white|gray|grey|blonde|silver|golden|auburn|chestnut)\s+hair\b',
        r'\b(hair\s+ornament|hair\s+ribbon|hair\s+clip|hair\s+band|hair\s+bow)\b',
    ],
    "Facial Expressions": [
        r'\b(smile|frown|grin|pout|blush|tear|cry|laugh|wink|stare|glare|surprised|shocked|angry|sad|happy|joy|sadness|fear|disgust|surprise)\b',
        r'\b(open\s+mouth|closed\s+mouth|tongue\s+out|licking\s+lips)\b',
    ],
    "Posture": [
        r'\b(standing|sitting|lying|kneeling|crouching|jumping|running|walking|dancing|posing)\b',
        r'\b(looking\s+at\s+viewer|looking\s+away|looking\s+up|looking\s+down|looking\s+back)\b',
        r'\b(arms\s+up|arms\s+behind|hands\s+on\s+hip|hands\s+behind\s+head|crossed\s+arms)\b',
    ],
    "Topwear": [
        r'\b(shirt|blouse|top|tank\s+top|crop\s+top|t-shirt|tshirt|sweater|hoodie|jacket|coat|vest|bra|underwear)\b',
        r'\b(long|short|sleeveless)\s+sleeve\b',
    ],
    "Bottomwear": [
        r'\b(pants|trousers|jeans|shorts|skirt|miniskirt|long\s+skirt)\b',
    ],
    "Dresses": [
        r'\b(dress|gown|kimono|yukata|qipao|cheongsam)\b',
    ],
    "Footwear": [
        r'\b(shoes|boots|sneakers|sandals|high\s+heels|heels|slippers|barefoot)\b',
    ],
    "Headwear": [
        r'\b(hat|cap|beanie|helmet|crown|tiara|headband|hairband|ribbon|bow)\b',
    ],
    "Locations": [
        r'\b(background|indoor|outdoor|room|bedroom|bathroom|kitchen|street|park|beach|forest|mountain|city|building|house|school|office)\b',
        r'\b(simple|white|black|gradient|nature|urban|rural)\s+background\b',
    ],
    "Format": [
        r'\b(highres|absurdres|lowres|quality|masterpiece|best\s+quality|worst\s+quality)\b',
        r'\b(1girl|1boy|2girls|multiple\s+girls|solo|group)\b',
    ],
    "View Angle": [
        r'\b(from\s+above|from\s+below|from\s+side|from\s+behind|from\s+front|bird\s+eye|worm\s+eye)\b',
        r'\b(close-up|closeup|full\s+body|upper\s+body|lower\s+body|head\s+only)\b',
    ],
    "Styles and Techniques": [
        r'\b(anime|manga|realistic|photorealistic|sketch|watercolor|oil\s+painting|digital\s+art|pixel\s+art|3d|2d)\b',
        r'\b(cel\s+shading|soft\s+shading|hard\s+shading|no\s+shading)\b',
    ],
    "Breasts": [
        r'\b(breast|breasts|chest|cleavage|underboob|sideboob|flat\s+chest|large\s+breasts|small\s+breasts|medium\s+breasts)\b',
    ],
    "Sleeves": [
        r'\b(long\s+sleeves|short\s+sleeves|sleeveless|detached\s+sleeves|puffy\s+sleeves)\b',
    ],
    "Neckwear": [
        r'\b(necklace|choker|scarf|tie|bow\s+tie|necktie)\b',
    ],
    "Wings": [
        r'\b(wing|wings|angel\s+wing|demon\s+wing|butterfly\s+wing)\b',
    ],
    "Tails": [
        r'\b(tail|tails|fox\s+tail|cat\s+tail|dog\s+tail|bunny\s+tail)\b',
    ],
    "Focus": [
        r'\b(focus|blur|bokeh|depth\s+of\s+field|shallow\s+focus)\b',
    ],
    "Swimsuits and Bodysuits": [
        r'\b(swimsuit|bikini|one\s+piece|bodysuit|leotard)\b',
    ],
    "Full Body Outfits": [
        r'\b(uniform|school\s+uniform|maid\s+uniform|nurse\s+uniform|sailor\s+uniform)\b',
        r'\b(armor|suit|tuxedo|wedding\s+dress)\b',
    ],
    "Sexual Attire": [
        r'\b(lingerie|bra|panties|underwear|nude|naked|topless|bottomless)\b',
    ],
    "Sexual Positions": [
        r'\b(cowgirl|missionary|doggy|69|blowjob|handjob)\b',
    ],
    "Sex Acts": [
        r'\b(sex|intercourse|penetration|oral|anal|vaginal)\b',
    ],
}

# 未分类的词条将放入此分类
UNCLASSIFIED_CATEGORY = "Unclassified"

# 预编译正则表达式以提高性能
COMPILED_PATTERNS = {}
for category, patterns in CLASSIFICATION_RULES.items():
    COMPILED_PATTERNS[category] = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]

def classify_term(term):
    """
    根据词条内容分类
    返回分类名称列表（一个词条可能属于多个分类）
    """
    term_lower = term.lower()
    categories = []
    
    for category, compiled_patterns in COMPILED_PATTERNS.items():
        for pattern in compiled_patterns:
            if pattern.search(term_lower):
                if category not in categories:
                    categories.append(category)
                break  # 找到一个匹配就足够了
    
    return categories if categories else [UNCLASSIFIED_CATEGORY]

def classify_lexicon(lexicon_data):
    """
    对词库进行分类
    """
    classified_data = {}
    
    # 初始化所有分类
    for category in CLASSIFICATION_RULES.keys():
        classified_data[category] = []
    classified_data[UNCLASSIFIED_CATEGORY] = []
    
    print("📚 开始分类词条...")
    
    # 遍历所有词条
    total_items = 0
    for category_name, items in lexicon_data.items():
        print(f"   处理分类: {category_name} ({len(items)} 个词条)...")
        total_items += len(items)
        
        for i, item in enumerate(items):
            term = item.get('term', '').strip()
            if not term:
                continue
            
            # 分类
            categories = classify_term(term)
            
            # 添加到对应分类（一个词条可能属于多个分类）
            for cat in categories:
                if cat not in classified_data:
                    classified_data[cat] = []
                
                # 检查是否已存在（避免重复）
                existing_terms = {item['term'] for item in classified_data[cat]}
                if term not in existing_terms:
                    classified_data[cat].append({
                        'term': term,
                        'translation': item.get('translation', '').strip()
                    })
            
            # 显示进度
            if (i + 1) % 10000 == 0:
                print(f"     已处理: {i + 1}/{len(items)} ({((i+1)/len(items)*100):.1f}%)")
    
    print(f"\n✅ 分类完成！共处理 {total_items} 个词条")
    
    # 统计信息
    print(f"\n📊 分类统计:")
    for category, items in sorted(classified_data.items(), key=lambda x: len(x[1]), reverse=True):
        if items:  # 只显示有内容的分类
            print(f"   - {category}: {len(items)} 个词条")
    
    return classified_data

def merge_knowledge_bases(classified_data, kb_data):
    """
    合并分类后的词库和knowledge_base.json
    """
    print("\n🔄 开始合并知识库...")
    
    merged_data = {}
    
    # 先添加knowledge_base.json的所有分类（优先级更高）
    for category, items in kb_data.items():
        merged_data[category] = items
        print(f"   ✓ 添加分类: {category} ({len(items)} 个词条)")
    
    # 添加分类后的词库
    for category, items in classified_data.items():
        if not items:  # 跳过空分类
            continue
            
        if category in merged_data:
            # 合并去重
            print(f"   ⚠ 分类 '{category}' 已存在，正在合并去重...")
            existing_terms = {item['term']: item for item in merged_data[category]}
            new_count = 0
            for item in items:
                term = item.get('term', '').strip()
                if term and term not in existing_terms:
                    existing_terms[term] = item
                    new_count += 1
            merged_data[category] = list(existing_terms.values())
            print(f"     添加了 {new_count} 个新词条，总计 {len(merged_data[category])} 个词条")
        else:
            # 新分类，直接添加
            merged_data[category] = items
            print(f"   ✓ 添加分类: {category} ({len(items)} 个词条)")
    
    return merged_data

def main():
    """
    主函数：分类词库并合并
    """
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        os.chdir(script_dir)
        
        lexicon_file = os.path.join(script_dir, '词库.json')
        kb_file = os.path.join(script_dir, 'knowledge_base.json')
        classified_file = os.path.join(script_dir, 'classified_lexicon.json')
        merged_file = os.path.join(script_dir, 'merged_knowledge_base.json')
        
        print("=" * 60)
        print("  词库分类与合并工具")
        print("=" * 60)
        print()
        
        # 步骤1: 读取词库文件
        print("📖 步骤1: 读取词库文件...")
        if not os.path.exists(lexicon_file):
            print(f"❌ 错误: 文件不存在: {lexicon_file}")
            return
        
        with open(lexicon_file, 'r', encoding='utf-8') as f:
            lexicon_data = json.load(f)
        print(f"✅ 已读取: {lexicon_file}")
        print()
        
        # 步骤2: 分类词条
        print("📚 步骤2: 分类词条...")
        classified_data = classify_lexicon(lexicon_data)
        print()
        
        # 保存分类后的词库
        print("💾 保存分类后的词库...")
        with open(classified_file, 'w', encoding='utf-8') as f:
            json.dump(classified_data, f, ensure_ascii=False, indent=2)
        print(f"✅ 已保存: {classified_file}")
        print()
        
        # 步骤3: 读取knowledge_base.json
        print("📖 步骤3: 读取knowledge_base.json...")
        kb_data = {}
        if os.path.exists(kb_file):
            with open(kb_file, 'r', encoding='utf-8') as f:
                kb_data = json.load(f)
            print(f"✅ 已读取: {kb_file}")
        else:
            print(f"⚠️  文件不存在: {kb_file}，将只使用分类后的词库")
        print()
        
        # 步骤4: 合并知识库
        print("🔄 步骤4: 合并知识库...")
        merged_data = merge_knowledge_bases(classified_data, kb_data)
        print()
        
        # 步骤5: 保存合并后的知识库
        print("💾 步骤5: 保存合并后的知识库...")
        with open(merged_file, 'w', encoding='utf-8') as f:
            json.dump(merged_data, f, ensure_ascii=False, indent=2)
        print(f"✅ 已保存: {merged_file}")
        print()
        
        # 最终统计
        print("=" * 60)
        print("✅ 处理完成！")
        print("=" * 60)
        print(f"📊 最终统计:")
        print(f"   - 分类数量: {len(merged_data)}")
        total_items = sum(len(items) for items in merged_data.values())
        print(f"   - 总词条数: {total_items}")
        print()
        print(f"📁 生成的文件:")
        print(f"   - {classified_file} (分类后的词库)")
        print(f"   - {merged_file} (合并后的知识库)")
        print()
        
    except FileNotFoundError as e:
        print(f"❌ 错误: 文件未找到 - {e}")
    except json.JSONDecodeError as e:
        print(f"❌ JSON解析错误: {e}")
    except Exception as e:
        print(f"❌ 处理文件时发生错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()

