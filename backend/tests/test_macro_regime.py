import sys
from pathlib import Path

# Add parent directory to path to ensure absolute imports work
sys.path.append(str(Path(__file__).resolve().parent.parent))

from core.pipelines.research_pipeline import analyze_macro_regime

def main():
    print("🚀 啟動自適應總經分析 (dry_run) 測試...")
    
    # We will test for both Taiwan and US regions
    for region in ["Taiwan", "US"]:
        print(f"\n==================================================")
        print(f"🌍 正在執行區域分析：{region}")
        print(f"==================================================")
        try:
            # Call analyze_macro_regime with dry_run=True to prevent database logging
            macro_report, macro_regime = analyze_macro_regime(region, dry_run=True)
            
            print(f"\n[✓] 成功取得大模型判定結果！")
            print(f"👉 偵測到的 Macro Regime (總經情境)：\033[92m{macro_regime}\033[0m")
            print(f"📄 總體經濟報告內容摘要 (前 250 字)：")
            print("-" * 50)
            print(macro_report[:250] + "\n...")
            print("-" * 50)
        except Exception as e:
            print(f"❌ 分析區域 {region} 失敗：{e}")

if __name__ == "__main__":
    main()
