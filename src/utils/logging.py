"""Structured logging module for DevOps Agent."""
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, Optional
from functools import wraps
import time
import uuid


class StructuredFormatter(logging.Formatter):
    """Custom formatter that outputs JSON-structured logs."""

    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record as JSON.

        Args:
            record: Log record to format

        Returns:
            JSON-formatted log string
        """
        log_data = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }

        # Add correlation ID if present
        if hasattr(record, 'correlation_id'):
            log_data['correlation_id'] = record.correlation_id

        # Add user info if present
        if hasattr(record, 'user'):
            log_data['user'] = record.user

        # Add action info if present
        if hasattr(record, 'action'):
            log_data['action'] = record.action

        # Add command info if present
        if hasattr(record, 'command'):
            log_data['command'] = record.command

        # Add result info if present
        if hasattr(record, 'result'):
            log_data['result'] = record.result

        # Add execution time if present
        if hasattr(record, 'execution_time_ms'):
            log_data['execution_time_ms'] = record.execution_time_ms

        # Add metadata if present
        if hasattr(record, 'metadata'):
            log_data['metadata'] = record.metadata

        # Add exception info if present
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)

        return json.dumps(log_data)


class ConsoleFormatter(logging.Formatter):
    """Custom formatter for console output with colors."""

    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[35m',  # Magenta
    }
    RESET = '\033[0m'

    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record for console with colors.

        Args:
            record: Log record to format

        Returns:
            Formatted log string with colors
        """
        color = self.COLORS.get(record.levelname, self.RESET)
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Basic message
        message = f"{color}[{record.levelname}]{self.RESET} {timestamp} - {record.getMessage()}"

        # Add action if present
        if hasattr(record, 'action'):
            message += f" [action={record.action}]"

        # Add execution time if present
        if hasattr(record, 'execution_time_ms'):
            message += f" ({record.execution_time_ms}ms)"

        return message


def setup_logging(
    log_file: str,
    log_level: str = 'INFO',
    max_size_mb: int = 100,
    backup_count: int = 5,
    console_output: bool = True,
    json_format: bool = True
) -> None:
    """
    Set up structured logging for the application.

    Args:
        log_file: Path to log file
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        max_size_mb: Maximum log file size in MB before rotation
        backup_count: Number of backup files to keep
        console_output: Whether to output logs to console
        json_format: Whether to use JSON format for file logs
    """
    # Create logs directory if it doesn't exist
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Remove existing handlers
    root_logger.handlers = []

    # File handler with rotation
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_size_mb * 1024 * 1024,
        backupCount=backup_count
    )
    file_handler.setLevel(getattr(logging, log_level.upper()))

    if json_format:
        file_handler.setFormatter(StructuredFormatter())
    else:
        file_handler.setFormatter(
            logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        )

    root_logger.addHandler(file_handler)

    # Console handler
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, log_level.upper()))
        console_handler.setFormatter(ConsoleFormatter())
        root_logger.addHandler(console_handler)

    # Set third-party loggers to WARNING to reduce noise
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('botocore').setLevel(logging.WARNING)
    logging.getLogger('kubernetes').setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance.

    Args:
        name: Logger name (usually __name__)

    Returns:
        Logger instance
    """
    return logging.getLogger(name)


def log_operation(action: str, user: Optional[str] = None):
    """
    Decorator to log function operations with timing and result.

    Args:
        action: Name of the action being performed
        user: User performing the action

    Returns:
        Decorated function
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            logger = get_logger(func.__module__)
            correlation_id = str(uuid.uuid4())[:8]

            # Start timing
            start_time = time.time()

            # Create log record with extra fields
            extra_fields = {
                'correlation_id': correlation_id,
                'action': action,
                'user': user or 'system'
            }

            try:
                # Log operation start
                logger.info(f"Starting {action}", extra=extra_fields)

                # Execute function
                result = func(*args, **kwargs)

                # Calculate execution time
                execution_time_ms = int((time.time() - start_time) * 1000)
                extra_fields['execution_time_ms'] = execution_time_ms
                extra_fields['result'] = 'success'

                # Log success
                logger.info(f"Completed {action}", extra=extra_fields)

                return result

            except Exception as e:
                # Calculate execution time
                execution_time_ms = int((time.time() - start_time) * 1000)
                extra_fields['execution_time_ms'] = execution_time_ms
                extra_fields['result'] = 'failure'

                # Log failure
                logger.error(
                    f"Failed {action}: {str(e)}",
                    extra=extra_fields,
                    exc_info=True
                )
                raise

        return wrapper
    return decorator


def log_command_execution(
    logger: logging.Logger,
    command: str,
    result: str,
    execution_time_ms: int,
    success: bool = True,
    metadata: Optional[Dict[str, Any]] = None
) -> None:
    """
    Log a command execution with structured data.

    Args:
        logger: Logger instance
        command: Command that was executed
        result: Result of the command
        execution_time_ms: Execution time in milliseconds
        success: Whether the command succeeded
        metadata: Additional metadata
    """
    extra_fields = {
        'action': 'execute_command',
        'command': command,
        'result': 'success' if success else 'failure',
        'execution_time_ms': execution_time_ms,
        'metadata': metadata or {}
    }

    if success:
        logger.info(f"Command executed: {command}", extra=extra_fields)
    else:
        logger.error(f"Command failed: {command}", extra=extra_fields)


def mask_sensitive_data(text: str) -> str:
    """
    Mask sensitive data in text (API keys, tokens, passwords).

    Args:
        text: Text potentially containing sensitive data

    Returns:
        Text with sensitive data masked
    """
    # Common patterns for sensitive data
    patterns = [
        (r'(api[_-]?key|token|password|secret)["\s:=]+([^\s"]+)', r'\1=***MASKED***'),
        (r'(AKIA[0-9A-Z]{16})', r'***MASKED_AWS_KEY***'),
        (r'([0-9a-f]{40})', r'***MASKED_TOKEN***'),
    ]

    import re
    result = text
    for pattern, replacement in patterns:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    return result
