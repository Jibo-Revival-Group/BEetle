"""Windows-only USB driver guidance. Invoked explicitly from the Help menu."""
import os
from pathlib import Path

DRIVER_GUIDE = (
    'BEetle runs directly on Windows. WSL and virtualization are not needed.\n\n'
    'For first-time USB access, use the included Zadig utility. In Options, choose '
    'List All Devices. Select only your Jibo:\n'
    '  RCM/APX: USB ID 0955:7740\n'
    '  RAM DFU: USB ID 0955:701a (after entering DFU)\n\n'
    'Choose libusbK, then Install/Replace Driver for each Jibo USB mode when it appears. '
    'Windows asks for administrator approval for driver installation. '
    'Do not select a different USB device.\n\n'
    'RCM needs libusbK: WinUSB limits control transfers to 4 KiB, while Jibo recovery '
    'uses a larger request. The bundled utility contains the drivers; no download is needed.'
)


def show_driver_help(runtime, parent=None, busy=False):
    from tkinter import messagebox
    if busy:
        messagebox.showwarning('USB operation in progress',
                               'Wait for the current robot operation before changing its USB driver.', parent=parent)
        return
    driver = Path(runtime) / 'tools/zadig.exe'
    if not driver.is_file():
        messagebox.showerror('USB driver utility missing',
                             'Use the complete BEetle Windows download; its driver utility is bundled.', parent=parent)
        return
    if messagebox.askyesno('Jibo USB driver setup', DRIVER_GUIDE + '\n\nOpen the included driver utility?',
                           parent=parent, default='no'):
        try:
            os.startfile(str(driver), 'runas', cwd=str(driver.parent))
        except OSError as exc:
            messagebox.showerror('Driver utility did not start', str(exc), parent=parent)


def add_driver_menu(root, controller):
    import tkinter as tk
    bar = tk.Menu(root)
    menu = tk.Menu(bar, tearoff=False)
    menu.add_command(label='Windows USB driver setup…', command=lambda: show_driver_help(
        Path(__file__).resolve().parent, parent=root, busy=controller.busy))
    bar.add_cascade(label='Help', menu=menu)
    root.configure(menu=bar)
