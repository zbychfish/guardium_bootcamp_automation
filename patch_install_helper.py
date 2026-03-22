#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Helper function for patch installation - standalone version
"""

import time
import socket
import re
import sys


def strip_ansi(text):
    """Usuwa kody ANSI z tekstu"""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)


def execute_patch_install_standalone(
    appliance,
    command: str = "store system patch install sys",
    patch_selection: str = "2",
    reinstall_answer: str = "y",
    live_output: bool = True,
    timeout: int = 600
):
    """
    Wykonuje instalację patcha z obsługą dwóch pytań - standalone version.
    
    Args:
        appliance: Obiekt ApplianceCommand (musi być połączony)
        command: Polecenie instalacji patcha
        patch_selection: Wybór patchy (np. "1-2", "1,3", "1", "2")
        reinstall_answer: Odpowiedź na pytanie o reinstalację ("y", "yes", "n", "no")
        live_output: Czy wyświetlać output na bieżąco
        timeout: Timeout w sekundach
    
    Returns:
        Output z instalacji patcha
    """
    if not appliance.channel:
        raise RuntimeError("Appliance not connected")
    
    channel = appliance.channel
    prompt_re = appliance.prompt_re
    strip_ansi_flag = appliance.strip_ansi_flag
    
    # Set channel timeout for non-blocking recv
    original_timeout = channel.gettimeout()
    channel.settimeout(0.1)
    
    try:
        # Flush buffer
        time.sleep(0.03)
        while channel.recv_ready():
            channel.recv(65535)
        
        # Send command
        channel.send((command + "\r").encode())
        
        buf = ""
        last_activity = time.time()
        deadline = time.time() + timeout
        patch_selected = False
        reinstall_answered = False
        
        while time.time() < deadline:
            try:
                chunk = channel.recv(65535).decode('utf-8', errors='replace')
                if chunk:
                    buf += chunk
                    last_activity = time.time()
                    
                    # Print new content live immediately
                    if live_output:
                        display_chunk = strip_ansi(chunk) if strip_ansi_flag else chunk
                        print(display_chunk, end='', flush=True)
                        sys.stdout.flush()
                    
                    buf_clean = strip_ansi(buf) if strip_ansi_flag else buf
                    
                    # Sprawdź czy jest pytanie o wybór patcha
                    if not patch_selected and ("Please choose patches" in buf_clean or "or q to quit" in buf_clean):
                        # Sprawdź czy linia kończy się dwukropkiem (pytanie jest kompletne)
                        last_line = buf_clean.strip().split('\n')[-1]
                        if last_line.endswith(':'):
                            # Poczekaj jeszcze chwilę aby upewnić się że to koniec pytania
                            time.sleep(1.0)
                            # Sprawdź czy nie ma więcej danych
                            try:
                                extra = channel.recv(65535).decode('utf-8', errors='replace')
                                if extra:
                                    buf += extra
                                    if live_output:
                                        display_extra = strip_ansi(extra) if strip_ansi_flag else extra
                                        print(display_extra, end='', flush=True)
                                        sys.stdout.flush()
                            except:
                                pass
                            
                            if live_output:
                                print(f"\n[Sending patch selection: {patch_selection}]", flush=True)
                                sys.stdout.flush()
                            
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
                                extra = channel.recv(65535).decode('utf-8', errors='replace')
                                if extra:
                                    buf += extra
                                    if live_output:
                                        display_extra = strip_ansi(extra) if strip_ansi_flag else extra
                                        print(display_extra, end='', flush=True)
                                        sys.stdout.flush()
                            except:
                                pass
                            
                            if live_output:
                                print(f"\n[Sending reinstall answer: {reinstall_answer}]", flush=True)
                                sys.stdout.flush()
                            
                            channel.send((reinstall_answer + "\r").encode())
                            reinstall_answered = True
                            last_activity = time.time()
                            time.sleep(0.5)
                    
                    # Sprawdź czy wróciliśmy do promptu
                    if patch_selected and prompt_re.search(buf_clean):
                        # Poczekaj chwilę na ewentualny dodatkowy output
                        time.sleep(1)
                        try:
                            while channel.recv_ready():
                                chunk = channel.recv(65535).decode('utf-8', errors='replace')
                                if chunk:
                                    buf += chunk
                                    if live_output:
                                        display_chunk = strip_ansi(chunk) if strip_ansi_flag else chunk
                                        print(display_chunk, end='', flush=True)
                                        sys.stdout.flush()
                        except:
                            pass
                        
                        if live_output:
                            print()  # New line at the end
                            sys.stdout.flush()
                        
                        # Return full buffer
                        return buf
                        
            except socket.timeout:
                # Timeout jest normalny - po prostu nie ma danych
                # Sprawdź czy nie minęło zbyt dużo czasu bez aktywności
                if time.time() - last_activity > 300:  # 5 minut bez aktywności
                    raise TimeoutError("No activity for 5 minutes")
                time.sleep(0.1)
            
            # Sprawdź czy nadal połączeni
            if channel.closed:
                raise RuntimeError("Channel closed")
        
        raise TimeoutError(f"Timeout waiting for patch install prompts")
    
    finally:
        # Restore original timeout
        if original_timeout is not None:
            channel.settimeout(original_timeout)


# Made with Bob