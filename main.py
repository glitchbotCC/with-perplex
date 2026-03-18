# smart_farm/main.py

import tkinter as tk
from .gui.main_window import MainWindow

def start_app():
    """Initializes and runs the Smart Farm application."""
    try:
        root = tk.Tk()
        app = MainWindow(root)
        root.mainloop()
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        # Optionally, show a simple error dialog if Tkinter is still available
        try:
            tk.messagebox.showerror("Fatal Error", f"A fatal error occurred and the application must close:\n\n{e}")
        except:
            pass # Can't show a dialog if Tkinter itself fails

if __name__ == "__main__":
    start_app()