"""
Tests for curriculum and quiz routes.

Covers:
- Quiz submit scoring logic (correct / wrong / mixed answers)
- Quiz submit: session-based integrity (no client-supplied correct values accepted)
- Progress toggle: upsert and idempotency
- Quiz history best_pct calculation
"""
import json
import pytest


SAMPLE_QUESTIONS = [
    {
        "question": "What command lists running containers?",
        "options": ["docker ps", "docker ls", "docker list", "docker show"],
        "correct": 0,
        "explanation": "docker ps lists running containers.",
    },
    {
        "question": "What does kubectl apply do?",
        "options": ["Deletes resources", "Applies a manifest", "Lists pods", "Restarts deployments"],
        "correct": 1,
        "explanation": "kubectl apply creates or updates resources from a manifest.",
    },
    {
        "question": "Which Terraform command previews changes?",
        "options": ["terraform apply", "terraform plan", "terraform init", "terraform show"],
        "correct": 1,
        "explanation": "terraform plan shows what changes will be made.",
    },
]

MODULE_ID = "docker-fundamentals"
PHASE_ID = "04"


def _seed_quiz_session(client, questions=None):
    """Seed the server-side session with quiz questions (simulates /api/quiz/generate)."""
    qs = questions or SAMPLE_QUESTIONS
    with client.session_transaction() as sess:
        sess[f'quiz_{MODULE_ID}'] = qs


# ── Quiz submit scoring ───────────────────────────────────────────────────────

class TestQuizSubmitScoring:

    def test_all_correct_scores_100(self, authenticated_client, app):
        with app.app_context():
            _seed_quiz_session(authenticated_client)
            answers = [q["correct"] for q in SAMPLE_QUESTIONS]
            rv = authenticated_client.post(
                '/curriculum/api/quiz/submit',
                json={"module_id": MODULE_ID, "answers": answers},
            )
            data = rv.get_json()
            assert rv.status_code == 200
            assert data["success"] is True
            assert data["score"] == len(SAMPLE_QUESTIONS)
            assert data["pct"] == 100
            assert data["passed"] is True

    def test_all_wrong_scores_0(self, authenticated_client, app):
        with app.app_context():
            _seed_quiz_session(authenticated_client)
            wrong_answers = [(q["correct"] + 1) % 4 for q in SAMPLE_QUESTIONS]
            rv = authenticated_client.post(
                '/curriculum/api/quiz/submit',
                json={"module_id": MODULE_ID, "answers": wrong_answers},
            )
            data = rv.get_json()
            assert data["score"] == 0
            assert data["pct"] == 0
            assert data["passed"] is False

    def test_mixed_answers_scores_correctly(self, authenticated_client, app):
        with app.app_context():
            _seed_quiz_session(authenticated_client)
            # Answer first correct, rest wrong
            answers = [SAMPLE_QUESTIONS[0]["correct"]] + [
                (q["correct"] + 1) % 4 for q in SAMPLE_QUESTIONS[1:]
            ]
            rv = authenticated_client.post(
                '/curriculum/api/quiz/submit',
                json={"module_id": MODULE_ID, "answers": answers},
            )
            data = rv.get_json()
            assert data["score"] == 1
            assert data["pct"] == 33

    def test_pass_threshold_at_70_pct(self, authenticated_client, app):
        """2/3 correct = 67% → fail. 3/3 = 100% → pass."""
        with app.app_context():
            # 2 correct out of 3 = 67% — should fail
            _seed_quiz_session(authenticated_client)
            answers = [
                SAMPLE_QUESTIONS[0]["correct"],
                SAMPLE_QUESTIONS[1]["correct"],
                (SAMPLE_QUESTIONS[2]["correct"] + 1) % 4,
            ]
            rv = authenticated_client.post(
                '/curriculum/api/quiz/submit',
                json={"module_id": MODULE_ID, "answers": answers},
            )
            data = rv.get_json()
            assert data["passed"] is False  # 67% < 70%


# ── Session integrity (Issue 1 fix) ──────────────────────────────────────────

