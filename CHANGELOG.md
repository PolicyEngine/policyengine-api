# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), 
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.35.2] - 2026-02-26 15:44:39

### Changed

- Update PolicyEngine US to 1.587.1

## [3.35.1] - 2026-02-26 01:16:43

### Fixed

- Fixed deploy Dockerfile by replacing stale base Docker image (Python 3.10) with python:3.11 directly.

## [3.35.0] - 2026-02-24 17:31:20

### Added

- Added Python 3.14 support and dropped Python 3.10.

## [3.34.3] - 2026-02-24 15:24:21

### Fixed

- Fix intra-decile income change formula that doubled all percentage changes.

## [3.34.2] - 2026-02-16 16:12:14

### Changed

- Update PolicyEngine US to 1.562.3

## [3.34.1] - 2026-02-04 21:15:46

### Changed

- Update PolicyEngine US to 1.550.1

## [3.34.0] - 2026-02-04 00:34:28

### Added

- Add place-level region support for US Census places with format place/{STATE_ABBREV}-{PLACE_FIPS}

## [3.33.6] - 2026-02-03 15:31:31

### Changed

- Update PolicyEngine US to 1.550.0

## [3.33.5] - 2026-01-23 22:30:43

### Changed

- Update PolicyEngine US to 1.514.0

## [3.33.4] - 2026-01-23 19:02:50

### Added

- Ingredient metadata (policy IDs, process ID) to simulation API calls for improved Logfire tracing

## [3.33.3] - 2026-01-20 19:57:25

### Changed

- Updated model version alignment check to use Modal gateway instead of GCP and only verify US versions.

## [3.33.2] - 2026-01-20 19:27:06

## [3.33.1] - 2026-01-20 16:34:03

### Changed

- Update PolicyEngine US to 1.508.0

## [3.33.0] - 2026-01-15 06:55:58

### Changed

- Society-wide reports for the US nationwide now call district breakdown-enabled simulation API

## [3.32.0] - 2026-01-14 22:02:55

### Changed

- Enable Modal simulation API by default instead of GCP Workflows

## [3.31.1] - 2026-01-14 21:25:34

### Fixed

- Updated tests to expect Enhanced CPS dataset by default

## [3.31.0] - 2026-01-14 20:30:23

### Added

- Modal simulation API support alongside GCP Workflows for economy calculations
- SimulationAPIModal class for HTTP-based job submission and polling
- Factory function to select between GCP and Modal backends via USE_MODAL_SIMULATION_API env var
- Status constants for both GCP and Modal execution states
- Unit tests for Modal client, factory, and status handling

### Changed

- EconomyService now handles both GCP and Modal execution status values

## [3.30.4] - 2026-01-13 13:30:17

### Changed

- Update PolicyEngine US to 1.499.0

## [3.30.3] - 2026-01-06 17:11:08

### Changed

- Increase RAM back to 24 GB (matches deployment settings pre-Nov. 2025)

## [3.30.2] - 2025-12-23 20:08:56

### Changed

- Increased CPU and RAM to prevent frequent crashing.

## [3.30.1] - 2025-12-19 12:14:41

### Fixed

- Reduced memory to 8gb

## [3.30.0] - 2025-12-16 10:27:20

### Added

- Metadata for UK local authorities
- Calculation of UK local authority-level outputs

## [3.29.3] - 2025-12-11 11:59:27

### Added

- US congressional district metadata

### Changed

- US simulations use default datasets from .py
- Upgraded .py version to 0.7.0

## [3.29.2] - 2025-12-11 11:17:26

### Changed

- Update PolicyEngine US to 1.457.0

## [3.29.1] - 2025-12-11 10:42:05

## [3.29.0] - 2025-12-09 16:28:44

### Changed

- Set dataset to None for US state-level simulations in economy service

## [3.28.22] - 2025-12-08 11:26:45

### Changed

- Downgraded push action Python versions to 3.11 to fix faiss-cpu install error.
- Ensured deploy occurs after checking that API can run with updated model version.

## [3.28.21] - 2025-12-01 18:12:09

### Changed

- Update PolicyEngine US to 1.444.1

## [3.28.20] - 2025-11-25 20:03:04

### Changed

- Update PolicyEngine US to 1.441.0

## [3.28.19] - 2025-11-20 14:32:26

## [3.28.18] - 2025-11-20 14:01:58

### Changed

- Revert Python version to 3.11 in GitHub Actions workflow

## [3.28.17] - 2025-11-18 15:57:43

### Changed

- Update PolicyEngine US to 1.435.0

## [3.28.16] - 2025-11-14 21:43:16

### Added

- Handling for year values in report_output records

## [3.28.15] - 2025-11-12 00:20:18

### Changed

- Update PolicyEngine US to 1.432.8

## [3.28.14] - 2025-10-23 15:57:11

### Changed

- Update PolicyEngine US to 1.425.4

## [3.28.13] - 2025-10-20 14:24:28

### Changed

- Updated simulation table and PATCH endpoint to contain output structures present in report_outputs.

## [3.28.12] - 2025-10-19 22:42:32

### Changed

- Update PolicyEngine US to 1.423.0

## [3.28.11] - 2025-10-17 23:49:56

### Added

- Output storage for household simulation calculations in simulations table

## [3.28.10] - 2025-10-08 05:35:21

### Changed

- Make error_message optional within report service

## [3.28.9] - 2025-10-04 16:29:29

### Changed

- Update PolicyEngine US to 1.408.1

## [3.28.8] - 2025-10-03 01:58:54

### Changed

- Update PolicyEngine US to 1.407.4

## [3.28.7] - 2025-10-03 00:00:00

### Changed

- Use latest data version for UK automatically.

## [3.28.6] - 2025-10-01 21:42:27

### Changed

- Update PolicyEngine US to 1.407.3

## [3.28.5] - 2025-09-30 15:41:52

### Changed

- Fixed app.yaml timeout key

## [3.28.4] - 2025-09-30 15:00:06

### Changed

- Attempted to fix deployments using gunicorn preload option and modified readiness check timeouts

## [3.28.3] - 2025-09-29 15:14:52

### Changed

- Update PolicyEngine US to 1.407.0

## [3.28.2] - 2025-09-25 21:19:43

### Fixed

- Removed HF API calls.

## [3.28.1] - 2025-09-19 12:56:22

## [3.28.0] - 2025-09-13 19:43:47

### Added

- Simulation endpoints for creating and retrieving simulation metadata
- Report output endpoints for managing report data
- SimulationService and ReportOutputService classes
- {'Database schema': 'simulation table for policy + geography metadata'}
- {'Database schema': 'report_outputs table for storing report data'}

## [3.27.14] - 2025-09-11 15:06:14

### Added

- API setup Logging

### Changed

- Reverted app.yaml settings to previous values

## [3.27.13] - 2025-09-10 19:00:29

### Changed

- Increased check_interval_sec to be greater than timeout_sec in app.yaml

## [3.27.12] - 2025-09-10 12:27:27

### Changed

- Increase timeouts for each GCP readiness check and for all checks collectively.

## [3.27.11] - 2025-09-09 21:27:12

### Changed

- Update PolicyEngine US to 1.395.1

## [3.27.10] - 2025-09-09 13:42:03

### Changed

- Formatted tracer analysis service file to fix linting issue in main

## [3.27.9] - 2025-08-18 21:25:42

### Fixed

- UK economic impacts by setting version to latest.

## [3.27.8] - 2025-08-12 15:59:24

### Changed

- Update PolicyEngine US to 1.369.0

## [3.27.7] - 2025-08-07 16:18:14

### Changed

- Update PolicyEngine US to 1.366.2

## [3.27.6] - 2025-08-05 18:30:31

### Changed

- Bump policyengine-us to 1.360.0

## [3.27.5] - 2025-08-04 23:24:33

### Changed

- Refactored test_varying_your_earnings to better serve testing needs

## [3.27.4] - 2025-08-01 20:24:35

## [3.27.3] - 2025-07-26 02:50:40

### Changed

- Upgraded FRS to 2023-24 version

## [3.27.2] - 2025-07-24 13:55:59

### Changed

- Update PolicyEngine CANADA to 0.96.3

## [3.27.1] - 2025-07-24 00:59:55

### Added

- Added a version check for `policyengine_us` in `push.yml` to wait for the version to appear on PyPI before proceeding with the installation.

## [3.27.0] - 2025-07-23 19:24:16

### Fixed

- UK dataset updated.

## [3.26.5] - 2025-07-16 11:54:01

### Fixed

- UK package updated.

## [3.26.4] - 2025-07-10 04:19:05

### Changed

- Update PolicyEngine US to 1.337.0

## [3.26.3] - 2025-07-09 19:35:29

### Changed

- Update PolicyEngine US to 1.338.0

## [3.26.2] - 2025-07-03 04:01:12

### Changed

- Update PolicyEngine US to 1.334.0

## [3.26.1] - 2025-07-02 16:54:02

### Changed

- Update PolicyEngine US to 1.331.0

## [3.26.0] - 2025-07-01 18:50:15

### Changed

- Refactored get_economic_impacts function to improve modularity and maintainability
- Passed include_cliffs value to simulation API to enable cliff impacts

## [3.25.17] - 2025-06-30 16:43:08

### Changed

- Update PolicyEngine US to 1.327.2

## [3.25.16] - 2025-06-28 19:00:58

### Changed

- Increase API memory from 16GB to 24GB

## [3.25.15] - 2025-06-27 21:05:11

### Changed

- Increased GCP time to readiness threshold from 400 to 600 seconds.

## [3.25.14] - 2025-06-26 19:55:58

### Changed

- Update PolicyEngine US to 1.327.0

## [3.25.13] - 2025-06-25 15:29:48

### Changed

- Update PolicyEngine US to 1.323.0

## [3.25.12] - 2025-06-24 16:46:08

### Changed

- Passed include_cliffs value to simulation API to enable cliff impacts

## [3.25.11] - 2025-06-23 21:07:35

### Changed

- Update PolicyEngine US to 1.321.0

## [3.25.10] - 2025-06-23 18:58:27

### Changed

- Improved user profile test to pass unused user ID; in future, this test should be fully refactored.

## [3.25.9] - 2025-06-23 15:50:20

### Changed

- Modified simulation analysis InboundParameters schema to properly capture API output changes.
- Updated tests to reflect new schema.

## [3.25.8] - 2025-06-20 18:37:35

### Changed

- Update PolicyEngine US to 1.320.0

## [3.25.7] - 2025-06-19 20:52:10

### Changed

- Reupgraded to Claude-4 and instructed the AI only to explain policies without commentary or quotes.

## [3.25.6] - 2025-06-19 19:27:26

### Added

- test automatic git tag publish

## [3.25.5] - 2025-06-19 18:45:32

### Fixed

- Added functions and tests to handle invalid or incorrect input parameters.

## [3.25.4] - 2025-06-19 02:05:34

### Added

- Added `.env.example` file with all relevant environment variables and example values for local setup.
- Modified Makefile `install` target to auto-copy `.env.example` to `.env` if `.env` does not exist.

## [3.25.3] - 2025-06-12 16:32:30

### Fixed

- Incorrect variable usage in the UK package.

## [3.25.2] - 2025-06-12 12:17:52

### Fixed

- GCP specs made sensible.

## [3.25.1] - 2025-06-11 09:28:54

### Changed

- Update PolicyEngine UK to 2.32.0

## [3.25.0] - 2025-06-10 21:40:43

## [3.24.1] - 2025-06-10 17:34:58

### Changed

- Properly pass args to API v1 run method

## [3.24.0] - 2025-06-10 09:44:12

### Changed

- Simulations run off APIv2.

## [3.23.4] - 2025-06-09 23:13:23

### Added

- GitHub Actions workflow to prevent deployment if simulation API does not possess model version defined in full API

## [3.23.3] - 2025-06-09 11:47:54

### Changed

- Update PolicyEngine US to 1.309.0

## [3.23.2] - 2025-06-06 22:01:31

### Changed

- Update PolicyEngine US to 1.307.0

## [3.23.1] - 2025-06-06 15:47:51

### Fixed

- Reverted a previous PR.

## [3.23.0] - 2025-06-06 14:39:05

### Added

- GitHub Actions checks that full API and simulation API model versions are in sync

## [3.22.17] - 2025-06-05 21:59:22

### Fixed

- Bug with the 2023 CPS.

## [3.22.16] - 2025-06-04 20:50:25

### Changed

- Improved logging within API

## [3.22.15] - 2025-06-04 11:53:20

### Fixed

- Pass country and data versions to APIv2.

## [3.22.14] - 2025-06-03 23:18:58

### Fixed

- V2 comparisons.

## [3.22.13] - 2025-06-03 21:22:08

### Changed

- Update PolicyEngine US to 1.302.0

## [3.22.12] - 2025-06-03 11:25:31

### Added

- Bash script to check for model versions within simulation API; not yet integrated into GitHub Actions.

## [3.22.11] - 2025-05-30 22:26:39

### Changed

- Update PolicyEngine US to 1.300.0

## [3.22.10] - 2025-05-30 18:59:49

### Changed

- Update PolicyEngine US to 1.299.1

## [3.22.9] - 2025-05-30 13:23:29

### Changed

- Update PolicyEngine US to 1.298.0

## [3.22.8] - 2025-05-28 22:05:53

### Changed

- Temporarily downgraded Claude to 3.5 Sonnet.

## [3.22.7] - 2025-05-28 11:04:12

### Changed

- Update PolicyEngine UK to 2.28.2

## [3.22.6] - 2025-05-27 17:45:02

### Changed

- Update the claude version

## [3.22.5] - 2025-05-27 13:54:11

### Changed

- Update PolicyEngine UK to 2.28.1

## [3.22.4] - 2025-05-27 07:09:00

### Changed

- Created test_create_profile.py to test the create_profile function.

## [3.22.3] - 2025-05-22 21:13:24

### Changed

- Update PolicyEngine US to 1.289.1

## [3.22.2] - 2025-05-22 17:52:59

### Changed

- Update PolicyEngine US to 1.289.0

## [3.22.1] - 2025-05-22 13:10:29

### Changed

- Update PolicyEngine US to 1.288.0

## [3.22.0] - 2025-05-20 21:23:24

## [3.21.1] - 2025-05-20 16:17:08

### Changed

- Update PolicyEngine US to 1.287.0

## [3.21.0] - 2025-05-17 21:06:43

### Added

- test_update_profile.py to test for update_profile method under user_service.py

## [3.20.8] - 2025-05-15 00:51:20

### Fixed

- Logging uses GCP client.

## [3.20.7] - 2025-05-14 16:21:06

### Added

- Semi-structured logging for API v1 failures

### Changed

- Updated .py version

## [3.20.6] - 2025-05-14 13:43:57

### Changed

- Update PolicyEngine US to 1.282.1

## [3.20.5] - 2025-05-13 22:05:50

### Added

- API v1 and v2 country package version data to GCP logging

## [3.20.4] - 2025-05-13 21:27:23

### Changed

- Update PolicyEngine US to 1.281.0

## [3.20.3] - 2025-05-13 18:38:59

### Changed

- Update PolicyEngine US to 1.280.1

## [3.20.2] - 2025-05-13 11:31:09

### Changed

- Update PolicyEngine US to 1.276.0

## [3.20.1] - 2025-05-12 21:16:29

### Changed

- Update PolicyEngine US to 1.272.0

## [3.20.0] - 2025-05-12 07:52:21

### Added

- New logging structure
- New logging outputs for simulation API v1 and v2 runs

### Changed

- Rolled back to simulation API v1

## [3.19.5] - 2025-05-11 20:36:16

### Changed

- Update PolicyEngine US to 1.270.0

## [3.19.4] - 2025-05-09 10:45:43

### Added

- Added setup method for simulation API config dict
- Added methods to convert API v1 to simulation API config items

## [3.19.3] - 2025-05-08 19:59:28

### Changed

- Update PolicyEngine US to 1.269.0

## [3.19.2] - 2025-05-08 14:17:36

### Changed

- Update PolicyEngine UK to 2.24.2

## [3.19.1] - 2025-05-07 14:44:52

### Changed

- Update PolicyEngine US to 1.265.3

## [3.19.0] - 2025-05-06 23:37:50

### Added

- Refactored tests for set_policy_service

## [3.18.4] - 2025-05-05 15:50:32

### Fixed

- github deploy actions can no longer run concurrently.

## [3.18.3] - 2025-05-01 20:51:56

### Changed

- Update PolicyEngine US to 1.265.0

## [3.18.2] - 2025-05-01 14:14:52

### Added

- Utah state tax reform test.

## [3.18.1] - 2025-04-29 14:04:30

## [3.18.0] - 2025-04-25 14:34:39

### Changed

- Economic impacts from APIv1 to APIv2

## [3.17.6] - 2025-04-25 11:21:26

### Changed

- Update PolicyEngine UK to 2.24.0

## [3.17.5] - 2025-04-22 21:04:05

### Added

- Created .coveragerc file created to exclude test files from the coverage report

## [3.17.4] - 2025-04-22 14:46:15

### Changed

- Update PolicyEngine US to 1.254.0

## [3.17.3] - 2025-04-19 00:54:32

### Changed

- File formating and related import tags

## [3.17.2] - 2025-04-17 18:46:34

### Changed

- Re-pinned policyengine-core version to 3.16.6

## [3.17.1] - 2025-04-16 18:49:28

### Changed

- Fixed tracer parsing function. It was not properly handling variables whose names are substrings of other variables.

## [3.17.0] - 2025-04-16 18:29:11

### Added

- Tests for execute_analysis function

## [3.16.6] - 2025-04-16 12:35:21

### Added

- Ability to return APIv2 results.

## [3.16.5] - 2025-04-14 20:46:17

### Changed

- Extended Google Cloud build timeout to 40 minutes

## [3.16.4] - 2025-04-14 08:57:48

### Changed

- Update PolicyEngine US to 1.250.0

## [3.16.3] - 2025-04-11 14:27:31

### Fixed

- Comparison to APIv2 correctly compares 0s.

## [3.16.2] - 2025-04-09 10:57:06

### Fixed

- Allowed for None/{} comparisons (v1/v2).

## [3.16.1] - 2025-04-08 08:13:39

### Changed

- Update PolicyEngine US to 1.247.0

## [3.16.0] - 2025-04-08 08:08:47

### Changed

- Handle economy simulations in the Simulation API.

## [3.15.7] - 2025-04-06 16:12:40

### Changed

- Update PolicyEngine US to 1.245.0

## [3.15.6] - 2025-04-03 17:25:33

### Changed

- Update PolicyEngine US to 1.240.5

## [3.15.5] - 2025-04-03 13:02:55

### Changed

- Update PolicyEngine UK to 2.22.8

## [3.15.4] - 2025-04-02 22:48:13

### Changed

- Corrected readiness check path in app.yaml
- Lowered readiness check timeout threshold

## [3.15.3] - 2025-04-02 16:20:27

### Changed

- Deployment readiness check timeout to 1000s.

## [3.15.2] - 2025-04-02 08:24:52

### Changed

- Update PolicyEngine US to 1.240.1

## [3.15.1] - 2025-04-01 22:52:34

### Changed

- Extended the readiness check value in GCP

## [3.15.0] - 2025-04-01 16:06:09

### Changed

- US and UK year impacts extended by 1.

## [3.14.8] - 2025-03-27 01:52:01

### Added

- Created test cases for get_profile() in user_service.py

## [3.14.7] - 2025-03-27 01:47:18

### Changed

- Fixed bug in parse_tracer_output method that incorrectly returned empty tracer due to bad regex matching
- Updated the test fixtures to align with production tracer structure
- Modified the test module for parse_tracer_output target method

## [3.14.6] - 2025-03-26 18:11:12

### Changed

- Update PolicyEngine UK to 2.22.6

## [3.14.5] - 2025-03-26 15:05:55

### Changed

- Update PolicyEngine UK to 2.22.5

## [3.14.4] - 2025-03-26 14:54:48

### Changed

- Update PolicyEngine US to 1.230.0

## [3.14.3] - 2025-03-26 10:11:36

### Changed

- Update PolicyEngine UK to 2.22.4

## [3.14.2] - 2025-03-24 14:33:27

### Changed

- Update PolicyEngine US to 1.226.0

## [3.14.1] - 2025-03-24 08:21:01

### Changed

- Update PolicyEngine UK to 2.22.2

## [3.14.0] - 2025-03-21 06:46:14

### Added

- new test module for tracer_analysis_service.parse_tracer_output funtion
- fixture file for testing module

### Changed

- tracer_analysis_service.parse_tracer_output to perform input validation
- tracer_analysis_service.parse_tracer_output to fix suffixed-variable false-positive issue

## [3.13.4] - 2025-03-21 06:37:42

### Fixed

- fixed the issue in test_metadata_service

## [3.13.3] - 2025-03-21 06:34:34

### Changed

- TestGetTracer updated the file name and resolved issues
- tracer_fixture_service added new file structure for fitures

## [3.13.2] - 2025-03-19 21:12:15

### Changed

- Update PolicyEngine UK to 2.22.1

## [3.13.1] - 2025-03-17 10:50:56

### Changed

- Update PolicyEngine US to 1.214.0

## [3.13.0] - 2025-03-15 00:31:52

### Added

- Refactored test for get policy service
- Refactored tests for get get_policy_json

## [3.12.12] - 2025-03-14 01:07:33

### Changed

- Update PolicyEngine US to 1.213.1

## [3.12.11] - 2025-03-11 13:49:35

### Changed

- Update PolicyEngine US to 1.209.1

## [3.12.10] - 2025-03-10 12:55:10

### Changed

- Update PolicyEngine US to 1.208.0

## [3.12.9] - 2025-03-05 15:56:31

### Changed

- Update PolicyEngine US to 1.207.0

## [3.12.8] - 2025-03-04 20:47:07

### Added

- Error handling for Claude streaming error messages

### Changed

- Modified how Claude streaming messages are handled

## [3.12.7] - 2025-03-04 07:00:56

### Changed

- Update PolicyEngine US to 1.205.0

## [3.12.6] - 2025-03-03 12:31:18

### Changed

- Update PolicyEngine UK to 2.22.0

## [3.12.5] - 2025-03-01 15:43:36

### Changed

- Update PolicyEngine US to 1.204.0

## [3.12.4] - 2025-02-28 20:59:57

### Changed

- Altered UK constituency data addresses to use new public Hugging Face model

## [3.12.3] - 2025-02-28 15:58:06

### Changed

- Update PolicyEngine UK to 2.20.0

## [3.12.2] - 2025-02-28 14:31:14

### Changed

- Update PolicyEngine US to 1.203.1

## [3.12.1] - 2025-02-28 01:35:52

## [3.12.0] - 2025-02-28 00:53:50

### Added

- Created tests to confirm that expiring environment variables are still valid

## [3.11.11] - 2025-02-25 21:08:59

### Fixed

- Allowed for None values in UK constituency impact outputs

## [3.11.10] - 2025-02-25 16:34:23

### Changed

- Update PolicyEngine UK to 2.19.3

## [3.11.9] - 2025-02-25 15:02:53

### Changed

- PolicyEngine UK updated to 2.19.2.

## [3.11.8] - 2025-02-25 13:53:21

### Added

- Unit tests for UK country filter functionality with constituencies

### Fixed

- Bug causing UK country filters to fail with constituency outputs

## [3.11.7] - 2025-02-24 23:54:23

### Changed

- Update PolicyEngine US to 1.202.2

## [3.11.6] - 2025-02-24 18:12:13

### Fixed

- Bug causing some scale parameters to not change.

## [3.11.5] - 2025-02-24 17:41:51

### Fixed

- Bug causing UK country filters to fail.

## [3.11.4] - 2025-02-24 15:28:19

### Changed

- Update PolicyEngine UK to 2.19.1

## [3.11.3] - 2025-02-24 15:07:16

### Changed

- Update PolicyEngine US to 1.202.1

## [3.11.2] - 2025-02-24 11:42:02

### Fixed

- Constituency data returns in dictionary form, not `BaseModel`.

## [3.11.1] - 2025-02-22 07:47:21

### Changed

- Update PolicyEngine US to 1.202.0

## [3.11.0] - 2025-02-21 19:09:17

### Added

- UK parliamentary constituency outputs.

## [3.10.6] - 2025-02-21 17:41:01

### Changed

- Monkeypatched local_database
- Refactored fixtures folder to make clearer which are valid and which need refactoring

## [3.10.5] - 2025-02-20 16:27:59

### Changed

- Update PolicyEngine US to 1.201.0

## [3.10.4] - 2025-02-20 13:52:58

### Changed

- Update PolicyEngine US to 1.200.1

## [3.10.3] - 2025-02-20 11:43:20

### Changed

- Update PolicyEngine US to 1.200.0

## [3.10.2] - 2025-02-18 02:14:08

### Changed

- Update PolicyEngine US to 1.197.0

## [3.10.1] - 2025-02-14 21:29:29

### Changed

- Update PolicyEngine US to 1.196.1

## [3.10.0] - 2025-02-14 00:49:17

### Added

- AI prompt template file for society-wide simulation analyses

### Changed

- AIAnalysisService to return JSON instead of streaming outputs when analysis already exists inside db
- SimulationAnalysisService and TracerAnalysisService to injest these changes

## [3.9.9] - 2025-02-13 01:32:46

### Changed

- Update PolicyEngine US to 1.195.0

## [3.9.8] - 2025-02-13 00:33:29

### Changed

- Temporarily patched errors in state-level ECPS decile data

## [3.9.7] - 2025-02-11 00:48:37

### Changed

- checkout action from v3 to v4 and setup-gcloud from v1 to v2

## [3.9.6] - 2025-02-06 21:26:46

### Changed

- Refactored test files
- Created example unit tests for household service

## [3.9.5] - 2025-02-05 13:57:53

### Changed

- Update PolicyEngine US to 1.187.2

## [3.9.4] - 2025-02-04 19:00:10

### Changed

- Update PolicyEngine US to 1.187.1

## [3.9.3] - 2025-02-04 18:04:16

### Added

- conftest.py configuration file for tests folder

## [3.9.2] - 2025-02-04 16:30:08

### Added

- added test coverage report generation

## [3.9.1] - 2025-02-03 22:36:12

### Changed

- Update PolicyEngine US to 1.187.0

## [3.9.0] - 2025-01-31 00:38:45

### Changed

- Refactored policy endpoints to use new API structure

## [3.8.6] - 2025-01-29 20:20:31

### Changed

- metadata_route to add status and message values to the response object

## [3.8.5] - 2025-01-29 16:27:23

### Changed

- Update PolicyEngine US to 1.183.1

## [3.8.4] - 2025-01-28 16:27:35

### Changed

- Update PolicyEngine US to 1.182.2

## [3.8.3] - 2025-01-27 13:56:08

### Changed

- Update PolicyEngine US to 1.182.0

## [3.8.2] - 2025-01-24 17:17:11

### Changed

- Update PolicyEngine US to 1.181.0

