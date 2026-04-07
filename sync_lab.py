#!/usr/bin/env python3
# -*- coding: utf-8 -*-


from subprocess import SubprocessError
import os
import re
import time
import json
import paramiko
from dotenv import load_dotenv
from typing import Any, Dict, List, Optional
import urllib.request
import sys
import traceback
import zipfile
import glob
from pathlib import Path
import subprocess
from packaging.version import Version
#import pwd

from appliance_command import ApplianceCommand
from manual_web_ui_processing import guardium_customer_upload_import
from guardium_patch import install_patch
from windows_management import run_winrm
from guardium_rest_api import GuardiumRestAPI
from utils import (
    get_env_value, save_to_env, parse_unit_summary, run_as_user,
    to_valid_json, parse_mus_from_message_dict,
    parse_patch_list, get_patch_line_numbers, load_state, save_state,
    run_task, monitor_gim_module_installation, change_password_as_root,
    scp_file_as_root, run_many_commands_remotely, get_oracle_conn,
    get_postgres_conn, run_sql_oracle, run_sql_postgres,
    create_appliance as utils_create_appliance,
    wait_for_appliance as utils_wait_for_appliance
)

# Check .env file existence
env_file_path = os.path.join(os.path.dirname(__file__), '.env')
if not os.path.exists(env_file_path):
    print("=" * 60)
    print("ERROR: Configuration file .env not found!")
    print("=" * 60)
    print("\nCreate .env base on .env.example:")
    print(f"1. Copy .env.example to .env")
    print(f"2. Fill up required values in .env")
    print("=" * 60)
    sys.exit(1)

# Load environment variables from .env
load_dotenv()

# Configuration
common_config = {
    'user': 'cli',
    'initial_pattern': 'Last login',
    'timeout': 120
}

appliances = {
    'collector': {
        'host': '10.10.9.239',
        'prompt_regex': r'coll1\.gdemo\.com>',
        'password': get_env_value('COLLECTOR_PASSWORD')
    },
    'collector_unconfigured': {
        'host': '10.10.9.239',
        'prompt_regex': r'guard\.yourcompany\.com>',
        'password': get_env_value('COLLECTOR_PASSWORD'),
        'initial_pattern': None  # Disable initial_pattern for unconfigured collector
    },
    'cm': {
        'host': '10.10.9.219',
        'prompt_regex': r'cm\.gdemo\.com>',
        'password': get_env_value('CM_PASSWORD')
    },
    'toolnode': {
        'host': '10.10.9.229',
        'prompt_regex': r'toolnode\.gdemo\.com>',
        'password': get_env_value('TOOLNODE_PASSWORD')
    }
}

managed_machines: dict[str, dict[str, str]] = {
    'raptor': {
        'host': '10.10.9.70',
        'prompt_regex': r'raptor\.gdemo\.com>',
        'password': get_env_value('RAPTOR_PASSWORD')
    },
    'hana': {
        'host': '10.10.9.60',
        'prompt_regex': r'hana\.gdemo\.com>',
        'password': get_env_value('HANA_PASSWORD')
    },
    'winsql': {
        'host': '10.10.9.59',
        'prompt_regex': r'winsql\.gdemo\.com>',
        'password': get_env_value('WINSQL_PASSWORD')
    },
    'appnode': {
        'host': '10.10.9.50',
        'prompt_regex': r'appnode\.gdemo\.com>',
        'password': get_env_value('APPNODE_PASSWORD')
    }
}

# Helper functions to wrap utils functions with local config
def create_appliance(appliance_name: str) -> ApplianceCommand:
    """Create ApplianceCommand instance for given appliance"""
    return utils_create_appliance(appliance_name, appliances, common_config)

def wait_for_appliance(appliance_name: str, max_attempts: int = 40, interval: int = 15) -> ApplianceCommand:
    """Wait until appliance is available and establish connection"""
    return utils_wait_for_appliance(appliance_name, appliances, common_config, max_attempts, interval)

# State file path
STATE_FILE = "sync_lab_state.json"

def t_password_change_on_appliances():
    current_appliances = appliances.copy()
    del current_appliances['collector']
    for name, cfg in current_appliances.items():
        print(f"  ➜ Changing password on {name} ({cfg['host']})")
        ok = change_password_as_root(
            host=cfg["host"],
            root_password=get_env_value("ROOT_PASSWORD"),
            target_user="cli",
            new_password=get_env_value("COLLECTOR_PASSWORD")
        )

def t_initial_collector_settings():
    appliance = create_appliance('collector_unconfigured')
    if not appliance.connect():
        print("  ✗ Failed to connect to collector")
        exit(1)
    print("  ➜ Disabling purge")
    output = appliance.execute_command("grdapi disable_purge")
    print("  ➜ Set time zone to Europe/Warsaw")
    output = appliance.execute_command("show system clock all")
    timezone = output.strip().splitlines()[-1]
    if timezone != "Europe/Warsaw":
        output = appliance.execute_command_with_confirmation(
            command="store system clock timezone Europe/Warsaw",
            response="y",
            confirmation_pattern=r"Do you want to proceed\?\s*\(y/n\)\s*"
        )
        print("  ℹ New TZ is:")
        output = appliance.execute_command("show system clock all")
        print(output)
    else:
        print(f"  ℹ Time zone already set to {timezone}")
    print("  ➜ Configure NTP servers")
    appliance.execute_command("store system time_server hostname 0.pool.ntp.org 1.pool.ntp.org 2.pool.ntp.org")
    print("  ➜ Enabling time synchronization")
    appliance.execute_command("store system time_server state on")
    appliance.disconnect()

def t_restart_system():
    appliance = create_appliance('collector_unconfigured')
    if not appliance.connect():
        print("  ✗ Failed to connect to collector")
        exit(1)
    print("  ➜ Restart system")
    result = appliance.execute_restart_with_check()
    #print(f"  {result}")
    appliance.disconnect()
    
    if "System is restarting - connection broke" in result:
        print(" ⌛ Waiting for system availability...")
        appliance = wait_for_appliance('collector_unconfigured')
        print("  ✔ Appliance available")
    else:
        print("  ✗ Could not restart - MYSQL is busy")
        print("  ✗ Run script again in 1 minute or restart collector manually and then start again")

def t_other_collector_settings():
    appliance = create_appliance('collector_unconfigured')
    if not appliance.connect():
        print("  ✗ Failed to connect to collector")
        exit(1)
    print("  ➜ Setup collector name and domain")
    appliance.execute_command("store system hostname coll1")
    appliance.execute_command("store system domain gdemo.com")
    
    print("  ➜ Configure session timeouts")
    appliance.execute_command("store gui session_timeout 9999")
    appliance.execute_command("store timeout cli_session 600")
   
    print("  ➜ Restart GUI")
    appliance.execute_command_with_confirmation(
        command="restart gui",
        response="y",
        confirmation_pattern=r"Are you sure you want to restart GUI\s*\(y/n\)\?"
    )

    print("  ➜ Set shared secret on collector")
    appliance.execute_command("store system shared secret guardium")

    print("  ➜ Set manual hosts resolving")
    output = appliance.execute_command("support show hosts")
    existing = set()
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            ip = parts[0].strip().lower()
            host = parts[1].strip().lower()
            existing.add((ip, host))
    current_appliances = appliances.copy()
    del current_appliances['collector_unconfigured']
    del current_appliances['collector']
    machines = current_appliances | managed_machines
    for machine, cfg in machines.items():
        ip = str(cfg["host"]).strip().lower()
        prompt_host = re.sub(r"\\", "", str(cfg["prompt_regex"])).strip()
        if prompt_host.endswith(">"):
            prompt_host = prompt_host[:-1]
        prompt_host = prompt_host.strip().lower()
        if (ip, prompt_host) in existing:
            continue
        command = f'support store hosts {cfg["host"]} {prompt_host}'
        appliance.execute_command(command)
    print(appliance.execute_command("support show hosts"))

    print("  ➜ Disabling guardcli accounts")
    for account_number in range(2, 9):
        appliance.execute_command(f"store guarduser_state disable guardcli{account_number}")
    appliance.disconnect()

def t_initial_cm_settings():
    appliance = create_appliance('cm')
    if not appliance.connect():
        print("  ✗ Failed to connect to CM")
        exit(1)
    print("  ➜ Create oauth client for bootcamp sync")
    result = appliance.execute_command("grdapi list_oauth_clients")
    if "Client Id: BOOTCAMP" in result:
        appliance.execute_command("grdapi delete_oauth_clients client_id=BOOTCAMP")
    result = appliance.execute_command('grdapi register_oauth_client client_id=BOOTCAMP grant_types="password"')
    client_secret = None
    for line in result.splitlines():
        line = line.strip()
        if line.startswith('{') and line.endswith('}'):
            try:
                data = json.loads(line)
                client_secret = data.get('client_secret')
                if client_secret:
                    if save_to_env("CLIENT_SECRET", client_secret):
                        print(f"  ℹ Client secret saved to .env")
                    else:
                        print(f"  ⚠ Warning: Could not save client_secret to .env")
                        exit(1)
                    break
            except json.JSONDecodeError:
                pass

    print("  ➜ Set shared secret on Central Manager")
    appliance.execute_command("store system shared secret guardium")

    print("  ➜ Disabling guardcli accounts")
    for account_number in range(2, 9):
        appliance.execute_command(f"store guarduser_state disable guardcli{account_number}")

    print("  ➜ Set resolving for coll1.gdemo.com")
    appliance.execute_command(f"support store hosts 10.10.9.239 coll1.gdemo.com")
    appliance.disconnect()

def t_create_demo_user(api):
    token = api.get_token(username='accessmgr', password=get_env_value('ACCESSMGR_PASSWORD'))
    users = api.get_users()
    for u in users:
        status = "DISABLED" if u.get("disabled") == "true" else "ACTIVE"
        print(f"    {u['user_name']:12} | {status}")
    demo_exists = any(u.get('user_name') == 'demo' for u in users)
    if not demo_exists:
        print("  ➜ Creating demo user")
        demo_password = get_env_value('DEMOUSER_PASSWORD')
        result = api.create_user(
            username='demo',
            password=demo_password,
            confirm_password=demo_password,
            first_name='User',
            last_name='Demo',
            email='demo@demo.training',
            country='PL',
            disabled=False,
            disable_pwd_expiry=True
        )
        print("  ➜ Assigning roles to demo user")    
        result = api.set_user_roles(username='demo', roles='admin,cli,user,vulnerability-assess')  
    else:
        print("  ℹ Demo user already exists")
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    if not demo_exists:
        print("  ➜ Import Training dashboard for demo user")
        result = api.import_definitions('guardium_definition_files/exp_dashboard_training.sql')

def t_register_collector(api):  
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    units = api.get_registered_units()
    units = parse_mus_from_message_dict(units)
    # print(units)
    out: List[Dict[str, Optional[str]]] = []
    for u in units:
        out.append({
            "ip": u.get("ip"),
        })
    if not any(d.get('ip') == '10.10.9.239' for d in out):
        appliance = create_appliance('collector')
        if not appliance.connect():
            print("  ✗ Failed to connect to collector")
            exit(1)
        print("  Unit type:")
        result = appliance.execute_command("show unit type")
        print(f"  ℹ ", result)

        try:
            print("⌛ Registering collector, it can take few minutes")

            result = appliance.execute_command("register management 10.10.9.219 8443", timeout=600)
            print("  ℹ ", json.loads(result)['unit_type'])
        except TimeoutError:
            print("  ✗ registration command timeout, it sometimes happens, lets wait additional 5 minutes and check again")
            time.sleep(300)
            appliance = create_appliance('collector')
            if not appliance.connect():
                print("  ✗ Failed to connect to collector")
                exit(1)
            print("  Unit type:")
            result = appliance.execute_command("show unit type")
            print(f"  ℹ ", result)
        
        # unit_data = api.get_unit_data(api_target_host='10.10.9.239')
        # if unit_data and 'Message' in unit_data:
        #     unit_data = parse_unit_summary(unit_data['Message'])
        #     print("  ℹ ", unit_data)
        # else:
        #     print("  ✗ Uncexpected answer from API: ", unit_data)
        # try:
        #     result = appliance.execute_command("show unit type")
        #     print("  ℹ ", result)
        # except (TimeoutError, OSError):
        #     pass
        print("  ✓ Collector registered ")
    else:
        unit_data = api.get_unit_data(api_target_host='10.10.9.239')
        if unit_data and 'Message' in unit_data:
            unit_data = parse_unit_summary(unit_data['Message'])
            print("  ℹ ", unit_data)
        else:
            print("  ✗ Incorrect API answer: ", unit_data)
        print("  ✓ Collector is already registered ")

