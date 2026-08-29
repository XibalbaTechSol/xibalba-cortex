import textwrap
from argparse import Namespace

import pytest

from xibalba_cortex.codex_mcp_backfill import parse_codex_session, run


def test_parse_codex_session_reconstructs_turn_and_tool_call(tmp_path):
    transcript = tmp_path / "rollout-2026-08-17T09-17-46-session.jsonl"
    transcript.write_text(
        textwrap.dedent(
            """
            {"timestamp":"2026-08-17T14:00:00Z","type":"session_meta","payload":{"id":"sess-1","cwd":"/repo","cli_version":"0.1"}}
            {"timestamp":"2026-08-17T14:00:01Z","type":"turn_context","payload":{"turn_id":"turn-1","model":"gpt-5.5"}}
            {"timestamp":"2026-08-17T14:00:02Z","type":"event_msg","payload":{"type":"user_message","message":"collect telemetry"}}
            {"timestamp":"2026-08-17T14:00:03Z","type":"response_item","payload":{"type":"function_call","name":"exec_command","arguments":"{\\"cmd\\":\\"pwd\\"}","call_id":"call-1","internal_chat_message_metadata_passthrough":{"turn_id":"turn-1"}}}
            {"timestamp":"2026-08-17T14:00:04Z","type":"response_item","payload":{"type":"function_call_output","call_id":"call-1","output":"ok","internal_chat_message_metadata_passthrough":{"turn_id":"turn-1"}}}
            {"timestamp":"2026-08-17T14:00:05Z","type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"done"}],"internal_chat_message_metadata_passthrough":{"turn_id":"turn-1"}}}
            """
        ).strip()
        + "\n"
    )

    turns = parse_codex_session(transcript)

    assert len(turns) == 1
    assert turns[0].session_id == "sess-1"
    assert turns[0].turn_id == "turn-1"
    assert turns[0].prompt == "collect telemetry"
    assert turns[0].response == "done"
    assert turns[0].tool_calls[0]["name"] == "exec_command"
    assert turns[0].tool_calls[0]["attributes"]["arguments"] == {"cmd": "pwd"}
    assert turns[0].tool_calls[0]["attributes"]["output"] == "ok"


def test_parse_codex_session_skips_incomplete_turns(tmp_path):
    transcript = tmp_path / "rollout-empty.jsonl"
    transcript.write_text(
        '{"timestamp":"2026-08-17T14:00:02Z","type":"event_msg",'
        '"payload":{"type":"user_message","message":"no answer"}}\n'
    )

    assert parse_codex_session(transcript) == []


@pytest.mark.asyncio
async def test_watch_mode_can_run_one_dry_iteration(tmp_path):
    transcript = tmp_path / "rollout-watch.jsonl"
    transcript.write_text(
        textwrap.dedent(
            """
            {"timestamp":"2026-08-17T14:00:00Z","type":"session_meta","payload":{"id":"sess-watch"}}
            {"timestamp":"2026-08-17T14:00:01Z","type":"turn_context","payload":{"turn_id":"turn-watch"}}
            {"timestamp":"2026-08-17T14:00:02Z","type":"event_msg","payload":{"type":"user_message","message":"watch"}}
            {"timestamp":"2026-08-17T14:00:03Z","type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"ok"}],"internal_chat_message_metadata_passthrough":{"turn_id":"turn-watch"}}}
            """
        ).strip()
        + "\n"
    )

    result = await run(
        Namespace(
            sessions=tmp_path,
            home=tmp_path / "graph",
            server_command="xibalba-cortex",
            dry_run=True,
            watch=True,
            poll_interval=0,
            max_iterations=1,
            limit_files=0,
            limit_turns=0,
        )
    )

    assert result["iterations"] == 1
    assert result["last_summary"]["turns_seen"] == 1
    assert result["last_summary"]["turns_ingested"] == 0
