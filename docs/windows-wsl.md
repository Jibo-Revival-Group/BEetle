# Legacy Windows/WSL launcher

Use an x64 Windows PC with WSL 2 and Ubuntu. For a first-time setup, open **PowerShell as Administrator** and install WSL with Ubuntu 22.04 LTS:

```powershell
wsl --install -d Ubuntu-22.04
```

Restart Windows if prompted, then open **Ubuntu 22.04** once to create its Linux username and password. In PowerShell, update WSL and check that Ubuntu shows `VERSION 2`:

```powershell
wsl --update
wsl --list --verbose
```

If Ubuntu shows `VERSION 1`, run `wsl --set-version Ubuntu-22.04 2`. Install [usbipd-win](https://github.com/dorssel/usbipd-win) from PowerShell with Windows Package Manager, then reopen PowerShell so `usbipd` is on your path:

```powershell
winget install --interactive --exact dorssel.usbipd-win
usbipd list
```

If `winget` is unavailable, install the `.msi` from the [usbipd-win releases](https://github.com/dorssel/usbipd-win/releases). [Microsoft's WSL instructions](https://learn.microsoft.com/windows/wsl/install), [Ubuntu's WSL guide](https://ubuntu.com/wsl/docs/latest/howto/install-ubuntu-wsl2/), and [Microsoft's USB connection guide](https://learn.microsoft.com/windows/wsl/connect-usb) cover the setup and USB prerequisites.

Open PowerShell in the downloaded or cloned toolkit folder and run:

```powershell
.\run-wsl.ps1 -Gui -Distro Ubuntu-22.04
```

The launcher selects that WSL 2 distribution, shares and attaches a connected Jibo USB device, then runs `run.sh --gui` inside WSL. WSLg must be available to display the window; if it is missing, run `wsl --update` and `wsl --shutdown`, then reopen the launcher. The robot can change from APX (`0955:7740`) to DFU (`0955:701a`); the launcher watches both USB identities while the menu is open. Sharing a new USB identity may show a Windows administrator prompt. Run `.\run-wsl.ps1 -Gui -Distro Ubuntu-22.04 -ManualUsb` if you prefer to attach from another PowerShell window with `usbipd bind --busid <BUSID>` (administrator) and `usbipd attach --wsl --busid <BUSID>`. The Linux `./run.sh --gui` also works directly inside WSL with manual USB attachment and WSLg. If PowerShell's script policy blocks the launcher, use `powershell -NoProfile -ExecutionPolicy Bypass -File .\run-wsl.ps1 -Gui -Distro Ubuntu-22.04` for that invocation.


This is an opt-in legacy path. The ordinary Windows EXE and run.ps1 now use the native backend.
