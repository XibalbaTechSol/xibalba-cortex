// Observer-only OpenClaw typed-hook bridge into local Cortex.
import { spawn } from "node:child_process";

const PYTHON = process.env.XIBALBA_CORTEX_PYTHON ||
  "/home/xibalba/Projects/xibalba-cortex/.venv/bin/python";

function forward(hook, event) {
  try {
    const child = spawn(PYTHON, ["-m", "xibalba_cortex.openclaw_bridge", hook], {
      detached: true,
      stdio: ["pipe", "ignore", "ignore"],
      env: { ...process.env, XIBALBA_RUNTIME: "openclaw" },
    });
    child.stdin.end(JSON.stringify(event, (_key, value) =>
      typeof value === "bigint" ? String(value) : value));
    child.unref();
  } catch (_) {
    // Telemetry must never block or fail the OpenClaw turn.
  }
}

export default {
  id: "xibalba-cortex-telemetry",
  name: "Xibalba Cortex telemetry",
  description: "Forwards OpenClaw typed lifecycle events to local Cortex.",
  register(api) {
    const hooks = [
      "before_model_resolve", "before_prompt_build", "before_agent_reply", "agent_end",
      "before_compaction", "after_compaction", "before_tool_call", "after_tool_call",
      "tool_result_persist", "message_received", "message_sending", "message_sent",
      "session_start", "session_end", "subagent_spawned", "subagent_ended",
      "gateway_start", "gateway_stop",
    ];
    for (const hook of hooks) api.on(hook, async (event) => { forward(hook, event); });
  },
};
