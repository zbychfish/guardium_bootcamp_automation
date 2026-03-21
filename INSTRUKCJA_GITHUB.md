# 📘 Instrukcja Krok po Kroku - Publikacja na GitHub

## 🎯 Cel
Ta instrukcja pomoże Ci opublikować projekt SSH Automation & MinIO na GitHub.

## ✅ Przed rozpoczęciem

Upewnij się, że masz:
- [ ] Komputer z systemem Windows/Linux/Mac
- [ ] Dostęp do internetu
- [ ] Konto email (do rejestracji GitHub)

## 📋 Krok 1: Instalacja Git

### Windows

1. **Pobierz Git:**
   - Otwórz przeglądarkę
   - Przejdź na: https://git-scm.com/download/win
   - Pobierz instalator (automatycznie rozpocznie się pobieranie)

2. **Zainstaluj Git:**
   - Uruchom pobrany plik `.exe`
   - Kliknij "Next" we wszystkich krokach (domyślne ustawienia są OK)
   - Kliknij "Install"
   - Poczekaj na zakończenie instalacji
   - Kliknij "Finish"

3. **Weryfikacja:**
   - Otwórz **nowy** PowerShell (ważne: nowy terminal!)
   - Wpisz: `git --version`
   - Powinieneś zobaczyć wersję Git (np. "git version 2.43.0")

### Linux

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install git

# Fedora/RHEL
sudo dnf install git

# Weryfikacja
git --version
```

### Mac

```bash
# Instalacja przez Homebrew
brew install git

# Weryfikacja
git --version
```

## 📋 Krok 2: Konfiguracja Git

1. **Otwórz terminal** (PowerShell na Windows)

2. **Ustaw swoją nazwę:**
```bash
git config --global user.name "Twoje Imię i Nazwisko"
```
Przykład:
```bash
git config --global user.name "Jan Kowalski"
```

3. **Ustaw swój email:**
```bash
git config --global user.email "twoj.email@example.com"
```
Przykład:
```bash
git config --global user.email "jan.kowalski@gmail.com"
```

4. **Sprawdź konfigurację:**
```bash
git config --global --list
```

## 📋 Krok 3: Utworzenie konta GitHub

1. **Przejdź na GitHub:**
   - Otwórz przeglądarkę
   - Wejdź na: https://github.com

2. **Zarejestruj się:**
   - Kliknij "Sign up" (w prawym górnym rogu)
   - Podaj swój email
   - Utwórz hasło (silne!)
   - Wybierz nazwę użytkownika (będzie widoczna publicznie)
   - Kliknij "Continue"

3. **Weryfikacja email:**
   - Sprawdź swoją skrzynkę email
   - Znajdź email od GitHub
   - Kliknij link weryfikacyjny

4. **Zaloguj się:**
   - Wróć na https://github.com
   - Zaloguj się swoimi danymi

## 📋 Krok 4: Użycie automatycznego skryptu (ZALECANE)

### Windows

1. **Otwórz PowerShell w katalogu projektu:**
   - Otwórz folder `c:/Users/zbych/bob` w Eksploratorze
   - Kliknij prawym przyciskiem w pustym miejscu
   - Wybierz "Open in Terminal" lub "Otwórz w PowerShell"

2. **Uruchom skrypt:**
```powershell
.\setup_github.ps1
```

3. **Postępuj zgodnie z instrukcjami na ekranie:**
   - Skrypt sprawdzi Git
   - Skonfiguruje repozytorium
   - Poprosi Cię o utworzenie repo na GitHub
   - Połączy z GitHub
   - Wypchnię kod

### Linux/Mac

1. **Otwórz terminal w katalogu projektu:**
```bash
cd /ścieżka/do/projektu
```

2. **Nadaj uprawnienia wykonywania:**
```bash
chmod +x setup_github.sh
```

3. **Uruchom skrypt:**
```bash
./setup_github.sh
```

## 📋 Krok 5: Utworzenie repozytorium na GitHub (podczas działania skryptu)

Gdy skrypt poprosi Cię o utworzenie repozytorium:

1. **Otwórz nową kartę przeglądarki**

2. **Przejdź na:**
   - https://github.com/new

3. **Wypełnij formularz:**
   - **Repository name:** `ssh-automation-minio`
   - **Description:** `SSH Automation tool and MinIO Ansible deployment`
   - **Public/Private:** Wybierz według preferencji
     - Public = każdy może zobaczyć kod
     - Private = tylko Ty widzisz kod
   - **NIE zaznaczaj:** "Add a README file"
   - **NIE zaznaczaj:** "Add .gitignore"
   - **NIE zaznaczaj:** "Choose a license"

4. **Kliknij:** "Create repository"

5. **Skopiuj URL repozytorium:**
   - Na następnej stronie zobaczysz URL
   - Będzie wyglądać jak: `https://github.com/TWOJA_NAZWA/ssh-automation-minio.git`
   - Skopiuj ten URL (Ctrl+C)

