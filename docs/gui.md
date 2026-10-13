# Graphical Jibo DFU Toolkit

The Tkinter/ttk window is the **recommended entry point** in the README and
a view of the existing guided toolkit. The launch behavior is unchanged:
`run.sh` and `run.ps1` without a GUI flag still open the original text menu.
No drawing or image of Jibo is used. The GUI does not add another flashing
implementation or bypass the backend's validation, backups or confirmations.

## Launch

Keep the launchers in the toolkit folder. First launch may build the existing
ShofEL helper/package and ask for administrator authorization. This is host
setup, not permission to flash a robot: device writes have a separate review.

| Platform | Double-click entry | Terminal equivalent |
| --- | --- | --- |
| Linux x86_64 | `Jibo DFU Toolkit.desktop` | `./run.sh --gui` |
| Windows x64 with WSL 2 + WSLg | `run-gui.cmd` | `.\run.ps1 -Gui -Distro Ubuntu-22.04` |
| macOS Intel / Apple silicon | `Jibo DFU Toolkit.command` | `./run.sh --gui` |

- **Linux:** the desktop file locates the adjacent `run-gui.sh` using its own
  path, including folders with spaces. It requests a terminal for `sudo`,
  initial-build output and fallback messages. Some file managers require
  **Allow Launching**, **Trust**, or executable permission; copying it away
  from the toolkit is not supported. `./run-gui.sh` is also available.
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
write review and backup progress screens. The optional
[Phoenix connection path](phoenix-nudge.md) has companion screenshots and its
exact wording documented separately.

The sidebar continuously checks the USB connection while idle. Its four-item
**USB FLOW** is the only numbered USB sequence; the state card is labelled
**USB READINESS** rather than repeating the TUI's separate three-step count.
RCM/APX and DFU are distinct; partition operations require the toolkit loader
marker and `var` alternate. Multiple robots, missing/incomplete loader, access
errors and failed enumeration disable unsafe actions. A failed check does not
keep previously ready actions enabled. **Refresh USB**, F5 or Ctrl+R retries.

Available operations use `jibo_tui.execute_action()` and the original
`jibo_dfu` / `jibo_images` implementations:

- **Enter DFU with ShofEL:** review the Meerkat Rev02 RAM-slot warning and
  explicitly approve starting the RAM loader. This step does not write eMMC.
- **Mode / Wi-Fi:** normal, developer, int-developer and OOBE, protected or
  open networks, repeated hidden password entry, quick file editing where
  supported, and the same explicit slower full-var fallback.
- **Set mode and configure Wi-Fi:** developer modes show a checked-by-default
  **Show Wi-Fi status and IP on the boot screen** checkbox. Checked maps to
  the existing `install` choice; unchecked maps to `keep` (leave unchanged),
  **not removal**. The separate Remove button maps to `remove`. Install and
  removal use the existing 500 MiB full-var transaction with rollback and
  SHA-256 readback; the exact shared review still precedes writing.
- **Save/check var backup:** reuse the backend's verified robot-specific
  baseline, show transfer progress and the resulting path.
- **Official update:** select from the toolkit folder's `updates` directory,
  choose preserve / fresh / fresh with this robot's calibration, and review
  the original full-flash plan. Like the TUI, the default checks DFU transfer
  completion, **not full update readback**. For the CLI's optional
  `--verify-readback` or resume path, use the documented CLI; these extra
  scripting options are not added to the guided GUI.
- **More tools:** partition-layout check, selected-partition backup/restore,
  writing an edited var image, inspecting/editing local backups, and
  **Remove boot-screen Wi-Fi/IP status**. To restore only var from a backup
  set, choose the manifest/folder and select only var. To write a standalone
  var image, use **Write an edited var image**; the backend still validates
  its size and image before the write review.

Radio choices use Up/Down and Enter; partition checklists use Up/Down, Space,
A (select all), N (clear), then Enter. Tab reaches buttons and text fields.
Esc cancels the open question. Image/manifest inputs include file/folder
pickers. Review text and long logs are scrollable and selectable/copyable.

## Safety and threading contract

