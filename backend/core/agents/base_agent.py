from google import genai
from google.genai import types
import time
from core.config import GEMINI_API_KEY, DEFAULT_GEMINI_MODEL, TEMPERATURE

class BaseAgent:
    def __init__(self, name: str, role: str, system_instruction: str, model_name: str = DEFAULT_GEMINI_MODEL):
        """Initializes the base agent with a name, role, system instructions, and target Gemini model."""
        self.name = name
        self.role = role
        self.model_name = model_name
        self.prompt_version = "v1.0.0"
        
        # Proactively load the system prompt from prompt_registry defensively
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

    def run(self, prompt: str, retries: int = 5, delay: int = 15) -> str:
        """Sends a prompt to the Gemini model and returns the response, with rate-limit retry logic."""
        self.last_prompt = prompt
        for attempt in range(retries):
            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=self.config
                )
                if response and response.text:
                    print(f"[✓] [{self.name}] 成功生成內容！字元數: {len(response.text)}")
                    return response.text
                return "Agent failed to generate response."
            except Exception as e:
                print(f"[{self.name}] Error on attempt {attempt + 1}: {e}")
                if attempt < retries - 1:
                    time.sleep(delay * (attempt + 1))  # Exponential backoff
                else:
                    raise e
