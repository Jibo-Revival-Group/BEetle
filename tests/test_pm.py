"""BEetle's PM step against a local SSH server that runs commands with sh (no robot)."""
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest

import paramiko

from beetle import pm


class Server(paramiko.ServerInterface):
    def check_auth_password(self, username, password):
        return paramiko.AUTH_SUCCESSFUL if (username, password) == ("root", "jibo") else paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return "password"

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED

    def check_channel_pty_request(self, *args):
        return True

    def check_channel_exec_request(self, channel, command):
        def run():
            process = subprocess.Popen(["sh", "-c", command.decode()], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.processes.append(process)
            for chunk in iter(lambda: process.stdout.read1(4096), b""):
                try:
                    channel.sendall(chunk)
                except Exception:
                    break
            channel.send_exit_status(process.wait())
            channel.close()
        threading.Thread(target=run, daemon=True).start()
        return True


def fake_jibo():
    key = paramiko.RSAKey.generate(2048)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)
    servers = []

    def accept():
        while True:
            try:
                client, _ = listener.accept()
            except OSError:
                return
            transport = paramiko.Transport(client)
            transport.add_server_key(key)
            server = Server()
            server.processes = []
            servers.append(server)
            transport.start_server(server=server)
    threading.Thread(target=accept, daemon=True).start()
    return listener, servers


class PmTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.listener, cls.servers = fake_jibo()
        cls.port = cls.listener.getsockname()[1]

    @classmethod
    def tearDownClass(cls):
        cls.listener.close()
        for server in cls.servers:
            for process in server.processes:
                process.kill()

    def setUp(self):
        self.run_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.run_dir, True)

    def run_pm(self, script):
        seen = []
        result = pm.run_pm("127.0.0.1", seen.append, port=self.port, pm=script, run=self.run_dir, wait=5)
        return result, "".join(seen)

    def test_successful_pm_streams_its_output_and_converts(self):
        result, output = self.run_pm("echo installing BEam; echo installing BEnch")
        self.assertEqual(result, (pm.CONVERTED, ""))
        self.assertIn("installing BEam\ninstalling BEnch\n5X1_PM_EXIT 0", output)
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, "5x1-pm.started")))

    def test_failing_pm_reports_its_exit_code(self):
        result, _ = self.run_pm("echo oops; exit 3")
        self.assertEqual(result[0], pm.FAILED)
        self.assertIn("exit 3", result[1])

    def test_system_update_first_asks_for_a_second_run(self):
        result, _ = self.run_pm("echo Restart Jibo, then run this script again to install BEam and BEnch.; exit 0")
        self.assertEqual(result, (pm.UPDATING, ""))

    def test_reconnecting_follows_the_running_pm_instead_of_starting_another(self):
        marker = os.path.join(self.run_dir, "runs")
        script = "echo run >> {}; sleep 2; echo finished".format(marker)
        first = threading.Thread(target=self.run_pm, args=(script,))
        first.start()
        threading.Event().wait(1)
        result, output = self.run_pm(script)
        first.join()
        self.assertEqual(result, (pm.CONVERTED, ""))
        self.assertIn("finished", output)
        with open(marker) as runs:
            self.assertEqual(runs.read(), "run\n")

    def test_wrong_password_is_reported(self):
        with self.assertRaises(RuntimeError):
            pm.run_pm("127.0.0.1", print, port=self.port, password="nope", pm="true", run=self.run_dir, wait=5)

    def test_robot_script_has_no_single_quotes(self):
        self.assertNotIn("'", pm.SCRIPT)


if __name__ == "__main__":
    unittest.main()