`jibo_gui_core.py` loads a **private copy** of `jibo_tui` and adapts only its
four prompt primitives. The normal TUI module is not modified. Reviews,
Cancel/Confirm choices, full-var fallback warnings, backend confirmation
callbacks, GPT/identity/hash/size checks and result semantics stay shared.
The GUI omits the menu's “quick edit” capability suffix from visible titles
because boot-status or fallback operations can use full-var instead.

- Cancel is focused by default. Enter on initial focus cancels; there is no
  “yes” default, implicit approval, auto-confirm or timer that approves.
- Confirm is disabled for 700 ms on each review to stop a carried double-click
  from the previous page. It then becomes available but still needs an
  explicit click or focused keyboard invocation. The footer explains this.
- Only one action runs at a time. Duplicate starts are refused immediately,
  including while a question is open. Actions and USB probes share a lock;
  stale probe results cannot overwrite a running action's state.
- Tk runs only on the main thread. Backend work runs on a non-daemon worker
  and sends prompt/output/result events through a queue. Stdout/stderr
  progress becomes a stage label, numeric progress when available, and a
  bounded operation log; percentage is for the current backend stage.
- Closing during a transfer is refused. Closing at an unanswered question
  asks **Cancel and quit?**, with No as the default. Shutdown checks under
  the controller lock that the prompt is still unanswered: a recently
  approved prompt cannot be mistaken for a cancellable question.
- No interrupt button is provided for an active write. Wait for completion;
  forcibly killing Python or removing USB can still interrupt a transfer.
- Password inputs are masked, not added to review/log output, and cleared
  when submitted or cancelled. This is not a claim of cryptographic memory
  erasure in Python/Tk. Synthetic test passwords are used in verification.

## Verification report

**Scope:** local automated verification used Linux and an isolated device
boundary. The owner has also tested the GUI, USB handoff and real write flows
successfully on Windows and Linux.

### Verified locally

Recorded on 2026-10-12 UTC from clean revision
`51a6bf176430e9b085bce7c87f4cd52634192921` (the subsequent report commit changes
only this document). Python 3.10 and the test-only Tk 8.6.12 overlay were used.

| Lane / command | Real execution result |
| --- | --- |
| Baseline before completion: `python3 -m pytest -q` | **273 passed, 47 subtests passed** |
| Final headless suite: `python3 -m pytest -q` | **346 passed, 13 intentionally skipped, 47 subtests passed** |
| Final real-window suite: `JIBO_GUI_TEST_DISPLAY=1 xvfb-run -a python3 -m pytest -q` | **359 passed, 47 subtests passed**, no skips |
| Original unittest lane: `python3 -m unittest discover -s tests -q` | **273 tests, OK** |
| GUI-specific test collection | **86 cases**: 61 headless controller, 12 launcher/package, 13 actual Tk window cases |
| Source real-window walkthrough: `scripts/gui_smoke.py` | **103 screenshots, 459 checks, 0 Tk callback errors** |
| Same walkthrough using modules extracted from a test `.pyz` | **103 screenshots, 459 checks, 0 Tk callback errors** |
| Existing Node renderer/OTA tests, five invocations | **92 passed**: 8 OTA helper, 28 current X11, 28 early X11, 20 DOM display, 8 DOM source |
| `bash -n` on all four shell entries; `desktop-file-validate` | Exit **0** |

The two final walkthrough lanes produced **206 screenshots and 918 checks**
in total. Each walkthrough exercised real Tk widgets, a real worker thread,
Cancel/Confirm and password flows, numeric progress, fallback/errors, local
mode/Wi-Fi edits, selected-var backup/restore, all update policies, boot-status
removal, 920×640 scrollable review, actual file/manifest/folder dialogs, and
native close-warning/default-No quit dialogs. Each lane recorded 20 fake
backend calls and 10 approved **simulated** device-write operations; these
are not hardware writes.

Evidence paths (local, ephemeral `/dev/shm`, not committed):

- `/dev/shm/dfu-gui-shots/receipt.json` and the 103 named source screenshots
  directly beside it; `sheet-00.png` through `sheet-12.png` are contact sheets.
- `/dev/shm/dfu-gui-shots/packaged/receipt.json` and its 103 screenshots.
  Receipts identify the actual imported GUI/controller/TUI file paths and
  include screenshot hashes, checks and `dirty: false`.
- `pytest-headless.xml`, `pytest-xvfb.xml`, `unittest.log`, `node-results.json`
  and the five `node-*.log` files under `/dev/shm/dfu-gui-shots/`.
