"""Core DevOps Agent with Claude API integration."""
import anthropic
from typing import List, Dict, Any, Optional, Callable
import json
import time
from datetime import datetime

from ..config import ConfigManager
from ..utils import get_logger, log_operation
from .conversation import ConversationManager
from .safety import SafetyValidator


class DevOpsAgent:
    """Main DevOps Agent class that orchestrates Claude AI and tool execution."""

    def __init__(self, config: ConfigManager):
        """
        Initialize DevOps Agent.

        Args:
            config: Configuration manager instance
        """
        self.config = config
        self.logger = get_logger(__name__)
        self.client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        self.conversation = ConversationManager()

        # Initialize SafetyValidator with pentest configuration
        pentest_config = {
            'enabled': config.get('pentest.enabled', False),
            'require_confirmation': config.get('pentest.require_confirmation', True),
            'whitelisted_targets': config.get('pentest.whitelisted_targets', []),
            'max_scan_intensity': config.get('pentest.max_scan_intensity', 4),
            'prohibited_scan_types': config.get('pentest.prohibited_scan_types', [])
        }
        self.safety_validator = SafetyValidator(config.dangerous_commands, pentest_config)
        self.tools: Dict[str, Callable] = {}
        self.tool_definitions: List[Dict[str, Any]] = []

        self.logger.info("DevOps Agent initialized")

    def register_tool(
        self,
        name: str,
        description: str,
        input_schema: Dict[str, Any],
        handler: Callable
    ) -> None:
        """
        Register a tool that Claude can use.

        Args:
            name: Tool name
            description: Tool description
            input_schema: JSON schema for tool input
            handler: Function to execute when tool is called
        """
        # Store tool definition for Claude API
        self.tool_definitions.append({
            'name': name,
            'description': description,
            'input_schema': input_schema
        })

        # Store handler function
        self.tools[name] = handler

        self.logger.info(f"Registered tool: {name}")

    def register_tools_from_module(self, module: Any) -> None:
        """
        Register all tools from a module.

        Args:
            module: Module containing tool definitions and handlers
        """
        if hasattr(module, 'get_tools'):
            tools = module.get_tools()
            for tool in tools:
                self.register_tool(
                    name=tool['name'],
                    description=tool['description'],
                    input_schema=tool['input_schema'],
                    handler=tool['handler']
                )

    @log_operation("process_user_message")
    def process_message(self, user_message: str, user_preferences_context: Optional[str] = None) -> str:
        """
        Process a user message and return the agent's response.

        Args:
            user_message: User's input message
            user_preferences_context: Optional context string with user preferences

        Returns:
            Agent's response text
        """
        self.logger.info(f"Processing user message: {user_message[:100]}...")

        # Add user message to conversation
        self.conversation.add_user_message(user_message)

        # Process with Claude API
        response_text = self._call_claude_api(user_preferences_context)

        return response_text

    def _build_system_prompt(self, user_preferences_context: Optional[str] = None) -> Optional[str]:
        """
        Build system prompt with user preferences context.

        Args:
            user_preferences_context: Optional context string with user preferences

        Returns:
            System prompt string or None if no context provided
        """
        if not user_preferences_context:
            return None

        base_prompt = """You are a helpful DevOps agent with access to multiple cloud platforms and tools.
You can help manage AWS, Azure, GCP, Kubernetes, Docker, Terraform, and more.

User Preferences and Context:
{preferences}

Please use these preferences to provide personalized assistance:
- Use the user's preferred cloud provider when applicable
- Apply their default regions and instance types
- Consider their recent operations for context
- Provide suggestions if they have that enabled
- Adjust verbosity based on their preference"""

        return base_prompt.format(preferences=user_preferences_context)

    def _call_claude_api(self, user_preferences_context: Optional[str] = None) -> str:
        """
        Call Claude API with current conversation and handle tool execution.

        Args:
            user_preferences_context: Optional context string with user preferences

        Returns:
            Final response text from Claude
        """
        max_iterations = 50  # Prevent infinite loops (increased for complex operations)
        iteration = 0

        while iteration < max_iterations:
            iteration += 1
            self.logger.debug(f"Claude API call iteration {iteration}")

            try:
                # Build system prompt with user preferences if provided
                system_prompt = self._build_system_prompt(user_preferences_context)

                # Call Claude API with streaming to prevent timeouts
                api_params = {
                    'model': self.config.claude_model,
                    'max_tokens': self.config.claude_max_tokens,
                    'temperature': self.config.claude_temperature,
                    'tools': self.tool_definitions if self.tool_definitions else None,
                    'messages': self.conversation.get_messages_for_api()
                }

                # Add system prompt if we have one
                if system_prompt:
                    api_params['system'] = system_prompt

                # Use streaming to prevent network timeouts on long requests
                with self.client.messages.stream(**api_params) as stream:
                    # The stream context manager handles all the event processing
                    # and assembles the final message for us
                    response = stream.get_final_message()

                # Add assistant's response to conversation
                self.conversation.add_assistant_message(response.content)

                # Check stop reason
                if response.stop_reason == 'end_turn':
                    # Claude is done, extract text response
                    return self._extract_text_from_response(response.content)

                elif response.stop_reason == 'tool_use':
                    # Claude wants to use tools
                    self._handle_tool_uses(response.content)
                    # Continue loop to get final response

                elif response.stop_reason == 'max_tokens':
                    self.logger.warning("Response truncated due to max_tokens limit")
                    return self._extract_text_from_response(response.content) + "\n\n[Response truncated]"

                else:
                    self.logger.warning(f"Unexpected stop reason: {response.stop_reason}")
                    return self._extract_text_from_response(response.content)

            except anthropic.RateLimitError as e:
                error_msg = f"Rate limit exceeded: {str(e)}"
                self.logger.warning(error_msg)
                return "⏸️ Rate limit reached. The API is automatically retrying, but please wait a moment before making another request.\n\nTip: Try combining multiple operations into a single request to reduce API calls."

            except anthropic.APIStatusError as e:
                error_msg = f"Claude API status error: {e.status_code} - {str(e)}"
                self.logger.error(error_msg)

                # Check if it's a temporary server error
                if e.status_code in [500, 502, 503, 504]:
                    return f"⚠️ Temporary API issue (status {e.status_code}). The API is experiencing issues on Anthropic's side. Please try again in a few moments."

                # Check if it's a conversation history corruption error
                if "unexpected tool_use_id" in str(e) or "tool_result" in str(e):
                    self.logger.warning("Conversation history corrupted. Clearing and retrying...")
                    # Save the original user message
                    last_user_msg = self.conversation.messages[-1] if self.conversation.messages else None

                    # Clear conversation history
                    self.conversation.clear_history()

                    # Re-add just the last user message if we had one
                    if last_user_msg and last_user_msg.role == 'user':
                        self.conversation.messages.append(last_user_msg)

                    # Retry once with clean history
                    if iteration == 1:  # Only retry on first iteration
                        continue

                return f"❌ Error communicating with Claude: {str(e)}\n\nThe conversation was reset due to a synchronization error. Please try your request again."

            except anthropic.APIError as e:
                error_msg = f"Claude API error: {str(e)}"
                self.logger.error(error_msg)
                return f"❌ Error communicating with Claude: {str(e)}"

            except Exception as e:
                error_msg = f"Unexpected error: {str(e)}"
                self.logger.error(error_msg, exc_info=True)
                return f"❌ Unexpected error: {str(e)}"

        # Max iterations reached
        self.logger.error("Max iterations reached in Claude API loop")
        return "❌ Maximum number of tool executions reached. Please try rephrasing your request."

    def _handle_tool_uses(self, content: List[Dict[str, Any]]) -> None:
        """
        Handle tool use requests from Claude.

        Args:
            content: Response content containing tool uses
        """
        for block in content:
            if block.type == 'tool_use':
                tool_name = block.name
                tool_input = block.input
                tool_use_id = block.id

                self.logger.info(f"Executing tool: {tool_name}")
                self.logger.debug(f"Tool input: {json.dumps(tool_input, indent=2)}")

                # Validate tool call safety
                validation = self.safety_validator.validate_tool_call(tool_name, tool_input)

                if not validation.is_safe:
                    result = {
                        'success': False,
                        'error': f"Tool execution blocked: {validation.reason}",
                        'risk_level': validation.risk_level
                    }
                    self.conversation.add_tool_result(tool_use_id, json.dumps(result))
                    continue

                # Check if confirmation is required
                if validation.requires_confirmation and self.config.require_confirmation:
                    # For now, we'll proceed but log the warning
                    # In a real CLI, you'd prompt the user here
                    self.logger.warning(
                        f"High-risk operation requires confirmation: {tool_name} "
                        f"(risk_level: {validation.risk_level})"
                    )

                # Execute tool
                try:
                    if tool_name in self.tools:
                        result = self.tools[tool_name](**tool_input)
                    else:
                        result = {
                            'success': False,
                            'error': f"Unknown tool: {tool_name}"
                        }

                    self.logger.info(f"Tool {tool_name} executed successfully")

                except Exception as e:
                    self.logger.error(f"Tool {tool_name} failed: {str(e)}", exc_info=True)
                    result = {
                        'success': False,
                        'error': f"Tool execution failed: {str(e)}"
                    }

                # Add tool result to conversation
                result_str = json.dumps(result, indent=2)
                sanitized_result = self.safety_validator.sanitize_output(result_str)
                self.conversation.add_tool_result(tool_use_id, sanitized_result)

                # Add small delay to help with rate limiting
                time.sleep(0.5)

    def _extract_text_from_response(self, content: List[Dict[str, Any]]) -> str:
        """
        Extract text from Claude's response content.

        Args:
            content: Response content blocks

        Returns:
            Combined text from all text blocks
        """
        text_blocks = []
        for block in content:
            if block.type == 'text':
                text_blocks.append(block.text)

        return '\n'.join(text_blocks) if text_blocks else ""

    def clear_conversation(self) -> None:
        """Clear conversation history."""
        self.conversation.clear_history()
        self.logger.info("Conversation history cleared")

    def reset_conversation_with_diagnostics(self) -> Dict[str, Any]:
        """
        Force reset conversation with full diagnostics.

        This is more aggressive than clear_conversation() and provides
        diagnostic information about the state before reset.

        Returns:
            Dictionary with diagnostic information
        """
        # Gather diagnostics before clearing
        diagnostics = {
            'messages_count': len(self.conversation.messages),
            'session_duration_seconds': (datetime.utcnow() - self.conversation.session_start).total_seconds(),
            'had_tool_results': False,
            'had_tool_uses': False,
            'message_roles': []
        }

        # Analyze message structure
        for msg in self.conversation.messages:
            diagnostics['message_roles'].append(msg.role)
            for block in msg.content:
                block_type = block.get('type') if isinstance(block, dict) else getattr(block, 'type', None)
                if block_type == 'tool_result':
                    diagnostics['had_tool_results'] = True
                elif block_type == 'tool_use':
                    diagnostics['had_tool_uses'] = True

        # Clear conversation
        self.conversation.clear_history()

        self.logger.warning(
            f"Conversation forcefully reset. Diagnostics: "
            f"{diagnostics['messages_count']} messages, "
            f"tool_uses={diagnostics['had_tool_uses']}, "
            f"tool_results={diagnostics['had_tool_results']}"
        )

        return diagnostics

    def get_conversation_summary(self) -> Dict[str, Any]:
        """
        Get summary of current conversation.

        Returns:
            Dictionary with conversation statistics
        """
        return self.conversation.get_summary()

    def list_available_tools(self) -> List[str]:
        """
        Get list of available tool names.

        Returns:
            List of tool names
        """
        return list(self.tools.keys())

    def get_tool_info(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a specific tool.

        Args:
            tool_name: Name of the tool

        Returns:
            Tool definition or None if not found
        """
        for tool_def in self.tool_definitions:
            if tool_def['name'] == tool_name:
                return tool_def
        return None

    def export_conversation(self) -> List[Dict[str, Any]]:
        """
        Export conversation for debugging or analysis.

        Returns:
            List of all messages with timestamps
        """
        return self.conversation.export_conversation()

    def __repr__(self) -> str:
        """String representation of agent."""
        return (
            f"DevOpsAgent("
            f"model={self.config.claude_model}, "
            f"tools={len(self.tools)}, "
            f"messages={len(self.conversation)})"
        )