class TestQuizSessionIntegrity:

    def test_submit_without_session_returns_400(self, authenticated_client, app):
        """Submit with no active session should fail — cannot fake questions."""
        with app.app_context():
            rv = authenticated_client.post(
                '/curriculum/api/quiz/submit',
                json={"module_id": MODULE_ID, "answers": [0, 1, 1]},
            )
            assert rv.status_code == 400
            data = rv.get_json()
            assert "No active quiz session" in data["error"]

    def test_session_cleared_after_submit(self, authenticated_client, app):
        """After a successful submit, the session slot is cleared (no double-submit)."""
        with app.app_context():
            _seed_quiz_session(authenticated_client)
            answers = [q["correct"] for q in SAMPLE_QUESTIONS]
            authenticated_client.post(
                '/curriculum/api/quiz/submit',
                json={"module_id": MODULE_ID, "answers": answers},
            )
            # Second submit should fail
            rv = authenticated_client.post(
                '/curriculum/api/quiz/submit',
                json={"module_id": MODULE_ID, "answers": answers},
            )
            assert rv.status_code == 400

    def test_answer_count_mismatch_returns_400(self, authenticated_client, app):
        with app.app_context():
            _seed_quiz_session(authenticated_client)
            rv = authenticated_client.post(
                '/curriculum/api/quiz/submit',
                json={"module_id": MODULE_ID, "answers": [0]},  # only 1 answer for 3 questions
            )
            assert rv.status_code == 400


# ── Progress toggle ───────────────────────────────────────────────────────────

class TestProgressToggle:

    def test_mark_module_complete(self, authenticated_client, app):
        with app.app_context():
            rv = authenticated_client.post(
                '/curriculum/api/progress',
                json={"module_id": "linux-cli", "phase_id": "01", "completed": True},
            )
            data = rv.get_json()
            assert data["success"] is True
            assert data["progress"]["completed"] is True

    def test_toggle_is_idempotent(self, authenticated_client, app):
        """Posting completed=True twice should still result in completed=True."""
        with app.app_context():
            payload = {"module_id": "git-fundamentals", "phase_id": "02", "completed": True}
            authenticated_client.post('/curriculum/api/progress', json=payload)
            rv = authenticated_client.post('/curriculum/api/progress', json=payload)
            data = rv.get_json()
            assert data["success"] is True
            assert data["progress"]["completed"] is True

    def test_unmark_module(self, authenticated_client, app):
        with app.app_context():
            authenticated_client.post(
                '/curriculum/api/progress',
                json={"module_id": "linux-networking", "phase_id": "01", "completed": True},
            )
            rv = authenticated_client.post(
                '/curriculum/api/progress',
                json={"module_id": "linux-networking", "phase_id": "01", "completed": False},
            )
            data = rv.get_json()
            assert data["progress"]["completed"] is False


# ── Quiz history best_pct ─────────────────────────────────────────────────────

class TestQuizHistory:
    # Use a unique module_id so this class doesn't pick up attempts from other tests
    HIST_MODULE_ID = "k8s-architecture"

    def _submit_quiz(self, client, answers):
        with client.session_transaction() as sess:
            sess[f'quiz_{self.HIST_MODULE_ID}'] = SAMPLE_QUESTIONS
        return client.post(
            '/curriculum/api/quiz/submit',
            json={"module_id": self.HIST_MODULE_ID, "answers": answers},
        )

    def test_best_pct_is_highest_score(self, authenticated_client, app):
        with app.app_context():
            # First attempt: all wrong (0%)
            self._submit_quiz(
                authenticated_client,
                [(q["correct"] + 1) % 4 for q in SAMPLE_QUESTIONS],
            )
            # Second attempt: all correct (100%)
            self._submit_quiz(
                authenticated_client,
                [q["correct"] for q in SAMPLE_QUESTIONS],
            )
            rv = authenticated_client.get(f'/curriculum/api/quiz/history/{self.HIST_MODULE_ID}')
            data = rv.get_json()
            assert data["best_pct"] == 100
            assert data["attempt_count"] == 2
