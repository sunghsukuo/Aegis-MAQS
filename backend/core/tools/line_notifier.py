import sys
import os
from pathlib import Path
import requests

# Add backend and core paths for independent script testing
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

# Import LINE credentials from config
from core.config import LINE_CHANNEL_ACCESS_TOKEN, LINE_USER_ID

class LineNotifier:
    """
    LINE Messaging API Notifier for the Investment Analyst Agent.
    Provides robust, non-blocking single-push message delivery.
    """
    def __init__(self):
        self.token = LINE_CHANNEL_ACCESS_TOKEN
        self.user_id = LINE_USER_ID
        self.api_url = "https://api.line.me/v2/bot/message/push"
        
        # Defensive check: warning if credentials are missing
        if not self.token or not self.user_id:
            print("[!] Warning: LINE Messaging API credentials are not configured in your environment variables.")

    def send_message(self, text: str) -> bool:
        """
        Sends a single text push message to the configured LINE User ID.
        Wrapped in defensive exceptions so any connection failures DO NOT crash the calling agent pipeline.
        """
        # Mute all LINE notifications during backtesting to prevent spamming
        if os.environ.get("AEGIS_IN_BACKTEST") == "1":
            print("[🛡️ 回測沙盒] 偵測到回測模式，自動攔截並靜音 LINE 通知。")
            return True

        if not self.token or not self.user_id:
            print("[✗] LINE Notifier: Skipping message send due to missing credentials.")
            return False
            
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}"
        }
        
        payload = {
            "to": self.user_id,
            "messages": [
                {
                    "type": "text",
                    "text": text
                }
            ]
        }
        
        try:
            # 10-second timeout to prevent blocking agent pipelines on network congestion
            response = requests.post(self.api_url, headers=headers, json=payload, timeout=10)
            
            if response.status_code == 200:
                print("[✓] LINE Notifier: Message sent successfully!")
                return True
            else:
                print(f"[✗] LINE Notifier Fail: API responded with status {response.status_code}. Response: {response.text}")
                return False
                
        except requests.exceptions.Timeout:
            print("[✗] LINE Notifier Fail: Network request timed out (10s limit). Message skipped defensively.")
            return False
        except Exception as e:
            print(f"[✗] LINE Notifier Fail: Encountered unexpected exception: {e}. Message skipped defensively.")
            return False

if __name__ == "__main__":
    print("[*] Testing LINE Messaging API Notifier...")
    notifier = LineNotifier()
    
    from datetime import datetime
    test_msg = (
        "🛡️ 【投資研究代理人·實作測試】\n"
        "恭喜！您的 LINE Messaging API 串接測試成功！🎉\n\n"
        "當前系統時間：" + datetime.now().strftime("%Y-%m-%d %H:%M") + "\n"
        "此管道未來將用於推送：\n"
        "1. 每日盤後實時物理停損 / 停利平倉警報\n"
        "2. 每週美股 / 台股策略週報深度分析卡片\n\n"
        "系統已就緒，實戰沙盒觀測中。📈"
    )
    
    success = notifier.send_message(test_msg)
    if success:
        print("[✓] Test message dispatched! Please check your LINE App.")
    else:
        print("[✗] Test dispatch failed. Please verify your token, user ID, or network connectivity.")
