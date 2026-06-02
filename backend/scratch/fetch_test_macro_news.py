import sys
from pathlib import Path

# Add the backend root directory to sys.path to resolve imports correctly
backend_root = str(Path(__file__).resolve().parent.parent)
sys.path.append(backend_root)

import core.tools.web_search as search_tool

def print_banner(title):
    print("=" * 60)
    print(f" 📍 {title}")
    print("=" * 60)

def display_news_list(news_list):
    if not news_list:
        print("   ⚠️ 暫無符合篩選條件的專業新聞。")
        return
        
    for i, news in enumerate(news_list, 1):
        print(f"{i}. 標題：{news['title']}")
        print(f"   來源網址：{news['link']}")
        print(f"   發布時間：{news['pub_date']}")
        if news.get('summary') and news['summary'].strip():
            print(f"   內容摘要：{news['summary'][:150]}...")
        else:
            print("   內容摘要：（摘要與標題重複，已自動去噪合併）")
        print("-" * 60)

if __name__ == "__main__":
    print_banner("測試：台股總體經濟新聞 (已啟用深度去噪與白名單)")
    tw_news = search_tool.get_macro_news("Taiwan", max_items=4)
    display_news_list(tw_news)
    
    print("\n")
    
    print_banner("測試：美股總體經濟新聞 (已啟用深度去噪與白名單)")
    us_news = search_tool.get_macro_news("US", max_items=4)
    display_news_list(us_news)
