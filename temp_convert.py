# -*- coding: utf-8 -*-
import json
import os

# 使用当前文件所在目录
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)

lexicon_file = os.path.join(script_dir, '词库.json')
print(f"📖 正在读取词库.json文件...")
print(f"   文件路径: {lexicon_file}")

# 读取原始词库文件
with open(lexicon_file, 'r', encoding='utf-8') as f:
    lexicon_data = json.load(f)

print(f"✅ 文件读取完成，开始转换...")

# 创建新的知识库格式
knowledge_base = {}

# 遍历原始数据
for category_name, items in lexicon_data.items():
    print(f"   处理分类: {category_name} ({len(items)} 个词条)...")
    converted_items = []
    
    for i, item in enumerate(items):
        # 转换为新格式
        converted_item = {
            "term": item.get("提示词", "").strip(),
            "translation": item.get("Unnamed: 2", "").strip()
        }
        
        # 只添加非空term的项
        if converted_item["term"]:
            converted_items.append(converted_item)
        
        # 每处理10000条显示一次进度
        if (i + 1) % 10000 == 0:
            print(f"     已处理: {i + 1}/{len(items)}")
    
    # 如果分类有内容，添加到知识库
    if converted_items:
        knowledge_base[category_name] = converted_items

print("💾 正在保存转换后的文件...")
# 保存转换后的文件（覆盖原文件）
with open(lexicon_file, 'w', encoding='utf-8') as f:
    json.dump(knowledge_base, f, ensure_ascii=False, indent=2)

print(f"\n✅ 转换完成！")
print(f"   - 分类数量: {len(knowledge_base)}")
total_items = 0
for category, items in knowledge_base.items():
    print(f"   - {category}: {len(items)} 个词条")
    total_items += len(items)
print(f"   - 总计: {total_items} 个词条")



