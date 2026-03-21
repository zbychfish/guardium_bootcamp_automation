# 🚀 START TUTAJ - Szybka Instrukcja

## 📌 Co masz w tym projekcie?

1. **SSH Automation** - Narzędzie do automatyzacji poleceń SSH
2. **MinIO Deployment** - Automatyczne wdrożenie MinIO przez Ansible

## ⚡ Jak opublikować na GitHub? (3 kroki)

### Krok 1: Zainstaluj Git
- **Windows:** Pobierz z https://git-scm.com/download/win
- **Linux:** `sudo apt-get install git`
- **Mac:** `brew install git`

### Krok 2: Uruchom automatyczny skrypt

**Windows (PowerShell):**
```powershell
.\setup_github.ps1
```

**Linux/Mac:**
```bash
chmod +x setup_github.sh
./setup_github.sh
```

### Krok 3: Postępuj zgodnie z instrukcjami na ekranie

Skrypt przeprowadzi Cię przez:
- ✅ Konfigurację Git
- ✅ Inicjalizację repozytorium
- ✅ Utworzenie repo na GitHub
- ✅ Publikację kodu

## 📚 Szczegółowe instrukcje

Jeśli potrzebujesz więcej informacji:

1. **INSTRUKCJA_GITHUB.md** - Szczegółowa instrukcja krok po kroku
2. **GITHUB_SETUP.md** - Pełna dokumentacja konfiguracji GitHub
3. **README_MAIN.md** - Główna dokumentacja projektu

## 🆘 Problemy?

### Git nie jest rozpoznawany
**Rozwiązanie:** Zainstaluj Git i uruchom ponownie terminal

### Skrypt nie działa
**Rozwiązanie (Windows):**
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Nie masz konta GitHub
1. Przejdź na https://github.com
2. Kliknij "Sign up"
3. Postępuj zgodnie z instrukcjami

## 📖 Dokumentacja projektu

### SSH Automation
- `README_SSH_AUTOMATION.md` - Pełna dokumentacja
- `QUICK_START.md` - Szybki start
- `example_usage.py` - Przykłady użycia

### MinIO Deployment
- `README.md` - Pełna dokumentacja MinIO
- `minio-playbook.yml` - Playbook Ansible

## 🎯 Co dalej po publikacji?

### Aktualizacja kodu
```bash
git add .
git commit -m "Opis zmian"
git push
```

### Sprawdzenie statusu
```bash
git status
```

### Historia zmian
```bash
git log --oneline
```

## 💡 Szybkie linki

- **Instalacja Git:** https://git-scm.com/downloads
- **Rejestracja GitHub:** https://github.com/signup
- **Dokumentacja Git:** https://git-scm.com/doc
- **GitHub Docs:** https://docs.github.com

## ✅ Checklist

- [ ] Git zainstalowany
- [ ] Konto GitHub utworzone
- [ ] Skrypt uruchomiony
- [ ] Kod na GitHub

---

**Potrzebujesz pomocy?** Otwórz `INSTRUKCJA_GITHUB.md` dla szczegółowych instrukcji.

**Made with ❤️ by Bob**