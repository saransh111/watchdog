# Command Types Reference

The watchdog system supports multiple command types with specialized handlers for different use cases.

## Command Handler Architecture

The system uses a **strategy pattern** with specialized handlers:
- Each command type has its own handler
- Handlers are auto-detected based on command content or explicit type
- Simple `.run()` interface for execution

## Supported Command Types

### 1. Shell Commands (Default)

General shell/terminal commands.

**Job Definition:**
```json
{
  "job_id": "cleanup-logs",
  "description": "Clean up old log files",
  "schedule": "0 2 * * *",
  "task": {
    "type": "shell",
    "command": "rm -f /tmp/*.log",
    "timeout": 60
  }
}
```

**Auto-detection:** Used as default for unmatched commands

**Supported types:** `shell`, `bash`, `terminal`, `execute_command`

---

### 2. HTTP/CURL Requests

API calls and HTTP requests with automatic JSON formatting.

**Job Definition:**
```json
{
  "job_id": "api-monitor",
  "description": "Monitor API endpoint",
  "schedule": "*/10 * * * *",
  "task": {
    "type": "curl",
    "command": "curl -X GET https://api.example.com/health -H 'Authorization: Bearer token'",
    "timeout": 30
  }
}
```

**Auto-detection:** Commands starting with `curl`

**Supported types:** `curl`, `http`, `https`, `api`

**Features:**
- Automatic JSON response formatting
- Pretty-printed output
- Specialized error handling for network issues

---

### 3. Python Scripts

Execute Python scripts with proper environment handling.

**Job Definition:**
```json
{
  "job_id": "data-processor",
  "description": "Process daily data",
  "schedule": "0 3 * * *",
  "task": {
    "type": "python",
    "command": "/usr/bin/python3 /opt/scripts/process_data.py --date today",
    "timeout": 600
  }
}
```

**Inline Python:**
```json
{
  "job_id": "quick-calc",
  "description": "Quick calculation",
  "schedule": "onetime",
  "task": {
    "type": "python",
    "command": "python3 -c \"print(sum(range(1, 101)))\""
  }
}
```

**Auto-detection:** Commands starting with `python` or `python3`

**Supported types:** `python`, `python3`, `py`

---

### 4. Docker Commands

Manage Docker containers and operations.

**Job Definition:**
```json
{
  "job_id": "container-cleanup",
  "description": "Clean up stopped containers",
  "schedule": "0 4 * * 0",
  "task": {
    "type": "docker",
    "command": "docker container prune -f",
    "timeout": 300
  }
}
```

**Auto-detection:** Commands starting with `docker`

**Supported types:** `docker`, `container`

---

### 5. Process Configuration

Load and process configuration files.

**Job Definition:**
```json
{
  "job_id": "load-config",
  "description": "Load application configuration",
  "schedule": "2026-05-11T15:00:00Z",
  "task": {
    "type": "config",
    "command": "/path/to/config.json",
    "timeout": 30
  }
}
```

**Supported types:** `config`, `process_config`, `configure`

**Note:** Command should be path to JSON configuration file

---

## Task Field Reference

### Required Fields

- **type** or **command_type**: Handler type (optional if command is auto-detectable)
- **command**: The actual command to execute

### Optional Fields

- **timeout**: Execution timeout in seconds (default: 300)

### Example with All Options

```json
{
  "job_id": "comprehensive-job",
  "description": "Job with all options",
  "schedule": "0 * * * *",
  "task": {
    "type": "curl",
    "command": "curl -s https://api.example.com/data",
    "timeout": 60
  }
}
```

---

## Auto-Detection Rules

The system automatically detects command types:

1. **Priority Order:** Handlers are checked in this order:
   - CurlCommandHandler
   - PythonScriptHandler
   - DockerCommandHandler
   - ProcessConfigHandler
   - ShellCommandHandler (default)

2. **Detection Logic:**
   - `curl` → CurlCommandHandler
   - `python` or `python3` → PythonScriptHandler
   - `docker` → DockerCommandHandler
   - Everything else → ShellCommandHandler

3. **Explicit Type:** Override auto-detection by setting `type` field

---

## Adding Custom Handlers

To add a new command handler:

1. **Create Handler Class** in `command_handlers.py`:
```python
class CustomHandler(CommandHandler):
    def can_handle(self, command: str, command_type: Optional[str] = None) -> bool:
        if command_type == 'custom':
            return True
        return command.startswith('mycmd')

    def execute(self, command: str, timeout: int = 300) -> CommandResult:
        # Your execution logic
        return CommandResult(success=True, output="Done")
```

2. **Register Handler** in `CommandExecutor.__init__()`:
```python
self.handlers = [
    CustomHandler(),  # Add before ShellCommandHandler
    CurlCommandHandler(),
    # ... other handlers
    ShellCommandHandler(),  # Keep as last
]
```

3. **Use in Jobs**:
```json
{
  "task": {
    "type": "custom",
    "command": "mycmd arg1 arg2"
  }
}
```

---

## Command Result Handling

All handlers return a `CommandResult` object:

```python
class CommandResult:
    success: bool        # True if command succeeded
    output: str         # Standard output
    error: str          # Error messages
    return_code: int    # Process return code
```

**Logging:**
- Success: Logs output at INFO level
- Failure: Logs error at ERROR level with return code

---

## Examples by Use Case

### Daily Report Generation
```json
{
  "job_id": "daily-report",
  "description": "Generate daily sales report",
  "schedule": "0 8 * * *",
  "task": {
    "type": "python",
    "command": "/usr/bin/python3 /opt/scripts/daily_report.py",
    "timeout": 1800
  }
}
```

### API Health Monitoring
```json
{
  "job_id": "health-check",
  "description": "Check service health",
  "schedule": "*/5 * * * *",
  "task": {
    "type": "curl",
    "command": "curl -f https://myservice.com/health || exit 1"
  }
}
```

### Database Backup
```json
{
  "job_id": "db-backup",
  "description": "Backup PostgreSQL database",
  "schedule": "0 2 * * *",
  "task": {
    "type": "shell",
    "command": "pg_dump mydb > /backups/mydb_$(date +%Y%m%d).sql",
    "timeout": 3600
  }
}
```

### Docker Maintenance
```json
{
  "job_id": "docker-prune",
  "description": "Clean up Docker resources",
  "schedule": "0 3 * * 0",
  "task": {
    "type": "docker",
    "command": "docker system prune -af --volumes"
  }
}
```
