#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sync Lab - orkiestracja synchronizacji środowiska laboratoryjnego
"""

#from pexpect.FSM import Error
from subprocess import SubprocessError
import psycopg2
#from paramiko.proxy import subprocess
import os
import re
import time
import json
import paramiko
from dotenv import load_dotenv
from appliance_command import ApplianceCommand, change_password_as_root, scp_file_as_root, run_many_commands_remotely
from manual_web_ui_processing import guardium_customer_upload_import
from guardium_patch import install_patch
from windows_management import run_winrm
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
import pwd
from databases import get_oracle_conn, run_sql_oracle


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

def run_as_user(argv, user, *, check=True, **kwargs):
    pw = pwd.getpwnam(user)
    uid, gid = pw.pw_uid, pw.pw_gid
    home = pw.pw_dir

    def demote():
        # ustaw grupę i uid procesu dziecka
        os.setgid(gid)
        os.setuid(uid)
        # opcjonalnie: czyść umask / env itp.

    env = dict(os.environ)
    env["HOME"] = home
    env["USER"] = user
    env["LOGNAME"] = user

    return subprocess.run(
        argv,
        check=check,
        env=env,
        preexec_fn=demote,
        **kwargs
    )

common_config = {
    'user': 'cli',
    'initial_pattern': 'Last login',
    'timeout': 120
}

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

def monitor_gim_module_installation(api, client_ip):
    pending = ["initial"]  # Inicjalizacja aby wejść do pętli
    while pending:
        modules = api.gim_list_client_modules(client_ip=client_ip)
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
        if unit_data and 'Message' in unit_data:
            unit_data = parse_unit_summary(unit_data['Message'])
            print(unit_data)
        else:
            print(f"  ⚠ Uncexpected answer from API: {unit_data}")
        print("  Unit type:")
        try:
            result = appliance.execute_command("show unit type")
            print(f"    {result}")
        except (TimeoutError, OSError):
            pass  # Ignoruj timeout, kontynuuj
        print(f"  ✓ Collector registered ")
    else:
        unit_data = api.get_unit_data(api_target_host='10.10.9.239')
        if unit_data and 'Message' in unit_data:
            unit_data = parse_unit_summary(unit_data['Message'])
            print(unit_data)
        else:
            print(f"  ⚠ Incorrect API answer: {unit_data}")
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

    time.sleep(10)

    print("\n S-TAP installation monitoring")

    monitor_gim_module_installation(api, "10.10.9.70")

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
            alias="etapca",
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

def t_configure_raptor_for_va():
    print("\n postgres package installation to enable some features")
    subprocess.run(["dnf", "-y", "install", "postgresql-contrib"], check=True)

    print("\n Create sqlguard user")
    conn = psycopg2.connect(dbname="postgres", user= "postgres", password="guardium", host="localhost", port=5432)
    cur = conn.cursor()
    cur.execute(f"CREATE USER sqlguard WITH ENCRYPTED PASSWORD '{get_env_value('DEFAULT_SERVICE_PASSWORD')}';")
    cur.execute(f"CREATE GROUP gdmmonitor;")
    conn.commit()
    cur.execute(f"ALTER GROUP gdmmonitor ADD USER sqlguard;")
    cur.execute(f"GRANT pg_read_all_settings TO gdmmonitor;")
    cur.execute(f"GRANT SELECT ON pg_authid TO gdmmonitor;")
    cur.execute(f"CREATE EXTENSION IF NOT EXISTS pgcrypto;")
    cur.close()
    conn.close()

    print("\nDownload DPS archive")
    target_dir = "/root/gn-trainings"
    os.makedirs(target_dir, exist_ok=True)
    filename = os.path.join(target_dir, os.path.basename("dps.zip"))
    urllib.request.urlretrieve(get_env_value("DPS_ZIP_ARCHIVE"), filename)
    print("\nExtract DPS file")
    with zipfile.ZipFile(filename, "r") as zipf:
            zipf.extractall(path=target_dir)
            print(f"  ✓ DPS downloaded and unpacked")

def t_import_DPS():
    print("\nConfigure playwright browsers")
    subprocess.run(["playwright", "install"], check=True)

    print("\nStart DPS import")
    guardium_customer_upload_import(
        login_url='https://10.10.9.219:8443',
        username='demo',
        password=get_env_value("DEMOUSER_PASSWORD"),
        file_to_upload=f'/root/gn-trainings/{get_env_value("DPS_NAME")}.enc',
        headless=True
    )

def t_import_va_process_for_postgres(api):
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    print("\n Import Vulnerability Assessment process")
    result = api.import_definitions('guardium_definition_files/exp_security_assessment_va_postgres.sql')
    print(f"  ✓ VA process imported")

def t_setup_vascanner():
    print(f"\nCreate API key for vascanner")
    appliance = create_appliance('cm')
    if not appliance.connect():
        print(f"  ✗ Failed to connect to cm")
        return None
    output = appliance.execute_command("grdapi create_api_key name=vascanner")
    match = re.search(r"Encoded API key:\s*([A-Za-z0-9+/=_-]+)", output)
    if not match:
        print(f"  ✗ Failed to extract API key from output")
        return None
    api_key = match.group(1)
    print(f"  ✓ API key extracted: {api_key}")
    print("\nPull vascanner image on hana")
    result=run_many_commands_remotely(host='10.10.9.60', password=get_env_value("HANA_PASSWORD"), commands=["mkdir -p /root/gn-trainings/vascanner/certs", f"podman login cp.icr.io -u cp -p {get_env_value('IBM_REGISTRY_KEY')} && podman pull cp.icr.io/cp/ibm-guardium-data-security-center/guardium/{get_env_value('VASCANNER_IMAGE_TAG')}", "podman images --format '{{.ID}}'"])
    va_image_id = result[2]['stdout'].strip()
    print("\nPrepare vascanner config file")
    subprocess.run(["cp", "guardium_configuration_files/vascanner_config", "guardium_configuration_files/config"], check=True)
    with open('guardium_configuration_files/config', 'a') as f:
        subprocess.run(["echo", f"\nCLIENT_API_KEY={api_key}", ], stdout=f, text=True, check=True)
    print("\nCopy vascanner file to hana machine")
    scp_file_as_root(host='10.10.9.60', root_password=get_env_value("HANA_PASSWORD"), local_path='guardium_configuration_files/config', remote_path='/root/gn-trainings/vascanner/config')
    print("\nCopy cm certificate to hana machine")
    scp_file_as_root(host='10.10.9.60', root_password=get_env_value("HANA_PASSWORD"), local_path='guardium_configuration_files/vascanner.pem', remote_path='/root/gn-trainings/vascanner/certs/vascanner.pem')
    print("\nRun vascanner container on hana")
    result=run_many_commands_remotely(host='10.10.9.60', password=get_env_value("HANA_PASSWORD"), commands=[f"podman run --network host -d --replace --env-file /root/gn-trainings/vascanner/config --name va-scanner-hana -v /root/gn-trainings/vascanner/certs:/var/vascanner/certs {va_image_id}"])
    print(result)

def t_install_gim_on_winsql():
    print("\n Run GIM client on winsql")
    res = run_winrm(
        host="10.10.9.59",
        username=r".\administrator",
        password=get_env_value("WINSQL_PASSWORD"),
        command= ("New-Item -ItemType Directory -Force -Path 'GIM_Client' | Out-Null; Invoke-WebRequest -Uri 'https://ibm.box.com/shared/static/w26pu9sm69l6ysr2xklvoh9nkxgah23b.zip' -OutFile 'GIM_Client\\GIM_install.zip'; Expand-Archive -Force -Path 'GIM_Client\\GIM_install.zip' -DestinationPath 'GIM_Client\\'; & '.\\GIM_Client\\Setup.exe' -UNATTENDED -APPLIANCE 10.10.9.219 -LOCALIP 10.10.9.59"),
        command_type="ps",
        transport="ntlm",
        use_ssl=False,  # HTTP
    )

def t_install_stap_on_winsql(api):
    print("\n WINSTAP installation schedule")
    time.sleep(60)
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    api.gim_client_assign(
        client_ip="10.10.9.59",
        module="WINSTAP",
        module_version="12.2_r120201205_1"
    )
    api.gim_client_params(
        client_ip="10.10.9.59",
        param_name="WINSTAP_SQLGUARD_IP",
        param_value="10.10.9.239"
    )
    api.gim_schedule_install(
        client_ip="10.10.9.59",
        date="now",
    )
    
    print("\n WINSTAP installation monitoring")
    monitor_gim_module_installation(api, "10.10.9.59")

def t_enable_fam_on_raptor(api):
    print("\n Set FAM settings")
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    api.gim_client_params(
        client_ip="10.10.9.70",
        param_name="STAP_FAM_ENABLED",
        param_value="1"
    )
    api.gim_client_params(
        client_ip="10.10.9.70",
        param_name="STAP_FAM_INSTALLED",
        param_value="1"
    )
    api.gim_schedule_install(
        client_ip="10.10.9.70",
        date="now",
    )
    # time.sleep(10)
    print("\n Monitoring is a FAM enabled")
    monitor_gim_module_installation(api, "10.10.9.70")
    
    print("\nEnable root account monitoring")
    subprocess.run(["sed", "-i", r"s/^fam_protect_privileged[[:space:]]*=.*/fam_protect_privileged=1/", "/opt/guardium/modules/STAP/current/guard_tap.ini"], check=True)
    subprocess.run(["/opt/guardium/modules/STAP/current/guard-config-update", "--restart", "stap"], check=True)

def t_install_enable_fam_on_winsql(api):
    print("\n Set FAM settings")
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    api.gim_client_assign(
        client_ip="10.10.9.59",
        module="FAMMONITOR",
        module_version="12.2_r120201205_1"
    )
    api.gim_client_params(
        client_ip="10.10.9.59",
        param_name="FAMMONITOR_SQLGUARD_IP",
        param_value="10.10.9.239"
    )
    api.gim_client_params(
        client_ip="10.10.9.59",
        param_name="FAMMONITOR_FAM_PROTECT_PRIVILEGED",
        param_value="1"
    )
    api.gim_schedule_install(
        client_ip="10.10.9.59",
        date="now",
    )
    time.sleep(10)

    print("\n Monitoring is a FAM enabled")
    monitor_gim_module_installation(api, "10.10.9.59")

def t_import_fam_definitions(api):
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    print("\n Import FAM policy")
    result = api.import_definitions('guardium_definition_files/exp_raptor_fam_policy.sql')
    print("\n Import FAM dashboard")
    result = api.import_definitions('guardium_definition_files/exp_dashboard_fam.sql')
    print(f"  ✓ Definitions imported")
    
def t_install_fam_policy(api):
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    print("\n Install FAM policy")
    result = api.install_policy("Log Everything|raptor FAM policy", api_target_host="10.10.9.239")
    print(f"  ✓ FAM policy installed")

def t_configure_env_for_oracle(api):
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    print("\n Setup oracle user settings")
    run_as_user(["bash", "-c", r'mkdir -p ~/.sqlcl && printf "%s\n" "SET SQLFORMAT ansiconsole" > "$HOME/.sqlcl/login.sql" && printf "%s\n" "export SQLPATH=.:$HOME/.sqlcl/" >> "$HOME/.bashrc"'], user="oracle", text=True)
    print("\n Import Oracle dashboard")
    result = api.import_definitions('guardium_definition_files/exp_dashboard_oracle.sql')
    print("\n Add missing IE definition")
    api.create_inspection_engine(
        stap_host="10.10.9.70",
        protocol="oracle",
        port_min="1521",
        port_max="1521",
        ktap_db_port="1521",
        db_user="oracle",
        db_version="19",
        client="0.0.0.0/0.0.0.0",
        proc_name="/opt/oracle/product/19c/dbhome_1/bin/oracle",
        db_install_dir="/home/oracle",
        unix_socket_marker="EXTPROC2",
        api_target_host="10.10.9.239"
    )

def t_setup_SSL_for_oracle():
    print("\n Create server wallet")
    run_as_user(["mkdir", "-p", "/opt/oracle/product/19c/dbhome_1/wallet"], user="oracle", text=True)
    run_as_user(["/opt/oracle/product/19c/dbhome_1/bin/orapki", "wallet", "create", "-wallet", "/opt/oracle/product/19c/dbhome_1/wallet", "-auto_login_local", "-pwd", f"'{get_env_value("DEMOUSER_PASSWORD")}'"], user="oracle", text=True)
    print("\n Add self-sign certificate to server wallet")
    run_as_user(["/opt/oracle/product/19c/dbhome_1/bin/orapki", "wallet", "add", "-wallet", r'/opt/oracle/product/19c/dbhome_1/wallet', "-dn", r'CN=raptor.gdemo.com', "-keysize", "2048", "-self_signed", "-validity", "3650", "-pwd", f"'{get_env_value("DEMOUSER_PASSWORD")}'"], user="oracle", text=True)
    print("\n Create client wallet")
    run_as_user(["mkdir", "-p", "/opt/oracle/product/19c/dbhome_1/client_wallet"], user="oracle", text=True)
    run_as_user(["/opt/oracle/product/19c/dbhome_1/bin/orapki", "wallet", "create", "-wallet", "/opt/oracle/product/19c/dbhome_1/client_wallet", "-auto_login_local", "-pwd", f"'{get_env_value("DEMOUSER_PASSWORD")}'"], user="oracle", text=True)
    print("\n Add self-sign certificate to client wallet")
    run_as_user(["/opt/oracle/product/19c/dbhome_1/bin/orapki", "wallet", "add", "-wallet", r'/opt/oracle/product/19c/dbhome_1/client_wallet', "-dn", r'CN=client', "-keysize", "2048", "-self_signed", "-validity", "3650", "-pwd", f"'{get_env_value("DEMOUSER_PASSWORD")}'"], user="oracle", text=True)
    print("\n Export public keys")
    run_as_user(["/opt/oracle/product/19c/dbhome_1/bin/orapki", "wallet", "export", "-wallet", r'/opt/oracle/product/19c/dbhome_1/wallet', "-dn", r'CN=raptor.gdemo.com', "-cert", "/tmp/server-cert.crt", "-pwd", f"'{get_env_value("DEMOUSER_PASSWORD")}'"], user="oracle", text=True)
    run_as_user(["/opt/oracle/product/19c/dbhome_1/bin/orapki", "wallet", "export", "-wallet", r'/opt/oracle/product/19c/dbhome_1/client_wallet', "-dn", r'CN=client', "-cert", "/tmp/client-cert.crt", "-pwd", f"'{get_env_value("DEMOUSER_PASSWORD")}'"], user="oracle", text=True)
    print("\n Import public keys")
    run_as_user(["/opt/oracle/product/19c/dbhome_1/bin/orapki", "wallet", "add", "-wallet", r'/opt/oracle/product/19c/dbhome_1/client_wallet', "-trusted_cert", "-cert", "/tmp/server-cert.crt", "-pwd", f"'{get_env_value("DEMOUSER_PASSWORD")}'"], user="oracle", text=True)
    run_as_user(["/opt/oracle/product/19c/dbhome_1/bin/orapki", "wallet", "add", "-wallet", r'/opt/oracle/product/19c/dbhome_1/wallet', "-trusted_cert", "-cert", "/tmp/client-cert.crt", "-pwd", f"'{get_env_value("DEMOUSER_PASSWORD")}'"], user="oracle", text=True)
    run_as_user(["rm", "/tmp/server-cert.crt", "/tmp/client-cert.crt"], user="oracle", text=True)

    print("\nChange listener configuration")
    subprocess.run(["cp", "-f", "guardium_configuration_files/listener.ora", "/opt/oracle/product/19c/dbhome_1/network/admin/listener.ora"], check=True)
    subprocess.run(["cp", "-f", "guardium_configuration_files/tnsnames.ora", "/opt/oracle/product/19c/dbhome_1/network/admin/tnsnames.ora"], check=True)
    subprocess.run(["cp", "-f", "guardium_configuration_files/sqlnet.ora", "/opt/oracle/product/19c/dbhome_1/network/admin/sqlnet.ora"], check=True)
    subprocess.run(["chown", "-R", "oracle:oinstall", "/opt/oracle/product/19c/dbhome_1/network/admin/"], check=True)

    print("\n Restart listener")
    run_as_user(["bash","-lc", "/opt/oracle/product/19c/dbhome_1/bin/lsnrctl reload"], user="oracle", text=True)

def t_setup_ATAP_for_oracle():
    print("\n Stop oracle instance")
    run_as_user(["bash","-lc", "/opt/oracle/product/19c/dbhome_1/bin/lsnrctl stop"], user="oracle", text=True)
    run_as_user(["bash","-lc", r"$ORACLE_HOME/bin/dbshut $ORACLE_HOME"], user="oracle", text=True)
    print("\n ATAP setup for oracle on raptor")
    subprocess.run(["/opt/guardium/modules/ATAP/current/files/bin/guardctl", "--db-user=oracle", "--db-home=/opt/oracle/product/19c/dbhome_1", "--db-base=/home/oracle", "--db-type=oracle", "--db-instance=ORCLDB", "--db-version=19", "store-conf"], check=True)
    subprocess.run(["/opt/guardium/modules/ATAP/current/files/bin/guardctl", "authorize-user", "oracle"], check=True)
    subprocess.run(["/opt/guardium/modules/ATAP/current/files/bin/guardctl", "--db-type=oracle --db-instance=ORCLDB", "activate"], check=True)
    print("\n Start oracle instance")
    run_as_user(["bash","-lc", r"$ORACLE_HOME/bin/dbstart $ORACLE_HOME"], user="oracle", text=True)
    run_as_user(["bash","-lc", "/opt/oracle/product/19c/dbhome_1/bin/lsnrctl stop"], user="oracle", text=True)

def t_deploy_oracle_in_container_on_hana():
    print("\n Download and setup Oracle 21c container on hana")
    unpack_cmd = "bash -lc 'gunzip -k /home/oracle19_oua_image.tar.gz 2>/dev/null || true'"
    result=run_many_commands_remotely(host='10.10.9.60', password=get_env_value("HANA_PASSWORD"),
    commands=[
        f"wget -q {get_env_value('ORACLE_OUA_IMAGE')} -O /home/oracle19_oua_image.tar.gz",
        unpack_cmd,
        f"rm -f /home/oracle19_oua_image.tar.gz",
        "podman load -qi /home/oracle19_oua_image.tar",
        f"rm -f /home/oracle19_oua_image.tar"
    ])

    print("\n Setup oracle container on hana")
    result=run_many_commands_remotely(host='10.10.9.60', password=get_env_value("HANA_PASSWORD"),
    commands=[
        "mkdir -p /home/oradata",
        "chown -R 54321:54321 /home/oradata",
        "chmod -R 775 /home/oradata",
        "semanage fcontext -a -t container_file_t '/home/oradata(/.*)?'",
        "restorecon -Rv /home/oradata"
    ])

    print("\n Starting oracle container on hana")
    result=run_many_commands_remotely(host='10.10.9.60', password=get_env_value("HANA_PASSWORD"),
    commands=[
        f"podman run -d --name oracle_db_21c -p 1521:1521 -p 5500:5500 -e ORACLE_EDITION=EE -e ORACLE_SID=ORCL  -e ORACLE_PDB=ORCLPDB1  -e ORACLE_CHARACTERSET=AL32UTF8 -e ORACLE_SERVICE_NAME=ORCLPDB1.localdomain -v /home/oradata:/opt/oracle/oradata -e ORACLE_PWD='{get_env_value("DEFAULT_SERVICE_PASSWORD")}' oracle/database:21.3.0-ee-oua"
    ])
    interval_sec = 30
    timeout_sec = 1800
    deadline = time.time() + timeout_sec
    last_out = None
    print("\n Monitoring first start of oracle container on hana")
    while time.time() < deadline:
        res=run_many_commands_remotely(host='10.10.9.60', password=get_env_value("HANA_PASSWORD"),
            commands=[r"podman logs oracle_db_21c 2>&1 | grep -F 'DATABASE IS READY TO USE' | wc -l"],
        )[0]
        out = (res.get("stdout") or "").strip()
        err = (res.get("stderr") or "").strip()
        rc = res.get("rc")
        last_out = out

        # Jeśli chcesz logować status:
        print(f"rc={rc} out={out!r} err={err[:120]!r}")
        # out powinno być liczbą (wynik wc -l)
        try:
            count = int(out) if out else 0
        except ValueError:
            count = 0
        if count >= 1:
            print("✅ Found readiness marker in logs. Exiting loop.")
            break
        time.sleep(interval_sec)
    else:
        raise TimeoutError(
            f"Timeout after {timeout_sec}s waiting for log marker. Last stdout={last_out!r}"
    )

def t_create_oracle_csr_for_etap():
    appliance = ApplianceCommand(
        host="10.10.9.239",
        user="cli",
        password=get_env_value("COLLECTOR_PASSWORD"),
        prompt_regex=r">",
        debug=True
    )
    if appliance.connect():
        csr, token, line_above = appliance.generate_external_stap_csr(
        alias="oracle-etap",
        common_name="oracle-etap",
        san1="coll1.gdemo.com"
    )
        file_path = "/root/gn-trainings/ETAP/ca/etap2.csr"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(csr)
        save_to_env("ETAP_CSR_ID", line_above)
        save_to_env("ETAP_TOKEN_ORACLE", token)
    appliance.disconnect()
    print("\n Signing CSR by CA")
    subprocess.run(["openssl", "x509", "-sha256", "-req", "-days", "3650", "-CA", "/root/gn-trainings/ETAP/ca/ca.pem", "-CAkey", "/root/gn-trainings/ETAP/ca/ca.key", "-CAcreateserial", "-CAserial", "serial", "-in", "/root/gn-trainings/ETAP/ca/etap2.csr", "-out", "/root/gn-trainings/ETAP/ca/etap2.pem"], check=True)
    return None

def t_import_oracle_etap_cert():
    appliance = ApplianceCommand(
    host="10.10.9.239",
    user="cli",
    password=get_env_value("COLLECTOR_PASSWORD"),
    prompt_regex=r">",
    debug=True
    )   

    if appliance.connect():
    # Wczytaj certyfikat External S-TAP
        with open("/root/gn-trainings/ETAP/ca/etap2.pem") as f:
            etap_cert = f.read()
        
        # Importuj certyfikat
        appliance.import_external_stap_certificate(
            alias_line=get_env_value("ETAP_CSR_ID"),
            stap_cert=etap_cert
        )

def t_start_oracle_etap():
    etap_host = "10.10.9.60"
    database_port = "1521"
    token = get_env_value("ETAP_TOKEN_ORACLE")
    db_type = "oracle"
    etap_label = "ORACLEETAP"
    collector_ip = "10.10.9.239"
    etap_release = get_env_value("GUARDIUM_ETAP_VERSION")
    listen_port = "64444"

    etap_command = [
        "podman",
        "run",
        "--restart",
        "unless-stopped",
        "--name",
        "oracle-etap",
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
        "STAP_CONFIG_PROXY_GROUP_UUID=df7c55b1-a8ba-45e5-a3e8-271d17f0068a",
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
    time.sleep(10)
    print("\n ETAP stopped for other part of lab")
    subprocess.run(["podman", "stop", "oracle-etap"], check=True)

def t_setup_oracle_traffic_generator():
    password = get_env_value("DEFAULT_SERVICE_PASSWORD")
    commands = [
        {"cmd": ["mkdir", "-p", "/root/gn-trainings/dbtraffic"]},
        {"cmd": ["/usr/bin/python3.12", "-m", "venv", ".venv"], "cwd" : "/root/gn-trainings/dbtraffic"},
        {"cmd": ["/root/gn-trainings/dbtraffic/.venv/bin/python3", "-m", "pip", "install", "--upgrade", "pip"], "cwd" : "/root/gn-trainings/dbtraffic"},
        {"cmd": ["/root/gn-trainings/dbtraffic/.venv/bin/pip3", "install", "oracledb", "psycopg2_binary", "faker"], "cwd" : "/root/gn-trainings/dbtraffic"},
        {"cmd": ["wget", "https://ibm.box.com/shared/static/dcm5st6jt4w6ippvkz3ka5ebvb47gymi.zip", "-O", "dbtraffic.zip"], "cwd" : "/root/gn-trainings/dbtraffic"},
        {"cmd": ["unzip", "dbtraffic.zip"], "cwd" : "/root/gn-trainings/dbtraffic"},
        {"cmd": ["sed", "-i", f"s|^password *=.*|password = {password}|", "/root/gn-trainings/dbtraffic/files/config.cfg"]},
        {"cmd": ["/root/gn-trainings/dbtraffic/.venv/bin/python3", "./gn_dbtraffic.py", "schema"], "cwd" : "/root/gn-trainings/dbtraffic"}
    ]
    for c in commands:
        subprocess.run(
            c["cmd"],
            cwd=c.get("cwd"),
            check=True
        )

def t_setup_OUA_on_oracle_on_hana():
    print("\n Create secadmin and guardium users")
    conn =  get_oracle_conn(user="system", password=get_env_value('DEFAULT_SERVICE_PASSWORD'), host="10.10.9.60", port=1521, service_name="ORCLPDB1")
    run_sql_oracle(conn, 'CREATE USER secadmin IDENTIFIED BY "{}"'.format(get_env_value('DEFAULT_SERVICE_PASSWORD')))
    run_sql_oracle(conn, 'CREATE USER guardium IDENTIFIED BY "{}"'.format(get_env_value('DEFAULT_SERVICE_PASSWORD')))
    conn.commit()
    run_sql_oracle(conn, "grant CONNECT, SELECT ANY DICTIONARY, SELECT_CATALOG_ROLE, AUDIT_ADMIN, CREATE PROCEDURE, DROP ANY PROCEDURE, AUDIT SYSTEM, AUDIT ANY, CREATE JOB to SECADMIN")
    run_sql_oracle(conn, "GRANT CONNECT, RESOURCE to guardium")
    run_sql_oracle(conn, "GRANT SELECT ANY DICTIONARY TO guardium")
    run_sql_oracle(conn, r"BEGIN DBMS_NETWORK_ACL_ADMIN.APPEND_HOST_ACE(host => 'localhost', ace => xs$ace_type(privilege_list => xs$name_list('connect', 'resolve'), principal_name => 'guardium', principal_type => xs_acl.ptype_db)); END;")
    conn.commit()
    conn.close()

    print("\n Setup access to OUA records")
    conn =  get_oracle_conn(user="secadmin", password=f"{get_env_value('DEFAULT_SERVICE_PASSWORD')}", host="10.10.9.60", port=1521, service_name="ORCLPDB1")
    run_sql_oracle(conn, r"BEGIN DECLARE v_cnt NUMBER; BEGIN SELECT COUNT(*) INTO v_cnt FROM audit_unified_policies WHERE policy_name='GAME_APP'; IF v_cnt=0 THEN EXECUTE IMMEDIATE 'CREATE AUDIT POLICY GAME_APP ACTIONS ALL ON game.customers, ALL ON game.credit_cards, ALL ON game.transactions, ALL ON game.extras, ALL ON game.features'; END IF; EXECUTE IMMEDIATE 'AUDIT POLICY GAME_APP'; END; END;")
    run_sql_oracle(conn, r"BEGIN DBMS_SCHEDULER.create_job(job_name=>'ENSURE_GAME_APP_AUDIT', job_type=>'STORED_PROCEDURE', job_action=>'ENSURE_GAME_APP_AUDIT', repeat_interval=>'FREQ=MINUTELY;INTERVAL=45', enabled=>TRUE); END;")
    conn.commit()

    policies = run_sql_oracle(conn, "SELECT POLICY_NAME FROM AUDIT_UNIFIED_ENABLED_POLICIES", fetch=True)
    if policies:
        for policy in policies:
            print(policy)
    else:
        pass
    conn.close()

def t_install_stap_on_hana(api):
    # print("\n Installing oracle instant client on hana")
    # result=run_many_commands_remotely(host='10.10.9.60', password=get_env_value("HANA_PASSWORD"), commands=[
    #     "wget -O oracle-instantclient-basic-21.12.0.0.0-1.el9.x86_64.rpm https://ibm.box.com/shared/static/6kyb3ivksqvv26bfnz2ckrojw2b34bhg.rpm",
    #     "dnf -y install ./oracle-instantclient-basic-21.12.0.0.0-1.el9.x86_64.rpm",
    #     "rm -f ./oracle-instantclient-basic-21.12.0.0.0-1.el9.x86_64.rpm"
    # ])
    # print("\n Copy files from raptor to hana")
    # scp_file_as_root(host='10.10.9.60', root_password=get_env_value("HANA_PASSWORD"),  local_path="/root/gn-trainings/gim_installers/guard-bundle-GIM-12.2.0.0_r121306_v12_2_1-rhel-9-linux-x86_64.gim.sh", remote_path=".")
    # scp_file_as_root(host='10.10.9.60', root_password=get_env_value("HANA_PASSWORD"),  local_path="guardium_configuration_files/tnsnames_hana.ora", remote_path="/usr/lib/oracle/21/client64/lib/network/admin/tnsnames.ora")
    # print("\n Install gim client on hana")
    # run_many_commands_remotely(host='10.10.9.60', password=get_env_value("HANA_PASSWORD"), commands=[
    #     "./guard-bundle-GIM-12.2.0.0_r121306_v12_2_1-rhel-9-linux-x86_64.gim.sh -- --dir /opt/guardium --tapip 10.10.9.60 --sqlguardip 10.10.9.219 -q"
    # ])
    # print("\n Install STAP on hana")
    # time.sleep(60)
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    # api.gim_client_assign(
    #     client_ip="10.10.9.60",
    #     module="BUNDLE-STAP",
    #     module_version="12.2.0.0_r121306_5"
    # )
    # api.gim_client_params(
    #     client_ip="10.10.9.60",
    #     param_name="KTAP_ENABLED",
    #     param_value="0"
    # )
    # api.gim_client_params(
    #     client_ip="10.10.9.60",
    #     param_name="STAP_SQLGUARD_IP",
    #     param_value="10.10.9.239"
    # )
    # api.gim_schedule_install(
    #     client_ip="10.10.9.60",
    #     date="now",
    # )

    # print("\n STAP installation monitoring")
    # monitor_gim_module_installation(api, "10.10.9.60")

    # print("\n Configure STAP to support OUA monitoring")
    # run_many_commands_remotely(host='10.10.9.60', password=get_env_value("HANA_PASSWORD"), commands=[
    #     "sed -i 's|^sqlc_properties_dir=.*|sqlc_properties_dir=/usr/lib/oracle/21/client64/lib/network/admin|' /opt/guardium/modules/STAP/current/guard_tap.ini",
    #     "sed -i 's|^ld_library_paths=.*|ld_library_paths=/usr/lib/oracle/21/client64/lib|' /opt/guardium/modules/STAP/current/guard_tap.ini",
    #     "/opt/guardium/modules/STAP/current/guard-config-update --restart STAP"
    # ])
    
    # print("\n Add oracle user credentials to get access to OUA records")
    # api.store_sql_credentials(password=get_env_value("DEFAULT_SERVICE_PASSWORD"), username="guardium", stap_host='10.10.9.60', api_target_host='10.10.9.239')

    print("\n Adding OUA configuration")
    print(api.create_sql_configuration(b_type="Oracle", instance="ORCLPDB1", stap_host='10.10.9.60', username='guardium', api_target_host='10.10.9.239'))
    exit(0)
    
def lab11_oracle(state):
    """
    LAB 11 - Oracle
    """
    api = GuardiumRestAPI(
        base_url='https://10.10.9.219:8443/',
        client_id='BOOTCAMP'
    )
    
    run_task('Configure system for oracle lab', lambda: t_configure_env_for_oracle(api), state)

    run_task('Configure SSL support for oracle on raptor', lambda: t_setup_SSL_for_oracle(), state)

    run_task('Configure ATAP for oracle on raptor', lambda: t_setup_ATAP_for_oracle(), state)

    run_task('Deploy Oracle in container on hana', lambda: t_deploy_oracle_in_container_on_hana(), state)

    run_task('Create CSR for ETAP for oracle in container', lambda: t_create_oracle_csr_for_etap(), state)

    run_task('Import ETAP for oracle in container certificate', lambda: t_import_oracle_etap_cert(), state)

    run_task('Start oracle ETAP', lambda: t_start_oracle_etap(), state)

    run_task('Traffic generator for Oracle', lambda: t_setup_oracle_traffic_generator(), state)

    run_task('Confgure OUA to monitor application', lambda: t_setup_OUA_on_oracle_on_hana(), state)

    run_task('Install STAP on hana', lambda: t_install_stap_on_hana(api), state)

    

  





    
    

def lab10_fam(state):
    """
    LAB 10 - FAM
    """
    api = GuardiumRestAPI(
        base_url='https://10.10.9.219:8443/',
        client_id='BOOTCAMP'
    )
    
    run_task('Enable FAM on raptor', lambda: t_enable_fam_on_raptor(api), state)

    run_task('Enable FAM on winsql', lambda: t_install_enable_fam_on_winsql(api), state)

    run_task('Import FAM definitions', lambda: t_import_fam_definitions(api), state)

    run_task('Install FAM policy on collector', lambda: t_install_fam_policy(api), state)

def lab9_winstap(state):
    """
    LAB 9 - WINSTAP
    """

    api = GuardiumRestAPI(
        base_url='https://10.10.9.219:8443/',
        client_id='BOOTCAMP'
    )
    
    run_task('Install GIM client on winsql', lambda: t_install_gim_on_winsql(), state)

    run_task('Install STAP on winsql', lambda: t_install_stap_on_winsql(api), state)

def lab8_va(state):
    """
    LAB 8 - VA
    """

    run_task('Configure raptor for VA', lambda: t_configure_raptor_for_va(), state)

    run_task('Configure VA scanner', lambda: t_setup_vascanner(), state)

    api = GuardiumRestAPI(
        base_url='https://10.10.9.219:8443/',
        client_id='BOOTCAMP'
    )
    
    run_task('Import VA process for postgres', lambda: t_import_va_process_for_postgres(api), state)

    run_task('Import DPS', lambda: t_import_DPS(), state)

def lab7_etap(state):
    """
    LAB 7 - ETAP
    """

    api = GuardiumRestAPI(
        base_url='https://10.10.9.219:8443',
        client_id='BOOTCAMP'
    )
    run_task('Setup raptor for ETAP', lambda: t_setup_raptor_to_deploy_etap(), state)

    run_task('Deploy CA on raptor', lambda: t_deploy_ca_on_raptor(), state)

    run_task('Create CSR for ETAP for mysql', lambda: t_create_mysql_csr_for_etap(), state)

    run_task('Import CA cert for ETAP', lambda: t_import_etap_ca_cert(), state)

    run_task('Import mysql ETAP cert', lambda: t_import_etap_cert(), state)

    run_task('Start mysql ETAP on raptor', lambda: t_start_etap(), state)

def lab5_exit(state):
    """
    LAB 5 - EXIT
    """

    api = GuardiumRestAPI(
        base_url='https://10.10.9.219:8443',
        client_id='BOOTCAMP'
    )

    run_task('Setup EXIT for DB2 on raptor', lambda: t_exit_for_db2_setup(api), state)

def lab4_atap(state):
    """
    LAB 4 - ATAP
    """

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

def lab2_gim(state):
    """
    LAB 2 - Konfiguracja GIM (Group Identity Management).
    
    Args:
        appliance: Opcjonalny połączony obiekt ApplianceCommand
    
    Returns:
        appliance: Połączony obiekt ApplianceCommand lub None w przypadku błędu
    """

    api = GuardiumRestAPI(
        base_url='https://10.10.9.219:8443',
        client_id='BOOTCAMP'
    )

    run_task('resolving_collector_on_raptor', lambda: t_set_collector_resolving_on_raptor(), state)

    run_task('getting_gim_files', lambda: t_getting_gim_files(), state)

    run_task('import_gim_files_on_cm', lambda: t_import_gim_modules(api), state)

def lab1_appliance_setup(state):
    """
    LAB 1 - Konfiguracja appliance (collector).
    """
    
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

    appliance = None
    if 'other_collector_settings' not in state["completed_tasks"]:
        appliance = create_appliance('collector_unconfigured')
        if not appliance.connect():
            print("  ✗ Failed to connect to collector")
            return None
        else:
            print("    ✓ Connected to collector - OK")

        run_task('other_collector_settings', lambda: t_other_collector_settings(appliance), state)
   
        if appliance:
            appliance.disconnect()

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
    
    return None

def sync_lab(state, skip_below: int = 0, stop_at: int = 999):
    """
    Główna funkcja synchronizacji laboratorium.
    
    Args:
        skip_below: Pomiń LAB-y o numerze mniejszym niż podana wartość (domyślnie 0 - wykonaj wszystkie)
        stop_at: Zatrzymaj się po wykonaniu LAB-a o podanym numerze (domyślnie 999 - wykonaj wszystkie)
    """

    print(state)
    
    # Konfiguracja LAB-ów: (numer, funkcja, nazwa, opis)
    labs_config = [
        (1, lab1_appliance_setup, "Appliance Setup", "Appliance setup"),
        (2, lab2_gim, "GIM Setup", "GIM setup"),
        (3, None, "SKIPPED", "LAB 3 does not modify final environment"),
        (4, lab4_atap, "ATAP", "ATAP"),
        (5, lab5_exit, "EXIT", "EXIT"),
        (6, None, "UC 1.0", "LAB 6 focuses on UC 1.0 which will withdrawn in the future. There is no API to automate UC 1.0 configuration. Will decide later to automate some steps from this lab later"),
        (7, lab7_etap, "ETAP", "ETAP"),
        (8, lab8_va, "VA", "VA"),
        (9, lab9_winstap, "WINSTAP", "WINSTAP"),
        (10, lab10_fam, "FAM", "FAM"),
        (11, lab11_oracle, "Oracle", "Oracle"),

    ]
    
    # Iteracja przez wszystkie LAB-y
    for lab_num, lab_func, lab_name, lab_desc in labs_config:
        if skip_below < lab_num and stop_at >= lab_num:
            if lab_func is not None:
                # Wykonaj LAB
                lab_func(state)
                print("\n" + "=" * 60)
                print(f"LAB {lab_num} completed!")
                print("=" * 60)
            else:
                # LAB pominięty (None)
                print(f"\n[LAB {lab_num}] SKIPPED")
                print(lab_desc)
            
            # Sprawdź czy zatrzymać się po tym LAB-ie
            if stop_at == lab_num:
                print(f"\n[INFO] Zatrzymano po LAB {lab_num} (--stop-at={lab_num})")
                return
        elif skip_below >= lab_num:
            print(f"\n[LAB {lab_num}] SKIPPED - {lab_name} (--skip-below)")
        else:
            print(f"\n[LAB {lab_num}] SKIPPED - {lab_name} (--stop-at)")


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




