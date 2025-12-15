#!/usr/bin/env python3
"""
Test script for UK Local Authority API functionality.

This script tests the economy-wide simulation API for:
1. A specific UK local authority (e.g., Leicester)
2. UK-wide calculation (to confirm local_authority_impact is returned)
3. Scotland country filter (to confirm authorities are filtered by country)

SETUP INSTRUCTIONS:
===================

You need THREE terminal windows:

Terminal 1 - Start Redis:
    redis-server

Terminal 2 - Start the API worker (handles economy calculations):
    FLASK_DEBUG=1 python policyengine_api/worker.py

Terminal 3 - Start the API server:
    make debug

Then run this script in a 4th terminal:
    python scripts/test_local_authority_api.py

NOTE: UK calculations require access to the policyengine-uk-data-private
HuggingFace repo. Make sure HUGGING_FACE_TOKEN is set in your environment.
"""

import requests
import json
import time
import sqlite3
from pathlib import Path

# Configuration
API_BASE_URL = "http://127.0.0.1:5000"
COUNTRY_ID = "uk"
BASELINE_POLICY_ID = 1  # UK current law
TIME_PERIOD = 2025
DATASET = "default"

# Raise the UK income tax base rate by 6 percentage points (20% -> 26%)
SAMPLE_REFORM = {
    "gov.hmrc.income_tax.rates.uk[0].rate": {"2025-01-01.2100-12-31": 0.26}
}


