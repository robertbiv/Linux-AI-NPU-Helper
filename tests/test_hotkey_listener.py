from unittest.mock import patch, MagicMock
from src.hotkey_listener import HotkeyListener, _COPILOT_KEY_CODES

class TestHotkeyListener:
    def test_start_copilot(self):
        cb = MagicMock()
        listener = HotkeyListener("copilot", cb)
        with patch("threading.Thread") as mock_thread:
            # mock thread's is_alive method
            mock_thread_instance = MagicMock()
            mock_thread_instance.is_alive.return_value = True
            mock_thread.return_value = mock_thread_instance

            listener.start()
            mock_thread.assert_called_once()
            args, kwargs = mock_thread.call_args
            assert kwargs["target"] == listener._evdev_loop
            assert kwargs["name"] == "hotkey-evdev"
            assert listener.is_alive() == True

    def test_start_pynput(self):
        cb = MagicMock()
        listener = HotkeyListener("<ctrl>+<alt>+space", cb)
        with patch("threading.Thread") as mock_thread:
            listener.start()
            mock_thread.assert_called_once()
            args, kwargs = mock_thread.call_args
            assert kwargs["target"] == listener._pynput_loop
            assert kwargs["name"] == "hotkey-pynput"

    def test_stop(self):
        listener = HotkeyListener("copilot", MagicMock())
        assert listener._stop_event.is_set() is False
        listener.stop()
        assert listener._stop_event.is_set() is True

    def test_is_alive_false_when_no_thread(self):
        listener = HotkeyListener("copilot", MagicMock())
        assert listener.is_alive() is False

    def test_evdev_loop_no_evdev_fallback(self):
        listener = HotkeyListener("copilot", MagicMock())
        with patch.dict("sys.modules", {"evdev": None}):
            with patch.object(listener, "_pynput_loop") as mock_pynput:
                listener._evdev_loop()
                mock_pynput.assert_called_once()

    def test_evdev_loop_no_devices_fallback(self):
        listener = HotkeyListener("copilot", MagicMock())
        with patch.dict("sys.modules", {"evdev": MagicMock()}):
            with patch("src.hotkey_listener.HotkeyListener._find_copilot_devices", return_value=[]):
                with patch.object(listener, "_pynput_loop") as mock_pynput:
                    listener._evdev_loop()
                    mock_pynput.assert_called_once()

    def test_evdev_loop_success(self):
        listener = HotkeyListener("copilot", MagicMock())
        mock_dev = MagicMock()
        mock_dev.path = "/dev/input/eventX"
        mock_dev.fd = 4

        # We need a mock evdev event
        mock_event = MagicMock()
        mock_event.type = 1 # EV_KEY
        mock_event.value = 1 # key down
        mock_event.code = list(_COPILOT_KEY_CODES)[0]

        mock_dev.read.return_value = [mock_event]

        # Setup selector mock
        mock_sel = MagicMock()
        mock_key = MagicMock()
        mock_key.data = mock_dev
        mock_sel.select.return_value = [(mock_key, 1)]

        mock_evdev = MagicMock()
        mock_evdev.ecodes.EV_KEY = 1
        mock_evdev.KeyEvent.key_down = 1

        with patch.dict("sys.modules", {"evdev": mock_evdev}):
            with patch("src.hotkey_listener.HotkeyListener._find_copilot_devices", return_value=[mock_dev]):
                with patch("selectors.DefaultSelector", return_value=mock_sel):
                    with patch.object(listener, "_fire") as mock_fire:
                        # Break loop after first fire
                        mock_fire.side_effect = lambda: listener._stop_event.set()
                        listener._evdev_loop()
                        mock_fire.assert_called_once()
                        mock_dev.close.assert_called_once()
                        mock_sel.close.assert_called_once()

    def test_evdev_loop_exception(self):
        listener = HotkeyListener("copilot", MagicMock())
        mock_dev = MagicMock()
        mock_sel = MagicMock()
        mock_sel.select.side_effect = Exception("Test Error")

        mock_evdev = MagicMock()

        with patch.dict("sys.modules", {"evdev": mock_evdev}):
            with patch("src.hotkey_listener.HotkeyListener._find_copilot_devices", return_value=[mock_dev]):
                with patch("selectors.DefaultSelector", return_value=mock_sel):
                    listener._evdev_loop()
                    # Should swallow exception, close devices and exit
                    mock_dev.close.assert_called_once()
                    mock_sel.close.assert_called_once()

    def test_find_copilot_devices(self):
        evdev = MagicMock()
        evdev.list_devices.return_value = ["/dev/input/event0", "/dev/input/event1", "/dev/input/event2"]
        evdev.ecodes.EV_KEY = 1

        def mock_InputDevice(path):
            dev = MagicMock()
            if path == "/dev/input/event0":
                dev.capabilities.return_value = {1: [list(_COPILOT_KEY_CODES)[0]]}
            elif path == "/dev/input/event1":
                dev.capabilities.return_value = {1: [999]} # some other key
            else:
                dev.capabilities.side_effect = PermissionError
            return dev

        evdev.InputDevice = mock_InputDevice

        devices = HotkeyListener._find_copilot_devices(evdev)
        assert len(devices) == 1

    def test_pynput_loop_no_pynput(self):
        listener = HotkeyListener("copilot", MagicMock())
        with patch.dict("sys.modules", {"pynput": None}):
            with patch("src.hotkey_listener.logger.error") as mock_err:
                listener._pynput_loop()
                mock_err.assert_called_once()

    def test_pynput_loop_success(self):
        listener = HotkeyListener("copilot", MagicMock())
        mock_keyboard = MagicMock()
        mock_listener_ctx = MagicMock()
        mock_keyboard.GlobalHotKeys.return_value.__enter__.return_value = mock_listener_ctx

        with patch.dict("sys.modules", {"pynput": MagicMock(keyboard=mock_keyboard)}):
            with patch("src.hotkey_listener.threading.Event.wait", side_effect=lambda: listener._stop_event.set()):
                listener._pynput_loop()
                mock_keyboard.GlobalHotKeys.assert_called_once_with({"<ctrl>+<alt>+space": listener._fire})
                mock_listener_ctx.stop.assert_called_once()

    def test_pynput_loop_exception(self):
        listener = HotkeyListener("copilot", MagicMock())
        mock_keyboard = MagicMock()
        mock_keyboard.GlobalHotKeys.side_effect = Exception("Test Error")

        with patch.dict("sys.modules", {"pynput": MagicMock(keyboard=mock_keyboard)}):
            with patch("src.hotkey_listener.logger.error") as mock_err:
                listener._pynput_loop()
                mock_err.assert_called_once()

    def test_fire(self):
        cb = MagicMock()
        listener = HotkeyListener("copilot", cb)
        listener._fire()
        cb.assert_called_once()

    def test_fire_exception(self):
        cb = MagicMock(side_effect=Exception("Test Callback Error"))
        listener = HotkeyListener("copilot", cb)
        with patch("src.hotkey_listener.logger.error") as mock_err:
            listener._fire()
            mock_err.assert_called_once()