## [3.8.1] - 2025-01-22 10:58:53

### Changed

- Update PolicyEngine US to 1.180.1

## [3.8.0] - 2025-01-22 05:11:18

### Added

- Pointing the API directly to HuggingFace data downloads.

## [3.7.14] - 2025-01-22 04:35:25

### Changed

- Update PolicyEngine US to 1.180.0

## [3.7.13] - 2025-01-19 15:40:18

### Changed

- Update PolicyEngine US to 1.176.2

## [3.7.12] - 2025-01-17 19:26:30

### Changed

- Update PolicyEngine US to 1.176.1

## [3.7.11] - 2025-01-17 13:53:42

### Changed

- Described method to run worker in debug mode

## [3.7.10] - 2025-01-13 15:57:57

### Changed

- Update PolicyEngine US to 1.172.0

## [3.7.9] - 2025-01-08 02:04:21

### Changed

- Updated PolicyEngine US to 1.168.1.

## [3.7.8] - 2025-01-06 16:09:37

### Changed

- Update PolicyEngine US to 1.168.0

## [3.7.7] - 2025-01-04 00:04:43

## [3.7.6] - 2025-01-03 21:14:38

### Changed

- Update PolicyEngine US to 1.167.1

## [3.7.5] - 2025-01-03 16:14:56

### Changed

- updated the user_profile endpoints to use blueprints instead of endpoints.

### Fixed

- updated the user profile endpoint to resist injection attacks on update.

## [3.7.4] - 2024-12-28 03:54:13

### Changed

- Update PolicyEngine US to 1.167.0

## [3.7.3] - 2024-12-27 22:12:01

### Changed

- Update PolicyEngine US to 1.166.0

## [3.7.2] - 2024-12-24 21:57:10

### Changed

- Update PolicyEngine US to 1.164.0

## [3.7.1] - 2024-12-23 15:51:28

### Fixed

- Refactored metadata endpoint to remove improperly nested result JSON

## [3.7.0] - 2024-12-20 19:36:36

### Changed

- Refactored household endpoints to match new API structure

## [3.6.10] - 2024-12-18 02:59:52

### Changed

- Update PolicyEngine US to 1.162.0

## [3.6.9] - 2024-12-16 16:24:53

### Changed

- Update PolicyEngine US to 1.161.2

## [3.6.8] - 2024-12-14 00:02:24

### Changed

- Update PolicyEngine US to 1.161.1

## [3.6.7] - 2024-12-09 19:29:15

### Changed

- /<country_id>/metadata is now implemented via a blueprint/service instead of endpoint.

## [3.6.6] - 2024-12-05 17:15:35

### Changed

- Update PolicyEngine US to 1.160.0

## [3.6.5] - 2024-12-05 11:49:53

### Changed

- Update PolicyEngine UK to 2.17.0

## [3.6.4] - 2024-12-04 22:11:05

### Added

- Hugging Face connection token to CI/CD scripts and Docker image build script

## [3.6.3] - 2024-12-04 15:35:00

### Changed

- Update PolicyEngine CANADA to 0.96.2

## [3.6.2] - 2024-12-02 18:02:15

### Changed

- Update PolicyEngine US to 1.154.1

## [3.6.1] - 2024-11-29 09:19:35

### Changed

- Update PolicyEngine UK to 2.16.0

## [3.6.0] - 2024-11-27 20:25:17

### Added

- dataset descriptor to various endpoints and controllers enabling enhanced CPS runs for any specified region

## [3.5.1] - 2024-11-26 15:59:05

### Changed

- Update PolicyEngine US to 1.153.0

## [3.5.0] - 2024-11-25 21:55:51

### Added

- Testing for simulation payload validators

### Changed

- Refactored AI endpoints to match new routes/services/jobs architecture
- Disabled default buffering on App Engine deployments for AI endpoints
- Updated relevant tests

## [3.4.0] - 2024-11-25 10:39:19

### Fixed

- Bug causing UK impacts to crash.

## [3.3.3] - 2024-11-23 00:21:18

### Changed

- validate_country to decorator for validation on applicable functions

## [3.3.2] - 2024-11-21 13:05:23

## [3.3.1] - 2024-11-21 04:05:52

### Changed

- Update PolicyEngine US to 1.150.0

## [3.3.0] - 2024-11-19 23:12:23

### Changed

- Refactored country agnostic code to use American English, changed "labour" to "labor"

## [3.2.1] - 2024-11-19 13:24:01

### Changed

- Update PolicyEngine UK to 2.15.1

## [3.2.0] - 2024-11-19 10:06:07

### Changed

- Refactored routes to use Flask Blueprint
- Refactored economy-wide simulations to operate as distinct services
- Moved worker-driven code to jobs, which inherit from new BaseJob class

### Fixed

- Cliff impact calculations

## [3.1.2] - 2024-11-18 11:35:27

### Changed

- Update PolicyEngine US to 1.144.0

## [3.1.1] - 2024-11-11 00:46:00

### Changed

- Modified GCP shell script to drop Bash-specific for loop

## [3.1.0] - 2024-11-11 00:03:47

## [3.0.0] - 2024-11-08 23:46:57

### Changed

- Renamed endpoints containing underscores (user_policy, user_profile, liveness_check & readiness_check) to use hyphens; updated tests

## [2.3.4] - 2024-11-08 23:37:42

### Fixed

- removed redundant route declaration for GET /simulation.

## [2.3.3] - 2024-11-06 19:03:55

### Fixed

- Removed simulation chunking.

## [2.3.2] - 2024-11-05 14:49:05

### Changed

- Update PolicyEngine UK to 2.15.1

## [2.3.1] - 2024-11-05 13:14:41

### Fixed

- Use cloud database for policy.
- Error logs now show again.

## [2.3.0] - 2024-11-05 11:45:05

### Added

- Chunking and baseline/reform parallelisation.

## [2.2.25] - 2024-11-04 12:49:27

### Changed

- Update PolicyEngine US to 1.137.4

## [2.2.24] - 2024-11-01 22:30:37

### Changed

- Update PolicyEngine US to 1.137.3

## [2.2.23] - 2024-11-01 16:08:29

### Changed

- Update PolicyEngine US to 1.137.2

## [2.2.22] - 2024-10-30 17:42:00

### Changed

- Update PolicyEngine UK to 2.15.0

## [2.2.21] - 2024-10-30 15:12:57

### Changed

- Update PolicyEngine UK to 2.14.1

## [2.2.20] - 2024-10-30 14:26:09

### Changed

- Update PolicyEngine UK to 2.14.1

## [2.2.19] - 2024-10-30 10:21:34

### Changed

- Update PolicyEngine US to 1.136.2

## [2.2.18] - 2024-10-29 20:15:07

### Changed

- Update PolicyEngine US to 1.136.1

## [2.2.17] - 2024-10-29 19:34:26

### Changed

- Changed to use google-github-actions/auth instead of service_account_key

## [2.2.16] - 2024-10-29 14:11:39

### Changed

- Update PolicyEngine US to 1.136.0

## [2.2.15] - 2024-10-28 20:53:09

### Changed

- Re-enable Python 3.11

## [2.2.14] - 2024-10-28 17:15:17

### Changed

- Revert previous db change; don't use local db in production

## [2.2.13] - 2024-10-28 12:30:34

### Changed

- Update PolicyEngine UK to 2.14.0

## [2.2.12] - 2024-10-28 11:12:07

### Changed

- Update PolicyEngine UK to 2.13.2

## [2.2.11] - 2024-10-27 23:51:34

### Changed

- Upgraded to Python 3.11

## [2.2.10] - 2024-10-27 23:23:00

### Changed

- Update PolicyEngine US to 1.133.0

## [2.2.9] - 2024-10-24 14:17:22

### Changed

- Update PolicyEngine UK to 2.13.1

## [2.2.8] - 2024-10-24 11:15:09

### Changed

- Update PolicyEngine UK to 2.13.0

## [2.2.7] - 2024-10-24 09:13:10

### Changed

- Update PolicyEngine US to 1.132.0

## [2.2.6] - 2024-10-23 14:19:11

### Changed

- Update PolicyEngine UK to 2.12.0

## [2.2.5] - 2024-10-23 09:44:58

### Changed

- Update PolicyEngine UK to 2.11.0

## [2.2.4] - 2024-10-22 10:47:25

### Changed

- Update PolicyEngine UK to 2.10.0

## [2.2.3] - 2024-10-22 08:50:29

### Changed

- Update PolicyEngine UK to 2.9.0

## [2.2.2] - 2024-10-21 20:57:52

### Changed

- Update PolicyEngine US to 1.129.3

## [2.2.1] - 2024-10-21 12:55:19

### Changed

- Update PolicyEngine UK to 2.8.0

## [2.2.0] - 2024-10-21 11:00:46

### Changed

- PolicyEngine UK bumped to 2.7.0.
- Government revenue in the UK switch to include employer NI.

## [2.1.6] - 2024-10-19 19:47:44

### Changed

- Update PolicyEngine UK to 2.6.0

## [2.1.5] - 2024-10-17 22:19:45

### Changed

- Update PolicyEngine UK to 2.4.0

## [2.1.4] - 2024-10-17 16:01:24

### Changed

- Changed infinite value representation from ".inf" to "Infinity"

## [2.1.3] - 2024-10-17 10:27:41

### Changed

- Update PolicyEngine UK to 2.3.0

## [2.1.2] - 2024-10-16 13:24:12

### Changed

- Update PolicyEngine UK to 2.2.0

## [2.1.1] - 2024-10-15 20:03:02

### Changed

- Update PolicyEngine US to 1.127.0

## [2.1.0] - 2024-10-15 18:59:24

### Added

- added fix to return correct status codes for no policies found in get_policy_search endpoint

## [2.0.5] - 2024-10-15 12:57:00

### Changed

- Update PolicyEngine UK to 2.1.1

## [2.0.4] - 2024-10-14 20:59:49

### Changed

- Change wording for ELI5 prompt in microsimulation ai analysis

## [2.0.3] - 2024-10-14 19:47:55

### Changed

- Update PolicyEngine US to 1.117.0

## [2.0.2] - 2024-10-11 14:48:23

### Added

- Test to prevent errors when running multiple simulations with neutralized variables

## [2.0.1] - 2024-10-10 20:38:28

### Changed

- Explicitly use stream_with_context in execute_tracer_analysis

## [2.0.0] - 2024-10-09 19:44:08

### Added

- /tracer_analysis endpoint for household tracer outputs
- Database for simulation tracer outputs

### Changed

- /analysis endpoint renamed to /simulation_analysis endpoint
- Simulation runs now write tracer output to database
- Simulation analysis runs now return ReadableStreams
- Refactored Claude interaction code to be decoupled from endpoints

## [1.34.2] - 2024-10-09 15:29:57

### Changed

- Update PolicyEngine US to 1.115.0

## [1.34.1] - 2024-10-09 11:25:27

### Changed

- Update PolicyEngine US to 1.114.0

## [1.34.0] - 2024-10-07 22:02:30

## [1.33.3] - 2024-10-07 21:44:10

## [1.33.2] - 2024-10-07 14:44:40

### Changed

- Update PolicyEngine US to 1.110.0

## [1.33.1] - 2024-09-30 09:52:58

### Changed

- Update PolicyEngine US to 1.103.0

## [1.33.0] - 2024-09-26 14:37:28

## [1.32.0] - 2024-09-26 00:02:30

### Changed

- {'README.md': 'Updated instructions for branch creation'}

## [1.31.1] - 2024-09-25 18:11:37

### Changed

- Update PolicyEngine US to 1.93.0

## [1.31.0] - 2024-09-25 16:43:29

### Added

- Improvements to status reporting, with a new /simulations endpoint.

## [1.30.1] - 2024-09-24 20:28:50

### Added

- Tests based upon Oregon Rebate (Measure 118)

## [1.30.0] - 2024-09-24 09:28:47

### Added

- True subsetting for regional breakdowns.

## [1.29.1] - 2024-09-23 15:13:17

### Changed

- Update PolicyEngine US to 1.89.0

## [1.29.0] - 2024-09-20 22:22:39

### Added

- Added check for invalid country in get_analysis endpoint

## [1.28.6] - 2024-09-19 18:09:32

### Changed

- Update PolicyEngine US to 1.85.3

## [1.28.5] - 2024-09-18 19:59:30

### Changed

- Update PolicyEngine UK to 2.1.1

## [1.28.4] - 2024-09-18 18:48:27

### Changed

- Update PolicyEngine US to 1.81.0

## [1.28.3] - 2024-09-17 04:49:37

### Changed

- Update PolicyEngine US to 1.80.0

## [1.28.2] - 2024-09-14 20:28:44

### Changed

- Use the 2024 CPS in the compute_economy function.

## [1.28.1] - 2024-09-14 18:37:15

### Changed

- Update PolicyEngine US to 1.79.1

## [1.28.0] - 2024-09-05 18:33:24

### Changed

- {'README.md': 'Updated instructions for local testing and API configuration'}

## [1.27.15] - 2024-09-04 00:13:14

### Changed

- Update PolicyEngine US to 1.71.1
- Update PolicyEngine Canada to 0.96.1
- Update PolicyEngine UK to 1.7.3
- Remove explicit PolicyEngine Core dependency, since it is in country packages.

## [1.27.14] - 2024-09-01 18:31:57

### Changed

- Update PolicyEngine US to 1.68.0

## [1.27.13] - 2024-08-31 19:25:41

### Changed

- Update PolicyEngine US to 1.67.0

## [1.27.12] - 2024-08-31 17:17:01

### Changed

- Filter negative income deciles out of decile_impact and wealth_decile_impact prior to calculating

## [1.27.11] - 2024-08-27 00:28:45

### Changed

- Update PolicyEngine US to 1.63.0

## [1.27.10] - 2024-08-23 16:48:50

### Changed

- Update PolicyEngine US to 1.61.0

## [1.27.9] - 2024-08-22 20:58:54

### Changed

- Update PolicyEngine UK to 1.7.1

## [1.27.8] - 2024-08-21 15:34:17

### Changed

- Update PolicyEngine US to 1.57.1

## [1.27.7] - 2024-08-20 02:41:03

### Changed

- Update PolicyEngine US to 1.57.0

## [1.27.6] - 2024-08-19 19:01:34

### Changed

- Update PolicyEngine US to 1.56.1

## [1.27.5] - 2024-08-18 17:12:53

### Changed

- Update PolicyEngine US to 1.55.0

## [1.27.4] - 2024-08-17 23:06:11

### Changed

- Update PolicyEngine US to 1.54.3

## [1.27.3] - 2024-08-17 19:02:11

### Changed

- Update PolicyEngine US to 1.54.2

## [1.27.2] - 2024-08-17 17:11:21

### Changed

- Update PolicyEngine US to 1.54.1

## [1.27.1] - 2024-08-16 15:51:29

### Changed

- Update PolicyEngine US to 1.52.0

## [1.27.0] - 2024-08-16 13:08:46

### Added

- Expanded budgetary window to 10 years.

## [1.26.45] - 2024-08-16 12:01:13

### Changed

- Update PolicyEngine US to 1.51.1

## [1.26.44] - 2024-08-15 12:03:15

### Changed

- Update PolicyEngine UK to 1.7.0

## [1.26.43] - 2024-08-13 23:48:26

### Changed

- Increased max GCP instances to 2

## [1.26.42] - 2024-08-13 16:16:42

### Changed

- Update PolicyEngine US to 1.50.0

## [1.26.41] - 2024-08-12 16:47:46

### Changed

- Update PolicyEngine US to 1.47.0

## [1.26.40] - 2024-08-10 20:58:28

### Changed

- Update PolicyEngine US to 1.45.2

## [1.26.39] - 2024-08-10 11:47:40

### Changed

- Update PolicyEngine US to 1.45.1

## [1.26.38] - 2024-08-08 18:33:50

### Changed

- Update PolicyEngine US to 1.44.1

## [1.26.37] - 2024-08-06 17:47:19

### Changed

- Update PolicyEngine US to 1.42.1

## [1.26.36] - 2024-08-02 03:51:46

### Changed

- Update PolicyEngine US to 1.39.0

## [1.26.35] - 2024-08-01 20:18:44

### Fixed

- Updated README, fixed typo.

## [1.26.34] - 2024-08-01 15:54:44

### Changed

- Increased max_tokens in Claude AI summary to 1500

## [1.26.33] - 2024-08-01 14:12:25

### Changed

- Update PolicyEngine US to 1.37.0

## [1.26.32] - 2024-07-31 07:32:36

### Changed

- Update PolicyEngine US to 1.35.0

## [1.26.31] - 2024-07-30 20:43:17

### Changed

- Update PolicyEngine US to 1.34.7

## [1.26.30] - 2024-07-30 17:07:51

### Changed

- Update PolicyEngine US to 1.34.5

## [1.26.29] - 2024-07-30 13:26:31

### Changed

- Update PolicyEngine UK to 1.4.0

## [1.26.28] - 2024-07-30 12:58:41

### Changed

- Update PolicyEngine US to 1.34.4

## [1.26.27] - 2024-07-30 02:34:58

### Changed

- Update PolicyEngine US to 1.34.3

## [1.26.26] - 2024-07-29 21:30:42

### Changed

- Update PolicyEngine US to 1.34.2

## [1.26.25] - 2024-07-29 17:07:09

### Changed

- Update PolicyEngine UK to 1.3.0

## [1.26.24] - 2024-07-26 09:52:22

### Changed

- Update PolicyEngine UK to 1.1.0

## [1.26.23] - 2024-07-26 03:19:23

### Changed

- Update PolicyEngine US to 1.34.1

## [1.26.22] - 2024-07-25 13:24:02

### Changed

- Update PolicyEngine US to 1.33.1

## [1.26.21] - 2024-07-25 10:20:30

### Changed

- Update PolicyEngine US to 1.32.0

## [1.26.20] - 2024-07-24 20:41:05

### Changed

- Update PolicyEngine US to 1.31.2

## [1.26.19] - 2024-07-23 04:40:00

### Changed

- Update PolicyEngine US to 1.28.0

## [1.26.18] - 2024-07-21 16:36:36

### Changed

- Update PolicyEngine US to 1.25.2

## [1.26.17] - 2024-07-21 05:33:36

### Changed

- Update PolicyEngine US to 1.25.0

## [1.26.16] - 2024-07-19 09:59:40

### Changed

- Update PolicyEngine UK to 1.0.0

## [1.26.15] - 2024-07-17 19:29:50

### Changed

- Update PolicyEngine US to 1.22.0

## [1.26.14] - 2024-07-15 18:45:40

### Fixed

- Removed explicit filepath from GCP launch Dockerfile

## [1.26.13] - 2024-07-15 18:20:27

### Fixed

- Made repairs to GCP launch Dockerfile

## [1.26.12] - 2024-07-15 04:11:20

### Fixed

- Updated Dockerfile pull address

## [1.26.11] - 2024-07-14 22:40:34

### Changed

- Update PolicyEngine UK to 0.86.3

## [1.26.10] - 2024-07-14 22:32:42

### Changed

- Update PolicyEngine US to 1.21.0

## [1.26.9] - 2024-07-14 22:18:26

### Changed

- Return to using Python 3.10
- Use standard-build Python image for Docker container

## [1.26.8] - 2024-07-02 22:44:34

### Changed

- Update PolicyEngine US to 1.12.0

## [1.26.7] - 2024-07-02 15:50:34

### Changed

- Update PolicyEngine US to 1.8.0

## [1.26.6] - 2024-06-28 20:15:30

### Changed

- Update PolicyEngine UK to 0.85.0

## [1.26.5] - 2024-06-28 16:52:36

### Changed

- Update PolicyEngine UK to 0.84.0

## [1.26.4] - 2024-06-28 03:01:48

### Changed

- Temporarily downgraded to Python 3.9 pending Dockerfile changes

## [1.26.3] - 2024-06-28 01:02:50

### Changed

- Update PolicyEngine UK to 0.83.2

## [1.26.2] - 2024-06-26 00:15:58

### Changed

- Upgraded to Python 3.10

## [1.26.1] - 2024-06-25 03:00:34

### Changed

- Update PolicyEngine US to 0.796.0

## [1.26.0] - 2024-06-24 05:03:05

### Changed

- Updated to Claude 3.5 Sonnet.

## [1.25.7] - 2024-06-21 19:44:57

### Changed

- Update PolicyEngine US to 0.794.2

## [1.25.6] - 2024-06-20 02:27:42

### Changed

- Update PolicyEngine US to 0.792.0

## [1.25.5] - 2024-06-19 21:11:34

### Changed

- Update PolicyEngine US to 0.791.0

## [1.25.4] - 2024-06-19 21:09:22

### Added

- queue_position to response for active jobs

### Changed

- Display "Your position in the queue is 0" instead of "Your position in the queue is None" for active jobs

## [1.25.3] - 2024-06-12 15:43:55

### Changed

- Update PolicyEngine US to 0.788.0

## [1.25.2] - 2024-06-11 22:54:28

### Changed

- Update PolicyEngine US to 0.787.0

## [1.25.1] - 2024-06-11 12:31:12

### Changed

- Update PolicyEngine US to 0.785.2

## [1.25.0] - 2024-06-11 08:38:31

### Added

- 2028 and 2029 UK impacts.

## [1.24.9] - 2024-06-11 08:10:06

### Changed

- Update PolicyEngine UK to 0.82.0

## [1.24.8] - 2024-06-10 22:00:50

### Changed

- Update PolicyEngine US to 0.785.1

## [1.24.7] - 2024-06-10 17:29:17

### Changed

- Update PolicyEngine US to 0.785.0

## [1.24.6] - 2024-06-08 02:46:31

### Changed

- Update PolicyEngine US to 0.783.0

## [1.24.5] - 2024-06-07 15:11:17

### Changed

- Update PolicyEngine US to 0.780.2

## [1.24.4] - 2024-06-07 08:35:57

### Changed

- Update PolicyEngine UK to 0.80.0

## [1.24.3] - 2024-06-04 23:18:47

### Changed

- Update PolicyEngine US to 0.779.2

## [1.24.2] - 2024-05-30 21:20:01

### Added

- Calculation of overall relative LSR impacts

## [1.24.1] - 2024-05-30 16:24:46

### Changed

- Calculates relative LSR impacts using baseline earnings, not household market income

## [1.24.0] - 2024-05-29 09:54:55

### Fixed

- Added extra safety check on deciles.

## [1.23.5] - 2024-05-28 12:24:43

### Changed

- Update PolicyEngine UK to 0.79.0

## [1.23.4] - 2024-05-27 22:44:23

### Changed

- Update PolicyEngine UK to 0.78.0

## [1.23.3] - 2024-05-24 19:41:01

### Changed

- Update PolicyEngine US to 0.777.5

## [1.23.2] - 2024-05-24 13:12:54

### Changed

- Update PolicyEngine US to 0.777.3

## [1.23.1] - 2024-05-23 17:36:00

### Changed

- Update PolicyEngine UK to 0.77.0

## [1.23.0] - 2024-05-19 09:50:45

### Added

- Hours response handling.

## [1.22.2] - 2024-05-17 00:35:24

### Changed

- Update PolicyEngine US to 0.776.0

## [1.22.1] - 2024-05-13 16:23:44

### Changed

- Converted get_analysis SQL GET statement argument to tuple-type

## [1.22.0] - 2024-05-13 14:26:36

### Added

- Decile breakdowns for labor supply impacts.

## [1.21.0] - 2024-05-09 20:04:08

### Changed

- Replaced ChatGPT with Claude for analysis endpoint

## [1.20.8] - 2024-05-08 15:46:42

### Changed

- Update PolicyEngine US to 0.767.0

## [1.20.7] - 2024-05-08 13:22:46

### Added

- /.vscode to .gitignore

## [1.20.6] - 2024-05-08 06:38:32

### Changed

- Job timeouts to 20m.

## [1.20.5] - 2024-05-07 19:41:17

### Changed

- Update PolicyEngine US to 0.766.0

## [1.20.4] - 2024-05-07 09:28:03

### Fixed

- State taxes unfrozen in US sims.

## [1.20.3] - 2024-05-07 01:47:50

### Changed

- Update PolicyEngine US to 0.763.0

## [1.20.2] - 2024-05-06 20:20:20

### Changed

- Update PolicyEngine US to 0.761.0

## [1.20.1] - 2024-05-06 16:11:42

### Changed

- Update PolicyEngine US to 0.760.0

## [1.20.0] - 2024-05-02 12:12:36

### Added

- Revenue impacts of LSRs to outputs.

## [1.19.26] - 2024-05-01 17:08:44

### Changed

- Update PolicyEngine UK to 0.75.0

## [1.19.25] - 2024-04-30 19:43:56

### Changed

- Update PolicyEngine UK to 0.74.1

## [1.19.24] - 2024-04-29 20:00:20

### Changed

- Pinned policyengine-core to v. 2.19.0 or lower

## [1.19.23] - 2024-04-29 19:04:45

### Changed

- Update PolicyEngine US to 0.754.0

## [1.19.22] - 2024-04-29 14:01:56

### Changed

- Update PolicyEngine US to 0.753.0

## [1.19.21] - 2024-04-26 15:24:11

## [1.19.20] - 2024-04-26 15:23:39

### Changed

- get_user_policy controller now filters by country_id

## [1.19.19] - 2024-04-26 00:23:36

### Changed

- Update PolicyEngine US to 0.752.0

## [1.19.18] - 2024-04-24 18:12:35

### Changed

- Update PolicyEngine US to 0.750.3

## [1.19.17] - 2024-04-24 17:15:38

### Changed

- Altered how test_user_policy's test_nulls test removes test records

## [1.19.16] - 2024-04-24 12:06:42

### Changed

- Added script to convert user_policy SELECT statements with None values to SQL NULL values

## [1.19.15] - 2024-04-23 18:54:38

### Changed

- Update PolicyEngine US to 0.750.0

## [1.19.14] - 2024-04-23 03:04:12

### Changed

- Update PolicyEngine US to 0.748.0

## [1.19.13] - 2024-04-23 00:00:57

### Changed

- Update PolicyEngine CANADA to 0.95.0

## [1.19.12] - 2024-04-22 16:20:11

### Changed

- Fetch all user policies, not just those corresponding with current country

## [1.19.11] - 2024-04-22 16:17:17

### Changed

- set_user_policy now returns the data which has been entered, as well as the new policy's ID

## [1.19.10] - 2024-04-20 03:32:23

### Changed

- Update PolicyEngine US to 0.743.1

## [1.19.9] - 2024-04-19 08:56:58

### Changed

- Renamed user_policies table's "budgetary_cost" column to "budgetary_impact"

## [1.19.8] - 2024-04-18 10:37:44

### Changed

- user_profile POST requests now return complete user object, not just user_id
- Change timestamp values in user_policies and user_profiles databases to BIGINT types and update endpoints accordingly

## [1.19.7] - 2024-04-17 10:29:07

### Added

