import json
import os
import time
import translators as ts
from tqdm import tqdm

# --- 配置 ---
SOURCE_FILE = 'classified_lexicon.json'
# 您可以尝试不同的翻译器，例如 'google', 'bing', 'deepl'。'google' 通常最稳定。
TRANSLATOR_SERVICE = 'google' 
# 目标语言代码，'zh-CN' 代表简体中文
TARGET_LANGUAGE = 'zh-CN' 
# 每次翻译请求之间的延迟（秒），以避免被服务屏蔽
DELAY_BETWEEN_REQUESTS = 0.2 

def translate_lexicon():
    """
    读取分类后的知识库，并使用免费翻译服务翻译标签。
    """
    if not os.path.exists(SOURCE_FILE):
        print(f"❌ 错误：源文件 '{SOURCE_FILE}' 不存在。请先运行 classify_lexicon.py 生成该文件。")
        return

    print(f"📖 正在读取源知识库: {SOURCE_FILE}")
    with open(SOURCE_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    print("🚀 开始翻译任务...")
    
    total_tags_to_translate = 0
    for category, tags in data.items():
        if category == "未分类":
            continue
        for tag in tags:
            # 只翻译 translation 字段为空或与 term 相同的标签
            if not tag.get('translation') or tag.get('translation') == tag.get('term'):
                total_tags_to_translate += 1
    
    if total_tags_to_translate == 0:
        print("✅ 所有标签都已有翻译，无需执行翻译任务。")
        return

    # 使用 tqdm 创建一个进度条
    with tqdm(total=total_tags_to_translate, desc="翻译进度") as pbar:
        for category, tags in data.items():
            if category == "未分类":
                print(f"\n⏭️ 跳过 '未分类' 目录...")
                continue
            
            # print(f"\n🔍 正在处理目录: {category}")
            for tag in tags:
                term_to_translate = tag.get('term')
                # 检查是否需要翻译
                if term_to_translate and (not tag.get('translation') or tag.get('translation') == term_to_translate):
                    try:
                        # 执行翻译
                        translated_text = ts.translate_text(
                            term_to_translate,
                            translator=TRANSLATOR_SERVICE,
                            to_language=TARGET_LANGUAGE
                        )
                        tag['translation'] = translated_text
                        pbar.set_postfix_str(f"{term_to_translate} -> {translated_text}")
                        time.sleep(DELAY_BETWEEN_REQUESTS) # 增加延迟
                    except Exception as e:
                        pbar.set_postfix_str(f"翻译 '{term_to_translate}' 时出错: {e}")
                        time.sleep(1) # 如果出错，稍微多等一下
                    finally:
                        pbar.update(1) # 更新进度条

    print(f"\n💾 正在将翻译结果写回: {SOURCE_FILE}")
    with open(SOURCE_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("\n🎉 翻译任务完成！ 🎉")

if __name__ == "__main__":
    print("="*50)
    print("知识库标签翻译脚本".center(50))
    print("="*50)
    print(f"源文件: {SOURCE_FILE}")
    print(f"翻译服务: {TRANSLATOR_SERVICE}")
    print(f"目标语言: {TARGET_LANGUAGE}")
    print("注意：翻译过程可能需要较长时间，具体取决于需要翻译的标签数量。")
    print("="*50)
    
    try:
        translate_lexicon()
    except Exception as e:
        print(f"\n❌ 发生严重错误: {e}")
        print("请检查您的网络连接和依赖库是否已正确安装。")
