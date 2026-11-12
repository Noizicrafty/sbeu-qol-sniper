import threading
import unittest
from unittest.mock import Mock
from itemsniper.app import App


class FocusGateTests(unittest.TestCase):
    def test_no_capture_or_job_when_tarkov_not_focused(self):
        app=App.__new__(App);app.closing=threading.Event();app.root=Mock();app.overlay=Mock()
        app.service=Mock();app.service.scanning=True;app.service.state.value={'interval':.05}
        app.window=Mock();app.window.current.return_value={'found':True,'focused':False}
        app.background=Mock();app.tick()
        app.background.assert_not_called();app.overlay.hide.assert_called_once()
        self.assertEqual(app.service.set_health.call_args.args[0],'waiting')
