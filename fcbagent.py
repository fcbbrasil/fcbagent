#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════
# FCB Agent v2.0 — Federação Columbófila Brasileira
# Monitora pasta PAMPA e envia chegadas ao painel ao vivo
# fcbpigeonslive.com.br
# ═══════════════════════════════════════════════════════════════

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import requests
import json
import time
import logging
import os
import sys
import queue
import hashlib
import re
from datetime import datetime
from pathlib import Path
import pystray
from PIL import Image, ImageDraw
import winreg

# ── Paths ──────────────────────────────────────────────────────
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent

CONFIG_FILE    = BASE_DIR / "config.json"
OFFLINE_FILE   = BASE_DIR / "offline_queue.json"
PROCESSED_FILE = BASE_DIR / "processed_files.json"
LOG_FILE       = BASE_DIR / "fcbagent.log"

# ── Logging ────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8')]
)
log = logging.getLogger("FCBAgent")

# ── Config padrão ──────────────────────────────────────────────
DEFAULT_CONFIG = {
    "criador_id":   "",
    "criador_nome": "",
    "clube_id":     "",
    "api_token":    "",
    "api_url":      "https://api.fcbpigeonslive.com.br/api/chegadas",
    "pampa_pasta":  "C:\\PAMPA",
    "autostart":    True,
    "minimized":    True,
}


# ─────────────────────────────────────────────────────────
# MÓDULO GPC IMPORTER — importação histórica do sistema GPC
# ─────────────────────────────────────────────────────────
import re as _re

def _gpc_gms(g, m, s):
    try:
        return round(float(g) + float(m)/60 + float(s)/3600, 6)
    except Exception:
        return None

def gpc_parse_concorrentes(path_xls):
    import pandas as pd
    df = pd.read_excel(path_xls, engine="xlrd", header=None)
    cols = df.iloc[0].tolist()
    df.columns = cols
    df = df.iloc[1:].reset_index(drop=True)
    atletas = []
    for _, r in df.iterrows():
        num  = str(r.get("numero", "")).strip()
        nome = str(r.get("nome",   "")).strip()
        if not num or not nome or nome == "nan":
            continue
        lat = _gpc_gms(r.get("grau1"), r.get("min1"), r.get("seg1"))
        lng = _gpc_gms(r.get("grau2"), r.get("min2"), r.get("seg2"))
        atletas.append({"gpc_num": num, "nome": nome,
                        "lat": -lat if lat else None,
                        "lng": -lng if lng else None, "origem": "gpc"})
    return atletas

def gpc_parse_pombos(path_xlsx):
    import pandas as pd
    xf = pd.ExcelFile(path_xlsx)
    LINHA = _re.compile(r"^(\d{7})/(\d{2})\s+([MF])\s+102/\s*(\d{3,4})\s+(.+)$")
    pombos, vistos = [], set()
    for sheet in xf.sheet_names:
        df = pd.read_excel(path_xlsx, sheet_name=sheet, header=None)
        texto = ""
        for _, row in df.iterrows():
            for cell in row:
                if pd.notna(cell):
                    txt = str(cell)
                    txt = _re.sub(r"(?<!\n)(\d{7}/\d{2}\s+[MF]\s+102/)", r"\n\1", txt)
                    texto += txt + "\n"
        for linha in texto.split("\n"):
            linha = linha.strip()
            m = LINHA.match(linha)
            if not m:
                continue
            anilha, ano_s, sexo, num_c, nome_raw = m.groups()
            ano  = "20" + ano_s
            nome = _re.split(r"CLUBE|Pag\.?|Total|POMOR|www\.", nome_raw, flags=_re.IGNORECASE)[0]
            nome = _re.sub(r"\s+", " ", nome).strip()[:60]
            if len(nome) < 2:
                continue
            chave = (anilha, ano)
            if chave not in vistos:
                vistos.add(chave)
                pombos.append({"anilha": anilha, "ano_nascimento": int(ano),
                               "sexo": sexo, "num_concorrente": num_c, "origem": "gpc"})
    return pombos

