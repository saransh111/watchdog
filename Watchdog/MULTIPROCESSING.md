# Multiprocessing & Dead Letter Queue System

## Overview

The watchdog system uses a sophisticated multiprocessing architecture with async operations, bounded process pools, and automatic retry with dead letter queue (DLQ) management.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Job Scheduler                           │
│  - Schedules jobs (cron/datetime)                          │
│  - Submits to MultiProcessExecutor                         │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              MultiProcessExecutor                           │
│  - ProcessPoolExecutor (max 10 workers)                    │
│  - Async command execution                                  │
│  - Retry management                                         │
│  - Dead Letter Queue                                        │
└──────────────────────┬──────────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
    Process 1      Process 2    ... Process 10
    (Async)        (Async)          (Async)
        │              │              │
        └──────────────┴──────────────┘
                       │
                       ▼
              Command Handlers
         (Shell, Curl, Python, etc.)
```

## Key Features

### 1. Bounded Process Pool

- **Max Workers**: 10 concurrent processes
- **Process Management**: Automatic scaling and cleanup
- **Isolation**: Each job runs in separate process
- **Async Operations**: Each process uses asyncio for efficiency

### 2. Job Types

#### One-Time Jobs
- Scheduled with ISO 8601 datetime
- **Retry Enabled**: Up to 5 retries
- **Exponential Backoff**: Wait time increases with retries
- **DLQ**: Failed jobs go to dead letter queue

```json
{
  "job_id": "backup-001",
  "schedule": "2026-05-11T02:00:00Z",
  "task": { "command": "backup.sh" }
}
```

#### Cron Jobs
- Scheduled with cron expression
- **No Retries**: Skip on failure
- **Recurring**: Next execution not affected by failures

```json
{
  "job_id": "monitor-001",
  "schedule": "*/5 * * * *",
  "task": { "command": "health_check.sh" }
}
```

### 3. Retry Logic

#### Retry Strategy
1. **Immediate Failure Detection**: Job fails with non-zero exit code
2. **Add to Retry Queue**: If retry count < max retries (5)
3. **Exponential Backoff**: Wait time = min(2^retry_count, 60) seconds
4. **Retry Processor**: Runs every 30 seconds
5. **Mark as Dead**: After 5 failed attempts

#### Retry Timeline Example
```
Attempt 1: Immediate execution → FAIL
Attempt 2: Wait 2 seconds → FAIL
Attempt 3: Wait 4 seconds → FAIL
Attempt 4: Wait 8 seconds → FAIL
Attempt 5: Wait 16 seconds → FAIL
Attempt 6: Wait 32 seconds → FAIL (Max retries)
→ Marked as DEAD
```

### 4. Dead Letter Queue (DLQ)

The DLQ tracks failed jobs that exceeded retry limits.

#### DLQ Structure
```python
{
  "job_id": "failed-job-001",
  "command": "problematic_command.sh",
  "retry_count": 5,
  "last_error": "Command returned non-zero exit status 1",
  "first_attempt_time": 1715434567.123,
  "last_attempt_time": 1715434628.456
}
```

#### DLQ Operations

**Check Stats:**
```python
stats = job_scheduler.get_dlq_stats()
# {
#   "pending_retries": 2,
#   "dead_jobs": 3,
#   "dead_job_ids": ["job-1", "job-2", "job-3"],
#   "active_jobs": 5,
#   "active_job_ids": ["job-4", "job-5", ...]
# }
```

**Get Dead Jobs:**
```python
dead_jobs = job_scheduler.get_dead_jobs()
for job_id, job_exec in dead_jobs.items():
    print(f"{job_id}: {job_exec.last_error}")
