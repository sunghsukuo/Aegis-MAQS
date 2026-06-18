import unittest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path

# Add backend directory to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from core.agents.base_agent import BaseAgent
import core.config as config

class TestDeepSeekAgent(unittest.TestCase):
    def setUp(self):
        # 確保測試時不命中本地快取
        self.cached_patcher = patch('core.agents.base_agent.get_cached_data', return_value=None)
        self.mock_get_cached = self.cached_patcher.start()
        
    def tearDown(self):
        self.cached_patcher.stop()
        
    @patch('core.agents.base_agent.genai.Client')
    @patch('core.config.GEMINI_API_KEY', 'mock_gemini_key')
    @patch('core.config.DEEPSEEK_API_KEY', 'mock_deepseek_key')
    @patch('core.config.LLM_PROVIDER', 'gemini')
    def test_agent_routing_gemini(self, mock_gemini_client):
        # Should initialize Gemini client
        agent = BaseAgent(name="TestGemini", role="Tester", system_instruction="System instruction", model_name="gemini-2.5-flash", register_db=False)
        self.assertFalse(agent.is_deepseek)
        self.assertTrue(hasattr(agent, 'client'))

    @patch('core.config.DEEPSEEK_API_KEY', 'mock_deepseek_key')
    @patch('core.config.LLM_PROVIDER', 'gemini')
    @patch('core.config.DEEPSEEK_THINKING', 'disabled')
    def test_agent_routing_deepseek_init(self):
        # 1. Standard initialization with deepseek model name
        agent = BaseAgent(name="TestDeepSeek", role="Tester", system_instruction="System instruction", model_name="deepseek-v4-flash", register_db=False)
        self.assertTrue(agent.is_deepseek)
        self.assertEqual(agent.deepseek_key, 'mock_deepseek_key')
        self.assertFalse(hasattr(agent, 'client'))
        self.assertEqual(agent.thinking_mode, 'disabled')

        # 2. Overwrite thinking mode
        agent_enabled = BaseAgent(name="TestDeepSeek", role="Tester", system_instruction="System instruction", model_name="deepseek-v4-flash", thinking_mode="enabled", register_db=False)
        self.assertEqual(agent_enabled.thinking_mode, 'enabled')

    @patch('core.config.DEEPSEEK_API_KEY', 'mock_deepseek_key')
    @patch('core.config.LLM_PROVIDER', 'deepseek')
    @patch('core.config.DEFAULT_MODEL', 'deepseek-v4-flash')
    def test_agent_routing_provider_deepseek(self):
        # Under deepseek provider, default model should route to DeepSeek
        agent = BaseAgent(name="TestDeepSeekProvider", role="Tester", system_instruction="System instruction", register_db=False)
        self.assertTrue(agent.is_deepseek)
        self.assertEqual(agent.model_name, 'deepseek-v4-flash')

    @patch('core.config.DEEPSEEK_API_KEY', 'mock_deepseek_key')
    @patch('requests.post')
    def test_agent_run_deepseek_thinking_disabled(self, mock_post):
        # Mock successful DeepSeek response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "Hello from DeepSeek (non-thinking)"
                    }
                }
            ]
        }
        mock_post.return_value = mock_response

        agent = BaseAgent(name="TestDeepSeekRun", role="Tester", system_instruction="System instruction", model_name="deepseek-v4-flash", thinking_mode="disabled", register_db=False)
        result = agent.run("Hello test")
        
        self.assertEqual(result, "Hello from DeepSeek (non-thinking)")
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        payload = kwargs['json']
        
        # Verify disabled thinking configuration
        self.assertEqual(payload['model'], 'deepseek-v4-flash')
        self.assertEqual(payload['thinking'], {"type": "disabled"})
        self.assertIn('temperature', payload)
        self.assertEqual(payload['temperature'], 0.2)

    @patch('core.config.DEEPSEEK_API_KEY', 'mock_deepseek_key')
    @patch('requests.post')
    def test_agent_run_deepseek_thinking_enabled(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "Hello from DeepSeek (thinking)"
                    }
                }
            ]
        }
        mock_post.return_value = mock_response

        agent = BaseAgent(name="TestDeepSeekRun", role="Tester", system_instruction="System instruction", model_name="deepseek-v4-flash", thinking_mode="enabled", register_db=False)
        result = agent.run("Hello test")
        
        self.assertEqual(result, "Hello from DeepSeek (thinking)")
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        payload = kwargs['json']
        
        # Verify enabled thinking configuration
        self.assertEqual(payload['model'], 'deepseek-v4-flash')
        self.assertEqual(payload['thinking'], {"type": "enabled"})
        # Temperature must be omitted to prevent API strict errors
        self.assertNotIn('temperature', payload)

if __name__ == "__main__":
    unittest.main()
