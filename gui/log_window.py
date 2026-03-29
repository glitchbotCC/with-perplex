# smart_farm/gui/log_window.py

import tkinter as tk
from tkinter import ttk

class LogWindow(tk.Toplevel):
    """A Toplevel window for displaying system logs."""
    def __init__(self, master_app):
        super().__init__(master_app.root)
        self.master_app = master_app
        self.title("📜 System Logs")
        self.geometry("860x520")
        self.transient(master_app.root)
        self.minsize(600, 300)

        bg       = self.master_app.style.lookup(".", "background")
        frame_bg = self.master_app.style.lookup("Card.TFrame", "background")
        self.configure(bg=bg)

        wrapper = ttk.Frame(self, padding=(16, 12))
        wrapper.pack(fill=tk.BOTH, expand=True)

        ttk.Label(wrapper, text="System Logs", font=('Segoe UI Semibold', 13)).pack(anchor="w", pady=(0, 8))
        ttk.Separator(wrapper, orient="horizontal").pack(fill=tk.X, pady=(0, 8))

        main_frame = ttk.Frame(wrapper)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)

        self.log_text = tk.Text(
            main_frame, height=7,
            bg=self.master_app.style.lookup("TEntry", "fieldbackground"),
            fg=self.master_app.style.lookup("TEntry", "foreground"),
            insertbackground=self.master_app.style.lookup("TEntry", "insertcolor"),
            font=("Consolas", 10), state="disabled", wrap="none",
            relief="flat", borderwidth=0,
            padx=10, pady=8)
        log_v = ttk.Scrollbar(main_frame, orient="vertical",  command=self.log_text.yview)
        log_h = ttk.Scrollbar(main_frame, orient="horizontal", command=self.log_text.xview)
        self.log_text.configure(yscrollcommand=log_v.set, xscrollcommand=log_h.set)

        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_v.grid(row=0, column=1, sticky="ns")
        log_h.grid(row=1, column=0, sticky="ew")

        self.populate_logs()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def populate_logs(self):
        """Fills the text widget with existing logs."""
        self.log_text.config(state="normal")
        self.log_text.delete('1.0', tk.END)
        for entry in self.master_app.logs:
            self.log_text.insert(tk.END, entry + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")

    def add_log_entry(self, entry):
        """Appends a new log entry to the text widget."""
        if self.winfo_exists():
            self.log_text.config(state="normal")
            self.log_text.insert(tk.END, entry + "\n")
            self.log_text.see(tk.END)
            self.log_text.config(state="disabled")

    def on_close(self):
        """Handles the window close event."""
        self.master_app.log_window = None
        self.destroy()