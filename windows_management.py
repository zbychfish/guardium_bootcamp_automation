from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence
import re
import time
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
    command_type: str = "ps",              # "ps" or "cmd"
    args: Optional[Sequence[str]] = None,  # only for cmd
    port: Optional[int] = None,
    use_ssl: bool = False,
    path: str = "wsman",
    transport: str = "ntlm",               # "ntlm" | "kerberos" | "basic" | "certificate" | "credssp"
    ca_trust_path: Optional[str] = None,   # path do CA bundle (opcjonalnie)
    server_cert_validation: str = "validate",  # "validate" lub "ignore" (dla labów/self-signed) [2](https://github.com/faezehghiasi/ansible-windows-playbooks)[4](https://github.com/diyan/pywinrm)
    read_timeout_sec: int = 60,
    operation_timeout_sec: int = 40,
) -> WinRMResult:
    """
    Execute a remote command on Windows via WinRM.

    NOTE:
    - pywinrm NIE wspiera parametru 'verify=' w Session/Protocol; użyj server_cert_validation i ca_trust_path. [1](https://buildingtents.com/2025/01/15/using-kerberos-to-authenticate-winrm-for-ansible/)[2](https://github.com/faezehghiasi/ansible-windows-playbooks)
    """

    scheme = "https" if use_ssl else "http"

    # Jeśli host ma już port (np. "example.com:26612"), nie doklejaj kolejnego
    if re.search(r":\d+$", host):
        endpoint = f"{scheme}://{host}/{path}"
    else:
        if port is None:
            port = 5986 if use_ssl else 5985
        endpoint = f"{scheme}://{host}:{port}/{path}"

    session = winrm.Session(
        endpoint,
        auth=(username, password),
        transport=transport,
        server_cert_validation=server_cert_validation,
        ca_trust_path=ca_trust_path,
        read_timeout_sec=read_timeout_sec,
        operation_timeout_sec=operation_timeout_sec,
    )

    if command_type.lower() == "ps":
        # Wycisz progress (usuwa CLIXML typu "Preparing modules for first use.")
        prolog = (
            "$ProgressPreference = 'SilentlyContinue'\n"
            "$VerbosePreference  = 'SilentlyContinue'\n"
            "$DebugPreference    = 'SilentlyContinue'\n"
            "$InformationPreference = 'SilentlyContinue'\n"
        )
        ps_script = prolog + command

        r = session.run_ps(ps_script)
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


# === PRZYKŁAD UŻYCIA ===
res = run_winrm(
    host="10.10.9.59",
    username=r".\administrator",
    password="gdptraining",
    command="mkdir GIM_Client; Invoke-WebRequest -Uri 'https://ibm.box.com/shared/static/w26pu9sm69l6ysr2xklvoh9nkxgah23b.zip' -OutFile 'GIM_Client\\GIM_install.zip';Expand-Archive -Path 'GIM_Client\\GIM_install.zip' -DestinationPath 'GIM_Client\\';'GIM_Client\\Setup.exe -UNATTENDED -APPLIANCE 10.10.9.219 -LOCALIP 10.10.9.59'",
    command_type="ps",
    transport="ntlm",
    use_ssl=False,  # HTTP
)

print("RC:", res.status_code)
print("OUT:", res.stdout)
print("ERR:", res.stderr)


# service_name = "gim"
# timeout_sec = 300     # total time to wait
# interval_sec = 5      # sleep between checks

# deadline = time.time() + timeout_sec

# # PowerShell that won't error if service is missing
# ps = (
#     f"$svc = Get-Service -Name '{service_name}' -ErrorAction SilentlyContinue; "
#     "if (-not $svc) { 'MISSING' } else { $svc.Status.ToString() }"
# )

# last = None

# while time.time() < deadline:
#     res = run_winrm(
#         host="10.10.9.59",
#         username=r".\administrator",
#         password="gdptraining",
#         command=ps,
#         command_type="ps",
#         transport="ntlm",
#         use_ssl=False,
#     )

#     status = (res.stdout or "").strip()
#     last = status

#     print(f"Service {service_name} status: {status!r}")

#     if status == "Running":
#         print("✅ Service is Running")
#         break

#     # Still missing or not running yet -> wait and retry
#     time.sleep(interval_sec)
# else:
#     raise TimeoutError(
#         f"Service '{service_name}' did not reach 'Running' within {timeout_sec}s. "
#         f"Last status: {last!r}"
#     )
