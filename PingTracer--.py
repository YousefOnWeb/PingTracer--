import tkinter as tk
import threading
import queue

try:
    from PIL import Image, ImageDraw, ImageTk
except ImportError:
    print("Pillow library not found. Please install it: pip install Pillow")
    exit()

from config import Config
from traceroute_tool import trace_route
from ping3 import ping


# functions for color interpolation
def interpolate(a, b, t):
    """Linear interpolation between two numbers a and b with t in [0,1]."""
    return a + (b - a) * t


def interpolate_color_tuple(color1, color2, t):
    """Interpolate two RGB color tuples. t should be in [0,1]. Returns RGB tuple."""
    r = int(interpolate(color1[0], color2[0], t))
    g = int(interpolate(color1[1], color2[1], t))
    b = int(interpolate(color1[2], color2[2], t))
    return (r, g, b)


# define base colors (in RGB tuples for PIL)
GREEN = (0, 255, 0)  # good ping color as RGB tuple
YELLOW = (255, 255, 0)  # slow ping color as RGB tuple
RED = (255, 0, 0)  # bad ping color as RGB tuple
BLUE = (0, 0, 255)  # Timeout color as RGB tuple

BLACK = (0, 0, 0)  # Background color for image

# a constant for the fixed label height (in pixels)
LABEL_HEIGHT = 6


