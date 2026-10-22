"""
Hardware Monitor - Professional (CustomTkinter Edition)
- Full AMD Ryzen & Intel CPU Support
- Dark / Light / System theme modes
- Modern UI with CustomTkinter
- Smooth Anti-aliased Circular Gauges (Pillow)
- Top Processes with icons
- Separate "All Processes" window
- FPS counter via RTSS
- Auto GPU detection
- CSV logging
- GPU/CPU Details windows
- OSD Overlay
"""

import os
import sys
import time
import json
import csv
import ctypes
import struct
import threading
import tkinter as tk
from tkinter import ttk
from datetime import datetime
from ctypes import wintypes
from pathlib import Path
import psutil
import customtkinter as ctk
from HardwareMonitor.Hardware import Computer, IVisitor
from PIL import Image, ImageDraw, ImageTk, ImageFont
import pystray


# ---------- Themes ----------
DARK_PALETTE = {
    "bg": "#0d1117", "card": "#161b22", "card2": "#1c2128",
    "fg": "#e6edf3", "dim": "#8b949e", "track": "#21262d",
    "green": "#3fb950", "yellow": "#d29922", "red": "#f85149",
    "blue": "#58a6ff", "purple": "#bc8cff", "orange": "#ff7b72",
}

LIGHT_PALETTE = {
    "bg": "#f6f8fa", "card": "#ffffff", "card2": "#eaeef2",
    "fg": "#1f2328", "dim": "#656d76", "track": "#d0d7de",
    "green": "#1a7f37", "yellow": "#9a6700", "red": "#cf222e",
    "blue": "#0969da", "purple": "#8250df", "orange": "#bc4c00",
}


def detect_system_theme():
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return "Light" if value == 1 else "Dark"
    except Exception:
        return "Dark"


# ---------- Config ----------
DEFAULT_CONFIG = {
    "update_ms": 1000,
    "collect_interval": 1.0,
    "osd_enabled": False,
    "osd_alpha": 0.75,
    "osd_font_size": 12,
    "osd_x": None,
    "osd_y": 8,
    "osd_show_fps": True,
    "osd_show_gpu": True,
    "osd_show_cpu": True,
    "osd_show_ram": True,
    "osd_show_net": True,
    "start_minimized": False,
    "default_gpu_index": 0,
    "auto_gpu_select": True,
    "theme_mode": "System",
    "pawnio_warning_dismissed": False,
    "log_enabled": False,
    "log_interval_s": 2.0,
}


