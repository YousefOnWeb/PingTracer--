import tkinter as tk
import threading
import queue
import time # Added for timestamps

try:
    from PIL import Image, ImageDraw, ImageTk
except ImportError:
    print("Pillow library not found. Please install it: pip install Pillow")
    exit()

# Assuming config.py and traceroute_tool.py exist (in the same directory) and work as expected
from config import Config
from traceroute_tool import trace_route
from ping3 import ping


# functions for color interpolation
def interpolate(a, b, t):
    return a + (b - a) * t

def interpolate_color_tuple(color1, color2, t):
    r = int(interpolate(color1[0], color2[0], t))
    g = int(interpolate(color1[1], color2[1], t))
    b = int(interpolate(color1[2], color2[2], t))
    return (r, g, b)

# define base colors
GREEN = (0, 255, 0)
YELLOW = (255, 255, 0)
RED = (255, 0, 0)
BLUE = (0, 0, 255)
BLACK = (0, 0, 0)

class PingGraph(tk.Frame):
    def __init__(
        self, master, app, host_ip, host_hostname=None, **kwargs
    ):
        print(f"[INIT] Creating PingGraph for host: {host_ip} ({host_hostname})")
        super().__init__(master, bg="#222222", **kwargs)
        self.app = app # Store reference to the main app
        self.host_ip = host_ip
        self.host_hostname = host_hostname

        self.pings = []  # stores all historical ping values for this host (None, False, or float ms)

        # --- Ping Statistics Attributes ---
        self.stat_count = 0         # Number of successful pings
        self.stat_sum = 0.0         # Sum of successful ping times
        self.stat_min = float('inf')
        self.stat_max = float('-inf')
        self.stat_loss_count = 0    # Number of timeouts/errors
        self.stat_last_valid_ping = None # For jitter calculation
        self.stat_jitter_sum = 0.0
        self.stat_jitter_count = 0  # Number of jitter values calculated
        self.label_font_normal = ("TkDefaultFont", 8)
        self.label_font_tiny = ("TkDefaultFont", 4) # For compact mode option (terrible idea but i will choose to leave it for now)

        # image buffer attributes (image holds a graph)
        self.pil_image = None # PIL Image object
        self.photo_image = None
        self.image_on_canvas = None # ID of the image item on the canvas
        self.current_width = 0 # Tracks the canvas width for buffer size
        self.current_height = 3 # Start with a minimal height, packing will expand it
        self.current_buffer_index = 0 # Tracks the next drawing position in the buffer (horizontal position of next ping line on the graph buffer)

        # --- UI Element Creation and Packing ---
        # create info label first and pack it to the top of the 'PingGraph'
        self.info_label = tk.Label(
            self,
            text=self.get_info_text(),
            anchor="w",
            bg="#222222",
            fg="white",
            font=self.label_font_normal, # Use normal font (tiny font is meant for on-top mode)
        )
        self.info_label.pack(side=tk.TOP, fill=tk.X, expand=False, padx=1, pady=0) # Fill X, in other words, don't expand vertically

        # create canvas second (below info label) and pack it to fill/occupy the rest of the PingGraph
        self.canvas = tk.Canvas(
            self, bg="black", height=self.current_height, highlightthickness=0
        )
        # graph canvas fills BOTH axes and expand vertically to take available space
        self.canvas.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True)

        # bind events
        self.canvas.bind("<Motion>", self.on_mouse_move)
        self.canvas.bind("<Leave>", self.on_mouse_leave)
        self.hover_timer = None

        self.canvas.bind("<Configure>", self.on_resize) # bind function on_resize to canvas resize

        print(f"[INIT COMPLETE] PingGraph initialized for {host_ip}") 

    def _create_or_resize_buffer(self, width, height):
        """Creates or resizes the PIL Image buffer and the Tk PhotoImage."""
        # ensure it's at least 1 pixel for drawing
        height = max(1, height)
        if width <= 0:
            print(f"[BUFFER WARN {self.host_ip}] Invalid width for buffer: {width}") 
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
                print(f"[BUFFER {self.host_ip}] Created canvas image item: {self.image_on_canvas}") 
            else:
                self.canvas.itemconfig(self.image_on_canvas, image=self.photo_image)
                print(f"[BUFFER {self.host_ip}] Updated canvas image item: {self.image_on_canvas}") 

            return True
        except Exception as e:
            print(f"[BUFFER ERROR {self.host_ip}] Failed to create/resize buffer: {e}")
            self.pil_image = None
            self.photo_image = None
            self.image_on_canvas = None
            return False

    def on_resize(self, event=None):
        """Handles canvas resize events."""
        # Use event data if available, otherwise query widget
        new_width = event.width if event else self.canvas.winfo_width()
        new_height = event.height if event else self.canvas.winfo_height()

        # Ensure height is at least 1 for buffer creation
        new_height = max(1, new_height)
        
        # Check if size changed and is valid
        if (
            (new_width == self.current_width and new_height == self.current_height and self.pil_image)
            or new_width <= 0
        ):
            print(f"[RESIZE SKIP/WAIT {self.host_ip}] Size {new_width}x{new_height}, Current {self.current_width}x{self.current_height}") 
            return

        print(f"[RESIZE {self.host_ip}] Triggered. New size: {new_width}x{new_height}") 

        if not self._create_or_resize_buffer(new_width, new_height):
            return

        self.redraw_image_buffer()
        print(f"[RESIZE COMPLETE {self.host_ip}] Buffer resized and redrawn") 

    def redraw_image_buffer(self):
        """Redraws the visible portion of ping history onto the PIL buffer."""
        if not self.pil_image or self.current_width <= 0 or self.current_height <= 0:
            print(f"[REDRAW WARN {self.host_ip}] Cannot redraw, buffer not ready.") 
            return

        print(f"[REDRAW {self.host_ip}] Redrawing image buffer ({self.current_width}x{self.current_height})") 

        draw = ImageDraw.Draw(self.pil_image)
        draw.rectangle([0, 0, self.current_width, self.current_height], fill=BLACK) # Clear buffer

        # Determine what amount of last pings should be visible (most recent ones up to buffer width, since 1 ping is 1-pixel wide vertical line)
        visible_pings = self.pings[-self.current_width :]
        num_visible = len(visible_pings)
        print(f"[REDRAW {self.host_ip}] Drawing {num_visible} visible pings") 

        # Draw each visible ping onto the *new* buffer starting from the left (index 0)
        for buffer_x, val in enumerate(visible_pings):
            # Draw the ping value at the calculated buffer_x coordinate
            self.draw_line_on_image(buffer_x, val, self.pil_image)

        # --- Update the current buffer index correctly ---
        # After a full redraw, the buffer is filled from the left up to 'num_visible' pings.
        # The *next* drawing position (if adding a new ping without shifting)
        # would be at index 'num_visible'.
        # If num_visible == current_width, the buffer is full of ping lines.
        self.current_buffer_index = num_visible # Index for the *next* potential draw

        # Update the PhotoImage displayed on the canvas
        self.photo_image = ImageTk.PhotoImage(self.pil_image)
        if self.image_on_canvas:
            self.canvas.itemconfig(self.image_on_canvas, image=self.photo_image)
            print(f"[REDRAW {self.host_ip}] Canvas image updated.") 
        else:
            self.image_on_canvas = self.canvas.create_image(
                0, 0, anchor=tk.NW, image=self.photo_image
            )
            print(f"[REDRAW {self.host_ip}] Created canvas image item during redraw.") 

    def draw_line_on_image(self, x, ping_value, pil_img):
        """Draws a single vertical ping line on the provided PIL Image object."""
        # --- Use thresholds from the config ---
        # Ensure app reference exists before accessing config
        if not hasattr(self.app, 'config'): return
        bad_threshold = self.app.config.bad_threshold
        so_bad_threshold = self.app.config.so_bad_threshold

        if not pil_img: return
        w = pil_img.width
        h = pil_img.height
        if h <= 0 or not (0 <= x < w) : return # Bounds check for x and h

        # Color/Height calculation (uses config)
        col = BLACK # Default/fallback
        lh = 0 # Default line height
        if ping_value is False or ping_value is None or (isinstance(ping_value, (int, float)) and ping_value < 0): # Explicit check for False/None/Negative
            lh = h
            col = BLUE
        elif isinstance(ping_value, (int, float)): # Only proceed if numeric and positive
            if ping_value < 1:
                lh = 1
                col = GREEN
            elif ping_value < bad_threshold:
                f = ping_value / bad_threshold
                lh = max(1, int(interpolate(1, h * 0.5, f)))
                col = interpolate_color_tuple(GREEN, YELLOW, f)
            elif ping_value < so_bad_threshold:
                f = (ping_value - bad_threshold) / (so_bad_threshold - bad_threshold)
                lh = int(interpolate(h * 0.5, h, f))
                col = interpolate_color_tuple(YELLOW, RED, f)
            else: # >= so_bad_threshold
                lh = h
                col = RED
        else: # should not happen if input is cleaned
            lh = h
            col = BLUE # Treat other unexpected types as timeout

        lh = min(h, max(1, int(lh))) # Ensure line height is within bounds and integer
        y0 = h - lh
        y1 = h - 1 # Draw up to the last pixel row

        # Draw using putpixel for potentially better performance on single columns
        try:
            # Avoid creating ImageDraw object repeatedly if possible, but safer here
            # For single column, putpixel is fine
            for y in range(y0, y1 + 1):
                if 0 <= y < h: # Double check y bounds
                    pil_img.putpixel((int(x), y), col)
        except IndexError:
            print(f"[DRAW ERR {self.host_ip}] Index error drawing at x={x}, y=[{y0},{y1}] on image {w}x{h}")
        except Exception as e:
            print(f"[DRAW ERR {self.host_ip}] Error drawing line: {e}")


    def add_ping(self, ping_value):
        """Adds a new ping result, updates stats in O(1), updates the image buffer, and refreshes the canvas."""
        print(f"[PING {self.host_ip}] Adding ping result: {ping_value}") 
        self.pings.append(ping_value)

        # --- Update Statistics ---
        total_pings = len(self.pings)
        if isinstance(ping_value, (int, float)) and ping_value >= 0: # Count 0ms as success for stats
            self.stat_count += 1
            self.stat_sum += ping_value
            self.stat_min = min(self.stat_min, ping_value)
            self.stat_max = max(self.stat_max, ping_value)
            if self.stat_last_valid_ping is not None:
                jitter = abs(ping_value - self.stat_last_valid_ping)
                self.stat_jitter_sum += jitter
                self.stat_jitter_count += 1
            self.stat_last_valid_ping = ping_value
        else: # Timeout or error (None, False, < 0)
            self.stat_loss_count += 1
        # --- End Statistics Update ---


        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()

        # Ensure buffer exists and matches current canvas dimensions
        if (not self.pil_image or self.current_width != canvas_width or self.current_height != canvas_height):
            print(f"[PING WARN {self.host_ip}] Buffer mismatch/missing. Forcing resize/redraw.") 
            if not self._create_or_resize_buffer(canvas_width, max(1, canvas_height)): # Ensure height >= 1
                print(f"[PING ERR {self.host_ip}] Failed to create buffer. Cannot add ping visually.")
                return
            self.redraw_image_buffer() # Redraw history; current_buffer_index is reset here

        # --- Drawing Logic ---
        num_pings = len(self.pings)

        if not self.pil_image: return # Cannot draw without a buffer

        if num_pings <= self.current_width:
            # Buffer is not full yet, draw at the next position
            draw_x = num_pings - 1
            print(f"[DRAW {self.host_ip}] Drawing new line at index {draw_x}") 
            self.draw_line_on_image(draw_x, ping_value, self.pil_image)
            self.current_buffer_index = num_pings # Next index is simply the new count
        else:
            # Buffer is full, shift image left, draw at the end
            print(f"[SHIFT {self.host_ip}] Shifting buffer content left") 
            if self.current_width > 1: # Avoid cropping if width is 1
                shifted_region = self.pil_image.crop((1, 0, self.current_width, self.current_height))
                self.pil_image.paste(shifted_region, (0, 0))
            # Clear the last column before drawing
            draw = ImageDraw.Draw(self.pil_image)
            draw.rectangle([(self.current_width - 1, 0),(self.current_width, self.current_height)],fill=BLACK)
            # Draw the new ping value in the last column
            self.draw_line_on_image(self.current_width - 1, ping_value, self.pil_image)
            # current_buffer_index remains >= current_width (conceptually)

        # --- Update Canvas ---
        self.photo_image = ImageTk.PhotoImage(self.pil_image)
        if self.image_on_canvas:
            self.canvas.itemconfig(self.image_on_canvas, image=self.photo_image)
        else:
            print(f"[WARN {self.host_ip}] image_on_canvas is None during add_ping. Creating.") 
            self.image_on_canvas = self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo_image)

        # Update text info only if not in compact mode where labels are hidden
        if not self.app.is_compact_mode or self.app.compact_mode_label_behavior == 'tiny':
            self.update_info()


    def get_info_text(self, extra=""):
        """Generates the text for the info label, using all historical data for stats (not only visible pings)."""
        # --- Use calculated statistics ---
        total_pings = self.stat_count + self.stat_loss_count

        if self.stat_count > 0: # If we have successful pings
            # Use safe division
            avg = round(self.stat_sum / self.stat_count, 2) if self.stat_count > 0 else 0
            mini = round(self.stat_min, 2) if self.stat_min != float('inf') else "N/A"
            maxi = round(self.stat_max, 2) if self.stat_max != float('-inf') else "N/A"
            # Get last value directly from pings array
            last_val = self.pings[-1] if self.pings else None
            last = round(last_val, 2) if isinstance(last_val, (int, float)) and last_val >= 0 else "N/A"
            loss_percent = round((self.stat_loss_count / total_pings) * 100, 1) if total_pings > 0 else 0
            jitter = round(self.stat_jitter_sum / self.stat_jitter_count, 2) if self.stat_jitter_count > 0 else 0

            stats = f"min:{mini} max:{maxi} avg:{avg} last:{last} loss:{loss_percent}% jit:{jitter}"
        else: # No successful pings yet
            loss_percent = round((self.stat_loss_count / total_pings) * 100, 1) if total_pings > 0 else 0
            stats = f"loss:{loss_percent}% ({total_pings} total attempts)"

        # --- Host Info: IP (Hostname) or IP ---
        if self.host_hostname:
            host_info = f"{self.host_ip} ({self.host_hostname})"
        else:
            host_info = f"{self.host_ip}"

        # --- Construct final text ---
        if extra: # Hover text overrides stats
            final_text = extra
        else:
            final_text = f"{host_info} | {stats}"

        return final_text

    def update_info(self):
        print(f"[INFO {self.host_ip}] Updating label") 
        # Update only if the label hasn't been hidden by compact mode
        if self.info_label.winfo_ismapped():
            self.info_label.config(text=self.get_info_text())

    def on_mouse_move(self, event):
        """Handles mouse movement over the canvas to display ping details."""
        canvas_width = self.canvas.winfo_width()
        if canvas_width <= 0: return

        num_pings = len(self.pings)
        if num_pings == 0: return # No pings yet

        x = int(event.x)
        target_index = -1 # Default to invalid index

        # --- Corrected Index Calculation (Fixing Hover Bug) ---
        if num_pings < canvas_width:
            # Data is aligned to the left, not filling the canvas
            # Check if hover x is within the drawn data area (0 to num_pings - 1)
            if 0 <= x < num_pings:
                target_index = x # Index in pings array is directly x
        else:
            # Data fills the canvas, potentially shifted left
            # Check if hover x is within the canvas bounds (0 to canvas_width - 1)
            if 0 <= x < canvas_width:
                # The data displayed starts at index (num_pings - canvas_width)
                target_index = (num_pings - canvas_width) + x

        # --- Display Info if Index is Valid ---
        if 0 <= target_index < num_pings:
            value = self.pings[target_index]
            value_str = "Timeout/Error"
            if isinstance(value, (int, float)) and value >= 0:
                value_str = f"{round(value, 2)} ms"
            elif value is False or value is None: # Explicit check for common non-numeric results
                value_str = "Timeout/Error"
            else: # Should not happen with current ping logic, but catchall
                value_str = f"Unknown ({value})"

            # --- Get Timestamp ---
            ping_time_str = "??:??:??"
            if hasattr(self.app, 'ping_timestamps') and target_index < len(self.app.ping_timestamps):
                timestamp = self.app.ping_timestamps[target_index]
                ping_time_str = time.strftime("%H:%M:%S", time.localtime(timestamp))
            else:
                print(f"[WARN {self.host_ip}] Timestamp index {target_index} out of bounds ({len(self.app.ping_timestamps)})")


            # --- Host Info: IP (Hostname) or IP ---
            host_info = f"{self.host_ip}{f' ({self.host_hostname})' if self.host_hostname else ''}"
            disp = f"{host_info} | {value_str} @ {ping_time_str}"

            # Update label only if not in compact mode where labels are hidden
            if not self.app.is_compact_mode or self.app.compact_mode_label_behavior == 'tiny':
                self.info_label.config(text=self.get_info_text(extra=disp))
            print(f"[HOVER {self.host_ip}] Index {target_index} (x={x}), Value: {value}") 

            # Schedule revert back to normal info text
            if self.hover_timer is not None:
                self.after_cancel(self.hover_timer)
            # Revert even if label is hidden, so it's correct when shown again
            self.hover_timer = self.after(2000, self.update_info)
        else:
            # Mouse is over empty area or invalid index calculated
            self.on_mouse_leave(None) # Revert label immediately


    def on_mouse_leave(self, event):
        print(f"[HOVER LEAVE {self.host_ip}]") 
        if self.hover_timer is not None:
            self.after_cancel(self.hover_timer)
            self.hover_timer = None
        # Update info only if not hidden
        if not self.app.is_compact_mode or self.app.compact_mode_label_behavior == 'tiny':
             self.update_info()

    def set_label_visibility(self, visible):
        """Shows or hides the info label using pack/pack_forget."""
        if visible:
            if not self.info_label.winfo_ismapped():
                 self.info_label.pack(side=tk.TOP, fill=tk.X, expand=False, padx=1, pady=0)
                 self.update_info() # Refresh text when showing
        else:
            if self.info_label.winfo_ismapped():
                self.info_label.pack_forget()

    def set_label_font(self, font_size_option='normal'):
        """Sets the label font to normal or tiny."""
        if font_size_option == 'tiny':
            self.info_label.config(font=self.label_font_tiny)
            self.update_info() # Recalculate text for potentially smaller space
        else: # 'normal' or default
            self.info_label.config(font=self.label_font_normal)
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
        self.index = index # This is the ping_round_index
        self.stop_event = stop_event

    def run(self):
        print(f"[THREAD START] Pinging {self.host_ip}") 
        ping_result = False # Default to False for errors/timeouts

        if self.stop_event.is_set():
            print(f"[THREAD STOP] Stop event set before pinging {self.host_ip}") 
            pass # Put result False outside the try block
        else:
            try:
                # ping3 expects timeout in seconds
                timeout_sec = max(0.01, float(self.ping_timeout))
                # Ensure size is non-negative
                packet_size = max(0, int(self.ping_size))

                # Perform the ping
                result_ms = ping(
                    self.host_ip, timeout=timeout_sec, size=packet_size, unit="ms"
                )

                # Process the result from ping3
                if result_ms is None: # Explicit timeout indication from ping3
                    ping_result = None # Use None consistently for timeout
                    print(f"[PING TIMEOUT] Host: {self.host_ip}") 
                elif result_ms is False: # Explicit error indication from ping3
                    ping_result = False # Use False consistently for error
                    print(f"[PING FAIL] Host: {self.host_ip}") 
                elif isinstance(result_ms, (int, float)):
                     ping_result = result_ms # Keep the numeric value
                     print(f"[PING RESULT] Host: {self.host_ip}, Result: {ping_result} ms") 
                else: # Unexpected result type
                     ping_result = False # Treat as error
                     print(f"[PING UNEXPECTED] Host: {self.host_ip}, Result: {result_ms}")

            except Exception as e:
                print(f"[PING EXCEPTION] Host: {self.host_ip}, Error: {e}")
                ping_result = False # Indicate error

        # Only put result if the stop event wasn't set *during* the ping execution
        if not self.stop_event.is_set():
             # Queue tuple: (host_ip, ping_round_index, result_value)
             self.result_queue.put((self.host_ip, self.index, ping_result))
        # else:
             print(f"[THREAD STOP] Stop event set after pinging {self.host_ip}") 
             pass


