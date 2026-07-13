"""Rules are pure: synthetic snapshot dicts in, Signals out. No DB, no LLM."""
from datetime import date

from app.insights import rules

TODAY = date(2026, 7, 13)


def _ctx(today, history=None):
    return rules.Ctx(day=TODAY, today=today, history=history or [])


def _codes(signals):
    return {s.code for s in signals}


def test_recovery_green_is_positive_anchor():
    sigs = rules.run_rules(_ctx({"recovery_pct": 80}))
    band = next(s for s in sigs if s.code == "recovery_band")
    assert band.tone == "positive"
    assert band.facts["recovery_pct"] == 80
    assert sigs[0].code == "recovery_band"          # anchor first


def test_recovery_red_is_caution():
    band = next(s for s in rules.run_rules(_ctx({"recovery_pct": 25}))
                if s.code == "recovery_band")
    assert band.tone == "caution"


def test_no_recovery_no_anchor():
    # strain present but recovery absent -> no recovery_band, no crash
    sigs = rules.run_rules(_ctx({"day_strain": 10.0}))
    assert "recovery_band" not in _codes(sigs)


def test_recovery_trend_down_vs_baseline():
    history = [{"recovery_pct": 70}, {"recovery_pct": 74}, {"recovery_pct": 72}]
    sigs = rules.run_rules(_ctx({"recovery_pct": 45}, history))
    trend = next(s for s in sigs if s.code == "recovery_trend")
    assert trend.tone == "caution"


def test_overreaching_high_strain_low_recovery():
    sigs = rules.run_rules(_ctx({"recovery_pct": 40, "day_strain": 16.0}))
    over = next(s for s in sigs if s.code == "strain_recovery_balance")
    assert over.tone == "caution"


def test_low_sleep_quality_is_caution():
    sigs = rules.run_rules(_ctx({"recovery_pct": 60, "sleep_quality_pct": 55}))
    sleep = next(s for s in sigs if s.code == "sleep_performance")
    assert sleep.tone == "caution"
    assert "55" in sleep.template


def test_rhr_elevation_vs_baseline():
    history = [{"resting_hr": 52}, {"resting_hr": 54}, {"resting_hr": 53}]
    sigs = rules.run_rules(_ctx({"recovery_pct": 60, "resting_hr": 61}, history))
    assert "rhr_elevation" in _codes(sigs)


def test_empty_day_produces_nothing():
    assert rules.run_rules(_ctx(None)) == []


def test_hrv_suppressed_is_caution():
    history = [{"hrv_ms": 60.0}, {"hrv_ms": 62.0}, {"hrv_ms": 58.0}]
    sigs = rules.run_rules(_ctx({"recovery_pct": 60, "hrv_ms": 40.0}, history))
    hrv = next(s for s in sigs if s.code == "hrv_trend")
    assert hrv.tone == "caution"


def test_hrv_strong_is_positive():
    history = [{"hrv_ms": 50.0}, {"hrv_ms": 52.0}, {"hrv_ms": 48.0}]
    sigs = rules.run_rules(_ctx({"recovery_pct": 60, "hrv_ms": 70.0}, history))
    hrv = next(s for s in sigs if s.code == "hrv_trend")
    assert hrv.tone == "positive"


def test_recovery_yellow_is_neutral():
    band = next(s for s in rules.run_rules(_ctx({"recovery_pct": 50}))
                if s.code == "recovery_band")
    assert band.tone == "neutral"


def test_recovery_trend_up_is_positive():
    history = [{"recovery_pct": 55}, {"recovery_pct": 58}, {"recovery_pct": 57}]
    sigs = rules.run_rules(_ctx({"recovery_pct": 80}, history))
    trend = next(s for s in sigs if s.code == "recovery_trend")
    assert trend.tone == "positive"


def test_primed_underused_is_positive():
    sigs = rules.run_rules(_ctx({"recovery_pct": 75, "day_strain": 5.0}))
    bal = next(s for s in sigs if s.code == "strain_recovery_balance")
    assert bal.tone == "positive"


def test_sleep_streak_without_low_quality_is_caution():
    history = [{"sleep_hours": 5.2}, {"recovery_pct": 60}]
    sigs = rules.run_rules(_ctx({"recovery_pct": 60, "sleep_hours": 5.5}, history))
    sleep = next(s for s in sigs if s.code == "sleep_performance")
    assert sleep.tone == "caution"
    assert sleep.facts["short_nights"] >= 2