class Config:
    def __init__(self):
        self.path = Path(os.environ.get("APPDATA", ".")) / "HardwareMonitor" / "config.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = dict(DEFAULT_CONFIG)
        self.load()

    def load(self):
        try:
            if self.path.exists():
                with open(self.path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                for k, v in DEFAULT_CONFIG.items():
                    self.data[k] = loaded.get(k, v)
        except Exception:
            pass

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
        except Exception:
            pass

    def get(self, key, default=None):
        return self.data.get(key, default if default is not None else DEFAULT_CONFIG.get(key))

    def set(self, key, value):
        self.data[key] = value
        self.save()


CONFIG = Config()


# ---------- Apply appearance mode ----------
_mode = CONFIG.get("theme_mode", "System")
if _mode == "Dark":
    ctk.set_appearance_mode("dark")
elif _mode == "Light":
    ctk.set_appearance_mode("light")
else:
    ctk.set_appearance_mode("system")

ctk.set_default_color_theme("blue")


# ---------- Load Theme Colors ----------
def _get_palette():
    mode = CONFIG.get("theme_mode", "System")
    if mode == "Dark":
        return DARK_PALETTE
    elif mode == "Light":
        return LIGHT_PALETTE
    else:
        system = detect_system_theme()
        return LIGHT_PALETTE if system == "Light" else DARK_PALETTE


_palette = _get_palette()
BG      = _palette["bg"]
CARD    = _palette["card"]
CARD2   = _palette["card2"]
FG      = _palette["fg"]
DIM     = _palette["dim"]
TRACK   = _palette["track"]
GREEN   = _palette["green"]
YELLOW  = _palette["yellow"]
RED     = _palette["red"]
BLUE    = _palette["blue"]
PURPLE  = _palette["purple"]
ORANGE  = _palette["orange"]

FONT = "Segoe UI"
MIN_WIDTH = 560
MIN_HEIGHT = 620
OSD_KEEP_ON_TOP_MS = 1500
PAWNIO_URL = "https://pawnio.eu/"
RTSS_URL = "https://www.guru3d.com/files-details/rtss-rivatuner-statistics-server-download.html"


# ---------- Process Icons (Windows) ----------
try:
    import win32gui
    import win32ui
    import win32con
    import win32api
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False


class ProcessIconCache:
    def __init__(self):
        self._cache = {}

    def get(self, exe_path, size=20):
        if not exe_path or not HAS_WIN32:
            return None
        key = (exe_path, size)
        if key in self._cache:
            return self._cache[key]
        photo = None
        try:
            pil = self._extract_icon(exe_path, size)
            if pil is not None:
                photo = ImageTk.PhotoImage(pil)
        except Exception:
            photo = None
        self._cache[key] = photo
        return photo

    def _extract_icon(self, exe_path, size):
        hicon = None
        large = small = ()
        try:
            large, small = win32gui.ExtractIconEx(exe_path, 0)
            if large:
                hicon = large[0]
            elif small:
                hicon = small[0]
            if not hicon:
                return None

            ico_x = win32api.GetSystemMetrics(win32con.SM_CXICON)
            ico_y = win32api.GetSystemMetrics(win32con.SM_CYICON)

            hdc = win32ui.CreateDCFromHandle(win32gui.GetDC(0))
            hdc_mem = hdc.CreateCompatibleDC()
            hbmp = win32ui.CreateBitmap()
            hbmp.CreateCompatibleBitmap(hdc, ico_x, ico_y)
            hdc_mem.SelectObject(hbmp)
            hdc_mem.DrawIcon((0, 0), hicon)

            bmpinfo = hbmp.GetInfo()
            bmpstr = hbmp.GetBitmapBits(True)

            img = Image.frombuffer(
                "RGBA",
                (bmpinfo["bmWidth"], bmpinfo["bmHeight"]),
                bmpstr, "raw", "BGRA", 0, 1,
            )
            bbox = img.getbbox()
            if bbox:
                img = img.crop(bbox)
            img = img.resize((size, size), Image.LANCZOS)

            hdc_mem.DeleteDC()
            hdc.DeleteDC()
            return img
        except Exception:
            return None
        finally:
            try:
                if hicon:
                    win32gui.DestroyIcon(hicon)
                for h in large:
                    if h and h != hicon:
                        win32gui.DestroyIcon(h)
                for h in small:
                    if h and h != hicon:
                        win32gui.DestroyIcon(h)
            except Exception:
                pass


ICON_CACHE = ProcessIconCache()


# ---------- RTSS FPS Reader ----------
class RtssReader:
    SIGNATURE = 0x52545353
    FILE_MAP_READ = 0x0004

    def __init__(self):
        self.ptr = None
        self.handle = None
        try:
            self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            self._kernel32.OpenFileMappingW.restype = wintypes.HANDLE
            self._kernel32.OpenFileMappingW.argtypes = [
                wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR
            ]
            self._kernel32.MapViewOfFile.restype = ctypes.c_void_p
            self._kernel32.MapViewOfFile.argtypes = [
                wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                wintypes.DWORD, ctypes.c_size_t
            ]
            self._kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
            self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            self._open()
        except Exception:
            self._kernel32 = None

    def _open(self):
        try:
            self.handle = self._kernel32.OpenFileMappingW(
                self.FILE_MAP_READ, False, "RTSSSharedMemoryV2")
            if self.handle:
                self.ptr = self._kernel32.MapViewOfFile(
                    self.handle, self.FILE_MAP_READ, 0, 0, 0)
        except Exception:
            self.ptr = None

    def available(self):
        return self.ptr is not None and self.ptr != 0

    def close(self):
        try:
            if self.ptr:
                self._kernel32.UnmapViewOfFile(self.ptr)
            if self.handle:
                self._kernel32.CloseHandle(self.handle)
        except Exception:
            pass
        self.ptr = None
        self.handle = None

    def get_fps(self):
        if not self.available():
            return None, None, None
        try:
            header = ctypes.string_at(self.ptr, 36)
            signature, version, entry_size, arr_offset, arr_size = \
                struct.unpack_from("<IIIII", header, 0)
            if signature != self.SIGNATURE:
                return None, None, None
            if entry_size == 0 or arr_size == 0 or arr_size > 500:
                return None, None, None
            total = arr_offset + arr_size * entry_size
            if total > 16 * 1024 * 1024:
                total = 16 * 1024 * 1024
            data = ctypes.string_at(self.ptr, total)
            best = None
            for i in range(arr_size):
                base = arr_offset + i * entry_size
                if base + 284 > len(data):
                    break
                pid = struct.unpack_from("<I", data, base)[0]
                if pid == 0:
                    continue
                name_bytes = data[base + 4: base + 4 + 260]
                name = name_bytes.split(b"\x00", 1)[0].decode("utf-8", errors="ignore")
                t0 = struct.unpack_from("<I", data, base + 268)[0]
                t1 = struct.unpack_from("<I", data, base + 272)[0]
                frames = struct.unpack_from("<I", data, base + 276)[0]
                ftime = struct.unpack_from("<I", data, base + 280)[0]
                if frames < 1 or t1 <= t0:
                    continue
                elapsed = t1 - t0
                if elapsed <= 0:
                    continue
                fps = (frames * 1000.0) / elapsed
                if not (0.1 < fps < 2000):
                    continue
                if best is None or fps > best[0]:
                    best = (fps, float(ftime), name)
            if best:
                return best
            return None, None, None
        except Exception:
            return None, None, None


# ---------- Log Writer ----------
class LogWriter:
    def __init__(self):
        self.writer = None
        self.file = None
        self.path = None
        self.last_write = 0.0
        self.interval = float(CONFIG.get("log_interval_s", 2.0))
        self._lock = threading.Lock()

    def set_interval(self, seconds):
        self.interval = max(0.5, float(seconds))

    def start(self):
        if self.writer is not None:
            return
        try:
            logs_dir = Path(os.environ.get("APPDATA", ".")) / "HardwareMonitor" / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            self.path = logs_dir / f"session_{ts}.csv"
            self.file = open(self.path, "w", newline="", encoding="utf-8")
            self.writer = csv.writer(self.file)
            self.writer.writerow([
                "timestamp", "fps", "frametime_ms",
                "cpu_pct", "cpu_temp_c", "cpu_power_w", "cpu_clock_mhz",
                "gpu_load_pct", "gpu_temp_c", "gpu_power_w",
                "gpu_vram_used_mb", "gpu_vram_total_mb",
                "ram_pct", "ram_used_mb", "ram_total_mb",
                "net_down_mbs", "net_up_mbs",
            ])
            self.file.flush()
        except Exception:
            self.writer = None
            self.file = None

    def stop(self):
        with self._lock:
            if self.file:
                try:
                    self.file.close()
                except Exception:
                    pass
            self.file = None
            self.writer = None

    def log(self, fps, frametime, cpu_pct, cpu_data, cpu_clock, gpu_data, vm, net_down, net_up):
        if not self.writer:
            return
        now = time.time()
        if now - self.last_write < self.interval:
            return
        self.last_write = now
        try:
            def _f(v, fmt=".1f"):
                return f"{v:{fmt}}" if v is not None else ""
            with self._lock:
                self.writer.writerow([
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    _f(fps, ".1f"),
                    _f(frametime, ".2f"),
                    f"{cpu_pct:.1f}",
                    _f(cpu_data.get("temp")),
                    _f(cpu_data.get("power"), ".2f"),
                    _f(cpu_clock, ".0f"),
                    _f(gpu_data.get("load")) if gpu_data else "",
                    _f(gpu_data.get("temp")) if gpu_data else "",
                    _f(gpu_data.get("power"), ".2f") if gpu_data else "",
                    _f(gpu_data.get("vram_used", 0) / 1048576, ".0f") if gpu_data and gpu_data.get("vram_used") else "",
                    _f(gpu_data.get("vram_total", 0) / 1048576, ".0f") if gpu_data and gpu_data.get("vram_total") else "",
                    f"{vm.percent:.1f}",
                    f"{vm.used / 1048576:.0f}",
                    f"{vm.total / 1048576:.0f}",
                    f"{net_down / 1048576:.3f}",
                    f"{net_up / 1048576:.3f}",
                ])
                self.file.flush()
        except Exception:
            pass


# ---------- LHM ----------
class UpdateVisitor(IVisitor):
    __namespace__ = "HardwareMonitorApp"

    def VisitComputer(self, computer):
        computer.Traverse(self)

    def VisitHardware(self, hardware):
        hardware.Update()
        for sub in hardware.SubHardware:
            sub.Update()

    def VisitParameter(self, parameter):
        pass

    def VisitSensor(self, sensor):
        pass


COMPUTER = Computer()
COMPUTER.IsCpuEnabled = True
COMPUTER.IsGpuEnabled = True
COMPUTER.IsMemoryEnabled = True
COMPUTER.Open()
VISITOR = UpdateVisitor()


def refresh_lhm():
    try:
        COMPUTER.Accept(VISITOR)
    except Exception:
        pass


# ---------- Sensor Cache ----------
class SensorCache:
    def __init__(self, hardware):
        self.hardware = hardware
        self.by_name = {}
        self.rebuild()

    def rebuild(self):
        self.by_name = {}
        if self.hardware is None:
            return
        for s in self.hardware.Sensors:
            self.by_name.setdefault(s.Name, []).append(s)

    def get(self, name, type_keyword=None):
        sensors = self.by_name.get(name)
        if not sensors:
            return None
        if type_keyword is None:
            return sensors[0]
        kw = type_keyword.lower()
        for s in sensors:
            if kw in str(s.SensorType).lower():
                return s
        return None


def list_gpus():
    refresh_lhm()
    return [hw for hw in COMPUTER.Hardware
            if "gpu" in str(hw.HardwareType).lower()]


def get_cpu_hardware():
    for hw in COMPUTER.Hardware:
        if "cpu" in str(hw.HardwareType).lower():
            return hw
    return None


def find_power_sensor(hardware, preferred_names):
    if hardware is None:
        return None
    candidates = []
    for s in hardware.Sensors:
        if s.Value is None:
            continue
        if "power" not in str(s.SensorType).lower():
            continue
        candidates.append(s)
    if not candidates:
        return None
    for pref in preferred_names:
        for s in candidates:
            if s.Name == pref:
                return s
    for pref in preferred_names:
        pl = pref.lower()
        for s in candidates:
            if pl in s.Name.lower():
                return s
    try:
        candidates.sort(key=lambda x: x.Value if x.Value is not None else 0,
                        reverse=True)
    except Exception:
        pass
    return candidates[0]


# ---------- Readers ----------
def read_cpu_summary(cache):
    data = {
        "name": cache.hardware.Name if cache.hardware else "Unknown CPU",
        "cores": psutil.cpu_count(logical=False),
        "threads": psutil.cpu_count(logical=True),
        "temp": None,
        "power": None,
    }
    if cache.hardware:
        # Intel
        s = cache.get("CPU Package", "Temperature")
        if s and s.Value is not None:
            data["temp"] = s.Value
        else:
            # AMD fallback
            for name in ("Core (Tctl/Tdie)", "Core Average", "CPU Die (average)", "Core Max"):
                s = cache.get(name, "Temperature")
                if s and s.Value is not None:
                    data["temp"] = s.Value
                    break
            if data["temp"] is None:
                for s in cache.hardware.Sensors:
                    if "temperature" in str(s.SensorType).lower() and s.Value is not None:
                        data["temp"] = s.Value
                        break

        # Power
        s = find_power_sensor(cache.hardware, [
            "CPU Package", "Package", "Core", "SoC", "CPU Cores", "CPU Platform",
        ])
        if s and s.Value is not None:
            data["power"] = s.Value
    return data


def read_cpu_clock(cache):
    if cache.hardware is None:
        return None
    
    p_clocks, e_clocks, amd_clocks = [], [], []
    for s in cache.hardware.Sensors:
        if s.Value is None: continue
        if "clock" not in str(s.SensorType).lower(): continue
        
        name = s.Name
        if name.startswith("P-Core"): p_clocks.append(s.Value)
        elif name.startswith("E-Core"): e_clocks.append(s.Value)
        elif name.startswith("Core #"): amd_clocks.append(s.Value)
    
    if p_clocks: return sum(p_clocks) / len(p_clocks)
    if e_clocks: return sum(e_clocks) / len(e_clocks)
    if amd_clocks: return sum(amd_clocks) / len(amd_clocks)
    return None


def read_cpu_details(cache):
    rows = {"load": [], "clock": [], "temp": [], "power": [], "voltage": []}
    if cache.hardware is None:
        return rows
    
    for s in cache.hardware.Sensors:
        if s.Value is None: continue
        stype = str(s.SensorType).lower()
        name = s.Name
        
        if "load" in stype and (name.startswith("CPU Core") or name.startswith("Core")):
            rows["load"].append((name, s.Value))
        elif "clock" in stype and (name.startswith("P-Core") or name.startswith("E-Core") or name.startswith("Core #")):
            rows["clock"].append((name, s.Value))
        elif "temperature" in stype and (
            name.startswith("P-Core") or name.startswith("E-Core") or 
            name.startswith("Core (") or "CCD" in name
        ) and "Distance" not in name:
            rows["temp"].append((name, s.Value))
        elif "power" in stype and (name.startswith("CPU") or name in ("Package", "Core", "SoC")):
            rows["power"].append((name, s.Value))
        elif "voltage" in stype and (name.startswith("P-Core") or name.startswith("E-Core") or "SVI2" in name):
            rows["voltage"].append((name, s.Value))
            
    return rows


def read_gpu(cache):
    htype = str(cache.hardware.HardwareType).lower() if cache.hardware else ""
    data = {
        "name": cache.hardware.Name if cache.hardware else "",
        "load": None, "temp": None, "power": None,
        "vram_used": None, "vram_total": None,
    }
    if "nvidia" in htype:
        s = cache.get("GPU Core", "Load")
        if s and s.Value is not None: data["load"] = s.Value
        s = cache.get("GPU Core", "Temperature")
        if s and s.Value is not None: data["temp"] = s.Value
        s = find_power_sensor(cache.hardware, ["GPU Package", "GPU Power", "Power"])
        if s and s.Value is not None: data["power"] = s.Value
        s = cache.get("GPU Memory Used")
        if s and s.Value is not None: data["vram_used"] = s.Value * 1024 * 1024
        s = cache.get("GPU Memory Total")
        if s and s.Value is not None: data["vram_total"] = s.Value * 1024 * 1024
    elif "intel" in htype or "amd" in htype:
        s = cache.get("D3D 3D", "Load")
        if s and s.Value is not None: data["load"] = s.Value
        else:
            s = cache.get("GPU Core", "Load")
            if s and s.Value is not None: data["load"] = s.Value
            
        s = find_power_sensor(cache.hardware, ["GPU Power", "Power", "Package"])
        if s and s.Value is not None: data["power"] = s.Value
        
        s = cache.get("D3D Shared Memory Used")
        if s and s.Value is not None: data["vram_used"] = s.Value * 1024 * 1024
        s = cache.get("D3D Shared Memory Total")
        if s and s.Value is not None: data["vram_total"] = s.Value * 1024 * 1024
    return data


def read_gpu_details(cache):
    rows = {"load": [], "temp": [], "clock": [], "power": [],
            "memory": [], "throughput": [], "voltage": []}
    if cache.hardware is None:
        return rows
    for s in cache.hardware.Sensors:
        if s.Value is None:
            continue
        stype = str(s.SensorType).lower()
        name = s.Name
        if "load" in stype:
            if name in ("GPU Core", "GPU Memory", "GPU Memory Controller",
                        "GPU Video Engine", "GPU Bus", "D3D 3D"):
                rows["load"].append((name, s.Value))
        elif "temperature" in stype:
            rows["temp"].append((name, s.Value))
        elif "clock" in stype and ("GPU" in name or "Core" in name or "Memory" in name):
            rows["clock"].append((name, s.Value))
        elif "power" in stype:
            rows["power"].append((name, s.Value))
        elif "smalldata" in stype and ("Memory" in name or "VRAM" in name):
            rows["memory"].append((name, s.Value))
        elif "throughput" in stype:
            rows["throughput"].append((name, s.Value))
        elif "voltage" in stype and "GPU" in name:
            rows["voltage"].append((name, s.Value))
    return rows


# ---------- Helpers ----------
def fmt_bytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def pick_color(pct):
    if pct < 60: return GREEN
    if pct < 85: return YELLOW
    return RED


def pick_fps_color(fps):
    if fps is None: return DIM
    if fps >= 60: return GREEN
    if fps >= 30: return YELLOW
    return RED


def top_procs(n=5):
    procs = []
    for p in psutil.process_iter(["name", "memory_percent", "exe", "cpu_percent"]):
        try:
            info = p.info
            if info["name"] and info["memory_percent"] is not None:
                procs.append((
                    info["memory_percent"],
                    float(info.get("cpu_percent") or 0.0),
                    info["name"],
                    info.get("exe"),
                ))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    procs.sort(key=lambda x: x[0], reverse=True)
    return procs[:max(n, 10)]


# ---------- Circular Gauge (Pillow Anti-aliased) ----------
class CircularGauge:
    def __init__(self, parent, title, size=110, thickness=8):
        self.size = size
        self.thickness = thickness
        self.pct = -1.0
        self.title = title

        # إطار البطاقة
        self.frame = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=12,
                                  border_width=1, border_color=TRACK)

        # ليبل لعرض الصورة
        self.image_label = ctk.CTkLabel(self.frame, text="", fg_color=CARD)
        self.image_label.pack(padx=6, pady=6)

        # تحميل الخطوط بحجمها الطبيعي (مش هيتصغر لأننا هنرسمه في الآخر)
        try:
            self.font_pct = ImageFont.truetype("C:\\Windows\\Fonts\\segoeuib.ttf", 20)
            self.font_title = ImageFont.truetype("C:\\Windows\\Fonts\\segoeuib.ttf", 11)
        except Exception:
            self.font_pct = ImageFont.load_default()
            self.font_title = ImageFont.load_default()

        self.set(0)

    def set(self, pct):
        new = max(0.0, min(100.0, float(pct)))
        if abs(new - self.pct) < 0.5 and self.pct != -1.0:
            return
        self.pct = new
        color = pick_color(self.pct)

        # نرسم الأقواس بحجم كبير 4 مرات عشان تنعيم الحواف
        scale = 4
        w = self.size * scale
        t = self.thickness * scale

        # 1. إنشاء صورة كبيرة ورسم الأقواس
        img = Image.new("RGBA", (w, w), CARD)
        draw = ImageDraw.Draw(img)

        pad = t // 2 + (4 * scale)
        box = [pad, pad, w - pad, w - pad]

        draw.arc(box, start=-90, end=270, fill=TRACK, width=t)
        extent = 360 * (self.pct / 100.0)
        if extent > 0.5:
            draw.arc(box, start=-90, end=-90 + extent, fill=color, width=t)

        # 2. تصغير الصورة للحجم الطبيعي (هنا بتنعم الحواف)
        img = img.resize((self.size, self.size), Image.Resampling.LANCZOS)

        # 3. رسم النص فوق الصورة الصغيرة عشان يطلع واضح جداً
        draw = ImageDraw.Draw(img)
        cx = cy = self.size // 2
        
        # رسم النسبة
        draw.text((cx, cy - 6), text=f"{self.pct:.0f}%",
                  font=self.font_pct, fill=FG, anchor="mm")

        # رسم الاسم (CPU / GPU)
        draw.text((cx, cy + 16), text=self.title,
                  font=self.font_title, fill=DIM, anchor="mm")

        # عرض الصورة النهائية
        self.photo = ImageTk.PhotoImage(img)
        self.image_label.configure(image=self.photo)


