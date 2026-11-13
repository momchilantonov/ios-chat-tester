#!/usr/bin/env python3
"""Entry point.

  python3 simchat_server.py                     -> MCP server on stdio (what Copilot CLI / VS Code start)
  python3 simchat_server.py <tool> [key=value]  -> run one tool by hand and print the JSON result, e.g.
        python3 simchat_server.py status
        python3 simchat_server.py start_driver
        python3 simchat_server.py send_message text="Hello"
        python3 simchat_server.py wait_for_reply
        python3 simchat_server.py tap element=7
  python3 simchat_server.py demo "Hello"        -> start driver, show screen, send, wait, print the reply
Values are parsed as JSON when possible (numbers, true/false, {...}), otherwise taken as text.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

if sys.version_info < (3, 9):
    sys.exit("simchat needs Python 3.9+ (macOS: /usr/bin/python3 from the Xcode command line tools)")

from simchat.config import load_config  # noqa: E402
from simchat.mcp import TOOL_NAMES, Server, call_tool  # noqa: E402
from simchat.tester import Tester, ToolError  # noqa: E402


def _parse(pairs):
    args = {}
    for pair in pairs:
        if "=" not in pair:
            sys.exit("arguments must look like key=value, got %r" % pair)
        key, value = pair.split("=", 1)
        try:
            args[key] = json.loads(value)
        except ValueError:
            args[key] = value
    return args


def _print(result):
    result = dict(result)
    if result.get("_image"):
        result["screenshot"] = result.pop("_image")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _cli(argv):
    tester = Tester(load_config())
    if argv[0] == "demo":
        text = argv[1] if len(argv) > 1 else "Hello"
        for name, args in (("start_driver", {"wait_s": 110}), ("open_app", {}), ("screen", {}),
                           ("send_message", {"text": text}), ("wait_for_reply", {})):
            print("== %s %s" % (name, json.dumps(args, ensure_ascii=False)))
            try:
                _print(call_tool(tester, name, args))
            except ToolError as exc:
                _print(exc.to_dict())
                return 1
        return 0
    if argv[0] not in TOOL_NAMES:
        sys.exit("unknown tool %r. Tools: %s" % (argv[0], ", ".join(sorted(TOOL_NAMES))))
    try:
        _print(call_tool(tester, argv[0], _parse(argv[1:])))
        return 0
    except ToolError as exc:
        _print(exc.to_dict())
        return 1


def main():
    if len(sys.argv) > 1:
        if sys.argv[1] in ("-h", "--help", "help"):
            print(__doc__)
            return 0
        return _cli(sys.argv[1:])
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    Server(lambda: Tester(load_config()), sys.stdout).serve(sys.stdin)
    return 0


if __name__ == "__main__":
    sys.exit(main())
