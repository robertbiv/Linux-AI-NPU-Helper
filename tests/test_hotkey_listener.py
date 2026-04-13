from unittest.mock import MagicMock
from src.hotkey_listener import HotkeyListener, _COPILOT_KEY_CODES

def test_init_and_state():
    mock_cb = MagicMock()
    listener = HotkeyListener("copilot", mock_cb)
    assert listener._hotkey == "copilot"
    assert listener._callback == mock_cb
    assert listener._thread is None
    assert not listener._stop_event.is_set()
    assert not listener.is_alive()

def test_start_evdev(mocker):
    listener = HotkeyListener("copilot", MagicMock())
    mock_thread = mocker.patch("src.hotkey_listener.threading.Thread")
    listener.start()
    mock_thread.assert_called_once_with(
        target=listener._evdev_loop, daemon=True, name="hotkey-evdev"
    )
    assert listener._thread is mock_thread.return_value
    listener._thread.start.assert_called_once()
    assert not listener._stop_event.is_set()

def test_start_pynput(mocker):
    listener = HotkeyListener("<ctrl>+<alt>+space", MagicMock())
    mock_thread = mocker.patch("src.hotkey_listener.threading.Thread")
    listener.start()
    mock_thread.assert_called_once_with(
        target=listener._pynput_loop, daemon=True, name="hotkey-pynput"
    )

def test_stop():
    listener = HotkeyListener("copilot", MagicMock())
    assert not listener._stop_event.is_set()
    listener.stop()
    assert listener._stop_event.is_set()

def test_is_alive():
    listener = HotkeyListener("copilot", MagicMock())
    assert not listener.is_alive()

    mock_thread = MagicMock()
    mock_thread.is_alive.return_value = True
    listener._thread = mock_thread
    assert listener.is_alive()

def test_fire_success():
    mock_cb = MagicMock()
    listener = HotkeyListener("copilot", mock_cb)
    listener._fire()
    mock_cb.assert_called_once()

def test_fire_exception(mocker):
    mock_cb = MagicMock(side_effect=ValueError("Test Error"))
    listener = HotkeyListener("copilot", mock_cb)

    mock_logger = mocker.patch("src.hotkey_listener.logger.error")

    listener._fire()
    mock_cb.assert_called_once()
    mock_logger.assert_called_once()
    assert "Hotkey callback raised an exception: %s" in mock_logger.call_args[0][0]

def test_evdev_loop_import_error(mocker):
    listener = HotkeyListener("copilot", MagicMock())
    mocker.patch.dict("sys.modules", {"evdev": None})
    mock_pynput_loop = mocker.patch.object(listener, "_pynput_loop")
    mock_logger = mocker.patch("src.hotkey_listener.logger.warning")

    listener._evdev_loop()

    mock_logger.assert_called_once()
    assert "evdev not installed" in mock_logger.call_args[0][0]
    mock_pynput_loop.assert_called_once()

def test_evdev_loop_no_devices(mocker):
    listener = HotkeyListener("copilot", MagicMock())

    mock_evdev = MagicMock()
    mocker.patch.dict("sys.modules", {"evdev": mock_evdev})
    mocker.patch.object(listener, "_find_copilot_devices", return_value=[])
    mock_pynput_loop = mocker.patch.object(listener, "_pynput_loop")
    mock_logger = mocker.patch("src.hotkey_listener.logger.warning")

    listener._evdev_loop()

    mock_logger.assert_called_once()
    assert "No evdev device found" in mock_logger.call_args[0][0]
    mock_pynput_loop.assert_called_once()