def t_preparing_appliances_for_patching(api):
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    print("  ➜ Download and unpack patches locally")
    target_dir = "/root/gn-trainings/appliance-patches"
    os.makedirs(target_dir, exist_ok=True)
    filename = os.path.join(target_dir, os.path.basename("patches.zip"))
    urllib.request.urlretrieve(get_env_value("PATCH_ARCHIVE"), filename)
    with zipfile.ZipFile(filename, "r") as zipf:
            zipf.extractall(path=target_dir)
    with zipfile.ZipFile(filename, "r") as zipf:
        patch_list = sorted(zipf.namelist())
    patch_order = get_env_value("PATCH_NAME_LIST").split(",")
    sorted_patch_list = sorted(patch_order)
    save_to_env("PATCH_ORDER", ",".join(str(sorted_patch_list.index(item) + 1) for item in patch_order))

    print("  ➜ Removing old patch archives on central manager")
    result = api.patch_cleanup()   
        
    print("  ➜ Copying patches to central manager and collector")
    patch_files = glob.glob('/root/gn-trainings/appliance-patches/patches/*.sig')
    
    if not patch_files:
        print("  ✗ No patch files found in /root/gn-trainings/appliance-patches/patches/")
        exit(1)    
    print(f"  ℹ Found {len(patch_files)} patch files to copy")
    all_success = True
    for appl in ['10.10.9.219', '10.10.9.239']:
        for patch_file in patch_files:
            success = scp_file_as_root(
                host=appl,
                root_password=get_env_value("ROOT_PASSWORD"),
                local_path=patch_file,
                remote_path='/var/log/guard/patches/',
                direction='put'
            )
            if not success:
                all_success = False
                break
    if all_success:
        print(f"  ℹ All {len(patch_files)} patches copied successfully")

        print("  ➜ Changing ownership of patches to tomcat:tomcat")
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        for appl in ['10.10.9.219', '10.10.9.239']:
            try:
                client.connect(
                    hostname=appl,
                    username='root',
                    password=get_env_value("ROOT_PASSWORD"),
                    look_for_keys=False,
                    allow_agent=False
                )
                stdin, stdout, stderr = client.exec_command('chown tomcat:tomcat /var/log/guard/patches/*.sig')
                exit_status = stdout.channel.recv_exit_status()
                if exit_status != 0:
                    error = stderr.read().decode()
                    print(f"  ✗ Failed to change ownership: {error}")
                    exit(1)
                client.close()
            except Exception as e:
                print(f"  ✗ Error changing ownership: {e}")
                exit(1)
    else:
        print("  ✗ Problem with copying of patches to central manager or collector")
        exit(1)
 
def t_registering_patches_installation(appliance_name, appliance_ip, password):
    appliance = create_appliance(appliance_name)
    if not appliance.connect():
        print(f"  ✗ Failed to connect to {appliance_name}")
        exit(1)
    appliance.execute_command("show system patch available")
    
    output = install_patch(
        host=appliance_ip,
        username='cli',
        password=password,
        patch_selection=get_env_value("PATCH_ORDER"),
        reinstall_answer="y",
        live_log=False
    )
    appliance.disconnect()

def t_monitoring_patch_installation(appliance_name):
    appliance = create_appliance(appliance_name)
    if not appliance.connect():
        print(f"  ✗ Failed to connect to {appliance_name}")
        exit(1)   
    required_status = "DONE: Patch installation Succeeded."
    while True:
        result = appliance.execute_command("show system patch installed")
        wanted = set(get_env_value("PATCH_LIST").split(","))
        status_by_id = {}
        for line in result.splitlines():
            line = line.strip()
            if not line or line.startswith("P#"):
                continue
            m = re.match(r"^(\d+)\b.*", line)
            if not m:
                continue
            pid = m.group(1)
            has_ok_status = required_status in line
            status_by_id[pid] = has_ok_status        
        all_installed = all(pid in status_by_id and status_by_id[pid] for pid in wanted)
        if all_installed:
            print(f"  ℹ All required patches ({', '.join(wanted)}) on {appliance_name} are installed with status: {required_status}")
            break
        else:
            missing = [pid for pid in wanted if pid not in status_by_id or not status_by_id[pid]]
            print(f"  ⏳ Waiting for patches: {', '.join(missing)}")
            time.sleep(10)
    appliance.disconnect()

def t_install_policy_on_collector(api):
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    result = api.install_policy("Log Everything", api_target_host="10.10.9.239")

def t_set_collector_resolving_on_raptor():
    HOSTS_FILE = Path("/etc/hosts")
    old_ip = "10.10.9.239"
    new_entry = "10.10.9.239\t coll1.gdemo.com coll1\n"
    lines = HOSTS_FILE.read_text().splitlines(keepends=True)
    updated = []
    for line in lines:
        if line.startswith(old_ip):
            updated.append(new_entry)
        else:
            updated.append(line)
    HOSTS_FILE.write_text("".join(updated))

def t_getting_gim_files():
    print("  ➜ Download gim installers and gim modules locally")
    target_dir = "/root/gn-trainings"
    os.makedirs(target_dir, exist_ok=True)
    filename = os.path.join(target_dir, os.path.basename("gims.zip"))
    urllib.request.urlretrieve(get_env_value("GIM_INSTALLERS_ARCHIVE"), filename)
    with zipfile.ZipFile(filename, "r") as zipf:
        zipf.extractall(path=target_dir)
        print(f"  ➜ GIM installers extracted")
    filename = os.path.join(target_dir, os.path.basename("agents.zip"))
    urllib.request.urlretrieve(get_env_value("GIM_BUNDLES_ARCHIVE"), filename)
    with zipfile.ZipFile(filename, "r") as zipf:
        zipf.extractall(path=target_dir)
        print(f"  ➜ GIM modules extracted")
    
    print("  ➜ Adding execution flag to GIM installers")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname='10.10.9.70',
        username='root',
        password=get_env_value("RAPTOR_PASSWORD"),
        look_for_keys=False,
        allow_agent=False
    )
    stdin, stdout, stderr = client.exec_command('chmod 755 /root/gn-trainings/gim_installers/*.sh')
    print("  ➜ Copying GIM modules to central manager")
    patch_files = glob.glob('/root/gn-trainings/*.gim')
    all_success = True
    for patch_file in patch_files:
        success = scp_file_as_root(
            host='10.10.9.219',
            root_password=get_env_value("ROOT_PASSWORD"),
            local_path=patch_file,
            remote_path='/var/dump/',
            direction='put'
        )
        if not success:
            all_success = False
            exit(1)
    if all_success:
        print(f"  ℹ All {len(patch_files)} modules copied successfully")

    print("  ➜ Removing zip anf gim files from raptor")
    stdin, stdout, stderr = client.exec_command('rm -f /root/gn-trainings/*.zip')
    exit_status = stdout.channel.recv_exit_status()
    stdin, stdout, stderr = client.exec_command('rm -f /root/gn-trainings/*.gim')
    exit_status = stdout.channel.recv_exit_status()
    client.close()

def t_import_gim_modules(api):
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    api.get_gim_package(filename="*.gim")

def t_postgres_installation():
    print("  ➜ Postgres 16 installation")
    subprocess.run(["dnf", "-qy", "install", "@postgresql:16"], check=True, capture_output=True)
    print("  ➜ Postgres database initialization")
    subprocess.run(["postgresql-setup", "--initdb", '--unit', 'postgresql'], check=True)
    print("  ➜ Set postgres user password")
    subprocess.run(["chpasswd"], input=f"postgres:{get_env_value('DEFAULT_SERVICE_PASSWORD')}", text=True, check=True)
    print("  ➜ Create certificate for postgres")
    subprocess.run(["openssl", "req", "-new", "-x509", "-days", "365", "-nodes", "-text", "-out", "/var/lib/pgsql/data/pgsql.crt", "-keyout", "/var/lib/pgsql/data/pgsql.key", "-subj", "/CN=raptor.demo.com"], check=True, capture_output=True)
    files = glob.glob("/var/lib/pgsql/data/pgsql.*")
    subprocess.run(["chown", "postgres:postgres"] + files, check=True)
    print("  ➜ Change postgres configuration")
    conf = Path("/var/lib/pgsql/data/postgresql.conf")
    lines = []
    with conf.open() as f:
        for line in f:
            if re.match(r"^\s*#\s*ssl\s*=\s*off\s*$", line):
                line = "ssl = on\n"
            elif re.match(r"^\s*#?\s*ssl_cert_file\s*=\s*'[^']+'\s*$", line):
                line = "ssl_cert_file = '/var/lib/pgsql/data/pgsql.crt'\n"
            elif re.match(r"^\s*#?\s*ssl_key_file\s*=\s*'[^']+'\s*$", line):
                line = "ssl_key_file = '/var/lib/pgsql/data/pgsql.key'\n"
            elif re.match(r"^\s*#?\s*listen_addresses\s*=\s*'[^']+'\s*(#.*)?$", line):
                line = "listen_addresses = '*'                  # what IP address(es) to listen on;\n"
            lines.append(line)
    conf.write_text("".join(lines))

    conf = Path("/var/lib/pgsql/data/pg_hba.conf")
    lines = []
    with conf.open() as f:
        for line in f:
            if re.match(r"^\s*local\s+all\s+all\s+peer\s*$", line):
                line = "local   all             all                                     ident\n"
            elif re.match(r"^\s*host\s+all\s+all\s+127\.0\.0\.1/32\s+ident\s*$", line):
                lines.append("host    all             all             127.0.0.1/32            scram-sha-256\n")
                line = "host    all             all             10.10.9.0/24            scram-sha-256\n"
            elif re.match(r"^\s*#\s*listen_addresses\s*=\s*'localhost'\s*$", line):
                line = "listen_addresses = '*'\n"
            lines.append(line)
    conf.write_text("".join(lines))
    print("  ➜ Start postgres service")
    subprocess.run(["systemctl", "start", 'postgresql.service'], check=True)
    print("  ➜ Enable postgres service")
    subprocess.run(["systemctl", "enable", 'postgresql.service'], check=True, capture_output=True)
    print("  ➜ Set postgres user password in database")
    sql = "ALTER USER postgres WITH PASSWORD '{}';".format(get_env_value("DEFAULT_SERVICE_PASSWORD"))
    subprocess.run(["sudo", "-u", "postgres", "psql", "-d", "postgres", "-U", "postgres", "-c",  sql], check=True, capture_output=True)

def t_create_postgres_admin_users():
    conn = get_postgres_conn(dbname="postgres", user= "postgres", password="guardium", host="localhost", port=5432)
    cur = conn.cursor()
    cur.execute(f"CREATE ROLE tom PASSWORD '{get_env_value('DEFAULT_SERVICE_PASSWORD')}' SUPERUSER CREATEDB CREATEROLE INHERIT LOGIN;")
    cur.execute(f"CREATE ROLE jerry PASSWORD '{get_env_value('DEFAULT_SERVICE_PASSWORD')}' SUPERUSER CREATEDB CREATEROLE INHERIT LOGIN;")
    conn.commit()
    cur.close()
    conn.close()

