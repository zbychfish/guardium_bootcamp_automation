#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sync Lab - orkiestracja synchronizacji środowiska laboratoryjnego
"""

from appliance_command import ApplianceCommand


# Konfiguracja
config = {
    'host': '10.10.9.239',
    'user': 'cli',
    'password': 'Guardium123!',
    'prompt_regex': r'coll1\.gdemo\.com>',
    'initial_pattern': 'Last login',
    'timeout': 120
}

# Utworzenie instancji
appliance = ApplianceCommand(
    host=config['host'],
    user=config['user'],
    password=config['password'],
    prompt_regex=config['prompt_regex'],
    initial_pattern=config['initial_pattern'],
    timeout=config['timeout']
)

# Połączenie
if appliance.connect():
    # Wykonanie polecenia
    output = appliance.execute_command("support show hosts")
    print(output)
    
    # Rozłączenie
    appliance.disconnect()

# Made with Bob
