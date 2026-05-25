from __future__ import annotations

import threading
from typing import Callable

from .app_settings import AppSettings, apply_settings


_dialog_lock = threading.Lock()
_dialog_open = False


def open_settings_dialog(initial_settings: AppSettings, on_save: Callable[[AppSettings], None] | None = None) -> None:
    global _dialog_open

    with _dialog_lock:
        if _dialog_open:
            return
        _dialog_open = True

    def _run_dialog() -> None:
        global _dialog_open

        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.title("Paramètres GoPro-Webcam")
            root.resizable(False, False)
            root.attributes("-topmost", True)

            startup_var = tk.BooleanVar(value=initial_settings.launch_at_startup)
            view_var = tk.BooleanVar(value=initial_settings.launch_with_view)

            frame = tk.Frame(root, padx=16, pady=14)
            frame.pack(fill="both", expand=True)

            title = tk.Label(frame, text="Paramètres", font=("Segoe UI", 12, "bold"))
            title.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

            startup_check = tk.Checkbutton(frame, text="Lancer GoPro-Webcam au démarrage de Windows", variable=startup_var)
            startup_check.grid(row=1, column=0, columnspan=2, sticky="w", pady=2)

            view_check = tk.Checkbutton(frame, text="Lancer avec l'aperçu local", variable=view_var)
            view_check.grid(row=2, column=0, columnspan=2, sticky="w", pady=2)

            hint = tk.Label(frame, text="Les changements seront appliqués au prochain lancement.", fg="#555555")
            hint.grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 12))

            def _save() -> None:
                updated_settings = AppSettings(
                    launch_at_startup=startup_var.get(),
                    launch_with_view=view_var.get(),
                )
                applied = apply_settings(updated_settings)
                if on_save is not None:
                    on_save(updated_settings)
                message = "Paramètres enregistrés."
                if not applied and updated_settings.launch_at_startup:
                    message += " L'option de démarrage automatique n'a pas pu être appliquée sur ce système."
                messagebox.showinfo("GoPro-Webcam", message)
                root.destroy()

            button_row = tk.Frame(frame)
            button_row.grid(row=4, column=0, columnspan=2, sticky="e")

            cancel_button = tk.Button(button_row, text="Annuler", command=root.destroy, width=12)
            cancel_button.pack(side="right", padx=(8, 0))

            save_button = tk.Button(button_row, text="Enregistrer", command=_save, width=12)
            save_button.pack(side="right")

            def _close() -> None:
                root.destroy()

            root.protocol("WM_DELETE_WINDOW", _close)
            root.mainloop()
        finally:
            with _dialog_lock:
                _dialog_open = False

    threading.Thread(target=_run_dialog, daemon=True).start()