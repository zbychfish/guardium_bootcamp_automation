#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Przykłady użycia SSH Automation
"""

from ssh_automation import SSHExecutor


def example_basic():
    """Przyklad 1: Podstawowe uzycie"""
    print("\n" + "="*60)
    print("PRZYKLAD 1: Podstawowe uzycie")
    print("="*60)
    
    # Parametry - ZMIEN NA SWOJE
    HOST = "eu-de.services.cloud.techzone.ibm.com"
    USERNAME = "root"
    PASSWORD = "Guardium123!"
    PORT = 32726  # Zmien jesli SSH dziala na innym porcie (np. 2222)
    
    executor = SSHExecutor(HOST, USERNAME, PASSWORD, PORT)
    
    try:
        if executor.connect():
            # Wykonaj pojedyncze polecenie
            result = executor.execute_command("ps")
            
            print(f"\nPolecenie: who am i")
            print(f"Sukces: {result['success']}")
            print(f"Wyjscie: {result['output']}")
            print(f"Kod wyjscia: {result['exit_code']}")
    finally:
        executor.disconnect()


def example_multiple_commands():
    """Przykład 2: Wiele poleceń"""
    print("\n" + "="*60)
    print("PRZYKŁAD 2: Wykonanie wielu poleceń")
    print("="*60)
    
    HOST = "10.10.9.50"
    USERNAME = "admin"
    PASSWORD = "haslo"
    PORT = 22  # Zmień jeśli SSH działa na innym porcie
    
    executor = SSHExecutor(HOST, USERNAME, PASSWORD, PORT)
    
    try:
        if executor.connect():
            commands = [
                "hostname",
                "date",
                "uptime",
                "df -h"
            ]
            
            results = executor.execute_commands(commands)
            
            for i, result in enumerate(results):
                print(f"\n--- Polecenie {i+1}: {commands[i]} ---")
                if result['success']:
                    for line in result['output']:
                        print(f"  {line}")
                else:
                    print(f"  Błąd: {result['error']}")
    finally:
        executor.disconnect()


def example_cli_application():
    """Przykład 3: Wykonanie CLI aplikacji"""
    print("\n" + "="*60)
    print("PRZYKŁAD 3: CLI aplikacji")
    print("="*60)
    
    HOST = "10.10.9.50"
    USERNAME = "admin"
    PASSWORD = "haslo"
    PORT = 22  # Zmień jeśli SSH działa na innym porcie
    
    # Przykładowe polecenia CLI - dostosuj do swojej aplikacji
    CLI_COMMANDS = [
        "docker ps",                    # Docker
        "podman ps",                    # Podman
        "mc ls myminio",                # MinIO Client
        "kubectl get pods",             # Kubernetes
        "systemctl status nginx",       # Systemd
    ]
    
    executor = SSHExecutor(HOST, USERNAME, PASSWORD, PORT)
    
    try:
        if executor.connect():
            # Wybierz polecenie które jest dostępne w Twoim systemie
            command = CLI_COMMANDS[0]  # Zmień indeks lub użyj własnego polecenia
            
            print(f"\nWykonuję: {command}")
            result = executor.execute_command(command)
            
            if result['success']:
                print("\n✓ Sukces! Wyjście:")
                for line in result['output']:
                    print(f"  {line}")
            else:
                print(f"\n✗ Błąd: {result['error']}")
                print(f"Kod wyjścia: {result['exit_code']}")
    finally:
        executor.disconnect()


def example_with_parameters():
    """Przykład 4: Funkcja z parametrami"""
    print("\n" + "="*60)
    print("PRZYKŁAD 4: Funkcja z parametrami")
    print("="*60)
    
    def execute_remote_command(host: str, username: str, password: str,
                              command: str, port: int = 22) -> list:
        """
        Wykonaj polecenie i zwróć wyjście jako listę
        
        Args:
            host: Adres IP serwera
            username: Nazwa użytkownika
            password: Hasło
            command: Polecenie do wykonania
            port: Port SSH (domyślnie 22)
            
        Returns:
            Lista linii wyjścia lub pusta lista w przypadku błędu
        """
        executor = SSHExecutor(host, username, password, port)
        
        try:
            if not executor.connect():
                print(f"Nie można połączyć się z {host}")
                return []
            
            result = executor.execute_command(command)
            
            if result['success']:
                return result['output']
            else:
                print(f"Błąd wykonania: {result['error']}")
                return []
        finally:
            executor.disconnect()
    
    # Użycie funkcji
    output = execute_remote_command(
        host="10.10.9.50",
        username="admin",
        password="haslo",
        command="ls -la /tmp",
        port=22  # Lub inny port, np. 2222
    )
    
    print(f"\nZwrócono {len(output)} linii:")
    for line in output[:10]:  # Pokaż pierwsze 10 linii
        print(f"  {line}")


def example_error_handling():
    """Przykład 5: Obsługa błędów"""
    print("\n" + "="*60)
    print("PRZYKŁAD 5: Obsługa błędów")
    print("="*60)
    
    HOST = "10.10.9.50"
    USERNAME = "admin"
    PASSWORD = "haslo"
    PORT = 22  # Zmień jeśli SSH działa na innym porcie
    
    executor = SSHExecutor(HOST, USERNAME, PASSWORD, PORT)
    
    try:
        # Próba połączenia
        if not executor.connect(timeout=5):
            print("✗ Nie udało się połączyć")
            return
        
        # Polecenie które może się nie powieść
        result = executor.execute_command("nonexistent-command")
        
        if result['success']:
            print("✓ Polecenie wykonane")
            for line in result['output']:
                print(f"  {line}")
        else:
            print(f"✗ Polecenie nie powiodło się")
            print(f"  Kod wyjścia: {result['exit_code']}")
            print(f"  Błąd: {result['error']}")
            
    except KeyboardInterrupt:
        print("\n\n⚠ Przerwano przez użytkownika")
    except Exception as e:
        print(f"\n✗ Nieoczekiwany błąd: {e}")
    finally:
        executor.disconnect()


def example_interactive():
    """Przykład 6: Interaktywny wybór"""
    print("\n" + "="*60)
    print("PRZYKŁAD 6: Interaktywny wybór polecenia")
    print("="*60)
    
    HOST = "10.10.9.50"
    USERNAME = "admin"
    PASSWORD = "haslo"
    PORT = 22  # Zmień jeśli SSH działa na innym porcie
    
    # Menu poleceń
    commands_menu = {
        "1": ("Sprawdź hostname", "hostname"),
        "2": ("Sprawdź datę", "date"),
        "3": ("Sprawdź użytkownika", "whoami"),
        "4": ("Lista procesów", "ps aux | head -10"),
        "5": ("Użycie dysku", "df -h"),
    }
    
    print("\nDostępne polecenia:")
    for key, (desc, cmd) in commands_menu.items():
        print(f"  {key}. {desc} ({cmd})")
    
    choice = input("\nWybierz polecenie (1-5): ").strip()
    
    if choice not in commands_menu:
        print("Nieprawidłowy wybór")
        return
    
    desc, command = commands_menu[choice]
    
    executor = SSHExecutor(HOST, USERNAME, PASSWORD, PORT)
    
    try:
        if executor.connect():
            print(f"\nWykonuję: {desc}")
            result = executor.execute_command(command)
            
            if result['success']:
                print("\nWynik:")
                for line in result['output']:
                    print(f"  {line}")
            else:
                print(f"\nBłąd: {result['error']}")
    finally:
        executor.disconnect()


if __name__ == "__main__":
    print("\n" + "="*60)
    print("SSH AUTOMATION - PRZYKLADY UZYCIA")
    print("="*60)
    print("\nUWAGA: Przed uruchomieniem zmien parametry HOST, USERNAME, PASSWORD")
    print("       w kazdym przykladzie na swoje dane!")
    
    # Uruchom wszystkie przykłady
    try:
        example_basic()
        #example_multiple_commands()
        #example_cli_application()
        #example_with_parameters()
        #example_error_handling()
        
        # Przykład interaktywny - odkomentuj aby użyć
        # example_interactive()
        
    except Exception as e:
        print(f"\nBlad: {e}")
    
    print("\n" + "="*60)
    print("KONIEC PRZYKLADOW")
    print("="*60)

# Made with Bob
