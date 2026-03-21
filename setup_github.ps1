# Skrypt automatyzacji GitHub dla projektu SSH Automation & MinIO
# Autor: Bob
# Data: 2026-03-21

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  GitHub Setup - SSH Automation & MinIO" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Sprawdzenie czy Git jest zainstalowany
Write-Host "[1/8] Sprawdzanie instalacji Git..." -ForegroundColor Yellow
try {
    $gitVersion = git --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Git jest zainstalowany: $gitVersion" -ForegroundColor Green
    } else {
        throw "Git nie jest zainstalowany"
    }
} catch {
    Write-Host "✗ Git nie jest zainstalowany!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Pobierz Git z: https://git-scm.com/download/win" -ForegroundColor Yellow
    Write-Host "Po instalacji uruchom ponownie ten skrypt." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Naciśnij Enter aby zakończyć"
    exit 1
}

Write-Host ""

# Sprawdzenie konfiguracji Git
Write-Host "[2/8] Sprawdzanie konfiguracji Git..." -ForegroundColor Yellow
$gitUser = git config --global user.name 2>&1
$gitEmail = git config --global user.email 2>&1

if ([string]::IsNullOrWhiteSpace($gitUser) -or [string]::IsNullOrWhiteSpace($gitEmail)) {
    Write-Host "⚠ Git nie jest skonfigurowany" -ForegroundColor Yellow
    Write-Host ""
    $userName = Read-Host "Podaj swoją nazwę użytkownika Git"
    $userEmail = Read-Host "Podaj swój email Git"
    
    git config --global user.name "$userName"
    git config --global user.email "$userEmail"
    
    Write-Host "✓ Konfiguracja Git zapisana" -ForegroundColor Green
} else {
    Write-Host "✓ Git jest skonfigurowany:" -ForegroundColor Green
    Write-Host "  Użytkownik: $gitUser" -ForegroundColor Gray
    Write-Host "  Email: $gitEmail" -ForegroundColor Gray
}

Write-Host ""

# Inicjalizacja repozytorium
Write-Host "[3/8] Inicjalizacja repozytorium Git..." -ForegroundColor Yellow
if (Test-Path ".git") {
    Write-Host "⚠ Repozytorium Git już istnieje" -ForegroundColor Yellow
} else {
    git init
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Repozytorium Git zainicjalizowane" -ForegroundColor Green
    } else {
        Write-Host "✗ Błąd inicjalizacji repozytorium" -ForegroundColor Red
        exit 1
    }
}

Write-Host ""

# Dodanie plików
Write-Host "[4/8] Dodawanie plików do repozytorium..." -ForegroundColor Yellow
git add .
if ($LASTEXITCODE -eq 0) {
    $filesCount = (git diff --cached --numstat | Measure-Object).Count
    Write-Host "✓ Dodano $filesCount plików" -ForegroundColor Green
} else {
    Write-Host "✗ Błąd dodawania plików" -ForegroundColor Red
    exit 1
}

Write-Host ""

# Utworzenie commita
Write-Host "[5/8] Tworzenie pierwszego commita..." -ForegroundColor Yellow
git commit -m "Initial commit: SSH Automation i MinIO Ansible Deployment"
if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Commit utworzony" -ForegroundColor Green
} else {
    Write-Host "✗ Błąd tworzenia commita" -ForegroundColor Red
    exit 1
}

Write-Host ""

