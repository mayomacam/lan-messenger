from ui import LANMessengerApp

if __name__ == "__main__":
    app = LANMessengerApp()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()
