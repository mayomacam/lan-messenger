# LAN Messenger

A secure, peer-to-peer LAN messenger and file sharing application built with Python and CustomTkinter. Messages and files are transferred directly between devices on the local network without a central server.

## Features

-   **Discovery**: Automatically finds other users on the LAN.
-   **Global Chat**: Real-time group chat with all active peers.
-   **Message Actions**: Right-click messages to Edit, Delete, or Copy.
-   **File Sharing**:
    -   Share individual files or entire folders.
    -   Browse files shared by other peers.
    -   Download files with a progress bar (UI feedback pending, but supported in backend).
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

## Creating a Standalone Application (.exe)

To convert this project into a standalone executable that works on computers without Python installed, use `PyInstaller`.

1.  **Install PyInstaller**:
    ```bash
    pip install pyinstaller
    ```

2.  **Build the Executable**:
    Run the following command in your terminal. We use `--collect-all customtkinter` to ensure the UI library assets are included.

    ```bash
    pyinstaller --noconfirm --onedir --windowed --collect-all customtkinter --name "LAN Messenger" main.py
    ```

    *   `--onedir`: Creates a directory (faster startup than `--onefile`).
    *   `--windowed`: Hides the console window.
    *   `--collect-all customtkinter`: Copies necessary fonts and images for the UI.

3.  **Run**:
    Go to the `dist/LAN Messenger/` folder and run `LAN Messenger.exe`.

    > **Note**: You can zip this folder and share it with others on your network. They do not need Python installed.