def t_install_gim_on_raptor():
    subprocess.run(["/root/gn-trainings/gim_installers/guard-bundle-GIM-12.2.0.0_r121306_v12_2_1-rhel-8-linux-x86_64.gim.sh", "--", "--dir", "/opt/guardium", "--tapip", "10.10.9.70", "--sqlguardip", "10.10.9.219"], check=True, capture_output=True)

def t_install_stap_on_raptor(api):
    print("  ➜ S-TAP installation schedule")
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    api.gim_client_assign(
        client_ip="10.10.9.70",
        module="BUNDLE-STAP",
        module_version="12.2.1.0_r122289_1"
    )
    api.gim_client_params(
        client_ip="10.10.9.70",
        param_name="STAP_SQLGUARD_IP",
        param_value="10.10.9.239"
    )
    api.gim_client_params(
        client_ip="10.10.9.70",
        param_name="STAP_USE_TLS",
        param_value="1"
    )
    api.gim_client_params(
        client_ip="10.10.9.70",
        param_name="STAP_STATISTICS",
        param_value="-3"
    )
    api.gim_client_params(
        client_ip="10.10.9.70",
        param_name="STAP_CONNECTION_POOL_SIZE",
        param_value="2"
    )
    api.gim_schedule_install(
        client_ip="10.10.9.70",
        date="now",
    )
    time.sleep(10)
    print("  ➜ S-TAP installation monitoring")
    monitor_gim_module_installation(api, "10.10.9.70")

def t_enable_atap_for_postgres_on_raptor():
    subprocess.run(["/opt/guardium/modules/ATAP/current/files/bin/guardctl", "--db-user=postgres", "--db-home=/usr", "--db-user-dir=/var/lib/pgsql", "--db-type=postgres", "--db-instance=postgres", "--db-version=16", "store-conf"], check=True, capture_output=True)
    subprocess.run(["/opt/guardium/modules/ATAP/current/files/bin/guardctl", "authorize-user", "postgres"], check=True, capture_output=True)
    subprocess.run(["systemctl", "stop", "postgresql"], check=True, capture_output=True)
    subprocess.run(["/opt/guardium/modules/ATAP/current/files/bin/guardctl", "--db-instance=postgres", "activate"], check=True, capture_output=True)
    subprocess.run(["systemctl", "start", "postgresql"], check=True, capture_output=True)

def t_correct_mysql_ie(api):
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    print("  ➜ Delete mysql Inspection Engine definitions")
    api.delete_inspection_engine(
        stap_host="10.10.9.70",
        type="mysql",
        wait_for_response="1",
        api_target_host="10.10.9.239"
    )
    print("  ➜ Create mysql Inspection Engine 1")
    api.create_inspection_engine(
        stap_host="10.10.9.70",
        protocol="mysql",
        port_min="3306",
        port_max="3306",
        ktap_db_port="3306",
        db_user="mysqld",
        db_version="8",
        client="0.0.0.0/0.0.0.0",
        proc_name="/usr/sbin/mysqld",
        db_install_dir="/var/lib/mysql",
        unix_socket_marker="mysql.sock",
        api_target_host="10.10.9.239"
    )
    print("  ➜ Create mysql Inspection Engine 2")
    api.create_inspection_engine(
        stap_host="10.10.9.70",
        protocol="mysql",
        port_min="33060",
        port_max="33060",
        ktap_db_port="33060",
        db_user="mysqld",
        db_version="8",
        client="0.0.0.0/0.0.0.0",
        proc_name="/usr/sbin/mysqld",
        db_install_dir="/var/lib/mysql",
        unix_socket_marker="mysql.sock",
        api_target_host="10.10.9.239"
    )
    print("  ➜ Create mysql Inspection Engine 3")
    api.create_inspection_engine(
        stap_host="10.10.9.70",
        protocol="mysql",
        port_min="3306",
        port_max="3306",
        ktap_db_port="3306",
        db_user="mysqld",
        db_version="8",
        client="0.0.0.0/0.0.0.0",
        proc_name="/usr/sbin/mysqld",
        db_install_dir="/var/lib/mysql",
        unix_socket_marker="mysqlx.sock",
        api_target_host="10.10.9.239"
    )
    print("  ➜ Create mysql Inspection Engine 4")
    api.create_inspection_engine(
        stap_host="10.10.9.70",
        protocol="mysql",
        port_min="33060",
        port_max="33060",
        ktap_db_port="33060",
        db_user="mysqld",
        db_version="8",
        client="0.0.0.0/0.0.0.0",
        proc_name="/usr/sbin/mysqld",
        db_install_dir="/var/lib/mysql",
        unix_socket_marker="mysqlx.sock",
        api_target_host="10.10.9.239"
    )

def t_configure_ssl_for_mongo():
    subprocess.run(["mkdir", "-p", "/var/lib/mongo/cert"], check=True)
    subprocess.run(["openssl", "req", '-x509', '-newkey', "rsa:4096", "-keyout", "/var/lib/mongo/cert/key.pem", "-out", "/var/lib/mongo/cert/cert.pem", "-sha256", "-days", "3650", "-nodes", "-subj", "/C=PL/ST=Lubuskie/L=Nowa Sol/O=Training/OU=Demo/CN=mongod"], check=True, capture_output=True)
    with open("/var/lib/mongo/cert/both.pem", "w") as f:
        subprocess.run(["cat", "/var/lib/mongo/cert/key.pem", "/var/lib/mongo/cert/cert.pem"], stdout=f, stderr=subprocess.STDOUT, check=True)
    subprocess.run(["chown", "-R", "mongod:mongod", "/var/lib/mongo/cert"], check=True)
    conf = Path("/etc/mongod.conf")
    lines = []
    with conf.open() as f:
        for line in f:
            if re.match(r"^\s*bindIp\s*:", line):
                line = "  bindIp: 0.0.0.0  # Enter 0.0.0.0,:: to bind to all IPv4 and IPv6 addresses or, alternatively, use the net.bindIpAll setting.\n"
                lines.append("  tls:\n")
                lines.append("    mode: requireTLS\n")
                lines.append("    certificateKeyFile: /var/lib/mongo/cert/both.pem\n")
            else:
                lines.append(line)
    conf.write_text("".join(lines))
    subprocess.run(["systemctl", "restart", "mongod"], check=True)

def t_enable_atap_for_mongo():
    subprocess.run(["mv", "/opt/guardium/etc/guard/root/postgres.conf", "/opt/guardium/etc/guard"], check=True)
    subprocess.run(["/opt/guardium/modules/ATAP/current/files/bin/guardctl", "--db-user=mongod", "--db-home=/usr", "--db-base=/var/lib/mongo", "--db-type=mongodb",     "--db-instance=mongo4", "store-conf"], check=True, capture_output=True)
    subprocess.run(["/opt/guardium/modules/ATAP/current/files/bin/guardctl", "authorize-user", "mongod"], check=True, capture_output=True)
    subprocess.run(["systemctl", "stop", "mongod"], check=True, capture_output=True)
    subprocess.run(["/opt/guardium/modules/ATAP/current/files/bin/guardctl", "--db-instance=mongo4", "activate"], check=True, capture_output=True)
    subprocess.run(["systemctl", "start", "mongod"], check=True, capture_output=True)
    subprocess.run(["mv", "/opt/guardium/etc/guard/postgres.conf", "/opt/guardium/etc/guard/root"], check=True, capture_output=True)

def t_exit_for_db2_setup(api):
    print("  ➜ Registering db2inst1 user")
    subprocess.run(["/opt/guardium/modules/ATAP/current/files/bin/guardctl", "authorize-user", "db2inst1"], check=True, capture_output=True)
    print("  ➜ Stopping DB2")
    subprocess.run(["sudo", "-iu", "db2inst1", "db2stop"], check=True, capture_output=True)
    print("  ➜ Configuring EXIT shared library")
    subprocess.run(["sudo", "-iu", "db2inst1", "mkdir", "-p", "/home/db2inst1/sqllib/security64/plugin/commexit"], check=True, capture_output=True)
    subprocess.run(["sudo", "-iu", "db2inst1", "ln", "-fs", "/usr/lib64/libguard_db2_exit_64.so", "/home/db2inst1/sqllib/security64/plugin/commexit/libguard_db2_exit_64.so"], check=True)
    subprocess.run(["sudo", "-iu", "db2inst1", "db2", "update", "dbm", "cfg", "using", "comm_exit_list", "libguard_db2_exit_64"], check=True, capture_output=True)
    print("  ➜ Starting DB2")
    subprocess.run(["sudo", "-iu", "db2inst1", "db2start"], check=True, capture_output=True)
    # print("\n Configure DB2 IE for EXIT")
    # subprocess.run(["/opt/guardium/modules/STAP/current/setup_exit.sh", "db2"], check=True)
    print("  ➜ Correcting DB2 Inspection Engine definition")
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    api.delete_inspection_engine(
        stap_host="10.10.9.70",
        type="Db2",
        wait_for_response="1",
        api_target_host="10.10.9.239"
    )
    api.create_inspection_engine(
        stap_host="10.10.9.70",
        protocol="Db2 Exit",
        db_user="db2inst1",
        db_version="11",
        client="0.0.0.0/0.0.0.0",
        proc_name="/home/db2inst1/sqllib/adm/db2sysc",
        db_install_dir="/home/db2inst1",
        api_target_host="10.10.9.239"
    )

def t_setup_cassandra():
    print("  ➜ Copying config files to hana")
    scp_file_as_root(host='10.10.9.60', root_password=get_env_value("HANA_PASSWORD"), local_path="guardium_configuration_files/cassandra.repo", remote_path="/etc/yum.repos.d/cassandra.repo")
    scp_file_as_root(host='10.10.9.60', root_password=get_env_value("HANA_PASSWORD"), local_path="guardium_configuration_files/cassandra_table.cql", remote_path="/root")
    print("  ➜ Installing java, cassandra, configuration of cassandra")
    result=run_many_commands_remotely(host='10.10.9.60', password=get_env_value("HANA_PASSWORD"), print_output=False,
    commands=[
        "dnf -y install java-11-openjdk",
        "dnf -y install cassandra",
        r"sed -i '/^audit_logging_options:/,/^[[:space:]]*- class_name:/c\audit_logging_options:\n  enabled: true\n  logger:\n    - class_name: FileAuditLogger' /etc/cassandra/conf/cassandra.yaml",
        "sed -i '/<!-- <appender name=\"AUDIT\"/,/SizeAndTimeBasedRollingPolicy/ { s/<!-- //; s/ -->// }' /etc/cassandra/conf/logback.xml",
        "sed -i 's|<!-- *<fileNamePattern>\\(.*\\)</fileNamePattern> *-->|<fileNamePattern>\1</fileNamePattern>|' /etc/cassandra/conf/logback.xml",
        "sed -i '/<!-- *<maxFileSize>/,/<\\/appender> *-->/ { s/<!-- //; s/ -->// }' /etc/cassandra/conf/logback.xml",
        "sed -i '/<!-- *<logger name=\"org.apache.cassandra.audit\"/,/<\\/logger> *-->/ { s/<!-- //; s/ -->// }' /etc/cassandra/conf/logback.xml",
        "sed -i 's|^10\\.10\\.9\\.239[[:space:]]\\+yourcollectorname\\.gdemo\\.com[[:space:]]\\+yourcollectorname$|10.10.9.239     coll1.gdemo.com coll1|' /etc/hosts"
        "service cassandra start",
        "service cassandra start",
        "dnf -qy install python3-pip",
        "pip install --user cqlsh",
        "cqlsh -f /root/cassandra_table.cql"
    ])
    time.sleep(30)

