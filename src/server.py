#!/usr/bin/env python3
"""
MCP Server for Browser Automation
Official MCP SDK implementation targeting the 2026-07-28 specification.
"""

import sys
import json
import logging
import asyncio
from typing import Dict, Any, Optional, List
from urllib.parse import urlsplit

import anyio

from mcp.server import CacheHint, Server
from mcp.server.stdio import stdio_server
from mcp.server.lowlevel.server import InitializationOptions
from mcp import types
from playwright.async_api import async_playwright, Page, Browser, BrowserContext, Playwright

# Configure logging for MCP compliance
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger("mcp-browser-server")

class BrowserSession:
    """Represents a browser automation session"""
    
    def __init__(self, session_id: str, playwright: Playwright, browser: Browser, 
                 context: BrowserContext, page: Page):
        self.session_id = session_id
        self.playwright = playwright
        self.browser = browser
        self.context = context
        self.page = page
        self.created_at = asyncio.get_event_loop().time()
        self.element_counter = 0
        
    async def cleanup(self):
        """Clean up browser resources"""
        await cleanup_browser_resources(
            self.page, self.context, self.browser, self.playwright
        )


async def cleanup_browser_resources(page, context, browser, playwright):
    """Attempt every close, including after partial startup or cancellation."""
    # MCP cancels requests using AnyIO cancel scopes. Cleanup must survive those.
    with anyio.CancelScope(shield=True):
        for resource, method in (
            (page, "close"), (context, "close"),
            (browser, "close"), (playwright, "stop"),
        ):
            if resource is None:
                continue
            try:
                with anyio.fail_after(5):
                    await getattr(resource, method)()
            except Exception:
                logger.warning("Browser resource cleanup failed: %s", method)

# Global state for browser sessions
active_sessions: Dict[str, BrowserSession] = {}
session_counter = 0
max_sessions = 10  # Security: limit concurrent sessions
pending_launches = 0

async def highlight_element(page: Page, x: int, y: int, number: int, color: str = 'red'):
    """Add visual highlight at coordinates"""
    js_args = {'x': x - 15, 'y': y - 15, 'number': number, 'color': color}
    await page.evaluate('''
        args => {
            const box = document.createElement('div');
            box.style.position = 'absolute';
            box.style.left = args.x + 'px';
            box.style.top = args.y + 'px';
            box.style.width = '30px';
            box.style.height = '30px';
            box.style.backgroundColor = args.color;
            box.style.opacity = '0.5';
            box.style.border = '2px solid ' + args.color;
            box.style.borderRadius = '5px';
            box.style.display = 'flex';
            box.style.alignItems = 'center';
            box.style.justifyContent = 'center';
            box.style.color = 'white';
            box.style.fontWeight = 'bold';
            box.style.zIndex = '10000';
            box.textContent = args.number;
            document.body.appendChild(box);
            return box;
        }
    ''', js_args)

def validate_session(session_id: str) -> BrowserSession:
    """Validate session exists and return it"""
    if not session_id:
        raise ValueError("Session ID is required")
    
    session = active_sessions.get(session_id)
    if not session:
        raise ValueError(f"No browser session found with ID: {session_id}")
    
    return session