def gpc_parse_classificacao(path_xlsx):
    import pandas as pd
    xf = pd.ExcelFile(path_xlsx)
    ANILHA_RE   = _re.compile(r"^\d{7}/\d{2}$")
    CONC_RE     = _re.compile(r"^102/(\d{3,4})$")
    CONCURSO_RE = _re.compile(r"(\d{4})/\s*(\d+)\s+([\w\s\-\.]+?)\s+(\d{2}/\d{2}/\d{4})")
    concursos, resultados, atual = {}, [], None
    for sheet in xf.sheet_names:
        df = pd.read_excel(path_xlsx, sheet_name=sheet, header=None)
        for _, row in df.iterrows():
            cells = [str(c).strip() if pd.notna(c) else "" for c in row]
            full  = " ".join(cells)
            m = CONCURSO_RE.search(full)
            if m:
                cid = m.group(1) + "/" + m.group(2).strip()
                atual = {"gpc_id": cid, "ano": m.group(1), "num": m.group(2).strip(),
                         "nome": m.group(3).strip(), "data": m.group(4), "origem": "gpc"}
                if cid not in concursos:
                    concursos[cid] = atual
                continue
            for i, c in enumerate(cells):
                if not ANILHA_RE.match(c):
                    continue
                for j in range(i+1, min(i+5, len(cells))):
                    mc = CONC_RE.match(cells[j])
                    if not mc:
                        continue
                    lugar = None
                    for k in range(j+1, min(j+5, len(cells))):
                        if cells[k].isdigit():
                            lugar = int(cells[k])
                            break
                    if atual and lugar:
                        resultados.append({
                            "concurso_gpc_id": atual["gpc_id"],
                            "concurso_nome": atual["nome"],
                            "concurso_data": atual["data"],
                            "anilha": c.split("/")[0],
                            "ano_pombo": "20" + c.split("/")[1],
                            "num_concorrente": mc.group(1),
                            "posicao": lugar, "origem": "gpc"})
                    break
    return list(concursos.values()), resultados

def gpc_gerar_json(path_conc, path_pombos, path_provas):
    atletas = gpc_parse_concorrentes(path_conc)
    pombos  = gpc_parse_pombos(path_pombos)
    provas, resultados = gpc_parse_classificacao(path_provas)
    return {"versao": "1.0", "origem": "gpc",
            "atletas": atletas, "portadores": pombos,
            "provas": provas, "resultados": resultados,
            "stats": {"total_atletas": len(atletas),
                      "total_portadores": len(pombos),
                      "total_provas": len(provas),
                      "total_resultados": len(resultados)}}


def load_config():
    if CONFIG_FILE.exists():
        try:
            return {**DEFAULT_CONFIG, **json.loads(CONFIG_FILE.read_text(encoding='utf-8'))}
        except:
            pass
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding='utf-8')

def load_queue():
    if OFFLINE_FILE.exists():
        try:
            return json.loads(OFFLINE_FILE.read_text(encoding='utf-8'))
        except:
            return []
    return []

def save_queue(q):
    OFFLINE_FILE.write_text(json.dumps(q, indent=2), encoding='utf-8')

def load_processed():
    if PROCESSED_FILE.exists():
        try:
            return set(json.loads(PROCESSED_FILE.read_text(encoding='utf-8')))
        except:
            return set()
    return set()

def save_processed(s):
    PROCESSED_FILE.write_text(json.dumps(list(s)), encoding='utf-8')

