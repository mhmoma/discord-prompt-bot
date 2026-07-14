# Discord Prompt Bot（小哈）

Discord 全能机器人：图片反推提示词、创意生成、Danbooru 标签浏览/翻译，以及轻度群聊互动。

## 功能

- 图片反推与创意提示词生成（OpenAI 兼容 API）
- Danbooru 标签浏览、中英对照与词库增强
- 可选：随机闲聊、彩虹屁、护主/欢迎引导
- 支持 Docker / Railway / Render 等平台部署（含健康检查 Web 服务）

## 快速开始

```bash
git clone https://github.com/mhmoma/discord-prompt-bot.git
cd discord-prompt-bot
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env：填入 DISCORD_TOKEN、OPENAI_API_BASE、OPENAI_API_KEY、OPENAI_MODEL_NAME
python main.py
# 或：uvicorn app:app --host 0.0.0.0 --port 7860
```

### Docker

```bash
docker build -t discord-prompt-bot .
docker run --env-file .env -p 7860:7860 discord-prompt-bot
```

## 配置说明

必填环境变量见 [`.env.example`](.env.example)：

| 变量 | 说明 |
|------|------|
| `DISCORD_TOKEN` | Discord Bot Token |
| `OPENAI_API_BASE` | OpenAI 兼容 API 地址 |
| `OPENAI_API_KEY` | API Key |
| `OPENAI_MODEL_NAME` | 模型名 |

其余如代理、Danbooru、聊天概率等均为可选。

## 主要文件

| 路径 | 说明 |
|------|------|
| `bot.py` | 机器人主逻辑 |
| `danbooru_api.py` / `tag_*.py` | 标签与词库 |
| `app.py` | FastAPI 健康检查入口 |
| `chat_style_corpus.json` | 聊天人设语料 |

## 注意

- 不要将真实 `.env`、Token、频道/用户 ID 提交到仓库
- 大规模词库文件体积较大，克隆时请确保磁盘空间充足