def t_setup_filebeat(api):
    """
    # API call added to create UC 1.0 cert but rest automatization is not implemented
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    cert = api.generate_ssl_key_universal_connector(
        expiration_days=3650,
        hostname="*.gdemo.com",
        overwrite=True,
        api_target_host='10.10.9.239',
    )
    """

    result=run_many_commands_remotely(host='10.10.9.60', password=get_env_value("HANA_PASSWORD"), print_output=False,
    commands=[
        "mkdir -p /root/gn-trainings",
        f"curl -L -O https://artifacts.elastic.co/downloads/beats/filebeat/filebeat-{get_env_value("FILEBEAT_VERSION")}-x86_64.rpm --output-dir /root/gn-trainings",
        f"cd /root/gn-trainings && dnf -y install /root/gn-trainings/filebeat-{get_env_value("FILEBEAT_VERSION")}-x86_64.rpm",
        r"sed -i '/^- type: filestream/,/^[^[:space:]]/c\- type: filestream\n  id: \"cassandra\"\n  enabled: true\n  paths:\n    - /var/log/cassandra/audit/audit.log\n  exclude_lines: [\"AuditLogManager\"]\n  tags: [\"cassandra\"]\n  multiline.type: pattern\n  multiline.pattern: \"^INFO\"\n  multiline.negate: true\n  multiline.match: after' /etc/filebeat/filebeat.yml",
        r"sed -i '/^output.elasticsearch:/,/^[^[:space:]]/ { s/^/# / }' /etc/filebeat/filebeat.yml",
        r"sed -i '/^#output.logstash:/,/^[^[:space:]]/ { s/^#output\.logstash:/output.logstash:/; s|^  #hosts:.*|  hosts: [\"coll1.demo.com:5047\"]| }' /etc/filebeat/filebeat.yml",
        "systemctl start filebeat",
        "systemctl enable filebeat"
    ])

def t_setup_raptor_to_deploy_etap():
    print("  ➜ Installing package requirements")
    subprocess.run(["dnf", "-y", "install", "podman-docker", "skopeo"], check=True, capture_output=True)
    print("  ➜ Determine the latest ETAP version")
    result = subprocess.run(["skopeo", "list-tags", "docker://icr.io/guardium/guardium_external_s-tap"], check=True, text=True, capture_output=True)
    etap_versions = json.loads(result.stdout)
    latest = {}
    for t in etap_versions["Tags"]:
        m = re.match(r"^v(\d+\.\d+\.\d+)", t)
        if not m:
            continue
        version_str = m.group(1)
        major, minor, patch = version_str.split(".")
        key = f"{major}.{minor}"
        v = Version(version_str)
        latest[key] = max(latest.get(key, v), v)
    save_to_env("GUARDIUM_ETAP_VERSION", str( latest[get_env_value("GUARDIUM_MINOR_VERSION")]))

def t_deploy_ca_on_raptor():
    print("  ➜ Create CA directory")
    subprocess.run(["mkdir", "-p", "/root/gn-trainings/ETAP/ca"], check=True)
    print("  ➜ Create CA private key")
    subprocess.run(["openssl", "genrsa", "-out", "/root/gn-trainings/ETAP/ca/ca.key", "2048"], check=True, capture_output=True)
    print("  ➜ Generate CA certificate")
    subprocess.run(["openssl", "req", "-x509", "-sha256", "-new", "-key", "/root/gn-trainings/ETAP/ca/ca.key", "-days", "3650", "-out", "/root/gn-trainings/ETAP/ca/ca.pem", "-subj", "/C=PL/O=Demo/OU=Training/CN=Demo Root CA"], check=True, capture_output=True)

def t_create_mysql_csr_for_etap():
    print("  ➜ Connecting to collector")
    appliance = ApplianceCommand(
        host="10.10.9.239",
        strip_ansi=True,
        user="cli",
        password=get_env_value("COLLECTOR_PASSWORD"),
        prompt_regex=r">",
        debug=False
    )
    print("  ➜ Generating CSR for MySQL ETAP")
    if appliance.connect():
        csr, token, line_above = appliance.generate_external_stap_csr(
        alias="mysql-etap",
        common_name="mysql-etap",
        san1="coll1.gdemo.com"
    )
        file_path = "/root/gn-trainings/ETAP/ca/etap.csr"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(csr)
        save_to_env("ETAP_CSR_ID", line_above)
        save_to_env("ETAP_TOKEN", token)
    appliance.disconnect()
    print("  ➜ Signing CSR by CA")
    subprocess.run(["openssl", "x509", "-sha256", "-req", "-days", "3650", "-CA", "/root/gn-trainings/ETAP/ca/ca.pem", "-CAkey", "/root/gn-trainings/ETAP/ca/ca.key", "-CAcreateserial", "-CAserial", "serial", "-in", "/root/gn-trainings/ETAP/ca/etap.csr", "-out", "/root/gn-trainings/ETAP/ca/etap.pem"], check=True, capture_output=True)

def t_import_etap_ca_cert():
    appliance = ApplianceCommand(
        host="10.10.9.239",
        strip_ansi=True,
        user="cli",
        password=get_env_value("COLLECTOR_PASSWORD"),
        prompt_regex=r">",
        debug=False
    )
    if appliance.connect():
        # Wczytaj certyfikat CA
        with open("/root/gn-trainings/ETAP/ca/ca.pem") as f:
            ca_cert_pem = f.read()
        # Importuj certyfikat
        appliance.import_external_stap_ca_certificate(
            alias="etapca",
            ca_cert=ca_cert_pem
        )
    appliance.disconnect()

def t_import_etap_cert():
    appliance = ApplianceCommand(
        host="10.10.9.239",
        strip_ansi=True,
    user="cli",
    password=get_env_value("COLLECTOR_PASSWORD"),
    prompt_regex=r">",
    debug=False
    )   
    if appliance.connect():
    # Wczytaj certyfikat External S-TAP
        with open("/root/gn-trainings/ETAP/ca/etap.pem") as f:
            etap_cert = f.read()
        # Importuj certyfikat
        appliance.import_external_stap_certificate(
            alias_line=get_env_value("ETAP_CSR_ID"),
            stap_cert=etap_cert
        )
    appliance.disconnect()

def t_start_etap():
    etap_host = "10.10.9.70"
    database_port = "3306"
    token = get_env_value("ETAP_TOKEN")
    db_type = "mysql"
    etap_label = "MYSQLETAP"
    collector_ip = "10.10.9.239"
    etap_release = get_env_value("GUARDIUM_ETAP_VERSION")
    listen_port = "63333"

    etap_command = [
        "podman",
        "run",
        "--restart",
        "unless-stopped",
        # "--hostname",
        # "localhost-gext0-044eb2cb-0b29-4d0f-852b-b4c347831f41",
        "--name",
        "mysql-etap",
        "-d",
        "--shm-size",
        "800M",
        "-e",
        "STAP_CONFIG_TAP_TAP_IP=NULL",
        "-e",
        "STAP_CONFIG_TAP_PRIVATE_TAP_IP=NULL",
        "-e",
        "STAP_CONFIG_TAP_FORCE_SERVER_IP=0",
        "-e",
        "STAP_CONFIG_PROXY_GROUP_UUID=044eb2cb-0b29-4d0f-852b-b4c347831f41",
        "-e",
        "STAP_CONFIG_PROXY_GROUP_MEMBER_COUNT=1",
        "-e",
        f"STAP_CONFIG_PROXY_DB_HOST={etap_host}",
        "-e",
        "STAP_CONFIG_PROXY_NUM_WORKERS=1",
        "-e",
        "STAP_CONFIG_PROXY_PROXY_PROTOCOL=0",
        "-e",
        "STAP_CONFIG_PROXY_DISCONNECT_ON_INVALID_CERTIFICATE=0",
        "-e",
        "STAP_CONFIG_PROXY_NOTIFY_ON_INVALID_CERTIFICATE=0",
        "-e",
        "STAP_CONFIG_PROXY_DETECT_SSL_WITHIN_X_PACKETS=-1",
        "-e",
        f"STAP_CONFIG_DB_0_REAL_DB_PORT={database_port}",
        "-e",
        "STAP_CONFIG_PROXY_LISTEN_PORT=8888",
        "-e",
        "STAP_CONFIG_PROXY_DEBUG=0",
        "-e",
        f"STAP_CONFIG_PROXY_SECRET={token}",
        "-e",
        "STAP_CONFIG_PROXY_CSR_NAME=",
        "-e",
        "STAP_CONFIG_PROXY_CSR_COUNTRY=",
        "-e",
        "STAP_CONFIG_PROXY_CSR_PROVINCE=",
        "-e",
        "STAP_CONFIG_PROXY_CSR_CITY=",
        "-e",
        "STAP_CONFIG_PROXY_CSR_ORGANIZATION=",
        "-e",
        "STAP_CONFIG_PROXY_CSR_KEYLENGTH=2048",
        "-e",
        f"STAP_CONFIG_DB_0_DB_TYPE={db_type}",
        "-e",
        "STAP_CONFIG_PARTICIPATE_IN_LOAD_BALANCING=0",
        "-e",
        f"STAP_CONFIG_TAP_TENANT_ID={etap_label}",
        "-e",
        f"STAP_CONFIG_SQLGUARD_0_SQLGUARD_IP={collector_ip}",
        f"-p={listen_port}:8888/tcp",
        "-q",
        f"icr.io/guardium/guardium_external_s-tap:v{etap_release}"
    ]
    subprocess.run(etap_command, check=True, capture_output=True)

def t_configure_raptor_for_va():
    print("  ➜ postgres package installation to enable some features")
    subprocess.run(["dnf", "-y", "install", "postgresql-contrib"], check=True, capture_output=True)
    print("  ➜ Create sqlguard user")
    conn = get_postgres_conn(host="localhost", user="postgres", password='guardium', port=5432, dbname="postgres")
    cur = conn.cursor()
    cur.execute("CREATE USER sqlguard WITH ENCRYPTED PASSWORD 'guardium';")
    cur.execute("CREATE GROUP gdmmonitor;")
    conn.commit()
    cur.execute("ALTER GROUP gdmmonitor ADD USER sqlguard;")
    cur.execute("GRANT pg_read_all_settings TO gdmmonitor;")
    cur.execute("GRANT SELECT ON pg_authid TO gdmmonitor;")
    cur.close()
    conn.close()
    print("  ➜ Download DPS archive")
    target_dir = "/root/gn-trainings"
    os.makedirs(target_dir, exist_ok=True)
    filename = os.path.join(target_dir, os.path.basename("dps.zip"))
    urllib.request.urlretrieve(get_env_value("DPS_ZIP_ARCHIVE"), filename)
    print("  ➜ Extract DPS file")
    with zipfile.ZipFile(filename, "r") as zipf:
            zipf.extractall(path=target_dir)

