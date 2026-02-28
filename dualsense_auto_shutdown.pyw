import hid
import time
import ctypes
import sys
import os
import threading
import tkinter as tk
from tkinter import messagebox
import pystray
from PIL import Image, ImageDraw
import binascii
import winreg

# Prevent crashes when running invisibly
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
    sys.stderr = open(os.devnull, 'w')

VENDOR_ID = 0x054C
PRODUCT_ID = 0x0CE6
APP_NAME = "DualSenseAutoShutdown"

# --- MODERN UI COLORS & FONTS ---
BG_MAIN = "#121212"     
BG_CARD = "#1E1E1E"     
BG_ENTRY = "#2D2D2D"    
FG_TEXT = "#FFFFFF"     
FG_SUBTEXT = "#A0A0A0"  
ACCENT_BLUE = "#0078D4"
ACCENT_PURPLE = "#6200EA"
ACCENT_RED = "#D32F2F"
ACCENT_GREEN = "#00C853"

FONT_LABEL = ("Segoe UI", 10)
FONT_ENTRY = ("Segoe UI", 11)
FONT_BUTTON = ("Segoe UI", 10, "bold")

# Global Configuration
config = {
    'idle_timeout': 180.0,
    'hold_time': 4.0,
    'deadzone': 3,
    'keep_running': True,
    'reset_timer_flag': False 
}

active_controllers = {}  
comms_lock = threading.Lock()
icon = None 

# --- TRAY ICON COLORS ---
COLOR_BLUE = (0, 120, 215)
COLOR_RED = (204, 0, 0)

def create_tray_image(color):
    image = Image.new('RGBA', (64, 64), color=(0, 0, 0, 0))
    ImageDraw.Draw(image).ellipse((8, 8, 56, 56), fill=color)
    return image

# --- TOOLTIP LOGIC ---
class ToolTip(object):
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tw = None
        self.timer = None
        self.widget.bind("<Enter>", self.enter)
        self.widget.bind("<Leave>", self.leave)
        self.widget.bind("<ButtonPress>", self.leave) # Hides instantly if clicked

    def enter(self, event=None):
        self.schedule()

    def leave(self, event=None):
        self.unschedule()
        self.hide()

    def schedule(self):
        self.unschedule()
        self.timer = self.widget.after(400, self.show) # 400ms delay before showing

    def unschedule(self):
        if self.timer:
            self.widget.after_cancel(self.timer)
            self.timer = None

    def show(self):
        self.unschedule()
        x = self.widget.winfo_rootx() + 25
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5 # Spawns safely below mouse
        
        self.tw = tk.Toplevel(self.widget)
        self.tw.wm_overrideredirect(True) 
        self.tw.wm_geometry("+%d+%d" % (x, y))
        label = tk.Label(self.tw, text=self.text, justify='left',
                       background="#333333", foreground="#FFFFFF", 
                       relief='flat', padx=10, pady=6, font=("Segoe UI", 9))
        label.pack()

    def hide(self):
        if self.tw:
            self.tw.destroy()
            self.tw = None

# --- WINDOWS STARTUP LOGIC ---
def get_executable_path():
    if getattr(sys, 'frozen', False): return sys.executable
    return os.path.abspath(__file__)

def check_startup_status():
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ)
        value, _ = winreg.QueryValueEx(key, APP_NAME)
        winreg.CloseKey(key)
        return value != "" 
    except FileNotFoundError: return "FIRST_RUN"

def toggle_startup(enable):
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    exe_path = get_executable_path()
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
        if enable: winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{exe_path}"')
        else: winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, "")
        winreg.CloseKey(key)
    except Exception: pass

current_startup_status = check_startup_status()
if current_startup_status == "FIRST_RUN":
    toggle_startup(True)
    is_startup_enabled = True
else: is_startup_enabled = current_startup_status

