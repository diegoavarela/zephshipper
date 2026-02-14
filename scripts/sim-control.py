#!/usr/bin/env python3
"""
ZephShipper - Simulator Control
Click, swipe, and navigate iOS Simulator via Quartz events.

Usage:
  python3 sim-control.py click <x_pct> <y_pct>     # Click at % of phone screen
  python3 sim-control.py screenshot <output_path>    # Take screenshot
  python3 sim-control.py statusbar                   # Set clean 9:41 status bar
  python3 sim-control.py launch <bundle_id>          # Launch app
  python3 sim-control.py kill <bundle_id>            # Kill app
  python3 sim-control.py uninstall <bundle_id>       # Uninstall app
  python3 sim-control.py info                        # Show simulator window info

Coordinates are percentages (0-100) of the phone screen area.
Example: click 50 95 = click center bottom (tab bar area)

Requires: Accessibility permissions for node/terminal.
"""

import subprocess
import sys
import time
import json


def get_booted_device():
    """Get the booted simulator device ID."""
    r = subprocess.run(
        ["xcrun", "simctl", "list", "devices", "booted", "-j"],
        capture_output=True, text=True
    )
    data = json.loads(r.stdout)
    for runtime, devices in data.get("devices", {}).items():
        for d in devices:
            if d["state"] == "Booted":
                return d["udid"], d["name"]
    return None, None


def get_sim_window():
    """Get Simulator window bounds."""
    try:
        import Quartz
        windows = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly,
            Quartz.kCGNullWindowID
        )
        for w in windows:
            if 'Simulator' in str(w.get('kCGWindowOwnerName', '')):
                bounds = w.get('kCGWindowBounds', {})
                if bounds.get('Height', 0) > 200:
                    return {
                        'x': float(bounds['X']),
                        'y': float(bounds['Y']),
                        'w': float(bounds['Width']),
                        'h': float(bounds['Height'])
                    }
    except ImportError:
        print("ERROR: Quartz not available. Install: pip3 install pyobjc-framework-Quartz")
        sys.exit(1)
    return None


def click_screen(x_pct, y_pct):
    """Click at percentage coordinates of the phone screen in Simulator."""
    import Quartz

    # Activate Simulator
    subprocess.run(["osascript", "-e", 'tell application "Simulator" to activate'],
                   capture_output=True)
    time.sleep(0.3)

    win = get_sim_window()
    if not win:
        print("ERROR: Simulator window not found")
        return False

    # Title bar offset (~28px on macOS)
    TITLE_BAR = 28
    content_y = win['y'] + TITLE_BAR
    content_h = win['h'] - TITLE_BAR

    # Convert percentage to absolute screen coordinates
    abs_x = win['x'] + (x_pct / 100.0) * win['w']
    abs_y = content_y + (y_pct / 100.0) * content_h

    # Click
    evt = Quartz.CGEventCreateMouseEvent(
        None, Quartz.kCGEventLeftMouseDown, (abs_x, abs_y), Quartz.kCGMouseButtonLeft
    )
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, evt)
    time.sleep(0.1)
    evt = Quartz.CGEventCreateMouseEvent(
        None, Quartz.kCGEventLeftMouseUp, (abs_x, abs_y), Quartz.kCGMouseButtonLeft
    )
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, evt)

    print(f"✅ Clicked at ({x_pct}%, {y_pct}%) → screen ({abs_x:.0f}, {abs_y:.0f})")
    return True


def set_statusbar():
    """Set clean status bar for screenshots."""
    device_id, _ = get_booted_device()
    if not device_id:
        print("ERROR: No booted simulator")
        return
    subprocess.run([
        "xcrun", "simctl", "status_bar", device_id, "override",
        "--time", "9:41",
        "--batteryState", "charged",
        "--batteryLevel", "100",
        "--wifiBars", "3",
        "--cellularBars", "4",
        "--cellularMode", "active"
    ])
    print("✅ Status bar set to 9:41")


def screenshot(output_path):
    """Take simulator screenshot."""
    device_id, _ = get_booted_device()
    if not device_id:
        print("ERROR: No booted simulator")
        return
    subprocess.run(["xcrun", "simctl", "io", device_id, "screenshot", output_path])
    print(f"✅ Screenshot saved: {output_path}")


def launch_app(bundle_id):
    device_id, _ = get_booted_device()
    if not device_id:
        print("ERROR: No booted simulator")
        return
    subprocess.run(["xcrun", "simctl", "launch", device_id, bundle_id])
    print(f"✅ Launched {bundle_id}")


def kill_app(bundle_id):
    device_id, _ = get_booted_device()
    if not device_id:
        return
    subprocess.run(["xcrun", "simctl", "terminate", device_id, bundle_id],
                   capture_output=True)
    print(f"✅ Terminated {bundle_id}")


def uninstall_app(bundle_id):
    device_id, _ = get_booted_device()
    if not device_id:
        return
    subprocess.run(["xcrun", "simctl", "uninstall", device_id, bundle_id],
                   capture_output=True)
    print(f"✅ Uninstalled {bundle_id}")


def show_info():
    device_id, name = get_booted_device()
    win = get_sim_window()
    print(f"Device: {name} ({device_id})")
    if win:
        print(f"Window: x={win['x']}, y={win['y']}, w={win['w']}, h={win['h']}")
    else:
        print("Window: not found")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "click" and len(sys.argv) >= 4:
        click_screen(float(sys.argv[2]), float(sys.argv[3]))
    elif cmd == "screenshot" and len(sys.argv) >= 3:
        screenshot(sys.argv[2])
    elif cmd == "statusbar":
        set_statusbar()
    elif cmd == "launch" and len(sys.argv) >= 3:
        launch_app(sys.argv[2])
    elif cmd == "kill" and len(sys.argv) >= 3:
        kill_app(sys.argv[2])
    elif cmd == "uninstall" and len(sys.argv) >= 3:
        uninstall_app(sys.argv[2])
    elif cmd == "info":
        show_info()
    else:
        print(__doc__)