6. **Wróć do terminala:**
   - Wklej URL gdy skrypt o to poprosi

## 📋 Krok 6: Personal Access Token (PAT)

Gdy skrypt będzie wypychał kod, GitHub poprosi o uwierzytelnienie:

### Tworzenie Personal Access Token

1. **Przejdź na GitHub:**
   - https://github.com/settings/tokens

2. **Kliknij:** "Generate new token" → "Generate new token (classic)"

3. **Wypełnij formularz:**
   - **Note:** `SSH Automation Project`
   - **Expiration:** `90 days` (lub dłużej)
   - **Select scopes:** Zaznacz `repo` (pełny dostęp do repozytoriów)

4. **Kliknij:** "Generate token"

5. **WAŻNE - Skopiuj token:**
   - Token pojawi się tylko raz!
   - Skopiuj go (Ctrl+C)
   - Zapisz w bezpiecznym miejscu

### Użycie tokena

Gdy Git poprosi o hasło:
- **Username:** Twoja nazwa użytkownika GitHub
- **Password:** Wklej skopiowany token (NIE hasło do konta!)

## 📋 Krok 7: Weryfikacja

1. **Sprawdź GitHub:**
   - Przejdź na: `https://github.com/TWOJA_NAZWA/ssh-automation-minio`
   - Powinieneś zobaczyć wszystkie pliki projektu

2. **Sprawdź lokalnie:**
```bash
git status
git log --oneline
```

## 🎉 Gotowe!

Twój projekt jest teraz na GitHub! 

### Co dalej?

**Aktualizacja kodu w przyszłości:**

1. Wprowadź zmiany w plikach
2. Otwórz terminal w katalogu projektu
3. Wykonaj:
```bash
git add .
git commit -m "Opis zmian"
git push
```

**Przykład:**
```bash
# Edytujesz plik ssh_automation.py
git add ssh_automation.py
git commit -m "Dodano obsługę timeout"
git push
```

## 🆘 Rozwiązywanie problemów

### Problem: "git: command not found"
**Rozwiązanie:** Git nie jest zainstalowany lub terminal nie został zrestartowany
- Zainstaluj Git (Krok 1)
- Zamknij i otwórz ponownie terminal

### Problem: "Permission denied"
**Rozwiązanie:** Sprawdź Personal Access Token
- Upewnij się, że używasz tokena, nie hasła
- Sprawdź czy token ma uprawnienia `repo`
- Wygeneruj nowy token jeśli stary wygasł

### Problem: "remote origin already exists"
**Rozwiązanie:**
```bash
git remote remove origin
git remote add origin https://github.com/USERNAME/repo.git
```

### Problem: "failed to push"
**Rozwiązanie:**
```bash
git pull origin main --rebase
git push origin main
```

### Problem: Skrypt nie działa na Windows
**Rozwiązanie:** Zmień politykę wykonywania
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

## 📞 Potrzebujesz pomocy?

1. **Dokumentacja Git:** https://git-scm.com/doc
2. **GitHub Docs:** https://docs.github.com
3. **GitHub Support:** https://support.github.com

## ✅ Checklist

Zaznacz po wykonaniu każdego kroku:

- [ ] Git zainstalowany i skonfigurowany
- [ ] Konto GitHub utworzone i zweryfikowane
- [ ] Skrypt setup_github uruchomiony
- [ ] Repozytorium utworzone na GitHub
- [ ] Personal Access Token wygenerowany
- [ ] Kod wypchnięty na GitHub
- [ ] Projekt widoczny na GitHub

## 🎓 Dodatkowe zasoby

### Przydatne komendy Git

```bash
# Status repozytorium
git status

# Historia zmian
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

### Struktura projektu na GitHub

```
ssh-automation-minio/
├── .gitignore              # Pliki ignorowane przez Git
├── LICENSE                 # Licencja MIT
├── README_MAIN.md          # Główny README
├── README.md               # README MinIO
├── README_SSH_AUTOMATION.md # README SSH
├── QUICK_START.md          # Szybki start
├── GITHUB_SETUP.md         # Setup GitHub
├── INSTRUKCJA_GITHUB.md    # Ten plik
├── setup_github.ps1        # Skrypt Windows
├── setup_github.sh         # Skrypt Linux/Mac
├── ssh_automation.py       # Główny moduł SSH
├── example_usage.py        # Przykłady użycia
├── requirements.txt        # Zależności Python
├── minio-playbook.yml      # Playbook Ansible
└── ...                     # Inne pliki
```

---

**Powodzenia! 🚀**

Jeśli masz pytania, sprawdź dokumentację lub otwórz Issue na GitHub.

**Made with ❤️ by Bob**