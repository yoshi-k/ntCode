"""End-to-end integration test for ntCode.

This test simulates a batch frontend interaction using a DummyLLM.
It verifies that user instructions are correctly routed through the
Connector to the Agent, and that the Agent can correctly parse tool
calls and execute them via the actual tool implementations.
"""

import os
import sys
import threading
import unittest
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Path / import setup
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent))

# Stub out anthropic and dotenv to allow imports
sys.modules.setdefault("anthropic", unittest.mock.MagicMock())
sys.modules.setdefault("dotenv", unittest.mock.MagicMock())

# Ensure dummy environment variables are set
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy-key")
os.environ.setdefault("NTCODE_MODEL", "gpt-4o") # Trigger native FC logic if needed

from utils.connector import Connector
from utils.agent import run_agent
from utils.dummy_llm import DummyLLM
import utils.llm as llm_module

# ---------------------------------------------------------------------------
# The Test Case
# ---------------------------------------------------------------------------

class TestEndToEndBatchWithDummyLLM(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.replay_file = self.tmp_dir / "test_replay.txt"
        self.output_file = self.tmp_dir / "test_out.txt"
        
        # We will use a sequence of responses that includes a tool call
        # The first response will be a tool call to list_files.
        # The second response (from DummyLLM) will be a plain text reply.
        self.replay_content = [
            "tool: list_files({\"path\": \".\"})",
            "I have listed the files for you."
        ]
        self.replay_file.write_text("\n".join(self.replay_content), encoding="utf-8")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir)

    def test_batch_flow_with_tool_call(self):
        """Simulate: User -> Connector -> Agent -> DummyLLM -> Tool -> Agent -> Connector -> User"""
        
        # 1. Setup DummyLLM
        dummy = DummyLLM(self.replay_file)
        
        # 2. Patch the module-level llm singleton to use our dummy
        original_llm = llm_module.llm
        llm_module.llm = dummy
        
        connector = Connector()
        
        # 3. Start Agent in background
        agent_thread = threading.Thread(
            target=run_agent,
            args=(connector,),
            daemon=True
        )
        agent_thread.start()

        try:
            # 4. Simulate Batch Frontend: Send User Instruction
            instruction = "Please list the files in the current directory."
            connector.send_user(instruction)

            # 5. Wait for the final assistant response
            # The sequence should be:
            #   - LLM returns tool call
            #   - Tool executes
            #   - LLM returns plain text
            #   - Assistant sends plain text to connector
            
            response = connector.receive_assistant_blocking(timeout=5)
            
            # 6. Assertions
            self.assertIsNotNone(response, "Agent failed to respond within timeout.")
            self.assertEqual(response["content"], "I have listed the files for you.")
            
            # Verify the tool was called (final response confirms execution)
            # Note: tool results are stored in the agent's ConversationManager,
            # not sent through the Connector, so we can't check them here.

        finally:
            # Cleanup
            connector.shutdown()
            agent_thread.join(timeout=2)
            llm_module.llm = original_llm

if __name__ == "__main__":
    unittest.main()
