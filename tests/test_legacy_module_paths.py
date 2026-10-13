"""Names that outside files still use after the backend was split into packages.

Trained model files record their classes by module path, and the documented run command is
``uvicorn claims.api:app``. Both must keep working without retraining or editing anything.
"""

import pickle
import subprocess
import sys
from pathlib import Path

import pytest

import claims
from claims.ml import analytics, fraud_features

# A pickle that asks for an instance of the class by the module path a model saved before the split recorded.
LEGACY = {
    ("claims.analytics", "ClaimTypeMedianRegressor"): analytics.ClaimTypeMedianRegressor,
    ("claims.fraud_features", "FraudFeatureEncoder"): fraud_features.FraudFeatureEncoder,
    ("claims.fraud_features", "FraudProbabilityEnsemble"): fraud_features.FraudProbabilityEnsemble,
}


@pytest.mark.parametrize(("path", "expected"), LEGACY.items(), ids=lambda value: value[1] if isinstance(value, tuple) else "")
def test_a_model_file_saved_before_the_split_still_finds_its_class(path, expected):
    module, name = path
    data = b"\x80\x02c" + module.encode() + b"\n" + name.encode() + b"\n)\x81."
    assert type(pickle.loads(data)) is expected


def test_models_saved_from_now_on_record_the_new_module_path():
    assert analytics.ClaimTypeMedianRegressor.__module__ == "claims.ml.analytics"
    assert fraud_features.FraudProbabilityEnsemble.__module__ == "claims.ml.fraud_features"


def test_the_documented_run_command_still_resolves_to_the_app():
    import claims.api
    from claims.api import main

    assert claims.api.app is main.app
    assert claims.api.create_app is main.create_app


def test_an_unknown_name_on_the_api_package_fails_instead_of_resolving_silently():
    import claims.api

    # monkeypatch.setattr("claims.api.build_synapt_adapter", ...) must not "work" while patching the wrong module.
    with pytest.raises(AttributeError):
        _ = claims.api.build_synapt_adapter


def test_importing_the_api_package_or_its_auth_store_does_not_build_the_app():
    source = str(Path(claims.__file__).resolve().parents[1])
    code = (
        f"import sys; sys.path.insert(0, {source!r})\n"
        "import claims.api, claims.api.auth\n"
        "raise SystemExit('built' if 'claims.api.main' in sys.modules else 0)"
    )
    done = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
