import sys
from pathlib import Path

# Add backend to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import core.db_manager as db

def main():
    baseline_path = Path(__file__).resolve().parent.parent / "core" / "prompts" / "fundamental_agent_baseline.txt"
    if not baseline_path.exists():
        print(f"[✗] 找不到基準提示詞檔案：{baseline_path}")
        return
        
    prompt_content = baseline_path.read_text(encoding="utf-8").strip()
    
    # Get active version to bump version number
    active_prompt = db.get_active_prompt("FundamentalAgent")
    if active_prompt:
        curr_version = active_prompt["version"]
        try:
            # e.g., v1.0.1 -> major=1, minor=0, patch=1
            major, minor, patch = map(int, curr_version.replace("v", "").split("."))
            new_version = f"v{major}.{minor}.{patch + 1}"
        except Exception:
            new_version = "v1.1.0"
        print(f"[*] 偵測到目前資料庫中活躍版本：{curr_version}，即將升級至最新版本：{new_version}")
    else:
        new_version = "v1.0.0"
        print(f"[*] 未偵測到活躍版本，即將初始化版本為：{new_version}")
        
    # Write to database prompt_registry
    db.save_prompt_registry("FundamentalAgent", prompt_content, new_version, is_active=1)
    print(f"[✓] 成功將最新的 {baseline_path.name} 寫入資料庫，新版本號：{new_version}，且已設為活躍狀態。")

if __name__ == "__main__":
    main()
