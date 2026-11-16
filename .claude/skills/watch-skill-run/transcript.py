#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Find and follow another Claude Code session's transcript, for the watch-skill-run skill.

Usage:
  transcript.py sessions [--hours N]
      One line per session transcript written in the last N hours (default 6), newest first:
      session ID, last write (UTC), working directory, and the first slash command it ran with its args.
  transcript.py follow <session id> [--subagents] [--from-start] [--interval SECONDS] [--idle-minutes N]
      Runs until killed. Prints one line per new event in that session's transcript: assistant text, tool
      calls, the user's answers to questions, tool errors and the user's own messages. With --subagents, also
      every agent the session starts (forks, finders, verifiers), each line prefixed with the agent's name.
      Starts at the transcripts' current ends, or with --from-start replays everything already written first.

Each line is `HH:MM:SS <source> <kind>: <text>`, with newlines collapsed and text cut to a few hundred
characters, so it can feed the Monitor tool directly. The session is looked up by ID under every project
folder on each poll, because a session that enters a worktree starts writing its transcript under a different
project folder; `TRANSCRIPT MOVED` reports that. `IDLE` reports a transcript with no new event for
--idle-minutes, which is either a question waiting on the user or a session that has died.
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECTS_ROOT = Path.home() / ".claude" / "projects"
TEXT_LIMIT = 400


@dataclass
class _FollowedFile:
    path: Path
    source: str
    lines_read: int


@dataclass
class _Follower:
    session_id: str
    include_subagents: bool
    from_start: bool
    main: _FollowedFile | None = None
    subagents: dict[Path, _FollowedFile] = field(default_factory=dict)


def _one_line(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) > TEXT_LIMIT:
        return collapsed[:TEXT_LIMIT] + "…"
    return collapsed


def _complete_lines(*, path: Path) -> list[str]:
    content = path.read_text(encoding="utf-8", errors="replace")
    lines = content.split("\n")
    return lines[:-1]  # the last element is either "" or a line still being written


def _content_blocks(record: dict[str, Any]) -> list[dict[str, Any]]:
    message = record.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [block for block in content if isinstance(block, dict)]
    return []


def _tool_result_text(block: dict[str, Any]) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return " ".join([str(part.get("text", "")) for part in content if isinstance(part, dict)])


def _tool_result_event(*, block: dict[str, Any]) -> str | None:
    text = _tool_result_text(block)
    if block.get("is_error") is True:
        return f"TOOL ERROR: {_one_line(text)}"
    if "The user answered" in text:
        return f"ANSWER: {_one_line(text)}"
    if "questions have been answered" in text:
        return f"ANSWER: {_one_line(text)}"
    return None


def _text_event(*, block: dict[str, Any], from_assistant: bool) -> str | None:
    text = str(block.get("text", ""))
    if from_assistant:
        return f"TEXT: {_one_line(text)}"
    if text.startswith("<system-reminder>"):
        return None
    return f"USER: {_one_line(text)}"


def _block_event(*, block: dict[str, Any], from_assistant: bool) -> str | None:
    block_type = block.get("type")
    if block_type == "tool_use":
        tool_input = json.dumps(block.get("input", {}), ensure_ascii=False)
        return f"TOOL {block.get('name')}: {_one_line(tool_input)}"
    if block_type == "tool_result":
        return _tool_result_event(block=block)
    if block_type == "text":
        return _text_event(block=block, from_assistant=from_assistant)
    return None


def _event_lines(*, record: dict[str, Any], source: str) -> list[str]:
    record_type = record.get("type")
    if record_type == "assistant":
        from_assistant = True
    elif record_type == "user":
        from_assistant = False
    else:
        return []
    stamp = str(record.get("timestamp", ""))[11:19]
    lines: list[str] = []
    for block in _content_blocks(record):
        event = _block_event(block=block, from_assistant=from_assistant)
        if event is not None:
            lines.append(f"{stamp} {source} {event}")
    return lines


def _emit(line: str) -> None:
    _ = sys.stdout.write(line + "\n")
    _ = sys.stdout.flush()


def _read_new_events(*, followed: _FollowedFile) -> list[str]:
    lines = _complete_lines(path=followed.path)
    events: list[str] = []
    for raw in lines[followed.lines_read :]:
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            events.extend(_event_lines(record=record, source=followed.source))
    followed.lines_read = len(lines)
    return events


def _find_main_transcript(*, session_id: str) -> Path | None:
    candidates = list(PROJECTS_ROOT.glob(f"*/{session_id}.jsonl"))
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _subagent_source(*, transcript: Path) -> str:
    meta_path = transcript.with_name(transcript.name.removesuffix(".jsonl") + ".meta.json")
    agent_id = transcript.stem.removeprefix("agent-")[:8]
    if not meta_path.exists():
        return f"agent:{agent_id}"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    name = meta.get("name")
    if isinstance(name, str):
        return f"@{name}"
    description = str(meta.get("description", ""))
    return f"agent:{agent_id}({_one_line(description)[:40]})"


