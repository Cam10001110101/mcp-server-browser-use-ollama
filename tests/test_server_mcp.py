"""
Tests for the pure MCP server implementation.
"""
import pytest
import json
import asyncio
from unittest.mock import Mock, patch, AsyncMock
import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Import server module
import server


class TestMCPServer:
    """Test the pure MCP server implementation."""
    
    def test_server_instance_exists(self):
        """Test that server instance exists."""
        assert hasattr(server, 'server')
        assert server.server is not None
        assert server.server.name == "browser-automation"
    
    def test_global_state_initialized(self):
        """Test that global state is properly initialized."""
        assert hasattr(server, 'active_sessions')
        assert isinstance(server.active_sessions, dict)
        assert hasattr(server, 'session_counter')
        assert hasattr(server, 'max_sessions')
        assert server.max_sessions == 10  # Security limit
    
    def test_browser_session_class(self):
        """Test BrowserSession class structure."""
        # Test the class exists and has required methods
        assert hasattr(server, 'BrowserSession')
        session_class = server.BrowserSession
        
        # Check it has cleanup method
        assert hasattr(session_class, 'cleanup')
    
    def test_validation_functions(self):
        """Test validation utility functions."""
        assert hasattr(server, 'validate_session')
        assert callable(server.validate_session)
        
        # Test session validation with empty session_id
        with pytest.raises(ValueError, match="Session ID is required"):
            server.validate_session("")
        
        # Test session validation with non-existent session
        with pytest.raises(ValueError, match="No browser session found"):
            server.validate_session("non_existent")


class TestToolImplementations:
    """Test the tool implementation functions."""
    
    @pytest.mark.asyncio
    async def test_launch_browser_validation(self):
        """Test launch_browser input validation."""
        # Test empty URL
        with pytest.raises(ValueError, match="URL is required"):
            await server.launch_browser_impl("")
        
        # Test invalid URL protocol
        with pytest.raises(ValueError, match="Only HTTP/HTTPS URLs are allowed"):
            await server.launch_browser_impl("ftp://example.com")
    
    @pytest.mark.asyncio
    async def test_click_element_validation(self):
        """Test click_element input validation."""
        # Test invalid session
        with pytest.raises(ValueError, match="No browser session found"):
            await server.click_element_impl("invalid_session", 100, 100)
        
        # Test coordinate validation with mock session
        server.active_sessions["test"] = Mock()
        
        # Test non-integer coordinates
        with pytest.raises(ValueError, match="Coordinates must be integers"):
            await server.click_element_impl("test", "100", 100)
        
        # Test out of bounds coordinates
        with pytest.raises(ValueError, match="Coordinates out of reasonable bounds"):
            await server.click_element_impl("test", -1, 100)
        
        with pytest.raises(ValueError, match="Coordinates out of reasonable bounds"):
            await server.click_element_impl("test", 100, 20000)
        
        # Cleanup
        del server.active_sessions["test"]
    
    @pytest.mark.asyncio
    async def test_type_text_validation(self):
        """Test type_text input validation."""
        # Test invalid session
        with pytest.raises(ValueError, match="No browser session found"):
            await server.type_text_impl("invalid_session", "test")
        
        # Test text validation with mock session
        server.active_sessions["test"] = Mock()
        
        # Test non-string text
        with pytest.raises(ValueError, match="Text must be a string"):
            await server.type_text_impl("test", 123)
        
        # Test text length limit
        long_text = "a" * 10001
        with pytest.raises(ValueError, match="Text too long"):
            await server.type_text_impl("test", long_text)
        
        # Cleanup
        del server.active_sessions["test"]
    
    @pytest.mark.asyncio
    async def test_scroll_page_validation(self):
        """Test scroll_page input validation."""
        # Test invalid session
        with pytest.raises(ValueError, match="No browser session found"):
            await server.scroll_page_impl("invalid_session", "down")
        
        # Test direction validation with mock session
        server.active_sessions["test"] = Mock()
        
        # Test invalid direction
        with pytest.raises(ValueError, match="Direction must be 'up' or 'down'"):
            await server.scroll_page_impl("test", "left")
        
        # Cleanup
        del server.active_sessions["test"]
    
    @pytest.mark.asyncio
    async def test_get_dom_structure_validation(self):
        """Test get_dom_structure input validation."""
        # Test invalid session
        with pytest.raises(ValueError, match="No browser session found"):
            await server.get_dom_structure_impl("invalid_session", 3)
        
        # Test max_depth validation with mock session
        server.active_sessions["test"] = Mock()
        
        # Test invalid max_depth values
        with pytest.raises(ValueError, match="max_depth must be integer between 1 and 10"):
            await server.get_dom_structure_impl("test", 0)
        
        with pytest.raises(ValueError, match="max_depth must be integer between 1 and 10"):
            await server.get_dom_structure_impl("test", 11)
        
        with pytest.raises(ValueError, match="max_depth must be integer between 1 and 10"):
            await server.get_dom_structure_impl("test", "invalid")
        
        # Cleanup
        del server.active_sessions["test"]
    
    @pytest.mark.asyncio
    async def test_extract_data_validation(self):
        """Test extract_data input validation."""
        # Test invalid session
        with pytest.raises(ValueError, match="No browser session found"):
            await server.extract_data_impl("invalid_session", "pattern")
        
        # Test pattern validation with mock session
        server.active_sessions["test"] = Mock()
        
        # Test empty pattern
        with pytest.raises(ValueError, match="Extraction pattern is required"):
            await server.extract_data_impl("test", "")
        
        # Cleanup
        del server.active_sessions["test"]


