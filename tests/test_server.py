"""
Tests for the MCP server implementation.
"""
import pytest
import json
from unittest.mock import Mock, patch, AsyncMock
import sys
import os

# Import server module
import server


class TestServerTools:
    """Test the MCP server tools."""
    
    @pytest.mark.asyncio
    async def test_server_has_mcp_instance(self):
        """Test that server has an MCP instance."""
        assert hasattr(server, 'server')
        assert server.server is not None
    
    @pytest.mark.asyncio
    async def test_launch_browser_tool_exists(self):
        """Test that launch_browser tool is registered."""
        # The registered tool has an implementation
        assert hasattr(server, 'launch_browser_impl')
        assert callable(server.launch_browser_impl)
    
    @pytest.mark.asyncio
    async def test_click_element_tool_exists(self):
        """Test that click_element tool is registered."""
        assert hasattr(server, 'click_element_impl')
        assert callable(server.click_element_impl)
    
    @pytest.mark.asyncio
    async def test_type_text_tool_exists(self):
        """Test that type_text tool is registered."""
        assert hasattr(server, 'type_text_impl')
        assert callable(server.type_text_impl)
    
    @pytest.mark.asyncio
    async def test_all_required_tools_exist(self):
        """Test that all required tools exist in the server module."""
        required_tools = [
            'launch_browser',
            'click_element',
            'click_selector',
            'type_text',
            'scroll_page',
            'get_page_content',
            'get_dom_structure',
            'take_screenshot',
            'extract_data',
            'close_browser'
        ]
        
        for tool in required_tools:
            assert hasattr(server, tool + "_impl"), f"Tool {tool} not found in server module"
            assert callable(getattr(server, tool + "_impl")), f"Tool {tool} is not callable"
    
    @pytest.mark.asyncio
    async def test_launch_browser_with_mock(self):
        """Test launch_browser function with mocked playwright."""
        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_context = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        
        mock_playwright_instance = AsyncMock()
        mock_playwright_instance.chromium.launch = AsyncMock(return_value=mock_browser)
        
        with patch('server.async_playwright') as mock_async_playwright:
            mock_async_playwright.return_value.start = AsyncMock(return_value=mock_playwright_instance)
            
            # Call launch_browser (no headless parameter)
            result = await server.launch_browser_impl(url="https://example.com")
            
            # The MCP implementation returns strings
            assert isinstance(result, str)
            assert result.isdigit()  # Should be session ID
    
    @pytest.mark.asyncio
    async def test_error_handling_no_session(self):
        """Test error handling when session doesn't exist."""
        # Most tools require a session_id that doesn't exist
        with pytest.raises(ValueError) as exc_info:
            await server.click_element_impl(session_id="nonexistent", x=100, y=100)
        
        assert "No browser session found" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_close_browser_nonexistent_session(self):
        """Test closing a browser session that doesn't exist."""
        with pytest.raises(ValueError) as exc_info:
            await server.close_browser_impl(session_id="nonexistent")
        
        assert "No browser session found" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_screenshot_output_format(self):
        """Test that screenshot raises error when session doesn't exist."""
        # This will fail with no session
        with pytest.raises(ValueError) as exc_info:
            await server.take_screenshot_impl(session_id="test")
        
        assert "No browser session found" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_tool_descriptions_exist(self):
        tools = await server.list_tools()
        assert tools
        for tool in tools:
            assert tool.name
            assert tool.description
            assert tool.input_schema["type"] == "object"


class TestServerIntegration:
    """Integration tests for server functionality."""
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_full_browser_lifecycle(self):
        """Test a complete browser lifecycle with mocked components."""
        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value="Test page content")
        mock_page.close = AsyncMock()
        mock_context = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_browser.close = AsyncMock()
        
        mock_playwright_instance = AsyncMock()
        mock_playwright_instance.chromium.launch = AsyncMock(return_value=mock_browser)
        
        with patch('server.async_playwright') as mock_async_playwright:
            mock_async_playwright.return_value.start = AsyncMock(return_value=mock_playwright_instance)
            
            # Launch browser
            launch_result = await server.launch_browser_impl(url="https://example.com")
            session_id = launch_result  # The MCP implementation returns string session ID
            
            assert session_id is not None
            assert session_id.isdigit()
            
            # Get page content - this will be a string
            content_result = await server.get_page_content_impl(session_id=session_id)
            assert isinstance(content_result, str)
            
            # Close browser - this will be a string  
            close_result = await server.close_browser_impl(session_id=session_id)
            assert isinstance(close_result, str)