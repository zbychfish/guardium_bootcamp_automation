#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Appliance Command - klasa do wykonywania poleceń na urządzeniach CLI przez SSH
"""

import re
import sys
import time
import socket
from typing import List, Optional, Tuple

import paramiko


ANSI_RE = re.compile(r"\x1B\[[0-9;?]*[ -/]*[@-~]")


def strip_ansi(s: str) -> str:
    """Usuwa sekwencje ANSI z tekstu"""
    return ANSI_RE.sub("", s)


def _find_last_prompt_span(text: str, prompt_re: re.Pattern) -> Optional[Tuple[int, int]]:
    """Zwraca (start, end) ostatniego dopasowania promptu"""
    last = None
    for m in prompt_re.finditer(text):
        last = (m.start(), m.end())
    return last



def change_password_as_root(
    host: str,
    root_password: str,
    target_user: str,
    new_password: str,
    port: int = 22,
    timeout: int = 10,
) -> bool:
    """
    Loguje się jako root przez SSH (hasłem) i zmienia hasło target_user.
    Zwraca True jeśli OK, False jeśli błąd.
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

        # chpasswd czyta z stdin: user:new_password
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
    Przesyła plik przez SCP jako root używając sshpass + scp.
    
    Args:
        host: Adres IP/hostname
        root_password: Hasło root
        local_path: Ścieżka do lokalnego pliku (dla 'put') lub zdalnego (dla 'get')
        remote_path: Ścieżka docelowa na serwerze (dla 'put') lub lokalna (dla 'get')
        port: Port SSH (domyślnie 22)
        timeout: Timeout w sekundach
        direction: Kierunek transferu - 'put' (upload) lub 'get' (download)
    
    Returns:
        True jeśli sukces, False w przypadku błędu
    """
    import subprocess
    
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


class ApplianceCommand:
    """Klasa do wykonywania poleceń na urządzeniach CLI przez SSH"""
    
    def __init__(
        self,
        host: str,
        user: str,
        password: str,
        prompt_regex: str,
        port: int = 22,
        timeout: int = 60,
        initial_pattern: Optional[str] = None,
        logout_command: str = "quit",
        strip_ansi: bool = False,
        debug: bool = False
    ):
        self.host = host
        self.user = user
        self.password = password
        self.port = port
        self.timeout = timeout
        self.logout_command = logout_command
        self.strip_ansi_flag = strip_ansi
        self.debug = debug
        
        self.prompt_re = re.compile(prompt_regex)
        self.initial_re = re.compile(initial_pattern) if initial_pattern else None
        self.error_re = re.compile(r"^(ERROR:|Error:)", re.MULTILINE)
        
        self.client: Optional[paramiko.SSHClient] = None
        self.channel: Optional[paramiko.Channel] = None
    
    def connect(self) -> bool:
        """Nawiązuje połączenie SSH i otwiera shell"""
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            self.client.connect(
                hostname=self.host,
                port=self.port,
                username=self.user,
                password=self.password,
                look_for_keys=False,
                allow_agent=False,
                timeout=15,
                banner_timeout=15,
                auth_timeout=15,
                compress=True,
            )
            
            self.channel = self.client.invoke_shell(term="xterm", width=200, height=40)
            time.sleep(0.2)
            
            # Nudge prompt
            for _ in range(2):
                self.channel.send(b"\r")
                time.sleep(0.1)
                self.channel.send(b"\n")
                time.sleep(0.1)
            
            # Wait for initial pattern
            if self.initial_re:
                self._read_until_regex(self.initial_re, echo=False)
            
            # Wait for prompt
            self._read_until_regex(self.prompt_re, echo=False)
            
            return True
            
        except Exception as e:
            if self.debug:
                print(f"[ERROR] Connection failed: {e}", file=sys.stderr)
            return False
    
    def _read_until_regex(
        self,
        regex: re.Pattern,
        echo: bool = False,
        timeout: Optional[int] = None
    ) -> str:
        """Czyta output do momentu dopasowania regex"""
        if not self.channel:
            raise RuntimeError("No channel available")
        
        cmd_timeout = timeout if timeout is not None else self.timeout
        buf = ""
        deadline = time.time() + cmd_timeout
        
        while time.time() < deadline:
            if self.channel.recv_ready():
                chunk = self.channel.recv(65535).decode(errors="replace")
                buf += chunk
                if echo:
                    out = strip_ansi(chunk) if self.strip_ansi_flag else chunk
                    sys.stdout.write(out)
                    sys.stdout.flush()
            
            buf_for_match = strip_ansi(buf) if self.strip_ansi_flag else buf
            if regex.search(buf_for_match):
                return buf
            
            if self.channel.closed:
                break
            
            time.sleep(0.05)
        
        raise TimeoutError(f"Timeout waiting for: {regex.pattern} (timeout: {cmd_timeout}s)")
    
    def execute_command_with_confirmation(
        self,
        command: str,
        confirmation_pattern: str = r"Do you want to proceed\?\s*\(y/n\)\s*",
        response: str = "y",
        confirm_idle: float = 0.2
    ) -> str:
        """
        Wykonuje polecenie, które wymaga interaktywnego potwierdzenia.
        
        Args:
            command: Polecenie do wykonania
            confirmation_pattern: Regex pattern dla pytania o potwierdzenie
            response: Odpowiedź do wysłania (np. 'y', 'n')
            confirm_idle: Czas oczekiwania na idle przed wysłaniem odpowiedzi (sekundy)
        
        Returns:
            Pełny output polecenia
        """
        if not self.channel:
            raise RuntimeError("Not connected")
        
        # Flush buffer
        time.sleep(0.03)
        while self.channel.recv_ready():
            self.channel.recv(65535)
        
        # Send command with CR only (no LF)
        self.channel.send((command + "\r").encode())
        
        confirmation_re = re.compile(confirmation_pattern)
        buf = ""
        deadline = time.time() + self.timeout
        confirmed = False
        
        while time.time() < deadline:
            if self.channel.recv_ready():
                chunk = self.channel.recv(65535).decode(errors="replace")
                buf += chunk
            
            buf_for_match = strip_ansi(buf) if self.strip_ansi_flag else buf
            
            # Handle confirmation once when detected
            if (not confirmed) and confirmation_re.search(buf_for_match):
                if self.debug:
                    print(f"[DEBUG] Confirmation detected, waiting idle {confirm_idle}s then sending '{response}'", file=sys.stderr)
                
                # Wait until channel is idle
                idle_deadline = time.time() + confirm_idle
                while time.time() < deadline:
                    if self.channel.recv_ready():
                        chunk = self.channel.recv(65535).decode(errors="replace")
                        buf += chunk
                        idle_deadline = time.time() + confirm_idle
                    if time.time() >= idle_deadline:
                        break
                    time.sleep(0.01)
                
                # Send response with CR only
                self.channel.send((response + "\r").encode())
                confirmed = True
                time.sleep(0.02)
            
            # Check if prompt returned
            if self.prompt_re.search(buf_for_match):
                if self.debug:
                    print(f"[DEBUG] Prompt detected after command", file=sys.stderr)
                break
            
            if self.channel.closed:
                raise RuntimeError("Channel closed")
            
            time.sleep(0.005)
        else:
            raise TimeoutError(f"Timeout waiting for prompt: {self.prompt_re.pattern}")
        
        # Clean output
        working = strip_ansi(buf) if self.strip_ansi_flag else buf
        last_span = _find_last_prompt_span(working, self.prompt_re)
        output_region = working[: last_span[0]] if last_span else working
        
        lines = output_region.splitlines()
        
        # Remove empty lines and command echo
        while lines and not lines[0].strip():
            lines.pop(0)
        if lines and lines[0].strip() == command.strip():
            lines = lines[1:]
        
        return "\n".join(lines).strip()
    
    def execute_restart_with_check(
        self,
        command: str = "restart system",
        confirmation_pattern: str = r"Are you sure you want to restart the system\s*\(y/n\)\?",
        busy_pattern: str = r"MYSQL is busy updating the database",
        confirm_idle: float = 0.2
    ) -> str:
        """
        Wykonuje restart systemu z warunkiem - sprawdza czy MySQL jest busy.
        
        Args:
            command: Polecenie restartu
            confirmation_pattern: Regex pattern dla pytania o potwierdzenie
            busy_pattern: Regex pattern dla komunikatu o busy MySQL
            confirm_idle: Czas oczekiwania na idle przed wysłaniem odpowiedzi
        
        Returns:
            Komunikat o wyniku operacji
        """
        if not self.channel:
            raise RuntimeError("Not connected")
        
        # Flush buffer
        time.sleep(0.03)
        while self.channel.recv_ready():
            self.channel.recv(65535)
        
        # Send command with CR only
        self.channel.send((command + "\r").encode())
        
        confirmation_re = re.compile(confirmation_pattern)
        busy_re = re.compile(busy_pattern)
        buf = ""
        deadline = time.time() + self.timeout
        confirmed = False
        
        while time.time() < deadline:
            if self.channel.recv_ready():
                chunk = self.channel.recv(65535).decode(errors="replace")
                buf += chunk
            
            buf_for_match = strip_ansi(buf) if self.strip_ansi_flag else buf
            
            # Handle confirmation once when detected
            if (not confirmed) and confirmation_re.search(buf_for_match):
                # Wait until channel is idle
                idle_deadline = time.time() + confirm_idle
                while time.time() < deadline:
                    if self.channel.recv_ready():
                        chunk = self.channel.recv(65535).decode(errors="replace")
                        buf += chunk
                        idle_deadline = time.time() + confirm_idle
                    if time.time() >= idle_deadline:
                        break
                    time.sleep(0.01)
                
                buf_for_match = strip_ansi(buf) if self.strip_ansi_flag else buf
                
                # Check if MySQL is busy
                if busy_re.search(buf_for_match):
                    if self.debug:
                        print("[DEBUG] MySQL busy detected, sending 'n'", file=sys.stderr)
                    # Send 'n' to reject restart
                    self.channel.send(b"n\r")
                    confirmed = True
                    time.sleep(0.02)
                    
                    # Wait for prompt
                    try:
                        self._read_until_regex(self.prompt_re, echo=False)
                    except TimeoutError:
                        pass
                    
                    return "Restart odrzucony - MySQL is busy updating the database"
                else:
                    if self.debug:
                        print("[DEBUG] No busy detected, sending 'y' - system will restart", file=sys.stderr)
                    # Send 'y' to confirm restart
                    self.channel.send(b"y\r")
                    confirmed = True
                    time.sleep(0.5)
                    
                    # System will restart - connection will be lost
                    # Try to read any remaining output
                    try:
                        remaining = ""
                        end_time = time.time() + 5
                        while time.time() < end_time:
                            if self.channel.recv_ready():
                                chunk = self.channel.recv(65535).decode(errors="replace")
                                remaining += chunk
                            if self.channel.closed:
                                break
                            time.sleep(0.1)
                    except Exception:
                        pass
                    
                    return "System is restarting - connection broken"
            
            if self.channel.closed:
                return "System is restarting - connection broken"
            
            time.sleep(0.005)
        
        raise TimeoutError(f"Timeout waiting for confirmation pattern: {confirmation_pattern}")
    
    def execute_command(self, command: str, timeout: Optional[int] = None) -> str:
        """
        Wykonuje pojedyncze polecenie i zwraca output.
        
        Args:
            command: Polecenie do wykonania
            timeout: Opcjonalny timeout w sekundach (jeśli None, używa self.timeout)
        
        Returns:
            Output polecenia
        """
        if not self.channel:
            raise RuntimeError("Not connected")
        
        # Flush buffer
        time.sleep(0.05)
        while self.channel.recv_ready():
            self.channel.recv(65535)
        
        # Send command
        self.channel.send((command + "\r\n").encode())
        
        # Read until prompt with optional timeout
        raw = self._read_until_regex(self.prompt_re, echo=False, timeout=timeout)
        
        # Clean output
        working = strip_ansi(raw) if self.strip_ansi_flag else raw
        last_span = _find_last_prompt_span(working, self.prompt_re)
        output_region = working[: last_span[0]] if last_span else working
        
        lines = output_region.splitlines()
        
        # Remove empty lines and command echo
        while lines and not lines[0].strip():
            lines.pop(0)
        
        if lines:
            first = lines[0].rstrip("\r\n")
            if first.strip() == command.strip():
                lines = lines[1:]
        
        # Filter out unwanted lines
        filtered_lines = []
        for line in lines:
            stripped = line.strip()
            # Skip empty lines, "ok", and prompt lines
            if not stripped:
                continue
            if stripped == "ok":
                continue
            if self.prompt_re.search(stripped):
                continue
            filtered_lines.append(line)
        
        return "\n".join(filtered_lines)
    
    def execute_commands(self, commands: List[str]) -> List[str]:
        """Wykonuje listę poleceń i zwraca listę outputów"""
        results = []
        for cmd in commands:
            output = self.execute_command(cmd)
            results.append(output)
        return results
    
    def execute_patch_install(
        self,
        command: str = "store system patch install sys",
        patch_selection: str = "2",
        reinstall_answer: str = "y",
        live_output: bool = True,
        timeout: Optional[int] = None
    ) -> str:
        """
        Wykonuje instalację patcha z obsługą dwóch pytań:
        1. "Please choose patches to install (1-2, or multiple numbers separated by ",", or q to quit):"
        2. "Do you really want to install again (yes or no)?" (opcjonalne)
        
        Args:
            command: Polecenie instalacji patcha (domyślnie "store system patch install sys")
            patch_selection: Wybór patchy (np. "1-2", "1,3", "1", "2")
            reinstall_answer: Odpowiedź na pytanie o reinstalację ("y", "yes", "n", "no")
            live_output: Czy wyświetlać output na bieżąco (domyślnie True)
            timeout: Opcjonalny timeout w sekundach (jeśli None, używa self.timeout)
        
        Returns:
            Output z instalacji patcha
        """
        if not self.channel:
            raise RuntimeError("Not connected")
        
        use_timeout = timeout if timeout is not None else self.timeout
        
        # Set channel timeout for non-blocking recv
        original_timeout = self.channel.gettimeout()
        self.channel.settimeout(0.1)
        
        try:
            # Flush buffer
            time.sleep(0.03)
            while self.channel.recv_ready():
                self.channel.recv(65535)
            
            # Send command with CR only
            self.channel.send((command + "\r").encode())
            
            buf = ""
            last_activity = time.time()
            deadline = time.time() + use_timeout
            patch_selected = False
            reinstall_answered = False
            
            while time.time() < deadline:
                try:
                    chunk = self.channel.recv(65535).decode(errors="replace")
                    if chunk:
                        buf += chunk
                        last_activity = time.time()
                        
                        # Print new content live immediately
                        if live_output:
                            display_chunk = strip_ansi(chunk) if self.strip_ansi_flag else chunk
                            print(display_chunk, end='', flush=True)
                            sys.stdout.flush()
                        
                        buf_clean = strip_ansi(buf) if self.strip_ansi_flag else buf
                        
                        # Sprawdź czy jest pytanie o wybór patcha
                        if not patch_selected and ("Please choose patches" in buf_clean or "or q to quit" in buf_clean):
                            # Sprawdź czy linia kończy się dwukropkiem (pytanie jest kompletne)
                            last_line = buf_clean.strip().split('\n')[-1]
                            if last_line.endswith(':'):
                                # Poczekaj jeszcze chwilę aby upewnić się że to koniec pytania
                                time.sleep(1.0)
                                # Sprawdź czy nie ma więcej danych
                                try:
                                    extra = self.channel.recv(65535).decode(errors="replace")
                                    if extra:
                                        buf += extra
                                        if live_output:
                                            display_extra = strip_ansi(extra) if self.strip_ansi_flag else extra
                                            print(display_extra, end='', flush=True)
                                except:
                                    pass
                                
                                if live_output:
                                    print(f"\n[Sending patch selection: {patch_selection}]", flush=True)
                                    sys.stdout.flush()
                                
                                self.channel.send((patch_selection + "\r").encode())
                                patch_selected = True
                                last_activity = time.time()
                                time.sleep(0.5)
                        
                        # Sprawdź czy jest pytanie o reinstalację
                        if patch_selected and not reinstall_answered and "Do you really want to install again" in buf_clean:
                            # Sprawdź czy pytanie jest kompletne - szukaj "(yes or no)?"
                            if "(yes or no)?" in buf_clean:
                                # Poczekaj jeszcze chwilę aby upewnić się że to koniec pytania
                                time.sleep(1.0)
                                # Sprawdź czy nie ma więcej danych
                                try:
                                    extra = self.channel.recv(65535).decode(errors="replace")
                                    if extra:
                                        buf += extra
                                        if live_output:
                                            display_extra = strip_ansi(extra) if self.strip_ansi_flag else extra
                                            print(display_extra, end='', flush=True)
                                except:
                                    pass
                                
                                if live_output:
                                    print(f"\n[Sending reinstall answer: {reinstall_answer}]", flush=True)
                                    sys.stdout.flush()
                                
                                self.channel.send((reinstall_answer + "\r").encode())
                                reinstall_answered = True
                                last_activity = time.time()
                                time.sleep(0.5)
                        
                        # Sprawdź czy wróciliśmy do promptu
                        if patch_selected and self.prompt_re.search(buf_clean):
                            # Poczekaj chwilę na ewentualny dodatkowy output
                            time.sleep(1)
                            try:
                                while self.channel.recv_ready():
                                    chunk = self.channel.recv(65535).decode(errors="replace")
                                    if chunk:
                                        buf += chunk
                                        if live_output:
                                            display_chunk = strip_ansi(chunk) if self.strip_ansi_flag else chunk
                                            print(display_chunk, end='', flush=True)
                            except:
                                pass
                            
                            if live_output:
                                print()  # New line at the end
                            
                            # Clean and return output
                            working = strip_ansi(buf) if self.strip_ansi_flag else buf
                            last_span = _find_last_prompt_span(working, self.prompt_re)
                            output_region = working[: last_span[0]] if last_span else working
                            
                            lines = output_region.splitlines()
                            
                            # Remove empty lines and command echo
                            while lines and not lines[0].strip():
                                lines.pop(0)
                            if lines and lines[0].strip() == command.strip():
                                lines = lines[1:]
                            
                            return "\n".join(lines).strip()
                            
                except socket.timeout:
                    # Timeout jest normalny - po prostu nie ma danych
                    # Sprawdź czy nie minęło zbyt dużo czasu bez aktywności
                    if time.time() - last_activity > 300:  # 5 minut bez aktywności
                        raise TimeoutError("No activity for 5 minutes")
                    time.sleep(0.1)
                
                # Sprawdź czy nadal połączeni
                if self.channel.closed:
                    raise RuntimeError("Channel closed")
            
            raise TimeoutError(f"Timeout waiting for patch install prompts")
        
        finally:
            # Restore original timeout
            if original_timeout is not None:
                self.channel.settimeout(original_timeout)
    
    def generate_external_stap_csr(
        self,
        alias: str,
        common_name: str,
        san1: str,
        organizational_unit: str = "Training",
        organization: str = "Demo",
        locality: str = "",
        state: str = "",
        country: str = "PL",
        email: str = "",
        encryption_algorithm: str = "2",
        keysize: str = "2",
        san2: str = "",
        timeout_sec: int = 180,
        prompt_timeout_sec: int = 20
    ) -> Tuple[str, str, str]:
        """
        Generuje CSR dla Guardium External S-TAP używając istniejącego połączenia.
        
        Args:
            alias: Alias CSR (np. mysql-etap)
            common_name: CN certyfikatu
            san1: Pierwsza wartość SAN
            organizational_unit: Jednostka organizacyjna (domyślnie "Training")
            organization: Organizacja (domyślnie "Demo")
            locality: Miasto/lokalizacja (domyślnie puste - skip)
            state: Stan/prowincja (domyślnie puste - skip)
            country: Dwuliterowy kod kraju (domyślnie "PL")
            email: Adres email (domyślnie puste - skip)
            encryption_algorithm: Algorytm szyfrowania (domyślnie "2")
            keysize: Rozmiar klucza (domyślnie "2")
            san2: Druga wartość SAN (domyślnie puste)
            timeout_sec: Globalny timeout w sekundach (domyślnie 180)
            prompt_timeout_sec: Timeout dla pojedynczego promptu (domyślnie 20)
        
        Returns:
            Tuple[str, str, str]: (csr_pem, deployment_token, line_above_token)
        
        Raises:
            RuntimeError: Jeśli nie połączono lub wystąpił błąd
            TimeoutError: Jeśli przekroczono timeout
        """
        if not self.channel:
            raise RuntimeError("Not connected")
        
        # Type assertion dla type checkera
        assert self.channel is not None
        
        # Definicja kroków wizarda - dokładnie jak w csr.py
        steps = [
            ("alias", "Please enter the hostname as the alias", alias),
            ("CN", "What is the Common Name", common_name),
            ("OU", "organizational unit", organizational_unit),
            ("OU-confirm", "another organizational unit", "n"),
            ("O", "organization (O=", organization),
            ("L", "city or locality", locality),
            ("L-skip", "skip 'L'", "y" if not locality else "n"),
            ("ST", "state or province", state),
            ("ST-skip", "skip 'ST'", "y" if not state else "n"),
            ("C", "two-letter country code", country),
            ("email", "email address", email),
            ("email-skip", "skip 'emailAddress'", "y" if not email else "n"),
            ("crypto", "encryption algorithm", encryption_algorithm),
            ("keysize", "keysize", keysize),
            ("SAN1", "What is the name of SAN #1", san1),
            ("SAN2", "What is the name of SAN #2", san2),
        ]
        
        if self.debug:
            print(f"[DEBUG] Starting External S-TAP CSR generation", file=sys.stderr)
            print(f"[DEBUG] Alias={alias}, CN={common_name}, SAN1={san1}", file=sys.stderr)
        
        # Funkcja pomocnicza do odczytu outputu
        def read_output() -> str:
            assert self.channel is not None
            buf = ""
            while self.channel.recv_ready():
                chunk = self.channel.recv(65535).decode("utf-8", errors="ignore")
                if self.debug:
                    print(f"[DEBUG] RECV <<< {chunk}", file=sys.stderr)
                buf += chunk
            return buf
        
        # Funkcja pomocnicza do wysyłania
        def send(text: str) -> None:
            assert self.channel is not None
            if self.debug:
                print(f"[DEBUG] SEND >>> {text!r}", file=sys.stderr)
            self.channel.send((text + "\n").encode("utf-8"))
        
        # Wyślij komendę
        send("create csr external_stap")
        if self.debug:
            print("[DEBUG] Command sent: create csr external_stap", file=sys.stderr)
        
        full_output = ""
        step_idx = 0
        start_time = time.time()
        last_activity = time.time()
        
        # Główna pętla - dokładnie jak w csr.py
        while True:
            if time.time() - start_time > timeout_sec:
                raise TimeoutError("GLOBAL TIMEOUT: CSR generation took too long")
            
            out = read_output()
            if out:
                full_output += out
                last_activity = time.time()
            
            # CSR już istnieje → wybór opcji [2]
            if (
                "CSR for this alias already exists" in full_output
                or "How would you like to proceed?" in full_output
            ):
                if self.debug:
                    print("[DEBUG] Existing CSR detected – selecting option [2]", file=sys.stderr)
                send("2")
                full_output = ""
                continue
            
            # Koniec – token
            if "To deploy the external_stap, use the following token:" in full_output:
                if self.debug:
                    print("[DEBUG] Wizard completed – token detected", file=sys.stderr)
                break
            
            # Standardowy flow
            if step_idx < len(steps):
                step_name, expected_prompt, answer = steps[step_idx]
                
                if expected_prompt in full_output:
                    if self.debug:
                        print(
                            f"[DEBUG] Step [{step_idx + 1}/{len(steps)}] "
                            f"{step_name} → sending "
                            f"{'ENTER' if answer == '' else answer}",
                            file=sys.stderr
                        )
                    send(answer)
                    step_idx += 1
                    full_output = ""
                    continue
                
                if time.time() - last_activity > prompt_timeout_sec:
                    raise TimeoutError(
                        f"PROMPT TIMEOUT at step '{step_name}', "
                        f"waiting for: '{expected_prompt}'"
                    )
            
            time.sleep(0.3)
        
        if self.debug:
            print("[DEBUG] CSR generation completed", file=sys.stderr)
        
        # Ekstrakcja CSR
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
        
        # Ekstrakcja tokenu i linii powyżej
        lines = full_output.splitlines()
        token: Optional[str] = None
        line_above: Optional[str] = None
        
        for i, line in enumerate(lines):
            if "To deploy the external_stap, use the following token:" in line:
                token = line.split(":")[-1].strip()
                if i > 0:
                    line_above = lines[i - 1].strip()
                break
        
        if token is None:
            raise RuntimeError("Deployment token not found")
        if line_above is None:
            raise RuntimeError("Line above token not found")
        
        if self.debug:
            print(f"[DEBUG] Deployment token extracted: {token}", file=sys.stderr)
        
        return csr, token, line_above
    
    def import_external_stap_ca_certificate(
        self,
        alias: str,
        ca_cert: str,
        timeout_sec: int = 120,
        prompt_timeout_sec: int = 20,
        ignore_time_parse_error: bool = True
    ) -> None:
        """
        Importuje certyfikat CA do Guardium External S-TAP keystore używając istniejącego połączenia.
        
        Flow:
          - store certificate keystore_external_stap
          - alias
          - wklejenie certyfikatu PEM
          - ENTER
          - CTRL+D
          - SUCCESS + opcjonalny błąd 'Error parsing time' → ignorowany
        
        Args:
            alias: Alias dla certyfikatu CA
            ca_cert: Certyfikat CA w formacie PEM (string)
            timeout_sec: Globalny timeout w sekundach (domyślnie 120)
            prompt_timeout_sec: Timeout dla pojedynczego promptu (domyślnie 20)
            ignore_time_parse_error: Czy ignorować błąd "Error parsing time" (domyślnie True)
        
        Raises:
            RuntimeError: Jeśli nie połączono lub wystąpił błąd
            TimeoutError: Jeśli przekroczono timeout
        """
        if not self.channel:
            raise RuntimeError("Not connected")
        
        # Type assertion dla type checkera
        assert self.channel is not None
        
        if self.debug:
            print(f"[DEBUG] Starting External S-TAP CA certificate import", file=sys.stderr)
            print(f"[DEBUG] Alias: {alias}", file=sys.stderr)
        
        # Funkcje pomocnicze
        def send(text: str) -> None:
            assert self.channel is not None
            if self.debug:
                print(f"[DEBUG] SEND >>> {text!r}", file=sys.stderr)
            self.channel.send((text + "\n").encode("utf-8"))
        
        def send_raw(data: str) -> None:
            assert self.channel is not None
            if self.debug:
                print("[DEBUG] SEND >>> (raw certificate data)", file=sys.stderr)
            self.channel.send(data.encode("utf-8"))
        
        def send_ctrl_d() -> None:
            assert self.channel is not None
            if self.debug:
                print("[DEBUG] SEND >>> CTRL+D", file=sys.stderr)
            self.channel.send(b"\x04")
        
        def read_output() -> str:
            assert self.channel is not None
            buf = ""
            while self.channel.recv_ready():
                chunk = self.channel.recv(65535).decode("utf-8", errors="ignore")
                if self.debug:
                    print(f"[DEBUG] RECV <<< {chunk}", file=sys.stderr)
                buf += chunk
            return buf
        
        # Wyślij komendę
        send("store certificate keystore_external_stap")
        if self.debug:
            print("[DEBUG] Command sent: store certificate keystore_external_stap", file=sys.stderr)
        
        full_output = ""
        start_time = time.time()
        last_activity = time.time()
        
        # Główna pętla - dokładnie jak w csr.py
        while True:
            if time.time() - start_time > timeout_sec:
                raise TimeoutError("GLOBAL TIMEOUT during CA certificate import")
            
            out = read_output()
            if out:
                full_output += out
                last_activity = time.time()
            
            # Alias prompt
            if "Please enter the alias associated with the certificate" in full_output:
                if self.debug:
                    print(f"[DEBUG] Sending alias: {alias}", file=sys.stderr)
                send(alias)
                full_output = ""
                continue
            
            # Certificate paste prompt
            if "Please paste your Trusted certificate below" in full_output:
                if self.debug:
                    print("[DEBUG] Pasting CA certificate", file=sys.stderr)
                send_raw(ca_cert.strip() + "\n")
                send("")       # ENTER
                time.sleep(0.5)
                send_ctrl_d()  # CTRL+D
                full_output = ""
                continue
            
            # Success
            if "SUCCESS: Certificate imported successfully" in full_output:
                if self.debug:
                    print("[DEBUG] Certificate imported successfully", file=sys.stderr)
                break
            
            # Optional known error → normal termination
            if (
                ignore_time_parse_error
                and "Error parsing time" in full_output
            ):
                if self.debug:
                    print("[DEBUG] Known 'Error parsing time' detected – treating as success", file=sys.stderr)
                break
            
            if time.time() - last_activity > prompt_timeout_sec:
                raise TimeoutError("PROMPT TIMEOUT during CA certificate import")
    def import_external_stap_certificate(
        self,
        alias_line: str,
        stap_cert: str,
        timeout_sec: int = 180,
        prompt_timeout_sec: int = 30,
        ignore_time_parse_error: bool = True
    ) -> None:
        """
        Importuje certyfikat External S-TAP (end-entity) do Guardium używając istniejącego połączenia.
        
        Flow:
          - store certificate external_stap
          - alias (pełna linia: <alias> proxy_keycert <UUID>)
          - potwierdzenie zgodności z CSR (y)
          - wklejenie certyfikatu PEM
          - ENTER
          - CTRL+D
          - SUCCESS
          - opcjonalny błąd: 'Error parsing time' → ignorowany
        
        Args:
            alias_line: Pełna linia aliasu (np. "mysql-etap proxy_keycert 02717b9d-2a87-11f1-af30-c4df3d41f195")
            stap_cert: Certyfikat External S-TAP w formacie PEM (string)
            timeout_sec: Globalny timeout w sekundach (domyślnie 180)
            prompt_timeout_sec: Timeout dla pojedynczego promptu (domyślnie 30)
            ignore_time_parse_error: Czy ignorować błąd "Error parsing time" (domyślnie True)
        
        Raises:
            RuntimeError: Jeśli nie połączono lub wystąpił błąd
            TimeoutError: Jeśli przekroczono timeout
        """
        if not self.channel:
            raise RuntimeError("Not connected")
        
        # Type assertion dla type checkera
        assert self.channel is not None
        
        if self.debug:
            print(f"[DEBUG] Starting External S-TAP certificate import", file=sys.stderr)
            print(f"[DEBUG] Alias line: {alias_line}", file=sys.stderr)
        
        # Funkcje pomocnicze
        def send(text: str) -> None:
            assert self.channel is not None
            if self.debug:
                print(f"[DEBUG] SEND >>> {text!r}", file=sys.stderr)
            self.channel.send((text + "\n").encode("utf-8"))
        
        def send_raw(data: str) -> None:
            assert self.channel is not None
            if self.debug:
                print("[DEBUG] SEND >>> (raw certificate data)", file=sys.stderr)
            self.channel.send(data.encode("utf-8"))
        
        def send_ctrl_d() -> None:
            assert self.channel is not None
            if self.debug:
                print("[DEBUG] SEND >>> CTRL+D", file=sys.stderr)
            self.channel.send(b"\x04")
        
        def read_output() -> str:
            assert self.channel is not None
            buf = ""
            while self.channel.recv_ready():
                chunk = self.channel.recv(65535).decode("utf-8", errors="ignore")
                if self.debug:
                    print(f"[DEBUG] RECV <<< {chunk}", file=sys.stderr)
                buf += chunk
            return buf
        
        # Wyślij komendę
        send("store certificate external_stap")
        if self.debug:
            print("[DEBUG] Command sent: store certificate external_stap", file=sys.stderr)
        
        full_output = ""
        start_time = time.time()
        last_activity = time.time()
        csr_confirmed = False
        cert_sent = False
        
        # Główna pętla - dokładnie jak w csr.py
        while True:
            if time.time() - start_time > timeout_sec:
                raise TimeoutError("GLOBAL TIMEOUT during External S-TAP cert import")
            
            out = read_output()
            if out:
                full_output += out
                last_activity = time.time()
            
            # Alias prompt
            if "Please enter the alias associated with the certificate" in full_output:
                if self.debug:
                    print("[DEBUG] Sending External S-TAP alias line", file=sys.stderr)
                send(alias_line)
                full_output = ""
                continue
            
            # CSR confirmation
            if (
                not csr_confirmed
                and "Are you importing an External S-TAP certificate" in full_output
            ):
                if self.debug:
                    print("[DEBUG] Confirming certificate corresponds to CSR (y)", file=sys.stderr)
                send("y")
                csr_confirmed = True
                full_output = ""
                continue
            
            # Paste certificate
            if (
                "Please paste your End-Entity certificate below" in full_output
                and not cert_sent
            ):
                if self.debug:
                    print("[DEBUG] Pasting External S-TAP certificate", file=sys.stderr)
                send_raw(stap_cert.strip() + "\n")
                send("")        # ENTER
                time.sleep(0.5)
                send_ctrl_d()   # CTRL+D
                cert_sent = True
                full_output = ""
                continue
            
            # Success
            if "SUCCESS: Certificate imported successfully" in full_output:
                if self.debug:
                    print("[DEBUG] External S-TAP certificate imported successfully", file=sys.stderr)
                break
            
            # Known Guardium bug → treat as success
            if (
                ignore_time_parse_error
                and "Error parsing time" in full_output
            ):
                if self.debug:
                    print("[DEBUG] Known Guardium bug 'Error parsing time' detected – treating as success", file=sys.stderr)
                break
            
            if time.time() - last_activity > prompt_timeout_sec:
                raise TimeoutError("PROMPT TIMEOUT during External S-TAP certificate import")
            
            time.sleep(0.3)
        
        if self.debug:
            print("[DEBUG] External S-TAP cert import completed", file=sys.stderr)
    
            
            time.sleep(0.3)
        
        if self.debug:
            print("[DEBUG] CA import completed successfully", file=sys.stderr)
    
    
    def disconnect(self):
        """Zamyka połączenie"""
        try:
            if self.channel:
                self.channel.send((self.logout_command + "\r\n").encode())
                time.sleep(0.2)
        except Exception:
            pass
        
        try:
            if self.client:
                self.client.close()
        except Exception:
            pass

# Made with Bob

