#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Guardium REST API - class for communication with Guardium via REST API
"""

import os
import requests
from typing import Optional, Any
from dotenv import load_dotenv
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

class GuardiumRestAPI:
    """Class for communication with Guardium via REST API"""
    
    def __init__(
        self,
        base_url: str,
        client_id: str = "BOOTCAMP",
        client_secret: Optional[str] = None,
        verify_ssl: bool = False
    ):
        """
        Initializes the REST API client.
        
        Args:
            base_url: Base API URL (e.g., 'https://10.10.9.219')
            client_id: OAuth client ID (default 'BOOTCAMP')
            client_secret: OAuth client secret (if None, retrieves from .env)
            verify_ssl: Whether to verify SSL certificate (default False)
        """
        self.base_url = base_url.rstrip('/')
        self.client_id = client_id
        self.verify_ssl = verify_ssl
        
        # Get client_secret from parameter or environment variables
        if client_secret:
            self.client_secret = client_secret
        else:
            self.client_secret = os.getenv('CLIENT_SECRET')
            if not self.client_secret:
                raise ValueError("CLIENT_SECRET not found in environment variables")
        
        self.access_token: Optional[str] = None
    
    def get_token(self, username: str, password: str) -> str:
        """
        Retrieves access token from Guardium OAuth.
        
        Args:
            username: Guardium username
            password: Guardium user password
        
        Returns:
            Access token
        
        Raises:
            requests.exceptions.RequestException: In case of HTTP error
            KeyError: If response does not contain access_token
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
        Returns HTTP headers with authorization token.
        
        Returns:
            Dictionary with headers
        
        Raises:
            RuntimeError: If token has not been retrieved yet
        """
        if not self.access_token:
            raise RuntimeError("Access token not available. Call get_token() first.")
        
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }
    
    def get_users(self) -> dict:
        """
        Retrieves list of users from Guardium.
        
        Returns:
            Dictionary with user data
        
        Raises:
            RuntimeError: If token has not been retrieved yet
            requests.exceptions.RequestException: In case of HTTP error
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
        Creates a new user in Guardium.
        
        Args:
            username: Username (required)
            password: Password (required, min. 8 characters, uppercase/lowercase letter, digit, special character)
            confirm_password: Password confirmation (required, must match password)
            first_name: First name (required)
            last_name: Last name (required)
            email: Email address (optional)
            country: ISO 3166 2-letter country code, e.g., 'US', 'PL' (optional)
            disabled: Whether user is disabled (default False)
            disable_pwd_expiry: Whether to disable password change requirement on first login (default False)
        
        Returns:
            Dictionary with API response
        
        Raises:
            RuntimeError: If token has not been retrieved yet
            requests.exceptions.RequestException: In case of HTTP error
            ValueError: If password != confirm_password
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
        
        # Add optional parameters
        if email:
            data['email'] = email
        if country:
            data['country'] = country
        
        response = requests.post(url, json=data, headers=headers, verify=self.verify_ssl)
        response.raise_for_status()
        
        return response.json()
    
    def set_user_roles(self, username: str, roles: str) -> dict:
        """
        Assigns or updates user roles in Guardium.
        
        Args:
            username: Username (required)
            roles: Role or roles to assign (required)
                   For multiple roles use comma without spaces, e.g., "role1,role2,role3"
        
        Returns:
            Dictionary with API response
        
        Raises:
            RuntimeError: If token has not been retrieved yet
            requests.exceptions.RequestException: In case of HTTP error
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
        Imports definitions from file to Guardium.
        
        Args:
            file_path: Path to file with definitions (e.g., from guardium_definitions_file directory)
        
        Returns:
            Dictionary with API response
        
        Raises:
            RuntimeError: If token has not been retrieved yet
            FileNotFoundError: If file does not exist
            requests.exceptions.RequestException: In case of HTTP error
        """
        import os
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        url = f'{self.base_url}/restAPI/import_definitions'
        headers = self.get_headers()
        
        # Remove Content-Type from headers, requests will set it automatically for multipart/form-data
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
        Registers a unit in Guardium Central Manager.
        
        Args:
            unit_ip: Unit IP address (required)
            unit_port: Unit port (required)
            secret_key: Secret key for registration (required)
        
        Returns:
            Dictionary with API response
        
        Raises:
            RuntimeError: If token has not been retrieved yet
            requests.exceptions.RequestException: In case of HTTP error
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
        Retrieves list of registered units in Guardium Central Manager.
        
        Returns:
            Dictionary with list of registered units
        
        Raises:
            RuntimeError: If token has not been retrieved yet
            requests.exceptions.RequestException: In case of HTTP error
        """
        url = f'{self.base_url}/restAPI/get_registered_units'
        headers = self.get_headers()
        
        response = requests.get(url, headers=headers, verify=self.verify_ssl)
        response.raise_for_status()
        
        return response.json()
    
    def get_unit_data(self, api_target_host: str) -> dict:
        """
        Retrieves unit data from Guardium.
        
        Args:
            api_target_host: Unit IP address or hostname
        
        Returns:
            Dictionary with unit data
        
        Raises:
            RuntimeError: If token has not been retrieved yet
            requests.exceptions.RequestException: In case of HTTP error
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
        Installs patch on Guardium units.
        
        Args:
            patch_number: Patch number to install
            unit_ip_list: Comma-separated list of unit IPs (e.g., "10.10.9.219,10.10.9.220")
            mode: Installation mode:
                - "local_only": Install locally only
                - "pull_only": Only pull patch
                - "pull_install": Pull and install
        
        Returns:
            Dictionary with API response
        
        Raises:
            RuntimeError: If token has not been retrieved yet
            ValueError: If mode is invalid
            requests.exceptions.RequestException: In case of HTTP error
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
        Cleans up old patch files from Guardium system.
        
        Returns:
            Dictionary with API response
        
        Raises:
            RuntimeError: If token has not been retrieved yet
            requests.exceptions.RequestException: In case of HTTP error
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
        Installs policy or policies in Guardium.
        
        Args:
            policy: Policy or policies name to install (required)
                For multiple policies use pipe character (|), e.g., "policy1|policy2|policy3"
            install_action: Installation action (optional)
            api_target_host: Target host for API (optional)
        
        Returns:
            Dictionary with API response
        
        Raises:
            RuntimeError: If token has not been retrieved yet
            requests.exceptions.RequestException: In case of HTTP error
        
        Example:
            # Install single policy
            api.install_policy("MyPolicy")
            
            # Install multiple policies
            api.install_policy("Policy1|Policy2|Policy3")
            
            # With additional target
            api.install_policy("MyPolicy", api_target_host="10.10.9.239")
        """
        url = f'{self.base_url}/restAPI/policy_install'
        headers = self.get_headers()
        
        data = {
            'policy': policy
        }
        
        # Add optional parameters
        if install_action:
            data['install_action'] = install_action
        if api_target_host:
            data['api_target_host'] = api_target_host
        
        response = requests.post(url, json=data, headers=headers, verify=self.verify_ssl)
        response.raise_for_status()
        
        return response.json()
    
    def get_gim_package(self, filename: str) -> dict:
        """
        Retrieves GIM (Group Identity Management) package from Guardium.
        
        Args:
            filename: GIM package filename (required)
        
        Returns:
            Dictionary with API response containing GIM package information
        
        Raises:
            RuntimeError: If token has not been retrieved yet
            requests.exceptions.RequestException: In case of HTTP error
        
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
        Assigns GIM module to client.
        
        Args:
            client_ip: Client IP address (required)
            module: GIM module name (required)
            module_version: Module version (required)
        
        Returns:
            Dictionary with API response
        
        Raises:
            RuntimeError: If token has not been retrieved yet
            requests.exceptions.RequestException: In case of HTTP error
        
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
        Schedules GIM module(s) installation on client.
        
        Args:
            client_ip: Client IP address (required)
            date: Installation date in format "now" or "yyyy-MM-dd HH:mm" (required)
            module: GIM module name (optional). If not provided, all modules
                   for the given client will be scheduled for installation.
        
        Returns:
            Dictionary with API response
        
        Raises:
            RuntimeError: If token has not been retrieved yet
            requests.exceptions.RequestException: In case of HTTP error
        
        Example:
            # Schedule installation immediately
            api.gim_schedule_install(
                client_ip="10.10.9.100",
                date="now",
                module="PostgreSQL"
            )
            
            # Schedule installation for specific date
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
        
        # Add optional module parameter
        if module:
            data['module'] = module
        
        response = requests.put(url, json=data, headers=headers, verify=self.verify_ssl)
        response.raise_for_status()
        
        return response.json()
    
    def gim_list_client_modules(self, client_ip: str) -> dict:
        """
        Retrieves list of GIM modules assigned to client.
        
        Args:
            client_ip: Client IP address (required)
        
        Returns:
            Dictionary with list of GIM modules for the given client
        
        Raises:
            RuntimeError: If token has not been retrieved yet
            requests.exceptions.RequestException: In case of HTTP error
        
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
        Sets GIM client parameters.
        
        Args:
            client_ip: Target client IP address (required)
            param_name: Parameter name (required)
            param_value: Parameter value (optional)
        
        Returns:
            Dictionary with API response
        
        Raises:
            RuntimeError: If token has not been retrieved yet
            requests.exceptions.RequestException: In case of HTTP error
        
        Example:
            # Set parameter with value
            api.gim_client_params(
                client_ip="10.10.9.100",
                param_name="connection_timeout",
                param_value="30"
            )
            
            # Set parameter without value
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
        
        # Add optional paramValue parameter
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
        Deletes inspection engine from Guardium.
        
        Args:
            stap_host: S-TAP inspection engine host (required)
            type: Type of monitored data repository (required)
                  Examples: PostgreSQL, Oracle, MSSQL, MongoDB, MySQL, etc.
            sequence: Sequence number of inspection engine to delete (optional)
            wait_for_response: Whether to wait for response from S-TAP (optional)
                              0 = don't wait, 1 = wait
            api_target_host: Target host for API (optional)
        
        Returns:
            Dictionary with API response
        
        Raises:
            RuntimeError: If token has not been retrieved yet
            requests.exceptions.RequestException: In case of HTTP error
        
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
        
        # Add optional parameters
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
        
        # Add optional parameters
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
        Creates SQL configuration for Oracle in Guardium.
        
        Args:
            db_type: Type of monitored data repository (required)
                    Valid value: "Oracle"
            instance: Connection identifier in tnsnames.ora used to connect to database (required)
            stap_host: S-TAP hostname (required)
                      To get valid values, call create_sql_configuration with --help=true
            username: Username to login to Oracle DB (required)
            data_pull_interval: Time in seconds between attempts to pull data from database (optional)
                               Default: 30
            data_pull_rows: Number of audit data rows to pull in one pass (optional)
                           Default: 100
            timeout: Time in seconds for database response (optional)
                    Default: 300000
            user_role: Role to login to Oracle DB (optional)
                      Valid values: "sysdba", "sysoper"
                      Default: ""
            api_target_host: Target host for API (optional)
        
        Returns:
            Dictionary with API response
        
        Raises:
            RuntimeError: If token has not been retrieved yet
            requests.exceptions.RequestException: In case of HTTP error
        
        Example:
            api.create_sql_configuration(
                db_type="Oracle",
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
        
        # Add optional parameters
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
        Stores SQL credentials for Oracle in Guardium.
        
        Args:
            password: Password to login to Oracle DB (required)
            stap_host: S-TAP hostname that connects to this Oracle DB instance (required)
                      To get valid values, call store_sql_credentials with --help=true
            username: Username to login to Oracle DB (required)
            api_target_host: Target host for API (optional)
        
        Returns:
            Dictionary with API response
        
        Raises:
            RuntimeError: If token has not been retrieved yet
            requests.exceptions.RequestException: In case of HTTP error
        
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
        
        # Add optional parameter
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
        Configures Inspection Engine settings in Guardium.
        
        Args:
            compute_average: When enabled, average response time is calculated for each SQL construct (optional)
                           Valid values: True (1), False (0)
            inspect_data: When enabled, data returned by SQL queries is inspected,
                         and ingress and egress counters are updated.
                         If rules are used in security policy, this parameter must be enabled (optional)
                         Valid values: True (1), False (0)
            log_exception_sql: When enabled, full SQL statement is logged during exception logging (optional)
                              Valid values: True (1), False (0)
            log_records: When enabled, number of records affected by SQL statement is logged
                        for each SQL statement (when applicable) (optional)
                        Valid values: True (1), False (0)
                        Default: False (0)
            log_sequencing: When enabled, immediately previous SQL statement is logged,
                           as well as current SQL statement, provided that previous construct
                           occurs within sufficiently short time period (optional)
                           Valid values: True (1), False (0)
            max_hits: When returned data is inspected, indicates how many hits (policy rule violations)
                     should be logged (optional)
            parse_xml: Inspection Engine normally does not parse XML traffic. Enable to parse XML traffic (optional)
                      Valid values: True (1), False (0)
            record_empty: When enabled, sessions containing no SQL statements are logged.
                         When disabled, these sessions are ignored (optional)
                         Valid values: True (1), False (0)
            api_target_host: Target host for API (optional)
        
        Returns:
            Dictionary with API response
        
        Raises:
            RuntimeError: If token has not been retrieved yet
            requests.exceptions.RequestException: In case of HTTP error
        
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
        
        # Add optional parameters - convert bool to int (0/1)
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
        Generates SSL key for Universal Connector.
        
        Args:
            expiration_days: Number of days certificate is valid (default 100)
            hostname: Guardium machine hostname or wildcard (default '*.guard.swg.usma.ibm.com')
            overwrite: Whether to overwrite existing key and certificate (default False)
                      False (0): don't overwrite
                      True (1): overwrite
            api_target_host: Optional target API host (default None)
        
        Returns:
            Dictionary with API response
        
        Raises:
            RuntimeError: If token has not been retrieved yet
            requests.exceptions.RequestException: In case of HTTP error
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
