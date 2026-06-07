import sys
import os
import argparse
import json
import difflib
from pathlib import Path

# Add backend to path to ensure core imports work correctly
sys.path.append(str(Path(__file__).resolve().parent.parent))

from core.agents.base_agent import BaseAgent
from core.agents.reflection_agent import ReflectionAgent
import core.db_manager as db

def color_diff_line(line: str) -> str:
    """Adds ANSI terminal colors to diff output lines for readability."""
    if line.startswith('+') and not line.startswith('+++'):
        return f"\033[92m{line}\033[0m"  # Green for additions
    elif line.startswith('-') and not line.startswith('---'):
        return f"\033[91m{line}\033[0m"  # Red for deletions
    elif line.startswith('@@'):
        return f"\033[96m{line}\033[0m"  # Cyan for range information
    return line

def main():
    parser = argparse.ArgumentParser(description="Aegis-MAQS 投資反思與 Prompt 演化功能診斷測試工具 (無副作用)")
    parser.add_argument("--date", "-d", type=str, default="2026-05-30", help="指定推薦週日期 (格式: YYYY-MM-DD)")
    parser.add_argument("--mock-roi", action="store_true", help="若指定日期之個股尚未結算 ROI，是否進行隨機模擬 (Mock)")
    parser.add_argument("--output", "-o", type=str, default=None, help="將結果寫入指定文字檔案")
    parser.add_argument("--model", "-m", type=str, default="gemini-2.5-pro", help="指定 Meta-Agent 使用的模型 (預設: gemini-2.5-pro)")
    args = parser.parse_args()
    
    print("==================================================")
    print(f"🔍 啟動 Aegis-MAQS 反思演化測試：指定日期週 {args.date}")
    print("==================================================")
    
    # 直接調用生產環境中的 ReflectionAgent 演化核心函數，使用 dry_run=True 避免污染資料庫
    result = ReflectionAgent.evolve_prompts_core(
        report_date=args.date,
        mock_if_empty=args.mock_roi,
        dry_run=True,
        model_name=args.model
    )
    
    if not result:
        print("[✗] 反思演化跳過或失敗。原因可能是該日期沒有足夠的交易紀錄 (少於 2 筆)，或者生成的 Prompt 因格式/長度校驗未通過而被過濾。")
        return
        
    curr_prompt = result["old_prompt"]
    new_prompt = result["new_prompt"]
    old_version = result["old_version"]
    new_version = result["new_version"]
    success_cases = result["success_cases"]
    failure_cases = result["failure_cases"]
    logs_count = result["logs_count"]
    
    print(f"[✓] 成功取得 {logs_count} 筆個股推論與 ROI 記錄：")
    for case in success_cases:
        print(f"  - {case['ticker']} | ROI: {case['roi']} (成功案例)")
    for case in failure_cases:
        print(f"  - {case['ticker']} | ROI: {case['roi']} (失敗案例)")
        
    print(f"[✓] 成功取得前週使用的 System Prompt 基準（版本：{old_version}），長度：{len(curr_prompt)} 字元")
    print(f"[✓] 成功生成且驗證通過新版 System Prompt！長度：{len(new_prompt)} 字元")
    
    # Compute text diff using difflib
    diff_lines = list(difflib.unified_diff(
        curr_prompt.splitlines(),
        new_prompt.splitlines(),
        fromfile=f"FundamentalAgent_old_{old_version}",
        tofile=f"FundamentalAgent_new_{new_version}",
        lineterm=""
    ))
    
    diff_content = "\n".join(diff_lines)
    
    # Request Gemini semantic evaluation of changes
    print("[*] 正在調度評估助理進行前後 System Prompt 語意對比與優化成效分析...")
    analysis_agent = BaseAgent(
        name="PromptDifferenceAnalyzer",
        role="Senior Prompt & Strategy Evaluator",
        system_instruction="你是一位資深的金融 Prompt 評估專家。請評估、比較並總結前後兩個 System Prompt 的差異，著重於新提示詞中新增了哪些風控紅線、交易紀律或規則優化，並以繁體中文提供精煉的總結報告。"
    )
    
    analysis_prompt = f"""
請對比並分析以下兩個 System Prompt 的實質差異與改進：

【舊版 System Prompt】：
{curr_prompt}

【新版 System Prompt】：
{new_prompt}

請整理出一份條理分明的繁體中文評估報告，包含：
1. 新版 Prompt 新增或收緊了哪些財務/基本面指標與交易紀律？
2. 是否有加強對回撤與風險控制的防禦？
3. 整體 Prompt 的演化品質評估。
"""
    analysis_report = analysis_agent.run(analysis_prompt)
    
    # Format final report outputs
    output_buffer = []
    output_buffer.append("==================================================")
    output_buffer.append(f"📊 Aegis-MAQS 反思演化測試報告 (指定日期週: {args.date})")
    output_buffer.append("==================================================")
    output_buffer.append(f"1. 測試背景：對比前週使用 Prompt 與本週演化 Prompt。此測試為純唯讀，無寫回資料庫。")
    output_buffer.append(f"2. 參與對比學習的交易個股共 {logs_count} 檔。")
    output_buffer.append("\n[3. System Prompt Unified Diff 文本差異對比]")
    output_buffer.append("-" * 50)
    
    terminal_diff = "\n".join([color_diff_line(line) for line in diff_lines])
    plain_diff = "\n".join(diff_lines)
    
    output_buffer.append(plain_diff)
    output_buffer.append("-" * 50)
    output_buffer.append("\n[4. Prompt 語意優化成效分析報告]")
    output_buffer.append("-" * 50)
    output_buffer.append(analysis_report)
    output_buffer.append("-" * 50)
    
    final_plain_report = "\n".join(output_buffer)
    
    # Print colored diff to the terminal
    print("\n" + "=" * 50)
    print("📊 終端機即時輸出測試報告：")
    print("=" * 50)
    print(f"1. 測試背景：對比前週使用 Prompt 與本週演化 Prompt。此測試為純唯讀，無寫回資料庫。")
    print(f"2. 參與對比學習的交易個股共 {logs_count} 檔。")
    print("\n[3. System Prompt Unified Diff 文本差異對比]")
    print("-" * 50)
    print(terminal_diff)
    print("-" * 50)
    print("\n[4. Prompt 語意優化成效分析報告]")
    print("-" * 50)
    print(analysis_report)
    print("-" * 50)
    
    # Save to file if output is specified
    if args.output:
        try:
            out_path = Path(args.output).resolve()
            out_path.write_text(final_plain_report, encoding="utf-8")
            print(f"\n[✓] 測試報告已成功儲存至檔案：{out_path}")
        except Exception as e:
            print(f"\n[✗] 寫入檔案失敗: {e}")

    # 自動將舊版與新版 system prompt 輸出到個別檔案存檔
    try:
        old_prompt_path = (Path(__file__).resolve().parent / f"old_prompt_{args.date}.txt").resolve()
        new_prompt_path = (Path(__file__).resolve().parent / f"new_prompt_{args.date}.txt").resolve()
        
        old_prompt_path.write_text(curr_prompt, encoding="utf-8")
        new_prompt_path.write_text(new_prompt, encoding="utf-8")
        
        print(f"\n[✓] 舊版 System Prompt 已存檔至：{old_prompt_path}")
        print(f"[✓] 新版 System Prompt 已存檔至：{new_prompt_path}")
    except Exception as e:
        print(f"\n[✗] 儲存提示詞檔案時發生錯誤: {e}")
            
if __name__ == "__main__":
    main()
