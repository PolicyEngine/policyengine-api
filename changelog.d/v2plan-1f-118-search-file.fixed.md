Responses are gzip-compressed only for a client whose Accept-Encoding accepts gzip: a client that refuses it (for example gzip;q=0) now receives an uncompressed response instead of a gzip one.
