Serialize local sqlite initialization under a file lock so concurrent gunicorn worker boots cannot race the seed inserts or observe a partially initialized database.