# --- HAPTIC & CORE LOGIC ---
def trigger_vibration(device):
    if device is None: return
    try:
        with comms_lock:
            report = bytearray([0] * 78)
            report[0] = 0x31; report[1] = 0x02; report[2] = 0x03 
            report[3] = 120;  report[4] = 120
            header = bytearray([0xA2])
            crc = binascii.crc32(header + report[0:74]) & 0xFFFFFFFF
            report[74:78] = crc.to_bytes(4, byteorder='little')
            device.write(report)
            time.sleep(0.3)
            stop_report = bytearray([0] * 78)
            stop_report[0] = 0x31; stop_report[1] = 0x02
            stop_crc = binascii.crc32(header + stop_report[0:74]) & 0xFFFFFFFF
            stop_report[74:78] = stop_crc.to_bytes(4, byteorder='little')
            device.write(stop_report)
    except: pass

def disconnect_bluetooth(mac_string):
    if not mac_string: return False
    try:
        clean_mac = mac_string.replace(":", "")
        mac_int = int(clean_mac, 16)
        bthprops = ctypes.windll.LoadLibrary("bthprops.cpl")
        class BLUETOOTH_ADDRESS(ctypes.Structure): _fields_ = [("ullLong", ctypes.c_uint64)]
        addr = BLUETOOTH_ADDRESS(mac_int)
        bthprops.BluetoothDisconnectDevice.argtypes = [ctypes.c_void_p, ctypes.POINTER(BLUETOOTH_ADDRESS)]
        bthprops.BluetoothDisconnectDevice.restype = ctypes.c_uint32
        return bthprops.BluetoothDisconnectDevice(None, ctypes.byref(addr)) == 0
    except Exception: return False

def force_initial_scan():
    try:
        current_enum = hid.enumerate(VENDOR_ID, PRODUCT_ID)
        for dev_info in current_enum:
            path = dev_info['path']
            if path not in active_controllers:
                try:
                    dev = hid.device()
                    dev.open_path(path)
                    dev.set_nonblocking(True)
                    active_controllers[path] = {'device': dev, 'sn': dev_info.get('serial_number', ''), 'last_active': time.time(), 'start_pressed': None}
                except: pass
    except: pass

def monitor_system():
    last_scan_time = 0
    while config['keep_running']:
        if time.time() - last_scan_time > 2.0:
            try:
                current_enum = hid.enumerate(VENDOR_ID, PRODUCT_ID)
                # Tracking by PATH guarantees multiple controllers are detected even if Windows hides the serial number
                current_paths = [d['path'] for d in current_enum]
                for dev_info in current_enum:
                    path = dev_info['path']
                    if path not in active_controllers:
                        try:
                            dev = hid.device()
                            dev.open_path(path)
                            dev.set_nonblocking(True)
                            active_controllers[path] = {'device': dev, 'sn': dev_info.get('serial_number', ''), 'last_active': time.time(), 'start_pressed': None}
                            update_status_ui()
                        except: pass
                
                disconnected = [p for p in active_controllers if p not in current_paths]
                for p in disconnected:
                    try: active_controllers[p]['device'].close()
                    except: pass
                    del active_controllers[p]
                    update_status_ui()
            except Exception: pass
            last_scan_time = time.time()

        for path, ctrl in list(active_controllers.items()):
            if config['reset_timer_flag']: ctrl['last_active'] = time.time()
            try:
                with comms_lock: report = ctrl['device'].read(64)
                if report:
                    activity_detected = False
                    for i in range(1, 7):
                        if abs(report[i] - ctrl.get('last_report', [0]*64)[i]) > config['deadzone']:
                            activity_detected = True; break
                    if activity_detected:
                        ctrl['last_active'] = time.time()
                        ctrl['last_report'] = report[:]
                    if time.time() - ctrl['last_active'] >= config['idle_timeout']:
                        trigger_vibration(ctrl['device'])
                        ctrl['device'].close(); disconnect_bluetooth(ctrl['sn'])
                        del active_controllers[path]; update_status_ui()
                        continue
                    options_down = bool(report[6] & 0x20) if report[0] == 0x01 and len(report) > 6 else False
                    if options_down:
                        if ctrl['start_pressed'] is None: ctrl['start_pressed'] = time.time()
                        elif time.time() - ctrl['start_pressed'] >= config['hold_time']:
                            trigger_vibration(ctrl['device'])
                            ctrl['device'].close(); disconnect_bluetooth(ctrl['sn'])
                            del active_controllers[path]; update_status_ui()
                            continue
                    else: ctrl['start_pressed'] = None
            except IOError:
                try: ctrl['device'].close()
                except: pass
                del active_controllers[path]; update_status_ui()
        config['reset_timer_flag'] = False
        time.sleep(0.02) 

