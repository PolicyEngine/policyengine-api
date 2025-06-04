"""
PolicyEngine API Client - A tool for batch processing economic impact requests.

This module provides functionality to sequentially send requests to the PolicyEngine API
and collect their results, with appropriate pacing to avoid overloading the service.
"""

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict
from datetime import datetime
import sys

import requests
from requests.exceptions import RequestException


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class PolicyRequest(TypedDict, total=False):
    """Type definition for a policy request configuration."""
    
    reform: int
    baseline: int
    region: str
    timePeriod: int
    dataset: str
    version: str
    maxHouseholds: int


class PolicyResponse(TypedDict, total=False):
    """Type definition for a policy response."""
    
    status: str
    result: Dict[str, Any]
    message: str


class RequestResult(TypedDict):
    """Type definition for a complete request result."""
    
    request: PolicyRequest
    response: PolicyResponse
    elapsed_time: float


@dataclass
class PollingConfig:
    """Configuration for API polling behavior."""
    
    max_attempts: int = 600
    interval_seconds: float = 1.0


@dataclass
class BatchConfig:
    """Configuration for request batching behavior."""
    
    size: int = 10
    pause_seconds: int = 120


class APIError(Exception):
    """Custom exception for API-related errors."""
    
    pass


class PolicyEngineClient:
    """Client for interacting with the PolicyEngine API."""

    def __init__(
        self,
        base_url: str = "https://api.policyengine.org",
        polling_config: Optional[PollingConfig] = None,
        batch_config: Optional[BatchConfig] = None
    ):
        """
        Initialize the PolicyEngine API client.
        
        Args:
            base_url: Base URL for the PolicyEngine API
            polling_config: Configuration for polling behavior
            batch_config: Configuration for request batching
        """
        self.base_url = base_url
        self.polling_config = polling_config or PollingConfig()
        self.batch_config = batch_config or BatchConfig()
        
    def create_url(
        self,
        country_id: str,
        reform_id: int,
        baseline_id: int,
        region: str = "us",
        time_period: int = 2025,
        dataset: Optional[str] = None,
        max_households: Optional[int] = None,
        household: Optional[int] = None,
        mode: Optional[str] = None
    ) -> str:
        """
        Create the API endpoint URL with query parameters.
        
        Args:
            country_id: ID of the country for the simulation
            reform_id: ID of the reform policy
            baseline_id: ID of the baseline policy
            region: Geographic region for the simulation
            time_period: Time period (year) for the simulation
            dataset: Dataset to use for the simulation
            max_households: Maximum number of households to include
            household: Specific household ID to include
            
        Returns:
            Fully formed URL string for the API request
        """
        # Build base endpoint URL
        endpoint = f"{self.base_url}/{country_id}/economy/{reform_id}/over/{baseline_id}"
        
        # Collect required query parameters
        params = {
            "region": region,
            "time_period": time_period,
        }
        
        # Add optional parameters if provided
        if dataset:
            params["dataset"] = dataset

        if max_households:
            params["max_households"] = max_households

        if household:
            params["household"] = household

        if mode:
            params["mode"] = mode
            
        # Build query string
        query_string = "&".join(f"{key}={value}" for key, value in params.items())
        
        print(f"Generated URL: {endpoint}?{query_string}", file=sys.stderr)
        return f"{endpoint}?{query_string}"
    
    def poll_until_complete(self, url: str) -> PolicyResponse:
        """
        Poll the API until computation is complete or max attempts reached.
        
        Args:
            url: The API endpoint URL to poll
            
        Returns:
            The final API response
            
        Raises:
            APIError: If there's a persistent error in the API communication
        """
        consecutive_errors = 0
        max_consecutive_errors = 3
        
        for attempt in range(self.polling_config.max_attempts):
            try:
                logger.info("Polling API...")
                response = requests.get(url, timeout=30)
                logger.debug(f"Response status code: {response.status_code}")
                response.raise_for_status()
                data = response.json()
                
                # Reset error counter on successful request
                consecutive_errors = 0
                
                # Check if computation is complete
                if data.get("status") != "computing":
                    logger.info(f"Computation completed after {attempt + 1} attempts")
                    return data
                    
                logger.debug(f"Computation in progress (attempt {attempt + 1}/{self.polling_config.max_attempts})")
                
            except RequestException as error:
                logger.warning(f"Request failed: {error}")
                consecutive_errors += 1
                logger.error(f"Error during API request: {error}")
                
                # If we've had too many consecutive errors, abort
                if consecutive_errors >= max_consecutive_errors:
                    raise APIError(f"Encountered {max_consecutive_errors} consecutive errors") from error
            
            # Sleep before next attempt
            time.sleep(self.polling_config.interval_seconds)
                
        logger.warning("Maximum polling attempts reached without completion")
        return {"status": "error", "message": "Maximum polling attempts reached without completion"}
    
    def _get_country_id(self, region: str = "us") -> str:
        
        # All UK regions that aren't "uk" contain "/"; US ones do not
        if region != "uk" and "/" not in region:
            print(f"Assuming US region: {region}", file=sys.stderr)
            return "us"
        
        print(f"Assuming UK region: {region}", file=sys.stderr)
        return "uk"
    
    def process_single_request(self, request_data: PolicyRequest) -> RequestResult:
        """
        Process a single policy request.
        
        Args:
            request_data: Configuration for the request
            
        Returns:
            Complete result with request, response, and timing data
        """
        # Extract parameters from request data with defaults
        region = request_data.get("region", "us")
        time_period = request_data.get("timePeriod")
        reform_id = request_data.get("reform")
        baseline_id = request_data.get("baseline")
        dataset = request_data.get("dataset", None)
        max_households = request_data.get("maxHouseholds")
        household_id = request_data.get("household", None)
        mode = request_data.get("mode", None)
        
        # Handle case where reform_id is missing (use baseline as reform)
        if not reform_id:
            reform_id = baseline_id
        
        # Build the request URL
        url = self.create_url(
            country_id=self._get_country_id(region),
            reform_id=reform_id,
            baseline_id=baseline_id,
            region=region,
            time_period=time_period,
            dataset=dataset,
            max_households=max_households,
            household=household_id,
            mode=mode
        )

        print(f"Processing request: {url}", file=sys.stderr)
        
        # Track timing and execute request
        start_time = time.time()
        
        try:
            response = self.poll_until_complete(url)
        except APIError as error:
            logger.error(f"Failed to process request: {error}")
            response = {"status": "error", "message": str(error)}
            
        elapsed_time = time.time() - start_time
        
        return {
            "request": request_data,
            "response": response,
            "elapsed_time": elapsed_time
        }
    
    def process_request_batch(self, requests_data: List[PolicyRequest]) -> List[RequestResult]:
        """
        Process a batch of API requests with appropriate pacing.
        
        Args:
            requests_data: List of request configurations
            
        Returns:
            List of results for each request
        """
        results = []
        total_requests = len(requests_data)
        
        for index, request_data in enumerate(requests_data):
            current_position = index + 1
            logger.info(f"Processing request {current_position}/{total_requests}")
            
            # Process the request
            result = self.process_single_request(request_data)
            results.append(result)
            
            # Determine if we should pause
            is_batch_complete = current_position % self.batch_config.size == 0
            has_more_requests = current_position < total_requests
            
            if is_batch_complete and has_more_requests:
                pause_duration = self.batch_config.pause_seconds
                logger.info(f"Completed batch of {self.batch_config.size} requests. "
                           f"Pausing for {pause_duration} seconds before continuing.")
                time.sleep(pause_duration)
            elif has_more_requests:
                # Small pause between individual requests
                time.sleep(1)
                
        return results


