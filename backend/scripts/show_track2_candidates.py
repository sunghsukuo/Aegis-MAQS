import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

# Add backend directory to path
backend_root = Path(__file__).resolve().parent.parent
sys.path.append(str(backend_root))

def show_candidates(report_date, region):
    cache_file = backend_root / "core" / "data" / "cache" / f"pipeline_state_{report_date}.json"
    if not cache_file.exists():
        print(f"[✗] 找不到指定日期 {report_date} 的管線快取狀態檔案。")
        print(f"    請確認當日週報已執行完成，或快取檔案存在：{cache_file}")
        return
        
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception as e:
        print(f"[✗] 載入快取檔案失敗: {e}")
        return
        
    analysis = state.get("analysis", {})
    if region not in analysis:
        available_regions = list(analysis.keys())
        print(f"[✗] 區域 {region} 不在快取資料中。可用的區域為：{available_regions}")
        return
        
    candidates = analysis[region].get("track2_candidates", [])
    if not candidates:
        print(f"[!] 區域 {region} 在 {report_date} 沒有符合篩選標準的軌道二候選股。")
        return
        
    print(f"\n==================================================================")
    print(f"📊 {report_date} [{region}] 軌道二（財務加速 Alpha）所有合格候選股名單")
    print(f"   總計有 {len(candidates)} 檔個股通過過濾（PEG <= 1.5 且 站上 50 日均線）")
    print(f"==================================================================\n")
    
    # Print markdown table header
    print(f"| 排名 | 代號 | 公司名稱 | 平均增長率 | PE | PEG | 現價 | 50日均線 |")
    print(f"|---|---|---|---|---|---|---|---|")
    
    for idx, c in enumerate(candidates, 1):
        pe_ratio = c.get("pe_ratio")
        peg_ratio = c.get("peg_ratio")
        avg_growth = c.get("avg_growth", 0.0)
        current_price = c.get("current_price")
        fifty_day_sma = c.get("fifty_day_sma")
        
        pe_str = f"{pe_ratio:.1f}" if pe_ratio is not None else "N/A"
        peg_str = f"{peg_ratio:.2f}" if peg_ratio is not None else "轉機股"
        growth_str = f"{avg_growth*100:.2f}%"
        curr_price_str = f"{current_price:.2f}" if current_price is not None else "N/A"
        sma_50_str = f"{fifty_day_sma:.2f}" if fifty_day_sma is not None else "N/A"
        
        print(f"| {idx} | {c['ticker']} | {c['name']} | {growth_str} | {pe_str} | {peg_str} | {curr_price_str} | {sma_50_str} |")

def main():
    parser = argparse.ArgumentParser(description="查詢指定日期選股管線中軌道二財務加速的所有合格候選股結果")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"), help="週報執行日期 (YYYY-MM-DD)")
    parser.add_argument("--region", default="Taiwan", choices=["Taiwan", "US"], help="區域 (Taiwan 或 US)")
    args = parser.parse_args()
    
    show_candidates(args.date, args.region)

if __name__ == "__main__":
    main()
