#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════
# FCB Agent v1.0 — Federação Columbófila Brasileira
# Captura chegadas do constatador e envia ao painel ao vivo
# fcbpigeonslive.com.br
# ═══════════════════════════════════════════════════════════════

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import serial
import serial.tools.list_ports
import requests
import json
import time
import logging
import os
import sys
import queue
from datetime import datetime
from pathlib import Path
import pystray
from PIL import Image, ImageDraw
import winreg
import subprocess

# ── Paths ──────────────────────────────────────────────────────
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent

CONFIG_FILE  = BASE_DIR / "config.json"
OFFLINE_FILE = BASE_DIR / "offline_queue.json"
LOG_FILE     = BASE_DIR / "fcbagent.log"

# ── Logging ────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
    ]
)
log = logging.getLogger("FCBAgent")

# ── Config padrão ──────────────────────────────────────────────
DEFAULT_CONFIG = {
    "criador_id":   "",
    "criador_nome": "",
    "clube_id":     "",
    "api_token":    "",
    "api_url":      "https://api.fcbpigeonslive.com.br/api/chegadas",
    "serial_port":  "auto",
    "baud_rate":    9600,
    "autostart":    True,
    "minimized":    True,
}

def load_config():
    if CONFIG_FILE.exists():
        try:
            return {**DEFAULT_CONFIG, **json.loads(CONFIG_FILE.read_text(encoding='utf-8'))}
        except:
            pass
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding='utf-8')

# ── Offline queue ──────────────────────────────────────────────
def load_queue():
    if OFFLINE_FILE.exists():
        try:
            return json.loads(OFFLINE_FILE.read_text(encoding='utf-8'))
        except:
            return []
    return []

def save_queue(q):
    OFFLINE_FILE.write_text(json.dumps(q, indent=2), encoding='utf-8')

# ── Parser Unives 1.7 ──────────────────────────────────────────
def parse_unives(raw):
    if len(raw) < 20:
        return None
    if raw[0] != 0x02 or raw[-1] != 0x03:
        return None
    if raw[1] != 0x41:
        return None
    chk = 0
    for b in raw[1:-3]:
        chk ^= b
    if chk != int.from_bytes(raw[-3:-1], 'big'):
        return None
    def bcd(b): return (b >> 4) * 10 + (b & 0x0F)
    transponder = raw[2:10].hex().upper()
    hh = bcd(raw[10]); mm = bcd(raw[11]); ss = bcd(raw[12])
    dd = bcd(raw[13]); mo = bcd(raw[14]); aa = bcd(raw[15]) + 2000
    return {
        "transponder_id":  transponder,
        "timestamp_local": f"{aa}-{mo:02d}-{dd:02d}T{hh:02d}:{mm:02d}:{ss:02d}",
        "timestamp_utc":   datetime.utcnow().isoformat() + "Z",
    }

# ── Autostart no Windows ───────────────────────────────────────
REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_KEY  = "FCBAgent"

def set_autostart(enable):
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_SET_VALUE)
        if enable:
            exe = sys.executable if getattr(sys, 'frozen', False) else f'pythonw "{__file__}"'
            winreg.SetValueEx(key, REG_KEY, 0, winreg.REG_SZ, f'"{exe}" --minimized')
        else:
            try: winreg.DeleteValue(key, REG_KEY)
            except: pass
        winreg.CloseKey(key)
    except Exception as e:
        log.warning(f"Autostart: {e}")

