from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Union
import winrm


@dataclass
class WinRMResult:
    host: str
    transport: str
    command_type: str  # "ps" or "cmd"
    command: str
    status_code: int
    stdout: str
    stderr: str


def run_winrm(
    host: str,
    username: str,
    password: str,
    *,
    command: str,
    command_type: str = "ps",          # "ps" (PowerShell) or "cmd"
    args: Optional[Sequence[str]] = None,  # Only for command_type="cmd"
    port: Optional[int] = None,
    use_ssl: bool = False,
    path: str = "wsman",
    transport: str = "ntlm",           # "ntlm" | "kerberos" | "basic" | "certificate"
    verify_ssl: Union[bool, str] = True,   # True/False or path to CA bundle
    server_cert_validation: str = "validate",  # "validate" or "ignore" (pywinrm uses this)
    read_timeout_sec: int = 60,
    operation_timeout_sec: int = 40,
) -> WinRMResult:
    """
    Execute a remote command on Windows via WinRM.

    Parameters
    ----------
    host : str
        DNS name or IP of the Windows host
    username/password : str
        Credentials (DOMAIN\\user, user@domain, or local user)
    command : str
        PowerShell script (command_type="ps") or CMD command (command_type="cmd")
    command_type : str
        "ps" or "cmd"
    args : list[str] | None
        Optional arguments for CMD command when using run_cmd
    use_ssl : bool
        True -> HTTPS (typically 5986), False -> HTTP (typically 5985)
    verify_ssl : bool | str
        TLS validation: True, False, or CA bundle file path
    server_cert_validation : str
        "validate" (recommended) or "ignore" (not recommended)
    read_timeout_sec / operation_timeout_sec : int
        WinRM timeouts

    Returns
    -------
    WinRMResult
    """
    scheme = "https" if use_ssl else "http"
    if port is None:
        port = 5986 if use_ssl else 5985
    endpoint = f"{scheme}://{host}:{port}/{path}"

    # Map verify_ssl to what pywinrm expects.
    # pywinrm uses requests under the hood; verify can be True/False or CA bundle path.
    # server_cert_validation is a pywinrm setting used mainly in older versions;
    # leaving both gives flexibility across environments.
    session = winrm.Session(
        target=endpoint,
        auth=(username, password),
        transport=transport,
        server_cert_validation=server_cert_validation,
        read_timeout_sec=read_timeout_sec,
        operation_timeout_sec=operation_timeout_sec,
        # requests kwargs:
        
    )

    if command_type.lower() == "ps":
        r = session.run_ps(command)
        stdout = (r.std_out or b"").decode("utf-8", errors="replace")
        stderr = (r.std_err or b"").decode("utf-8", errors="replace")
        return WinRMResult(
            host=host,
            transport=transport,
            command_type="ps",
            command=command,
            status_code=r.status_code,
            stdout=stdout,
            stderr=stderr,
        )

    elif command_type.lower() == "cmd":
        r = session.run_cmd(command, args or [])
        stdout = (r.std_out or b"").decode("utf-8", errors="replace")
        stderr = (r.std_err or b"").decode("utf-8", errors="replace")
        return WinRMResult(
            host=host,
            transport=transport,
            command_type="cmd",
            command=" ".join([command] + list(args or [])),
            status_code=r.status_code,
            stdout=stdout,
            stderr=stderr,
        )

    else:
        raise ValueError("command_type must be 'ps' or 'cmd'")

res = run_winrm(
    host="10.10.9.59",
    username=r".\administrator",
    password="gdptraining",
    command="Get-Date; hostname; whoami",
    command_type="ps",
    transport="ntlm",
    use_ssl=False,        # HTTP
)

print("RC:", res.status_code)
print("OUT:", res.stdout)
print("ERR:", res.stderr)
