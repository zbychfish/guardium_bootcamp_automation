#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Paramiko CLI runner for proprietary shells (e.g., Guardium).

What it does:
  - Connects via SSH (password or key).
  - Optionally waits for an initial banner/pattern (e.g., "Last login").
  - Detects the CLI prompt via a user-supplied regex (e.g., r"coll1\\.gdemo\\.com>").
  - Sends ONE or MANY commands; for each command:
      * sends CRLF,
      * captures output until the NEXT prompt,
      * strips command echo,
      * optionally strips ANSI sequences,
      * checks error by regex (default: ^(ERROR:|Error:)).
  - Logs out using a logout command (default: "quit").

Exit codes:
  0  success (all commands considered OK by error-regex)
  1  invalid args
  2  SSH connection/auth failure
  3  timeout while waiting for initial pattern or prompt
  4  at least one command reported error (matched --error-regex)
  5  unexpected runtime error

Typical usage (Guardium-like CLI):
  python test.py \
    --host 10.10.9.239 \
    --user cli \
    --password 'Guardium123!' \
    --prompt-regex "coll1\.gdemo\.com>" \
    --commands-file cmds.txt \
    --timeout 120 \
    --logout-command "quit" \
    --strip-ansi --debug

Where cmds.txt can contain for example:
  unlock accessmgr
  unlock admin
  unregister management
  update certificate smime recipient
  update certificate smime sender
  upgradeserver
  ok
