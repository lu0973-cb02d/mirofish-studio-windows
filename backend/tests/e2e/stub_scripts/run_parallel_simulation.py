"""Stand-in for ``backend/scripts/run_parallel_simulation.py``.

The real script drives camel-oasis, which downloads recommendation models and
needs a live LLM, so it cannot run in CI. This stub honours the same process
contract the Flask side depends on and keeps everything else real:

* CLI flags: ``--config``, ``--max-rounds``, ``--no-wait``
* ``<platform>/actions.jsonl`` written through the real ``action_logger``
* ``env_status.json`` and the ``ipc_commands``/``ipc_responses`` directories,
  with the same command and response shapes as ``ParallelIPCHandler``

Environment knobs: ``STUB_ROUND_DELAY`` (seconds per round) and
``STUB_CRASH_AT_ROUND`` (exit with status 3 after that round started).
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from action_logger import PlatformActionLogger  # noqa: E402  (real implementation)


def write_status(directory: str, status: str) -> None:
    with open(os.path.join(directory, "env_status.json"), "w", encoding="utf-8") as handle:
        json.dump({"status": status, "twitter_available": True, "reddit_available": True,
                   "timestamp": datetime.now().isoformat()}, handle)


def respond(directory: str, command_id: str, status: str, result=None, error=None) -> None:
    body = {"command_id": command_id, "status": status, "result": result, "error": error,
            "timestamp": datetime.now().isoformat()}
    with open(os.path.join(directory, "ipc_responses", f"{command_id}.json"), "w", encoding="utf-8") as handle:
        json.dump(body, handle, ensure_ascii=False)
    try:
        os.remove(os.path.join(directory, "ipc_commands", f"{command_id}.json"))
    except OSError:
        pass


def interview_answer(agent_id: int, prompt: str, platform: str) -> dict:
    return {"agent_id": agent_id, "prompt": prompt, "platform": platform,
            "response": f"[{platform}] agent {agent_id} 回答：{prompt[-20:]}",
            "timestamp": datetime.now().isoformat()}


def handle(directory: str, command: dict) -> bool:
    """Return False once the environment should shut down."""
    command_id, kind, args = command["command_id"], command["command_type"], command.get("args", {})
    if kind == "close_env":
        respond(directory, command_id, "completed", {"message": "环境即将关闭"})
        return False
    if kind == "interview":
        platform = args.get("platform")
        if platform in ("twitter", "reddit"):
            result = interview_answer(args["agent_id"], args["prompt"], platform)
        else:
            result = {"agent_id": args["agent_id"], "prompt": args["prompt"], "platforms": {
                p: interview_answer(args["agent_id"], args["prompt"], p) for p in ("twitter", "reddit")}}
        respond(directory, command_id, "completed", result)
    elif kind == "batch_interview":
        interviews = args.get("interviews", [])
        results = {f"{item.get('platform') or 'twitter'}_{item['agent_id']}":
                   interview_answer(item["agent_id"], item["prompt"], item.get("platform") or "twitter")
                   for item in interviews}
        respond(directory, command_id, "completed",
                {"interviews_count": len(results), "results": results})
    else:
        respond(directory, command_id, "failed", error=f"未知命令类型: {kind}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--max-rounds", type=int)
    parser.add_argument("--no-wait", action="store_true")
    args = parser.parse_args()

    directory = os.path.dirname(os.path.abspath(args.config))
    config = json.load(open(args.config, encoding="utf-8"))
    time_config = config.get("time_config", {})
    rounds = int(time_config.get("total_simulation_hours", 2) * 60 / time_config.get("minutes_per_round", 60))
    if args.max_rounds:
        rounds = min(rounds, args.max_rounds)
    agents = config.get("agent_configs", [])
    delay = float(os.environ.get("STUB_ROUND_DELAY", "0.05"))
    crash_at = int(os.environ.get("STUB_CRASH_AT_ROUND", "0"))

    loggers = {p: PlatformActionLogger(p, directory) for p in ("twitter", "reddit")}
    for logger in loggers.values():
        logger.log_simulation_start(config)
    totals = {p: 0 for p in loggers}
    for round_number in range(1, rounds + 1):
        for platform, logger in loggers.items():
            logger.log_round_start(round_number, round_number % 24)
            for agent in agents[:2]:
                logger.log_action(round_number, agent["agent_id"], agent.get("entity_name", f"agent{agent['agent_id']}"),
                                  "CREATE_POST", {"content": f"第{round_number}轮的发言"}, success=True)
                totals[platform] += 1
            logger.log_round_end(round_number, min(len(agents), 2))
        if crash_at and round_number >= crash_at:
            print("stub crashing on request", flush=True)
            return 3
        time.sleep(delay)
    for platform, logger in loggers.items():
        logger.log_simulation_end(rounds, totals[platform])

    if args.no_wait:
        return 0

    os.makedirs(os.path.join(directory, "ipc_commands"), exist_ok=True)
    os.makedirs(os.path.join(directory, "ipc_responses"), exist_ok=True)
    write_status(directory, "alive")
    running = True
    while running:
        for name in sorted(os.listdir(os.path.join(directory, "ipc_commands"))):
            if not name.endswith(".json"):
                continue
            try:
                command = json.load(open(os.path.join(directory, "ipc_commands", name), encoding="utf-8"))
            except (OSError, ValueError):
                continue
            running = handle(directory, command)
            if not running:
                break
        time.sleep(0.1)
    write_status(directory, "stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