def tool_definitions() -> List[types.Tool]:
    """List available browser automation tools"""
    return [
        types.Tool(
            name="launch_browser",
            description="Launch a new browser session and navigate to URL",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to navigate to"
                    }
                },
                "required": ["url"]
            }
        ),
        types.Tool(
            name="click_element",
            description="Click at specific coordinates in the browser",
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Browser session ID"
                    },
                    "x": {
                        "type": "integer",
                        "description": "X coordinate to click"
                    },
                    "y": {
                        "type": "integer", 
                        "description": "Y coordinate to click"
                    }
                },
                "required": ["session_id", "x", "y"]
            }
        ),
        types.Tool(
            name="click_selector",
            description="Click an element by CSS selector",
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Browser session ID"
                    },
                    "selector": {
                        "type": "string",
                        "description": "CSS selector to identify element"
                    }
                },
                "required": ["session_id", "selector"]
            }
        ),
        types.Tool(
            name="type_text",
            description="Type text into the currently focused element",
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Browser session ID"
                    },
                    "text": {
                        "type": "string",
                        "description": "Text to type"
                    }
                },
                "required": ["session_id", "text"]
            }
        ),
        types.Tool(
            name="scroll_page",
            description="Scroll the page up or down",
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Browser session ID"
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["up", "down"],
                        "description": "Scroll direction",
                        "default": "down"
                    }
                },
                "required": ["session_id"]
            }
        ),
        types.Tool(
            name="get_page_content",
            description="Get text content of the current page",
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Browser session ID"
                    }
                },
                "required": ["session_id"]
            }
        ),
        types.Tool(
            name="get_dom_structure",
            description="Get simplified DOM structure of the page",
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Browser session ID"
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Maximum DOM tree depth",
                        "default": 3,
                        "minimum": 1,
                        "maximum": 10
                    }
                },
                "required": ["session_id"]
            }
        ),
        types.Tool(
            name="take_screenshot",
            description="Take a screenshot of the current page",
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Browser session ID"
                    }
                },
                "required": ["session_id"]
            }
        ),
        types.Tool(
            name="extract_data",
            description="Extract structured data from the page",
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Browser session ID"
                    },
                    "pattern": {
                        "type": "string",
                        "description": "Data extraction pattern (e.g. 'product prices')"
                    }
                },
                "required": ["session_id", "pattern"]
            }
        ),
        types.Tool(
            name="close_browser",
            description="Close a browser session",
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Browser session ID to close"
                    }
                },
                "required": ["session_id"]
            }
        )
    ]

async def list_tools() -> List[types.Tool]:
    return tool_definitions()


async def call_tool(name: str, arguments: dict) -> List[types.TextContent]:
    """Handle tool calls with proper MCP compliance"""
    global session_counter
    
    try:
        if name == "launch_browser":
            result = await launch_browser_impl(arguments.get("url"))
        elif name == "click_element":
            result = await click_element_impl(
                arguments.get("session_id"),
                arguments.get("x"),
                arguments.get("y")
            )
        elif name == "click_selector":
            result = await click_selector_impl(
                arguments.get("session_id"),
                arguments.get("selector")
            )
        elif name == "type_text":
            result = await type_text_impl(
                arguments.get("session_id"),
                arguments.get("text")
            )
        elif name == "scroll_page":
            result = await scroll_page_impl(
                arguments.get("session_id"),
                arguments.get("direction", "down")
            )
        elif name == "get_page_content":
            result = await get_page_content_impl(arguments.get("session_id"))
        elif name == "get_dom_structure":
            result = await get_dom_structure_impl(
                arguments.get("session_id"),
                arguments.get("max_depth", 3)
            )
        elif name == "take_screenshot":
            result = await take_screenshot_impl(arguments.get("session_id"))
        elif name == "extract_data":
            result = await extract_data_impl(
                arguments.get("session_id"),
                arguments.get("pattern")
            )
        elif name == "close_browser":
            result = await close_browser_impl(arguments.get("session_id"))
        else:
            raise ValueError(f"Unknown tool: {name}")
            
        return [types.TextContent(type="text", text=result)]
        
    except Exception as e:
        logger.error(f"Tool {name} failed: {e}")
        raise RuntimeError(f"Tool execution failed: {str(e)}")

# Tool implementations
async def launch_browser_impl(url: str) -> str:
    """Launch browser session with security controls"""
    global session_counter, pending_launches
    
    if not url:
        raise ValueError("URL is required")
    
    # Security: limit concurrent sessions
    if len(active_sessions) + pending_launches >= max_sessions:
        raise RuntimeError(f"Maximum sessions ({max_sessions}) exceeded")
    
    # Security: validate URL format
    if not isinstance(url, str) or not url.startswith(('http://', 'https://')):
        raise ValueError("Only HTTP/HTTPS URLs are allowed")
    parsed_url = urlsplit(url)
    if not parsed_url.hostname:
        raise ValueError("URL must include a hostname")
    
    session_id = str(session_counter)
    session_counter += 1
    # Reserve a slot before the first await so in-flight launches count too.
    pending_launches += 1
    playwright = browser = context = page = None
    registered = False
    
    try:
        # Playwright cannot stop a driver until start() has returned its handle.
        # Defer request cancellation across acquisition, then honor it before
        # launching a browser. Raw asyncio cancellation must also keep ownership.
        with anyio.CancelScope(shield=True):
            startup = asyncio.create_task(async_playwright().start())
            try:
                playwright = await asyncio.shield(startup)
            except asyncio.CancelledError:
                playwright = await startup
                raise
        await anyio.lowlevel.checkpoint()
        browser = await playwright.chromium.launch(
            headless=False,
            chromium_sandbox=True,
            args=['--disable-dev-shm-usage', '--start-maximized']
        )
        context = await browser.new_context(
            no_viewport=True  # Use full browser window instead of fixed viewport
        )
        page = await context.new_page()
        
        # Set viewport to full screen dimensions (common full HD resolution)
        # This prevents scrollbars and improves AI automation efficiency
        await page.set_viewport_size({"width": 1920, "height": 1080})
        
        await page.goto(url)
        
        session = BrowserSession(session_id, playwright, browser, context, page)
        active_sessions[session_id] = session
        registered = True
        
        logger.info("Browser session %s launched", session_id)
        return session_id
        
    except Exception as e:
        logger.error(f"Failed to launch browser: {e}")
        raise RuntimeError(f"Browser launch failed: {str(e)}")
    finally:
        try:
            if not registered:
                await cleanup_browser_resources(page, context, browser, playwright)
        finally:
            pending_launches -= 1

