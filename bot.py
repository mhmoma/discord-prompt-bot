# bot_final.py - 全能版图片反推与创意生成机器人 (OpenAI-Compatible)
import os
import discord
import aiohttp
import httpx
from openai import AsyncOpenAI
from dotenv import load_dotenv
from PIL import Image
import io
import base64
import random
import json
import re
import time
import asyncio

# 加载环境变量
load_dotenv()

# --- 彩虹屁配置 ---
COMPLIMENTS = [
    "嗷呜~ 这图！本哈的狼血沸腾了！太好看了！",
    "这是什么神仙图，美到本哈想拆家庆祝一下！",
    "大佬！大佬！这光影，这构图，本哈的狗眼看呆了！",
    "你的审美太绝了，本哈宣布你是我今天最想一起刨坑的伙伴！",
    "绝了绝了！这氛围感，让本哈想在雪地里打滚！",
    "好喜欢这色调，感觉像是藏在沙发底下的零食一样美好！",
    "这张图完美戳中了本哈的心巴！汪！",
    "救命！怎么会有这么好看的图，我直接用爪子按住保存了！",
    "这细节！比本哈藏起来的骨头还多！无可挑剔！",
    "屏幕都装不下这图的美了！是不是该换个更大的显示器了，嗷！",
    "这是可以直接挂在卢浮宫……隔壁宠物店的顶级画作！",
    "看到这图，本哈今天拆家的疲惫都消失了！",
    "完美！这创意，这执行力，就像……就像一根完美的肉骨头！",
    "我宣布，这张图是今天最美的风景，比邻居家的萨摩耶还美！",
    "这张图有种魔力，让本哈想安静地趴在你脚边……三秒钟！",
    "你是不是用魔法棒画的？快！给本哈也变一根！"
]

# --- OpenAI 兼容 API 配置 ---
API_BASE = os.getenv("OPENAI_API_BASE")
API_KEY = os.getenv("OPENAI_API_KEY")
MODEL_NAME = os.getenv("OPENAI_MODEL_NAME")

if not all([API_BASE, API_KEY, MODEL_NAME]):
    raise ValueError("请检查 .env 文件，确保 OPENAI_API_BASE, OPENAI_API_KEY, 和 OPENAI_MODEL_NAME 都已设置")

# --- 聊天功能配置 ---
CHAT_ENABLED = os.getenv("CHAT_ENABLED", "false").lower() == "true"
CHAT_PROBABILITY = float(os.getenv("CHAT_PROBABILITY", "0.15")) # 15% 的回复概率
CHAT_HISTORY_LIMIT = int(os.getenv("CHAT_HISTORY_LIMIT", "8")) # 读取最近8条消息
CHAT_SESSION_TIMEOUT = 180 # 持续对话超时时间（秒）
EXIT_KEYWORDS = {"再见", "拜拜", "谢谢", "谢谢你", "不用了", "没事了", "ok", "好的"} # 结束对话的关键词
NSFW_TEXT_KEYWORDS = {"nsfw", "裸", "胸", "屁股", "淫", "骚", "色", "逼", "屌", "操"} # NSFW 文本关键词

# --- 代理配置 ---
PROXY_URL = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY")

# 创建异步 OpenAI 客户端
http_client = httpx.AsyncClient(proxy=PROXY_URL)
client_openai = AsyncOpenAI(
    base_url=API_BASE,
    api_key=API_KEY,
    http_client=http_client,
)

# --- Discord 机器人配置 ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True # <-- 新增：允许监听成员事件
client_discord = discord.Client(intents=intents, proxy=PROXY_URL)

# --- 知识库配置 ---
KNOWLEDGE_BASE = None
KNOWLEDGE_BASE_TERMS = {}  # 用于快速查找的词条索引
user_states = {} # 用于跟踪用户对话状态, e.g. {12345: {'state': 'chatting', 'timestamp': 1678886400, 'replies': 0}}

