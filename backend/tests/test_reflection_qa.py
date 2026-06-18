import sys
import os
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

# Add backend to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import core.db_manager as db
from core.agents.reflection_agent import ReflectionAgent
from backtest.prompt_qa import temp_sandbox_context, run_prompt_qa_verification

class TestReflectionQAIntegration(unittest.TestCase):
    def setUp(self):
        self.agent_name = "FundamentalAgent"
        from core.agents.base_agent import BaseAgent
        BaseAgent.last_prompt = "mock_last_prompt"
        
    @patch("backtest.prompt_qa.run_prompt_qa_verification")
    @patch("core.db_manager.get_extreme_inference_logs_with_roi")
    @patch("core.db_manager.get_active_prompt")
    @patch("core.db_manager.save_prompt_registry")
    @patch("core.agents.base_agent.BaseAgent.run")
    def test_evolve_prompts_qa_passed(self, mock_agent_run, mock_save, mock_get_active, mock_get_logs, mock_qa_verify):
        """測試當 QA 驗證通過時，成功更新 Prompt"""
        # Mocking
        mock_get_logs.return_value = [
            {"ticker": "2330.TW", "roi": 0.1, "input_prompt": "x", "output_response": "投資評級: BUY\n目標價: 600\n停損點: 500", "prompt_version": "v1.0.0"},
            {"ticker": "2454.TW", "roi": -0.05, "input_prompt": "y", "output_response": "投資評級: BUY\n目標價: 1000\n停損點: 900", "prompt_version": "v1.0.0"}
        ]
        mock_get_active.return_value = {
            "system_prompt": "舊的 Prompt，包含投資評級與核心論點、推薦買入區間、中線目標價、防禦停損點、建議持倉權重",
            "version": "v1.0.0"
        }
        # 模擬 Meta-Agent 生成一個有效的新 Prompt
        mock_agent_run.return_value = "新一代優化 Prompt，包含投資評級與核心論點、推薦買入區間、中線目標價、防禦停損點、建議持倉權重"
        
        # 模擬 QA 通過
        mock_qa_verify.return_value = True
        
        # 執行演化 (dry_run=False)
        result = ReflectionAgent.evolve_prompts_core(dry_run=False)
        
        # 驗證
        self.assertIsNotNone(result)
        mock_qa_verify.assert_called_once()
        mock_save.assert_called()
        
        # 檢查是否有寫入 FundamentalAgent
        called_agents = [call.args[0] for call in mock_save.call_args_list]
        self.assertIn("FundamentalAgent", called_agents)
        
    @patch("backtest.prompt_qa.run_prompt_qa_verification")
    @patch("core.db_manager.get_extreme_inference_logs_with_roi")
    @patch("core.db_manager.get_active_prompt")
    @patch("core.db_manager.save_prompt_registry")
    @patch("core.agents.base_agent.BaseAgent.run")
    def test_evolve_prompts_qa_failed(self, mock_agent_run, mock_save, mock_get_active, mock_get_logs, mock_qa_verify):
        """測試當 QA 驗證失敗時，拒絕更新 Prompt，不寫入 registry"""
        # Mocking
        mock_get_logs.return_value = [
            {"ticker": "2330.TW", "roi": 0.1, "input_prompt": "x", "output_response": "投資評級: BUY\n目標價: 600\n停損點: 500", "prompt_version": "v1.0.0"},
            {"ticker": "2454.TW", "roi": -0.05, "input_prompt": "y", "output_response": "投資評級: BUY\n目標價: 1000\n停損點: 900", "prompt_version": "v1.0.0"}
        ]
        mock_get_active.return_value = {
            "system_prompt": "舊的 Prompt，包含投資評級與核心論點、推薦買入區間、中線目標價、防禦停損點、建議持倉權重",
            "version": "v1.0.0"
        }
        mock_agent_run.return_value = "新一代優化 Prompt，包含投資評級與核心論點、推薦買入區間、中線目標價、防禦停損點、建議持倉權重"
        
        # 模擬 QA 未通過
        mock_qa_verify.return_value = False
        
        # 執行演化 (dry_run=False)
        result = ReflectionAgent.evolve_prompts_core(dry_run=False)
        
        # 驗證
        self.assertIsNone(result)
        mock_qa_verify.assert_called_once()
        
        # 驗證沒有儲存 FundamentalAgent 的新 Prompt
        called_agents = [call.args[0] for call in mock_save.call_args_list]
        self.assertNotIn("FundamentalAgent", called_agents)

if __name__ == "__main__":
    unittest.main()
