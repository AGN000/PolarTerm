# PolarTerm — HPC Terminal & File Manager (Linux + Windows)

A MobaXterm alternative for **Linux + Windows**: **Tabbed SSH terminal + SFTP file transfer GUI + HPC friendly** with penguin easter eggs.

Built with **Python + PyQt6 + Paramiko**. Works on Ubuntu 22.04/24.04, Fedora, Arch **and Windows 10/11**.

## Features

- **Tabbed SSH terminal** — **Two modes:** (1) **Native embedded xterm** (Linux X11, `xterm -into <WID>` - 100% like `gnome-terminal`, vim/htop/tmux/fonts/backspace perfect) and (2) **Emulated pyte** (cross-platform, `pyte` VT100 + fallback). Toggle via `View → Native Terminal`.
- **SFTP File Manager** — dual-pane (Local ↔ Remote), upload/download with progress, mkdir/rename/delete, dir navigation.
- **Session Manager** — save hosts, ports, users, password/key auth, jump/bastion host, remote/local start paths.
- **HPC Ready** — jump host support, quick bar for `squeue`, `qstat`, `sinfo`, `module avail`, etc.
- **Local Terminal** — open bash tabs alongside remote sessions (native or emulated).

## Install (Linux)

**Recommended — use venv (isolates from system packages like `metadrive`):**
```bash
git clone https://github.com/AGN000/PolarTerm.git
cd PolarTerm
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python3 main.py
# later: ./launch.sh  # auto-uses venv if present
```

**Direct install (if you have no conflicting packages):**
```bash
pip install -r requirements.txt
# or: pip install PyQt6 paramiko cryptography
python3 main.py
```

Requires Python 3.9+.

> **Seen this error?** `ERROR: pip's dependency resolver does not currently take into account all the packages that are installed... metadrive 1.4.35 requires aiofiles==0.4.0...`
> 
> This is **not** a PolarTerm bug. You have `metadrive` (or similar) with very old strict pins (`paramiko==2.10.1`, `aiofiles==0.4.0`, etc.) installed in your global environment. PolarTerm needs `paramiko>=3.0` and `cryptography>=3.0`. Fix:
> ```bash
> # Option A: isolate with venv (recommended above)
> python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt
>
> # Option B: install missing dep that metadrive wants (silences warning but not the pin conflicts)
> pip install "aiofiles==0.4.0" cryptography
>
> # Option C: ignore resolver warning — PolarTerm still works; the conflicts are metadrive's old pins
> pip install --no-deps -r requirements.txt  # if you know what you're doing
> ```
> `pip check` will keep warning about `metadrive`'s old pins until you update/uninstall it — that's expected.

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

## Auth & Credentials

- **Password** — saved **encrypted with Fernet** if you tick **"Save password"** (default ON, 0600 perms in `~/.config/polarterm/.key`). If you enter a password but leave Save unchecked, you'll see a warning and it won't be stored (you'll be prompted each time).
- **Key** — select private key file; handles RSA/Ed25519/ECDSA; passphrase optional (also encrypted if Save ticked).
- **Agent** — also tries `ssh-agent` keys automatically.

If credentials appear "not saving", ensure **Save password** is ticked in the New/Edit dialog. Check `~/.config/polarterm/sessions.json` — passwords are stored as `enc:...` when saved.

## Jump Host

Format: `host`, `user@host`, `host:port`, `user@host:port`. Connects via Paramiko `direct-tcpip`.

## Screenshots (concept)

- Left: session list; Right tabs: Terminal (dark) + SFTP dual pane; Bottom: progress bar.

## Troubleshooting

- `Connection Failed` (e.g. HPC `10.21.1.16:2222`) → check host/port/user, auth, VPN, firewall, jump host. **HPC fix (v1.0.1+)**: timeout increased to 20s (`banner_timeout`/`auth_timeout`) for slow HPC banners; ensure Save ticked so password is actually stored (see Auth & Credentials). Test manually: `ssh -p 2222 user@host` first.
- `Dark theme mid portion not working / white blank` → fixed in v1.0.1: UI now auto-detects GNOME dark mode and paints central `QTabWidget` pane dark (`#1e1e22`) instead of hard-coded white. Toggle via **View → 🌙 Dark Mode** and **View → Reload Theme**, or set `POLARTERM_DARK=1`. Restart after OS theme change.
- `Terminal very poor / backspace not deleting / fonts` → fixed in v1.0.2: (1) **Fonts:** `QFontDatabase` fallback chain (`JetBrains Mono/Fira Code/Cascadia/DejaVu/Ubuntu/Consolas`) + `PreferAntialias` + zoom `Ctrl+/-`. (2) **Backspace:** now server-driven `0x7f` (no local double-delete) + proper `pyte` `HistoryScreen` handling `BS/CR/CUB/CUF/ED/EL`. (3) **Native embedded:** `View → Native Terminal` embeds real `xterm` via X11 `-into` (100% Linux: `vim/htop/tmux` perfect). Requires `sudo apt install xterm` [ + `sshpass` for auto-login ]. Fallback pyte works on any system. Toggle via `View → Native Terminal` or `POLARTERM_NATIVE=0`. See `View → Terminal Info`.
- Key fails → ensure `chmod 600 ~/.ssh/id_rsa` and correct passphrase; try `ssh -i key user@host` first.
- SFTP empty → click Refresh or check Remote Path `~` resolves.
- `pip dependency resolver` error with `metadrive` → see Install (Linux) note — use `venv` to isolate; `metadrive 1.4.35` pins old `paramiko==2.10.1` etc.

## Roadmap

- Drag & drop, recursive folder transfer, X11 forwarding, SCP, persistent log.

## License

MIT
