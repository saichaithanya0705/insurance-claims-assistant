"""The old import path of the saved models' classes. Do not import from here; use ``claims.ml.analytics``.

A trained model file records its classes by module path. ``artifacts/models/claims_models.joblib`` holds a
``claims.analytics.ClaimTypeMedianRegressor``, and the experiment reports record that file's SHA-256, so the file
is not re-saved. This re-export is what lets ``joblib.load`` find the class where the file says it is. Models
saved from now on record ``claims.ml.analytics``.
"""

from claims.ml.analytics import ClaimTypeMedianRegressor

__all__ = ["ClaimTypeMedianRegressor"]
