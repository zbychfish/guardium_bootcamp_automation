# MinIO Ansible Deployment

Ansible playbook do wdrożenia MinIO w kontenerze Docker/Podman z obsługą niestandardowych certyfikatów i automatycznym tworzeniem bucket S3.

## Wymagania

- Ansible 2.9+
- Docker lub Podman
- System Linux (zalecany) lub Windows z WSL2

## Funkcje

- ✅ Wdrożenie MinIO w kontenerze Docker/Podman
- ✅ Konfigurowalna lokalizacja danych trwałych
- ✅ Opcjonalne niestandardowe certyfikaty CA i TLS
- ✅ Automatyczne tworzenie bucket S3
- ✅ Generowanie pliku z informacjami dostępowymi
- ✅ Parametryzowane dane logowania administratora

## Szybki Start

### 1. Podstawowe wdrożenie (domyślne ustawienia)

```bash
ansible-playbook minio-playbook.yml
```

### 2. Wdrożenie z niestandardowymi parametrami

```bash
ansible-playbook minio-playbook.yml \
  -e "minio_admin_user=admin" \
  -e "minio_admin_password=SecurePass123!" \
  -e "minio_data_path=/opt/minio-data" \
  -e "s3_bucket_name=my-app-bucket"
```

### 3. Wdrożenie z niestandardowymi certyfikatami

```bash
ansible-playbook minio-playbook.yml \
  -e "use_custom_certs=true" \
  -e "ca_cert_path=/path/to/ca.crt" \
  -e "minio_cert_path=/path/to/server.crt" \
  -e "minio_key_path=/path/to/server.key"
```

### 4. Użycie Podman zamiast Docker

```bash
ansible-playbook minio-playbook.yml \
  -e "container_runtime=podman"
```

## Zmienne Konfiguracyjne

### Konfiguracja MinIO

| Zmienna | Domyślna Wartość | Opis |
|---------|------------------|------|
| `minio_admin_user` | `minioadmin` | Nazwa użytkownika administratora MinIO |
| `minio_admin_password` | `minioadmin123` | Hasło administratora MinIO |
| `minio_data_path` | `/data/minio` | Ścieżka do katalogu danych trwałych na hoście |
| `minio_container_name` | `minio` | Nazwa kontenera |
| `minio_image` | `quay.io/minio/minio:latest` | Obraz Docker MinIO |
| `minio_console_port` | `9001` | Port konsoli webowej MinIO |
| `minio_api_port` | `9000` | Port API MinIO (S3) |

### Konfiguracja Bucket S3

| Zmienna | Domyślna Wartość | Opis |
|---------|------------------|------|
| `s3_bucket_name` | `my-bucket` | Nazwa bucket S3 do utworzenia |

### Konfiguracja Certyfikatów (Opcjonalna)

| Zmienna | Domyślna Wartość | Opis |
|---------|------------------|------|
| `use_custom_certs` | `false` | Włącz niestandardowe certyfikaty TLS |
| `ca_cert_path` | `""` | Ścieżka do certyfikatu CA |
| `minio_cert_path` | `""` | Ścieżka do certyfikatu serwera MinIO |
| `minio_key_path` | `""` | Ścieżka do klucza prywatnego serwera |

### Konfiguracja Sieci (NOWE)

| Zmienna | Domyślna Wartość | Opis |
|---------|------------------|------|
| `use_host_network` | `true` | Użyj sieci hosta (zalecane dla Podman) |
| `bind_to_all_interfaces` | `true` | Binduj porty do 0.0.0.0 (jeśli nie używasz host network) |

### Konfiguracja Firewall (NOWE)

| Zmienna | Domyślna Wartość | Opis |
|---------|------------------|------|
| `configure_firewall` | `true` | Automatycznie otwórz porty w firewalld |

### Konfiguracja Walidacji (NOWE)