- Year, geography, budgetary_cost, updated_date, added_date, number_of_provisions, and api_version as rows in user_policy table
- PUT endpoint for handling updates to existing records
- user_profiles table that holds non-identifying user information
- POST endpoint to create records within user_profiles table
- GET endpoint for fetching records from user_profiles table
- PUT endpoint for updated user_profiles records

## [1.19.6] - 2024-04-16 13:43:56

### Changed

- Update PolicyEngine UK to 0.73.1

## [1.19.5] - 2024-04-16 00:55:51

### Changed

- Update PolicyEngine US to 0.739.0

## [1.19.4] - 2024-04-15 21:22:41

### Changed

- Update PolicyEngine US to 0.737.1

## [1.19.3] - 2024-04-15 16:12:17

### Added

- Function to ensure that only unique user policies are saved

## [1.19.2] - 2024-04-15 14:41:51

### Changed

- Update PolicyEngine US to 0.737.0

## [1.19.1] - 2024-04-13 14:52:31

### Changed

- Update PolicyEngine US to 0.733.1

## [1.19.0] - 2024-04-12 16:01:49

### Added

- user_policies database
- user_policy GET and POST routes

## [1.18.4] - 2024-04-11 12:50:10

### Changed

- Update PolicyEngine US to 0.728.0

## [1.18.3] - 2024-04-11 02:51:06

### Changed

- Update PolicyEngine US to 0.727.2

## [1.18.2] - 2024-04-09 21:00:48

## [1.18.1] - 2024-04-09 19:29:37

### Changed

- Update PolicyEngine US to 0.727.1

## [1.18.0] - 2024-04-04 14:05:05

### Fixed

- add units to parameters that were lacking units due to specification of units at a higher level (using rate_unit, for instance)

## [1.17.22] - 2024-03-27 20:14:54

### Changed

- Update PolicyEngine US to 0.717.0

## [1.17.21] - 2024-03-26 17:51:46

## [1.17.20] - 2024-03-26 14:42:08

### Changed

- Increased individual test timeout length to 350 seconds

## [1.17.19] - 2024-03-26 14:12:23

### Added

- Added flag to disable Pytest capturing temporarily

## [1.17.18] - 2024-03-25 18:41:40

### Changed

- Update PolicyEngine US to 0.715.0

## [1.17.17] - 2024-03-25 15:52:04

### Changed

- Update PolicyEngine US to 0.713.3

## [1.17.16] - 2024-03-22 19:15:53

### Changed

- Update PolicyEngine US to 0.713.1

## [1.17.15] - 2024-03-22 12:15:27

### Changed

- Update PolicyEngine US to 0.713.0

## [1.17.14] - 2024-03-22 02:30:54

### Changed

- Update PolicyEngine US to 0.712.0

## [1.17.13] - 2024-03-19 16:21:18

### Changed

- Update PolicyEngine US to 0.710.1

## [1.17.12] - 2024-03-19 00:07:32

### Added

- Various sections to README to more easily onboard contributors

## [1.17.11] - 2024-03-16 03:19:05

### Changed

- Update PolicyEngine US to 0.708.4

## [1.17.10] - 2024-03-15 21:44:35

### Changed

- Update PolicyEngine US to 0.708.3

## [1.17.9] - 2024-03-15 13:47:39

### Changed

- Update PolicyEngine US to 0.708.0

## [1.17.8] - 2024-03-15 12:21:53

### Changed

- Update PolicyEngine US to 0.707.0

## [1.17.7] - 2024-03-14 17:52:59

### Changed

- Update PolicyEngine US to 0.703.0

## [1.17.6] - 2024-03-14 13:39:08

### Changed

- Update PolicyEngine US to 0.700.0

## [1.17.5] - 2024-03-14 13:01:30

### Changed

- Update PolicyEngine US to 0.699.2

## [1.17.4] - 2024-03-13 20:47:11

### Changed

- Update PolicyEngine US to 0.699.0

## [1.17.3] - 2024-03-10 21:28:15

### Changed

- Update PolicyEngine US to 0.696.0

## [1.17.2] - 2024-03-06 23:36:26

### Changed

- Update PolicyEngine US to 0.691.1

## [1.17.1] - 2024-03-06 12:37:37

### Fixed

- Increased test timeout to 250s.

## [1.17.0] - 2024-03-06 11:47:00

### Changed

- UK and US versions updated.
- US enhanced CPS handling.

## [1.16.3] - 2024-03-05 17:41:42

### Changed

- Update PolicyEngine UK to 0.70.0

## [1.16.2] - 2024-03-04 22:34:57

### Changed

- Update PolicyEngine US to 0.688.2

## [1.16.1] - 2024-03-04 19:43:26

### Changed

- Update PolicyEngine UK to 0.69.1

## [1.16.0] - 2024-03-04 11:09:20

### Added

- Query param for policy search endpoint that returns only the first policy with a label-policy hash pair

## [1.15.42] - 2024-03-03 00:18:54

### Changed

- Update PolicyEngine US to 0.688.1

## [1.15.41] - 2024-02-28 11:04:13

### Changed

- Update PolicyEngine US to 0.684.0

## [1.15.40] - 2024-02-27 23:23:49

### Changed

- Update PolicyEngine US to 0.683.1

## [1.15.39] - 2024-02-26 21:18:51

### Changed

- Update PolicyEngine US to 0.682.0

## [1.15.38] - 2024-02-24 05:04:58

### Changed

- Update PolicyEngine US to 0.680.0

## [1.15.37] - 2024-02-24 00:21:41

### Changed

- Update PolicyEngine US to 0.679.1

## [1.15.36] - 2024-02-21 12:45:19

### Changed

- Update PolicyEngine US to 0.676.0

## [1.15.35] - 2024-02-21 03:07:57

### Changed

- Update PolicyEngine US to 0.675.0

## [1.15.34] - 2024-02-20 12:20:22

### Changed

- Update PolicyEngine UK to 0.69.0

## [1.15.33] - 2024-02-20 01:42:12

### Changed

- Update PolicyEngine US to 0.669.0

## [1.15.32] - 2024-02-18 18:37:01

### Changed

- Core unpinned, UK, US and Canada updated.

### Fixed

- Negative income deciles removed from outputs.

## [1.15.31] - 2024-02-14 17:40:21

### Changed

- Fixed the test_policy test

## [1.15.30] - 2024-02-14 13:20:25

### Changed

- Ensure that get_household_year doesn't break on empty age variable

## [1.15.29] - 2024-02-14 12:37:50

### Changed

- Altered set_policy controller behavior to prevent creation of multiple records when changing labels

## [1.15.28] - 2024-02-13 16:34:39

### Changed

- Update PolicyEngine US to 0.654.1

## [1.15.27] - 2024-02-08 21:49:02

### Changed

- Update PolicyEngine US to 0.648.3

## [1.15.26] - 2024-02-07 14:32:28

### Changed

- Update PolicyEngine US to 0.644.0

## [1.15.25] - 2024-02-01 21:36:49

### Changed

- Update PolicyEngine US to 0.637.4

## [1.15.24] - 2024-02-01 03:53:07

### Changed

- Update PolicyEngine US to 0.637.2

## [1.15.23] - 2024-01-29 18:31:47

### Changed

- Update PolicyEngine US to 0.635.0

## [1.15.22] - 2024-01-28 20:19:12

### Changed

- Update PolicyEngine UK to 0.65.0

## [1.15.21] - 2024-01-27 19:42:55

### Changed

- Updated code formatting for new black.
- Updated policyengine-us and policyengine-canada.

## [1.15.20] - 2024-01-25 20:33:11

### Changed

- Update PolicyEngine US to 0.632.0

## [1.15.19] - 2024-01-23 23:35:40

### Changed

- Altered deployment CPU number

## [1.15.18] - 2024-01-23 12:14:04

### Changed

- Update PolicyEngine US to 0.631.0

## [1.15.17] - 2024-01-22 16:52:12

### Changed

- Update PolicyEngine US to 0.629.2

## [1.15.16] - 2024-01-20 17:07:30

### Changed

- Update PolicyEngine US to 0.627.0

## [1.15.15] - 2024-01-17 18:13:03

### Added

- Enabled 2025 household calculations for US

## [1.15.14] - 2024-01-17 13:54:40

### Changed

- Update PolicyEngine US to 0.622.1

## [1.15.13] - 2024-01-16 22:11:34

### Changed

- Update PolicyEngine US to 0.621.0

## [1.15.12] - 2024-01-14 12:43:02

### Changed

- Update PolicyEngine US to 0.619.0

## [1.15.11] - 2024-01-12 13:37:44

### Changed

- Update PolicyEngine US to 0.617.0

## [1.15.10] - 2024-01-11 13:40:17

### Changed

- Update PolicyEngine US to 0.614.0

## [1.15.9] - 2024-01-10 16:13:06

### Changed

- Update PolicyEngine US to 0.610.1

## [1.15.8] - 2024-01-04 19:36:19

### Fixed

- Bug causing state tax revenues to be double counted.

## [1.15.7] - 2024-01-04 01:29:48

### Changed

- Update PolicyEngine US to 0.603.3

## [1.15.6] - 2024-01-03 18:00:44

### Changed

- Update PolicyEngine US to 0.603.0

## [1.15.5] - 2023-12-31 01:02:19

### Changed

- Removed hard-coded year from add_yearly_variables function

## [1.15.4] - 2023-12-30 10:27:22

### Added

- Automatic docker container builds on new versions.

## [1.15.3] - 2023-12-30 03:50:21

### Changed

- Update PolicyEngine US to 0.601.1

## [1.15.2] - 2023-12-29 01:12:14

### Changed

- Update PolicyEngine US to 0.600.1

## [1.15.1] - 2023-12-28 20:49:32

### Changed

- Update PolicyEngine US to 0.600.0

## [1.15.0] - 2023-12-28 13:37:15

### Added

- Labour supply response data to economic impacts.

## [1.14.28] - 2023-12-28 00:46:33

### Changed

- Update PolicyEngine US to 0.598.0

## [1.14.27] - 2023-12-27 13:04:21

### Fixed

- Budgetary impacts are now correct when market income changes.

## [1.14.26] - 2023-12-24 20:57:35

### Changed

- Update PolicyEngine US to 0.595.2

## [1.14.25] - 2023-12-22 16:55:56

### Changed

- Update PolicyEngine US to 0.595.0

## [1.14.24] - 2023-12-21 13:01:25

### Changed

- Update PolicyEngine US to 0.586.2

## [1.14.23] - 2023-12-20 20:29:00

### Fixed

- Pin core to address randomness issue.

## [1.14.22] - 2023-12-19 11:46:07

### Changed

- Update PolicyEngine US to 0.585.0

## [1.14.21] - 2023-12-18 04:24:45

### Changed

- Update PolicyEngine US to 0.584.1

## [1.14.20] - 2023-12-18 03:02:20

### Changed

- Upgrade all workflow actions.
- Upgrade to GPT-4 Turbo.
- Upgrade policyengine-core, policyengine-us, and policyengine-us.

## [1.14.19] - 2023-12-18 02:41:20

### Changed

- Update PolicyEngine US to 0.584.0

## [1.14.18] - 2023-12-16 16:16:01

### Changed

- Update PolicyEngine US to 0.583.0

## [1.14.17] - 2023-12-15 12:41:51

### Changed

- Update PolicyEngine US to 0.580.0

## [1.14.16] - 2023-12-14 12:19:34

### Changed

- Core bumped to 2.11.3

## [1.14.15] - 2023-12-11 12:30:18

### Changed

- Update PolicyEngine US to 0.571.2

## [1.14.14] - 2023-12-06 19:49:38

### Changed

- Update PolicyEngine US to 0.563.0

## [1.14.13] - 2023-12-06 18:17:04

### Changed

- Update PolicyEngine US to 0.561.1

## [1.14.12] - 2023-12-06 17:36:44

### Changed

- Update PolicyEngine US to 0.560.0

## [1.14.11] - 2023-12-05 17:00:43

### Changed

- Update PolicyEngine US to 0.558.1

## [1.14.10] - 2023-12-05 15:18:09

### Changed

- Update PolicyEngine US to 0.558.0

## [1.14.9] - 2023-12-05 14:01:49

### Changed

- Update PolicyEngine UK to 0.62.0

## [1.14.8] - 2023-11-28 19:12:43

### Changed

- Update PolicyEngine US to 0.541.1

## [1.14.7] - 2023-11-28 14:42:12

### Changed

- Bump -uk now that -us supports latest version of -core.

## [1.14.6] - 2023-11-28 12:13:02

### Changed

- Update PolicyEngine US to 0.540.0

## [1.14.5] - 2023-11-27 23:03:23

### Fixed

- Downgraded policyengine-core to fix US microsimulation bug.

## [1.14.4] - 2023-11-26 20:45:28

### Changed

- Update PolicyEngine UK to 0.61.3

## [1.14.3] - 2023-11-26 19:47:09

### Changed

- Update PolicyEngine US to 0.538.1

## [1.14.2] - 2023-11-23 19:13:40

### Changed

- Update PolicyEngine US to 0.538.0

## [1.14.1] - 2023-11-23 18:23:54

### Changed

- Update PolicyEngine UK to 0.61.1

## [1.14.0] - 2023-11-22 16:07:33

### Fixed

- Bumped Core to 2.11

## [1.13.4] - 2023-11-22 15:25:46

### Changed

- Update PolicyEngine UK to 0.60.0

## [1.13.3] - 2023-11-22 02:04:29

### Changed

- Update PolicyEngine US to 0.537.1

## [1.13.2] - 2023-11-20 23:48:29

### Changed

- Update PolicyEngine US to 0.536.1

## [1.13.1] - 2023-11-20 16:10:10

### Changed

- Update PolicyEngine US to 0.536.0

## [1.13.0] - 2023-11-20 12:06:42

### Changed

- Add option to specify full or only-selected-variables /calculate option.

## [1.12.27] - 2023-11-17 21:49:38

### Changed

- Update PolicyEngine US to 0.535.1

## [1.12.26] - 2023-11-17 20:10:03

### Changed

- Update PolicyEngine UK to 0.58.2

## [1.12.25] - 2023-11-15 21:10:30

### Changed

- Update PolicyEngine US to 0.534.0

## [1.12.24] - 2023-11-15 13:39:27

### Changed

- Update PolicyEngine US to 0.532.0

## [1.12.23] - 2023-11-13 21:44:42

### Changed

- Update PolicyEngine US to 0.529.0

## [1.12.22] - 2023-11-13 15:56:23

### Changed

- Update PolicyEngine US to 0.528.0

## [1.12.21] - 2023-11-12 22:38:45

### Changed

- Update PolicyEngine CANADA to 0.87.0

## [1.12.20] - 2023-11-12 01:38:56

### Changed

- Update PolicyEngine US to 0.527.0

## [1.12.19] - 2023-11-10 17:32:28

### Changed

- Update PolicyEngine US to 0.526.0

## [1.12.18] - 2023-11-09 02:55:05

### Changed

- Update PolicyEngine US to 0.523.1

## [1.12.17] - 2023-11-07 18:49:28

### Changed

- Update PolicyEngine US to 0.519.0

## [1.12.16] - 2023-11-06 16:00:32

### Changed

- Update PolicyEngine US to 0.518.5

## [1.12.15] - 2023-11-04 22:25:11

### Changed

- Update PolicyEngine US to 0.518.3

## [1.12.14] - 2023-11-04 05:26:48

### Changed

- Update PolicyEngine US to 0.518.1

## [1.12.13] - 2023-11-03 05:50:52

### Changed

- Update PolicyEngine US to 0.516.3

## [1.12.12] - 2023-11-02 22:29:45

### Changed

- Update PolicyEngine US to 0.516.2

## [1.12.11] - 2023-11-02 02:22:54

### Changed

- Update PolicyEngine US to 0.515.0

## [1.12.10] - 2023-11-01 19:25:39

### Changed

- Update PolicyEngine US to 0.514.2

## [1.12.9] - 2023-11-01 11:48:49

### Changed

- Update PolicyEngine US to 0.514.1

## [1.12.8] - 2023-11-01 02:50:00

### Changed

- Update PolicyEngine US to 0.514.0

## [1.12.7] - 2023-10-31 15:35:33

### Changed

- Repaired unit tests for calculate and household under policy endpoints

## [1.12.6] - 2023-10-30 12:53:16

### Changed

- Update PolicyEngine US to 0.513.0

## [1.12.5] - 2023-10-28 19:36:10

### Changed

- Update PolicyEngine US to 0.512.0

## [1.12.4] - 2023-10-28 17:07:54

### Changed

- Update PolicyEngine US to 0.511.0

## [1.12.3] - 2023-10-27 20:53:09

### Changed

- Update PolicyEngine UK to 0.58.1

## [1.12.2] - 2023-10-23 16:16:26

### Changed

- Update PolicyEngine US to 0.510.0

## [1.12.1] - 2023-10-22 22:12:09

### Changed

- Update PolicyEngine US to 0.509.0

## [1.12.0] - 2023-10-20 11:40:48

### Added

- Eternal and monthly variables to API-computed set.

## [1.11.36] - 2023-10-20 05:29:43

### Changed

- Update PolicyEngine US to 0.508.3

## [1.11.35] - 2023-10-19 22:45:37

### Changed

- Update PolicyEngine US to 0.508.2

## [1.11.34] - 2023-10-19 19:05:50

### Changed

- Update PolicyEngine US to 0.508.1

## [1.11.33] - 2023-10-18 00:13:55

### Changed

- Update PolicyEngine US to 0.506.1

## [1.11.32] - 2023-10-17 15:14:58

### Changed

- Update PolicyEngine UK to 0.57.0

## [1.11.31] - 2023-10-16 01:26:57

### Changed

- Update PolicyEngine US to 0.503.1

## [1.11.30] - 2023-10-14 14:36:44

### Changed

- Update PolicyEngine US to 0.502.1

## [1.11.29] - 2023-10-13 19:16:46

### Changed

- Update PolicyEngine US to 0.502.0

## [1.11.28] - 2023-10-12 23:29:10

### Changed

- Update PolicyEngine US to 0.501.1

## [1.11.27] - 2023-10-12 20:46:40

### Changed

- Update PolicyEngine US to 0.501.0

## [1.11.26] - 2023-10-12 20:01:13

### Changed

- Update PolicyEngine UK to 0.56.4

## [1.11.25] - 2023-10-11 01:35:56

### Changed

- Update PolicyEngine US to 0.499.0

## [1.11.24] - 2023-10-10 20:05:34

### Changed

- Update PolicyEngine US to 0.498.0

## [1.11.23] - 2023-10-09 21:55:20

### Changed

- Update PolicyEngine US to 0.497.2

## [1.11.22] - 2023-10-09 20:35:46

### Changed

- Update PolicyEngine UK to 0.56.3

## [1.11.21] - 2023-10-08 13:18:16

### Changed

- Update PolicyEngine CANADA to 0.86.2

## [1.11.20] - 2023-10-06 16:04:32

### Changed

- Update PolicyEngine CANADA to 0.86.1

## [1.11.19] - 2023-10-05 03:37:35

### Changed

- Update PolicyEngine CANADA to 0.86.0

## [1.11.18] - 2023-10-04 21:46:42

### Changed

- Update PolicyEngine US to 0.493.0

## [1.11.17] - 2023-10-04 13:24:04

### Changed

- Update PolicyEngine US to 0.492.0

## [1.11.16] - 2023-10-04 02:46:04

### Changed

- Update PolicyEngine US to 0.491.0

## [1.11.15] - 2023-10-03 04:45:13

### Changed

- Update PolicyEngine US to 0.488.1

## [1.11.14] - 2023-10-02 23:40:10

### Changed

- Update PolicyEngine US to 0.488.0

## [1.11.13] - 2023-10-02 16:29:39

### Changed

- Update PolicyEngine US to 0.487.0

## [1.11.12] - 2023-10-02 00:52:15

### Changed

- Update PolicyEngine US to 0.486.0

## [1.11.11] - 2023-09-29 22:48:00

### Changed

- Update PolicyEngine US to 0.485.0

## [1.11.10] - 2023-09-29 22:10:52

### Changed

- Update PolicyEngine US to 0.484.0

## [1.11.9] - 2023-09-29 21:50:36

### Changed

- Update PolicyEngine CANADA to 0.85.0

## [1.11.8] - 2023-09-29 17:42:08

### Changed

- Update PolicyEngine US to 0.483.0

## [1.11.7] - 2023-09-28 17:52:35

### Changed

- Update PolicyEngine US to 0.482.1

## [1.11.6] - 2023-09-27 18:46:35

### Changed

- Update PolicyEngine US to 0.481.0

## [1.11.5] - 2023-09-27 14:38:33

### Changed

- Add script to add default variables to household situation before enqueuing for calculation
- Add endpoint for updating existing households
- Add test US household that contains variables not present in the policyengine-us package
- Add various tests for new features

## [1.11.4] - 2023-09-25 17:37:41

### Changed

- Update PolicyEngine US to 0.479.0

## [1.11.3] - 2023-09-24 03:48:27

### Changed

- Update PolicyEngine US to 0.476.0

## [1.11.2] - 2023-09-24 03:23:52

### Changed

- Update PolicyEngine CANADA to 0.84.0

## [1.11.1] - 2023-09-22 20:12:16

### Changed

- Update PolicyEngine US to 0.474.0

## [1.11.0] - 2023-09-22 13:05:16

### Added

- Support for the enhanced CPS in the US.

## [1.10.99] - 2023-09-21 16:53:16

### Changed

- Update PolicyEngine US to 0.471.1

## [1.10.98] - 2023-09-13 14:32:32

### Added

- /economy regression test

## [1.10.98] - 2023-09-13 11:14:23

### Changed

- Update PolicyEngine US to 0.465.0

## [1.10.97] - 2023-09-12 16:48:01

### Changed

- Update PolicyEngine US to 0.463.0

## [1.10.96] - 2023-09-08 01:39:30

### Changed

- Update PolicyEngine US to 0.462.3

## [1.10.95] - 2023-09-07 19:07:02

### Changed

- Update PolicyEngine US to 0.462.2

## [1.10.94] - 2023-09-07 15:17:33

### Changed

- Update PolicyEngine US to 0.462.1

## [1.10.93] - 2023-09-06 15:01:16

### Changed

- Update PolicyEngine US to 0.460.1

## [1.10.92] - 2023-09-06 12:42:48

### Changed

- M
- a
- n
- u
- a
- l
- l
- y
-  
- a
- d
- d
-  
- r
- e
- c
- o
- r
- d
- s
-  
- t
- o
-  
- h
- o
- u
- s
- e
- h
- o
- l
- d
-  
- a
- n
- d
-  
- p
- o
- l
- i
- c
- y
-  
- t
- a
- b
- l
- e
- s
-  
- f
- o
- r
-  
- b
- a
- c
- k
- -
- e
- n
- d
-  
- t
- e
- s
- t
- i
- n
- g

## [1.10.91] - 2023-09-04 23:54:09

### Changed

- Update PolicyEngine CANADA to 0.83.0

## [1.10.90] - 2023-09-04 23:15:51

### Changed

- Update PolicyEngine US to 0.458.2

## [1.10.89] - 2023-09-04 18:05:45

### Changed

- Update PolicyEngine US to 0.458.0

## [1.10.88] - 2023-09-04 01:43:34

### Changed

- Update PolicyEngine US to 0.456.0

## [1.10.87] - 2023-09-03 14:41:29

### Changed

- Update PolicyEngine US to 0.455.0

## [1.10.86] - 2023-09-03 02:41:31

### Changed

- Update PolicyEngine US to 0.454.0

## [1.10.85] - 2023-09-02 22:48:20

### Changed

- Update PolicyEngine US to 0.453.0

## [1.10.84] - 2023-09-02 21:31:21

### Changed

- Update PolicyEngine US to 0.452.1

## [1.10.83] - 2023-09-02 02:48:40

### Changed

- Update PolicyEngine US to 0.452.0

## [1.10.82] - 2023-09-01 19:39:35

### Changed

- Update PolicyEngine US to 0.451.0

## [1.10.81] - 2023-08-31 22:02:48

### Changed

- Update PolicyEngine US to 0.450.0

## [1.10.80] - 2023-08-30 02:27:21

### Changed

- Update PolicyEngine US to 0.449.0

## [1.10.79] - 2023-08-30 00:03:05

### Changed

- Update PolicyEngine US to 0.447.1

## [1.10.78] - 2023-08-29 20:53:16

### Changed

- Update PolicyEngine US to 0.447.0

## [1.10.77] - 2023-08-29 20:06:27

### Changed

- Update PolicyEngine US to 0.445.0

## [1.10.76] - 2023-08-29 15:56:04

### Changed

- Update PolicyEngine US to 0.444.0

## [1.10.75] - 2023-08-26 20:08:53

### Changed

- Update PolicyEngine US to 0.443.0

## [1.10.74] - 2023-08-25 15:41:43

### Changed

- Update PolicyEngine CANADA to 0.82.0

## [1.10.73] - 2023-08-25 03:10:20

### Changed

- Update PolicyEngine US to 0.442.0

## [1.10.72] - 2023-08-24 21:54:24

### Changed

- Update PolicyEngine CANADA to 0.81.0

## [1.10.71] - 2023-08-24 19:16:59

### Changed

- Update PolicyEngine US to 0.441.0

## [1.10.70] - 2023-08-24 15:32:18

### Changed

- Update PolicyEngine UK to 0.55.2

## [1.10.69] - 2023-08-24 12:38:39

### Changed

- Update PolicyEngine US to 0.439.1

## [1.10.68] - 2023-08-23 12:56:42

### Changed

- Update PolicyEngine US to 0.439.0

## [1.10.67] - 2023-08-22 18:59:00

### Changed

- Update PolicyEngine US to 0.438.0

## [1.10.66] - 2023-08-21 21:00:56

### Changed

- Update PolicyEngine CANADA to 0.80.2

## [1.10.65] - 2023-08-21 20:46:53

### Changed

- Update PolicyEngine US to 0.437.1

## [1.10.64] - 2023-08-21 20:36:03

### Changed

- Update PolicyEngine CANADA to 0.80.1

## [1.10.63] - 2023-08-21 12:47:49

### Changed

- Update PolicyEngine US to 0.437.0

## [1.10.62] - 2023-08-21 04:54:26

### Changed

- Update PolicyEngine US to 0.436.0

## [1.10.61] - 2023-08-20 20:49:09

### Changed

- Update PolicyEngine CANADA to 0.80.0

## [1.10.60] - 2023-08-20 18:25:48

### Changed

- Update PolicyEngine US to 0.432.0

## [1.10.59] - 2023-08-20 13:14:52

### Changed

- Update PolicyEngine US to 0.431.3

## [1.10.58] - 2023-08-19 20:38:46

### Changed

- Update PolicyEngine US to 0.431.2

## [1.10.57] - 2023-08-19 05:27:02

### Changed

- Update PolicyEngine US to 0.431.1