# ── Parser PAMPA .txt ──────────────────────────────────────────
def parse_pampa_txt(filepath):
    chegadas = []
    try:
        texto = None
        for enc in ['latin-1', 'cp1252', 'utf-8']:
            try:
                texto = Path(filepath).read_text(encoding=enc)
                break
            except:
                continue
        if not texto:
            return []

        linhas = texto.splitlines()
        data_prova = None

        for linha in linhas:
            linha = linha.strip()
            if not linha:
                continue

            m_data = re.search(r'(\d{2})[/\-](\d{2})[/\-](\d{4})', linha)
            if m_data and not data_prova:
                data_prova = f"{m_data.group(3)}-{m_data.group(2)}-{m_data.group(1)}"

            m = re.search(
                r'([A-Z]{2}\d{2}[-\s]?\d{6,7}|\d{7})\s+(\d{2}:\d{2}:\d{2})',
                linha
            )
            if m:
                anilha_raw = m.group(1).replace('-','').replace(' ','')
                hora       = m.group(2)
                nums       = re.sub(r'[^0-9]', '', anilha_raw)
                anilha     = nums[-7:].zfill(7) if len(nums) >= 7 else nums.zfill(7)
                data_ts    = data_prova or datetime.now().strftime('%Y-%m-%d')
                chegadas.append({
                    "anilha":          anilha,
                    "timestamp_local": f"{data_ts}T{hora}",
                    "timestamp_utc":   datetime.utcnow().isoformat() + "Z",
                    "fonte":           "pampa_txt",
                    "arquivo_origem":  Path(filepath).name,
                })
    except Exception as e:
        log.error(f"parse_pampa_txt: {e}")
    return chegadas

# ── Autostart ──────────────────────────────────────────────────
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
class FCBEngine(threading.Thread):
    def __init__(self, ui_queue):
        super().__init__(daemon=True)
        self.ui_queue = ui_queue
        self.running  = False

    def emit(self, tipo, msg, dados=None):
        self.ui_queue.put({"tipo": tipo, "msg": msg, "dados": dados})

    def enviar(self, dados):
        cfg = load_config()
        headers = {
            "Authorization": f"Bearer {cfg['api_token']}",
            "Content-Type":  "application/json",
            "X-Agent-ID":    f"AGENT-{cfg['criador_id']}",
        }
        payload = {**dados, "criador_id": cfg["criador_id"],
                   "clube_id": cfg["clube_id"], "agent_version": "2.0"}
        try:
            r = requests.post(cfg["api_url"], json=payload, headers=headers, timeout=8)
            if r.status_code == 200:
                return True, r.json().get("velocidade","—")
            return False, None
        except:
            return False, None

    def sincronizar_offline(self):
        fila = load_queue()
        if not fila:
            return
        self.emit("log", f"Sincronizando {len(fila)} chegadas offline...", "info")
        enviadas = []
        for item in fila:
            ok, _ = self.enviar(item)
            if ok: enviadas.append(item)
            else: break
        fila = [i for i in fila if i not in enviadas]
        save_queue(fila)
        if enviadas:
            self.emit("log", f"✓ {len(enviadas)} chegadas sincronizadas", "ok")

    def processar_arquivo(self, filepath, processados):
        conteudo  = Path(filepath).read_bytes()
        file_hash = hashlib.md5(conteudo).hexdigest()
        if file_hash in processados:
            return processados

        self.emit("log", f"📂 Novo arquivo PAMPA: {Path(filepath).name}", "info")
        chegadas = parse_pampa_txt(filepath)

        if not chegadas:
            self.emit("log", f"⚠ Nenhuma chegada em {Path(filepath).name}", "erro")
            processados.add(file_hash)
            save_processed(processados)
            return processados

        self.emit("log", f"📋 {len(chegadas)} chegadas encontradas — enviando...", "info")
        for c in chegadas:
            anilha = c["anilha"]
            hora   = c["timestamp_local"][11:]
            self.emit("log", f"🕊 Anilha {anilha} · {hora} · enviando...", "lj")
            ok, vel = self.enviar(c)
            if ok:
                vel_str = f"{vel:,.2f} m/min".replace(",","X").replace(".",",").replace("X",".") if isinstance(vel,(int,float)) else "—"
                self.emit("log", f"✓ Chegada registrada · {vel_str}", "ok")
                self.emit("chegada", c.get("timestamp_local",""), vel)
            else:
                fila = load_queue()
                fila.append(c)
                save_queue(fila)
                self.emit("log", f"⚠ Sem conexão · salvo offline ({len(fila)} na fila)", "erro")

        processados.add(file_hash)
        save_processed(processados)
        return processados

    def run(self):
        self.running = True
        cfg = load_config()

        if not cfg["criador_id"] or not cfg["api_token"]:
            self.emit("status", "Configuração incompleta", "erro")
            self.emit("log", "⚠ Configure seu ID FCB e Token antes de iniciar", "erro")
            return

        pasta = Path(cfg["pampa_pasta"])
        if not pasta.exists():
            self.emit("status", "Pasta PAMPA não encontrada", "erro")
            self.emit("log", f"⚠ Pasta não encontrada: {pasta}", "erro")
            self.emit("log", "Configure o caminho correto em Config → Pasta PAMPA", "info")
            return

        self.emit("status", "Monitorando · Aguardando arquivos PAMPA", "ok")
        self.emit("log", f"✓ Monitorando pasta: {pasta}", "ok")
        self.emit("log", "Aguardando exportação do PAMPA CLUB...", "info")
        self.emit("conectado", None)

        processados = load_processed()
        ultimo_sync = time.time()

        while self.running:
            try:
                txts = sorted(pasta.glob("*.txt"), key=lambda f: f.stat().st_mtime, reverse=True)
                for txt in txts[:10]:
                    processados = self.processar_arquivo(str(txt), processados)
                if time.time() - ultimo_sync > 60:
                    self.sincronizar_offline()
                    ultimo_sync = time.time()
                time.sleep(5)
            except Exception as e:
                self.emit("log", f"⚠ Erro: {e}", "erro")
                time.sleep(10)

    def stop(self):
        self.running = False


