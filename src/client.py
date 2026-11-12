#!/usr/bin/env python
import asyncio
import sys
import logging
import json
import os
import argparse
from typing import Optional, List, Dict, Any
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MCPClient:
    def __init__(self):
        # Initialize session and client objects
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        
        # Get Ollama model from environment variable or use default
        ollama_model = os.environ.get("OLLAMA_MODEL", "qwen3")
        logger.info(f"Using Ollama model: {ollama_model}")
        
        # Configure Ollama with optimized parameters
        self.llm = ChatOllama(
            model=ollama_model,
            num_ctx=32000,  # Large context window for complex tasks
            base_url="http://localhost:11434",
            temperature=0,  # Deterministic outputs for consistent automation
        )
        
        # Initialize conversation history for continuous context
        self.messages = [
            SystemMessage(content="""You are an expert browser automation assistant with advanced capabilities for web analysis and data extraction. 
            You will be given access to browser automation tools and will help navigate websites, extract information, and perform tasks.
            You should think step by step, explaining your reasoning, and then decide on the next action to take.
            """)
        ]
        
        # Cache for storing frequently accessed data
        self.cache = {}
        
    async def connect_to_server(self, server_script_path: str):
        """Connect to an MCP server
        
        Args:
            server_script_path: Path to the server script (.py or .js)
        """
        logger.debug(f"Connecting to server at {server_script_path}")
        is_python = server_script_path.endswith('.py')
        is_js = server_script_path.endswith('.js')
        if not (is_python or is_js):
            raise ValueError("Server script must be a .py or .js file")
            
        command = sys.executable if is_python else "node"
        server_params = StdioServerParameters(
            command=command,
            args=[server_script_path],
            env=None
        )
        
        logger.debug("Creating stdio transport")
        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
        self.stdio, self.write = stdio_transport
        
        logger.debug("Creating client session")
        self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))
        
        logger.debug("Discovering server (MCP 2026-07-28)")
        await self.session.discover()
        
        # List available tools
        logger.debug("Listing tools")
        try:
            response = await self.session.list_tools()
            self.tools = response.tools
            print("\nConnected to server with tools:", [tool.name for tool in self.tools])
            
            # Add tools information to the system message
            tools_info = "\n".join([f"- {tool.name}: {tool.description}" for tool in self.tools])
            self.messages[0] = SystemMessage(content=f"{self.messages[0].content}\n\nAvailable tools:\n{tools_info}")
            
        except Exception as e:
            logger.error(f"Error listing tools: {str(e)}", exc_info=True)
            raise

    async def interactive_browser_automation(self, initial_task: str):
        """Run an interactive browser automation session with continuous Ollama guidance
        
        Args:
            initial_task: The initial task description
        """
        try:
            # Add the initial task to the conversation
            self.messages.append(HumanMessage(content=f"Task: {initial_task}\n\nWhat should be my first step?"))
            
            # Start the interactive loop
            session_id = None
            task_complete = False
            
            while not task_complete:
                # Get Ollama's next recommendation
                print("\nSending current state to Ollama for analysis...")
                response = await self.llm.ainvoke(self.messages)
                print(f"\nOllama's analysis:\n{response.content}")
                
                # Add Ollama's response to the conversation history
                self.messages.append(AIMessage(content=response.content))
                
                # Parse the recommended action
                action = self._parse_next_action(response.content)
                if not action:
                    # Ask for a more specific action
                    self.messages.append(HumanMessage(content="Please provide a specific action to take using one of the available tools. Format your response as a JSON object with 'tool' and 'parameters' fields."))
                    continue
                
                # Check if the task is complete
                if action.get("tool") == "task_complete":
                    print("\nTask completed successfully!")
                    task_complete = True
                    break
                
                # Execute the recommended action
                tool_name = action["tool"]
                parameters = action["parameters"]
                
                # Handle session ID for browser actions
                if tool_name == "launch_browser":
                    print(f"\nExecuting: {tool_name}")
                    print(f"Parameters: {json.dumps(parameters, indent=2)}")
                    
                    result = await self.session.call_tool(tool_name, parameters)
                    result_text = result.content[0].text
                    print(f"Result: {result_text}")
                    
                    # Store the session ID
                    session_id = result_text
                    
                elif session_id and "session_id" in parameters:
                    # Update the session ID in the parameters
                    parameters["session_id"] = session_id
                    
                    print(f"\nExecuting: {tool_name}")
                    print(f"Parameters: {json.dumps(parameters, indent=2)}")
                    
                    result = await self.session.call_tool(tool_name, parameters)
                    result_text = result.content[0].text
                    print(f"Result: {result_text}")
                    
                    # Special handling for screenshot results
                    if tool_name == "take_screenshot":
                        result_text = f"Screenshot saved. The browser window shows the current state of the page."
                else:
                    print(f"\nExecuting: {tool_name}")
                    print(f"Parameters: {json.dumps(parameters, indent=2)}")
                    
                    result = await self.session.call_tool(tool_name, parameters)
                    result_text = result.content[0].text
                    print(f"Result: {result_text}")
                
                # Add the result to the conversation
                self.messages.append(HumanMessage(content=f"Action result: {result_text}\n\nWhat should be my next step?"))
                
                # Add delay between actions
                await asyncio.sleep(1)
            
            # Ensure browser is closed
            if session_id:
                await self.session.call_tool("close_browser", {"session_id": session_id})
                print("\nBrowser closed.")
            
        except Exception as e:
            logger.error(f"Error during interactive automation: {str(e)}", exc_info=True)
            print(f"\nError during interactive automation: {str(e)}")
            
            # Ensure browser is closed on error
            if session_id:
                try:
                    await self.session.call_tool("close_browser", {"session_id": session_id})
                    print("\nBrowser closed after error.")
                except Exception as close_error:
                    logger.error(f"Error closing browser: {str(close_error)}", exc_info=True)

    def _parse_next_action(self, response_text: str) -> Dict[str, Any]:
        """Parse the next action from Ollama's response
        
        Args:
            response_text: Ollama's response text
            
        Returns:
            Dictionary with tool name and parameters, or None if no valid action found
        """
        try:
            # Look for JSON blocks in the response
            json_pattern = r'```json\\s*([\\s\\S]*?)\\s*```'
            import re
            json_matches = re.findall(json_pattern, response_text)
            
            if json_matches:
                for json_str in json_matches:
                    try:
                        action = json.loads(json_str)
                        if isinstance(action, dict) and "tool" in action and "parameters" in action:
                            return action
                    except json.JSONDecodeError:
                        continue
            
            # If no JSON blocks, look for tool mentions in the text (only if tools are loaded)
            if hasattr(self, 'tools'):
                tool_names = [tool.name for tool in self.tools]
                for tool_name in tool_names:
                    if tool_name in response_text:
                        # Try to extract parameters from the text
                        params_start = response_text.find(tool_name) + len(tool_name)
                        params_text = response_text[params_start:].strip()
                        
                        # Simple heuristic to extract parameters
                        parameters = {}
                        if "url" in params_text.lower() and tool_name == "launch_browser":
                            url_match = re.search(r'https?://[^\s"\']+', params_text)
                            if url_match:
                                parameters["url"] = url_match.group(0)
                                return {"tool": tool_name, "parameters": parameters}
            
            # If task completion is mentioned
            if "task complete" in response_text.lower() or "task is complete" in response_text.lower():
                return {"tool": "task_complete", "parameters": {}}
                
            return None
            
        except Exception as e:
            logger.warning(f"Failed to parse next action: {e}")
            return None

    async def run_task_from_file(self, task_file: str):
        """Run a task from a file
        
        Args:
            task_file: Path to the task description file
        """
        try:
            with open(task_file, 'r') as f:
                task_description = f.read()
            logger.info(f"Loaded task description from {task_file}")
            
            await self.interactive_browser_automation(task_description)
            
        except Exception as e:
            logger.error(f"Error reading task file: {str(e)}")
            raise

    async def cleanup(self):
        """Clean up resources"""
        logger.debug("Cleaning up resources")
        await self.exit_stack.aclose()

