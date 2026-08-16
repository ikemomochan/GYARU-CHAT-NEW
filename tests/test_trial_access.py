from __future__ import annotations

import pytest

from app.core.trial_access import (
    TrialCookieSigner,
    TrialLimitExceeded,
    TrialUsageStore,
)


def test_trial_usage_persists_locks_and_refunds(tmp_path) -> None:
    store = TrialUsageStore(tmp_path / "trial.db")

    assert store.status("device-a", 2).remaining == 2
    assert store.consume("device-a", 2).remaining == 1
    assert store.consume("device-a", 2).locked is True
    with pytest.raises(TrialLimitExceeded):
        store.consume("device-a", 2)

    store.refund("device-a")
    assert store.status("device-a", 2).remaining == 1


def test_trial_cookies_are_signed_and_debug_access_is_device_bound() -> None:
    signer = TrialCookieSigner("strong-test-secret", debug_ttl_seconds=3600)
    device_id, device_token = signer.new_device_token()

    assert signer.verify_device_token(device_token) == device_id
    assert signer.verify_device_token(f"{device_token}tampered") is None

    debug_token, _ = signer.new_debug_token(device_id)
    assert signer.verify_debug_token(debug_token, device_id) is True
    assert signer.verify_debug_token(debug_token, "another-device") is False
