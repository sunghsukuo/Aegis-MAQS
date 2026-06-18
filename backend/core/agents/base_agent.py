from google import genai
from google.genai import types
import time
import hashlib
import sys
from datetime import datetime
from core.config import GEMINI_API_KEY, DEFAULT_MODEL, TEMPERATURE, CACHE_DIR
import core.config as config
from core.tools.utils import get_cached_data, save_to_cache

class BaseAgent:
    def __init__(self, name: str, role: str, system_instruction: str, model_name: str = None, thinking_mode: str = None, register_db: bool = True):
        """Initializes the base agent with a name, role, system instructions, and target model."""
        self.name = name
        self.role = role
        self.model_name = model_name if model_name is not None else config.DEFAULT_MODEL
        self.prompt_version = "v1.0.0"
        
        # Proactively load the system prompt from prompt_registry defensively if enabled
        if register_db:
            try:
                import core.db_manager as db
                active_prompt = db.get_active_prompt(self.name)
                if active_prompt:
                    self.system_instruction = active_prompt["system_prompt"]
                    self.prompt_version = active_prompt["version"]
                    print(f"[✓] [{self.name}] 成功自資料庫載入系統指令，版本：{self.prompt_version}")
                else:
                    self.system_instruction = system_instruction
                    try:
                        db.save_prompt_registry(self.name, system_instruction, "v1.0.0", is_active=1)
                        print(f"[✓] [{self.name}] 首發系統指令已自動註冊至資料庫，版本：v1.0.0")
                    except Exception:
                        pass
            except Exception as e:
                self.system_instruction = system_instruction
        else:
            self.system_instruction = system_instruction
            
        self.is_deepseek = (
            self.model_name.lower().startswith("deepseek") or 
            (config.LLM_PROVIDER == "deepseek" and not self.model_name.lower().startswith("gemini"))
        )
        
        if self.is_deepseek:
            from core.config import DEEPSEEK_API_KEY, DEEPSEEK_API_BASE
            if not DEEPSEEK_API_KEY:
                raise ValueError("DEEPSEEK_API_KEY is not set in the environment or .env file!")
            self.deepseek_key = DEEPSEEK_API_KEY
            self.deepseek_base = DEEPSEEK_API_BASE
            self.thinking_mode = thinking_mode if thinking_mode is not None else config.DEEPSEEK_THINKING
        else:
            # Configure Gemini Client using the new unified google-genai SDK
            if not GEMINI_API_KEY:
                raise ValueError("GEMINI_API_KEY is not set in the environment or .env file!")
                
            self.client = genai.Client(api_key=GEMINI_API_KEY)
            
            # Setup modern GenerateContentConfig including system_instruction
            self.config = types.GenerateContentConfig(
                system_instruction=self.system_instruction,
                temperature=TEMPERATURE,
                top_p=0.95,
                top_k=40,
                max_output_tokens=8192
            )

    def run(self, prompt: str, retries: int = 5, delay: int = 15, bypass_cache: bool = False) -> str:
        """Sends a prompt to the model and returns the response, with rate-limit retry logic and caching."""
        self.last_prompt = prompt
        
        # Check if we are in backtest mode and get simulated date dynamically
        sim_date = None
        try:
            from backtest.replayer import get_simulated_date
            sim_date = get_simulated_date()
        except Exception:
            pass

        system_instruction_to_use = self.system_instruction
        if sim_date:
            temporal_instruction = f"""
[🚨 TIME-TRAVEL BACKTESTING CONSTRAINT - CRITICAL]
The current simulated date is {sim_date}. You are writing a report and making decisions on {sim_date}.
You MUST NOT mention any events, technologies, policies, or market themes that occurred after {sim_date}.
- If the simulated date {sim_date} is before late 2022: Generative AI (ChatGPT, AI servers, etc.) does NOT exist yet. You must absolutely NOT mention AI, AI demand, AI servers, or related terms in your report or decision making.
- Global central banks (Fed, etc.) are in whatever state they were in at {sim_date}. Do not reference future pivots, rate-cut cycles, or rate-hike cycles that occurred after {sim_date}.
- Avoid lookahead bias. Do not assume or hint at future market recoveries, recessions, or events. Analyze the situation as if you are living on {sim_date} and have no memory of the future.
"""
            system_instruction_to_use = self.system_instruction + "\n" + temporal_instruction
            
        # Calculate cache key using system_instruction_to_use
        cache_key = None
        try:
            hash_input = f"{self.name}_{system_instruction_to_use}_{prompt}".encode("utf-8")
            cache_key = f"agent_cache_{hashlib.md5(hash_input).hexdigest()}"
        except Exception as hash_ex:
            print(f"[!] Warning: Failed to generate cache key for agent {self.name}: {hash_ex}")

        # Check cache if not bypassed
        bypass_cache_flag = bypass_cache or ("--force" in sys.argv) or getattr(self, "bypass_cache", False)
        if not bypass_cache_flag and cache_key:
            try:
                cached_data = get_cached_data(CACHE_DIR, cache_key, ttl_hours=24)
                if cached_data and "response_text" in cached_data:
                    print(f"[✓] [Cache Hit] 成功載入 {self.name} 的大模型快取回應。")
                    return cached_data["response_text"]
            except Exception as cache_ex:
                print(f"[!] Warning: Failed to retrieve cache for agent {self.name}: {cache_ex}")

        for attempt in range(retries):
            try:
                if self.is_deepseek:
                    import requests
                    url = f"{self.deepseek_base.rstrip('/')}/chat/completions"
                    headers = {
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.deepseek_key}"
                    }
                    payload = {
                        "model": self.model_name,
                        "messages": [
                            {"role": "system", "content": system_instruction_to_use},
                            {"role": "user", "content": prompt}
                        ],
                        "max_tokens": 8192
                    }
                    if self.thinking_mode == "enabled":
                        payload["thinking"] = {"type": "enabled"}
                    else:
                        payload["thinking"] = {"type": "disabled"}
                        payload["temperature"] = TEMPERATURE
                    response = requests.post(url, headers=headers, json=payload, timeout=90)
                    response.raise_for_status()
                    res_data = response.json()
                    if res_data and "choices" in res_data and len(res_data["choices"]) > 0:
                        text = res_data["choices"][0]["message"]["content"]
                        print(f"[✓] [{self.name}] (DeepSeek) 成功生成內容！字元數: {len(text)}")
                        
                        # Save response to cache
                        if cache_key:
                            try:
                                cache_payload = {
                                    "agent_name": self.name,
                                    "system_instruction": system_instruction_to_use,
                                    "prompt": prompt,
                                    "response_text": text,
                                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                }
                                save_to_cache(CACHE_DIR, cache_key, cache_payload)
                            except Exception as cache_save_ex:
                                print(f"[!] Warning: Failed to save cache for agent {self.name}: {cache_save_ex}")
                                
                        return text
                    return "Agent failed to generate response."
                else:
                    # Create a copy of the config with updated system_instruction
                    config_to_use = types.GenerateContentConfig(
                        system_instruction=system_instruction_to_use,
                        temperature=self.config.temperature,
                        top_p=self.config.top_p,
                        top_k=self.config.top_k,
                        max_output_tokens=self.config.max_output_tokens
                    )
                    response = self.client.models.generate_content(
                        model=self.model_name,
                        contents=prompt,
                        config=config_to_use
                    )
                    if response and response.text:
                        text = response.text
                        print(f"[✓] [{self.name}] 成功生成內容！字元數: {len(text)}")
                        
                        # Save response to cache
                        if cache_key:
                            try:
                                cache_payload = {
                                    "agent_name": self.name,
                                    "system_instruction": system_instruction_to_use,
                                    "prompt": prompt,
                                    "response_text": text,
                                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                }
                                save_to_cache(CACHE_DIR, cache_key, cache_payload)
                            except Exception as cache_save_ex:
                                print(f"[!] Warning: Failed to save cache for agent {self.name}: {cache_save_ex}")
                                
                        return text
                    return "Agent failed to generate response."
            except Exception as e:
                print(f"[{self.name}] Error on attempt {attempt + 1}: {e}")
                if attempt < retries - 1:
                    time.sleep(delay * (attempt + 1))  # Exponential backoff
                else:
                    raise e

