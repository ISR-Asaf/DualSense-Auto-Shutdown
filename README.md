# DualSense Auto-Shutdown 🎮

A lightweight, Windows utility that automatically shuts down connected PlayStation 5 DualSense controllers after a period of inactivity, saving your battery life. Runs silently in the system tray!

## ✨ Features
<img width="412" height="688" alt="ui_preview" src="https://github.com/user-attachments/assets/03e9bcf3-ec6a-4534-b683-387bb1d9db4f" />
![drag_preview](https://github.com/user-attachments/assets/82d9f065-9f45-4047-a4d0-289ece055a9a)



* **Auto-Idle Shutdown: Set a custom timer to turn off your controller when you step away.
* **Manual Quick-Shutdown: Hold the 'START' (Options) button for a custom number of seconds to instantly kill the power.
* **Drift Threshold: An adjustable deadzone threshold prevents physical stick drift from keeping your controller awake.
* **Reset Bluetooth Connection: Forcefully disconnects the controller. This is highly helpful when using the application after exiting apps like Steam or     the EA app, which tend to hijack the controller's connection.
* **Run on Startup: Can automatically launch minimized to the system tray when Windows boots.
* **Multi-Controller Support: Automatically detects and manages multiple DualSense controllers simultaneously.
* **Smart Haptic Warning: Gives a double-pulse vibration warning right before shutting down.

## 🚀 Download & Installation (For Regular Users)
You do not need Python installed to use this program.
1. Go to the [Releases](../../releases) tab on the right side of this page.
2. Download the latest `dualsense_auto_shutdown.exe`.
3. Run the executable. It will appear in your System Tray!

## 💻 For Developers (Running from Source)
If you want to run the raw Python script or compile it yourself:

**Prerequisites:**
* Python 3.8+
* Windows 10/11 with Bluetooth support

**Setup:**
1. Clone the repository.
2. Install the required libraries:
   `pip install -r requirements.txt`
3. Run the script:
   `python dualsense_off.pyw`

## 🛠️ Building the .exe
To compile the standalone executable using PyInstaller:

`python -m PyInstaller --noconsole --onefile --icon=app_icon.ico dualsense_auto_shutdown.pyw`









