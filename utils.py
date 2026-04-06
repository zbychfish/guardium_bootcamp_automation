#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Utility functions for Guardium Bootcamp Automation
Contains helper functions for SSH operations, database connections, parsing, and file operations
"""

import os
import re
import json
import time
import socket
import subprocess
import pwd
from typing import Any, Dict, List, Optional, Tuple, Iterator
from pathlib import Path

import paramiko
import oracledb
import psycopg2


# ============================================================================
# ANSI and Text Processing
# ============================================================================

ANSI_RE = re.compile(r"\x1B\[[0-9;?]*[ -/]*[@-~]")


def strip_ansi(s: str) -> str:
    """Remove ANSI escape sequences from text"""
    return ANSI_RE.sub("", s)


def _find_last_prompt_span(text: str, prompt_re: re.Pattern) -> Optional[Tuple[int, int]]:
    """Return (start, end) of the last prompt match"""
    last = None
    for m in prompt_re.finditer(text):
        last = (m.start(), m.end())
    return last


# ============================================================================
# Environment and Configuration
# ============================================================================

def get_env_value(key: str) -> str:
    """Return the value of the environment variable specified by the key argument"""
    value = os.getenv(key)
    if not value:
        raise ValueError(f"Value for {key} not found in .env")
    return value


def save_to_env(key: str, value: str, env_file: str = ".env") -> bool:
    """
    Save value for key in .env file
    
    Args:
        key: Variable name
        value: Variable value
        env_file: Path to .env file
    
    Returns:
        True if successful, False otherwise
    """
    try:
        env_path = os.path.join(os.path.dirname(__file__), env_file)
        lines = []
        key_found = False
        
        if os.path.exists(env_path):
            with open(env_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            for i, line in enumerate(lines):
                if line.strip().startswith(f"{key}="):
                    lines[i] = f"{key}={value}\n"
                    key_found = True
                    break
        
        if not key_found:
            if lines and not lines[-1].endswith('\n'):
                lines.append('\n')
            lines.append(f"{key}={value}\n")
        
        with open(env_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        
        os.environ[key] = value
        return True
    except Exception as e:
        print(f"  ✗ Error saving to .env: {e}")
        return False


# ============================================================================
# SSH and Remote Command Execution
# ============================================================================

def run_many_commands_remotely(host, commands, port=22, key_file=None, password=None):
    """Execute multiple commands on remote host via SSH"""
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())

    client.connect(
        hostname=host,
        port=port,
        username="root",
        key_filename=key_file,
        password=password,
        look_for_keys=True,
        allow_agent=True,
        timeout=15,
    )

    results = []
    for cmd in commands:
        stdin, stdout, stderr = client.exec_command(cmd, timeout=60)
        rc = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        results.append({"cmd": cmd, "rc": rc, "stdout": out, "stderr": err})

    client.close()
    return results


def change_password_as_root(
    host: str,
    root_password: str,
    target_user: str,
    new_password: str,
    port: int = 22,
    timeout: int = 10,
) -> bool:
    """
    Log in as root via SSH (password) and change target_user password.
    
    Returns:
        True if successful, False on error
    """
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        client.connect(
            hostname=host,
            port=port,
            username="root",
            password=root_password,
            look_for_keys=False,
            allow_agent=False,
            timeout=timeout,
            banner_timeout=timeout,
            auth_timeout=timeout,
        )

        # chpasswd reads from stdin: user:new_password
        cmd = "chpasswd"
        stdin, stdout, stderr = client.exec_command(cmd)

        stdin.write(f"{target_user}:{new_password}\n")
        stdin.flush()
        stdin.close()

        exit_code = stdout.channel.recv_exit_status()
        client.close()

        return exit_code == 0

    except (paramiko.SSHException, socket.error) as e:
        print(f"SSH error on {host}: {e}")
        return False


def scp_file_as_root(
    host: str,
    root_password: str,
    local_path: str,
    remote_path: str,
    port: int = 22,
    timeout: int = 30,
    direction: str = "put"
) -> bool:
    """
    Transfer file via SCP as root using sshpass + scp.
    
    Args:
        host: IP address/hostname
        root_password: Root password
        local_path: Local file path (for 'put') or remote path (for 'get')
        remote_path: Target path on server (for 'put') or local path (for 'get')
        port: SSH port (default 22)
        timeout: Timeout in seconds
        direction: Transfer direction - 'put' (upload) or 'get' (download)
    
    Returns:
        True if successful, False on error
    """
    try:
        if direction == "put":
            # Upload: local -> remote
            cmd = [
                "sshpass", "-p", root_password,
                "scp",
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-P", str(port),
                local_path,
                f"root@{host}:{remote_path}"
            ]
        elif direction == "get":
            # Download: remote -> local
            cmd = [
                "sshpass", "-p", root_password,
                "scp",
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-P", str(port),
                f"root@{host}:{local_path}",
                remote_path
            ]
        else:
            raise ValueError(f"Invalid direction: {direction}. Use 'put' or 'get'")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        if result.returncode == 0:
            return True
        else:
            print(f"  SCP error on {host}: {result.stderr.strip()}")
            return False
            
    except FileNotFoundError:
        print(f"  SCP error on {host}: sshpass not found. Install: apt-get install sshpass")
        return False
    except subprocess.TimeoutExpired:
        print(f"  SCP error on {host}: Timeout after {timeout}s")
        return False
    except Exception as e:
        print(f"  SCP error on {host}: {e}")
        return False


def run_as_user(argv, user, *, check=True, **kwargs):
    """Run subprocess as a specific user"""
    pw = pwd.getpwnam(user)
    uid, gid = pw.pw_uid, pw.pw_gid
    home = pw.pw_dir

    def demote():
        # Set group and uid of child process
        os.setgid(gid)
        os.setuid(uid)

    env = dict(os.environ)
    env["HOME"] = home
    env["USER"] = user
    env["LOGNAME"] = user

    return subprocess.run(
        argv,
        check=check,
        env=env,
        preexec_fn=demote,
        **kwargs
    )


# ============================================================================
# Database Operations - Oracle
# ============================================================================

def get_oracle_conn(
    user: str,
    password: str,
    host: str,
    port: int,
    service_name: str
) -> oracledb.Connection:
    """
    Create and return Oracle connection (Thin mode).
    """
    dsn = f"{host}:{port}/{service_name}"
    return oracledb.connect(
        user=user,
        password=password,
        dsn=dsn
    )


def run_sql_oracle(
    conn: oracledb.Connection,
    sql: str,
    params: Optional[Dict[str, Any]] = None,
    fetch: bool = False
) -> Optional[list]:
    """
    Execute SQL on Oracle.

    Args:
        conn: Open oracledb.Connection
        sql: SQL query
        params: Named parameters (:param)
        fetch: Whether to return results (True for SELECT)
    
    Returns:
        List of rows or None
    """
    with conn.cursor() as cursor:
        cursor.execute(sql, params or {})

        if fetch:
            # Fetch all results before closing cursor
            return cursor.fetchall()

        conn.commit()
        return None


# ============================================================================
# Database Operations - PostgreSQL
# ============================================================================

def get_postgres_conn(
    host: str,
    port: int,
    dbname: str,
    user: str,
    password: str
) -> psycopg2.extensions.connection:
    """
    Create and return PostgreSQL connection.
    """
    return psycopg2.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password
    )


def run_sql_postgres(
    cur: psycopg2.extensions.cursor,
    sql: str,
    params: Optional[Tuple | Dict[str, Any]] = None,
    fetch: bool = False
) -> Optional[Iterator[Tuple]]:
    """
    Execute SQL on PostgreSQL.

    Args:
        cur: PostgreSQL cursor
        sql: SQL query
        params: Query parameters (tuple or dict)
        fetch: Whether to return results
            - fetch=True  -> returns iterator over results (SELECT)
            - fetch=False -> commit (INSERT/UPDATE/DELETE/DDL)
    
    Returns:
        Iterator or None
    """
    with cur as cursor:
        cursor.execute(sql, params)

        if fetch:
            # Iterator – lazy fetch
            return cursor
        return None


# ============================================================================
# Parsing and Text Processing
# ============================================================================

def parse_unit_summary(text: str) -> dict:
    """
    Extract from loose text:
      - host (from 'Unit Host=...'; if missing, uses first FQDN in text),
      - ip (from 'IP=...'),
      - unit_type (from 'Unit Type=...'),
      - online (from 'Online=true/false' -> bool).
    
    Returns:
        Dictionary with extracted values
    """
    # Safely flatten spaces
    t = re.sub(r"\s+", " ", text.strip())

    def grab(pattern, flags=0, group=1):
        m = re.search(pattern, t, flags)
        return m.group(group) if m else None

    # Host: prefer 'Unit Host=...'; fallback: first FQDN at line start
    host = grab(r"\bUnit\s+Host=([A-Za-z0-9._-]+)")
    if not host:
        host = grab(r"\b([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")  # e.g. coll1.gdemo.com

    # IP (first after 'IP=')
    ip = grab(r"\bIP=(\d{1,3}(?:\.\d{1,3}){3})\b")

    # Unit Type
    unit_type = grab(r"\bUnit\s+Type=([A-Za-z0-9._-]+)")

    # Online (as bool)
    online_str = grab(r"\bOnline=(true|false)\b", flags=re.IGNORECASE)
    online = None
    if online_str is not None:
        online = online_str.lower() == "true"

    return {
        "host": host,
        "ip": ip,
        "unit_type": unit_type,
        "online": online,
    }


def to_valid_json(src: str) -> str:
    """Convert loose JavaScript-like object notation to valid JSON"""
    s = src

    # a) Quote keys: {hostName: ... , port: ...} -> {"hostName": ..., "port": ...}
    s = re.sub(r'([{\s,])([A-Za-z_]\w*)\s*:', r'\1"\2":', s)

    # b) Quote known text values (hostName, unitType, guardRelease, ip, lastInstalledPatch)
    #    Use separate patterns to avoid touching numbers, [] or {}.
    def quote_value_for(key: str, text: str) -> str:
        # Match:  "<key>" : <unquoted-value>  ending with  , ] }
        pattern = rf'("{key}"\s*:\s*)([^"\s\[\]{{}},][^,\]}}]*)'
        def repl(m):
            g1, val = m.group(1), m.group(2).strip()
            return f'{g1}"{val}"'
        return re.sub(pattern, repl, text)

    for k in ("hostName", "unitType", "guardRelease", "ip", "lastInstalledPatch"):
        s = quote_value_for(k, s)

    # c) Remove double spaces/commas from artifacts
    s = re.sub(r'\s+', ' ', s)
    return s


def parse_mus_from_message_dict(dct: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse MUS (Managed Unit Summary) from message dictionary"""
    raw = dct.get("Message") or dct.get("message")
    if not raw:
        return []
    fixed = to_valid_json(raw)
    obj = json.loads(fixed)  # May raise ValueError if format is different than expected
    mus = obj.get("mus")
    if not isinstance(mus, list):
        return []
    # At this point 'mus' is a regular list of JSON dicts
    return mus


