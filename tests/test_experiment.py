from __future__ import annotations

from app.core.experiment import (
    DeviceCookieSigner,
    ExperimentPhase,
    ExperimentStore,
)


class FakeClock:
    def __init__(self) -> None:
        self.value = 10_000.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def test_experiment_has_two_independent_four_minute_phases(tmp_path) -> None:
    clock = FakeClock()
    store = ExperimentStore(tmp_path / "experiment.db", clock=clock)

    waiting = store.status("device", 240)
    simple = store.start("device", 240)
    clock.advance(240)
    transition = store.status("device", 240)
    full = store.advance_to_full("device", 240)
    clock.advance(240)
    complete = store.status("device", 240)

    assert waiting.phase is ExperimentPhase.WAITING
    assert simple.phase is ExperimentPhase.SIMPLE
    assert transition.phase is ExperimentPhase.TRANSITION
    assert full.phase is ExperimentPhase.FULL
    assert complete.phase is ExperimentPhase.COMPLETE


def test_phase_histories_and_export_remain_separate(tmp_path) -> None:
    store = ExperimentStore(tmp_path / "experiment.db")
    state = store.start("device", 240)
    store.append_turn(state.experiment_id, ExperimentPhase.SIMPLE, "前半U", "前半A")
    store.append_turn(state.experiment_id, ExperimentPhase.FULL, "後半U", "後半A")

    assert store.history(state.experiment_id, ExperimentPhase.SIMPLE, 12) == [
        {"role": "user", "content": "前半U"},
        {"role": "assistant", "content": "前半A"},
    ]
    assert store.history(state.experiment_id, ExperimentPhase.FULL, 12) == [
        {"role": "user", "content": "後半U"},
        {"role": "assistant", "content": "後半A"},
    ]
    exported = store.export_csv()
    assert "前半U" in exported
    assert "後半U" in exported


def test_csv_export_neutralizes_spreadsheet_formulas(tmp_path) -> None:
    store = ExperimentStore(tmp_path / "experiment.db")
    state = store.start("device", 240)
    store.append_turn(
        state.experiment_id,
        ExperimentPhase.SIMPLE,
        "=HYPERLINK(\"bad\")",
        "通常の返答",
    )

    assert "'=HYPERLINK" in store.export_csv()


def test_device_cookie_rejects_tampering() -> None:
    signer = DeviceCookieSigner("test-secret")
    device_id, token = signer.new_token()

    assert signer.verify(token) == device_id
    assert signer.verify(f"{token}tampered") is None
