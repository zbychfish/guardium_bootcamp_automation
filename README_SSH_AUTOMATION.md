# SSH Automation - Automatyzacja poleceń SSH

Skrypt Python do automatycznego wykonywania poleceń na zdalnych maszynach przez SSH bez konieczności instalacji dodatkowego oprogramowania na serwerze docelowym.

## Wymagania

- Python 3.7+
- Biblioteka Paramiko

## Instalacja

```bash
# Instalacja zależności
pip install -r requirements.txt

# Lub bezpośrednio
pip install paramiko
```

## Użycie

### Podstawowe użycie

```python
from ssh_automation import SSHExecutor

# Utworzenie executora
executor = SSHExecutor(
    host="10.10.9.50",
    username="admin",
    password="haslo",
    port=22  # Domyślnie 22, zmień jeśli SSH działa na innym porcie
)

# Połączenie
if executor.connect():
    # Wykonanie polecenia
    result = executor.execute_command("ls -la")
    
    # Wyświetlenie wyniku
    print(f"Sukces: {result['success']}")
    print(f"Wyjście: {result['output']}")  # Lista linii
    print(f"Kod wyjścia: {result['exit_code']}")
    
    # Rozłączenie
    executor.disconnect()
```

### Wykonanie wielu poleceń

```python
from ssh_automation import SSHExecutor

executor = SSHExecutor("10.10.9.50", "admin", "haslo", 22)

try:
    if executor.connect():
        # Lista poleceń
        commands = [
            "whoami",
            "pwd",
            "ls -la /data",
            "df -h"
        ]
        
        # Wykonanie wszystkich poleceń
        results = executor.execute_commands(commands)
        
        # Przetworzenie wyników
        for i, result in enumerate(results):
            print(f"\n=== Polecenie: {commands[i]} ===")
            if result['success']:
                for line in result['output']:
                    print(line)
            else:
                print(f"Błąd: {result['error']}")
finally:
    executor.disconnect()
```

### Uruchomienie przykładowego skryptu

```bash
# Edytuj parametry w ssh_automation.py (HOST, USERNAME, PASSWORD)
python ssh_automation.py
```

## API

### Klasa SSHExecutor

#### `__init__(host, username, password, port=22)`

Inicjalizacja executora SSH.

**Parametry:**
- `host` (str): Adres IP lub hostname zdalnej maszyny
- `username` (str): Nazwa użytkownika
- `password` (str): Hasło
- `port` (int): Port SSH (domyślnie 22)

#### `connect(timeout=10) -> bool`

Nawiązanie połączenia SSH.

**Parametry:**
- `timeout` (int): Timeout połączenia w sekundach

**Zwraca:**
- `bool`: True jeśli połączenie udane, False w przeciwnym razie

#### `execute_command(command, timeout=30) -> Dict[str, Any]`

Wykonanie pojedynczego polecenia.

**Parametry:**
- `command` (str): Polecenie do wykonania
- `timeout` (int): Timeout wykonania w sekundach

**Zwraca:**
```python
{
    'success': bool,        # True jeśli polecenie zakończyło się sukcesem
    'output': List[str],    # Lista linii wyjścia
    'error': str,           # Komunikat błędu (jeśli wystąpił)
    'exit_code': int        # Kod wyjścia polecenia
}
```

#### `execute_commands(commands) -> List[Dict[str, Any]]`

Wykonanie wielu poleceń.

**Parametry:**
- `commands` (List[str]): Lista poleceń do wykonania

**Zwraca:**
- `List[Dict[str, Any]]`: Lista wyników dla każdego polecenia

#### `disconnect()`

Zamknięcie połączenia SSH.

## Przykłady użycia

### Przykład 1: Monitorowanie systemu

```python
from ssh_automation import SSHExecutor

executor = SSHExecutor("10.10.9.50", "admin", "haslo")

if executor.connect():
    # Sprawdź obciążenie systemu
    result = executor.execute_command("uptime")
    print("Uptime:", result['output'][0])
    
    # Sprawdź użycie dysku
    result = executor.execute_command("df -h")
    for line in result['output']:
        print(line)
    
    # Sprawdź procesy
    result = executor.execute_command("ps aux | head -10")
    for line in result['output']:
        print(line)
    
    executor.disconnect()
```

### Przykład 2: Zarządzanie aplikacją

```python
from ssh_automation import SSHExecutor

def restart_application(host, username, password, app_name):
    """Restart aplikacji na zdalnym serwerze"""
    executor = SSHExecutor(host, username, password)
    
    try:
        if not executor.connect():
            return False
        
        # Sprawdź status
        result = executor.execute_command(f"systemctl status {app_name}")
        print(f"Status przed restartem: {result['output']}")
        
        # Restart
        result = executor.execute_command(f"systemctl restart {app_name}")
        if not result['success']:
            print(f"Błąd restartu: {result['error']}")
            return False
        
        # Sprawdź status po restarcie
        result = executor.execute_command(f"systemctl status {app_name}")
        print(f"Status po restarcie: {result['output']}")
        
        return True
    finally:
        executor.disconnect()

# Użycie
restart_application("10.10.9.50", "admin", "haslo", "nginx")
```