def parse_patch_list(output: str) -> dict[int, int]:
    """
    Parse output with patch list and return mapping: patch_number -> line_number.
    
    Args:
        output: Output from 'store system patch install sys' command containing patch list
    
    Returns:
        Dictionary mapping patch number to line number (1-based), e.g. {9997: 1, 4015: 2}
    
    Example:
        >>> output = '''Attempting to retrieve the patch information...
        ... P#      Description                                   Version Md5sum
        ... 9997    Health Check for GPU and Bundle installation  12.0    de27af692f57b738e50c829a4f1d6800
        ... 4015    Snif Update (Nov 20 2025)                     12.0    4ff4686f434c68c261ba52933bef1d0d'''
        >>> parse_patch_list(output)
        {9997: 1, 4015: 2}
    """
    patch_map = {}
    line_number = 0
    
    for line in output.splitlines():
        # Skip empty lines and headers
        line = line.strip()
        if not line or line.startswith('Attempting') or line.startswith('P#') or 'Please wait' in line:
            continue
        
        # Check if line starts with a number (patch number)
        parts = line.split(None, 1)  # Split on first space
        if parts and parts[0].isdigit():
            patch_number = int(parts[0])
            line_number += 1
            patch_map[patch_number] = line_number
    
    return patch_map


def get_patch_line_numbers(output: str) -> list[int]:
    """
    Return line numbers for patches defined in PATCH_LIST environment variable.
    
    Args:
        output: Output from 'store system patch install sys' command containing patch list
    
    Returns:
        List of line numbers (1-based) corresponding to patches from PATCH_LIST in order
    
    Example:
        If PATCH_LIST="9997,4015" in .env file:
        >>> output = '''...
        ... 9997    Health Check for GPU and Bundle installation  12.0    de27af692f57b738e50c829a4f1d6800
        ... 4015    Snif Update (Nov 20 2025)                     12.0    4ff4686f434c68c261ba52933bef1d0d'''
        >>> get_patch_line_numbers(output)
        [1, 2]
    """
    # Get PATCH_LIST from environment variables
    patch_list_str = get_env_value('PATCH_LIST')
    
    # Parse string to list of ints (e.g. "9997,4015" -> [9997, 4015])
    patch_numbers = [int(p.strip()) for p in patch_list_str.split(',') if p.strip()]
    
    # Parse output and create mapping patch_number -> line_number
    patch_map = parse_patch_list(output)
    
    # Convert patch numbers to line numbers in PATCH_LIST order
    line_numbers = []
    for patch_num in patch_numbers:
        if patch_num in patch_map:
            line_numbers.append(patch_map[patch_num])
        else:
            raise ValueError(f"Patch number {patch_num} not found in output")
    
    return line_numbers