async def click_element_impl(session_id: str, x: int, y: int) -> str:
    """Click at coordinates with validation"""
    session = validate_session(session_id)
    
    if not isinstance(x, int) or not isinstance(y, int):
        raise ValueError("Coordinates must be integers")
    
    if x < 0 or y < 0 or x > 10000 or y > 10000:
        raise ValueError("Coordinates out of reasonable bounds")
    
    try:
        session.element_counter += 1
        await highlight_element(session.page, x, y, session.element_counter)
        await session.page.mouse.click(x, y)
        
        logger.info(f"Clicked at ({x}, {y}) in session {session_id}")
        return f"Clicked at coordinates ({x}, {y})"
        
    except Exception as e:
        logger.error(f"Click failed: {e}")
        raise RuntimeError(f"Click operation failed: {str(e)}")

async def click_selector_impl(session_id: str, selector: str) -> str:
    """Click element by CSS selector"""
    session = validate_session(session_id)
    
    if not selector:
        raise ValueError("CSS selector is required")
    
    try:
        element = await session.page.wait_for_selector(selector, timeout=5000)
        if not element:
            raise RuntimeError(f"Element with selector '{selector}' not found")
        
        # Get position for highlighting
        bounding_box = await element.bounding_box()
        if bounding_box:
            x = bounding_box['x'] + bounding_box['width'] / 2
            y = bounding_box['y'] + bounding_box['height'] / 2
            session.element_counter += 1
            await highlight_element(session.page, x, y, session.element_counter)
        
        await element.click()
        logger.info(f"Clicked element '{selector}' in session {session_id}")
        return f"Clicked element with selector: {selector}"
        
    except Exception as e:
        logger.error(f"Selector click failed: {e}")
        raise RuntimeError(f"Failed to click element: {str(e)}")

async def type_text_impl(session_id: str, text: str) -> str:
    """Type text with security validation"""
    session = validate_session(session_id)
    
    if not isinstance(text, str):
        raise ValueError("Text must be a string")
    
    # Security: limit text length
    if len(text) > 10000:
        raise ValueError("Text too long (max 10000 characters)")
    
    try:
        await session.page.keyboard.type(text)
        logger.info(f"Typed {len(text)} characters in session {session_id}")
        return f"Typed text: {text[:50]}{'...' if len(text) > 50 else ''}"
        
    except Exception as e:
        logger.error(f"Text typing failed: {e}")
        raise RuntimeError(f"Failed to type text: {str(e)}")

async def scroll_page_impl(session_id: str, direction: str) -> str:
    """Scroll page with direction validation"""
    session = validate_session(session_id)
    
    if direction not in ["up", "down"]:
        raise ValueError("Direction must be 'up' or 'down'")
    
    try:
        if direction == "down":
            await session.page.evaluate('window.scrollBy(0, window.innerHeight)')
        else:
            await session.page.evaluate('window.scrollBy(0, -window.innerHeight)')
        
        logger.info(f"Scrolled {direction} in session {session_id}")
        return f"Scrolled {direction}"
        
    except Exception as e:
        logger.error(f"Scroll failed: {e}")
        raise RuntimeError(f"Scroll operation failed: {str(e)}")

