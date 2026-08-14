"""
validators — HAVI Entomology data validation
---------------------------------------------
Validation checks:

ento_collection (16 checks):
 1.  Required fields non-null
 2.  mrccode validity (known MRC codes)
 3.  datasource codes (1–2)
 4.  clocation codes (1–2)
 5.  Mosquito counts non-negative
 6.  dateofcollection not in future
 7.  dateofcollection not before study start date
 8.  Duration impossible (stoptime < starttime)
 9.  Duration too long (> 12 hours)
 10. numfanoph=0 but child records exist
 11. numfanoph >= 1 but no child records
 12. numfanoph != actual child row count
 13. Duplicate collection primary key
 14. Duplicate session_id + datasource + clocation
 15. Device record count <= 2
 16. Sparse columns (>50% null)

ento_mosquito (11 checks):
 17. Required fields non-null
 18. Orphan record (session_id not in ento_collection)
 19. clocation mismatch vs parent collection
 20. hhid mismatch vs parent collection
 21. chour codes (1-18)
 22. grossspecies codes (1-9)
 23. abdstatus codes (0-3)
 24. Barcode format (H26-{sitecode}-{4digits})
 25. Barcode uniqueness
 26. Duplicate uniqueid
 27. Duration impossible

pheno_assay (7 checks):
 28. Required fields non-null
 29. numdead <= numtested
 30. numkd <= numtested
 31. pctmortality / pctkd consistency (within 0.1%)
 32. mosqspecies codes (1-9)
 33. Orphan assay (site_id not in pheno_site)
 34. Duplicate uniqueid

hbo_household (13 checks):
 35. Required fields non-null
 36. mrccode validity
 37. hhid exactly 9 numeric digits
 38. hhid unique per dateofobservation
 39. dateofobservation not future
 40. dateofobservation not before study start
 41. numsleeprooms integer 0–20
 42. numsleepareas integer 0–20
 43. numsleeprooms inconsistent across visits
 44. numhangbednets integer 0–20
 45. numpeople integer 1–15
 46. Duplicate uniqueid
 47. Sparse columns

hbo_person (12 checks):
 48. Required fields non-null
 49. age numeric 0–120 (null allowed)
 50. gender codes (1=Male, 2=Female)
 51. individualnum sequential per session (no gaps/duplicates)
 52. obs_* codes valid (1–5 or null)
 53. Missing observation hours (non-trailing null)
 54. Away entire night (all obs = 5)
 55. Asleep entire night (all obs = 3)
 56. Transition: Under net IN → Near OUT → Under net IN
 57. Infant (age < 1) Away OUT during late night
 58. Orphan person (session_id not in hbo_household) — run globally via
     validate_hbo_person_orphans(), not per-site (see that method's docstring)
 59. Duplicate uniqueid

cross-form hbo (2 checks):
 60. Person count != numpeople
 61. numhangbednets=0 but obs=1 (Under net IN)
"""

from ._base import _ValidatorBase
from .collection import _CollectionChecks
from .hbo import _HboChecks
from .mosquito import _MosquitoChecks
from .pheno import _PhenoChecks


class EntomologyValidator(
    _ValidatorBase,
    _CollectionChecks,
    _MosquitoChecks,
    _PhenoChecks,
    _HboChecks,
):
    """Validates HAVI entomology DataFrames (silver layer).

    Args:
        valid_mrc_codes: Set of valid MRC site codes. Defaults to the
            trial-configured list. Pass from config so new field sites
            can be added without a code change.
        study_start_date: ISO date string for the study start (e.g. '2026-04-13').
            Observations before this date are flagged as warnings.
    """


# Legacy alias — kept for backward compatibility with any callers using DataValidator.
DataValidator = EntomologyValidator

__all__ = ['EntomologyValidator', 'DataValidator']
