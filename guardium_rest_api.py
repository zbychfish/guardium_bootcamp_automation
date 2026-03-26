#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Guardium REST API - klasa do komunikacji z Guardium przez REST API
"""

import os
import requests
from typing import Optional
from dotenv import load_dotenv

# Wyłącz ostrzeżenia o niezweryfikowanych certyfikatach SSL
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Załaduj zmienne środowiskowe
load_dotenv()


class GuardiumRestAPI:
    """Klasa do komunikacji z Guardium przez REST API"""
    
    def __init__(
        self,
        base_url: str,
        client_id: str = "BOOTCAMP",
        client_secret: Optional[str] = None,
        verify_ssl: bool = False
    ):
        """
        Inicjalizuje klienta REST API.
        
        Args:
            base_url: Bazowy URL API (np. 'https://10.10.9.219')
            client_id: ID klienta OAuth (domyślnie 'BOOTCAMP')
            client_secret: Secret klienta OAuth (jeśli None, pobiera z .env)
            verify_ssl: Czy weryfikować certyfikat SSL (domyślnie False)
        """
        self.base_url = base_url.rstrip('/')
        self.client_id = client_id
        self.verify_ssl = verify_ssl
        
        # Pobierz client_secret z parametru lub ze zmiennych środowiskowych
        if client_secret:
            self.client_secret = client_secret
        else:
            self.client_secret = os.getenv('CLIENT_SECRET')
            if not self.client_secret:
                raise ValueError("CLIENT_SECRET not found in environment variables")
        
        self.access_token: Optional[str] = None
    
    def get_token(self, username: str, password: str) -> str:
        """
        Pobiera access token z Guardium OAuth.
        
        Args:
            username: Nazwa użytkownika Guardium
            password: Hasło użytkownika Guardium
        
        Returns:
            Access token
        
        Raises:
            requests.exceptions.RequestException: W przypadku błędu HTTP
            KeyError: Jeśli odpowiedź nie zawiera access_token
        """
        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'grant_type': 'password',
            'username': username,
            'password': password
        }
        
        url = f'{self.base_url}/oauth/token'
        response = requests.post(url, data=data, verify=self.verify_ssl)
        response.raise_for_status()
        
        token_data = response.json()
        access_token = token_data['access_token']
        self.access_token = access_token
        
        return access_token
    
    def get_headers(self) -> dict:
        """
        Zwraca nagłówki HTTP z tokenem autoryzacji.
        
        Returns:
            Słownik z nagłówkami
        
        Raises:
            RuntimeError: Jeśli token nie został jeszcze pobrany
        """
        if not self.access_token:
            raise RuntimeError("Access token not available. Call get_token() first.")
        
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }
    
    def get_users(self) -> dict:
        """
        Pobiera listę użytkowników z Guardium.
        
        Returns:
            Słownik z danymi użytkowników
        
        Raises:
            RuntimeError: Jeśli token nie został jeszcze pobrany
            requests.exceptions.RequestException: W przypadku błędu HTTP
        """
        url = f'{self.base_url}/restAPI/user'
        headers = self.get_headers()
        
        response = requests.get(url, headers=headers, verify=self.verify_ssl)
        response.raise_for_status()
        
        return response.json()
    
    def create_user(
        self,
        username: str,
        password: str,
        confirm_password: str,
        first_name: str,
        last_name: str,
        email: Optional[str] = None,
        country: Optional[str] = None,
        disabled: bool = False,
        disable_pwd_expiry: bool = False
    ) -> dict:
        """
        Tworzy nowego użytkownika w Guardium.
        
        Args:
            username: Nazwa użytkownika (wymagane)
            password: Hasło (wymagane, min. 8 znaków, wielka/mała litera, cyfra, znak specjalny)
            confirm_password: Potwierdzenie hasła (wymagane, musi być takie samo jak password)
            first_name: Imię (wymagane)
            last_name: Nazwisko (wymagane)
            email: Adres email (opcjonalne)
            country: Kod kraju ISO 3166 2-literowy, np. 'US', 'PL' (opcjonalne)
            disabled: Czy użytkownik jest wyłączony (domyślnie False)
            disable_pwd_expiry: Czy wyłączyć wymóg zmiany hasła przy pierwszym logowaniu (domyślnie False)
        
        Returns:
            Słownik z odpowiedzią API
        
        Raises:
            RuntimeError: Jeśli token nie został jeszcze pobrany
            requests.exceptions.RequestException: W przypadku błędu HTTP
            ValueError: Jeśli password != confirm_password
        """
        if password != confirm_password:
            raise ValueError("Password and confirmPassword must match")
        
        url = f'{self.base_url}/restAPI/user'
        headers = self.get_headers()
        
        data = {
            'userName': username,
            'password': password,
            'confirmPassword': confirm_password,
            'firstName': first_name,
            'lastName': last_name,
            'disabled': 1 if disabled else 0,
            'disablePwdExpiry': 1 if disable_pwd_expiry else 0
        }
        
        # Dodaj opcjonalne parametry
        if email:
            data['email'] = email
        if country:
            data['country'] = country
        
        response = requests.post(url, json=data, headers=headers, verify=self.verify_ssl)
        response.raise_for_status()
        
        return response.json()
    
    def set_user_roles(self, username: str, roles: str) -> dict:
        """
        Przypisuje lub aktualizuje role użytkownika w Guardium.
        
        Args:
            username: Nazwa użytkownika (wymagane)
            roles: Rola lub role do przypisania (wymagane)
                   Dla wielu ról użyj przecinka bez spacji, np. "role1,role2,role3"
        
        Returns:
            Słownik z odpowiedzią API
        
        Raises:
            RuntimeError: Jeśli token nie został jeszcze pobrany
            requests.exceptions.RequestException: W przypadku błędu HTTP
        """
        url = f'{self.base_url}/restAPI/user_roles'
        headers = self.get_headers()
        
        data = {
            'userName': username,
            'roles': roles
        }
        
        response = requests.put(url, json=data, headers=headers, verify=self.verify_ssl)
        response.raise_for_status()
        
        return response.json()
    
    def import_definitions(self, file_path: str) -> dict:
        """
        Importuje definicje z pliku do Guardium.
        
        Args:
            file_path: Ścieżka do pliku z definicjami (np. z katalogu guardium_definitions_file)
        
        Returns:
            Słownik z odpowiedzią API
        
        Raises:
            RuntimeError: Jeśli token nie został jeszcze pobrany
            FileNotFoundError: Jeśli plik nie istnieje
            requests.exceptions.RequestException: W przypadku błędu HTTP
        """
        import os
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        url = f'{self.base_url}/restAPI/import_definitions'
        headers = self.get_headers()
        
        # Usuń Content-Type z nagłówków, requests ustawi go automatycznie dla multipart/form-data
        headers_without_content_type = {k: v for k, v in headers.items() if k != 'Content-Type'}
        
        with open(file_path, 'rb') as f:
            files = {'file': (os.path.basename(file_path), f)}
            response = requests.post(
                url,
                files=files,
                headers=headers_without_content_type,
                verify=self.verify_ssl
            )
        
        response.raise_for_status()
        
        return response.json()
    
    def register_unit(self, unit_ip: str, unit_port: str, secret_key: str) -> dict:
        """
        Rejestruje jednostkę (unit) w Guardium Central Manager.
        
        Args:
            unit_ip: Adres IP jednostki (wymagane)
            unit_port: Port jednostki (wymagane)
            secret_key: Klucz tajny do rejestracji (wymagane)
        
        Returns:
            Słownik z odpowiedzią API
        
        Raises:
            RuntimeError: Jeśli token nie został jeszcze pobrany
            requests.exceptions.RequestException: W przypadku błędu HTTP
        """
        url = f'{self.base_url}/restAPI/register_unit'
        headers = self.get_headers()
        
        data = {
            'unitIp': unit_ip,
            'unitPort': unit_port,
            'secretKey': secret_key
        }
        
        response = requests.post(url, json=data, headers=headers, verify=self.verify_ssl)
        response.raise_for_status()
        
        return response.json()
    
    def get_registered_units(self) -> dict:
        """
        Pobiera listę zarejestrowanych jednostek (units) w Guardium Central Manager.
        
        Returns:
            Słownik z listą zarejestrowanych jednostek
        
        Raises:
            RuntimeError: Jeśli token nie został jeszcze pobrany
            requests.exceptions.RequestException: W przypadku błędu HTTP
        """
        url = f'{self.base_url}/restAPI/get_registered_units'
        headers = self.get_headers()
        
        response = requests.get(url, headers=headers, verify=self.verify_ssl)
        response.raise_for_status()
        
        return response.json()
    
    def get_unit_data(self, api_target_host: str) -> dict:
        """
        Pobiera dane jednostki (unit) z Guardium.
        
        Args:
            api_target_host: Adres IP lub hostname jednostki
        
        Returns:
            Słownik z danymi jednostki
        
        Raises:
            RuntimeError: Jeśli token nie został jeszcze pobrany
            requests.exceptions.RequestException: W przypadku błędu HTTP
        """
        url = f'{self.base_url}/restAPI/unit_data'
        headers = self.get_headers()
        
        params = {
            'api_target_host': api_target_host
        }
        
        response = requests.get(url, headers=headers, params=params, verify=self.verify_ssl)
        response.raise_for_status()
        
        return response.json()
    
    def install_patch(
        self,
        patch_number: int,
        unit_ip_list: str,
        mode: str = "local_only"
    ) -> dict:
        """
        Instaluje patch na jednostkach Guardium.
        
        Args:
            patch_number: Numer patcha do zainstalowania
            unit_ip_list: Lista IP jednostek oddzielona przecinkami (np. "10.10.9.219,10.10.9.220")
            mode: Tryb instalacji:
                - "local_only": Instaluj tylko lokalnie
                - "pull_only": Tylko pobierz patch
                - "pull_install": Pobierz i zainstaluj
        
        Returns:
            Słownik z odpowiedzią API
        
        Raises:
            RuntimeError: Jeśli token nie został jeszcze pobrany
            ValueError: Jeśli mode jest nieprawidłowy
            requests.exceptions.RequestException: W przypadku błędu HTTP
        """
        valid_modes = ["local_only", "pull_only", "pull_install"]
        if mode not in valid_modes:
            raise ValueError(f"Invalid mode: {mode}. Valid values: {', '.join(valid_modes)}")
        
        url = f'{self.base_url}/restAPI/patch_install'
        headers = self.get_headers()
        
        data = {
            'mode': mode,
            'patch_number': patch_number,
            'unitIpList': unit_ip_list
        }
        
        response = requests.put(url, json=data, headers=headers, verify=self.verify_ssl)
        response.raise_for_status()
        
        return response.json()
    
    def patch_cleanup(self) -> dict:
        """
        Czyści stare pliki patchy z systemu Guardium.
        
        Returns:
            Słownik z odpowiedzią API
        
        Raises:
            RuntimeError: Jeśli token nie został jeszcze pobrany
            requests.exceptions.RequestException: W przypadku błędu HTTP
        """
        url = f'{self.base_url}/restAPI/patch_cleanup'
        headers = self.get_headers()
        
        response = requests.put(url, headers=headers, verify=self.verify_ssl)
        response.raise_for_status()
        
        return response.json()

    def install_policy(
        self,
        policy: str,
        install_action: Optional[str] = None,
        api_target_host: Optional[str] = None
    ) -> dict:
        """
        Instaluje policy lub policies w Guardium.
        
        Args:
            policy: Nazwa policy lub policies do zainstalowania (wymagane)
                Dla wielu policies użyj znaku pipe (|), np. "policy1|policy2|policy3"
            install_action: Akcja instalacji (opcjonalne)
            api_target_host: Docelowy host dla API (opcjonalne)
        
        Returns:
            Słownik z odpowiedzią API
        
        Raises:
            RuntimeError: Jeśli token nie został jeszcze pobrany
            requests.exceptions.RequestException: W przypadku błędu HTTP
        
        Example:
            # Instalacja pojedynczej policy
            api.install_policy("MyPolicy")
            
            # Instalacja wielu policies
            api.install_policy("Policy1|Policy2|Policy3")
            
            # Z dodatkowym targetem
            api.install_policy("MyPolicy", api_target_host="10.10.9.239")
        """
        url = f'{self.base_url}/restAPI/policy_install'
        headers = self.get_headers()
        
        data = {
            'policy': policy
        }
        
        # Dodaj opcjonalne parametry
        if install_action:
            data['install_action'] = install_action
        if api_target_host:
            data['api_target_host'] = api_target_host
        
        response = requests.post(url, json=data, headers=headers, verify=self.verify_ssl)
        response.raise_for_status()
        
        return response.json()
    
    def get_gim_package(self, filename: str) -> dict:
        """
        Pobiera pakiet GIM (Group Identity Management) z Guardium.
        
        Args:
            filename: Nazwa pliku pakietu GIM (wymagane)
        
        Returns:
            Słownik z odpowiedzią API zawierający informacje o pakiecie GIM
        
        Raises:
            RuntimeError: Jeśli token nie został jeszcze pobrany
            requests.exceptions.RequestException: W przypadku błędu HTTP
        
        Example:
            api.get_gim_package("gim_package_name.tar.gz")
        """
        url = f'{self.base_url}/restAPI/gim_package'
        headers = self.get_headers()
        
        params = {
            'filename': filename
        }
        
        response = requests.get(url, headers=headers, params=params, verify=self.verify_ssl)
        response.raise_for_status()
        
        return response.json()
    def gim_client_assign(
        self,
        client_ip: str,
        module: str,
        module_version: str
    ) -> dict:
        """
        Przypisuje moduł GIM do klienta.
        
        Args:
            client_ip: Adres IP klienta (wymagane)
            module: Nazwa modułu GIM (wymagane)
            module_version: Wersja modułu (wymagane)
        
        Returns:
            Słownik z odpowiedzią API
        
        Raises:
            RuntimeError: Jeśli token nie został jeszcze pobrany
            requests.exceptions.RequestException: W przypadku błędu HTTP
        
        Example:
            api.gim_client_assign(
                client_ip="10.10.9.100",
                module="PostgreSQL",
                module_version="1.0.0"
            )
        """
        url = f'{self.base_url}/restAPI/gim_client_assign'
        headers = self.get_headers()
        
        data = {
            'clientIP': client_ip,
            'module': module,
            'moduleVersion': module_version
        }
        
        response = requests.put(url, json=data, headers=headers, verify=self.verify_ssl)
        response.raise_for_status()
        
        return response.json()
    def gim_schedule_install(
        self,
        client_ip: str,
        date: str,
        module: Optional[str] = None
    ) -> dict:
        """
        Planuje instalację modułu/modułów GIM na kliencie.
        
        Args:
            client_ip: Adres IP klienta (wymagane)
            date: Data instalacji w formacie "now" lub "yyyy-MM-dd HH:mm" (wymagane)
            module: Nazwa modułu GIM (opcjonalne). Jeśli nie podano, wszystkie moduły
                   dla danego klienta zostaną zaplanowane do instalacji.
        
        Returns:
            Słownik z odpowiedzią API
        
        Raises:
            RuntimeError: Jeśli token nie został jeszcze pobrany
            requests.exceptions.RequestException: W przypadku błędu HTTP
        
        Example:
            # Zaplanuj instalację natychmiast
            api.gim_schedule_install(
                client_ip="10.10.9.100",
                date="now",
                module="PostgreSQL"
            )
            
            # Zaplanuj instalację na konkretną datę
            api.gim_schedule_install(
                client_ip="10.10.9.100",
                date="2026-03-27 14:30"
            )
        """
        url = f'{self.base_url}/restAPI/gim_schedule_install'
        headers = self.get_headers()
        
        data = {
            'clientIP': client_ip,
            'date': date
        }
        
        # Dodaj opcjonalny parametr module
        if module:
            data['module'] = module
        
        response = requests.put(url, json=data, headers=headers, verify=self.verify_ssl)
        response.raise_for_status()
        
        return response.json()
    
    def gim_list_client_modules(self, client_ip: str) -> dict:
        """
        Pobiera listę modułów GIM przypisanych do klienta.
        
        Args:
            client_ip: Adres IP klienta (wymagane)
        
        Returns:
            Słownik z listą modułów GIM dla danego klienta
        
        Raises:
            RuntimeError: Jeśli token nie został jeszcze pobrany
            requests.exceptions.RequestException: W przypadku błędu HTTP
        
        Example:
            modules = api.gim_list_client_modules(client_ip="10.10.9.100")
        """
        url = f'{self.base_url}/restAPI/gim_list_client_modules'
        headers = self.get_headers()
        
        params = {
            'clientIP': client_ip
        }
        
        response = requests.get(url, headers=headers, params=params, verify=self.verify_ssl)
        response.raise_for_status()
        
        return response.json()




# Made with Bob
