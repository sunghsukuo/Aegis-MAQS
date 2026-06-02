import sys
from pathlib import Path
from urllib.parse import urlparse

# Add backend root to sys.path
backend_root = str(Path(__file__).resolve().parent.parent)
sys.path.append(backend_root)

import core.tools.web_search as search_tool

def print_section_banner(title):
    print("\n" + "=" * 70)
    print(f" 🌟 {title}")
    print("=" * 70)

def display_formatted_news(news_list):
    if not news_list:
        print("   ⚠️ 暫無符合篩選條件的專業新聞。")
        return
        
    for i, news in enumerate(news_list, 1):
        # Extract domain for display
        try:
            domain = urlparse(news['link']).hostname
        except Exception:
            domain = "未知來源"
            
        print(f"[{i}] 標題：{news['title']}")
        print(f"    來源網站：{domain}")
        print(f"    發布時間：{news['pub_date']}")
        print(f"    新聞連結：{news['link']}")
        
        # Check summary status
        summary = news.get('summary', '').strip()
        if summary:
            print(f"    內容精華摘要 (前 150 字)：{summary[:150]}...")
        else:
            print("    內容摘要狀態：（摘要與標題重複，已由去噪引擎自動去重合併，防範 Token 冗餘）")
        print("-" * 70)

if __name__ == "__main__":
    print("======================================================================")
    print(" 🚀 啟動「多維度新聞分析引擎（總經、板塊、個股）」端到端實時抓取測試")
    print("======================================================================")
    
    # 1. 總體經濟新聞測試
    print_section_banner("第一維度：總體經濟新聞 (Macroeconomic News)")
    print("正在抓取台灣總體經濟環境最新動向...")
    tw_macro = search_tool.get_macro_news("Taiwan", max_items=2)
    display_formatted_news(tw_macro)
    
    print("\n正在抓取美國總體經濟與聯準會風向...")
    us_macro = search_tool.get_macro_news("US", max_items=2)
    display_formatted_news(us_macro)
    
    # 2. 板塊/產業新聞測試
    print_section_banner("第二維度：板塊與產業趨勢新聞 (Sector & Industry Trends)")
    print("正在追蹤本週焦點強勢板塊「AI 半導體與伺服器供應鏈」動態...")
    sector_news = search_tool.search_news("AI 半導體 供應鏈", max_items=2)
    display_formatted_news(sector_news)
    
    # 3. 個股消息與催化劑測試
    print_section_banner("第三維度：個股重大消息與催化劑評估 (Stock-Specific Catalysts)")
    print("正在抓取台股龍頭標的「台積電 (2330.TW)」當週最新重大消息...")
    tsmc_news = search_tool.get_stock_news("2330.TW", max_items=2)
    display_formatted_news(tsmc_news)
    
    print("\n正在抓取美股 AI 巨頭「輝達 (NVDA)」最新核心催化劑事件...")
    nvda_news = search_tool.get_stock_news("NVDA", max_items=2)
    display_formatted_news(nvda_news)
    
    print("\n======================================================================")
    print(" 🎉 實時多維度新聞抓取與優化測試順利完成！")
    print("======================================================================")