# ============================================================================
# State Management
# ============================================================================

def create_appliance(appliance_name: str, appliances: dict, common_config: dict):
    """Create ApplianceCommand instance for given appliance"""
    from appliance_command import ApplianceCommand
    
    appliance_config = appliances[appliance_name]
    
    # Use initial_pattern from appliance_config if exists, otherwise from common_config
    initial_pattern = appliance_config.get('initial_pattern', common_config['initial_pattern'])
    
    return ApplianceCommand(
        host=appliance_config['host'],
        user=common_config['user'],
        password=appliance_config['password'],
        prompt_regex=appliance_config['prompt_regex'],
        initial_pattern=initial_pattern,
        timeout=common_config['timeout']
    )


def wait_for_appliance(appliance_name: str, appliances: dict, common_config: dict, max_attempts: int = 40, interval: int = 15):
    """
    Wait until appliance is available and establish connection.
    
    Args:
        appliance_name: Appliance name from configuration
        appliances: Appliances configuration dictionary
        common_config: Common configuration dictionary
        max_attempts: Maximum number of connection attempts
        interval: Interval between attempts in seconds
    
    Returns:
        Connected ApplianceCommand object
    
    Raises:
        RuntimeError: If connection failed after all attempts
    """
    print(f"\n[INFO] Waiting for appliance '{appliance_name}' availability...")
    
    for attempt in range(1, max_attempts + 1):
        print(f"[INFO] Connection attempt {attempt}/{max_attempts}...")
        
        try:
            appliance = create_appliance(appliance_name, appliances, common_config)
            if appliance.connect():
                print(f"[INFO] ✓ Connected to '{appliance_name}' after {attempt} attempts")
                return appliance
        except Exception as e:
            print(f"[INFO] ✗ Attempt {attempt} failed: {e}")
        
        if attempt < max_attempts:
            print(f"[INFO] Waiting {interval} seconds before next attempt...")
            time.sleep(interval)
    
    raise RuntimeError(f"Failed to connect to '{appliance_name}' after {max_attempts} attempts")


