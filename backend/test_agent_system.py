import sys
import os
from pathlib import Path

# Add parent directory to path to ensure absolute imports work
sys.path.append(str(Path(__file__).resolve().parent))

# Import config, tools
from core.config import GEMINI_API_KEY, REGIONS
import core.tools.yahoo_finance as yf_tool
import core.tools.web_search as search_tool

# Colors
def print_green(msg): print(f"\033[92m[✓] {msg}\033[0m")
def print_blue(msg): print(f"\033[94m[*] {msg}\033[0m")
def print_yellow(msg): print(f"\033[93m[!] {msg}\033[0m")
def print_red(msg): print(f"\033[91m[✗] {msg}\033[0m")

def test_yahoo_finance():
    print_blue("--- 測試 Yahoo Finance 數據源 ---")
    try:
        # Test benchmark performance
        us_bench = yf_tool.get_benchmark_performance("US")
        print_green(f"美股大盤指數讀取成功：{us_bench['name']} | 指數：{us_bench['current_price']:.2f} | 週回報：{us_bench['weekly_return']*100:.2f}%")
        
        tw_bench = yf_tool.get_benchmark_performance("Taiwan")
        print_green(f"台股大盤指數讀取成功：{tw_bench['name']} | 指數：{tw_bench['current_price']:.2f} | 週回報：{tw_bench['weekly_return']*100:.2f}%")
        
        # Test sector ranking
        us_rankings = yf_tool.get_sector_rankings("US")
        if us_rankings:
            print_green(f"美股板塊強度排行讀取成功！最強勢板塊：{us_rankings[0]['label']} ({us_rankings[0]['weekly_return']*100:.2f}%)")
        else:
            print_red("美股板塊強度排行讀取失敗！")
            
        # Test stock financials
        test_ticker = "NVDA"
        financials = yf_tool.get_stock_financials(test_ticker)
        if financials and financials.get("current_price"):
            print_green(f"個股基本面資料獲取成功！{financials['company_name']} ({test_ticker}) | 現價: {financials['current_price']:.2f} | P/E: {financials.get('pe_ratio')}")
        else:
            print_red(f"個股基本面資料獲取失敗：{test_ticker}")
            
        return True
    except Exception as e:
        print_red(f"Yahoo Finance 數據源測試發生例外錯誤: {e}")
        return False

def test_web_search():
    print_blue("--- 測試 RSS 新聞搜尋工具 ---")
    try:
        # Test macro news
        tw_news = search_tool.get_macro_news("Taiwan", max_items=2)
        if tw_news:
            print_green(f"台股總經新聞讀取成功！首條新聞：{tw_news[0]['title']}")
        else:
            print_yellow("台股總經新聞為空，請確認網路連線是否正常。")
            
        # Test stock news
        nvda_news = search_tool.get_stock_news("NVDA", max_items=2)
        if nvda_news:
            print_green(f"個股新聞催化劑讀取成功！首條新聞：{nvda_news[0]['title']}")
        else:
            print_yellow("個股新聞讀取為空。")
            
        return True
    except Exception as e:
        print_red(f"RSS 新聞工具測試發生例外錯誤: {e}")
        return False

def test_gemini_api():
    print_blue("--- 測試 Gemini API 與代理人核心 ---")
    if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
        print_yellow("未偵測到 GEMINI_API_KEY。請先在 backend/.env 檔案中設定您的 Gemini API 金鑰。")
        print_yellow("跳過 Gemini 代理人 API 連線測試。")
        return False
        
    try:
        from core.agents.base_agent import BaseAgent
        from core.config import DEFAULT_GEMINI_MODEL
        print_blue(f"正在發送測試 Prompts 給 {DEFAULT_GEMINI_MODEL} 模型...")
        agent = BaseAgent(name="TestAgent", role="Tester", system_instruction="你是一個測試助手，請只回覆 'Hello World'")
        response = agent.run("哈囉，請進行連線測試")
        
        if "Agent encountered error" in response:
            print_red(f"Gemini API 呼叫失敗！錯誤資訊：{response}")
            try:
                from google import genai
                client = genai.Client(api_key=GEMINI_API_KEY)
                print_blue("🔍 正在嘗試列出您的 API 金鑰支援的所有可用模型 (Available Models)...")
                models = client.models.list()
                for m in list(models)[:15]:
                    print(f"  - {m.name}")
            except Exception as list_err:
                print_red(f"❌ 嘗試列出模型時失敗，可能您的 API 金鑰無效或被限制：{list_err}")
            return False
            
        if "Hello World" in response or response:
            print_green(f"Gemini API 連線成功！回應內容：{response.strip()}")
            return True
        else:
            print_red(f"Gemini API 響應異常，收到內容：{response}")
            return False
    except Exception as e:
        print_red(f"Gemini API 連線發生嚴重錯誤: {e}")
        try:
            from google import genai
            client = genai.Client(api_key=GEMINI_API_KEY)
            print_blue("🔍 嘗試列出您的 API 金鑰所支援的所有可用模型 (Available Models)...")
            models = client.models.list()
            for m in list(models)[:15]:  # Limit to top 15 to avoid clutter
                print(f"  - {m.name}")
        except Exception as list_err:
            print_red(f"❌ 嘗試列出模型時失敗，可能您的 API 金鑰無效或被限制：{list_err}")
        return False

def main():
    print("==================================================")
    print("🔍 啟動「投資研究代理人系統」核心功能診斷測試")
    print("==================================================")
    
    yf_ok = test_yahoo_finance()
    search_ok = test_web_search()
    gemini_ok = test_gemini_api()
    
    print("==================================================")
    print("📊 診斷測試結果報告 (Diagnostic Report):")
    print(f"1. Yahoo Finance 數據引擎：{'[ OK ]' if yf_ok else '[ ERROR ]'}")
    print(f"2. RSS 新聞擷取引擎：{'[ OK ]' if search_ok else '[ WARNING/ERROR ]'}")
    print(f"3. Gemini 大模型代理人連結：{'[ OK ]' if gemini_ok else '[ PENDING/ERROR ]'}")
    print("==================================================")
    if yf_ok and search_ok:
        if gemini_ok:
            print_green("🎉 所有核心模組測試全數通過！您可以執行 pipenv run python aegis_cli.py 生成完整投資週報了！")
        else:
            print_yellow("💡 數據源功能正常，只要在 backend/.env 中填入 GEMINI_API_KEY，即可啟用完整多代理人研究報告！")
    else:
        print_red("⚠️ 有部分核心數據組件測試失敗，請檢查您的網際網路連線。")

if __name__ == "__main__":
    main()
