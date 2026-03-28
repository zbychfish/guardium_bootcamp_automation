#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sync Lab - orkiestracja synchronizacji środowiska laboratoryjnego
"""

#from pexpect.FSM import Error
import psycopg2
#from paramiko.proxy import subprocess
import os
import re
import time
import json
import paramiko
from dotenv import load_dotenv
from appliance_command import ApplianceCommand, change_password_as_root, scp_file_as_root
from guardium_patch import install_patch
import os
from guardium_rest_api import GuardiumRestAPI
from typing import Any, Dict, List, Optional
import urllib.request
import sys
import traceback
import zipfile
import glob
from pathlib import Path
import subprocess
from packaging.version import Version





# Sprawdź czy plik .env istnieje
env_file_path = os.path.join(os.path.dirname(__file__), '.env')
if not os.path.exists(env_file_path):
    print("=" * 60)
    print("ERROR: Plik .env nie został znaleziony!")
    print("=" * 60)
    print("\nUtwórz plik .env na podstawie .env.example:")
    print(f"1. Skopiuj plik .env.example do .env")
    print(f"2. Uzupełnij hasła w pliku .env")
    print(f"\nLokalizacja: {env_file_path}")
    print("=" * 60)
    import sys
    sys.exit(1)

# Załaduj zmienne środowiskowe z pliku .env
load_dotenv()


def get_env_value(key: str) -> str:
    """Pobiera wartość ze zmiennych środowiskowych"""
    value = os.getenv(key)
    if not value:
        raise ValueError(f"Wartość dla {key} nie została znaleziona w pliku .env")
    return value


def save_to_env(key: str, value: str, env_file: str = ".env") -> bool:
    """
    Zapisuje lub aktualizuje zmienną w pliku .env
    
    Args:
        key: Nazwa zmiennej
        value: Wartość zmiennej
        env_file: Ścieżka do pliku .env
    
    Returns:
        True jeśli sukces, False w przypadku błędu
    """
    try:
        env_path = os.path.join(os.path.dirname(__file__), env_file)
        
        # Wczytaj istniejące linie
        lines = []
        key_found = False
        
        if os.path.exists(env_path):
            with open(env_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # Zaktualizuj istniejący klucz lub oznacz że nie znaleziono
            for i, line in enumerate(lines):
                if line.strip().startswith(f"{key}="):
                    lines[i] = f"{key}={value}\n"
                    key_found = True
                    break
        
        # Jeśli klucz nie istnieje, dodaj na końcu
        if not key_found:
            if lines and not lines[-1].endswith('\n'):
                lines.append('\n')
            lines.append(f"{key}={value}\n")
        
        # Zapisz plik
        with open(env_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        
        # Zaktualizuj zmienną środowiskową w bieżącej sesji
        os.environ[key] = value
        
        return True
    except Exception as e:
        print(f"  ✗ Error saving to .env: {e}")
        return False


def parse_unit_summary(text: str) -> dict:
    """
    Ekstrahuje z luźnego tekstu:
      - host (z 'Unit Host=...'; jeśli brak, użyje pierwszego FQDN w tekście),
      - ip (z 'IP=...'),
      - unit_type (z 'Unit Type=...'),
      - online (z 'Online=true/false' -> bool).
    Zwraca słownik.
    """
    # Bezpiecznie spłaszcz spacje
    t = re.sub(r"\s+", " ", text.strip())

    def grab(pattern, flags=0, group=1):
        m = re.search(pattern, t, flags)
        return m.group(group) if m else None

    # Host: preferuj 'Unit Host=...' ; fallback: pierwszy FQDN na początku linii
    host = grab(r"\bUnit\s+Host=([A-Za-z0-9._-]+)")
    if not host:
        host = grab(r"\b([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")  # np. coll1.gdemo.com

    # IP (pierwszy po 'IP=')
    ip = grab(r"\bIP=(\d{1,3}(?:\.\d{1,3}){3})\b")

    # Unit Type
    unit_type = grab(r"\bUnit\s+Type=([A-Za-z0-9._-]+)")

    # Online (jako bool)
    online_str = grab(r"\bOnline=(true|false)\b", flags=re.IGNORECASE)
    online = None
    if online_str is not None:
        online = online_str.lower() == "true"

    return {
        "host": host,
        "ip": ip,
        "unit_type": unit_type,
        "online": online,
    }


# Wspólna konfiguracja dla wszystkich appliance
common_config = {
    'user': 'cli',
    'initial_pattern': 'Last login',
    'timeout': 120
}


# Konfiguracja specyficzna dla każdego appliance
appliances = {
    'collector': {
        'host': '10.10.9.239',
        'prompt_regex': r'coll1\.gdemo\.com>',
        'password': get_env_value('COLLECTOR_PASSWORD')
    },
    'collector_unconfigured': {
        'host': '10.10.9.239',
        'prompt_regex': r'guard\.yourcompany\.com>',
        'password': get_env_value('COLLECTOR_PASSWORD'),
        'initial_pattern': None  # Wyłącz initial_pattern dla unconfigured collector
    },
    'cm': {
        'host': '10.10.9.219',
        'prompt_regex': r'cm\.gdemo\.com>',
        'password': get_env_value('CM_PASSWORD')
    },
    'toolnode': {
        'host': '10.10.9.229',
        'prompt_regex': r'toolnode\.gdemo\.com>',
        'password': get_env_value('TOOLNODE_PASSWORD')
    }
}

managed_machines: dict[str, dict[str, str]] = {
    'raptor': {
        'host': '10.10.9.70',
        'prompt_regex': r'raptor\.gdemo\.com>',
        'password': get_env_value('RAPTOR_PASSWORD')
    },
    'hana': {
        'host': '10.10.9.60',
        'prompt_regex': r'hana\.gdemo\.com>',
        'password': get_env_value('HANA_PASSWORD')
    },
    'winsql': {
        'host': '10.10.9.59',
        'prompt_regex': r'winsql\.gdemo\.com>',
        'password': get_env_value('WINSQL_PASSWORD')
    },
    'appnode': {
        'host': '10.10.9.50',
        'prompt_regex': r'appnode\.gdemo\.com>',
        'password': get_env_value('APPNODE_PASSWORD')
    }
}

def create_appliance(appliance_name: str) -> ApplianceCommand:
    """Tworzy instancję ApplianceCommand dla danego appliance"""
    appliance_config = appliances[appliance_name]
    
    # Użyj initial_pattern z appliance_config jeśli istnieje, w przeciwnym razie z common_config
    initial_pattern = appliance_config.get('initial_pattern', common_config['initial_pattern'])
    
    return ApplianceCommand(
        host=appliance_config['host'],
        user=common_config['user'],
        password=appliance_config['password'],
        prompt_regex=appliance_config['prompt_regex'],
        initial_pattern=initial_pattern,
        timeout=common_config['timeout']
    )

def wait_for_appliance(appliance_name: str, max_attempts: int = 40, interval: int = 15) -> ApplianceCommand:
    """
    Czeka aż appliance będzie dostępny i nawiąże połączenie.
    
    Args:
        appliance_name: Nazwa appliance z konfiguracji
        max_attempts: Maksymalna liczba prób połączenia
        interval: Odstęp między próbami w sekundach
    
    Returns:
        Połączony obiekt ApplianceCommand
    
    Raises:
        RuntimeError: Jeśli nie udało się połączyć po wszystkich próbach
    """
    print(f"\n[INFO] Oczekiwanie na dostępność appliance '{appliance_name}'...")
    
    for attempt in range(1, max_attempts + 1):
        print(f"[INFO] Próba połączenia {attempt}/{max_attempts}...")
        
        try:
            appliance = create_appliance(appliance_name)
            if appliance.connect():
                print(f"[INFO] ✓ Połączono z '{appliance_name}' po {attempt} próbach")
                return appliance
        except Exception as e:
            print(f"[INFO] ✗ Próba {attempt} nieudana: {e}")
        
        if attempt < max_attempts:
            print(f"[INFO] Oczekiwanie {interval} sekund przed kolejną próbą...")
            time.sleep(interval)
    
    raise RuntimeError(f"Nie udało się połączyć z '{appliance_name}' po {max_attempts} próbach")

# --- 1) Zamiana tekstu pseudo-JSON => prawidłowy JSON ---
def to_valid_json(src: str) -> str:
    s = src

    # a) Cytuj klucze: {hostName: ... , port: ...} -> {"hostName": ..., "port": ...}
    s = re.sub(r'([{\s,])([A-Za-z_]\w*)\s*:', r'\1"\2":', s)

    # b) Cytuj znane wartości tekstowe (hostName, unitType, guardRelease, ip, lastInstalledPatch)
    #    Używamy osobnych wzorców, żeby nie ruszać liczb, [] ani {}.
    def quote_value_for(key: str, text: str) -> str:
        # dopasuj:  "<key>" : <wartość-niecytowana>  kończąca się na  , ] }
        pattern = rf'("{key}"\s*:\s*)([^"\s\[\]{{}},][^,\]}}]*)'
        def repl(m):
            g1, val = m.group(1), m.group(2).strip()
            return f'{g1}"{val}"'
        return re.sub(pattern, repl, text)

    for k in ("hostName", "unitType", "guardRelease", "ip", "lastInstalledPatch"):
        s = quote_value_for(k, s)

    # c) Ewentualnie usuń podwójne spacje/przecinki z artefaktów
    s = re.sub(r'\s+', ' ', s)
    return s

# --- 2) Wyciągnięcie listy mus z obiektu Message (który jest już JSON-em) ---
def parse_mus_from_message_dict(dct: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = dct.get("Message") or dct.get("message")
    if not raw:
        return []
    fixed = to_valid_json(raw)
    obj = json.loads(fixed)  # tu może polecieć ValueError, jeśli format jest inny niż zakładany
    mus = obj.get("mus")
    if not isinstance(mus, list):
        return []
    # W tym miejscu 'mus' to już zwykła lista dictów JSON-owych
    return mus

def parse_patch_list(output: str) -> dict[int, int]:
    """
    Parsuje output z listą patchy i zwraca mapowanie: numer_patcha -> numer_linii.
    
    Args:
        output: Output z komendy 'store system patch install sys' zawierający listę patchy
    
    Returns:
        Słownik mapujący numer patcha na numer linii (1-based), np. {9997: 1, 4015: 2}
    
    Example:
        >>> output = '''Attempting to retrieve the patch information...
        ... P#      Description                                   Version Md5sum
        ... 9997    Health Check for GPU and Bundle installation  12.0    de27af692f57b738e50c829a4f1d6800
        ... 4015    Snif Update (Nov 20 2025)                     12.0    4ff4686f434c68c261ba52933bef1d0d'''
        >>> parse_patch_list(output)
        {9997: 1, 4015: 2}
    """
    patch_map = {}
    line_number = 0
    
    for line in output.splitlines():
        # Pomiń puste linie i nagłówki
        line = line.strip()
        if not line or line.startswith('Attempting') or line.startswith('P#') or 'Please wait' in line:
            continue
        
        # Sprawdź czy linia zaczyna się od numeru (patch number)
        parts = line.split(None, 1)  # Split na pierwszej spacji
        if parts and parts[0].isdigit():
            patch_number = int(parts[0])
            line_number += 1
            patch_map[patch_number] = line_number
    
    return patch_map

def get_patch_line_numbers(output: str) -> list[int]:
    """
    Zwraca numery linii dla patchy zdefiniowanych w zmiennej środowiskowej PATCH_LIST.
    
    Args:
        output: Output z komendy 'store system patch install sys' zawierający listę patchy
    
    Returns:
        Lista numerów linii (1-based) odpowiadających patchom z PATCH_LIST w kolejności
    
    Example:
        Jeśli PATCH_LIST="9997,4015" w pliku .env:
        >>> output = '''...
        ... 9997    Health Check for GPU and Bundle installation  12.0    de27af692f57b738e50c829a4f1d6800
        ... 4015    Snif Update (Nov 20 2025)                     12.0    4ff4686f434c68c261ba52933bef1d0d'''
        >>> get_patch_line_numbers(output)
        [1, 2]
    """
    # Pobierz PATCH_LIST ze zmiennych środowiskowych
    patch_list_str = get_env_value('PATCH_LIST')
    
    # Parsuj string na listę intów (np. "9997,4015" -> [9997, 4015])
    patch_numbers = [int(p.strip()) for p in patch_list_str.split(',') if p.strip()]
    
    # Parsuj output i stwórz mapowanie patch_number -> line_number
    patch_map = parse_patch_list(output)
    
    # Konwertuj numery patchy na numery linii w kolejności z PATCH_LIST
    line_numbers = []
    for patch_num in patch_numbers:
        if patch_num in patch_map:
            line_numbers.append(patch_map[patch_num])
        else:
            raise ValueError(f"Patch number {patch_num} not found in output")
    
    return line_numbers

def load_state():
    if not os.path.exists(STATE_FILE):
        return {"completed_tasks": []}
    with open(STATE_FILE, "r") as f:
        return json.load(f)

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def run_task(task_id, task_fn, state):
    if task_id in state["completed_tasks"]:
        print(f"Skipping {task_id}")
        return        
    print(f"Running {task_id}")
    output = task_fn()
    state["completed_tasks"].append(task_id)
    save_state(state)
    return output

def t_password_change_on_appliances():
    print("\nPassword change for cli user on appliances")
    current_appliances = appliances.copy()
    del current_appliances['collector']
    for name, cfg in current_appliances.items():
        print(f"  Changing password on {name} ({cfg['host']})")
        ok = change_password_as_root(
            host=cfg["host"],
            root_password=get_env_value("ROOT_PASSWORD"),
            target_user="cli",
            new_password=get_env_value("COLLECTOR_PASSWORD")
        )
        print("    ✓ OK" if ok else "    ✗ FAILED")
    return None

def t_initial_collector_settings(appliance):
    print("Connect to collector and get network settings")
    print(appliance.execute_command("show network interface all"))
    print(appliance.execute_command("show network route default"))
    print(appliance.execute_command("show network resolvers"))
    
    print("\nDisabling purge")
    output = appliance.execute_command("grdapi diable_purge")
    print("    ✓ OK")

    print("\nSet time zone to Europe/Warsaw")
    output = appliance.execute_command("show system clock all")
    timezone = output.strip().splitlines()[-1]
    if timezone != "Europe/Warsaw":
        output = appliance.execute_command_with_confirmation(
            command="store system clock timezone Europe/Warsaw",
            response="y",
            confirmation_pattern=r"Do you want to proceed\?\s*\(y/n\)\s*"
        )
        print(output)
        output = appliance.execute_command("show system clock all")
        print(output)
    else:
        print(f"  Time zone already set to {timezone}")
    print("    ✓ OK")
    print("\nConfigure NTP servers")
    appliance.execute_command("store system time_server hostname 0.pool.ntp.org 1.pool.ntp.org 2.pool.ntp.org")
    print(appliance.execute_command("show system time_server all"))
    print("\nEnabling time synchronization")
    appliance.execute_command("store system time_server state on")
    print(appliance.execute_command("show system time_server all"))
    print("    ✓ OK")

def t_restart_system(appliance):
    print("\nRestart system")
    result = appliance.execute_restart_with_check()
    print(f"  {result}")
    appliance.disconnect()
    
    if "System is restarting - connection broke" in result:
        print("\nWaiting for system availability...")
        appliance = wait_for_appliance('collector_unconfigured')
        print("  ✓ Appliance available")
    else:
        print("  ✗ Could not restart - MYSQL is busy")
        print("  ✗ Run script again in 1 minute or restart collector manually and then start again")
    return None

def t_other_collector_settings(appliance):
    print("\nSetup collector name and domain")
    appliance.execute_command("store system hostname coll1")
    appliance.execute_command("store system domain gdemo.com")
    print("  ✓ Collector name set")
    
    print("\nConfigure session timeouts")
    appliance.execute_command("store gui session_timeout 9999")
    appliance.execute_command("store timeout cli_session 600")
    print("  ✓ Timeouts configured")
   
    print("\nRestart GUI")
    appliance.execute_command_with_confirmation(
        command="restart gui",
        response="y",
        confirmation_pattern=r"Are you sure you want to restart GUI\s*\(y/n\)\?"
    )
    print("  ✓ GUI restarted")

    print("\nSet shared secret on collector")
    appliance.execute_command("store system shared secret guardium")
    print("  ✓ Shared Secret set")

    print("\nSet manual hosts settings")
    output = appliance.execute_command("support show hosts")
    existing = set()
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            ip = parts[0].strip().lower()
            host = parts[1].strip().lower()
            existing.add((ip, host))
    current_appliances = appliances.copy()
    del current_appliances['collector_unconfigured']
    del current_appliances['collector']
    machines = current_appliances | managed_machines
    for machine, cfg in machines.items():
        ip = str(cfg["host"]).strip().lower()
        prompt_host = re.sub(r"\\", "", str(cfg["prompt_regex"])).strip()
        if prompt_host.endswith(">"):
            prompt_host = prompt_host[:-1]
        prompt_host = prompt_host.strip().lower()
        if (ip, prompt_host) in existing:
            continue
        command = f'support store hosts {cfg["host"]} {prompt_host}'
        appliance.execute_command(command)
    print(appliance.execute_command("support show hosts"))
    print("  ✓ Hosts updated")

    print("\nDisabling guardcli accounts")
    for account_number in range(2, 9):
        appliance.execute_command(f"store guarduser_state disable guardcli{account_number}")
    print("  ✓Accounts disabled")
    return None

def t_initial_cm_settings(appliance):
    print("\nCreate oauth client for bootcamp sync")
    result = appliance.execute_command("grdapi list_oauth_clients")
    if "Client Id: BOOTCAMP" in result:
        appliance.execute_command("grdapi delete_oauth_clients client_id=BOOTCAMP")
    result = appliance.execute_command('grdapi register_oauth_client client_id=BOOTCAMP grant_types="password"')
    client_secret = None
    for line in result.splitlines():
        line = line.strip()
        if line.startswith('{') and line.endswith('}'):
            try:
                data = json.loads(line)
                client_secret = data.get('client_secret')
                if client_secret:
                    if save_to_env("CLIENT_SECRET", client_secret):
                        print(f"  ✓ Client secret saved to .env")
                    else:
                        print(f"  ⚠ Warning: Could not save client_secret to .env")
                    break
            except json.JSONDecodeError:
                pass
    if not client_secret:
        print("  ⚠ Warning: Could not extract client_secret from response")
        return None
    print("  ✓ Oauth client configured")

    print("\nSet shared secret on Central Manager")
    appliance.execute_command("store system shared secret guardium")
    print("  ✓ Shared Secret set")

    print("\nDisabling guardcli accounts")
    for account_number in range(2, 9):
        appliance.execute_command(f"store guarduser_state disable guardcli{account_number}")
    print("  ✓ Accounts disabled")

    print("\nSet resolving for coll1.gdemo.com")
    appliance.execute_command(f"support store hosts 10.10.9.239 coll1.gdemo.com")
    print("  ✓ Done")
    return None

def t_create_demo_user(api):
    print("\nCreate demo user")
    token = api.get_token(username='accessmgr', password=get_env_value('ACCESSMGR_PASSWORD'))
    users = api.get_users()
    print("  Current users:")
    for u in users:
        status = "DISABLED" if u.get("disabled") == "true" else "ACTIVE"
        print(f"    {u['user_name']:12} | {status}")
    
    demo_exists = any(u.get('user_name') == 'demo' for u in users)
    if not demo_exists:
        print("\n  Creating demo user...")
        demo_password = get_env_value('DEMOUSER_PASSWORD')
        result = api.create_user(
            username='demo',
            password=demo_password,
            confirm_password=demo_password,
            first_name='User',
            last_name='Demo',
            email='demo@demo.training',
            country='PL',
            disabled=False,
            disable_pwd_expiry=True
        )
        print(f"  ✓ Demo user created")
        print("\n  Assigning roles to demo user")    
        result = api.set_user_roles(username='demo', roles='admin,cli,user,vulnerability-assess')  
        print(f"  ✓ Roles assigned to demo user")
    else:
        print("\n  Demo user already exists")
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    if not demo_exists:
        print("\n Import Training dashboard for demo user")
        result = api.import_definitions('guardium_definition_files/exp_dashboard_training.sql')
        print(f"  ✓ Dashboard Training added to demo user UI")
    return None

def t_register_collector(api):  
    print("\nRegister collector to central manager")
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    units = api.get_registered_units()
    units = parse_mus_from_message_dict(units)
    # print(units)
    out: List[Dict[str, Optional[str]]] = []
    for u in units:
        out.append({
            "ip": u.get("ip"),
        })
    if not any(d.get('ip') == '10.10.9.239' for d in out):
        appliance = create_appliance('collector')
        if not appliance.connect():
            print("  ✗ Failed to connect to collector")
            return None

        print("  Unit type:")
        result = appliance.execute_command("show unit type")
        print(f"    {result}")

        try:
            result = appliance.execute_command("register management 10.10.9.219 8443", timeout=600)
            print(result)
        except TimeoutError:
            pass  # Ignoruj timeout, kontynuuj
        
        unit_data = api.get_unit_data(api_target_host='10.10.9.239')
        unit_data = parse_unit_summary(unit_data['Message'])
        print(unit_data)
        print("  Unit type:")
        try:
            result = appliance.execute_command("show unit type")
            print(f"    {result}")
        except (TimeoutError, OSError):
            pass  # Ignoruj timeout, kontynuuj
        print(f"  ✓ Collector registered ")
    else:
        unit_data = api.get_unit_data(api_target_host='10.10.9.239')
        unit_data = parse_unit_summary(unit_data['Message'])
        print(unit_data)
        print(f"  ✓ Collector is already registered ")
    return None

def t_preparing_appliances_for_patching(api):
    print("\nDownload and unpack patches locally")
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    target_dir = "/root/gn-trainings/appliance-patches"
    os.makedirs(target_dir, exist_ok=True)
    filename = os.path.join(target_dir, os.path.basename("patches.zip"))
    urllib.request.urlretrieve(get_env_value("PATCH_ARCHIVE"), filename)
    with zipfile.ZipFile(filename, "r") as zipf:
            zipf.extractall(path=target_dir)
    print(f"  ✓ Patches extracted")
    with zipfile.ZipFile(filename, "r") as zipf:
        patch_list = sorted(zipf.namelist())
    patch_order = get_env_value("PATCH_NAME_LIST").split(",")
    sorted_patch_list = sorted(patch_order)
    save_to_env("PATCH_ORDER", ",".join(str(sorted_patch_list.index(item) + 1) for item in patch_order))

    print("\nRemoving old patch archives on central manager")
    result = api.patch_cleanup()   
    print("    ✓ OK")
    
    print("\nCopying patches to central manager and collector")
    patch_files = glob.glob('/root/gn-trainings/appliance-patches/patches/*.sig')
    
    if not patch_files:
        print("  ✗ No patch files found in /root/gn-trainings/appliance-patches/patches/")
        exit(1)    
    print(f"  Found {len(patch_files)} patch files to copy")
    all_success = True
    for appl in ['10.10.9.219', '10.10.9.239']:
        for patch_file in patch_files:
            success = scp_file_as_root(
                host=appl,
                root_password=get_env_value("ROOT_PASSWORD"),
                local_path=patch_file,
                remote_path='/var/log/guard/patches/',
                direction='put'
            )
            if not success:
                all_success = False
                break
    if all_success:
        print(f"  ✓ All {len(patch_files)} patches copied successfully")

        print("\nChanging ownership of patches to tomcat:tomcat")
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        for appl in ['10.10.9.219', '10.10.9.239']:
            try:
                client.connect(
                    hostname=appl,
                    username='root',
                    password=get_env_value("ROOT_PASSWORD"),
                    look_for_keys=False,
                    allow_agent=False
                )
                stdin, stdout, stderr = client.exec_command('chown tomcat:tomcat /var/log/guard/patches/*.sig')
                exit_status = stdout.channel.recv_exit_status()
                if exit_status != 0:
                    error = stderr.read().decode()
                    print(f"  ✗ Failed to change ownership: {error}")
                    exit(1)
                client.close()
            except Exception as e:
                print(f"  ✗ Error changing ownership: {e}")
                exit(1)
        print(f"  ✓ Ownership changed to tomcat:tomcat")
    else:
        print("  ✗ Problem with copying of patches to central manager or collector")
        exit(1)
    return None

def t_registering_patches_installation(appliance_name, appliance_ip, password):
    appliance = create_appliance(appliance_name)
    if not appliance.connect():
        print(f"  ✗ Failed to connect to {appliance_name}")
        return None
    appliance.execute_command("show system patch available")
    
    output = install_patch(
        host=appliance_ip,
        username='cli',
        password=password,
        patch_selection=get_env_value("PATCH_ORDER"),
        reinstall_answer="y",
        live_log=False
    )

    appliance.disconnect()
    return None

def t_monitoring_patch_installation(appliance_name):
    appliance = create_appliance(appliance_name)
    if not appliance.connect():
        print(f"  ✗ Failed to connect to {appliance_name}")
        return None   
    required_status = "DONE: Patch installation Succeeded."
    while True:
        result = appliance.execute_command("show system patch installed")
        # Pobierz listę numerów patchy ze zmiennej środowiskowej (np. "9997,4015")
        wanted = set(get_env_value("PATCH_LIST").split(","))
        status_by_id = {}
        for line in result.splitlines():
            line = line.strip()
            if not line or line.startswith("P#"):
                continue
            m = re.match(r"^(\d+)\b.*", line)
            if not m:
                continue
            pid = m.group(1)
            has_ok_status = required_status in line
            status_by_id[pid] = has_ok_status        
        # Sprawdź czy wszystkie wymagane patche są zainstalowane z poprawnym statusem
        all_installed = all(pid in status_by_id and status_by_id[pid] for pid in wanted)
        if all_installed:
            print(f"  ✓ All required patches ({', '.join(wanted)}) on {appliance_name} are installed with status: {required_status}")
            break
        else:
            missing = [pid for pid in wanted if pid not in status_by_id or not status_by_id[pid]]
            print(f"  ⏳ Waiting for patches: {', '.join(missing)}")
            time.sleep(10)
    appliance.disconnect()

def t_getting_gim_files():
    print("\nDownload and unpack gim installers and gim modules locally")
    target_dir = "/root/gn-trainings"
    os.makedirs(target_dir, exist_ok=True)
    filename = os.path.join(target_dir, os.path.basename("gims.zip"))
    urllib.request.urlretrieve(get_env_value("GIM_INSTALLERS_ARCHIVE"), filename)
    with zipfile.ZipFile(filename, "r") as zipf:
            zipf.extractall(path=target_dir)
            print(f"  ✓ GIM installers extracted")
    filename = os.path.join(target_dir, os.path.basename("agents.zip"))
    urllib.request.urlretrieve(get_env_value("GIM_BUNDLES_ARCHIVE"), filename)
    with zipfile.ZipFile(filename, "r") as zipf:
            zipf.extractall(path=target_dir)
    print(f"  ✓ GIM modules extracted")
    
    print("\nAdding execution flag to GIM installers")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname='10.10.9.70',
        username='root',
        password=get_env_value("RAPTOR_PASSWORD"),
        look_for_keys=False,
        allow_agent=False
    )
    stdin, stdout, stderr = client.exec_command('chmod 755 /root/gn-trainings/gim_installers/*.sh')
    exit_status = stdout.channel.recv_exit_status()
    if exit_status != 0:
        error = stderr.read().decode()
        print(f"  ✗ Failed to change files permisions: {error}")
        exit(1)

    print("\nCopying gim modules to central manager")
    patch_files = glob.glob('/root/gn-trainings/*.gim')
    
    if not patch_files:
        print("  ✗ gim files found in /root/gn-trainings/")
        exit(1)    
    print(f"  Found {len(patch_files)} patch files to copy")
    all_success = True

    for patch_file in patch_files:
        success = scp_file_as_root(
            host='10.10.9.219',
            root_password=get_env_value("ROOT_PASSWORD"),
            local_path=patch_file,
            remote_path='/var/dump/',
            direction='put'
        )
        if not success:
            all_success = False
            break
    if all_success:
        print(f"  ✓ All {len(patch_files)} patches copied successfully")

    print("\nRemoving zip files")
    stdin, stdout, stderr = client.exec_command('rm -f /root/gn-trainings/*.zip')
    exit_status = stdout.channel.recv_exit_status()
    if exit_status != 0:
        error = stderr.read().decode()
        print(f"  ✗ Failed to remove zip archives: {error}")
        exit(1)
    print("\nRemoving gim files")
    stdin, stdout, stderr = client.exec_command('rm -f /root/gn-trainings/*.gim')
    exit_status = stdout.channel.recv_exit_status()
    if exit_status != 0:
        error = stderr.read().decode()
        print(f"  ✗ Failed to remove gim files: {error}")
        exit(1) 
    client.close()
    return None

def t_set_collector_resolving_on_raptor():
    print("\nReslving collector on raptor")
    HOSTS_FILE = Path("/etc/hosts")
    old_ip = "10.10.9.239"
    new_entry = "10.10.9.239\t coll1.gdemo.com coll1\n"
    lines = HOSTS_FILE.read_text().splitlines(keepends=True)
    updated = []
    for line in lines:
        if line.startswith(old_ip):
            updated.append(new_entry)
        else:
            updated.append(line)
    HOSTS_FILE.write_text("".join(updated))

def t_install_policy_on_collector(api):
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    print("\nPolicy installation on collector")
    result = api.install_policy("Log Everything", api_target_host="10.10.9.239")

def t_import_gim_modules(api):
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    api.get_gim_package(filename="*.gim")

def t_postgres_installation():
    print("\n Postgres 16 installation")
    subprocess.run(["dnf", "-y", "install", "@postgresql:16"], check=True)
    print("\n Postgres database initialization")
    subprocess.run(["postgresql-setup", "--initdb", '--unit', 'postgresql'], check=True)
    print("\n Set postgres user password")
    subprocess.run(["chpasswd"], input=f"postgres:{get_env_value('DEFAULT_SERVICE_PASSWORD')}", text=True, check=True)
    print("\n Create certificate for postgres")
    subprocess.run(["openssl", "req", "-new", "-x509", "-days", "365", "-nodes", "-text", "-out", "/var/lib/pgsql/data/pgsql.crt", "-keyout", "/var/lib/pgsql/data/pgsql.key", "-subj", "/CN=raptor.demo.com"], check=True)
    files = glob.glob("/var/lib/pgsql/data/pgsql.*")
    subprocess.run(["chown", "postgres:postgres"] + files, check=True)
    print("\n Change postgres configuration")
    conf = Path("/var/lib/pgsql/data/postgresql.conf")
    lines = []
    with conf.open() as f:
        for line in f:
            if re.match(r"^\s*#\s*ssl\s*=\s*off\s*$", line):
                line = "ssl = on\n"
            elif re.match(r"^\s*#?\s*ssl_cert_file\s*=\s*'[^']+'\s*$", line):
                line = "ssl_cert_file = '/var/lib/pgsql/data/pgsql.crt'\n"
            elif re.match(r"^\s*#?\s*ssl_key_file\s*=\s*'[^']+'\s*$", line):
                line = "ssl_key_file = '/var/lib/pgsql/data/pgsql.key'\n"
            elif re.match(r"^\s*#?\s*listen_addresses\s*=\s*'[^']+'\s*(#.*)?$", line):
                line = "listen_addresses = '*'                  # what IP address(es) to listen on;\n"
            lines.append(line)
    conf.write_text("".join(lines))

    conf = Path("/var/lib/pgsql/data/pg_hba.conf")
    lines = []
    with conf.open() as f:
        for line in f:
            if re.match(r"^\s*local\s+all\s+all\s+peer\s*$", line):
                line = "local   all             all                                     ident\n"
            elif re.match(r"^\s*host\s+all\s+all\s+127\.0\.0\.1/32\s+ident\s*$", line):
                lines.append("host    all             all             127.0.0.1/32            scram-sha-256\n")
                line = "host    all             all             10.10.9.0/24            scram-sha-256\n"
            elif re.match(r"^\s*#\s*listen_addresses\s*=\s*'localhost'\s*$", line):
                line = "listen_addresses = '*'\n"
            lines.append(line)
    conf.write_text("".join(lines))
    print("\n Start postgres service")
    subprocess.run(["systemctl", "start", 'postgresql.service'], check=True)
    print("\n Enable postgres service")
    subprocess.run(["systemctl", "enable", 'postgresql.service'], check=True)

    print("\n Set postgres user password in database")
    sql = "ALTER USER postgres WITH PASSWORD '{}';".format(get_env_value("DEFAULT_SERVICE_PASSWORD"))
    subprocess.run(["sudo", "-u", "postgres", "psql", "-d", "postgres", "-U", "postgres", "-c",  sql], check=True)

def t_create_postgres_admin_users():
    print("\n Create postgres admin users")
    conn = psycopg2.connect(dbname="postgres", user= "postgres", password="guardium", host="localhost", port=5432)
    cur = conn.cursor()
    cur.execute(f"CREATE ROLE tom PASSWORD '{get_env_value('DEFAULT_SERVICE_PASSWORD')}' SUPERUSER CREATEDB CREATEROLE INHERIT LOGIN;")
    cur.execute(f"CREATE ROLE jerry PASSWORD '{get_env_value('DEFAULT_SERVICE_PASSWORD')}' SUPERUSER CREATEDB CREATEROLE INHERIT LOGIN;")
    conn.commit()
    cur.execute("SELECT 1;")
    print(cur.fetchone())
    cur.close()
    conn.close()

def t_install_gim_on_raptor():
    print("\n GIM client installation on raptor")
    subprocess.run(["/root/gn-trainings/gim_installers/guard-bundle-GIM-12.2.0.0_r121306_v12_2_1-rhel-8-linux-x86_64.gim.sh", "--", "--dir", "/opt/guardium", "--tapip", "10.10.9.70", "--sqlguardip", "10.10.9.219"], check=True)

def t_install_stap_on_raptor(api):
    print("\n S-TAP installation schedule")
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    api.gim_client_assign(
        client_ip="10.10.9.70",
        module="BUNDLE-STAP",
        module_version="12.2.0.0_r121306_5"
    )
    api.gim_client_params(
        client_ip="10.10.9.70",
        param_name="STAP_SQLGUARD_IP",
        param_value="10.10.9.239"
    )
    api.gim_client_params(
        client_ip="10.10.9.70",
        param_name="STAP_USE_TLS",
        param_value="1"
    )
    api.gim_client_params(
        client_ip="10.10.9.70",
        param_name="STAP_STATISTICS",
        param_value="-3"
    )
    api.gim_client_params(
        client_ip="10.10.9.70",
        param_name="STAP_CONNECTION_POOL_SIZE",
        param_value="2"
    )
    api.gim_schedule_install(
        client_ip="10.10.9.70",
        date="now",
    )

    print("\n S-TAP installation monitoring")
    # Pętla sprawdzająca status instalacji modułów co 10 sekund
    pending = ["initial"]  # Inicjalizacja aby wejść do pętli
    
    while pending:
        modules = api.gim_list_client_modules(client_ip="10.10.9.70")
        msg = modules["Message"]

        entries = [
            e.strip()
            for e in re.split(r"#+\s*ENTRY\s+\d+\s*#+", msg)
            if e.strip()
        ]

        result = []

        for e in entries:
            def g(p):
                m = re.search(p, e)
                return m.group(1) if m else None

            result.append({
                "module_id": g(r"MODULE_ID:\s+(-?\d+)"),
                "name": g(r"NAME:\s+([A-Z0-9\-]+)"),
                "installed_version": g(r"INSTALLED_VERSION\s+([0-9][^\s]+)"),
                "scheduled_version": g(r"SCHEDULED_VERSION\s+([0-9][^\s]+)"),
                "state": g(r"STATE:\s+([A-Z\-]+)"),
                "is_scheduled": g(r"IS_SCHEDULED:\s+([NY])"),
                "schedule_time": g(r"IS_SCHEDULED:\s+[NY]\s+\(([^)]+)\)")
            })
        
        pending = [m for m in result if m["state"] != "INSTALLED"]
        
        if pending:
            print("Waiting 30 seconds before next check...")
            time.sleep(30)
        else:
            print("All modules installed successfully!")

def t_enable_atap_for_postgres_on_raptor():
    print("\n ATAP setup for postgres on raptor")
    subprocess.run(["/opt/guardium/modules/ATAP/current/files/bin/guardctl", "--db-user=postgres", "--db-home=/usr", "--db-user-dir=/var/lib/pgsql", "--db-type=postgres", "--db-instance=postgres", "--db-version=16", "store-conf"], check=True)
    subprocess.run(["/opt/guardium/modules/ATAP/current/files/bin/guardctl", "authorize-user", "postgres"], check=True)
    subprocess.run(["systemctl", "stop", "postgresql"], check=True)
    subprocess.run(["/opt/guardium/modules/ATAP/current/files/bin/guardctl", "--db-instance=postgres", "activate"], check=True)
    subprocess.run(["systemctl", "start", "postgresql"], check=True)

def t_correct_mysql_ie(api):
    print("\n Correcting mysql Inspection Engine definition")
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    api.delete_inspection_engine(
        stap_host="10.10.9.70",
        type="mysql",
        wait_for_response="1",
        api_target_host="10.10.9.239"
    )
    api.create_inspection_engine(
        stap_host="10.10.9.70",
        protocol="mysql",
        port_min="3306",
        port_max="3306",
        ktap_db_port="3306",
        db_user="mysqld",
        db_version="8",
        client="0.0.0.0/0.0.0.0",
        proc_name="/usr/sbin/mysqld",
        db_install_dir="/var/lib/mysql",
        unix_socket_marker="mysql.sock",
        api_target_host="10.10.9.239"
    )
    api.create_inspection_engine(
        stap_host="10.10.9.70",
        protocol="mysql",
        port_min="33060",
        port_max="33060",
        ktap_db_port="33060",
        db_user="mysqld",
        db_version="8",
        client="0.0.0.0/0.0.0.0",
        proc_name="/usr/sbin/mysqld",
        db_install_dir="/var/lib/mysql",
        unix_socket_marker="mysql.sock",
        api_target_host="10.10.9.239"
    )
    api.create_inspection_engine(
        stap_host="10.10.9.70",
        protocol="mysql",
        port_min="3306",
        port_max="3306",
        ktap_db_port="3306",
        db_user="mysqld",
        db_version="8",
        client="0.0.0.0/0.0.0.0",
        proc_name="/usr/sbin/mysqld",
        db_install_dir="/var/lib/mysql",
        unix_socket_marker="mysqlx.sock",
        api_target_host="10.10.9.239"
    )
    api.create_inspection_engine(
        stap_host="10.10.9.70",
        protocol="mysql",
        port_min="33060",
        port_max="33060",
        ktap_db_port="33060",
        db_user="mysqld",
        db_version="8",
        client="0.0.0.0/0.0.0.0",
        proc_name="/usr/sbin/mysqld",
        db_install_dir="/var/lib/mysql",
        unix_socket_marker="mysqlx.sock",
        api_target_host="10.10.9.239"
    )
    return None

def t_configure_ssl_for_mongo():
    print("\n Mongo SSL configuration")
    subprocess.run(["mkdir", "-p", "/var/lib/mongo/cert"], check=True)
    subprocess.run(["openssl", "req", '-x509', '-newkey', "rsa:4096", "-keyout", "/var/lib/mongo/cert/key.pem", "-out", "/var/lib/mongo/cert/cert.pem", "-sha256", "-days", "3650", "-nodes", "-subj", "/C=PL/ST=Lubuskie/L=Nowa Sol/O=Training/OU=Demo/CN=mongod"], check=True)
    with open("/var/lib/mongo/cert/both.pem", "w") as f:
        subprocess.run(["cat", "/var/lib/mongo/cert/key.pem", "/var/lib/mongo/cert/cert.pem"], stdout=f, stderr=subprocess.STDOUT, check=True)
    subprocess.run(["chown", "-R", "mongod:mongod", "/var/lib/mongo/cert"], check=True)
    conf = Path("/etc/mongod.conf")
    lines = []
    with conf.open() as f:
        for line in f:
            if re.match(r"^\s*bindIp\s*:", line):
                line = "  bindIp: 0.0.0.0  # Enter 0.0.0.0,:: to bind to all IPv4 and IPv6 addresses or, alternatively, use the net.bindIpAll setting.\n"
                lines.append("  tls:\n")
                lines.append("    mode: requireTLS\n")
                lines.append("    certificateKeyFile: /var/lib/mongo/cert/both.pem\n")
            else:
                lines.append(line)
    conf.write_text("".join(lines))
    subprocess.run(["systemctl", "restart", "mongod"], check=True)
    return None

def t_enable_atap_for_mongo():
    print("\n ATAP setup for postgres on raptor")
    subprocess.run(["mv", "/opt/guardium/etc/guard/root/postgres.conf", "/opt/guardium/etc/guard"], check=True)
    subprocess.run(["/opt/guardium/modules/ATAP/current/files/bin/guardctl", "--db-user=mongod", "--db-home=/usr", "--db-base=/var/lib/mongo", "--db-type=mongodb",     "--db-instance=mongo4", "store-conf"], check=True)
    subprocess.run(["/opt/guardium/modules/ATAP/current/files/bin/guardctl", "authorize-user", "mongod"], check=True)
    subprocess.run(["systemctl", "stop", "mongod"], check=True)
    subprocess.run(["/opt/guardium/modules/ATAP/current/files/bin/guardctl", "--db-instance=mongo4", "activate"], check=True)
    subprocess.run(["systemctl", "start", "mongod"], check=True)
    subprocess.run(["mv", "/opt/guardium/etc/guard/postgres.conf", "/opt/guardium/etc/guard/root"], check=True)
    return None

def t_exit_for_db2_setup(api):
    print("\n Registering db2inst1 user")
    subprocess.run(["/opt/guardium/modules/ATAP/current/files/bin/guardctl", "authorize-user", "db2inst1"], check=True)
    print("\n Stop DB2")
    subprocess.run(["sudo", "-iu", "db2inst1", "db2stop"], check=True)
    print("\n Configure EXIT shared library")
    subprocess.run(["sudo", "-iu", "db2inst1", "mkdir", "-p", "/home/db2inst1/sqllib/security64/plugin/commexit"], check=True)
    subprocess.run(["sudo", "-iu", "db2inst1", "ln", "-fs", "/usr/lib64/libguard_db2_exit_64.so", "/home/db2inst1/sqllib/security64/plugin/commexit/libguard_db2_exit_64.so"], check=True)
    subprocess.run(["sudo", "-iu", "db2inst1", "db2", "update", "dbm", "cfg", "using", "comm_exit_list", "libguard_db2_exit_64"], check=True)
    subprocess.run(["sudo", "-iu", "db2inst1", "db2", "get", "database", "manager", "configuration"], check=True)
    print("\n Start DB2")
    subprocess.run(["sudo", "-iu", "db2inst1", "db2start"], check=True)
    # print("\n Configure DB2 IE for EXIT")
    # subprocess.run(["/opt/guardium/modules/STAP/current/setup_exit.sh", "db2"], check=True)
    print("\n Correcting DB2 Inspection Engine definition")
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    api.delete_inspection_engine(
        stap_host="10.10.9.70",
        type="Db2",
        wait_for_response="1",
        api_target_host="10.10.9.239"
    )
    api.create_inspection_engine(
        stap_host="10.10.9.70",
        protocol="Db2 Exit",
        db_user="db2inst1",
        db_version="11",
        client="0.0.0.0/0.0.0.0",
        proc_name="/home/db2inst1/sqllib/adm/db2sysc",
        db_install_dir="/home/db2inst1",
        api_target_host="10.10.9.239"
    )
    return None

def t_setup_raptor_to_deploy_etap():
    print("\n Installing package requirements")
    subprocess.run(["dnf", "-y", "install", "podman-docker", "skopeo"], check=True)
    print("\n Determine the latest ETAP version")
    result = subprocess.run(["skopeo", "list-tags", "docker://icr.io/guardium/guardium_external_s-tap"], check=True, text=True, capture_output=True)
    etap_versions = json.loads(result.stdout)
    latest = {}
    for t in etap_versions["Tags"]:
        m = re.match(r"^v(\d+\.\d+\.\d+)", t)
        if not m:
            continue
        version_str = m.group(1)
        major, minor, patch = version_str.split(".")
        key = f"{major}.{minor}"
        v = Version(version_str)
        latest[key] = max(latest.get(key, v), v)
    save_to_env("GUARDIUM_ETAP_VERSION", str( latest[get_env_value("GUARDIUM_MINOR_VERSION")]))
    return None

def t_deploy_ca_on_raptor():
    print("\n Create CA directory")
    subprocess.run(["mkdir", "-p", "/root/gn-trainings/ETAP/ca"], check=True)
    print("\n Create CA private key")
    subprocess.run(["openssl", "genrsa", "-out", "/root/gn-trainings/ETAP/ca/ca.key", "2048"], check=True)
    print("\n Generate CA certificate")
    subprocess.run(["openssl", "req", "-x509", "-sha256", "-new", "-key", "/root/gn-trainings/ETAP/ca/ca.key", "-days", "3650", "-out", "/root/gn-trainings/ETAP/ca/ca.pem", "-subj", "/C=PL/O=Demo/OU=Training/CN=Demo Root CA"], check=True)
    return None

def t_create_mysql_csr_for_etap():
    appliance = ApplianceCommand(
        host="10.10.9.239",
        user="cli",
        password=get_env_value("COLLECTOR_PASSWORD"),
        prompt_regex=r">",
        debug=True
    )
    if appliance.connect():
        csr, token, line_above = appliance.generate_external_stap_csr(
        alias="mysql-etap",
        common_name="mysql-etap",
        san1="coll1.gdemo.com"
    )
        file_path = "/root/gn-trainings/ETAP/ca/etap.csr"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(csr)
        save_to_env("ETAP_CSR_ID", line_above)
        save_to_env("ETAP_TOKEN", token)
    appliance.disconnect()
    print("\n Signing CSR by CA")
    subprocess.run(["openssl", "x509", "-sha256", "-req", "-days", "3650", "-CA", "/root/gn-trainings/ETAP/ca/ca.pem", "-CAkey", "/root/gn-trainings/ETAP/ca/ca.key", "-CAcreateserial", "-CAserial", "serial", "-in", "/root/gn-trainings/ETAP/ca/etap.csr", "-out", "/root/gn-trainings/ETAP/ca/etap.pem"], check=True)
    return None

def t_import_etap_ca_cert():
    appliance = ApplianceCommand(
        host="10.10.9.239",
        user="cli",
        password=get_env_value("COLLECTOR_PASSWORD"),
        prompt_regex=r">",
        debug=True
    )

    if appliance.connect():
        # Wczytaj certyfikat CA
        with open("/root/gn-trainings/ETAP/ca/ca.pem") as f:
            ca_cert_pem = f.read()
        
        # Importuj certyfikat
        appliance.import_external_stap_ca_certificate(
            alias="etapca10",
            ca_cert=ca_cert_pem
        )
    
    appliance.disconnect()

def t_import_etap_cert():
    appliance = ApplianceCommand(
    host="10.10.9.239",
    user="cli",
    password=get_env_value("COLLECTOR_PASSWORD"),
    prompt_regex=r">",
    debug=True
)

    if appliance.connect():
    # Wczytaj certyfikat External S-TAP
        with open("/root/gn-trainings/ETAP/ca/etap.pem") as f:
            etap_cert = f.read()
        
        # Importuj certyfikat
        appliance.import_external_stap_certificate(
            alias_line=get_env_value("ETAP_CSR_ID"),
            stap_cert=etap_cert
        )

def t_start_etap():
    etap_host = "10.10.9.70"
    database_port = "3306"
    token = get_env_value("ETAP_TOKEN")
    db_type = "mysql"
    etap_label = "MYSQLETAP"
    collector_ip = "10.10.9.239"
    etap_release = get_env_value("GUARDIUM_ETAP_VERSION")
    listen_port = "63333"

    etap_command = [
        "podman",
        "run",
        "--restart",
        "unless-stopped",
        "--hostname",
        "localhost-gext0-044eb2cb-0b29-4d0f-852b-b4c347831f41",
        "--name",
        "gext0-044eb2cb-0b29-4d0f-852b-b4c347831f41",
        "-d",
        "--shm-size",
        "800M",
        "-e",
        "STAP_CONFIG_TAP_TAP_IP=NULL",
        "-e",
        "STAP_CONFIG_TAP_PRIVATE_TAP_IP=NULL",
        "-e",
        "STAP_CONFIG_TAP_FORCE_SERVER_IP=0",
        "-e",
        "STAP_CONFIG_PROXY_GROUP_UUID=044eb2cb-0b29-4d0f-852b-b4c347831f41",
        "-e",
        "STAP_CONFIG_PROXY_GROUP_MEMBER_COUNT=1",
        "-e",
        f"STAP_CONFIG_PROXY_DB_HOST={etap_host}",
        "-e",
        "STAP_CONFIG_PROXY_NUM_WORKERS=1",
        "-e",
        "STAP_CONFIG_PROXY_PROXY_PROTOCOL=0",
        "-e",
        "STAP_CONFIG_PROXY_DISCONNECT_ON_INVALID_CERTIFICATE=0",
        "-e",
        "STAP_CONFIG_PROXY_NOTIFY_ON_INVALID_CERTIFICATE=0",
        "-e",
        "STAP_CONFIG_PROXY_DETECT_SSL_WITHIN_X_PACKETS=-1",
        "-e",
        f"STAP_CONFIG_DB_0_REAL_DB_PORT={database_port}",
        "-e",
        "STAP_CONFIG_PROXY_LISTEN_PORT=8888",
        "-e",
        "STAP_CONFIG_PROXY_DEBUG=0",
        "-e",
        f"STAP_CONFIG_PROXY_SECRET={token}",
        "-e",
        "STAP_CONFIG_PROXY_CSR_NAME=",
        "-e",
        "STAP_CONFIG_PROXY_CSR_COUNTRY=",
        "-e",
        "STAP_CONFIG_PROXY_CSR_PROVINCE=",
        "-e",
        "STAP_CONFIG_PROXY_CSR_CITY=",
        "-e",
        "STAP_CONFIG_PROXY_CSR_ORGANIZATION=",
        "-e",
        "STAP_CONFIG_PROXY_CSR_KEYLENGTH=2048",
        "-e",
        f"STAP_CONFIG_DB_0_DB_TYPE={db_type}",
        "-e",
        "STAP_CONFIG_PARTICIPATE_IN_LOAD_BALANCING=0",
        "-e",
        f"STAP_CONFIG_TAP_TENANT_ID={etap_label}",
        "-e",
        f"STAP_CONFIG_SQLGUARD_0_SQLGUARD_IP={collector_ip}",
        f"-p={listen_port}:8888/tcp",
        f"icr.io/guardium/guardium_external_s-tap:v{etap_release}"
    ]
    subprocess.run(etap_command, check=True)
    exit(0)
 

def lab1_appliance_setup(state):
    """
    LAB 1 - Konfiguracja appliance (collector).
    """
    
    print("=" * 60)
    print("LAB 1 - Appliance Setup")
    print("=" * 60)
    
    run_task('cli_users_password_change_on_appliances', lambda: t_password_change_on_appliances, state)
    if 'other_collector_settings' not in state["completed_tasks"]:
        appliance = create_appliance('collector_unconfigured')
        if not appliance.connect():
            print("  ✗ Failed to connect to collector")
            return None
        else:
            print("    ✓ Connected to collector - OK")
    
    run_task('initial_collector_settings', lambda: t_initial_collector_settings(appliance), state)
    run_task('restart_collector', lambda: t_restart_system(appliance), state)

    if 'other_collector_settings' not in state["completed_tasks"]:
        appliance = create_appliance('collector_unconfigured')
        if not appliance.connect():
            print("  ✗ Failed to connect to collector")
            return None
        else:
            print("    ✓ Connected to collector - OK")

    run_task('other_collector_settings', lambda: t_other_collector_settings(appliance), state)
   
    if 'other_collector_settings' not in state["completed_tasks"]:
        appliance.disconnect

    appliance = create_appliance('cm')
    if not appliance.connect():
        print("  ✗ Failed to connect to CM")
        return None
    else:
        print("    ✓ Connected to CM - OK")
    
    run_task('initial_cm_settings', lambda: t_initial_cm_settings(appliance), state)
    
    appliance.disconnect

    api = GuardiumRestAPI(
        base_url='https://10.10.9.219:8443',
        client_id='BOOTCAMP'
    )
    
    run_task('create_demo_user', lambda: t_create_demo_user(api), state)
    run_task('register_collector', lambda: t_register_collector(api), state)
    run_task('prepare_appliances_for_patching', lambda: t_preparing_appliances_for_patching(api), state)

    print(f"\nRegister patches on appliances and start patching process")
    for appliance_name, appliance_ip, password, task_number in [('cm', '10.10.9.219', get_env_value('CM_PASSWORD'), 'register_patches_on_cm'), ('collector', '10.10.9.239', get_env_value('COLLECTOR_PASSWORD'), 'register_patches_on_collector')]:
        run_task(task_number, lambda: t_registering_patches_installation(appliance_name, appliance_ip, password), state)

    print("\nMonitoring patch installation on appliances")
    for appliance_name, task_number in [('cm', 'monitor_patch_installation_on_cm'), ('collector', 'monitor_patch_installation_on_collector')]:
        run_task(task_number, lambda: t_monitoring_patch_installation(appliance_name), state)

    run_task('policy_installation_on_collector', lambda: t_install_policy_on_collector(api), state)
    
    print("\n" + "=" * 60)
    print("LAB 1 - Appliance Setup completed!")
    print("=" * 60)
    
    return None
    
def lab2_gim(state):
    """
    LAB 2 - Konfiguracja GIM (Group Identity Management).
    
    Args:
        appliance: Opcjonalny połączony obiekt ApplianceCommand
    
    Returns:
        appliance: Połączony obiekt ApplianceCommand lub None w przypadku błędu
    """
    print("=" * 60)
    print("LAB 2 - GIM Setup")
    print("=" * 60)

    api = GuardiumRestAPI(
        base_url='https://10.10.9.219:8443',
        client_id='BOOTCAMP'
    )

    run_task('resolving_collector_on_raptor', lambda: t_set_collector_resolving_on_raptor(), state)

    run_task('getting_gim_files', lambda: t_getting_gim_files(), state)

    run_task('import_gim_files_on_cm', lambda: t_import_gim_modules(api), state) 

    print("\n" + "=" * 60)
    print("Lab 2 completed!")
    print("=" * 60)

def lab4_atap(state):
    print("=" * 60)
    print("LAB 4 - ATAP")
    print("=" * 60)

    run_task('installing psql on raptor', lambda: t_postgres_installation(), state)

    run_task('create postgres admin users', lambda: t_create_postgres_admin_users(), state)

    run_task('install gim client on raptor', lambda: t_install_gim_on_raptor(), state)

    api = GuardiumRestAPI(
        base_url='https://10.10.9.219:8443',
        client_id='BOOTCAMP'
    )

    run_task('install_stap_on_raptor', lambda: t_install_stap_on_raptor(api), state)

    run_task('configure_atap_for_postgres_on_raptor', lambda: t_enable_atap_for_postgres_on_raptor(), state)
    
    api = GuardiumRestAPI(
        base_url='https://10.10.9.219:8443',
        client_id='BOOTCAMP'
    )

    run_task('Correct mysql IE\'s', lambda: t_correct_mysql_ie(api), state)

    run_task('Configure SSL for Mongo', lambda: t_configure_ssl_for_mongo(), state)

    run_task('Enable ATAP for Mongo', lambda: t_enable_atap_for_mongo(), state)


    print("\n" + "=" * 60)
    print("Lab 4 completed!")
    print("=" * 60)

def lab5_exit(state):
    print("=" * 60)
    print("LAB 5 - EXIT")
    print("=" * 60)

    api = GuardiumRestAPI(
        base_url='https://10.10.9.219:8443',
        client_id='BOOTCAMP'
    )

    run_task('Setup EXIT for DB2 on raptor', lambda: t_exit_for_db2_setup(api), state)

    print("\n" + "=" * 60)
    print("Lab 5 completed!")
    print("=" * 60)

def lab7_etap(state):
    print("=" * 60)
    print("LAB 7 - ETAP")
    print("=" * 60)

    api = GuardiumRestAPI(
        base_url='https://10.10.9.219:8443',
        client_id='BOOTCAMP'
    )
    run_task('Setup EXIT for DB2 on raptor', lambda: t_setup_raptor_to_deploy_etap(), state)

    run_task('Deploy CA on raptor', lambda: t_deploy_ca_on_raptor(), state)

    run_task('Create CSR for ETAP for mysql', lambda: t_create_mysql_csr_for_etap(), state)

    run_task('Import CA cert for ETAP', lambda: t_import_etap_ca_cert(), state)

    run_task('Import mysql ETAP cert', lambda: t_import_etap_cert(), state)

    run_task('Start mysql ETAP on raptor', lambda: t_start_etap(), state)

    print("\n" + "=" * 60)
    print("Lab 7 completed!")
    print("=" * 60)

def lab8_va(state):
    print("=" * 60)
    print("LAB 7 - ETAP")
    print("=" * 60)



    print("\n" + "=" * 60)
    print("Lab 7 completed!")
    print("=" * 60)


def sync_lab(state, skip_below: int = 0, stop_at: int = 999):
    """
    Główna funkcja synchronizacji laboratorium.
    
    Args:
        skip_below: Pomiń LAB-y o numerze mniejszym niż podana wartość (domyślnie 0 - wykonaj wszystkie)
        stop_at: Zatrzymaj się po wykonaniu LAB-a o podanym numerze (domyślnie 999 - wykonaj wszystkie)
    """

    print(state)
    appliance = None
    parameter = 1
    
    # LAB 1: Appliance Setup
    if skip_below < 1 and stop_at >= 1:
        lab1_appliance_setup(state)
        print("\n" + "=" * 60)
        print("LAB 1 completed!")
        print("=" * 60)
        if stop_at == 1:
            print("\n[INFO] Zatrzymano po LAB 1 (--stop-at=1)")
            return
    elif skip_below >= 1:
        print("\n[LAB 1] SKIPPED - Appliance setup (--skip-below)")
    else:
        print("\n[LAB 1] SKIPPED - Appliance setup (--stop-at)")
    
    # LAB 2: GIM Setup
    if skip_below < 2 and stop_at >= 2:
        lab2_gim(state)
        print("\n" + "=" * 60)
        print("LAB 2 completed!")
        print("=" * 60)
        if stop_at == 2:
            print("\n[INFO] Zatrzymano po LAB 2 (--stop-at=2)")
            return
    elif skip_below >= 2:
        print("\n[LAB 2] SKIPPED - GIM setup (--skip-below)")
    else:
        print("\n[LAB 2] SKIPPED - GIM setup (--stop-at)")
    
    # LAB 3: Tutaj dodasz kolejny lab
    if skip_below < 3 and stop_at >= 3:
        print("\n[LAB 3] SKIPPED")
        if stop_at == 3:
            print("\n[INFO] Zatrzymano po LAB 3 (--stop-at=3)")
            return
    else:
        print("LAB 3 does not modify final environment")

    # LAB 4: ATAP
    if skip_below < 4 and stop_at >= 4:
        lab4_atap(state)
        print("\n" + "=" * 60)
        print("LAB 4 completed!")
        print("=" * 60)
        if stop_at == 4:
            print("\n[INFO] Zatrzymano po LAB 4 (--stop-at=4)")
            return
    elif skip_below >= 4:
        print("\n[LAB 4] SKIPPED - ATAP (--skip-below)")
    else:
        print("\n[LAB 4] SKIPPED - ATAP (--stop-at)")

    # LAB 5: EXIT
    if skip_below < 5 and stop_at >= 5:
        lab5_exit(state)
        print("\n" + "=" * 60)
        print("LAB 5 completed!")
        print("=" * 60)
        if stop_at == 4:
            print("\n[INFO] Stopped after LAB 5 (--stop-at=5)")
            return
    elif skip_below >= 5:
        print("\n[LAB 4] SKIPPED - EXIT (--skip-below)")
    else:
        print("\n[LAB 4] SKIPPED - EXIT (--stop-at)")

    if skip_below < 6 and stop_at >= 6:
        print("\n[LAB 6] SKIPPED")
        if stop_at == 6:
            print("\n[INFO] Zatrzymano po LAB 6 (--stop-at=6)")
            return
    else:
        print("LAB 6 focuses on UC 1.0 which will withdrawn in the future. There is no API to automate UC 1.0 configuration. Will decide later to automate some steps from this lab later")

    # LAB 7: ETAP
    if skip_below < 7 and stop_at >= 7:
        lab7_etap(state)
        print("\n" + "=" * 60)
        print("LAB 7 completed!")
        print("=" * 60)
        if stop_at == 7:
            print("\n[INFO] Stopped after LAB 7 (--stop-at=7)")
            return
    elif skip_below >= 7:
        print("\n[LAB 7] SKIPPED - EXIT (--skip-below)")
    else:
        print("\n[LAB 7] SKIPPED - EXIT (--stop-at)")

    # LAB 8: VA
    if skip_below < 8 and stop_at >= 8:
        lab8_va(state)
        print("\n" + "=" * 60)
        print("LAB 8 completed!")
        print("=" * 60)
        if stop_at == 8:
            print("\n[INFO] Stopped after LAB 8 (--stop-at=8)")
            return
    elif skip_below >= 8:
        print("\n[LAB 8] SKIPPED - EXIT (--skip-below)")
    else:
        print("\n[LAB 8] SKIPPED - EXIT (--stop-at)")


if __name__ == "__main__":
    import argparse

    STATE_FILE = "state.json"
    state = load_state()


    parser = argparse.ArgumentParser(description="Sync Lab - synchronizacja środowiska laboratoryjnego")
    parser.add_argument(
        "--skip-below",
        type=int,
        default=0,
        help="Pomiń LAB-y o numerze mniejszym niż podana wartość (domyślnie 0 - wykonaj wszystkie)"
    )
    parser.add_argument(
        "--stop-at",
        type=int,
        default=999,
        help="Zatrzymaj się po wykonaniu LAB-a o podanym numerze (domyślnie 999 - wykonaj wszystkie)"
    )
    
    args = parser.parse_args()
    
    try:
        sync_lab(state, skip_below=args.skip_below, stop_at=args.stop_at)
    except KeyboardInterrupt:
        print("\n\n[INFO] Przerwano przez użytkownika")
    except Exception as e:
        print(f"\n[ERROR] Błąd: {e}")
        import traceback
        traceback.print_exc()




