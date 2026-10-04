# Product Requirement Document (PRD)

## Title
Automated Multi-VM Infrastructure Provisioning for OpenCode & Hermes Agent via Ansible on Apple Silicon (OrbStack)

---

## 1. Executive Summary & Goal
The objective is to create a complete **Ansible playbook and inventory suite** that automatically provisions two isolated ARM64 Ubuntu Linux virtual machines on Apple Silicon using OrbStack. 

* **VM 1 (`hermes-vm`):** Operates as the orchestrator/manager running **Hermes Agent** with WebUI and MCP routing enabled.
* **VM 2 (`opencode-vm`):** Operates as the execution sandbox running **OpenCode Server** (`opencode serve`) mounted to a shared host project directory via VirtioFS.

This setup enforces strict security isolation while enabling automated cross-VM communication over an internal DNS bridge (`.orb.local`).

---

## 2. Architecture & Topography

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                             Mac Studio (macOS Host)                              │
│                                                                                  │
│   [ Local Workspace Path ] <──────── VirtioFS Mount ────────┐                    │
│   ~/AgentWorkspaces/project-alpha                          │                    │
│                                                            │                    │
│   [ Host Web Browser ] ──────> http://localhost:8333       │                    │
│                                                            │                    │
│   ┌───────────────────────────┐                ┌───────────▼──────────────┐     │
│   │   OrbStack: hermes-vm     │                │   OrbStack: opencode-vm  │     │
│   │                           │                │                          │     │
│   │   [ Hermes Agent ]        │ ─ REST / MCP ─>│   [ OpenCode Server ]    │     │
│   │   • Manager UI (:8333)    │  (Port 4096)   │   • `opencode serve`     │     │
│   │   • Subagent Orchestrator │                │   • `/workspace` Mount   │     │
│   └───────────────────────────┘                └──────────────────────────┘     │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Detailed Requirements & Technical Specifications

### Requirement 1: Host System & OrbStack VM Initialization
* **Target Environment:** macOS on Apple Silicon running OrbStack.
* **Ansible Role/Tasks:**
  1. Verify `orb` CLI availability on the controller.
  2. Provision two ARM64 Ubuntu 24.04 Linux instances:
     * Instance 1: `hermes-vm` (2 vCPUs, 4GB RAM dynamic memory allocation).
     * Instance 2: `opencode-vm` (4 vCPUs, 8GB RAM dynamic memory allocation).
  3. Ensure SSH key injection across host and both guest instances for non-interactive Ansible execution.

---

### Requirement 2: Provisioning `opencode-vm` (Execution Sandbox)
* **OS Target:** `opencode-vm.orb.local` (Ubuntu 24.04 ARM64).
* **System Packages:** `git`, `curl`, `unzip`, `build-essential`, `python3`, `python3-pip`, `nodejs`, `npm`.
* **Workspace & VirtioFS Mount:**
  * Ensure path `/mnt/mac/Users/{{ host_user }}/AgentWorkspaces/project-alpha` is mounted to `/workspace` inside the VM.
* **OpenCode Installation:**
  * Fetch and execute the official OpenCode CLI installer (`curl -fsSL https://opencode.ai/install.sh | bash`).
* **Daemon Configuration (systemd):**
  * Create a non-root system service (`opencode-server.service`) running:
    ```bash
    opencode serve --host 0.0.0.0 --port 4096 --workspace /workspace
    ```
  * Ensure the service automatically restarts on failure and starts on system boot.

---

### Requirement 3: Provisioning `hermes-vm` (Orchestrator Node)
* **OS Target:** `hermes-vm.orb.local` (Ubuntu 24.04 ARM64).
* **System Packages:** `git`, `curl`, `python3-venv`, `pip`, `build-essential`.
* **Hermes Agent Installation:**
  * Download and run official Hermes Agent CLI setup script (`curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash`).
* **Hermes Configuration & Cross-VM Orchestration:**
  * Configure Hermes environment file (`~/.hermes/.env` or `config.yaml`) with:
    * **Model Provider Keys:** Exposed via Ansible vault/variables (`OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`).
    * **Remote MCP Server Integration:** Configure `opencode-vm.orb.local:4096` as a registered execution tool endpoint in Hermes.
* **Daemon Configuration (systemd):**
  * Create a systemd service (`hermes-webui.service`) running:
    ```bash
    hermes webui --host 0.0.0.0 --port 8333
    ```
  * Ensure port 8333 is bound so it forwards natively to `http://localhost:8333` on the host Mac Studio.

---

## 4. Expected Deliverables for OpenCode

OpenCode should generate the following directory structure and files based on this PRD:

```text
ansible-agent-infrastructure/
├── inventory.ini
├── group_vars/
│   ├── all.yml
│   └── secrets.yml (encrypted or template)
├── playbook.yml
└── roles/
    ├── orbstack_init/
    │   └── tasks/main.yml
    ├── opencode_node/
    │   ├── tasks/main.yml
    │   └── templates/opencode-server.service.j2
    └── hermes_node/
        ├── tasks/main.yml
        └── templates/hermes-webui.service.j2
```

---

## 5. Execution Prompt for OpenCode

Save this file as `PRD-Ansible-Infrastructure.md` and run the following command in OpenCode:

> *"Read `PRD-Ansible-Infrastructure.md`. Based on the specification, construct a complete Ansible repository containing `inventory.ini`, `playbook.yml`, and the required roles (`orbstack_init`, `opencode_node`, and `hermes_node`). Make sure systemd service templates use system-level standard configuration paths, set up correct environment variables for API keys, and handle VirtioFS path mapping automatically."*