async def get_page_content_impl(session_id: str) -> str:
    """Extract page text content with size limits"""
    session = validate_session(session_id)
    
    try:
        content = await session.page.evaluate('() => document.body.innerText')
        
        # Security: limit content size
        if len(content) > 50000:
            content = content[:50000] + "\n... (content truncated for size)"
        
        logger.info(f"Extracted {len(content)} characters from session {session_id}")
        return content
        
    except Exception as e:
        logger.error(f"Content extraction failed: {e}")
        raise RuntimeError(f"Failed to get page content: {str(e)}")

async def get_dom_structure_impl(session_id: str, max_depth: int) -> str:
    """Get DOM structure with depth limits"""
    session = validate_session(session_id)
    
    if not isinstance(max_depth, int) or max_depth < 1 or max_depth > 10:
        raise ValueError("max_depth must be integer between 1 and 10")
    
    try:
        dom_structure = await session.page.evaluate(f'''
            () => {{
                function extractDomNode(node, depth = 0, maxDepth = {max_depth}) {{
                    if (depth > maxDepth) return "...";
                    
                    if (node.nodeType === 8 || 
                        (node.tagName && node.tagName.toLowerCase() === 'script')) {{
                        return null;
                    }}
                    
                    if (node.nodeType === 3) {{
                        const text = node.textContent.trim();
                        return text ? text.substring(0, 50) + (text.length > 50 ? "..." : "") : null;
                    }}
                    
                    if (node.nodeType === 1) {{
                        const result = {{
                            tag: node.tagName.toLowerCase(),
                            id: node.id || undefined,
                            classes: node.className ? Array.from(node.classList) : undefined,
                        }};
                        
                        if (node.hasAttribute('href')) result.href = node.getAttribute('href');
                        if (node.hasAttribute('src')) result.src = node.getAttribute('src');
                        if (node.hasAttribute('alt')) result.alt = node.getAttribute('alt');
                        if (node.hasAttribute('title')) result.title = node.getAttribute('title');
                        
                        if (depth < maxDepth) {{
                            const children = [];
                            for (const child of node.childNodes) {{
                                const childResult = extractDomNode(child, depth + 1, maxDepth);
                                if (childResult) children.push(childResult);
                            }}
                            if (children.length > 0) result.children = children;
                        }} else if (node.childNodes.length > 0) {{
                            result.children = "...";
                        }}
                        
                        return result;
                    }}
                    
                    return null;
                }}
                
                return extractDomNode(document.documentElement);
            }}
        ''')
        
        result = json.dumps(dom_structure, indent=2)
        logger.info(f"Extracted DOM structure from session {session_id}")
        return result
        
    except Exception as e:
        logger.error(f"DOM extraction failed: {e}")
        raise RuntimeError(f"Failed to get DOM structure: {str(e)}")

async def take_screenshot_impl(session_id: str) -> str:
    """Take screenshot with secure file handling"""
    session = validate_session(session_id)
    
    try:
        # Keep potentially sensitive page contents off disk, even on failure.
        screenshot = await session.page.screenshot()
        file_size = len(screenshot)
        
        logger.info(f"Screenshot taken for session {session_id} ({file_size} bytes)")
        return f"Screenshot captured ({file_size} bytes). Processed in memory."
        
    except Exception as e:
        logger.error(f"Screenshot failed: {e}")
        raise RuntimeError(f"Screenshot operation failed: {str(e)}")