class PingGraph(tk.Frame):
    def __init__(
        self, master, host_ip, host_hostname=None, init_graph_height=80, **kwargs
    ):
        print(f"[INIT] Creating PingGraph for host: {host_ip} ({host_hostname})")
        super().__init__(master, bg="#222222", **kwargs)
        self.host_ip = host_ip
        self.host_hostname = host_hostname

        self.pings = []  # stores all historical ping values (None, False, or float ms)

        # image buffer attributes
        self.pil_image = None  # PIL Image object
        self.photo_image = None
        self.image_on_canvas = None  # ID of the image item on the canvas
        self.current_width = 0  # Tracks the canvas width for buffer size
        self.current_height = max(3, int(init_graph_height))
        self.current_buffer_index = 0  # Tracks the next drawing position in the buffer

        self.canvas = tk.Canvas(
            self, bg="black", height=self.current_height, highlightthickness=0
        )
        self.canvas.pack(fill=tk.X, expand=True, side=tk.BOTTOM)

        # create info label
        self.info_label = tk.Label(
            self,
            text=self.get_info_text(),
            anchor="w",
            bg="#222222",
            fg="white",
            font=("TkDefaultFont", 8),
        )
        self.info_label.pack(fill=tk.X, side=tk.TOP)
        # bind events
        self.canvas.bind("<Motion>", self.on_mouse_move)
        self.canvas.bind("<Leave>", self.on_mouse_leave)
        self.hover_timer = None

        self.canvas.bind("<Configure>", self.on_resize)  # bind to canvas resize

        # self.after(10, self._initial_buffer_setup) # Defer initial setup slightly

        print(f"[INIT COMPLETE] PingGraph initialized for {host_ip}")

    def _create_or_resize_buffer(self, width, height):
        """Creates or resizes the PIL Image buffer and the Tk PhotoImage."""
        if width <= 0 or height <= 0:
            print(
                f"[BUFFER WARN {self.host_ip}] Invalid dimensions for buffer: {width}x{height}"
            )
            return False

        print(f"[BUFFER {self.host_ip}] Creating/Resizing buffer to {width}x{height}")
        self.current_width = width
        self.current_height = height

        try:
            # create a new black PIL Image
            self.pil_image = Image.new("RGB", (width, height), color=BLACK)
            # create PhotoImage from the PIL image
            self.photo_image = ImageTk.PhotoImage(self.pil_image)

            # if the canvas item doesn't exist, create it
            if self.image_on_canvas is None:
                self.image_on_canvas = self.canvas.create_image(
                    0, 0, anchor=tk.NW, image=self.photo_image
                )
                print(
                    f"[BUFFER {self.host_ip}] Created canvas image item: {self.image_on_canvas}"
                )
            else:
                # otherwise, update the existing canvas item
                self.canvas.itemconfig(self.image_on_canvas, image=self.photo_image)
                print(
                    f"[BUFFER {self.host_ip}] Updated canvas image item: {self.image_on_canvas}"
                )

            return True
        except Exception as e:
            print(f"[BUFFER ERROR {self.host_ip}] Failed to create/resize buffer: {e}")
            self.pil_image = None
            self.photo_image = None
            self.image_on_canvas = None
            return False

    def on_resize(self, event=None):  # Accept event argument
        """Handles canvas resize events."""
        # Use event data if available, otherwise query widget
        new_width = event.width if event else self.canvas.winfo_width()
        new_height = event.height if event else self.canvas.winfo_height()

        # Check if size actually changed and is valid
        if (
            (
                new_width == self.current_width
                and new_height == self.current_height
                and self.pil_image
            )
            or new_width <= 0
            or new_height < 3
        ):
            print(
                f"[RESIZE SKIP/WAIT {self.host_ip}] Size {new_width}x{new_height}, Current {self.current_width}x{self.current_height}"
            )
            return

        print(f"[RESIZE {self.host_ip}] Triggered. New size: {new_width}x{new_height}")

        if not self._create_or_resize_buffer(new_width, new_height):
            return

        self.redraw_image_buffer()
        print(f"[RESIZE COMPLETE {self.host_ip}] Buffer resized and redrawn")

    def redraw_image_buffer(self):
        """Redraws the visible portion of ping history onto the PIL buffer."""
        if not self.pil_image or self.current_width < 0 or self.current_height < 0:
            print(f"[REDRAW WARN {self.host_ip}] Cannot redraw, buffer not ready.")
            return

        print(
            f"[REDRAW {self.host_ip}] Redrawing image buffer ({self.current_width}x{self.current_height})"
        )

        draw = ImageDraw.Draw(self.pil_image)
        draw.rectangle([0, 0, self.current_width, self.current_height], fill=BLACK)

        # determine which pings are visible
        visible_pings = self.pings[-self.current_width :]
        num_visible = len(visible_pings)
        print(f"[REDRAW {self.host_ip}] Drawing {num_visible} visible pings")

        # draw each visible ping onto the buffer
        for idx, val in enumerate(visible_pings):
            self.draw_line_on_image(idx, val, self.pil_image)

        # update the current buffer index
        self.current_buffer_index = (
            num_visible % self.current_width
        )  # Index within the buffer window

        # update the PhotoImage displayed on the canvas
        # important: create a new PhotoImage from the *modified* pil_image
        self.photo_image = ImageTk.PhotoImage(self.pil_image)
        if self.image_on_canvas:
            self.canvas.itemconfig(self.image_on_canvas, image=self.photo_image)
            print(f"[REDRAW {self.host_ip}] Canvas image updated.")
        else:
            # this case might happen if the canvas wasn't ready during init
            self.image_on_canvas = self.canvas.create_image(
                0, 0, anchor=tk.NW, image=self.photo_image
            )
            print(f"[REDRAW {self.host_ip}] Created canvas image item during redraw.")

    def draw_line_on_image(self, x, ping_value, pil_img):
        """Draws a single vertical line on the provided PIL Image object."""
        bad_threshold = app.config.bad_threshold
        so_bad_threshold = app.config.so_bad_threshold

        if not pil_img:
            return

        h = pil_img.height
        # Ensure the height is valid, otherwise skip drawing
        if h <= 0:
            return  # Bounds check for x too

        # if ping_value is invalid (less than 0), use blue
        if ping_value < 0:
            lh = h
            col = BLUE
        # elif ping_value is extremely low (0<->1ms), use green
        elif ping_value < 1:
            lh = 1
            col = GREEN
        # elif ping_value is extremely high (e.g., 1ms<->bad_threshold), use yellow or green
        elif ping_value < bad_threshold:
            f = ping_value / bad_threshold
            lh = max(1, int(interpolate(1, h * 0.5, f)))
            col = interpolate_color_tuple(GREEN, YELLOW, f)
        # elif ping_value is extremely high (e.g., bad_threshold<->so_bad_threshold), use red or yellow
        elif ping_value < so_bad_threshold:
            f = (ping_value - bad_threshold) / (so_bad_threshold - bad_threshold)
            lh = int(interpolate(h * 0.5, h, f))
            col = interpolate_color_tuple(YELLOW, RED, f)
        # elif ping_value is extremely high (e.g., <so_bad_threshold), use red
        else:
            lh = h
            col = RED

        lh = min(h, max(1, lh))
        y0 = h - lh
        y1 = h - 1  # Draw up to the last pixel row

        # Draw the line directly on the PIL image
        # Use ImageDraw.line for simplicity, though drawing pixel by pixel might be marginally faster for vertical lines
        try:
            ImageDraw.Draw(pil_img)
            # draw.line((x, y0, x, y1), fill=col, width=1) # width=1 is default
            # setting pixels might be faster
            for y in range(int(y0), int(y1 + 1)):
                if 0 <= y < h:  # Boundary check
                    pil_img.putpixel((x, y), col)
        except IndexError:
            print(
                f"[DRAW ERR {self.host_ip}] Index error drawing at x={x}, y=[{y0},{y1}] on image {pil_img.width}x{h}"
            )
        except Exception as e:
            print(f"[DRAW ERR {self.host_ip}] Error drawing line: {e}")

    def add_ping(self, ping_value):
        """Adds a new ping result, updates the image buffer, and refreshes the canvas."""
        print(f"[PING {self.host_ip}] Adding ping result: {ping_value}")
        self.pings.append(ping_value)

        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()

        if (
            not self.pil_image
            or self.current_width != canvas_width
            or self.current_height != canvas_height
        ):
            print(
                f"[PING WARN {self.host_ip}] Buffer mismatch or missing. Triggering resize/redraw."
            )
            # Force resize which creates buffer and redraws historical data
            # Use canvas height directly for consistency
            if not self._create_or_resize_buffer(canvas_width, canvas_height):
                print(
                    f"[PING ERR {self.host_ip}] Failed to create buffer. Cannot add ping visually."
                )
                return  # Cannot proceed without a buffer
            self.redraw_image_buffer()  # Redraw history into the new buffer
            # After redraw, current_buffer_index is set correctly
            # Fall through to potentially add the *newest* ping if space allows (unlikely after full redraw)

        if self.current_buffer_index < self.current_width:
            # --- Draw directly onto the buffer at the next spot ---
            print(
                f"[DRAW {self.host_ip}] Drawing new line at index {self.current_buffer_index}"
            )
            self.draw_line_on_image(
                self.current_buffer_index, ping_value, self.pil_image
            )
            self.current_buffer_index += 1
        else:
            # --- Shift buffer content left, clear last column, draw new line ---
            print(f"[SHIFT {self.host_ip}] Shifting buffer content left")
            # Crop image excluding the first column
            shifted_region = self.pil_image.crop(
                (1, 0, self.current_width, canvas_height)
            )
            # Paste it back, shifted one pixel to the left
            self.pil_image.paste(shifted_region, (0, 0))
            # Clear the last column (draw a black rectangle)
            draw = ImageDraw.Draw(self.pil_image)
            draw.rectangle(
                [
                    (self.current_width - 1, 0),
                    (self.current_width, canvas_height),
                ],
                fill=BLACK,
            )
            # Draw the new ping value in the last column
            self.draw_line_on_image(self.current_width - 1, ping_value, self.pil_image)
            # current_buffer_index remains >= current_width

        # --- Update the canvas ---
        # Create a new PhotoImage from the updated PIL Image *and keep reference*
        self.photo_image = ImageTk.PhotoImage(self.pil_image)
        if self.image_on_canvas:
            # Update the existing canvas item efficiently
            self.canvas.itemconfig(self.image_on_canvas, image=self.photo_image)
        else:
            print(
                f"[WARN {self.host_ip}] image_on_canvas is None during add_ping. Creating."
            )
            self.image_on_canvas = self.canvas.create_image(
                0, 0, anchor=tk.NW, image=self.photo_image, sticky="w"
            )

        self.update_info()

    def get_info_text(self, extra=""):
        # Filter visible pings based on *stored data*, not buffer index
        # The image buffer only shows a window, stats should reflect actual history
        canvas_width = self.canvas.winfo_width() or 1
        visible_ping_data = self.pings[-canvas_width:]  # Get data for visible range
        successful_visible = [
            p for p in visible_ping_data if isinstance(p, (int, float)) and p > 0
        ]

        print(
            # f"[INFO TEXT {self.host_ip}] Generating info. Total pings: {len(self.pings)}, Visible data points: {len(visible_ping_data)}"
        )

        if successful_visible:
            mini = round(min(successful_visible), 2)
            maxi = round(max(successful_visible), 2)
            avg = round(sum(successful_visible) / len(successful_visible), 2)
            last = (
                round(ping_value, 2)
                if isinstance(ping_value := self.pings[-1], (int, float))
                else "N/A"
            )
            total_visible = len(visible_ping_data)
            losses_visible = len(
                [
                    p
                    for p in visible_ping_data
                    if p is None
                    or p is False
                    or (isinstance(p, (int, float)) and p < 0)
                ]
            )
            loss_percent = (
                round((losses_visible / total_visible) * 100, 2)
                if total_visible > 0
                else 0
            )
            jitters = [
                abs(successful_visible[i] - successful_visible[i - 1])
                for i in range(1, len(successful_visible))
            ]
            jitter = round(sum(jitters) / len(jitters), 2) if jitters else 0
            stats = f"min:{mini} max:{maxi} avg:{avg} last:{last} loss:{loss_percent}% jit:{jitter}"
        else:
            stats = f"No recent data ({len(visible_ping_data)} samples)"

        base = (
            f"{self.host_hostname or self.host_ip}"  # Show hostname first if available
        )
        # base = f"{self.host_ip}"
        # if self.host_hostname:
        #     base += f" ({self.host_hostname})"
        base += " | " + stats
        if extra:  # Hover text overrides stats
            base = extra
        return base

    def update_info(self):
        print(f"[INFO {self.host_ip}] Updating label")
        self.info_label.config(text=self.get_info_text())

    def on_mouse_move(self, event):
        # Calculate index relative to the *end* of the stored pings array
        # based on the *current* canvas width
        canvas_width = self.canvas.winfo_width()
        if canvas_width <= 0:
            return

        x = int(event.x)
        # Calculate the index into the self.pings array corresponding to the mouse X
        # The rightmost pixel (canvas_width - 1) corresponds to self.pings[-1]
        # The pixel at x corresponds to self.pings[len(self.pings) - canvas_width + x]
        target_index = len(self.pings) - canvas_width + x

        if 0 <= target_index < len(self.pings):
            value = self.pings[target_index]
            # Estimate timestamp (less accurate over long runs due to potential delays)
            # time_ago_seconds = (len(self.pings) - 1 - target_index) / app.ping_rate # Seconds ago
            # ping_timestamp = time.time() - time_ago_seconds
            # ping_time_str = time.strftime("%H:%M:%S", time.localtime(ping_timestamp))
            # Simplified hover text
            value_str = (
                f"{round(value, 2)} ms"
                if isinstance(value, (int, float))
                else "Timeout/Error"
            )
            disp = f"{self.host_hostname or self.host_ip} | {value_str} at pos {x}"  # Simplified hover

            # Use the 'extra' parameter of get_info_text for hover display
            self.info_label.config(text=self.get_info_text(extra=disp))
            print(
                f"[HOVER {self.host_ip}] Index {target_index} (x={x}), Value: {value}"
            )

            if self.hover_timer is not None:
                self.after_cancel(self.hover_timer)
            self.hover_timer = self.after(2000, self.update_info)  # Revert after 2 secs

    def on_mouse_leave(self, event):
        print(f"[HOVER LEAVE {self.host_ip}]")
        if self.hover_timer is not None:
            self.after_cancel(self.hover_timer)
            self.hover_timer = None
        self.update_info()


