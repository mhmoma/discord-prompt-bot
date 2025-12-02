# -*- coding: utf-8 -*-
"""
合并词库.json和knowledge_base.json，创建统一的知识库
"""
import json
import os

def merge_knowledge_bases():
    """
    合并两个知识库文件
    """
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        os.chdir(script_dir)
        
        lexicon_file = os.path.join(script_dir, '词库.json')
        kb_file = os.path.join(script_dir, 'knowledge_base.json')
        merged_file = os.path.join(script_dir, 'merged_knowledge_base.json')
        
        print("📖 正在读取文件...")
        
        # 读取词库.json
        print(f"   读取: {lexicon_file}")
        with open(lexicon_file, 'r', encoding='utf-8') as f:
            lexicon_data = json.load(f)
        
        # 读取knowledge_base.json
        print(f"   读取: {kb_file}")
        with open(kb_file, 'r', encoding='utf-8') as f:
            kb_data = json.load(f)
        
        print("✅ 文件读取完成，开始合并...")
        
        # 创建合并后的知识库
        merged_kb = {}
        
        # 先添加knowledge_base.json的所有分类（优先级更高，更详细）
        for category, items in kb_data.items():
            merged_kb[category] = items
            print(f"   ✓ 添加分类: {category} ({len(items)} 个词条)")
        
        # 添加词库.json的分类
        for category, items in lexicon_data.items():
            if category in merged_kb:
                # 如果分类已存在，合并词条（去重）
                print(f"   ⚠ 分类 '{category}' 已存在，正在合并去重...")
                existing_terms = {item['term']: item for item in merged_kb[category]}
                new_count = 0
                for item in items:
                    term = item.get('term', '').strip()
                    if term and term not in existing_terms:
                        existing_terms[term] = item
                        new_count += 1
                merged_kb[category] = list(existing_terms.values())
                print(f"     添加了 {new_count} 个新词条，总计 {len(merged_kb[category])} 个词条")
            else:
                # 新分类，直接添加
                merged_kb[category] = items
                print(f"   ✓ 添加分类: {category} ({len(items)} 个词条)")
        
        print("💾 正在保存合并后的知识库...")
        with open(merged_file, 'w', encoding='utf-8') as f:
            json.dump(merged_kb, f, ensure_ascii=False, indent=2)
        
        print(f"\n✅ 合并完成！")
        print(f"   - 输出文件: {merged_file}")
        print(f"   - 分类数量: {len(merged_kb)}")
        total_items = 0
        for category, items in merged_kb.items():
            total_items += len(items)
        print(f"   - 总计: {total_items} 个词条")
        
        # 统计信息
        print(f"\n📊 分类统计:")
        for category, items in sorted(merged_kb.items(), key=lambda x: len(x[1]), reverse=True):
            print(f"   - {category}: {len(items)} 个词条")
        
    except FileNotFoundError as e:
        print(f"❌ 错误: 文件未找到 - {e}")
    except json.JSONDecodeError as e:
        print(f"❌ JSON解析错误: {e}")
    except Exception as e:
        print(f"❌ 处理文件时发生错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    merge_knowledge_bases()