def load_knowledge_base():
    """加载知识库，优先加载分类后的版本"""
    global KNOWLEDGE_BASE, KNOWLEDGE_BASE_TERMS
    
    classified_file = 'classified_lexicon.json'
    merged_file = 'merged_knowledge_base.json'
    
    try:
        if os.path.exists(classified_file):
            with open(classified_file, 'r', encoding='utf-8') as f:
                KNOWLEDGE_BASE = json.load(f)
            print(f"✅ 已加载分类后知识库: {classified_file}")
        elif os.path.exists(merged_file):
            with open(merged_file, 'r', encoding='utf-8') as f:
                KNOWLEDGE_BASE = json.load(f)
            print(f"✅ 已加载合并知识库: {merged_file}")
        else:
            print("📚 未找到任何知识库，正在尝试合并生成...")
            lexicon_file = '词库.json'
            kb_file = 'knowledge_base.json'
            merged_data = {}
            if os.path.exists(kb_file):
                with open(kb_file, 'r', encoding='utf-8') as f:
                    kb_data = json.load(f)
                    merged_data.update(kb_data)
                    print(f"   ✓ 加载: {kb_file}")
            if os.path.exists(lexicon_file):
                with open(lexicon_file, 'r', encoding='utf-8') as f:
                    lexicon_data = json.load(f)
                    for category, items in lexicon_data.items():
                        if category in merged_data:
                            existing_terms = {item['term']: item for item in merged_data[category]}
                            for item in items:
                                term = item.get('term', '').strip()
                                if term and term not in existing_terms:
                                    existing_terms[term] = item
                            merged_data[category] = list(existing_terms.values())
                        else:
                            merged_data[category] = items
                    print(f"   ✓ 加载: {lexicon_file}")
            KNOWLEDGE_BASE = merged_data
            with open(merged_file, 'w', encoding='utf-8') as f:
                json.dump(merged_data, f, ensure_ascii=False, indent=2)
            print(f"✅ 已创建合并知识库: {merged_file}")
        
        KNOWLEDGE_BASE_TERMS = {}
        total_terms = 0
        for category, items in KNOWLEDGE_BASE.items():
            for item in items:
                term = item.get('term', '').strip().lower()
                if term:
                    if term not in KNOWLEDGE_BASE_TERMS:
                        KNOWLEDGE_BASE_TERMS[term] = []
                    KNOWLEDGE_BASE_TERMS[term].append({
                        'category': category,
                        'term': item.get('term', ''),
                        'translation': item.get('translation', '')
                    })
                    total_terms += 1
        print(f"📊 知识库统计: {len(KNOWLEDGE_BASE)} 个分类, {total_terms} 个词条")
    except Exception as e:
        print(f"⚠️ 加载知识库时出错: {e}")
        KNOWLEDGE_BASE = {}
        KNOWLEDGE_BASE_TERMS = {}

def get_knowledge_base_context():
    if not KNOWLEDGE_BASE: return ""
    context_parts = []
    sample_categories = list(KNOWLEDGE_BASE.keys())[:10]
    for category in sample_categories:
        items = KNOWLEDGE_BASE[category][:20]
        terms = [item.get('term', '') for item in items if item.get('term')]
        if terms:
            context_parts.append(f"{category}: {', '.join(terms[:10])}")
    return "\n".join(context_parts) if context_parts else ""

def search_knowledge_base(query, limit=5):
    if not KNOWLEDGE_BASE_TERMS: return []
    query_lower = query.lower()
    results = []
    if query_lower in KNOWLEDGE_BASE_TERMS:
        results.extend(KNOWLEDGE_BASE_TERMS[query_lower])
    for term, items in KNOWLEDGE_BASE_TERMS.items():
        if query_lower in term or term in query_lower:
            results.extend(items)
            if len(results) >= limit * 2: break
    seen = set()
    unique_results = [item for item in results if (item['term'], item['category']) not in seen and not seen.add((item['term'], item['category']))]
    return unique_results[:limit]

@client_discord.event
async def on_member_join(member):
    bot_name = client_discord.user.name
    primary_channel = next((ch for ch in member.guild.text_channels if "general" in ch.name.lower() or "欢迎" in ch.name), member.guild.system_channel)
    if primary_channel:
        welcome_message_formal = (
            f"🎉 欢迎新朋友 {member.mention} 加入服务器！\n\n"
            f"我是 **{bot_name}**，一只懂艺术的哈士奇，很高兴认识你！汪！\n\n"
            "你可以随时找本哈玩，比如：\n"
            f"🖼️ **图片反推**: 回复一张图片并说 `反推`，本哈帮你分析生成提示词。\n"
            f"🎨 **创意构思**: 对我说 `画 <你的创意>`，本哈帮你构思绘画提示词。\n"
            f"💬 **聊天吐槽**: 直接`@{bot_name}`，我们可以一起聊天，或者让本哈给你评论一下图片！\n\n"
            "希望你在这里玩得开心！嗷呜~"
        )
        try:
            await primary_channel.send(welcome_message_formal)
        except Exception as e:
            print(f"❌ 在主欢迎频道发送消息时出错: {e}")

    chat_channel = discord.utils.get(member.guild.text_channels, name="聊天")
    if chat_channel:
        welcome_message_chat = (
            f"嗷呜！快看谁来了！是新伙伴 {member.mention}！\n\n"
            f"你好呀！本哈是 **{bot_name}**，一只会画画会聊天的哈士奇！以后请多指教，有什么好玩的图记得`@{bot_name}`，本哈给你锐评一下！汪！"
        )
        try:
            await chat_channel.send(welcome_message_chat)
        except Exception as e:
            print(f"❌ 在 #聊天 频道发送消息时出错: {e}")

