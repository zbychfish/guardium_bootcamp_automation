# SSH Automation - Szybki Start

## Instalacja

```bash
pip install paramiko
```

## Podstawowe użycie

```python
from ssh_automation import SSHExecutor

# Połączenie z domyślnym portem SSH (22)
executor = SSHExecutor(
    host="10.10.9.50",
    username="admin",
    password="haslo"
)

# Połączenie z niestandardowym portem SSH
executor = SSHExecutor(
    host="10.10.9.50",
    username="admin",
    password="haslo",
    port=2222  # Niestandardowy port
)

# Wykonanie polecenia
if executor.connect():
    result = executor.execute_command("ls -la")
    
    # Wynik jako lista linii
    for line in result['output']:
        print(line)
    
    executor.disconnect()
```

## Przykłady portów SSH

| Scenariusz | Port | Przykład |
|------------|------|----------|
| Standardowy SSH | 22 | `SSHExecutor(host, user, pass, 22)` |
| Niestandardowy SSH | 2222 | `SSHExecutor(host, user, pass, 2222)` |
| SSH przez tunel | 10022 | `SSHExecutor(host, user, pass, 10022)` |
| SSH w kontenerze | 2200 | `SSHExecutor(host, user, pass, 2200)` |

## Kompletny przykład z niestandardowym portem

```python
from ssh_automation import SSHExecutor

def execute_on_custom_port():
    """Wykonaj polecenie na serwerze z niestandardowym portem SSH"""
    
    # Konfiguracja
    HOST = "192.168.1.100"
    USERNAME = "admin"
    PASSWORD = "SecurePass123"
    PORT = 2222  # Niestandardowy port SSH
    
    # Utworzenie executora
    executor = SSHExecutor(HOST, USERNAME, PASSWORD, PORT)
    
    try:
        # Połączenie
        if not executor.connect(timeout=10):
            print(f"Nie można połączyć się z {HOST}:{PORT}")
            return
        
        # Wykonanie poleceń
        commands = [
            "hostname",
            "uptime",
            "df -h"
        ]
        
        results = executor.execute_commands(commands)
        
        # Wyświetlenie wyników
        for i, result in enumerate(results):
            print(f"\n=== {commands[i]} ===")
            if result['success']:
                for line in result['output']:
                    print(line)
            else:
                print(f"Błąd: {result['error']}")
                
    finally:
        executor.disconnect()

# Uruchomienie
execute_on_custom_port()
```

## Sprawdzanie portu SSH

Przed połączeniem możesz sprawdzić czy port SSH jest otwarty:

### Windows (PowerShell)
```powershell
Test-NetConnection -ComputerName 10.10.9.50 -Port 2222
```

### Linux/Mac
```bash
nc -zv 10.10.9.50 2222
# lub
telnet 10.10.9.50 2222
```

## Typowe problemy z portami

### Problem: "Connection refused"
**Rozwiązanie:** Sprawdź czy używasz poprawnego portu
```python
# Spróbuj różnych portów
for port in [22, 2222, 10022]:
    executor = SSHExecutor(host, user, pass, port)
    if executor.connect(timeout=5):
        print(f"✓ Połączono na porcie {port}")
        executor.disconnect()
        break
    else:
        print(f"✗ Port {port} niedostępny")
```

### Problem: "Connection timeout"
**Rozwiązanie:** Zwiększ timeout lub sprawdź firewall
```python
executor = SSHExecutor(host, user, pass, port)
if executor.connect(timeout=30):  # Zwiększony timeout
    print("Połączono")
```

## Bezpieczeństwo

### Używanie zmiennych środowiskowych dla portu

```python
import os

HOST = os.getenv('SSH_HOST', '10.10.9.50')
USERNAME = os.getenv('SSH_USER', 'admin')
PASSWORD = os.getenv('SSH_PASSWORD')
PORT = int(os.getenv('SSH_PORT', '22'))  # Domyślnie 22

executor = SSHExecutor(HOST, USERNAME, PASSWORD, PORT)
```

Plik `.env`:
```
SSH_HOST=10.10.9.50
SSH_USER=admin
SSH_PASSWORD=haslo
SSH_PORT=2222
```

## Więcej informacji

Zobacz pełną dokumentację w `README_SSH_AUTOMATION.md`