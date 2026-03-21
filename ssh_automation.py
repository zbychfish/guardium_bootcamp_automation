#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Automatyzacja SSH - wykonywanie polecen na zdalnej maszynie
Autor: Bob
Data: 2026-03-20
"""

import paramiko
import sys
from typing import List, Dict, Optional, Any


class SSHExecutor:
    """Klasa do wykonywania poleceń przez SSH"""
    
    def __init__(self, host: str, username: str, password: str, port: int = 22):
        """
        Inicjalizacja połączenia SSH
        
        Args:
            host: Adres IP lub hostname zdalnej maszyny
            username: Nazwa użytkownika
            password: Hasło
            port: Port SSH (domyślnie 22)
        """
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.client = None
        
    def connect(self, timeout: int = 10) -> bool:
        """
        Nawiązanie połączenia SSH
        
        Args:
            timeout: Timeout połączenia w sekundach
            
        Returns:
            True jeśli połączenie udane, False w przeciwnym razie
        """
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            self.client.connect(
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                timeout=timeout,
                look_for_keys=False,
                allow_agent=False
            )
            
            print(f"[OK] Polaczono z {self.host}")
            return True
            
        except paramiko.AuthenticationException:
            print(f"[BLAD] Uwierzytelnianie dla {self.username}@{self.host}")
            return False
        except paramiko.SSHException as e:
            print(f"[BLAD] SSH: {e}")
            return False
        except Exception as e:
            print(f"[BLAD] Polaczenie: {e}")
            return False
    
    def execute_command(self, command: str, timeout: int = 30) -> Dict[str, Any]:
        """
        Wykonanie polecenia na zdalnej maszynie
        
        Args:
            command: Polecenie do wykonania
            timeout: Timeout wykonania w sekundach
            
        Returns:
            Słownik z wynikami:
            {
                'success': bool,
                'output': List[str],  # Lista linii wyjścia
                'error': str,
                'exit_code': int
            }
        """
        if not self.client:
            return {
                'success': False,
                'output': [],
                'error': 'Brak połączenia SSH',
                'exit_code': -1
            }
        
        try:
            stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)
            
            # Odczyt wyjścia jako lista linii
            output_lines = stdout.read().decode('utf-8').splitlines()
            error_output = stderr.read().decode('utf-8').strip()
            exit_code = stdout.channel.recv_exit_status()
            
            success = exit_code == 0
            
            if success:
                print(f"[OK] Polecenie wykonane: {command}")
            else:
                print(f"[BLAD] Polecenie zakonczono z kodem {exit_code}: {command}")
            
            return {
                'success': success,
                'output': output_lines,
                'error': error_output,
                'exit_code': exit_code
            }
            
        except paramiko.SSHException as e:
            return {
                'success': False,
                'output': [],
                'error': f'Błąd SSH: {str(e)}',
                'exit_code': -1
            }
        except Exception as e:
            return {
                'success': False,
                'output': [],
                'error': f'Błąd wykonania: {str(e)}',
                'exit_code': -1
            }
    
    def execute_commands(self, commands: List[str]) -> List[Dict[str, Any]]:
        """
        Wykonanie wielu poleceń
        
        Args:
            commands: Lista poleceń do wykonania
            
        Returns:
            Lista wyników dla każdego polecenia
        """
        results = []
        for command in commands:
            result = self.execute_command(command)
            results.append(result)
        return results
    
    def disconnect(self):
        """Zamkniecie polaczenia SSH"""
        if self.client:
            self.client.close()
            print(f"[OK] Rozlaczono z {self.host}")
            self.client = None


def main():
    """Przykład użycia"""
    
    # Parametry połączenia
    HOST = "10.10.9.50"  # Zmień na swój adres IP
    USERNAME = "admin"    # Zmień na swoją nazwę użytkownika
    PASSWORD = "haslo"    # Zmień na swoje hasło
    
    # Polecenia do wykonania
    COMMANDS = [
        "whoami",
        "pwd",
        "ls -la",
        "date"
    ]
    
    # Utworzenie instancji executora
    executor = SSHExecutor(HOST, USERNAME, PASSWORD)
    
    try:
        # Połączenie
        if not executor.connect():
            print("Nie udało się połączyć z serwerem")
            sys.exit(1)
        
        # Wykonanie pojedynczego polecenia
        print("\n=== Wykonanie pojedynczego polecenia ===")
        result = executor.execute_command("hostname")
        print(f"Wyjście: {result['output']}")
        print(f"Sukces: {result['success']}")
        print(f"Kod wyjścia: {result['exit_code']}")
        
        # Wykonanie wielu poleceń
        print("\n=== Wykonanie wielu poleceń ===")
        results = executor.execute_commands(COMMANDS)
        
        for i, result in enumerate(results):
            print(f"\nPolecenie {i+1}: {COMMANDS[i]}")
            print(f"Sukces: {result['success']}")
            print(f"Wyjście ({len(result['output'])} linii):")
            for line in result['output']:
                print(f"  {line}")
            if result['error']:
                print(f"Błąd: {result['error']}")
        
    except KeyboardInterrupt:
        print("\n\nPrzerwano przez użytkownika")
    except Exception as e:
        print(f"\n✗ Nieoczekiwany błąd: {e}")
    finally:
        # Zawsze rozłącz
        executor.disconnect()


if __name__ == "__main__":
    main()

# Made with Bob
