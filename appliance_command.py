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
