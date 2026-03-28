import paramiko
import time
import logging
from typing import Optional


def import_external_stap_ca_certificate(
    host: str,
    username: str,
    password: str,
    *,
    alias: str,
    ca_cert: str,
    log_file: str = "external_stap_ca_import.log",
    cli_prompt: str = ">",
    timeout_sec: int = 120,
    prompt_timeout_sec: int = 20,
    ignore_time_parse_error: bool = True,
) -> None:
    """
    Importuje certyfikat CA do Guardium External S-TAP keystore.

    Flow:
      - store certificate keystore_external_stap
      - alias
      - wklejenie certyfikatu PEM
      - ENTER
      - CTRL+D
      - SUCCESS + opcjonalny błąd 'Error parsing time' → ignorowany
    """

    # ------------------------------------------------------------------
    # LOGGING
    # ------------------------------------------------------------------
    logger = logging.getLogger("guardium-ca-import")
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

    logger.info("Starting Guardium External S-TAP CA certificate import")
    logger.debug(f"Target host: {host}")
    logger.debug(f"Alias: {alias}")

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
    # WAIT FOR GUARDIUM PROMPT
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
    # START COMMAND
    # ------------------------------------------------------------------
    send("store certificate keystore_external_stap")
    logger.info("Command sent: store certificate keystore_external_stap")

    full_output = ""
    start_time = time.time()
    last_activity = time.time()

    # ------------------------------------------------------------------
    # MAIN LOOP
    # ------------------------------------------------------------------
    while True:
        if time.time() - start_time > timeout_sec:
            ssh.close()
            raise RuntimeError("GLOBAL TIMEOUT during CA certificate import")

        out = read_output()
        if out:
            full_output += out
            last_activity = time.time()

        # alias prompt
        if "Please enter the alias associated with the certificate" in full_output:
            logger.info(f"Sending alias: {alias}")
            send(alias)
            full_output = ""
            continue

        # certificate paste prompt
        if "Please paste your Trusted certificate below" in full_output:
            logger.info("Pasting CA certificate")
            send_raw(ca_cert.strip() + "\n")
            send("")       # ENTER
            time.sleep(0.5)
            send_ctrl_d()  # CTRL+D
            full_output = ""
            continue

        # success
        if "SUCCESS: Certificate imported successfully" in full_output:
            logger.info("Certificate imported successfully")
            break

        # optional known error → normal termination
        if (
            ignore_time_parse_error
            and "Error parsing time" in full_output
        ):
            logger.warning("Known 'Error parsing time' detected – treating as success")
            break

        if time.time() - last_activity > prompt_timeout_sec:
            ssh.close()
            raise RuntimeError(
                "PROMPT TIMEOUT during CA certificate import"
            )

        time.sleep(0.3)

    ssh.close()
    logger.info("SSH session closed – CA import completed successfully")


with open("/root/gn-trainings/ETAP/ca/ca.pem") as f:
    ca_cert_pem = f.read()

import_external_stap_ca_certificate(
    host="10.10.9.239",
    username="cli",
    password="Guardium123!",
    alias="etapca2",
    ca_cert=ca_cert_pem,
)