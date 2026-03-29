# smart_farm/gui/map_manager.py

import os
import math
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from PIL import Image, ImageTk
try:
    from .. import constants
except ImportError:
    import constants


class AssignValveDialog(tk.Toplevel):
    """A dialog for assigning a valve to a drawn map zone."""
    def __init__(self, master, available_valves):
        super().__init__(master)
        self.transient(master)
        self.title("Assign Valve to Section")
        self.result = None

        main_frame = ttk.Frame(self, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Zone Name:").pack(anchor="w")
        self.name_var = tk.StringVar()
        self.name_entry = ttk.Entry(main_frame, textvariable=self.name_var, width=40)
        self.name_entry.pack(fill="x", pady=(0, 15))
        self.name_entry.focus_set()

        ttk.Label(main_frame, text="Assign Valve:").pack(anchor="w")
        self.valve_var = tk.StringVar()
        self.valve_combo = ttk.Combobox(main_frame, textvariable=self.valve_var,
                                        values=list(available_valves.keys()), state="readonly")
        if available_valves:
            self.valve_combo.current(0)
        self.valve_combo.pack(fill="x", pady=(0, 20))
        self.available_valves = available_valves

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill="x")
        ok_button = ttk.Button(button_frame, text="Assign", command=self._on_ok, style="Accent.TButton")
        ok_button.pack(side="right")
        cancel_button = ttk.Button(button_frame, text="Cancel", command=self._on_cancel)
        cancel_button.pack(side="right", padx=(0, 5))

        self.wait_window(self)

    def _on_ok(self):
        zone_name = self.name_var.get().strip()
        selected_valve_display = self.valve_var.get()
        if not zone_name or not selected_valve_display:
            messagebox.showerror("Error", "Both a name and a valve must be selected.", parent=self)
            return

        valve_index = self.available_valves[selected_valve_display]
        self.result = {"name": zone_name, "valve_index": valve_index}
        self.destroy()

    def _on_cancel(self):
        self.result = None
        self.destroy()


