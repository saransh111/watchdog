import time
import logging
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from process_executor import MultiProcessExecutor, JobType

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


class JobScheduler:
    """Manages job scheduling and execution"""

    def __init__(self, max_workers: int = 10):
        self.scheduler = BackgroundScheduler()
        self.jobs: Dict[str, dict] = {}
        self.process_executor = MultiProcessExecutor(max_workers=max_workers)

        # Schedule periodic retry processing every 30 seconds
        self.scheduler.add_job(
            self.process_retries,
            'interval',
            seconds=30,
            id='retry_processor',
            name='Retry Queue Processor'
        )

        self.scheduler.start()
        logging.info("Job scheduler initialized")

    def load_job_from_file(self, file_path: Path) -> Optional[dict]:
        """Load and parse a job definition from a JSON file"""
        try:
            with open(file_path, 'r') as f:
                job_data = json.load(f)

            required_fields = ['job_id', 'description', 'schedule', 'task']
            if not all(field in job_data for field in required_fields):
                logging.error(f"Job file {file_path} missing required fields")
                return None

            if 'type' not in job_data['task'] or 'command' not in job_data['task']:
                logging.error(f"Job file {file_path} has invalid task definition")
                return None

            return job_data
        except json.JSONDecodeError as e:
            logging.error(f"Invalid JSON in {file_path}: {e}")
            return None
        except Exception as e:
            logging.error(f"Error loading job from {file_path}: {e}")
            return None

    def execute_job(
        self,
        job_id: str,
        command: str,
        description: str,
        command_type: Optional[str] = None,
        timeout: int = 300,
        job_type: JobType = JobType.ONETIME
    ):
        """Execute a job's command using multiprocess executor"""
        logging.info(f"Executing job [{job_id}] ({job_type.value}): {description}")

        # Submit job to process executor
        self.process_executor.submit_job(
            job_id=job_id,
            command=command,
            description=description,
            command_type=command_type,
            timeout=timeout,
            job_type=job_type
        )

    def process_retries(self):
        """Process retry queue periodically"""
        self.process_executor.process_retries()

    def get_dlq_stats(self) -> dict:
        """Get dead letter queue statistics"""
        return self.process_executor.get_dlq_stats()

    def get_dead_jobs(self):
        """Get all dead jobs"""
        return self.process_executor.get_dead_jobs()

    def retry_dead_job(self, job_id: str) -> bool:
        """Manually retry a dead job"""
        return self.process_executor.retry_dead_job(job_id)

    def add_job(self, job_data: dict):
        """Add or update a job in the scheduler"""
        job_id = job_data['job_id']
        schedule = job_data['schedule']
        task = job_data['task']
        command = task['command']
        description = job_data['description']

        # Extract optional command type and timeout from task
        command_type = task.get('command_type') or task.get('type')
        timeout = task.get('timeout', 300)

        if job_id in self.jobs:
            self.remove_job(job_id)

        try:
            # Detect schedule type based on format
            if self._is_datetime_schedule(schedule):
                # ISO 8601 datetime format - one-time execution at specific date/time
                try:
                    run_date = datetime.fromisoformat(schedule.replace('Z', '+00:00'))
                    now = datetime.now(timezone.utc)

                    # Ensure run_date is timezone-aware
                    if run_date.tzinfo is None:
                        run_date = run_date.replace(tzinfo=timezone.utc)

                    if run_date < now:
                        logging.warning(f"Job [{job_id}] scheduled time {run_date} is in the past, will execute immediately")
                        run_date = now

                    logging.info(f"Scheduling one-time job [{job_id}]: {description} at {run_date}")
                    self.scheduler.add_job(
                        self.execute_job,
                        'date',
                        run_date=run_date,
                        args=[job_id, command, description, command_type, timeout, JobType.ONETIME],
                        id=job_id
                    )
                except ValueError as e:
                    logging.error(f"Invalid datetime format for job [{job_id}]: {schedule} - {e}")
                    return
            else:
                # Cron expression format - recurring execution
                cron_parts = schedule.split()
                if len(cron_parts) != 5:
                    logging.error(f"Invalid cron expression for job [{job_id}]: {schedule}. Expected format: 'minute hour day month day_of_week'")
                    return

                trigger = CronTrigger(
                    minute=cron_parts[0],
                    hour=cron_parts[1],
                    day=cron_parts[2],
                    month=cron_parts[3],
                    day_of_week=cron_parts[4]
                )

                logging.info(f"Scheduling cron job [{job_id}]: {description} with schedule '{schedule}'")
                self.scheduler.add_job(
                    self.execute_job,
                    trigger=trigger,
                    args=[job_id, command, description, command_type, timeout, JobType.CRON],
                    id=job_id
                )

            self.jobs[job_id] = job_data
            logging.info(f"Job [{job_id}] added successfully")
        except Exception as e:
            logging.error(f"Error adding job [{job_id}]: {e}")

    def _is_datetime_schedule(self, schedule: str) -> bool:
        """Check if schedule is a datetime string (ISO 8601 format)"""
        # Check for datetime indicators: T separator and date-like format
        if 'T' in schedule or '-' in schedule[:10]:
            # Try parsing as datetime
            try:
                datetime.fromisoformat(schedule.replace('Z', '+00:00'))
                return True
            except ValueError:
                return False
        return False

    def remove_job(self, job_id: str):
        """Remove a job from the scheduler"""
        try:
            if job_id in self.jobs:
                self.scheduler.remove_job(job_id)
                del self.jobs[job_id]
                logging.info(f"Job [{job_id}] removed")
        except Exception as e:
            logging.error(f"Error removing job [{job_id}]: {e}")

    def initialize_jobs(self, jobs_dir: Path):
        """Initialize all jobs from JSON files in the directory"""
        logging.info(f"Initializing jobs from {jobs_dir}")
        job_files = list(jobs_dir.glob('*.json'))

        if not job_files:
            logging.warning(f"No job files found in {jobs_dir}")
            return

        for job_file in job_files:
            logging.info(f"Loading job from {job_file.name}")
            job_data = self.load_job_from_file(job_file)
            if job_data:
                self.add_job(job_data)

        logging.info(f"Initialized {len(self.jobs)} jobs")

    def shutdown(self):
        """Shutdown the scheduler and process executor"""
        logging.info("Shutting down job scheduler...")

        # Log DLQ stats before shutdown
        dlq_stats = self.get_dlq_stats()
        logging.info(f"DLQ Stats: {dlq_stats}")

        # Shutdown scheduler
        self.scheduler.shutdown()

        # Shutdown process executor (will process remaining retries)
        self.process_executor.shutdown(wait=True)


