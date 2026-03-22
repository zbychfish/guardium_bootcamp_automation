#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prosty test instalacji patcha - bez użycia klasy ApplianceCommand
"""

import paramiko
import time
import sys
import re
from dotenv import load_dotenv
import os

# Załaduj zmienne środowiskowe
load_dotenv()

def strip_ansi(text):
    """Usuwa kody ANSI z tekstu"""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

def test_patch_install():
    """Testowa instalacja patcha z live output"""
    
    host = '10.10.9.219'
    username = 'cli'
    password = os.getenv('CM_PASSWORD')
    
    print(f"Connecting to {host}...")
    
    # Połącz się
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        client.connect(
            hostname=host,
            username=username,
            password=password,
            look_for_keys=False,
            allow_agent=False
        )
        
        # Otwórz interaktywny kanał
        channel = client.invoke_shell()
        channel.settimeout(0.1)
        
        print("Connected! Waiting for prompt...")
        
        # Czekaj na prompt systemowy
        buf = ""
        prompt_found = False
        timeout = time.time() + 30
        
        while time.time() < timeout:
            try:
                chunk = channel.recv(4096).decode('utf-8', errors='replace')
                if chunk:
                    buf += chunk
                    print(strip_ansi(chunk), end='', flush=True)
                    
                    # Sprawdź czy jest prompt (cm.gdemo.com> lub inne)
                    buf_clean = strip_ansi(buf)
                    if "cm.gdemo.com>" in buf_clean or ".com>" in buf_clean or "grdadmin>" in buf_clean:
                        prompt_found = True
                        break
            except:
                time.sleep(0.1)
        
        if not prompt_found:
            print("\n\nERROR: Prompt not found!")
            return
        
        print("\n\n=== Prompt found! Sending command: store system patch install sys ===\n")
        time.sleep(0.5)
        
        # Wyślij polecenie
        channel.send(b"store system patch install sys\r")
        
        # Czytaj output na żywo
        buf = ""
        patch_selected = False
        reinstall_answered = False
        
        while True:
            try:
                chunk = channel.recv(4096).decode('utf-8', errors='replace')
                if chunk:
                    buf += chunk
                    # Wyświetl na żywo
                    print(strip_ansi(chunk), end='', flush=True)
                    
                    buf_clean = strip_ansi(buf)
                    
                    # Sprawdź czy jest pytanie o wybór patcha
                    if not patch_selected and ("Please choose patches" in buf_clean or "or q to quit" in buf_clean):
                        # Sprawdź czy linia kończy się dwukropkiem (pytanie jest kompletne)
                        last_line = buf_clean.strip().split('\n')[-1]
                        if last_line.endswith(':'):
                            # Poczekaj jeszcze chwilę aby upewnić się że to koniec pytania
                            time.sleep(1.0)
                            # Sprawdź czy nie ma więcej danych
                            try:
                                extra = channel.recv(4096).decode('utf-8', errors='replace')
                                if extra:
                                    buf += extra
                                    print(strip_ansi(extra), end='', flush=True)
                            except:
                                pass
                            
                            print("\n>>> Sending patch selection: 2 <<<", flush=True)
                            channel.send(b"2\r")
                            patch_selected = True
                            time.sleep(0.5)
                    
                    # Sprawdź czy jest pytanie o reinstalację
                    if patch_selected and not reinstall_answered and "Do you really want to install again" in buf_clean:
                        # Sprawdź czy linia kończy się znakiem zapytania (pytanie jest kompletne)
                        last_line = buf_clean.strip().split('\n')[-1]
                        if '?' in last_line:
                            # Poczekaj jeszcze chwilę aby upewnić się że to koniec pytania
                            time.sleep(1.0)
                            # Sprawdź czy nie ma więcej danych
                            try:
                                extra = channel.recv(4096).decode('utf-8', errors='replace')
                                if extra:
                                    buf += extra
                                    print(strip_ansi(extra), end='', flush=True)
                            except:
                                pass
                            
                            print("\n>>> Sending reinstall answer: y <<<", flush=True)
                            channel.send(b"y\r")
                            reinstall_answered = True
                            time.sleep(0.5)
                    
                    # Sprawdź czy wróciliśmy do promptu
                    if patch_selected and ("cm.gdemo.com>" in buf_clean or ".com>" in buf_clean or "grdadmin>" in buf_clean):
                        # Poczekaj chwilę na ewentualny dodatkowy output
                        time.sleep(1)
                        try:
                            while True:
                                chunk = channel.recv(4096).decode('utf-8', errors='replace')
                                if chunk:
                                    print(strip_ansi(chunk), end='', flush=True)
                                else:
                                    break
                        except:
                            pass
                        print("\n\n=== Command completed ===")
                        break
                        
            except Exception as e:
                if "timed out" not in str(e).lower():
                    print(f"\nError: {e}")
                time.sleep(0.1)
                
                # Sprawdź czy nadal połączeni
                if channel.closed:
                    print("\nChannel closed")
                    break
        
        channel.close()
        client.close()
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_patch_install()

# Made with Bob
