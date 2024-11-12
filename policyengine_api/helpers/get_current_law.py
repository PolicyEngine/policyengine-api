def get_current_law_policy_id(country_id: str) -> int:
    return {
        "uk": 1,
        "us": 2,
        "ca": 3,
        "ng": 4,
    }[country_id]