### Przykład 3: Zbieranie logów

```python
from ssh_automation import SSHExecutor
import datetime

def collect_logs(host, username, password, log_path, lines=100):
    """Zbierz ostatnie linie z pliku logów"""
    executor = SSHExecutor(host, username, password)
    
    try:
        if not executor.connect():
            return []
        
        # Pobierz ostatnie linie
        result = executor.execute_command(f"tail -n {lines} {log_path}")
        
        if result['success']:
            # Zapisz lokalnie
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"logs_{timestamp}.txt"
            
            with open(filename, 'w') as f:
                for line in result['output']:
                    f.write(line + '\n')
            
            print(f"Logi zapisane do: {filename}")
            return result['output']
        else:
            print(f"Błąd pobierania logów: {result['error']}")
            return []
    finally:
        executor.disconnect()

# Użycie
logs = collect_logs("10.10.9.50", "admin", "haslo", "/var/log/app.log", 50)
```

### Przykład 4: Wykonanie CLI aplikacji

```python
from ssh_automation import SSHExecutor

def execute_app_cli(host, username, password, cli_command):
    """Wykonaj polecenie CLI specyficznej aplikacji"""
    executor = SSHExecutor(host, username, password)
    
    try:
        if not executor.connect():
            return None
        
        # Wykonaj polecenie CLI
        result = executor.execute_command(cli_command)
        
        if result['success']:
            print("✓ Polecenie wykonane pomyślnie")
            return result['output']
        else:
            print(f"✗ Błąd: {result['error']}")
            return None
    finally:
        executor.disconnect()

# Przykłady użycia z różnymi CLI
# MinIO Client
output = execute_app_cli("10.10.9.50", "admin", "haslo", "mc ls myminio")

# Docker
output = execute_app_cli("10.10.9.50", "admin", "haslo", "docker ps")

# Własne CLI
output = execute_app_cli("10.10.9.50", "admin", "haslo", "myapp-cli status")
```

## Obsługa błędów

```python
from ssh_automation import SSHExecutor

executor = SSHExecutor("10.10.9.50", "admin", "haslo")

try:
    if not executor.connect():
        print("Nie można połączyć się z serwerem")
        exit(1)
    
    result = executor.execute_command("some-command")
    
    if result['success']:
        # Sukces
        for line in result['output']:
            print(line)
    else:
        # Błąd wykonania polecenia
        print(f"Kod wyjścia: {result['exit_code']}")
        print(f"Błąd: {result['error']}")
        
except KeyboardInterrupt:
    print("\nPrzerwano przez użytkownika")
except Exception as e:
    print(f"Nieoczekiwany błąd: {e}")
finally:
    executor.disconnect()
```

## Bezpieczeństwo

### Używanie kluczy SSH (zalecane)

Zmodyfikuj metodę `connect()` aby używać kluczy zamiast haseł:

```python
def connect_with_key(self, key_path: str, timeout: int = 10) -> bool:
    """Połączenie z użyciem klucza SSH"""
    try:
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        self.client.connect(
            hostname=self.host,
            port=self.port,
            username=self.username,
            key_filename=key_path,
            timeout=timeout
        )
        
        print(f"✓ Połączono z {self.host} (klucz SSH)")
        return True
    except Exception as e:
        print(f"✗ Błąd połączenia: {e}")
        return False
```

### Przechowywanie danych uwierzytelniających

Używaj zmiennych środowiskowych lub plików konfiguracyjnych:

```python
import os
from dotenv import load_dotenv

load_dotenv()

executor = SSHExecutor(
    host=os.getenv('SSH_HOST'),
    username=os.getenv('SSH_USER'),
    password=os.getenv('SSH_PASSWORD')
)
```

Plik `.env`:
```
SSH_HOST=10.10.9.50
SSH_USER=admin
SSH_PASSWORD=haslo
```

## Rozwiązywanie problemów

### Błąd: "Authentication failed"
- Sprawdź poprawność nazwy użytkownika i hasła
- Upewnij się, że użytkownik ma dostęp SSH

### Błąd: "Connection timeout"
- Sprawdź czy host jest osiągalny: `ping 10.10.9.50`
- Sprawdź czy port SSH jest otwarty: `telnet 10.10.9.50 22`
- Zwiększ timeout: `executor.connect(timeout=30)`

### Błąd: "Command not found"
- Polecenie może nie być dostępne w ograniczonym shellu
- Sprawdź dostępne polecenia: `executor.execute_command("help")`
- Użyj pełnej ścieżki do polecenia: `/usr/bin/command`

### Polecenie zwraca pusty output
- Niektóre polecenia wymagają interaktywnego terminala
- Użyj `invoke_shell()` dla interaktywnych sesji
- Sprawdź stderr: `result['error']`

## Licencja

Ten skrypt jest dostarczany "tak jak jest" bez żadnych gwarancji.