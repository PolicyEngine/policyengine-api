from google.cloud import logging
import json
import datetime
import argparse
import os
import time
from typing import Optional, List, Dict, Any
from collections import Counter


def extract_simulation_logs(
    project_id: str = "policyengine-api",
    start_time: Optional[datetime.datetime] = None,
    end_time: Optional[datetime.datetime] = None,
    output_file: str = "simulation_logs.json",
    metrics_file: str = "message_metrics.json",
    max_results: int = 1_000_000_000,
    page_size: int = 100,
    sleep_interval: int = 100,  # Sleep after this many records
    sleep_duration: float = 1.0,  # Sleep duration in seconds
) -> List[Dict[str, Any]]:
    """
    Extract economy simulation logs from Google Cloud logs.

    Args:
        project_id: The GCP project ID
        start_time: Start time for log extraction (defaults to 24 hours ago)
        end_time: End time for log extraction (defaults to now)
        output_file: Path to save the log results
        metrics_file: Path to save the message metrics results
        max_results: Maximum number of results to return
        page_size: Number of results to fetch per API call
        sleep_interval: Number of records to process before sleeping
        sleep_duration: Time to sleep in seconds

    Returns:
        A list of simulation logs
    """
    # Initialize the logging client
    client = logging.Client(project=project_id)

    # Set default time range if not provided
    if start_time is None:
        start_time = datetime.datetime.now(
            datetime.timezone.utc
        ) - datetime.timedelta(hours=24)
    if end_time is None:
        end_time = datetime.datetime.now(datetime.timezone.utc)

    # List for storing results
    simulation_logs = []
    message_counter = Counter()

    # Counter for progress tracking
    log_count = 0
    matched_count = 0
    fetch_count = 0

    try:
        # Create a file to stream results to
        with open(output_file, "w") as f:
            # Write the opening bracket for the JSON array
            f.write("[\n")

            first_entry = True

            # Break down the request into smaller time windows instead of using pagination
            current_start = start_time

            while current_start < end_time and matched_count < max_results:
                # Calculate a small time window (e.g., 1 hour)
                window_end = min(
                    current_start + datetime.timedelta(hours=1), end_time
                )

                # Format timestamps for GCP filter
                start_time_str = current_start.isoformat()
                end_time_str = window_end.isoformat()

                # Build a specific filter for this time window
                filter_str = (
                    f'resource.type="gae_app" AND '
                    f'resource.labels.project_id="{project_id}" AND '
                    f'timestamp >= "{start_time_str}" AND '
                    f'timestamp < "{end_time_str}" AND '
                    f'(jsonPayload.message="APIv2 job started" OR '
                    f'jsonPayload.message="APIv2 job completed" OR '
                    f'jsonPayload.message="APIv2 job comparison with APIv1 completed" OR '
                    f'jsonPayload.message="APIv1 job failed" OR '
                    f'jsonPayload.message="APIv2 job failed")'
                )

                print(
                    f"Fetching logs from {start_time_str} to {end_time_str}..."
                )

                # Fetch logs for this time window (without pagination)
                entries = client.list_entries(
                    filter_=filter_str, page_size=page_size
                )

                # Process entries for this time window
                window_count = 0

                for entry in entries:
                    window_count += 1
                    log_count += 1
                    fetch_count += 1

                    # Add a sleep after every sleep_interval records fetched to avoid rate limits
                    if fetch_count % sleep_interval == 0:
                        print(
                            f"Sleeping after fetching {fetch_count} records..."
                        )
                        time.sleep(sleep_duration)  # Sleep to avoid rate limiting

                    matched_count += 1

                    # Extract the message for metrics counting
                    message = extract_message(entry)
                    if message:
                        message_counter[message] += 1

                    # Convert the entire log entry to a dict
                    entry_dict = log_entry_to_dict(entry)

                    # Write the full log entry to the file
                    if not first_entry:
                        f.write(",\n")
                    else:
                        first_entry = False

                    json.dump(entry_dict, f, indent=2)

                    # Append to in-memory list if not too big
                    if len(simulation_logs) < max_results:
                        simulation_logs.append(entry_dict)

                    # Show progress every 10 entries
                    if matched_count % 10 == 0:
                        print(
                            f"Processed {log_count} logs, matched {matched_count}..."
                        )

                    # Check if we've hit the maximum results
                    if matched_count >= max_results:
                        print(f"Reached maximum result limit of {max_results}")
                        break

                print(
                    f"Found {window_count} logs in this time window, {matched_count} matching logs so far."
                )

                # Move to the next time window
                current_start = window_end

                # Sleep between time windows to avoid rate limiting
                time.sleep(sleep_duration * 2)  # Slightly longer sleep between time windows

            # Write the closing bracket for the JSON array
            f.write("\n]")

        # After processing all logs, write message metrics to the metrics file
        write_message_metrics(message_counter, metrics_file)

    except Exception as e:
        print(f"Error fetching logs: {e}")
        import traceback

        traceback.print_exc()
        # If the file was created but not completed, add the closing bracket
        if os.path.exists(output_file):
            with open(output_file, "a") as f:
                f.write("\n]")

        # Write whatever metrics we've collected so far
        write_message_metrics(message_counter, metrics_file)

    print(f"Finished processing {log_count} logs, matched {matched_count}.")
    print(f"Results saved to {output_file}")
    print(f"Message metrics saved to {metrics_file}")

    return simulation_logs


