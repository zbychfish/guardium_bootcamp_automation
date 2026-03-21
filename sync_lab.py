#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sync Lab - orkiestracja synchronizacji środowiska laboratoryjnego
"""

import os
import re
import time
from dotenv import load_dotenv
from appliance_command import ApplianceCommand, change_password_as_root

# Załaduj zmienne środowiskowe z pliku .env
load_dotenv()


def get_env_password(key: str) -> str:
    """Pobiera hasło ze zmiennych środowiskowych"""
    password = os.getenv(key)
    if not password:
        raise ValueError(f"Hasło dla {key} nie zostało znalezione w pliku .env")
    return password



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
        'password': get_env_password('COLLECTOR_PASSWORD')
    },
    'collector_unconfigured': {
        'host': '10.10.9.239',
        'prompt_regex': r'guard\.yourcompany\.com>',
        'password': get_env_password('COLLECTOR_PASSWORD')
    },
    'cm': {
        'host': '10.10.9.219',
        'prompt_regex': r'cm\.gdemo\.com>',
        'password': get_env_password('CM_PASSWORD')
    },
    'toolnode': {
        'host': '10.10.9.229',
        'prompt_regex': r'toolnode\.gdemo\.com>',
        'password': get_env_password('TOOLNODE_PASSWORD')
    }
}

managed_machines: dict[str, dict[str, str]] = {
    'raptor': {
        'host': '10.10.9.70',
        'prompt_regex': r'raptor\.gdemo\.com>',
        'password': get_env_password('RAPTOR_PASSWORD')
    },
    'hana': {
        'host': '10.10.9.60',
        'prompt_regex': r'hana\.gdemo\.com>',
        'password': get_env_password('HANA_PASSWORD')
    },
    'winsql': {
        'host': '10.10.9.59',
        'prompt_regex': r'winsql\.gdemo\.com>',
        'password': get_env_password('WINSQL_PASSWORD')
    },
    'appnode': {
        'host': '10.10.9.50',
        'prompt_regex': r'appnode\.gdemo\.com>',
        'password': get_env_password('APPNODE_PASSWORD')
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


# Przykład użycia
print("Lab 1 - appliance setup")
print("---------------------------")
print("\n[INFO] Password change for cli user on appliances")
current_appliances = appliances.copy()
del current_appliances['collector']
for name, cfg in current_appliances.items():
    print(f"\n[INFO] Changing password on {name} ({cfg['host']})")
    ok = change_password_as_root(
        host=cfg["host"],
        root_password=get_env_password("ROOT_PASSWORD"),
        target_user="cli",
        new_password=get_env_password("COLLECTOR_PASSWORD")
    )
    print("  OK" if ok else "  FAILED")

appliance = create_appliance('collector_unconfigured')
print("\n[INFO] Get current network settings of collector")
if appliance.connect():
    print(appliance.execute_command("show network interface all"))
    print(appliance.execute_command("show network route default"))
    print(appliance.execute_command("show network resolvers"))
    print("\n[INFO] Set manual hosts settings")
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
        # jeśli para (IP, host) już istnieje w output → pomiń
        if (ip, prompt_host) in existing:
            continue
        command = f'support store hosts {cfg["host"]} {prompt_host}'
        # print(command)
        appliance.execute_command(command)
    print(appliance.execute_command("support show hosts"))
    print("\n[INFO] Set time zone on collector to Europe/Warsaw")
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
        print(f"\n[INFO] Time zone already set to {timezone}")
    print(f"\n[INFO] Setting public NTP servers")
    appliance.execute_command("store system time_server hostname 0.pool.ntp.org 1.pool.ntp.org 2.pool.ntp.org")
    print(appliance.execute_command("show system time_server all"))
    print(f"\n[INFO] Time synchronization is switching on")
    appliance.execute_command("store system time_server state on")
    print(appliance.execute_command("show system time_server all"))
    print(f"\n[INFO] Time synchronization switched on")
    result = appliance.execute_restart_with_check()
    print(result)
    appliance.disconnect()
    if "System is restarting" in result:
        print("\n[INFO] System restarted waiting for its availability...")
        appliance = wait_for_appliance('collector_unconfigured')
        print("[INFO] Appliance available, can continue ...")
        # Tutaj możesz kontynuować konfigurację po restarcie
        print("[INFO] Set collector hostname to coll1")
        result = appliance.execute_command("store system hostname coll1")
        print("[INFO] Set collector domain to gdemo.com")
        result = appliance.execute_command("store system domain gdemo.com")
        print("[INFO] Show unit type")
        result = appliance.execute_command("show unit type")
        print(result)
        print("[INFO] Set sessions timeouts")
        result = appliance.execute_command("store gui session_timeout 9999")
        result = appliance.execute_command("store timeout cli_session 600")
        print("[INFO] Restart GUI")
        appliance.execute_command_with_confirmation(
            command="restart gui",
            response="y",
            confirmation_pattern=r"Are you sure you want to restart GUI\s*\(y/n\)\?")
    else:
        print("\n[INFO] I could not restart appliance because MYSQL is busy, check it or restart task in a while ...")
        
        

