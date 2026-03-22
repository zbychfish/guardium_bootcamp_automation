#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test Guardium Patch Installation - standalone test script
"""

from guardium_patch import install_patch
from dotenv import load_dotenv
import os

# Załaduj zmienne środowiskowe
load_dotenv()

def test_patch_install():
    """Testowa instalacja patcha"""
    host = '10.10.9.219'
    username = 'cli'
    password = "Guardium123!"
    
    if not password:
        print("ERROR: CM_PASSWORD not found in .env")
        return
    
    output = install_patch(
        host=host,
        username=username,
        password=password,
        patch_selection="2",
        reinstall_answer="y",
        live_log=True  # W teście zawsze pokazuj output
    )
    
    if output:
        print("\n=== Installation successful ===")
    else:
        print("\n=== Installation failed ===")


if __name__ == "__main__":
    test_patch_install()

# Made with Bob