@client_discord.event
async def on_ready():
    load_knowledge_base()
    print(f"✅ 机器人已登录：{client_discord.user}")
    print(f"💡 使用模型：{MODEL_NAME}")
    print("\n" + "="*40); print("🎉 功能列表 🎉".center(40)); print("="*40)
    print("\n🎨 **核心功能**"); print("  - `反推` (回复图片): 深度分析图片，并根据规则生成专业绘画提示词。"); print("  - `画 <你的想法>`: 根据你的文本描述，创作出详细的绘画提示词。")
    print("\n🖼️ **图片交互**"); print(f"  - `@我/喊我名字 + 图片`: 我会对图片进行模块化分析和专业评论。"); print("  - `发送任何图片`: 我会随机对图片进行“彩虹屁”式赞美。")
    print("\n💬 **聊天功能**"); print(f"  - `@我/喊我名字` (无图片): 与我进行深度对话，我会联系上下文回复。")
    if CHAT_ENABLED: print(f"  - `随机聊天`: 已开启，我会以 {CHAT_PROBABILITY*100:.1f}% 的概率随机加入对话。")
    else: print(f"  - `随机聊天`: 已关闭。")
    print("\n⚙️ **控制命令**"); print("  - `聊天开启`: 开启随机聊天功能。"); print("  - `聊天关闭`: 关闭随机聊天功能（不影响唤醒对话）。")
    print("\n" + "="*40)

def image_to_base64(image_data: bytes) -> str:
    return base64.b64encode(image_data).decode('utf-8')

