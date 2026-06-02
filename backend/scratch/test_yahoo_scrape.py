import requests
from bs4 import BeautifulSoup

# Direct Yahoo Finance link from the NVDA news feed
url = "https://finance.yahoo.com/news/nvidia-stock-slides-ai-data-121500473.html"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

try:
    print(f"Scraping direct Yahoo Finance article: {url}...")
    response = requests.get(url, headers=headers, timeout=10)
    print(f"Status Code: {response.status_code}")
    
    soup = BeautifulSoup(response.content, "html.parser")
    
    # Clean standard elements
    for element in soup(["script", "style", "nav", "footer", "iframe", "header", "aside"]):
        element.decompose()
        
    paragraphs = soup.find_all("p")
    print(f"Total paragraphs found: {len(paragraphs)}")
    
    text_content = []
    for p in paragraphs[:8]:
        text = p.get_text().strip()
        if len(text) > 20:
            text_content.append(text)
            
    print("\nScraped Content Highlights:")
    print("\n\n".join(text_content)[:600])
except Exception as e:
    print(f"Error: {e}")