def t_setup_vascanner():
    print(f"  ➜ Create API key for vascanner")
    appliance = create_appliance('cm')
    if not appliance.connect():
        print(f"  ✗ Failed to connect to cm")
        exit(1)
    output = appliance.execute_command("grdapi create_api_key name=vascanner")
    match = re.search(r"Encoded API key:\s*([A-Za-z0-9+/=_-]+)", output)
    if not match:
        print(f"  ✗ Failed to extract API key from output")
        exit(1)
    api_key = match.group(1)
    print("  ➜ Pull vascanner image on hana")
    result=run_many_commands_remotely(host='10.10.9.60', password=get_env_value("HANA_PASSWORD"), print_output=False, commands=["mkdir -p /root/gn-trainings/vascanner/certs", f"podman login cp.icr.io -u cp -p {get_env_value('IBM_REGISTRY_KEY')} > /dev/null && podman pull -q cp.icr.io/cp/ibm-guardium-data-security-center/guardium/{get_env_value('VASCANNER_IMAGE_TAG')}", "podman images --format '{{.ID}}'"])
    va_image_id = result[2]['stdout'].strip()
    print("  ➜ Prepare vascanner config file")
    subprocess.run(["cp", "guardium_configuration_files/vascanner_config", "guardium_configuration_files/config"], check=True)
    with open('guardium_configuration_files/config', 'a') as f:
        subprocess.run(["echo", f"\nCLIENT_API_KEY={api_key}", ], stdout=f, text=True, check=True)
    print("  ➜ Copy vascanner file to hana machine")
    scp_file_as_root(host='10.10.9.60', root_password=get_env_value("HANA_PASSWORD"), local_path='guardium_configuration_files/config', remote_path='/root/gn-trainings/vascanner/config')
    print("  ➜ Copy cm certificate to hana machine")
    scp_file_as_root(host='10.10.9.60', root_password=get_env_value("HANA_PASSWORD"), local_path='guardium_configuration_files/vascanner.pem', remote_path='/root/gn-trainings/vascanner/certs/vascanner.pem')
    print("  ➜ Run vascanner container on hana")
    run_many_commands_remotely(host='10.10.9.60', password=get_env_value("HANA_PASSWORD"),print_output=False, commands=[f"podman run --network host -d --replace --env-file /root/gn-trainings/vascanner/config --name va-scanner-hana -v /root/gn-trainings/vascanner/certs:/var/vascanner/certs {va_image_id}"])

def t_import_va_process_for_postgres(api):
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    print("  ➜ Import Vulnerability Assessment process")
    result = api.import_definitions('guardium_definition_files/exp_security_assessment_va_postgres.sql')

def t_import_DPS():
    print("  ➜ Configure playwright browsers")
    subprocess.run(["playwright", "install"], check=True, capture_output=True)

    print("  ➜ Start DPS import")
    guardium_customer_upload_import(
        login_url='https://10.10.9.219:8443',
        username='demo',
        password=get_env_value("DEMOUSER_PASSWORD"),
        file_to_upload=f'/root/gn-trainings/{get_env_value("DPS_NAME")}.enc',
        headless=True
    )

def t_install_gim_on_winsql():
    res = run_winrm(
        host="10.10.9.59",
        username=r".\administrator",
        password=get_env_value("WINSQL_PASSWORD"),
        command= ("New-Item -ItemType Directory -Force -Path 'GIM_Client' | Out-Null; Invoke-WebRequest -Uri 'https://ibm.box.com/shared/static/w26pu9sm69l6ysr2xklvoh9nkxgah23b.zip' -OutFile 'GIM_Client\\GIM_install.zip'; Expand-Archive -Force -Path 'GIM_Client\\GIM_install.zip' -DestinationPath 'GIM_Client\\'; & '.\\GIM_Client\\Setup.exe' -UNATTENDED -APPLIANCE 10.10.9.219 -LOCALIP 10.10.9.59"),
        command_type="ps",
        transport="ntlm",
        use_ssl=False,  # HTTP
    )

def t_install_stap_on_winsql(api):
    time.sleep(60) # wait for registration GIM client
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    print("  ➜ WINSTAP installation schedule")
    api.gim_client_assign(
        client_ip="10.10.9.59",
        module="WINSTAP",
        module_version="12.2_r120201205_1"
    )
    api.gim_client_params(
        client_ip="10.10.9.59",
        param_name="WINSTAP_SQLGUARD_IP",
        param_value="10.10.9.239"
    )
    print("  ➜ WINSTAP installation start")
    api.gim_schedule_install(
        client_ip="10.10.9.59",
        date="now",
    )
    print("  ➜ WINSTAP installation monitoring")
    monitor_gim_module_installation(api, "10.10.9.59")

def t_enable_fam_on_raptor(api):
    print("  ➜ Set FAM settings")
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    api.gim_client_params(
        client_ip="10.10.9.70",
        param_name="STAP_FAM_ENABLED",
        param_value="1"
    )
    api.gim_client_params(
        client_ip="10.10.9.70",
        param_name="STAP_FAM_INSTALLED",
        param_value="1"
    )
    print("  ➜ Schedule STAP reconfiguration")
    api.gim_schedule_install(
        client_ip="10.10.9.70",
        date="now",
    )
    print("  ➜ Monitoring is a FAM enabled")
    monitor_gim_module_installation(api, "10.10.9.70")
    
    print("  ➜ Enable root account monitoring")
    subprocess.run(["sed", "-i", r"s/^fam_protect_privileged[[:space:]]*=.*/fam_protect_privileged=1/", "/opt/guardium/modules/STAP/current/guard_tap.ini"], check=True)
    subprocess.run(["/opt/guardium/modules/STAP/current/guard-config-update", "--restart", "stap"], check=True, capture_output=True)

def t_install_enable_fam_on_winsql(api):
    print("  ➜ Set FAMMONITOR installation and settings")
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    api.gim_client_assign(
        client_ip="10.10.9.59",
        module="FAMMONITOR",
        module_version="12.2_r120201205_1"
    )
    api.gim_client_params(
        client_ip="10.10.9.59",
        param_name="FAMMONITOR_SQLGUARD_IP",
        param_value="10.10.9.239"
    )
    api.gim_client_params(
        client_ip="10.10.9.59",
        param_name="FAMMONITOR_FAM_PROTECT_PRIVILEGED",
        param_value="1"
    )
    print("  ➜ Schedule FAMMONITOR installation")
    api.gim_schedule_install(
        client_ip="10.10.9.59",
        date="now",
    )
    print("  ➜ Monitoring is a FAM enabled")
    monitor_gim_module_installation(api, "10.10.9.59")

def t_import_fam_definitions(api):
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    print("  ➜ Import FAM policy")
    result = api.import_definitions('guardium_definition_files/exp_raptor_fam_policy.sql')
    print("  ➜ Import FAM dashboard")
    result = api.import_definitions('guardium_definition_files/exp_dashboard_fam.sql')
    
def t_install_fam_policy(api):
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    result = api.install_policy("Log Everything|raptor FAM policy", api_target_host="10.10.9.239")

def t_configure_env_for_oracle(api):
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    print("  ➜ Setup oracle user settings")
    run_as_user(["bash", "-c", r'mkdir -p ~/.sqlcl && printf "%s\n" "SET SQLFORMAT ansiconsole" > "$HOME/.sqlcl/login.sql" && printf "%s\n" "export SQLPATH=.:$HOME/.sqlcl/" >> "$HOME/.bashrc"'], user="oracle", text=True)
    print("  ➜ Import Oracle dashboard")
    result = api.import_definitions('guardium_definition_files/exp_dashboard_oracle.sql')
    print("  ➜ Add missing IE definition")
    api.create_inspection_engine(
        stap_host="10.10.9.70",
        protocol="oracle",
        port_min="1521",
        port_max="1521",
        ktap_db_port="1521",
        db_user="oracle",
        db_version="19",
        client="0.0.0.0/0.0.0.0",
        proc_name="/opt/oracle/product/19c/dbhome_1/bin/oracle",
        db_install_dir="/home/oracle",
        unix_socket_marker="EXTPROC2",
        api_target_host="10.10.9.239"
    )

def t_setup_SSL_for_oracle():
    print("  ➜ Create server wallet")
    run_as_user(["mkdir", "-p", "/opt/oracle/product/19c/dbhome_1/wallet"], user="oracle", text=True, capture_output=True)
    run_as_user(["/opt/oracle/product/19c/dbhome_1/bin/orapki", "wallet", "create", "-wallet", "/opt/oracle/product/19c/dbhome_1/wallet", "-auto_login_local", "-pwd", f"'{get_env_value("DEMOUSER_PASSWORD")}'"], user="oracle", text=True, capture_output=True)
    print("  ➜ Add self-sign certificate to server wallet")
    run_as_user(["/opt/oracle/product/19c/dbhome_1/bin/orapki", "wallet", "add", "-wallet", r'/opt/oracle/product/19c/dbhome_1/wallet', "-dn", r'CN=raptor.gdemo.com', "-keysize", "2048", "-self_signed", "-validity", "3650", "-pwd", f"'{get_env_value("DEMOUSER_PASSWORD")}'"], user="oracle", text=True, capture_output=True)
    print("  ➜ Create client wallet")
    run_as_user(["mkdir", "-p", "/opt/oracle/product/19c/dbhome_1/client_wallet"], user="oracle", text=True)
    run_as_user(["/opt/oracle/product/19c/dbhome_1/bin/orapki", "wallet", "create", "-wallet", "/opt/oracle/product/19c/dbhome_1/client_wallet", "-auto_login_local", "-pwd", f"'{get_env_value("DEMOUSER_PASSWORD")}'"], user="oracle", text=True, capture_output=True)
    print("  ➜ Add self-sign certificate to client wallet")
    run_as_user(["/opt/oracle/product/19c/dbhome_1/bin/orapki", "wallet", "add", "-wallet", r'/opt/oracle/product/19c/dbhome_1/client_wallet', "-dn", r'CN=client', "-keysize", "2048", "-self_signed", "-validity", "3650", "-pwd", f"'{get_env_value("DEMOUSER_PASSWORD")}'"], user="oracle", text=True, capture_output=True)
    print("  ➜ Export public keys")
    run_as_user(["/opt/oracle/product/19c/dbhome_1/bin/orapki", "wallet", "export", "-wallet", r'/opt/oracle/product/19c/dbhome_1/wallet', "-dn", r'CN=raptor.gdemo.com', "-cert", "/tmp/server-cert.crt", "-pwd", f"'{get_env_value("DEMOUSER_PASSWORD")}'"], user="oracle", text=True, capture_output=True)
    run_as_user(["/opt/oracle/product/19c/dbhome_1/bin/orapki", "wallet", "export", "-wallet", r'/opt/oracle/product/19c/dbhome_1/client_wallet', "-dn", r'CN=client', "-cert", "/tmp/client-cert.crt", "-pwd", f"'{get_env_value("DEMOUSER_PASSWORD")}'"], user="oracle", text=True, capture_output=True)
    print("  ➜ Import public keys")
    run_as_user(["/opt/oracle/product/19c/dbhome_1/bin/orapki", "wallet", "add", "-wallet", r'/opt/oracle/product/19c/dbhome_1/client_wallet', "-trusted_cert", "-cert", "/tmp/server-cert.crt", "-pwd", f"'{get_env_value("DEMOUSER_PASSWORD")}'"], user="oracle", text=True, capture_output=True)
    run_as_user(["/opt/oracle/product/19c/dbhome_1/bin/orapki", "wallet", "add", "-wallet", r'/opt/oracle/product/19c/dbhome_1/wallet', "-trusted_cert", "-cert", "/tmp/client-cert.crt", "-pwd", f"'{get_env_value("DEMOUSER_PASSWORD")}'"], user="oracle", text=True, capture_output=True)
    run_as_user(["rm", "/tmp/server-cert.crt", "/tmp/client-cert.crt"], user="oracle", text=True)
    print("  ➜ Change listener configuration")
    subprocess.run(["cp", "-f", "guardium_configuration_files/listener.ora", "/opt/oracle/product/19c/dbhome_1/network/admin/listener.ora"], check=True, capture_output=True)
    subprocess.run(["cp", "-f", "guardium_configuration_files/tnsnames.ora", "/opt/oracle/product/19c/dbhome_1/network/admin/tnsnames.ora"], check=True, capture_output=True)
    subprocess.run(["cp", "-f", "guardium_configuration_files/sqlnet.ora", "/opt/oracle/product/19c/dbhome_1/network/admin/sqlnet.ora"], check=True, capture_output=True)
    subprocess.run(["chown", "-R", "oracle:oinstall", "/opt/oracle/product/19c/dbhome_1/network/admin/"], check=True)
    print("  ➜ Restart listener")
    run_as_user(["bash","-lc", "/opt/oracle/product/19c/dbhome_1/bin/lsnrctl reload"], user="oracle", text=True, capture_output=True)

