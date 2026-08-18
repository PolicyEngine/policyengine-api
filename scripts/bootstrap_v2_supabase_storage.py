"""Explicit operator entry point for Stage 8 Supabase Storage bootstrap."""

import json

from policyengine_api.data.v2.settings import load_supabase_storage_settings
from policyengine_api.data.v2.storage_bootstrap import initialize_supabase_storage


def main() -> None:
    settings = load_supabase_storage_settings()
    result = initialize_supabase_storage(settings)
    print(
        json.dumps(
            {
                "bucket": result.bucket,
                "created": result.created,
                "environment": result.environment,
                "project_ref": result.project_ref,
                "public": result.public,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