class JobFileWatchHandler(FileSystemEventHandler):
    """Handler for job file system events"""

    def __init__(self, job_scheduler: JobScheduler):
        super().__init__()
        self.job_scheduler = job_scheduler

    def on_created(self, event: FileSystemEvent):
        """Called when a job file is created"""
        if not event.is_directory and event.src_path.endswith('.json'):
            logging.info(f"JOB FILE CREATED: {event.src_path}")
            job_data = self.job_scheduler.load_job_from_file(Path(event.src_path))
            if job_data:
                self.job_scheduler.add_job(job_data)

    def on_modified(self, event: FileSystemEvent):
        """Called when a job file is modified"""
        if not event.is_directory and event.src_path.endswith('.json'):
            logging.info(f"JOB FILE MODIFIED: {event.src_path}")
            job_data = self.job_scheduler.load_job_from_file(Path(event.src_path))
            if job_data:
                self.job_scheduler.add_job(job_data)

    def on_deleted(self, event: FileSystemEvent):
        """Called when a job file is deleted"""
        if not event.is_directory and event.src_path.endswith('.json'):
            logging.info(f"JOB FILE DELETED: {event.src_path}")
            # Extract job_id from filename or find the job to remove
            file_name = Path(event.src_path).stem
            # Try to find and remove job by checking existing jobs
            for job_id in list(self.job_scheduler.jobs.keys()):
                if file_name in job_id or job_id in file_name:
                    self.job_scheduler.remove_job(job_id)
                    break

    def on_moved(self, event: FileSystemEvent):
        """Called when a job file is moved or renamed"""
        if not event.is_directory and event.dest_path.endswith('.json'):
            logging.info(f"JOB FILE MOVED: {event.src_path} -> {event.dest_path}")
            # Reload the job from the new location
            job_data = self.job_scheduler.load_job_from_file(Path(event.dest_path))
            if job_data:
                self.job_scheduler.add_job(job_data)

def main():
    jobs_dir = Path(__file__).parent / 'tmp' / 'data'

    # Create directory if it doesn't exist
    jobs_dir.mkdir(parents=True, exist_ok=True)

    # Initialize job scheduler
    job_scheduler = JobScheduler()

    # Load all existing job files
    job_scheduler.initialize_jobs(jobs_dir)

    logging.info(f"Starting job file watchdog on: {jobs_dir}")
    logging.info("Monitoring for job file changes... (Press Ctrl+C to stop)")

    # Set up file system observer
    event_handler = JobFileWatchHandler(job_scheduler)
    observer = Observer()
    observer.schedule(event_handler, str(jobs_dir), recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Stopping watchdog...")
        observer.stop()
        job_scheduler.shutdown()

    observer.join()
    logging.info("Watchdog stopped.")

if __name__ == "__main__":
    main()

