"""Direct Windows GUI/CLI entry point. No WSL, VM, distro or feature setup."""
from contextlib import redirect_stderr, redirect_stdout
import json
import os
from pathlib import Path
import sys


def runtime_path():
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / 'runtime'
    return Path(__file__).resolve().parents[2] / '.build/release-windows-native/runtime'


def show_console():
    if sys.platform != 'win32':
        return
    import ctypes
    kernel = ctypes.windll.kernel32
    if not kernel.AttachConsole(-1):
        kernel.AllocConsole()
    for name, file, mode in (('stdin','CONIN$','r'),('stdout','CONOUT$','w'),('stderr','CONOUT$','w')):
        if getattr(sys, name) is None:
            setattr(sys, name, open(file, mode, buffering=1))


def _main(arguments):
    runtime = runtime_path()
    if not (runtime / 'release-manifest.json').is_file():
        raise RuntimeError('The native Windows bundle is not built. Download BEetle-Windows-x64.exe '
                           'from the native-bundles workflow, or build it with --windows-native.')
    receipt = json.loads((runtime / 'release-manifest.json').read_text())
    print('BEetle (build ' + receipt['revision'][:7] + ')', flush=True)
    if arguments == ['--version']:
        print('BEetle Windows x64 — native GUI and USB; no WSL or virtualization')
        return 0
    sys.path.insert(0, str(runtime))
    from manifest import verify_manifest
    verify_manifest(runtime)
    if arguments == ['--driver-help']:
        from jibo_windows import show_driver_help
        show_driver_help(runtime)
        return 0
    if arguments and arguments[0] not in ('gui','--gui','--self-check','--gui-smoke','--filesystem-smoke'):
        show_console()
    import native_launcher
    return native_launcher.main(runtime=runtime, arguments=arguments or ['gui'])


def main():
    args = sys.argv[1:]
    output = None
    if args and '--output' in args and args[0] in ('--version','--self-check','--gui-smoke','--filesystem-smoke'):
        index = args.index('--output')
        if index + 1 >= len(args):
            raise RuntimeError('--output requires a filename')
        output = Path(args[index + 1])
        del args[index:index + 2]
    if output is None and args and args[0] not in ('gui','--gui','--driver-help','--self-check','--gui-smoke','--filesystem-smoke'):
        show_console()
    # A windowed PyInstaller program has no stdout/stderr by default.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, 'w')
    if sys.stderr is None:
        sys.stderr = open(os.devnull, 'w')
    def invoke():
        try:
            return _main(args)
        except Exception as exc:
            message = 'BEetle could not start: ' + str(exc)
            print(message, file=sys.stderr, flush=True)
            if output is None and sys.platform == 'win32':
                import ctypes
                ctypes.windll.user32.MessageBoxW(None, message, 'BEetle', 0x10)
            return 1
    if output is not None:
        with output.open('w', encoding='utf-8') as stream, redirect_stdout(stream), redirect_stderr(stream):
            return invoke()
    return invoke()


if __name__ == '__main__':
    raise SystemExit(main())
