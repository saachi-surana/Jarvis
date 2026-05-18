# Setup notes:
# 1. Install pynput: pip install pynput
#    Grant Accessibility permission on macOS for global hotkeys:
#    System Settings → Privacy & Security → Accessibility → add Terminal / IDE
# 2. tkinter ships with Python from python.org.
#    Homebrew Python: brew install python-tk

import os
import sys
import threading
import tkinter as tk

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Rosé Pine palette ──────────────────────────────────────────────────────────
BG       = "#191724"   # base
CONV_BG  = "#0f0e17"   # deeper well for conversation area
SURFACE  = "#1f1d2e"   # surface
OVERLAY  = "#26233a"   # selection highlight
FOAM     = "#9ccfd8"   # primary accent
IRIS     = "#c4a7e7"   # secondary accent
TEXT     = "#e0def4"   # main text
MUTED    = "#6e6a86"   # status / subdued
GRID     = "#1b192a"   # barely-visible grid lines

# Glow layers for the J.A.R.V.I.S title (outer → inner → main)
GLOW_OUT = "#2a4a50"
GLOW_MID = "#4a8a94"
# Arc decorations — simulated low-opacity IRIS (tkinter has no alpha)
ARC_DIM  = "#2a1f3d"
ARC_MID  = "#3a2b52"

# ── Typography ─────────────────────────────────────────────────────────────────
_MONO    = "Monaco"
F_SMALL  = (_MONO, 11)
F_LABEL  = (_MONO, 10, "bold")
F_TITLE  = (_MONO, 13, "bold")
F_STAT   = (_MONO, 10)
F_BTN    = (_MONO, 16)
F_WC     = (_MONO, 15)   # window-control ×, −

# ── Layout ─────────────────────────────────────────────────────────────────────
W        = 420
H        = 600
TOP_H    = 52
INPUT_H  = 70
STAT_H   = 30
CONV_H   = H - TOP_H - INPUT_H - STAT_H   # 448