# Zmiana nazwy gałęzi na main
Write-Host "[6/8] Zmiana nazwy gałęzi na 'main'..." -ForegroundColor Yellow
git branch -M main
if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Gałąź zmieniona na 'main'" -ForegroundColor Green
} else {
    Write-Host "⚠ Nie udało się zmienić nazwy gałęzi" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  NASTĘPNE KROKI - RĘCZNE" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[7/8] Utworzenie repozytorium na GitHub:" -ForegroundColor Yellow
Write-Host "  1. Przejdź na https://github.com/new" -ForegroundColor White
Write-Host "  2. Nazwa repozytorium: ssh-automation-minio" -ForegroundColor White
Write-Host "  3. Opis: SSH Automation tool and MinIO Ansible deployment" -ForegroundColor White
Write-Host "  4. Wybierz Public lub Private" -ForegroundColor White
Write-Host "  5. NIE zaznaczaj 'Initialize with README'" -ForegroundColor White
Write-Host "  6. Kliknij 'Create repository'" -ForegroundColor White
Write-Host ""

$continue = Read-Host "Czy utworzyłeś repozytorium na GitHub? (t/n)"
if ($continue -ne "t") {
    Write-Host ""
    Write-Host "Przerwano. Uruchom skrypt ponownie po utworzeniu repozytorium." -ForegroundColor Yellow
    exit 0
}

Write-Host ""
Write-Host "[8/8] Połączenie z GitHub:" -ForegroundColor Yellow
$repoUrl = Read-Host "Podaj URL repozytorium (np. https://github.com/username/ssh-automation-minio.git)"

# Dodanie zdalnego repozytorium
git remote add origin $repoUrl 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "⚠ Remote 'origin' już istnieje, aktualizuję..." -ForegroundColor Yellow
    git remote set-url origin $repoUrl
}

Write-Host "✓ Zdalne repozytorium dodane" -ForegroundColor Green
Write-Host ""

# Push do GitHub
Write-Host "Wypychanie kodu na GitHub..." -ForegroundColor Yellow
Write-Host ""
Write-Host "UWAGA: Zostaniesz poproszony o uwierzytelnienie:" -ForegroundColor Cyan
Write-Host "  - Użytkownik: Twoja nazwa użytkownika GitHub" -ForegroundColor White
Write-Host "  - Hasło: Personal Access Token (NIE hasło do konta!)" -ForegroundColor White
Write-Host ""
Write-Host "Jak uzyskać Personal Access Token:" -ForegroundColor Yellow
Write-Host "  1. GitHub → Settings → Developer settings" -ForegroundColor White
Write-Host "  2. Personal access tokens → Tokens (classic)" -ForegroundColor White
Write-Host "  3. Generate new token (classic)" -ForegroundColor White
Write-Host "  4. Wybierz uprawnienia: repo (pełny dostęp)" -ForegroundColor White
Write-Host "  5. Skopiuj wygenerowany token" -ForegroundColor White
Write-Host ""

$pushNow = Read-Host "Czy chcesz teraz wypchnąć kod na GitHub? (t/n)"
if ($pushNow -eq "t") {
    git push -u origin main
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        Write-Host "========================================" -ForegroundColor Green
        Write-Host "  ✓ SUKCES!" -ForegroundColor Green
        Write-Host "========================================" -ForegroundColor Green
        Write-Host ""
        Write-Host "Twój projekt jest teraz na GitHub!" -ForegroundColor Green
        Write-Host "URL: $repoUrl" -ForegroundColor Cyan
        Write-Host ""
    } else {
        Write-Host ""
        Write-Host "✗ Błąd podczas push" -ForegroundColor Red
        Write-Host ""
        Write-Host "Spróbuj ręcznie:" -ForegroundColor Yellow
        Write-Host "  git push -u origin main" -ForegroundColor White
        Write-Host ""
    }
} else {
    Write-Host ""
    Write-Host "Aby wypchnąć kod później, użyj:" -ForegroundColor Yellow
    Write-Host "  git push -u origin main" -ForegroundColor White
    Write-Host ""
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  PRZYDATNE KOMENDY" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Aktualizacja kodu w przyszłości:" -ForegroundColor Yellow
Write-Host "  git add ." -ForegroundColor White
Write-Host "  git commit -m 'Opis zmian'" -ForegroundColor White
Write-Host "  git push" -ForegroundColor White
Write-Host ""
Write-Host "Sprawdzenie statusu:" -ForegroundColor Yellow
Write-Host "  git status" -ForegroundColor White
Write-Host ""
Write-Host "Historia commitów:" -ForegroundColor Yellow
Write-Host "  git log --oneline" -ForegroundColor White
Write-Host ""

Read-Host "Naciśnij Enter aby zakończyć"

# Made with Bob
