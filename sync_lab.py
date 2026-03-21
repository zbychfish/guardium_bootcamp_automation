#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sync Lab - orkiestracja synchronizacji środowiska laboratoryjnego
"""

from appliance_command import ApplianceCommand


# Wspólna konfiguracja dla wszystkich appliance
common_config = {
    'user': 'cli',
    'initial_pattern': 'Last login',
    'timeout': 120
}

#appliances_resolving =[('cm.gdemo.com', '10.10.9.219'), ('coll1.gdemo.com', '10.10.9.239'), ('guard', '10.10.9.239'), ('cm', '10.10.9.219'), ('cm_unconfigured', '10.10.9.219'), ('guard', '10.10.9.239'), ('toolnode.gdemo.com', '10.10.9.229')]


# Konfiguracja specyficzna dla każdego appliance
appliances = {
    'collector': {
        'host': '10.10.9.239',
        'prompt_regex': r'coll1\.gdemo\.com>',
        'password': 'Guardium123!'
    },
    'collector_unconfigured': {
        'host': '10.10.9.239',
        'prompt_regex': r'guard\.yourcompany\.com>',
        'password': 'Guardium123!'
    },
    'cm': {
        'host': '10.10.9.219',
        'prompt_regex': r'cm\.gdemo\.com>',
        'password': 'Guardium123!'
    },
    'toolnode': {
        'host': '10.10.9.229',
        'prompt_regex': r'toolnode\.gdemo\.com>',
        'password': 'Guardium123!'
    }
}

managed_machines: dict[str, dict[str, str]] = {
    'raptor': {
        'host': '10.10.9.70',
        'prompt_regex': r'raptor\.gdemo\.com>',
        'password': 'Guardium123!'
    },
    'hana': {
        'host': '10.10.9.60',
        'prompt_regex': r'hana\.gdemo\.com>',
        'password': 'Guardium123!'
    },
    'winsql': {
        'host': '10.10.9.59',
        'prompt_regex': r'winsql\.gdemo\.com>',
        'password': 'gdptraining'
    },
    'appnode': {
        'host': '10.10.9.50',
        'prompt_regex': r'appnode\.gdemo\.com>',
        'password': 'Guardium123!'
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
print("Get current network settings")

appliance = create_appliance('collector_unconfigured')

if appliance.connect():
    print(appliance.execute_command("show network interface all"))
    print(appliance.execute_command("show network route default"))
    print(appliance.execute_command("show network resolvers"))
    print(appliance.execute_command("support show hosts"))
    current_appliances = appliances
    del current_appliances['collector_unconfigured']
    machines = current_appliances | managed_machines
    for machine, cfg in machines.items():
        print("support store hosts", cfg['host'], cfg['prompt_regex'].replace("\\", ""))
       
    appliance.disconnect()
