"""Run 5x1's PM script on the robot over SSH, the same way BEep does (BEep/Conversion.swift).

PM runs detached on the robot with its output in /run/5x1-pm.log, so it finishes even if the
connection drops; connecting again only follows the log.
"""
import re
import time

USER = "root"
PASSWORD = "jibo"  # int-developer Jibo's root password

# OOBE robots get BEach's OOBE PM, everything else scripts.5x1.com/pm. No single quotes: it runs inside sh -c '...'.
SCRIPT = ("if [ -f /var/jibo/5x1-pm-oobe-state.json ] || [ ! -s /var/jibo/credentials.json ] || grep -q oobe /var/jibo/mode.json; "
          "then echo \"This Jibo was never set up (OOBE): running the OOBE script.\" && mount -o remount,rw / && "
          "mount -o remount,rw /usr/local && curl -fsSL -k https://raw.githubusercontent.com/Jibo-Revival-Group/BEach/master/PM/post-oobe-mod.sh "
          "-o /run/5x1-pm.sh && sh /run/5x1-pm.sh; "
          "else jibo-mount --rw && curl -fsSL -k https://scripts.5x1.com/pm -o /run/5x1-pm.sh && sh /run/5x1-pm.sh; fi")

CONVERTED, UPDATING, FAILED = "converted", "updating", "failed"


def command(pm=SCRIPT, run="/run"):
    """The shell command BEetle runs on the robot. Tests swap in a harmless `pm` and a temp `run`."""
    return ("L={run}/5x1-pm.log\n"
            "if [ ! -f {run}/5x1-pm.started ]; then\n"
            "  touch {run}/5x1-pm.started\n"
            "  sh -c 'trap \"\" HUP; ({pm}); echo \"5X1_PM_EXIT $?\"; rm -f {run}/5x1-pm.started' </dev/null >$L 2>&1 &\n"
            "  sleep 1\n"
            "fi\n"
            "exec tail -n +1 -f $L\n").format(run=run, pm=pm)


def outcome(line):
    """What a line of PM output means: (CONVERTED|UPDATING|FAILED, detail) or None."""
    if "run this script again to install BEam and BEnch" in line:
        return UPDATING, ""
    if "Rebooting now" in line:
        return CONVERTED, ""
    if line.startswith("5X1_PM_EXIT "):
        code = line[len("5X1_PM_EXIT "):].strip()
        if code == "0":
            return CONVERTED, ""
        return FAILED, "The 5x1 script stopped with an error (exit {}). Its output is above.".format(code)
    return None


def valid_host(host):
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]+", host or ""))


def connect(host, port=22, password=PASSWORD, wait=180, cancelled=lambda: False, status=print):
    """Log in as root, retrying while Jibo finishes starting up."""
    import paramiko
    deadline = time.monotonic() + wait
    while True:
        client = paramiko.SSHClient()
        # A freshly modded robot has a host key we have never seen; the user just typed its IP.
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(host, port=port, username=USER, password=password, look_for_keys=False,
                           allow_agent=False, timeout=10, banner_timeout=20, auth_timeout=20)
            return client
        except paramiko.AuthenticationException:
            client.close()
            raise RuntimeError("Jibo refused the login. Make sure this is the IP of the Jibo you just modded.")
        except Exception as exc:
            client.close()
            if cancelled() or time.monotonic() > deadline:
                raise RuntimeError("Could not reach Jibo at {} ({}). Check the IP on his screen and that "
                                   "this computer is on the same Wi-Fi.".format(host, exc))
            status("Waiting for Jibo at {}…".format(host))
            time.sleep(5)


def run_pm(host, output, port=22, password=PASSWORD, pm=SCRIPT, run="/run", cancelled=lambda: False,
           status=print, wait=180):
    """Start (or rejoin) PM and stream its output to `output(text)`. Returns (result, detail)."""
    client = connect(host, port, password, wait, cancelled, status)
    try:
        channel = client.get_transport().open_session(timeout=20)
        channel.get_pty(term="xterm")  # PM calls `clear`
        channel.exec_command(command(pm, run))
        pending, result = "", None
        while True:
            if channel.recv_ready():
                text = channel.recv(32768).decode("utf-8", "replace").replace("\r\n", "\n")
                output(text)
                pending += text
                *lines, pending = pending.split("\n")
                for line in lines:
                    seen = outcome(line)
                    # "Updating" stays even if PM later exits 0 (BEep does the same).
                    if seen and not (result and result[0] == UPDATING):
                        result = seen
                    if line.startswith("5X1_PM_EXIT "):
                        return result
            elif channel.exit_status_ready() or channel.closed or cancelled():
                break
            else:
                time.sleep(0.05)
        # PM reboots Jibo after "Rebooting now", which can drop the connection first.
        return result or (FAILED, "Lost the connection to Jibo before the 5x1 script finished. "
                                  "Click Run again to keep following it.")
    finally:
        client.close()
