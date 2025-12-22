# LAN Messenger

A secure, peer-to-peer LAN messenger and file sharing application built with Python and CustomTkinter. Messages and files are transferred directly between devices on the local network without a central server.

## Features

-   **Manual Connection**: Connect to devices by IP address.
-   **Global Chat**: Real-time group chat with connected peers.
-   **Message Actions**: Right-click messages to Edit, Delete, or Copy.
-   **File Sharing**:
    -   Share individual files or entire folders.
    -   Browse files shared by other peers.
    -   Download files with a progress bar.
-   **Modern UI**: Dark-mode interface using `CustomTkinter`.

## Requirements

-   Python 3.8+
-   `customtkinter`

## Installation & Running (Source)

1.  Clone or download the repository.
2.  Install dependencies:
    ```bash
    pip install customtkinter
    ```
3.  Run the application:
    ```bash
    python main.py
    ```

## Manual Connection

If you cannot see other users automatically:
1.  Click **"Info / Connect IP"** in the sidebar.
2.  Share your IP address with the other person.
3.  Enter their IP address and click **Connect**.

## Creating a Standalone Application (.exe)

To convert this project into a standalone executable that shows as "LAN Messenger" (not "Python"), use `PyInstaller` with version metadata.

1.  **Install PyInstaller**:
    ```bash
    pip install pyinstaller
    ```

2.  **Build the Executable**:
    Run this command in the project directory:

    ```bash
    pyinstaller --noconfirm --onedir --windowed --collect-all customtkinter --icon=NONE --name "LAN Messenger" --version-file version.txt main.py
    ```

    **Command Breakdown:**
    *   `--onedir`: Creates a folder with the executable and dependencies
    *   `--windowed`: Hides the console window
    *   `--collect-all customtkinter`: Includes UI library assets
    *   `--name "LAN Messenger"`: Sets the executable name
    *   `--version-file version.txt`: Adds Windows metadata (shows proper name in Task Manager, Firewall)

3.  **Run**:
    Go to the `dist/LAN Messenger/` folder and run `LAN Messenger.exe`.
    
    When Windows Firewall prompts you, it will show as **"LAN Messenger"** instead of "Python".

4.  **Optional - Add an Icon**:
    If you have an `.ico` file, replace `--icon=NONE` with `--icon=youricon.ico`.