class PingRunner(threading.Thread):
    def __init__(
        self, host_ip, ping_timeout, ping_size, rate, result_queue, index, stop_event
    ):
        print(f"[THREAD INIT] PingRunner for {host_ip}")
        super().__init__()
        self.host_ip = host_ip
        self.ping_timeout = ping_timeout
        self.ping_size = ping_size
        self.rate = rate
        self.result_queue = result_queue
        self.index = index
        self.stop_event = stop_event

    def run(self):
        print(f"[THREAD START] Pinging {self.host_ip}")  # Reduce noise
        if self.stop_event.is_set():
            print(f"[THREAD STOP] Stop event set before pinging {self.host_ip}")
            self.result_queue.put((self.host_ip, self.index, False))
            return
        try:
            timeout_sec = max(0.01, float(self.ping_timeout))
            result = ping(
                self.host_ip, timeout=timeout_sec, size=self.ping_size, unit="ms"
            )
            print(f"[PING RESULT] Host: {self.host_ip}, Result: {result}")
        except Exception as e:
            print(f"[PING ERROR] Host: {self.host_ip}, Error: {e}")  # Reduce noise
            result = False  # Indicate error/timeout consistently
        # Only put result if not stopped during ping
        if not self.stop_event.is_set():
            self.result_queue.put((self.host_ip, self.index, result))
            # else:
            print(f"[THREAD STOP] Stop event set after pinging {self.host_ip}")