```

**Manual Retry:**
```python
success = job_scheduler.retry_dead_job("failed-job-001")
# Resets retry count and re-executes
```

## Process Execution Flow

### Successful Execution
```
1. Job submitted to ProcessPoolExecutor
2. Process allocated from pool
3. Async command execution
4. Command succeeds (exit code 0)
5. Log success output
6. Process returned to pool
```

### Failed Execution with Retry
```
1. Job submitted to ProcessPoolExecutor
2. Process allocated from pool
3. Async command execution
4. Command fails (exit code != 0)
5. Mark retry (increment count)
6. Add to retry queue
7. Wait for retry processor (30s interval)
8. Apply exponential backoff
9. Re-submit to executor
10. Repeat until success or max retries
```

### Dead Job
```
1. Job fails 6th time (max retries = 5)
2. Move to Dead Letter Queue
3. Log as DEAD with error details
4. Stop retry attempts
5. Await manual intervention
```

## Configuration

### Adjust Max Workers
```python
# In main.py
job_scheduler = JobScheduler(max_workers=20)  # Default: 10
```

### Adjust Max Retries
Edit `process_executor.py`:
```python
@dataclass
class JobExecution:
    max_retries: int = 10  # Default: 5
```

### Adjust Retry Interval
Edit `main.py`:
```python
self.scheduler.add_job(
    self.process_retries,
    'interval',
    seconds=60,  # Default: 30
    id='retry_processor'
)
```

### Adjust Backoff Strategy
Edit `process_executor.py`:
```python
def process_retries(self):
    for job_exec in retry_jobs:
        # Current: exponential backoff
        wait_time = min(2 ** job_exec.retry_count, 60)

        # Alternative: linear backoff
        # wait_time = job_exec.retry_count * 10

        # Alternative: fixed interval
        # wait_time = 30
```

## Monitoring

### Real-Time Logs
The system logs DLQ activity:
```
2026-05-11 14:10:00 - WARNING - Job [backup-001] failed (attempt 1/5). Adding to retry queue. Error: Exit code 1
2026-05-11 14:10:02 - INFO - Processing 1 jobs from retry queue
2026-05-11 14:10:04 - ERROR - Job [backup-001] failed (attempt 2/5): Connection timeout
2026-05-11 14:10:08 - ERROR - Job [backup-001] marked as DEAD after 5 failed attempts. Last error: Connection timeout
```

### DLQ Stats
Stats are logged:
- Every 30 seconds during retry processing
- On system shutdown

```
2026-05-11 14:10:30 - INFO - DLQ Stats: {'pending_retries': 0, 'dead_jobs': 1, 'dead_job_ids': ['backup-001'], 'active_jobs': 3}
```

### Manual Monitoring
```bash
# Watch logs for DLQ activity
tail -f watchdog.log | grep -E "DLQ|retry|DEAD"