- `/dev/shm/dfu-gui-package/artifact.json`, `fake-inputs.pyz` and `runtime/`.
  All **14 checked runtime source/asset files** extracted from that archive
  matched the checkout byte-for-byte. Both GUI modules and the private TUI
  source were imported from the extracted directory during the packaged lane.
  **The archive uses synthetic test loader/tool inputs and test loader pins;
  it is not a flashable or distributable production package.** This proves
  GUI inclusion/extraction/runtime behavior, not a native-tools release build.
- An earlier exploratory `expanded-preview/` receipt is marked dirty and is
  not counted or cited as final evidence.

The source screenshots were visually reviewed across the contact sheets,
with full-size review and native modal checks. No major clipping or overlap
was found, including the minimum-size review footer, scrollbar and both
buttons. The visible boot checkbox was checked by default; the armed review
showed an enabled red Confirm button. Initial pale Confirm is intentional,
not a disabled-workflow bug.

### Defects found and proved fixed

Real-window tests initially exposed Tk `Tcl_Obj` conversion errors in label
wrapping, the missing boot-status checkbox and missing checklist keyboard
navigation. Later named failing tests exposed an approval-to-close race,
stale enabled actions after USB enumeration failure, and misleading “quick
edit” titles on full-var operations. Desktop validation caught missing `$`
escaping in the Linux entry. These were fixed and the real lanes rerun.
No backend device-operation code, `jibo_tui.py`, `jibo_images.py` or pinned
boot assets were changed by the GUI completion work.

Two independent negative controls also ran on disposable **fake-only** copies
of the controller, leaving the repository untouched:

- Removing the busy guard made
  `test_duplicate_start_and_refresh_refused_until_action_finishes` fail:
  **1 failed**, expected exit 1.
- Forcing review approval made
  `test_mode_write_requires_explicit_confirm` fail for rejected answers:
  **8 failed, 2 passed**, expected exit 1. The two explicit-confirm cases
  continued to pass, distinguishing approval from mere backend invocation.

Actual outputs are in `falsification.json`, `falsify-duplicate-start.log` and
`falsify-explicit-approval.log` under the screenshot directory. The unmodified
controller's corresponding tests pass.

### Environment issue, not a product test result

Invoking this host's standalone `pytest` executable initially omitted the
checkout from its import path and caused collection errors. Using
`python3 -m pytest` resolved that; no dependency installation or fabricated
results were substituted. System Python has no installed Tk, so the already
available extracted overlay was reused. There is no PowerShell runtime on
this host: the Windows launcher received structural assertions only, not a
PowerShell execution claim.

### Reproduce the fake lanes

From the toolkit root, with Python 3.10+ and pytest installed:

```sh
python3 -m pytest -q
# Opt-in actual Tk widgets (not a display mock):
JIBO_GUI_TEST_DISPLAY=1 xvfb-run -a python3 -m pytest -q
# Real-window walkthrough using only tests/gui_fakes.py:
xvfb-run -a -s '-screen 0 1400x1000x24' \
  python3 scripts/gui_smoke.py --out /dev/shm/dfu-gui-shots
bash -n run.sh run-macos.sh run-gui.sh 'Jibo DFU Toolkit.command'
desktop-file-validate 'Jibo DFU Toolkit.desktop'
```

Normal headless test runs intentionally skip the real-window tests unless
`JIBO_GUI_TEST_DISPLAY=1` is set. The Tk smoke requires ImageMagick's `import`
for X-window captures. On this host the system Python lacks installed Tk;
verification uses the **pre-existing extracted test-only overlay** by sourcing
`/dev/shm/dfu-gui-tk/env.sh`. Those files are not repository content, install
prerequisites, or distributed toolkit artifacts.

### Owner-tested platforms

The owner has tested the GUI, USB handoff and real write flows successfully
on Windows and Linux.

### Open acceptance gates

- **macOS Intel / Apple silicon:** experimental; not yet tested.
- **Hardware/firmware:** no new evidence for RAM slot 3, boot-status release
  compatibility on real robots, services-OTA overlay timing, calibration
  preservation or interrupted-flash recovery. Keep all existing README
  hardware caveats and gates in force.
