import paramiko
import time
import re
import logging
from typing import Tuple


def generate_external_stap_csr(
    host: str,
    username: str,
    password: str,
    log_file: str = "external_stap_csr.log",
    cli_prompt: str = ">",
    timeout_sec: int = 180,
    prompt_timeout_sec: int = 20,
) -> Tuple[str, str, str]:
    """
    Automatycznie generuje CSR dla Guardium External S-TAP.

    Zwraca:
      - csr_pem (str)
      - deployment_token (str)
      - line_above_token (str)

    Rzuca RuntimeError w przypadku timeoutu lub nieoczekiwanego outputu.
    """

    # ------------------------------------------------------------------
    # LOGGING
    # ------------------------------------------------------------------
    logger = logging.getLogger("guardium-csr")
    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s"
    )

    logger.handlers.clear()

    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    logger.info("Starting External S-TAP CSR generation")
    logger.debug(f"Target host: {host}")

    # ------------------------------------------------------------------
    # MASZYNA STANÓW – GŁÓWNE KROKI WIZARDA
    # ------------------------------------------------------------------
    steps = [
        ("alias", "Please enter the hostname as the alias", "mysql-etap"),
        ("CN", "What is the Common Name", "mysqletap.gdemo.com"),
        ("OU", "organizational unit", "Training"),
        ("OU-confirm", "another organizational unit", "n"),
        ("O", "organization (O=", "Demo"),
        ("L", "city or locality", ""),               # ENTER
        ("L-skip", "skip 'L'", "y"),
        ("ST", "state or province", ""),              # ENTER
        ("ST-skip", "skip 'ST'", "y"),
        ("C", "two-letter country code", "PL"),
        ("email", "email address", ""),               # ENTER
        ("email-skip", "skip 'emailAddress'", "y"),
        ("crypto", "encryption algorithm", "2"),
        ("keysize", "keysize", "2"),
        ("SAN1", "What is the name of SAN #1", "coll1.gdemo.com"),
        ("SAN2", "What is the name of SAN #2", ""),   # ENTER
    ]

    # ------------------------------------------------------------------
    # SSH
    # ------------------------------------------------------------------
    logger.info("Opening SSH connection")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=username, password=password)

    chan = ssh.invoke_shell()
    chan.settimeout(2)

    def send(text: str) -> None:
        logger.debug(f"SEND >>> {text!r}")
        chan.send((text + "\n").encode("utf-8"))

    def read_output() -> str:
        buf = ""
        while chan.recv_ready():
            chunk = chan.recv(65535).decode("utf-8", errors="ignore")
            logger.debug(f"RECV <<< {chunk}")
            buf += chunk
        return buf

    # ------------------------------------------------------------------
    # CZEKAJ NA PROMPT GUARDIUM
    # ------------------------------------------------------------------
    logger.info("Waiting for Guardium CLI prompt")

    start_wait = time.time()
    prompt_buffer = ""

    while True:
        if time.time() - start_wait > 60:
            ssh.close()
            raise RuntimeError("Timeout waiting for Guardium CLI prompt")

        if chan.recv_ready():
            chunk = chan.recv(65535).decode("utf-8", errors="ignore")
            logger.debug(f"RECV <<< {chunk}")
            prompt_buffer += chunk

            if cli_prompt in prompt_buffer:
                logger.info("Guardium CLI prompt detected")
                break

        time.sleep(0.3)

    # ------------------------------------------------------------------
    # START KOMENDY
    # ------------------------------------------------------------------
    send("create csr external_stap")
    logger.info("Command sent: create csr external_stap")

    full_output = ""
    step_idx = 0
    start_time = time.time()
    last_activity = time.time()

    # ------------------------------------------------------------------
    # GŁÓWNA PĘTLA MASZYNY STANÓW
    # ------------------------------------------------------------------
    while True:
        if time.time() - start_time > timeout_sec:
            ssh.close()
            raise RuntimeError("GLOBAL TIMEOUT: CSR generation took too long")

        out = read_output()
        if out:
            full_output += out
            last_activity = time.time()

        # --------------------------------------------------------------
        # OBSŁUGA SYTUACJI: CSR JUŻ ISTNIEJE
        # --------------------------------------------------------------
        if (
            "CSR for this alias already exists" in full_output
            or "How would you like to proceed?" in full_output
        ):
            logger.warning(
                "Existing CSR detected – selecting option [2] Create new CSR"
            )
            send("2")
            full_output = ""
            continue

        # --------------------------------------------------------------
        # ZAKOŃCZENIE – TOKEN
        # --------------------------------------------------------------
        if "To deploy the external_stap, use the following token:" in full_output:
            logger.info("Wizard finished – deployment token detected")
            break

        # --------------------------------------------------------------
        # STANDARDOWE KROKI WIZARDA
        # --------------------------------------------------------------
        if step_idx < len(steps):
            step_name, expected_prompt, answer = steps[step_idx]

            if expected_prompt in full_output:
                logger.info(
                    f"Step [{step_idx + 1}/{len(steps)}] "
                    f"{step_name} → sending "
                    f"{'ENTER' if answer == '' else answer}"
                )
                send(answer)
                step_idx += 1
                full_output = ""
                continue

            if time.time() - last_activity > prompt_timeout_sec:
                ssh.close()
                raise RuntimeError(
                    f"PROMPT TIMEOUT at step '{step_name}', "
                    f"waiting for: '{expected_prompt}'"
                )

        time.sleep(0.3)

    ssh.close()
    logger.info("SSH session closed")

    # ------------------------------------------------------------------
    # PARSOWANIE CSR
    # ------------------------------------------------------------------
    csr_match = re.search(
        r"-----BEGIN NEW CERTIFICATE REQUEST-----(.*?)-----END NEW CERTIFICATE REQUEST-----",
        full_output,
        re.S,
    )
    if not csr_match:
        raise RuntimeError("CSR not found in output")

    csr = (
        "-----BEGIN NEW CERTIFICATE REQUEST-----"
        + csr_match.group(1)
        + "-----END NEW CERTIFICATE REQUEST-----"
    )

    logger.info("CSR extracted successfully")

    # ------------------------------------------------------------------
    # TOKEN + LINIA POWYŻEJ
    # ------------------------------------------------------------------
    lines = full_output.splitlines()
    token: str | None = None
    line_above: str | None = None

    for i, line in enumerate(lines):
        if "To deploy the external_stap, use the following token:" in line:
            token = line.split(":")[-1].strip()
            if i > 0:
                line_above = lines[i - 1].strip()
            break

    if token is None:
        raise RuntimeError("Deployment token not found")
    if line_above is None:
        raise RuntimeError("Line above token not found – unexpected Guardium output")

    logger.info(f"Deployment token extracted: {token}")

    return csr, token, line_above


generate_external_stap_csr(host="10.10.9.239", username="cli", password="Guardium123!")  