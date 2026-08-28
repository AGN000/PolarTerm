# PolarTerm — HPC Terminal & File Manager (Linux + Windows)

A MobaXterm alternative for **Linux + Windows**: **Tabbed SSH terminal + SFTP file transfer GUI + HPC friendly** with penguin easter eggs.

Built with **Python + PyQt6 + Paramiko**. Works on Ubuntu 22.04/24.04, Fedora, Arch **and Windows 10/11**.

## Features

- **Tabbed SSH terminal** — interactive shell (xterm-256color), ANSI handling, copy/paste, Ctrl-C/L, resize.
- **SFTP File Manager** — dual-pane (Local ↔ Remote), upload/download with progress, mkdir/rename/delete, dir navigation.
- **Session Manager** — save hosts, ports, users, password/key auth, jump/bastion host, remote/local start paths.
- **HPC Ready** — jump host support, quick bar for `squeue`, `qstat`, `sinfo`, `module avail`, etc.
- **Local Terminal** — open bash tabs alongside remote sessions.

## Install (Linux)

```bash
git clone https://github.com/AGN000/PolarTerm.git
cd PolarTerm
pip install -r requirements.txt
# or: pip install PyQt6 paramiko
python3 main.py
```

Requires Python 3.9+.

### Desktop Launcher (Ubuntu)

```bash
chmod +x main.py
./install_desktop.sh   # creates ~/.local/share/applications/polarterm.desktop
```

Then find "PolarTerm" in app grid.

## Install (Windows) — Exe

**Option 1: Download exe (easy)**
1. Go to **Releases** → https://github.com/AGN000/PolarTerm/releases
2. Download `PolarTerm.exe` (or `PolarTerm-Setup-1.0.exe` installer)
3. Double-click to run — no Python needed.

**Option 2: Build exe yourself on Windows**

```bat
REM In Windows CMD or PowerShell, in PolarTerm folder:
pip install -r requirements.txt
pip install pyinstaller pillow

REM Quick build (onefile):
pyinstaller --noconfirm --clean --windowed --onefile --icon=resources/polarterm.ico --name=PolarTerm --add-data "resources/polarterm.png;resources" --add-data "resources/polarterm.ico;resources" main.py
REM Result: dist\PolarTerm.exe

REM Or use spec:
pyinstaller PolarTerm.spec

REM Or just double-click:
build_windows.bat
REM PowerShell:
.\build_windows.ps1
```

For installer (Start Menu + Desktop shortcut):
```bat
REM Install Inno Setup from https://jrsoftware.org/isinfo.php
iscc installer.iss
REM Result: installer\PolarTerm-Setup-1.0.exe
```

Config on Windows: `%APPDATA%\polarterm\sessions.json` (or `%TEMP%\polarterm.log`), portable.

## Usage

1. Click **＋ New** → fill Name, Host, Username, Auth (password or `~/.ssh/id_rsa`).
2. Optional: set **Remote Initial Path** (e.g. `/scratch/$USER` for HPC), **Jump Host** (e.g. `user@bastion.iitb.ac.in:22`).
3. Double-click session → opens **Terminal** + **Files** tabs.
4. File Transfer: select file → **Upload →→** or **←← Download** (or right-click).
5. HPC Quick Bar → type/select command → **Send to Active Terminal**.

Config stored at `~/.config/polarterm/sessions.json` (plain JSON; passwords only if you tick “Save”).

## Auth

- **Password** — optionally saved (plain text, like PolarTerm). Leave unticked to prompt each time.
- **Key** — select private key file; handles RSA/Ed25519/ECDSA; passphrase optional.
- **Agent** — also tries `ssh-agent` keys automatically.

## Jump Host

Format: `host`, `user@host`, `host:port`, `user@host:port`. Connects via Paramiko `direct-tcpip`.

## Screenshots (concept)

- Left: session list; Right tabs: Terminal (dark) + SFTP dual pane; Bottom: progress bar.

## Troubleshooting

- `Connection Failed` → check host/port/user, auth, VPN, firewall, jump host.
- Key fails → ensure `chmod 600 ~/.ssh/id_rsa` and correct passphrase; try `ssh -i key user@host` first.
- SFTP empty → click Refresh or check Remote Path `~` resolves.

## Roadmap

- Drag & drop, recursive folder transfer, X11 forwarding, SCP, persistent log.

## License

MIT
