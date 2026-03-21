# SSH Automation & MinIO Deployment

Kompleksowe narzędzie do automatyzacji SSH i wdrażania MinIO w środowisku kontenerowym.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.7+](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/downloads/)
[![Ansible 2.9+](https://img.shields.io/badge/ansible-2.9+-red.svg)](https://www.ansible.com/)

## 📋 Spis Treści

- [O Projekcie](#o-projekcie)
- [Funkcje](#funkcje)
- [Szybki Start](#szybki-start)
- [Instalacja](#instalacja)
- [Użycie](#użycie)
- [Dokumentacja](#dokumentacja)
- [Przykłady](#przykłady)
- [Publikacja na GitHub](#publikacja-na-github)
- [Licencja](#licencja)

## 🎯 O Projekcie

Ten projekt zawiera dwa główne komponenty:

### 1. SSH Automation Tool
Biblioteka Python do automatyzacji wykonywania poleceń na zdalnych maszynach przez SSH.

**Główne cechy:**
- ✅ Proste API do wykonywania poleceń SSH
- ✅ Obsługa niestandardowych portów SSH
- ✅ Zwracanie wyników jako lista linii
- ✅ Kompleksowa obsługa błędów
- ✅ Wsparcie dla wielu poleceń
- ✅ Timeout dla długotrwałych operacji

### 2. MinIO Ansible Deployment
Playbook Ansible do automatycznego wdrażania MinIO w kontenerze Docker/Podman.

**Główne cechy:**
- ✅ Wdrożenie MinIO w kontenerze
- ✅ Konfigurowalna lokalizacja danych
- ✅ Opcjonalne certyfikaty TLS
- ✅ Automatyczne tworzenie bucket S3
- ✅ Konfiguracja firewall
- ✅ Wsparcie dla Docker i Podman

## 🚀 Funkcje

### SSH Automation
```python
from ssh_automation import SSHExecutor

executor = SSHExecutor("10.10.9.50", "admin", "haslo", port=22)
if executor.connect():
    result = executor.execute_command("ls -la")
    for line in result['output']:
        print(line)
    executor.disconnect()
```

### MinIO Deployment
```bash
ansible-playbook minio-playbook.yml \
  -e "minio_admin_user=admin" \
  -e "minio_admin_password=SecurePass123!"
```

## ⚡ Szybki Start

### SSH Automation

1. **Instalacja zależności:**
```bash
pip install -r requirements.txt
```

2. **Podstawowe użycie:**
```python
from ssh_automation import SSHExecutor

executor = SSHExecutor(
    host="10.10.9.50",
    username="admin",
    password="haslo",
    port=22
)

try:
    if executor.connect():
        result = executor.execute_command("hostname")
        print(result['output'])
finally:
    executor.disconnect()
```

3. **Uruchomienie przykładów:**
```bash
python example_usage.py
```

### MinIO Deployment

1. **Podstawowe wdrożenie:**
```bash
ansible-playbook minio-playbook.yml
```

2. **Z niestandardowymi parametrami:**
```bash
ansible-playbook minio-playbook.yml \
  -e "minio_admin_user=admin" \
  -e "minio_admin_password=SecurePass123!" \
  -e "container_runtime=podman"
```

## 📦 Instalacja

### Wymagania

**SSH Automation:**
- Python 3.7+
- paramiko 3.0.0+

**MinIO Deployment:**
- Ansible 2.9+
- Docker lub Podman
- System Linux (zalecany) lub Windows z WSL2

### Instalacja Python

```bash
# Klonowanie repozytorium
git clone https://github.com/TWOJA_NAZWA/ssh-automation-minio.git
cd ssh-automation-minio

# Instalacja zależności
pip install -r requirements.txt
```

### Instalacja Ansible

```bash
# Ubuntu/Debian
sudo apt-get install ansible

# Fedora/RHEL
sudo dnf install ansible

# macOS
brew install ansible
```

## 📖 Użycie

### SSH Automation - Przykłady

#### Pojedyncze polecenie
```python
from ssh_automation import SSHExecutor

executor = SSHExecutor("10.10.9.50", "admin", "haslo")
if executor.connect():
    result = executor.execute_command("uptime")
    if result['success']:
        print(f"Uptime: {result['output'][0]}")
    executor.disconnect()
```

#### Wiele poleceń
```python
commands = ["hostname", "date", "df -h"]
results = executor.execute_commands(commands)

for i, result in enumerate(results):
    print(f"\n{commands[i]}:")
    for line in result['output']:
        print(f"  {line}")
```

#### Niestandardowy port SSH
```python
executor = SSHExecutor("10.10.9.50", "admin", "haslo", port=2222)
```

### MinIO Deployment - Przykłady

#### Podstawowe wdrożenie
```bash
ansible-playbook minio-playbook.yml
```

#### Produkcyjne wdrożenie z HTTPS
```bash
ansible-playbook minio-playbook.yml \
  -e "minio_admin_user=prod-admin" \
  -e "minio_admin_password=$(openssl rand -base64 32)" \
  -e "use_custom_certs=true" \
  -e "ca_cert_path=/etc/ssl/certs/ca.crt" \
  -e "minio_cert_path=/etc/ssl/certs/minio.crt" \
  -e "minio_key_path=/etc/ssl/private/minio.key"
```

#### Wdrożenie z Podman
```bash
ansible-playbook minio-playbook.yml \
  -e "container_runtime=podman" \
  -e "use_host_network=true"
```

## 📚 Dokumentacja

### SSH Automation
- [README_SSH_AUTOMATION.md](README_SSH_AUTOMATION.md) - Pełna dokumentacja SSH Automation
- [QUICK_START.md](QUICK_START.md) - Szybki start z przykładami
- [example_usage.py](example_usage.py) - Przykłady użycia

### MinIO Deployment
- [README.md](README.md) - Pełna dokumentacja MinIO Deployment
- [INSTRUKCJE_WDROZENIA.md](INSTRUKCJE_WDROZENIA.md) - Instrukcje wdrożenia
- [PLAN_POPRAWEK_ANSIBLE.md](PLAN_POPRAWEK_ANSIBLE.md) - Plan poprawek

## 💡 Przykłady

### Przykład 1: Sprawdzenie statusu serwera
```python
from ssh_automation import SSHExecutor

def check_server_status(host, username, password):
    executor = SSHExecutor(host, username, password)
    
    try:
        if not executor.connect():
            return "Nie można połączyć"
        
        commands = [
            "uptime",
            "free -h",
            "df -h /",
            "systemctl status docker"
        ]
        
        results = executor.execute_commands(commands)
        
        for i, result in enumerate(results):
            print(f"\n=== {commands[i]} ===")
            if result['success']:
                for line in result['output']:
                    print(line)
            else:
                print(f"Błąd: {result['error']}")
                
    finally:
        executor.disconnect()

check_server_status("10.10.9.50", "admin", "haslo")
```

### Przykład 2: Wdrożenie MinIO dla środowiska deweloperskiego
```bash
ansible-playbook minio-playbook.yml \
  -e "minio_admin_user=dev" \
  -e "minio_admin_password=dev123" \
  -e "minio_data_path=/home/developer/minio-dev" \
  -e "s3_bucket_name=dev-bucket" \
  -e "configure_firewall=false"
```

## 🐙 Publikacja na GitHub

### Automatyczna konfiguracja (zalecane)

**Windows:**
```powershell
.\setup_github.ps1
```

**Linux/Mac:**
```bash
chmod +x setup_github.sh
./setup_github.sh
```

### Ręczna konfiguracja

Szczegółowe instrukcje znajdziesz w [GITHUB_SETUP.md](GITHUB_SETUP.md)

**Krótka wersja:**

1. **Zainstaluj Git:**
   - Windows: https://git-scm.com/download/win
   - Linux: `sudo apt-get install git`
   - Mac: `brew install git`

2. **Inicjalizacja repozytorium:**
```bash
git init
git add .
git commit -m "Initial commit"
```

3. **Utwórz repozytorium na GitHub:**
   - Przejdź na https://github.com/new
   - Nazwa: `ssh-automation-minio`
   - Kliknij "Create repository"

4. **Połącz i wypchnij:**
```bash
git remote add origin https://github.com/USERNAME/ssh-automation-minio.git
git branch -M main
git push -u origin main
```

### Aktualizacja kodu

Po wprowadzeniu zmian:
```bash
git add .
git commit -m "Opis zmian"
git push
```

## 🔧 Konfiguracja

### SSH Automation

Parametry połączenia można przekazać przez zmienne środowiskowe:

```bash
export SSH_HOST=10.10.9.50
export SSH_USER=admin
export SSH_PASSWORD=haslo
export SSH_PORT=22
```

### MinIO Deployment

Wszystkie zmienne konfiguracyjne są opisane w [README.md](README.md)

Najważniejsze:
- `minio_admin_user` - Nazwa użytkownika administratora
- `minio_admin_password` - Hasło administratora
- `minio_data_path` - Ścieżka do danych
- `s3_bucket_name` - Nazwa bucket S3
- `container_runtime` - docker lub podman

## 🤝 Współpraca

Chętnie przyjmujemy pull requesty! Jeśli chcesz wnieść wkład:

1. Fork projektu
2. Utwórz branch dla swojej funkcji (`git checkout -b feature/AmazingFeature`)
3. Commit zmian (`git commit -m 'Add some AmazingFeature'`)
4. Push do brancha (`git push origin feature/AmazingFeature`)
5. Otwórz Pull Request

## 📝 Licencja

Ten projekt jest licencjonowany na licencji MIT - zobacz plik [LICENSE](LICENSE) dla szczegółów.

## 👤 Autor

**Bob**

## 🙏 Podziękowania

- Społeczność Ansible
- Zespół MinIO
- Twórcy biblioteki Paramiko

## 📞 Wsparcie

Jeśli masz pytania lub problemy:
- Otwórz Issue na GitHub
- Zobacz dokumentację w katalogu projektu
- Sprawdź sekcję "Rozwiązywanie problemów" w dokumentacji

## 🗺️ Roadmap

- [ ] Wsparcie dla kluczy SSH (bez hasła)
- [ ] GUI dla SSH Automation
- [ ] Wsparcie dla Kubernetes w MinIO
- [ ] Automatyczne testy
- [ ] Docker Compose dla MinIO
- [ ] Integracja z CI/CD

---

**Made with ❤️ by Bob**