class PingApp(tk.Tk):
    def __init__(self, config):
        print("[APP INIT] Initializing PingApp")
        super().__init__()
        self.title("Network Ping Graph (Buffered)")
        self.configure(bg="#222222")
        # Initial size, might be overridden by AlwaysOnTop
        self.geometry("987x600")
        self.minsize(100, 50)  # Slightly larger min size

        self.config = config  # Assuming config class is defined in config.py

        self.ping_graphs = {}  # Dictionary: host_ip -> PingGraph instance
        self.ping_order = []  # List to maintain traceroute order for display
        self.ping_round_index = 0  # Tracks the overall ping round number
        self.result_queue = queue.Queue()
        self.running = False
        self.stop_event = threading.Event()
        self._scheduled_ping_after_id = None  # Store after id for cancellation

        self.build_options_frame()
        self.build_status_frame()
        self.build_graph_frame()

        self.handle_auto_start()
        self.after(100, self.process_ping_results)  # Start processing queue
        print("[APP INIT COMPLETE]")

    def handle_auto_start(self):
        """Check if auto-start is enabled and start pinging if so."""
        if self.config.start:
            self.config.start = False
            self.start_pinging()  # Start pinging immediately

    def build_options_frame(self):
        print("[UI] Building options frame")
        self.control_frame = tk.Frame(self, bg="#333333")
        self.control_frame.pack(fill=tk.X, side=tk.TOP)

        # --- Row 0 ---
        tk.Label(
            self.control_frame,
            text="Host:",
            bg="#333333",
            fg="white",
            font=("TkDefaultFont", 8),
        ).grid(row=0, column=0, padx=2, pady=2, sticky="w")
        self.host_entry = tk.Entry(self.control_frame, width=20)
        self.host_entry.grid(row=0, column=1, padx=2, pady=2, sticky="w")
        self.host_entry.insert(0, self.config.domain)  # Default domain from config

        tk.Label(
            self.control_frame,
            text="Pings/sec:",
            bg="#333333",
            fg="white",
            font=("TkDefaultFont", 8),
        ).grid(row=0, column=2, padx=2, pady=2, sticky="w")
        self.rate_entry = tk.Entry(self.control_frame, width=5)
        self.rate_entry.grid(row=0, column=3, padx=2, pady=2)
        self.rate_entry.insert(0, str(self.config.ping_rate))
        self.rate_label = tk.Label(
            self.control_frame,
            text=self.get_rate_text(self.config.ping_rate),
            bg="#333333",
            fg="white",
            font=("TkDefaultFont", 8),
        )
        self.rate_label.grid(row=0, column=4, columnspan=3, padx=2, pady=2, sticky="w")

        self.rate_entry.bind("<FocusOut>", lambda e: self.update_rate_label())
        self.rate_entry.bind("<Return>", lambda e: self.update_rate_label())

        # --- Row 1 ---
        tk.Label(
            self.control_frame,
            text="Timeout(s):",
            bg="#333333",
            fg="white",
            font=("TkDefaultFont", 8),
        ).grid(row=1, column=0, padx=2, pady=2, sticky="w")
        self.timeout_entry = tk.Entry(self.control_frame, width=5)
        self.timeout_entry.grid(row=1, column=1, padx=2, pady=2)
        self.timeout_entry.insert(0, str(self.config.ping_timeout))

        tk.Label(
            self.control_frame,
            text="Size(B):",
            bg="#333333",
            fg="white",
            font=("TkDefaultFont", 8),
        ).grid(row=1, column=2, padx=2, pady=2, sticky="w")
        self.size_entry = tk.Entry(self.control_frame, width=5)
        self.size_entry.grid(row=1, column=3, padx=2, pady=2)
        self.size_entry.insert(0, str(self.config.ping_size))

        # --- Row 2 ---
        tk.Label(
            self.control_frame,
            text="Bad(ms):",
            bg="#333333",
            fg="white",
            font=("TkDefaultFont", 8),
        ).grid(row=2, column=0, padx=2, pady=2, sticky="w")
        self.bad_entry = tk.Entry(self.control_frame, width=5)
        self.bad_entry.grid(row=2, column=1, padx=2, pady=2)
        self.bad_entry.insert(0, str(self.config.bad_threshold))

        tk.Label(
            self.control_frame,
            text="So Bad(ms):",
            bg="#333333",
            fg="white",
            font=("TkDefaultFont", 8),
        ).grid(row=2, column=2, padx=2, pady=2, sticky="w")
        self.sobad_entry = tk.Entry(self.control_frame, width=5)
        self.sobad_entry.grid(row=2, column=3, padx=2, pady=2)
        self.sobad_entry.insert(0, str(self.config.so_bad_threshold))

        self.start_button = tk.Button(
            self.control_frame,
            text="Start",
            font=("TkDefaultFont", 9),
            command=self.start_pinging,
            width=8,
        )
        self.start_button.focus_set()
        self.start_button.grid(row=2, column=4, padx=10, pady=5)

        # Bind Enter and KP_Enter to start button
        self.bind("<Return>", lambda event: self.handle_enter())
        self.bind("<KP_Enter>", lambda event: self.handle_enter())

        print("[UI] Options frame ready")

    def get_rate_text(self, rate):
        try:
            rate = float(rate)
            if rate <= 0:
                return "Rate <= 0!"
            if rate < 1:
                seconds = round(1 / rate, 2)
                return f"~1 ping / {seconds}s"
            else:
                return f"~{rate} pings / sec"
        except ValueError:
            return "Invalid Rate"

    def update_rate_label(self):
        try:
            rate = float(self.rate_entry.get())
            if rate < 0.01:
                rate = 0.01  # Min rate
            elif rate > 50:
                rate = 50  # Max practical rate
            self.config.ping_rate = rate
            self.rate_entry.delete(0, tk.END)
            self.rate_entry.insert(0, str(self.config.ping_rate))
            print(f"[SETTINGS] Updated ping rate to {self.ping_rate}")
        except ValueError:
            # Revert to current value if input is invalid
            self.rate_entry.delete(0, tk.END)
            self.rate_entry.insert(0, str(self.config.ping_rate))
            print("[SETTINGS] Invalid rate entry, keeping current value.")
        self.rate_label.config(text=self.get_rate_text(self.config.ping_rate))

    def build_status_frame(self):
        print("[UI] Building status frame")
        self.status_frame = tk.Frame(self, bg="#333333")
        # status_frame is packed/unpacked in start/stop

        self.stop_button = tk.Button(
            self.status_frame,
            text="Stop",
            font=("TkDefaultFont", 8),
            command=self.stop_pinging,
            width=6,
        )
        self.stop_button.pack(side=tk.LEFT, padx=5, pady=2)
        self.bind(
            "<Escape>", lambda event: self.stop_button.invoke()
        )  # Allow stop with Escape key

        self.always_on_top_var = tk.BooleanVar(value=False)
        self.always_on_top_check = tk.Checkbutton(
            self.status_frame,
            text="On Top",
            font=("TkDefaultFont", 8),
            variable=self.always_on_top_var,
            command=self.set_always_on_top,
            bg="#333333",
            fg="white",
            selectcolor="#555555",
            borderwidth=0,
            highlightthickness=0,
        )
        self.always_on_top_check.pack(side=tk.LEFT, padx=5, pady=2)

        # Frame to hold the dynamic graph toggle checkboxes
        self.graph_checkbox_frame = tk.Frame(self.status_frame, bg="#333333")
        self.graph_checkbox_frame.pack(
            side=tk.LEFT, padx=5, pady=2, fill=tk.X, expand=True
        )

        self.graph_vars = {}  # Dictionary: host_ip -> tk.BooleanVar

        print("[UI] Status frame ready")

    def build_graph_frame(self):
        self.graph_frame = tk.Frame(self, bg="#222222")
        self.graph_frame.pack(fill=tk.BOTH, expand=True, side=tk.BOTTOM)

    # def on_graph_frame_resize(self, event): # Removed - handled by individual graphs now
    def handle_enter(self):
        """Invoke Start or focus Host if stopped."""
        if not self.running:
            self.start_button.invoke()

    def handle_escape(self):
        """Invoke Stop if running."""
        if self.running:
            self.stop_button.invoke()

    def _read_settings(self):
        """Reads and validates settings from entry widgets."""
        print("[SETTINGS] Reading settings from UI")
        try:
            # Rate is updated via update_rate_label on focus out/enter
            self.config.ping_rate = float(self.rate_entry.get())
            if not (0.01 <= self.config.ping_rate <= 50):
                raise ValueError("Rate out of bounds")
        except ValueError:
            print("[WARN] Invalid ping rate. Using default:", self.config.ping_rate)
            self.rate_entry.delete(0, tk.END)
            self.rate_entry.insert(0, str(self.config.ping_rate))
            self.update_rate_label()  # Also update text label

        try:
            self.config.ping_timeout = float(self.timeout_entry.get())
            if not (0.1 <= self.config.ping_timeout <= 10):
                raise ValueError("Timeout out of bounds")
        except ValueError:
            print("[WARN] Invalid timeout. Using default:", self.config.ping_timeout)
            self.config.ping_timeout = 1.0
            self.timeout_entry.delete(0, tk.END)
            self.timeout_entry.insert(0, str(self.config.ping_timeout))

        try:
            self.config.ping_size = int(self.size_entry.get())
            if not (0 <= self.config.ping_size <= 1400):
                raise ValueError("Size out of bounds")  # Typical MTU limit
        except ValueError:
            print("[WARN] Invalid ping size. Using default:", self.config.ping_size)
            self.config.ping_size = 1
            self.size_entry.delete(0, tk.END)
            self.size_entry.insert(0, str(self.config.ping_size))

        try:
            self.config.bad_threshold = float(self.bad_entry.get())
            if not (1 <= self.config.bad_threshold <= 5000):
                raise ValueError("Bad threshold out of bounds")
        except ValueError:
            print(
                "[WARN] Invalid bad threshold. Using default:",
                self.config.bad_threshold,
            )
            self.config.bad_threshold = 100
            self.bad_entry.delete(0, tk.END)
            self.bad_entry.insert(0, str(self.config.bad_threshold))

        try:
            self.config.so_bad_threshold = float(self.sobad_entry.get())
            if not (self.config.bad_threshold < self.config.so_bad_threshold <= 5000):
                raise ValueError("So Bad threshold invalid")
        except ValueError:
            print(
                "[WARN] Invalid 'so bad' threshold. Using default:",
                self.config.so_bad_threshold,
            )
            self.so_bad_threshold = max(
                self.config.bad_threshold + 50, 200
            )  # Ensure > bad_threshold
            self.sobad_entry.delete(0, tk.END)
            self.sobad_entry.insert(0, str(self.config.so_bad_threshold))

        # Ensure bad < so_bad
        if self.config.bad_threshold >= self.config.so_bad_threshold:
            print("[WARN] Bad threshold >= So Bad threshold. Adjusting So Bad.")
            self.so_bad_threshold = self.config.bad_threshold + 50
            self.sobad_entry.delete(0, tk.END)
            self.sobad_entry.insert(0, str(self.config.so_bad_threshold))

    def start_pinging(self):
        print("[START] Initiating pinging process...")
        if self.running:
            print("[WARN] Already running, stop first.")
            return

        # --- Clear previous state ---
        self.stop_pinging(
            clear_ui=False
        )  # Stop backend tasks, but don't hide status yet
        self.stop_event.clear()  # Ensure stop flag is reset

        for widget in self.graph_frame.winfo_children():
            widget.destroy()
        self.ping_graphs.clear()
        for widget in self.graph_checkbox_frame.winfo_children():
            widget.destroy()
        self.graph_vars.clear()
        self.ping_order.clear()
        self.ping_round_index = 0
        # Clear the queue (optional, good practice)
        while not self.result_queue.empty():
            try:
                self.result_queue.get_nowait()
            except queue.Empty:
                break
        # --- End Clear state ---

        target = self.host_entry.get().strip()
        if not target:
            print("[ERROR] Host cannot be empty.")
            # Optionally show a message box
            return

        print(f"[INFO] Target entered: {target}")
        self._read_settings()  # Read and validate settings from UI

        # Switch UI
        self.control_frame.pack_forget()
        self.status_frame.pack(fill=tk.X, side=tk.TOP)
        self.start_button.config(state=tk.DISABLED)  # Disable start while running
        self.stop_button.config(state=tk.NORMAL)

        print("[INFO] Starting traceroute thread...")
        self.status_label = tk.Label(
            self.graph_frame,
            text=f"Tracing route to {target}...",
            bg="#222222",
            fg="grey",
        )
        self.status_label.pack(pady=20)
        self.graph_frame.update_idletasks()  # Make label appear

        threading.Thread(
            target=self.do_trace_route, args=(target,), daemon=True
        ).start()

    def do_trace_route(self, target):
        print(f"[TRACE] Starting traceroute to {target}")
        hops = None
        try:
            hops = trace_route(
                target
            )  # Assuming this returns a list of (ip, hostname) tuples or None
        except Exception as e:
            print(f"[TRACE ERROR] Error during trace_route: {e}")
            hops = None  # Ensure hops is None on error

        # --- Update UI from the main thread using 'after' ---
        self.after(0, self._process_traceroute_results, hops, target)

    def _process_traceroute_results(self, hops, target):
        # This runs in the Tkinter main thread
        print("[TRACE] Processing traceroute results in main thread.")
        if hasattr(self, "status_label") and self.status_label.winfo_exists():
            self.status_label.destroy()  # Remove "Tracing..." label

        if self.stop_event.is_set():
            print("[TRACE] Stop event set during traceroute, aborting.")
            self.stop_pinging()  # Go back to initial state
            return

        if not hops:
            print(f"[TRACE FAIL] Traceroute to {target} failed or returned no hops.")
            # Show error message
            error_label = tk.Label(
                self.graph_frame,
                text=f"Failed to trace route to {target}.\nCheck hostname or network.",
                bg="#222222",
                fg="red",
            )
            error_label.pack(pady=20)
            self.after(5000, self.stop_pinging)  # Stop after 5s
            return

        print(f"[TRACE SUCCESS] Traceroute completed with {len(hops)} hops.")
        initial_height = max(
            30, self.graph_frame.winfo_height() / len(hops) if len(hops) > 0 else 80
        )

        # Clear checkboxes again just in case
        for widget in self.graph_checkbox_frame.winfo_children():
            widget.destroy()
        self.graph_vars.clear()

        valid_hops_count = 0
        for hop_index, hop in enumerate(hops):
            if self.stop_event.is_set():
                break  # Check stop event during setup
            if not hop or not hop[0]:  # Skip hops with no IP
                print(f"[GRAPH SKIP] Skipping invalid hop: {hop}")
                continue

            host_ip = hop[0]
            host_hostname = (
                hop[1] if len(hop) > 1 and hop[1] and hop[1] != host_ip else None
            )  # Use None if hostname is same as IP or missing
            hop_label = (
                f"{hop_index + 1}: {host_hostname or host_ip}"  # Label for checkbox
            )
            short_label = host_ip.split(".")[-1]  # Use last octet for short label

            print(f"[GRAPH] Adding PingGraph for {host_ip} ({host_hostname})")
            pg = PingGraph(
                self.graph_frame,
                host_ip,
                host_hostname,
                init_graph_height=initial_height,
            )
            # Pack immediately - resize/redraw will happen via configure events
            pg.pack(
                fill=tk.X, expand=False, padx=0, pady=1
            )  # Fill X, but don't expand height initially
            self.ping_graphs[host_ip] = pg
            self.ping_order.append(host_ip)

            # Add toggle checkbox
            var = tk.BooleanVar(value=True)
            cb = tk.Checkbutton(
                self.graph_checkbox_frame,
                text=short_label,
                font=("TkFixedFont", 7),  # Fixed font, smaller
                variable=var,
                command=lambda ip=host_ip: self.toggle_graph_visibility(ip),
                bg="#333333",
                fg="white",
                selectcolor="#555555",
                borderwidth=0,
                highlightthickness=0,
                padx=1,
                pady=0,
                indicatoron=False,  # Make it look like a button
                relief=tk.RAISED,
                width=4,
            )
            cb.pack(side=tk.LEFT, padx=1)
            self.graph_vars[host_ip] = (var, cb)  # Store var and checkbox itself
            valid_hops_count += 1

        if self.stop_event.is_set():
            print("[TRACE] Stop event set during graph creation, aborting.")
            self.stop_pinging()
            return

        if valid_hops_count == 0:
            print("[ERROR] No valid hops found after traceroute processing.")
            error_label = tk.Label(
                self.graph_frame,
                text="No pingable hops found.",
                bg="#222222",
                fg="orange",
            )
            error_label.pack(pady=20)
            self.after(4000, self.stop_pinging)
            return

        # Adjust packing now that all graphs are added
        self.refresh_graph_packs()

        print("[INFO] All graphs added. Starting ping rounds.")
        self.running = True
        self.schedule_next_ping_round()

    def toggle_graph_visibility(self, host_ip):
        """Handles checkbox clicks to show/hide graphs."""
        if host_ip not in self.ping_graphs or host_ip not in self.graph_vars:
            return

        var, cb = self.graph_vars[host_ip]
        is_visible = var.get()

        pg = self.ping_graphs[host_ip]
        if is_visible:
            print(f"[TOGGLE {host_ip}] Showing graph")
            cb.config(relief=tk.RAISED)  # Update checkbox appearance
        else:
            print(f"[TOGGLE {host_ip}] Hiding graph")
            pg.pack_forget()
            cb.config(relief=tk.SUNKEN)

        # Instead of repacking just one, repack all visible to maintain order easily
        self.refresh_graph_packs()

    def refresh_graph_packs(self):
        """Repacks visible PingGraphs in the original traceroute order."""
        print("[PACK] Refreshing graph packing order.")
        # Temporarily hide all
        for pg in self.ping_graphs.values():
            pg.pack_forget()

        visible_graphs = []
        for host_ip in self.ping_order:
            if host_ip in self.graph_vars:
                var, _ = self.graph_vars[host_ip]
                if var.get():  # Check the variable state
                    pg = self.ping_graphs.get(host_ip)
                    if pg:
                        visible_graphs.append(pg)

        # Pack only the visible ones
        num_visible = len(visible_graphs)
        print(f"[PACK] Packing {num_visible} visible graphs.")
        for pg in visible_graphs:
            # Make them expand equally in the available space
            pg.pack(fill=tk.BOTH, expand=True, padx=0, pady=1)

        # Trigger resize/redraw on packed graphs if needed (might be redundant)
        # self.graph_frame.update_idletasks()
        # for pg in visible_graphs:
        #    pg.on_resize()

    def schedule_next_ping_round(self):
        """Schedules the next batch of pings."""
        if self._scheduled_ping_after_id:  # Cancel previous schedule if any
            self.after_cancel(self._scheduled_ping_after_id)
            self._scheduled_ping_after_id = None

        if not self.running or self.stop_event.is_set():
            print("[SCHEDULER] Pinging stopped.")
            self.running = False
            # Ensure buttons are correct state if stopped externally
            if hasattr(self, "start_button"):
                self.start_button.config(state=tk.NORMAL)
            if hasattr(self, "stop_button"):
                self.stop_button.config(state=tk.DISABLED)
            return

        # --- Start the pings for this round ---
        current_round = self.ping_round_index
        print(f"[ROUND {current_round}] Scheduling pings")
        hosts_to_ping = list(
            self.ping_graphs.keys()
        )  # Ping all hosts currently tracked

        if not hosts_to_ping:
            print("[SCHEDULER] No hosts to ping. Stopping!")
            self.stop_pinging()
            return

        active_threads = []
        for host_ip in hosts_to_ping:
            if self.stop_event.is_set():
                break
            print(f"[PING START {host_ip}] Round {current_round}")
            runner = PingRunner(
                host_ip,
                self.config.ping_timeout,
                self.config.ping_size,
                self.config.ping_rate,
                self.result_queue,
                current_round,
                self.stop_event,
            )
            runner.start()
            active_threads.append(runner)

        self.ping_round_index += 1

        # --- Schedule the *next* round ---
        delay_ms = max(
            10, int(1000 / self.config.ping_rate)
        )  # Ensure minimum delay > 0
        print(f"[SCHEDULER] Next round in {delay_ms} ms")  # Reduce noise
        self._scheduled_ping_after_id = self.after(
            delay_ms, self.schedule_next_ping_round
        )

        # Optional: Cleanup threads (usually handled by daemon=True, but explicit join can be safer)
        # threading.Thread(target=self._join_threads, args=(active_threads,), daemon=True).start()

        # Clean unpingable graphs periodically (less frequent)
        if (
            self.ping_round_index > 10 and self.ping_round_index % 100 == 0
        ):  # After 10 rounds, check every 100
            print("[MAINTENANCE] Scheduling check for unpingable graphs...")
            self.after(1000, self.clean_unpingable)  # Check 1 sec after round start

    # Optional thread joiner
    # def _join_threads(self, threads):
    #     for t in threads:
    #         t.join(timeout=self.ping_timeout + 1) # Wait slightly longer than ping timeout

    def clean_unpingable(self):
        """Removes graphs that haven't received any successful pings recently."""
        if not self.running:
            return  # Don't clean if stopped

        print("[CLEANUP] Checking for unresponsive graphs...")
        remove_ips = []
        kept_ips = []

        if len(self.ping_graphs) <= 1:
            print("[CLEANUP] Skipping, only one graph remains.")
            return  # Don't remove the last graph

        for ip, pg in list(self.ping_graphs.items()):
            # Check if *any* successful ping ever occurred
            has_ever_succeeded = any(
                isinstance(p, (int, float)) and p > 0 for p in pg.pings
            )

            # Check after at least 10 attempts
            if not has_ever_succeeded and len(pg.pings) > 10:
                print(
                    f"[REMOVE] {ip} marked for removal (never successful after {len(pg.pings)} attempts)"
                )
                remove_ips.append(ip)
            else:
                kept_ips.append(ip)

        if not remove_ips:
            print("[CLEANUP] No unresponsive graphs found.")
            return

        # if traceroute returned only bad ones, return
        if len(kept_ips) == 0 and len(remove_ips) > 0:
            print("[CLEANUP] All graphs are unresponsive, keeping them for now.")
            return

        print(f"[CLEANUP] Removing {len(remove_ips)} graphs: {remove_ips}")
        for ip in remove_ips:
            if ip in self.ping_graphs:
                pg = self.ping_graphs.pop(ip)
                pg.destroy()  # Destroy the frame and canvas
            if ip in self.graph_vars:
                _, cb = self.graph_vars.pop(ip)
                cb.destroy()  # Destroy the checkbox
            if ip in self.ping_order:
                try:
                    self.ping_order.remove(ip)
                except ValueError:
                    pass

        self.refresh_graph_packs()

    def process_ping_results(self):
        """Processes results from the queue and updates graphs."""
        try:
            while True:  # Process all available results
                host_ip, round_idx, ping_value = self.result_queue.get_nowait()

                print(f"[RESULT] {host_ip} Round {round_idx}: {ping_value}")

                if host_ip in self.ping_graphs:
                    value = False
                    if isinstance(ping_value, (int, float)) and ping_value > 0.0:
                        value = round(ping_value, 2)

                    self.ping_graphs[host_ip].add_ping(value)
                else:
                    print(f"[WARN] Received result for unknown/removed host: {host_ip}")
        except queue.Empty:
            pass
        except Exception as e:
            print(f"[ERROR] Exception in process_ping_results: {e}")

        # Reschedule check even if errors occur
        self.after(50, self.process_ping_results)  # Check queue every 50ms

    def stop_pinging(self, clear_ui=True):
        print("[STOP] Stopping ping process...")
        self.running = False
        self.stop_event.set()  # Signal threads to stop

        if self._scheduled_ping_after_id:  # Cancel any scheduled next round
            self.after_cancel(self._scheduled_ping_after_id)
            self._scheduled_ping_after_id = None

        if clear_ui:
            # Destroy graphs and checkboxes
            for widget in self.graph_frame.winfo_children():
                widget.destroy()
            for widget in self.graph_checkbox_frame.winfo_children():
                widget.destroy()
            self.graph_vars.clear()

            # Switch back to options view
            self.status_frame.pack_forget()
            self.control_frame.pack(fill=tk.X, side=tk.TOP)

            # Reset always on top if it was set
            if self.always_on_top_var.get():
                self.always_on_top_var.set(False)
                self.set_always_on_top()  # Call the method to apply the change

        # Always reset button states
        if hasattr(self, "start_button"):
            self.start_button.config(state=tk.NORMAL)
        if hasattr(self, "stop_button"):
            self.stop_button.config(state=tk.DISABLED)

        # Clear internal state
        self.ping_graphs.clear()
        self.ping_order.clear()

        print("[STOP] Pinging stopped.")

    def set_always_on_top(self):
        is_on_top = self.always_on_top_var.get()
        print(f"[UI] Setting Always on Top: {is_on_top}")
        self.attributes("-topmost", is_on_top)

    def on_close(self):
        """Gracefully stop threads and close the app."""
        print("Closing application...")
        self.stop_pinging()
        self.destroy()


if __name__ == "__main__":
    config_parser = Config()
    args = config_parser.parse_args()
    app = PingApp(args)
    app.protocol("WM_DELETE_WINDOW", app.on_close)  # Handle window close button
    try:
        app.mainloop()
    except KeyboardInterrupt:
        print("KeyboardInterrupt detected, closing.")
        app.on_close()