## [1.10.56] - 2023-08-19 00:16:18

### Changed

- Update PolicyEngine US to 0.430.0

## [1.10.55] - 2023-08-18 23:39:39

### Changed

- Update PolicyEngine US to 0.429.1

## [1.10.54] - 2023-08-18 15:44:02

### Changed

- Update PolicyEngine US to 0.428.0

## [1.10.53] - 2023-08-18 04:40:14

### Changed

- Update PolicyEngine US to 0.427.0

## [1.10.52] - 2023-08-18 04:32:40

### Changed

- Update PolicyEngine CANADA to 0.79.0

## [1.10.51] - 2023-08-17 19:10:55

### Changed

- Update PolicyEngine US to 0.426.0

## [1.10.50] - 2023-08-17 18:46:04

### Changed

- Update PolicyEngine US to 0.425.1

## [1.10.49] - 2023-08-17 12:19:48

### Changed

- Update PolicyEngine US to 0.424.1

## [1.10.48] - 2023-08-16 07:20:30

### Changed

- Update PolicyEngine US to 0.424.0

## [1.10.47] - 2023-08-13 16:39:58

### Changed

- Update PolicyEngine US to 0.423.1

## [1.10.46] - 2023-08-12 18:05:10

### Changed

- Update PolicyEngine UK to 0.55.1

## [1.10.45] - 2023-08-11 17:59:47

### Changed

- Update PolicyEngine US to 0.423.0

## [1.10.44] - 2023-08-11 04:47:04

### Changed

- Update PolicyEngine CANADA to 0.76.0

## [1.10.43] - 2023-08-10 02:33:21

### Changed

- Update PolicyEngine UK to 0.55.0

## [1.10.42] - 2023-08-10 02:12:10

### Changed

- Update PolicyEngine US to 0.422.0

## [1.10.41] - 2023-08-10 02:06:24

### Changed

- Update PolicyEngine CANADA to 0.75.0

## [1.10.40] - 2023-08-10 01:21:49

### Changed

- Update PolicyEngine CANADA to 0.74.0

## [1.10.39] - 2023-08-09 23:47:43

### Changed

- Update PolicyEngine US to 0.419.0

## [1.10.38] - 2023-08-09 23:20:10

### Changed

- Update PolicyEngine CANADA to 0.73.0

## [1.10.37] - 2023-08-09 14:18:24

### Changed

- Update PolicyEngine US to 0.417.3

## [1.10.36] - 2023-08-09 13:01:56

### Changed

- Update PolicyEngine US to 0.417.2

## [1.10.35] - 2023-08-08 23:58:41

### Changed

- Update PolicyEngine US to 0.417.1

## [1.10.34] - 2023-08-08 21:29:25

### Changed

- Update PolicyEngine US to 0.417.0

## [1.10.33] - 2023-08-08 17:29:33

### Changed

- Update PolicyEngine US to 0.416.2

## [1.10.32] - 2023-08-08 16:42:14

### Changed

- Update PolicyEngine US to 0.416.1

## [1.10.31] - 2023-08-08 04:47:59

### Changed

- Update PolicyEngine US to 0.416.0

## [1.10.30] - 2023-08-08 01:55:33

### Changed

- Update PolicyEngine CANADA to 0.72.0

## [1.10.29] - 2023-08-08 01:37:47

### Changed

- Update PolicyEngine US to 0.415.0

## [1.10.28] - 2023-08-07 23:16:38

### Changed

- Update PolicyEngine US to 0.411.0

## [1.10.27] - 2023-08-07 18:57:05

### Changed

- Update PolicyEngine US to 0.410.2

## [1.10.26] - 2023-08-07 01:43:03

### Changed

- Update PolicyEngine US to 0.410.1

## [1.10.25] - 2023-08-07 01:29:22

### Changed

- Update PolicyEngine CANADA to 0.71.0

## [1.10.24] - 2023-08-06 22:47:51

### Changed

- Update PolicyEngine US to 0.410.0

## [1.10.23] - 2023-08-06 17:48:35

### Changed

- Update PolicyEngine US to 0.409.3

## [1.10.22] - 2023-08-06 16:20:58

### Changed

- Update PolicyEngine US to 0.409.2

## [1.10.21] - 2023-08-05 21:53:51

### Changed

- Update PolicyEngine US to 0.409.1

## [1.10.20] - 2023-08-05 04:13:06

### Changed

- Update PolicyEngine US to 0.409.0

## [1.10.19] - 2023-08-05 01:02:31

### Changed

- Update PolicyEngine US to 0.408.0

## [1.10.18] - 2023-08-03 06:39:40

### Changed

- Update PolicyEngine US to 0.407.0

## [1.10.17] - 2023-08-03 05:40:18

### Changed

- Update PolicyEngine US to 0.405.0

## [1.10.16] - 2023-08-02 18:20:03

### Changed

- Update PolicyEngine US to 0.403.3

## [1.10.15] - 2023-08-02 14:17:54

### Changed

- Update PolicyEngine US to 0.403.2

## [1.10.14] - 2023-08-02 04:14:44

### Changed

- Update PolicyEngine US to 0.403.1

## [1.10.13] - 2023-08-02 01:44:23

### Changed

- Update PolicyEngine US to 0.403.0

## [1.10.12] - 2023-08-01 01:57:53

### Changed

- Update PolicyEngine US to 0.402.0

## [1.10.11] - 2023-07-31 22:59:44

### Changed

- Update PolicyEngine US to 0.401.5

## [1.10.10] - 2023-07-31 21:06:14

### Changed

- Available US years from {2023,2024,2022} to {2023,2022,2021}.
- Update PolicyEngine US to 0.401.4.

### Fixed

- Include all US states in country.py and alphabetize them.

## [1.10.9] - 2023-07-31 16:22:11

### Changed

- Update PolicyEngine US to 0.401.2

## [1.10.8] - 2023-07-30 17:10:51

### Changed

- Update PolicyEngine US to 0.401.1

## [1.10.7] - 2023-07-28 15:50:30

### Changed

- Update PolicyEngine US to 0.401.0

## [1.10.6] - 2023-07-28 03:59:07

### Changed

- Rename nj_child_tax_credit to nj_ctc in tests, following policyengine-us.

## [1.10.5] - 2023-07-28 02:54:37

### Changed

- Update PolicyEngine US to 0.400.0

## [1.10.4] - 2023-07-28 01:05:20

### Changed

- Update PolicyEngine US to 0.397.0

## [1.10.3] - 2023-07-27 18:40:46

### Changed

- Update PolicyEngine US to 0.396.0

## [1.10.2] - 2023-07-27 13:13:12

### Changed

- Update PolicyEngine US to 0.394.0

## [1.10.1] - 2023-07-27 12:30:32

### Changed

- Update PolicyEngine US to 0.393.0

## [1.10.0] - 2023-07-26 17:15:02

### Changed

- PolicyEngine US bumped to 0.390.0
- Correct state income tax variable used to distinguish State revenues.

## [1.9.30] - 2023-07-25 17:49:15

### Changed

- Update PolicyEngine US to 0.389.1

## [1.9.29] - 2023-07-25 13:09:35

### Changed

- Update PolicyEngine US to 0.388.0

## [1.9.28] - 2023-07-25 10:21:27

### Changed

- Update PolicyEngine UK to 0.54.0

## [1.9.27] - 2023-07-24 17:40:59

### Changed

- Update PolicyEngine US to 0.387.1

## [1.9.26] - 2023-07-22 04:07:48

### Changed

- Update PolicyEngine US to 0.386.0

## [1.9.25] - 2023-07-21 04:17:40

### Changed

- Update PolicyEngine US to 0.380.0

## [1.9.24] - 2023-07-21 03:41:10

### Changed

- Update PolicyEngine US to 0.379.0

## [1.9.23] - 2023-07-20 19:59:47

### Changed

- Update PolicyEngine US to 0.377.1

## [1.9.22] - 2023-07-20 14:50:07

### Changed

- Update PolicyEngine US to 0.373.0

## [1.9.21] - 2023-07-19 19:22:42

### Changed

- Update PolicyEngine CANADA to 0.70.0

## [1.9.20] - 2023-07-19 16:20:35

### Changed

- Update PolicyEngine US to 0.371.0

## [1.9.19] - 2023-07-19 13:39:55

### Changed

- Update PolicyEngine US to 0.370.1

## [1.9.18] - 2023-07-19 00:07:55

### Changed

- Update PolicyEngine US to 0.370.0

## [1.9.17] - 2023-07-18 21:27:24

### Changed

- Update PolicyEngine US to 0.369.0

## [1.9.16] - 2023-07-18 02:30:30

### Changed

- Update PolicyEngine US to 0.368.1

## [1.9.15] - 2023-07-17 17:25:19

### Changed

- Update PolicyEngine UK to 0.53.0

## [1.9.14] - 2023-07-16 21:31:32

### Changed

- Update PolicyEngine US to 0.367.0

## [1.9.13] - 2023-07-16 15:31:30

### Changed

- Update PolicyEngine US to 0.366.0

## [1.9.12] - 2023-07-16 00:58:08

### Changed

- Update PolicyEngine US to 0.365.0

## [1.9.11] - 2023-07-14 08:13:02

### Changed

- Update PolicyEngine US to 0.364.1

## [1.9.10] - 2023-07-13 21:29:52

### Changed

- Update PolicyEngine US to 0.363.0

## [1.9.9] - 2023-07-13 05:28:51

### Changed

- Update PolicyEngine US to 0.362.0

## [1.9.8] - 2023-07-12 12:09:54

### Changed

- Update PolicyEngine US to 0.360.1

## [1.9.7] - 2023-07-10 21:46:04

### Changed

- Update PolicyEngine US to 0.360.0

## [1.9.6] - 2023-07-10 20:20:40

### Fixed

- /economy endpoint was being cached with falsk caching and is breaking functionality, was added by mistake. There was already a different kind of caching for this endpoint that works fine.

## [1.9.5] - 2023-07-10 18:40:06

### Changed

- Update PolicyEngine US to 0.359.1

## [1.9.4] - 2023-07-10 12:55:56

### Changed

- Update PolicyEngine US to 0.359.0

## [1.9.3] - 2023-07-09 21:01:45

### Changed

- Update PolicyEngine UK to 0.52.0

## [1.9.2] - 2023-07-08 15:49:06

### Changed

- Update PolicyEngine US to 0.358.0

## [1.9.1] - 2023-07-06 19:05:11

### Changed

- Update PolicyEngine US to 0.357.1

## [1.9.0] - 2023-07-06 16:44:51

### Changed

- PolicyEngine Israel update to 0.1.0.

## [1.8.0] - 2023-07-06 11:48:31

### Added

- UK program breakdowns.

## [1.7.1] - 2023-07-06 05:37:06

### Changed

- Update PolicyEngine US to 0.357.0

## [1.7.0] - 2023-07-05 16:06:19

### Added

- Israel country starter.

## [1.6.43] - 2023-07-05 15:35:46

### Added

- Flask-Cashing setup against redis, supper simple hashing to identify requests.
- /calculate endpoint is now be cached, thus repeated calls should be really fast.

## [1.6.42] - 2023-07-04 13:08:23

### Changed

- Update PolicyEngine US to 0.356.0

## [1.6.41] - 2023-07-04 11:26:58

### Changed

- Update PolicyEngine US to 0.354.0

## [1.6.40] - 2023-07-04 01:41:28

### Changed

- Update PolicyEngine US to 0.353.0

## [1.6.39] - 2023-07-04 00:32:24

### Changed

- Update PolicyEngine US to 0.352.0

## [1.6.38] - 2023-07-03 15:31:56

### Changed

- Update PolicyEngine US to 0.350.1

## [1.6.37] - 2023-07-03 04:24:45

### Changed

- Update PolicyEngine US to 0.350.0

## [1.6.36] - 2023-07-03 04:07:51

### Changed

- Update PolicyEngine CANADA to 0.69.0

## [1.6.35] - 2023-07-03 02:13:16

### Changed

- Update PolicyEngine US to 0.348.0

## [1.6.34] - 2023-07-02 04:20:22

### Changed

- Update PolicyEngine US to 0.346.2

## [1.6.33] - 2023-06-30 05:58:36

### Changed

- Update PolicyEngine US to 0.346.0

## [1.6.32] - 2023-06-29 20:59:39

### Changed

- Update PolicyEngine US to 0.345.12

## [1.6.31] - 2023-06-29 17:01:22

### Changed

- Update PolicyEngine CANADA to 0.68.0

## [1.6.30] - 2023-06-29 16:35:44

### Changed

- Update PolicyEngine US to 0.345.1

## [1.6.29] - 2023-06-29 14:13:02

### Changed

- Update PolicyEngine US to 0.345.0

## [1.6.28] - 2023-06-29 04:33:22

### Changed

- Update PolicyEngine US to 0.342.0

## [1.6.27] - 2023-06-26 03:06:30

### Changed

- Update PolicyEngine US to 0.341.0

## [1.6.26] - 2023-06-26 02:08:41

### Changed

- Update PolicyEngine US to 0.340.0

## [1.6.25] - 2023-06-24 21:40:15

### Changed

- Update PolicyEngine US to 0.339.1

## [1.6.24] - 2023-06-23 19:00:27

### Changed

- Update PolicyEngine US to 0.339.0

## [1.6.23] - 2023-06-23 03:44:31

### Changed

- Update PolicyEngine US to 0.338.0

## [1.6.22] - 2023-06-22 01:04:05

### Changed

- Update PolicyEngine US to 0.337.1

## [1.6.21] - 2023-06-20 19:57:17

### Changed

- Update PolicyEngine UK to 0.51.1

## [1.6.20] - 2023-06-19 18:45:36

### Changed

- Update PolicyEngine US to 0.335.1

## [1.6.19] - 2023-06-18 10:23:47

### Changed

- Update PolicyEngine UK to 0.51.0

## [1.6.18] - 2023-06-12 15:24:50

### Changed

- Update PolicyEngine US to 0.335.0

## [1.6.17] - 2023-06-08 22:19:10

### Changed

- Update PolicyEngine US to 0.334.0

## [1.6.16] - 2023-06-07 18:23:59

### Changed

- Alter POST to /{country_id}/policy and /{country_id}/household to return 201 instead of 200.

## [1.6.15] - 2023-06-05 09:40:02

### Fixed

- Issues causing errors when running a local debug version (DB query parsing errors).

## [1.6.14] - 2023-06-01 03:31:40

### Changed

- Update PolicyEngine CANADA to 0.67.0

## [1.6.13] - 2023-06-01 00:30:23

### Changed

- Update PolicyEngine US to 0.331.0

## [1.6.12] - 2023-05-31 04:35:03

### Changed

- Update PolicyEngine US to 0.330.1

## [1.6.11] - 2023-05-30 16:37:02

### Changed

- Update PolicyEngine CANADA to 0.66.0

## [1.6.10] - 2023-05-30 16:31:32

### Changed

- Update PolicyEngine US to 0.330.0

## [1.6.9] - 2023-05-30 09:52:41

### Changed

- Add '.yaml' extension to 'test_get_search_malformed_country_id'

## [1.6.8] - 2023-05-30 09:51:44

### Changed

- Added debug-test script to Makefile

## [1.6.7] - 2023-05-29 06:46:58

### Changed

- Update PolicyEngine US to 0.329.3

## [1.6.6] - 2023-05-28 20:58:14

### Changed

- Update PolicyEngine CANADA to 0.65.0

## [1.6.5] - 2023-05-28 17:35:41

### Changed

- Update PolicyEngine US to 0.329.2

## [1.6.4] - 2023-05-28 02:58:36

### Changed

- Update PolicyEngine UK to 0.50.1

## [1.6.3] - 2023-05-27 23:42:52

### Changed

- Update PolicyEngine CANADA to 0.64.0

## [1.6.2] - 2023-05-27 18:24:22

### Changed

- Update PolicyEngine US to 0.329.1

## [1.6.1] - 2023-05-27 17:25:33

### Changed

- Update PolicyEngine US to 0.329.0

## [1.6.0] - 2023-05-27 16:18:12

### Added

- Python 3.10 support by upgrading each country package.

## [1.5.27] - 2023-05-26 19:52:18

### Changed

- Update PolicyEngine CANADA to 0.62.0

## [1.5.26] - 2023-05-25 05:47:07

### Changed

- Update PolicyEngine US to 0.321.0

## [1.5.25] - 2023-05-24 05:01:48

### Changed

- Update PolicyEngine UK to 0.49.1

## [1.5.24] - 2023-05-23 08:22:25

### Changed

- Update PolicyEngine US to 0.320.1

## [1.5.23] - 2023-05-23 05:59:11

### Changed

- Update PolicyEngine CANADA to 0.61.0

## [1.5.22] - 2023-05-23 04:31:15

### Changed

- Update PolicyEngine US to 0.320.0

## [1.5.21] - 2023-05-23 03:50:49

### Changed

- Update PolicyEngine US to 0.319.0

## [1.5.20] - 2023-05-21 12:38:28

### Changed

- Add code to data/data.py to check whether or not app is in debug mode before executing remote db connection

## [1.5.19] - 2023-05-21 12:24:11

### Changed

- Alter /{country_id}/search endpoint to return 404 with malformed country_id

## [1.5.18] - 2023-05-21 12:16:08

### Changed

- Update GitHub actions/checkout from v2 to v3

## [1.5.17] - 2023-05-21 03:19:00

### Changed

- Update PolicyEngine US to 0.318.0

## [1.5.16] - 2023-05-20 15:12:21

### Changed

- Update PolicyEngine CANADA to 0.60.0

## [1.5.15] - 2023-05-18 12:51:41

### Fixed

- Added null check before keys() in household calculations.

## [1.5.14] - 2023-05-18 10:17:15

### Changed

- Update PolicyEngine CANADA to 0.59.0

## [1.5.13] - 2023-05-16 05:04:25

### Changed

- Update PolicyEngine US to 0.317.0

## [1.5.12] - 2023-05-16 03:14:55

### Changed

- Update PolicyEngine US to 0.316.1

## [1.5.11] - 2023-05-12 06:59:29

### Changed

- Updated OpenAPI spec

## [1.5.10] - 2023-05-10 22:41:40

### Changed

- Update PolicyEngine US to 0.316.0

## [1.5.9] - 2023-05-10 20:28:50

### Changed

- Update PolicyEngine CANADA to 0.58.0

## [1.5.8] - 2023-05-08 05:22:06

### Changed

- Update PolicyEngine CANADA to 0.56.0

## [1.5.7] - 2023-05-05 03:08:40

### Changed

- Update PolicyEngine US to 0.314.1

## [1.5.6] - 2023-05-04 19:53:48

### Changed

- Update PolicyEngine US to 0.314.0

## [1.5.5] - 2023-05-04 00:57:08

### Changed

- Update PolicyEngine US to 0.313.0

## [1.5.4] - 2023-05-03 21:55:57

### Changed

- Update PolicyEngine US to 0.311.0

## [1.5.3] - 2023-05-03 04:45:39

### Changed

- Update PolicyEngine CANADA to 0.54.0

## [1.5.2] - 2023-05-01 03:40:47

### Changed

- Update PolicyEngine US to 0.310.1

## [1.5.1] - 2023-05-01 01:46:45

### Changed

- Update PolicyEngine US to 0.310.0

## [1.5.0] - 2023-04-30 18:40:32

### Added

- Debugging statements to track economic impacts better.
- State tax revenue budgetary impacts.

## [1.4.8] - 2023-04-29 21:00:21

### Fixed

- Error handling correctly captures some integrity errors.

## [1.4.7] - 2023-04-28 20:54:59

### Changed

- Update PolicyEngine CANADA to 0.52.0

## [1.4.6] - 2023-04-28 03:51:32

### Changed

- Update PolicyEngine CANADA to 0.50.0

## [1.4.5] - 2023-04-28 03:34:10

### Changed

- Update PolicyEngine US to 0.307.0

## [1.4.4] - 2023-04-28 03:18:58

### Changed

- Update PolicyEngine CANADA to 0.49.0

## [1.4.3] - 2023-04-27 02:10:18

### Changed

- Update PolicyEngine US to 0.303.0

## [1.4.2] - 2023-04-26 13:35:39

### Changed

- Update PolicyEngine US to 0.302.0

## [1.4.1] - 2023-04-26 05:37:13

### Changed

- Update PolicyEngine US to 0.301.2

## [1.4.0] - 2023-04-25 15:36:37

### Added

- NYC region option for US economic impacts.

## [1.3.10] - 2023-04-24 17:58:57

### Fixed

- EndBug/add-and-commit updated to remove git commit warnings.

## [1.3.9] - 2023-04-24 14:21:57

### Changed

- Update PolicyEngine UK to 0.48.0

## [1.3.8] - 2023-04-24 12:31:11

### Changed

- Update PolicyEngine UK to 0.46.0

## [1.3.7] - 2023-04-24 05:53:25

### Changed

- Update PolicyEngine CANADA to 0.47.1

## [1.3.6] - 2023-04-22 16:57:44

### Changed

- Update PolicyEngine US to 0.299.0

## [1.3.5] - 2023-04-22 02:11:15

### Changed

- Update PolicyEngine US to 0.298.0

## [1.3.4] - 2023-04-21 16:08:03

### Changed

- Update PolicyEngine US to 0.297.0

## [1.3.3] - 2023-04-21 13:08:28

### Changed

- Update PolicyEngine us to 0.296.0

## [1.3.2] - 2023-04-21 10:31:05

### Added

- OpenAPI v3 specification.

## [1.3.1] - 2023-04-20 16:12:11

### Changed

- Update PolicyEngine us to 0.295.1

## [1.3.0] - 2023-04-19 13:27:05

### Changed

- PolicyEngine Nigeria bumped to 0.5.1.

## [1.2.5] - 2023-04-19 04:09:56

### Changed

- Update PolicyEngine canada to 0.47.0

## [1.2.4] - 2023-04-18 01:04:35

### Changed

- Update PolicyEngine canada to 0.46.0

## [1.2.3] - 2023-04-17 15:58:45

### Changed

- Update PolicyEngine us to 0.295.0

## [1.2.2] - 2023-04-17 00:12:13

### Changed

- Update PolicyEngine us to 0.294.0

## [1.2.1] - 2023-04-16 14:01:29

### Fixed

- Policy re-labelling is now working correctly.

## [1.2.0] - 2023-04-15 11:39:17

### Added

- Poverty racial breakdowns for the US.

## [1.1.7] - 2023-04-15 08:51:54

### Changed

- Update PolicyEngine uk to 0.45.1

## [1.1.6] - 2023-04-15 03:28:59

### Changed

- Update PolicyEngine us to 0.289.0

## [1.1.5] - 2023-04-14 10:19:47

### Changed

- Update PolicyEngine us to 0.286.2

## [1.1.4] - 2023-04-13 03:46:26

### Changed

- Update PolicyEngine us to 0.286.0

## [1.1.3] - 2023-04-12 19:34:47

### Fixed

- Bug causing zeroed out baseline household values.

## [1.1.2] - 2023-04-12 10:01:08

### Fixed

- Economic impact runtimes cut down by 9 seconds.

## [1.1.1] - 2023-04-12 09:20:43

### Changed

- Performance improvements

## [1.1.0] - 2023-04-11 22:40:05

### Added

- /search endpoint for variables and parameters.

## [1.0.7] - 2023-04-11 20:16:23

### Changed

- Update PolicyEngine us to 0.285.1

## [1.0.6] - 2023-04-11 05:00:41

### Changed

- Update PolicyEngine us to 0.285.0

## [1.0.5] - 2023-04-10 22:00:53

### Changed

- Update PolicyEngine us to 0.282.0

## [1.0.4] - 2023-04-10 03:45:20

### Changed

- Update PolicyEngine us to 0.281.0

## [1.0.3] - 2023-04-08 12:51:41

### Changed

- Update PolicyEngine us to 0.280.0

## [1.0.2] - 2023-04-07 17:24:42

### Changed

- Update PolicyEngine us to 0.279.0

## [1.0.1] - 2023-04-07 13:06:13

### Added

- Added missing `redis` Python dependency.

## [1.0.0] - 2023-04-07 11:34:18

### Changed

- Use redis server workers to process jobs in a more standardised way.
- Combine main and compute servers into a single server.

## [0.13.25] - 2023-04-06 18:42:39

### Changed

- Bump policyengine-us to 0.278.0

## [0.13.24] - 2023-04-06 14:19:38

### Changed

- Bump policyengine-us to 0.277.0

## [0.13.23] - 2023-04-06 04:17:45

### Changed

- Bump policyengine-canada to 0.45.0

## [0.13.22] - 2023-04-05 17:17:50

### Changed

- Bump policyengine-us to 0.276.0

## [0.13.21] - 2023-04-05 03:28:24

### Changed

- Bump policyengine-us to 0.275.0

## [0.13.20] - 2023-04-04 14:37:18

### Changed

- Bump policyengine-us to 0.273.0

## [0.13.19] - 2023-04-04 04:49:17

### Changed

- Bump policyengine-us to 0.271.0

## [0.13.18] - 2023-04-03 17:43:08

### Changed

- Bump policyengine-us to 0.268.0

## [0.13.17] - 2023-04-03 16:26:44

### Changed

- Bump policyengine-us to 0.267.0

## [0.13.16] - 2023-04-02 20:56:40

### Changed

- Bump policyengine-us to 0.266.0

## [0.13.15] - 2023-04-02 02:42:16

### Changed

- Bump policyengine-us to 0.264.0

## [0.13.14] - 2023-04-01 15:35:04

### Changed

- Bump policyengine-us to 0.263.5

## [0.13.13] - 2023-04-01 09:51:26

### Changed

- Bump policyengine-uk to 0.45.0

## [0.13.12] - 2023-03-31 06:50:42

### Changed

- Bump policyengine-us to 0.263.4

## [0.13.11] - 2023-03-30 21:54:35

### Changed

- Bump policyengine-us to 0.263.3

## [0.13.10] - 2023-03-30 18:23:20

### Changed

- Bump policyengine-us to 0.263.2

## [0.13.9] - 2023-03-30 15:00:19

### Changed

- Bump policyengine-uk to 0.44.3

## [0.13.8] - 2023-03-30 05:26:32

### Changed

- Bump policyengine-us to 0.263.1

## [0.13.7] - 2023-03-30 04:29:37

### Changed

- Bump policyengine-us to 0.263.0

## [0.13.6] - 2023-03-30 02:39:15

### Changed

- Bump policyengine-us to 0.262.0

## [0.13.5] - 2023-03-30 01:38:20

### Changed

- Bump policyengine-canada to 0.44.0

## [0.13.4] - 2023-03-29 23:53:23

### Changed

- Bump policyengine-us to 0.261.1

## [0.13.3] - 2023-03-29 12:36:32

### Changed

- Bump policyengine-uk to 0.44.2

## [0.13.2] - 2023-03-29 04:43:52

### Changed

- Bump policyengine-us to 0.260.0

## [0.13.1] - 2023-03-28 23:06:53