# --- UI & TRAY INTERACTION ---
def update_status_ui():
    def _refresh():
        count = len(active_controllers)
        if count == 0:
            status_dot.config(fg=ACCENT_RED)
            status_text.config(text="NO CONTROLLERS DETECTED", fg=FG_SUBTEXT)
            if icon: icon.icon = create_tray_image(COLOR_RED)
        else:
            status_dot.config(fg=ACCENT_GREEN)
            status_text.config(text=f"{count} CONTROLLER{'S' if count > 1 else ''} CONNECTED", fg=ACCENT_GREEN)
            if icon: icon.icon = create_tray_image(COLOR_BLUE)
    root.after(0, _refresh)

def display_ui_message(message, color):
    ui_message_label.config(text=message, fg=color)
    root.after(3500, lambda: ui_message_label.config(text=""))

def save_settings():
    try:
        config['idle_timeout'] = float(entry_idle.get())
        config['hold_time'] = float(entry_hold.get())
        config['deadzone'] = int(entry_deadzone.get())
        toggle_startup(startup_var.get())
        config['reset_timer_flag'] = True
        display_ui_message("✓ Settings applied and timers reset", ACCENT_GREEN)
    except: 
        display_ui_message("✗ Error: Invalid numbers entered", ACCENT_RED)

def reset_connections():
    """Actually disconnects the controllers from Windows Bluetooth"""
    with comms_lock:
        for path, ctrl in list(active_controllers.items()):
            try: ctrl['device'].close()
            except: pass
            disconnect_bluetooth(ctrl['sn']) # Force Bluetooth disconnect
        active_controllers.clear()
    update_status_ui()
    display_ui_message("✓ Bluetooth connections reset", ACCENT_PURPLE)

def quit_program():
    config['keep_running'] = False
    if icon: icon.stop()
    root.destroy(); sys.exit()

def setup_tray():
    global icon
    menu = pystray.Menu(pystray.MenuItem('Open Menu', lambda: root.after(0, root.deiconify), default=True), pystray.MenuItem('Quit', quit_program))
    icon = pystray.Icon("DualSenseMonitor", create_tray_image(COLOR_RED), "DualSense Auto-Shutdown", menu)
    def on_ready(icon_item): icon_item.visible = True; update_status_ui() 
    icon.run(setup=on_ready)

# --- MAIN GUI ---
force_initial_scan() 