async def extract_data_impl(session_id: str, pattern: str) -> str:
    """Extract data with pattern matching"""
    session = validate_session(session_id)
    
    if not isinstance(pattern, str) or not pattern:
        raise ValueError("Extraction pattern is required")
    
    try:
        # Define extraction strategies
        strategies = {
            "product prices": '''
                () => {
                    const prices = [];
                    const priceElements = document.querySelectorAll('.price, [class*="price"], [id*="price"], .product-price, .amount');
                    priceElements.forEach(el => {
                        prices.push({
                            text: el.innerText.trim(),
                            location: el.getBoundingClientRect()
                        });
                    });
                    return prices.slice(0, 20); // Limit results
                }
            ''',
            "article headlines": '''
                () => {
                    const headlines = [];
                    const headingElements = document.querySelectorAll('h1, h2, h3, .headline, .title, article h2, article h3');
                    headingElements.forEach(el => {
                        headlines.push({
                            text: el.innerText.trim(),
                            tag: el.tagName.toLowerCase()
                        });
                    });
                    return headlines.slice(0, 20);
                }
            ''',
            "navigation links": '''
                () => {
                    const links = [];
                    const navLinks = document.querySelectorAll('nav a, header a, .navigation a, .menu a');
                    navLinks.forEach(el => {
                        links.push({
                            text: el.innerText.trim(),
                            href: el.getAttribute('href')
                        });
                    });
                    return links.slice(0, 20);
                }
            '''
        }
        
        # Use predefined strategy or generic extraction
        pattern_lower = pattern.lower()
        if pattern_lower in strategies:
            extraction_js = strategies[pattern_lower]
        else:
            # Generic extraction with security limits
            extraction_js = '''
                pattern => {
                    const elements = [];
                    const allElements = document.querySelectorAll('*');
                    const patternLower = pattern.toLowerCase();
                    
                    for (const el of allElements) {
                        const text = el.innerText?.trim();
                        const id = el.id?.toLowerCase();
                        const className = el.getAttribute('class')?.toLowerCase();
                        const tagName = el.tagName?.toLowerCase();
                        
                        if ((text && text.toLowerCase().includes(patternLower)) ||
                            (id && id.includes(patternLower)) ||
                            (className && className.includes(patternLower)) ||
                            (tagName && patternLower.includes(tagName))) {
                            
                            elements.push({
                                tag: tagName,
                                text: text ? (text.length > 100 ? text.substring(0, 100) + "..." : text) : "",
                                id: id || undefined,
                                class: className || undefined
                            });
                            
                            if (elements.length >= 20) break;
                        }
                    }
                    
                    return elements;
                }
            '''
        
        extracted_data = await session.page.evaluate(extraction_js, pattern)
        result = json.dumps(extracted_data, indent=2)
        
        logger.info("Extracted data from session %s", session_id)
        return result
        
    except Exception as e:
        logger.error(f"Data extraction failed: {e}")
        raise RuntimeError(f"Data extraction failed: {str(e)}")

async def close_browser_impl(session_id: str) -> str:
    """Close browser session with cleanup"""
    session = validate_session(session_id)
    
    try:
        await session.cleanup()
        del active_sessions[session_id]
        
        logger.info(f"Browser session {session_id} closed")
        return f"Browser session {session_id} closed successfully"
        
    except Exception as e:
        logger.error(f"Session cleanup failed: {e}")
        raise RuntimeError(f"Failed to close session: {str(e)}")

async def cleanup_all_sessions():
    """Clean up all browser sessions"""
    logger.info("Cleaning up all browser sessions...")
    for session_id in list(active_sessions.keys()):
        try:
            await close_browser_impl(session_id)
        except Exception as e:
            logger.error(f"Failed to cleanup session {session_id}: {e}")

async def _list_tools_handler(context, params):
    return types.ListToolsResult(tools=await list_tools())


async def _call_tool_handler(context, params):
    try:
        content = await call_tool(params.name, params.arguments or {})
        return types.CallToolResult(content=content)
    except RuntimeError as exc:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=str(exc))], is_error=True
        )


# MCP 2 registers handlers in the constructor and validates tool inputs here.
_TOOL_SCHEMAS = {tool.name: tool.input_schema for tool in tool_definitions()}
server = Server(
    "browser-automation",
    version="0.1.0",
    on_list_tools=_list_tools_handler,
    on_call_tool=_call_tool_handler,
    get_tool_input_schema=_TOOL_SCHEMAS.get,
    cache_hints={"tools/list": CacheHint(ttl_ms=0, scope="private")},
)


async def main():
    """Run the MCP server, closing browsers on EOF, cancellation or termination."""
    import signal

    task = asyncio.current_task()
    previous_sigterm = signal.signal(signal.SIGTERM, lambda *_: task.cancel())
    try:
        async with stdio_server() as (read_stream, write_stream):
            initialization_options = InitializationOptions(
                server_name="browser-automation",
                server_version="0.1.0",
                capabilities=types.ServerCapabilities(tools=types.ToolsCapability()),
            )
            await server.run(read_stream, write_stream, initialization_options)
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        await cleanup_all_sessions()


def cli():
    asyncio.run(main())


if __name__ == "__main__":
    cli()