def _poll(*, follower: _Follower) -> list[str]:
    events: list[str] = []
    main_path = _find_main_transcript(session_id=follower.session_id)
    if main_path is None:
        return events
    if follower.main is None:
        lines_read = 0
        if not follower.from_start:
            lines_read = len(_complete_lines(path=main_path))
        follower.main = _FollowedFile(path=main_path, source="main", lines_read=lines_read)
    elif follower.main.path != main_path:
        events.append(f"TRANSCRIPT MOVED: {follower.main.path} -> {main_path}")
        follower.main = _FollowedFile(path=main_path, source="main", lines_read=0)
    events.extend(_read_new_events(followed=follower.main))
    if not follower.include_subagents:
        return events
    for transcript in _subagent_transcripts(session_id=follower.session_id):
        followed = follower.subagents.get(transcript)
        if followed is None:
            followed = _FollowedFile(path=transcript, source=_subagent_source(transcript=transcript), lines_read=0)
            follower.subagents[transcript] = followed
            events.append(f"NEW AGENT {followed.source}: {transcript}")
        events.extend(_read_new_events(followed=followed))
    return events


def _subagent_transcripts(*, session_id: str) -> list[Path]:
    return sorted(PROJECTS_ROOT.glob(f"*/{session_id}/subagents/agent-*.jsonl"))


def _seed_existing_subagents(*, follower: _Follower) -> None:
    for transcript in _subagent_transcripts(session_id=follower.session_id):
        follower.subagents[transcript] = _FollowedFile(
            path=transcript,
            source=_subagent_source(transcript=transcript),
            lines_read=len(_complete_lines(path=transcript)),
        )


def follow(*, session_id: str, include_subagents: bool, from_start: bool, interval: float, idle_minutes: float) -> None:
    follower = _Follower(session_id=session_id, include_subagents=include_subagents, from_start=from_start)
    if _find_main_transcript(session_id=session_id) is None:
        _ = sys.stderr.write(f"No transcript named {session_id}.jsonl under {PROJECTS_ROOT}\n")
        sys.exit(1)
    if include_subagents and not from_start:
        _seed_existing_subagents(follower=follower)
    last_event_at = time.monotonic()
    idle_reported = False
    while True:
        events = _poll(follower=follower)
        for event in events:
            _emit(event)
        if events:
            last_event_at = time.monotonic()
            idle_reported = False
        elif not idle_reported:
            idle_seconds = time.monotonic() - last_event_at
            if idle_seconds >= idle_minutes * 60:
                _emit(f"IDLE: no new event for {idle_minutes:g} min")
                idle_reported = True
        time.sleep(interval)


def _first_command(*, path: Path) -> str:
    for raw in _complete_lines(path=path):
        if "<command-name>" not in raw:
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if record.get("type") != "user":
            continue
        for block in _content_blocks(record):
            text = str(block.get("text", ""))
            if not text.startswith("<command-"):
                continue
            if "<command-name>" not in text:
                continue
            name = text.split("<command-name>", 1)[1].split("</command-name>", 1)[0]
            if name == "/clear":
                continue
            args = ""
            if "<command-args>" in text:
                args = text.split("<command-args>", 1)[1].split("</command-args>", 1)[0]
            return _one_line(f"{name} {args}")
    return "-"


def _working_directory(*, path: Path) -> str:
    for raw in _complete_lines(path=path):
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            cwd = record.get("cwd")
            if isinstance(cwd, str):
                return cwd
    return "-"


def sessions(*, hours: float) -> None:
    cutoff = time.time() - hours * 3600
    transcripts = [path for path in PROJECTS_ROOT.glob("*/*.jsonl") if path.stat().st_mtime >= cutoff]
    for path in sorted(transcripts, key=lambda p: p.stat().st_mtime, reverse=True):
        written = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
        _emit(f"{path.stem}\t{written}\t{_working_directory(path=path)}\t{_first_command(path=path)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    sessions_parser = commands.add_parser("sessions")
    _ = sessions_parser.add_argument("--hours", type=float, default=6)
    follow_parser = commands.add_parser("follow")
    _ = follow_parser.add_argument("session_id")
    _ = follow_parser.add_argument("--subagents", action="store_true")
    _ = follow_parser.add_argument("--from-start", action="store_true")
    _ = follow_parser.add_argument("--interval", type=float, default=2)
    _ = follow_parser.add_argument("--idle-minutes", type=float, default=10)
    args = parser.parse_args()
    if args.command == "sessions":
        sessions(hours=args.hours)
        return
    follow(
        session_id=args.session_id,
        include_subagents=args.subagents,
        from_start=args.from_start,
        interval=args.interval,
        idle_minutes=args.idle_minutes,
    )


if __name__ == "__main__":
    main()
