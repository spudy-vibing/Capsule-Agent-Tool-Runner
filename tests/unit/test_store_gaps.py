"""
Tests for store/db.py coverage gaps:
- record_planner_proposal and get_proposals_for_run
- Eval run methods (additional edge cases)
"""

import json
import tempfile
from pathlib import Path

import pytest

from capsule.store.db import CapsuleDB


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    with CapsuleDB(db_path) as db:
        yield db


@pytest.fixture
def sample_run_id(db):
    """Create a minimal run and return its ID."""
    from capsule.schema import Plan, Policy, PlanStep

    plan = Plan(
        version="1.0",
        steps=[PlanStep(tool="fs.read", args={"path": "./test.txt"})],
    )
    policy = Policy()
    return db.create_run(plan, policy)


class TestPlannerProposalOperations:
    def test_record_proposal_tool_call(self, db, sample_run_id):
        """Record a tool_call proposal."""
        proposal_id = db.record_planner_proposal(
            run_id=sample_run_id,
            iteration=0,
            proposal_type="tool_call",
            tool_name="fs.read",
            args={"path": "/tmp/test.txt"},
            reasoning="Need to read the file",
            raw_response='{"tool": "fs.read", "args": {"path": "/tmp/test.txt"}}',
        )
        assert proposal_id is not None
        assert len(proposal_id) == 8

    def test_record_proposal_done(self, db, sample_run_id):
        """Record a done proposal."""
        proposal_id = db.record_planner_proposal(
            run_id=sample_run_id,
            iteration=1,
            proposal_type="done",
            reasoning="Task completed",
            raw_response='{"done": true, "reason": "task_complete"}',
        )
        assert proposal_id is not None

    def test_get_proposals_for_run(self, db, sample_run_id):
        """Retrieve all proposals in order."""
        db.record_planner_proposal(
            run_id=sample_run_id,
            iteration=0,
            proposal_type="tool_call",
            tool_name="fs.read",
            args={"path": "/tmp/a.txt"},
        )
        db.record_planner_proposal(
            run_id=sample_run_id,
            iteration=1,
            proposal_type="tool_call",
            tool_name="shell.run",
            args={"cmd": ["echo", "hi"]},
        )
        db.record_planner_proposal(
            run_id=sample_run_id,
            iteration=2,
            proposal_type="done",
        )

        proposals = db.get_proposals_for_run(sample_run_id)
        assert len(proposals) == 3
        assert proposals[0]["iteration"] == 0
        assert proposals[0]["proposal_type"] == "tool_call"
        assert proposals[0]["tool_name"] == "fs.read"
        assert proposals[0]["args"] == {"path": "/tmp/a.txt"}
        assert proposals[1]["iteration"] == 1
        assert proposals[2]["proposal_type"] == "done"
        assert proposals[2]["tool_name"] is None
        assert proposals[2]["args"] is None

    def test_get_proposals_empty(self, db, sample_run_id):
        """No proposals returns empty list."""
        proposals = db.get_proposals_for_run(sample_run_id)
        assert proposals == []

    def test_proposal_preserves_reasoning(self, db, sample_run_id):
        """Reasoning text is preserved."""
        db.record_planner_proposal(
            run_id=sample_run_id,
            iteration=0,
            proposal_type="tool_call",
            tool_name="fs.read",
            args={"path": "/test"},
            reasoning="I need to check the file contents first",
        )
        proposals = db.get_proposals_for_run(sample_run_id)
        assert proposals[0]["reasoning"] == "I need to check the file contents first"

    def test_proposal_preserves_raw_response(self, db, sample_run_id):
        """Raw response is preserved."""
        raw = '{"tool": "fs.read", "args": {"path": "/test"}, "extra": "data"}'
        db.record_planner_proposal(
            run_id=sample_run_id,
            iteration=0,
            proposal_type="tool_call",
            raw_response=raw,
        )
        proposals = db.get_proposals_for_run(sample_run_id)
        assert proposals[0]["raw_response"] == raw


class TestEvalRunEdgeCases:
    def test_eval_run_with_null_score(self, db):
        """Eval run with None score."""
        eval_id = db.record_eval_run(
            pack_name="test-pack",
            category="deterministic",
            total_cases=0,
            passed_cases=0,
            failed_cases=0,
            skipped_cases=0,
            score=None,
            score_breakdown=None,
            results_json="[]",
            duration_seconds=0.0,
        )
        run = db.get_eval_run(eval_id)
        assert run["score"] is None
        assert run["score_breakdown"] is None

    def test_list_eval_runs_ordering(self, db):
        """Eval runs are returned most-recent-first."""
        id1 = db.record_eval_run(
            pack_name="pack-a", category="all",
            total_cases=1, passed_cases=1, failed_cases=0, skipped_cases=0,
            score=1.0, score_breakdown=None, results_json="[]", duration_seconds=0.01,
        )
        id2 = db.record_eval_run(
            pack_name="pack-b", category="all",
            total_cases=1, passed_cases=0, failed_cases=1, skipped_cases=0,
            score=0.0, score_breakdown=None, results_json="[]", duration_seconds=0.02,
        )
        runs = db.list_eval_runs()
        assert len(runs) == 2
        # Most recent first
        assert runs[0]["eval_id"] == id2
        assert runs[1]["eval_id"] == id1

    def test_eval_run_complex_results(self, db):
        """Eval run with detailed results JSON."""
        results = [
            {
                "name": "test_1",
                "passed": True,
                "checks": [
                    {"check_type": "decision", "passed": True, "expected": "deny", "actual": "deny"},
                ],
            },
        ]
        eval_id = db.record_eval_run(
            pack_name="test-pack", category="deterministic",
            total_cases=1, passed_cases=1, failed_cases=0, skipped_cases=0,
            score=1.0, score_breakdown={"policy_compliance": 1.0},
            results_json=json.dumps(results), duration_seconds=0.05,
        )
        run = db.get_eval_run(eval_id)
        assert len(run["results"]) == 1
        assert run["results"][0]["passed"] is True
        assert run["results"][0]["checks"][0]["check_type"] == "decision"