def test_evdev_loop_success(mocker):
    listener = HotkeyListener("copilot", MagicMock())

    mock_evdev = MagicMock()
    mock_evdev.ecodes.EV_KEY = 1
    mock_evdev.KeyEvent.key_down = 1
    mocker.patch.dict("sys.modules", {"evdev": mock_evdev})

    mock_device = MagicMock()
    mock_device.path = "/dev/input/event0"
    mock_device.fd = 10

    mock_event = MagicMock()
    mock_event.type = 1
    mock_event.value = 1
    # Use one of the valid codes
    valid_code = list(_COPILOT_KEY_CODES)[0]
    mock_event.code = valid_code

    mock_device.read.return_value = [mock_event]

    mocker.patch.object(listener, "_find_copilot_devices", return_value=[mock_device])

    mock_sel = MagicMock()
    mocker.patch("selectors.DefaultSelector", return_value=mock_sel)

    mock_key = MagicMock()
    mock_key.data = mock_device
    mock_sel.select.return_value = [(mock_key, None)]

    mock_fire = mocker.patch.object(listener, "_fire")

    # We want to break out of the loop after first iteration
    def set_stop_event(*args, **kwargs):
        listener._stop_event.set()
        return [(mock_key, None)]

    mock_sel.select.side_effect = set_stop_event

    listener._evdev_loop()

    mock_sel.register.assert_called_once_with(10, mocker.ANY, mock_device)
    mock_fire.assert_called_once()
    mock_sel.close.assert_called_once()
    mock_device.close.assert_called_once()

def test_find_copilot_devices(mocker):
    mock_evdev = MagicMock()
    mock_evdev.ecodes.EV_KEY = 1

    mock_evdev.list_devices.return_value = ["/dev/input/event0", "/dev/input/event1", "/dev/input/event2"]

    # device 0: matches
    dev0 = MagicMock()
    dev0.capabilities.return_value = {1: [list(_COPILOT_KEY_CODES)[0], 999]}

    # device 1: doesn't match
    dev1 = MagicMock()
    dev1.capabilities.return_value = {1: [999]}

    # device 2: throws OSError on init
    def init_device(path):
        if path == "/dev/input/event0":
            return dev0
        if path == "/dev/input/event1":
            return dev1
        if path == "/dev/input/event2":
            raise OSError("Permission denied")

    mock_evdev.InputDevice = init_device

    found = HotkeyListener._find_copilot_devices(mock_evdev)

    assert len(found) == 1
    assert found[0] == dev0
    dev1.close.assert_called_once()

def test_pynput_loop_import_error(mocker):
    listener = HotkeyListener("copilot", MagicMock())
    mocker.patch.dict("sys.modules", {"pynput": None})
    mock_logger = mocker.patch("src.hotkey_listener.logger.error")

    listener._pynput_loop()

    mock_logger.assert_called_once()
    assert "Neither evdev nor pynput is available" in mock_logger.call_args[0][0]

def test_pynput_loop_success(mocker):
    listener = HotkeyListener("copilot", MagicMock())

    mock_pynput = MagicMock()
    mocker.patch.dict("sys.modules", {"pynput": mock_pynput})

    mock_listener = MagicMock()
    mock_pynput.keyboard.GlobalHotKeys.return_value.__enter__.return_value = mock_listener

    # Break the wait immediately
    mocker.patch.object(listener._stop_event, "wait")

    listener._pynput_loop()

    mock_pynput.keyboard.GlobalHotKeys.assert_called_once_with({"<ctrl>+<alt>+space": listener._fire})
    listener._stop_event.wait.assert_called_once()
    mock_listener.stop.assert_called_once()


def test_evdev_loop_exception(mocker):
    listener = HotkeyListener("copilot", MagicMock())

    mock_evdev = MagicMock()
    mocker.patch.dict("sys.modules", {"evdev": mock_evdev})

    mock_device = MagicMock()
    mocker.patch.object(listener, "_find_copilot_devices", return_value=[mock_device])

    mock_sel = MagicMock()
    mocker.patch("selectors.DefaultSelector", return_value=mock_sel)

    mock_sel.select.side_effect = Exception("Test exception in evdev loop")

    mock_logger = mocker.patch("src.hotkey_listener.logger.error")

    listener._evdev_loop()

    mock_logger.assert_called_once()
    assert "evdev loop error" in mock_logger.call_args[0][0]

def test_pynput_loop_exception(mocker):
    listener = HotkeyListener("copilot", MagicMock())

    mock_pynput = MagicMock()
    mocker.patch.dict("sys.modules", {"pynput": mock_pynput})

    mock_pynput.keyboard.GlobalHotKeys.side_effect = Exception("Test exception in pynput loop")

    mock_logger = mocker.patch("src.hotkey_listener.logger.error")

    listener._pynput_loop()

    mock_logger.assert_called_once()
    assert "pynput listener error" in mock_logger.call_args[0][0]