"""

import argparse
import os
import re
import sys
import time
import socket
from typing import List, Optional, Tuple

import paramiko

# ---------- ANSI handling ----------
ANSI_RE = re.compile(r"\x1B\[[0-9;?]*[ -/]*[@-~]")  # CSI + some ESC seqs


def strip_ansi(s: str) -> str:
    return ANSI_RE.sub("", s)


# ---------- Regex / prompt helpers ----------
def _find_last_prompt_span(text: str, prompt_re: re.Pattern) -> Optional[Tuple[int, int]]:
    """
    Returns (start, end) of the LAST prompt match in text, or None if not found.
    """
    last = None
    for m in prompt_re.finditer(text):
        last = (m.start(), m.end())
    return last


# ---------- SSH / channel helpers ----------
def open_shell(client: paramiko.SSHClient, debug: bool = False) -> paramiko.Channel:
    """
    Open an interactive shell with a PTY and gently "nudge" the prompt.
    Some appliance CLIs need CR/LF to wake up.
    """
    chan = client.invoke_shell(term="xterm", width=200, height=40)
    time.sleep(0.2)
    # Send CR/LF a couple times to surface the prompt
    for _ in range(2):
        chan.send("\r")
        time.sleep(0.1)
        chan.send("\n")
        time.sleep(0.1)
    if debug:
        print("[DEBUG] invoke_shell opened and nudged with CR/LF")
    return chan


def read_until_regex(
    channel: paramiko.Channel,
    regex: re.Pattern,
    timeout: int,
    echo: bool = True,
    stripansi: bool = False,
    debug: bool = False,
) -> str:
    """
    Read channel output until 'regex' matches or timeout occurs.
    Optionally strip ANSI for matching and echoing.
    Returns the FULL raw buffer (without forcibly stripping).
    """
    buf = ""
    deadline = time.time() + timeout
    backoff = 0.05

    while time.time() < deadline:
        progressed = False

        if channel.recv_ready():
            chunk = channel.recv(65535).decode(errors="replace")
            buf += chunk
            progressed = True
            out = strip_ansi(chunk) if stripansi else chunk
            if echo:
                sys.stdout.write(out)
                sys.stdout.flush()

        if channel.recv_stderr_ready():
            chunk = channel.recv_stderr(65535).decode(errors="replace")
            buf += chunk
            progressed = True
            out = strip_ansi(chunk) if stripansi else chunk
            if echo:
                sys.stdout.write(out)
                sys.stdout.flush()

        # Matching on stripped or raw buffer
        buf_for_match = strip_ansi(buf) if stripansi else buf
        if regex.search(buf_for_match):
            if debug:
                print(f"\n[DEBUG] regex matched: {regex.pattern!r}")
            return buf

        if not progressed:
            time.sleep(backoff)

        if channel.closed:
            break

    raise TimeoutError(f"Timed out waiting for regex: {regex.pattern!r}")


def send_command_until_prompt(
    channel: paramiko.Channel,
    command: str,
    prompt_re: re.Pattern,
    timeout: int,
    echo: bool = True,
    stripansi: bool = False,
    debug: bool = False,
) -> str:
    """
    Send a SINGLE command (CRLF), then read output until the NEXT prompt appears.
    Returns the output BETWEEN the command echo and the prompt.
    """
    # Flush any residual output before sending the command
    time.sleep(0.05)
    flushed = False
    while channel.recv_ready():
        channel.recv(65535)
        flushed = True
    while channel.recv_stderr_ready():
        channel.recv_stderr(65535)
        flushed = True
    if flushed:
        time.sleep(0.05)

    # Send command with CRLF (appliance CLIs often prefer CR)
    channel.send(command + "\r\n")

    # Read until prompt is visible again
    raw = read_until_regex(
        channel, prompt_re, timeout=timeout, echo=echo, stripansi=stripansi, debug=debug
    )

    # Work on a cleaned version for parsing lines; keep ANSI stripped if requested
    working = strip_ansi(raw) if stripansi else raw

    # Cut off the final prompt
    last_span = _find_last_prompt_span(working, prompt_re)
    output_region = working[: last_span[0]] if last_span else working

    # Lines processing: drop leading blanks and command echo
    lines = output_region.splitlines()

    # Drop leading empty lines
    while lines and not lines[0].strip():
        lines.pop(0)

    # Remove command echo:
    #  a) line equal to the command
    #  b) "<prompt> command"
    if lines:
        first = lines[0].rstrip("\r\n")
        if first.strip() == command.strip():
            lines = lines[1:]
        else:
            # Try "<PROMPT> command"
            prompt_src = prompt_re.pattern
            prompt_cmd_re = re.compile(rf"^(?:{prompt_src})\s*{re.escape(command.strip())}\s*$")
            if prompt_cmd_re.match(first):
                lines = lines[1:]

    cleaned = "\n".join(lines).strip("\n")
    if debug:
        print(f"[DEBUG] extracted output for '{command}' ({len(cleaned)} chars)")
    return cleaned


# ---------- Command runner ----------
def run_commands_sequence(
    channel: paramiko.Channel,
    commands: List[str],
    prompt_re: re.Pattern,
    timeout: int,
    error_re: re.Pattern,
    echo: bool,
    stripansi: bool,
    debug: bool,
) -> bool:
    """
    Runs commands in order. Prints output for each.
    Returns True if ALL commands considered successful (i.e., did not match error_re).
    """
    all_ok = True
    for idx, cmd in enumerate(commands, 1):
        if debug:
            print(f"\n[INFO] Running [{idx}/{len(commands)}]: {cmd}")
        output = send_command_until_prompt(
            channel,
            cmd,
            prompt_re=prompt_re,
            timeout=timeout,
            echo=False,  # Don't echo during command execution
            stripansi=stripansi,
            debug=debug,
        )

        # Only print the actual command output, not the command itself
        if output:
            print(output)

        if error_re.search(output):
            print("[ERROR] Error pattern matched in command output.")
            all_ok = False

    return all_ok


# ---------- Main ----------
def main() -> int:
    ap = argparse.ArgumentParser(
        description="Paramiko CLI runner: wait for prompt and run one or many commands"
    )
    # Connection/auth
    ap.add_argument("--host", required=True, help="Hostname or IP")
    ap.add_argument("--port", type=int, default=22, help="SSH port (default 22)")
    ap.add_argument("--user", required=True, help="SSH username")
    ap.add_argument("--password", help="SSH password or key passphrase")
    ap.add_argument("--key", help="Path to private key file (optional)")

    # Flow control & matching
    ap.add_argument(
        "--pattern",
        help="Regex to wait for initially (e.g., 'Last login'). Omit with --skip-initial.",
    )
    ap.add_argument(
        "--skip-initial",
        action="store_true",
        help="Do NOT wait for initial --pattern; go straight to prompt waiting.",
    )
    ap.add_argument(
        "--prompt-regex",
        required=True,
        help=r"Regex for CLI prompt, e.g., 'coll1\.gdemo\.com>' or '>\s*$'",
    )
    ap.add_argument("--timeout", type=int, default=60, help="Timeout in seconds")

    # Commands
    ap.add_argument(
        "--command",
        action="append",
        help="Command to run (can be given multiple times). Mutually usable with --commands-file.",
    )
    ap.add_argument(
        "--commands-file",
        help="Path to a file with one command per line (empty lines ignored).",
    )

    # Behavior
    ap.add_argument(
        "--logout-command",
        default="quit",
        help='Logout command to end the session (default: "quit")',
    )
    ap.add_argument(
        "--error-regex",
        default=r"^(ERROR:|Error:)",
        help="Regex; if it matches command output, the command is considered failed.",
    )
    ap.add_argument("--no-echo", action="store_true", help="Do not echo remote output live")
    ap.add_argument("--strip-ansi", action="store_true", help="Strip ANSI sequences for matching/echo")
    ap.add_argument("--debug", action="store_true", help="Verbose internal logs")

    # Host key policy
    ap.add_argument(
        "--strict-host-key",
        action="store_true",
        help="Reject unknown host keys (load system/user known_hosts).",
    )
    ap.add_argument("--known-hosts", help="Additional known_hosts file to load (optional)")

    args = ap.parse_args()

    # Validate arguments
    if not args.skip_initial and not args.pattern:
        print("Either provide --pattern or use --skip-initial to bypass initial waiting.", file=sys.stderr)
        return 1

    commands: List[str] = []
    if args.command:
        commands.extend(args.command)
    if args.commands_file:
        path = os.path.expanduser(args.commands_file)
        if not os.path.isfile(path):
            print(f"--commands-file not found: {path}", file=sys.stderr)
            return 1
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if line.strip() == "" or line.strip().startswith("#"):
                    continue
                commands.append(line)
    if not commands:
        print("Provide at least one --command or a --commands-file.", file=sys.stderr)
        return 1

    # Compile regexes
    try:
        prompt_re = re.compile(args.prompt_regex)
    except re.error as e:
        print(f"Invalid --prompt-regex: {e}", file=sys.stderr)
        return 1

    if not args.skip_initial and args.pattern:
        try:
            initial_re = re.compile(args.pattern)
        except re.error as e:
            print(f"Invalid --pattern: {e}", file=sys.stderr)
            return 1
    else:
        initial_re = None  # type: ignore

    try:
        error_re = re.compile(args.error_regex, re.MULTILINE)
    except re.error as e:
        print(f"Invalid --error-regex: {e}", file=sys.stderr)
        return 1

    # Prepare SSH client
    client = paramiko.SSHClient()
    if args.strict_host_key:
        client.load_system_host_keys()
        if args.known_hosts and os.path.isfile(os.path.expanduser(args.known_hosts)):
            client.load_host_keys(os.path.expanduser(args.known_hosts))
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        try:
            client.load_system_host_keys()
        except Exception:
            pass
        if args.known_hosts and os.path.isfile(os.path.expanduser(args.known_hosts)):
            try:
                client.load_host_keys(os.path.expanduser(args.known_hosts))
            except Exception:
                pass
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    # Load private key if provided
    pkey = None
    if args.key:
        key_path = os.path.expanduser(args.key)
        last_exc: Optional[Exception] = None
        for KeyCls in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
            try:
                pkey = KeyCls.from_private_key_file(key_path, password=args.password)
                break
            except Exception as e:
                last_exc = e
                pkey = None
        if pkey is None and last_exc:
            print(f"Failed to load key {key_path}: {last_exc}", file=sys.stderr)
            return 2

    # Connect
    try:
        client.connect(
            hostname=args.host,
            port=args.port,
            username=args.user,
            password=args.password if pkey is None else None,
            pkey=pkey,
            look_for_keys=False,
            allow_agent=False,
            timeout=15,
            banner_timeout=15,
            auth_timeout=15,
            compress=True,
        )
    except (socket.error, paramiko.AuthenticationException, paramiko.SSHException) as e:
        print(f"SSH connection/auth error: {e}", file=sys.stderr)
        return 2

    try:
        chan = open_shell(client, debug=args.debug)

        # 1) Initial banner/pattern (optional) - suppress output
        if initial_re is not None:
            try:
                _ = read_until_regex(
                    chan,
                    initial_re,
                    timeout=args.timeout,
                    echo=False,  # Don't show login banner
                    stripansi=args.strip_ansi,
                    debug=args.debug,
                )
                if args.debug:
                    print(f"\n[INFO] Initial pattern matched: {initial_re.pattern!r}\n")
            except TimeoutError as te:
                print(str(te), file=sys.stderr)
                return 3

        # 2) Ensure we see the prompt before sending commands - suppress output
        try:
            _ = read_until_regex(
                chan,
                prompt_re,
                timeout=args.timeout,
                echo=False,  # Don't show prompt waiting
                stripansi=args.strip_ansi,
                debug=args.debug,
            )
        except TimeoutError:
            # Try nudging again
            chan.send("\r\n")
            _ = read_until_regex(
                chan,
                prompt_re,
                timeout=args.timeout,
                echo=False,  # Don't show prompt waiting
                stripansi=args.strip_ansi,
                debug=args.debug,
            )

        # 3) Run commands
        all_ok = run_commands_sequence(
            chan,
            commands,
            prompt_re=prompt_re,
            timeout=args.timeout,
            error_re=error_re,
            echo=not args.no_echo,
            stripansi=args.strip_ansi,
            debug=args.debug,
        )

        # 4) Logout
        try:
            chan.send(args.logout_command + "\r\n")
            time.sleep(0.2)
        except Exception:
            pass

        return 0 if all_ok else 4

    except TimeoutError as te:
        print(str(te), file=sys.stderr)
        return 3
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 5
    finally:
        try:
            client.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())