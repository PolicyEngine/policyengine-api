v2 metadata reads run in autocommit read-only sessions on the shared pool, so each request sends no BEGIN or ROLLBACK to the database (two fewer round trips per request).
