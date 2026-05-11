import logging
import asyncio
import time
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FuturesTimeoutError
from multiprocessing import Manager
from typing import Dict, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from command_handlers import CommandExecutor, CommandResult


class JobType(Enum):
    """Type of job execution"""
    ONETIME = "onetime"
    CRON = "cron"


@dataclass
class JobExecution:
    """Tracks a job execution attempt"""
    job_id: str
    command: str
    command_type: Optional[str]
    description: str
    job_type: JobType
    timeout: int
    retry_count: int = 0
    max_retries: int = 5
    last_error: str = ""
    first_attempt_time: float = field(default_factory=time.time)
    last_attempt_time: float = field(default_factory=time.time)

    def can_retry(self) -> bool:
        """Check if job can be retried"""
        if self.job_type == JobType.CRON:
            return False  # No retries for cron jobs
        return self.retry_count < self.max_retries

    def mark_retry(self, error: str):
        """Mark a retry attempt"""
        self.retry_count += 1
        self.last_error = error
        self.last_attempt_time = time.time()


class DeadLetterQueue:
    """In-memory dead letter queue for failed commands"""

    def __init__(self):
        self.failed_jobs: Dict[str, JobExecution] = {}
        self.retry_queue: List[JobExecution] = []

    def add_to_retry(self, job_exec: JobExecution):
        """Add job to retry queue"""
        if job_exec.can_retry():
            logging.warning(
                f"Job [{job_exec.job_id}] failed (attempt {job_exec.retry_count}/{job_exec.max_retries}). "
                f"Adding to retry queue. Error: {job_exec.last_error}"
            )
            self.retry_queue.append(job_exec)
        else:
            self.mark_as_dead(job_exec)

    def mark_as_dead(self, job_exec: JobExecution):
        """Mark job as dead after max retries"""
        self.failed_jobs[job_exec.job_id] = job_exec
        logging.error(
            f"Job [{job_exec.job_id}] marked as DEAD after {job_exec.retry_count} failed attempts. "
            f"Last error: {job_exec.last_error}"
        )

    def get_retry_jobs(self) -> List[JobExecution]:
        """Get all jobs pending retry"""
        jobs = self.retry_queue.copy()
        self.retry_queue.clear()
        return jobs

    def get_dead_jobs(self) -> Dict[str, JobExecution]:
        """Get all dead jobs"""
        return self.failed_jobs.copy()

    def remove_from_dead(self, job_id: str):
        """Remove a job from dead letter queue (for manual retry)"""
        if job_id in self.failed_jobs:
            del self.failed_jobs[job_id]
            logging.info(f"Job [{job_id}] removed from dead letter queue")

    def get_stats(self) -> dict:
        """Get DLQ statistics"""
        return {
            "pending_retries": len(self.retry_queue),
            "dead_jobs": len(self.failed_jobs),
            "dead_job_ids": list(self.failed_jobs.keys())
        }


async def execute_command_async(command: str, command_type: Optional[str], timeout: int) -> CommandResult:
    """Execute command asynchronously in subprocess"""
    executor = CommandExecutor()
    loop = asyncio.get_event_loop()

    # Run command in thread pool to avoid blocking
    result = await loop.run_in_executor(
        None,
        executor.run,
        command,
        command_type,
        timeout
    )
    return result


def run_job_in_process(job_exec: JobExecution) -> CommandResult:
    """
    Entry point for process execution.
    Runs async command execution within the process.
    """
    try:
        # Create new event loop for this process
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Execute command asynchronously
        result = loop.run_until_complete(
            execute_command_async(
                job_exec.command,
                job_exec.command_type,
                job_exec.timeout
            )
        )

        loop.close()
        return result

    except Exception as e:
        logging.error(f"Process execution error for job [{job_exec.job_id}]: {e}")
        return CommandResult(
            success=False,
            error=f"Process execution failed: {str(e)}",
            return_code=-1
        )


