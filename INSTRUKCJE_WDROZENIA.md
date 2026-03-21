# Instrukcje Wdrożenia Zaktualizowanego MinIO Playbooka

## Co Zostało Naprawione

✅ **MinIO dostępne spoza maszyny** - dodano `--network host` dla Podman lub binding do `0.0.0.0`  
✅ **Automatyczna konfiguracja firewalld** - porty 9000 i 9001 otwierane automatycznie  
✅ **Walidacja HTTPS** - sprawdzanie czy certyfikaty działają  
✅ **Test dostępu zewnętrznego** - automatyczne sprawdzanie dostępności z IP serwera  
✅ **Lepsze komunikaty** - jasne informacje o konfiguracji i błędach

---

## Jak Wdrożyć Zmiany

### Krok 1: Zatrzymaj Obecny Kontener MinIO

```bash
podman stop minio
podman rm minio
```

### Krok 2: Uruchom Zaktualizowany Playbook

**Dla HTTP (bez certyfikatów):**
```bash
ansible-playbook minio-playbook.yml \
  -e "container_runtime=podman" \
  -e "use_host_network=true" \
  -e "configure_firewall=true"
```

**Dla HTTPS (gdy certyfikaty będą na serwerze):**
```bash
# Najpierw przenieś certyfikaty na serwer (z innej maszyny):
scp /path/to/ca.crt root@10.10.9.50:/tmp/
scp /path/to/server.crt root@10.10.9.50:/tmp/
scp /path/to/server.key root@10.10.9.50:/tmp/

# Następnie uruchom playbook:
ansible-playbook minio-playbook.yml \
  -e "container_runtime=podman" \
  -e "use_host_network=true" \
  -e "configure_firewall=true" \
  -e "use_custom_certs=true" \
  -e "ca_cert_path=/tmp/ca.crt" \
  -e "minio_cert_path=/tmp/server.crt" \
  -e "minio_key_path=/tmp/server.key"
```

### Krok 3: Sprawdź Wyniki

Po uruchomieniu playbooka sprawdź:

1. **Logi MinIO:**
   ```bash
   podman logs minio | grep -E "API:|WebUI:"
   ```
   
   Powinieneś zobaczyć:
   ```
   API: http://10.10.9.50:9000  http://127.0.0.1:9000
   WebUI: http://10.10.9.50:9001 http://127.0.0.1:9001
   ```
   
   (lub `https://` jeśli używasz certyfikatów)

2. **Firewall:**
   ```bash
   sudo firewall-cmd --list-ports
   ```
   
   Powinieneś zobaczyć:
   ```
   9000/tcp 9001/tcp
   ```

3. **Dostęp z innej maszyny:**
   ```bash
   # Z innego komputera w sieci
   curl http://10.10.9.50:9000/minio/health/live
   ```
   
   Powinieneś otrzymać odpowiedź HTTP 200

4. **Plik z informacjami:**
   ```bash
   cat minio_access_info.txt
   ```
   
   Sprawdź czy zawiera poprawne IP i URL-e

---

## Nowe Zmienne Konfiguracyjne

### `use_host_network` (domyślnie: `true`)
- **Zalecane dla Podman**
- MinIO nasłuchuje na wszystkich interfejsach sieciowych
- Używa sieci hosta zamiast bridge network

### `bind_to_all_interfaces` (domyślnie: `true`)
- Używane gdy `use_host_network=false`
- Binduje porty do `0.0.0.0` zamiast tylko localhost

### `configure_firewall` (domyślnie: `true`)
- Automatycznie otwiera porty 9000 i 9001 w firewalld
- Działa tylko na systemach z firewalld (RHEL/CentOS/Fedora)

### `validate_external_access` (domyślnie: `true`)
- Sprawdza czy MinIO jest dostępne z zewnętrznego IP
- Wyświetla ostrzeżenie jeśli test się nie powiedzie

---

## Przykłady Użycia

### 1. Podstawowe wdrożenie (HTTP, Podman, z firewall)
```bash
ansible-playbook minio-playbook.yml
```

### 2. Wdrożenie z Docker zamiast Podman
```bash
ansible-playbook minio-playbook.yml \
  -e "container_runtime=docker" \
  -e "use_host_network=false" \
  -e "bind_to_all_interfaces=true"
```