# Use monitoring script
python dlq_monitor.py
```

## Best Practices

### 1. Job Design
- ✅ Make jobs idempotent (safe to retry)
- ✅ Use appropriate timeouts
- ✅ Handle errors gracefully in scripts
- ❌ Don't rely on order of execution
- ❌ Avoid jobs with external dependencies on other jobs

### 2. Retry Strategy
- ✅ Use one-time jobs for critical operations needing retries
- ✅ Use cron jobs for monitoring/health checks (no retry needed)
- ✅ Set realistic timeouts (balance between completion and resource usage)
- ❌ Don't use retries for jobs that will always fail (fix the job instead)

### 3. DLQ Management
- ✅ Monitor DLQ regularly
- ✅ Investigate dead jobs to find root causes
- ✅ Fix underlying issues before manual retry
- ✅ Clean up old dead jobs periodically
- ❌ Don't ignore growing DLQ

### 4. Resource Management
- ✅ Keep max_workers appropriate for your system (default: 10)
- ✅ Use timeouts to prevent runaway jobs
- ✅ Monitor system resources (CPU, memory)
- ❌ Don't set max_workers too high (can overwhelm system)

## Examples

### Critical Job with Retries
```json
{
  "job_id": "critical-backup",
  "description": "Critical database backup",
  "schedule": "2026-05-12T02:00:00Z",
  "task": {
    "type": "shell",
    "command": "pg_dump mydb > /backups/backup.sql",
    "timeout": 3600
  }
}
```
- One-time job → Retries enabled
- Long timeout for large backup
- Will retry up to 5 times if fails

### Health Check Without Retries
```json
{
  "job_id": "health-monitor",
  "description": "API health check",
  "schedule": "*/5 * * * *",
  "task": {
    "type": "curl",
    "command": "curl -f https://api.example.com/health",
    "timeout": 10
  }
}
```
- Cron job → No retries
- Runs every 5 minutes
- Next check happens regardless of failure

### Python Script with Custom Timeout
```json
{
  "job_id": "data-processor",
  "description": "Process daily data",
  "schedule": "2026-05-12T03:00:00Z",
  "task": {
    "type": "python",
    "command": "python3 /opt/scripts/process_data.py",
    "timeout": 1800
  }
}
```
- One-time job → Retries enabled
- 30-minute timeout
- Retries with exponential backoff

## Troubleshooting

### High DLQ Count
**Symptom**: Many jobs in dead letter queue

**Possible Causes**:
- Jobs have bugs or incorrect configuration
- External dependencies are down
- Timeouts are too short
- System resources exhausted

**Solutions**:
1. Check job logs for error patterns
2. Test jobs manually
3. Increase timeouts if needed
4. Fix external dependencies
5. Add monitoring for dependencies

### Jobs Not Retrying
**Symptom**: Failed jobs not appearing in retry queue

**Possible Causes**:
- Jobs are cron type (no retries by design)
- Retry processor not running
- System shutdown before retry

**Solutions**:
1. Verify job type (check schedule format)
2. Check logs for retry processor activity
3. Ensure watchdog runs long enough for retries

### Process Pool Exhaustion
**Symptom**: Jobs queuing up, slow execution

**Possible Causes**:
- Too many concurrent jobs
- Jobs taking longer than expected
- max_workers too low

**Solutions**:
1. Increase max_workers
2. Optimize job execution time
3. Spread out job schedules
4. Add job prioritization

## Performance Tuning

### For High-Throughput Systems
```python
# Increase workers
job_scheduler = JobScheduler(max_workers=50)

# Faster retry processing
self.scheduler.add_job(
    self.process_retries,
    'interval',
    seconds=10
)

# Shorter backoff
wait_time = min(2 ** job_exec.retry_count, 10)
```

### For Resource-Constrained Systems
```python
# Reduce workers
job_scheduler = JobScheduler(max_workers=5)

# Slower retry processing
self.scheduler.add_job(
    self.process_retries,
    'interval',
    seconds=60
)

# Longer backoff
wait_time = min(2 ** job_exec.retry_count, 120)
```

## API Reference

### MultiProcessExecutor

```python
executor = MultiProcessExecutor(max_workers=10)

# Submit job
executor.submit_job(
    job_id="my-job",
    command="echo hello",
    description="Test job",
    command_type="shell",
    timeout=60,
    job_type=JobType.ONETIME
)

# Process retries
executor.process_retries()

# Get stats
stats = executor.get_dlq_stats()

# Get dead jobs
dead_jobs = executor.get_dead_jobs()

# Retry dead job
success = executor.retry_dead_job("job-id")

# Shutdown
executor.shutdown(wait=True)
```

### JobScheduler

```python
scheduler = JobScheduler(max_workers=10)

# Get DLQ stats
stats = scheduler.get_dlq_stats()

# Get dead jobs
dead_jobs = scheduler.get_dead_jobs()

# Retry dead job
success = scheduler.retry_dead_job("job-id")

# Shutdown
scheduler.shutdown()
```

## Future Enhancements

Potential improvements:
- Persistent DLQ (survive restarts)
- Priority queues for jobs
- Job dependencies
- Webhook notifications for failures
- Web dashboard for DLQ monitoring
- Configurable retry strategies per job
- Job execution history/audit log