### Fixed

- OpenAI API key included in API environments.

## [0.13.0] - 2023-03-28 22:25:38

### Added

- /analysis endpoint for policy analyses by GPT-4.

## [0.12.4] - 2023-03-28 03:57:32

### Changed

- Bump policyengine-canada to 0.43.0

## [0.12.3] - 2023-03-27 21:43:16

### Changed

- Bump policyengine-us to 0.259.0

## [0.12.2] - 2023-03-26 00:58:55

### Fixed

- Bumped UK system.

## [0.12.1] - 2023-03-26 00:21:42

### Fixed

- UK microsimulation runs download the correct data.

## [0.12.0] - 2023-03-25 16:34:24

### Changed

- Country packages updated.

## [0.11.18] - 2023-03-22 01:10:33

### Changed

- Server sizes increased to 3x CPU/18GB RAM

## [0.11.17] - 2023-03-21 01:05:37

### Changed

- Bump policyengine-us to 0.251.1

## [0.11.16] - 2023-03-20 16:02:46

### Changed

- Bump policyengine-us to 0.251.0

## [0.11.15] - 2023-03-20 14:15:31

### Changed

- Bump policyengine-canada to 0.42.2

## [0.11.14] - 2023-03-20 05:30:25

### Changed

- Bump policyengine-us to 0.250.0

## [0.11.13] - 2023-03-19 22:56:28

### Fixed

- API deployment timeout increased.

## [0.11.12] - 2023-03-19 16:51:00

### Changed

- Bump policyengine-us to 0.248.0

## [0.11.11] - 2023-03-18 05:55:38

### Changed

- Bump policyengine-us to 0.247.0

## [0.11.10] - 2023-03-15 11:50:35

### Changed

- Bump policyengine-uk to 0.43.0

## [0.11.9] - 2023-03-14 23:14:23

### Changed

- Bump policyengine-canada to 0.42.1

## [0.11.8] - 2023-03-14 21:24:10

### Changed

- Bump policyengine-us to 0.243.0
- Bump policyengine-uk to 0.42.1

## [0.11.7] - 2023-03-13 21:42:38

### Changed

- Bump policyengine-us to 0.241.0

## [0.11.6] - 2023-03-13 02:07:52

### Changed

- Bump policyengine-us to 0.240.0

## [0.11.5] - 2023-03-12 20:28:43

### Changed

- Bump policyengine-us to 0.239.1

## [0.11.4] - 2023-03-11 14:06:40

### Changed

- Bump policyengine-us to 0.238.1

## [0.11.3] - 2023-03-11 04:06:45

### Changed

- Bump policyengine-us to 0.238.0

## [0.11.2] - 2023-03-10 23:58:53

### Changed

- Bump policyengine-us to 0.237.1

## [0.11.1] - 2023-03-10 12:07:43

### Fixed

- Bug causing an error when returning the available API versions for economic impacts.

## [0.11.0] - 2023-03-09 20:53:00

### Added

- Per-package version labelling.

## [0.10.3] - 2023-03-09 16:45:30

### Changed

- Bump policyengine-us to 0.234.0

## [0.10.2] - 2023-03-08 22:47:20

### Changed

- Bump policyengine-us to 0.231.2

## [0.10.1] - 2023-03-08 17:29:42

### Changed

- Bump policyengine-us to 0.231.1

## [0.10.0] - 2023-03-08 16:43:27

### Added

- Gender poverty breakdowns.

## [0.9.22] - 2023-03-08 13:49:47

### Changed

- Bump policyengine-us to 0.230.1

## [0.9.21] - 2023-03-07 22:42:56

### Changed

- Bump policyengine-us to 0.230.0

## [0.9.20] - 2023-03-07 14:51:27

### Changed

- Bump policyengine-us to 0.229.0

## [0.9.19] - 2023-03-07 07:17:36

### Changed

- Bump policyengine-us to 0.228.0

## [0.9.18] - 2023-03-07 04:12:26

### Changed

- Bump policyengine-us to 0.227.1

## [0.9.17] - 2023-03-06 18:56:56

### Changed

- Bump policyengine-us to 0.227.0

## [0.9.16] - 2023-03-06 00:08:40

### Changed

- Bump policyengine-us to 0.226.0

## [0.9.15] - 2023-03-04 23:03:18

### Changed

- Bump policyengine-us to 0.225.0

## [0.9.14] - 2023-03-04 00:28:26

### Changed

- Bump policyengine-uk to 0.42.0

## [0.9.13] - 2023-03-03 23:59:10

### Changed

- Bump policyengine-us to 0.224.1

## [0.9.12] - 2023-03-03 22:52:11

### Changed

- Bump policyengine-us to 0.224.0

## [0.9.11] - 2023-03-02 22:16:32

### Changed

- Bump policyengine-us to 0.223.0

## [0.9.10] - 2023-03-02 12:13:37

### Changed

- Bump policyengine-uk to 0.41.11

## [0.9.9] - 2023-03-02 03:27:22

### Changed

- Bump policyengine-us to 0.222.1

## [0.9.8] - 2023-03-01 02:03:27

### Changed

- Bump policyengine-us to 0.222.0

## [0.9.7] - 2023-02-28 06:02:45

### Changed

- Bump policyengine-us to 0.220.5

## [0.9.6] - 2023-02-28 05:32:03

### Changed

- Bump policyengine-canada to 0.42.0

## [0.9.5] - 2023-02-27 17:41:36

### Changed

- Bump policyengine-us to 0.220.4

## [0.9.4] - 2023-02-27 17:15:05

### Changed

- Bump policyengine-uk to 0.41.9

## [0.9.3] - 2023-02-27 15:54:05

### Changed

- Bump policyengine-uk to 0.41.7

## [0.9.2] - 2023-02-27 15:45:32

### Changed

- Reduced CPU counts by half.

## [0.9.1] - 2023-02-27 01:09:22

### Changed

- Bump policyengine-us to 0.220.3

## [0.9.0] - 2023-02-25 13:33:17

### Added

- UK wealth decile charts.

## [0.8.19] - 2023-02-24 15:17:14

### Changed

- Bump policyengine-us to 0.220.2

## [0.8.18] - 2023-02-23 21:22:55

### Changed

- Bump policyengine-canada to 0.40.0

## [0.8.17] - 2023-02-23 15:51:55

### Changed

- Bump policyengine-canada to 0.39.0

## [0.8.16] - 2023-02-23 15:20:41

### Changed

- Bump policyengine-us to 0.220.1

## [0.8.15] - 2023-02-19 06:30:38

### Changed

- Bump policyengine-us to 0.219.0

## [0.8.14] - 2023-02-17 05:49:09

### Changed

- Bump policyengine-us to 0.218.0

## [0.8.13] - 2023-02-17 04:57:13

### Changed

- Bump policyengine-us to 0.217.1

## [0.8.12] - 2023-02-17 00:19:06

### Changed

- Bump policyengine-us to 0.217.0

## [0.8.11] - 2023-02-16 23:26:53

### Changed

- Bump policyengine-us to 0.216.0

## [0.8.10] - 2023-02-14 22:11:05

### Changed

- Bump policyengine-us to 0.215.1

## [0.8.9] - 2023-02-14 05:25:20

### Changed

- Bump policyengine-us to 0.214.4

## [0.8.8] - 2023-02-14 02:13:09

### Changed

- Bump policyengine-canada to 0.38.1

## [0.8.7] - 2023-02-14 01:27:14

### Changed

- Bump policyengine-us to 0.214.2

## [0.8.6] - 2023-02-13 01:22:44

### Changed

- Bump policyengine-us to 0.214.1

## [0.8.5] - 2023-02-12 20:30:54

### Changed

- Bump policyengine-us to 0.214.0

## [0.8.4] - 2023-02-12 02:22:28

### Changed

- Bump policyengine-canada to 0.38.0

## [0.8.3] - 2023-02-11 15:17:04

### Added

- Economy options to enable NG's policy editor.

## [0.8.2] - 2023-02-11 15:02:33

### Changed

- Bump policyengine-us to 0.213.4

## [0.8.1] - 2023-02-11 14:11:31

### Changed

- Updated PolicyEngine-NG.

## [0.8.0] - 2023-02-11 13:30:36

### Added

- PolicyEngine Nigeria.

## [0.7.30] - 2023-02-10 16:43:19

### Changed

- Bump policyengine-us to 0.213.3

## [0.7.29] - 2023-02-10 04:51:38

### Changed

- Bump policyengine-canada to 0.36.0

## [0.7.28] - 2023-02-10 04:38:09

### Changed

- Bump policyengine-us to 0.213.2

## [0.7.27] - 2023-02-10 03:55:05

### Changed

- Bump policyengine-canada to 0.35.0

## [0.7.26] - 2023-02-09 00:32:55

### Changed

- Bump policyengine-us to 0.213.1

## [0.7.25] - 2023-02-08 04:47:41

### Changed

- Bump policyengine-us to 0.213.0

## [0.7.24] - 2023-02-08 04:02:04

### Changed

- Bump policyengine-canada to 0.33.0

## [0.7.23] - 2023-02-07 20:38:54

### Fixed

- A bug causing zero-parameter reforms to not update.

## [0.7.22] - 2023-02-07 20:15:43

### Fixed

- Bug causing some parameters to be incorrectly parsed as strings.

## [0.7.21] - 2023-02-07 05:47:10

### Changed

- Bump policyengine-us to 0.211.1

## [0.7.20] - 2023-02-06 22:03:16

### Changed

- Bump policyengine-us to 0.211.0

## [0.7.19] - 2023-02-05 18:06:59

### Changed

- Bump policyengine-us to 0.210.1

## [0.7.18] - 2023-02-04 21:51:21

### Changed

- Bump policyengine-canada to 0.32.0

## [0.7.17] - 2023-02-04 03:53:22

### Changed

- Bump policyengine-us to 0.209.3

## [0.7.16] - 2023-02-03 15:48:13

### Changed

- Bump policyengine-us to 0.209.2

## [0.7.15] - 2023-02-02 17:07:41

### Changed

- Bump policyengine-us to 0.208.0

## [0.7.14] - 2023-02-02 15:16:16

### Changed

- Bump policyengine-canada to 0.31.0

## [0.7.13] - 2023-02-02 12:09:24

### Fixed

- Bug causing state taxes to be frozen in all cases.

## [0.7.12] - 2023-02-02 00:38:48

### Changed

- Bump policyengine-us to 0.207.3

## [0.7.11] - 2023-02-01 04:25:51

### Changed

- Bump policyengine-us to 0.207.2

## [0.7.10] - 2023-02-01 00:59:41

### Changed

- Bump policyengine-us to 0.207.1

## [0.7.9] - 2023-01-31 23:47:18

### Changed

- Bump policyengine-us to 0.207.0

## [0.7.8] - 2023-01-31 19:14:58

### Changed

- Bump policyengine-us to 0.205.3

## [0.7.7] - 2023-01-31 18:49:17

### Changed

- Bump policyengine-canada to 0.30.0

## [0.7.6] - 2023-01-31 17:51:10

### Changed

- Bump policyengine-us to 0.205.1

## [0.7.5] - 2023-01-31 01:21:40

### Changed

- Bump policyengine-canada to 0.29.0

## [0.7.4] - 2023-01-29 08:27:28

### Fixed

- Bug affecting some household reform impacts.

## [0.7.3] - 2023-01-29 03:33:18

### Changed

- Bump policyengine-us to 0.203.10

## [0.7.2] - 2023-01-28 16:15:45

### Changed

- Core bumped.

## [0.7.1] - 2023-01-28 03:23:35

### Changed

- Bump policyengine-canada to 0.27.1

## [0.7.0] - 2023-01-27 23:17:23

### Added

- Performance improvements for the Households API (caching, mostly).

## [0.6.10] - 2023-01-27 13:13:59

### Changed

- Bump policyengine-uk to 0.41.2

## [0.6.9] - 2023-01-27 10:06:09

### Changed

- Bump policyengine-uk to 0.41.1

## [0.6.8] - 2023-01-26 20:27:31

### Changed

- Bump policyengine-uk to 0.41.0

## [0.6.7] - 2023-01-25 21:56:55

### Changed

- Bump policyengine-uk to 0.40.0

## [0.6.6] - 2023-01-25 20:34:54

### Changed

- Bump policyengine-us to 0.203.8

## [0.6.5] - 2023-01-25 10:27:08

### Fixed

- UK microsimulation outputs.

## [0.6.4] - 2023-01-24 16:35:50

### Fixed

- US national impacts freeze State tax as reported.
- Erroring reform impacts return an error message and don't just repeat endlessly.

## [0.6.3] - 2023-01-23 18:57:17

### Fixed

- /calculate endpoints return under the results key.

## [0.6.2] - 2023-01-22 14:48:37

### Changed

- /calculate endpoint runtime cut by around 70%.

## [0.6.1] - 2023-01-20 17:35:47

### Changed

- Bump policyengine-canada to 0.23.0

## [0.6.0] - 2023-01-19 23:29:37

### Changed

- UK and US systems updated.

## [0.5.7] - 2023-01-16 20:33:01

### Changed

- Bump policyengine-us to 0.200.7

## [0.5.6] - 2023-01-12 21:07:37

### Fixed

- Poverty impacts in non-country states.

## [0.5.5] - 2023-01-12 00:36:18

### Changed

- GCP instance counts increased.
- Metadata added for modelled policies.

## [0.5.4] - 2023-01-11 12:38:16

### Added

- Tools to manage policy data from the dashboard.

## [0.5.3] - 2023-01-11 06:21:45

### Changed

- Bump policyengine-uk to 0.38.6

## [0.5.2] - 2023-01-11 06:16:05

### Changed

- Bump policyengine-us to 0.199.6

## [0.5.1] - 2023-01-06 12:43:44

### Fixed

- Variable errors now gracefully handled.

## [0.5.0] - 2023-01-06 11:39:50

### Changed

- Made 2023 the default US simulation year.

## [0.4.2] - 2023-01-03 23:58:16

### Changed

- UK and Canada systems patch-bumped.

## [0.4.1] - 2023-01-03 23:34:13

### Changed

- PolicyEngine US bumped.

## [0.4.0] - 2023-01-03 22:23:44

### Added

- PolicyEngine Canada.

## [0.3.6] - 2022-12-30 17:22:06

### Changed

- Bump policyengine-uk to 0.38.2

## [0.3.5] - 2022-12-30 13:01:48

### Fixed

- Bug where policy reforms changing zeros to fractions were ignored in population impacts.

## [0.3.4] - 2022-12-29 22:28:31

### Fixed

- Population impacts now compute.

## [0.3.3] - 2022-12-29 16:48:25

### Fixed

- Bug where the population impacts would sometimes be killed.

## [0.3.2] - 2022-12-28 23:50:42

### Changed

- Bump policyengine-us to 0.194.3

## [0.3.1] - 2022-12-28 23:47:33

### Changed

- Bump policyengine-uk to 0.38.1

## [0.3.0] - 2022-12-28 21:05:16

### Added

- Deep poverty impacts.

## [0.2.5] - 2022-12-28 18:47:45

### Changed

- Bump policyengine-us to 0.194.2

## [0.2.4] - 2022-12-28 16:36:04

### Added

- Error handling inside error handling.

## [0.2.3] - 2022-12-28 14:45:10

### Fixed

- Negative income handling in the intra-decile chart.

## [0.2.2] - 2022-12-28 12:02:47

### Added

- Error handling and logging.

## [0.2.1] - 2022-12-28 03:50:35

### Changed

- Bump policyengine-uk to 0.38.0

## [0.2.0] - 2022-12-27 22:34:48

### Added

- Error handling for household and economy computations.

## [0.1.12] - 2022-12-27 20:02:12

### Changed

- Bump policyengine-us to 0.194.1

## [0.1.11] - 2022-12-27 12:35:48

### Changed

- Bump policyengine-us to 0.193.1

## [0.1.10] - 2022-12-26 21:01:00

### Changed

- Bump policyengine-us to 0.193.0

## [0.1.9] - 2022-12-25 21:24:14

### Fixed

- Bug causing US impacts to fail.

## [0.1.8] - 2022-12-25 20:21:17

### Fixed

- Bug preventing Compute API runtimes starting.

## [0.1.7] - 2022-12-24 10:28:28

### Fixed

- Bug affecting refundable credit reforms for State filters.

## [0.1.6] - 2022-12-23 18:04:50

### Fixed

- Bug affecting refundable credit reforms for State filters.

## [0.1.5] - 2022-12-20 23:01:56

### Changed

- Bump policyengine-uk to 0.37.6

## [0.1.4] - 2022-12-20 18:50:29

### Fixed

- Updates to the version number clear the visible reform impact database.

## [0.1.3] - 2022-12-20 17:21:07

### Changed

- Bump policyengine-us to 0.190.3

## [0.1.2] - 2022-12-20 15:03:17

### Changed

- Updated PolicyEngine US to 0.190.2.

## [0.1.1] - 2022-12-19 16:29:27

### Added

- Versioning.

## [0.1.0] - 2022-12-19 00:00:00

### Added

- Initial API.