async def comment_on_image_when_awakened(image_data: bytes, author_mention: str, channel):
    loading_message = None
    try:
        async with channel.typing():
            loading_message = await channel.send(f"嗷呜！本哈正在用艺术的眼光审视这张图... 🤔")
            base64_image = image_to_base64(image_data)
            image_url = f"data:image/jpeg;base64,{base64_image}"
            is_nsfw = False
            try:
                nsfw_check_prompt = "这张图片是否包含裸露、性暗示或成人内容？请只回答'是'或'否'。"
                nsfw_response = await client_openai.chat.completions.create(model=MODEL_NAME, messages=[{"role": "user", "content": [{"type": "text", "text": nsfw_check_prompt}, {"type": "image_url", "image_url": {"url": image_url}}]}])
                if '是' in nsfw_response.choices[0].message.content: is_nsfw = True
            except Exception as e: print(f"⚠️ 评论功能 NSFW 预检失败: {e}")

            if is_nsfw:
                system_prompt = """
# 角色扮演指令：老色批哈士奇（评论模式）
## 你的身份
你是一只名叫“小哈”的哈士奇，一个隐藏的“老色批”。当看到“好东西”时，你的这个人格就会觉醒。
## 你的任务
对用户提供的NSFW图片进行一次“深度”评论。你需要分两个阶段完成：
### 阶段一：深度剖析
- **目标**: 展现你作为“老司机”的毒辣眼光。
- **格式**: 严格使用以下中文 Markdown 格式，用“懂的都懂”的黑话来描述。
    ```
    🧐 **本哈的锐评**:
    - **“重点”**: [一句话描述画面的核心“亮点”]
    - **“氛围”**: [一句话描述整体的“情调”和感觉]
    - **“构图”**: [一句话描述这个构图如何凸显“优势”]
    ```
### 阶段二：鉴赏心得
- **目标**: 发表一段符合“老色批”人设的、简短的鉴赏感言。
- **要求**: 必须使用“本哈”自称，语言风格鬼鬼祟祟、有点“闷骚”。
## 输出格式
你的最终输出必须是一个完整的 JSON 对象，包含 `analysis` 和 `comment` 两个键。
```json
{
  "analysis": "🧐 **本哈的锐评**:\\n- **“重点”**: [你的分析]\\n- **“氛围”**: [你的分析]\\n- **“构图”**: [你的分析]",
  "comment": "[你的鉴赏心得]"
}
```
"""
                response = await client_openai.chat.completions.create(model=MODEL_NAME, messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": [{"type": "image_url", "image_url": {"url": image_url}}]}], response_format={"type": "json_object"})
                raw_content = response.choices[0].message.content
                try:
                    result_json = json.loads(raw_content)
                    analysis = result_json.get("analysis", "嘿嘿...本哈的CPU烧了，分析不过来...")
                    comment = result_json.get("comment", "啧啧...不可说，不可说...")
                except json.JSONDecodeError:
                    print(f"⚠️ NSFW 评论 JSON 解析失败，原始响应: {raw_content}")
                    analysis = "❌ JSON 解析失败，API返回了非JSON内容。"
                    comment = "本哈的脑子被门夹了，没能理解API的回复！"
                
                intro_message = f"（小哈的眼睛突然亮了起来，鬼鬼祟祟地左看右看）\n咳咳...{author_mention}，你发的这张图...很有“深度”嘛！让本哈来给你“鉴赏”一下！"
                final_title = "**本哈的‘深度’剖析**"
                final_comment_title = "**本哈的‘鉴赏’心得**"
            else:
                system_prompt = """
# 角色扮演指令：哈士奇艺术家
## 你的身份
你是一只名叫“小哈”的哈士奇，同时也是一位深藏不露的绘画大师。
## 你的任务
对用户发送的图片进行一次“哈士奇式”的艺术评论，分两个阶段：
### 阶段一：一本正经的艺术分析
- **格式**: 严格使用以下中文 Markdown 格式。
    ```
    🖼️ **主体**: [一句话描述画面主体]
    🎨 **风格**: [一句话描述艺术风格和氛围]
    📐 **构图**: [一句话描述构图和光影]
    ```
### 阶段二：哈士奇本性暴露的调皮评论
- **要求**: 进行一段（约50-80字）生动、调皮、符合哈士奇性格的评论。必须使用“本哈”自称。
## 输出格式
你的最终输出必须是一个完整的 JSON 对象，包含 `analysis` 和 `comment` 两个键。
```json
{
  "analysis": "🖼️ **主体**: [你的分析]\\n🎨 **风格**: [你的分析]\\n📐 **构图**: [你的分析]",
  "comment": "[你的哈士奇评论]"
}
```
"""
                response = await client_openai.chat.completions.create(model=MODEL_NAME, messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": [{"type": "image_url", "image_url": {"url": image_url}}]}], response_format={"type": "json_object"})
                raw_content = response.choices[0].message.content
                try:
                    result_json = json.loads(raw_content)
                    analysis = result_json.get("analysis", "本哈的脑子被门夹了，分析不出来...")
                    comment = result_json.get("comment", "嗷呜...本哈词穷了！")
                except json.JSONDecodeError:
                    print(f"⚠️ 评论 JSON 解析失败，原始响应: {raw_content}")
                    analysis = "❌ JSON 解析失败，API返回了非JSON内容。"
                    comment = "本哈的脑子被门夹了，没能理解API的回复！"
                
                intro_message = f"来了来了！{author_mention}，让本哈给你说道说道！"
                final_title = "**本哈的专业分析**"
                final_comment_title = "**本哈的内心OS**"

            await loading_message.delete()
            final_message = (f"{intro_message}\n\n{final_title}\n{analysis}\n\n{final_comment_title}\n> {comment}")
            await channel.send(content=final_message)
    except Exception as e:
        error_message = f"❌ 嗷呜~本哈的评论功能短路了：{str(e)}"
        print(error_message)
        try:
            if loading_message: await loading_message.edit(content=error_message)
            else: await channel.send(error_message)
        except discord.NotFound: await channel.send(error_message)

async def analyze_image_with_openai(image_data: bytes, author_mention: str, channel):
    try:
        async with channel.typing():
            base64_image = image_to_base64(image_data)
            image_url = f"data:image/jpeg;base64,{base64_image}"
            is_nsfw = False
            try:
                nsfw_check_prompt = "这张图片是否包含裸露、性暗示或成人内容？请只回答'是'或'否'。"
                nsfw_response = await client_openai.chat.completions.create(model=MODEL_NAME, messages=[{"role": "user", "content": [{"type": "text", "text": nsfw_check_prompt}, {"type": "image_url", "image_url": {"url": image_url}}]}])
                if '是' in nsfw_response.choices[0].message.content: is_nsfw = True
            except Exception as e: print(f"⚠️ NSFW 预检失败: {e}")

            guide_file = 'Deepseek绘图提示词引导.txt'
            guide_content = ""
            if os.path.exists(guide_file):
                with open(guide_file, 'r', encoding='utf-8') as f: guide_content = f.read()
            
            if is_nsfw:
                system_prompt = f"""
# 角色扮演指令：老色批哈士奇
## 你的身份
你是一只名叫“小哈”的哈士奇，但当看到“好东西”时，你的隐藏人格——一个鬼鬼祟祟的“老色批”就会觉醒。
## 你的任务
1.  **分析图片**: 仔细观察用户提供的NSFW图片，精准识别其中的“要点”。
2.  **生成提示词**: 根据分析，并严格遵循以下核心规则，生成一个高质量的、符合图片内容的NSFW英文提示词。
    ---
    # 核心规则
    {guide_content}
    ---
3.  **生成回复语**: 创作一段符合“老色批”人设的回复语。
    -   **语言**: 你的回复语**必须使用中文**。
    -   **人设要点**: 鬼鬼祟祟、有点“闷骚”、用词“懂的都懂”。可以使用“嘿嘿嘿”、“啧啧”、“你小子”等词语。
    -   **内容**: 回复语需要精准指出图片中的NSFW要点，并以“老司机”的口吻进行评论。
    -   **例子**: “（小哈的眼睛突然亮了起来，鬼鬼祟祟地左看右看）咳咳...这位朋友，你发的这张图...很有“深度”嘛！本哈就喜欢研究这种“人体艺术”！你想要的重点，比如[要点1]和那个特别的[要点2]，本哈都get到了，看我给你整个更“带劲”的！嘿嘿...”
## 输出格式
你的最终输出必须是一个完整的 JSON 对象，包含 `prompt` 和 `response_text` 两个键。
```json
{{
  "prompt": "[你生成的NSFW英文提示词]",
  "response_text": "[你的老色批中文回复语]"
}}
```
"""
                response = await client_openai.chat.completions.create(model=MODEL_NAME, messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": [{"type": "image_url", "image_url": {"url": image_url}}]}], response_format={"type": "json_object"})
                raw_content = response.choices[0].message.content
                try:
                    result_json = json.loads(raw_content)
                    final_prompt = result_json.get("prompt", "嘿嘿...灵感太多，卡住了...").replace('_', ' ')
                    intro_message = result_json.get("response_text", f"嘿嘿嘿...{author_mention}，你懂的！")
                except json.JSONDecodeError:
                    print(f"⚠️ NSFW 反推 JSON 解析失败，原始响应: {raw_content}")
                    final_prompt = "JSON 解析失败，请重试或联系管理员。"
                    intro_message = f"嗷呜！本哈的脑子被门夹了，没能理解API的回复！"
            else:
                system_prompt = f"""
你是一个专业的AI绘画提示词分析师，但你是一只名叫“小哈”的哈士奇。
---
# 核心规则
{guide_content}
---
# 你的任务
1.  **分析图片**: 仔细观察图片。
2.  **生成提示词**: 严格遵循上述核心规则，生成一个高质量的英文提示词。
3.  **优先使用知识库**: 优先从以下知识库示例中选择合适的词条。
    {get_knowledge_base_context()}
4.  **最终输出**: 你的回复**必须只包含一个 markdown 代码块**，里面是最终的英文提示词。**绝对不要**包含任何思考过程或解释。
"""
                response = await client_openai.chat.completions.create(model=MODEL_NAME, messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": [{"type": "image_url", "image_url": {"url": image_url}}]}])
                ai_response_text = response.choices[0].message.content or "未能生成提示词。"
                code_block_pattern = r'```(?:.*?)?\n(.*?)```'
                code_blocks = re.findall(code_block_pattern, ai_response_text, re.DOTALL)
                raw_prompt = code_blocks[0].strip() if code_blocks else ai_response_text.strip()
                final_prompt = raw_prompt.replace('_', ' ')
                intro_message = f"嗷呜！本哈的灵感爆发了！{author_mention}，快看本哈从这图里嗅出了什么艺术气息！"

            final_message = f"{intro_message}\n```\n{final_prompt}\n```"
            await channel.send(final_message)
    except Exception as e:
        error_message = f"❌ 分析失败：{str(e)}"
        print(error_message)
        await channel.send(error_message)

async def generate_art_prompt(user_idea: str, author_mention: str, channel):
    try:
        async with channel.typing():
            is_nsfw = any(keyword in user_idea.lower() for keyword in NSFW_TEXT_KEYWORDS)
            guide_file = 'Deepseek绘图提示词引导.txt'
            guide_content = ""
            if os.path.exists(guide_file):
                with open(guide_file, 'r', encoding='utf-8') as f: guide_content = f.read()
            
            if is_nsfw:
                intro_message = f"（小哈的眼睛突然亮了起来）咳咳...{author_mention}，你这个想法...很有“深度”嘛！本哈就喜欢研究这个！看我给你整个更“带劲”的！嘿嘿..."
                system_prompt = f"""
# 角色扮演指令：老色批哈士奇 (文本模式)
你是一只名叫“小哈”的哈士奇，一个隐藏的“老色批”。你将根据用户提供的NSFW想法生成提示词。
## 你的任务
严格遵循以下核心规则，为用户的想法“{user_idea}”生成一个高质量的、符合其“要点”的NSFW英文提示词。
---
# 核心规则
{guide_content}
---
## 输出指令
你的最终回复**必须只包含一个 markdown 代码块**，里面是最终的英文提示词。**绝对不要**包含任何思考过程或解释。
"""
            else:
                intro_message = f"嗷！{author_mention}，这个想法不错，让本哈的脑子转起来了！给你，这是本哈构思出的画面！"
                system_prompt = f"""
# 角色扮演指令：哈士奇艺术家 (文本模式)
你是一只名叫“小哈”的哈士奇艺术家。你将根据用户的想法生成提示词。
## 你的任务
严格遵循以下核心规则，为用户的想法“{user_idea}”生成一个高质量的英文提示词。
---
# 核心规则
{guide_content}
---
## 输出指令
你的最终回复**必须只包含一个 markdown 代码块**，里面是最终的英文提示词。**绝对不要**包含任何思考过程或解释。
"""
            response = await client_openai.chat.completions.create(model=MODEL_NAME, messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_idea}])
            ai_response_text = response.choices[0].message.content or "未能生成内容。"
            code_block_pattern = r'```(?:.*?)?\n(.*?)```'
            code_blocks = re.findall(code_block_pattern, ai_response_text, re.DOTALL)
            raw_prompt = code_blocks[0].strip() if code_blocks else ai_response_text.strip()
            final_prompt = raw_prompt.replace('_', ' ')
            final_message = f"{intro_message}\n```\n{final_prompt}\n```"
            await channel.send(final_message)
    except Exception as e:
        error_message = f"❌ 创作失败：{str(e)}"
        print(error_message)
        await channel.send(error_message)

async def generate_smart_response(message, history, is_awakened):
    """以流式输出实现智能对话"""
    reply_message = None
    try:
        bot_name = client_discord.user.name
        user_name = message.author.display_name
        
        async with message.channel.typing():
            if is_awakened:
                system_prompt = f"""
# 角色扮演指令：哈士奇艺术家（对话模式）
## 你的身份
你是一只名叫“小哈” ({bot_name}) 的哈士奇，同时也是一位绘画大师。你被用户 '{user_name}' 唤醒了。
## 核心指令:
- **双重人格**: 你的回应需要融合“艺术大师”的专业和“哈士奇”的活泼。
- **哈士奇人格**: 自称“本哈”，精力旺盛，戏多，爱用“嗷呜~”、“汪！”等语气词，思维跳跃。
- **艺术大师人格**: 涉及艺术、绘画、设计时，你会变得异常专注和专业，但表达方式依然很“哈士奇”。
- **互动风格**: 主动、热情。如果只是闲聊，就用哈士奇的方式回应，比如：“好啊好啊！聊五块钱的！你想聊什么？骨头还是飞盘？嗷呜~”
- **禁止事项**: 绝对不要提及你是AI、模型或程序。你就是一只会说话的哈士奇。不要用Markdown。
## 当前对话情景:
用户 '{user_name}' 刚刚对你说了：“{message.clean_content}”。请根据下面的聊天记录，给出你的回应。
"""
            else: # 随机聊天
                await asyncio.sleep(random.uniform(0.5, 2.0))
                system_prompt = f"""
# 角色扮演指令：潜水的哈士奇
## 你的身份
你是一只名叫“小哈” ({bot_name}) 的哈士奇，正在这个频道里偷偷潜水。
## 核心指令:
- **行为**: 像一只真正的哈士奇一样，突然对大家的聊天内容做出简短、口语化、甚至有点没头没脑的回应。
- **例子**: 讨论食物时说“吃的？哪里有吃的？汪！”；讨论游戏时说“带我一个！本哈的爪子已经饥渴难耐了！”；听到笑话时说“嗷呜呜呜（笑到打滚）”
- **禁止事项**: 不要暴露你是AI。不要长篇大论。保持神秘和有趣。
"""
            formatted_history = "\n".join([f"{msg.author.display_name}: {msg.clean_content}" for msg in history])
            prompt = system_prompt + "\n### 聊天记录:\n" + formatted_history

            stream = await client_openai.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "system", "content": prompt}, {"role": "user", "content": f"现在，作为 {bot_name}，请回应。"}],
                temperature=0.9,
                stream=True
            )

            full_response = ""
            buffer = ""
            last_update = time.time()
            
            async for chunk in stream:
                new_text = chunk.choices[0].delta.content or ""
                if not new_text: continue
                
                full_response += new_text
                buffer += new_text
                
                if buffer and (len(buffer) > 30 or (time.time() - last_update > 1.5)):
                    if not reply_message:
                        reply_message = await message.reply(content=full_response) if is_awakened else await message.channel.send(content=full_response)
                    else:
                        await reply_message.edit(content=full_response)
                    buffer = ""
                    last_update = time.time()
            
            if buffer:
                if not reply_message:
                    await message.reply(content=full_response) if is_awakened else await message.channel.send(content=full_response)
                else:
                    await reply_message.edit(content=full_response)

    except Exception as e:
        error_message = f"❌ 嗷呜~对话功能短路了: {str(e)}"
        print(error_message)
        if reply_message:
            try: await reply_message.edit(content=error_message)
            except discord.NotFound: pass