# ---------- Linear Bar ----------
class InfoBar:
    def __init__(self, parent, title, color=BLUE):
        self.color = color
        self._pct = -1
        self._text = None
        self.card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=10)
        self.card.pack(fill="x", padx=14, pady=4)
        head = ctk.CTkFrame(self.card, fg_color=CARD)
        head.pack(fill="x", padx=14, pady=(10, 4))
        self.title_lbl = ctk.CTkLabel(head, text=title, text_color=FG,
                                      font=(FONT, 12, "bold"), anchor="w")
        self.title_lbl.pack(side="left", fill="x", expand=True)
        self.value_lbl = ctk.CTkLabel(head, text="", text_color=DIM,
                                      font=(FONT, 11), anchor="e")
        self.value_lbl.pack(side="right")
        self.bar = ctk.CTkProgressBar(self.card, height=8,
                                      fg_color=TRACK, progress_color=color,
                                      corner_radius=4)
        self.bar.set(0)
        self.bar.pack(fill="x", padx=14, pady=(0, 12))

    def set_title(self, title):
        if title != self.title_lbl.cget("text"):
            self.title_lbl.configure(text=title)

    def set(self, text, pct=None):
        if text != self._text:
            self._text = text
            self.value_lbl.configure(text=text)
        if pct is not None:
            new = max(0, min(100, pct))
            if abs(new - self._pct) >= 0.5:
                self._pct = new
                self.bar.set(new / 100.0)


# ---------- Compact CPU Card ----------
class CpuCard:
    def __init__(self, parent, on_details_click, on_warning_click=None):
        self.card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=10)
        self.card.pack(fill="x", padx=14, pady=4)
        head = ctk.CTkFrame(self.card, fg_color=CARD)
        head.pack(fill="x", padx=14, pady=(12, 4))
        ctk.CTkLabel(head, text="CPU", text_color=FG,
                     font=(FONT, 12, "bold")).pack(side="left")
        self.details_btn = ctk.CTkLabel(head, text="Details ▸", text_color=BLUE,
                                        font=(FONT, 10, "bold"), cursor="hand2")
        self.details_btn.pack(side="right")
        self.details_btn.bind("<Button-1>", lambda e: on_details_click())
        self.name_lbl = ctk.CTkLabel(self.card, text="—", text_color=FG,
                                     font=(FONT, 13, "bold"), anchor="w", justify="left")
        self.name_lbl.pack(fill="x", padx=14)
        self.summary_lbl = ctk.CTkLabel(self.card, text="—", text_color=DIM,
                                        font=(FONT, 11), anchor="w", justify="left")
        self.summary_lbl.pack(fill="x", padx=14, pady=(2, 4))
        self.warning_frame = ctk.CTkFrame(self.card, fg_color=CARD)
        self.warning_lbl = ctk.CTkLabel(
            self.warning_frame,
            text="⚠  CPU power reads 0W — click to install PawnIO driver",
            text_color=YELLOW, font=(FONT, 10), anchor="w",
            cursor="hand2", justify="left",
        )
        self.warning_lbl.pack(fill="x", padx=0, pady=(0, 6))
        if on_warning_click:
            self.warning_lbl.bind("<Button-1>", lambda e: on_warning_click())
        self.bottom_pad = ctk.CTkFrame(self.card, fg_color=CARD, height=6)
        self.bottom_pad.pack(fill="x")
        self._last_name = None
        self._last_summary = None
        self._warning_shown = False

    def set(self, data, freq_current):
        if data["name"] != self._last_name:
            self._last_name = data["name"]
            self.name_lbl.configure(text=data["name"])
        parts = [
            f"{data['cores']}C / {data['threads']}T",
            f"{freq_current:.0f} MHz" if freq_current else "— MHz",
            f"{data['temp']:.0f}°C" if data["temp"] is not None else "N/A °C",
            f"{data['power']:.1f}W" if data["power"] is not None else "N/A W",
        ]
        summary = "  ·  ".join(parts)
        if summary != self._last_summary:
            self._last_summary = summary
            self.summary_lbl.configure(text=summary)

    def show_warning(self, show):
        if show and not self._warning_shown:
            self.bottom_pad.pack_forget()
            self.warning_frame.pack(fill="x", padx=14)
            self._warning_shown = True
        elif not show and self._warning_shown:
            self.warning_frame.pack_forget()
            self.bottom_pad.pack(fill="x")
            self._warning_shown = False


# ---------- CPU Details Window ----------
class CpuDetailsWindow:
    def __init__(self, master, get_data_fn):
        self.get_data_fn = get_data_fn
        self.win = tk.Toplevel(master)
        self.win.title("CPU Details")
        self.win.geometry("720x640")
        self.win.minsize(560, 480)
        self.win.configure(bg=BG)
        self.win.resizable(True, True)
        header = tk.Frame(self.win, bg=BG)
        header.pack(fill="x", padx=20, pady=(16, 10))
        tk.Label(header, text="CPU Details", bg=BG, fg=FG,
                 font=(FONT, 14, "bold")).pack(side="left")
        self.clock = tk.Label(header, text="", bg=BG, fg=DIM, font=(FONT, 10))
        self.clock.pack(side="right")
        container = tk.Frame(self.win, bg=BG)
        container.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        container.columnconfigure(0, weight=1, uniform="col")
        container.columnconfigure(1, weight=1, uniform="col")
        container.rowconfigure(0, weight=1)
        self.left = tk.Frame(container, bg=CARD)
        self.left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.right = tk.Frame(container, bg=CARD)
        self.right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        tk.Label(self.left, text="Loads & Temps", bg=CARD, fg=FG,
                 font=(FONT, 11, "bold")).pack(anchor="w", padx=14, pady=(12, 8))
        self.left_body = tk.Label(self.left, text="", bg=CARD, fg=DIM,
                                  font=("Consolas", 10), justify="left", anchor="nw")
        self.left_body.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        tk.Label(self.right, text="Clocks · Power · Voltage", bg=CARD, fg=FG,
                 font=(FONT, 11, "bold")).pack(anchor="w", padx=14, pady=(12, 8))
        self.right_body = tk.Label(self.right, text="", bg=CARD, fg=DIM,
                                   font=("Consolas", 10), justify="left", anchor="nw")
        self.right_body.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        self._last_left = None
        self._last_right = None
        self._last_clock = None
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.win.transient(master)
        self._alive = True
        self.update()

    def close(self):
        self._alive = False
        self.win.destroy()

    def update(self):
        if not self._alive: return
        try:
            if self.win.state() == "iconic":
                self.win.after(2000, self.update)
                return
        except Exception:
            pass
        clock = time.strftime("%H:%M:%S")
        if clock != self._last_clock:
            self._last_clock = clock
            self.clock.config(text=clock)
        rows = self.get_data_fn()
        left_lines = ["── Loads ──"]
        for name, val in rows["load"]:
            left_lines.append(f"  {name:<22} {val:>6.1f} %")
        left_lines.append("")
        left_lines.append("── Temperatures ──")
        for name, val in rows["temp"]:
            left_lines.append(f"  {name:<22} {val:>6.1f} °C")
        left_text = "\n".join(left_lines)
        if left_text != self._last_left:
            self._last_left = left_text
            self.left_body.config(text=left_text)
        right_lines = ["── Clocks ──"]
        for name, val in rows["clock"]:
            right_lines.append(f"  {name:<18} {val:>7.0f} MHz")
        right_lines.append("")
        right_lines.append("── Power ──")
        for name, val in rows["power"]:
            right_lines.append(f"  {name:<18} {val:>7.2f} W")
        right_lines.append("")
        right_lines.append("── Voltage ──")
        for name, val in rows["voltage"]:
            right_lines.append(f"  {name:<18} {val:>7.3f} V")
        right_text = "\n".join(right_lines)
        if right_text != self._last_right:
            self._last_right = right_text
            self.right_body.config(text=right_text)
        self.win.after(1000, self.update)