[3.35.2]: https://github.com/PolicyEngine/policyengine-api/compare/3.35.1...3.35.2
[3.35.1]: https://github.com/PolicyEngine/policyengine-api/compare/3.35.0...3.35.1
[3.35.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.34.3...3.35.0
[3.34.3]: https://github.com/PolicyEngine/policyengine-api/compare/3.34.2...3.34.3
[3.34.2]: https://github.com/PolicyEngine/policyengine-api/compare/3.34.1...3.34.2
[3.34.1]: https://github.com/PolicyEngine/policyengine-api/compare/3.34.0...3.34.1
[3.34.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.33.6...3.34.0
[3.33.6]: https://github.com/PolicyEngine/policyengine-api/compare/3.33.5...3.33.6
[3.33.5]: https://github.com/PolicyEngine/policyengine-api/compare/3.33.4...3.33.5
[3.33.4]: https://github.com/PolicyEngine/policyengine-api/compare/3.33.3...3.33.4
[3.33.3]: https://github.com/PolicyEngine/policyengine-api/compare/3.33.2...3.33.3
[3.33.2]: https://github.com/PolicyEngine/policyengine-api/compare/3.33.1...3.33.2
[3.33.1]: https://github.com/PolicyEngine/policyengine-api/compare/3.33.0...3.33.1
[3.33.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.32.0...3.33.0
[3.32.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.31.1...3.32.0
[3.31.1]: https://github.com/PolicyEngine/policyengine-api/compare/3.31.0...3.31.1
[3.31.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.30.4...3.31.0
[3.30.4]: https://github.com/PolicyEngine/policyengine-api/compare/3.30.3...3.30.4
[3.30.3]: https://github.com/PolicyEngine/policyengine-api/compare/3.30.2...3.30.3
[3.30.2]: https://github.com/PolicyEngine/policyengine-api/compare/3.30.1...3.30.2
[3.30.1]: https://github.com/PolicyEngine/policyengine-api/compare/3.30.0...3.30.1
[3.30.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.29.3...3.30.0
[3.29.3]: https://github.com/PolicyEngine/policyengine-api/compare/3.29.2...3.29.3
[3.29.2]: https://github.com/PolicyEngine/policyengine-api/compare/3.29.1...3.29.2
[3.29.1]: https://github.com/PolicyEngine/policyengine-api/compare/3.29.0...3.29.1
[3.29.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.28.22...3.29.0
[3.28.22]: https://github.com/PolicyEngine/policyengine-api/compare/3.28.21...3.28.22
[3.28.21]: https://github.com/PolicyEngine/policyengine-api/compare/3.28.20...3.28.21
[3.28.20]: https://github.com/PolicyEngine/policyengine-api/compare/3.28.19...3.28.20
[3.28.19]: https://github.com/PolicyEngine/policyengine-api/compare/3.28.18...3.28.19
[3.28.18]: https://github.com/PolicyEngine/policyengine-api/compare/3.28.17...3.28.18
[3.28.17]: https://github.com/PolicyEngine/policyengine-api/compare/3.28.16...3.28.17
[3.28.16]: https://github.com/PolicyEngine/policyengine-api/compare/3.28.15...3.28.16
[3.28.15]: https://github.com/PolicyEngine/policyengine-api/compare/3.28.14...3.28.15
[3.28.14]: https://github.com/PolicyEngine/policyengine-api/compare/3.28.13...3.28.14
[3.28.13]: https://github.com/PolicyEngine/policyengine-api/compare/3.28.12...3.28.13
[3.28.12]: https://github.com/PolicyEngine/policyengine-api/compare/3.28.11...3.28.12
[3.28.11]: https://github.com/PolicyEngine/policyengine-api/compare/3.28.10...3.28.11
[3.28.10]: https://github.com/PolicyEngine/policyengine-api/compare/3.28.9...3.28.10
[3.28.9]: https://github.com/PolicyEngine/policyengine-api/compare/3.28.8...3.28.9
[3.28.8]: https://github.com/PolicyEngine/policyengine-api/compare/3.28.7...3.28.8
[3.28.7]: https://github.com/PolicyEngine/policyengine-api/compare/3.28.6...3.28.7
[3.28.6]: https://github.com/PolicyEngine/policyengine-api/compare/3.28.5...3.28.6
[3.28.5]: https://github.com/PolicyEngine/policyengine-api/compare/3.28.4...3.28.5
[3.28.4]: https://github.com/PolicyEngine/policyengine-api/compare/3.28.3...3.28.4
[3.28.3]: https://github.com/PolicyEngine/policyengine-api/compare/3.28.2...3.28.3
[3.28.2]: https://github.com/PolicyEngine/policyengine-api/compare/3.28.1...3.28.2
[3.28.1]: https://github.com/PolicyEngine/policyengine-api/compare/3.28.0...3.28.1
[3.28.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.27.14...3.28.0
[3.27.14]: https://github.com/PolicyEngine/policyengine-api/compare/3.27.13...3.27.14
[3.27.13]: https://github.com/PolicyEngine/policyengine-api/compare/3.27.12...3.27.13
[3.27.12]: https://github.com/PolicyEngine/policyengine-api/compare/3.27.11...3.27.12
[3.27.11]: https://github.com/PolicyEngine/policyengine-api/compare/3.27.10...3.27.11
[3.27.10]: https://github.com/PolicyEngine/policyengine-api/compare/3.27.9...3.27.10
[3.27.9]: https://github.com/PolicyEngine/policyengine-api/compare/3.27.8...3.27.9
[3.27.8]: https://github.com/PolicyEngine/policyengine-api/compare/3.27.7...3.27.8
[3.27.7]: https://github.com/PolicyEngine/policyengine-api/compare/3.27.6...3.27.7
[3.27.6]: https://github.com/PolicyEngine/policyengine-api/compare/3.27.5...3.27.6
[3.27.5]: https://github.com/PolicyEngine/policyengine-api/compare/3.27.4...3.27.5
[3.27.4]: https://github.com/PolicyEngine/policyengine-api/compare/3.27.3...3.27.4
[3.27.3]: https://github.com/PolicyEngine/policyengine-api/compare/3.27.2...3.27.3
[3.27.2]: https://github.com/PolicyEngine/policyengine-api/compare/3.27.1...3.27.2
[3.27.1]: https://github.com/PolicyEngine/policyengine-api/compare/3.27.0...3.27.1
[3.27.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.26.5...3.27.0
[3.26.5]: https://github.com/PolicyEngine/policyengine-api/compare/3.26.4...3.26.5
[3.26.4]: https://github.com/PolicyEngine/policyengine-api/compare/3.26.3...3.26.4
[3.26.3]: https://github.com/PolicyEngine/policyengine-api/compare/3.26.2...3.26.3
[3.26.2]: https://github.com/PolicyEngine/policyengine-api/compare/3.26.1...3.26.2
[3.26.1]: https://github.com/PolicyEngine/policyengine-api/compare/3.26.0...3.26.1
[3.26.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.25.17...3.26.0
[3.25.17]: https://github.com/PolicyEngine/policyengine-api/compare/3.25.16...3.25.17
[3.25.16]: https://github.com/PolicyEngine/policyengine-api/compare/3.25.15...3.25.16
[3.25.15]: https://github.com/PolicyEngine/policyengine-api/compare/3.25.14...3.25.15
[3.25.14]: https://github.com/PolicyEngine/policyengine-api/compare/3.25.13...3.25.14
[3.25.13]: https://github.com/PolicyEngine/policyengine-api/compare/3.25.12...3.25.13
[3.25.12]: https://github.com/PolicyEngine/policyengine-api/compare/3.25.11...3.25.12
[3.25.11]: https://github.com/PolicyEngine/policyengine-api/compare/3.25.10...3.25.11
[3.25.10]: https://github.com/PolicyEngine/policyengine-api/compare/3.25.9...3.25.10
[3.25.9]: https://github.com/PolicyEngine/policyengine-api/compare/3.25.8...3.25.9
[3.25.8]: https://github.com/PolicyEngine/policyengine-api/compare/3.25.7...3.25.8
[3.25.7]: https://github.com/PolicyEngine/policyengine-api/compare/3.25.6...3.25.7
[3.25.6]: https://github.com/PolicyEngine/policyengine-api/compare/3.25.5...3.25.6
[3.25.5]: https://github.com/PolicyEngine/policyengine-api/compare/3.25.4...3.25.5
[3.25.4]: https://github.com/PolicyEngine/policyengine-api/compare/3.25.3...3.25.4
[3.25.3]: https://github.com/PolicyEngine/policyengine-api/compare/3.25.2...3.25.3
[3.25.2]: https://github.com/PolicyEngine/policyengine-api/compare/3.25.1...3.25.2
[3.25.1]: https://github.com/PolicyEngine/policyengine-api/compare/3.25.0...3.25.1
[3.25.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.24.1...3.25.0
[3.24.1]: https://github.com/PolicyEngine/policyengine-api/compare/3.24.0...3.24.1
[3.24.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.23.4...3.24.0
[3.23.4]: https://github.com/PolicyEngine/policyengine-api/compare/3.23.3...3.23.4
[3.23.3]: https://github.com/PolicyEngine/policyengine-api/compare/3.23.2...3.23.3
[3.23.2]: https://github.com/PolicyEngine/policyengine-api/compare/3.23.1...3.23.2
[3.23.1]: https://github.com/PolicyEngine/policyengine-api/compare/3.23.0...3.23.1
[3.23.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.22.17...3.23.0
[3.22.17]: https://github.com/PolicyEngine/policyengine-api/compare/3.22.16...3.22.17
[3.22.16]: https://github.com/PolicyEngine/policyengine-api/compare/3.22.15...3.22.16
[3.22.15]: https://github.com/PolicyEngine/policyengine-api/compare/3.22.14...3.22.15
[3.22.14]: https://github.com/PolicyEngine/policyengine-api/compare/3.22.13...3.22.14
[3.22.13]: https://github.com/PolicyEngine/policyengine-api/compare/3.22.12...3.22.13
[3.22.12]: https://github.com/PolicyEngine/policyengine-api/compare/3.22.11...3.22.12
[3.22.11]: https://github.com/PolicyEngine/policyengine-api/compare/3.22.10...3.22.11
[3.22.10]: https://github.com/PolicyEngine/policyengine-api/compare/3.22.9...3.22.10
[3.22.9]: https://github.com/PolicyEngine/policyengine-api/compare/3.22.8...3.22.9
[3.22.8]: https://github.com/PolicyEngine/policyengine-api/compare/3.22.7...3.22.8
[3.22.7]: https://github.com/PolicyEngine/policyengine-api/compare/3.22.6...3.22.7
[3.22.6]: https://github.com/PolicyEngine/policyengine-api/compare/3.22.5...3.22.6
[3.22.5]: https://github.com/PolicyEngine/policyengine-api/compare/3.22.4...3.22.5
[3.22.4]: https://github.com/PolicyEngine/policyengine-api/compare/3.22.3...3.22.4
[3.22.3]: https://github.com/PolicyEngine/policyengine-api/compare/3.22.2...3.22.3
[3.22.2]: https://github.com/PolicyEngine/policyengine-api/compare/3.22.1...3.22.2
[3.22.1]: https://github.com/PolicyEngine/policyengine-api/compare/3.22.0...3.22.1
[3.22.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.21.1...3.22.0
[3.21.1]: https://github.com/PolicyEngine/policyengine-api/compare/3.21.0...3.21.1
[3.21.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.20.8...3.21.0
[3.20.8]: https://github.com/PolicyEngine/policyengine-api/compare/3.20.7...3.20.8
[3.20.7]: https://github.com/PolicyEngine/policyengine-api/compare/3.20.6...3.20.7
[3.20.6]: https://github.com/PolicyEngine/policyengine-api/compare/3.20.5...3.20.6
[3.20.5]: https://github.com/PolicyEngine/policyengine-api/compare/3.20.4...3.20.5
[3.20.4]: https://github.com/PolicyEngine/policyengine-api/compare/3.20.3...3.20.4
[3.20.3]: https://github.com/PolicyEngine/policyengine-api/compare/3.20.2...3.20.3
[3.20.2]: https://github.com/PolicyEngine/policyengine-api/compare/3.20.1...3.20.2
[3.20.1]: https://github.com/PolicyEngine/policyengine-api/compare/3.20.0...3.20.1
[3.20.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.19.5...3.20.0
[3.19.5]: https://github.com/PolicyEngine/policyengine-api/compare/3.19.4...3.19.5
[3.19.4]: https://github.com/PolicyEngine/policyengine-api/compare/3.19.3...3.19.4
[3.19.3]: https://github.com/PolicyEngine/policyengine-api/compare/3.19.2...3.19.3
[3.19.2]: https://github.com/PolicyEngine/policyengine-api/compare/3.19.1...3.19.2
[3.19.1]: https://github.com/PolicyEngine/policyengine-api/compare/3.19.0...3.19.1
[3.19.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.18.4...3.19.0
[3.18.4]: https://github.com/PolicyEngine/policyengine-api/compare/3.18.3...3.18.4
[3.18.3]: https://github.com/PolicyEngine/policyengine-api/compare/3.18.2...3.18.3
[3.18.2]: https://github.com/PolicyEngine/policyengine-api/compare/3.18.1...3.18.2
[3.18.1]: https://github.com/PolicyEngine/policyengine-api/compare/3.18.0...3.18.1
[3.18.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.17.6...3.18.0
[3.17.6]: https://github.com/PolicyEngine/policyengine-api/compare/3.17.5...3.17.6
[3.17.5]: https://github.com/PolicyEngine/policyengine-api/compare/3.17.4...3.17.5
[3.17.4]: https://github.com/PolicyEngine/policyengine-api/compare/3.17.3...3.17.4
[3.17.3]: https://github.com/PolicyEngine/policyengine-api/compare/3.17.2...3.17.3
[3.17.2]: https://github.com/PolicyEngine/policyengine-api/compare/3.17.1...3.17.2
[3.17.1]: https://github.com/PolicyEngine/policyengine-api/compare/3.17.0...3.17.1
[3.17.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.16.6...3.17.0
[3.16.6]: https://github.com/PolicyEngine/policyengine-api/compare/3.16.5...3.16.6
[3.16.5]: https://github.com/PolicyEngine/policyengine-api/compare/3.16.4...3.16.5
[3.16.4]: https://github.com/PolicyEngine/policyengine-api/compare/3.16.3...3.16.4
[3.16.3]: https://github.com/PolicyEngine/policyengine-api/compare/3.16.2...3.16.3
[3.16.2]: https://github.com/PolicyEngine/policyengine-api/compare/3.16.1...3.16.2
[3.16.1]: https://github.com/PolicyEngine/policyengine-api/compare/3.16.0...3.16.1
[3.16.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.15.7...3.16.0
[3.15.7]: https://github.com/PolicyEngine/policyengine-api/compare/3.15.6...3.15.7
[3.15.6]: https://github.com/PolicyEngine/policyengine-api/compare/3.15.5...3.15.6
[3.15.5]: https://github.com/PolicyEngine/policyengine-api/compare/3.15.4...3.15.5
[3.15.4]: https://github.com/PolicyEngine/policyengine-api/compare/3.15.3...3.15.4
[3.15.3]: https://github.com/PolicyEngine/policyengine-api/compare/3.15.2...3.15.3
[3.15.2]: https://github.com/PolicyEngine/policyengine-api/compare/3.15.1...3.15.2
[3.15.1]: https://github.com/PolicyEngine/policyengine-api/compare/3.15.0...3.15.1
[3.15.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.14.8...3.15.0
[3.14.8]: https://github.com/PolicyEngine/policyengine-api/compare/3.14.7...3.14.8
[3.14.7]: https://github.com/PolicyEngine/policyengine-api/compare/3.14.6...3.14.7
[3.14.6]: https://github.com/PolicyEngine/policyengine-api/compare/3.14.5...3.14.6
[3.14.5]: https://github.com/PolicyEngine/policyengine-api/compare/3.14.4...3.14.5
[3.14.4]: https://github.com/PolicyEngine/policyengine-api/compare/3.14.3...3.14.4
[3.14.3]: https://github.com/PolicyEngine/policyengine-api/compare/3.14.2...3.14.3
[3.14.2]: https://github.com/PolicyEngine/policyengine-api/compare/3.14.1...3.14.2
[3.14.1]: https://github.com/PolicyEngine/policyengine-api/compare/3.14.0...3.14.1
[3.14.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.13.4...3.14.0
[3.13.4]: https://github.com/PolicyEngine/policyengine-api/compare/3.13.3...3.13.4
[3.13.3]: https://github.com/PolicyEngine/policyengine-api/compare/3.13.2...3.13.3
[3.13.2]: https://github.com/PolicyEngine/policyengine-api/compare/3.13.1...3.13.2
[3.13.1]: https://github.com/PolicyEngine/policyengine-api/compare/3.13.0...3.13.1
[3.13.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.12.12...3.13.0
[3.12.12]: https://github.com/PolicyEngine/policyengine-api/compare/3.12.11...3.12.12
[3.12.11]: https://github.com/PolicyEngine/policyengine-api/compare/3.12.10...3.12.11
[3.12.10]: https://github.com/PolicyEngine/policyengine-api/compare/3.12.9...3.12.10
[3.12.9]: https://github.com/PolicyEngine/policyengine-api/compare/3.12.8...3.12.9
[3.12.8]: https://github.com/PolicyEngine/policyengine-api/compare/3.12.7...3.12.8
[3.12.7]: https://github.com/PolicyEngine/policyengine-api/compare/3.12.6...3.12.7
[3.12.6]: https://github.com/PolicyEngine/policyengine-api/compare/3.12.5...3.12.6
[3.12.5]: https://github.com/PolicyEngine/policyengine-api/compare/3.12.4...3.12.5
[3.12.4]: https://github.com/PolicyEngine/policyengine-api/compare/3.12.3...3.12.4
[3.12.3]: https://github.com/PolicyEngine/policyengine-api/compare/3.12.2...3.12.3
[3.12.2]: https://github.com/PolicyEngine/policyengine-api/compare/3.12.1...3.12.2
[3.12.1]: https://github.com/PolicyEngine/policyengine-api/compare/3.12.0...3.12.1
[3.12.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.11.11...3.12.0
[3.11.11]: https://github.com/PolicyEngine/policyengine-api/compare/3.11.10...3.11.11
[3.11.10]: https://github.com/PolicyEngine/policyengine-api/compare/3.11.9...3.11.10
[3.11.9]: https://github.com/PolicyEngine/policyengine-api/compare/3.11.8...3.11.9
[3.11.8]: https://github.com/PolicyEngine/policyengine-api/compare/3.11.7...3.11.8
[3.11.7]: https://github.com/PolicyEngine/policyengine-api/compare/3.11.6...3.11.7
[3.11.6]: https://github.com/PolicyEngine/policyengine-api/compare/3.11.5...3.11.6
[3.11.5]: https://github.com/PolicyEngine/policyengine-api/compare/3.11.4...3.11.5
[3.11.4]: https://github.com/PolicyEngine/policyengine-api/compare/3.11.3...3.11.4
[3.11.3]: https://github.com/PolicyEngine/policyengine-api/compare/3.11.2...3.11.3
[3.11.2]: https://github.com/PolicyEngine/policyengine-api/compare/3.11.1...3.11.2
[3.11.1]: https://github.com/PolicyEngine/policyengine-api/compare/3.11.0...3.11.1
[3.11.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.10.6...3.11.0
[3.10.6]: https://github.com/PolicyEngine/policyengine-api/compare/3.10.5...3.10.6
[3.10.5]: https://github.com/PolicyEngine/policyengine-api/compare/3.10.4...3.10.5
[3.10.4]: https://github.com/PolicyEngine/policyengine-api/compare/3.10.3...3.10.4
[3.10.3]: https://github.com/PolicyEngine/policyengine-api/compare/3.10.2...3.10.3
[3.10.2]: https://github.com/PolicyEngine/policyengine-api/compare/3.10.1...3.10.2
[3.10.1]: https://github.com/PolicyEngine/policyengine-api/compare/3.10.0...3.10.1
[3.10.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.9.9...3.10.0
[3.9.9]: https://github.com/PolicyEngine/policyengine-api/compare/3.9.8...3.9.9
[3.9.8]: https://github.com/PolicyEngine/policyengine-api/compare/3.9.7...3.9.8
[3.9.7]: https://github.com/PolicyEngine/policyengine-api/compare/3.9.6...3.9.7
[3.9.6]: https://github.com/PolicyEngine/policyengine-api/compare/3.9.5...3.9.6
[3.9.5]: https://github.com/PolicyEngine/policyengine-api/compare/3.9.4...3.9.5
[3.9.4]: https://github.com/PolicyEngine/policyengine-api/compare/3.9.3...3.9.4
[3.9.3]: https://github.com/PolicyEngine/policyengine-api/compare/3.9.2...3.9.3
[3.9.2]: https://github.com/PolicyEngine/policyengine-api/compare/3.9.1...3.9.2
[3.9.1]: https://github.com/PolicyEngine/policyengine-api/compare/3.9.0...3.9.1
[3.9.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.8.6...3.9.0
[3.8.6]: https://github.com/PolicyEngine/policyengine-api/compare/3.8.5...3.8.6
[3.8.5]: https://github.com/PolicyEngine/policyengine-api/compare/3.8.4...3.8.5
[3.8.4]: https://github.com/PolicyEngine/policyengine-api/compare/3.8.3...3.8.4
[3.8.3]: https://github.com/PolicyEngine/policyengine-api/compare/3.8.2...3.8.3
[3.8.2]: https://github.com/PolicyEngine/policyengine-api/compare/3.8.1...3.8.2
[3.8.1]: https://github.com/PolicyEngine/policyengine-api/compare/3.8.0...3.8.1
[3.8.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.7.14...3.8.0
[3.7.14]: https://github.com/PolicyEngine/policyengine-api/compare/3.7.13...3.7.14
[3.7.13]: https://github.com/PolicyEngine/policyengine-api/compare/3.7.12...3.7.13
[3.7.12]: https://github.com/PolicyEngine/policyengine-api/compare/3.7.11...3.7.12
[3.7.11]: https://github.com/PolicyEngine/policyengine-api/compare/3.7.10...3.7.11
[3.7.10]: https://github.com/PolicyEngine/policyengine-api/compare/3.7.9...3.7.10
[3.7.9]: https://github.com/PolicyEngine/policyengine-api/compare/3.7.8...3.7.9
[3.7.8]: https://github.com/PolicyEngine/policyengine-api/compare/3.7.7...3.7.8
[3.7.7]: https://github.com/PolicyEngine/policyengine-api/compare/3.7.6...3.7.7
[3.7.6]: https://github.com/PolicyEngine/policyengine-api/compare/3.7.5...3.7.6
[3.7.5]: https://github.com/PolicyEngine/policyengine-api/compare/3.7.4...3.7.5
[3.7.4]: https://github.com/PolicyEngine/policyengine-api/compare/3.7.3...3.7.4
[3.7.3]: https://github.com/PolicyEngine/policyengine-api/compare/3.7.2...3.7.3
[3.7.2]: https://github.com/PolicyEngine/policyengine-api/compare/3.7.1...3.7.2
[3.7.1]: https://github.com/PolicyEngine/policyengine-api/compare/3.7.0...3.7.1
[3.7.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.6.10...3.7.0
[3.6.10]: https://github.com/PolicyEngine/policyengine-api/compare/3.6.9...3.6.10
[3.6.9]: https://github.com/PolicyEngine/policyengine-api/compare/3.6.8...3.6.9
[3.6.8]: https://github.com/PolicyEngine/policyengine-api/compare/3.6.7...3.6.8
[3.6.7]: https://github.com/PolicyEngine/policyengine-api/compare/3.6.6...3.6.7
[3.6.6]: https://github.com/PolicyEngine/policyengine-api/compare/3.6.5...3.6.6
[3.6.5]: https://github.com/PolicyEngine/policyengine-api/compare/3.6.4...3.6.5
[3.6.4]: https://github.com/PolicyEngine/policyengine-api/compare/3.6.3...3.6.4
[3.6.3]: https://github.com/PolicyEngine/policyengine-api/compare/3.6.2...3.6.3
[3.6.2]: https://github.com/PolicyEngine/policyengine-api/compare/3.6.1...3.6.2
[3.6.1]: https://github.com/PolicyEngine/policyengine-api/compare/3.6.0...3.6.1
[3.6.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.5.1...3.6.0
[3.5.1]: https://github.com/PolicyEngine/policyengine-api/compare/3.5.0...3.5.1
[3.5.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.4.0...3.5.0
[3.4.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.3.3...3.4.0
[3.3.3]: https://github.com/PolicyEngine/policyengine-api/compare/3.3.2...3.3.3
[3.3.2]: https://github.com/PolicyEngine/policyengine-api/compare/3.3.1...3.3.2
[3.3.1]: https://github.com/PolicyEngine/policyengine-api/compare/3.3.0...3.3.1
[3.3.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.2.1...3.3.0
[3.2.1]: https://github.com/PolicyEngine/policyengine-api/compare/3.2.0...3.2.1
[3.2.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.1.2...3.2.0
[3.1.2]: https://github.com/PolicyEngine/policyengine-api/compare/3.1.1...3.1.2
[3.1.1]: https://github.com/PolicyEngine/policyengine-api/compare/3.1.0...3.1.1
[3.1.0]: https://github.com/PolicyEngine/policyengine-api/compare/3.0.0...3.1.0
[3.0.0]: https://github.com/PolicyEngine/policyengine-api/compare/2.3.4...3.0.0
[2.3.4]: https://github.com/PolicyEngine/policyengine-api/compare/2.3.3...2.3.4
[2.3.3]: https://github.com/PolicyEngine/policyengine-api/compare/2.3.2...2.3.3
[2.3.2]: https://github.com/PolicyEngine/policyengine-api/compare/2.3.1...2.3.2
[2.3.1]: https://github.com/PolicyEngine/policyengine-api/compare/2.3.0...2.3.1
[2.3.0]: https://github.com/PolicyEngine/policyengine-api/compare/2.2.25...2.3.0
[2.2.25]: https://github.com/PolicyEngine/policyengine-api/compare/2.2.24...2.2.25
[2.2.24]: https://github.com/PolicyEngine/policyengine-api/compare/2.2.23...2.2.24
[2.2.23]: https://github.com/PolicyEngine/policyengine-api/compare/2.2.22...2.2.23
[2.2.22]: https://github.com/PolicyEngine/policyengine-api/compare/2.2.21...2.2.22
[2.2.21]: https://github.com/PolicyEngine/policyengine-api/compare/2.2.20...2.2.21
[2.2.20]: https://github.com/PolicyEngine/policyengine-api/compare/2.2.19...2.2.20
[2.2.19]: https://github.com/PolicyEngine/policyengine-api/compare/2.2.18...2.2.19
[2.2.18]: https://github.com/PolicyEngine/policyengine-api/compare/2.2.17...2.2.18
[2.2.17]: https://github.com/PolicyEngine/policyengine-api/compare/2.2.16...2.2.17
[2.2.16]: https://github.com/PolicyEngine/policyengine-api/compare/2.2.15...2.2.16
[2.2.15]: https://github.com/PolicyEngine/policyengine-api/compare/2.2.14...2.2.15
[2.2.14]: https://github.com/PolicyEngine/policyengine-api/compare/2.2.13...2.2.14
[2.2.13]: https://github.com/PolicyEngine/policyengine-api/compare/2.2.12...2.2.13
[2.2.12]: https://github.com/PolicyEngine/policyengine-api/compare/2.2.11...2.2.12
[2.2.11]: https://github.com/PolicyEngine/policyengine-api/compare/2.2.10...2.2.11
[2.2.10]: https://github.com/PolicyEngine/policyengine-api/compare/2.2.9...2.2.10
[2.2.9]: https://github.com/PolicyEngine/policyengine-api/compare/2.2.8...2.2.9
[2.2.8]: https://github.com/PolicyEngine/policyengine-api/compare/2.2.7...2.2.8
[2.2.7]: https://github.com/PolicyEngine/policyengine-api/compare/2.2.6...2.2.7
[2.2.6]: https://github.com/PolicyEngine/policyengine-api/compare/2.2.5...2.2.6
[2.2.5]: https://github.com/PolicyEngine/policyengine-api/compare/2.2.4...2.2.5
[2.2.4]: https://github.com/PolicyEngine/policyengine-api/compare/2.2.3...2.2.4
[2.2.3]: https://github.com/PolicyEngine/policyengine-api/compare/2.2.2...2.2.3
[2.2.2]: https://github.com/PolicyEngine/policyengine-api/compare/2.2.1...2.2.2
[2.2.1]: https://github.com/PolicyEngine/policyengine-api/compare/2.2.0...2.2.1
[2.2.0]: https://github.com/PolicyEngine/policyengine-api/compare/2.1.6...2.2.0
[2.1.6]: https://github.com/PolicyEngine/policyengine-api/compare/2.1.5...2.1.6
[2.1.5]: https://github.com/PolicyEngine/policyengine-api/compare/2.1.4...2.1.5
[2.1.4]: https://github.com/PolicyEngine/policyengine-api/compare/2.1.3...2.1.4
[2.1.3]: https://github.com/PolicyEngine/policyengine-api/compare/2.1.2...2.1.3
[2.1.2]: https://github.com/PolicyEngine/policyengine-api/compare/2.1.1...2.1.2
[2.1.1]: https://github.com/PolicyEngine/policyengine-api/compare/2.1.0...2.1.1
[2.1.0]: https://github.com/PolicyEngine/policyengine-api/compare/2.0.5...2.1.0
[2.0.5]: https://github.com/PolicyEngine/policyengine-api/compare/2.0.4...2.0.5
[2.0.4]: https://github.com/PolicyEngine/policyengine-api/compare/2.0.3...2.0.4
[2.0.3]: https://github.com/PolicyEngine/policyengine-api/compare/2.0.2...2.0.3
[2.0.2]: https://github.com/PolicyEngine/policyengine-api/compare/2.0.1...2.0.2
[2.0.1]: https://github.com/PolicyEngine/policyengine-api/compare/2.0.0...2.0.1
[2.0.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.34.2...2.0.0
[1.34.2]: https://github.com/PolicyEngine/policyengine-api/compare/1.34.1...1.34.2
[1.34.1]: https://github.com/PolicyEngine/policyengine-api/compare/1.34.0...1.34.1
[1.34.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.33.3...1.34.0
[1.33.3]: https://github.com/PolicyEngine/policyengine-api/compare/1.33.2...1.33.3
[1.33.2]: https://github.com/PolicyEngine/policyengine-api/compare/1.33.1...1.33.2
[1.33.1]: https://github.com/PolicyEngine/policyengine-api/compare/1.33.0...1.33.1
[1.33.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.32.0...1.33.0
[1.32.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.31.1...1.32.0
[1.31.1]: https://github.com/PolicyEngine/policyengine-api/compare/1.31.0...1.31.1
[1.31.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.30.1...1.31.0
[1.30.1]: https://github.com/PolicyEngine/policyengine-api/compare/1.30.0...1.30.1
[1.30.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.29.1...1.30.0
[1.29.1]: https://github.com/PolicyEngine/policyengine-api/compare/1.29.0...1.29.1
[1.29.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.28.6...1.29.0
[1.28.6]: https://github.com/PolicyEngine/policyengine-api/compare/1.28.5...1.28.6
[1.28.5]: https://github.com/PolicyEngine/policyengine-api/compare/1.28.4...1.28.5
[1.28.4]: https://github.com/PolicyEngine/policyengine-api/compare/1.28.3...1.28.4
[1.28.3]: https://github.com/PolicyEngine/policyengine-api/compare/1.28.2...1.28.3
[1.28.2]: https://github.com/PolicyEngine/policyengine-api/compare/1.28.1...1.28.2
[1.28.1]: https://github.com/PolicyEngine/policyengine-api/compare/1.28.0...1.28.1
[1.28.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.27.15...1.28.0
[1.27.15]: https://github.com/PolicyEngine/policyengine-api/compare/1.27.14...1.27.15
[1.27.14]: https://github.com/PolicyEngine/policyengine-api/compare/1.27.13...1.27.14
[1.27.13]: https://github.com/PolicyEngine/policyengine-api/compare/1.27.12...1.27.13
[1.27.12]: https://github.com/PolicyEngine/policyengine-api/compare/1.27.11...1.27.12
[1.27.11]: https://github.com/PolicyEngine/policyengine-api/compare/1.27.10...1.27.11
[1.27.10]: https://github.com/PolicyEngine/policyengine-api/compare/1.27.9...1.27.10
[1.27.9]: https://github.com/PolicyEngine/policyengine-api/compare/1.27.8...1.27.9
[1.27.8]: https://github.com/PolicyEngine/policyengine-api/compare/1.27.7...1.27.8
[1.27.7]: https://github.com/PolicyEngine/policyengine-api/compare/1.27.6...1.27.7
[1.27.6]: https://github.com/PolicyEngine/policyengine-api/compare/1.27.5...1.27.6
[1.27.5]: https://github.com/PolicyEngine/policyengine-api/compare/1.27.4...1.27.5
[1.27.4]: https://github.com/PolicyEngine/policyengine-api/compare/1.27.3...1.27.4
[1.27.3]: https://github.com/PolicyEngine/policyengine-api/compare/1.27.2...1.27.3
[1.27.2]: https://github.com/PolicyEngine/policyengine-api/compare/1.27.1...1.27.2
[1.27.1]: https://github.com/PolicyEngine/policyengine-api/compare/1.27.0...1.27.1
[1.27.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.45...1.27.0
[1.26.45]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.44...1.26.45
[1.26.44]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.43...1.26.44
[1.26.43]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.42...1.26.43
[1.26.42]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.41...1.26.42
[1.26.41]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.40...1.26.41
[1.26.40]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.39...1.26.40
[1.26.39]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.38...1.26.39
[1.26.38]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.37...1.26.38
[1.26.37]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.36...1.26.37
[1.26.36]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.35...1.26.36
[1.26.35]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.34...1.26.35
[1.26.34]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.33...1.26.34
[1.26.33]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.32...1.26.33
[1.26.32]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.31...1.26.32
[1.26.31]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.30...1.26.31
[1.26.30]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.29...1.26.30
[1.26.29]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.28...1.26.29
[1.26.28]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.27...1.26.28
[1.26.27]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.26...1.26.27
[1.26.26]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.25...1.26.26
[1.26.25]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.24...1.26.25
[1.26.24]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.23...1.26.24
[1.26.23]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.22...1.26.23
[1.26.22]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.21...1.26.22
[1.26.21]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.20...1.26.21
[1.26.20]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.19...1.26.20
[1.26.19]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.18...1.26.19
[1.26.18]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.17...1.26.18
[1.26.17]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.16...1.26.17
[1.26.16]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.15...1.26.16
[1.26.15]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.14...1.26.15
[1.26.14]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.13...1.26.14
[1.26.13]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.12...1.26.13
[1.26.12]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.11...1.26.12
[1.26.11]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.10...1.26.11
[1.26.10]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.9...1.26.10
[1.26.9]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.8...1.26.9
[1.26.8]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.7...1.26.8
[1.26.7]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.6...1.26.7
[1.26.6]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.5...1.26.6
[1.26.5]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.4...1.26.5
[1.26.4]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.3...1.26.4
[1.26.3]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.2...1.26.3
[1.26.2]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.1...1.26.2
[1.26.1]: https://github.com/PolicyEngine/policyengine-api/compare/1.26.0...1.26.1
[1.26.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.25.7...1.26.0
[1.25.7]: https://github.com/PolicyEngine/policyengine-api/compare/1.25.6...1.25.7
[1.25.6]: https://github.com/PolicyEngine/policyengine-api/compare/1.25.5...1.25.6
[1.25.5]: https://github.com/PolicyEngine/policyengine-api/compare/1.25.4...1.25.5
[1.25.4]: https://github.com/PolicyEngine/policyengine-api/compare/1.25.3...1.25.4
[1.25.3]: https://github.com/PolicyEngine/policyengine-api/compare/1.25.2...1.25.3
[1.25.2]: https://github.com/PolicyEngine/policyengine-api/compare/1.25.1...1.25.2
[1.25.1]: https://github.com/PolicyEngine/policyengine-api/compare/1.25.0...1.25.1
[1.25.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.24.9...1.25.0
[1.24.9]: https://github.com/PolicyEngine/policyengine-api/compare/1.24.8...1.24.9
[1.24.8]: https://github.com/PolicyEngine/policyengine-api/compare/1.24.7...1.24.8
[1.24.7]: https://github.com/PolicyEngine/policyengine-api/compare/1.24.6...1.24.7
[1.24.6]: https://github.com/PolicyEngine/policyengine-api/compare/1.24.5...1.24.6
[1.24.5]: https://github.com/PolicyEngine/policyengine-api/compare/1.24.4...1.24.5
[1.24.4]: https://github.com/PolicyEngine/policyengine-api/compare/1.24.3...1.24.4
[1.24.3]: https://github.com/PolicyEngine/policyengine-api/compare/1.24.2...1.24.3
[1.24.2]: https://github.com/PolicyEngine/policyengine-api/compare/1.24.1...1.24.2
[1.24.1]: https://github.com/PolicyEngine/policyengine-api/compare/1.24.0...1.24.1
[1.24.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.23.5...1.24.0
[1.23.5]: https://github.com/PolicyEngine/policyengine-api/compare/1.23.4...1.23.5
[1.23.4]: https://github.com/PolicyEngine/policyengine-api/compare/1.23.3...1.23.4
[1.23.3]: https://github.com/PolicyEngine/policyengine-api/compare/1.23.2...1.23.3
[1.23.2]: https://github.com/PolicyEngine/policyengine-api/compare/1.23.1...1.23.2
[1.23.1]: https://github.com/PolicyEngine/policyengine-api/compare/1.23.0...1.23.1
[1.23.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.22.2...1.23.0
[1.22.2]: https://github.com/PolicyEngine/policyengine-api/compare/1.22.1...1.22.2
[1.22.1]: https://github.com/PolicyEngine/policyengine-api/compare/1.22.0...1.22.1
[1.22.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.21.0...1.22.0
[1.21.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.20.8...1.21.0
[1.20.8]: https://github.com/PolicyEngine/policyengine-api/compare/1.20.7...1.20.8
[1.20.7]: https://github.com/PolicyEngine/policyengine-api/compare/1.20.6...1.20.7
[1.20.6]: https://github.com/PolicyEngine/policyengine-api/compare/1.20.5...1.20.6
[1.20.5]: https://github.com/PolicyEngine/policyengine-api/compare/1.20.4...1.20.5
[1.20.4]: https://github.com/PolicyEngine/policyengine-api/compare/1.20.3...1.20.4
[1.20.3]: https://github.com/PolicyEngine/policyengine-api/compare/1.20.2...1.20.3
[1.20.2]: https://github.com/PolicyEngine/policyengine-api/compare/1.20.1...1.20.2
[1.20.1]: https://github.com/PolicyEngine/policyengine-api/compare/1.20.0...1.20.1
[1.20.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.19.26...1.20.0
[1.19.26]: https://github.com/PolicyEngine/policyengine-api/compare/1.19.25...1.19.26
[1.19.25]: https://github.com/PolicyEngine/policyengine-api/compare/1.19.24...1.19.25
[1.19.24]: https://github.com/PolicyEngine/policyengine-api/compare/1.19.23...1.19.24
[1.19.23]: https://github.com/PolicyEngine/policyengine-api/compare/1.19.22...1.19.23
[1.19.22]: https://github.com/PolicyEngine/policyengine-api/compare/1.19.21...1.19.22
[1.19.21]: https://github.com/PolicyEngine/policyengine-api/compare/1.19.20...1.19.21
[1.19.20]: https://github.com/PolicyEngine/policyengine-api/compare/1.19.19...1.19.20
[1.19.19]: https://github.com/PolicyEngine/policyengine-api/compare/1.19.18...1.19.19
[1.19.18]: https://github.com/PolicyEngine/policyengine-api/compare/1.19.17...1.19.18
[1.19.17]: https://github.com/PolicyEngine/policyengine-api/compare/1.19.16...1.19.17
[1.19.16]: https://github.com/PolicyEngine/policyengine-api/compare/1.19.15...1.19.16
[1.19.15]: https://github.com/PolicyEngine/policyengine-api/compare/1.19.14...1.19.15
[1.19.14]: https://github.com/PolicyEngine/policyengine-api/compare/1.19.13...1.19.14
[1.19.13]: https://github.com/PolicyEngine/policyengine-api/compare/1.19.12...1.19.13
[1.19.12]: https://github.com/PolicyEngine/policyengine-api/compare/1.19.11...1.19.12
[1.19.11]: https://github.com/PolicyEngine/policyengine-api/compare/1.19.10...1.19.11
[1.19.10]: https://github.com/PolicyEngine/policyengine-api/compare/1.19.9...1.19.10
[1.19.9]: https://github.com/PolicyEngine/policyengine-api/compare/1.19.8...1.19.9
[1.19.8]: https://github.com/PolicyEngine/policyengine-api/compare/1.19.7...1.19.8
[1.19.7]: https://github.com/PolicyEngine/policyengine-api/compare/1.19.6...1.19.7
[1.19.6]: https://github.com/PolicyEngine/policyengine-api/compare/1.19.5...1.19.6
[1.19.5]: https://github.com/PolicyEngine/policyengine-api/compare/1.19.4...1.19.5
[1.19.4]: https://github.com/PolicyEngine/policyengine-api/compare/1.19.3...1.19.4
[1.19.3]: https://github.com/PolicyEngine/policyengine-api/compare/1.19.2...1.19.3
[1.19.2]: https://github.com/PolicyEngine/policyengine-api/compare/1.19.1...1.19.2
[1.19.1]: https://github.com/PolicyEngine/policyengine-api/compare/1.19.0...1.19.1
[1.19.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.18.4...1.19.0
[1.18.4]: https://github.com/PolicyEngine/policyengine-api/compare/1.18.3...1.18.4
[1.18.3]: https://github.com/PolicyEngine/policyengine-api/compare/1.18.2...1.18.3
[1.18.2]: https://github.com/PolicyEngine/policyengine-api/compare/1.18.1...1.18.2
[1.18.1]: https://github.com/PolicyEngine/policyengine-api/compare/1.18.0...1.18.1
[1.18.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.17.22...1.18.0
[1.17.22]: https://github.com/PolicyEngine/policyengine-api/compare/1.17.21...1.17.22
[1.17.21]: https://github.com/PolicyEngine/policyengine-api/compare/1.17.20...1.17.21
[1.17.20]: https://github.com/PolicyEngine/policyengine-api/compare/1.17.19...1.17.20
[1.17.19]: https://github.com/PolicyEngine/policyengine-api/compare/1.17.18...1.17.19
[1.17.18]: https://github.com/PolicyEngine/policyengine-api/compare/1.17.17...1.17.18
[1.17.17]: https://github.com/PolicyEngine/policyengine-api/compare/1.17.16...1.17.17
[1.17.16]: https://github.com/PolicyEngine/policyengine-api/compare/1.17.15...1.17.16
[1.17.15]: https://github.com/PolicyEngine/policyengine-api/compare/1.17.14...1.17.15
[1.17.14]: https://github.com/PolicyEngine/policyengine-api/compare/1.17.13...1.17.14
[1.17.13]: https://github.com/PolicyEngine/policyengine-api/compare/1.17.12...1.17.13
[1.17.12]: https://github.com/PolicyEngine/policyengine-api/compare/1.17.11...1.17.12
[1.17.11]: https://github.com/PolicyEngine/policyengine-api/compare/1.17.10...1.17.11
[1.17.10]: https://github.com/PolicyEngine/policyengine-api/compare/1.17.9...1.17.10
[1.17.9]: https://github.com/PolicyEngine/policyengine-api/compare/1.17.8...1.17.9
[1.17.8]: https://github.com/PolicyEngine/policyengine-api/compare/1.17.7...1.17.8
[1.17.7]: https://github.com/PolicyEngine/policyengine-api/compare/1.17.6...1.17.7
[1.17.6]: https://github.com/PolicyEngine/policyengine-api/compare/1.17.5...1.17.6
[1.17.5]: https://github.com/PolicyEngine/policyengine-api/compare/1.17.4...1.17.5
[1.17.4]: https://github.com/PolicyEngine/policyengine-api/compare/1.17.3...1.17.4
[1.17.3]: https://github.com/PolicyEngine/policyengine-api/compare/1.17.2...1.17.3
[1.17.2]: https://github.com/PolicyEngine/policyengine-api/compare/1.17.1...1.17.2
[1.17.1]: https://github.com/PolicyEngine/policyengine-api/compare/1.17.0...1.17.1
[1.17.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.16.3...1.17.0
[1.16.3]: https://github.com/PolicyEngine/policyengine-api/compare/1.16.2...1.16.3
[1.16.2]: https://github.com/PolicyEngine/policyengine-api/compare/1.16.1...1.16.2
[1.16.1]: https://github.com/PolicyEngine/policyengine-api/compare/1.16.0...1.16.1
[1.16.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.42...1.16.0
[1.15.42]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.41...1.15.42
[1.15.41]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.40...1.15.41
[1.15.40]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.39...1.15.40
[1.15.39]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.38...1.15.39
[1.15.38]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.37...1.15.38
[1.15.37]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.36...1.15.37
[1.15.36]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.35...1.15.36
[1.15.35]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.34...1.15.35
[1.15.34]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.33...1.15.34
[1.15.33]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.32...1.15.33
[1.15.32]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.31...1.15.32
[1.15.31]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.30...1.15.31
[1.15.30]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.29...1.15.30
[1.15.29]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.28...1.15.29
[1.15.28]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.27...1.15.28
[1.15.27]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.26...1.15.27
[1.15.26]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.25...1.15.26
[1.15.25]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.24...1.15.25
[1.15.24]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.23...1.15.24
[1.15.23]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.22...1.15.23
[1.15.22]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.21...1.15.22
[1.15.21]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.20...1.15.21
[1.15.20]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.19...1.15.20
[1.15.19]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.18...1.15.19
[1.15.18]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.17...1.15.18
[1.15.17]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.16...1.15.17
[1.15.16]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.15...1.15.16
[1.15.15]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.14...1.15.15
[1.15.14]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.13...1.15.14
[1.15.13]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.12...1.15.13
[1.15.12]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.11...1.15.12
[1.15.11]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.10...1.15.11
[1.15.10]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.9...1.15.10
[1.15.9]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.8...1.15.9
[1.15.8]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.7...1.15.8
[1.15.7]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.6...1.15.7
[1.15.6]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.5...1.15.6
[1.15.5]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.4...1.15.5
[1.15.4]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.3...1.15.4
[1.15.3]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.2...1.15.3
[1.15.2]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.1...1.15.2
[1.15.1]: https://github.com/PolicyEngine/policyengine-api/compare/1.15.0...1.15.1
[1.15.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.14.28...1.15.0
[1.14.28]: https://github.com/PolicyEngine/policyengine-api/compare/1.14.27...1.14.28
[1.14.27]: https://github.com/PolicyEngine/policyengine-api/compare/1.14.26...1.14.27
[1.14.26]: https://github.com/PolicyEngine/policyengine-api/compare/1.14.25...1.14.26
[1.14.25]: https://github.com/PolicyEngine/policyengine-api/compare/1.14.24...1.14.25
[1.14.24]: https://github.com/PolicyEngine/policyengine-api/compare/1.14.23...1.14.24
[1.14.23]: https://github.com/PolicyEngine/policyengine-api/compare/1.14.22...1.14.23
[1.14.22]: https://github.com/PolicyEngine/policyengine-api/compare/1.14.21...1.14.22
[1.14.21]: https://github.com/PolicyEngine/policyengine-api/compare/1.14.20...1.14.21
[1.14.20]: https://github.com/PolicyEngine/policyengine-api/compare/1.14.19...1.14.20
[1.14.19]: https://github.com/PolicyEngine/policyengine-api/compare/1.14.18...1.14.19
[1.14.18]: https://github.com/PolicyEngine/policyengine-api/compare/1.14.17...1.14.18
[1.14.17]: https://github.com/PolicyEngine/policyengine-api/compare/1.14.16...1.14.17
[1.14.16]: https://github.com/PolicyEngine/policyengine-api/compare/1.14.15...1.14.16
[1.14.15]: https://github.com/PolicyEngine/policyengine-api/compare/1.14.14...1.14.15
[1.14.14]: https://github.com/PolicyEngine/policyengine-api/compare/1.14.13...1.14.14
[1.14.13]: https://github.com/PolicyEngine/policyengine-api/compare/1.14.12...1.14.13
[1.14.12]: https://github.com/PolicyEngine/policyengine-api/compare/1.14.11...1.14.12
[1.14.11]: https://github.com/PolicyEngine/policyengine-api/compare/1.14.10...1.14.11
[1.14.10]: https://github.com/PolicyEngine/policyengine-api/compare/1.14.9...1.14.10
[1.14.9]: https://github.com/PolicyEngine/policyengine-api/compare/1.14.8...1.14.9
[1.14.8]: https://github.com/PolicyEngine/policyengine-api/compare/1.14.7...1.14.8
[1.14.7]: https://github.com/PolicyEngine/policyengine-api/compare/1.14.6...1.14.7
[1.14.6]: https://github.com/PolicyEngine/policyengine-api/compare/1.14.5...1.14.6
[1.14.5]: https://github.com/PolicyEngine/policyengine-api/compare/1.14.4...1.14.5
[1.14.4]: https://github.com/PolicyEngine/policyengine-api/compare/1.14.3...1.14.4
[1.14.3]: https://github.com/PolicyEngine/policyengine-api/compare/1.14.2...1.14.3
[1.14.2]: https://github.com/PolicyEngine/policyengine-api/compare/1.14.1...1.14.2
[1.14.1]: https://github.com/PolicyEngine/policyengine-api/compare/1.14.0...1.14.1
[1.14.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.13.4...1.14.0
[1.13.4]: https://github.com/PolicyEngine/policyengine-api/compare/1.13.3...1.13.4
[1.13.3]: https://github.com/PolicyEngine/policyengine-api/compare/1.13.2...1.13.3
[1.13.2]: https://github.com/PolicyEngine/policyengine-api/compare/1.13.1...1.13.2
[1.13.1]: https://github.com/PolicyEngine/policyengine-api/compare/1.13.0...1.13.1
[1.13.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.12.27...1.13.0
[1.12.27]: https://github.com/PolicyEngine/policyengine-api/compare/1.12.26...1.12.27
[1.12.26]: https://github.com/PolicyEngine/policyengine-api/compare/1.12.25...1.12.26
[1.12.25]: https://github.com/PolicyEngine/policyengine-api/compare/1.12.24...1.12.25
[1.12.24]: https://github.com/PolicyEngine/policyengine-api/compare/1.12.23...1.12.24
[1.12.23]: https://github.com/PolicyEngine/policyengine-api/compare/1.12.22...1.12.23
[1.12.22]: https://github.com/PolicyEngine/policyengine-api/compare/1.12.21...1.12.22
[1.12.21]: https://github.com/PolicyEngine/policyengine-api/compare/1.12.20...1.12.21
[1.12.20]: https://github.com/PolicyEngine/policyengine-api/compare/1.12.19...1.12.20
[1.12.19]: https://github.com/PolicyEngine/policyengine-api/compare/1.12.18...1.12.19
[1.12.18]: https://github.com/PolicyEngine/policyengine-api/compare/1.12.17...1.12.18
[1.12.17]: https://github.com/PolicyEngine/policyengine-api/compare/1.12.16...1.12.17
[1.12.16]: https://github.com/PolicyEngine/policyengine-api/compare/1.12.15...1.12.16
[1.12.15]: https://github.com/PolicyEngine/policyengine-api/compare/1.12.14...1.12.15
[1.12.14]: https://github.com/PolicyEngine/policyengine-api/compare/1.12.13...1.12.14
[1.12.13]: https://github.com/PolicyEngine/policyengine-api/compare/1.12.12...1.12.13
[1.12.12]: https://github.com/PolicyEngine/policyengine-api/compare/1.12.11...1.12.12
[1.12.11]: https://github.com/PolicyEngine/policyengine-api/compare/1.12.10...1.12.11
[1.12.10]: https://github.com/PolicyEngine/policyengine-api/compare/1.12.9...1.12.10
[1.12.9]: https://github.com/PolicyEngine/policyengine-api/compare/1.12.8...1.12.9
[1.12.8]: https://github.com/PolicyEngine/policyengine-api/compare/1.12.7...1.12.8
[1.12.7]: https://github.com/PolicyEngine/policyengine-api/compare/1.12.6...1.12.7
[1.12.6]: https://github.com/PolicyEngine/policyengine-api/compare/1.12.5...1.12.6
[1.12.5]: https://github.com/PolicyEngine/policyengine-api/compare/1.12.4...1.12.5
[1.12.4]: https://github.com/PolicyEngine/policyengine-api/compare/1.12.3...1.12.4
[1.12.3]: https://github.com/PolicyEngine/policyengine-api/compare/1.12.2...1.12.3
[1.12.2]: https://github.com/PolicyEngine/policyengine-api/compare/1.12.1...1.12.2
[1.12.1]: https://github.com/PolicyEngine/policyengine-api/compare/1.12.0...1.12.1
[1.12.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.36...1.12.0
[1.11.36]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.35...1.11.36
[1.11.35]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.34...1.11.35
[1.11.34]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.33...1.11.34
[1.11.33]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.32...1.11.33
[1.11.32]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.31...1.11.32
[1.11.31]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.30...1.11.31
[1.11.30]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.29...1.11.30
[1.11.29]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.28...1.11.29
[1.11.28]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.27...1.11.28
[1.11.27]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.26...1.11.27
[1.11.26]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.25...1.11.26
[1.11.25]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.24...1.11.25
[1.11.24]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.23...1.11.24
[1.11.23]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.22...1.11.23
[1.11.22]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.21...1.11.22
[1.11.21]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.20...1.11.21
[1.11.20]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.19...1.11.20
[1.11.19]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.18...1.11.19
[1.11.18]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.17...1.11.18
[1.11.17]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.16...1.11.17
[1.11.16]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.15...1.11.16
[1.11.15]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.14...1.11.15
[1.11.14]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.13...1.11.14
[1.11.13]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.12...1.11.13
[1.11.12]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.11...1.11.12
[1.11.11]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.10...1.11.11
[1.11.10]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.9...1.11.10
[1.11.9]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.8...1.11.9
[1.11.8]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.7...1.11.8
[1.11.7]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.6...1.11.7
[1.11.6]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.5...1.11.6
[1.11.5]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.4...1.11.5
[1.11.4]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.3...1.11.4
[1.11.3]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.2...1.11.3
[1.11.2]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.1...1.11.2
[1.11.1]: https://github.com/PolicyEngine/policyengine-api/compare/1.11.0...1.11.1
[1.11.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.99...1.11.0
[1.10.99]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.98...1.10.99
[1.10.98]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.98...1.10.98
[1.10.98]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.97...1.10.98
[1.10.97]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.96...1.10.97
[1.10.96]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.95...1.10.96
[1.10.95]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.94...1.10.95
[1.10.94]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.93...1.10.94
[1.10.93]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.92...1.10.93
[1.10.92]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.91...1.10.92
[1.10.91]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.90...1.10.91
[1.10.90]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.89...1.10.90
[1.10.89]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.88...1.10.89
[1.10.88]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.87...1.10.88
[1.10.87]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.86...1.10.87
[1.10.86]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.85...1.10.86
[1.10.85]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.84...1.10.85
[1.10.84]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.83...1.10.84
[1.10.83]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.82...1.10.83
[1.10.82]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.81...1.10.82
[1.10.81]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.80...1.10.81
[1.10.80]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.79...1.10.80
[1.10.79]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.78...1.10.79
[1.10.78]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.77...1.10.78
[1.10.77]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.76...1.10.77
[1.10.76]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.75...1.10.76
[1.10.75]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.74...1.10.75
[1.10.74]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.73...1.10.74
[1.10.73]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.72...1.10.73
[1.10.72]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.71...1.10.72
[1.10.71]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.70...1.10.71
[1.10.70]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.69...1.10.70
[1.10.69]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.68...1.10.69
[1.10.68]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.67...1.10.68
[1.10.67]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.66...1.10.67
[1.10.66]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.65...1.10.66
[1.10.65]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.64...1.10.65
[1.10.64]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.63...1.10.64
[1.10.63]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.62...1.10.63
[1.10.62]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.61...1.10.62
[1.10.61]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.60...1.10.61
[1.10.60]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.59...1.10.60
[1.10.59]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.58...1.10.59
[1.10.58]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.57...1.10.58
[1.10.57]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.56...1.10.57
[1.10.56]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.55...1.10.56
[1.10.55]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.54...1.10.55
[1.10.54]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.53...1.10.54
[1.10.53]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.52...1.10.53
[1.10.52]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.51...1.10.52
[1.10.51]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.50...1.10.51
[1.10.50]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.49...1.10.50
[1.10.49]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.48...1.10.49
[1.10.48]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.47...1.10.48
[1.10.47]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.46...1.10.47
[1.10.46]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.45...1.10.46
[1.10.45]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.44...1.10.45
[1.10.44]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.43...1.10.44
[1.10.43]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.42...1.10.43
[1.10.42]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.41...1.10.42
[1.10.41]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.40...1.10.41
[1.10.40]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.39...1.10.40
[1.10.39]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.38...1.10.39
[1.10.38]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.37...1.10.38
[1.10.37]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.36...1.10.37
[1.10.36]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.35...1.10.36
[1.10.35]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.34...1.10.35
[1.10.34]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.33...1.10.34
[1.10.33]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.32...1.10.33
[1.10.32]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.31...1.10.32
[1.10.31]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.30...1.10.31
[1.10.30]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.29...1.10.30
[1.10.29]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.28...1.10.29
[1.10.28]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.27...1.10.28
[1.10.27]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.26...1.10.27
[1.10.26]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.25...1.10.26
[1.10.25]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.24...1.10.25
[1.10.24]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.23...1.10.24
[1.10.23]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.22...1.10.23
[1.10.22]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.21...1.10.22
[1.10.21]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.20...1.10.21
[1.10.20]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.19...1.10.20
[1.10.19]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.18...1.10.19
[1.10.18]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.17...1.10.18
[1.10.17]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.16...1.10.17
[1.10.16]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.15...1.10.16
[1.10.15]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.14...1.10.15
[1.10.14]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.13...1.10.14
[1.10.13]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.12...1.10.13
[1.10.12]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.11...1.10.12
[1.10.11]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.10...1.10.11
[1.10.10]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.9...1.10.10
[1.10.9]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.8...1.10.9
[1.10.8]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.7...1.10.8
[1.10.7]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.6...1.10.7
[1.10.6]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.5...1.10.6
[1.10.5]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.4...1.10.5
[1.10.4]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.3...1.10.4
[1.10.3]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.2...1.10.3
[1.10.2]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.1...1.10.2
[1.10.1]: https://github.com/PolicyEngine/policyengine-api/compare/1.10.0...1.10.1
[1.10.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.9.30...1.10.0
[1.9.30]: https://github.com/PolicyEngine/policyengine-api/compare/1.9.29...1.9.30
[1.9.29]: https://github.com/PolicyEngine/policyengine-api/compare/1.9.28...1.9.29
[1.9.28]: https://github.com/PolicyEngine/policyengine-api/compare/1.9.27...1.9.28
[1.9.27]: https://github.com/PolicyEngine/policyengine-api/compare/1.9.26...1.9.27
[1.9.26]: https://github.com/PolicyEngine/policyengine-api/compare/1.9.25...1.9.26
[1.9.25]: https://github.com/PolicyEngine/policyengine-api/compare/1.9.24...1.9.25
[1.9.24]: https://github.com/PolicyEngine/policyengine-api/compare/1.9.23...1.9.24
[1.9.23]: https://github.com/PolicyEngine/policyengine-api/compare/1.9.22...1.9.23
[1.9.22]: https://github.com/PolicyEngine/policyengine-api/compare/1.9.21...1.9.22
[1.9.21]: https://github.com/PolicyEngine/policyengine-api/compare/1.9.20...1.9.21
[1.9.20]: https://github.com/PolicyEngine/policyengine-api/compare/1.9.19...1.9.20
[1.9.19]: https://github.com/PolicyEngine/policyengine-api/compare/1.9.18...1.9.19
[1.9.18]: https://github.com/PolicyEngine/policyengine-api/compare/1.9.17...1.9.18
[1.9.17]: https://github.com/PolicyEngine/policyengine-api/compare/1.9.16...1.9.17
[1.9.16]: https://github.com/PolicyEngine/policyengine-api/compare/1.9.15...1.9.16
[1.9.15]: https://github.com/PolicyEngine/policyengine-api/compare/1.9.14...1.9.15
[1.9.14]: https://github.com/PolicyEngine/policyengine-api/compare/1.9.13...1.9.14
[1.9.13]: https://github.com/PolicyEngine/policyengine-api/compare/1.9.12...1.9.13
[1.9.12]: https://github.com/PolicyEngine/policyengine-api/compare/1.9.11...1.9.12
[1.9.11]: https://github.com/PolicyEngine/policyengine-api/compare/1.9.10...1.9.11
[1.9.10]: https://github.com/PolicyEngine/policyengine-api/compare/1.9.9...1.9.10
[1.9.9]: https://github.com/PolicyEngine/policyengine-api/compare/1.9.8...1.9.9
[1.9.8]: https://github.com/PolicyEngine/policyengine-api/compare/1.9.7...1.9.8
[1.9.7]: https://github.com/PolicyEngine/policyengine-api/compare/1.9.6...1.9.7
[1.9.6]: https://github.com/PolicyEngine/policyengine-api/compare/1.9.5...1.9.6
[1.9.5]: https://github.com/PolicyEngine/policyengine-api/compare/1.9.4...1.9.5
[1.9.4]: https://github.com/PolicyEngine/policyengine-api/compare/1.9.3...1.9.4
[1.9.3]: https://github.com/PolicyEngine/policyengine-api/compare/1.9.2...1.9.3
[1.9.2]: https://github.com/PolicyEngine/policyengine-api/compare/1.9.1...1.9.2
[1.9.1]: https://github.com/PolicyEngine/policyengine-api/compare/1.9.0...1.9.1
[1.9.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.8.0...1.9.0
[1.8.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.7.1...1.8.0
[1.7.1]: https://github.com/PolicyEngine/policyengine-api/compare/1.7.0...1.7.1
[1.7.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.43...1.7.0
[1.6.43]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.42...1.6.43
[1.6.42]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.41...1.6.42
[1.6.41]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.40...1.6.41
[1.6.40]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.39...1.6.40
[1.6.39]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.38...1.6.39
[1.6.38]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.37...1.6.38
[1.6.37]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.36...1.6.37
[1.6.36]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.35...1.6.36
[1.6.35]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.34...1.6.35
[1.6.34]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.33...1.6.34
[1.6.33]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.32...1.6.33
[1.6.32]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.31...1.6.32
[1.6.31]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.30...1.6.31
[1.6.30]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.29...1.6.30
[1.6.29]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.28...1.6.29
[1.6.28]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.27...1.6.28
[1.6.27]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.26...1.6.27
[1.6.26]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.25...1.6.26
[1.6.25]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.24...1.6.25
[1.6.24]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.23...1.6.24
[1.6.23]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.22...1.6.23
[1.6.22]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.21...1.6.22
[1.6.21]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.20...1.6.21
[1.6.20]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.19...1.6.20
[1.6.19]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.18...1.6.19
[1.6.18]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.17...1.6.18
[1.6.17]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.16...1.6.17
[1.6.16]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.15...1.6.16
[1.6.15]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.14...1.6.15
[1.6.14]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.13...1.6.14
[1.6.13]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.12...1.6.13
[1.6.12]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.11...1.6.12
[1.6.11]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.10...1.6.11
[1.6.10]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.9...1.6.10
[1.6.9]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.8...1.6.9
[1.6.8]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.7...1.6.8
[1.6.7]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.6...1.6.7
[1.6.6]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.5...1.6.6
[1.6.5]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.4...1.6.5
[1.6.4]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.3...1.6.4
[1.6.3]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.2...1.6.3
[1.6.2]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.1...1.6.2
[1.6.1]: https://github.com/PolicyEngine/policyengine-api/compare/1.6.0...1.6.1
[1.6.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.5.27...1.6.0
[1.5.27]: https://github.com/PolicyEngine/policyengine-api/compare/1.5.26...1.5.27
[1.5.26]: https://github.com/PolicyEngine/policyengine-api/compare/1.5.25...1.5.26
[1.5.25]: https://github.com/PolicyEngine/policyengine-api/compare/1.5.24...1.5.25
[1.5.24]: https://github.com/PolicyEngine/policyengine-api/compare/1.5.23...1.5.24
[1.5.23]: https://github.com/PolicyEngine/policyengine-api/compare/1.5.22...1.5.23
[1.5.22]: https://github.com/PolicyEngine/policyengine-api/compare/1.5.21...1.5.22
[1.5.21]: https://github.com/PolicyEngine/policyengine-api/compare/1.5.20...1.5.21
[1.5.20]: https://github.com/PolicyEngine/policyengine-api/compare/1.5.19...1.5.20
[1.5.19]: https://github.com/PolicyEngine/policyengine-api/compare/1.5.18...1.5.19
[1.5.18]: https://github.com/PolicyEngine/policyengine-api/compare/1.5.17...1.5.18
[1.5.17]: https://github.com/PolicyEngine/policyengine-api/compare/1.5.16...1.5.17
[1.5.16]: https://github.com/PolicyEngine/policyengine-api/compare/1.5.15...1.5.16
[1.5.15]: https://github.com/PolicyEngine/policyengine-api/compare/1.5.14...1.5.15
[1.5.14]: https://github.com/PolicyEngine/policyengine-api/compare/1.5.13...1.5.14
[1.5.13]: https://github.com/PolicyEngine/policyengine-api/compare/1.5.12...1.5.13
[1.5.12]: https://github.com/PolicyEngine/policyengine-api/compare/1.5.11...1.5.12
[1.5.11]: https://github.com/PolicyEngine/policyengine-api/compare/1.5.10...1.5.11
[1.5.10]: https://github.com/PolicyEngine/policyengine-api/compare/1.5.9...1.5.10
[1.5.9]: https://github.com/PolicyEngine/policyengine-api/compare/1.5.8...1.5.9
[1.5.8]: https://github.com/PolicyEngine/policyengine-api/compare/1.5.7...1.5.8
[1.5.7]: https://github.com/PolicyEngine/policyengine-api/compare/1.5.6...1.5.7
[1.5.6]: https://github.com/PolicyEngine/policyengine-api/compare/1.5.5...1.5.6
[1.5.5]: https://github.com/PolicyEngine/policyengine-api/compare/1.5.4...1.5.5
[1.5.4]: https://github.com/PolicyEngine/policyengine-api/compare/1.5.3...1.5.4
[1.5.3]: https://github.com/PolicyEngine/policyengine-api/compare/1.5.2...1.5.3
[1.5.2]: https://github.com/PolicyEngine/policyengine-api/compare/1.5.1...1.5.2
[1.5.1]: https://github.com/PolicyEngine/policyengine-api/compare/1.5.0...1.5.1
[1.5.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.4.8...1.5.0
[1.4.8]: https://github.com/PolicyEngine/policyengine-api/compare/1.4.7...1.4.8
[1.4.7]: https://github.com/PolicyEngine/policyengine-api/compare/1.4.6...1.4.7
[1.4.6]: https://github.com/PolicyEngine/policyengine-api/compare/1.4.5...1.4.6
[1.4.5]: https://github.com/PolicyEngine/policyengine-api/compare/1.4.4...1.4.5
[1.4.4]: https://github.com/PolicyEngine/policyengine-api/compare/1.4.3...1.4.4
[1.4.3]: https://github.com/PolicyEngine/policyengine-api/compare/1.4.2...1.4.3
[1.4.2]: https://github.com/PolicyEngine/policyengine-api/compare/1.4.1...1.4.2
[1.4.1]: https://github.com/PolicyEngine/policyengine-api/compare/1.4.0...1.4.1
[1.4.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.3.10...1.4.0
[1.3.10]: https://github.com/PolicyEngine/policyengine-api/compare/1.3.9...1.3.10
[1.3.9]: https://github.com/PolicyEngine/policyengine-api/compare/1.3.8...1.3.9
[1.3.8]: https://github.com/PolicyEngine/policyengine-api/compare/1.3.7...1.3.8
[1.3.7]: https://github.com/PolicyEngine/policyengine-api/compare/1.3.6...1.3.7
[1.3.6]: https://github.com/PolicyEngine/policyengine-api/compare/1.3.5...1.3.6
[1.3.5]: https://github.com/PolicyEngine/policyengine-api/compare/1.3.4...1.3.5
[1.3.4]: https://github.com/PolicyEngine/policyengine-api/compare/1.3.3...1.3.4
[1.3.3]: https://github.com/PolicyEngine/policyengine-api/compare/1.3.2...1.3.3
[1.3.2]: https://github.com/PolicyEngine/policyengine-api/compare/1.3.1...1.3.2
[1.3.1]: https://github.com/PolicyEngine/policyengine-api/compare/1.3.0...1.3.1
[1.3.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.2.5...1.3.0
[1.2.5]: https://github.com/PolicyEngine/policyengine-api/compare/1.2.4...1.2.5
[1.2.4]: https://github.com/PolicyEngine/policyengine-api/compare/1.2.3...1.2.4
[1.2.3]: https://github.com/PolicyEngine/policyengine-api/compare/1.2.2...1.2.3
[1.2.2]: https://github.com/PolicyEngine/policyengine-api/compare/1.2.1...1.2.2
[1.2.1]: https://github.com/PolicyEngine/policyengine-api/compare/1.2.0...1.2.1
[1.2.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.1.7...1.2.0
[1.1.7]: https://github.com/PolicyEngine/policyengine-api/compare/1.1.6...1.1.7
[1.1.6]: https://github.com/PolicyEngine/policyengine-api/compare/1.1.5...1.1.6
[1.1.5]: https://github.com/PolicyEngine/policyengine-api/compare/1.1.4...1.1.5
[1.1.4]: https://github.com/PolicyEngine/policyengine-api/compare/1.1.3...1.1.4
[1.1.3]: https://github.com/PolicyEngine/policyengine-api/compare/1.1.2...1.1.3
[1.1.2]: https://github.com/PolicyEngine/policyengine-api/compare/1.1.1...1.1.2
[1.1.1]: https://github.com/PolicyEngine/policyengine-api/compare/1.1.0...1.1.1
[1.1.0]: https://github.com/PolicyEngine/policyengine-api/compare/1.0.7...1.1.0
[1.0.7]: https://github.com/PolicyEngine/policyengine-api/compare/1.0.6...1.0.7
[1.0.6]: https://github.com/PolicyEngine/policyengine-api/compare/1.0.5...1.0.6
[1.0.5]: https://github.com/PolicyEngine/policyengine-api/compare/1.0.4...1.0.5
[1.0.4]: https://github.com/PolicyEngine/policyengine-api/compare/1.0.3...1.0.4
[1.0.3]: https://github.com/PolicyEngine/policyengine-api/compare/1.0.2...1.0.3
[1.0.2]: https://github.com/PolicyEngine/policyengine-api/compare/1.0.1...1.0.2
[1.0.1]: https://github.com/PolicyEngine/policyengine-api/compare/1.0.0...1.0.1
[1.0.0]: https://github.com/PolicyEngine/policyengine-api/compare/0.13.25...1.0.0
[0.13.25]: https://github.com/PolicyEngine/policyengine-api/compare/0.13.24...0.13.25
[0.13.24]: https://github.com/PolicyEngine/policyengine-api/compare/0.13.23...0.13.24
[0.13.23]: https://github.com/PolicyEngine/policyengine-api/compare/0.13.22...0.13.23
[0.13.22]: https://github.com/PolicyEngine/policyengine-api/compare/0.13.21...0.13.22
[0.13.21]: https://github.com/PolicyEngine/policyengine-api/compare/0.13.20...0.13.21
[0.13.20]: https://github.com/PolicyEngine/policyengine-api/compare/0.13.19...0.13.20
[0.13.19]: https://github.com/PolicyEngine/policyengine-api/compare/0.13.18...0.13.19
[0.13.18]: https://github.com/PolicyEngine/policyengine-api/compare/0.13.17...0.13.18
[0.13.17]: https://github.com/PolicyEngine/policyengine-api/compare/0.13.16...0.13.17
[0.13.16]: https://github.com/PolicyEngine/policyengine-api/compare/0.13.15...0.13.16
[0.13.15]: https://github.com/PolicyEngine/policyengine-api/compare/0.13.14...0.13.15
[0.13.14]: https://github.com/PolicyEngine/policyengine-api/compare/0.13.13...0.13.14
[0.13.13]: https://github.com/PolicyEngine/policyengine-api/compare/0.13.12...0.13.13
[0.13.12]: https://github.com/PolicyEngine/policyengine-api/compare/0.13.11...0.13.12
[0.13.11]: https://github.com/PolicyEngine/policyengine-api/compare/0.13.10...0.13.11
[0.13.10]: https://github.com/PolicyEngine/policyengine-api/compare/0.13.9...0.13.10
[0.13.9]: https://github.com/PolicyEngine/policyengine-api/compare/0.13.8...0.13.9
[0.13.8]: https://github.com/PolicyEngine/policyengine-api/compare/0.13.7...0.13.8
[0.13.7]: https://github.com/PolicyEngine/policyengine-api/compare/0.13.6...0.13.7
[0.13.6]: https://github.com/PolicyEngine/policyengine-api/compare/0.13.5...0.13.6
[0.13.5]: https://github.com/PolicyEngine/policyengine-api/compare/0.13.4...0.13.5
[0.13.4]: https://github.com/PolicyEngine/policyengine-api/compare/0.13.3...0.13.4
[0.13.3]: https://github.com/PolicyEngine/policyengine-api/compare/0.13.2...0.13.3
[0.13.2]: https://github.com/PolicyEngine/policyengine-api/compare/0.13.1...0.13.2
[0.13.1]: https://github.com/PolicyEngine/policyengine-api/compare/0.13.0...0.13.1
[0.13.0]: https://github.com/PolicyEngine/policyengine-api/compare/0.12.4...0.13.0
[0.12.4]: https://github.com/PolicyEngine/policyengine-api/compare/0.12.3...0.12.4
[0.12.3]: https://github.com/PolicyEngine/policyengine-api/compare/0.12.2...0.12.3
[0.12.2]: https://github.com/PolicyEngine/policyengine-api/compare/0.12.1...0.12.2
[0.12.1]: https://github.com/PolicyEngine/policyengine-api/compare/0.12.0...0.12.1
[0.12.0]: https://github.com/PolicyEngine/policyengine-api/compare/0.11.18...0.12.0
[0.11.18]: https://github.com/PolicyEngine/policyengine-api/compare/0.11.17...0.11.18
[0.11.17]: https://github.com/PolicyEngine/policyengine-api/compare/0.11.16...0.11.17
[0.11.16]: https://github.com/PolicyEngine/policyengine-api/compare/0.11.15...0.11.16
[0.11.15]: https://github.com/PolicyEngine/policyengine-api/compare/0.11.14...0.11.15
[0.11.14]: https://github.com/PolicyEngine/policyengine-api/compare/0.11.13...0.11.14
[0.11.13]: https://github.com/PolicyEngine/policyengine-api/compare/0.11.12...0.11.13
[0.11.12]: https://github.com/PolicyEngine/policyengine-api/compare/0.11.11...0.11.12
[0.11.11]: https://github.com/PolicyEngine/policyengine-api/compare/0.11.10...0.11.11
[0.11.10]: https://github.com/PolicyEngine/policyengine-api/compare/0.11.9...0.11.10
[0.11.9]: https://github.com/PolicyEngine/policyengine-api/compare/0.11.8...0.11.9
[0.11.8]: https://github.com/PolicyEngine/policyengine-api/compare/0.11.7...0.11.8
[0.11.7]: https://github.com/PolicyEngine/policyengine-api/compare/0.11.6...0.11.7
[0.11.6]: https://github.com/PolicyEngine/policyengine-api/compare/0.11.5...0.11.6
[0.11.5]: https://github.com/PolicyEngine/policyengine-api/compare/0.11.4...0.11.5
[0.11.4]: https://github.com/PolicyEngine/policyengine-api/compare/0.11.3...0.11.4
[0.11.3]: https://github.com/PolicyEngine/policyengine-api/compare/0.11.2...0.11.3
[0.11.2]: https://github.com/PolicyEngine/policyengine-api/compare/0.11.1...0.11.2
[0.11.1]: https://github.com/PolicyEngine/policyengine-api/compare/0.11.0...0.11.1
[0.11.0]: https://github.com/PolicyEngine/policyengine-api/compare/0.10.3...0.11.0
[0.10.3]: https://github.com/PolicyEngine/policyengine-api/compare/0.10.2...0.10.3
[0.10.2]: https://github.com/PolicyEngine/policyengine-api/compare/0.10.1...0.10.2
[0.10.1]: https://github.com/PolicyEngine/policyengine-api/compare/0.10.0...0.10.1
[0.10.0]: https://github.com/PolicyEngine/policyengine-api/compare/0.9.22...0.10.0
[0.9.22]: https://github.com/PolicyEngine/policyengine-api/compare/0.9.21...0.9.22
[0.9.21]: https://github.com/PolicyEngine/policyengine-api/compare/0.9.20...0.9.21
[0.9.20]: https://github.com/PolicyEngine/policyengine-api/compare/0.9.19...0.9.20
[0.9.19]: https://github.com/PolicyEngine/policyengine-api/compare/0.9.18...0.9.19
[0.9.18]: https://github.com/PolicyEngine/policyengine-api/compare/0.9.17...0.9.18
[0.9.17]: https://github.com/PolicyEngine/policyengine-api/compare/0.9.16...0.9.17
[0.9.16]: https://github.com/PolicyEngine/policyengine-api/compare/0.9.15...0.9.16
[0.9.15]: https://github.com/PolicyEngine/policyengine-api/compare/0.9.14...0.9.15
[0.9.14]: https://github.com/PolicyEngine/policyengine-api/compare/0.9.13...0.9.14
[0.9.13]: https://github.com/PolicyEngine/policyengine-api/compare/0.9.12...0.9.13
[0.9.12]: https://github.com/PolicyEngine/policyengine-api/compare/0.9.11...0.9.12
[0.9.11]: https://github.com/PolicyEngine/policyengine-api/compare/0.9.10...0.9.11
[0.9.10]: https://github.com/PolicyEngine/policyengine-api/compare/0.9.9...0.9.10
[0.9.9]: https://github.com/PolicyEngine/policyengine-api/compare/0.9.8...0.9.9
[0.9.8]: https://github.com/PolicyEngine/policyengine-api/compare/0.9.7...0.9.8
[0.9.7]: https://github.com/PolicyEngine/policyengine-api/compare/0.9.6...0.9.7
[0.9.6]: https://github.com/PolicyEngine/policyengine-api/compare/0.9.5...0.9.6
[0.9.5]: https://github.com/PolicyEngine/policyengine-api/compare/0.9.4...0.9.5
[0.9.4]: https://github.com/PolicyEngine/policyengine-api/compare/0.9.3...0.9.4
[0.9.3]: https://github.com/PolicyEngine/policyengine-api/compare/0.9.2...0.9.3
[0.9.2]: https://github.com/PolicyEngine/policyengine-api/compare/0.9.1...0.9.2
[0.9.1]: https://github.com/PolicyEngine/policyengine-api/compare/0.9.0...0.9.1
[0.9.0]: https://github.com/PolicyEngine/policyengine-api/compare/0.8.19...0.9.0
[0.8.19]: https://github.com/PolicyEngine/policyengine-api/compare/0.8.18...0.8.19
[0.8.18]: https://github.com/PolicyEngine/policyengine-api/compare/0.8.17...0.8.18
[0.8.17]: https://github.com/PolicyEngine/policyengine-api/compare/0.8.16...0.8.17
[0.8.16]: https://github.com/PolicyEngine/policyengine-api/compare/0.8.15...0.8.16
[0.8.15]: https://github.com/PolicyEngine/policyengine-api/compare/0.8.14...0.8.15
[0.8.14]: https://github.com/PolicyEngine/policyengine-api/compare/0.8.13...0.8.14
[0.8.13]: https://github.com/PolicyEngine/policyengine-api/compare/0.8.12...0.8.13
[0.8.12]: https://github.com/PolicyEngine/policyengine-api/compare/0.8.11...0.8.12
[0.8.11]: https://github.com/PolicyEngine/policyengine-api/compare/0.8.10...0.8.11
[0.8.10]: https://github.com/PolicyEngine/policyengine-api/compare/0.8.9...0.8.10
[0.8.9]: https://github.com/PolicyEngine/policyengine-api/compare/0.8.8...0.8.9
[0.8.8]: https://github.com/PolicyEngine/policyengine-api/compare/0.8.7...0.8.8
[0.8.7]: https://github.com/PolicyEngine/policyengine-api/compare/0.8.6...0.8.7
[0.8.6]: https://github.com/PolicyEngine/policyengine-api/compare/0.8.5...0.8.6
[0.8.5]: https://github.com/PolicyEngine/policyengine-api/compare/0.8.4...0.8.5
[0.8.4]: https://github.com/PolicyEngine/policyengine-api/compare/0.8.3...0.8.4
[0.8.3]: https://github.com/PolicyEngine/policyengine-api/compare/0.8.2...0.8.3
[0.8.2]: https://github.com/PolicyEngine/policyengine-api/compare/0.8.1...0.8.2
[0.8.1]: https://github.com/PolicyEngine/policyengine-api/compare/0.8.0...0.8.1
[0.8.0]: https://github.com/PolicyEngine/policyengine-api/compare/0.7.30...0.8.0
[0.7.30]: https://github.com/PolicyEngine/policyengine-api/compare/0.7.29...0.7.30
[0.7.29]: https://github.com/PolicyEngine/policyengine-api/compare/0.7.28...0.7.29
[0.7.28]: https://github.com/PolicyEngine/policyengine-api/compare/0.7.27...0.7.28
[0.7.27]: https://github.com/PolicyEngine/policyengine-api/compare/0.7.26...0.7.27
[0.7.26]: https://github.com/PolicyEngine/policyengine-api/compare/0.7.25...0.7.26
[0.7.25]: https://github.com/PolicyEngine/policyengine-api/compare/0.7.24...0.7.25
[0.7.24]: https://github.com/PolicyEngine/policyengine-api/compare/0.7.23...0.7.24
[0.7.23]: https://github.com/PolicyEngine/policyengine-api/compare/0.7.22...0.7.23
[0.7.22]: https://github.com/PolicyEngine/policyengine-api/compare/0.7.21...0.7.22
[0.7.21]: https://github.com/PolicyEngine/policyengine-api/compare/0.7.20...0.7.21
[0.7.20]: https://github.com/PolicyEngine/policyengine-api/compare/0.7.19...0.7.20
[0.7.19]: https://github.com/PolicyEngine/policyengine-api/compare/0.7.18...0.7.19
[0.7.18]: https://github.com/PolicyEngine/policyengine-api/compare/0.7.17...0.7.18
[0.7.17]: https://github.com/PolicyEngine/policyengine-api/compare/0.7.16...0.7.17
[0.7.16]: https://github.com/PolicyEngine/policyengine-api/compare/0.7.15...0.7.16
[0.7.15]: https://github.com/PolicyEngine/policyengine-api/compare/0.7.14...0.7.15
[0.7.14]: https://github.com/PolicyEngine/policyengine-api/compare/0.7.13...0.7.14
[0.7.13]: https://github.com/PolicyEngine/policyengine-api/compare/0.7.12...0.7.13
[0.7.12]: https://github.com/PolicyEngine/policyengine-api/compare/0.7.11...0.7.12
[0.7.11]: https://github.com/PolicyEngine/policyengine-api/compare/0.7.10...0.7.11
[0.7.10]: https://github.com/PolicyEngine/policyengine-api/compare/0.7.9...0.7.10
[0.7.9]: https://github.com/PolicyEngine/policyengine-api/compare/0.7.8...0.7.9
[0.7.8]: https://github.com/PolicyEngine/policyengine-api/compare/0.7.7...0.7.8
[0.7.7]: https://github.com/PolicyEngine/policyengine-api/compare/0.7.6...0.7.7
[0.7.6]: https://github.com/PolicyEngine/policyengine-api/compare/0.7.5...0.7.6
[0.7.5]: https://github.com/PolicyEngine/policyengine-api/compare/0.7.4...0.7.5
[0.7.4]: https://github.com/PolicyEngine/policyengine-api/compare/0.7.3...0.7.4
[0.7.3]: https://github.com/PolicyEngine/policyengine-api/compare/0.7.2...0.7.3
[0.7.2]: https://github.com/PolicyEngine/policyengine-api/compare/0.7.1...0.7.2
[0.7.1]: https://github.com/PolicyEngine/policyengine-api/compare/0.7.0...0.7.1
[0.7.0]: https://github.com/PolicyEngine/policyengine-api/compare/0.6.10...0.7.0
[0.6.10]: https://github.com/PolicyEngine/policyengine-api/compare/0.6.9...0.6.10
[0.6.9]: https://github.com/PolicyEngine/policyengine-api/compare/0.6.8...0.6.9
[0.6.8]: https://github.com/PolicyEngine/policyengine-api/compare/0.6.7...0.6.8
[0.6.7]: https://github.com/PolicyEngine/policyengine-api/compare/0.6.6...0.6.7
[0.6.6]: https://github.com/PolicyEngine/policyengine-api/compare/0.6.5...0.6.6
[0.6.5]: https://github.com/PolicyEngine/policyengine-api/compare/0.6.4...0.6.5
[0.6.4]: https://github.com/PolicyEngine/policyengine-api/compare/0.6.3...0.6.4
[0.6.3]: https://github.com/PolicyEngine/policyengine-api/compare/0.6.2...0.6.3
[0.6.2]: https://github.com/PolicyEngine/policyengine-api/compare/0.6.1...0.6.2
[0.6.1]: https://github.com/PolicyEngine/policyengine-api/compare/0.6.0...0.6.1
[0.6.0]: https://github.com/PolicyEngine/policyengine-api/compare/0.5.7...0.6.0
[0.5.7]: https://github.com/PolicyEngine/policyengine-api/compare/0.5.6...0.5.7
[0.5.6]: https://github.com/PolicyEngine/policyengine-api/compare/0.5.5...0.5.6
[0.5.5]: https://github.com/PolicyEngine/policyengine-api/compare/0.5.4...0.5.5
[0.5.4]: https://github.com/PolicyEngine/policyengine-api/compare/0.5.3...0.5.4
[0.5.3]: https://github.com/PolicyEngine/policyengine-api/compare/0.5.2...0.5.3
[0.5.2]: https://github.com/PolicyEngine/policyengine-api/compare/0.5.1...0.5.2
[0.5.1]: https://github.com/PolicyEngine/policyengine-api/compare/0.5.0...0.5.1
[0.5.0]: https://github.com/PolicyEngine/policyengine-api/compare/0.4.2...0.5.0
[0.4.2]: https://github.com/PolicyEngine/policyengine-api/compare/0.4.1...0.4.2
[0.4.1]: https://github.com/PolicyEngine/policyengine-api/compare/0.4.0...0.4.1
[0.4.0]: https://github.com/PolicyEngine/policyengine-api/compare/0.3.6...0.4.0
[0.3.6]: https://github.com/PolicyEngine/policyengine-api/compare/0.3.5...0.3.6
[0.3.5]: https://github.com/PolicyEngine/policyengine-api/compare/0.3.4...0.3.5
[0.3.4]: https://github.com/PolicyEngine/policyengine-api/compare/0.3.3...0.3.4
[0.3.3]: https://github.com/PolicyEngine/policyengine-api/compare/0.3.2...0.3.3
[0.3.2]: https://github.com/PolicyEngine/policyengine-api/compare/0.3.1...0.3.2
[0.3.1]: https://github.com/PolicyEngine/policyengine-api/compare/0.3.0...0.3.1
[0.3.0]: https://github.com/PolicyEngine/policyengine-api/compare/0.2.5...0.3.0
[0.2.5]: https://github.com/PolicyEngine/policyengine-api/compare/0.2.4...0.2.5
[0.2.4]: https://github.com/PolicyEngine/policyengine-api/compare/0.2.3...0.2.4
[0.2.3]: https://github.com/PolicyEngine/policyengine-api/compare/0.2.2...0.2.3
[0.2.2]: https://github.com/PolicyEngine/policyengine-api/compare/0.2.1...0.2.2
[0.2.1]: https://github.com/PolicyEngine/policyengine-api/compare/0.2.0...0.2.1
[0.2.0]: https://github.com/PolicyEngine/policyengine-api/compare/0.1.12...0.2.0
[0.1.12]: https://github.com/PolicyEngine/policyengine-api/compare/0.1.11...0.1.12
[0.1.11]: https://github.com/PolicyEngine/policyengine-api/compare/0.1.10...0.1.11
[0.1.10]: https://github.com/PolicyEngine/policyengine-api/compare/0.1.9...0.1.10
[0.1.9]: https://github.com/PolicyEngine/policyengine-api/compare/0.1.8...0.1.9
[0.1.8]: https://github.com/PolicyEngine/policyengine-api/compare/0.1.7...0.1.8
[0.1.7]: https://github.com/PolicyEngine/policyengine-api/compare/0.1.6...0.1.7
[0.1.6]: https://github.com/PolicyEngine/policyengine-api/compare/0.1.5...0.1.6
[0.1.5]: https://github.com/PolicyEngine/policyengine-api/compare/0.1.4...0.1.5
[0.1.4]: https://github.com/PolicyEngine/policyengine-api/compare/0.1.3...0.1.4
[0.1.3]: https://github.com/PolicyEngine/policyengine-api/compare/0.1.2...0.1.3
[0.1.2]: https://github.com/PolicyEngine/policyengine-api/compare/0.1.1...0.1.2
[0.1.1]: https://github.com/PolicyEngine/policyengine-api/compare/0.1.0...0.1.1