class PingApp(tk.Tk):
    def __init__(self, config):
        print("[APP INIT] Initializing PingApp") 
        super().__init__()
        self.title("PingTracer--")
        self.configure(bg="#222222")
        self.geometry("800x500") # Adjusted initial size
        self.minsize(150, 100) # Adjusted min size

        self.config = config

        self.ping_graphs = {} # Dictionary: host_ip -> PingGraph instance
        self.ping_order = [] # List to remember traceroute hops order for display
        self.ping_timestamps = [] # Unified list for timestamps (since pings are done in rounds, a ping at the same index across all hops/hosts is done in the same round and is expected to be performed at nearly the same time)
        self.ping_round_index = 0
        self.result_queue = queue.Queue()
        self.running = False
        self.stop_event = threading.Event()
        self._scheduled_ping_after_id = None

        # --- State for On Top Mode ---
        self.is_compact_mode = False
        self.compact_mode_label_behavior = 'hide' # 'hide' or 'tiny' (tiny mode is terrible but i'm currently lazy to remove the code for it)
        self.original_geometry = ""
        self.original_overrideredirect = False
        self.original_alpha = 1.0
        self._drag_offset_x = 0 # For dragging borderless window
        self._drag_offset_y = 0

        self.build_options_frame()
        self.build_status_frame()
        self.build_graph_frame()

        self.handle_auto_start()
        self.after(100, self.process_ping_results) # Start processing queue
        print("[APP INIT COMPLETE]") 

    def handle_auto_start(self):
    """Check if auto-start is enabled and start pinging if so."""
        if self.config.start:
            print("[INFO] Auto-starting...") 
            self.config.start = False
            self.start_pinging() # Start pinging immediately

    def build_options_frame(self):
        print("[UI] Building options frame") 
        self.control_frame = tk.Frame(self, bg="#333333")
        self.control_frame.pack(fill=tk.X, side=tk.TOP, pady=(0,1)) # Add small padding below

        # --- Configuration entries and labels---
        tk.Label(self.control_frame,text="Host:",bg="#333333",fg="white",font=("TkDefaultFont", 8)).grid(row=0, column=0, padx=2, pady=1, sticky="w")
        self.host_entry = tk.Entry(self.control_frame, width=20)
        self.host_entry.grid(row=0, column=1, padx=2, pady=1, sticky="w")
        self.host_entry.insert(0, self.config.domain) # Default domain from config

        tk.Label(self.control_frame,text="Pings/sec:",bg="#333333",fg="white",font=("TkDefaultFont", 8)).grid(row=0, column=2, padx=2, pady=1, sticky="w")
        self.rate_entry = tk.Entry(self.control_frame, width=5)
        self.rate_entry.grid(row=0, column=3, padx=2, pady=1)
        self.rate_entry.insert(0, str(self.config.ping_rate))
        self.rate_label = tk.Label(self.control_frame,text=self.get_rate_text(self.config.ping_rate), bg="#333333", fg="white", font=("TkDefaultFont", 8))
        self.rate_label.grid(row=0, column=4, columnspan=3, padx=2, pady=1, sticky="w")
        self.rate_entry.bind("<FocusOut>", lambda e: self.update_rate_label())
        self.rate_entry.bind("<Return>", lambda e: self.update_rate_label())

        tk.Label(self.control_frame,text="Timeout(s):",bg="#333333",fg="white",font=("TkDefaultFont", 8)).grid(row=1, column=0, padx=2, pady=1, sticky="w")
        self.timeout_entry = tk.Entry(self.control_frame, width=5)
        self.timeout_entry.grid(row=1, column=1, padx=2, pady=1)
        self.timeout_entry.insert(0, str(self.config.ping_timeout))

        tk.Label(self.control_frame,text="Size(B):",bg="#333333",fg="white",font=("TkDefaultFont", 8)).grid(row=1, column=2, padx=2, pady=1, sticky="w")
        self.size_entry = tk.Entry(self.control_frame, width=5)
        self.size_entry.grid(row=1, column=3, padx=2, pady=1)
        self.size_entry.insert(0, str(self.config.ping_size))

        tk.Label(self.control_frame,text="Bad(ms):",bg="#333333",fg="white",font=("TkDefaultFont", 8)).grid(row=2, column=0, padx=2, pady=1, sticky="w")
        self.bad_entry = tk.Entry(self.control_frame, width=5)
        self.bad_entry.grid(row=2, column=1, padx=2, pady=1)
        self.bad_entry.insert(0, str(self.config.bad_threshold))
        self.bad_entry.bind("<FocusOut>", lambda e: self._read_settings()) # Update thresholds on change
        self.bad_entry.bind("<Return>", lambda e: self._read_settings())

        tk.Label(self.control_frame,text="So Bad(ms):",bg="#333333",fg="white",font=("TkDefaultFont", 8)).grid(row=2, column=2, padx=2, pady=1, sticky="w")
        self.sobad_entry = tk.Entry(self.control_frame, width=5)
        self.sobad_entry.grid(row=2, column=3, padx=2, pady=1)
        self.sobad_entry.insert(0, str(self.config.so_bad_threshold))
        self.sobad_entry.bind("<FocusOut>", lambda e: self._read_settings())
        self.sobad_entry.bind("<Return>", lambda e: self._read_settings())


        self.start_button = tk.Button(self.control_frame,text="Start",font=("TkDefaultFont", 9),command=self.start_pinging, width=8)
        self.start_button.focus_set()
        self.start_button.grid(row=2, column=4, padx=10, pady=3) # Slightly more padding

        self.bind("<Return>", lambda event: self.handle_enter())
        self.bind("<KP_Enter>", lambda event: self.handle_enter())
        print("[UI] Options frame ready") 

    def get_rate_text(self, rate):
        try:
            rate = float(rate)
            if rate <= 0: return "Rate <= 0!"
            if rate < 1:
                seconds = round(1 / rate, 2)
                return f"~1 ping / {seconds}s"
            else: return f"~{rate} pings / sec"
        except ValueError: return "Invalid Rate"

    def update_rate_label(self):
        try:
            rate = float(self.rate_entry.get())
            if rate < 0.01: rate = 0.01
            elif rate > 50: rate = 50
            self.config.ping_rate = rate
            self.rate_entry.delete(0, tk.END)
            self.rate_entry.insert(0, str(self.config.ping_rate))
            print(f"[SETTINGS] Updated ping rate to {self.config.ping_rate}") 
        except ValueError:
            self.rate_entry.delete(0, tk.END)
            self.rate_entry.insert(0, str(self.config.ping_rate))
            print("[SETTINGS] Invalid rate entry, keeping current value.") 
        self.rate_label.config(text=self.get_rate_text(self.config.ping_rate))

    def build_status_frame(self):
        print("[UI] Building status frame") 
        self.status_frame = tk.Frame(self, bg="#333333")
        # status_frame packed/unpacked in start/stop/on_top

        # Stop button on the left
        self.stop_button = tk.Button(self.status_frame,text="Stop",font=("TkDefaultFont", 8),command=self.stop_pinging, width=6)
        self.stop_button.pack(side=tk.LEFT, padx=5, pady=1)
        self.bind("<Escape>", lambda event: self.handle_escape())

        # On Top checkbox next
        self.always_on_top_var = tk.BooleanVar(value=False)
        self.always_on_top_check = tk.Checkbutton(self.status_frame,text="On Top",font=("TkDefaultFont", 8),variable=self.always_on_top_var,command=self.toggle_compact_mode,bg="#333333",fg="white",selectcolor="#555555",borderwidth=0,highlightthickness=0,padx=2, pady=0)
        self.always_on_top_check.pack(side=tk.LEFT, padx=5, pady=1)

        # Frame for graph toggles fills remaining space
        self.graph_checkbox_frame = tk.Frame(self.status_frame, bg="#333333")
        self.graph_checkbox_frame.pack(side=tk.LEFT, padx=5, pady=0, fill=tk.X, expand=True)

        self.graph_vars = {}
        print("[UI] Status frame ready") 

        # --- Bindings for dragging borderless window ---
        self.status_frame.bind("<Button-1>", self._start_drag)
        self.status_frame.bind("<B1-Motion>", self._do_drag)
        # Also bind the checkbox itself, otherwise clicking it might not start drag
        self.always_on_top_check.bind("<Button-1>", self._start_drag)
        self.always_on_top_check.bind("<B1-Motion>", self._do_drag)
        # You might need to bind other static elements in status_frame too if they cover significant area


    def build_graph_frame(self):
        self.graph_frame = tk.Frame(self, bg="#222222")
        # Pack with expand=True to allow PingGraphs inside to expand vertically
        self.graph_frame.pack(fill=tk.BOTH, expand=True, side=tk.BOTTOM)
        self.graph_frame.config(height=1) # Start small when nothing is running

    def handle_enter(self):
        if not self.running: self.start_button.invoke()

    def handle_escape(self):
        if self.running: self.stop_button.invoke()

    def _read_settings(self):
        """Reads and validates ALL settings from entry widgets."""
        print("[SETTINGS] Reading settings from UI") 

        # --- Rate ---
        try:
            rate = float(self.rate_entry.get())
            if not (0.01 <= rate <= 50): raise ValueError("Rate out of bounds")
            self.config.ping_rate = rate
        except ValueError:
            print("[WARN] Invalid ping rate. Reverting.") 
            self.rate_entry.delete(0, tk.END)
            self.rate_entry.insert(0, str(self.config.ping_rate))
        self.update_rate_label() # Update text label regardless

        # --- Timeout ---
        try:
            timeout = float(self.timeout_entry.get())
            if not (0.1 <= timeout <= 10): raise ValueError("Timeout out of bounds")
            self.config.ping_timeout = timeout
        except ValueError:
            print("[WARN] Invalid timeout. Reverting.") 
            self.timeout_entry.delete(0, tk.END)
            self.timeout_entry.insert(0, str(self.config.ping_timeout))

        # --- Size ---
        try:
            size = int(self.size_entry.get())
            if not (0 <= size <= 1400): raise ValueError("Size out of bounds")
            self.config.ping_size = size
        except ValueError:
            print("[WARN] Invalid ping size. Reverting.") 
            self.size_entry.delete(0, tk.END)
            self.size_entry.insert(0, str(self.config.ping_size))

        # --- Bad Threshold ---
        try:
            bad = float(self.bad_entry.get())
            if not (1 <= bad <= 5000): raise ValueError("Bad threshold out of bounds")
            self.config.bad_threshold = bad
        except ValueError:
            print("[WARN] Invalid bad threshold. Reverting.") 
            self.bad_entry.delete(0, tk.END)
            self.bad_entry.insert(0, str(self.config.bad_threshold))

        # --- So Bad Threshold ---
        try:
            so_bad = float(self.sobad_entry.get())
            # Check against the potentially just updated bad_threshold
            if not (self.config.bad_threshold < so_bad <= 5000):
                raise ValueError("'So Bad' threshold invalid relative to 'Bad' or bounds")
            self.config.so_bad_threshold = so_bad
        except ValueError:
            print("[WARN] Invalid 'so bad' threshold. Adjusting/Reverting.") 
            # Ensure so_bad is strictly greater than bad
            self.config.so_bad_threshold = self.config.bad_threshold + 50
            self.sobad_entry.delete(0, tk.END)
            self.sobad_entry.insert(0, str(self.config.so_bad_threshold))

        # Final check: ensure bad < so_bad after all updates
        if self.config.bad_threshold >= self.config.so_bad_threshold:
            print("[WARN] Bad threshold >= So Bad threshold. Adjusting So Bad.") 
            self.config.so_bad_threshold = self.config.bad_threshold + 50
            self.sobad_entry.delete(0, tk.END)
            self.sobad_entry.insert(0, str(self.config.so_bad_threshold))
        print("[SETTINGS] Settings read complete.") 

    def start_pinging(self):
        print("[START] Initiating pinging process...") 
        if self.running:
            print("[WARN] Already running, stop first.") 
            return

        self.stop_pinging(clear_ui=False)
        self.stop_event.clear()

        for widget in self.graph_frame.winfo_children(): widget.destroy()
        self.ping_graphs.clear()
        for widget in self.graph_checkbox_frame.winfo_children(): widget.destroy()
        self.graph_vars.clear()
        self.ping_order.clear()
        self.ping_timestamps.clear() # Clear timestamps
        self.ping_round_index = 0
        while not self.result_queue.empty():
            try: self.result_queue.get_nowait()
            except queue.Empty: break

        target = self.host_entry.get().strip()
        if not target:
            print("[ERROR] Host cannot be empty.")
            tk.messagebox.showerror("Error", "Host cannot be empty.")
            return

        print(f"[INFO] Target entered: {target}") 
        self._read_settings() # Read settings *before* traceroute/pinging

        # --- UI Switch ---
        # Ensure graph frame is reset to allow expansion
        self.graph_frame.config(height=-1) # Remove explicit height
        self.graph_frame.pack(fill=tk.BOTH, expand=True, side=tk.BOTTOM) # Ensure packed correctly

        self.control_frame.pack_forget()
        self.status_frame.pack(fill=tk.X, side=tk.TOP, pady=(0,1)) # Add small padding below
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)

        print("[INFO] Starting traceroute thread...") 
        self.status_label = tk.Label(self.graph_frame,text=f"Tracing route to {target}...",bg="#222222",fg="grey")
        self.status_label.pack(pady=20)
        self.update_idletasks()

        threading.Thread(target=self.do_trace_route, args=(target,), daemon=True).start()

    def do_trace_route(self, target):
        print(f"[TRACE] Starting traceroute to {target}") 
        hops = None
        try:
            hops = trace_route(target)
        except Exception as e:
            print(f"[TRACE ERROR] Error during trace_route: {e}")
            hops = None
        self.after(0, self._process_traceroute_results, hops, target)

    def _process_traceroute_results(self, hops, target): # Added 'app=self' to PingGraph call
        print("[TRACE] Processing traceroute results in main thread.") 
        if hasattr(self, "status_label") and self.status_label.winfo_exists():
            self.status_label.destroy()

        if self.stop_event.is_set():
            print("[TRACE] Stop event set during traceroute, aborting.") 
            self.stop_pinging()
            return

        if not hops:
            print(f"[TRACE FAIL] Traceroute to {target} failed or returned no hops.")
            error_label = tk.Label(self.graph_frame,text=f"Failed to trace route to {target}.\nCheck hostname or network.",bg="#222222",fg="red")
            error_label.pack(pady=20)
            self.after(5000, self.stop_pinging)
            return

        print(f"[TRACE SUCCESS] Traceroute completed with {len(hops)} hops.") 

        for widget in self.graph_checkbox_frame.winfo_children(): widget.destroy()
        self.graph_vars.clear()

        valid_hops_count = 0
        for hop_index, hop in enumerate(hops):
            if self.stop_event.is_set(): break
            if not hop or not hop[0]: continue

            host_ip = hop[0]
            # Ensure hostname is not None and not same as IP
            host_hostname = hop[1] if len(hop) > 1 and hop[1] and hop[1] != host_ip else None
            short_label = f"{hop_index+1}" # Use hop number for short label

            print(f"[GRAPH] Adding PingGraph for {host_ip} ({host_hostname})") 
            pg = PingGraph(
                self.graph_frame,
                app=self, # Pass the app instance
                host_ip=host_ip,
                host_hostname=host_hostname,
            )
            # Pack with expand=True now, relies on refresh_graph_packs later
            pg.pack(fill=tk.BOTH, expand=True, padx=0, pady=1)
            self.ping_graphs[host_ip] = pg
            self.ping_order.append(host_ip)

            # Add toggle checkbox
            var = tk.BooleanVar(value=True)
            cb = tk.Checkbutton(
                self.graph_checkbox_frame, text=short_label, font=("TkFixedFont", 7),
                variable=var, command=lambda ip=host_ip: self.toggle_graph_visibility(ip),
                bg="#333333", fg="white", selectcolor="#555555", borderwidth=0, highlightthickness=0,
                padx=1, pady=0, indicatoron=False, relief=tk.RAISED, width=3 # Shorter width
            )
            cb.pack(side=tk.LEFT, padx=1)
            self.graph_vars[host_ip] = (var, cb)
            valid_hops_count += 1

        if self.stop_event.is_set():
            print("[TRACE] Stop event set during graph creation, aborting.") 
            self.stop_pinging()
            return

        if valid_hops_count == 0:
            print("[ERROR] No valid hops found after traceroute processing.")
            error_label = tk.Label(self.graph_frame,text="No pingable hops found.",bg="#222222",fg="orange")
            error_label.pack(pady=20)
            self.after(4000, self.stop_pinging)
            return

        # Initial pack might be uneven, refresh corrects it
        self.refresh_graph_packs()
        self.update_idletasks() # Allow geometry to settle
        # Trigger initial resize/redraw for all created graphs
        for pg in self.ping_graphs.values():
             pg.on_resize()

        print("[INFO] All graphs added. Starting ping rounds.") 
        self.running = True
        self.schedule_next_ping_round()

    def toggle_graph_visibility(self, host_ip):
        if host_ip not in self.ping_graphs or host_ip not in self.graph_vars: return
        var, cb = self.graph_vars[host_ip]
        is_visible = var.get()
        cb.config(relief=tk.RAISED if is_visible else tk.SUNKEN)
        self.refresh_graph_packs()

    def refresh_graph_packs(self):
        """Repacks visible PingGraphs ensuring they fill vertically and maintain the original traceroute order."""
        print("[PACK] Refreshing graph packing order.") 

        # 1. Temporarily hide ALL PingGraph widgets managed by this frame
        #    This clears the current packing order within graph_frame.
        for host_ip in self.ping_order:
            if host_ip in self.ping_graphs:
                pg = self.ping_graphs[host_ip]
                if pg.winfo_ismapped(): # Only forget if currently packed
                    pg.pack_forget()

        # 2. Iterate through the desired ping_order sequence
        #    and re-pack only those that should be visible.
        num_packed = 0
        for host_ip in self.ping_order:
            # Ensure the graph and its toggle variable exist
            if host_ip in self.ping_graphs and host_ip in self.graph_vars:
                pg = self.ping_graphs[host_ip]
                var, cb = self.graph_vars[host_ip] # Get checkbox too for relief update

                # Check the state of the toggle variable
                if var.get():
                    # If it should be visible, pack it. Since we pack sequentially
                    # following ping_order after clearing, the order will be correct.
                    pg.pack(fill=tk.BOTH, expand=True, padx=0, pady=1)
                    cb.config(relief=tk.RAISED) # Ensure checkbox looks correct
                    num_packed += 1
                else:
                    # Ensure checkbox looks correct even if already hidden
                    cb.config(relief=tk.SUNKEN)


        print(f"[PACK] Re-packed {num_packed} visible graphs in order.") 

        # Optional: might help prevent visual glitches after toggling, but often not necessary
        # self.update_idletasks()
        
    def schedule_next_ping_round(self):
        """Schedules the next batch of pings and records timestamp."""
        if self._scheduled_ping_after_id:
            self.after_cancel(self._scheduled_ping_after_id)
            self._scheduled_ping_after_id = None

        if not self.running or self.stop_event.is_set():
            print("[SCHEDULER] Pinging stopped.") 
            self.running = False
            if hasattr(self, "start_button"): self.start_button.config(state=tk.NORMAL)
            if hasattr(self, "stop_button"): self.stop_button.config(state=tk.DISABLED)
            return

        # --- Record Timestamp for this Round ---
        current_round_time = time.time()
        self.ping_timestamps.append(current_round_time)
        current_round_index = self.ping_round_index # Index corresponds to timestamp list

        # --- Start Pings ---
        print(f"[ROUND {current_round_index}] Scheduling pings @ {current_round_time:.2f}") 
        hosts_to_ping = list(self.ping_graphs.keys())
        if not hosts_to_ping:
            print("[SCHEDULER] No hosts to ping. Stopping.") 
            self.stop_pinging()
            return

        active_threads = []
        for host_ip in hosts_to_ping:
            if self.stop_event.is_set(): break
            print(f"[PING START {host_ip}] Round {current_round_index}") 
            runner = PingRunner(
                host_ip, self.config.ping_timeout, self.config.ping_size,
                self.config.ping_rate, self.result_queue,
                current_round_index, # Pass the index for this round
                self.stop_event)
            runner.start()
            active_threads.append(runner)

        self.ping_round_index += 1 # Increment for the *next* round

        # --- Schedule Next ---
        delay_ms = max(10, int(1000 / self.config.ping_rate))
        print(f"[SCHEDULER] Next round in {delay_ms} ms") 
        self._scheduled_ping_after_id = self.after(delay_ms, self.schedule_next_ping_round)

        # --- Periodic Cleanup ---
        if (current_round_index > 10 and current_round_index % 100 == 0):
            print("[MAINTENANCE] Scheduling check for unpingable graphs...") 
            self.after(1000, self.clean_unpingable)

    def clean_unpingable(self):
        if not self.running: return
        print("[CLEANUP] Checking for unresponsive graphs...") 
        remove_ips, kept_ips = [], []
        if len(self.ping_graphs) <= 1: return

        for ip, pg in list(self.ping_graphs.items()):
            # Use the incremental stats: check if stat_count is 0 after enough attempts
            if pg.stat_count == 0 and (pg.stat_count + pg.stat_loss_count) > 10:
                print(f"[REMOVE] {ip} marked (never successful after {len(pg.pings)} attempts)") 
                remove_ips.append(ip)
            else:
                kept_ips.append(ip)

        if not remove_ips: return
        if len(kept_ips) == 0 and len(remove_ips) > 0:
             print("[CLEANUP] All graphs unresponsive, keeping.") 
             return

        print(f"[CLEANUP] Removing {len(remove_ips)} graphs: {remove_ips}") 
        for ip in remove_ips:
            if ip in self.ping_graphs: self.ping_graphs.pop(ip).destroy()
            if ip in self.graph_vars: self.graph_vars.pop(ip)[1].destroy() # Destroy checkbox
            if ip in self.ping_order:
                try: self.ping_order.remove(ip)
                except ValueError: pass
        self.refresh_graph_packs()

    def process_ping_results(self): # Added round_idx processing (though not used directly here yet)
        """Processes results from the queue and updates graphs."""
        try:
            while True:
                host_ip, round_idx, ping_value = self.result_queue.get_nowait()
                print(f"[RESULT] {host_ip} Round {round_idx}: {ping_value}") 
                if host_ip in self.ping_graphs:
                     # Add the value (could be float, None, False)
                     self.ping_graphs[host_ip].add_ping(ping_value)
                # else: print(f"[WARN] Received result for unknown/removed host: {host_ip}") 
        except queue.Empty:
            pass
        except Exception as e:
            print(f"[ERROR] Exception in process_ping_results: {e}")
            import traceback
            traceback.print_exc() print full traceback for debugging

        self.after(50, self.process_ping_results) # Reschedule check

    def stop_pinging(self, clear_ui=True):
        print("[STOP] Stopping ping process...") 
        self.running = False
        self.stop_event.set()

        if self._scheduled_ping_after_id:
            self.after_cancel(self._scheduled_ping_after_id)
            self._scheduled_ping_after_id = None

        # --- Exit Compact mode if active ---
        if self.is_compact_mode:
            self.always_on_top_var.set(False) # Untick the box
            self._restore_normal_mode()       # Restore normal view settings

        if clear_ui:
            for widget in self.graph_frame.winfo_children(): widget.destroy()
            for widget in self.graph_checkbox_frame.winfo_children(): widget.destroy()
            self.graph_vars.clear()

            self.status_frame.pack_forget()
            self.control_frame.pack(fill=tk.X, side=tk.TOP, pady=(0,1))

            # --- Shrink Graph Frame ---
            self.graph_frame.pack(fill=tk.X, expand=False) # Stop expanding vertically
            self.graph_frame.config(height=1) # Set minimal height

        # Always reset button states
        if hasattr(self, "start_button"): self.start_button.config(state=tk.NORMAL)
        if hasattr(self, "stop_button"): self.stop_button.config(state=tk.DISABLED)

        # Clear internal state (keep config)
        self.ping_graphs.clear()
        self.ping_order.clear()
        self.ping_timestamps.clear()
        print("[STOP] Pinging stopped.") 

    def toggle_compact_mode(self):
        """Called when the 'On Top' checkbox is clicked."""
        if self.always_on_top_var.get():
            self._enter_compact_mode()
        else:
            # Only restore if we were actually in compact mode
            if self.is_compact_mode:
                self._restore_normal_mode()
            else: # If unchecked but wasn't compact, just ensure topmost is off
                self.attributes("-topmost", False)


    def _enter_compact_mode(self):
            """Apply settings for compact 'On Top' mode."""
            print("[UI] Entering Compact Mode") 
            if self.is_compact_mode: return # Already compact

            # --- Store Original State ---
            self.original_geometry = self.geometry()
            # REMOVED: self.original_overrideredirect = self.overrideredirect() # Not needed, assume default is False
            try: # Reading alpha might fail on some platforms if never set
                self.original_alpha = self.attributes('-alpha')
            except tk.TclError:
                self.original_alpha = 1.0 # Assume default

            # --- Apply Compact Settings ---
            self.attributes("-topmost", True)     # Always on top
            self.overrideredirect(True)           # Hide title bar/borders
            self.geometry('250x70')              # Fixed size
            self.attributes("-alpha", 0.50)       # Semi-transparent

            # Hide controls within the status frame (Stop button, Graph toggles)
            if self.stop_button.winfo_ismapped():
                self.stop_button.pack_forget()
            if self.graph_checkbox_frame.winfo_ismapped():
                self.graph_checkbox_frame.pack_forget()

            # Handle graph labels based on preference
            if self.compact_mode_label_behavior == 'hide':
                for pg in self.ping_graphs.values():
                    pg.set_label_visibility(False)
            elif self.compact_mode_label_behavior == 'tiny':
                for pg in self.ping_graphs.values():
                    pg.set_label_font('tiny')
                    pg.set_label_visibility(True) # Ensure visible if tiny

            self.is_compact_mode = True
            self.update_idletasks() # Allow UI to redraw

    def _restore_normal_mode(self):
        """Restore settings when leaving compact 'On Top' mode."""
        print("[UI] Restoring Normal Mode") 
        if not self.is_compact_mode: return # Already normal

        # --- Restore Original State ---
        self.attributes("-topmost", False) # Turn off always on top
        self.overrideredirect(False) # <--- !!! Explicitly set to False to restore title bar
        try:
            # Check if original geometry string is valid before applying
            if self.original_geometry and 'x' in self.original_geometry and '+' in self.original_geometry:
                self.geometry(self.original_geometry) # Restore size/position
            else: # Fallback if stored geometry was bad
                self.geometry("800x500") # Default size
        except tk.TclError as e:
            print(f"[WARN] Failed to restore geometry '{self.original_geometry}': {e}")
            self.geometry("800x500") # Fallback
        self.attributes("-alpha", self.original_alpha) # Restore opacity

        # Show controls (order matters for layout) - Repack 'On Top' check LAST
        # Check if monitoring is actually running before showing stop button etc.
        if self.running:
            # Repack stop button FIRST if running
            if not self.stop_button.winfo_ismapped():
                self.stop_button.pack(side=tk.LEFT, padx=5, pady=1)
            # Repack toggles SECOND if running
            if not self.graph_checkbox_frame.winfo_ismapped():
                self.graph_checkbox_frame.pack(side=tk.LEFT, padx=5, pady=0, fill=tk.X, expand=True)

        # Repack 'On Top' check LAST, ensuring it's visible
        if not self.always_on_top_check.winfo_ismapped():
             self.always_on_top_check.pack(side=tk.LEFT, padx=5, pady=1)


        # Restore graph labels
        for pg in self.ping_graphs.values():
            pg.set_label_font('normal') # Restore normal font size
            pg.set_label_visibility(True) # Ensure labels are visible

        self.is_compact_mode = False
        self.update_idletasks()

    # --- Methods for dragging borderless window ---
    def _start_drag(self, event):
        """Records the initial mouse offset when dragging starts."""
        if self.is_compact_mode: # Only allow dragging in compact mode
             self._drag_offset_x = event.x
             self._drag_offset_y = event.y

    def _do_drag(self, event):
        """Moves the window based on mouse movement."""
        if self.is_compact_mode: # Only allow dragging in compact mode
             # Calculate new window top-left coordinates
             new_x = self.winfo_x() + (event.x - self._drag_offset_x)
             new_y = self.winfo_y() + (event.y - self._drag_offset_y)
             # Apply the new geometry (position part only)
             # Keep the fixed size of compact mode
             self.geometry(f'250x70+{new_x}+{new_y}')


    def on_close(self):
        """Gracefully stop threads and close the app."""
        print("Closing application...")
        self.stop_pinging(clear_ui=True) # Ensure cleanup happens
        # Explicitly destroy to avoid potential issues with lingering 'after' calls
        # Destroy children first might be safer
        for child in self.winfo_children():
            child.destroy()
        self.destroy()


if __name__ == "__main__":
    config_parser = Config()
    args = config_parser.parse_args()
    app = PingApp(args)
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    try:
        app.mainloop()
    except KeyboardInterrupt:
        print("KeyboardInterrupt detected, closing.")
        app.on_close()
    except Exception as e:
        print(f"Unhandled exception in main loop: {e}")
        import traceback
        traceback.print_exc()
        # Try to close cleanly even on unexpected error
        try:
             app.on_close()
        except: # Ignore errors during cleanup on top of other errors
             pass