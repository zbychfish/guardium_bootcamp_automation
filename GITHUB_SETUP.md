# Przewodnik: Tworzenie projektu na GitHub

## Krok 1: Instalacja Git

### Windows
1. Pobierz Git z oficjalnej strony: https://git-scm.com/download/win
2. Uruchom instalator i postępuj zgodnie z instrukcjami
3. Wybierz domyślne opcje (zalecane)
4. Po instalacji uruchom ponownie PowerShell/Terminal

### Weryfikacja instalacji
Po instalacji otwórz nowy terminal i wpisz:
```bash
git --version
```

## Krok 2: Konfiguracja Git

Po zainstalowaniu Git, skonfiguruj swoją tożsamość:

```bash
git config --global user.name "Twoje Imię"
git config --global user.email "twoj.email@example.com"
```

## Krok 3: Utworzenie konta GitHub

1. Przejdź na https://github.com
2. Kliknij "Sign up"
3. Postępuj zgodnie z instrukcjami rejestracji
4. Zweryfikuj swój adres email

## Krok 4: Inicjalizacja lokalnego repozytorium

W katalogu projektu (c:/Users/zbych/bob) wykonaj:

```bash
# Inicjalizacja repozytorium
git init

# Dodanie wszystkich plików
git add .

# Pierwszy commit
git commit -m "Initial commit: SSH Automation i MinIO Ansible Deployment"
```

## Krok 5: Utworzenie repozytorium na GitHub

### Opcja A: Przez przeglądarkę (łatwiejsza)
1. Zaloguj się na https://github.com
2. Kliknij "+" w prawym górnym rogu → "New repository"
3. Wypełnij formularz:
   - **Repository name**: `ssh-automation-minio` (lub inna nazwa)
   - **Description**: "SSH Automation tool and MinIO Ansible deployment"
   - **Public/Private**: Wybierz według preferencji
   - **NIE zaznaczaj**: "Initialize this repository with a README"
4. Kliknij "Create repository"

### Opcja B: Przez GitHub CLI (wymaga instalacji gh)
```bash
gh repo create ssh-automation-minio --public --source=. --remote=origin
```

## Krok 6: Połączenie lokalnego repo z GitHub

Po utworzeniu repozytorium na GitHub, skopiuj URL (np. https://github.com/username/ssh-automation-minio.git)

```bash
# Dodaj zdalne repozytorium
git remote add origin https://github.com/TWOJA_NAZWA_UZYTKOWNIKA/ssh-automation-minio.git

# Zmień nazwę głównej gałęzi na main (jeśli potrzeba)
git branch -M main

# Wypchnij kod na GitHub
git push -u origin main
```

## Krok 7: Uwierzytelnienie

Przy pierwszym push Git poprosi o uwierzytelnienie:

### Opcja 1: Personal Access Token (zalecane)
1. Przejdź na GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
2. Kliknij "Generate new token (classic)"
3. Nadaj nazwę (np. "SSH Automation Project")
4. Wybierz uprawnienia: `repo` (pełny dostęp do repozytoriów)
5. Kliknij "Generate token"
6. **SKOPIUJ TOKEN** (nie będziesz mógł go ponownie zobaczyć!)
7. Przy push użyj tokena jako hasła

### Opcja 2: GitHub CLI
```bash
# Instalacja GitHub CLI
winget install --id GitHub.cli

# Logowanie
gh auth login
```

## Krok 8: Weryfikacja

Sprawdź czy kod jest na GitHub:
1. Przejdź na https://github.com/TWOJA_NAZWA_UZYTKOWNIKA/ssh-automation-minio
2. Powinieneś zobaczyć wszystkie pliki projektu

## Aktualizacja kodu w przyszłości

Po wprowadzeniu zmian w kodzie:

```bash
# Sprawdź status
git status

# Dodaj zmienione pliki
git add .

# Lub dodaj konkretne pliki
git add ssh_automation.py example_usage.py

# Utwórz commit z opisem zmian
git commit -m "Opis wprowadzonych zmian"

# Wypchnij na GitHub
git push
```

## Przydatne komendy Git

```bash
# Status repozytorium
git status

# Historia commitów
git log --oneline

# Cofnięcie zmian w pliku
git checkout -- nazwa_pliku.py

# Pobranie zmian z GitHub
git pull

# Lista zdalnych repozytoriów
git remote -v

# Tworzenie nowej gałęzi
git checkout -b nazwa-galezi

# Przełączanie między gałęziami
git checkout main
```

## Struktura projektu na GitHub

Twoje repozytorium będzie zawierać:
```
ssh-automation-minio/
├── .gitignore
├── README.md
├── README_SSH_AUTOMATION.md
├── QUICK_START.md
├── GITHUB_SETUP.md (ten plik)
├── INSTRUKCJE_WDROZENIA.md
├── PLAN_POPRAWEK_ANSIBLE.md
├── ssh_automation.py
├── example_usage.py
├── requirements.txt
└── minio-playbook.yml
```

## Rozwiązywanie problemów

### Problem: "fatal: not a git repository"
**Rozwiązanie:** Upewnij się, że jesteś w katalogu projektu i wykonaj `git init`

### Problem: "remote origin already exists"
**Rozwiązanie:** 
```bash
git remote remove origin
git remote add origin https://github.com/username/repo.git
```

### Problem: "failed to push some refs"
**Rozwiązanie:**
```bash
git pull origin main --rebase
git push origin main
```

### Problem: Uwierzytelnienie nie działa
**Rozwiązanie:** Użyj Personal Access Token zamiast hasła

## Następne kroki

Po skonfigurowaniu GitHub:
1. ✅ Dodaj opis projektu w README.md
2. ✅ Dodaj licencję (np. MIT)
3. ✅ Dodaj badges do README
4. ✅ Skonfiguruj GitHub Actions (opcjonalnie)
5. ✅ Dodaj CONTRIBUTING.md (opcjonalnie)

## Wsparcie

- Dokumentacja Git: https://git-scm.com/doc
- GitHub Docs: https://docs.github.com
- GitHub Learning Lab: https://lab.github.com

---

**Autor:** Bob  
**Data:** 2026-03-21