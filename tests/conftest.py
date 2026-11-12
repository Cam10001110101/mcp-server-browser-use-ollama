"""
Pytest configuration and shared fixtures for all tests.
"""
import pytest
import asyncio
import os
import sys
from pathlib import Path

# Add src directory to Python path
src_path = str(Path(__file__).parent.parent / "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)


@pytest.fixture(autouse=True)
async def isolated_browser_sessions(monkeypatch):
    import server

    monkeypatch.setattr(server, "active_sessions", {})
    monkeypatch.setattr(server, "pending_launches", 0)
    monkeypatch.setattr(server, "session_counter", 0)
    yield
    await server.cleanup_all_sessions()


@pytest.fixture
def mock_server_path(tmp_path):
    """Create a mock server script for testing."""
    mock_script = tmp_path / "mock_server.py"
    mock_script.write_text("""
import sys
print("Mock MCP server running")
sys.exit(0)
""")
    return str(mock_script)


@pytest.fixture
def sample_task_file(tmp_path):
    """Create a sample task file for testing."""
    task_file = tmp_path / "sample_task.md"
    task_file.write_text("""
# Sample Task

Navigate to example.com and take a screenshot.
""")
    return str(task_file)


@pytest.fixture
def mock_ollama_model():
    """Set up a mock Ollama model for testing."""
    original_model = os.environ.get("OLLAMA_MODEL")
    os.environ["OLLAMA_MODEL"] = "test-model"
    yield "test-model"
    if original_model:
        os.environ["OLLAMA_MODEL"] = original_model
    else:
        os.environ.pop("OLLAMA_MODEL", None)


@pytest.fixture
def mock_playwright_browser():
    """Mock Playwright browser for testing without actual browser launch."""
    class MockPage:
        async def goto(self, url):
            pass
        
        async def screenshot(self, **kwargs):
            return b"mock_screenshot_data"
        
        async def close(self):
            pass
    
    class MockBrowser:
        async def new_page(self):
            return MockPage()
        
        async def close(self):
            pass
    
    class MockPlaywright:
        class chromium:
            @staticmethod
            async def launch(**kwargs):
                return MockBrowser()
    
    return MockPlaywright()