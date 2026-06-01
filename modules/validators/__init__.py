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

ento_mosquito (10 checks):
 17. Required fields non-null
 18. Orphan record (session_id not in ento_collection)
 19. clocation mismatch vs parent collection
 20. chour codes (1-18)
 21. grossspecies codes (1-9)
 22. abdstatus codes (0-3)
 23. Barcode format (H26-{sitecode}-{4digits})
 24. Barcode uniqueness
 25. Duplicate uniqueid
 26. Duration impossible

pheno_assay (7 checks):
 27. Required fields non-null
 28. numdead <= numtested
 29. numkd <= numtested
 30. pctmortality / pctkd consistency (within 0.1%)
 31. mosqspecies codes (1-9)
 32. Orphan assay (site_id not in pheno_site)
 33. Duplicate uniqueid

hbo_household (13 checks):
 34. Required fields non-null
 35. mrccode validity
 36. hhid exactly 9 numeric digits
 37. hhid unique per dateofobservation
 38. dateofobservation not future
 39. dateofobservation not before study start
 40. numsleeprooms integer 0–20
 41. numsleepareas integer 0–20, >= numsleeprooms
 42. numsleeprooms inconsistent across visits
 43. numhangbednets integer 0–20
 44. numpeople integer 1–15
 45. Duplicate uniqueid
 46. Sparse columns

hbo_person (12 checks):
 47. Required fields non-null
 48. age numeric 0–120 (null allowed)
 49. gender codes (1=Male, 2=Female)
 50. individualnum sequential per session (no gaps/duplicates)
 51. obs_* codes valid (1–5 or null)
 52. Missing observation hours (non-trailing null)
 53. Away entire night (all obs = 5)
 54. Asleep entire night (all obs = 3)
 55. Transition: Under net IN → Near OUT → Under net IN
 56. Infant (age < 1) Away OUT during late night
 57. Orphan person (session_id not in hbo_household)
 58. Duplicate uniqueid

cross-form hbo (2 checks):
 59. Person count != numpeople
 60. numhangbednets=0 but obs=1 (Under net IN)
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
