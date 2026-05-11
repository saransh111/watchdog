import logging
import subprocess
import json
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from pathlib import Path


class CommandResult:
    """Result of command execution"""

    def __init__(self, success: bool, output: str = "", error: str = "", return_code: int = 0):
        self.success = success
        self.output = output
        self.error = error
        self.return_code = return_code


class CommandHandler(ABC):
    """Base class for command handlers"""

    @abstractmethod
    def can_handle(self, command: str, command_type: Optional[str] = None) -> bool:
        """Check if this handler can handle the given command"""
        pass

    @abstractmethod
    def execute(self, command: str, timeout: int = 300) -> CommandResult:
        """Execute the command and return result"""
        pass


class ShellCommandHandler(CommandHandler):
    """Handler for general shell commands"""

    def can_handle(self, command: str, command_type: Optional[str] = None) -> bool:
        if command_type in ['shell', 'bash', 'terminal', 'execute_command']:
            return True
        # Default handler for commands that don't match other types
        return True

    def execute(self, command: str, timeout: int = 300) -> CommandResult:
        """Execute shell command"""
        try:
            logging.info(f"Executing shell command: {command}")
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            return CommandResult(
                success=(result.returncode == 0),
                output=result.stdout.strip() if result.stdout else "",
                error=result.stderr.strip() if result.stderr else "",
                return_code=result.returncode
            )
        except subprocess.TimeoutExpired:
            return CommandResult(
                success=False,
                error=f"Command timed out after {timeout} seconds",
                return_code=-1
            )
        except Exception as e:
            return CommandResult(
                success=False,
                error=f"Error executing command: {str(e)}",
                return_code=-1
            )


class CurlCommandHandler(CommandHandler):
    """Handler for HTTP/CURL requests"""

    def can_handle(self, command: str, command_type: Optional[str] = None) -> bool:
        if command_type in ['curl', 'http', 'https', 'api']:
            return True
        # Auto-detect curl commands
        return command.strip().startswith('curl')

    def execute(self, command: str, timeout: int = 300) -> CommandResult:
        """Execute curl/HTTP request"""
        logging.info("Executing HTTP request")
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            success = result.returncode == 0
            output = result.stdout.strip() if result.stdout else ""

            # Try to parse JSON response
            if output:
                try:
                    json_data = json.loads(output)
                    output = json.dumps(json_data, indent=2)
                except json.JSONDecodeError:
                    pass  # Not JSON, keep as is

            return CommandResult(
                success=success,
                output=output,
                error=result.stderr.strip() if result.stderr else "",
                return_code=result.returncode
            )
        except subprocess.TimeoutExpired:
            return CommandResult(
                success=False,
                error=f"HTTP request timed out after {timeout} seconds",
                return_code=-1
            )
        except Exception as e:
            return CommandResult(
                success=False,
                error=f"Error executing HTTP request: {str(e)}",
                return_code=-1
            )


class PythonScriptHandler(CommandHandler):
    """Handler for Python script execution"""

    def can_handle(self, command: str, command_type: Optional[str] = None) -> bool:
        if command_type in ['python', 'python3', 'py']:
            return True
        # Auto-detect python commands
        cmd_lower = command.strip().lower()
        return cmd_lower.startswith('python') or cmd_lower.startswith('python3')

    def execute(self, command: str, timeout: int = 300) -> CommandResult:
        """Execute Python script"""
        logging.info("Executing Python script")
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=None  # Inherit environment
            )

            return CommandResult(
                success=(result.returncode == 0),
                output=result.stdout.strip() if result.stdout else "",
                error=result.stderr.strip() if result.stderr else "",
                return_code=result.returncode
            )
        except subprocess.TimeoutExpired:
            return CommandResult(
                success=False,
                error=f"Python script timed out after {timeout} seconds",
                return_code=-1
            )
        except Exception as e:
            return CommandResult(
                success=False,
                error=f"Error executing Python script: {str(e)}",
                return_code=-1
            )


class ProcessConfigHandler(CommandHandler):
    """Handler for process configuration files"""

    def can_handle(self, command: str, command_type: Optional[str] = None) -> bool:
        if command_type in ['config', 'process_config', 'configure']:
            return True
        return False

    def execute(self, command: str, timeout: int = 300) -> CommandResult:
        """Execute process configuration"""
        logging.info("Processing configuration")
        try:
            # Command should be path to config file
            config_path = Path(command.strip())

            if not config_path.exists():
                return CommandResult(
                    success=False,
                    error=f"Configuration file not found: {config_path}",
                    return_code=-1
                )

            # Read and validate config
            with open(config_path, 'r') as f:
                config_data = json.load(f)

            # Process the configuration (customize based on your needs)
            output = f"Configuration loaded successfully from {config_path}\n"
            output += f"Config keys: {', '.join(config_data.keys())}"

            return CommandResult(
                success=True,
                output=output,
                return_code=0
            )
        except json.JSONDecodeError as e:
            return CommandResult(
                success=False,
                error=f"Invalid JSON in config file: {str(e)}",
                return_code=-1
            )
        except Exception as e:
            return CommandResult(
                success=False,
                error=f"Error processing configuration: {str(e)}",
                return_code=-1
            )


class DockerCommandHandler(CommandHandler):
    """Handler for Docker commands"""

    def can_handle(self, command: str, command_type: Optional[str] = None) -> bool:
        if command_type in ['docker', 'container']:
            return True
        return command.strip().startswith('docker')

    def execute(self, command: str, timeout: int = 300) -> CommandResult:
        """Execute Docker command"""
        logging.info("Executing Docker command")
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            return CommandResult(
                success=(result.returncode == 0),
                output=result.stdout.strip() if result.stdout else "",
                error=result.stderr.strip() if result.stderr else "",
                return_code=result.returncode
            )
        except subprocess.TimeoutExpired:
            return CommandResult(
                success=False,
                error=f"Docker command timed out after {timeout} seconds",
                return_code=-1
            )
        except Exception as e:
            return CommandResult(
                success=False,
                error=f"Error executing Docker command: {str(e)}",
                return_code=-1
            )


class CommandExecutor:
    """Main executor that routes commands to appropriate handlers"""

    def __init__(self):
        # Register handlers in priority order (specific handlers first)
        self.handlers = [
            CurlCommandHandler(),
            PythonScriptHandler(),
            DockerCommandHandler(),
            ProcessConfigHandler(),
            ShellCommandHandler(),  # Default handler, keep last
        ]

    def run(self, command: str, command_type: Optional[str] = None, timeout: int = 300) -> CommandResult:
        """
        Execute command using appropriate handler

        Args:
            command: The command string to execute
            command_type: Optional explicit command type
            timeout: Command timeout in seconds
        """
        # Find appropriate handler
        for handler in self.handlers:
            if handler.can_handle(command, command_type):
                handler_name = handler.__class__.__name__
                logging.info(f"Using {handler_name} for command execution")
                return handler.execute(command, timeout)

        # Fallback (should never reach here due to ShellCommandHandler)
        return CommandResult(
            success=False,
            error="No suitable handler found for command",
            return_code=-1
        )