# ---------- GPU Details Window ----------
class GpuDetailsWindow:
    def __init__(self, master, app):
        self.app = app
        self.win = tk.Toplevel(master)
        self.win.title("GPU Details")
        self.win.geometry("760x660")
        self.win.minsize(600, 500)
        self.win.configure(bg=BG)
        self.win.resizable(True, True)
        header = tk.Frame(self.win, bg=BG)
        header.pack(fill="x", padx=20, pady=(16, 10))
        tk.Label(header, text="GPU Details", bg=BG, fg=FG,
                 font=(FONT, 14, "bold")).pack(side="left")
        self.clock = tk.Label(header, text="", bg=BG, fg=DIM, font=(FONT, 10))
        self.clock.pack(side="right")
        name_frame = tk.Frame(self.win, bg=BG)
        name_frame.pack(fill="x", padx=20, pady=(0, 10))
        self.name_lbl = tk.Label(name_frame, text="—", bg=BG, fg=BLUE,
                                 font=(FONT, 11, "bold"), anchor="w")
        self.name_lbl.pack(fill="x")
        container = tk.Frame(self.win, bg=BG)
        container.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        container.columnconfigure(0, weight=1, uniform="col")
        container.columnconfigure(1, weight=1, uniform="col")
        container.rowconfigure(0, weight=1)
        self.left = tk.Frame(container, bg=CARD)
        self.left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        tk.Label(self.left, text="Loads & Temperatures", bg=CARD, fg=FG,
                 font=(FONT, 11, "bold")).pack(anchor="w", padx=14, pady=(12, 8))
        self.left_body = tk.Label(self.left, text="", bg=CARD, fg=DIM,
                                  font=("Consolas", 10), justify="left", anchor="nw")
        self.left_body.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        self.right = tk.Frame(container, bg=CARD)
        self.right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        tk.Label(self.right, text="Clocks · Power · Memory · PCIe", bg=CARD, fg=FG,
                 font=(FONT, 11, "bold")).pack(anchor="w", padx=14, pady=(12, 8))
        self.right_body = tk.Label(self.right, text="", bg=CARD, fg=DIM,
                                   font=("Consolas", 10), justify="left", anchor="nw")
        self.right_body.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        self._last_left = None
        self._last_right = None
        self._last_clock = None
        self._last_name = None
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.win.transient(master)
        self._alive = True
        self.update()

    def close(self):
        self._alive = False
        self.win.destroy()

    def _current_cache(self):
        return getattr(self.app, "current_gpu_cache", None)

    def update(self):
        if not self._alive: return
        try:
            if self.win.state() == "iconic":
                self.win.after(2000, self.update)
                return
        except Exception:
            pass
        clock = time.strftime("%H:%M:%S")
        if clock != self._last_clock:
            self._last_clock = clock
            self.clock.config(text=clock)
        cache = self._current_cache()
        if cache is None or cache.hardware is None:
            self.left_body.config(text="No GPU selected")
            self.right_body.config(text="")
            self.win.after(1000, self.update)
            return
        if cache.hardware.Name != self._last_name:
            self._last_name = cache.hardware.Name
            self.name_lbl.config(text=cache.hardware.Name)
        rows = read_gpu_details(cache)
        left_lines = ["── Loads ──"]
        for name, val in rows["load"]:
            left_lines.append(f"  {name:<26} {val:>7.1f} %")
        left_lines.append("")
        left_lines.append("── Temperatures ──")
        for name, val in rows["temp"]:
            left_lines.append(f"  {name:<26} {val:>7.1f} °C")
        if rows["voltage"]:
            left_lines.append("")
            left_lines.append("── Voltage ──")
            for name, val in rows["voltage"]:
                left_lines.append(f"  {name:<26} {val:>7.3f} V")
        left_text = "\n".join(left_lines)
        if left_text != self._last_left:
            self._last_left = left_text
            self.left_body.config(text=left_text)
        right_lines = ["── Clocks ──"]
        for name, val in rows["clock"]:
            right_lines.append(f"  {name:<24} {val:>8.0f} MHz")
        right_lines.append("")
        right_lines.append("── Power ──")
        for name, val in rows["power"]:
            right_lines.append(f"  {name:<24} {val:>8.2f} W")
        right_lines.append("")
        right_lines.append("── Memory ──")
        for name, val in rows["memory"]:
            right_lines.append(f"  {name:<24} {val:>8.1f} MB")
        if rows["throughput"]:
            right_lines.append("")
            right_lines.append("── PCIe Throughput ──")
            for name, val in rows["throughput"]:
                if val > 1048576:
                    right_lines.append(f"  {name:<24} {val/1048576:>8.2f} MB/s")
                else:
                    right_lines.append(f"  {name:<24} {val/1024:>8.1f} KB/s")
        right_text = "\n".join(right_lines)
        if right_text != self._last_right:
            self._last_right = right_text
            self.right_body.config(text=right_text)
        self.win.after(1000, self.update)


# ---------- All Processes Window ----------
class AllProcessesWindow:
    def __init__(self, master):
        self.master = master
        self.win = tk.Toplevel(master)
        self.win.title("All Processes")
        self.win.geometry("720x600")
        self.win.minsize(560, 400)
        self.win.configure(bg=BG)
        self.win.resizable(True, True)
        self.win.transient(master)

        header = tk.Frame(self.win, bg=BG)
        header.pack(fill="x", padx=20, pady=(16, 10))
        tk.Label(header, text="All Processes", bg=BG, fg=FG,
                 font=(FONT, 14, "bold")).pack(side="left")
        self.count_lbl = tk.Label(header, text="", bg=BG, fg=DIM,
                                  font=(FONT, 10))
        self.count_lbl.pack(side="right")

        hint = tk.Frame(self.win, bg=BG)
        hint.pack(fill="x", padx=20, pady=(0, 8))
        tk.Label(hint,
                 text="Click a column to sort  ·  CPU% is normalized to total cores",
                 bg=BG, fg=DIM, font=(FONT, 9)).pack(anchor="w")

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("AllProcs.Treeview",
                        background=CARD, fieldbackground=CARD,
                        foreground=FG, borderwidth=0,
                        rowheight=28, font=(FONT, 10))
        style.configure("AllProcs.Treeview.Heading",
                        background=CARD2, foreground=FG,
                        borderwidth=0, font=(FONT, 10, "bold"),
                        relief="flat")
        style.map("AllProcs.Treeview",
                  background=[("selected", TRACK)],
                  foreground=[("selected", FG)])
        style.map("AllProcs.Treeview.Heading",
                  background=[("active", TRACK)])

        container = tk.Frame(self.win, bg=BG)
        container.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        self.tree = ttk.Treeview(
            container,
            columns=("name", "cpu", "ram"),
            show="tree headings",
            style="AllProcs.Treeview",
            selectmode="browse",
        )
        self.tree.heading("#0", text="")
        self.tree.heading("name", text="Process",
                          anchor="w", command=lambda: self._sort_by("name"))
        self.tree.heading("cpu", text="CPU %",
                          anchor="e", command=lambda: self._sort_by("cpu"))
        self.tree.heading("ram", text="RAM",
                          anchor="e", command=lambda: self._sort_by("ram"))

        self.tree.column("#0", width=30, stretch=False, anchor="center")
        self.tree.column("name", width=380, stretch=True, anchor="w")
        self.tree.column("cpu", width=100, stretch=False, anchor="e")
        self.tree.column("ram", width=140, stretch=False, anchor="e")

        scroll = ttk.Scrollbar(container, orient="vertical",
                               command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)

        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.tree.tag_configure("odd", background=CARD)
        self.tree.tag_configure("even", background=CARD2)

        self._icon_refs = []
        self._last_snapshot = None
        self._sort_col = "ram"
        self._sort_desc = True
        self._alive = True

        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.update()

    def close(self):
        self._alive = False
        try:
            self.win.destroy()
        except Exception:
            pass

    def _sort_by(self, col):
        if self._sort_col == col:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_col = col
            self._sort_desc = True
        self._last_snapshot = None

    def update(self):
        if not self._alive: return
        try:
            if self.win.state() == "iconic":
                self.win.after(2000, self.update)
                return
        except Exception:
            pass

        try:
            procs = self._collect()
        except Exception:
            procs = []

        total = len(procs)

        if self._sort_col == "name":
            procs.sort(key=lambda x: x[2].lower(), reverse=self._sort_desc)
        elif self._sort_col == "cpu":
            procs.sort(key=lambda x: x[1], reverse=self._sort_desc)
        else:
            procs.sort(key=lambda x: x[0], reverse=self._sort_desc)

        display = procs[:200]

        try:
            self.count_lbl.configure(text=f"{total} processes")
        except Exception:
            return

        snapshot = tuple(
            (name, round(cpu, 1), round(mem_mb, 1))
            for mem_mb, cpu, name, _ in display
        )
        if snapshot == self._last_snapshot:
            self.win.after(1500, self.update)
            return
        self._last_snapshot = snapshot

        try:
            for item in self.tree.get_children():
                self.tree.delete(item)
        except Exception:
            return
        self._icon_refs = []

        for i, (mem_mb, cpu, name, exe) in enumerate(display):
            tag = "even" if i % 2 == 0 else "odd"
            icon = ICON_CACHE.get(exe, size=16) if exe else None
            values = (name, f"{cpu:.1f}", f"{mem_mb:.1f} MB")
            if icon:
                self._icon_refs.append(icon)
                self.tree.insert("", "end", image=icon,
                                 values=values, tags=(tag,))
            else:
                self.tree.insert("", "end",
                                 values=values, tags=(tag,))

        self.win.after(1500, self.update)

    @staticmethod
    def _collect():
        total_cores = psutil.cpu_count(logical=True) or 1
        procs = []
        for p in psutil.process_iter(
            ["name", "memory_info", "cpu_percent", "exe"]
        ):
            try:
                info = p.info
                name = info.get("name")
                if not name:
                    continue
                mem_info = info.get("memory_info")
                mem_mb = (mem_info.rss / 1048576.0) if mem_info else 0.0
                cpu = float(info.get("cpu_percent") or 0.0) / total_cores
                if cpu < 0:
                    cpu = 0.0
                exe = info.get("exe")
                procs.append((mem_mb, cpu, name, exe))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return procs


