# -*- coding: utf-8 -*-
import json
import os
import sys

def convert_lexicon_to_knowledge_base():
    """
    将词库.json转换为knowledge_base.json的格式
    """
    try:
        # 获取脚本所在目录
        if getattr(sys, 'frozen', False):
            # 如果是打包后的exe文件
            script_dir = os.path.dirname(sys.executable)
        else:
            # 如果是Python脚本
            script_dir = os.path.dirname(os.path.abspath(__file__))
        
        os.chdir(script_dir)
        lexicon_file = os.path.join(script_dir, '词库.json')
        
        print(f"📖 正在读取词库.json文件...")
        print(f"   工作目录: {os.getcwd()}")
        print(f"   文件路径: {lexicon_file}")
        
        if not os.path.exists(lexicon_file):
            print(f"❌ 错误: 文件不存在: {lexicon_file}")
            return
        
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
                # 转换为新格式，确保值是字符串类型
                term_value = item.get("提示词", "")
                translation_value = item.get("Unnamed: 2", "")
                
                # 转换为字符串并去除空白
                term = str(term_value).strip() if term_value is not None else ""
                translation = str(translation_value).strip() if translation_value is not None else ""
                
                converted_item = {
                    "term": term,
                    "translation": translation
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
        
    except FileNotFoundError:
        print("❌ 错误: '词库.json' 文件未找到。")
        print(f"   当前工作目录: {os.getcwd()}")
    except json.JSONDecodeError as e:
        print(f"❌ JSON解析错误: {e}")
    except Exception as e:
        print(f"❌ 处理文件时发生错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    convert_lexicon_to_knowledge_base()