class MultiProcessExecutor:
    """
    Manages multiprocessing execution with bounded process pool,
    async operations, and dead letter queue with retries.
    """

    def __init__(self, max_workers: int = 10):
        self.max_workers = max_workers
        self.executor = ProcessPoolExecutor(max_workers=max_workers)
        self.dlq = DeadLetterQueue()
        self.active_jobs: Dict[str, JobExecution] = {}
        logging.info(f"MultiProcessExecutor initialized with {max_workers} workers")

    def submit_job(
        self,
        job_id: str,
        command: str,
        description: str,
        command_type: Optional[str] = None,
        timeout: int = 300,
        job_type: JobType = JobType.ONETIME
    ):
        """Submit a job for execution"""
        job_exec = JobExecution(
            job_id=job_id,
            command=command,
            command_type=command_type,
            description=description,
            job_type=job_type,
            timeout=timeout
        )

        self._execute_job(job_exec)

    def _execute_job(self, job_exec: JobExecution):
        """Execute job in process pool"""
        logging.info(
            f"Submitting job [{job_exec.job_id}] to process pool "
            f"(attempt {job_exec.retry_count + 1}/{job_exec.max_retries + 1})"
        )

        # Track active job
        self.active_jobs[job_exec.job_id] = job_exec

        # Submit to process pool
        future = self.executor.submit(run_job_in_process, job_exec)

        # Add callback for completion
        future.add_done_callback(lambda f: self._handle_completion(job_exec, f))

    def _handle_completion(self, job_exec: JobExecution, future):
        """Handle job completion or failure"""
        try:
            # Get result with timeout
            result = future.result(timeout=job_exec.timeout + 5)

            if result.success:
                logging.info(f"Job [{job_exec.job_id}] completed successfully")
                if result.output:
                    logging.info(f"Output: {result.output}")
            else:
                # Job failed, handle retry logic
                error_msg = result.error or f"Failed with return code {result.return_code}"
                job_exec.mark_retry(error_msg)

                logging.error(
                    f"Job [{job_exec.job_id}] failed: {error_msg} "
                    f"(attempt {job_exec.retry_count}/{job_exec.max_retries})"
                )

                # Add to DLQ for retry or mark as dead
                self.dlq.add_to_retry(job_exec)

        except FuturesTimeoutError:
            error_msg = f"Job execution timed out after {job_exec.timeout} seconds"
            job_exec.mark_retry(error_msg)
            logging.error(f"Job [{job_exec.job_id}] timed out")
            self.dlq.add_to_retry(job_exec)

        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            job_exec.mark_retry(error_msg)
            logging.error(f"Job [{job_exec.job_id}] error: {error_msg}")
            self.dlq.add_to_retry(job_exec)

        finally:
            # Remove from active jobs
            if job_exec.job_id in self.active_jobs:
                del self.active_jobs[job_exec.job_id]

    def process_retries(self):
        """Process all jobs in retry queue"""
        retry_jobs = self.dlq.get_retry_jobs()

        if retry_jobs:
            logging.info(f"Processing {len(retry_jobs)} jobs from retry queue")

            for job_exec in retry_jobs:
                if job_exec.can_retry():
                    # Wait a bit before retry (exponential backoff)
                    wait_time = min(2 ** job_exec.retry_count, 60)  # Max 60 seconds
                    time.sleep(wait_time)
                    self._execute_job(job_exec)
                else:
                    self.dlq.mark_as_dead(job_exec)

    def get_dlq_stats(self) -> dict:
        """Get dead letter queue statistics"""
        stats = self.dlq.get_stats()
        stats['active_jobs'] = len(self.active_jobs)
        stats['active_job_ids'] = list(self.active_jobs.keys())
        return stats

    def get_dead_jobs(self) -> Dict[str, JobExecution]:
        """Get all dead jobs"""
        return self.dlq.get_dead_jobs()

    def retry_dead_job(self, job_id: str) -> bool:
        """Manually retry a dead job"""
        dead_jobs = self.dlq.get_dead_jobs()
        if job_id in dead_jobs:
            job_exec = dead_jobs[job_id]
            # Reset retry count for manual retry
            job_exec.retry_count = 0
            job_exec.last_attempt_time = time.time()
            self.dlq.remove_from_dead(job_id)
            self._execute_job(job_exec)
            return True
        return False

    def shutdown(self, wait: bool = True):
        """Shutdown the executor"""
        logging.info("Shutting down MultiProcessExecutor...")

        # Process any pending retries
        self.process_retries()

        # Shutdown executor
        self.executor.shutdown(wait=wait)

        # Log final stats
        stats = self.get_dlq_stats()
        logging.info(f"Final DLQ stats: {stats}")

        if stats['dead_jobs'] > 0:
            logging.warning(f"Shutdown with {stats['dead_jobs']} dead jobs: {stats['dead_job_ids']}")