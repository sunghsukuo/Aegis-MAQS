import sys
from pathlib import Path

# Add backend root to sys.path
backend_root = str(Path(__file__).resolve().parent.parent)
sys.path.append(backend_root)

import core.tools.web_search as search_tool

def test_fetch_and_scrape():
    print("Fetching actual NVDA news using get_stock_news...")
    news = search_tool.get_stock_news("NVDA", max_items=3)
    
    for i, art in enumerate(news, 1):
        print(f"\n[{i}] {art['title']}")
        print(f"    URL: {art['link']}")
        print(f"    Raw summary length: {len(art['summary'])}")
        
        # Test scraping the URL
        url = art['link']
        if "google.com" in url:
            print("    Skipping Google News link (needs decoding).")
            continue
            
        print(f"    Scraping direct URL: {url}...")
        scraped_text = search_tool.scrape_article_content(url)
        print(f"    Scraped text length: {len(scraped_text)}")
        if scraped_text:
            print(f"    Snippet: {scraped_text[:200]}...")

if __name__ == "__main__":
    test_fetch_and_scrape()
