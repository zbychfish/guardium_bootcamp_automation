# Guardium Bootcamp Automation v12.0.1

## Project Overview

This project automates the setup and configuration of IBM Guardium lab environments for bootcamp training purposes. It orchestrates the deployment and configuration of multiple Guardium appliances, databases, and related components to create a fully functional training environment.

### Key Features

- **Automated Appliance Configuration**: Configures Guardium Central Manager, Collectors, and Tool Nodes
- **Database Setup**: Automates Oracle, PostgreSQL, SAP HANA, and Cassandra database configurations
- **Patch Management**: Handles Guardium patch installation and verification
- **GIM (Guardium Installation Manager)**: Automates GIM client installation and S-TAP deployment
- **Vulnerability Assessment**: Sets up VA scanner containers and processes
- **REST API Integration**: Leverages Guardium REST API for configuration tasks
- **State Management**: Tracks completed tasks to enable resumable execution
- **Multi-Platform Support**: Manages both Linux and Windows environments

### Components

The project consists of several key modules:

- `sync_lab.py` - Main orchestration script
- `appliance_command.py` - SSH-based appliance command execution
- `guardium_rest_api.py` - Guardium REST API client
- `guardium_patch.py` - Patch installation automation
- `windows_management.py` - Windows machine management via WinRM
- `utils.py` - Utility functions for SSH, database operations, and parsing
- `manual_web_ui_processing.py` - Web UI automation using Playwright


## Prerequisites

### System Requirements

You should use this project inside Guardiun Bootcamp lab environment - v12

### Python Dependencies

Install required Python packages:

```bash
pip install -r requirements.txt
```

Required packages:
- `paramiko` - SSH client library
- `python-dotenv` - Environment variable management
- `requests` - HTTP client for REST API
- `playwright` - Web automation
- `psycopg2-binary` - PostgreSQL adapter
- `oracledb` - Oracle database client
- `pywinrm` - Windows Remote Management client
- `packaging` - Version parsing utilities


## Setup Instructions

### Clone the Repository

```bash
git clone <repository-url>
cd guardium_bootcamp_automation
```

### Configure Environment Variables

Create a `.env` file based on the provided template:

```bash
cp .env.example .env
```

Edit the `.env` file and configure the following:

#### Required Passwords
- `COLLECTOR_PASSWORD` - Collector appliance CLI password
- `CM_PASSWORD` - Central Manager CLI password
- `TOOLNODE_PASSWORD` - Tool Node CLI password
- `ROOT_PASSWORD` - Root password for all appliances
- `ACCESSMGR_PASSWORD` - Central Manager UI admin password
- `DEMOUSER_PASSWORD` - Demo user UI password
- `RAPTOR_PASSWORD` - Raptor machine root password
- `HANA_PASSWORD` - HANA machine root password
- `WINSQL_PASSWORD` - Windows SQL server administrator password
- `APPNODE_PASSWORD` - Application node root password
- `DEFAULT_SERVICE_PASSWORD` - Default password for all configured services

#### Configuration Parameters
- `PATCH_ARCHIVE` - URL to Guardium patch archive
- `GIM_INSTALLERS_ARCHIVE` - URL to GIM installers
- `GIM_BUNDLES_ARCHIVE` - URL to GIM bundles
- `DPS_ZIP_ARCHIVE` - URL to DPS (Data Protection Suite) archive
- `ORACLE_OUA_IMAGE` - URL to Oracle OUA image
- `DPS_NAME` - DPS filename
- `PATCH_NAME_LIST` - Comma-separated list of patch filenames
- `PATCH_LIST` - Comma-separated list of patch IDs
- `GUARDIUM_MINOR_VERSION` - Guardium version (e.g., 12.2)
- `IBM_REGISTRY_KEY` - IBM Container Registry API key (required for VA scanner)
- `VASCANNER_IMAGE_TAG` - VA scanner container image tag
- `FILEBEAT_VERSION` - Filebeat version for log shipping

#### Dynamic Parameters
These are automatically generated during execution:
- `CLIENT_SECRET`
- `PATCH_ORDER`
- `ETAP_CSR_ID`
- `ETAP_TOKEN`
- `ETAP_TOKEN_ORACLE`
- `GUARDIUM_ETAP_VERSION`


## Running the Automation

### Full Lab Setup

To run the complete lab setup automation:

```bash
cd guardium_bootcamp_automation
python sync_lab.py
```

The script will:
1. Validate the `.env` configuration
2. Execute tasks in sequence
3. Track progress in `state.json`
4. Skip already completed tasks on restart

### Resume After Interruption

If the script is interrupted, simply run it again. The state management system will skip completed tasks and resume from where it left off.

### Acquire the desired lab environment state, run the following commands:

cd guardium_bootcamp_automation
python sync_lab.py --stop-at=<lab_number>

Lab order:
1 - Appliance setup
2 - GIM Setup
3 - STAP
4 - ATAP
5 - EXIT
6 - UC 1.0 (only pre-req)
7 - ETAP
8 - VA
9 - WINSTAP
10 - FAM
11 - ORACLE
12 - Policy & Reports I
13 - VA API


## Project Structure

```
guardium_bootcamp_automation/
├── README.md                           # This file
├── requirements.txt                    # Python dependencies
├── .env.example                        # Environment template
├── sync_lab.py                         # Main orchestration script
├── appliance_command.py                # Appliance SSH operations
├── guardium_rest_api.py                # REST API client
├── guardium_patch.py                   # Patch management
├── windows_management.py               # Windows operations
├── utils.py                            # Utility functions
├── manual_web_ui_processing.py         # Web UI automation
├── guardium_configuration_files/       # Configuration templates
│   ├── cassandra.repo
│   ├── cassandra_table.cql
│   ├── listener.ora
│   ├── sqlnet.ora
│   ├── tnsnames.ora
│   ├── tnsnames_hana.ora
│   └── vascanner_config
└── guardium_definition_files/          # Guardium definitions
    ├── exp_dashboard_*.sql
    ├── exp_policy_*.sql
    └── exp_security_assessment_*.sql
```


## Security Considerations

- Store `.env` file securely and never commit it to version control
- Use strong passwords for all services
- Restrict network access to management interfaces
- Regularly update patches and dependencies
- Review and audit automation logs