### 3. Wdrożenie bez konfiguracji firewall
```bash
ansible-playbook minio-playbook.yml \
  -e "configure_firewall=false"
```

### 4. Wdrożenie z HTTPS
```bash
ansible-playbook minio-playbook.yml \
  -e "use_custom_certs=true" \
  -e "ca_cert_path=/tmp/ca.crt" \
  -e "minio_cert_path=/tmp/server.crt" \
  -e "minio_key_path=/tmp/server.key"
```

---

## Weryfikacja Po Wdrożeniu

### ✅ Checklist

- [ ] MinIO nasłuchuje na rzeczywistym IP serwera (10.10.9.50)
- [ ] Porty 9000 i 9001 są otwarte w firewalld
- [ ] MinIO jest dostępne z innej maszyny w sieci
- [ ] Konsola webowa działa: http://10.10.9.50:9001
- [ ] API działa: http://10.10.9.50:9000
- [ ] Plik `minio_access_info.txt` zawiera poprawne informacje
- [ ] (Opcjonalnie) HTTPS działa jeśli używasz certyfikatów

### Komendy Weryfikacyjne

```bash
# 1. Sprawdź status kontenera
podman ps | grep minio

# 2. Sprawdź logi
podman logs minio | tail -20

# 3. Sprawdź na jakich adresach nasłuchuje
podman logs minio | grep -E "API:|WebUI:"

# 4. Sprawdź firewall
sudo firewall-cmd --list-ports

# 5. Sprawdź porty
ss -tlnp | grep -E '9000|9001'

# 6. Test lokalny
curl http://localhost:9000/minio/health/live

# 7. Test zewnętrzny (z tego samego serwera)
curl http://10.10.9.50:9000/minio/health/live

# 8. Test z innej maszyny (uruchom z innego komputera)
curl http://10.10.9.50:9000/minio/health/live
```

---

## Rozwiązywanie Problemów

### Problem: MinIO nadal nasłuchuje tylko na localhost

**Rozwiązanie:**
```bash
# Sprawdź czy używasz host network
podman inspect minio | grep -i network

# Jeśli nie, usuń i uruchom ponownie z use_host_network=true
podman stop minio && podman rm minio
ansible-playbook minio-playbook.yml -e "use_host_network=true"
```

### Problem: Firewall blokuje połączenia

**Rozwiązanie:**
```bash
# Sprawdź status firewalld
sudo systemctl status firewalld

# Otwórz porty ręcznie
sudo firewall-cmd --permanent --add-port=9000/tcp
sudo firewall-cmd --permanent --add-port=9001/tcp
sudo firewall-cmd --reload

# Lub uruchom playbook z configure_firewall=true
ansible-playbook minio-playbook.yml -e "configure_firewall=true"
```

### Problem: MinIO działa na HTTP mimo certyfikatów

**Rozwiązanie:**
```bash
# Sprawdź czy certyfikaty są w odpowiednim miejscu
ls -la /data/minio/certs/

# Sprawdź logi
podman logs minio | grep -i "certificate\|tls\|https"

# Sprawdź uprawnienia
sudo chmod 644 /data/minio/certs/public.crt
sudo chmod 600 /data/minio/certs/private.key

# Zrestartuj
podman stop minio && podman rm minio
ansible-playbook minio-playbook.yml -e "use_custom_certs=true" -e "ca_cert_path=/tmp/ca.crt" -e "minio_cert_path=/tmp/server.crt" -e "minio_key_path=/tmp/server.key"
```

---

## Następne Kroki

1. ✅ Wdróż zaktualizowany playbook
2. ✅ Zweryfikuj dostęp z zewnątrz
3. ⏳ (Opcjonalnie) Przenieś certyfikaty i włącz HTTPS
4. ⏳ Zaktualizuj aplikacje korzystające z MinIO z nowymi URL-ami
5. ⏳ Przetestuj backup i restore

---

## Kontakt i Wsparcie

Jeśli napotkasz problemy:
1. Sprawdź logi: `podman logs minio`
2. Sprawdź sekcję "Rozwiązywanie Problemów" w README.md
3. Sprawdź dokumentację MinIO: https://min.io/docs/minio/linux/index.html

---

**Data aktualizacji:** 2026-03-20  
**Wersja playbooka:** 2.0 (z poprawkami sieci i firewall)