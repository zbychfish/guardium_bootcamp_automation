import paramiko
import time
import logging
from typing import Optional


def import_external_stap_certificate(
    host: str,
    username: str,
    password: str,
    *,
    alias_line: str,
    stap_cert: str,
    log_file: str = "external_stap_cert_import.log",
    cli_prompt: str = ">",
    timeout_sec: int = 180,
    prompt_timeout_sec: int = 30,
    ignore_time_parse_error: bool = True,
) -> None:
    """
    Importuje certyfikat External S‑TAP (end-entity) do Guardium.

    Flow:
      - store certificate external_stap
      - alias (pełna linia: <alias> proxy_keycert <UUID>)
      - potwierdzenie zgodności z CSR (y)
      - wklejenie certyfikatu PEM
      - ENTER
      - CTRL+D
      - SUCCESS
      - opcjonalny błąd: 'Error parsing time' → ignorowany
    """

    # ------------------------------------------------------------------
    # LOGGING
    # ------------------------------------------------------------------
    logger = logging.getLogger("guardium-stap-cert-import")
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

    logger.info("Starting External S‑TAP certificate import")
    logger.debug(f"Target host: {host}")
    logger.debug(f"Alias line: {alias_line}")

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

    def send_raw(data: str) -> None:
        logger.debug("SEND >>> (raw certificate data)")
        chan.send(data.encode("utf-8"))

    def send_ctrl_d() -> None:
        logger.debug("SEND >>> CTRL+D")
        chan.send(b"\x04")

    def read_output() -> str:
        buf = ""
        while chan.recv_ready():
            chunk = chan.recv(65535).decode("utf-8", errors="ignore")
            logger.debug(f"RECV <<< {chunk}")
            buf += chunk
        return buf

    # ------------------------------------------------------------------
    # WAIT FOR GUARDIUM CLI PROMPT
    # ------------------------------------------------------------------
    logger.info("Waiting for Guardium CLI prompt")

    buffer = ""
    start_wait = time.time()

    while True:
        if time.time() - start_wait > 60:
            ssh.close()
            raise RuntimeError("Timeout waiting for Guardium CLI prompt")

        if chan.recv_ready():
            chunk = chan.recv(65535).decode("utf-8", errors="ignore")
            logger.debug(f"RECV <<< {chunk}")
            buffer += chunk

            if cli_prompt in buffer:
                logger.info("Guardium CLI prompt detected")
                break

        time.sleep(0.3)

    # ------------------------------------------------------------------
    # START COMMAND
    # ------------------------------------------------------------------
    send("store certificate external_stap")
    logger.info("Command sent: store certificate external_stap")

    full_output = ""
    start_time = time.time()
    last_activity = time.time()
    csr_confirmed = False
    cert_sent = False

    # ------------------------------------------------------------------
    # MAIN LOOP
    # ------------------------------------------------------------------
    while True:
        if time.time() - start_time > timeout_sec:
            ssh.close()
            raise RuntimeError("GLOBAL TIMEOUT during External S‑TAP cert import")

        out = read_output()
        if out:
            full_output += out
            last_activity = time.time()

        # alias prompt
        if "Please enter the alias associated with the certificate" in full_output:
            logger.info("Sending External S‑TAP alias line")
            send(alias_line)
            full_output = ""
            continue

        # CSR confirmation
        if (
            not csr_confirmed
            and "Are you importing an External S-TAP certificate" in full_output
        ):
            logger.info("Confirming certificate corresponds to CSR (y)")
            send("y")
            csr_confirmed = True
            full_output = ""
            continue

        # paste certificate
        if (
            "Please paste your End-Entity certificate below" in full_output
            and not cert_sent
        ):
            logger.info("Pasting External S‑TAP certificate")
            send_raw(stap_cert.strip() + "\n")
            send("")        # ENTER
            time.sleep(0.5)
            send_ctrl_d()   # CTRL+D
            cert_sent = True
            full_output = ""
            continue

        # success
        if "SUCCESS: Certificate imported successfully" in full_output:
            logger.info("External S‑TAP certificate imported successfully")
            break

        # known Guardium bug → treat as success
        if (
            ignore_time_parse_error
            and "Error parsing time" in full_output
        ):
            logger.warning(
                "Known Guardium bug 'Error parsing time' detected – treating as success"
            )
            break

        if time.time() - last_activity > prompt_timeout_sec:
            ssh.close()
            raise RuntimeError(
                "PROMPT TIMEOUT during External S‑TAP certificate import"
            )

        time.sleep(0.3)

    ssh.close()
    logger.info("SSH session closed – External S‑TAP cert import completed")

with open("/root/gn-trainings/ETAP/ca/etap.pem") as f:
    etap_cert = f.read()

import_external_stap_certificate(
    host="10.10.9.239",
    username="cli",
    password="Guardium123!",
    alias_line="mysql-etap proxy_keycert 02717b9d-2a87-11f1-af30-c4df3d41f195",
    stap_cert=etap_cert,
)