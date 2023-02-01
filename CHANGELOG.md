# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), 
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
