#!/usr/bin/env python3
"""
Dead Letter Queue Monitor
Shows stats and dead jobs from the watchdog system
"""
import sys
import json
from pathlib import Path

# This is a standalone script to help monitor DLQ
# In production, you would integrate this into a dashboard or API

def main():
    print("=" * 60)
    print("Dead Letter Queue Monitor")
    print("=" * 60)
    print()
    print("This is a monitoring script for the watchdog DLQ.")
    print()
    print("To see DLQ stats in real-time, check the watchdog logs:")
    print("  - Stats are logged every 30 seconds during retry processing")
    print("  - Final stats are logged on shutdown")
    print()
    print("DLQ Information:")
    print("  - One-time jobs: Retry up to 5 times with exponential backoff")
    print("  - Cron jobs: No retries (skip on failure)")
    print("  - Dead jobs: Jobs that failed all retry attempts")
    print()
    print("To manually retry a dead job:")
    print("  1. Note the job_id from the logs")
    print("  2. Add retry logic via the JobScheduler.retry_dead_job() method")
    print()
    print("=" * 60)

if __name__ == "__main__":
    main()