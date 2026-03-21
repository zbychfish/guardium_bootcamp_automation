#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sync Lab - orkiestracja synchronizacji środowiska laboratoryjnego
"""

import os
import re
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


# Przykład użycia
print("Lab 1 - appliance setup")
print("---------------------------")
print("Password change for cli user on appliances")
current_appliances = appliances.copy()
del current_appliances['collector']
for name, cfg in current_appliances.items():
    print(f"Changing password on {name} ({cfg['host']})")
    ok = change_password_as_root(
        host=cfg["host"],
        root_password=get_env_password("ROOT_PASSWORD"),
        target_user="cli",
        new_password=get_env_password("COLLECTOR_PASSWORD")
    )
    print("  OK" if ok else "  FAILED")

appliance = create_appliance('collector_unconfigured')
print("Get current network settings of collector")
if appliance.connect():
    print(appliance.execute_command("show network interface all"))
    print(appliance.execute_command("show network route default"))
    print(appliance.execute_command("show network resolvers"))
    print("Set manual hosts settings")
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
    print("Set time zone on collector to Europe/Warsaw")
    print(appliance.execute_command("show system clock all"))
    appliance.disconnect()
