#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sync Lab - orkiestracja synchronizacji środowiska laboratoryjnego
"""

import os
import re
import time
import json
import paramiko
from dotenv import load_dotenv
from appliance_command import ApplianceCommand, change_password_as_root, scp_file_as_root
from guardium_rest_api import GuardiumRestAPI
from typing import Any, Dict, List, Optional
import urllib.request
import sys
import traceback
import zipfile
import glob




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
        'password': get_env_value('COLLECTOR_PASSWORD')
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
    
    return ApplianceCommand(
        host=appliance_config['host'],
        user=common_config['user'],
        password=appliance_config['password'],
        prompt_regex=appliance_config['prompt_regex'],
        initial_pattern=common_config['initial_pattern'],
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


def lab1_appliance_setup(appliance=None):
    """
    LAB 1 - Konfiguracja appliance (collector).
    
    Returns:
        appliance: Połączony obiekt ApplianceCommand lub None w przypadku błędu
    """
    print("=" * 60)
    print("LAB 1 - Appliance Setup")
    print("=" * 60)
    
    print("\n[LAB 1.1] Password change for cli user on appliances")
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
    
    print("\n[LAB 1.2] Connect to collector and get network settings")
    appliance = create_appliance('collector_unconfigured')
    if not appliance.connect():
        print("  ✗ Failed to connect to collector")
        return None
    else:
        print("    ✓ OK")
    print(appliance.execute_command("show network interface all"))
    print(appliance.execute_command("show network route default"))
    print(appliance.execute_command("show network resolvers"))
    
    print("\n[LAB 1.3] Disabling purge")
    output = appliance.execute_command("grdapi diable_purge")
    print("    ✓ OK")

    print("\n[LAB 1.4 Set time zone to Europe/Warsaw")
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
    
    print("\n[LAB 1.5 Configure NTP servers")
    appliance.execute_command("store system time_server hostname 0.pool.ntp.org 1.pool.ntp.org 2.pool.ntp.org")
    print(appliance.execute_command("show system time_server all"))
    print("  Enabling time synchronization...")
    appliance.execute_command("store system time_server state on")
    print(appliance.execute_command("show system time_server all"))
    print("    ✓ OK")
    
    print("\n[LAB 1.6] Restart system")
    result = appliance.execute_restart_with_check()
    print(f"  {result}")
    appliance.disconnect()
    
    if "System is restarting - connection broke" in result:
        print("\n[LAB 1.7] Waiting for system availability...")
        appliance = wait_for_appliance('collector_unconfigured')
        print("  ✓ Appliance available")
    else:
        print("  ✗ Could not restart - MYSQL is busy")
        print("  ✗ Run script again in 1 minute or restart collector manually and then start again")
        return None
    
    print("\n[LAB 1.8] Setup collector name and domain")
    appliance.execute_command("store system hostname coll1")
    appliance.execute_command("store system domain gdemo.com")
    print("  ✓ Collector name set")
    
    print("\n[LAB 1.9] Configure session timeouts")
    appliance.execute_command("store gui session_timeout 9999")
    appliance.execute_command("store timeout cli_session 600")
    print("  ✓ Timeouts configured")
   
    print("\n[LAB 1.10] Restart GUI")
    appliance.execute_command_with_confirmation(
        command="restart gui",
        response="y",
        confirmation_pattern=r"Are you sure you want to restart GUI\s*\(y/n\)\?"
    )
    print("  ✓ GUI restarted")

    print("\n[LAB 1.11] Set shared secret on collector")
    appliance.execute_command("store system shared secret guardium")
    print("  ✓ Shared Secret set")

    print("\n[LAB 1.12] Set manual hosts settings")
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

    appliance.disconnect

    print("\n[LAB 1.13] Connect to Central Manager")
    appliance = create_appliance('cm')
    if not appliance.connect():
        print("  ✗ Failed to connect to CM")
        return None
    else:
        print("    ✓ OK")

    print("\n[LAB 1.14] Create oauth client for bootcamp sync")
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

    print("\n[LAB 1.15] Set shared secret on Central Manager")
    appliance.execute_command("store system shared secret guardium")
    print("  ✓ Shared Secret set")

    appliance.disconnect

    api = GuardiumRestAPI(
        base_url='https://10.10.9.219:8443',
        client_id='BOOTCAMP'
    )
    print("\n[LAB 1.16] Create demo user")
    try:
        token = api.get_token(username='accessmgr', password=get_env_value('ACCESSMGR_PASSWORD'))
        print(f"Access token: {token}")
  
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
        print("\n[LAB 1.17] Register collector to central manager")
        units = api.get_registered_units()
        units = parse_mus_from_message_dict(units)
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
        return appliance
    
    except Exception as e:
        print(f"  ✗ Error: {e}")
        import traceback
        traceback.print_exc()

    print("\n[LAB 1.18] Download and unpack patches locally")
    target_dir = "/root/gn-trainings/appliance-patches"
    if not os.path.isdir(target_dir):
        os.makedirs(target_dir, exist_ok=True)
        filename = os.path.join(target_dir, os.path.basename("patches.zip"))
        urllib.request.urlretrieve(get_env_value("PATCH_ARCHIVE"), filename)
        with zipfile.ZipFile(filename, "r") as zipf:
                zipf.extractall(path=target_dir)
        print(f"  ✓ Patches extracted")
    else:
        print(f"  ✓ Patches already extracted")

    print("\n[LAB 1.19] Copying patches to central manager")
    patch_files = glob.glob('/root/gn-trainings/appliance-patches/patches/*.sig')
    
    if not patch_files:
        print("  ✗ No patch files found in /root/gn-trainings/appliance-patches/patches/")
        exit(1)
    
    print(f"  Found {len(patch_files)} patch files to copy")
    all_success = True
    for patch_file in patch_files:
        success = scp_file_as_root(
            host='10.10.9.219',
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
        
        print("\n[LAB 1.20] Changing ownership of patches to tomcat:tomcat")
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname='10.10.9.219',
                username='root',
                password=get_env_value("ROOT_PASSWORD"),
                look_for_keys=False,
                allow_agent=False
            )
            stdin, stdout, stderr = client.exec_command('chown tomcat:tomcat /var/log/guard/patches/*.sig')
            exit_status = stdout.channel.recv_exit_status()
            if exit_status == 0:
                print(f"  ✓ Ownership changed to tomcat:tomcat")
            else:
                error = stderr.read().decode()
                print(f"  ✗ Failed to change ownership: {error}")
                exit(1)
            client.close()
        except Exception as e:
            print(f"  ✗ Error changing ownership: {e}")
            exit(1)
    else:
        print("  ✗ Problem with copying of patches to central manager")
        exit(1)

    print("\n" + "=" * 60)
    print("LAB 2 completed!")
    print("=" * 60)
    

def lab2_gim(appliance=None):
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
    
    print("\n[LAB 1.21] Register patches on cm")
    appliance = create_appliance('collector')
    if not appliance.connect():
        print("  ✗ Failed to connect to collector")
        return None
    result = appliance.execute_command("show system patch available")
    print(result)


    
    print("\n" + "=" * 60)
    print("All labs completed!")
    print("=" * 60)



def sync_lab(skip_below: int = 0):
    """
    Główna funkcja synchronizacji laboratorium.
    
    Args:
        skip_below: Pomiń LAB-y o numerze mniejszym niż podana wartość (domyślnie 0 - wykonaj wszystkie)
    """
    appliance = None
    
    # LAB 1: Appliance Setup
    if skip_below < 1:
        appliance = lab1_appliance_setup()
        if appliance:
            appliance.disconnect()
            appliance = None
    else:
        print("\n[LAB 1] SKIPPED - Appliance setup")
    
    # LAB 2: GIM Setup
    if skip_below < 2:
        appliance = lab2_gim(appliance)
        if appliance:
            appliance.disconnect()
            appliance = None
    else:
        print("\n[LAB 2] SKIPPED - GIM setup")
    
    # LAB 3: Tutaj dodasz kolejny lab
    if skip_below < 3:
        # print("\n[LAB 3] ...")
        pass
    else:
        print("\n[LAB 3] SKIPPED")
    
    print("\n" + "=" * 60)
    print("LAB 1 completed!")
    print("=" * 60)
    



if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Sync Lab - synchronizacja środowiska laboratoryjnego")
    parser.add_argument(
        "--skip-below",
        type=int,
        default=0,
        help="Pomiń LAB-y o numerze mniejszym niż podana wartość (domyślnie 0 - wykonaj wszystkie)"
    )
    
    args = parser.parse_args()
    
    try:
        sync_lab(skip_below=args.skip_below)
    except KeyboardInterrupt:
        print("\n\n[INFO] Przerwano przez użytkownika")
    except Exception as e:
        print(f"\n[ERROR] Błąd: {e}")
        import traceback
        traceback.print_exc()
