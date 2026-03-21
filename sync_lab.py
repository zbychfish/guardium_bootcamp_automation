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

# Konfiguracja specyficzna dla każdego appliance
appliances = {
    'collector': {
        'host': '10.10.9.239',
        'prompt_regex': r'coll1\.gdemo\.com>',
        'password': 'Guardium123!'
    },
    'collector_unconfigured': {
        'host': '10.10.9.239',
        'prompt_regex': r'coll1\.gdemo\.com>',
        'password': 'guardium'
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

appliance = create_appliance('collector')

if appliance.connect():
    print(appliance.execute_command("show network interface all"))
    print(appliance.execute_command("show network route default"))
    print(appliance.execute_command("show network resolvers"))
    appliance.disconnect()
