"""
US Congressional District Metadata

This module defines the metadata for all 435 US Congressional districts
based on the 2020 Census apportionment, effective for the 118th Congress
(2023-2025) and continuing through the 119th Congress (2025-2027).

Source: https://ballotpedia.org/Congressional_apportionment_after_the_2020_census
Census Data: https://www.census.gov/data/tables/2020/dec/2020-apportionment-data.html
"""

from pydantic import BaseModel, Field


class CongressionalDistrictMetadataItem(BaseModel):
    """
    Metadata for a single US Congressional district.

    Uses Pydantic BaseModel for:
    - Runtime validation of data integrity
    - Automatic serialization/deserialization
    - Consistency with existing codebase patterns (see policyengine_api/endpoints/economy/compare.py)
    - Self-documenting schema with type hints
    """

    state_code: str = Field(
        ...,
        description="Two-letter US state code (uppercase)",
        min_length=2,
        max_length=2,
        pattern="^[A-Z]{2}$"
    )
    number: int = Field(
        ...,
        description="Congressional district number (1 for at-large districts)",
        ge=1
    )


# All 435 US Congressional districts based on 2020 Census apportionment
CONGRESSIONAL_DISTRICTS: list[CongressionalDistrictMetadataItem] = [
    # Alabama - 7 districts
    CongressionalDistrictMetadataItem(state_code="AL", number=1),
    CongressionalDistrictMetadataItem(state_code="AL", number=2),
    CongressionalDistrictMetadataItem(state_code="AL", number=3),
    CongressionalDistrictMetadataItem(state_code="AL", number=4),
    CongressionalDistrictMetadataItem(state_code="AL", number=5),
    CongressionalDistrictMetadataItem(state_code="AL", number=6),
    CongressionalDistrictMetadataItem(state_code="AL", number=7),

    # Alaska - 1 at-large district
    CongressionalDistrictMetadataItem(state_code="AK", number=1),

    # Arizona - 9 districts
    CongressionalDistrictMetadataItem(state_code="AZ", number=1),
    CongressionalDistrictMetadataItem(state_code="AZ", number=2),
    CongressionalDistrictMetadataItem(state_code="AZ", number=3),
    CongressionalDistrictMetadataItem(state_code="AZ", number=4),
    CongressionalDistrictMetadataItem(state_code="AZ", number=5),
    CongressionalDistrictMetadataItem(state_code="AZ", number=6),
    CongressionalDistrictMetadataItem(state_code="AZ", number=7),
    CongressionalDistrictMetadataItem(state_code="AZ", number=8),
    CongressionalDistrictMetadataItem(state_code="AZ", number=9),

    # Arkansas - 4 districts
    CongressionalDistrictMetadataItem(state_code="AR", number=1),
    CongressionalDistrictMetadataItem(state_code="AR", number=2),
    CongressionalDistrictMetadataItem(state_code="AR", number=3),
    CongressionalDistrictMetadataItem(state_code="AR", number=4),

    # California - 52 districts
    CongressionalDistrictMetadataItem(state_code="CA", number=1),
    CongressionalDistrictMetadataItem(state_code="CA", number=2),
    CongressionalDistrictMetadataItem(state_code="CA", number=3),
    CongressionalDistrictMetadataItem(state_code="CA", number=4),
    CongressionalDistrictMetadataItem(state_code="CA", number=5),
    CongressionalDistrictMetadataItem(state_code="CA", number=6),
    CongressionalDistrictMetadataItem(state_code="CA", number=7),
    CongressionalDistrictMetadataItem(state_code="CA", number=8),
    CongressionalDistrictMetadataItem(state_code="CA", number=9),
    CongressionalDistrictMetadataItem(state_code="CA", number=10),
    CongressionalDistrictMetadataItem(state_code="CA", number=11),
    CongressionalDistrictMetadataItem(state_code="CA", number=12),
    CongressionalDistrictMetadataItem(state_code="CA", number=13),
    CongressionalDistrictMetadataItem(state_code="CA", number=14),
    CongressionalDistrictMetadataItem(state_code="CA", number=15),
    CongressionalDistrictMetadataItem(state_code="CA", number=16),
    CongressionalDistrictMetadataItem(state_code="CA", number=17),
    CongressionalDistrictMetadataItem(state_code="CA", number=18),
    CongressionalDistrictMetadataItem(state_code="CA", number=19),
    CongressionalDistrictMetadataItem(state_code="CA", number=20),
    CongressionalDistrictMetadataItem(state_code="CA", number=21),
    CongressionalDistrictMetadataItem(state_code="CA", number=22),
    CongressionalDistrictMetadataItem(state_code="CA", number=23),
    CongressionalDistrictMetadataItem(state_code="CA", number=24),
    CongressionalDistrictMetadataItem(state_code="CA", number=25),
    CongressionalDistrictMetadataItem(state_code="CA", number=26),
    CongressionalDistrictMetadataItem(state_code="CA", number=27),
    CongressionalDistrictMetadataItem(state_code="CA", number=28),
    CongressionalDistrictMetadataItem(state_code="CA", number=29),
    CongressionalDistrictMetadataItem(state_code="CA", number=30),
    CongressionalDistrictMetadataItem(state_code="CA", number=31),
    CongressionalDistrictMetadataItem(state_code="CA", number=32),
    CongressionalDistrictMetadataItem(state_code="CA", number=33),
    CongressionalDistrictMetadataItem(state_code="CA", number=34),
    CongressionalDistrictMetadataItem(state_code="CA", number=35),
    CongressionalDistrictMetadataItem(state_code="CA", number=36),
    CongressionalDistrictMetadataItem(state_code="CA", number=37),
    CongressionalDistrictMetadataItem(state_code="CA", number=38),
    CongressionalDistrictMetadataItem(state_code="CA", number=39),
    CongressionalDistrictMetadataItem(state_code="CA", number=40),
    CongressionalDistrictMetadataItem(state_code="CA", number=41),
    CongressionalDistrictMetadataItem(state_code="CA", number=42),
    CongressionalDistrictMetadataItem(state_code="CA", number=43),
    CongressionalDistrictMetadataItem(state_code="CA", number=44),
    CongressionalDistrictMetadataItem(state_code="CA", number=45),
    CongressionalDistrictMetadataItem(state_code="CA", number=46),
    CongressionalDistrictMetadataItem(state_code="CA", number=47),
    CongressionalDistrictMetadataItem(state_code="CA", number=48),
    CongressionalDistrictMetadataItem(state_code="CA", number=49),
    CongressionalDistrictMetadataItem(state_code="CA", number=50),
    CongressionalDistrictMetadataItem(state_code="CA", number=51),
    CongressionalDistrictMetadataItem(state_code="CA", number=52),

    # Colorado - 8 districts
    CongressionalDistrictMetadataItem(state_code="CO", number=1),
    CongressionalDistrictMetadataItem(state_code="CO", number=2),
    CongressionalDistrictMetadataItem(state_code="CO", number=3),
    CongressionalDistrictMetadataItem(state_code="CO", number=4),
    CongressionalDistrictMetadataItem(state_code="CO", number=5),
    CongressionalDistrictMetadataItem(state_code="CO", number=6),
    CongressionalDistrictMetadataItem(state_code="CO", number=7),
    CongressionalDistrictMetadataItem(state_code="CO", number=8),

    # Connecticut - 5 districts
    CongressionalDistrictMetadataItem(state_code="CT", number=1),
    CongressionalDistrictMetadataItem(state_code="CT", number=2),
    CongressionalDistrictMetadataItem(state_code="CT", number=3),
    CongressionalDistrictMetadataItem(state_code="CT", number=4),
    CongressionalDistrictMetadataItem(state_code="CT", number=5),

    # Delaware - 1 at-large district
    CongressionalDistrictMetadataItem(state_code="DE", number=1),

    # Florida - 28 districts
    CongressionalDistrictMetadataItem(state_code="FL", number=1),
    CongressionalDistrictMetadataItem(state_code="FL", number=2),
    CongressionalDistrictMetadataItem(state_code="FL", number=3),
    CongressionalDistrictMetadataItem(state_code="FL", number=4),
    CongressionalDistrictMetadataItem(state_code="FL", number=5),
    CongressionalDistrictMetadataItem(state_code="FL", number=6),
    CongressionalDistrictMetadataItem(state_code="FL", number=7),
    CongressionalDistrictMetadataItem(state_code="FL", number=8),
    CongressionalDistrictMetadataItem(state_code="FL", number=9),
    CongressionalDistrictMetadataItem(state_code="FL", number=10),
    CongressionalDistrictMetadataItem(state_code="FL", number=11),
    CongressionalDistrictMetadataItem(state_code="FL", number=12),
    CongressionalDistrictMetadataItem(state_code="FL", number=13),
    CongressionalDistrictMetadataItem(state_code="FL", number=14),
    CongressionalDistrictMetadataItem(state_code="FL", number=15),
    CongressionalDistrictMetadataItem(state_code="FL", number=16),
    CongressionalDistrictMetadataItem(state_code="FL", number=17),
    CongressionalDistrictMetadataItem(state_code="FL", number=18),
    CongressionalDistrictMetadataItem(state_code="FL", number=19),
    CongressionalDistrictMetadataItem(state_code="FL", number=20),
    CongressionalDistrictMetadataItem(state_code="FL", number=21),
    CongressionalDistrictMetadataItem(state_code="FL", number=22),
    CongressionalDistrictMetadataItem(state_code="FL", number=23),
    CongressionalDistrictMetadataItem(state_code="FL", number=24),
    CongressionalDistrictMetadataItem(state_code="FL", number=25),
    CongressionalDistrictMetadataItem(state_code="FL", number=26),
    CongressionalDistrictMetadataItem(state_code="FL", number=27),
    CongressionalDistrictMetadataItem(state_code="FL", number=28),

    # Georgia - 14 districts
    CongressionalDistrictMetadataItem(state_code="GA", number=1),
    CongressionalDistrictMetadataItem(state_code="GA", number=2),
    CongressionalDistrictMetadataItem(state_code="GA", number=3),
    CongressionalDistrictMetadataItem(state_code="GA", number=4),
    CongressionalDistrictMetadataItem(state_code="GA", number=5),
    CongressionalDistrictMetadataItem(state_code="GA", number=6),
    CongressionalDistrictMetadataItem(state_code="GA", number=7),
    CongressionalDistrictMetadataItem(state_code="GA", number=8),
    CongressionalDistrictMetadataItem(state_code="GA", number=9),
    CongressionalDistrictMetadataItem(state_code="GA", number=10),
    CongressionalDistrictMetadataItem(state_code="GA", number=11),
    CongressionalDistrictMetadataItem(state_code="GA", number=12),
    CongressionalDistrictMetadataItem(state_code="GA", number=13),
    CongressionalDistrictMetadataItem(state_code="GA", number=14),

    # Hawaii - 2 districts
    CongressionalDistrictMetadataItem(state_code="HI", number=1),
    CongressionalDistrictMetadataItem(state_code="HI", number=2),

    # Idaho - 2 districts
    CongressionalDistrictMetadataItem(state_code="ID", number=1),
    CongressionalDistrictMetadataItem(state_code="ID", number=2),

    # Illinois - 17 districts
    CongressionalDistrictMetadataItem(state_code="IL", number=1),
    CongressionalDistrictMetadataItem(state_code="IL", number=2),
    CongressionalDistrictMetadataItem(state_code="IL", number=3),
    CongressionalDistrictMetadataItem(state_code="IL", number=4),
    CongressionalDistrictMetadataItem(state_code="IL", number=5),
    CongressionalDistrictMetadataItem(state_code="IL", number=6),
    CongressionalDistrictMetadataItem(state_code="IL", number=7),
    CongressionalDistrictMetadataItem(state_code="IL", number=8),
    CongressionalDistrictMetadataItem(state_code="IL", number=9),
    CongressionalDistrictMetadataItem(state_code="IL", number=10),
    CongressionalDistrictMetadataItem(state_code="IL", number=11),
    CongressionalDistrictMetadataItem(state_code="IL", number=12),
    CongressionalDistrictMetadataItem(state_code="IL", number=13),
    CongressionalDistrictMetadataItem(state_code="IL", number=14),
    CongressionalDistrictMetadataItem(state_code="IL", number=15),
    CongressionalDistrictMetadataItem(state_code="IL", number=16),
    CongressionalDistrictMetadataItem(state_code="IL", number=17),

    # Indiana - 9 districts
    CongressionalDistrictMetadataItem(state_code="IN", number=1),
    CongressionalDistrictMetadataItem(state_code="IN", number=2),
    CongressionalDistrictMetadataItem(state_code="IN", number=3),
    CongressionalDistrictMetadataItem(state_code="IN", number=4),
    CongressionalDistrictMetadataItem(state_code="IN", number=5),
    CongressionalDistrictMetadataItem(state_code="IN", number=6),
    CongressionalDistrictMetadataItem(state_code="IN", number=7),
    CongressionalDistrictMetadataItem(state_code="IN", number=8),
    CongressionalDistrictMetadataItem(state_code="IN", number=9),

    # Iowa - 4 districts
    CongressionalDistrictMetadataItem(state_code="IA", number=1),
    CongressionalDistrictMetadataItem(state_code="IA", number=2),
    CongressionalDistrictMetadataItem(state_code="IA", number=3),
    CongressionalDistrictMetadataItem(state_code="IA", number=4),

    # Kansas - 4 districts
    CongressionalDistrictMetadataItem(state_code="KS", number=1),
    CongressionalDistrictMetadataItem(state_code="KS", number=2),
    CongressionalDistrictMetadataItem(state_code="KS", number=3),
    CongressionalDistrictMetadataItem(state_code="KS", number=4),

    # Kentucky - 6 districts
    CongressionalDistrictMetadataItem(state_code="KY", number=1),
    CongressionalDistrictMetadataItem(state_code="KY", number=2),
    CongressionalDistrictMetadataItem(state_code="KY", number=3),
    CongressionalDistrictMetadataItem(state_code="KY", number=4),
    CongressionalDistrictMetadataItem(state_code="KY", number=5),
    CongressionalDistrictMetadataItem(state_code="KY", number=6),

    # Louisiana - 6 districts
    CongressionalDistrictMetadataItem(state_code="LA", number=1),
    CongressionalDistrictMetadataItem(state_code="LA", number=2),
    CongressionalDistrictMetadataItem(state_code="LA", number=3),
    CongressionalDistrictMetadataItem(state_code="LA", number=4),
    CongressionalDistrictMetadataItem(state_code="LA", number=5),
    CongressionalDistrictMetadataItem(state_code="LA", number=6),

    # Maine - 2 districts
    CongressionalDistrictMetadataItem(state_code="ME", number=1),
    CongressionalDistrictMetadataItem(state_code="ME", number=2),

    # Maryland - 8 districts
    CongressionalDistrictMetadataItem(state_code="MD", number=1),
    CongressionalDistrictMetadataItem(state_code="MD", number=2),
    CongressionalDistrictMetadataItem(state_code="MD", number=3),
    CongressionalDistrictMetadataItem(state_code="MD", number=4),
    CongressionalDistrictMetadataItem(state_code="MD", number=5),
    CongressionalDistrictMetadataItem(state_code="MD", number=6),
    CongressionalDistrictMetadataItem(state_code="MD", number=7),
    CongressionalDistrictMetadataItem(state_code="MD", number=8),

    # Massachusetts - 9 districts
    CongressionalDistrictMetadataItem(state_code="MA", number=1),
    CongressionalDistrictMetadataItem(state_code="MA", number=2),
    CongressionalDistrictMetadataItem(state_code="MA", number=3),
    CongressionalDistrictMetadataItem(state_code="MA", number=4),
    CongressionalDistrictMetadataItem(state_code="MA", number=5),
    CongressionalDistrictMetadataItem(state_code="MA", number=6),
    CongressionalDistrictMetadataItem(state_code="MA", number=7),
    CongressionalDistrictMetadataItem(state_code="MA", number=8),
    CongressionalDistrictMetadataItem(state_code="MA", number=9),

    # Michigan - 13 districts
    CongressionalDistrictMetadataItem(state_code="MI", number=1),
    CongressionalDistrictMetadataItem(state_code="MI", number=2),
    CongressionalDistrictMetadataItem(state_code="MI", number=3),
    CongressionalDistrictMetadataItem(state_code="MI", number=4),
    CongressionalDistrictMetadataItem(state_code="MI", number=5),
    CongressionalDistrictMetadataItem(state_code="MI", number=6),
    CongressionalDistrictMetadataItem(state_code="MI", number=7),
    CongressionalDistrictMetadataItem(state_code="MI", number=8),
    CongressionalDistrictMetadataItem(state_code="MI", number=9),
    CongressionalDistrictMetadataItem(state_code="MI", number=10),
    CongressionalDistrictMetadataItem(state_code="MI", number=11),
    CongressionalDistrictMetadataItem(state_code="MI", number=12),
    CongressionalDistrictMetadataItem(state_code="MI", number=13),

    # Minnesota - 8 districts
    CongressionalDistrictMetadataItem(state_code="MN", number=1),
    CongressionalDistrictMetadataItem(state_code="MN", number=2),
    CongressionalDistrictMetadataItem(state_code="MN", number=3),
    CongressionalDistrictMetadataItem(state_code="MN", number=4),
    CongressionalDistrictMetadataItem(state_code="MN", number=5),
    CongressionalDistrictMetadataItem(state_code="MN", number=6),
    CongressionalDistrictMetadataItem(state_code="MN", number=7),
    CongressionalDistrictMetadataItem(state_code="MN", number=8),

    # Mississippi - 4 districts
    CongressionalDistrictMetadataItem(state_code="MS", number=1),
    CongressionalDistrictMetadataItem(state_code="MS", number=2),
    CongressionalDistrictMetadataItem(state_code="MS", number=3),
    CongressionalDistrictMetadataItem(state_code="MS", number=4),

    # Missouri - 8 districts
    CongressionalDistrictMetadataItem(state_code="MO", number=1),
    CongressionalDistrictMetadataItem(state_code="MO", number=2),
    CongressionalDistrictMetadataItem(state_code="MO", number=3),
    CongressionalDistrictMetadataItem(state_code="MO", number=4),
    CongressionalDistrictMetadataItem(state_code="MO", number=5),
    CongressionalDistrictMetadataItem(state_code="MO", number=6),
    CongressionalDistrictMetadataItem(state_code="MO", number=7),
    CongressionalDistrictMetadataItem(state_code="MO", number=8),

    # Montana - 2 districts
    CongressionalDistrictMetadataItem(state_code="MT", number=1),
    CongressionalDistrictMetadataItem(state_code="MT", number=2),

    # Nebraska - 3 districts
    CongressionalDistrictMetadataItem(state_code="NE", number=1),
    CongressionalDistrictMetadataItem(state_code="NE", number=2),
    CongressionalDistrictMetadataItem(state_code="NE", number=3),

    # Nevada - 4 districts
    CongressionalDistrictMetadataItem(state_code="NV", number=1),
    CongressionalDistrictMetadataItem(state_code="NV", number=2),
    CongressionalDistrictMetadataItem(state_code="NV", number=3),
    CongressionalDistrictMetadataItem(state_code="NV", number=4),

    # New Hampshire - 2 districts
    CongressionalDistrictMetadataItem(state_code="NH", number=1),
    CongressionalDistrictMetadataItem(state_code="NH", number=2),

    # New Jersey - 12 districts
    CongressionalDistrictMetadataItem(state_code="NJ", number=1),
    CongressionalDistrictMetadataItem(state_code="NJ", number=2),
    CongressionalDistrictMetadataItem(state_code="NJ", number=3),
    CongressionalDistrictMetadataItem(state_code="NJ", number=4),
    CongressionalDistrictMetadataItem(state_code="NJ", number=5),
    CongressionalDistrictMetadataItem(state_code="NJ", number=6),
    CongressionalDistrictMetadataItem(state_code="NJ", number=7),
    CongressionalDistrictMetadataItem(state_code="NJ", number=8),
    CongressionalDistrictMetadataItem(state_code="NJ", number=9),
    CongressionalDistrictMetadataItem(state_code="NJ", number=10),
    CongressionalDistrictMetadataItem(state_code="NJ", number=11),
    CongressionalDistrictMetadataItem(state_code="NJ", number=12),

    # New Mexico - 3 districts
    CongressionalDistrictMetadataItem(state_code="NM", number=1),
    CongressionalDistrictMetadataItem(state_code="NM", number=2),
    CongressionalDistrictMetadataItem(state_code="NM", number=3),

    # New York - 26 districts
    CongressionalDistrictMetadataItem(state_code="NY", number=1),
    CongressionalDistrictMetadataItem(state_code="NY", number=2),
    CongressionalDistrictMetadataItem(state_code="NY", number=3),
    CongressionalDistrictMetadataItem(state_code="NY", number=4),
    CongressionalDistrictMetadataItem(state_code="NY", number=5),
    CongressionalDistrictMetadataItem(state_code="NY", number=6),
    CongressionalDistrictMetadataItem(state_code="NY", number=7),
    CongressionalDistrictMetadataItem(state_code="NY", number=8),
    CongressionalDistrictMetadataItem(state_code="NY", number=9),
    CongressionalDistrictMetadataItem(state_code="NY", number=10),
    CongressionalDistrictMetadataItem(state_code="NY", number=11),
    CongressionalDistrictMetadataItem(state_code="NY", number=12),
    CongressionalDistrictMetadataItem(state_code="NY", number=13),
    CongressionalDistrictMetadataItem(state_code="NY", number=14),
    CongressionalDistrictMetadataItem(state_code="NY", number=15),
    CongressionalDistrictMetadataItem(state_code="NY", number=16),
    CongressionalDistrictMetadataItem(state_code="NY", number=17),
    CongressionalDistrictMetadataItem(state_code="NY", number=18),
    CongressionalDistrictMetadataItem(state_code="NY", number=19),
    CongressionalDistrictMetadataItem(state_code="NY", number=20),
    CongressionalDistrictMetadataItem(state_code="NY", number=21),
    CongressionalDistrictMetadataItem(state_code="NY", number=22),
    CongressionalDistrictMetadataItem(state_code="NY", number=23),
    CongressionalDistrictMetadataItem(state_code="NY", number=24),
    CongressionalDistrictMetadataItem(state_code="NY", number=25),
    CongressionalDistrictMetadataItem(state_code="NY", number=26),

    # North Carolina - 14 districts
    CongressionalDistrictMetadataItem(state_code="NC", number=1),
    CongressionalDistrictMetadataItem(state_code="NC", number=2),
    CongressionalDistrictMetadataItem(state_code="NC", number=3),
    CongressionalDistrictMetadataItem(state_code="NC", number=4),
    CongressionalDistrictMetadataItem(state_code="NC", number=5),
    CongressionalDistrictMetadataItem(state_code="NC", number=6),
    CongressionalDistrictMetadataItem(state_code="NC", number=7),
    CongressionalDistrictMetadataItem(state_code="NC", number=8),
    CongressionalDistrictMetadataItem(state_code="NC", number=9),
    CongressionalDistrictMetadataItem(state_code="NC", number=10),
    CongressionalDistrictMetadataItem(state_code="NC", number=11),
    CongressionalDistrictMetadataItem(state_code="NC", number=12),
    CongressionalDistrictMetadataItem(state_code="NC", number=13),
    CongressionalDistrictMetadataItem(state_code="NC", number=14),

    # North Dakota - 1 at-large district
    CongressionalDistrictMetadataItem(state_code="ND", number=1),

    # Ohio - 15 districts
    CongressionalDistrictMetadataItem(state_code="OH", number=1),
    CongressionalDistrictMetadataItem(state_code="OH", number=2),
    CongressionalDistrictMetadataItem(state_code="OH", number=3),
    CongressionalDistrictMetadataItem(state_code="OH", number=4),
    CongressionalDistrictMetadataItem(state_code="OH", number=5),
    CongressionalDistrictMetadataItem(state_code="OH", number=6),
    CongressionalDistrictMetadataItem(state_code="OH", number=7),
    CongressionalDistrictMetadataItem(state_code="OH", number=8),
    CongressionalDistrictMetadataItem(state_code="OH", number=9),
    CongressionalDistrictMetadataItem(state_code="OH", number=10),
    CongressionalDistrictMetadataItem(state_code="OH", number=11),
    CongressionalDistrictMetadataItem(state_code="OH", number=12),
    CongressionalDistrictMetadataItem(state_code="OH", number=13),
    CongressionalDistrictMetadataItem(state_code="OH", number=14),
    CongressionalDistrictMetadataItem(state_code="OH", number=15),

    # Oklahoma - 5 districts
    CongressionalDistrictMetadataItem(state_code="OK", number=1),
    CongressionalDistrictMetadataItem(state_code="OK", number=2),
    CongressionalDistrictMetadataItem(state_code="OK", number=3),
    CongressionalDistrictMetadataItem(state_code="OK", number=4),
    CongressionalDistrictMetadataItem(state_code="OK", number=5),

    # Oregon - 6 districts
    CongressionalDistrictMetadataItem(state_code="OR", number=1),
    CongressionalDistrictMetadataItem(state_code="OR", number=2),
    CongressionalDistrictMetadataItem(state_code="OR", number=3),
    CongressionalDistrictMetadataItem(state_code="OR", number=4),
    CongressionalDistrictMetadataItem(state_code="OR", number=5),
    CongressionalDistrictMetadataItem(state_code="OR", number=6),

    # Pennsylvania - 17 districts
    CongressionalDistrictMetadataItem(state_code="PA", number=1),
    CongressionalDistrictMetadataItem(state_code="PA", number=2),
    CongressionalDistrictMetadataItem(state_code="PA", number=3),
    CongressionalDistrictMetadataItem(state_code="PA", number=4),
    CongressionalDistrictMetadataItem(state_code="PA", number=5),
    CongressionalDistrictMetadataItem(state_code="PA", number=6),
    CongressionalDistrictMetadataItem(state_code="PA", number=7),
    CongressionalDistrictMetadataItem(state_code="PA", number=8),
    CongressionalDistrictMetadataItem(state_code="PA", number=9),
    CongressionalDistrictMetadataItem(state_code="PA", number=10),
    CongressionalDistrictMetadataItem(state_code="PA", number=11),
    CongressionalDistrictMetadataItem(state_code="PA", number=12),
    CongressionalDistrictMetadataItem(state_code="PA", number=13),
    CongressionalDistrictMetadataItem(state_code="PA", number=14),
    CongressionalDistrictMetadataItem(state_code="PA", number=15),
    CongressionalDistrictMetadataItem(state_code="PA", number=16),
    CongressionalDistrictMetadataItem(state_code="PA", number=17),

    # Rhode Island - 2 districts
    CongressionalDistrictMetadataItem(state_code="RI", number=1),
    CongressionalDistrictMetadataItem(state_code="RI", number=2),

    # South Carolina - 7 districts
    CongressionalDistrictMetadataItem(state_code="SC", number=1),
    CongressionalDistrictMetadataItem(state_code="SC", number=2),
    CongressionalDistrictMetadataItem(state_code="SC", number=3),
    CongressionalDistrictMetadataItem(state_code="SC", number=4),
    CongressionalDistrictMetadataItem(state_code="SC", number=5),
    CongressionalDistrictMetadataItem(state_code="SC", number=6),
    CongressionalDistrictMetadataItem(state_code="SC", number=7),

    # South Dakota - 1 at-large district
    CongressionalDistrictMetadataItem(state_code="SD", number=1),

    # Tennessee - 9 districts
    CongressionalDistrictMetadataItem(state_code="TN", number=1),
    CongressionalDistrictMetadataItem(state_code="TN", number=2),
    CongressionalDistrictMetadataItem(state_code="TN", number=3),
    CongressionalDistrictMetadataItem(state_code="TN", number=4),
    CongressionalDistrictMetadataItem(state_code="TN", number=5),
    CongressionalDistrictMetadataItem(state_code="TN", number=6),
    CongressionalDistrictMetadataItem(state_code="TN", number=7),
    CongressionalDistrictMetadataItem(state_code="TN", number=8),
    CongressionalDistrictMetadataItem(state_code="TN", number=9),

    # Texas - 38 districts
    CongressionalDistrictMetadataItem(state_code="TX", number=1),
    CongressionalDistrictMetadataItem(state_code="TX", number=2),
    CongressionalDistrictMetadataItem(state_code="TX", number=3),
    CongressionalDistrictMetadataItem(state_code="TX", number=4),
    CongressionalDistrictMetadataItem(state_code="TX", number=5),
    CongressionalDistrictMetadataItem(state_code="TX", number=6),
    CongressionalDistrictMetadataItem(state_code="TX", number=7),
    CongressionalDistrictMetadataItem(state_code="TX", number=8),
    CongressionalDistrictMetadataItem(state_code="TX", number=9),
    CongressionalDistrictMetadataItem(state_code="TX", number=10),
    CongressionalDistrictMetadataItem(state_code="TX", number=11),
    CongressionalDistrictMetadataItem(state_code="TX", number=12),
    CongressionalDistrictMetadataItem(state_code="TX", number=13),
    CongressionalDistrictMetadataItem(state_code="TX", number=14),
    CongressionalDistrictMetadataItem(state_code="TX", number=15),
    CongressionalDistrictMetadataItem(state_code="TX", number=16),
    CongressionalDistrictMetadataItem(state_code="TX", number=17),
    CongressionalDistrictMetadataItem(state_code="TX", number=18),
    CongressionalDistrictMetadataItem(state_code="TX", number=19),
    CongressionalDistrictMetadataItem(state_code="TX", number=20),
    CongressionalDistrictMetadataItem(state_code="TX", number=21),
    CongressionalDistrictMetadataItem(state_code="TX", number=22),
    CongressionalDistrictMetadataItem(state_code="TX", number=23),
    CongressionalDistrictMetadataItem(state_code="TX", number=24),
    CongressionalDistrictMetadataItem(state_code="TX", number=25),
    CongressionalDistrictMetadataItem(state_code="TX", number=26),
    CongressionalDistrictMetadataItem(state_code="TX", number=27),
    CongressionalDistrictMetadataItem(state_code="TX", number=28),
    CongressionalDistrictMetadataItem(state_code="TX", number=29),
    CongressionalDistrictMetadataItem(state_code="TX", number=30),
    CongressionalDistrictMetadataItem(state_code="TX", number=31),
    CongressionalDistrictMetadataItem(state_code="TX", number=32),
    CongressionalDistrictMetadataItem(state_code="TX", number=33),
    CongressionalDistrictMetadataItem(state_code="TX", number=34),
    CongressionalDistrictMetadataItem(state_code="TX", number=35),
    CongressionalDistrictMetadataItem(state_code="TX", number=36),
    CongressionalDistrictMetadataItem(state_code="TX", number=37),
    CongressionalDistrictMetadataItem(state_code="TX", number=38),

    # Utah - 4 districts
    CongressionalDistrictMetadataItem(state_code="UT", number=1),
    CongressionalDistrictMetadataItem(state_code="UT", number=2),
    CongressionalDistrictMetadataItem(state_code="UT", number=3),
    CongressionalDistrictMetadataItem(state_code="UT", number=4),

    # Vermont - 1 at-large district
    CongressionalDistrictMetadataItem(state_code="VT", number=1),

    # Virginia - 11 districts
    CongressionalDistrictMetadataItem(state_code="VA", number=1),
    CongressionalDistrictMetadataItem(state_code="VA", number=2),
    CongressionalDistrictMetadataItem(state_code="VA", number=3),
    CongressionalDistrictMetadataItem(state_code="VA", number=4),
    CongressionalDistrictMetadataItem(state_code="VA", number=5),
    CongressionalDistrictMetadataItem(state_code="VA", number=6),
    CongressionalDistrictMetadataItem(state_code="VA", number=7),
    CongressionalDistrictMetadataItem(state_code="VA", number=8),
    CongressionalDistrictMetadataItem(state_code="VA", number=9),
    CongressionalDistrictMetadataItem(state_code="VA", number=10),
    CongressionalDistrictMetadataItem(state_code="VA", number=11),

    # Washington - 10 districts
    CongressionalDistrictMetadataItem(state_code="WA", number=1),
    CongressionalDistrictMetadataItem(state_code="WA", number=2),
    CongressionalDistrictMetadataItem(state_code="WA", number=3),
    CongressionalDistrictMetadataItem(state_code="WA", number=4),
    CongressionalDistrictMetadataItem(state_code="WA", number=5),
    CongressionalDistrictMetadataItem(state_code="WA", number=6),
    CongressionalDistrictMetadataItem(state_code="WA", number=7),
    CongressionalDistrictMetadataItem(state_code="WA", number=8),
    CongressionalDistrictMetadataItem(state_code="WA", number=9),
    CongressionalDistrictMetadataItem(state_code="WA", number=10),

    # West Virginia - 2 districts
    CongressionalDistrictMetadataItem(state_code="WV", number=1),
    CongressionalDistrictMetadataItem(state_code="WV", number=2),

    # Wisconsin - 8 districts
    CongressionalDistrictMetadataItem(state_code="WI", number=1),
    CongressionalDistrictMetadataItem(state_code="WI", number=2),
    CongressionalDistrictMetadataItem(state_code="WI", number=3),
    CongressionalDistrictMetadataItem(state_code="WI", number=4),
    CongressionalDistrictMetadataItem(state_code="WI", number=5),
    CongressionalDistrictMetadataItem(state_code="WI", number=6),
    CongressionalDistrictMetadataItem(state_code="WI", number=7),
    CongressionalDistrictMetadataItem(state_code="WI", number=8),

    # Wyoming - 1 at-large district
    CongressionalDistrictMetadataItem(state_code="WY", number=1),

    # District of Columbia - 1 non-voting delegate
    CongressionalDistrictMetadataItem(state_code="DC", number=1),
]