if __name__ == "__main__":
    threading.Thread(target=monitor_system, daemon=True).start()
    threading.Thread(target=setup_tray, daemon=True).start()
    
    root = tk.Tk()
    root.title("DualSense Auto-Shutdown")
    root.resizable(False, False) 
    root.attributes('-toolwindow', True) 
    
    window_width, window_height = 420, 660
    screen_width, screen_height = root.winfo_screenwidth(), root.winfo_screenheight()
    center_x, center_y = int((screen_width/2)-(window_width/2)), int((screen_height/2)-(window_height/2))
    root.geometry(f"{window_width}x{window_height}+{center_x}+{center_y}")
    root.configure(bg=BG_MAIN)
    root.protocol("WM_DELETE_WINDOW", lambda: root.withdraw())

    container = tk.Frame(root, bg=BG_CARD, padx=25, pady=25)
    container.pack(fill="both", expand=True, padx=20, pady=20)
    
    status_frame = tk.Frame(container, bg=BG_CARD)
    status_frame.pack(pady=(0, 20), fill="x")
    status_dot = tk.Label(status_frame, text="●", font=("Arial", 14), bg=BG_CARD, fg=ACCENT_RED)
    status_dot.pack(side="left")
    status_text = tk.Label(status_frame, text="SCANNING...", font=("Segoe UI", 10, "bold"), bg=BG_CARD, fg=FG_SUBTEXT)
    status_text.pack(side="left", padx=10)

    def create_input(label_text, default_val, tooltip_text=None):
        header_frame = tk.Frame(container, bg=BG_CARD)
        header_frame.pack(anchor="w", fill="x", pady=(0, 5))
        tk.Label(header_frame, text=label_text, bg=BG_CARD, fg=FG_TEXT, font=FONT_LABEL).pack(side="left")
        
        if tooltip_text:
            help_lbl = tk.Label(header_frame, text="ⓘ", bg=BG_CARD, fg=FG_SUBTEXT, font=("Segoe UI", 12), cursor="hand2")
            help_lbl.pack(side="left", padx=8)
            ToolTip(help_lbl, tooltip_text) 
            
        e_frame = tk.Frame(container, bg=BG_ENTRY, bd=0)
        e_frame.pack(fill="x", pady=(0, 15))
        e = tk.Entry(e_frame, justify='center', bg=BG_ENTRY, fg=FG_TEXT, bd=0, font=FONT_ENTRY, insertbackground=FG_TEXT)
        e.insert(0, str(int(default_val)))
        e.pack(fill="x", padx=10, pady=8)
        return e

    entry_idle = create_input("Global Idle Timer (sec)", config['idle_timeout'], "Seconds of inactivity before shutdown.")
    entry_hold = create_input("Global Hold START (sec)", config['hold_time'], "Seconds to hold START to force shutdown.")
    entry_deadzone = create_input("Global Drift Threshold", config['deadzone'], "Higher values ignore stick drift. Recommended: 3")

    startup_var = tk.BooleanVar(value=is_startup_enabled)
    chk_startup = tk.Checkbutton(container, text="Run minimized on Windows Startup", variable=startup_var, 
                                 bg=BG_CARD, fg=FG_TEXT, selectcolor=BG_ENTRY, activebackground=BG_CARD, 
                                 activeforeground=FG_TEXT, font=FONT_LABEL, cursor="hand2", bd=0, highlightthickness=0,
                                 command=lambda: toggle_startup(startup_var.get()))
    chk_startup.pack(anchor="w", pady=(0, 15))

    def create_button(text, bg_color, hover_color, cmd, tooltip=None):
        btn = tk.Button(container, text=text, bg=bg_color, fg="#FFFFFF", font=FONT_BUTTON, 
                  bd=0, cursor="hand2", activebackground=hover_color, activeforeground="#FFFFFF", command=cmd, pady=8)
        btn.pack(fill="x", pady=(0, 8))
        if tooltip: ToolTip(btn, tooltip)
        return btn

    create_button("APPLY TO ALL DEVICES", ACCENT_BLUE, "#006CC0", save_settings)
    create_button("RESET BLUETOOTH CONNECTION", ACCENT_PURPLE, "#5000BA", reset_connections, 
                  "Forcefully drops the Bluetooth connection to all active controllers.")

    ui_message_label = tk.Label(container, text="", font=("Segoe UI", 9, "bold"), bg=BG_CARD, fg=ACCENT_GREEN)
    ui_message_label.pack(pady=(5, 5))

    create_button("EXIT PROGRAM COMPLETELY", ACCENT_RED, "#B00000", quit_program)

    update_status_ui() 
    root.mainloop()
