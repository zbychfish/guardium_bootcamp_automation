#!/bin/bash
# Skrypt automatyzacji GitHub dla projektu SSH Automation & MinIO
# Autor: Bob
# Data: 2026-03-21

# Kolory
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
NC='\033[0m' # No Color

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  GitHub Setup - SSH Automation & MinIO${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""

# Sprawdzenie czy Git jest zainstalowany
echo -e "${YELLOW}[1/8] Sprawdzanie instalacji Git...${NC}"
if command -v git &> /dev/null; then
    GIT_VERSION=$(git --version)
    echo -e "${GREEN}✓ Git jest zainstalowany: $GIT_VERSION${NC}"
else
    echo -e "${RED}✗ Git nie jest zainstalowany!${NC}"
    echo ""
    echo -e "${YELLOW}Instalacja Git:${NC}"
    echo -e "${WHITE}  Ubuntu/Debian: sudo apt-get install git${NC}"
    echo -e "${WHITE}  Fedora/RHEL:   sudo dnf install git${NC}"
    echo -e "${WHITE}  macOS:         brew install git${NC}"
    echo ""
    exit 1
fi

echo ""

# Sprawdzenie konfiguracji Git
echo -e "${YELLOW}[2/8] Sprawdzanie konfiguracji Git...${NC}"
GIT_USER=$(git config --global user.name 2>&1)
GIT_EMAIL=$(git config --global user.email 2>&1)

if [ -z "$GIT_USER" ] || [ -z "$GIT_EMAIL" ]; then
    echo -e "${YELLOW}⚠ Git nie jest skonfigurowany${NC}"
    echo ""
    read -p "Podaj swoją nazwę użytkownika Git: " USER_NAME
    read -p "Podaj swój email Git: " USER_EMAIL
    
    git config --global user.name "$USER_NAME"
    git config --global user.email "$USER_EMAIL"
    
    echo -e "${GREEN}✓ Konfiguracja Git zapisana${NC}"
else
    echo -e "${GREEN}✓ Git jest skonfigurowany:${NC}"
    echo -e "  Użytkownik: $GIT_USER"
    echo -e "  Email: $GIT_EMAIL"
fi

echo ""

# Inicjalizacja repozytorium
echo -e "${YELLOW}[3/8] Inicjalizacja repozytorium Git...${NC}"
if [ -d ".git" ]; then
    echo -e "${YELLOW}⚠ Repozytorium Git już istnieje${NC}"
else
    git init
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ Repozytorium Git zainicjalizowane${NC}"
    else
        echo -e "${RED}✗ Błąd inicjalizacji repozytorium${NC}"
        exit 1
    fi
fi

echo ""

# Dodanie plików
echo -e "${YELLOW}[4/8] Dodawanie plików do repozytorium...${NC}"
git add .
if [ $? -eq 0 ]; then
    FILES_COUNT=$(git diff --cached --numstat | wc -l)
    echo -e "${GREEN}✓ Dodano $FILES_COUNT plików${NC}"
else
    echo -e "${RED}✗ Błąd dodawania plików${NC}"
    exit 1
fi

echo ""

# Utworzenie commita
echo -e "${YELLOW}[5/8] Tworzenie pierwszego commita...${NC}"
git commit -m "Initial commit: SSH Automation i MinIO Ansible Deployment"
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Commit utworzony${NC}"
else
    echo -e "${RED}✗ Błąd tworzenia commita${NC}"
    exit 1
fi

echo ""

# Zmiana nazwy gałęzi na main
echo -e "${YELLOW}[6/8] Zmiana nazwy gałęzi na 'main'...${NC}"
git branch -M main
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Gałąź zmieniona na 'main'${NC}"
else
    echo -e "${YELLOW}⚠ Nie udało się zmienić nazwy gałęzi${NC}"
fi

echo ""
echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  NASTĘPNE KROKI - RĘCZNE${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""

echo -e "${YELLOW}[7/8] Utworzenie repozytorium na GitHub:${NC}"
echo -e "${WHITE}  1. Przejdź na https://github.com/new${NC}"
echo -e "${WHITE}  2. Nazwa repozytorium: ssh-automation-minio${NC}"
echo -e "${WHITE}  3. Opis: SSH Automation tool and MinIO Ansible deployment${NC}"
echo -e "${WHITE}  4. Wybierz Public lub Private${NC}"
echo -e "${WHITE}  5. NIE zaznaczaj 'Initialize with README'${NC}"
echo -e "${WHITE}  6. Kliknij 'Create repository'${NC}"
echo ""

read -p "Czy utworzyłeś repozytorium na GitHub? (t/n): " CONTINUE
if [ "$CONTINUE" != "t" ]; then
    echo ""
    echo -e "${YELLOW}Przerwano. Uruchom skrypt ponownie po utworzeniu repozytorium.${NC}"
    exit 0
fi

echo ""
echo -e "${YELLOW}[8/8] Połączenie z GitHub:${NC}"
read -p "Podaj URL repozytorium (np. https://github.com/username/ssh-automation-minio.git): " REPO_URL

# Dodanie zdalnego repozytorium
git remote add origin "$REPO_URL" 2>&1 > /dev/null
if [ $? -ne 0 ]; then
    echo -e "${YELLOW}⚠ Remote 'origin' już istnieje, aktualizuję...${NC}"
    git remote set-url origin "$REPO_URL"
fi

echo -e "${GREEN}✓ Zdalne repozytorium dodane${NC}"
echo ""

# Push do GitHub
echo -e "${YELLOW}Wypychanie kodu na GitHub...${NC}"
echo ""
echo -e "${CYAN}UWAGA: Zostaniesz poproszony o uwierzytelnienie:${NC}"
echo -e "${WHITE}  - Użytkownik: Twoja nazwa użytkownika GitHub${NC}"
echo -e "${WHITE}  - Hasło: Personal Access Token (NIE hasło do konta!)${NC}"
echo ""
echo -e "${YELLOW}Jak uzyskać Personal Access Token:${NC}"
echo -e "${WHITE}  1. GitHub → Settings → Developer settings${NC}"
echo -e "${WHITE}  2. Personal access tokens → Tokens (classic)${NC}"
echo -e "${WHITE}  3. Generate new token (classic)${NC}"
echo -e "${WHITE}  4. Wybierz uprawnienia: repo (pełny dostęp)${NC}"
echo -e "${WHITE}  5. Skopiuj wygenerowany token${NC}"
echo ""

read -p "Czy chcesz teraz wypchnąć kod na GitHub? (t/n): " PUSH_NOW
if [ "$PUSH_NOW" = "t" ]; then
    git push -u origin main
    
    if [ $? -eq 0 ]; then
        echo ""
        echo -e "${GREEN}========================================${NC}"
        echo -e "${GREEN}  ✓ SUKCES!${NC}"
        echo -e "${GREEN}========================================${NC}"
        echo ""
        echo -e "${GREEN}Twój projekt jest teraz na GitHub!${NC}"
        echo -e "${CYAN}URL: $REPO_URL${NC}"
        echo ""
    else
        echo ""
        echo -e "${RED}✗ Błąd podczas push${NC}"
        echo ""
        echo -e "${YELLOW}Spróbuj ręcznie:${NC}"
        echo -e "${WHITE}  git push -u origin main${NC}"
        echo ""
    fi
else
    echo ""
    echo -e "${YELLOW}Aby wypchnąć kod później, użyj:${NC}"
    echo -e "${WHITE}  git push -u origin main${NC}"
    echo ""
fi

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  PRZYDATNE KOMENDY${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""
echo -e "${YELLOW}Aktualizacja kodu w przyszłości:${NC}"
echo -e "${WHITE}  git add .${NC}"
echo -e "${WHITE}  git commit -m 'Opis zmian'${NC}"
echo -e "${WHITE}  git push${NC}"
echo ""
echo -e "${YELLOW}Sprawdzenie statusu:${NC}"
echo -e "${WHITE}  git status${NC}"
echo ""
echo -e "${YELLOW}Historia commitów:${NC}"
echo -e "${WHITE}  git log --oneline${NC}"
echo ""

# Made with Bob
