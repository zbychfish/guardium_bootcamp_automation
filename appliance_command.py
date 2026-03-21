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
        echo: bool = False
    ) -> str:
        """Czyta output do momentu dopasowania regex"""
        if not self.channel:
            raise RuntimeError("No channel available")
        
        buf = ""
        deadline = time.time() + self.timeout
        
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
        
        raise TimeoutError(f"Timeout waiting for: {regex.pattern}")
    
    def execute_command_with_confirmation(
        self,
        command: str,
        confirmation_pattern: str = r"\(y/n\)",
        response: str = "y",
        timeout_confirmation: int = 10
    ) -> str:
        """
        Wykonuje polecenie, które wymaga interaktywnego potwierdzenia.
        
        Args:
            command: Polecenie do wykonania
            confirmation_pattern: Regex pattern dla pytania o potwierdzenie
            response: Odpowiedź do wysłania (np. 'y', 'n', 'yes', 'no')
            timeout_confirmation: Timeout dla oczekiwania na pytanie (sekundy)
        
        Returns:
            Pełny output polecenia
        """
        if not self.channel:
            raise RuntimeError("Not connected")
        
        # Flush buffer
        time.sleep(0.05)
        while self.channel.recv_ready():
            self.channel.recv(65535)
        
        # Send command
        self.channel.send((command + "\r\n").encode())
        
        # Wait for confirmation prompt
        confirmation_re = re.compile(confirmation_pattern)
        buf = ""
        deadline = time.time() + timeout_confirmation
        
        while time.time() < deadline:
            if self.channel.recv_ready():
                chunk = self.channel.recv(65535).decode(errors="replace")
                buf += chunk
            
            buf_for_match = strip_ansi(buf) if self.strip_ansi_flag else buf
            if confirmation_re.search(buf_for_match):
                # Found confirmation prompt - wait a bit for system to be ready
                time.sleep(0.3)
                
                # Send response
                if self.debug:
                    print(f"[DEBUG] Confirmation prompt detected, sending: {response}", file=sys.stderr)
                
                self.channel.send(response.encode())
                time.sleep(0.1)
                self.channel.send(b"\n")
                time.sleep(0.1)
                break
            
            if self.channel.closed:
                raise RuntimeError("Channel closed while waiting for confirmation")
            
            time.sleep(0.05)
        else:
            raise TimeoutError(f"Timeout waiting for confirmation pattern: {confirmation_pattern}")
        
        # Now wait for the system prompt to return
        raw = self._read_until_regex(self.prompt_re, echo=False)
        
        # Combine all output
        full_output = buf + raw
        
        # Clean output
        working = strip_ansi(full_output) if self.strip_ansi_flag else full_output
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
            # Skip empty lines and prompt lines
            if not stripped:
                continue
            if self.prompt_re.search(stripped):
                continue
            filtered_lines.append(line)
        
        return "\n".join(filtered_lines)
    
    def execute_command(self, command: str) -> str:
        """Wykonuje pojedyncze polecenie i zwraca output"""
        if not self.channel:
            raise RuntimeError("Not connected")
        
        # Flush buffer
        time.sleep(0.05)
        while self.channel.recv_ready():
            self.channel.recv(65535)
        
        # Send command
        self.channel.send((command + "\r\n").encode())
        
        # Read until prompt
        raw = self._read_until_regex(self.prompt_re, echo=False)
        
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