class MapManagerMixin:
    """Encapsulates map view and zone editing features."""

    def _setup_map_view(self):
        self.map_scale = getattr(self, 'map_scale', 1.0)
        self.is_in_draw_mode = False
        self.is_in_edit_mode = False
        self.current_polygon_points = []
        self.temp_draw_items = []

        self.map_view_frame = ttk.Frame(self.notebook, style="TFrame")
        self.map_view_frame.rowconfigure(1, weight=1)
        self.map_view_frame.columnconfigure(0, weight=1)

        map_controls = ttk.Frame(self.map_view_frame, style="TFrame", padding=5)
        map_controls.grid(row=0, column=0, columnspan=2, sticky="ew")

        upload_btn = ttk.Button(map_controls, text="📂 Upload Map Image", command=self._upload_map_image)
        upload_btn.pack(side=tk.LEFT, padx=5)

        draw_btn = ttk.Button(map_controls, text="✏️ Draw New Zone", command=self._enter_draw_mode)
        draw_btn.pack(side=tk.LEFT, padx=5)

        edit_btn = ttk.Button(map_controls, text="🔧 Edit Zones", command=self._enter_edit_mode)
        edit_btn.pack(side=tk.LEFT, padx=5)

        zoom_in_btn = ttk.Button(map_controls, text="➕ Zoom In", command=self._zoom_in)
        zoom_in_btn.pack(side=tk.LEFT, padx=5)

        zoom_out_btn = ttk.Button(map_controls, text="➖ Zoom Out", command=self._zoom_out)
        zoom_out_btn.pack(side=tk.LEFT, padx=5)

        reset_zoom_btn = ttk.Button(map_controls, text="🔄 Reset Zoom", command=self._reset_zoom)
        reset_zoom_btn.pack(side=tk.LEFT, padx=5)

        self.map_canvas = tk.Canvas(self.map_view_frame, bg=self.style.lookup("TEntry", "fieldbackground"), highlightthickness=0)
        self.map_v_scroll = ttk.Scrollbar(self.map_view_frame, orient="vertical", command=self.map_canvas.yview)
        self.map_h_scroll = ttk.Scrollbar(self.map_view_frame, orient="horizontal", command=self.map_canvas.xview)

        self.map_canvas.configure(yscrollcommand=self.map_v_scroll.set, xscrollcommand=self.map_h_scroll.set)
        self.map_canvas.grid(row=1, column=0, sticky="nsew")
        self.map_v_scroll.grid(row=1, column=1, sticky="ns")
        self.map_h_scroll.grid(row=2, column=0, sticky="ew")

        self.map_view_data = self.settings.get("map_view_data", {"image_path": None, "sections": []})
        self.map_image = None
        self.map_image_original = None
        self.map_image_item = None

        if self.map_view_data.get("image_path") and os.path.exists(self.map_view_data["image_path"]):
            self._load_map_image(self.map_view_data["image_path"])
            self._render_map_image()

        self.root.after(100, self._draw_map_sections)
        return self.map_view_frame

    def _load_map_image(self, path):
        try:
            img = Image.open(path)
            self.map_image_original = img.convert("RGBA")
            self.map_view_data["image_path"] = path
            self.settings.set("map_view_data", self.map_view_data)
            self._render_map_image()
            self.log(f"Map image loaded from {path}")
        except Exception as e:
            self.log(f"Error loading map image: {e}")
            messagebox.showerror("Error", f"Could not load map image from {path}.\n\n{e}", parent=self.root)

    def _render_map_image(self):
        if not self.map_image_original:
            return

        width, height = self.map_image_original.size
        scaled_w = max(1, int(width * self.map_scale))
        scaled_h = max(1, int(height * self.map_scale))

        resized = self.map_image_original.resize((scaled_w, scaled_h), Image.LANCZOS)
        self.map_image = ImageTk.PhotoImage(resized)

        if self.map_image_item:
            self.map_canvas.delete(self.map_image_item)

        self.map_image_item = self.map_canvas.create_image(0, 0, anchor="nw", image=self.map_image)
        self.map_canvas.tag_lower(self.map_image_item)

        self.map_canvas.config(scrollregion=(0, 0, scaled_w, scaled_h))
        self._draw_map_sections()

    def _set_map_scale(self, scale):
        old_scale = self.map_scale
        self.map_scale = max(0.2, min(4.0, scale))
        if abs(self.map_scale - old_scale) < 1e-6:
            return

        self._render_map_image()
        self.map_canvas.config(scrollregion=self.map_canvas.bbox("all") or (0, 0, 0, 0))

    def _zoom_in(self):
        self._set_map_scale(self.map_scale * 1.2)

    def _zoom_out(self):
        self._set_map_scale(self.map_scale / 1.2)

    def _reset_zoom(self):
        self._set_map_scale(1.0)

    def _upload_map_image(self):
        path = filedialog.askopenfilename(title="Select Map Image", filetypes=[("Image Files", "*.png *.jpg *.jpeg *.bmp *.gif")])
        if not path:
            return
        self.map_view_data["image_path"] = path
        self.settings.set("map_view_data", self.map_view_data)
        self._load_map_image(path)

    def _enter_draw_mode(self):
        self.is_in_draw_mode = True
        self.current_polygon_points = []
        self.map_canvas.config(cursor="crosshair")
        self.map_canvas.bind("<Button-1>", self._on_map_left_click)
        self.map_canvas.bind("<Double-Button-1>", self._on_map_double_click)
        self.map_canvas.bind("<Button-3>", self._on_map_right_click)
        self.map_canvas.bind("<Motion>", self._on_map_mouse_move)
        self.root.bind("<Escape>", self._cancel_draw)
        self.notify("Draw Mode: Left-click to add points, double-click or Right-click to finish.", 4000)

    def _exit_draw_mode(self):
        self.is_in_draw_mode = False
        self.current_polygon_points = []
        self.map_canvas.config(cursor="")
        self.map_canvas.unbind("<Button-1>")
        self.map_canvas.unbind("<Button-3>")
        self.map_canvas.unbind("<Motion>")
        self.root.unbind("<Escape>")
        for item in self.temp_draw_items:
            self.map_canvas.delete(item)
        self.temp_draw_items = []

    def _cancel_draw(self, event=None):
        if self.is_in_draw_mode:
            self.log("Drawing cancelled by user.")
            self._exit_draw_mode()

    def _on_map_left_click(self, event):
        canvas_x, canvas_y = self.map_canvas.canvasx(event.x), self.map_canvas.canvasy(event.y)
        orig_x, orig_y = canvas_x / self.map_scale, canvas_y / self.map_scale
        self.current_polygon_points.extend([orig_x, orig_y])

        dot = self.map_canvas.create_oval(canvas_x-3, canvas_y-3, canvas_x+3, canvas_y+3,
                                          fill=self.style.lookup("Accent.TButton", "background"), outline="")
        self.temp_draw_items.append(dot)

        if len(self.current_polygon_points) > 2:
            scaled_points = [p * self.map_scale for p in self.current_polygon_points]
            line = self.map_canvas.create_line(scaled_points, fill="white", width=max(1,int(2*self.map_scale)))
            self.temp_draw_items.append(line)

        if len(self.current_polygon_points) >= 8:
            first_canvas_x = self.current_polygon_points[0] * self.map_scale
            first_canvas_y = self.current_polygon_points[1] * self.map_scale
            dist_to_start = math.hypot(canvas_x - first_canvas_x, canvas_y - first_canvas_y)
            if dist_to_start <= 12:
                self.log("Auto-completing and assigning zone: last point close to first point.")
                self._complete_draw_section()

    def _on_map_mouse_move(self, event):
        if not self.is_in_draw_mode or not self.current_polygon_points:
            return
        if self.temp_draw_items and "rubber_band" in self.map_canvas.gettags(self.temp_draw_items[-1]):
            self.map_canvas.delete(self.temp_draw_items.pop())

        last_x = self.current_polygon_points[-2] * self.map_scale
        last_y = self.current_polygon_points[-1] * self.map_scale
        cursor_canvas_x, cursor_canvas_y = self.map_canvas.canvasx(event.x), self.map_canvas.canvasy(event.y)

        line = self.map_canvas.create_line(last_x, last_y, cursor_canvas_x, cursor_canvas_y,
                                           fill="white", dash=(4, 4), tags="rubber_band")
        self.temp_draw_items.append(line)

    def _on_map_right_click(self, event):
        self._complete_draw_section()

    def _on_map_double_click(self, event):
        if self.is_in_draw_mode:
            self._complete_draw_section()
        else:
            return

    def _complete_draw_section(self):
        if len(self.current_polygon_points) < 6:
            self.notify("A shape needs at least 3 points.", 3000)
            return

        coords = self.current_polygon_points
        assigned_pins = {s['valve_pin'] for s in self.map_view_data.get('sections', [])}
        available_valves = {f"{v['name']} (Pin {v['pin']})": i for i, v in enumerate(self.valves) if v['pin'] not in assigned_pins}

        if not available_valves:
            messagebox.showwarning("No Valves", "There are no available valves to assign.", parent=self.root)
            self._exit_draw_mode()
            return

        dialog = AssignValveDialog(self.root, available_valves)
        if dialog.result:
            result = dialog.result
            valve_index = result['valve_index']
            new_name = result['name']
            valve_to_rename = self.valves[valve_index]
            self.log(f"Renaming valve '{valve_to_rename['name']}' to '{new_name}' via Map View.")
            valve_to_rename['name'] = new_name
            for plant, emoji in constants.PLANT_EMOJIS.items():
                if plant in new_name.lower():
                    valve_to_rename['icon'] = emoji
                    break
            new_section = {'coords': coords, 'valve_pin': valve_to_rename['pin']}
            self.map_view_data.setdefault('sections', []).append(new_section)
            self.settings.set('map_view_data', self.map_view_data)
            self.save_state()
            self._draw_map_sections()
            self.filter_valves()
            self.notify(f"Zone '{new_name}' created and assigned to Pin {valve_to_rename['pin']}.")

        self._exit_draw_mode()

    def _enter_edit_mode(self):
        self.is_in_edit_mode = True
        self.map_canvas.config(cursor="hand2")
        self.map_canvas.bind("<Button-1>", self._on_section_click)
        self.root.bind("<Escape>", self._exit_edit_mode)
        self.notify("Edit Mode: Click a zone to modify. Press ESC to exit.", 4000)

    def _exit_edit_mode(self, event=None):
        self.is_in_edit_mode = False
        self.map_canvas.config(cursor="")
        self.map_canvas.unbind("<Button-1>")
        self.root.unbind("<Escape>")
        self.notify("Exited Edit Mode.", 2000)

    def _on_section_click(self, event):
        canvas_x, canvas_y = self.map_canvas.canvasx(event.x), self.map_canvas.canvasy(event.y)

        clicked_items = self.map_canvas.find_closest(canvas_x, canvas_y)
        if not clicked_items:
            return

        tags = self.map_canvas.gettags(clicked_items[0])
        section_pin = None
        for tag in tags:
            if tag.startswith("section_pin_"):
                section_pin = int(tag.split("_")[-1])
                break

        if section_pin is None:
            return

        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Rename Zone...", command=lambda: self._rename_section(section_pin))
        menu.add_command(label="Delete Zone", command=lambda: self._delete_section(section_pin))
        menu.tk_popup(event.x_root, event.y_root)

    def _on_section_double_click(self, event, valve_pin):
        if self.is_in_draw_mode or self.is_in_edit_mode:
            return

        valve_index = -1
        for i, valve in enumerate(self.valves):
            if valve['pin'] == valve_pin:
                valve_index = i
                break

        if valve_index != -1:
            self.log(f"Toggling valve '{self.valves[valve_index]['name']}' via map double-click.")
            self.toggle_valve(valve_index)

    def _rename_section(self, valve_pin):
        valve = self.find_item_by_pin(valve_pin)
        if not valve:
            return

        new_name = simpledialog.askstring("Rename Zone", f"Enter new name for '{valve['name']}':", parent=self.root)
        if not new_name or not new_name.strip():
            return

        self.log(f"Renaming valve '{valve['name']}' to '{new_name}' via Map Edit.")
        valve['name'] = new_name.strip()
        self.save_state()
        self._draw_map_sections()
        self.filter_valves()
        self.notify(f"Zone renamed to '{new_name}'.")

    def _delete_section(self, valve_pin):
        valve = self.find_item_by_pin(valve_pin)
        if not valve:
            return

        if not messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete the zone '{valve['name']}' from the map?\n\n(The valve itself will not be deleted.)", parent=self.root):
            return

        sections = self.map_view_data.get('sections', [])
        self.map_view_data['sections'] = [s for s in sections if s['valve_pin'] != valve_pin]
        self.settings.set('map_view_data', self.map_view_data)
        self.log(f"Map zone for Pin {valve_pin} ('{valve['name']}') deleted.")
        self._draw_map_sections()
        self.notify(f"Zone '{valve['name']}' deleted.")

    def _draw_map_sections(self):
        self.map_canvas.delete("map_section")

        for section in self.map_view_data.get('sections', []):
            valve_pin = section['valve_pin']
            valve = self.find_item_by_pin(valve_pin)
            if not valve or not section.get('coords'):
                continue

            coords = section['coords']
            scaled_coords = [c * self.map_scale for c in coords]
            fill_color = "#81C784" if valve.get('status') else "#546E7A"
            unique_tag = f"section_pin_{valve_pin}"

            self.map_canvas.create_polygon(
                scaled_coords,
                outline=fill_color,
                fill=fill_color,
                stipple="gray50",
                width=max(1, int(2 * self.map_scale)),
                tags=("map_section", unique_tag)
            )

            avg_x = sum(scaled_coords[i] for i in range(0, len(scaled_coords), 2)) / (len(scaled_coords) / 2)
            avg_y = sum(scaled_coords[i] for i in range(1, len(scaled_coords), 2)) / (len(scaled_coords) / 2)

            self.map_canvas.create_text(
                avg_x, avg_y, text=valve['name'], fill="white",
                font=('Segoe UI', max(8, int(10 * self.map_scale)), 'bold'),
                tags=("map_section", unique_tag)
            )

            self.map_canvas.tag_bind(
                unique_tag,
                "<Double-Button-1>",
                lambda event, pin=valve_pin: self._on_section_double_click(event, pin)
            )

    def find_item_by_pin(self, pin):
        for item in self.valves + self.aux_controls:
            if item['pin'] == pin:
                return item
        return None

    def format_schedule_for_display(self, schedule_obj):
        s_type = schedule_obj.get('type', 'Fixed Time')
        if s_type == 'Cycle':
            count = schedule_obj.get('count', '∞') or '∞'
            details = f"CYCLE: ON {schedule_obj['on_m']}m, OFF {schedule_obj['off_m']}m, x{count} at {schedule_obj['time']}"
        else:
            details = f"{schedule_obj['action']} at {schedule_obj['time']}"
        if schedule_obj.get('skip_rainy'):
            details += " (☔ Skip if Rainy)"
        return details
