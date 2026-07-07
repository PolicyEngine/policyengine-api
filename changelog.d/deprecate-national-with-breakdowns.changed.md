Deprecated the `national-with-breakdowns`, `national-with-breakdowns-test`, and
`national-with-datasets` economy dataset aliases. API v1 now treats these as
the default certified dataset and ignores the old district-breakdown query flag,
so congressional district output can pass through from the sim API.
