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

# Made with Bob