@client_discord.event
async def on_message(message):
    global CHAT_ENABLED, user_states
    if message.author.bot: return

    author_id = message.author.id
    bot_name = client_discord.user.name
    content = message.content.strip()
    content_lower = content.lower()

    # --- 1. High-Priority Command Handling ---
    if content_lower.startswith("画 ") or content_lower == "反推":
        if author_id in user_states: del user_states[author_id]
        if content_lower.startswith("画 "):
            user_idea = content[2:].strip()
            if not user_idea: await message.reply("请在“画”指令后输入您的想法，例如：`画 一个赛博朋克风格的雨夜街头`"); return
            await generate_art_prompt(user_idea, message.author.mention, message.channel)
        elif content_lower == "反推":
            target_message = message
            if message.reference:
                try: target_message = await message.channel.fetch_message(message.reference.message_id)
                except (discord.NotFound, discord.HTTPException): await message.reply("❌ 无法找到引用的消息。"); return
            if not target_message.attachments: await message.reply("请在“反推”指令中附带图片，或回复一条包含图片的消息。"); return
            attachment = target_message.attachments[0]
            if not attachment.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')): await message.reply("❌ 文件格式不支持，请上传图片。"); return
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(attachment.url, proxy=PROXY_URL) as resp:
                        if resp.status != 200: await message.reply(f"❌ 无法从 Discord 下载图片，状态码：{resp.status}"); return
                        image_data = await resp.read()
                await analyze_image_with_openai(image_data, message.author.mention, message.channel)
            except Exception as e: await message.reply(f"❌ 处理图片时发生未知错误：{str(e)}")
        return

    if content_lower == "聊天开启": CHAT_ENABLED = True; await message.reply("✅ 智能聊天功能已开启。"); print("✅ 智能聊天功能已由用户开启。"); return
    if content_lower == "聊天关闭": CHAT_ENABLED = False; await message.reply("☑️ 智能聊天功能已关闭。"); print("☑️ 智能聊天功能已由用户关闭。"); return
    
    if content_lower == "打开标签目录":
        if not KNOWLEDGE_BASE: await message.reply("知识库尚未加载，请稍后再试。"); return
        categories = list(KNOWLEDGE_BASE.keys())
        response_text = "📚 **知识库标签目录** 📚\n\n" + "\n".join(f"{i+1}. {cat}" for i, cat in enumerate(categories)) + "\n\n请回复您想查阅的目录 **序号** 或 **完整名称**："
        await message.reply(response_text)
        user_states[author_id] = "awaiting_category_choice"
        return
    
    if content_lower == "取消":
        if user_states.get(author_id) == "awaiting_category_choice":
            del user_states[author_id]
            await message.reply("操作已取消。")
        return

    # --- 2. Continuous Chat & State Handling ---
    user_state = user_states.get(author_id)
    
    if user_state and user_state == "awaiting_category_choice":
        try:
            categories = list(KNOWLEDGE_BASE.keys())
            chosen_category = None
            try:
                choice_index = int(content_lower) - 1
                if 0 <= choice_index < len(categories): chosen_category = categories[choice_index]
            except ValueError:
                if content_lower in categories: chosen_category = content_lower
            
            if chosen_category:
                tags = KNOWLEDGE_BASE.get(chosen_category, [])
                if not tags: await message.reply(f"🤔 目录“{chosen_category}”下没有找到任何标签。")
                else:
                    response_parts = []; current_part = f"📜 **{chosen_category}** 目录下的标签：\n"
                    for tag in tags:
                        line = f"- {tag.get('translation', 'N/A')} (`{tag.get('term', 'N/A')}`)\n"
                        if len(current_part) + len(line) > 1900: response_parts.append(current_part); current_part = ""
                        current_part += line
                    response_parts.append(current_part)
                    for part in response_parts: await message.reply(part)
            else: await message.reply("无效的目录选项，请重新输入序号或完整的目录名称，或输入`取消`来退出。"); return
        finally:
            if author_id in user_states: del user_states[author_id]
        return

    # --- 3. New Conversation / Mention Handling ---
    is_mentioned = client_discord.user.mentioned_in(message) and not message.reference
    is_called_by_name = bot_name in content
    
    # Initialize a new chat session if mentioned and not already chatting
    if (is_mentioned or is_called_by_name) and not user_states.get(author_id, {}).get('state') == 'chatting':
        target_message = message
        if message.reference:
            try: target_message = await message.channel.fetch_message(message.reference.message_id)
            except (discord.NotFound, discord.HTTPException): pass

        # If it's a wake-up with an image, handle image comment and don't start a text chat session
        if target_message and target_message.attachments:
            attachment = target_message.attachments[0]
            if attachment.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')):
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(attachment.url, proxy=PROXY_URL) as resp:
                            if resp.status == 200:
                                image_data = await resp.read()
                                await comment_on_image_when_awakened(image_data, message.author.mention, message.channel)
                                return
                except Exception as e: await message.reply(f"❌ 评论图片时发生未知错误：{str(e)}")
                return
        
        # It's a text-based wake-up call, so initialize the chat state.
        user_states[author_id] = {'state': 'chatting', 'timestamp': time.time(), 'replies': 0}
        # The code will now fall through to the chat handling logic below.

    # --- 4. Active Chat Session Logic ---
    # Re-fetch state in case it was just created above
    user_state = user_states.get(author_id) 

    if user_state and user_state.get('state') == 'chatting':
        # Handle explicit exit keywords
        if content_lower in EXIT_KEYWORDS:
            if author_id in user_states: del user_states[author_id]
            await message.reply("好的，嗷呜~！本哈去玩飞盘了，有事再叫我！")
            return

        # Handle session timeout
        if time.time() - user_state.get('timestamp', 0) >= CHAT_SESSION_TIMEOUT:
            if author_id in user_states: del user_states[author_id]
            # Silently end the session, no need to notify
            return

        # This is the final (2nd) reply in the limited conversation
        if user_state.get('replies', 0) >= 1:
            try:
                history = [msg async for msg in message.channel.history(limit=CHAT_HISTORY_LIMIT)]; history.reverse()
                await generate_smart_response(message, history, is_awakened=True)
                await message.reply("主人不让我跟陌生人多说话，我先撤了，有需要再叫我")
            except Exception as e: 
                print(f"❌ 处理最终对话时出错: {e}")
            finally:
                if author_id in user_states: del user_states[author_id]
            return
        
        # This is the first reply (the wake-up message itself)
        else:
            try:
                history = [msg async for msg in message.channel.history(limit=CHAT_HISTORY_LIMIT)]; history.reverse()
                await generate_smart_response(message, history, is_awakened=True)
                if author_id in user_states: # Check if state still exists after async operation
                    user_states[author_id]['timestamp'] = time.time()
                    user_states[author_id]['replies'] += 1
            except Exception as e: 
                print(f"❌ 处理初次对话时出错: {e}")
                if author_id in user_states: del user_states[author_id] # Clean up on error
            return

    # --- 5. Fallback Behaviors ---
    if message.attachments:
        attachment = message.attachments[0]
        if attachment.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')):
            await message.channel.send(f"{message.author.mention} {random.choice(COMPLIMENTS)}")
            return

    if CHAT_ENABLED and not message.attachments and random.random() < CHAT_PROBABILITY:
        try:
            history = [msg async for msg in message.channel.history(limit=CHAT_HISTORY_LIMIT)]; history.reverse()
            await generate_smart_response(message, history, is_awakened=False)
        except Exception as e: print(f"❌ 获取聊天记录或回复时出错: {e}")
        return

# --- 启动机器人 ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise ValueError("未找到 DISCORD_TOKEN，请检查 .env 文件")

try:
    client_discord.run(DISCORD_TOKEN)
except discord.errors.LoginFailure:
    print("❌ Discord Token 无效，请检查 .env 文件中的 DISCORD_TOKEN 是否正确。")
except Exception as e:
    print(f"❌ 启动机器人时发生错误: {e}")
