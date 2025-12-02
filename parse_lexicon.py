import re
import json

def parse_md_to_json(md_content):
    """
    Parses the markdown lexicon content into a structured JSON format.
    """
    knowledge_base = {}
    current_category = None
    lines = md_content.split('\n')

    category_pattern = re.compile(r'^##\s+(.*?)(?:\s+\((.*)\))?$')
    artist_pattern = re.compile(r'^\s*-\s+\*\*(.*?)\*\*:\s+(.*)')
    example_pattern = re.compile(r'^\s*-\s+\*\*(.*?)\*\*\s*$')
    example_code_pattern = re.compile(r'^\s*`([^`]+)`\s*$')

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if not line:
            i += 1
            continue

        # Match category headers
        category_match = category_pattern.match(line)
        if category_match:
            category_name = category_match.group(1).strip()
            if "画师串" in category_name:
                current_category = "画师串"
                knowledge_base[current_category] = []
                knowledge_base["画师串使用示例"] = []
            else:
                current_category = category_name
                knowledge_base[current_category] = []
            i += 1
            continue

        if not current_category:
            i += 1
            continue
        
        # Handle "使用示例" subsection
        if "### 使用示例" in line:
            current_category = "画师串使用示例"
            i += 1
            continue

        if current_category == "画师串":
            artist_match = artist_pattern.match(line)
            if artist_match:
                name = artist_match.group(1).strip()
                description = artist_match.group(2).strip()
                knowledge_base[current_category].append({"name": name, "description": description})
            i += 1
            continue

        if current_category == "画师串使用示例":
            example_match = example_pattern.match(line)
            if example_match:
                title = example_match.group(1).strip()
                i += 1
                if i < len(lines):
                    code_line = lines[i].strip()
                    code_match = example_code_pattern.match(code_line)
                    if code_match:
                        combination = code_match.group(1).strip()
                        knowledge_base[current_category].append({"title": title, "combination": combination})
            i += 1
            continue

        # Handle regular term entries
        if line.startswith('-'):
            line_content = line[1:].strip()
            term = line_content
            translation = ""
            
            # Handle translations in parentheses
            match = re.match(r'^(.*?)\s*\((.*)\)\s*$', line_content)
            if match:
                term = match.group(1).strip()
                translation = match.group(2).strip()

            term = term.replace('\\', '').strip()
            translation = translation.replace('\\', '').strip()

            # Don't add empty terms
            if term:
                knowledge_base[current_category].append({"term": term, "translation": translation})
        
        i += 1

    return knowledge_base

def main():
    try:
        with open('银月佬的词库 v0.3.md', 'r', encoding='utf-8') as f:
            md_content = f.read()

        knowledge_base = parse_md_to_json(md_content)

        with open('knowledge_base.json', 'w', encoding='utf-8') as f:
            json.dump(knowledge_base, f, ensure_ascii=False, indent=2)

        print("知识库文件 'knowledge_base.json' 已成功生成。")

    except FileNotFoundError:
        print("错误: '银月佬的词库 v0.3.md' 文件未找到。")
    except Exception as e:
        print(f"处理文件时发生错误: {e}")

if __name__ == "__main__":
    main()
