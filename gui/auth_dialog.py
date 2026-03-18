# smart_farm/gui/auth_dialog.py

import tkinter as tk
from tkinter import ttk, messagebox

class AuthDialog(tk.Toplevel):
    """A dialog for setting or entering credentials to lock/unlock the configuration."""
    def __init__(self, master_app, is_setting_credentials=False):
        # The 'master' for a Toplevel should be the root window.
        super().__init__(master_app.root) 
        
        # We keep a reference to the main app object to access its style and other data.
        self.master_app = master_app 
        self.is_setting_credentials = is_setting_credentials
        self.result = None

        self.transient(master_app.root)
        self.grab_set()
        self.resizable(False, False)

        title = "Set Admin Credentials" if self.is_setting_credentials else "Authentication Required"
        self.title(f"🔒 {title}")

        self.username_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.password_confirm_var = tk.StringVar()

        self.configure(bg=self.master_app.style.lookup(".", "background"))
        self._setup_ui()

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.wait_window(self)

    def _setup_ui(self):
        main_frame = ttk.Frame(self, padding=20, style="TFrame")
        main_frame.pack(fill=tk.BOTH, expand=True)

        header_text = "Create a username and password to lock the configuration." if self.is_setting_credentials else "Enter credentials to unlock."
        ttk.Label(main_frame, text=header_text, wraplength=300, justify="center").pack(pady=(0, 15))

        ttk.Label(main_frame, text="Username:").pack(anchor="w", padx=5)
        self.user_entry = ttk.Entry(main_frame, textvariable=self.username_var, width=40)
        self.user_entry.pack(fill="x", padx=5, pady=(0, 10))

        ttk.Label(main_frame, text="Password:").pack(anchor="w", padx=5)
        self.pass_entry = ttk.Entry(main_frame, textvariable=self.password_var, show="*", width=40)
        self.pass_entry.pack(fill="x", padx=5, pady=(0, 10))

        if self.is_setting_credentials:
            ttk.Label(main_frame, text="Confirm Password:").pack(anchor="w", padx=5)
            self.pass_confirm_entry = ttk.Entry(main_frame, textvariable=self.password_confirm_var, show="*", width=40)
            self.pass_confirm_entry.pack(fill="x", padx=5, pady=(0, 15))

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill="x", pady=(10, 0))

        ok_text = "Set Credentials" if self.is_setting_credentials else "Unlock"
        self.ok_button = ttk.Button(button_frame, text=ok_text, command=self._on_ok, style="Accent.TButton")
        self.ok_button.pack(side="right", padx=(5, 0))
        
        cancel_button = ttk.Button(button_frame, text="Cancel", command=self._on_cancel)
        cancel_button.pack(side="right")

        self.user_entry.focus_set()

    def _on_ok(self):
        user = self.username_var.get().strip()
        pwd = self.password_var.get()

        if not user or not pwd:
            messagebox.showerror("Error", "Username and password cannot be empty.", parent=self)
            return

        if self.is_setting_credentials:
            pwd_confirm = self.password_confirm_var.get()
            if pwd != pwd_confirm:
                messagebox.showerror("Error", "Passwords do not match.", parent=self)
                return
            self.result = {"username": user, "password": pwd}
        else:
            self.result = {"username": user, "password": pwd}
        
        self.destroy()

    def _on_cancel(self):
        self.result = None
        self.destroy()
