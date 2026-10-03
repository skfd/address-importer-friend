"""Import-time registry of all available checks."""
from .base import Candidate, Check, CheckContext, Verdict
from .city_duplicate import CityDuplicateCheck
from .conflict import ConflictCheck
from .intra_source_duplicate import IntraSourceDuplicateCheck
from .match_number_drift import MatchNumberDriftCheck
from .missing_sample import MissingSampleCheck
from .nearby_street_mismatch import NearbyStreetMismatchCheck
from .postcode_mismatch import PostcodeMismatchCheck
from .potential_amenity import PotentialAmenityCheck
from .suffix_range import SuffixRangeCheck
from .unit_shape_ambiguous import UnitShapeAmbiguousCheck

REGISTRY: dict[str, Check] = {
    c.id: c
    for c in (
        ConflictCheck(),
        SuffixRangeCheck(),
        CityDuplicateCheck(),
        IntraSourceDuplicateCheck(),
        MissingSampleCheck(),
        NearbyStreetMismatchCheck(),
        MatchNumberDriftCheck(),
        PotentialAmenityCheck(),
        UnitShapeAmbiguousCheck(),
        PostcodeMismatchCheck(),
    )
}

__all__ = ["REGISTRY", "Check", "Candidate", "CheckContext", "Verdict"]