| Zmienna | Domyślna Wartość | Opis |
|---------|------------------|------|
| `validate_external_access` | `true` | Sprawdź dostęp z zewnętrznego IP po wdrożeniu |

### Inne Ustawienia

| Zmienna | Domyślna Wartość | Opis |
|---------|------------------|------|
| `output_file` | `minio_access_info.txt` | Nazwa pliku wyjściowego z informacjami dostępowymi |
| `container_runtime` | `docker` | Runtime kontenera (`docker` lub `podman`) |

## Przykłady Użycia

### Przykład 1: Podstawowe wdrożenie z Podman (zalecane)

```bash
ansible-playbook minio-playbook.yml \
  -e "container_runtime=podman" \
  -e "use_host_network=true"
```

### Przykład 2: Wdrożenie z Docker i bridge network

```bash
ansible-playbook minio-playbook.yml \
  -e "container_runtime=docker" \
  -e "use_host_network=false" \
  -e "bind_to_all_interfaces=true"
```

### Przykład 3: Produkcyjne wdrożenie z HTTPS

```bash
ansible-playbook minio-playbook.yml \
  -e "minio_admin_user=prod-admin" \
  -e "minio_admin_password=$(openssl rand -base64 32)" \
  -e "minio_data_path=/mnt/storage/minio" \
  -e "s3_bucket_name=production-data" \
  -e "use_custom_certs=true" \
  -e "ca_cert_path=/etc/ssl/certs/company-ca.crt" \
  -e "minio_cert_path=/etc/ssl/certs/minio.crt" \
  -e "minio_key_path=/etc/ssl/private/minio.key" \
  -e "container_runtime=podman"
```

### Przykład 4: Środowisko deweloperskie bez firewall

```bash
ansible-playbook minio-playbook.yml \
  -e "minio_admin_user=dev" \
  -e "minio_admin_password=dev123" \
  -e "minio_data_path=/home/developer/minio-dev" \
  -e "s3_bucket_name=dev-bucket" \
  -e "configure_firewall=false"
```

### Przykład 5: Wdrożenie bez walidacji dostępu zewnętrznego

```bash
ansible-playbook minio-playbook.yml \
  -e "validate_external_access=false"
```

### Przykład 6: Wiele bucket (uruchom playbook wielokrotnie)

```bash
# Pierwszy bucket
ansible-playbook minio-playbook.yml -e "s3_bucket_name=bucket-one"

# Drugi bucket (MinIO już działa)
ansible-playbook minio-playbook.yml -e "s3_bucket_name=bucket-two"
```

## Plik Wyjściowy

Po pomyślnym wdrożeniu, playbook generuje plik `minio_access_info.txt` (lub nazwę określoną w `output_file`) zawierający:

- URL konsoli MinIO
- Endpoint API MinIO
- Dane logowania administratora
- Informacje o bucket S3
- Przykłady konfiguracji AWS CLI
- Przykłady konfiguracji MinIO Client (mc)
- Lokalizację danych
- Informacje o certyfikatach (jeśli używane)
- Informacje o kontenerze

## Dostęp do MinIO

### Konsola Webowa

Otwórz przeglądarkę i przejdź do:
```
http://localhost:9001
```

Zaloguj się używając `minio_admin_user` i `minio_admin_password`.

### AWS CLI

```bash
# Konfiguracja
aws configure set aws_access_key_id <minio_admin_user>
aws configure set aws_secret_access_key <minio_admin_password>
aws configure set default.region us-east-1

# Użycie
aws --endpoint-url http://localhost:9000 s3 ls
aws --endpoint-url http://localhost:9000 s3 ls s3://my-bucket
aws --endpoint-url http://localhost:9000 s3 cp file.txt s3://my-bucket/
```

### MinIO Client (mc)

```bash
# Konfiguracja
mc alias set myminio http://localhost:9000 <minio_admin_user> <minio_admin_password>

# Użycie
mc ls myminio
mc ls myminio/my-bucket
mc cp file.txt myminio/my-bucket/
```