# ---------- OSD Overlay ----------
class OsdOverlay:
    def __init__(self, master):
        self.master = master
        self.win = tk.Toplevel(master)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self._osd_bg = "#000000"
        self.win.configure(bg=self._osd_bg)
        alpha = CONFIG.get("osd_alpha", 0.75)
        font_size = CONFIG.get("osd_font_size", 12)
        pos_x = CONFIG.get("osd_x")
        pos_y = CONFIG.get("osd_y", 8)
        self._auto_center = pos_x is None
        if pos_x is None:
            pos_x = 100
        self.win.geometry(f"1x1+{pos_x}+{pos_y}")
        try:
            self.win.attributes("-alpha", alpha)
        except Exception:
            pass
        self._font_size = font_size
        self._font_family = self._pick_font()
        self.label = tk.Label(self.win, text="", bg=self._osd_bg, fg="#ffffff",
                              font=(self._font_family, font_size, "bold"),
                              anchor="w", padx=10, pady=4)
        self.label.pack(fill="both", expand=True)
        self._drag_x = 0
        self._drag_y = 0
        for w in (self.win, self.label):
            w.bind("<Button-1>", self._start_drag)
            w.bind("<B1-Motion>", self._do_drag)
            w.bind("<ButtonRelease-1>", self._on_release)
            w.bind("<Button-3>", lambda e: self.hide())
        self.visible = False
        self._last_text = None
        self._alive = True
        self.win.withdraw()
        self._keep_on_top()

    @staticmethod
    def _pick_font():
        import tkinter.font as tkfont
        for f in ("Bahnschrift SemiBold", "Bahnschrift SemiCondensed",
                  "Bahnschrift", "Segoe UI Semibold", "Segoe UI", "Tahoma"):
            try:
                if f in set(tkfont.families()):
                    return f
            except Exception:
                pass
        return "Segoe UI"

    def _start_drag(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _do_drag(self, event):
        x = self.win.winfo_x() + event.x - self._drag_x
        y = self.win.winfo_y() + event.y - self._drag_y
        self.win.geometry(f"+{x}+{y}")

    def _on_release(self, event):
        try:
            CONFIG.set("osd_x", self.win.winfo_x())
            CONFIG.set("osd_y", self.win.winfo_y())
        except Exception:
            pass

    def _resize_to_content(self):
        try:
            self.label.update_idletasks()
            w = max(1, self.label.winfo_reqwidth())
            h = max(1, self.label.winfo_reqheight())
            if self._auto_center:
                screen_w = self.win.winfo_screenwidth()
                x = max(0, (screen_w - w) // 2)
                self._auto_center = False
            else:
                x = self.win.winfo_x()
            y = self.win.winfo_y()
            self.win.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

    def _keep_on_top(self):
        if not self._alive:
            return
        if self.visible:
            try:
                self.win.lift()
                self.win.attributes("-topmost", True)
            except Exception:
                pass
        try:
            self.win.after(OSD_KEEP_ON_TOP_MS, self._keep_on_top)
        except Exception:
            pass

    def show(self):
        self.win.deiconify()
        self.win.lift()
        self.win.attributes("-topmost", True)
        self.visible = True
        self._resize_to_content()

    def hide(self):
        self.win.withdraw()
        self.visible = False

    def set_text(self, text):
        if text != self._last_text:
            self._last_text = text
            self.label.config(text=text)
            self._resize_to_content()

    def apply_font_size(self, size):
        try:
            self._font_size = size
            self.label.config(font=(self._font_family, size, "bold"))
            self._resize_to_content()
        except Exception:
            pass

    def apply_alpha(self, alpha):
        try:
            self.win.attributes("-alpha", alpha)
        except Exception:
            pass

    def destroy(self):
        self._alive = False
        try:
            self.win.destroy()
        except Exception:
            pass


# ---------- Settings Window ----------
class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.title("Settings")
        self.geometry("600x760")
        self.minsize(560, 640)
        self.configure(fg_color=BG)
        self.transient(master)
        header = ctk.CTkFrame(self, fg_color=BG)
        header.pack(fill="x", padx=20, pady=(18, 8))
        ctk.CTkLabel(header, text="Settings", text_color=FG,
                     font=(FONT, 18, "bold")).pack(side="left")
        self.tabview = ctk.CTkTabview(
            self, fg_color=CARD, segmented_button_fg_color=CARD2,
            segmented_button_selected_color=TRACK,
            segmented_button_selected_hover_color=TRACK,
            text_color=FG, corner_radius=10,
        )
        self.tabview.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        self.tab_general = self.tabview.add("General")
        self.tab_osd = self.tabview.add("OSD")
        self.tab_about = self.tabview.add("About")
        self._build_general()
        self._build_osd()
        self._build_about()
        footer = ctk.CTkFrame(self, fg_color=BG)
        footer.pack(fill="x", padx=20, pady=(0, 16))
        ctk.CTkButton(footer, text="Close", width=120, height=32,
                      fg_color=CARD2, hover_color=TRACK, text_color=FG,
                      font=(FONT, 12), corner_radius=8,
                      command=self.destroy).pack(side="right")
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _section(self, parent, title):
        ctk.CTkLabel(parent, text=title, text_color=BLUE,
                     font=(FONT, 12, "bold"), anchor="w").pack(
            fill="x", padx=16, pady=(14, 4))
        sep = ctk.CTkFrame(parent, fg_color=TRACK, height=1)
        sep.pack(fill="x", padx=16, pady=(0, 6))

    def _label(self, parent, text):
        ctk.CTkLabel(parent, text=text, text_color=DIM,
                     font=(FONT, 10), anchor="w").pack(
            fill="x", padx=16, pady=(4, 2))

    def _entry(self, parent, var, on_change=None):
        e = ctk.CTkEntry(parent, textvariable=var, height=32,
                         fg_color=CARD2, text_color=FG,
                         border_color=TRACK, font=(FONT, 11),
                         corner_radius=8)
        e.pack(fill="x", padx=16, pady=(0, 8))
        if on_change:
            e.bind("<FocusOut>", lambda ev: on_change())
            e.bind("<Return>", lambda ev: on_change())
        return e

    def _checkbox(self, parent, text, var, on_change=None):
        def _cb():
            if on_change:
                on_change()
        sw = ctk.CTkSwitch(parent, text=text, variable=var,
                           text_color=FG, font=(FONT, 11),
                           progress_color=BLUE, fg_color=TRACK,
                           button_color=FG, button_hover_color=FG,
                           command=_cb)
        sw.pack(fill="x", padx=16, pady=6)
        return sw

    def _build_general(self):
        p = self.tab_general

        self._section(p, "Appearance")
        self._label(p, "Theme Mode (restart required)")
        self.var_theme = tk.StringVar(value=CONFIG.get("theme_mode", "System"))
        theme_options = ["System", "Dark", "Light"]
        theme_combo = ctk.CTkComboBox(
            p, values=theme_options, variable=self.var_theme,
            command=self._on_theme_change,
            fg_color=CARD2, button_color=TRACK,
            button_hover_color=BLUE, border_color=TRACK,
            text_color=FG, dropdown_fg_color=CARD2,
            dropdown_text_color=FG, dropdown_hover_color=TRACK,
            font=(FONT, 11), corner_radius=8, state="readonly",
        )
        theme_combo.pack(fill="x", padx=16, pady=(0, 6))
        ctk.CTkButton(
            p, text="Apply & Restart Now", height=32,
            fg_color=CARD2, hover_color=TRACK, text_color=BLUE,
            font=(FONT, 11), corner_radius=8,
            command=self._apply_theme_restart,
        ).pack(fill="x", padx=16, pady=(0, 12))

        self._section(p, "Performance")
        self._label(p, "UI update interval (ms)")
        self.var_update = tk.StringVar(value=str(CONFIG.get("update_ms")))
        self._entry(p, self.var_update, on_change=self._on_update_interval)
        self._label(p, "LHM collect interval (seconds)")
        self.var_collect = tk.StringVar(value=str(CONFIG.get("collect_interval")))
        self._entry(p, self.var_collect, on_change=self._on_collect_interval)

        self._section(p, "Startup")
        self.var_start_min = tk.BooleanVar(value=CONFIG.get("start_minimized", False))
        self._checkbox(p, "Start minimized to system tray", self.var_start_min,
                       on_change=lambda: CONFIG.set("start_minimized",
                                                    self.var_start_min.get()))

        self._section(p, "GPU")
        self.var_auto_gpu = tk.BooleanVar(value=CONFIG.get("auto_gpu_select", True))
        self._checkbox(p, "Auto-switch to GPU used by games", self.var_auto_gpu,
                       on_change=lambda: CONFIG.set("auto_gpu_select",
                                                    self.var_auto_gpu.get()))
        self._label(p, "Default GPU (used when no game is running)")
        gpu_names = [g.Name for g in self.app.gpus] or ["No GPU found"]
        self.var_gpu = tk.StringVar()
        current_idx = CONFIG.get("default_gpu_index", 0)
        if 0 <= current_idx < len(gpu_names):
            self.var_gpu.set(gpu_names[current_idx])
        else:
            self.var_gpu.set(gpu_names[0])
        combo = ctk.CTkComboBox(p, values=gpu_names, variable=self.var_gpu,
                                command=self._on_default_gpu,
                                fg_color=CARD2, button_color=TRACK,
                                button_hover_color=BLUE, border_color=TRACK,
                                text_color=FG, dropdown_fg_color=CARD2,
                                dropdown_text_color=FG, dropdown_hover_color=TRACK,
                                font=(FONT, 11), corner_radius=8,
                                state="readonly")
        combo.pack(fill="x", padx=16, pady=(0, 10))

        self._section(p, "Logging")
        self.var_log_enabled = tk.BooleanVar(value=CONFIG.get("log_enabled", False))
        self._checkbox(p, "Save performance log (CSV)", self.var_log_enabled,
                       on_change=self._on_log_enabled)
        self._label(p, "Log interval (seconds)")
        self.var_log_interval = tk.StringVar(value=str(CONFIG.get("log_interval_s", 2.0)))
        self._entry(p, self.var_log_interval, on_change=self._on_log_interval)
        ctk.CTkButton(p, text="Open Logs Folder", height=30,
                      fg_color=CARD2, hover_color=TRACK, text_color=BLUE,
                      font=(FONT, 10), corner_radius=8,
                      command=self.app._open_logs_folder).pack(fill="x", padx=16, pady=(0, 12))

        self._section(p, "Reset")
        ctk.CTkButton(p, text="Reset all settings to defaults", height=34,
                      fg_color=CARD2, hover_color="#3a1f1f", text_color=RED,
                      font=(FONT, 11), corner_radius=8,
                      command=self._reset_all).pack(fill="x", padx=16, pady=(0, 12))

    def _build_osd(self):
        p = self.tab_osd
        self._section(p, "Appearance")
        self._label(p, "Opacity (0.3 – 1.0)")
        self.var_alpha = tk.DoubleVar(value=CONFIG.get("osd_alpha", 0.75))
        self.alpha_val_lbl = ctk.CTkLabel(p, text=f"{self.var_alpha.get():.2f}",
                                          text_color=FG, font=(FONT, 10))
        self.alpha_val_lbl.pack(anchor="e", padx=16)
        ctk.CTkSlider(p, from_=0.3, to=1.0, number_of_steps=14,
                      variable=self.var_alpha, command=self._on_alpha,
                      fg_color=TRACK, progress_color=BLUE,
                      button_color=FG, button_hover_color=FG,
                      height=16).pack(fill="x", padx=16, pady=(0, 12))
        self._label(p, "Font size (8 – 20)")
        self.var_font = tk.IntVar(value=CONFIG.get("osd_font_size", 12))
        self.font_val_lbl = ctk.CTkLabel(p, text=f"{self.var_font.get()}",
                                         text_color=FG, font=(FONT, 10))
        self.font_val_lbl.pack(anchor="e", padx=16)
        ctk.CTkSlider(p, from_=8, to=20, number_of_steps=12,
                      variable=self.var_font, command=self._on_font_size,
                      fg_color=TRACK, progress_color=BLUE,
                      button_color=FG, button_hover_color=FG,
                      height=16).pack(fill="x", padx=16, pady=(0, 12))
        self._section(p, "Content")
        self.var_show_fps = tk.BooleanVar(value=CONFIG.get("osd_show_fps", True))
        self.var_show_gpu = tk.BooleanVar(value=CONFIG.get("osd_show_gpu", True))
        self.var_show_cpu = tk.BooleanVar(value=CONFIG.get("osd_show_cpu", True))
        self.var_show_ram = tk.BooleanVar(value=CONFIG.get("osd_show_ram", True))
        self.var_show_net = tk.BooleanVar(value=CONFIG.get("osd_show_net", True))
        self._checkbox(p, "Show FPS", self.var_show_fps,
                       on_change=lambda: self._toggle("osd_show_fps", self.var_show_fps))
        self._checkbox(p, "Show GPU", self.var_show_gpu,
                       on_change=lambda: self._toggle("osd_show_gpu", self.var_show_gpu))
        self._checkbox(p, "Show CPU", self.var_show_cpu,
                       on_change=lambda: self._toggle("osd_show_cpu", self.var_show_cpu))
        self._checkbox(p, "Show RAM", self.var_show_ram,
                       on_change=lambda: self._toggle("osd_show_ram", self.var_show_ram))
        self._checkbox(p, "Show Network", self.var_show_net,
                       on_change=lambda: self._toggle("osd_show_net", self.var_show_net))
        self._section(p, "Position")
        ctk.CTkButton(p, text="Reset OSD position to top-center", height=32,
                      fg_color=CARD2, hover_color=TRACK, text_color=FG,
                      font=(FONT, 11), corner_radius=8,
                      command=self._reset_osd_pos).pack(fill="x", padx=16, pady=(0, 12))

    def _build_about(self):
        p = self.tab_about
        ctk.CTkLabel(p, text="Hardware Monitor", text_color=FG,
                     font=(FONT, 16, "bold")).pack(pady=(40, 6))
        ctk.CTkLabel(p, text="Version 2.7 (AMD + Intel Support)", text_color=DIM,
                     font=(FONT, 11)).pack()
        ctk.CTkLabel(p, text="Real-time CPU, GPU, RAM & Disk monitoring",
                     text_color=DIM, font=(FONT, 10)).pack(pady=(14, 4))
        ctk.CTkLabel(p, text="Powered by LibreHardwareMonitor + RTSS",
                     text_color=DIM, font=(FONT, 10, "italic")).pack()
        ctk.CTkLabel(p, text="", text_color=BG).pack(pady=8)
        ctk.CTkLabel(p, text="Config file:", text_color=DIM,
                     font=(FONT, 10)).pack(pady=(20, 2))
        ctk.CTkLabel(p, text=str(CONFIG.path), text_color=BLUE,
                     font=(FONT, 9), wraplength=440).pack()

    def _on_update_interval(self):
        try:
            v = int(self.var_update.get())
            v = max(200, min(10000, v))
            CONFIG.set("update_ms", v)
            self.app.update_ms = v
            self.var_update.set(str(v))
        except Exception:
            self.var_update.set(str(CONFIG.get("update_ms")))

    def _on_collect_interval(self):
        try:
            v = float(self.var_collect.get())
            v = max(0.2, min(10.0, v))
            CONFIG.set("collect_interval", v)
            if self.app.collector:
                self.app.collector.set_interval(v)
            self.var_collect.set(str(v))
        except Exception:
            self.var_collect.set(str(CONFIG.get("collect_interval")))

    def _on_log_enabled(self):
        enabled = self.var_log_enabled.get()
        CONFIG.set("log_enabled", enabled)
        if enabled:
            self.app.log_writer.start()
        else:
            self.app.log_writer.stop()

    def _on_log_interval(self):
        try:
            v = float(self.var_log_interval.get())
            v = max(0.5, min(60, v))
            CONFIG.set("log_interval_s", v)
            self.app.log_writer.set_interval(v)
            self.var_log_interval.set(str(v))
        except Exception:
            self.var_log_interval.set(str(CONFIG.get("log_interval_s", 2.0)))

    def _on_default_gpu(self, value):
        try:
            names = list(self.app.gpu_names)
            idx = names.index(value)
            CONFIG.set("default_gpu_index", idx)
        except Exception:
            pass

    def _on_alpha(self, value):
        try:
            v = float(value)
            self.alpha_val_lbl.configure(text=f"{v:.2f}")
            CONFIG.set("osd_alpha", v)
            if self.app.osd:
                self.app.osd.apply_alpha(v)
        except Exception:
            pass

    def _on_font_size(self, value):
        try:
            v = int(float(value))
            self.font_val_lbl.configure(text=f"{v}")
            CONFIG.set("osd_font_size", v)
            if self.app.osd:
                self.app.osd.apply_font_size(v)
        except Exception:
            pass

    def _toggle(self, key, var):
        try:
            CONFIG.set(key, var.get())
            if self.app.osd and self.app.osd.visible:
                self.app.osd._last_text = None
        except Exception:
            pass

    def _reset_osd_pos(self):
        CONFIG.set("osd_x", None)
        CONFIG.set("osd_y", 8)
        if self.app.osd:
            try:
                self.app.osd._auto_center = True
                self.app.osd._resize_to_content()
            except Exception:
                pass

    def _on_theme_change(self, value):
        try:
            CONFIG.set("theme_mode", value)
        except Exception:
            pass

    def _apply_theme_restart(self):
        try:
            self.app.on_close()
        except Exception:
            pass
        try:
            os.execl(sys.executable, sys.executable, *sys.argv)
        except Exception:
            pass

    def _reset_all(self):
        for k, v in DEFAULT_CONFIG.items():
            CONFIG.set(k, v)
        self.var_update.set(str(DEFAULT_CONFIG["update_ms"]))
        self.var_collect.set(str(DEFAULT_CONFIG["collect_interval"]))
        self.var_alpha.set(DEFAULT_CONFIG["osd_alpha"])
        self.var_font.set(DEFAULT_CONFIG["osd_font_size"])
        self.var_show_fps.set(DEFAULT_CONFIG["osd_show_fps"])
        self.var_show_gpu.set(DEFAULT_CONFIG["osd_show_gpu"])
        self.var_show_cpu.set(DEFAULT_CONFIG["osd_show_cpu"])
        self.var_show_ram.set(DEFAULT_CONFIG["osd_show_ram"])
        self.var_show_net.set(DEFAULT_CONFIG["osd_show_net"])
        self.var_start_min.set(DEFAULT_CONFIG["start_minimized"])
        self.var_auto_gpu.set(DEFAULT_CONFIG["auto_gpu_select"])
        self.var_theme.set(DEFAULT_CONFIG["theme_mode"])
        self.var_log_enabled.set(DEFAULT_CONFIG["log_enabled"])
        self.var_log_interval.set(str(DEFAULT_CONFIG["log_interval_s"]))


# ---------- Background Data Collector ----------
class DataCollector:
    def __init__(self, cpu_cache, gpu_caches, interval=1.0):
        self.cpu_cache = cpu_cache
        self.gpu_caches = gpu_caches
        self.current_gpu_index = 0
        self.interval = interval
        self._lock = threading.Lock()
        self._snapshot = {}
        self._stop_flag = False
        self._thread = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_flag = False
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_flag = True
        if self._thread:
            self._thread.join(timeout=2.0)

    def set_gpu_index(self, idx):
        with self._lock:
            self.current_gpu_index = idx

    def set_interval(self, seconds):
        self.interval = max(0.2, min(10.0, float(seconds)))

    def get(self):
        with self._lock:
            return dict(self._snapshot)

    def _loop(self):
        try:
            refresh_lhm()
        except Exception:
            pass
        while not self._stop_flag:
            t0 = time.time()
            try:
                refresh_lhm()
                cpu_data = read_cpu_summary(self.cpu_cache)
                cpu_clock = read_cpu_clock(self.cpu_cache)
                with self._lock:
                    idx = self.current_gpu_index
                    interval = self.interval
                gpu_data = None
                if 0 <= idx < len(self.gpu_caches):
                    try:
                        gpu_data = read_gpu(self.gpu_caches[idx])
                    except Exception:
                        gpu_data = None
                with self._lock:
                    self._snapshot = {"cpu": cpu_data, "cpu_clock": cpu_clock, "gpu": gpu_data}
            except Exception:
                pass
            elapsed = time.time() - t0
            sleep_for = self.interval - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)


# ---------- Main App ----------
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Hardware Monitor")
        self.geometry("720x1000")
        self.minsize(MIN_WIDTH, MIN_HEIGHT)
        self.configure(fg_color=BG)

        self.update_ms = CONFIG.get("update_ms", 1000)
        self.normal_geometry = "720x1000"
        self.always_on_top = tk.BooleanVar(value=False)
        self.compact_mode = tk.BooleanVar(value=False)
        self.tray_icon = None
        self._tray_thread = None
        self._icon_img = None
        self._icon_photo = None
        self.osd_enabled = tk.BooleanVar(value=False)
        self.osd = None
        self.settings_window = None
        self.details_window = None
        self.gpu_details_window = None
        self.all_procs_window = None
        self.disk_path = "C:\\" if os.name == "nt" else "/"
        self.log_enabled_var = tk.BooleanVar(value=CONFIG.get("log_enabled", False))
        self._cpu_power_zero_count = 0
        self._pawnio_warning_active = False
        self._fps = None
        self._frametime = None
        self._fps_app = None
        self._manual_gpu_change_t = 0.0
        self._last_proc_snapshot = None
        self._proc_icon_refs = []

        try:
            self._set_window_icon()
        except Exception:
            pass

        self._build_menu()

        self.bind("<Control-o>", lambda e: self._toggle_osd())
        self.bind("<Control-O>", lambda e: self._toggle_osd())
        self.bind("<Control-comma>", lambda e: self._open_settings())

        header = ctk.CTkFrame(self, fg_color=BG)
        header.pack(fill="x", padx=20, pady=(16, 8))
        ctk.CTkLabel(header, text="Hardware Monitor", text_color=FG,
                     font=(FONT, 20, "bold")).pack(side="left")
        self.clock = ctk.CTkLabel(header, text="", text_color=DIM,
                                  font=(FONT, 11))
        self.clock.pack(side="right")

        self.scroll = ctk.CTkScrollableFrame(self, fg_color=BG,
                                             scrollbar_button_color=TRACK,
                                             scrollbar_button_hover_color=CARD2,
                                             corner_radius=0)
        self.scroll.pack(fill="both", expand=True, padx=0, pady=0)
        content = self.scroll

        fps_card = ctk.CTkFrame(content, fg_color=CARD, corner_radius=12)
        fps_card.pack(fill="x", padx=14, pady=(4, 4))
        fps_head = ctk.CTkFrame(fps_card, fg_color=CARD)
        fps_head.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(fps_head, text="FPS", text_color=FG,
                     font=(FONT, 12, "bold")).pack(side="left")
        self.fps_app_lbl = ctk.CTkLabel(fps_head, text="", text_color=DIM,
                                        font=(FONT, 10))
        self.fps_app_lbl.pack(side="right")
        self.fps_value_lbl = ctk.CTkLabel(fps_card, text="—", text_color=DIM,
                                          font=(FONT, 32, "bold"), anchor="w")
        self.fps_value_lbl.pack(fill="x", padx=16, pady=(0, 0))
        self.frametime_lbl = ctk.CTkLabel(fps_card, text="— ms", text_color=DIM,
                                          font=(FONT, 10), anchor="w")
        self.frametime_lbl.pack(fill="x", padx=16, pady=(0, 12))
        if not self._rtss_available():
            self.fps_app_lbl.configure(text="Install RTSS for FPS", text_color=YELLOW)
            self.fps_app_lbl.bind("<Button-1>", lambda e: self._open_rtss_url())
            self.fps_app_lbl.configure(cursor="hand2")

        # GPU Selector
        sel_frame = ctk.CTkFrame(content, fg_color=BG)
        sel_frame.pack(fill="x", padx=20, pady=(12, 8))
        
        ctk.CTkLabel(sel_frame, text="GPU:", text_color=DIM,
                     font=(FONT, 12, "bold")).pack(side="left", padx=(0, 8))
                     
        self.gpus = list_gpus()
        self.gpu_caches = [SensorCache(g) for g in self.gpus]
        self.gpu_names = [g.Name for g in self.gpus] or ["No GPU found"]
        default_idx = CONFIG.get("default_gpu_index", 0)
        if self.gpu_names and self.gpu_names[0] != "No GPU found":
            if not (0 <= default_idx < len(self.gpu_names)):
                default_idx = 0
            self.current_gpu_cache = self.gpu_caches[default_idx]
        else:
            self.current_gpu_cache = None
            
        self.gpu_selector = ctk.CTkComboBox(
            sel_frame, values=self.gpu_names,
            command=self.on_gpu_change,
            height=32, 
            fg_color=CARD2, button_color=TRACK, button_hover_color=BLUE,
            border_color=TRACK, text_color=FG,
            dropdown_fg_color=CARD2, dropdown_text_color=FG,
            dropdown_hover_color=TRACK,
            font=(FONT, 12), corner_radius=8, state="readonly",
        )
        if self.gpu_names and self.gpu_names[0] != "No GPU found":
            self.gpu_selector.set(self.gpu_names[default_idx])
        self.gpu_selector.pack(side="left", fill="x", expand=True)

        # Gauges
        gauges_frame = ctk.CTkFrame(content, fg_color=BG)
        gauges_frame.pack(fill="x", pady=(8, 12))
        for i in range(4):
            gauges_frame.columnconfigure(i, weight=1, uniform="gauge")
            
        self.cpu_gauge = CircularGauge(gauges_frame, "CPU")
        self.gpu_gauge = CircularGauge(gauges_frame, "GPU")
        self.ram_gauge = CircularGauge(gauges_frame, "RAM")
        self.disk_gauge = CircularGauge(gauges_frame, "DISK")
        
        self.cpu_gauge.frame.grid(row=0, column=0, padx=6, sticky="nsew")
        self.gpu_gauge.frame.grid(row=0, column=1, padx=6, sticky="nsew")
        self.ram_gauge.frame.grid(row=0, column=2, padx=6, sticky="nsew")
        self.disk_gauge.frame.grid(row=0, column=3, padx=6, sticky="nsew")

        self.cpu_hw = get_cpu_hardware()
        self.cpu_cache = SensorCache(self.cpu_hw)
        self.cpu_card = CpuCard(content, self.open_cpu_details,
                                on_warning_click=self._open_pawnio_url)

        self.gpu_bar = InfoBar(content, "GPU", GREEN)
        self.ram_bar = InfoBar(content, "Memory", PURPLE)
        self.disk_bar = InfoBar(content, "Disk C:", ORANGE)
        if self.current_gpu_cache:
            self.gpu_bar.set_title(self._short_name(self.current_gpu_cache.hardware.Name))

        net_card = ctk.CTkFrame(content, fg_color=CARD, corner_radius=12)
        net_card.pack(fill="x", padx=14, pady=4)
        ctk.CTkLabel(net_card, text="Network", text_color=FG,
                     font=(FONT, 12, "bold")).pack(anchor="w", padx=16, pady=(12, 4))
        net_row = ctk.CTkFrame(net_card, fg_color=CARD)
        net_row.pack(fill="x", padx=16, pady=(0, 12))
        self.down_lbl = ctk.CTkLabel(net_row, text="↓ 0 B/s", text_color=GREEN,
                                     font=(FONT, 11, "bold"))
        self.down_lbl.pack(side="left")
        self.up_lbl = ctk.CTkLabel(net_row, text="↑ 0 B/s", text_color=BLUE,
                                   font=(FONT, 11, "bold"))
        self.up_lbl.pack(side="right")
        self._last_down = None
        self._last_up = None

        proc_card = ctk.CTkFrame(content, fg_color=CARD, corner_radius=12)
        proc_card.pack(fill="x", padx=14, pady=(4, 16))
        proc_header = ctk.CTkFrame(proc_card, fg_color=CARD)
        proc_header.pack(fill="x", padx=16, pady=(12, 8))
        ctk.CTkLabel(proc_header, text="Top Processes", text_color=FG,
                     font=(FONT, 12, "bold")).pack(side="left")
        ctk.CTkButton(
            proc_header, text="All Processes  ▸",
            width=130, height=26,
            fg_color=CARD2, hover_color=TRACK, text_color=BLUE,
            font=(FONT, 10, "bold"), corner_radius=6,
            command=self._open_all_processes,
        ).pack(side="right")
        self.proc_rows = tk.Frame(proc_card, bg=CARD)
        self.proc_rows.pack(fill="x", padx=12, pady=(0, 10))

        psutil.cpu_percent(interval=None)
        self.last_net = psutil.net_io_counters()
        self.last_net_t = time.time()
        self.tick = 0
        self._was_iconic = False

        self.collector = DataCollector(self.cpu_cache, self.gpu_caches,
                                       interval=CONFIG.get("collect_interval", 1.0))
        self.collector.set_gpu_index(default_idx)
        self.collector.start()

        self.log_writer = LogWriter()
        if CONFIG.get("log_enabled", False):
            self.log_writer.start()

        self.rtss = RtssReader()

        self.osd = OsdOverlay(self)
        if CONFIG.get("osd_enabled", False):
            self.osd_enabled.set(True)
            self.osd.show()

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<Unmap>", self._on_unmap)

        if CONFIG.get("start_minimized", False):
            self.after(500, self._minimize_to_tray)

        self.update()

    def _open_all_processes(self):
        if (self.all_procs_window is not None
                and self.all_procs_window.win.winfo_exists()):
            self.all_procs_window.win.lift()
            self.all_procs_window.win.focus_force()
            return
        self.all_procs_window = AllProcessesWindow(self)

    def _refresh_processes(self):
        procs = top_procs(5)
        procs.sort(key=lambda x: x[0], reverse=True)
        procs = procs[:5]

        snapshot = tuple((name, round(ram, 1)) for ram, cpu, name, _ in procs)
        if snapshot == self._last_proc_snapshot:
            return
        self._last_proc_snapshot = snapshot

        for widget in self.proc_rows.winfo_children():
            widget.destroy()
        self._proc_icon_refs = []

        for ram, cpu, name, exe in procs:
            row = tk.Frame(self.proc_rows, bg=CARD)
            row.pack(fill="x", pady=2)

            icon = ICON_CACHE.get(exe, size=20) if exe else None
            if icon:
                self._proc_icon_refs.append(icon)
                tk.Label(row, image=icon, bg=CARD).pack(side="left", padx=(2, 8))
            else:
                tk.Label(row, text="", bg=CARD, width=2).pack(side="left", padx=(2, 8))

            short = name if len(name) <= 24 else name[:22] + "…"
            tk.Label(row, text=short, bg=CARD, fg=FG, font=(FONT, 11),
                     anchor="w").pack(side="left", fill="x", expand=True)

            ram_tag = GREEN if ram < 3 else (YELLOW if ram < 8 else RED)
            tk.Label(row, text=f"{ram:.1f}%", bg=CARD, fg=ram_tag,
                     font=(FONT, 11, "bold"), anchor="e", width=6).pack(
                side="right", padx=(0, 4))

    def _rtss_available(self):
        try:
            return self.rtss.available()
        except Exception:
            return False

    def _open_rtss_url(self):
        import webbrowser
        try:
            webbrowser.open(RTSS_URL)
        except Exception:
            pass

    def _open_pawnio_url(self):
        import webbrowser
        try:
            webbrowser.open(PAWNIO_URL)
        except Exception:
            pass

    @staticmethod
    def _short_name(name):
        return name if len(name) <= 28 else name[:26] + "…"

    def _make_icon_image(self, size=64):
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        pad = max(2, size // 16)
        d.rounded_rectangle([pad, pad, size - pad, size - pad],
                            radius=max(6, size // 5), fill=BG,
                            outline=BLUE, width=max(1, size // 21))
        arc_pad = size // 4
        d.arc([arc_pad, arc_pad, size - arc_pad, size - arc_pad],
              start=140, end=400, fill=GREEN, width=max(2, size // 12))
        r = max(3, size // 13)
        c = size // 2
        d.ellipse([c - r, c - r, c + r, c + r], fill=FG)
        return img

    def _set_window_icon(self):
        img = self._make_icon_image(64)
        self._icon_img = img
        self._icon_photo = ImageTk.PhotoImage(img)
        self.iconphoto(True, self._icon_photo)

    def _build_menu(self):
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Settings…  (Ctrl+,)", command=self._open_settings)
        file_menu.add_separator()
        file_menu.add_command(label="Minimize to Tray", command=self._minimize_to_tray)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_checkbutton(label="Always on Top", variable=self.always_on_top,
                                  command=self._toggle_topmost)
        view_menu.add_checkbutton(label="Compact Mode", variable=self.compact_mode,
                                  command=self._toggle_compact)
        view_menu.add_separator()
        view_menu.add_checkbutton(label="OSD Overlay  (Ctrl+O)",
                                  variable=self.osd_enabled, command=self._toggle_osd)
        menubar.add_cascade(label="View", menu=view_menu)

        details_menu = tk.Menu(menubar, tearoff=0)
        details_menu.add_command(label="GPU Details…", command=self.open_gpu_details)
        details_menu.add_command(label="CPU Details…", command=self.open_cpu_details)
        details_menu.add_command(label="All Processes…", command=self._open_all_processes)
        menubar.add_cascade(label="Details", menu=details_menu)

        tools_menu = tk.Menu(menubar, tearoff=0)
        tools_menu.add_checkbutton(label="Enable CSV Logging",
                                   variable=self.log_enabled_var,
                                   command=self._toggle_logging)
        tools_menu.add_command(label="Open Logs Folder", command=self._open_logs_folder)
        tools_menu.add_separator()
        tools_menu.add_command(label="Install PawnIO driver…", command=self._open_pawnio_url)
        tools_menu.add_command(label="Install RTSS (for FPS)…", command=self._open_rtss_url)
        menubar.add_cascade(label="Tools", menu=tools_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self._show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.config(menu=menubar)

    def _toggle_topmost(self):
        try:
            self.attributes("-topmost", self.always_on_top.get())
        except Exception:
            pass

    def _toggle_compact(self):
        if self.compact_mode.get():
            self.normal_geometry = self.geometry()
            self.geometry("380x160")
            try:
                self.attributes("-topmost", True)
            except Exception:
                pass
            self.always_on_top.set(True)
        else:
            self.geometry(self.normal_geometry)
            try:
                self.attributes("-topmost", self.always_on_top.get())
            except Exception:
                pass

    def _toggle_osd(self):
        if self.osd is None:
            return
        want = self.osd_enabled.get()
        if want and not self.osd.visible:
            self.osd.show()
        elif not want and self.osd.visible:
            self.osd.hide()
        CONFIG.set("osd_enabled", want)

    def open_gpu_details(self):
        if self.gpu_details_window and self.gpu_details_window.win.winfo_exists():
            self.gpu_details_window.win.lift()
            self.gpu_details_window.win.focus_force()
            return
        self.gpu_details_window = GpuDetailsWindow(self, self)

    def _toggle_logging(self):
        enabled = self.log_enabled_var.get()
        CONFIG.set("log_enabled", enabled)
        if enabled:
            self.log_writer.start()
        else:
            self.log_writer.stop()

    def _open_logs_folder(self):
        logs_dir = Path(os.environ.get("APPDATA", ".")) / "HardwareMonitor" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(logs_dir))
        except Exception:
            import subprocess
            try:
                subprocess.Popen(["explorer", str(logs_dir)])
            except Exception:
                pass

    def _check_pawnio_warning(self, cpu_data):
        if CONFIG.get("pawnio_warning_dismissed", False):
            return
        if cpu_data and cpu_data.get("power") is not None and cpu_data["power"] < 0.5:
            self._cpu_power_zero_count += 1
        else:
            self._cpu_power_zero_count = 0
            if self._pawnio_warning_active:
                self._pawnio_warning_active = False
                self.cpu_card.show_warning(False)
        if self._cpu_power_zero_count >= 15 and not self._pawnio_warning_active:
            self._pawnio_warning_active = True
            self.cpu_card.show_warning(True)

    def _auto_detect_gpu(self):
        if self._fps is None:
            return
        if not CONFIG.get("auto_gpu_select", True):
            return
        now = time.time()
        if now - self._manual_gpu_change_t < 10:
            return
        if len(self.gpu_caches) < 2:
            return
        best_idx = None
        best_load = 5.0
        for i, cache in enumerate(self.gpu_caches):
            if cache.hardware is None:
                continue
            try:
                data = read_gpu(cache)
                load = data.get("load") or 0
                if load > best_load:
                    best_load = load
                    best_idx = i
            except Exception:
                continue
        try:
            current_name = self.gpu_selector.get()
            current_idx = self.gpu_names.index(current_name)
        except Exception:
            current_idx = -1
        if best_idx is not None and best_idx != current_idx:
            self.gpu_selector.set(self.gpu_names[best_idx])
            self.current_gpu_cache = self.gpu_caches[best_idx]
            self.gpu_bar.set_title(self._short_name(self.current_gpu_cache.hardware.Name))
            if self.collector is not None:
                self.collector.set_gpu_index(best_idx)

    def _update_osd_text(self, cpu_pct, cpu_data, gpu_data, vm, freq_current):
        parts = []
        if CONFIG.get("osd_show_fps", True):
            if self._fps is not None:
                parts.append(f"FPS  {self._fps:.0f}")
            else:
                parts.append("FPS  N/A")
        if CONFIG.get("osd_show_gpu", True) and gpu_data:
            g = ["GPU"]
            g.append(f"{gpu_data['load']:.0f}%" if gpu_data["load"] is not None else "N/A")
            g.append(f"{gpu_data['temp']:.0f}°C" if gpu_data["temp"] is not None else "N/A")
            if gpu_data["vram_used"] is not None:
                g.append(f"{fmt_bytes(gpu_data['vram_used'])}")
            else:
                g.append("N/A")
            g.append(f"{gpu_data['power']:.0f}W" if gpu_data["power"] is not None else "N/A")
            parts.append("  ".join(g))
        if CONFIG.get("osd_show_cpu", True):
            c = ["CPU"]
            c.append(f"{cpu_pct:.0f}%")
            c.append(f"{cpu_data['temp']:.0f}°C" if cpu_data["temp"] is not None else "N/A")
            c.append(f"{freq_current:.0f}MHz" if freq_current else "N/A")
            c.append(f"{cpu_data['power']:.1f}W" if cpu_data["power"] is not None else "N/A")
            parts.append("  ".join(c))
        if CONFIG.get("osd_show_ram", True):
            parts.append(f"RAM  {vm.percent:.0f}%")
        if CONFIG.get("osd_show_net", True):
            net = psutil.net_io_counters()
            dt = time.time() - self.last_net_t
            if dt > 0:
                down = (net.bytes_recv - self.last_net.bytes_recv) / dt
                up = (net.bytes_sent - self.last_net.bytes_sent) / dt
                parts.append(f"NET  ↓{fmt_bytes(down)}/s  ↑{fmt_bytes(up)}/s")
        text = "     |     ".join(parts)
        self.osd.set_text(text)

    def _open_settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            self.settings_window.focus_force()
            return
        self.settings_window = SettingsWindow(self, self)

    def _show_about(self):
        win = ctk.CTkToplevel(self)
        win.title("About")
        win.geometry("440x300")
        win.configure(fg_color=BG)
        win.resizable(False, False)
        win.transient(self)
        ctk.CTkLabel(win, text="Hardware Monitor", text_color=FG,
                     font=(FONT, 16, "bold")).pack(pady=(30, 6))
        ctk.CTkLabel(win, text="Version 2.7 (AMD + Intel Support)",
                     text_color=DIM, font=(FONT, 11)).pack()
        ctk.CTkLabel(win, text="Real-time CPU, GPU, RAM & Disk monitoring",
                     text_color=DIM, font=(FONT, 10)).pack(pady=(10, 0))
        ctk.CTkLabel(win, text="FPS by RTSS · Sensors by LibreHardwareMonitor",
                     text_color=DIM, font=(FONT, 10, "italic")).pack(pady=(2, 0))
        ctk.CTkButton(win, text="OK", width=100, height=34,
                      fg_color=CARD2, hover_color=TRACK, text_color=FG,
                      font=(FONT, 11), corner_radius=8,
                      command=win.destroy).pack(pady=22)

    def _minimize_to_tray(self):
        self.withdraw()
        if self.tray_icon is not None:
            return

        def show(icon, item):
            self.after(0, self._restore_from_tray)

        def quit_app(icon, item):
            icon.stop()
            self.after(0, self.on_close)

        menu = pystray.Menu(
            pystray.MenuItem("Show", show, default=True),
            pystray.MenuItem("Exit", quit_app),
        )
        self.tray_icon = pystray.Icon("HardwareMonitor", self._make_icon_image(64),
                                       "Hardware Monitor", menu)
        self._tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        self._tray_thread.start()

    def _restore_from_tray(self):
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
            self.tray_icon = None
        self.deiconify()
        self.lift()
        self.focus_force()

    def _on_unmap(self, event):
        if event.widget is self and self.state() == "iconic":
            self.after(50, self._minimize_to_tray)

    def open_cpu_details(self):
        if self.details_window and self.details_window.win.winfo_exists():
            self.details_window.win.lift()
            self.details_window.win.focus_force()
            return
        self.details_window = CpuDetailsWindow(self,
                                                lambda: read_cpu_details(self.cpu_cache))

    def on_gpu_change(self, value=None):
        try:
            idx = self.gpu_names.index(value) if value else -1
        except Exception:
            idx = -1
        if 0 <= idx < len(self.gpu_caches):
            self.current_gpu_cache = self.gpu_caches[idx]
            self.gpu_bar.set_title(self._short_name(self.current_gpu_cache.hardware.Name))
            if self.collector is not None:
                self.collector.set_gpu_index(idx)
            self._manual_gpu_change_t = time.time()

    def _read_fps(self):
        try:
            fps, ftime, appname = self.rtss.get_fps()
            self._fps = fps
            self._frametime = ftime
            self._fps_app = appname
        except Exception:
            self._fps = None
            self._frametime = None
            self._fps_app = None

    def update(self):
        try:
            state = self.state()
        except Exception:
            state = "normal"
        minimized = state == "iconic"
        osd_on = self.osd is not None and self.osd.visible

        if minimized and not self._was_iconic:
            self._was_iconic = True
        elif not minimized and self._was_iconic:
            self._was_iconic = False

        now = time.time()
        cpu_pct = psutil.cpu_percent(interval=None)
        vm = psutil.virtual_memory()

        self._read_fps()
        self._auto_detect_gpu()

        snap = self.collector.get()
        cpu_data = snap.get("cpu") or {
            "name": "Unknown CPU", "cores": psutil.cpu_count(logical=False),
            "threads": psutil.cpu_count(logical=True), "temp": None, "power": None,
        }
        freq_current = snap.get("cpu_clock")
        gpu_data = snap.get("gpu")

        self._check_pawnio_warning(cpu_data)

        if self.log_writer.writer is not None:
            net = psutil.net_io_counters()
            dt = now - self.last_net_t
            if dt > 0:
                down = (net.bytes_recv - self.last_net.bytes_recv) / dt
                up = (net.bytes_sent - self.last_net.bytes_sent) / dt
            else:
                down = up = 0
            self.log_writer.log(self._fps, self._frametime, cpu_pct, cpu_data,
                                freq_current, gpu_data, vm, down, up)

        if osd_on:
            self._update_osd_text(cpu_pct, cpu_data, gpu_data, vm, freq_current)

        if minimized:
            interval = self.update_ms if osd_on else 2000
            self.after(interval, self.update)
            return

        clock_txt = time.strftime("%H:%M:%S")
        if clock_txt != self.clock.cget("text"):
            self.clock.configure(text=clock_txt)

        if self._fps is not None:
            self.fps_value_lbl.configure(text=f"{self._fps:.0f}",
                                          text_color=pick_fps_color(self._fps))
            self.frametime_lbl.configure(text=f"{self._frametime:.2f} ms", text_color=DIM)
            if self._fps_app:
                try:
                    import ntpath
                    short = ntpath.basename(self._fps_app)
                except Exception:
                    short = self._fps_app
                self.fps_app_lbl.configure(text=short, text_color=BLUE)
        else:
            self.fps_value_lbl.configure(text="—", text_color=DIM)
            self.frametime_lbl.configure(text="— ms", text_color=DIM)
            if not self.rtss.available():
                self.fps_app_lbl.configure(text="Install RTSS for FPS", text_color=YELLOW)
            else:
                self.fps_app_lbl.configure(text="No game running", text_color=DIM)

        self.cpu_gauge.set(cpu_pct)
        self.cpu_card.set(cpu_data, freq_current)

        if gpu_data:
            load = gpu_data["load"] if gpu_data["load"] is not None else 0
            self.gpu_gauge.set(load)
            parts = [f"{gpu_data['temp']:.0f}°C" if gpu_data["temp"] is not None else "N/A"]
            if gpu_data["vram_used"] is not None and gpu_data["vram_total"] is not None:
                parts.append(f"{fmt_bytes(gpu_data['vram_used'])} / {fmt_bytes(gpu_data['vram_total'])}")
            else:
                parts.append("N/A")
            parts.append(f"{gpu_data['power']:.1f}W" if gpu_data["power"] is not None else "N/A")
            vram_pct = 0
            if gpu_data["vram_used"] and gpu_data["vram_total"]:
                vram_pct = (gpu_data["vram_used"] / gpu_data["vram_total"]) * 100
            self.gpu_bar.set("  ·  ".join(parts), vram_pct)

        self.ram_gauge.set(vm.percent)
        self.ram_bar.set(f"{fmt_bytes(vm.used)} / {fmt_bytes(vm.total)}", vm.percent)

        try:
            du = psutil.disk_usage(self.disk_path)
            self.disk_gauge.set(du.percent)
            self.disk_bar.set(f"{fmt_bytes(du.used)} / {fmt_bytes(du.total)}", du.percent)
        except Exception:
            pass

        net = psutil.net_io_counters()
        dt = now - self.last_net_t
        if dt > 0:
            down = (net.bytes_recv - self.last_net.bytes_recv) / dt
            up = (net.bytes_sent - self.last_net.bytes_sent) / dt
            down_txt = f"↓ {fmt_bytes(down)}/s"
            if down_txt != self._last_down:
                self._last_down = down_txt
                self.down_lbl.configure(text=down_txt)
            up_txt = f"↑ {fmt_bytes(up)}/s"
            if up_txt != self._last_up:
                self._last_up = up_txt
                self.up_lbl.configure(text=up_txt)
        self.last_net, self.last_net_t = net, now

        self.tick += 1
        if self.tick % 3 == 0:
            self._refresh_processes()

        self.after(self.update_ms, self.update)

    def on_close(self):
        if self.collector is not None:
            try:
                self.collector.stop()
            except Exception:
                pass
        if self.log_writer is not None:
            try:
                self.log_writer.stop()
            except Exception:
                pass
        if self.rtss is not None:
            try:
                self.rtss.close()
            except Exception:
                pass
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
            self.tray_icon = None
        if self.details_window and self.details_window.win.winfo_exists():
            self.details_window.close()
        if self.gpu_details_window and self.gpu_details_window.win.winfo_exists():
            self.gpu_details_window.close()
        if (self.all_procs_window is not None
                and self.all_procs_window.win.winfo_exists()):
            self.all_procs_window.close()
        if self.osd is not None:
            self.osd.destroy()
        try:
            COMPUTER.Close()
        except Exception:
            pass
        self.destroy()


if __name__ == "__main__":
    App().mainloop()