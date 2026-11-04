# Task 1 report
Commit: 9140964
Changed: src/xibalba_cortex/managed/api.py (module constant MANAGED_DESTINATIONS after COOKIE; `me` returns "destinations": list(MANAGED_DESTINATIONS)); tests/test_managed_service.py (new test using setup/register + TestClient).

## Failing output (before implementation)
=================================== FAILURES ===================================
____________ test_me_declares_the_destinations_this_edition_serves _____________


    def test_me_declares_the_destinations_this_edition_serves(setup):
        register(setup)
        client = setup[4]
        response = client.get("/api/managed/me")
        assert response.status_code == 200, response.text
>       assert response.json()["destinations"] == [
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
            "graph", "timeline", "memories", "recall", "settings", "agents", "billing",
        ]
E       KeyError: 'destinations'

tests/test_managed_service.py:473: KeyError
=========================== short test summary info ============================
FAILED tests/test_managed_service.py::test_me_declares_the_destinations_this_edition_serves

## Passing output (after)
`uv run --frozen pytest tests/test_managed_service.py -q` -> 30 passed (file-wide); target test -k declares_the_destinations -> 1 passed.

## Concerns
- Constant sits beside COOKIE (module level, above create_app) because the route table is local to create_app; brief said "beside the route table".
- pyproject's editable integrity-sdk path ../integrity-core doesn't resolve from this worktree; I used a temporary symlink at worktrees/xibalba-cortex/integrity-core (removed after) and --frozen. .venv created in worktree (gitignored).