def t_setup_ATAP_for_oracle():
    print("  ➜ Stop oracle instance")
    run_as_user(["bash","-lc", "/opt/oracle/product/19c/dbhome_1/bin/lsnrctl stop"], user="oracle", text=True, capture_output=True)
    run_as_user(["bash","-lc", r"$ORACLE_HOME/bin/dbshut $ORACLE_HOME"], user="oracle", text=True, capture_output=True)
    print("  ➜ ATAP setup for oracle on raptor")
    subprocess.run(["/opt/guardium/modules/ATAP/current/files/bin/guardctl", "--db-user=oracle", "--db-home=/opt/oracle/product/19c/dbhome_1", "--db-base=/home/oracle", "--db-type=oracle", "--db-instance=ORCLDB", "--db-version=19", "store-conf"], check=True, capture_output=True)
    subprocess.run(["/opt/guardium/modules/ATAP/current/files/bin/guardctl", "authorize-user", "oracle"], check=True, capture_output=True)
    subprocess.run(["/opt/guardium/modules/ATAP/current/files/bin/guardctl", "--db-type=oracle --db-instance=ORCLDB", "activate"], check=True, capture_output=True)
    print("  ➜ Start oracle instance")
    run_as_user(["bash","-lc", r"$ORACLE_HOME/bin/dbstart $ORACLE_HOME"], user="oracle", text=True, capture_output=True)
    run_as_user(["bash","-lc", "/opt/oracle/product/19c/dbhome_1/bin/lsnrctl stop"], user="oracle", text=True, capture_output=True)

def t_deploy_oracle_in_container_on_hana():
    print("  ➜ Download and setup Oracle 21c container on hana")
    unpack_cmd = "bash -lc 'gunzip -k /home/oracle19_oua_image.tar.gz 2>/dev/null || true'"
    result=run_many_commands_remotely(host='10.10.9.60', password=get_env_value("HANA_PASSWORD"), print_output=False,
    commands=[
        f"wget -q {get_env_value('ORACLE_OUA_IMAGE')} -O /home/oracle19_oua_image.tar.gz",
        unpack_cmd,
        f"rm -f /home/oracle19_oua_image.tar.gz",
        "podman load -qi /home/oracle19_oua_image.tar",
        f"rm -f /home/oracle19_oua_image.tar"
    ])
    print("  ➜ Setup oracle container on hana")
    result=run_many_commands_remotely(host='10.10.9.60', password=get_env_value("HANA_PASSWORD"), print_output=False,
    commands=[
        "mkdir -p /home/oradata",
        "chown -R 54321:54321 /home/oradata",
        "chmod -R 775 /home/oradata",
        "semanage fcontext -a -t container_file_t '/home/oradata(/.*)?'",
        "restorecon -Rv /home/oradata"
    ])

    print("  ➜ Starting oracle container on hana")
    result=run_many_commands_remotely(host='10.10.9.60', password=get_env_value("HANA_PASSWORD"), print_output=False,
    commands=[
        f"podman run -d --name oracle_db_21c -p 1521:1521 -p 5500:5500 -e ORACLE_EDITION=EE -e ORACLE_SID=ORCL  -e ORACLE_PDB=ORCLPDB1  -e ORACLE_CHARACTERSET=AL32UTF8 -e ORACLE_SERVICE_NAME=ORCLPDB1.localdomain -v /home/oradata:/opt/oracle/oradata -e ORACLE_PWD='{get_env_value("DEFAULT_SERVICE_PASSWORD")}' oracle/database:21.3.0-ee-oua"
    ])
    interval_sec = 30
    timeout_sec = 1800
    deadline = time.time() + timeout_sec
    last_out = None
    print("  ➜ Monitoring first start of oracle container on hana")
    while time.time() < deadline:
        res=run_many_commands_remotely(host='10.10.9.60', password=get_env_value("HANA_PASSWORD"), print_output=False,
            commands=[r"podman logs oracle_db_21c 2>&1 | grep -F 'DATABASE IS READY TO USE' | wc -l"],
        )[0]
        out = (res.get("stdout") or "").strip()
        err = (res.get("stderr") or "").strip()
        rc = res.get("rc")
        last_out = out

        # If you want to log status:
        print(f"  ⌛ rc={rc} out={out!r} err={err[:120]!r}")
        # out should be a number (result of wc -l)
        try:
            count = int(out) if out else 0
        except ValueError:
            count = 0
        if count >= 1:
            print("  ✔ Found readiness marker in logs. Oracle deployed.")
            break
        time.sleep(interval_sec)
    else:
        raise TimeoutError(
            f"Timeout after {timeout_sec}s waiting for log marker. Last stdout={last_out!r}"
    )

def t_create_oracle_csr_for_etap():
    print("  ➜ Connect to appliance")
    appliance = ApplianceCommand(
        host="10.10.9.239",
        strip_ansi=True,
        user="cli",
        password=get_env_value("COLLECTOR_PASSWORD"),
        prompt_regex=r">",
        debug=False
    )
    print("  ➜ Generate CSR for Oracle ETAP")
    if appliance.connect():
        csr, token, line_above = appliance.generate_external_stap_csr(
        alias="oracle-etap",
        common_name="oracle-etap",
        san1="coll1.gdemo.com"
    )
        file_path = "/root/gn-trainings/ETAP/ca/etap2.csr"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(csr)
        save_to_env("ETAP_CSR_ID", line_above)
        save_to_env("ETAP_TOKEN_ORACLE", token)
    appliance.disconnect()
    print("  ➜ Signing CSR by CA")
    subprocess.run(["openssl", "x509", "-sha256", "-req", "-days", "3650", "-CA", "/root/gn-trainings/ETAP/ca/ca.pem", "-CAkey", "/root/gn-trainings/ETAP/ca/ca.key", "-CAcreateserial", "-CAserial", "serial", "-in", "/root/gn-trainings/ETAP/ca/etap2.csr", "-out", "/root/gn-trainings/ETAP/ca/etap2.pem"], check=True, capture_output=True)

def t_import_oracle_etap_cert():
    appliance = ApplianceCommand(
        host="10.10.9.239",
        strip_ansi=True,
    user="cli",
    password=get_env_value("COLLECTOR_PASSWORD"),
    prompt_regex=r">",
    debug=False
    )   
    if appliance.connect():
    # Wczytaj certyfikat External S-TAP
        with open("/root/gn-trainings/ETAP/ca/etap2.pem") as f:
            etap_cert = f.read()
        # Importuj certyfikat
        appliance.import_external_stap_certificate(
            alias_line=get_env_value("ETAP_CSR_ID"),
            stap_cert=etap_cert
        )
    appliance.disconnect()

def t_start_oracle_etap():
    etap_host = "10.10.9.60"
    database_port = "1521"
    token = get_env_value("ETAP_TOKEN_ORACLE")
    db_type = "oracle"
    etap_label = "ORACLEETAP"
    collector_ip = "10.10.9.239"
    etap_release = get_env_value("GUARDIUM_ETAP_VERSION")
    listen_port = "64444"

    etap_command = [
        "podman",
        "run",
        "--restart",
        "unless-stopped",
        "--name",
        "oracle-etap",
        "-d",
        "--shm-size",
        "800M",
        "-e",
        "STAP_CONFIG_TAP_TAP_IP=NULL",
        "-e",
        "STAP_CONFIG_TAP_PRIVATE_TAP_IP=NULL",
        "-e",
        "STAP_CONFIG_TAP_FORCE_SERVER_IP=0",
        "-e",
        "STAP_CONFIG_PROXY_GROUP_UUID=df7c55b1-a8ba-45e5-a3e8-271d17f0068a",
        "-e",
        "STAP_CONFIG_PROXY_GROUP_MEMBER_COUNT=1",
        "-e",
        f"STAP_CONFIG_PROXY_DB_HOST={etap_host}",
        "-e",
        "STAP_CONFIG_PROXY_NUM_WORKERS=1",
        "-e",
        "STAP_CONFIG_PROXY_PROXY_PROTOCOL=0",
        "-e",
        "STAP_CONFIG_PROXY_DISCONNECT_ON_INVALID_CERTIFICATE=0",
        "-e",
        "STAP_CONFIG_PROXY_NOTIFY_ON_INVALID_CERTIFICATE=0",
        "-e",
        "STAP_CONFIG_PROXY_DETECT_SSL_WITHIN_X_PACKETS=-1",
        "-e",
        f"STAP_CONFIG_DB_0_REAL_DB_PORT={database_port}",
        "-e",
        "STAP_CONFIG_PROXY_LISTEN_PORT=8888",
        "-e",
        "STAP_CONFIG_PROXY_DEBUG=0",
        "-e",
        f"STAP_CONFIG_PROXY_SECRET={token}",
        "-e",
        "STAP_CONFIG_PROXY_CSR_NAME=",
        "-e",
        "STAP_CONFIG_PROXY_CSR_COUNTRY=",
        "-e",
        "STAP_CONFIG_PROXY_CSR_PROVINCE=",
        "-e",
        "STAP_CONFIG_PROXY_CSR_CITY=",
        "-e",
        "STAP_CONFIG_PROXY_CSR_ORGANIZATION=",
        "-e",
        "STAP_CONFIG_PROXY_CSR_KEYLENGTH=2048",
        "-e",
        f"STAP_CONFIG_DB_0_DB_TYPE={db_type}",
        "-e",
        "STAP_CONFIG_PARTICIPATE_IN_LOAD_BALANCING=0",
        "-e",
        f"STAP_CONFIG_TAP_TENANT_ID={etap_label}",
        "-e",
        f"STAP_CONFIG_SQLGUARD_0_SQLGUARD_IP={collector_ip}",
        f"-p={listen_port}:8888/tcp",
        "-q",
        f"icr.io/guardium/guardium_external_s-tap:v{etap_release}"
    ]
    subprocess.run(etap_command, check=True, capture_output=True)
    time.sleep(10)
    print("\n ETAP stopped for other part of lab")
    subprocess.run(["podman", "stop", "oracle-etap"], check=True, capture_output=True)

def t_setup_oracle_traffic_generator():
    password = get_env_value("DEFAULT_SERVICE_PASSWORD")
    commands = [
        {"cmd": ["mkdir", "-p", "/root/gn-trainings/dbtraffic"]},
        {"cmd": ["/usr/bin/python3.12", "-m", "venv", ".venv"], "cwd" : "/root/gn-trainings/dbtraffic"},
        {"cmd": ["/root/gn-trainings/dbtraffic/.venv/bin/python3", "-m", "pip", "install", "--upgrade", "pip"], "cwd" : "/root/gn-trainings/dbtraffic"},
        {"cmd": ["/root/gn-trainings/dbtraffic/.venv/bin/pip3", "install", "oracledb", "psycopg2_binary", "faker"], "cwd" : "/root/gn-trainings/dbtraffic"},
        {"cmd": ["wget", "https://ibm.box.com/shared/static/dcm5st6jt4w6ippvkz3ka5ebvb47gymi.zip", "-O", "dbtraffic.zip"], "cwd" : "/root/gn-trainings/dbtraffic"},
        {"cmd": ["unzip", "dbtraffic.zip"], "cwd" : "/root/gn-trainings/dbtraffic"},
        {"cmd": ["sed", "-i", f"s|^password *=.*|password = {password}|", "/root/gn-trainings/dbtraffic/files/config.cfg"]},
        {"cmd": ["/root/gn-trainings/dbtraffic/.venv/bin/python3", "./gn_dbtraffic.py", "schema"], "cwd" : "/root/gn-trainings/dbtraffic"}
    ]
    for c in commands:
        subprocess.run(
            c["cmd"],
            cwd=c.get("cwd"),
            check=True, capture_output=True
        )

