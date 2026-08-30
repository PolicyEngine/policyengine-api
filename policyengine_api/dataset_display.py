"""User-facing labels for certified PolicyEngine dataset families."""

from __future__ import annotations


DATASET_FAMILY_DISPLAY_LABELS = (
    ("populace_", "Microcosm"),
    ("enhanced_frs_", "Enhanced FRS"),
)
DEFAULT_DATASET_DISPLAY_LABEL = "Certified dataset"


def get_dataset_display_label(dataset_name: object) -> str:
    """Return the public label for an internal logical dataset name."""

    normalized_name = str(dataset_name or "")
    for prefix, label in DATASET_FAMILY_DISPLAY_LABELS:
        if normalized_name.startswith(prefix):
            return label
    return DEFAULT_DATASET_DISPLAY_LABEL
