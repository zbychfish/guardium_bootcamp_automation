#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sync Lab - orkiestracja synchronizacji środowiska laboratoryjnego
"""

from paramiko.proxy import subprocess
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
        except TimeoutError:
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
    print("All labs completed!")
    print("=" * 60)

def lab4_atap(state):
    print("=" * 60)
    print("LAB 2 - GIM Setup")
    print("=" * 60)


    print("\n Postgres 16 installation")
    subprocess.run(["dnf", "-y", "install", "@postgresql:16"], check=True)
    print("\n Postgres database initialization")
    subprocess.run(["postgresql-setup", "--initdb", '--unit', 'postgresql'], check=True)
    print("\n Enable postgres service")
    subprocess.run(["systemctl", "enable", 'postgresql.service'], check=True)
    print("\n Set postgres user password")
    subprocess.run(["chpasswd"], input=f"postgres:{get_env_value('DEFAULT_SERVICE_PASSWORD')}", text=True, check=True)
    print("\n Create certificate for postgres")
    subprocess.run(["openssl", "req", "-new", "-x509", "-days", "365", "-nodes", "-text", "-out", "/var/lib/pgsql/data/pgsql.crt", "-keyout", "/var/lib/pgsql/data/pgsql.key", "-subj", '"/CN=raptor.demo.com"'], check=True)
    subprocess.run(["chown", "postgres:postgres", "/var/lib/pgsql/data/pgsql.*"], check=True)



    print("\n" + "=" * 60)
    print("All labs completed!")
    print("=" * 60)

def sync_lab(state, skip_below: int = 0):
    """
    Główna funkcja synchronizacji laboratorium.
    
    Args:
        skip_below: Pomiń LAB-y o numerze mniejszym niż podana wartość (domyślnie 0 - wykonaj wszystkie)
    """

    print(state)
    appliance = None
    parameter = 1
    # LAB 1: Appliance Setup
    if skip_below < 1:
        lab1_appliance_setup(state)
        print("\n" + "=" * 60)
        print("LAB 1 completed!")
        print("=" * 60)
    else:
        print("\n[LAB 1] SKIPPED - Appliance setup")
    
    # LAB 2: GIM Setup
    if skip_below < 2:
        lab2_gim(state)
        print("\n" + "=" * 60)
        print("LAB 2 completed!")
        print("=" * 60)
    else:
        print("\n[LAB 2] SKIPPED - GIM setup")
    
    # LAB 3: Tutaj dodasz kolejny lab
    if skip_below < 3:
        print("\n[LAB 3] SKIPPED")

    if skip_below < 4:
        lab4_atap(state)
        print("\n" + "=" * 60)
        print("LAB 2 completed!")
        print("=" * 60)
    else:
        print("\n[LAB 4] SKIPPED")

    


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
    
    args = parser.parse_args()
    
    try:
        sync_lab(state, skip_below=args.skip_below)
    except KeyboardInterrupt:
        print("\n\n[INFO] Przerwano przez użytkownika")
    except Exception as e:
        print(f"\n[ERROR] Błąd: {e}")
        import traceback
        traceback.print_exc()