def t_setup_OUA_on_oracle_on_hana():
    print("  ➜ Create secadmin and guardium users")
    conn =  get_oracle_conn(user="system", password=get_env_value('DEFAULT_SERVICE_PASSWORD'), host="10.10.9.60", port=1521, service_name="ORCLPDB1")
    run_sql_oracle(conn, 'CREATE USER secadmin IDENTIFIED BY "{}"'.format(get_env_value('DEFAULT_SERVICE_PASSWORD')))
    run_sql_oracle(conn, 'CREATE USER guardium IDENTIFIED BY "{}"'.format(get_env_value('DEFAULT_SERVICE_PASSWORD')))
    conn.commit()
    run_sql_oracle(conn, "grant CONNECT, SELECT ANY DICTIONARY, SELECT_CATALOG_ROLE, AUDIT_ADMIN, CREATE PROCEDURE, DROP ANY PROCEDURE, AUDIT SYSTEM, AUDIT ANY, CREATE JOB to SECADMIN")
    run_sql_oracle(conn, "GRANT CONNECT, RESOURCE to guardium")
    run_sql_oracle(conn, "GRANT SELECT ANY DICTIONARY TO guardium")
    run_sql_oracle(conn, r"BEGIN DBMS_NETWORK_ACL_ADMIN.APPEND_HOST_ACE(host => 'localhost', ace => xs$ace_type(privilege_list => xs$name_list('connect', 'resolve'), principal_name => 'guardium', principal_type => xs_acl.ptype_db)); END;")
    conn.commit()
    conn.close()
    print("  ➜ Setup access to OUA records")
    conn =  get_oracle_conn(user="secadmin", password=f"{get_env_value('DEFAULT_SERVICE_PASSWORD')}", host="10.10.9.60", port=1521, service_name="ORCLPDB1")
    run_sql_oracle(conn, r"BEGIN DECLARE v_cnt NUMBER; BEGIN SELECT COUNT(*) INTO v_cnt FROM audit_unified_policies WHERE policy_name='GAME_APP'; IF v_cnt=0 THEN EXECUTE IMMEDIATE 'CREATE AUDIT POLICY GAME_APP ACTIONS ALL ON game.customers, ALL ON game.credit_cards, ALL ON game.transactions, ALL ON game.extras, ALL ON game.features'; END IF; EXECUTE IMMEDIATE 'AUDIT POLICY GAME_APP'; END; END;")
    run_sql_oracle(conn, r"BEGIN DBMS_SCHEDULER.create_job(job_name=>'ENSURE_GAME_APP_AUDIT', job_type=>'STORED_PROCEDURE', job_action=>'ENSURE_GAME_APP_AUDIT', repeat_interval=>'FREQ=MINUTELY;INTERVAL=45', enabled=>TRUE); END;")
    conn.commit()
    # policies = run_sql_oracle(conn, "SELECT POLICY_NAME FROM AUDIT_UNIFIED_ENABLED_POLICIES", fetch=True)
    # if policies:
    #     for policy in policies:
    #         print(policy)
    # else:
    #     pass
    conn.close()

def t_install_stap_on_hana(api):
    print("  ➜ Installing oracle instant client on hana")
    run_many_commands_remotely(host='10.10.9.60', password=get_env_value("HANA_PASSWORD"), print_output=False,
        commands=[
            "wget -O oracle-instantclient-basic-21.12.0.0.0-1.el9.x86_64.rpm https://ibm.box.com/shared/static/6kyb3ivksqvv26bfnz2ckrojw2b34bhg.rpm",
            "dnf -y install ./oracle-instantclient-basic-21.12.0.0.0-1.el9.x86_64.rpm",
            "rm -f ./oracle-instantclient-basic-21.12.0.0.0-1.el9.x86_64.rpm"
        ])
    print("  ➜ Copy files from raptor to hana")
    scp_file_as_root(host='10.10.9.60', root_password=get_env_value("HANA_PASSWORD"),  local_path="/root/gn-trainings/gim_installers/guard-bundle-GIM-12.2.0.0_r121306_v12_2_1-rhel-9-linux-x86_64.gim.sh", remote_path=".")
    scp_file_as_root(host='10.10.9.60', root_password=get_env_value("HANA_PASSWORD"),  local_path="guardium_configuration_files/tnsnames_hana.ora", remote_path="/usr/lib/oracle/21/client64/lib/network/admin/tnsnames.ora")
    print("  ➜ Install gim client on hana")
    run_many_commands_remotely(host='10.10.9.60', password=get_env_value("HANA_PASSWORD"), print_output=False, commands=[
        "./guard-bundle-GIM-12.2.0.0_r121306_v12_2_1-rhel-9-linux-x86_64.gim.sh -- --dir /opt/guardium --tapip 10.10.9.60 --sqlguardip 10.10.9.219 -q"
    ])
    time.sleep(60)
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    print("  ➜ Install STAP on hana")
    api.gim_client_assign(
        client_ip="10.10.9.60",
        module="BUNDLE-STAP",
        module_version="12.2.0.0_r121306_5"
    )
    api.gim_client_params(
        client_ip="10.10.9.60",
        param_name="KTAP_ENABLED",
        param_value="0"
    )
    api.gim_client_params(
        client_ip="10.10.9.60",
        param_name="STAP_SQLGUARD_IP",
        param_value="10.10.9.239"
    )
    api.gim_schedule_install(
        client_ip="10.10.9.60",
        date="now",
    )
    print("  ➜ STAP installation monitoring")
    monitor_gim_module_installation(api, "10.10.9.60")
    print("  ➜ Configure STAP to support OUA monitoring")
    run_many_commands_remotely(host='10.10.9.60', password=get_env_value("HANA_PASSWORD"), print_output=False, commands=[
        "sed -i 's|^sqlc_properties_dir=.*|sqlc_properties_dir=/usr/lib/oracle/21/client64/lib/network/admin|' /opt/guardium/modules/STAP/current/guard_tap.ini",
        "sed -i 's|^ld_library_paths=.*|ld_library_paths=/usr/lib/oracle/21/client64/lib|' /opt/guardium/modules/STAP/current/guard_tap.ini",
        "/opt/guardium/modules/STAP/current/guard-config-update --restart STAP"
    ])
    print("  ➜ Add oracle user credentials to get access to OUA records")
    result = api.store_sql_credentials(password=get_env_value("DEFAULT_SERVICE_PASSWORD"), username="guardium", stap_host='10.10.9.60', api_target_host='10.10.9.239')
    print("  ➜ Adding OUA configuration")
    result = api.create_sql_configuration(db_type="Oracle", instance="ORCLPDB1", stap_host='10.10.9.60', username='guardium', api_target_host='10.10.9.239')
    print("  ➜ Stopping STAP on HANA")
    api.gim_client_params(
        client_ip="10.10.9.60",
        param_name="STAP_ENABLED",
        param_value="0"
    )
    api.gim_schedule_install(
        client_ip="10.10.9.60",
        date="now",
    )
    print("  ➜ STAP disable monitoring")
    monitor_gim_module_installation(api, "10.10.9.60")

def t_policy_report_1(api):
    print("  ➜ Create sensitive table for lab")
    conn = get_postgres_conn(host='10.10.9.70', port=5432, dbname='postgres', user='jerry', password=f'{get_env_value("DEFAULT_SERVICE_PASSWORD")}')
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("CREATE TABLE customers (first_name VARCHAR(50),last_name VARCHAR(50),email_address VARCHAR(100),credit_card_number VARCHAR(20))")
    cur.execute("INSERT INTO customers VALUES ('John', 'Smith', 'john.smith@example.com', '4111 1111 1111 1111'),('Jane', 'Doe', 'jane.doe@example.com', '5500 0000 0000 0004'),('Alice', 'Johnson', 'alice.j@example.com', '3400 0000 0000 009'),('Bob', 'Brown', 'bob.brown@example.com', '6011 0000 0000 0004'),('Carol', 'Davis', 'carol.d@example.com', '4111 1111 1111 1234'),('David', 'Wilson', 'david.w@example.com', '5500 0000 0000 5678'),('Emma', 'Taylor', 'emma.t@example.com', '3400 0000 0000 4321'),('Frank', 'Miller', 'frank.m@example.com', '6011 0000 0000 8765'),('Grace', 'Lee', 'grace.l@example.com', '4111 1111 1111 9999'),('Henry', 'Clark', 'henry.c@example.com', '5500 0000 0000 8888')")
    cur.execute("GRANT SELECT ON customers TO PUBLIC")
    cur.close()
    conn.close()
    print("  ➜ Enable STAP DBF feature on raptor")
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    api.gim_client_params(
        client_ip="10.10.9.70",
        param_name="STAP_FIREWALL_INSTALLED",
        param_value="1"
    )
    api.gim_client_params(
        client_ip="10.10.9.70",
        param_name="STAP_FIREWALL_DEFAULT_STATE",
        param_value="1"
    )
    api.gim_schedule_install(
        client_ip="10.10.9.70",
        date="now",
    )
    print("  ➜ STAP reconfiguration monitoring")
    monitor_gim_module_installation(api, "10.10.9.70")
    print("  ➜ Import blocking policy")
    result = api.import_definitions('guardium_definition_files/exp_policy_log_everything_with_blocking.sql')
    print("  ➜ Install blocking Policy")
    result = api.install_policy("Blocking Policy (Policies and Reports I)|raptor FAM policy", api_target_host="10.10.9.239")
    print("  ➜ Setup new dashboard - Policies and Reports I")
    result = api.import_definitions('guardium_definition_files/exp_dashboard_policies_and_reports_I.sql')
    print("  ➜ Configure parsing engine")
    result = api.engine_config(compute_average=True, inspect_data=True, log_records=True, record_empty=True, api_target_host="10.10.9.239")
    # print(result)
    # sprawdzic czy zmiany w engine core widoczne jak nie to albo restart appliance albo restart inspection-core

def t_va_api(api):
    token = api.get_token(username='demo', password=get_env_value('DEMOUSER_PASSWORD'))
    print("  ➜ Setup new dashboard - VA")
    result = api.import_definitions('guardium_definition_files/exp_dashboard_va.sql')
    print("  ➜ Import oracle VA definition")
    result = api.import_definitions('guardium_definition_files/exp_security_assessment_va_oracle.sql')
    print("  ➜ Setup VA REST API python project")
    commands = [
        {"cmd": ["mkdir", "-p", "/root/gn-trainings/va-api"]},
        {"cmd": ["/usr/bin/python3.12", "-m", "venv", ".venv"], "cwd" : "/root/gn-trainings/va-api"},
        {"cmd": ["/root/gn-trainings/va-api/.venv/bin/python3", "-m", "pip", "install", "--upgrade", "pip"], "cwd" : "/root/gn-trainings/va-api"},
        {"cmd": ["/root/gn-trainings/va-api/.venv/bin/pip3", "install", "requests", "argparse"], "cwd" : "/root/gn-trainings/va-api"},
        {"cmd": ["wget", "https://ibm.box.com/shared/static/u97weythylmplu0jottrpzmifnn7jvse", "-O", "project.zip"], "cwd" : "/root/gn-trainings/va-api"},
        {"cmd": ["unzip", "project.zip"], "cwd" : "/root/gn-trainings/va-api"},
    ]
    for c in commands:
        subprocess.run(
            c["cmd"],
            cwd=c.get("cwd"),
            check=True, capture_output=True,
        )

def lab13_va_api(state):
    """
    LAB 13 - VA API

    """

    api = GuardiumRestAPI(
        base_url='https://10.10.9.219:8443/',
        client_id='BOOTCAMP'
    )
    run_task('Setup environment for VA API lab', lambda: t_va_api(api), state, STATE_FILE)

def lab12_policy_report1(state):
    """
    LAB 12 - Policies and Reports I

    """
    
    api = GuardiumRestAPI(
        base_url='https://10.10.9.219:8443/',
        client_id='BOOTCAMP'
    )
    run_task('Setup environment for policies and report lab', lambda: t_policy_report_1(api), state, STATE_FILE)

