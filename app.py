from fastapi import FastAPI
import asyncio
import os
import bot

app = FastAPI()

@app.on_event("startup")
async def startup_event():
    DISCORD_TOKEN = bot.os.getenv("DISCORD_TOKEN")
    if not DISCORD_TOKEN:
        raise ValueError("未找到 DISCORD_TOKEN，请检查环境变量")
    
    print("🚀 正在尝试在后台启动 Discord 机器人...")
    asyncio.create_task(bot.client_discord.start(DISCORD_TOKEN))

@app.get("/")
def read_root():
    return {"status": "running", "message": "Discord bot is running in the background."}

@app.get("/health")
def health():
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "7860"))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
