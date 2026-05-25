import unittest
import unittest.mock
import sys
import subprocess
import builtins
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

if __name__ == '__main__':
    import unittest.mock
    unittest.main()
