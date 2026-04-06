#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Guardium REST API - klasa do komunikacji z Guardium przez REST API
"""

import os
import requests
from typing import Optional, Any
from dotenv import load_dotenv
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
    
    def gim_client_params(
        self,
        client_ip: str,
        param_name: str,
        param_value: Optional[str] = None
    ) -> dict:
        """
        Ustawia parametry klienta GIM.
        
        Args:
            client_ip: Adres IP klienta docelowego (wymagane)
            param_name: Nazwa parametru (wymagane)
            param_value: Wartość parametru (opcjonalne)
        
        Returns:
            Słownik z odpowiedzią API
        
        Raises:
            RuntimeError: Jeśli token nie został jeszcze pobrany
            requests.exceptions.RequestException: W przypadku błędu HTTP
        
        Example:
            # Ustaw parametr z wartością
            api.gim_client_params(
                client_ip="10.10.9.100",
                param_name="connection_timeout",
                param_value="30"
            )
            
            # Ustaw parametr bez wartości
            api.gim_client_params(
                client_ip="10.10.9.100",
                param_name="enable_ssl"
            )
        """
        url = f'{self.base_url}/restAPI/gim_client_params'
        headers = self.get_headers()
        
        data = {
            'clientIP': client_ip,
            'paramName': param_name
        }
        
        # Dodaj opcjonalny parametr paramValue
        if param_value is not None:
            data['paramValue'] = param_value
        
        response = requests.put(url, json=data, headers=headers, verify=self.verify_ssl)
        response.raise_for_status()
        
        return response.json()
    
    def delete_inspection_engine(
        self,
        stap_host: str,
        type: str,
        sequence: Optional[str] = None,
        wait_for_response: Optional[str] = None,
        api_target_host: Optional[str] = None
    ) -> dict:
        """
        Usuwa inspection engine z Guardium.
        
        Args:
            stap_host: Host S-TAP inspection engine (wymagane)
            type: Typ monitorowanego repozytorium danych (wymagane)
                  Przykłady: PostgreSQL, Oracle, MSSQL, MongoDB, MySQL, itp.
            sequence: Numer sekwencyjny inspection engine do usunięcia (opcjonalne)
            wait_for_response: Czy czekać na odpowiedź z S-TAP (opcjonalne)
                              0 = nie czekaj, 1 = czekaj
            api_target_host: Docelowy host dla API (opcjonalne)
        
        Returns:
            Słownik z odpowiedzią API
        
        Raises:
            RuntimeError: Jeśli token nie został jeszcze pobrany
            requests.exceptions.RequestException: W przypadku błędu HTTP
        
        Example:
            api.delete_inspection_engine(
                stap_host="10.10.9.70",
                type="PostgreSQL",
                sequence=1
            )
        """
        url = f'{self.base_url}/restAPI/inspection_engine'
        headers = self.get_headers()
        
        data: dict[str, Any] = {
            'stapHost': stap_host,
            'type': type
        }
        
        # Dodaj opcjonalne parametry
        if sequence is not None:
            data['sequence'] = sequence
        if wait_for_response is not None:
            data['waitForResponse'] = wait_for_response
        if api_target_host:
            data['api_target_host'] = api_target_host
        
        response = requests.delete(url, json=data, headers=headers, verify=self.verify_ssl)
        response.raise_for_status()
        
        return response.json()
    
    def create_inspection_engine(
        self,
        stap_host: str,
        protocol: str,
        client: Optional[str] = None,
        connect_to_ip: Optional[str] = None,
        db2_shared_mem_adjustment: Optional[int] = None,
        db2_shared_mem_client_position: Optional[int] = None,
        db2_shared_mem_size: Optional[int] = None,
        db_install_dir: Optional[str] = None,
        db_user: Optional[str] = None,
        db_version: Optional[str] = None,
        encryption: Optional[bool] = None,
        exclude_client: Optional[str] = None,
        ie_identifier: Optional[str] = None,
        informix_version: Optional[int] = None,
        instance_name: Optional[str] = None,
        intercept_types: Optional[str] = None,
        ktap_db_port: Optional[str] = None,
        named_pipe: Optional[str] = None,
        port_max: Optional[str] = None,
        port_min: Optional[str] = None,
        priority_count: Optional[int] = None,
        proc_name: Optional[str] = None,
        proc_names: Optional[str] = None,
        tee_listen_port: Optional[str] = None,
        tee_real_port: Optional[str] = None,
        unix_socket_marker: Optional[str] = None,
        api_target_host: Optional[str] = None
    ) -> dict:
        """
        Tworzy nowy inspection engine w Guardium.
        
        Args:
            stap_host: Host S-TAP (wymagane)
            protocol: Typ monitorowanego repozytorium danych (wymagane)
                     Przykłady: PostgreSQL, Oracle, MSSQL, MongoDB, MySQL, itp.
            client: Lista adresów IP klientów w formacie IP/maska (opcjonalne)
            connect_to_ip: Adres IP do połączenia z bazą danych (opcjonalne)
            db2_shared_mem_adjustment: Offset dla Db2 shared memory (opcjonalne)
            db2_shared_mem_client_position: Offset klienta dla Db2 shared memory (opcjonalne)
            db2_shared_mem_size: Rozmiar segmentu Db2 shared memory (opcjonalne)
            db_install_dir: Pełna ścieżka do katalogu instalacji bazy danych (opcjonalne, Linux)
            db_user: Nazwa użytkownika OS właściciela procesu DB (opcjonalne)
            db_version: Wersja bazy danych (opcjonalne)
            encryption: Czy włączyć szyfrowanie ASO/SSL (opcjonalne, Linux)
            exclude_client: Lista wykluczonych adresów IP klientów (opcjonalne)
            ie_identifier: Identyfikator inspection engine (opcjonalne)
            informix_version: Wersja Informix (opcjonalne)
            instance_name: Nazwa instancji bazy danych (opcjonalne, Windows)
            intercept_types: Typy protokołów do przechwytywania (opcjonalne, Linux)
            ktap_db_port: Port bazy danych dla K-TAP (opcjonalne, Linux)
            named_pipe: Named pipe dla MS SQL Server (opcjonalne, Windows)
            port_max: Najwyższy numer portu do monitorowania (opcjonalne)
            port_min: Najniższy numer portu do monitorowania (opcjonalne)
            priority_count: Liczba pakietów z wysokim priorytetem (opcjonalne)
            proc_name: Pełna ścieżka do pliku wykonywalnego bazy danych (opcjonalne, Linux)
            proc_names: Pliki wykonywalne usługi bazy danych (opcjonalne, Windows)
            tee_listen_port: Deprecated, użyj ktap_db_port (opcjonalne)
            tee_real_port: Deprecated (opcjonalne)
            unix_socket_marker: Marker UNIX domain socket (opcjonalne, Linux)
            api_target_host: Docelowy host dla API (opcjonalne)
        
        Returns:
            Słownik z odpowiedzią API
        
        Raises:
            RuntimeError: Jeśli token nie został jeszcze pobrany
            requests.exceptions.RequestException: W przypadku błędu HTTP
        
        Example:
            api.create_inspection_engine(
                stap_host="10.10.9.70",
                protocol="PostgreSQL",
                port_min="5432",
                port_max="5432",
                db_user="postgres"
            )
        """
        url = f'{self.base_url}/restAPI/inspection_engine'
        headers = self.get_headers()
        
        data: dict[str, Any] = {
            'stapHost': stap_host,
            'protocol': protocol
        }
        
        # Dodaj opcjonalne parametry
        if client:
            data['client'] = client
        if connect_to_ip:
            data['connectToIp'] = connect_to_ip
        if db2_shared_mem_adjustment is not None:
            data['db2SharedMemAdjustment'] = db2_shared_mem_adjustment
        if db2_shared_mem_client_position is not None:
            data['db2SharedMemClientPosition'] = db2_shared_mem_client_position
        if db2_shared_mem_size is not None:
            data['db2SharedMemSize'] = db2_shared_mem_size
        if db_install_dir:
            data['dbInstallDir'] = db_install_dir
        if db_user:
            data['dbUser'] = db_user
        if db_version:
            data['dbVersion'] = db_version
        if encryption is not None:
            data['encryption'] = 1 if encryption else 0
        if exclude_client:
            data['excludeClient'] = exclude_client
        if ie_identifier:
            data['ieIdentifier'] = ie_identifier
        if informix_version is not None:
            data['informixVersion'] = informix_version
        if instance_name:
            data['instanceName'] = instance_name
        if intercept_types:
            data['interceptTypes'] = intercept_types
        if ktap_db_port:
            data['ktapDbPort'] = ktap_db_port
        if named_pipe:
            data['namedPipe'] = named_pipe
        if port_max:
            data['portMax'] = port_max
        if port_min:
            data['portMin'] = port_min
        if priority_count is not None:
            data['priorityCount'] = priority_count
        if proc_name:
            data['procName'] = proc_name
        if proc_names:
            data['procNames'] = proc_names
        if tee_listen_port:
            data['teeListenPort'] = tee_listen_port
        if tee_real_port:
            data['teeRealPort'] = tee_real_port
        if unix_socket_marker:
            data['unixSocketMarker'] = unix_socket_marker
        if api_target_host:
            data['api_target_host'] = api_target_host
        response = requests.post(url, json=data, headers=headers, verify=self.verify_ssl)
        response.raise_for_status()
        
        return response.json()
    
    def create_sql_configuration(
        self,
        db_type: str,
        instance: str,
        stap_host: str,
        username: str,
        data_pull_interval: Optional[str] = None,
        data_pull_rows: Optional[str] = None,
        timeout: Optional[str] = None,
        user_role: Optional[str] = None,
        api_target_host: Optional[str] = None
    ) -> dict:
        """
        Tworzy konfigurację SQL dla Oracle w Guardium.
        
        Args:
            b_type: Typ monitorowanego repozytorium danych (wymagane)
                   Prawidłowa wartość: "Oracle"
            instance: Identyfikator połączenia w tnsnames.ora używany do połączenia z bazą danych (wymagane)
            stap_host: Hostname S-TAP (wymagane)
                      Aby uzyskać prawidłowe wartości, wywołaj create_sql_configuration z --help=true
            username: Nazwa użytkownika do logowania do Oracle DB (wymagane)
            data_pull_interval: Czas w sekundach między próbami pobrania danych z bazy danych (opcjonalne)
                               Domyślnie: 30
            data_pull_rows: Liczba wierszy danych audytowych do pobrania w jednym przebiegu (opcjonalne)
                           Domyślnie: 100
            timeout: Czas w sekundach na odpowiedź bazy danych (opcjonalne)
                    Domyślnie: 300000
            user_role: Rola do logowania do Oracle DB (opcjonalne)
                      Prawidłowe wartości: "sysdba", "sysoper"
                      Domyślnie: ""
            api_target_host: Docelowy host dla API (opcjonalne)
        
        Returns:
            Słownik z odpowiedzią API
        
        Raises:
            RuntimeError: Jeśli token nie został jeszcze pobrany
            requests.exceptions.RequestException: W przypadku błędu HTTP
        
        Example:
            api.create_sql_configuration(
                b_type="Oracle",
                instance="ORCLPDB1",
                stap_host="10.10.9.60",
                username="secadmin",
                data_pull_interval="30",
                data_pull_rows="100",
                user_role="sysdba"
            )
        """
        url = f'{self.base_url}/restAPI/create_sql_configuration'
        headers = self.get_headers()
        
        data: dict[str, Any] = {
            'dbType': db_type,
            'instance': instance,
            'stapHost': stap_host,
            'username': username
        }
        
        # Dodaj opcjonalne parametry
        if data_pull_interval:
            data['dataPullInterval'] = data_pull_interval
        if data_pull_rows:
            data['dataPullRows'] = data_pull_rows
        if timeout:
            data['timeout'] = timeout
        if user_role:
            data['userRole'] = user_role
        if api_target_host:
            data['api_target_host'] = api_target_host
        
        response = requests.post(url, json=data, headers=headers, verify=self.verify_ssl)
        response.raise_for_status()
        
        return response.json()
    
    def store_sql_credentials(
        self,
        password: str,
        stap_host: str,
        username: str,
        api_target_host: Optional[str] = None
    ) -> dict:
        """
        Przechowuje dane uwierzytelniające SQL dla Oracle w Guardium.
        
        Args:
            password: Hasło do logowania do Oracle DB (wymagane)
            stap_host: Hostname S-TAP, który łączy się z tą instancją Oracle DB (wymagane)
                      Aby uzyskać prawidłowe wartości, wywołaj store_sql_credentials z --help=true
            username: Nazwa użytkownika do logowania do Oracle DB (wymagane)
            api_target_host: Docelowy host dla API (opcjonalne)
        
        Returns:
            Słownik z odpowiedzią API
        
        Raises:
            RuntimeError: Jeśli token nie został jeszcze pobrany
            requests.exceptions.RequestException: W przypadku błędu HTTP
        
        Example:
            api.store_sql_credentials(
                password="SecurePassword123!",
                stap_host="10.10.9.60",
                username="secadmin"
            )
        """
        url = f'{self.base_url}/restAPI/stap'
        headers = self.get_headers()
        
        data: dict[str, Any] = {
            'password': password,
            'stapHost': stap_host,
            'username': username
        }
        
        # Dodaj opcjonalny parametr
        if api_target_host:
            data['api_target_host'] = api_target_host
        
        response = requests.post(url, json=data, headers=headers, verify=self.verify_ssl)
        response.raise_for_status()
        
        return response.json()
    
    def engine_config(
        self,
        compute_average: Optional[bool] = None,
        inspect_data: Optional[bool] = None,
        log_exception_sql: Optional[bool] = None,
        log_records: Optional[bool] = None,
        log_sequencing: Optional[bool] = None,
        max_hits: Optional[int] = None,
        parse_xml: Optional[bool] = None,
        record_empty: Optional[bool] = None,
        api_target_host: Optional[str] = None
    ) -> dict:
        """
        Konfiguruje ustawienia Inspection Engine w Guardium.
        
        Args:
            compute_average: Gdy włączone, dla każdej konstrukcji SQL obliczany jest średni czas odpowiedzi (opcjonalne)
                           Prawidłowe wartości: True (1), False (0)
            inspect_data: Gdy włączone, dane zwracane przez zapytania SQL są sprawdzane,
                         a liczniki ingress i egress są aktualizowane.
                         Jeśli w polityce bezpieczeństwa używane są reguły, ten parametr musi być włączony (opcjonalne)
                         Prawidłowe wartości: True (1), False (0)
            log_exception_sql: Gdy włączone, podczas logowania wyjątków zapisywana jest cała instrukcja SQL (opcjonalne)
                              Prawidłowe wartości: True (1), False (0)
            log_records: Gdy włączone, liczba rekordów, których dotyczy instrukcja SQL, jest rejestrowana
                        dla każdej instrukcji SQL (gdy ma to zastosowanie) (opcjonalne)
                        Prawidłowe wartości: True (1), False (0)
                        Domyślnie: False (0)
            log_sequencing: Gdy włączone, rejestrowana jest bezpośrednio poprzednia instrukcja SQL,
                           jak również bieżąca instrukcja SQL, pod warunkiem że poprzednia konstrukcja
                           występuje w wystarczająco krótkim okresie czasu (opcjonalne)
                           Prawidłowe wartości: True (1), False (0)
            max_hits: Gdy zwracane dane są sprawdzane, wskazuje ile trafień (naruszeń reguł polityki)
                     ma być zarejestrowanych (opcjonalne)
            parse_xml: Inspection Engine normalnie nie parsuje ruchu XML. Włącz aby parsować ruch XML (opcjonalne)
                      Prawidłowe wartości: True (1), False (0)
            record_empty: Gdy włączone, sesje nie zawierające instrukcji SQL są logowane.
                         Gdy wyłączone, te sesje są ignorowane (opcjonalne)
                         Prawidłowe wartości: True (1), False (0)
            api_target_host: Docelowy host dla API (opcjonalne)
        
        Returns:
            Słownik z odpowiedzią API
        
        Raises:
            RuntimeError: Jeśli token nie został jeszcze pobrany
            requests.exceptions.RequestException: W przypadku błędu HTTP
        
        Example:
            api.engine_config(
                compute_average=True,
                inspect_data=True,
                log_exception_sql=True,
                log_records=True,
                max_hits=100,
                api_target_host="10.10.9.239"
            )
        """
        url = f'{self.base_url}/restAPI/engine_config'
        headers = self.get_headers()
        
        data: dict[str, Any] = {}
        
        # Dodaj opcjonalne parametry - konwertuj bool na int (0/1)
        if compute_average is not None:
            data['computeAverage'] = 1 if compute_average else 0
        if inspect_data is not None:
            data['inspectData'] = 1 if inspect_data else 0
        if log_exception_sql is not None:
            data['logExceptionSql'] = 1 if log_exception_sql else 0
        if log_records is not None:
            data['logRecords'] = 1 if log_records else 0
        if log_sequencing is not None:
            data['logSequencing'] = 1 if log_sequencing else 0
        if max_hits is not None:
            data['maxHits'] = max_hits
        if parse_xml is not None:
            data['parseXml'] = 1 if parse_xml else 0
        if record_empty is not None:
            data['recordEmpty'] = 1 if record_empty else 0
        if api_target_host:
            data['api_target_host'] = api_target_host
        
        response = requests.put(url, json=data, headers=headers, verify=self.verify_ssl)
        response.raise_for_status()
        
        return response.json()
    def generate_ssl_key_universal_connector(
        self,
        expiration_days: int = 100,
        hostname: str = "*.guard.swg.usma.ibm.com",
        overwrite: bool = False,
        api_target_host: Optional[str] = None
    ) -> dict:
        """
        Generuje klucz SSL dla Universal Connector.
        
        Args:
            expiration_days: Liczba dni ważności certyfikatu (domyślnie 100)
            hostname: Hostname maszyny Guardium lub wildcard (domyślnie '*.guard.swg.usma.ibm.com')
            overwrite: Czy nadpisać istniejący klucz i certyfikat (domyślnie False)
                      False (0): nie nadpisuj
                      True (1): nadpisz
            api_target_host: Opcjonalny docelowy host API (domyślnie None)
        
        Returns:
            Słownik z odpowiedzią API
        
        Raises:
            RuntimeError: Jeśli token nie został jeszcze pobrany
            requests.exceptions.RequestException: W przypadku błędu HTTP
        """
        url = f'{self.base_url}/restAPI/generateSSLKeyUniversalConnector'
        headers = self.get_headers()
        
        data = {
            'expiration_days': expiration_days,
            'hostname': hostname,
            'overwrite': 1 if overwrite else 0
        }
        
        if api_target_host is not None:
            data['api_target_host'] = api_target_host
        
        response = requests.post(url, json=data, headers=headers, verify=self.verify_ssl)
        response.raise_for_status()
        
        return response.json()








# Made with Bob
