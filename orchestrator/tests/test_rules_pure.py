"""Unit tests for the rules engine's pure logic (boundary values, selectors)."""

import uuid

from vigil.db.models import AlertRule, RuleOp, Severity
from vigil.rules.engine import condition_breached, selector_matches


def _rule(op: RuleOp, threshold: float) -> AlertRule:
    return AlertRule(
        id=uuid.uuid4(), name=f"r-{op.value}", metric="cpu_pct", op=op,
        threshold=threshold, for_seconds=0, severity=Severity.warning, enabled=True,
    )


class TestConditionBoundaries:
    def test_gt_boundary(self):
        r = _rule(RuleOp.gt, 85.0)
        assert not condition_breached(r, 85.0)
        assert condition_breached(r, 85.000001)
        assert not condition_breached(r, 84.999)

    def test_gte_boundary(self):
        r = _rule(RuleOp.gte, 85.0)
        assert condition_breached(r, 85.0)
        assert not condition_breached(r, 84.999)

    def test_lt_boundary(self):
        r = _rule(RuleOp.lt, 10.0)
        assert not condition_breached(r, 10.0)
        assert condition_breached(r, 9.999)

    def test_lte_boundary(self):
        r = _rule(RuleOp.lte, 10.0)
        assert condition_breached(r, 10.0)
        assert not condition_breached(r, 10.001)

    def test_none_value_never_breaches(self):
        for op in RuleOp:
            assert not condition_breached(_rule(op, 50), None)


class TestSelectors:
    def test_null_selector_matches_everything(self):
        assert selector_matches(None, {"env": "prod"})
        assert selector_matches({}, None)

    def test_exact_match(self):
        assert selector_matches({"env": "prod"}, {"env": "prod", "region": "eu"})

    def test_mismatch(self):
        assert not selector_matches({"env": "prod"}, {"env": "dev"})

    def test_missing_label(self):
        assert not selector_matches({"env": "prod"}, {})
        assert not selector_matches({"env": "prod"}, None)

    def test_multi_key_requires_all(self):
        labels = {"env": "prod", "region": "eu"}
        assert selector_matches({"env": "prod", "region": "eu"}, labels)
        assert not selector_matches({"env": "prod", "region": "us"}, labels)