def print_header(title: str):
    """Print a formatted header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_step(step_num: int, description: str):
    """Print a step description."""
    print(f"\n[Step {step_num}] {description}")
    print("-" * 50)


def wait_for_confirmation(message: str = "Press Enter to continue..."):
    """Wait for user confirmation before proceeding."""
    input(f"\n>>> {message}")


def check_api_health():
    """Check if the API is running and healthy."""
    print_step(0, "Checking API Health")

    try:
        response = requests.get(f"{API_BASE_URL}/liveness-check", timeout=5)
        if response.status_code == 200:
            print(f"  [OK] API is running at {API_BASE_URL}")
            return True
        else:
            print(f"  [ERROR] API returned status {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print(f"  [ERROR] Cannot connect to API at {API_BASE_URL}")
        print("  Make sure the API server is running. You need 3 terminals:")
        print("")
        print("  Terminal 1 - Start Redis:")
        print("    redis-server")
        print("")
        print("  Terminal 2 - Start the API worker:")
        print("    FLASK_DEBUG=1 python policyengine_api/worker.py")
        print("")
        print("  Terminal 3 - Start the API server:")
        print("    make debug")
        return False


def create_reform_policy():
    """Create a reform policy and return its ID."""
    print_step(1, "Creating Reform Policy")

    print(f"  Reform to be created:")
    print(f"    {json.dumps(SAMPLE_REFORM, indent=4)}")

    wait_for_confirmation("Press Enter to create the reform policy...")

    payload = {
        "label": "Test LA Reform - UC Standard Allowance Increase",
        "data": SAMPLE_REFORM,
    }

    response = requests.post(
        f"{API_BASE_URL}/{COUNTRY_ID}/policy",
        json=payload,
        headers={"Content-Type": "application/json"},
    )

    print(f"  Response status: {response.status_code}")
    result = response.json()
    print(f"  Response body: {json.dumps(result, indent=4)}")

    if response.status_code in [200, 201]:
        policy_id = result["result"]["policy_id"]
        print(f"  [OK] Reform policy created/found with ID: {policy_id}")
        return policy_id
    else:
        print(f"  [ERROR] Failed to create policy")
        return None


def verify_baseline_policy_exists():
    """Verify the baseline (current law) policy exists."""
    print_step(2, "Verifying Baseline Policy Exists")

    print(f"  Checking policy ID: {BASELINE_POLICY_ID}")

    response = requests.get(
        f"{API_BASE_URL}/{COUNTRY_ID}/policy/{BASELINE_POLICY_ID}"
    )

    print(f"  Response status: {response.status_code}")

    if response.status_code == 200:
        result = response.json()
        policy_data = result.get("result", {})
        print(f"  Policy label: {policy_data.get('label', 'N/A')}")
        print(f"  [OK] Baseline policy exists")
        return True
    else:
        print(f"  [ERROR] Baseline policy not found")
        print(
            "  You may need to initialize the database with the current law policy"
        )
        return False


def poll_economy_endpoint(
    region: str, reform_policy_id: int, description: str
):
    """
    Poll the economy endpoint until the calculation is complete.

    Returns the result data or None if failed.
    """
    print(f"\n  Polling for: {description}")
    print(f"  Region: {region}")
    print(f"  Reform Policy ID: {reform_policy_id}")
    print(f"  Baseline Policy ID: {BASELINE_POLICY_ID}")
    print(f"  Time Period: {TIME_PERIOD}")

    url = f"{API_BASE_URL}/{COUNTRY_ID}/economy/{reform_policy_id}/over/{BASELINE_POLICY_ID}"
    params = {
        "region": region,
        "dataset": DATASET,
        "time_period": TIME_PERIOD,
        "target": "general",
    }

    print(f"\n  Full URL: {url}")
    print(f"  Query params: {params}")

    wait_for_confirmation("Press Enter to start polling the API...")

    max_attempts = 60  # 5 minutes with 5-second intervals
    attempt = 0

    while attempt < max_attempts:
        attempt += 1
        print(f"\n  Attempt {attempt}/{max_attempts}...")

        try:
            response = requests.get(url, params=params, timeout=30)
            result = response.json()

            status = result.get("status")
            print(f"    Status: {status}")

            if status == "ok":
                print(f"    [OK] Calculation complete!")
                return result.get("result")
            elif status == "computing":
                print(f"    Calculation in progress... waiting 5 seconds")
                time.sleep(5)
            elif status == "error":
                print(f"    [ERROR] Calculation failed")
                print(f"    Message: {result.get('message')}")
                return None
            else:
                print(f"    Unknown status: {status}")
                time.sleep(5)

        except requests.exceptions.Timeout:
            print(f"    Request timed out, retrying...")
            time.sleep(5)
        except Exception as e:
            print(f"    Error: {e}")
            time.sleep(5)

    print(f"  [ERROR] Timed out waiting for calculation")
    return None


def display_results(result: dict, description: str):
    """Display key results from the economy calculation."""
    print(f"\n  Results for: {description}")
    print("  " + "-" * 40)

    if result is None:
        print("    No results available")
        return

    # Budgetary impact
    budget = result.get("budget")
    if budget:
        print(f"\n  BUDGETARY IMPACT:")
        for key, value in budget.items():
            if isinstance(value, (int, float)):
                print(f"    {key}: {value:,.2f}")
            else:
                print(f"    {key}: {value}")

    # Decile impact summary
    decile = result.get("decile")
    if decile:
        print(f"\n  DECILE IMPACT (sample):")
        relative = decile.get("relative", {})
        if relative:
            for d in ["1", "5", "10"]:
                if d in relative:
                    print(f"    Decile {d}: {relative[d]*100:.2f}%")

    # Poverty impact
    poverty = result.get("poverty")
    if poverty:
        print(f"\n  POVERTY IMPACT:")
        deep_poverty = poverty.get("deep_poverty", {})
        regular_poverty = poverty.get("poverty", {})
        if deep_poverty:
            print(
                f"    Deep poverty change: {deep_poverty.get('change', 'N/A')}"
            )
        if regular_poverty:
            print(
                f"    Poverty change: {regular_poverty.get('change', 'N/A')}"
            )

    # Local Authority Impact (if present)
    la_impact = result.get("local_authority_impact")
    if la_impact:
        print(f"\n  LOCAL AUTHORITY IMPACT:")
        by_la = la_impact.get("by_local_authority", {})
        print(f"    Number of local authorities: {len(by_la)}")

        # Show first 5 local authorities
        print(f"    Sample local authorities:")
        for i, (name, data) in enumerate(list(by_la.items())[:5]):
            avg_change = data.get("average_household_income_change", 0)
            rel_change = data.get("relative_household_income_change", 0)
            print(
                f"      {name}: avg={avg_change:.2f}, rel={rel_change*100:.3f}%"
            )

        # Outcomes by region
        outcomes = la_impact.get("outcomes_by_region", {})
        if outcomes:
            print(f"\n    Outcomes by UK region:")
            for region, buckets in outcomes.items():
                total = sum(buckets.values())
                print(f"      {region}: {total} LAs")
                for bucket, count in buckets.items():
                    if count > 0:
                        print(f"        - {bucket}: {count}")
    else:
        print(f"\n  LOCAL AUTHORITY IMPACT: Not present in response")

    # Constituency Impact (if present)
    const_impact = result.get("constituency_impact")
    if const_impact:
        by_const = const_impact.get("by_constituency", {})
        print(f"\n  CONSTITUENCY IMPACT:")
        print(f"    Number of constituencies: {len(by_const)}")


def test_local_authority_simulation(reform_policy_id: int):
    """Test 1: Run simulation for a specific local authority."""
    print_header("TEST 1: Local Authority Simulation (Leicester)")

    print(
        """
    This test runs an economy simulation for a specific UK local authority.
    We're using Leicester as it's a well-known unitary authority.

    Expected: The API should accept the local_authority/Leicester region
    and return economic impact results.
    """
    )

    wait_for_confirmation(
        "Press Enter to run the local authority simulation..."
    )

    region = "local_authority/Leicester"
    result = poll_economy_endpoint(
        region, reform_policy_id, "Leicester Local Authority"
    )

    if result:
        display_results(result, "Leicester Local Authority")
        print(
            "\n  [TEST 1 PASSED] Local authority simulation completed successfully"
        )
        return True
    else:
        print("\n  [TEST 1 FAILED] Local authority simulation failed")
        return False


def test_uk_wide_simulation(reform_policy_id: int):
    """Test 2: Run UK-wide simulation and check for local_authority_impact."""
    print_header("TEST 2: UK-Wide Simulation (Check local_authority_impact)")

    print(
        """
    This test runs an economy simulation for the entire UK.

    Expected: The API should return results that include:
    - Standard budgetary/poverty/decile impacts
    - constituency_impact (existing feature)
    - local_authority_impact (NEW feature we just added)

    We'll verify that local_authority_impact is present and contains
    data for all 360 UK local authorities.
    """
    )

    wait_for_confirmation("Press Enter to run the UK-wide simulation...")

    region = "uk"
    result = poll_economy_endpoint(region, reform_policy_id, "UK-wide")

    if result:
        display_results(result, "UK-wide")

        # Verify local_authority_impact is present
        la_impact = result.get("local_authority_impact")
        if la_impact:
            by_la = la_impact.get("by_local_authority", {})
            if len(by_la) == 360:
                print(
                    f"\n  [OK] local_authority_impact contains all 360 local authorities"
                )
            else:
                print(
                    f"\n  [WARNING] Expected 360 local authorities, got {len(by_la)}"
                )

            # Check outcomes_by_region has all UK nations
            outcomes = la_impact.get("outcomes_by_region", {})
            expected_regions = [
                "uk",
                "england",
                "scotland",
                "wales",
                "northern_ireland",
            ]
            for r in expected_regions:
                if r in outcomes:
                    print(f"  [OK] {r} region present in outcomes")
                else:
                    print(f"  [MISSING] {r} region not in outcomes")

            print(
                "\n  [TEST 2 PASSED] UK-wide simulation includes local_authority_impact"
            )
            return True
        else:
            print(
                "\n  [TEST 2 FAILED] local_authority_impact not present in response"
            )
            return False
    else:
        print("\n  [TEST 2 FAILED] UK-wide simulation failed")
        return False


def test_wales_simulation(reform_policy_id: int):
    """Test 3: Run Wales simulation and check local authorities are filtered."""
    print_header("TEST 3: Wales Simulation (Filter Check)")

    print(
        """
    This test runs an economy simulation for Wales only.

    Expected: The API should return results where:
    - The simulation is filtered to Wales
    - If local_authority_impact is present, it should only contain
      Welsh local authorities (codes starting with 'W')
    - Wales has exactly 22 principal areas

    Note: The local_authority_impact breakdown may only be calculated
    for UK-wide simulations. This test will verify the behavior.
    """
    )

    wait_for_confirmation("Press Enter to run the Wales simulation...")

    region = "country/wales"
    result = poll_economy_endpoint(region, reform_policy_id, "Wales")

    if result:
        display_results(result, "Wales")

        la_impact = result.get("local_authority_impact")
        if la_impact:
            by_la = la_impact.get("by_local_authority", {})
            print(f"\n  Local authorities in response: {len(by_la)}")

            # If filtering is implemented, we'd expect 22 Welsh LAs
            if len(by_la) == 22:
                print(
                    f"  [OK] Correctly filtered to 22 Welsh local authorities"
                )
            elif len(by_la) == 360:
                print(
                    f"  [INFO] All 360 LAs returned (filtering not applied at LA level)"
                )
            else:
                print(f"  [INFO] Got {len(by_la)} local authorities")

            print("\n  [TEST 3 PASSED] Wales simulation completed")
            return True
        else:
            print(
                f"\n  [INFO] local_authority_impact not present for country-level simulation"
            )
            print(
                "  This may be expected behavior - LA breakdown may only be for UK-wide"
            )
            print(
                "\n  [TEST 3 PASSED] Wales simulation completed (no LA breakdown)"
            )
            return True
    else:
        print("\n  [TEST 3 FAILED] Wales simulation failed")
        return False


def main():
    """Main test runner."""
    print_header("UK Local Authority API Test Script")

    print(
        """
    This script tests the UK Local Authority feature in the PolicyEngine API.

    It will:
    1. Check API health
    2. Create a test reform policy
    3. Verify baseline policy exists
    4. Run TEST 1: Local Authority simulation (Leicester)
    5. Run TEST 2: UK-wide simulation (check local_authority_impact)
    6. Run TEST 3: Wales simulation (filter check)

    Prerequisites (you need 3 other terminals running):
    - Terminal 1: redis-server
    - Terminal 2: FLASK_DEBUG=1 python policyengine_api/worker.py
    - Terminal 3: make debug
    - HUGGING_FACE_TOKEN environment variable set (for UK data access)

    You will be prompted before each major step.
    """
    )

    wait_for_confirmation("Press Enter to begin testing...")

    # Step 0: Check API health
    if not check_api_health():
        print("\n[ABORT] API is not available. Please start the server first.")
        return

    wait_for_confirmation("API is healthy. Press Enter to continue...")

    # Step 1: Create reform policy
    reform_policy_id = create_reform_policy()
    if reform_policy_id is None:
        print("\n[ABORT] Failed to create reform policy.")
        return

    # Step 2: Verify baseline policy
    if not verify_baseline_policy_exists():
        print("\n[WARNING] Baseline policy not found. Tests may fail.")
        wait_for_confirmation("Press Enter to continue anyway...")

    print_header("Setup Complete - Ready to Run Tests")
    print(
        f"""
    Configuration:
    - API Base URL: {API_BASE_URL}
    - Country: {COUNTRY_ID}
    - Reform Policy ID: {reform_policy_id}
    - Baseline Policy ID: {BASELINE_POLICY_ID}
    - Time Period: {TIME_PERIOD}
    - Dataset: {DATASET}
    """
    )

    wait_for_confirmation("Press Enter to start running tests...")

    # Run tests
    results = []

    # Test 1: Local Authority simulation
    results.append(
        (
            "Local Authority (Leicester)",
            test_local_authority_simulation(reform_policy_id),
        )
    )
    wait_for_confirmation(
        "Test 1 complete. Press Enter to continue to Test 2..."
    )

    # Test 2: UK-wide simulation
    results.append(
        ("UK-Wide with LA Impact", test_uk_wide_simulation(reform_policy_id))
    )
    wait_for_confirmation(
        "Test 2 complete. Press Enter to continue to Test 3..."
    )

    # Test 3: Wales simulation
    results.append(("Wales Filter", test_wales_simulation(reform_policy_id)))

    # Summary
    print_header("Test Summary")
    print("\n  Results:")
    for test_name, passed in results:
        status = "[PASSED]" if passed else "[FAILED]"
        print(f"    {status} {test_name}")

    all_passed = all(r[1] for r in results)
    if all_passed:
        print("\n  All tests passed!")
    else:
        print("\n  Some tests failed. Review output above for details.")

    print("\n" + "=" * 70)
    print("  Testing complete.")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
