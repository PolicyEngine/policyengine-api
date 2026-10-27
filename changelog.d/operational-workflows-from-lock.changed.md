The Cloud SQL migration and household mirror-event workflows install their dependencies from uv.lock and run their scripts through uv run --frozen, instead of an unlocked pip install.