# ══════════════════════════════════════════════════════════════
# ENGINE — roda em thread separada
# ══════════════════════════════════════════════════════════════
class FCBEngine(threading.Thread):
    def __init__(self, ui_queue):
        super().__init__(daemon=True)
        self.ui_queue  = ui_queue
        self.running   = False
        self.cfg       = load_config()
        self.ser       = None
        self.connected = False

    def emit(self, tipo, msg, dados=None):
        self.ui_queue.put({"tipo": tipo, "msg": msg, "dados": dados})

    def detectar_porta(self):
        DRIVERS = ["CP210x","FTDI","CH340","PL2303","CDC","ACM","Serial"]
        portas  = serial.tools.list_ports.comports()
        for p in portas:
            desc = (p.description or "") + (p.manufacturer or "")
            if any(d.lower() in desc.lower() for d in DRIVERS):
                return p.device
        if portas:
            return portas[0].device
        return None

    def enviar(self, dados):
        cfg = load_config()
        headers = {
            "Authorization": f"Bearer {cfg['api_token']}",
            "Content-Type":  "application/json",
            "X-Agent-ID":    f"AGENT-{cfg['criador_id']}",
        }
        payload = {
            **dados,
            "criador_id": cfg["criador_id"],
            "clube_id":   cfg["clube_id"],
            "agent_version": "1.0",
        }
        try:
            r = requests.post(cfg["api_url"], json=payload, headers=headers, timeout=8)
            if r.status_code == 200:
                resp = r.json()
                vel  = resp.get("velocidade", "—")
                return True, vel
            else:
                return False, None
        except Exception as e:
            return False, None

    def sincronizar_offline(self):
        fila = load_queue()
        if not fila:
            return
        self.emit("log", f"Sincronizando {len(fila)} chegadas offline...", "info")
        enviadas = []
        for item in fila:
            ok, _ = self.enviar(item)
            if ok:
                enviadas.append(item)
            else:
                break
        fila = [i for i in fila if i not in enviadas]
        save_queue(fila)
        if enviadas:
            self.emit("log", f"✓ {len(enviadas)} chegadas sincronizadas", "ok")

    def run(self):
        self.running = True
        cfg = load_config()

        if not cfg["criador_id"] or not cfg["api_token"]:
            self.emit("status", "Configuração incompleta", "erro")
            self.emit("log", "⚠ Configure seu ID FCB e Token antes de iniciar", "erro")
            return

        porta = cfg["serial_port"]
        if porta == "auto":
            porta = self.detectar_porta()
        if not porta:
            self.emit("status", "Constatador não encontrado", "erro")
            self.emit("log", "⚠ Nenhum constatador detectado. Verifique a conexão USB.", "erro")
            return

        self.emit("log", f"Constatador detectado: {porta}", "info")
        self.emit("status", f"Conectando... {porta}", "info")

        try:
            self.ser = serial.Serial(
                port=porta, baudrate=cfg["baud_rate"],
                bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE, timeout=1.0
            )
        except Exception as e:
            self.emit("status", "Erro na porta serial", "erro")
            self.emit("log", f"⚠ Erro ao abrir {porta}: {e}", "erro")
            return

        self.connected = True
        self.emit("status", f"Monitorando · {porta}", "ok")
        self.emit("log", f"✓ Conectado em {porta} · {cfg['baud_rate']} baud", "ok")
        self.emit("log", "Aguardando chegadas de pombos...", "info")
        self.emit("conectado", None)

        buffer      = bytearray()
        ultimo_sync = time.time()

        while self.running:
            try:
                byte = self.ser.read(1)
                if not byte:
                    continue

                buffer.extend(byte)

                if buffer[0:1] != b'\x02':
                    buffer = bytearray()
                    continue

                if byte == b'\x03' and len(buffer) >= 20:
                    dados = parse_unives(bytes(buffer))
                    buffer = bytearray()

                    if dados:
                        tid = dados["transponder_id"]
                        ts  = dados["timestamp_local"][11:]
                        self.emit("log", f"🕊 Anilha {tid} · {ts} · enviando...", "lj")

                        ok, vel = self.enviar(dados)
                        if ok:
                            vel_str = f"{vel:,.2f} m/min".replace(",","X").replace(".",",").replace("X",".") if isinstance(vel, (int,float)) else "—"
                            self.emit("log", f"✓ Chegada registrada · {vel_str}", "ok")
                            self.emit("chegada", dados.get("timestamp_local",""), vel)
                        else:
                            fila = load_queue()
                            fila.append(dados)
                            save_queue(fila)
                            self.emit("log", f"⚠ Sem internet · salvo offline ({len(fila)} na fila)", "erro")

                if len(buffer) > 64:
                    buffer = bytearray()

                if time.time() - ultimo_sync > 60:
                    self.sincronizar_offline()
                    ultimo_sync = time.time()

            except serial.SerialException:
                self.emit("status", "Constatador desconectado", "erro")
                self.emit("log", "⚠ Constatador desconectado. Reconectando...", "erro")
                self.connected = False
                self.emit("desconectado", None)
                time.sleep(5)
                try:
                    self.ser = serial.Serial(porta, cfg["baud_rate"], timeout=1.0)
                    self.connected = True
                    self.emit("status", f"Reconectado · {porta}", "ok")
                    self.emit("log", "✓ Reconectado", "ok")
                    self.emit("conectado", None)
                except:
                    pass

        if self.ser and self.ser.is_open:
            self.ser.close()

    def stop(self):
        self.running = False