def load_state(state_file: str):
    """Load state from JSON file"""
    if not os.path.exists(state_file):
        return {"completed_tasks": []}
    with open(state_file, "r") as f:
        return json.load(f)


def save_state(state, state_file: str):
    """Save state to JSON file"""
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)


def run_task(task_id, task_fn, state, state_file: str):
    """Run task if not already completed"""
    if task_id in state["completed_tasks"]:
        print(f"Skipping {task_id}")
        return
    print(f"Running {task_id}")
    output = task_fn()
    state["completed_tasks"].append(task_id)
    save_state(state, state_file)
    return output


# ============================================================================
# Monitoring and Polling
# ============================================================================

def monitor_gim_module_installation(api, client_ip):
    """Monitor GIM module installation progress"""
    pending = ["initial"]  # Initialize to enter loop
    while pending:
        modules = api.gim_list_client_modules(client_ip=client_ip)
        msg = modules["Message"]

        entries = [
            e.strip()
            for e in re.split(r"#+\s*ENTRY\s+\d+\s*#+", msg)
            if e.strip()
        ]

        result = []

        for e in entries:
            def g(p):
                m = re.search(p, e)
                return m.group(1) if m else None

            result.append({
                "module_id": g(r"MODULE_ID:\s+(-?\d+)"),
                "name": g(r"NAME:\s+([A-Z0-9\-]+)"),
                "installed_version": g(r"INSTALLED_VERSION\s+([0-9][^\s]+)"),
                "scheduled_version": g(r"SCHEDULED_VERSION\s+([0-9][^\s]+)"),
                "state": g(r"STATE:\s+([A-Z\-]+)"),
                "is_scheduled": g(r"IS_SCHEDULED:\s+([NY])"),
                "schedule_time": g(r"IS_SCHEDULED:\s+[NY]\s+\(([^)]+)\)")
            })
        
        pending = [m for m in result if m["state"] != "INSTALLED"]
        
        if pending:
            print("Waiting 30 seconds before next check...")
            time.sleep(30)
        else:
            print("All modules installed successfully!")

# Made with Bob
