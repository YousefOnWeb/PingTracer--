import tkinter as tk
from tkinter import ttk
from tkinter import font
import threading
import time
import math
import queue

from traceroute_tool import trace_route 
from ping3 import ping

#functions for color interpolation

def interpolate(a, b, t):
    """Linear interpolation between two numbers a and b with t in [0,1]."""
    return a + (b - a) * t

def interpolate_color(color1, color2, t):
    """Interpolate two RGB color tuples. t should be in [0,1]."""
    r = int(interpolate(color1[0], color2[0], t))
    g = int(interpolate(color1[1], color2[1], t))
    b = int(interpolate(color1[2], color2[2], t))
    return f'#{r:02x}{g:02x}{b:02x}'

# define base colors (in RGB)
GREEN = (0, 255, 0)
YELLOW = (255, 255, 0)
RED = (255, 0, 0)
TIMEOUT_COLOR = "#0000ff"  # blue (for timeout)

# a constant for the fixed label height (in pixels)
LABEL_HEIGHT = 6

# ------------------ PingGraph Class (for one host) ------------------

class PingGraph(tk.Frame):
    def __init__(self, master, host_ip, host_hostname=None, init_graph_height=80, **kwargs):
        print(f"[INIT] Creating PingGraph for host: {host_ip} ({host_hostname})")
        super().__init__(master, bg="#222222", **kwargs)
        self.host_ip = host_ip
        self.host_hostname = host_hostname
        self.graph_height = init_graph_height  # initial canvas drawing height

        self.pings = []

        self.info_label = tk.Label(self, text=self.get_info_text(), anchor="w",
                                   bg="#222222", fg="white", font=("TkDefaultFont", 8))
        self.info_label.pack(fill=tk.X, side=tk.TOP)

        self.canvas = tk.Canvas(self, bg="black", height=self.graph_height, highlightthickness=0)
        self.canvas.pack(fill=tk.X, expand=True, side=tk.BOTTOM)

        self.line_ids = []
        self.current_index = 0

        self.canvas.bind("<Motion>", self.on_mouse_move)
        self.canvas.bind("<Leave>", self.on_mouse_leave)
        self.hover_timer = None

        self.bind("<Configure>", self.on_resize)
        print(f"[INIT COMPLETE] PingGraph initialized for {host_ip}")

    def on_resize(self, event):
        print(f"[RESIZE] Resize triggered for host: {self.host_ip}")
        total_height = self.winfo_height()

        if self.master:
            visible_graphs = [
                child for child in self.master.winfo_children()
                if isinstance(child, PingGraph) and child.winfo_viewable()
            ]
            num_graphs = len(visible_graphs) if visible_graphs else 1
        else:
            num_graphs = 1
        
        print(f"[RESIZE] Number of visible PingGraphs: {num_graphs}")
        
        if num_graphs > 1:
            new_canvas_height = (total_height - LABEL_HEIGHT)/num_graphs
            new_canvas_height = new_canvas_height * 3
        else:
            new_canvas_height = (total_height - LABEL_HEIGHT) * 0.3

        if new_canvas_height < 5:
            new_canvas_height = 5
            print("[RESIZE] Canvas height too small, setting minimum to 5")

        self.graph_height = new_canvas_height
        self.canvas.config(height=self.graph_height)
        print(f"[RESIZE COMPLETE] New canvas height: {self.graph_height}")
        self.redraw_lines()

    def redraw_lines(self):
        print(f"[REDRAW] Redrawing lines for host: {self.host_ip}")
        self.canvas.delete("all")
        canvas_width = self.canvas.winfo_width() or int(self.master.winfo_width() * 0.98)
        visible_pings = self.pings[-canvas_width:]
        print(f"[REDRAW] Total visible pings: {len(visible_pings)}")
        for idx, val in enumerate(visible_pings):
            self.draw_line(idx, val)

        self.current_index = len(visible_pings)
        print(f"[REDRAW COMPLETE] {self.current_index} lines drawn")

    def draw_line(self, x, ping_value):
        h = self.graph_height
        if ping_value is None or ping_value is False:
            lh = h
            col = TIMEOUT_COLOR
            print(f"[DRAW LINE] Timeout at x={x}")
        elif ping_value <= 0:
            lh = 0
            col = "#00ff00"
            print(f"[DRAW LINE] Ping <= 0 ms at x={x}")
        elif ping_value < 100:
            f = ping_value / 100.0
            lh = int(f * 0.5 * h)
            col = interpolate_color(GREEN, YELLOW, f)
            print(f"[DRAW LINE] Good ping ({ping_value} ms) at x={x}")
        elif ping_value < 200:
            f = (ping_value - 100) / 100.0
            lh = int((0.5 + 0.5 * f) * h)
            col = interpolate_color(YELLOW, RED, f)
            print(f"[DRAW LINE] Medium ping ({ping_value} ms) at x={x}")
        else:
            lh = h
            col = "#ff0000"
            print(f"[DRAW LINE] High ping ({ping_value} ms) at x={x}")

        y0 = h - lh
        y1 = h
        self.canvas.create_line(x, y0, x, y1, fill=col)


    def get_info_text(self, extra=""):
        visible = [p for p in self.pings if isinstance(p, (int, float)) and p > 0]
        print(f"[INFO TEXT] Generating info text for host {self.host_ip} with {len(visible)} visible pings")
        if visible:
            mini = round(min(visible), 2)
            maxi = round(max(visible), 2)
            avg = round(sum(visible)/len(visible), 2)
            last = round(visible[-1], 2) if visible else 0
            total = len(self.pings)
            losses = len([p for p in self.pings if p is None or p is False or (isinstance(p, (int, float)) and p <= 0)])
            loss_percent = round((losses/total)*100, 2) if total > 0 else 0
            jitters = [abs(visible[i]-visible[i-1]) for i in range(1, len(visible))]
            jitter = round(sum(jitters)/len(jitters), 2) if jitters else 0
            stats = f"min:{mini} max:{maxi} avg:{avg} last:{last} loss:{loss_percent}% jit:{jitter}"
        else:
            stats = "No successful pings"
        base = f"{self.host_ip}"
        if self.host_hostname:
            base += f" ({self.host_hostname})"
        base += " | " + stats
        if extra:
            base = extra
        return base

    def update_info(self):
        print(f"[INFO] Updating label for {self.host_ip}")
        self.info_label.config(text=self.get_info_text())

    def on_mouse_move(self, event):
        x = int(event.x)
        idx = x
        if idx < len(self.pings):
            value = self.pings[idx]
            ping_time = time.strftime("%H:%M:%S", time.localtime(time.time() - (len(self.pings)-idx)/app.ping_rate))
            disp = f"{self.host_ip} ({self.host_hostname or ''}) | ping: {value if isinstance(value, (int, float)) else 'timeout'} ms @ {ping_time}"
            self.info_label.config(text=disp)
            print(f"[HOVER] Showing ping {value} at index {idx} for {self.host_ip}")
            if self.hover_timer is not None:
                self.after_cancel(self.hover_timer)
            self.hover_timer = self.after(3000, self.update_info)

    def on_mouse_leave(self, event):
        print(f"[HOVER] Mouse left graph for {self.host_ip}")
        self.info_label.config(text=self.get_info_text())

    def add_ping(self, ping_value):
        print(f"[PING] Adding ping result: {ping_value} for {self.host_ip}")
        self.pings.append(ping_value)
        canvas_width = self.canvas.winfo_width() or int(app.winfo_width() * 0.98)
        if self.current_index >= canvas_width:
            print("[PING] Canvas full, redrawing...")
            self.redraw_lines()
        else:
            self.draw_line(self.current_index, ping_value)
            self.current_index += 1
        self.update_info()

