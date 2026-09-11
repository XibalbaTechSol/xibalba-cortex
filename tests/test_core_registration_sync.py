import pytest

from xibalba_cortex.accounts import account_for_token, create_account, issue_account_session
from xibalba_cortex.core_registration_sync import registered_agents_for_controller, sync_account_from_core


CONTROLLER = "0x1111111111111111111111111111111111111111"


def test_filters_finalized_core_directory_by_controller():
    payload = {"finalized": True, "chain_id": 84532, "block_number": 10, "snapshot_id": "directory:84532:10", "agents": [
        {"id": "did:integrity:owned", "controller": CONTROLLER},
        {"id": "did:integrity:other", "controller": "0x2222222222222222222222222222222222222222"},
    ]}
    assert registered_agents_for_controller(payload, CONTROLLER) == ["did:integrity:owned"]


def test_rejects_unfinalized_or_noncanonical_snapshot():
    with pytest.raises(ValueError, match="not finalized"):
        registered_agents_for_controller({"finalized": False, "agents": []}, CONTROLLER)
    with pytest.raises(ValueError, match="non-canonical"):
        registered_agents_for_controller({"finalized": True, "agents": [{"id": "agent", "controller": CONTROLLER}]}, CONTROLLER)


def test_sync_updates_account_session_agent_set(tmp_path):
    account = create_account(tmp_path, email="chain@example.com", password="correct horse battery staple", display_name="Chain User")
    ids = sync_account_from_core({"finalized": True, "chain_id": 84532, "block_number": 10, "snapshot_id": "directory:84532:10", "agents": [{"id": "did:integrity:owned", "controller": CONTROLLER}]}, home=str(tmp_path), account_id=str(account["id"]), controller=CONTROLLER)
    assert ids == ["did:integrity:owned"]
    _, session = issue_account_session(tmp_path, email="chain@example.com", password="correct horse battery staple")
    assert session["agent_ids"] == ids

    sync_account_from_core({"finalized": True, "chain_id": 84532, "block_number": 11, "snapshot_id": "directory:84532:11", "agents": []}, home=str(tmp_path), account_id=str(account["id"]), controller=CONTROLLER)
    assert account_for_token(tmp_path, _)["agent_ids"] == []


def test_stale_snapshot_cannot_roll_back_authorized_agents(tmp_path):
    account = create_account(tmp_path, email="cursor@example.com", password="correct horse battery staple", display_name="Cursor User")
    sync_account_from_core({"finalized": True, "chain_id": 84532, "block_number": 20, "snapshot_id": "directory:84532:20", "agents": [{"id": "did:integrity:new", "controller": CONTROLLER}]}, home=str(tmp_path), account_id=str(account["id"]), controller=CONTROLLER)
    with pytest.raises(ValueError, match="older than the applied cursor"):
        sync_account_from_core({"finalized": True, "chain_id": 84532, "block_number": 19, "snapshot_id": "directory:84532:19", "agents": [{"id": "did:integrity:old", "controller": CONTROLLER}]}, home=str(tmp_path), account_id=str(account["id"]), controller=CONTROLLER)
    token, _ = issue_account_session(tmp_path, email="cursor@example.com", password="correct horse battery staple")
    assert account_for_token(tmp_path, token)["agent_ids"] == ["did:integrity:new"]


def test_same_height_conflicting_snapshot_fails_closed(tmp_path):
    account = create_account(tmp_path, email="reorg@example.com", password="correct horse battery staple", display_name="Reorg User")
    sync_account_from_core({"finalized": True, "chain_id": 84532, "block_number": 30, "snapshot_id": "directory:84532:30:a", "agents": [{"id": "did:integrity:stable", "controller": CONTROLLER}]}, home=str(tmp_path), account_id=str(account["id"]), controller=CONTROLLER)
    with pytest.raises(ValueError, match="conflicts at the applied cursor"):
        sync_account_from_core({"finalized": True, "chain_id": 84532, "block_number": 30, "snapshot_id": "directory:84532:30:b", "agents": []}, home=str(tmp_path), account_id=str(account["id"]), controller=CONTROLLER)
    token, _ = issue_account_session(tmp_path, email="reorg@example.com", password="correct horse battery staple")
    assert account_for_token(tmp_path, token)["agent_ids"] == ["did:integrity:stable"]


def test_transfer_and_revoke_do_not_leave_old_controller_access(tmp_path):
    account = create_account(tmp_path, email="transfer@example.com", password="correct horse battery staple", display_name="Transfer User")
    moved = "did:integrity:moved"
    sync_account_from_core({"finalized": True, "chain_id": 84532, "block_number": 40, "snapshot_id": "directory:84532:40", "agents": [{"id": moved, "controller": CONTROLLER}]}, home=str(tmp_path), account_id=str(account["id"]), controller=CONTROLLER)
    token, _ = issue_account_session(tmp_path, email="transfer@example.com", password="correct horse battery staple")
    assert account_for_token(tmp_path, token)["agent_ids"] == [moved]

    # CORE's next finalized snapshot moves the DID to another controller; the old
    # account receives a revocation projection and cannot retain the old session scope.
    sync_account_from_core({"finalized": True, "chain_id": 84532, "block_number": 41, "snapshot_id": "directory:84532:41", "agents": [{"id": moved, "controller": "0x2222222222222222222222222222222222222222"}]}, home=str(tmp_path), account_id=str(account["id"]), controller=CONTROLLER)
    assert account_for_token(tmp_path, token)["agent_ids"] == []