### Python (boto3)

```python
import boto3

s3 = boto3.client(
    's3',
    endpoint_url='http://localhost:9000',
    aws_access_key_id='minioadmin',
    aws_secret_access_key='minioadmin123',
    region_name='us-east-1'
)

# Lista bucket
response = s3.list_buckets()
print(response['Buckets'])

# Upload pliku
s3.upload_file('local-file.txt', 'my-bucket', 'remote-file.txt')
```

## Zarządzanie Kontenerem

### Sprawdzenie statusu

```bash
docker ps | grep minio
# lub
podman ps | grep minio
```

### Wyświetlenie logów

```bash
docker logs minio
# lub
podman logs minio
```

### Zatrzymanie MinIO

```bash
docker stop minio
# lub
podman stop minio
```

### Uruchomienie ponownie

```bash
docker start minio
# lub
podman start minio
```

### Usunięcie kontenera

```bash
docker stop minio && docker rm minio
# lub
podman stop minio && podman rm minio
```

## Konfiguracja Certyfikatów

### Struktura katalogów certyfikatów

Gdy `use_custom_certs=true`, certyfikaty są kopiowane do:

```
<minio_data_path>/
└── certs/
    ├── CAs/
    │   └── ca.crt          # Certyfikat CA (opcjonalny)
    ├── public.crt          # Certyfikat serwera
    └── private.key         # Klucz prywatny
```

### Generowanie certyfikatów testowych

```bash
# Generowanie CA
openssl genrsa -out ca.key 2048
openssl req -new -x509 -days 365 -key ca.key -out ca.crt

# Generowanie certyfikatu serwera
openssl genrsa -out server.key 2048
openssl req -new -key server.key -out server.csr
openssl x509 -req -days 365 -in server.csr -CA ca.crt -CAkey ca.key -set_serial 01 -out server.crt
```

## Rozwiązywanie Problemów

### MinIO nie jest dostępne spoza maszyny

**Objawy:** MinIO działa lokalnie, ale nie można się połączyć z innej maszyny

**Rozwiązania:**

1. Sprawdź na jakich adresach MinIO nasłuchuje:
   ```bash
   podman logs minio | grep -E "API:|WebUI:"
   # Powinno pokazać Twój rzeczywisty IP (np. 10.10.9.50), nie tylko localhost
   ```

2. Jeśli MinIO nasłuchuje tylko na localhost/wewnętrznym IP:
   ```bash
   # Uruchom ponownie z use_host_network=true
   ansible-playbook minio-playbook.yml -e "use_host_network=true"
   ```

3. Sprawdź firewall:
   ```bash
   sudo firewall-cmd --list-ports
   # Powinno pokazać: 9000/tcp 9001/tcp
   ```

4. Jeśli porty nie są otwarte, uruchom z configure_firewall=true:
   ```bash
   ansible-playbook minio-playbook.yml -e "configure_firewall=true"
   ```

5. Ręczne otwarcie portów w firewalld:
   ```bash
   sudo firewall-cmd --permanent --add-port=9000/tcp
   sudo firewall-cmd --permanent --add-port=9001/tcp
   sudo firewall-cmd --reload
   ```

6. Testuj dostęp z innej maszyny:
   ```bash
   # Zastąp 10.10.9.50 swoim IP
   curl http://10.10.9.50:9000/minio/health/live
   ```

### MinIO działa na HTTP mimo use_custom_certs=true

**Objawy:** Ustawiłeś `use_custom_certs=true`, ale MinIO nadal używa HTTP

**Rozwiązania:**

1. Sprawdź logi MinIO:
   ```bash
   podman logs minio | grep -i "https\|tls\|certificate"
   ```

