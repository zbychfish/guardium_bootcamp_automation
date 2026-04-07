#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Guardium Patch Installation - funkcja do instalacji patchy
"""

import paramiko
import time
import sys
import re
import socket
from dotenv import load_dotenv
import os

# Załaduj zmienne środowiskowe
load_dotenv()

def strip_ansi(text):
    """Usuwa kody ANSI z tekstu"""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

def install_patch(
    host: str,
    username: str,
    password: str,
    patch_selection: str = "2",
    reinstall_answer: str = "y",
    command: str = "store system patch install sys",
    live_log: bool = False
):
    """
    Instalacja patcha na appliance Guardium.
    
    Args:
        host: Adres IP appliance
        username: Nazwa użytkownika (np. 'cli')
        password: Hasło
        patch_selection: Wybór patcha (np. "2", "1-2", "1,3")
        reinstall_answer: Odpowiedź na pytanie o reinstalację ("y" lub "n")
        command: Polecenie instalacji (domyślnie "store system patch install sys")
        live_log: Czy wyświetlać output na żywo (domyślnie False)
    
    Returns:
        String z pełnym outputem z instalacji
    """
    
    if live_log:
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
        
        channel = client.invoke_shell()
        channel.settimeout(0.1)

        buf = ""
        prompt_found = False
        timeout = time.time() + 30
        
        while time.time() < timeout:
            try:
                chunk = channel.recv(4096).decode('utf-8', errors='replace')
                if chunk:
                    buf += chunk
                    if live_log:
                        print(strip_ansi(chunk), end='', flush=True)
                    
                    # Sprawdź czy jest prompt (cm.gdemo.com> lub inne)
                    buf_clean = strip_ansi(buf)
                    if "cm.gdemo.com>" in buf_clean or ".com>" in buf_clean or "grdadmin>" in buf_clean:
                        prompt_found = True
                        break
            except:
                time.sleep(0.1)
        
        if not prompt_found:
            if live_log:
                print("\n\nERROR: Prompt not found!")
            return None
        
        if live_log:
            print(f"\n\n=== Prompt found! Sending command: {command} ===\n")
        time.sleep(0.5)
        
        # Wyślij polecenie
        channel.send((command + "\r").encode())
        
        # Czytaj output na żywo
        buf = ""
        patch_selected = False
        reinstall_answered = False
        last_activity = time.time()
        
        while True:
            try:
                chunk = channel.recv(4096).decode('utf-8', errors='replace')
                if chunk:
                    buf += chunk
                    last_activity = time.time()
                    # Wyświetl na żywo
                    if live_log:
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
                                    if live_log:
                                        print(strip_ansi(extra), end='', flush=True)
                            except:
                                pass
                            
                            if live_log:
                                print(f"\n>>> Sending patch selection: {patch_selection} <<<", flush=True)
                            channel.send((patch_selection + "\r").encode())
                            patch_selected = True
                            last_activity = time.time()
                            time.sleep(0.5)
                    
                    # Sprawdź czy jest pytanie o reinstalację
                    if patch_selected and not reinstall_answered and "Do you really want to install again" in buf_clean:
                        # Sprawdź czy pytanie jest kompletne - szukaj "(yes or no)?"
                        if "(yes or no)?" in buf_clean:
                            # Poczekaj jeszcze chwilę aby upewnić się że to koniec pytania
                            time.sleep(1.0)
                            # Sprawdź czy nie ma więcej danych
                            try:
                                extra = channel.recv(4096).decode('utf-8', errors='replace')
                                if extra:
                                    buf += extra
                                    if live_log:
                                        print(strip_ansi(extra), end='', flush=True)
                            except:
                                pass
                            
                            if live_log:
                                print(f"\n>>> Sending reinstall answer: {reinstall_answer} <<<", flush=True)
                            channel.send((reinstall_answer + "\r").encode())
                            reinstall_answered = True
                            last_activity = time.time()
                            time.sleep(0.5)
                    
                    # Sprawdź czy wróciliśmy do promptu
                    if patch_selected and ("cm.gdemo.com>" in buf_clean or ".com>" in buf_clean or "grdadmin>" in buf_clean):
                        # Poczekaj chwilę na ewentualny dodatkowy output
                        time.sleep(1)
                        try:
                            while True:
                                chunk = channel.recv(4096).decode('utf-8', errors='replace')
                                if chunk:
                                    if live_log:
                                        print(strip_ansi(chunk), end='', flush=True)
                                else:
                                    break
                        except:
                            pass
                        if live_log:
                            print("\n\n=== Command completed ===")
                        
                        channel.close()
                        client.close()
                        return buf
                        
            except socket.timeout:
                # Timeout jest normalny - po prostu nie ma danych
                # Sprawdź czy nie minęło zbyt dużo czasu bez aktywności
                if time.time() - last_activity > 300:  # 5 minut bez aktywności
                    if live_log:
                        print("\n\nTimeout: No activity for 5 minutes")
                    break
                time.sleep(0.1)
            except Exception as e:
                if live_log:
                    print(f"\nUnexpected error: {e}")
                break
            
            # Sprawdź czy nadal połączeni
            if channel.closed:
                if live_log:
                    print("\nChannel closed")
                break
        
        channel.close()
        client.close()
        return buf
        
    except Exception as e:
        if live_log:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
        return None


# Made with Bob