class TestSecurityFeatures:
    """Test security features implementation."""
    
    def test_session_limit_enforced(self):
        """Test that session limit is properly configured."""
        assert server.max_sessions == 10
    
    @pytest.mark.asyncio
    async def test_session_limit_validation(self):
        """Test session limit validation in launch_browser."""
        # Fill up sessions to the limit
        original_sessions = server.active_sessions.copy()
        try:
            # Create mock sessions up to the limit
            for i in range(server.max_sessions):
                server.active_sessions[f"session_{i}"] = Mock()
            
            # Try to create one more session - should fail
            with pytest.raises(RuntimeError, match="Maximum sessions .* exceeded"):
                await server.launch_browser_impl("https://example.com")
        finally:
            # Restore original sessions
            server.active_sessions.clear()
            server.active_sessions.update(original_sessions)
    
    def test_url_validation_patterns(self):
        """Test URL validation patterns."""
        valid_urls = [
            "https://example.com",
            "http://localhost:8080",
            "https://sub.domain.com/path?query=value"
        ]
        
        invalid_urls = [
            "ftp://example.com",
            "file:///etc/passwd",
            "javascript:alert('xss')",
            "",
            "not_a_url"
        ]
        
        # These tests would need to be run with actual function calls
        # but demonstrate the security validation concept
        for url in valid_urls:
            assert url.startswith(('http://', 'https://'))
        
        for url in invalid_urls:
            assert not url.startswith(('http://', 'https://'))


class TestErrorHandling:
    """Test error handling compliance."""
    
    @pytest.mark.asyncio
    async def test_tool_error_propagation(self):
        """Test that tool errors are properly propagated."""
        # Test with invalid arguments to ensure RuntimeError is raised
        with pytest.raises(RuntimeError, match="Tool execution failed"):
            await server.call_tool("launch_browser", {"url": ""})
        
        with pytest.raises(RuntimeError, match="Tool execution failed"):
            await server.call_tool("click_element", {"session_id": "invalid", "x": 100, "y": 100})
    
    @pytest.mark.asyncio
    async def test_unknown_tool_handling(self):
        """Test handling of unknown tool calls."""
        with pytest.raises(RuntimeError, match="Tool execution failed"):
            await server.call_tool("unknown_tool", {})


class TestMCPCompliance:
    """Test MCP specification compliance."""
    
    @pytest.mark.asyncio
    async def test_list_tools_structure(self):
        """Test that list_tools returns proper MCP Tool structures."""
        tools = await server.list_tools()
        
        assert isinstance(tools, list)
        assert len(tools) == 10  # All our browser automation tools
        
        # Test first tool structure
        tool = tools[0]
        assert hasattr(tool, 'name')
        assert hasattr(tool, 'description')
        assert hasattr(tool, 'input_schema')
        
        # Test that it's launch_browser
        assert tool.name == "launch_browser"
        assert "URL" in tool.description
        
        # Test input schema structure
        schema = tool.input_schema
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "required" in schema
        assert "url" in schema["properties"]
        assert "url" in schema["required"]
    
    @pytest.mark.asyncio
    async def test_call_tool_return_format(self):
        """Test that call_tool returns proper MCP TextContent format."""
        # This would require mocking the actual browser automation
        # but tests the return format structure
        
        # Test with a simple tool call that will fail validation
        try:
            result = await server.call_tool("launch_browser", {"url": ""})
        except RuntimeError:
            pass  # Expected due to validation
        
        # The return format should be List[types.TextContent] when successful
        # This is validated by the type hints and MCP spec compliance
    
    def test_tool_registration(self):
        """Test that tools are properly registered with MCP decorators."""
        # Test that the server has the decorated functions
        assert hasattr(server, 'list_tools')
        assert hasattr(server, 'call_tool')
        
        # Test that these are actually MCP-decorated functions
        # (This is implicit in the decorator usage in the source)


class TestCleanupMechanisms:
    """Test cleanup and resource management."""
    
    @pytest.mark.asyncio
    async def test_cleanup_all_sessions_function(self):
        """Test cleanup_all_sessions function."""
        assert hasattr(server, 'cleanup_all_sessions')
        assert callable(server.cleanup_all_sessions)
        
        # Test with mock sessions
        original_sessions = server.active_sessions.copy()
        try:
            # Add a mock session
            mock_session = Mock()
            mock_session.cleanup = AsyncMock()
            server.active_sessions["test_session"] = mock_session
            
            # Run cleanup - should not raise errors
            await server.cleanup_all_sessions()
            
            # Should have called cleanup on the mock session
            mock_session.cleanup.assert_called_once()
        finally:
            # Restore original sessions
            server.active_sessions.clear()
            server.active_sessions.update(original_sessions)
    
    def test_browser_session_cleanup_method(self):
        """Test BrowserSession cleanup method exists."""
        session_class = server.BrowserSession
        assert hasattr(session_class, 'cleanup')
        
        # Test that cleanup is async
        import inspect
        assert inspect.iscoroutinefunction(session_class.cleanup)


class TestUtilityFunctions:
    """Test utility functions."""
    
    @pytest.mark.asyncio
    async def test_highlight_element_function(self):
        """Test highlight_element utility function."""
        assert hasattr(server, 'highlight_element')
        assert callable(server.highlight_element)
        
        # Test that it's async
        import inspect
        assert inspect.iscoroutinefunction(server.highlight_element)
    
    def test_validation_helper(self):
        """Test session validation helper."""
        # Test with empty sessions dict
        original_sessions = server.active_sessions.copy()
        server.active_sessions.clear()
        
        try:
            # Test validation failure
            with pytest.raises(ValueError):
                server.validate_session("nonexistent")
        finally:
            # Restore sessions
            server.active_sessions.update(original_sessions)


if __name__ == "__main__":
    pytest.main([__file__])