2. Sprawdź strukturę katalogów certyfikatów:
   ```bash
   ls -la /data/minio/certs/
   # Powinno być:
   # /data/minio/certs/public.crt
   # /data/minio/certs/private.key
   # /data/minio/certs/CAs/ca.crt (opcjonalny)
   ```

3. Sprawdź uprawnienia certyfikatów:
   ```bash
   ls -la /data/minio/certs/
   # public.crt powinien mieć 644
   # private.key powinien mieć 600
   ```

4. Popraw uprawnienia jeśli potrzeba:
   ```bash
   sudo chmod 644 /data/minio/certs/public.crt
   sudo chmod 600 /data/minio/certs/private.key
   sudo chmod 644 /data/minio/certs/CAs/ca.crt
   ```

5. Zrestartuj kontener:
   ```bash
   podman stop minio && podman rm minio
   ansible-playbook minio-playbook.yml -e "use_custom_certs=true" -e "ca_cert_path=/path/to/ca.crt" -e "minio_cert_path=/path/to/server.crt" -e "minio_key_path=/path/to/server.key"
   ```

### MinIO nie startuje

1. Sprawdź logi kontenera:
   ```bash
   podman logs minio
   # lub
   docker logs minio
   ```

2. Sprawdź czy porty nie są zajęte:
   ```bash
   ss -tlnp | grep -E '9000|9001'
   # lub
   netstat -tuln | grep -E '9000|9001'
   ```

3. Sprawdź uprawnienia do katalogu danych:
   ```bash
   ls -la /data/minio
   ```

4. Sprawdź czy kontener działa:
   ```bash
   podman ps -a | grep minio
   ```

### Nie można utworzyć bucket

1. Sprawdź czy MinIO jest gotowy:
   ```bash
   curl http://localhost:9000/minio/health/live
   ```

2. Sprawdź dane logowania:
   ```bash
   podman exec minio env | grep MINIO_ROOT
   ```

3. Sprawdź logi mc (MinIO Client):
   ```bash
   podman logs minio | grep -i "mc\|bucket"
   ```

### Problemy z Podman vs Docker

**Podman (zalecane):**
- Używaj `use_host_network=true`
- Nie wymaga uprawnień root dla kontenera
- Lepsze bezpieczeństwo

**Docker:**
- Może używać `use_host_network=false` z `bind_to_all_interfaces=true`
- Wymaga uprawnień root
- Bardziej popularne rozwiązanie

### Problemy z firewalld

1. Sprawdź czy firewalld działa:
   ```bash
   sudo systemctl status firewalld
   ```

2. Jeśli firewalld nie działa:
   ```bash
   sudo systemctl start firewalld
   sudo systemctl enable firewalld
   ```

3. Sprawdź otwarte porty:
   ```bash
   sudo firewall-cmd --list-all
   ```

4. Sprawdź czy playbook otworzył porty:
   ```bash
   sudo firewall-cmd --list-ports | grep -E "9000|9001"
   ```

## Bezpieczeństwo

### Zalecenia produkcyjne

1. **Zmień domyślne hasło**: Zawsze używaj silnego, losowego hasła
2. **Użyj HTTPS**: Skonfiguruj niestandardowe certyfikaty TLS
3. **Ogranicz dostęp do sieci**: Użyj firewalla lub grup bezpieczeństwa
4. **Regularne kopie zapasowe**: Regularnie twórz kopie zapasowe `minio_data_path`
5. **Aktualizacje**: Regularnie aktualizuj obraz MinIO
6. **Polityki bucket**: Skonfiguruj odpowiednie polityki dostępu do bucket

### Przykład silnego hasła

```bash
# Generowanie bezpiecznego hasła
openssl rand -base64 32
```

## Licencja

Ten playbook jest dostarczany "tak jak jest" bez żadnych gwarancji.

## Wsparcie

Dla problemów związanych z MinIO, odwiedź:
- Dokumentacja MinIO: https://min.io/docs/minio/linux/index.html
- GitHub MinIO: https://github.com/minio/minio