# ══════════════════════════════════════════════════════════════
class ConfigDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("FCBAgent · Configuração")
        self.geometry("520x440")
        self.resizable(False, False)
        self.configure(bg="#0c1a0e")
        self.grab_set()

        cfg      = load_config()
        lbl_opts = {"bg":"#0c1a0e","fg":"#f2f0ea","font":("Consolas",9)}
        ent_opts = {"bg":"#111f13","fg":"#f2f0ea","insertbackground":"#f2f0ea",
                    "relief":"flat","font":("Consolas",9),"bd":6}

        def row(label, var, show=""):
            tk.Label(self, text=label, **lbl_opts).pack(anchor="w", padx=24, pady=(8,1))
            tk.Entry(self, textvariable=var, show=show, width=60, **ent_opts).pack(padx=24, fill="x")

        self.v_id    = tk.StringVar(value=cfg.get("criador_id",""))
        self.v_nome  = tk.StringVar(value=cfg.get("criador_nome",""))
        self.v_clube = tk.StringVar(value=cfg.get("clube_id",""))
        self.v_token = tk.StringVar(value=cfg.get("api_token",""))
        self.v_pasta = tk.StringVar(value=cfg.get("pampa_pasta","C:\\PAMPA"))
        self.v_auto  = tk.BooleanVar(value=cfg.get("autostart",True))

        row("ID FCB (usuario_id):", self.v_id)
        row("Nome:", self.v_nome)
        row("ID do Clube:", self.v_clube)
        row("Token FCB Agent:", self.v_token, show="*")

        tk.Label(self, text="Pasta PAMPA (onde o software salva os .txt):", **lbl_opts).pack(anchor="w", padx=24, pady=(8,1))
        frm = tk.Frame(self, bg="#0c1a0e")
        frm.pack(padx=24, fill="x")
        tk.Entry(frm, textvariable=self.v_pasta, width=48, **ent_opts).pack(side="left", fill="x", expand=True)
        tk.Button(frm, text="📁", bg="#2d7a3e", fg="white", relief="flat",
                  command=self.escolher_pasta).pack(side="left", padx=(4,0))

        tk.Checkbutton(self, text="Iniciar automaticamente com o Windows",
                       variable=self.v_auto, bg="#0c1a0e", fg="#f2f0ea",
                       selectcolor="#111f13", activebackground="#0c1a0e").pack(anchor="w", padx=24, pady=(12,0))

        tk.Button(self, text="SALVAR", bg="#2d7a3e", fg="white",
                  font=("Consolas",10,"bold"), relief="flat", pady=8,
                  command=self.salvar).pack(fill="x", padx=24, pady=(16,8))

    def escolher_pasta(self):
        pasta = filedialog.askdirectory(title="Selecione a pasta do PAMPA")
        if pasta:
            self.v_pasta.set(pasta.replace("/","\\"))

    def salvar(self):
        cfg = load_config()
        cfg["criador_id"]   = self.v_id.get().strip()
        cfg["criador_nome"] = self.v_nome.get().strip()
        cfg["clube_id"]     = self.v_clube.get().strip()
        cfg["api_token"]    = self.v_token.get().strip()
        cfg["pampa_pasta"]  = self.v_pasta.get().strip()
        cfg["autostart"]    = self.v_auto.get()
        save_config(cfg)
        set_autostart(cfg["autostart"])
        messagebox.showinfo("FCBAgent", "Configuração salva!")
        self.destroy()