# ------------------ PingRunner ------------------

class PingRunner(threading.Thread):
    def __init__(self, host_ip, ping_timeout, ping_size, rate, result_queue, index, stop_event):
        print(f"[THREAD] Initializing PingRunner for {host_ip}")
        super().__init__()
        self.host_ip = host_ip
        self.ping_timeout = ping_timeout
        self.ping_size = ping_size
        self.rate = rate
        self.result_queue = result_queue
        self.index = index
        self.stop_event = stop_event

    def run(self):
        print(f"[THREAD START] Pinging {self.host_ip}")
        try:
            result = ping(self.host_ip, timeout=self.ping_timeout, size=self.ping_size, unit="ms")
            print(f"[PING RESULT] Host: {self.host_ip}, Result: {result}")
        except Exception as e:
            print(f"[PING ERROR] Host: {self.host_ip}, Error: {e}")
            result = False
        self.result_queue.put((self.host_ip, self.index, result))

# ------------------ PingApp ------------------

class PingApp(tk.Tk):
    def __init__(self):
        print("[APP INIT] Initializing PingApp")
        super().__init__()
        self.title("Network Ping Graph")
        self.configure(bg="#222222")
        self.geometry("987x600")
        self.minsize(400, 300)
        self.ping_rate = 1.0
        self.ping_timeout = 4
        self.ping_size = 1
        self.bad_threshold = 100
        self.so_bad_threshold = 200

        self.ping_graphs = {}
        self.ping_order = []
        self.ping_index = 0
        self.result_queue = queue.Queue()
        self.running = False
        self.stop_event = threading.Event()

        self.build_options_frame()
        self.build_status_frame()
        self.build_graph_frame()
        self.after(50, self.process_ping_results)
        print("[APP INIT COMPLETE]")

    def build_options_frame(self):
        print("[UI] Building options frame")
        self.options_frame = tk.Frame(self, bg="#333333")
        self.options_frame.pack(fill=tk.X, side=tk.TOP)

        tk.Label(self.options_frame, text="Host to ping:", bg="#333333", fg="white", font=("TkDefaultFont", 8)
                ).grid(row=0, column=0, padx=2, pady=2)
        self.host_entry = tk.Entry(self.options_frame, width=20)
        self.host_entry.grid(row=0, column=1, padx=2, pady=2)
        self.host_entry.insert(0, "google.com")

        tk.Label(self.options_frame, text="Pings/sec:", bg="#333333", fg="white", font=("TkDefaultFont", 8)
                ).grid(row=0, column=2, padx=2, pady=2)
        self.rate_entry = tk.Entry(self.options_frame, width=5)
        self.rate_entry.grid(row=0, column=3, padx=2, pady=2)
        self.rate_entry.insert(0, str(self.ping_rate))
        self.rate_label = tk.Label(self.options_frame, text=self.get_rate_text(self.ping_rate),
                                   bg="#333333", fg="white", font=("TkDefaultFont", 8))
        self.rate_label.grid(row=0, column=4, padx=2, pady=2)

        tk.Label(self.options_frame, text="Timeout (s):", bg="#333333", fg="white", font=("TkDefaultFont", 8)
                ).grid(row=0, column=5, padx=2, pady=2)
        self.timeout_entry = tk.Entry(self.options_frame, width=5)
        self.timeout_entry.grid(row=0, column=6, padx=2, pady=2)
        self.timeout_entry.insert(0, str(self.ping_timeout))

        tk.Label(self.options_frame, text="Size:", bg="#333333", fg="white", font=("TkDefaultFont", 8)
                ).grid(row=0, column=7, padx=2, pady=2)
        self.size_entry = tk.Entry(self.options_frame, width=5)
        self.size_entry.grid(row=0, column=8, padx=2, pady=2)
        self.size_entry.insert(0, str(self.ping_size))

        tk.Label(self.options_frame, text="Bad threshold (ms):", bg="#333333", fg="white", font=("TkDefaultFont", 8)
                ).grid(row=1, column=0, padx=2, pady=2)
        self.bad_entry = tk.Entry(self.options_frame, width=5)
        self.bad_entry.grid(row=1, column=1, padx=2, pady=2)
        self.bad_entry.insert(0, str(self.bad_threshold))

        tk.Label(self.options_frame, text="So bad threshold (ms):", bg="#333333", fg="white", font=("TkDefaultFont", 8)
                ).grid(row=1, column=2, padx=2, pady=2)
        self.sobad_entry = tk.Entry(self.options_frame, width=5)
        self.sobad_entry.grid(row=1, column=3, padx=2, pady=2)
        self.sobad_entry.insert(0, str(self.so_bad_threshold))

        self.start_button = tk.Button(self.options_frame, text="Start", font=("TkDefaultFont", 8),
                                      command=self.start_pinging)
        self.start_button.grid(row=1, column=4, padx=2, pady=2)

        self.rate_entry.bind("<FocusOut>", lambda e: self.update_rate_label())
        
        print("[UI] Options frame ready")

    def get_rate_text(self, rate):
        if rate < 1:
            seconds = round(1 / rate, 2)
            return f"a ping every {seconds} seconds"
        else:
            return f"{rate} pings per second"

    def update_rate_label(self):
        try:
            self.ping_rate = float(self.rate_entry.get())
            if self.ping_rate < 0.001:
                self.ping_rate = 0.001
            elif self.ping_rate > 10:
                self.ping_rate = 10
            print(f"[SETTINGS] Updated ping rate to {self.ping_rate}")
        except ValueError:
            self.ping_rate = 1.0
            print("[SETTINGS] Invalid rate entry, resetting to default 1.0")
        self.rate_label.config(text=self.get_rate_text(self.ping_rate))

    def build_status_frame(self):
        print("[UI] Building status frame")
        self.status_frame = tk.Frame(self, bg="#333333")
        self.status_frame.pack_forget()

        self.stop_button = tk.Button(self.status_frame, text="Stop", font=("TkDefaultFont", 8), command=self.stop_pinging)
        self.stop_button.pack(side=tk.LEFT, padx=2, pady=2)

        self.always_on_top_var = tk.BooleanVar()
        self.always_on_top_check = tk.Checkbutton(self.status_frame, text="Always on Top",
                                                  font=("TkDefaultFont", 8), variable=self.always_on_top_var,
                                                  command=self.set_always_on_top, bg="#333333", fg="white",
                                                  selectcolor="#555555")
        self.always_on_top_check.pack(side=tk.LEFT, padx=2, pady=2)

        self.graph_checkbox_frame = tk.Frame(self.status_frame, bg="#333333")
        self.graph_checkbox_frame.pack(side=tk.LEFT, padx=2, pady=2)

        self.graph_vars = {}  # keyed by host ip
        
        print("[UI] Status frame ready")

    def build_graph_frame(self):
        self.graph_frame = tk.Frame(self, bg="#222222")
        self.graph_frame.pack(fill=tk.BOTH, expand=True)
        self.graph_frame.bind("<Configure>", self.on_graph_frame_resize)

    def on_graph_frame_resize(self, event):
        """When the group frame is resized, force each PingGraph to update its size."""
        # The PingGraphs are using pack(fill=BOTH, expand=True) so they auto-resize.
        # We just trigger a redraw in each PingGraph. (performance-risky)
        for pg in self.ping_graphs.values():
            pg.redraw_lines()

    def start_pinging(self):
        print("[START] Initiating pinging process...")
        for widget in self.graph_frame.winfo_children():
            widget.destroy()
        self.ping_graphs.clear()
        self.graph_vars.clear()
        self.ping_order.clear()

        self.ping_index = 0
        self.stop_event.clear()

        target = self.host_entry.get().strip()
        print(f"[INFO] Target entered: {target}")
        try:
            self.ping_rate = float(self.rate_entry.get())
        except ValueError:
            print("[WARN] Invalid ping rate input. Reverting to default.")
            self.ping_rate = 1.0
        try:
            self.ping_timeout = float(self.timeout_entry.get())
        except ValueError:
            print("[WARN] Invalid timeout input. Reverting to default.")
            self.ping_timeout = 4
        try:
            self.ping_size = int(self.size_entry.get())
        except ValueError:
            print("[WARN] Invalid ping size input. Reverting to default.")
            self.ping_size = 1
        try:
            self.bad_threshold = float(self.bad_entry.get())
        except ValueError:
            print("[WARN] Invalid bad threshold input. Reverting to default.")
            self.bad_threshold = 100
        try:
            self.so_bad_threshold = float(self.sobad_entry.get())
        except ValueError:
            print("[WARN] Invalid 'so bad' threshold input. Reverting to default.")
            self.so_bad_threshold = 200

        self.options_frame.pack_forget()
        self.status_frame.pack(fill=tk.X, side=tk.TOP)

        print("[INFO] Starting traceroute thread...")
        threading.Thread(target=self.do_trace_route, args=(target,), daemon=True).start()

    def do_trace_route(self, target):
        print(f"[TRACE] Starting traceroute to {target}")
        retry_start = time.time()
        hops = None
        while not hops and not self.stop_event.is_set():
            hops = trace_route(target)
            if not hops or len(hops) == 0:
                retry_seconds = int(time.time() - retry_start)
                print(f"[RETRY] Traceroute failed. Retrying... {retry_seconds}s elapsed")
                self.status_message = f"Retrying trace route... {retry_seconds}s"
                time.sleep(1)
            else:
                print(f"[SUCCESS] Traceroute completed with {len(hops)} hops.")
                break

        if hops:
            for hop in hops:
                if not hop or hop[0] is None:
                    continue
                host_ip = hop[0]
                host_hostname = hop[1] if len(hop) > 1 else None
                print(f"[GRAPH] Adding PingGraph for {host_ip} ({host_hostname})")
                pg = PingGraph(self.graph_frame, host_ip, host_hostname)
                pg.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)
                self.ping_graphs[host_ip] = pg
                self.ping_order.append(host_ip)
                var = tk.BooleanVar(value=True)
                cb = tk.Checkbutton(self.graph_checkbox_frame, text=host_ip[-4:], font=("TkDefaultFont", 8),
                                    variable=var, command=self.refresh_graph_packs,
                                    bg="#333333", fg="white", selectcolor="#555555")
                cb.pack(side=tk.LEFT)
                self.graph_vars[host_ip] = var

        if self.ping_graphs:
            print("[INFO] All graphs added. Starting ping rounds.")
            self.running = True
            self.schedule_next_ping_round()

    def refresh_graph_packs(self):
        """repack the ping graphs in the original order according to checkbox state."""
        for pg in self.graph_frame.winfo_children():
            pg.pack_forget()
        for host_ip in self.ping_order:
            if host_ip in self.graph_vars and self.graph_vars[host_ip].get():
                pg = self.ping_graphs.get(host_ip)
                if pg:
                    pg.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

    def schedule_next_ping_round(self):
        if not self.running or self.stop_event.is_set():
            print("[INFO] Ping loop stopped.")
            return

        current_index = self.ping_index
        print(f"[ROUND] Scheduling ping round {current_index}")
        for host_ip, pg in self.ping_graphs.items():
            print(f"[PING] Creating PingRunner for {host_ip} (index {current_index})")
            runner = PingRunner(host_ip, self.ping_timeout, self.ping_size, self.ping_rate,
                                self.result_queue, current_index, self.stop_event)
            runner.start()

        self.ping_index += 1

        if self.ping_index % 50 == 0:
            print("[MAINTENANCE] Cleaning unpingable graphs...")
            self.clean_unpingable()

        delay_ms = int(1000 / self.ping_rate)
        self.after(delay_ms, self.schedule_next_ping_round)

    def clean_unpingable(self):
        print("[CLEANUP] Checking for unresponsive graphs to remove...")
        successful = [pg for pg in self.ping_graphs.values() if any(
            isinstance(p, (int, float)) and p > 0 for p in pg.pings)]
        if successful and len(successful) < len(self.ping_graphs):
            remove_ips = []
            for ip, pg in list(self.ping_graphs.items()):
                if not any(isinstance(p, (int, float)) and p > 0 for p in pg.pings):
                    print(f"[REMOVE] {ip} marked for removal (no successful pings)")
                    remove_ips.append(ip)
            for ip in remove_ips:
                pg = self.ping_graphs.pop(ip)
                pg.destroy()
                if ip in self.graph_vars:
                    del self.graph_vars[ip]
                if ip in self.ping_order:
                    self.ping_order.remove(ip)
            self.refresh_graph_packs()

    def process_ping_results(self):
        try:
            while True:
                host_ip, index, ping_value = self.result_queue.get_nowait()
                print(f"[RESULT] {host_ip} index {index}: {ping_value}")
                if host_ip in self.ping_graphs:
                    value = round(ping_value, 2) if isinstance(ping_value, (int, float)) else ping_value
                    self.ping_graphs[host_ip].add_ping(value)
        except queue.Empty:
            pass
        self.after(50, self.process_ping_results)

    def stop_pinging(self):
        print("[STOP] Stopping ping process...")
        self.running = False
        self.stop_event.set()
        for widget in self.graph_frame.winfo_children():
            widget.destroy()
        self.ping_graphs.clear()
        self.ping_order.clear()
        self.status_frame.pack_forget()
        # Clean checkboxes
        for widget in self.graph_checkbox_frame.winfo_children():
            widget.destroy()
        self.graph_vars.clear()
        self.options_frame.pack(fill=tk.X, side=tk.TOP)
        self.overrideredirect(False)
        self.attributes("-topmost", False)
        self.geometry("987x600")

    def set_always_on_top(self):
        if self.always_on_top_var.get():
            self.attributes("-topmost", True)
            self.overrideredirect(True)
            self.geometry("987x300")
        else:
            self.attributes("-topmost", False)
            self.overrideredirect(False)
            self.geometry("987x600")

if __name__ == "__main__":
    app = PingApp()
    app.mainloop()
