"""The old import path of the saved fraud model's classes. Do not import from here; use ``claims.ml.fraud_features``.

``artifacts/models/claims_models.feature_candidate.joblib`` records ``claims.fraud_features.FraudFeatureEncoder`` and
``claims.fraud_features.FraudProbabilityEnsemble`` by module path, and the experiment reports record that file's
SHA-256, so the file is not re-saved. This re-export is what lets ``joblib.load`` find the classes where the file
says they are. Models saved from now on record ``claims.ml.fraud_features``.
"""

from claims.ml.fraud_features import FraudFeatureEncoder, FraudProbabilityEnsemble

__all__ = ["FraudFeatureEncoder", "FraudProbabilityEnsemble"]