def load_requests(file_path: str) -> List[PolicyRequest]:
    """
    Load request configurations from a JSON file.
    
    Args:
        file_path: Path to the JSON file
        
    Returns:
        List of request configurations
        
    Raises:
        FileNotFoundError: If the input file doesn't exist
        json.JSONDecodeError: If the file contains invalid JSON
    """
    file_path_obj = Path(file_path)
    
    if not file_path_obj.exists():
        raise FileNotFoundError(f"Input file not found: {file_path}")
    
    with open(file_path_obj, 'r', encoding='utf-8') as file:
        requests_data = json.load(file)
        
    if not isinstance(requests_data, list):
        raise ValueError("Expected a JSON array of request objects")
        
    return requests_data

def generate_unique_filename(base_filename: str) -> str:
    """
    Generate a unique filename by appending a timestamp.
    
    Args:
        base_filename: Base filename to append the unique identifier to
        
    Returns:
        Unique filename with timestamp
    """
    # Split the filename into name and extension
    file_path = Path(base_filename)
    file_stem = file_path.stem
    file_extension = file_path.suffix
    
    # Generate timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Create new filename with timestamp
    new_filename = f"{file_stem}_{timestamp}{file_extension}"
    
    return new_filename


def save_results(results: List[RequestResult], file_path: str, folder: str) -> None:
    """
    Save request results to a JSON file.
    
    Args:
        results: List of request results
        file_path: Path where to save the output file
    """
    # Generate unique filename
    unique_file_path = generate_unique_filename(file_path)
    
    with open(f"{folder}/{unique_file_path}", 'w', encoding='utf-8') as file:
        json.dump(results, file, indent=2)
    
    logger.info(f"Results saved to {unique_file_path}")


def summarize_results(results: List[RequestResult]) -> None:
    """
    Print a summary of request results.
    
    Args:
        results: List of request results
    """
    total = len(results)
    successful = sum(1 for r in results if r["response"].get("status") != "error")
    average_time = sum(r["elapsed_time"] for r in results) / total if total else 0
    
    logger.info(f"Summary:")
    logger.info(f"  - Total requests: {total}")
    logger.info(f"  - Successful: {successful} ({successful/total*100:.1f}%)")
    logger.info(f"  - Failed: {total - successful}")
    logger.info(f"  - Average processing time: {average_time:.2f} seconds")


def main() -> None:
    """Execute the main program flow."""
    try:
        # Configuration
        input_file = "policy_requests.json"
        output_file = "policy_results.json"

        # Check if input file is specified as a command line argument
        if len(sys.argv) > 1:
            input_file = sys.argv[1]
            logger.info(f"Using command line specified input file: {input_file}")
        
        # Set up client with custom configurations
        client = PolicyEngineClient(
            base_url="https://api.policyengine.org",
            polling_config=PollingConfig(),
            batch_config=BatchConfig()
        )
        
        # Load requests
        logger.info(f"Loading requests from {input_file}")
        requests_data = load_requests(input_file)
        logger.info(f"Loaded {len(requests_data)} requests")
        
        # Process requests
        results = client.process_request_batch(requests_data)
        
        # Save and summarize results
        save_results(results, output_file, folder="regression_runs")
        summarize_results(results)
        
    except Exception as error:
        logger.exception(f"Program failed: {error}")
        raise


if __name__ == "__main__":
    main()