async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Interactive browser automation with Ollama")
    parser.add_argument("server_script", help="Path to the MCP server script")
    parser.add_argument("task", nargs='?', help="Task description or path to task file")
    parser.add_argument("--file", action="store_true", help="Treat task argument as file path")
    parser.add_argument("--model", help="Ollama model to use (overrides OLLAMA_MODEL env var)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    
    args = parser.parse_args()
    
    # Set debug logging if requested
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")
    
    # Set model if provided
    if args.model:
        os.environ["OLLAMA_MODEL"] = args.model
        logger.info(f"Using specified Ollama model: {args.model}")
    
    # Default task if none provided
    if not args.task:
        args.task = "Navigate to Ollama's model library, analyze the page content, and extract information about the available models."
    
    client = MCPClient()
    
    try:
        await client.connect_to_server(args.server_script)
        
        if args.file:
            # Run task from file
            await client.run_task_from_file(args.task)
        else:
            # Run interactive automation with task description
            await client.interactive_browser_automation(args.task)
            
    except KeyboardInterrupt:
        logger.info("\nTask execution interrupted by user.")
    except Exception as e:
        logger.error(f"Error during execution: {str(e)}", exc_info=True)
    finally:
        await client.cleanup()

def cli():
    asyncio.run(main())


if __name__ == "__main__":
    cli()