class JarvisApp:
    def __init__(self, root: tk.Tk, process_input_fn, listener, transcriber):
        self.root         = root
        self._process     = process_input_fn
        self._listener    = listener
        self._transcriber = transcriber

        self._drag_ox   = 0
        self._drag_oy   = 0
        self._blinking  = False
        self._blink_on  = True
        self._recording = False

        self._setup_window()
        self._build_background()   # grid + full-window edge accent lines
        self._build_top_bar()      # HUD chrome, title glow, top corner arcs
        self._build_conversation()
        self._build_input()
        self._build_status()       # bottom corner arcs, brackets, status text
        self._setup_hotkey()

    # ── Window ────────────────────────────────────────────────────────────────

    def _setup_window(self):
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=BG)
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{W}x{H}+{(sw - W) // 2}+{(sh - H) // 2}")

    # ── Background canvas (grid + window-edge accent) ─────────────────────────

    def _build_background(self):
        c = tk.Canvas(self.root, width=W, height=H, bg=BG, highlightthickness=0)
        c.place(x=0, y=0)

        # Subtle grid (mostly covered by widgets, but visible at window margins)
        for x in range(0, W + 1, 28):
            c.create_line(x, 0, x, H, fill=GRID, width=1)
        for y in range(0, H + 1, 28):
            c.create_line(0, y, W, y, fill=GRID, width=1)

        # Thin accent lines along all four window edges (not covered by frames)
        c.create_line(0, 0, W, 0, fill=MUTED, width=1)        # top
        c.create_line(0, H-1, W, H-1, fill=MUTED, width=1)    # bottom
        c.create_line(0, 0, 0, H, fill=MUTED, width=1)        # left
        c.create_line(W-1, 0, W-1, H, fill=MUTED, width=1)    # right

    # ── HUD top bar ───────────────────────────────────────────────────────────

    def _build_top_bar(self):
        c = tk.Canvas(self.root, width=W, height=TOP_H, bg=BG, highlightthickness=0)
        c.place(x=0, y=0)
        self._top = c

        c.bind("<ButtonPress-1>", self._drag_start)
        c.bind("<B1-Motion>",    self._drag_move)

        # ── Corner arc rings (Iron Man HUD style) ─────────────────────────────
        # Each corner has three concentric quarter-circle arcs.
        # Top-left center (0,0): visible quadrant is x>0, y>0 → start=270, extent=90
        # Top-right center (W,0): visible quadrant x<W, y>0 → start=180, extent=90
        for radius, color in ((24, ARC_DIM), (36, ARC_DIM), (50, ARC_MID)):
            # top-left
            c.create_arc(-radius, -radius, radius, radius,
                         start=270, extent=90,
                         style=tk.ARC, outline=color, width=1)
            # top-right
            c.create_arc(W - radius, -radius, W + radius, radius,
                         start=180, extent=90,
                         style=tk.ARC, outline=color, width=1)

        # ── L-shaped corner brackets ──────────────────────────────────────────
        pad, arm = 8, 14
        _tl = [(pad, pad, pad + arm, pad), (pad, pad, pad, pad + arm)]
        _tr = [(W-pad, pad, W-pad-arm, pad), (W-pad, pad, W-pad, pad+arm)]
        for x1, y1, x2, y2 in _tl + _tr:
            c.create_line(x1, y1, x2, y2, fill=IRIS, width=1)

        # ── Flanking rule lines around the title ──────────────────────────────
        cx, cy, gap = W // 2, TOP_H // 2, 68
        lx1 = pad + arm + 6
        rx2 = W - pad - arm - 6
        for dy in (-7, 7):
            c.create_line(lx1, cy + dy, cx - gap, cy + dy, fill=MUTED, width=1)
            c.create_line(cx + gap, cy + dy, rx2, cy + dy, fill=MUTED, width=1)

        # Small tick marks at rule-line ends (HUD detail)
        for dy in (-7, 7):
            for x in (lx1, cx - gap, cx + gap, rx2):
                c.create_line(x, cy + dy - 2, x, cy + dy + 2, fill=IRIS, width=1)

        # ── Glowing J.A.R.V.I.S title ────────────────────────────────────────
        title = "J.A.R.V.I.S"
        # Outer glow (4 diagonal offsets, ±2px)
        for dx, dy in ((-2, -2), (2, -2), (-2, 2), (2, 2)):
            c.create_text(cx + dx, cy + dy, text=title,
                          fill=GLOW_OUT, font=F_TITLE, anchor="center")
        # Mid glow (4 cardinal offsets, ±1px)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            c.create_text(cx + dx, cy + dy, text=title,
                          fill=GLOW_MID, font=F_TITLE, anchor="center")
        # Sharp main layer
        c.create_text(cx, cy, text=title, fill=FOAM, font=F_TITLE, anchor="center")

        # ── Bottom separator ──────────────────────────────────────────────────
        c.create_line(0, TOP_H - 1, W, TOP_H - 1, fill=MUTED, width=1)

        # ── Window controls ───────────────────────────────────────────────────
        def _wc(x, label, cmd):
            iid = c.create_text(x, 13, text=label, fill=MUTED,
                                 font=F_WC, anchor="center")
            c.tag_bind(iid, "<Button-1>", lambda e: cmd())
            c.tag_bind(iid, "<Enter>",  lambda e: c.itemconfig(iid, fill=TEXT))
            c.tag_bind(iid, "<Leave>",  lambda e: c.itemconfig(iid, fill=MUTED))

        _wc(W - 14, "×", self.root.destroy)
        _wc(W - 34, "−", self.root.withdraw)

    # ── Scrollable conversation ───────────────────────────────────────────────

    def _build_conversation(self):
        outer = tk.Frame(self.root, bg=CONV_BG)
        outer.place(x=0, y=TOP_H, width=W, height=CONV_H)

        sb = tk.Scrollbar(outer, bg=SURFACE, troughcolor=CONV_BG,
                          activebackground=MUTED, relief=tk.FLAT,
                          highlightthickness=0, width=6)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self._conv = tk.Text(
            outer,
            bg=CONV_BG, fg=TEXT,
            font=F_SMALL,
            relief=tk.FLAT,
            wrap=tk.WORD,
            padx=16, pady=14,
            spacing1=2, spacing3=10,
            state=tk.DISABLED,
            yscrollcommand=sb.set,
            selectbackground=OVERLAY,
            selectforeground=TEXT,
            insertbackground=FOAM,
            highlightthickness=0,
            cursor="arrow",
        )
        self._conv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.config(command=self._conv.yview)

        self._conv.bind(
            "<MouseWheel>",
            lambda e: self._conv.yview_scroll(int(-1 * (e.delta / 120)), "units"),
        )

        # Conversation tags
        # "▎" character acts as the left-border accent
        self._conv.tag_config("u_pre",
            foreground=IRIS, font=F_LABEL)
        self._conv.tag_config("u_body",
            foreground=TEXT, font=F_SMALL,
            lmargin1=14, lmargin2=14)
        self._conv.tag_config("j_pre",
            foreground=FOAM, font=F_LABEL)
        self._conv.tag_config("j_body",
            foreground=FOAM, font=F_SMALL,
            lmargin1=14, lmargin2=14)

        # Thin separator at the bottom of conversation (above input)
        sep = tk.Canvas(outer, height=1, bg=MUTED, highlightthickness=0)
        sep.place(x=0, y=CONV_H - 1, width=W)

    # ── Input row ─────────────────────────────────────────────────────────────

    def _build_input(self):
        outer = tk.Frame(self.root, bg=BG)
        outer.place(x=0, y=TOP_H + CONV_H, width=W, height=INPUT_H)

        row = tk.Frame(outer, bg=BG)
        row.pack(fill=tk.BOTH, expand=True, padx=12, pady=14)

        # ── Mic button: canvas circle ──────────────────────────────────────
        mc = tk.Canvas(row, width=38, height=38, bg=BG, highlightthickness=0)
        mc.pack(side=tk.LEFT, padx=(0, 10))
        self._mic_c    = mc
        self._mic_ring = mc.create_oval(2, 2, 36, 36,
                                         outline=FOAM, fill=BG, width=1)
        # Inner dot
        mc.create_oval(15, 15, 23, 23, outline=FOAM, fill=BG, width=1,
                       tags="mic_dot")
        mc.bind("<Button-1>", self._on_mic)
        mc.bind("<Enter>",
            lambda e: mc.itemconfig(self._mic_ring, width=2))
        mc.bind("<Leave>",
            lambda e: mc.itemconfig(
                self._mic_ring, width=1,
                outline=IRIS if self._recording else FOAM))

        # ── Glowing entry border ──────────────────────────────────────────
        self._entry_frame = tk.Frame(row, bg=MUTED, padx=1, pady=1)
        self._entry_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                               padx=(0, 10))

        self._entry = tk.Entry(
            self._entry_frame,
            bg=SURFACE, fg=TEXT,
            font=F_SMALL,
            relief=tk.FLAT,
            insertbackground=FOAM,
            selectbackground=OVERLAY,
            selectforeground=TEXT,
        )
        self._entry.pack(fill=tk.BOTH, expand=True, padx=7, pady=5)
        self._entry.bind("<Return>",   self._on_enter)
        self._entry.bind("<FocusIn>",
            lambda e: self._entry_frame.config(bg=FOAM))
        self._entry.bind("<FocusOut>",
            lambda e: self._entry_frame.config(bg=MUTED))

        # ── Send button ───────────────────────────────────────────────────
        tk.Button(
            row,
            text="▶",
            bg=BG, fg=FOAM,
            font=F_BTN,
            relief=tk.FLAT,
            activebackground=BG, activeforeground=TEXT,
            bd=0, cursor="hand2",
            command=self._on_send,
        ).pack(side=tk.LEFT)

    # ── Status bar ────────────────────────────────────────────────────────────

    def _build_status(self):
        c = tk.Canvas(self.root, width=W, height=STAT_H,
                      bg=BG, highlightthickness=0)
        c.place(x=0, y=TOP_H + CONV_H + INPUT_H)
        self._stat_canvas = c

        # ── Bottom corner arc rings ────────────────────────────────────────
        # Bottom-left center (0, STAT_H): visible quadrant is x>0, y<STAT_H
        # → start=0, extent=90 sweeps from (r, STAT_H) to (0, STAT_H-r)
        # Bottom-right center (W, STAT_H):
        # → start=90, extent=90 sweeps from (W, STAT_H-r) to (W-r, STAT_H)
        for radius, color in ((18, ARC_DIM), (24, ARC_DIM), (32, ARC_MID)):
            # bottom-left
            c.create_arc(
                -radius, STAT_H - radius, radius, STAT_H + radius,
                start=0, extent=90,
                style=tk.ARC, outline=color, width=1,
            )
            # bottom-right
            c.create_arc(
                W - radius, STAT_H - radius, W + radius, STAT_H + radius,
                start=90, extent=90,
                style=tk.ARC, outline=color, width=1,
            )

        # ── Bottom corner brackets ─────────────────────────────────────────
        pad, arm = 8, 14
        # Bottom-left: bracket opens upward-right from (pad, STAT_H-pad)
        by = STAT_H - pad
        c.create_line(pad,     by, pad + arm, by, fill=IRIS, width=1)
        c.create_line(pad,     by, pad,     by - arm, fill=IRIS, width=1)
        # Bottom-right
        c.create_line(W-pad,   by, W-pad-arm, by, fill=IRIS, width=1)
        c.create_line(W-pad,   by, W-pad,   by - arm, fill=IRIS, width=1)

        # Top separator line
        c.create_line(0, 0, W, 0, fill=SURFACE, width=1)

        # ── Status text ───────────────────────────────────────────────────
        self._status_var = tk.StringVar(value="READY")
        self._status_lbl = tk.Label(
            c,
            textvariable=self._status_var,
            bg=BG, fg=MUTED,
            font=F_STAT,
            anchor="center",
        )
        c.create_window(W // 2, STAT_H // 2 + 2,
                        window=self._status_lbl, anchor="center")

    # ── Drag ──────────────────────────────────────────────────────────────────

    def _drag_start(self, event):
        self._drag_ox = event.x_root - self.root.winfo_x()
        self._drag_oy = event.y_root - self.root.winfo_y()

    def _drag_move(self, event):
        self.root.geometry(
            f"+{event.x_root - self._drag_ox}+{event.y_root - self._drag_oy}")

    # ── Show / hide ───────────────────────────────────────────────────────────

    def _toggle(self):
        if self.root.winfo_viewable():
            self.root.withdraw()
        else:
            self.root.deiconify()
            self.root.lift()
            self._entry.focus_set()

    # ── Global hotkey (Cmd+Shift+J) ───────────────────────────────────────────

    def _setup_hotkey(self):
        try:
            from pynput import keyboard as kb
            hl = kb.GlobalHotKeys(
                {"<cmd>+<shift>+j": lambda: self.root.after(0, self._toggle)})
            threading.Thread(target=hl.run, daemon=True).start()
        except Exception as exc:
            print(f"[UI] Global hotkey unavailable: {exc}")

    # ── Status / blink ────────────────────────────────────────────────────────

    def _set_status(self, text: str, blink: bool = False):
        self._blinking = False
        self._status_var.set(text)
        self._status_lbl.config(fg=MUTED)
        if blink:
            self._blinking = True
            self._blink()

    def _blink(self):
        if not self._blinking:
            self._status_lbl.config(fg=MUTED)
            return
        self._blink_on = not self._blink_on
        self._status_lbl.config(fg=FOAM if self._blink_on else BG)
        self.root.after(500, self._blink)

    # ── Conversation ──────────────────────────────────────────────────────────

    def add_message(self, speaker: str, text: str):
        """Must be called from the main thread (or via root.after)."""
        self._conv.config(state=tk.NORMAL)
        if speaker == "user":
            self._conv.insert(tk.END, "▎ YOU\n",     "u_pre")
            self._conv.insert(tk.END, text + "\n\n", "u_body")
        else:
            self._conv.insert(tk.END, "▎ JARVIS\n",  "j_pre")
            self._conv.insert(tk.END, text + "\n\n", "j_body")
        self._conv.config(state=tk.DISABLED)
        self._conv.see(tk.END)

    # ── Input handlers ────────────────────────────────────────────────────────

    def _on_enter(self, _event=None):
        self._on_send()

    def _on_send(self):
        text = self._entry.get().strip()
        if not text:
            return
        self._entry.delete(0, tk.END)
        self._submit(text)

    def _submit(self, text: str):
        self.add_message("user", text)
        self._set_status("THINKING...", blink=True)
        threading.Thread(
            target=self._process,
            args=(text,),
            kwargs={"on_response": lambda r: self.root.after(0, self._on_response, r)},
            daemon=True,
        ).start()

    def _on_response(self, response: str):
        self.add_message("jarvis", response)
        self._set_status("READY")

    # ── Microphone ────────────────────────────────────────────────────────────

    def _on_mic(self, _event=None):
        if self._recording:
            return
        self._recording = True
        self._mic_c.itemconfig(self._mic_ring, outline=IRIS)
        self._set_status("LISTENING...", blink=True)
        threading.Thread(target=self._record_thread, daemon=True).start()

    def _record_thread(self):
        try:
            self._listener.trigger_recording()
        finally:
            self.root.after(0, self._record_done)

    def _record_done(self):
        self._recording = False
        self._mic_c.itemconfig(self._mic_ring, outline=FOAM)

    def on_audio_received(self, audio_bytes: bytes):
        """
        Replaces main._on_audio. Wired into listener.on_audio by main.py.
        Called from the listener thread — all UI updates go via root.after.
        """
        self.root.after(0, lambda: self._set_status("TRANSCRIBING...", blink=True))
        text = self._transcriber.transcribe(audio_bytes)
        if text:
            self.root.after(0, self._submit, text)
        else:
            self.root.after(0, self._set_status, "READY")

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self):
        self._entry.focus_set()
        self.root.mainloop()
