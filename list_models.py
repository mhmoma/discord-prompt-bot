import google.generativeai as genai
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 设置代理
proxy_url = "http://127.0.0.1:7890"
os.environ['HTTP_PROXY'] = proxy_url
os.environ['HTTPS_PROXY'] = proxy_url

# 配置 Gemini API 密钥
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("未找到 GEMINI_API_KEY，请检查 .env 文件")
genai.configure(api_key=GEMINI_API_KEY)

print("--- 正在查询可用的 Gemini 模型 ---")

try:
    # 遍历所有可用的模型
    for m in genai.list_models():
        # 检查模型是否支持 'generateContent' 方法
        if 'generateContent' in m.supported_generation_methods:
            print(f"模型名称: {m.name}")
            print(f"  - 支持的方法: {m.supported_generation_methods}\n")

except Exception as e:
    print(f"❌ 查询模型列表时出错: {e}")

print("--- 查询完毕 ---")