# ══════════════════════════════════════════════════════════════
# JANELA DE CONFIGURAÇÃO
# ══════════════════════════════════════════════════════════════
class ConfigWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("FCB Agent · Configuração")
        self.resizable(True, True)
        self.configure(bg="#0a1a0c")
        self.grab_set()

        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w = min(480, sw - 40)
        h = min(540, sh - 80)
        x = (sw - w) // 2
        y = max(0, (sh - h) // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(min(440, sw - 40), min(460, sh - 80))

        cfg = load_config()

        lbl_opts = dict(bg="#0a1a0c", fg="#8a9a8e", font=("Segoe UI", 9))
        ent_opts  = dict(bg="#0f240f", fg="#f2f0ea", font=("Consolas", 10),
                         insertbackground="#f2f0ea", relief="flat",
                         highlightthickness=1, highlightcolor="#2d7a3e",
                         highlightbackground="#1a3a1c")

        def section(text):
            f = tk.Frame(self, bg="#0d2e1a", height=1)
            f.pack(fill="x", padx=20, pady=(14,4))
            tk.Label(f, text=text.upper(), bg="#0d2e1a", fg="#2d7a3e",
                     font=("Segoe UI", 8, "bold")).pack(side="left", padx=8, pady=3)

        def field(label, var, placeholder="", show=""):
            tk.Label(self, text=label, **lbl_opts).pack(anchor="w", padx=24, pady=(4,1))
            e = tk.Entry(self, textvariable=var, show=show, width=46, **ent_opts)
            e.pack(padx=20, pady=(0,2))
            return e

        tk.Label(self, text="FCBAgent", bg="#0a1a0c", fg="#f2f0ea",
                 font=("Segoe UI", 14, "bold")).pack(pady=(18,0))
        tk.Label(self, text="CONFIGURAÇÃO DO CRIADOR", bg="#0a1a0c", fg="#2d7a3e",
                 font=("Consolas", 8)).pack(pady=(0,8))

        self.v_nome    = tk.StringVar(value=cfg.get("criador_nome",""))
        self.v_id      = tk.StringVar(value=cfg.get("criador_id",""))
        self.v_clube   = tk.StringVar(value=cfg.get("clube_id",""))
        self.v_token   = tk.StringVar(value=cfg.get("api_token",""))
        self.v_porta   = tk.StringVar(value=cfg.get("serial_port","auto"))
        self.v_auto    = tk.BooleanVar(value=cfg.get("autostart", True))

        section("Dados do Criador")
        field("Nome completo", self.v_nome)
        field("ID FCB (encontrado no painel)", self.v_id)
        field("ID do Clube", self.v_clube)

        section("Autenticação")
        field("Token FCB Agent (Painel → Minha Conta)", self.v_token, show="•")

        section("Constatador")
        tk.Label(self, text="Porta serial (deixe 'auto' para detectar automaticamente)", **lbl_opts).pack(anchor="w", padx=24, pady=(4,1))
        portas = ["auto"] + [p.device for p in serial.tools.list_ports.comports()]
        cb = ttk.Combobox(self, textvariable=self.v_porta, values=portas, width=44,
                          font=("Consolas", 10), state="normal")
        cb.pack(padx=20, pady=(0,4))

        tk.Checkbutton(self, text="Iniciar automaticamente com o Windows",
                       variable=self.v_auto, bg="#0a1a0c", fg="#8a9a8e",
                       selectcolor="#0d2e1a", activebackground="#0a1a0c",
                       font=("Segoe UI", 9)).pack(anchor="w", padx=20, pady=(8,4))

        bf = tk.Frame(self, bg="#0a1a0c")
        bf.pack(fill="x", padx=20, pady=12)
        tk.Button(bf, text="SALVAR", command=self.salvar,
                  bg="#ff6b00", fg="#000", font=("Segoe UI", 10, "bold"),
                  relief="flat", padx=24, pady=6, cursor="hand2").pack(side="right")
        tk.Button(bf, text="Cancelar", command=self.destroy,
                  bg="#0d2e1a", fg="#8a9a8e", font=("Segoe UI", 9),
                  relief="flat", padx=16, pady=6, cursor="hand2").pack(side="right", padx=8)

    def salvar(self):
        cfg = load_config()
        cfg["criador_nome"] = self.v_nome.get().strip()
        cfg["criador_id"]   = self.v_id.get().strip()
        cfg["clube_id"]     = self.v_clube.get().strip()
        cfg["api_token"]    = self.v_token.get().strip()
        cfg["serial_port"]  = self.v_porta.get().strip()
        cfg["autostart"]    = self.v_auto.get()

        if not cfg["criador_id"] or not cfg["api_token"]:
            messagebox.showerror("Campos obrigatórios", "ID FCB e Token são obrigatórios.")
            return

        save_config(cfg)
        set_autostart(cfg["autostart"])
        messagebox.showinfo("Salvo", "Configuração salva com sucesso!\nReinicie o FCB Agent para aplicar.")
        self.destroy()


# ══════════════════════════════════════════════════════════════
# JANELA PRINCIPAL
# ══════════════════════════════════════════════════════════════
class FCBAgentApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("FCB Agent")
        self.root.resizable(True, True)
        self.root.configure(bg="#060e07")
        try:
            from ctypes import windll
            windll.user32.SetProcessDPIAware()
        except:
            pass
        self.root.geometry("560x420+50+30")
        self.root.minsize(400, 360)
        self.root.protocol("WM_DELETE_WINDOW", self.minimizar)

        self.cfg        = load_config()
        self.engine     = None
        self.ui_queue   = queue.Queue()
        self.chegadas   = 0
        self.tray_icon  = None

        self._build_ui()
        self._build_tray()
        self._poll_queue()

        primeira_vez = not self.cfg.get("criador_id") or not self.cfg.get("api_token")

        if primeira_vez:
            self.root.after(500, self.abrir_config)
        else:
            self.iniciar_engine()
            if "--minimized" in sys.argv:
                self.root.after(300, self.minimizar)

        self.root.after(1000, self._criar_atalho)

    def _criar_atalho(self):
        try:
            desktop = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop", "FCB Agent.lnk")
            if not os.path.exists(desktop):
                exe = sys.executable if getattr(sys, "frozen", False) else sys.executable
                ps = (
                    f'$s=(New-Object -COM WScript.Shell).CreateShortcut("{desktop}");'
                    f'$s.TargetPath="{exe}";'
                    f'$s.Description="FCB Agent - Federacao Columbofila Brasileira";'
                    f'$s.Save()'
                )
                subprocess.run(["powershell", "-Command", ps],
                               capture_output=True, timeout=5)
                self.add_log("Atalho criado na Área de Trabalho", "ok")
        except Exception:
            pass

    def _build_ui(self):
        hdr = tk.Frame(self.root, bg="#0d2e1a", height=44)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        tk.Label(hdr, text="FCBAgent", bg="#0d2e1a", fg="#f2f0ea",
                 font=("Segoe UI", 11, "bold")).pack(side="left", padx=12, pady=6)
        tk.Label(hdr, text="v1.0", bg="#0d2e1a", fg="#2d7a3e",
                 font=("Consolas", 7)).pack(side="left", pady=12)

        btn_frame = tk.Frame(hdr, bg="#0d2e1a")
        btn_frame.pack(side="right", padx=8)
        tk.Button(btn_frame, text="⚙ Config", command=self.abrir_config,
                  bg="#0d2e1a", fg="#8a9a8e", font=("Segoe UI", 8),
                  relief="flat", padx=8, cursor="hand2").pack(side="left", padx=2)
        tk.Button(btn_frame, text="↓ Bandeja", command=self.minimizar,
                  bg="#0d2e1a", fg="#8a9a8e", font=("Segoe UI", 8),
                  relief="flat", padx=8, cursor="hand2").pack(side="left")

        sb = tk.Frame(self.root, bg="#070f08")
        sb.pack(fill="x")

        self.dot = tk.Canvas(sb, width=10, height=10, bg="#070f08", highlightthickness=0)
        self.dot.pack(side="left", padx=(16,6), pady=10)
        self.oval = self.dot.create_oval(1,1,9,9, fill="#333", outline="")

        self.lbl_status = tk.Label(sb, text="Iniciando...", bg="#070f08", fg="#8a9a8e",
                                   font=("Consolas", 9))
        self.lbl_status.pack(side="left")

        self.lbl_hora = tk.Label(sb, text="", bg="#070f08", fg="#333333",
                                 font=("Consolas", 9))
        self.lbl_hora.pack(side="right", padx=16)
        self._tick()

        stats = tk.Frame(self.root, bg="#060e07")
        stats.pack(fill="x", padx=12, pady=(6,0))

        def stat_box(parent, label):
            f = tk.Frame(parent, bg="#0a1a0c", relief="flat")
            f.pack(side="left", padx=3, expand=True, fill="x")
            num = tk.Label(f, text="0", bg="#0a1a0c", fg="#f2f0ea",
                           font=("Segoe UI", 16, "bold"))
            num.pack(pady=(4,0))
            tk.Label(f, text=label, bg="#0a1a0c", fg="#4a6a4e",
                     font=("Consolas", 6)).pack(pady=(0,4))
            return num

        self.num_chegadas = stat_box(stats, "CHEGADAS ENVIADAS")
        self.num_offline  = stat_box(stats, "NA FILA OFFLINE")
        self.num_sesssao  = stat_box(stats, "ESTA SESSÃO")

        lf = tk.Frame(self.root, bg="#060e07")
        lf.pack(fill="both", expand=True, padx=12, pady=6)

        tk.Label(lf, text="LOG EM TEMPO REAL", bg="#060e07", fg="#2d7a3e",
                 font=("Consolas", 7)).pack(anchor="w", pady=(0,2))

        self.log_text = scrolledtext.ScrolledText(
            lf, bg="#040c05", fg="#8a9a8e",
            font=("Consolas", 9), relief="flat",
            state="disabled", wrap="word",
            insertbackground="#f2f0ea",
        )
        self.log_text.pack(fill="both", expand=True)

        self.log_text.tag_config("ok",   foreground="#2d7a3e")
        self.log_text.tag_config("erro", foreground="#c05050")
        self.log_text.tag_config("lj",   foreground="#ff6b00")
        self.log_text.tag_config("info", foreground="#6a8a6e")

        bf = tk.Frame(self.root, bg="#060e07")
        bf.pack(fill="x", padx=12, pady=(0,10))

        self.btn_toggle = tk.Button(bf, text="⏹ PARAR MONITORAMENTO",
                                    command=self.toggle_engine,
                                    bg="#c05050", fg="#fff",
                                    font=("Segoe UI", 9, "bold"),
                                    relief="flat", pady=6, cursor="hand2")
        self.btn_toggle.pack(side="left", expand=True, fill="x")

        tk.Button(bf, text="🌐 Painel",
                  command=lambda: os.startfile("https://fcbpigeonslive.com.br/painel-admin"),
                  bg="#0d2e1a", fg="#2d7a3e",
                  font=("Segoe UI", 8), relief="flat", pady=6,
                  padx=10, cursor="hand2").pack(side="left", padx=(6,0))

        tk.Button(bf, text="🕊 Simular Chegada",
                  command=self.simular_chegada,
                  bg="#1a3a1c", fg="#ff6b00",
                  font=("Segoe UI", 8), relief="flat", pady=6,
                  padx=10, cursor="hand2").pack(side="left", padx=(6,0))

    def _tick(self):
        agora = datetime.now().strftime("%H:%M:%S")
        self.lbl_hora.config(text=agora)
        self.root.after(1000, self._tick)

    def add_log(self, msg, tag="info"):
        agora = datetime.now().strftime("%H:%M:%S")
        self.log_text.config(state="normal")
        self.log_text.insert("end", f"[{agora}] {msg}\n", tag)
        self.log_text.see("end")
        self.log_text.config(state="disabled")
        log.info(msg)

    def set_status(self, msg, estado="info"):
        cores = {"ok": "#2d7a3e", "erro": "#c05050", "info": "#8a9a8e"}
        cor   = cores.get(estado, "#8a9a8e")
        self.lbl_status.config(text=msg, fg=cor)
        self.dot.itemconfig(self.oval, fill=cor)
        if self.tray_icon:
            self.tray_icon.icon = self._make_icon(cor)

    def _poll_queue(self):
        try:
            while True:
                ev = self.ui_queue.get_nowait()
                tipo = ev["tipo"]
                msg  = ev.get("msg","")
                if tipo == "log":
                    self.add_log(msg, ev.get("dados","info") or "info")
                elif tipo == "status":
                    self.set_status(msg, ev.get("dados","info") or "info")
                elif tipo == "chegada":
                    self.chegadas += 1
                    self.num_chegadas.config(text=str(self.chegadas))
                    self.num_sesssao.config(text=str(self.chegadas))
                    self.num_offline.config(text=str(len(load_queue())))
                elif tipo == "conectado":
                    self.set_status("Monitorando · Aguardando pombos", "ok")
                    self.btn_toggle.config(text="⏹ PARAR", bg="#c05050")
                elif tipo == "desconectado":
                    self.set_status("Constatador desconectado", "erro")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def iniciar_engine(self):
        if self.engine and self.engine.is_alive():
            return
        self.engine = FCBEngine(self.ui_queue)
        self.engine.start()
        self.btn_toggle.config(text="⏹ PARAR MONITORAMENTO", bg="#c05050")
        self.add_log("FCB Agent iniciado", "ok")

    def parar_engine(self):
        if self.engine:
            self.engine.stop()
            self.engine = None
        self.set_status("Monitoramento pausado", "info")
        self.btn_toggle.config(text="▶ INICIAR MONITORAMENTO", bg="#2d7a3e")
        self.add_log("Monitoramento pausado", "info")

    def toggle_engine(self):
        if self.engine and self.engine.is_alive():
            self.parar_engine()
        else:
            self.iniciar_engine()

    def simular_chegada(self):
        import random, string
        anilha = "BR25-" + "".join(random.choices(string.digits, k=7))
        vel = round(random.uniform(1300, 1420), 2)
        vel_str = f"{vel:,.2f} m/min".replace(",","X").replace(".",",").replace("X",".")
        cfg = load_config()
        criador = cfg.get("criador_id", "9999")
        clube   = cfg.get("clube_id", "1")

        chegada = {
            "anilha":     anilha,
            "criador_id": criador,
            "clube_id":   clube,
            "velocidade": vel,
            "timestamp":  datetime.now().isoformat(),
            "simulado":   True,
        }

        self.add_log(f"🕊 [SIMULAÇÃO] Anilha {anilha} · {vel_str}", "lj")

        try:
            api_url = "https://api.fcbpigeonslive.com.br/api/chegadas"
            token   = cfg.get("api_token", "")
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            import urllib.request, json as _json
            req = urllib.request.Request(
                api_url,
                data=_json.dumps(chegada).encode(),
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                status = resp.status
            self.add_log(f"✓ Enviado para API · HTTP {status}", "ok")
        except Exception as e:
            self.add_log(f"⚠ API indisponível · registrado offline: {e}", "info")
            fila = load_queue()
            fila.append(chegada)
            save_queue(fila)
            self.num_offline.config(text=str(len(fila)))

        self.chegadas += 1
        self.num_chegadas.config(text=str(self.chegadas))
        self.num_sesssao.config(text=str(self.chegadas))
        self.ui_queue.put({"tipo": "chegada"})

    def abrir_config(self):
        ConfigWindow(self.root)

    def _make_icon(self, cor="#2d7a3e"):
        img  = Image.new("RGBA", (64,64), (0,0,0,0))
        draw = ImageDraw.Draw(img)
        r, g, b = int(cor[1:3],16), int(cor[3:5],16), int(cor[5:7],16)
        draw.ellipse([8,8,56,56], fill=(r,g,b,255))
        draw.ellipse([20,22,44,38], fill=(255,255,255,200))
        draw.polygon([(32,15),(44,28),(20,28)], fill=(255,255,255,180))
        return img

    def _build_tray(self):
        menu = pystray.Menu(
            pystray.MenuItem("Abrir FCB Agent", self.mostrar, default=True),
            pystray.MenuItem("Configuração", lambda: self.root.after(0, self.abrir_config)),
            pystray.MenuItem("Abrir Painel ao Vivo", lambda: os.startfile("https://fcbpigeonslive.com.br/painel-admin")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Sair", self.sair),
        )
        self.tray_icon = pystray.Icon("FCBAgent", self._make_icon(), "FCB Agent", menu)
        t = threading.Thread(target=self.tray_icon.run, daemon=True)
        t.start()

    def minimizar(self):
        self.root.withdraw()

    def mostrar(self):
        self.root.after(0, self.root.deiconify)
        self.root.after(0, self.root.lift)

    def sair(self):
        if self.engine:
            self.engine.stop()
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.destroy()
        sys.exit(0)

    def run(self):
        self.root.mainloop()


# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = FCBAgentApp()
    app.run()
