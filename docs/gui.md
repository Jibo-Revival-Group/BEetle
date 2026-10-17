# Graphical BEetle

The Tkinter/ttk window is the **recommended entry point** in the README and
opens the guided setup wizard, with **Advanced recovery tools** available from
the welcome page. The terminal launch behavior is unchanged:
`run.sh` and `run.ps1` without a GUI flag still open the original text menu.
The existing 5x1 logo and dark green palette identify the fork. The GUI does not add another flashing
implementation or bypass the backend's validation, backups or confirmations.

## Launch

Keep the launchers in the toolkit folder. First launch may build the existing
ShofEL helper/package and ask for administrator authorization. This is host
setup, not permission to flash a robot: device writes have a separate review.

| Platform | Double-click entry | Terminal equivalent |
| --- | --- | --- |
| Linux x86_64 | `BEetle.desktop` | `./run.sh --gui` |
| Windows x64 with WSL 2 + WSLg | `run-gui.cmd` | `.\run.ps1 -Gui -Distro Ubuntu-22.04` |
| macOS Intel / Apple silicon | `BEetle.command` | `./run.sh --gui` |

- **Linux:** the desktop file locates the adjacent `run-gui.sh` using its own
  path, including folders with spaces. It requests a terminal for `sudo`,
  initial-build output and fallback messages. Some file managers require
  **Allow Launching**, **Trust**, or executable permission; copying it away
  from the toolkit is not supported. From a terminal, `./BEetle.desktop`
  and `./run-gui.sh` both launch the GUI.
- **Windows:** this uses the same WSL 2 / usbipd USB handoff as the TUI, not a
  native Windows DFU driver. WSLg displays the Linux Tk window on Windows.
  Install WSL/Ubuntu and usbipd-win as described in the README. Run
  `wsl --update`, then `wsl --shutdown` if WSLg is unavailable. The `.cmd`
  wrapper uses a process-local PowerShell execution-policy override, never a
  machine-wide policy change. Extra switches such as `-Distro` and `-ManualUsb`
  can be supplied when invoked from a terminal.
- **macOS:** keep native Python, libusb, dfu-util and e2fsprogs installed as
  described in `docs/macos.md`. Install the Tk package matching your Python,
  e.g. `brew install python-tk@3.12` for Python 3.12, or the matching
  MacPorts `py312-tkinter` port. Finder may require **Open** or permission to
  launch a downloaded shell script. The entry opens Terminal; it is not a
  signed/notarized `.app`. No macOS `sudo` is added.
- **Missing Tk/display:** the Python GUI entry prints platform-specific fixes
  and opens the unchanged text menu only if an interactive terminal exists.
  With no terminal it exits with code 2 rather than hanging. Linux's launcher
  attempts to install its Tk dependency through the existing supported host
  package-manager path. GUI `sudo` preserves only the desktop variables
  `DISPLAY`, `XAUTHORITY`, `WAYLAND_DISPLAY`, `XDG_RUNTIME_DIR`.
- The graphical modules are included in the Linux `.pyz`. Its cached-package
  check compares both GUI modules, so a stale GUI triggers a rebuild.
  `python3 dist/jibo-dfu-linux-x86_64.pyz gui` (or `--gui`) selects the window;
  no arguments still select the TUI. Tk remains a system Python dependency,
  not bundled native libraries in the archive.

## Screens and operations

The [README gallery](../README.md#gui-screenshots) shows the ready, mode/Wi-Fi,
write review and backup progress screens. The **Set up with 5x1** action uses the same prompts in the GUI, TUI and CLI. See [5x1 setup](setup-5x1.md).
