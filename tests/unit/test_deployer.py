import unittest
import unittest.mock
from unittest.mock import patch, MagicMock
import sys
import subprocess
import builtins

# Stub questionary in sys.modules if missing to prevent @patch('questionary.text') crashing at import time
if 'questionary' not in sys.modules:
    try:
        import questionary
    except ImportError:
        sys.modules['questionary'] = MagicMock()

from core.deployer import _require_paramiko

class TestDeployer(unittest.TestCase):

    def test_lazy_paramiko_offline_handling(self):
        """Simulate a network failure during pip install of paramiko."""
        
        # Save originals
        orig_check_output = subprocess.check_output
        orig_print = builtins.print
        orig_paramiko = sys.modules.get('paramiko')

        # Mock a CalledProcessError representing a network failure
        def mock_check_output(*args, **kwargs):
            raise subprocess.CalledProcessError(
                returncode=1,
                cmd=args[0],
                output=b"NewConnectionError: Failed to establish a new connection: [Errno -3] Temporary failure in name resolution"
            )

        subprocess.check_output = mock_check_output
        sys.modules['paramiko'] = None  # Force ImportError

        logs = []
        def mock_print(*args, **kwargs):
            logs.append(" ".join(map(str, args)))
        builtins.print = mock_print

        try:
            result = _require_paramiko()
            self.assertIsNone(result, "Should return None on installation failure")
            self.assertTrue(any("Network unreachable" in log for log in logs), "Did not detect network error")
        finally:
            # Restore originals
            subprocess.check_output = orig_check_output
            builtins.print = orig_print
            if orig_paramiko is not None:
                sys.modules['paramiko'] = orig_paramiko
            else:
                del sys.modules['paramiko']

    @unittest.mock.patch('core.deployer.platform.system', return_value="Linux")
    @unittest.mock.patch('core.deployer.os.path.exists')
    @unittest.mock.patch('questionary.text')
    @unittest.mock.patch('builtins.print')
    def test_deploy_local_validation_non_windows(self, mock_print, mock_q_text, mock_exists, mock_system):
        """Verify that Windows-style paths are blocked on native non-Windows OS."""
        mock_ask = unittest.mock.MagicMock(side_effect=["E:\\", ""])
        mock_text_instance = unittest.mock.MagicMock()
        mock_text_instance.ask = mock_ask
        mock_q_text.return_value = mock_text_instance
        
        mock_exists.return_value = False
        
        import os
        orig_environ = os.environ.copy()
        if "KACE_DOCKER" in os.environ:
            del os.environ["KACE_DOCKER"]
            
        try:
            from core.deployer import deploy_local
            deploy_local({}, artifact_type="config")
        finally:
            os.environ.clear()
            os.environ.update(orig_environ)
        
        printed_messages = [call[0][0] for call in mock_print.call_args_list]
        self.assertTrue(any("not supported on non-Windows platforms" in msg for msg in printed_messages))

    @unittest.mock.patch('core.deployer.platform.system', return_value="Linux")
    @unittest.mock.patch('core.deployer.os.path.exists')
    @unittest.mock.patch('questionary.text')
    @unittest.mock.patch('builtins.print')
    def test_deploy_local_validation_docker(self, mock_print, mock_q_text, mock_exists, mock_system):
        """Verify that Windows-style paths are blocked and direct users to /workspace inside Docker."""
        mock_ask = unittest.mock.MagicMock(side_effect=["E:\\", ""])
        mock_text_instance = unittest.mock.MagicMock()
        mock_text_instance.ask = mock_ask
        mock_q_text.return_value = mock_text_instance
        
        mock_exists.side_effect = lambda path: True if path == '/.dockerenv' else False
        
        from core.deployer import deploy_local
        deploy_local({}, artifact_type="config")
        
        printed_messages = [call[0][0] for call in mock_print.call_args_list]
        self.assertTrue(any("not accessible inside Docker" in msg for msg in printed_messages))
        self.assertTrue(any("please use /workspace" in msg for msg in printed_messages))

    @patch('core.deployer._require_paramiko')
    @patch('core.deployer.os.path.isfile')
    @patch('builtins.print')
    def test_deploy_config_missing_file(self, mock_print, mock_isfile, mock_paramiko):
        """If local printer.cfg is missing, deploy_config aborts."""
        mock_isfile.return_value = False
        mock_paramiko.return_value = MagicMock()
        
        from core.deployer import deploy_config
        deploy_config({'host': '127.0.0.1', 'user': 'pi', 'dest_path': '~/printer_data'})
        
        printed = [c[0][0] for c in mock_print.call_args_list]
        self.assertTrue(any("Deployment aborted: printer.cfg not found" in msg for msg in printed))

    @patch('core.deployer._require_paramiko')
    @patch('core.deployer.os.path.isfile')
    @patch('builtins.print')
    def test_deploy_config_ssh_exception(self, mock_print, mock_isfile, mock_paramiko_func):
        """Mock SSH connection exception, deploy_config should catch and print."""
        mock_isfile.return_value = True
        mock_paramiko = MagicMock()
        mock_paramiko_func.return_value = mock_paramiko
        
        # Mock SSH Client connect to raise an exception
        mock_client = MagicMock()
        mock_client.connect.side_effect = Exception("Connection timed out")
        mock_paramiko.SSHClient.return_value = mock_client
        
        from core.deployer import deploy_config
        deploy_config({'host': '127.0.0.1', 'user': 'pi', 'dest_path': '~/printer_data'})
        
        printed = [c[0][0] for c in mock_print.call_args_list]
        self.assertTrue(any("Deployment failed: Connection timed out" in msg for msg in printed))

    @patch('core.deployer._require_paramiko')
    @patch('core.deployer.os.path.isfile')
    @patch('core.deployer.os.path.exists')
    @patch('builtins.print')
    def test_deploy_config_sftp_success(self, mock_print, mock_exists, mock_isfile, mock_paramiko_func):
        """Test successful config & macros SSH upload."""
        import os
        mock_isfile.return_value = True
        mock_exists.side_effect = lambda path: True if "macros.cfg" in path else False
        
        mock_paramiko = MagicMock()
        mock_paramiko_func.return_value = mock_paramiko
        
        mock_client = MagicMock()
        mock_sftp = MagicMock()
        mock_client.open_sftp.return_value = mock_sftp
        mock_paramiko.SSHClient.return_value = mock_client
        
        from core.deployer import deploy_config
        deploy_config({'host': '127.0.0.1', 'user': 'pi', 'dest_path': '~/printer_data/config/printer.cfg'})
        
        mock_client.connect.assert_called_once_with('127.0.0.1', username='pi', password='')
        mock_sftp.put.assert_any_call(os.path.expanduser('~/kace/printer.cfg'), '/home/pi/printer_data/config/printer.cfg')
        mock_sftp.put.assert_any_call(os.path.expanduser('~/kace/macros.cfg'), '/home/pi/printer_data/config/macros.cfg')

    @patch('shutil.which', return_value="/usr/bin/avrdude")
    @patch('subprocess.run')
    @patch('questionary.text')
    @patch('questionary.confirm')
    @patch('builtins.print')
    def test_deploy_avrdude_success(self, mock_print, mock_confirm, mock_q_text, mock_run, mock_which):
        """Test avrdude flashing executes successfully."""
        mock_text_inst = MagicMock()
        mock_text_inst.ask.return_value = "/dev/ttyUSB0"
        mock_q_text.return_value = mock_text_inst
        
        mock_confirm_inst = MagicMock()
        mock_confirm_inst.ask.return_value = True
        mock_confirm.return_value = mock_confirm_inst
        
        from core.deployer import deploy_avrdude
        deploy_avrdude({'mcu_path': '/dev/ttyUSB0'}, 'klipper.bin', 'atmega2560')
        
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertIn("avrdude", cmd)
        self.assertIn("atmega2560", cmd)
        self.assertIn("/dev/ttyUSB0", cmd)

    @patch('shutil.which', return_value=None)
    @patch('builtins.print')
    def test_deploy_avrdude_missing_binary(self, mock_print, mock_which):
        """If avrdude is missing, it prints error."""
        from core.deployer import deploy_avrdude
        deploy_avrdude({}, 'klipper.bin', 'atmega2560')
        printed = [c[0][0] for c in mock_print.call_args_list]
        self.assertTrue(any("avrdude' is not installed" in msg for msg in printed))

    @patch('questionary.text')
    @patch('questionary.select')
    @patch('core.moonraker.check_moonraker')
    @patch('core.moonraker.upload_printer_cfg')
    @patch('core.moonraker.restart_firmware')
    @patch('builtins.print')
    def test_deploy_moonraker_success(self, mock_print, mock_restart, mock_upload, mock_check, mock_select, mock_text):
        """Test successful moonraker deploy & restart firmware."""
        # Mock connection prompts
        mock_text.side_effect = [
            MagicMock(ask=lambda: "192.168.1.50"), # host
            MagicMock(ask=lambda: "7125"),          # port
            MagicMock(ask=lambda: ""),              # api key
        ]
        mock_check.return_value = (True, "v0.1.0")
        mock_upload.return_value = (True, "Success")
        mock_select.return_value = MagicMock(ask=lambda: "firmware")
        mock_restart.return_value = (True, "Restarted")
        
        from core.deployer import deploy_moonraker
        deploy_moonraker({})
        
        mock_check.assert_called_once_with("192.168.1.50", 7125)
        mock_upload.assert_called_once()
        mock_restart.assert_called_once_with("192.168.1.50", 7125)

    @patch('questionary.text')
    @patch('core.moonraker.check_moonraker')
    @patch('questionary.confirm')
    @patch('core.deployer.deploy_config')
    @patch('builtins.print')
    def test_deploy_moonraker_unreachable_ssh_fallback(self, mock_print, mock_deploy_ssh, mock_confirm, mock_check, mock_text):
        """If Moonraker is unreachable, check SSH fallback option."""
        mock_text.side_effect = [
            MagicMock(ask=lambda: "192.168.1.50"), # host
            MagicMock(ask=lambda: "7125"),          # port
            MagicMock(ask=lambda: ""),              # api key
            MagicMock(ask=lambda: "pi"),            # SSH user
            MagicMock(ask=lambda: "/home/pi"),      # SSH dest_path
        ]
        mock_check.return_value = (False, "Timeout connection")
        mock_confirm.return_value = MagicMock(ask=lambda: True)
        
        with patch('questionary.password', return_value=MagicMock(ask=lambda: "raspberry")):
            from core.deployer import deploy_moonraker
            deploy_moonraker({})
        
        mock_deploy_ssh.assert_called_once()
        # Verify SSH user context was set
        user_data = mock_deploy_ssh.call_args[0][0]
        self.assertEqual(user_data['host'], '192.168.1.50')
        self.assertEqual(user_data['user'], 'pi')
        self.assertEqual(user_data['dest_path'], '/home/pi')

    @patch('questionary.text')
    @patch('core.deployer.os.path.isdir', return_value=True)
    @patch('core.deployer.os.path.exists', return_value=True)
    @patch('shutil.copy2')
    @patch('builtins.print')
    def test_deploy_usb_success(self, mock_print, mock_copy, mock_exists, mock_isdir, mock_text):
        """Test successful copy of printer.cfg and macros.cfg to USB."""
        import os
        mock_text.return_value = MagicMock(ask=lambda: "/media/usb")
        
        from core.deployer import deploy_usb
        deploy_usb({}, artifact_type="config")
        
        mock_copy.assert_any_call(os.path.expanduser('~/kace/printer.cfg'), os.path.join('/media/usb', 'printer.cfg'))
        mock_copy.assert_any_call(os.path.expanduser('~/kace/macros.cfg'), os.path.join('/media/usb', 'macros.cfg'))

    @patch('questionary.text')
    @patch('core.deployer.os.path.isdir', return_value=False)
    @patch('builtins.print')
    def test_deploy_usb_invalid_path(self, mock_print, mock_isdir, mock_text):
        """If USB directory path is invalid, deployment fails."""
        mock_text.return_value = MagicMock(ask=lambda: "/media/nonexistent")
        
        from core.deployer import deploy_usb
        deploy_usb({}, artifact_type="config")
        
        printed = [c[0][0] for c in mock_print.call_args_list]
        self.assertTrue(any("Invalid path or directory does not exist" in msg for msg in printed))

if __name__ == '__main__':
    import unittest.mock
    unittest.main()