def lab11_oracle(state):
    """
    LAB 11 - Oracle
    """
    
    api = GuardiumRestAPI(
        base_url='https://10.10.9.219:8443/',
        client_id='BOOTCAMP'
    )
    run_task('Configure system for oracle lab', lambda: t_configure_env_for_oracle(api), state, STATE_FILE)
    run_task('Configure SSL support for oracle on raptor', lambda: t_setup_SSL_for_oracle(), state, STATE_FILE)
    run_task('Configure ATAP for oracle on raptor', lambda: t_setup_ATAP_for_oracle(), state, STATE_FILE)
    run_task('Deploy Oracle in container on hana', lambda: t_deploy_oracle_in_container_on_hana(), state, STATE_FILE)
    run_task('Create CSR for ETAP for oracle in container', lambda: t_create_oracle_csr_for_etap(), state, STATE_FILE)
    run_task('Import ETAP for oracle in container certificate', lambda: t_import_oracle_etap_cert(), state, STATE_FILE)
    run_task('Start oracle ETAP', lambda: t_start_oracle_etap(), state, STATE_FILE)
    run_task('Traffic generator for Oracle', lambda: t_setup_oracle_traffic_generator(), state, STATE_FILE)
    run_task('Confgure OUA to monitor application', lambda: t_setup_OUA_on_oracle_on_hana(), state, STATE_FILE)
    run_task('Install STAP on hana', lambda: t_install_stap_on_hana(api), state, STATE_FILE)

def lab10_fam(state):
    """
    LAB 10 - FAM
    """
    
    api = GuardiumRestAPI(
        base_url='https://10.10.9.219:8443/',
        client_id='BOOTCAMP'
    )
    run_task('Enable FAM on raptor', lambda: t_enable_fam_on_raptor(api), state, STATE_FILE)
    run_task('Enable FAM on winsql', lambda: t_install_enable_fam_on_winsql(api), state, STATE_FILE)
    run_task('Import FAM definitions', lambda: t_import_fam_definitions(api), state, STATE_FILE)
    run_task('Install FAM policy on collector', lambda: t_install_fam_policy(api), state, STATE_FILE)

def lab9_winstap(state):
    """
    LAB 9 - WINSTAP
    """
    
    api = GuardiumRestAPI(
        base_url='https://10.10.9.219:8443/',
        client_id='BOOTCAMP'
    )
    run_task('Install GIM client on winsql', lambda: t_install_gim_on_winsql(), state, STATE_FILE)
    run_task('Install STAP on winsql', lambda: t_install_stap_on_winsql(api), state, STATE_FILE)

def lab8_va(state):
    """
    LAB 8 - VA
    """
    
    api = GuardiumRestAPI(
        base_url='https://10.10.9.219:8443/',
        client_id='BOOTCAMP'
    )
    run_task('Configure raptor for VA', lambda: t_configure_raptor_for_va(), state, STATE_FILE)
    run_task('Configure VA scanner', lambda: t_setup_vascanner(), state, STATE_FILE)
    run_task('Import VA process for postgres', lambda: t_import_va_process_for_postgres(api), state, STATE_FILE)
    run_task('Import DPS', lambda: t_import_DPS(), state, STATE_FILE)

def lab7_etap(state):
    """
    LAB 7 - ETAP
    """
        
    run_task('Setup raptor for ETAP', lambda: t_setup_raptor_to_deploy_etap(), state, STATE_FILE)
    run_task('Deploy CA on raptor', lambda: t_deploy_ca_on_raptor(), state, STATE_FILE)
    run_task('Create CSR for ETAP for mysql', lambda: t_create_mysql_csr_for_etap(), state, STATE_FILE)
    run_task('Import CA cert for ETAP', lambda: t_import_etap_ca_cert(), state, STATE_FILE)
    run_task('Import mysql ETAP cert', lambda: t_import_etap_cert(), state, STATE_FILE)
    run_task('Start mysql ETAP on raptor', lambda: t_start_etap(), state, STATE_FILE)

def lab6_uc1(state):
    """
    LAB 6 - UC 1.0

    """
      
    api = GuardiumRestAPI(
        base_url='https://10.10.9.239:8443/',
        client_id='BOOTCAMP'
    )
    run_task('Deploy cassandra on hana', lambda: t_setup_cassandra(), state, STATE_FILE)
    run_task('Deploy filebeat on hana', lambda: t_setup_filebeat(api), state, STATE_FILE)

def lab5_exit(state):
    """
    LAB 5 - EXIT
    """

    api = GuardiumRestAPI(
        base_url='https://10.10.9.219:8443',
        client_id='BOOTCAMP'
    )
    run_task('Setup EXIT for DB2 on raptor', lambda: t_exit_for_db2_setup(api), state, STATE_FILE)

def lab4_atap(state):
    """
    LAB 4 - ATAP
    """
    
    api = GuardiumRestAPI(
        base_url='https://10.10.9.219:8443',
        client_id='BOOTCAMP'
    )
    run_task('Installing psql on raptor', lambda: t_postgres_installation(), state, STATE_FILE)
    run_task('Create postgres admin users', lambda: t_create_postgres_admin_users(), state, STATE_FILE)
    run_task('Install GIM client on raptor', lambda: t_install_gim_on_raptor(), state, STATE_FILE)
    run_task('Install STAP on raptor', lambda: t_install_stap_on_raptor(api), state, STATE_FILE)
    run_task('Configure ATAP for postgres on raptor', lambda: t_enable_atap_for_postgres_on_raptor(), state, STATE_FILE)
    run_task('Correct mysql IE\'s', lambda: t_correct_mysql_ie(api), state, STATE_FILE)
    run_task('Configure SSL for Mongo', lambda: t_configure_ssl_for_mongo(), state, STATE_FILE)
    run_task('Enable ATAP for Mongo', lambda: t_enable_atap_for_mongo(), state, STATE_FILE)

def lab2_gim(state):
    """
    LAB 2 - GIM
    """

    api = GuardiumRestAPI(
        base_url='https://10.10.9.219:8443',
        client_id='BOOTCAMP'
    )
    run_task('Set collector resolving on raptor', lambda: t_set_collector_resolving_on_raptor(), state, STATE_FILE)
    run_task('Getting GIM files', lambda: t_getting_gim_files(), state, STATE_FILE)
    run_task('Import GIM files on CM', lambda: t_import_gim_modules(api), state, STATE_FILE)

def lab1_appliance_setup(state):
    """
    LAB 1 - Appliance configuration (collector).
    """

    run_task('Password change for cli users on appliances', lambda: t_password_change_on_appliances(), state, STATE_FILE)
    run_task('Initial collector setup', lambda: t_initial_collector_settings(), state, STATE_FILE)
    run_task('Collector restart', lambda: t_restart_system(), state, STATE_FILE)
    run_task('Other collector settings', lambda: t_other_collector_settings(), state, STATE_FILE)
    run_task('Initial CM settings', lambda: t_initial_cm_settings(), state, STATE_FILE)
    api = GuardiumRestAPI(
        base_url='https://10.10.9.219:8443',
        client_id='BOOTCAMP'
    )
    run_task('Create demo user', lambda: t_create_demo_user(api), state, STATE_FILE)
    run_task('Register collector', lambda: t_register_collector(api), state, STATE_FILE)
    run_task('Prepare appliances for patching', lambda: t_preparing_appliances_for_patching(api), state, STATE_FILE)
    for appliance_name, appliance_ip, password, task_number in [('cm', '10.10.9.219', get_env_value('CM_PASSWORD'), 'Register patches on cm'), ('collector', '10.10.9.239', get_env_value('COLLECTOR_PASSWORD'), f'Register patches on collector')]:
        run_task(task_number, lambda: t_registering_patches_installation(appliance_name, appliance_ip, password), state, STATE_FILE)
    for appliance_name, task_number in [('cm', 'Monitor patch installation on cm'), ('collector', 'Monitor patch installation on collector')]:
        run_task(task_number, lambda: t_monitoring_patch_installation(appliance_name), state, STATE_FILE)
    run_task('Policy installation on collector', lambda: t_install_policy_on_collector(api), state, STATE_FILE)

def sync_lab(state, skip_below: int = 0, stop_at: int = 999):
    """
        Args:
        skip_below: Skip LABs with number lower than given value (default 0 - execute all)
        stop_at: Stop after executing LAB with given number (default 999 - execute all)
    """
   
    # LAB configuration: (number, function, name, description)
    labs_config = [
        (1, lab1_appliance_setup, "Appliance Setup", "Appliance setup"),
        (2, lab2_gim, "GIM Setup", "GIM setup"),
        (3, None, "SKIPPED", "LAB 3 does not modify final environment"),
        (4, lab4_atap, "ATAP", "ATAP"),
        (5, lab5_exit, "EXIT", "EXIT"),
        (6, lab6_uc1, "UC 1.0", "LAB 6 focuses on UC 1.0 which will withdrawn in the future. There is no API to automate UC 1.0 configuration. Automated cassandra and filebeat setup."),
        (7, lab7_etap, "ETAP", "ETAP"),
        (8, lab8_va, "VA", "VA"),
        (9, lab9_winstap, "WINSTAP", "WINSTAP"),
        (10, lab10_fam, "FAM", "FAM"),
        (11, lab11_oracle, "Oracle", "Oracle"),
        (12, lab12_policy_report1, "Policy & Reports I", "New Dashboard added with reports for this lab"),
        (13, lab13_va_api, "VA API", "Use BOOTCAMP oauth client name instead 'va-api'"),
    ]
    
    # Iterate through all LABs
    for lab_num, lab_func, lab_name, lab_desc in labs_config:
        if skip_below < lab_num and stop_at >= lab_num:
            if lab_func is not None:
                # Execute LAB
                lab_func(state)
                print("\n" + "=" * 60)
                print(f"LAB {lab_num} - completed!")
                print("=" * 60)
            else:
                # LAB skipped (None)
                print("\n" + "=" * 60)
                print(f"LAB {lab_num} - skipped")
                print(lab_desc)
                print("=" * 60)
            
            # Check if should stop after this LAB
            if stop_at == lab_num:
                print(f"Stopped after LAB {lab_num} (--stop-at={lab_num})")
                return
        elif skip_below >= lab_num:
            print("\n" + "=" * 60)
            print(f"LAB {lab_num} - skipped - {lab_name} (--skip-below)")
            print("=" * 60)
        else:
            print("\n" + "=" * 60)
            print(f"LAB {lab_num} - skipped - {lab_name} (--stop-at)")
            print("=" * 60)

if __name__ == "__main__":
    import argparse
    import time

    STATE_FILE = "state.json"
    state = load_state(STATE_FILE)

    parser = argparse.ArgumentParser(description="Sync Lab - laboratory environment synchronization")
    parser.add_argument(
        "--skip-below",
        type=int,
        default=0,
        help="Skip LABs with number lower than given value (default 0 - execute all)"
    )
    parser.add_argument(
        "--stop-at",
        type=int,
        default=999,
        help="Stop after executing LAB with given number (default 999 - execute all)"
    )
    
    args = parser.parse_args()
    
    # Start time tracking
    start_time = time.time()
    
    try:
        sync_lab(state, skip_below=args.skip_below, stop_at=args.stop_at)
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user")
    except Exception as e:
        print(f"\n[ERROR] Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Calculate and display execution time
        end_time = time.time()
        execution_time = end_time - start_time
        hours = int(execution_time // 3600)
        minutes = int((execution_time % 3600) // 60)
        seconds = int(execution_time % 60)
        
        print("\n" + "=" * 60)
        print(f"Total execution time: {hours:02d}:{minutes:02d}:{seconds:02d}")
        print("=" * 60)