def extract_message(entry) -> str:
    """Extract the message field from a log entry"""
    try:
        if hasattr(entry, "payload") and entry.payload:
            # If the above didn't work, try as a dictionary
            payload_dict = dict(entry.payload)
            return payload_dict.get("message", "")
    except Exception:
        pass
    
    return ""


def log_entry_to_dict(entry) -> Dict[str, Any]:
    """Extract only the jsonPayload from a log entry and parse it to JSON"""
    try:
        # Extract timestamp for reference
        timestamp = entry.timestamp.isoformat() if hasattr(entry, "timestamp") else None
        
        # Initialize with timestamp
        result = {"timestamp": timestamp}
        
        # Extract jsonPayload
        if hasattr(entry, "payload") and entry.payload:
            # Try as dictionary
            payload_dict = dict(entry.payload)
            return payload_dict
        
        # If no jsonPayload found, return just the timestamp with a note
        result["jsonPayload_missing"] = True
        return result
    except Exception as e:
        print(f"Error extracting jsonPayload: {e}")
        # Return a minimal dict with timestamp if extraction fails
        return {
            "timestamp": entry.timestamp.isoformat() if hasattr(entry, "timestamp") else None,
            "extraction_error": str(e)
        }


def write_message_metrics(message_counter: Counter, metrics_file: str) -> None:
    """Write message metrics to a JSON file"""
    try:
        with open(metrics_file, "w") as f:
            metrics = {
                "total_logs": sum(message_counter.values()),
                "message_counts": dict(message_counter.most_common()),
                "unique_message_count": len(message_counter),
                "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }
            json.dump(metrics, f, indent=2, default=str)
        print(f"Message metrics written to {metrics_file}")
    except Exception as e:
        print(f"Error writing message metrics: {e}")


def parse_datetime(date_str: str) -> datetime.datetime:
    """Parse datetime string in ISO format with timezone awareness"""
    try:
        dt = datetime.datetime.fromisoformat(date_str)
        # Ensure timezone is set
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt
    except ValueError:
        raise ValueError(
            f"Invalid datetime format: {date_str}. Use ISO format (YYYY-MM-DDTHH:MM:SS+00:00)"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Extract economy simulation logs from GCP"
    )
    parser.add_argument(
        "--project-id", default="policyengine-api", help="GCP project ID"
    )
    parser.add_argument(
        "--start-time",
        help="Start time in ISO format (e.g., 2025-04-01T00:00:00+00:00)",
    )
    parser.add_argument(
        "--end-time",
        help="End time in ISO format (e.g., 2025-05-01T00:00:00+00:00)",
    )
    parser.add_argument(
        "--output-file",
        default="simulation_logs.json",
        help="Path to save the log results",
    )
    parser.add_argument(
        "--metrics-file",
        default="message_metrics.json",
        help="Path to save the message metrics results",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=1_000_000_000,
        help="Maximum number of results to return",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=100,
        help="Number of results to fetch per API call",
    )
    parser.add_argument(
        "--sleep-interval",
        type=int,
        default=100,
        help="Number of records to process before sleeping (default: 100)",
    )
    parser.add_argument(
        "--sleep-duration",
        type=float,
        default=1.0,
        help="Sleep duration in seconds (default: 1.0)",
    )

    args = parser.parse_args()

    # Parse datetime arguments if provided
    start_time = parse_datetime(args.start_time) if args.start_time else None
    end_time = parse_datetime(args.end_time) if args.end_time else None

    # Extract simulation logs
    extract_simulation_logs(
        project_id=args.project_id,
        start_time=start_time,
        end_time=end_time,
        output_file=args.output_file,
        metrics_file=args.metrics_file,
        max_results=args.max_results,
        page_size=args.page_size,
        sleep_interval=args.sleep_interval,
        sleep_duration=args.sleep_duration,
    )


if __name__ == "__main__":
    main()