class AbaImportarGPC(tk.Toplevel):
    def __init__(self, parent, api_url, token):
        super().__init__(parent)
        self.api_url = api_url
        self.token   = token
        self.title("Importar Historico GPC")
        self.geometry("520x430")
        self.configure(bg="#060e07")
        self.resizable(False, False)
        self.grab_set()
        self.v_conc  = tk.StringVar()
        self.v_pombo = tk.StringVar()
        self.v_prova = tk.StringVar()
        self._build()

    def _build(self):
        BG="#060e07"; BG2="#0c1a0e"; CRM="#f2f0ea"; VRD="#2d7a3e"
        hdr = tk.Frame(self, bg=BG2, height=46)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="IMPORTAR HISTORICO GPC", bg=BG2, fg=CRM,
                 font=("Consolas",10,"bold")).pack(side="left", padx=14, pady=12)
        body = tk.Frame(self, bg=BG, padx=18, pady=14)
        body.pack(fill="both", expand=True)
        tk.Label(body, text="Selecione os 3 arquivos exportados do GPC:",
                 bg=BG, fg="#999", font=("Consolas",8)).pack(anchor="w", pady=(0,10))
        def fila(lbl, var, ft):
            frm = tk.Frame(body, bg=BG); frm.pack(fill="x", pady=3)
            tk.Label(frm, text=lbl, bg=BG, fg=CRM,
                     font=("Consolas",8), width=24, anchor="w").pack(side="left")
            tk.Entry(frm, textvariable=var, bg=BG2, fg=CRM,
                     insertbackground=CRM, relief="flat",
                     font=("Consolas",8), width=26).pack(side="left", padx=(0,4))
            tk.Button(frm, text="...", bg=BG2, fg=CRM, relief="flat",
                      font=("Consolas",8), padx=5,
                      command=lambda v=var, f=ft: self._escolher(v, f)).pack(side="left")
        fila("Concorrentes (.xls):",   self.v_conc,
             [("Excel 97-2003","*.xls"),("Todos","*.*")])
        fila("Pombos (.xlsx):",        self.v_pombo,
             [("Excel","*.xlsx"),("Todos","*.*")])
        fila("Classificacao (.xlsx):", self.v_prova,
             [("Excel","*.xlsx"),("Todos","*.*")])
        tk.Label(body, text="Log:", bg=BG, fg="#999",
                 font=("Consolas",8)).pack(anchor="w", pady=(14,2))
        self.log = tk.Text(body, height=7, bg=BG2, fg=CRM,
                           font=("Consolas",8), relief="flat", state="disabled")
        self.log.pack(fill="x")
        bf = tk.Frame(body, bg=BG); bf.pack(fill="x", pady=(14,0))
        self.btn = tk.Button(bf, text="PROCESSAR E ENVIAR",
                             bg=VRD, fg="white", relief="flat",
                             font=("Consolas",9,"bold"), padx=14, pady=7,
                             command=self._iniciar)
        self.btn.pack(side="left")
        tk.Button(bf, text="Fechar", bg=BG2, fg=CRM, relief="flat",
                  font=("Consolas",8), padx=10, pady=7,
                  command=self.destroy).pack(side="right")

    def _escolher(self, var, ft):
        from tkinter import filedialog
        p = filedialog.askopenfilename(filetypes=ft)
        if p: var.set(p)

    def _log(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _iniciar(self):
        if not all([self.v_conc.get(), self.v_pombo.get(), self.v_prova.get()]):
            self._log("Selecione os 3 arquivos."); return
        if not self.token:
            self._log("Token nao configurado."); return
        self.btn.configure(state="disabled", text="Processando...")
        threading.Thread(target=self._importar, daemon=True).start()

    def _importar(self):
        import requests as req
        try:
            self._log("Lendo arquivos GPC...")
            dados = gpc_gerar_json(self.v_conc.get(), self.v_pombo.get(), self.v_prova.get())
            s = dados["stats"]
            self._log("  " + str(s["total_atletas"]) + " concorrentes")
            self._log("  " + str(s["total_portadores"]) + " pombos")
            self._log("  " + str(s["total_provas"]) + " provas / " + str(s["total_resultados"]) + " resultados")
            self._log("Enviando ao servidor...")
            r = req.post(
                self.api_url + "/api/importacao/gpc",
                json=dados,
                headers={"Authorization": "Bearer " + self.token,
                         "Content-Type": "application/json"},
                timeout=120
            )
            if r.status_code == 200:
                d = r.json()
                self._log("Importacao concluida!")
                self._log("  Atletas:       " + str(d.get("atletas_inseridos","?")))
                self._log("  Pombos:        " + str(d.get("pombos_inseridos","?")))
                self._log("  Provas:        " + str(d.get("provas_inseridas","?")))
                self._log("  Encestamentos: " + str(d.get("encestamentos_inseridos","?")))
            else:
                self._log("Erro " + str(r.status_code) + ": " + r.text[:150])
        except Exception as e:
            self._log("Erro: " + str(e))
        finally:
            self.btn.configure(state="normal", text="PROCESSAR E ENVIAR")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FCB Agent")
        self.geometry("640x460")
        self.configure(bg="#060e07")
        self.resizable(True, True)
        self.ui_queue = queue.Queue()
        self.engine   = None
        self.rodando  = False
        self.chegadas = 0

        self._build_ui()
        self._tick()

        if "--minimized" in sys.argv:
            self.after(100, self.iconify)

        cfg = load_config()
        if cfg.get("autostart") and cfg.get("criador_id") and cfg.get("api_token"):
            self.after(800, self.iniciar)

    def _build_ui(self):
        hdr = tk.Frame(self, bg="#0c1a0e", height=52)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="FCBAgent", bg="#0c1a0e", fg="#f2f0ea",
                 font=("Consolas",14,"bold")).pack(side="left", padx=16)
        tk.Label(hdr, text="v2.0", bg="#0c1a0e", fg="#3a9950",
                 font=("Consolas",8)).pack(side="left")
        tk.Button(hdr, text="⚙ Config", bg="#0c1a0e", fg="#f2f0ea",
                  relief="flat", command=self.abrir_config).pack(side="right", padx=8)
        tk.Button(hdr, text="GPC", bg="#0c1a0e", fg="#ff6b00",
                  relief="flat", font=("Consolas",8), padx=6,
                  command=self.abrir_importar_gpc).pack(side="right", padx=4)
        tk.Button(hdr, text="↓ Bandeja", bg="#0c1a0e", fg="#f2f0ea",
                  relief="flat", command=self.iconify).pack(side="right")

        self.lbl_status = tk.Label(self, text="● Aguardando configuração",
                                   bg="#060e07", fg="#ff6b00",
                                   font=("Consolas",9), anchor="w")
        self.lbl_status.pack(fill="x", padx=16, pady=(8,0))

        ctr = tk.Frame(self, bg="#060e07")
        ctr.pack(fill="x", padx=16, pady=8)
        f = tk.Frame(ctr, bg="#111f13", padx=20, pady=10)
        f.grid(row=0, column=0, padx=4, sticky="ew")
        ctr.columnconfigure(0, weight=1)
        self.lbl_chegadas = tk.Label(f, text="0", bg="#111f13",
                                     fg="#f2f0ea", font=("Consolas",22,"bold"))
        self.lbl_chegadas.pack()
        tk.Label(f, text="CHEGADAS ENVIADAS", bg="#111f13",
                 fg="#3a9950", font=("Consolas",7)).pack()

        tk.Label(self, text="LOG EM TEMPO REAL", bg="#060e07", fg="#3a9950",
                 font=("Consolas",7), anchor="w").pack(fill="x", padx=16)

        self.log_box = tk.Text(self, bg="#060e07", fg="#f2f0ea",
                               font=("Consolas",8), relief="flat",
                               state="disabled", wrap="word")
        self.log_box.pack(fill="both", expand=True, padx=16, pady=(2,8))
        self.log_box.tag_config("ok",   foreground="#3a9950")
        self.log_box.tag_config("erro", foreground="#ff6b00")
        self.log_box.tag_config("info", foreground="#f2f0ea")
        self.log_box.tag_config("lj",   foreground="#c8a84b")

        self.btn = tk.Button(self, text="▶ INICIAR", bg="#2d7a3e", fg="white",
                             font=("Consolas",10,"bold"), relief="flat", pady=8,
                             command=self.toggle)
        self.btn.pack(fill="x", padx=16, pady=(0,12))

    def log(self, msg, tag="info"):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{ts}] {msg}\n", tag)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _tick(self):
        try:
            while True:
                ev = self.ui_queue.get_nowait()
                t  = ev["tipo"]
                if t == "log":
                    self.log(ev["msg"], ev.get("dados","info") or "info")
                elif t == "status":
                    cor = {"ok":"#3a9950","erro":"#ff6b00","info":"#c8a84b"}.get(ev.get("dados","info"),"#f2f0ea")
                    self.lbl_status.config(text=f"● {ev['msg']}", fg=cor)
                elif t == "chegada":
                    self.chegadas += 1
                    self.lbl_chegadas.config(text=str(self.chegadas))
                elif t == "conectado":
                    self.btn.config(text="■ PARAR", bg="#c05050")
                    self.rodando = True
                elif t == "desconectado":
                    self.btn.config(text="▶ INICIAR", bg="#2d7a3e")
                    self.rodando = False
        except queue.Empty:
            pass
        self.after(200, self._tick)

    def toggle(self):
        if self.rodando: self.parar()
        else: self.iniciar()

    def iniciar(self):
        if self.engine and self.engine.is_alive():
            return
        self.chegadas = 0
        self.lbl_chegadas.config(text="0")
        self.engine = FCBEngine(self.ui_queue)
        self.engine.start()
        self.log("FCB Agent iniciado", "ok")

    def parar(self):
        if self.engine:
            self.engine.stop()
        self.btn.config(text="▶ INICIAR", bg="#2d7a3e")
        self.rodando = False
        self.log("FCB Agent parado", "erro")

    def abrir_config(self):
        ConfigDialog(self)

    def abrir_importar_gpc(self):
        cfg = load_config()
        AbaImportarGPC(
            self,
            cfg.get("api_url", "https://api.fcbpigeonslive.com.br"),
            cfg.get("api_token", "")
        )


    def on_close(self):
        self.parar()
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
