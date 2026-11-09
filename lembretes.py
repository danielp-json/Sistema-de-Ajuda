#!/usr/bin/env python3
"""
Lembretes — cronograma, modo acadêmico, contagem regressiva e avisos.
Funciona em Arch Linux e Windows. Sem dependências externas (só Tkinter).

Dados salvos em: ~/.lembretes/dados.json
"""

import json
import math
import os
import shutil
import subprocess
import sys
import uuid
import tkinter as tk
from tkinter import font as tkfont
from datetime import datetime, date, timedelta
from pathlib import Path

APP_DIR = Path.home() / ".lembretes"
DATA_FILE = APP_DIR / "dados.json"
IS_WIN = sys.platform.startswith("win")

DIAS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
DIAS_LONGO = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
              "sexta-feira", "sábado", "domingo"]
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]

PADRAO = {
    "config": {"intervalo_min": 10, "antecedencia_min": 60, "tema": "claro"},
    "atividades": [],  # {id, nome, horarios: [{dias, hora, fim}], data "YYYY-MM-DD"}
    "materias": [],    # {id, nome, local, atual, conteudos: [{texto, feito}], horarios: [{dias, hora, fim}]}
    "tarefas": [],     # gerado automaticamente a partir de 'atividades' e 'materias'
    "datas": [],       # {id, nome, data "YYYY-MM-DD"}
}

# ----------------------------------------------------------------- aparência
TEMAS = {
    "claro": dict(
        bg="#EFEBE3", lateral="#E5E0D4", card="#FAF8F3", linha="#D5CEC0",
        tinta="#1F1D1A", suave="#7C766B", destaque="#B5442A", destaque_h="#9A3720",
        sobre="#FFFFFF", ok="#2F6F6B",
    ),
    "escuro": dict(
        bg="#17181B", lateral="#121315", card="#222428", linha="#34363C",
        tinta="#ECE8DF", suave="#8D8F96", destaque="#E3835A", destaque_h="#EE9770",
        sobre="#17181B", ok="#5FA8A0",
    ),
}
CORES = ["#B5442A", "#2F6F6B", "#B8892B", "#4B6296", "#7D5A7B", "#5E7F3E", "#A0522D"]

SANS = ["Inter", "Noto Sans", "Segoe UI", "DejaVu Sans", "Liberation Sans", "Helvetica"]
SERIF = ["Source Serif 4", "Noto Serif", "Georgia", "DejaVu Serif", "Liberation Serif", "Times"]

LADO = 168      # lado dos blocos quadrados
LARG_MAT = 354  # largura dos blocos de matéria (2 * LADO + 18)


# ----------------------------------------------------------------- dados
def migrar_tarefas_antigas(dados):
    """Converte tarefas do formato antigo (1 horário só) para 'atividades' (múltiplos horários)."""
    if "atividades" not in dados:
        dados["atividades"] = []
    antigas = [t for t in dados.get("tarefas", [])
               if not t.get("materia_id") and not t.get("atividade_id")]
    if antigas:
        for t in antigas:
            dados["atividades"].append({
                "id": t.get("id") or uuid.uuid4().hex,
                "nome": t["nome"],
                "data": t.get("data", ""),
                "horarios": [{
                    "dias": t.get("dias", []),
                    "hora": t["hora"],
                    "fim": t.get("fim", ""),
                }],
            })


def sincronizar_grade(dados):
    """Reconstrói a lista 'tarefas' expandindo cada horário de 'atividades' e 'materias'."""
    migrar_tarefas_antigas(dados)
    lista = []

    for a in dados.get("atividades", []):
        data_unica = a.get("data", "")
        for idx, h in enumerate(a.get("horarios", [])):
            lista.append({
                "id": f"ativ_{a['id']}_{idx}",
                "atividade_id": a["id"],
                "nome": a["nome"],
                "hora": h["hora"],
                "fim": h.get("fim", ""),
                "dias": [] if data_unica else h.get("dias", []),
                "data": data_unica,
            })

    for m in dados.get("materias", []):
        for idx, h in enumerate(m.get("horarios", [])):
            lista.append({
                "id": f"mat_{m['id']}_{idx}",
                "materia_id": m["id"],
                "nome": m["nome"],
                "hora": h["hora"],
                "fim": h.get("fim", ""),
                "dias": h.get("dias", []),
                "data": "",
            })

    dados["tarefas"] = lista


def carregar():
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            dados = json.load(f)
    except (OSError, ValueError):
        dados = {}
    for k, v in PADRAO.items():
        dados.setdefault(k, json.loads(json.dumps(v)))
    for k, v in PADRAO["config"].items():
        dados["config"].setdefault(k, v)
    if dados["config"]["tema"] not in TEMAS:
        dados["config"]["tema"] = "claro"
    sincronizar_grade(dados)
    return dados


def salvar(dados):
    sincronizar_grade(dados)
    APP_DIR.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


# ----------------------------------------------------------------- utilidades
def fmt_min(m):
    """'30 minutos', '1h 20min'"""
    m = int(m)
    if m < 60:
        return f"{m} minuto{'s' if m != 1 else ''}"
    h, r = divmod(m, 60)
    return f"{h}h" + (f" {r:02d}min" if r else "")


def fmt_curto(m):
    """'30 min', '1h 20min', '3 dias'"""
    m = max(0, int(m))
    if m < 60:
        return f"{m} min"
    if m < 1440:
        h, r = divmod(m, 60)
        return f"{h}h {r:02d}min" if r else f"{h}h"
    d = m // 1440
    return f"{d} dia{'s' if d != 1 else ''}"


def iso_para_br(iso):
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%d/%m/%Y")


def parse_hora(s):
    s = s.strip().lower().replace("h", ":").replace(".", ":")
    if s.isdigit():
        s += ":00"
    if s.endswith(":"):
        s += "00"
    return datetime.strptime(s, "%H:%M").strftime("%H:%M")


def parse_data(s):
    return datetime.strptime(s.strip(), "%d/%m/%Y").strftime("%Y-%m-%d")


def inicio_em(tarefa, dia):
    """datetime de início da tarefa no dia (date) informado, ou None."""
    h, m = map(int, tarefa["hora"].split(":"))
    if tarefa.get("data"):
        if datetime.strptime(tarefa["data"], "%Y-%m-%d").date() != dia:
            return None
    elif dia.weekday() not in tarefa.get("dias", []):
        return None
    return datetime(dia.year, dia.month, dia.day, h, m)


def fim_em(tarefa, dia):
    """datetime de término (se a tarefa tiver horário de fim), ou None."""
    if not tarefa.get("fim"):
        return None
    h, m = map(int, tarefa["fim"].split(":"))
    return datetime(dia.year, dia.month, dia.day, h, m)


def dias_ate(d):
    return (datetime.strptime(d["data"], "%Y-%m-%d").date() - date.today()).days


def corta(txt, n=28):
    return txt if len(txt) <= n else txt[: n - 1].rstrip() + "…"


def cor_da(nome):
    return CORES[sum(ord(c) for c in nome.strip().lower()) % len(CORES)]


def instalar_autostart():
    script = os.path.abspath(__file__)
    if IS_WIN:
        pasta = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup"
        pythonw = sys.executable.replace("python.exe", "pythonw.exe")
        destino = pasta / "lembretes.bat"
        destino.write_text(f'@echo off\nstart "" "{pythonw}" "{script}" --auto\n', encoding="utf-8")
    else:
        pasta = Path.home() / ".config/autostart"
        pasta.mkdir(parents=True, exist_ok=True)
        destino = pasta / "lembretes.desktop"
        destino.write_text(
            "[Desktop Entry]\nType=Application\nName=Lembretes\n"
            f'Exec={sys.executable} "{script}" --auto\nX-GNOME-Autostart-enabled=true\n',
            encoding="utf-8",
        )
    return destino


# ----------------------------------------------------------------- componentes
class Bloco(tk.Frame):
    """Bloco quadrado com uma faixa de cor no topo. O conteúdo vai em .corpo"""

    def __init__(self, parent, t, lado, cor=None, altura=None):
        super().__init__(parent, width=lado, height=altura or lado, bg=t["card"],
                         highlightthickness=1, highlightbackground=t["linha"])
        self.pack_propagate(False)
        if cor:
            tk.Frame(self, bg=cor, height=5).pack(side="top", fill="x")
        self.corpo = tk.Frame(self, bg=t["card"])
        self.corpo.pack(fill="both", expand=True, padx=14, pady=(10, 12))


class BarraFina(tk.Canvas):
    """Barra de rolagem fina, sem setas."""

    def __init__(self, parent, t, comando):
        super().__init__(parent, width=10, bg=t["bg"], highlightthickness=0, bd=0)
        self.t, self.comando, self.lo, self.hi = t, comando, 0.0, 1.0
        self.bind("<Configure>", lambda e: self.desenhar())
        self.bind("<Button-1>", self.arrasta)
        self.bind("<B1-Motion>", self.arrasta)

    def set(self, lo, hi):
        self.lo, self.hi = float(lo), float(hi)
        self.desenhar()

    def desenhar(self):
        self.delete("all")
        h = self.winfo_height()
        topo = self.lo * h
        fim = max(self.hi * h, topo + 28)
        self.create_rectangle(2, topo + 1, 8, fim - 1, fill=self.t["suave"], outline="")

    def arrasta(self, e):
        h = max(self.winfo_height(), 1)
        self.comando("moveto", e.y / h - (self.hi - self.lo) / 2)


class Rolavel(tk.Frame):
    """Área com rolagem vertical e barra fina que some quando não é necessária."""

    def __init__(self, parent, t):
        super().__init__(parent, bg=t["bg"])
        self.canvas = tk.Canvas(self, bg=t["bg"], highlightthickness=0, bd=0, yscrollincrement=20)
        self.barra = BarraFina(self, t, self.canvas.yview)
        self.canvas.configure(yscrollcommand=self._set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=t["bg"])
        self.janela = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfigure(self.janela, width=e.width))

    def _set(self, lo, hi):
        if float(lo) <= 0 and float(hi) >= 1:
            self.barra.pack_forget()
        elif not self.barra.winfo_ismapped():
            self.barra.pack(side="right", fill="y", before=self.canvas)
        self.barra.set(lo, hi)

    def precisa(self):
        return self.inner.winfo_reqheight() > self.canvas.winfo_height()


# ----------------------------------------------------------------- aplicativo
class App:
    LAT = 220  # largura da barra lateral

    NAV = [
        ("hoje", "Hoje"),
        ("semana", "Cronograma"),
        ("academico", "Acadêmico"),
        ("datas", "Datas importantes"),
        ("ajustes", "Ajustes"),
    ]

    def __init__(self, root, auto=False):
        self.root = root
        self.dados = carregar()
        self.popups = {}
        self.avisados = set()
        self.view = "hoje"
        self.rol = None
        self._w = 0
        self._min = None
        self._agendado = None

        root.title("Lembretes")
        root.geometry("1280x820")
        root.minsize(1180, 680)
        root.protocol("WM_DELETE_WINDOW", root.iconify)  # minimiza e continua avisando

        self.fontes()
        self.aplicar_tema()
        root.bind("<Configure>", self.ao_redimensionar)
        for ev in ("<Button-4>", "<Button-5>", "<MouseWheel>"):
            root.bind_all(ev, self.roda)

        self.montar()
        self.render()
        agora = datetime.now()
        self.alerta(f"{self.saudacao(agora)} · resumo", self.itens_resumo(agora), slot="resumo")
        if auto:
            root.iconify()
        root.after(2000, self.checar)

    # ------------------------------------------------------------ base visual
    def fontes(self):
        disp = set(tkfont.families())

        def escolher(opcoes, padrao):
            for f in opcoes:
                if f in disp:
                    return f
            return padrao

        sans, serif = escolher(SANS, "Helvetica"), escolher(SERIF, "Times")
        self.F = {
            "h1": (serif, 34), "h2": (serif, 20, "bold"), "h3": (serif, 15, "bold"),
            "num": (serif, 36), "hora": (serif, 20, "bold"), "alerta": (serif, 22, "bold"),
            "marca": (serif, 18, "bold"),
            "corpo": (sans, 11), "corpo_b": (sans, 11, "bold"), "corpo_s": (sans, 11, "overstrike"),
            "mini": (sans, 9), "mini_b": (sans, 9, "bold"), "rotulo": (sans, 9, "bold"),
            "nav": (sans, 12), "nav_b": (sans, 12, "bold"),
        }

    def aplicar_tema(self):
        self.t = TEMAS[self.dados["config"]["tema"]]
        self.root.configure(bg=self.t["bg"])

    def saudacao(self, agora):
        return "Bom dia" if agora.hour < 12 else "Boa tarde" if agora.hour < 18 else "Boa noite"

    def largura_util(self):
        w = self.root.winfo_width()
        if w < 300:
            w = 1280
        return w - self.LAT - 1 - 64 - 14 - 12

    def materia_da_tarefa(self, x):
        mid = x.get("materia_id")
        if not mid:
            return None
        for m in self.dados.get("materias", []):
            if m["id"] == mid:
                return m
        return None

    def atividade_da_tarefa(self, x):
        aid = x.get("atividade_id")
        if not aid:
            return None
        for a in self.dados.get("atividades", []):
            if a["id"] == aid:
                return a
        return None

    def resumo_materia(self, m):
        """Retorna o assunto em andamento ou o próximo tópico pendente da matéria."""
        if m.get("atual"):
            return m["atual"]
        for c in m.get("conteudos", []):
            if not c.get("feito"):
                return c["texto"]
        return ""

    def botao(self, parent, texto, cmd, tipo="primario", fundo=None):
        t = self.t
        fundo = fundo or t["bg"]
        if tipo == "primario":
            bg, fg, borda, hov = t["destaque"], t["sobre"], t["destaque"], t["destaque_h"]
        elif tipo == "perigo":
            bg, fg, borda, hov = fundo, t["destaque"], t["destaque"], t["card"]
        else:
            bg, fg, borda, hov = fundo, t["tinta"], t["linha"], t["card"]
        b = tk.Label(parent, text=texto, font=self.F["corpo_b"], bg=bg, fg=fg, padx=18, pady=9,
                     cursor="hand2", highlightthickness=1, highlightbackground=borda)
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.configure(bg=hov))
        b.bind("<Leave>", lambda e: b.configure(bg=bg))
        return b

    def clicavel(self, w, cmd):
        w.bind("<Button-1>", lambda e: cmd())
        try:
            w.configure(cursor="hand2")
        except tk.TclError:
            pass
        for c in w.winfo_children():
            self.clicavel(c, cmd)

    @staticmethod
    def dentro(w, x, y):
        try:
            c = w.winfo_containing(x, y)
        except (KeyError, tk.TclError):
            return False
        while c is not None:
            if c is w:
                return True
            c = c.master
        return False

    def bloco_clicavel(self, b, cmd):
        self.clicavel(b, cmd)
        t = self.t
        b.bind("<Enter>", lambda e: b.configure(highlightbackground=t["destaque"]))
        b.bind("<Leave>", lambda e: None if self.dentro(b, e.x_root, e.y_root)
               else b.configure(highlightbackground=t["linha"]))

    # ------------------------------------------------------------ estrutura
    def montar(self):
        t, F = self.t, self.F
        for w in self.root.winfo_children():
            if not isinstance(w, tk.Toplevel):
                w.destroy()

        lado = tk.Frame(self.root, bg=t["lateral"], width=self.LAT)
        lado.pack(side="left", fill="y")
        lado.pack_propagate(False)
        tk.Frame(self.root, bg=t["linha"], width=1).pack(side="left", fill="y")

        marca = tk.Frame(lado, bg=t["lateral"])
        marca.pack(anchor="w", padx=24, pady=(32, 30))
        tk.Frame(marca, bg=t["destaque"], width=13, height=13).pack(side="left")
        tk.Label(marca, text="lembretes", font=F["marca"], bg=t["lateral"],
                 fg=t["tinta"]).pack(side="left", padx=(10, 0))

        self.itens_nav = {}
        for chave, texto in self.NAV:
            linha = tk.Frame(lado, bg=t["lateral"], cursor="hand2")
            linha.pack(fill="x")
            barra = tk.Frame(linha, width=4, bg=t["lateral"])
            barra.pack(side="left", fill="y")
            lab = tk.Label(linha, text=texto, font=F["nav"], anchor="w", padx=20, pady=12,
                           bg=t["lateral"], fg=t["suave"])
            lab.pack(side="left", fill="x", expand=True)
            for w in (linha, lab):
                w.bind("<Button-1>", lambda e, k=chave: self.ir(k))
            self.itens_nav[chave] = (linha, barra, lab)

        sair = tk.Label(lado, text="Encerrar aplicativo", font=F["mini"], bg=t["lateral"],
                        fg=t["suave"], cursor="hand2")
        sair.pack(side="bottom", anchor="w", padx=24, pady=24)
        sair.bind("<Button-1>", lambda e: self.root.destroy())
        sair.bind("<Enter>", lambda e: sair.configure(fg=t["destaque"]))
        sair.bind("<Leave>", lambda e: sair.configure(fg=t["suave"]))

        self.principal = tk.Frame(self.root, bg=t["bg"])
        self.principal.pack(side="left", fill="both", expand=True)

    def destacar_nav(self):
        t, F = self.t, self.F
        for k, (linha, barra, lab) in self.itens_nav.items():
            ativo = k == self.view
            fundo = t["card"] if ativo else t["lateral"]
            linha.configure(bg=fundo)
            barra.configure(bg=t["destaque"] if ativo else t["lateral"])
            lab.configure(bg=fundo, fg=t["tinta"] if ativo else t["suave"],
                          font=F["nav_b"] if ativo else F["nav"])

    def ir(self, chave):
        self.view = chave
        self.render()

    def render(self, conservar=False):
        t = self.t
        y = 0.0
        if conservar and self.rol is not None and self.rol.winfo_exists():
            y = self.rol.canvas.yview()[0]
        for w in self.principal.winfo_children():
            w.destroy()
        self.destacar_nav()
        self.rol = Rolavel(self.principal, t)
        self.rol.pack(fill="both", expand=True)
        p = tk.Frame(self.rol.inner, bg=t["bg"])
        p.pack(fill="x", padx=32, pady=(34, 34))
        getattr(self, "view_" + self.view)(p)
        self._min = datetime.now().replace(second=0, microsecond=0)
        if y:
            r = self.rol
            self.root.after(40, lambda: r.winfo_exists() and r.canvas.yview_moveto(y))

    def ao_redimensionar(self, e):
        if e.widget is not self.root or abs(e.width - self._w) < 8:
            return
        self._w = e.width
        if self._agendado:
            self.root.after_cancel(self._agendado)
        self._agendado = self.root.after(150, lambda: self.render(conservar=True))

    def roda(self, e):
        try:
            r = self.rol
            if r is None or not r.winfo_exists() or not r.precisa():
                return
            if e.widget.winfo_toplevel() is not self.root:
                return
            d = -1 if e.num == 4 else 1 if e.num == 5 else (-1 if e.delta > 0 else 1)
            r.canvas.yview_scroll(d * 2, "units")
        except (AttributeError, tk.TclError):
            pass

    # ------------------------------------------------------------ pedaços de tela
    def cabecalho(self, p, rotulo, titulo, acao=None):
        t, F = self.t, self.F
        f = tk.Frame(p, bg=t["bg"])
        f.pack(fill="x", padx=6, pady=(0, 18))
        esq = tk.Frame(f, bg=t["bg"])
        esq.pack(side="left")
        tk.Label(esq, text=rotulo, font=F["rotulo"], bg=t["bg"], fg=t["destaque"]).pack(anchor="w")
        tk.Label(esq, text=titulo, font=F["h1"], bg=t["bg"], fg=t["tinta"]).pack(anchor="w")
        if acao:
            self.botao(f, acao[0], acao[1]).pack(side="right", anchor="s", pady=(0, 6))

    def secao(self, p, titulo):
        t = self.t
        f = tk.Frame(p, bg=t["bg"])
        f.pack(fill="x", padx=6, pady=(30, 12))
        tk.Label(f, text=titulo.upper(), font=self.F["rotulo"], fg=t["suave"], bg=t["bg"]).pack(side="left")
        tk.Frame(f, bg=t["linha"], height=1).pack(side="left", fill="x", expand=True, padx=(14, 0))

    def vazio(self, p, texto, acao=None):
        t = self.t
        f = tk.Frame(p, bg=t["bg"])
        f.pack(fill="x", padx=6)
        tk.Label(f, text=texto, font=self.F["corpo"], bg=t["bg"], fg=t["suave"]).pack(side="left")
        if acao:
            self.botao(f, acao[0], acao[1], tipo="ghost").pack(side="left", padx=16)

    def grade(self, p, fabricas, lado=LADO):
        cols = max(1, self.largura_util() // (lado + 12))
        g = tk.Frame(p, bg=self.t["bg"])
        g.pack(fill="x", anchor="w")
        for i, fab in enumerate(fabricas):
            fab(g).grid(row=i // cols, column=i % cols, padx=6, pady=6, sticky="nw")

    def abrir_item(self, x):
        mat = self.materia_da_tarefa(x)
        if mat:
            return self.dialogo_materia(mat)
        ativ = self.atividade_da_tarefa(x)
        if ativ:
            return self.dialogo_tarefa(ativ)

    def bloco_tarefa(self, parent, x, lado, rodape=None, realce=False, apagado=False):
        t, F = self.t, self.F
        b = Bloco(parent, t, lado, cor_da(x["nome"]))
        c = b.corpo
        fg = t["suave"] if apagado else t["tinta"]
        mat = self.materia_da_tarefa(x)
        if rodape:
            tk.Label(c, text=rodape, font=F["mini_b"] if realce else F["mini"], bg=t["card"],
                     fg=t["destaque"] if realce else t["suave"]).pack(side="bottom", anchor="w")
        elif mat:
            tk.Label(c, text="ACADÊMICO", font=F["mini_b"], bg=t["card"],
                     fg=t["ok"]).pack(side="bottom", anchor="w")

        tk.Label(c, text=x["hora"], font=F["hora"], bg=t["card"], fg=fg).pack(anchor="w")
        if x.get("fim"):
            tk.Label(c, text=f"até {x['fim']}", font=F["mini_b"], bg=t["card"],
                     fg=t["suave"]).pack(anchor="w")
        tk.Label(c, text=corta(x["nome"], 24), font=F["corpo_b"], bg=t["card"], fg=fg, anchor="w",
                 justify="left", wraplength=lado - 32).pack(anchor="w", pady=(3, 0))
        if mat:
            res = self.resumo_materia(mat)
            if res:
                tk.Label(c, text=corta(res, 26), font=F["mini"], bg=t["card"],
                         fg=t["suave"], anchor="w", justify="left",
                         wraplength=lado - 32).pack(anchor="w", pady=(2, 0))
        self.bloco_clicavel(b, lambda: self.abrir_item(x))
        return b

    def bloco_data(self, parent, d, lado=LADO):
        t, F = self.t, self.F
        n = dias_ate(d)
        cor = t["suave"] if n < 0 else t["destaque"] if n <= 7 else t["ok"]
        b = Bloco(parent, t, lado, cor)
        c = b.corpo
        fg = t["suave"] if n < 0 else t["tinta"]
        tk.Label(c, text=iso_para_br(d["data"]), font=F["mini"], bg=t["card"],
                 fg=t["suave"]).pack(side="bottom", anchor="w")
        if n < 0:
            grande, pequeno = "—", "já passou"
        elif n == 0:
            grande, pequeno = "Hoje", "é hoje"
        else:
            grande, pequeno = str(n), "dia" if n == 1 else "dias"
        linha = tk.Frame(c, bg=t["card"])
        linha.pack(anchor="w")
        tk.Label(linha, text=grande, font=F["num"], bg=t["card"], fg=cor).pack(side="left")
        tk.Label(linha, text=pequeno, font=F["mini_b"], bg=t["card"], fg=t["suave"]).pack(
            side="left", padx=(7, 0), pady=(0, 9), anchor="s")
        tk.Label(c, text=corta(d["nome"]), font=F["corpo_b"], bg=t["card"], fg=fg, anchor="w",
                 justify="left", wraplength=lado - 32).pack(anchor="w", pady=(4, 0))
        self.bloco_clicavel(b, lambda: self.dialogo_data(d))
        return b

    # ------------------------------------------------------------ tela: Hoje
    def proxima(self, agora):
        melhor = None
        piso = agora.replace(second=0, microsecond=0)
        for k in range(8):
            dia = agora.date() + timedelta(days=k)
            for x in self.dados["tarefas"]:
                ini = inicio_em(x, dia)
                if ini and ini >= piso and (melhor is None or ini < melhor[0]):
                    melhor = (ini, x)
        return melhor

    def em_curso(self, agora):
        melhor = None
        for x in self.dados["tarefas"]:
            ini, fim = inicio_em(x, agora.date()), fim_em(x, agora.date())
            if ini and fim and ini <= agora < fim and (melhor is None or ini < melhor[0]):
                melhor = (ini, x)
        return melhor

    def view_hoje(self, p):
        t, F = self.t, self.F
        agora = datetime.now()
        self.cabecalho(p, f"{self.saudacao(agora).upper()} · {DIAS_LONGO[agora.weekday()].upper()}",
                       f"{agora.day} de {MESES[agora.month - 1]}")

        hero = tk.Frame(p, bg=t["card"], highlightthickness=1, highlightbackground=t["linha"])
        hero.pack(fill="x", padx=6)
        prox = self.proxima(agora)
        curso = self.em_curso(agora)
        if curso or prox:
            ini, x = curso if curso else prox
            fim = fim_em(x, ini.date())
            cor = cor_da(x["nome"])
            mat = self.materia_da_tarefa(x)
            tk.Frame(hero, bg=cor, width=8).pack(side="left", fill="y")
            miolo = tk.Frame(hero, bg=t["card"])
            miolo.pack(side="left", fill="both", expand=True, padx=26, pady=22)
            rot = ("AULA EM ANDAMENTO" if curso else "PRÓXIMA AULA") if mat else (
                  "EM ANDAMENTO" if curso else "PRÓXIMA ATIVIDADE")
            tk.Label(miolo, text=rot, font=F["rotulo"], bg=t["card"],
                     fg=t["ok"] if mat else t["suave"]).pack(anchor="w")
            tk.Label(miolo, text=x["nome"], font=F["h2"], bg=t["card"], fg=t["tinta"]).pack(anchor="w", pady=(4, 2))
            dif = (ini.date() - agora.date()).days
            quando = (f"Hoje, às {x['hora']}" if dif == 0 else f"Amanhã, às {x['hora']}" if dif == 1
                      else f"{DIAS_LONGO[ini.weekday()].capitalize()}, às {x['hora']}")
            if curso:
                quando = f"Das {x['hora']} até {x['fim']}"
            elif x.get("fim"):
                quando += f" até {x['fim']}"
            if mat and mat.get("local"):
                quando += f"  ·  {mat['local']}"
            tk.Label(miolo, text=quando, font=F["corpo"], bg=t["card"], fg=t["suave"]).pack(anchor="w")
            if mat:
                res = self.resumo_materia(mat)
                if res:
                    tk.Label(miolo, text=f"Conteúdo: {res}", font=F["corpo_b"], bg=t["card"],
                             fg=t["destaque"]).pack(anchor="w", pady=(6, 0))
            dir_ = tk.Frame(hero, bg=t["card"])
            dir_.pack(side="right", padx=34, pady=18)
            alvo = fim if curso else ini
            mins = math.ceil((alvo - agora).total_seconds() / 60)
            tk.Label(dir_, text="Agora" if mins <= 0 else fmt_curto(mins), font=F["num"],
                     bg=t["card"], fg=t["destaque"]).pack(anchor="e")
            tk.Label(dir_, text="" if mins <= 0 else ("para terminar" if curso else "para começar"),
                     font=F["mini_b"], bg=t["card"], fg=t["suave"]).pack(anchor="e")
            self.clicavel(hero, lambda: self.abrir_item(x))
        else:
            miolo = tk.Frame(hero, bg=t["card"])
            miolo.pack(fill="x", padx=26, pady=22)
            tk.Label(miolo, text="Nada agendado", font=F["h2"], bg=t["card"], fg=t["tinta"]).pack(anchor="w")
            tk.Label(miolo, text="Adicione atividades no Cronograma ou matérias no modo Acadêmico.", font=F["corpo"],
                     bg=t["card"], fg=t["suave"]).pack(anchor="w", pady=(4, 0))

        # hoje
        self.secao(p, "Hoje")
        hoje = sorted(((inicio_em(x, agora.date()), x) for x in self.dados["tarefas"]
                       if inicio_em(x, agora.date())), key=lambda i: i[0])
        if hoje:
            fabricas = []
            for ini, x in hoje:
                seg = (ini - agora).total_seconds()
                fim = fim_em(x, agora.date())
                if seg > 0:
                    rod, realce, apag = "em " + fmt_curto(math.ceil(seg / 60)), seg <= 3600, False
                elif (agora < fim) if fim else seg > -3600:
                    rod, realce, apag = "agora", True, False
                else:
                    rod, realce, apag = "já passou", False, True
                fabricas.append(lambda g, x=x, r=rod, re=realce, a=apag:
                                self.bloco_tarefa(g, x, LADO, r, re, a))
            self.grade(p, fabricas)
        else:
            self.vazio(p, "Nada agendado para hoje.",
                       ("+  Adicionar atividade", lambda: self.dialogo_tarefa()))

        # resumo acadêmico rápido se houver matérias
        if self.dados.get("materias"):
            self.secao(p, "Aulas & Conteúdos em andamento")
            self.grade(p, [lambda g, m=m: self.bloco_materia_resumo(g, m)
                           for m in self.dados["materias"]], lado=LARG_MAT)

        # datas
        self.secao(p, "Datas importantes")
        futuras = sorted((d for d in self.dados["datas"] if dias_ate(d) >= 0), key=lambda d: d["data"])[:10]
        if futuras:
            self.grade(p, [lambda g, d=d: self.bloco_data(g, d) for d in futuras])
        else:
            self.vazio(p, "Nenhuma data cadastrada.", ("+  Novo evento", lambda: self.dialogo_data()))

    # ------------------------------------------------------------ tela: Acadêmico
    def fmt_horarios_lista(self, horarios):
        partes = []
        for h in horarios:
            dias_str = ", ".join(DIAS[d] for d in h.get("dias", []))
            faixa = f"{h['hora']}–{h['fim']}" if h.get("fim") else h["hora"]
            partes.append(f"{dias_str} ({faixa})" if dias_str else faixa)
        return "  ·  ".join(partes) if partes else "Sem horários definidos"

    def alternar_conteudo(self, m, idx):
        lista = m.get("conteudos", [])
        if 0 <= idx < len(lista):
            lista[idx]["feito"] = not lista[idx].get("feito", False)
            salvar(self.dados)
            self.render(conservar=True)

    def bloco_materia_resumo(self, parent, m):
        """Cartão compacto de matéria para a tela Hoje."""
        t, F = self.t, self.F
        b = Bloco(parent, t, LARG_MAT, cor_da(m["nome"]), altura=130)
        c = b.corpo
        tk.Label(c, text=corta(m["nome"], 34), font=F["h3"], bg=t["card"], fg=t["tinta"]).pack(anchor="w")
        tk.Label(c, text=self.fmt_horarios_lista(m.get("horarios", [])), font=F["mini_b"], bg=t["card"],
                 fg=t["suave"]).pack(anchor="w", pady=(2, 6))
        res = self.resumo_materia(m)
        if res:
            tk.Label(c, text=f"Em aula: {corta(res, 42)}", font=F["corpo_b"], bg=t["card"],
                     fg=t["destaque"]).pack(anchor="w")
        else:
            tk.Label(c, text="Clique para definir o conteúdo atual", font=F["mini"], bg=t["card"],
                     fg=t["suave"]).pack(anchor="w")
        self.bloco_clicavel(b, lambda: self.dialogo_materia(m))
        return b

    def card_materia(self, parent, m, largura):
        """Cartão completo de matéria para a aba Acadêmico."""
        t, F = self.t, self.F
        cor = cor_da(m["nome"])
        card = tk.Frame(parent, width=largura, bg=t["card"], highlightthickness=1,
                        highlightbackground=t["linha"])
        tk.Frame(card, bg=cor, height=5).pack(side="top", fill="x")
        corpo = tk.Frame(card, bg=t["card"])
        corpo.pack(fill="both", expand=True, padx=20, pady=18)

        topo = tk.Frame(corpo, bg=t["card"])
        topo.pack(fill="x")
        esq = tk.Frame(topo, bg=t["card"])
        esq.pack(side="left", fill="x", expand=True)
        tk.Label(esq, text=m["nome"], font=F["h2"], bg=t["card"], fg=t["tinta"],
                 anchor="w", justify="left", wraplength=largura - 120).pack(anchor="w")
        if m.get("local"):
            tk.Label(esq, text=m["local"], font=F["mini_b"], bg=t["card"],
                     fg=t["ok"]).pack(anchor="w", pady=(2, 0))

        btn_edit = tk.Label(topo, text="Editar", font=F["mini_b"], bg=t["bg"], fg=t["tinta"],
                            padx=10, pady=5, cursor="hand2", highlightthickness=1,
                            highlightbackground=t["linha"])
        btn_edit.pack(side="right", anchor="n")
        btn_edit.bind("<Button-1>", lambda e: self.dialogo_materia(m))

        tk.Label(corpo, text=self.fmt_horarios_lista(m.get("horarios", [])), font=F["mini_b"], bg=t["card"],
                 fg=t["suave"], justify="left", wraplength=largura - 44).pack(anchor="w", pady=(8, 12))

        tk.Frame(corpo, bg=t["linha"], height=1).pack(fill="x", pady=(0, 12))

        tk.Label(corpo, text="ACONTECENDO NA AULA AGORA", font=F["rotulo"], bg=t["card"],
                 fg=t["destaque"]).pack(anchor="w")
        atual_txt = m.get("atual", "").strip() or "Nenhum tópico em destaque definido."
        tk.Label(corpo, text=atual_txt, font=F["corpo_b"] if m.get("atual") else F["corpo"],
                 bg=t["card"], fg=t["tinta"] if m.get("atual") else t["suave"],
                 justify="left", anchor="w", wraplength=largura - 44).pack(anchor="w", pady=(3, 12))

        conteudos = m.get("conteudos", [])
        feitos = sum(1 for c in conteudos if c.get("feito"))
        rot_cont = f"CONTEÚDOS DA MATÉRIA ({feitos}/{len(conteudos)})" if conteudos else "CONTEÚDOS DA MATÉRIA"
        tk.Label(corpo, text=rot_cont, font=F["rotulo"], bg=t["card"],
                 fg=t["suave"]).pack(anchor="w", pady=(0, 6))

        if conteudos:
            for idx, item in enumerate(conteudos):
                feito = item.get("feito", False)
                linha = tk.Frame(corpo, bg=t["card"], cursor="hand2")
                linha.pack(fill="x", pady=3)
                box = tk.Label(linha, text="✓" if feito else " ", font=F["mini_b"], width=2,
                               bg=t["ok"] if feito else t["bg"], fg=t["sobre"] if feito else t["tinta"],
                               highlightthickness=1, highlightbackground=t["ok"] if feito else t["linha"])
                box.pack(side="left", anchor="n", pady=2)
                lbl = tk.Label(linha, text=item["texto"],
                               font=F["corpo_s"] if feito else F["corpo"],
                               bg=t["card"], fg=t["suave"] if feito else t["tinta"],
                               justify="left", anchor="w", wraplength=largura - 80)
                lbl.pack(side="left", padx=(10, 0), fill="x", expand=True)
                for w in (linha, box, lbl):
                    w.bind("<Button-1>", lambda e, m=m, i=idx: self.alternar_conteudo(m, i))
        else:
            tk.Label(corpo, text="Clique em 'Editar' para listar os assuntos e horários.",
                     font=F["mini"], bg=t["card"], fg=t["suave"]).pack(anchor="w")

        return card

    def view_academico(self, p):
        t = self.t
        self.cabecalho(p, "DISCIPLINAS, CONTEÚDOS E AULAS", "Modo Acadêmico",
                       ("+  Nova matéria", lambda: self.dialogo_materia()))

        materias = self.dados.get("materias", [])
        if not materias:
            self.vazio(p, "Nenhuma matéria cadastrada ainda. Os horários adicionados aqui entram automaticamente no Cronograma.",
                       ("+  Cadastrar primeira matéria", lambda: self.dialogo_materia()))
            return

        avail = self.largura_util()
        cols = 2 if avail >= 760 else 1
        larg = (avail - (cols * 16)) // cols
        g = tk.Frame(p, bg=t["bg"])
        g.pack(fill="x", anchor="w")
        for i, m in enumerate(materias):
            card = self.card_materia(g, m, larg)
            card.grid(row=i // cols, column=i % cols, padx=6, pady=8, sticky="nw")

    # ------------------------------------------------------------ tela: Cronograma
    def view_semana(self, p):
        t, F = self.t, self.F
        self.cabecalho(p, "SEMANA", "Cronograma", ("+  Nova atividade", lambda: self.dialogo_tarefa()))
        avail = self.largura_util()
        cols = max(1, min(7, avail // (120 + 12)))
        lado = max(120, min(176, (avail - cols * 12) // cols))
        hoje_i = datetime.now().weekday()
        board = tk.Frame(p, bg=t["bg"])
        board.pack(fill="x", anchor="w")
        for i in range(7):
            eh_hoje = i == hoje_i
            col = tk.Frame(board, bg=t["bg"])
            col.grid(row=i // cols, column=i % cols, sticky="n", padx=6, pady=(0, 18))
            cab = tk.Frame(col, bg=t["bg"])
            cab.pack(fill="x", pady=(0, 8))
            tk.Label(cab, text=DIAS[i].upper(), font=F["rotulo"], bg=t["bg"],
                     fg=t["destaque"] if eh_hoje else t["suave"]).pack(side="left")
            if eh_hoje:
                tk.Label(cab, text="hoje", font=F["mini"], bg=t["bg"], fg=t["destaque"]).pack(side="left", padx=6)
            tk.Frame(col, bg=t["destaque"] if eh_hoje else t["linha"], height=2).pack(fill="x", pady=(0, 12))
            itens = sorted((x for x in self.dados["tarefas"] if not x.get("data") and i in x.get("dias", [])),
                           key=lambda x: x["hora"])
            for x in itens:
                self.bloco_tarefa(col, x, lado).pack(pady=(0, 10))
            add = tk.Frame(col, width=lado, height=42, bg=t["bg"], highlightthickness=1,
                           highlightbackground=t["linha"])
            add.pack_propagate(False)
            add.pack()
            tk.Label(add, text="+  adicionar", font=F["mini"], bg=t["bg"], fg=t["suave"]).pack(expand=True)
            self.clicavel(add, lambda i=i: self.dialogo_tarefa(pre_dias=[i]))

        unicas = sorted((x for x in self.dados["tarefas"] if x.get("data")), key=lambda x: (x["data"], x["hora"]))
        if unicas:
            self.secao(p, "Datas únicas")
            self.grade(p, [lambda g, x=x: self.bloco_tarefa(g, x, lado, iso_para_br(x["data"]))
                           for x in unicas], lado=lado)

    # ------------------------------------------------------------ tela: Datas
    def view_datas(self, p):
        self.cabecalho(p, "CONTAGEM REGRESSIVA", "Datas importantes", ("+  Novo evento", lambda: self.dialogo_data()))
        ev = sorted(self.dados["datas"], key=lambda d: d["data"])
        futuras = [d for d in ev if dias_ate(d) >= 0]
        passadas = [d for d in reversed(ev) if dias_ate(d) < 0]
        if futuras:
            self.grade(p, [lambda g, d=d: self.bloco_data(g, d) for d in futuras])
        else:
            self.vazio(p, "Nenhuma data por vir.")
        if passadas:
            self.secao(p, "Já passaram")
            self.grade(p, [lambda g, d=d: self.bloco_data(g, d) for d in passadas])

    # ------------------------------------------------------------ tela: Ajustes
    def view_ajustes(self, p):
        t, F = self.t, self.F
        self.cabecalho(p, "PREFERÊNCIAS", "Ajustes")
        cfg = self.dados["config"]
        caixa = tk.Frame(p, bg=t["card"], highlightthickness=1, highlightbackground=t["linha"])
        caixa.pack(anchor="w", padx=6)
        i = tk.Frame(caixa, bg=t["card"])
        i.pack(padx=32, pady=28)

        def spin(de, ate, valor):
            v = tk.StringVar(value=str(valor))
            tk.Spinbox(i, from_=de, to=ate, textvariable=v, width=5, font=F["corpo"], justify="center",
                       bg=t["bg"], fg=t["tinta"], relief="flat", buttonbackground=t["lateral"],
                       highlightthickness=1, highlightbackground=t["linha"], highlightcolor=t["destaque"],
                       insertbackground=t["tinta"]).grid(row=spin.n, column=1, padx=(40, 0), sticky="e")
            return v

        spin.n = 0

        def rotulo(titulo, desc):
            f = tk.Frame(i, bg=t["card"])
            f.grid(row=spin.n, column=0, sticky="w", pady=10)
            tk.Label(f, text=titulo, font=F["corpo_b"], bg=t["card"], fg=t["tinta"]).pack(anchor="w")
            tk.Label(f, text=desc, font=F["mini"], bg=t["card"], fg=t["suave"]).pack(anchor="w")

        rotulo("Avisar a cada", "minutos entre um aviso e outro")
        v_int = spin(1, 60, cfg["intervalo_min"])
        spin.n = 1
        rotulo("Começar a avisar", "minutos antes da atividade")
        v_ant = spin(5, 720, cfg["antecedencia_min"])
        spin.n = 2
        rotulo("Aparência", "tema da janela")
        tf = tk.Frame(i, bg=t["card"])
        tf.grid(row=2, column=1, padx=(40, 0), sticky="e")
        for nome, rot in (("claro", "Claro"), ("escuro", "Escuro")):
            on = cfg["tema"] == nome
            lab = tk.Label(tf, text=rot, font=F["corpo_b"], width=7, pady=7, cursor="hand2",
                           bg=t["destaque"] if on else t["bg"], fg=t["sobre"] if on else t["tinta"],
                           highlightthickness=1, highlightbackground=t["destaque"] if on else t["linha"])
            lab.pack(side="left", padx=(0, 6))
            lab.bind("<Button-1>", lambda e, n=nome: self.trocar_tema(n))

        msg = tk.Label(i, text="", font=F["mini"], bg=t["card"], fg=t["ok"])

        def salvar_cfg():
            try:
                cfg["intervalo_min"] = max(1, int(v_int.get()))
                cfg["antecedencia_min"] = max(1, int(v_ant.get()))
            except ValueError:
                msg.configure(text="Use apenas números.", fg=t["destaque"])
                return
            salvar(self.dados)
            msg.configure(text="Salvo.", fg=t["ok"])

        def auto():
            try:
                msg.configure(text=f"Criado: {instalar_autostart()}", fg=t["ok"])
            except Exception as e:
                msg.configure(text=str(e), fg=t["destaque"])

        bt = tk.Frame(i, bg=t["card"])
        bt.grid(row=3, column=0, columnspan=2, sticky="w", pady=(22, 0))
        self.botao(bt, "Salvar", salvar_cfg).pack(side="left")
        self.botao(bt, "Iniciar com o computador", auto, tipo="ghost", fundo=t["card"]).pack(side="left", padx=10)
        msg.grid(row=4, column=0, columnspan=2, sticky="w", pady=(12, 0))

        tk.Label(p, text=f"Dados salvos em {DATA_FILE}\nFechar a janela apenas a minimiza — o app continua avisando.",
                 font=F["mini"], bg=t["bg"], fg=t["suave"], justify="left").pack(anchor="w", padx=6, pady=(18, 0))

    def trocar_tema(self, nome):
        self.dados["config"]["tema"] = nome
        salvar(self.dados)
        self.aplicar_tema()
        self.montar()
        self.render()

    # ------------------------------------------------------------ diálogos
    def novo_dialogo(self, titulo, largura=520):
        t = self.t
        d = tk.Toplevel(self.root)
        d.title(titulo)
        d.configure(bg=t["bg"])
        d.transient(self.root)
        d.resizable(False, False)
        d.minsize(largura, 0)
        tk.Frame(d, bg=t["destaque"], height=5).pack(fill="x")
        c = tk.Frame(d, bg=t["bg"])
        c.pack(fill="both", expand=True, padx=30, pady=(22, 26))
        tk.Label(c, text=titulo, font=self.F["h2"], bg=t["bg"], fg=t["tinta"]).pack(anchor="w")
        d.bind("<Escape>", lambda e: d.destroy())
        return d, c

    def mostrar(self, d):
        d.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - d.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - d.winfo_height()) // 3
        d.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        try:
            d.wait_visibility()
            d.grab_set()
        except tk.TclError:
            pass

    def rotulo_campo(self, c, texto):
        tk.Label(c, text=texto.upper(), font=self.F["rotulo"], bg=self.t["bg"],
                 fg=self.t["suave"]).pack(anchor="w", pady=(14, 5))

    def campo(self, c, rotulo, valor=""):
        t = self.t
        self.rotulo_campo(c, rotulo)
        e = tk.Entry(c, font=self.F["corpo"], bg=t["card"], fg=t["tinta"], insertbackground=t["tinta"],
                     relief="flat", highlightthickness=1, highlightbackground=t["linha"],
                     highlightcolor=t["destaque"])
        e.pack(fill="x", ipady=8)
        e.insert(0, valor)
        return e

    def editor_horarios(self, c, horarios_iniciais, pre_dias=None):
        """
        Componente reutilizável para adicionar/editar múltiplos horários em dias diferentes
        (ex: Seg 13:00-14:00, Ter 08:00-10:00).
        Clique num horário listado para editá-lo; se mexer nos campos e clicar direto em Salvar,
        ele aplica automaticamente.
        """
        t, F = self.t, self.F
        horarios = [dict(dias=list(h.get("dias", [])), hora=h["hora"], fim=h.get("fim", ""))
                    for h in horarios_iniciais]

        # Se já existe exatamente 1 horário cadastrado, já deixa selecionado para edição direta
        edit_state = {"idx": 0 if len(horarios) == 1 else None}

        lista_frame = tk.Frame(c, bg=t["bg"])
        lista_frame.pack(fill="x", pady=(0, 8))

        box = tk.Frame(c, bg=t["bg"])
        box.pack(fill="x")

        rot_modo = tk.Label(box, text="", font=F["mini_b"], bg=t["bg"], fg=t["ok"])
        rot_modo.pack(anchor="w", pady=(0, 4))

        fr_dias = tk.Frame(box, bg=t["bg"])
        fr_dias.pack(anchor="w")

        dias_init = (horarios[0]["dias"] if len(horarios) == 1
                     else (pre_dias if pre_dias is not None else [0]))
        estado_dias = [i in dias_init for i in range(7)]
        labs_dias = []

        def pinta_dia(i):
            on = estado_dias[i]
            labs_dias[i].configure(bg=t["destaque"] if on else t["card"],
                                   fg=t["sobre"] if on else t["tinta"],
                                   highlightbackground=t["destaque"] if on else t["linha"])

        def alterna_dia(i):
            estado_dias[i] = not estado_dias[i]
            pinta_dia(i)

        def definir_dias(lista_indices):
            for i in range(7):
                estado_dias[i] = (i in lista_indices)
                pinta_dia(i)

        for i, n in enumerate(DIAS):
            lab = tk.Label(fr_dias, text=n, width=4, pady=6, font=F["corpo_b"],
                           cursor="hand2", highlightthickness=1)
            lab.pack(side="left", padx=(0, 6))
            lab.bind("<Button-1>", lambda e, i=i: alterna_dia(i))
            labs_dias.append(lab)
            pinta_dia(i)

        atalhos = tk.Frame(box, bg=t["bg"])
        atalhos.pack(anchor="w", pady=(6, 0))
        for texto, inds in (("Seg–Sex", [0, 1, 2, 3, 4]), ("Todos", [0, 1, 2, 3, 4, 5, 6]), ("Limpar", [])):
            a = tk.Label(atalhos, text=texto, font=F["mini_b"], bg=t["bg"], fg=t["destaque"], cursor="hand2")
            a.pack(side="left", padx=(0, 14))
            a.bind("<Button-1>", lambda e, v=inds: definir_dias(v))

        linha_hr = tk.Frame(box, bg=t["bg"])
        linha_hr.pack(fill="x", pady=(8, 0))

        tk.Label(linha_hr, text="Início:", font=F["mini_b"], bg=t["bg"], fg=t["suave"]).pack(side="left")
        e_ini = tk.Entry(linha_hr, width=8, font=F["corpo"], bg=t["card"], fg=t["tinta"],
                         insertbackground=t["tinta"], relief="flat", highlightthickness=1,
                         highlightbackground=t["linha"])
        e_ini.pack(side="left", padx=(6, 14), ipady=5)

        tk.Label(linha_hr, text="Término:", font=F["mini_b"], bg=t["bg"], fg=t["suave"]).pack(side="left")
        e_fim = tk.Entry(linha_hr, width=8, font=F["corpo"], bg=t["card"], fg=t["tinta"],
                         insertbackground=t["tinta"], relief="flat", highlightthickness=1,
                         highlightbackground=t["linha"])
        e_fim.pack(side="left", padx=(6, 14), ipady=5)

        if len(horarios) == 1:
            e_ini.insert(0, horarios[0]["hora"])
            e_fim.insert(0, horarios[0].get("fim", ""))

        btn_acao = self.botao(linha_hr, "+ Adicionar horário", lambda: confirmar_edicao(), tipo="ghost")
        btn_acao.pack(side="left")

        btn_novo = tk.Label(linha_hr, text="Novo horário", font=F["mini_b"], bg=t["bg"],
                            fg=t["suave"], cursor="hand2", padx=8)

        def atualizar_rotulo_modo():
            if edit_state["idx"] is not None:
                idx = edit_state["idx"]
                dias_txt = ", ".join(DIAS[d] for d in horarios[idx]["dias"])
                rot_modo.configure(
                    text=f"Editando horário #{idx + 1} ({dias_txt}) — altere abaixo ou clique em '+ Novo horário'",
                    fg=t["ok"]
                )
                btn_acao.configure(text="Aplicar no horário")
                btn_novo.pack(side="left", padx=(6, 0))
            else:
                rot_modo.configure(
                    text="Selecione os dias e informe o horário (você pode incluir vários horários em dias diferentes):",
                    fg=t["suave"]
                )
                btn_acao.configure(text="+ Incluir horário")
                btn_novo.pack_forget()

        def selecionar_para_editar(idx):
            edit_state["idx"] = idx
            h = horarios[idx]
            definir_dias(h["dias"])
            e_ini.delete(0, "end")
            e_ini.insert(0, h["hora"])
            e_fim.delete(0, "end")
            e_fim.insert(0, h.get("fim", ""))
            render_lista()
            atualizar_rotulo_modo()

        def modo_novo():
            edit_state["idx"] = None
            definir_dias([])
            e_ini.delete(0, "end")
            e_fim.delete(0, "end")
            render_lista()
            atualizar_rotulo_modo()

        btn_novo.bind("<Button-1>", lambda e: modo_novo())

        def remover_h(idx):
            horarios.pop(idx)
            if edit_state["idx"] == idx:
                modo_novo()
            elif edit_state["idx"] is not None and edit_state["idx"] > idx:
                edit_state["idx"] -= 1
            render_lista()
            atualizar_rotulo_modo()

        def render_lista():
            for w in lista_frame.winfo_children():
                w.destroy()
            if not horarios:
                tk.Label(lista_frame, text="Nenhum horário confirmado na lista ainda (preencha abaixo).",
                         font=F["mini"], bg=t["bg"], fg=t["suave"]).pack(anchor="w", pady=2)
                return
            for idx, h in enumerate(horarios):
                selecionado = (edit_state["idx"] == idx)
                borda = t["destaque"] if selecionado else t["linha"]
                row = tk.Frame(lista_frame, bg=t["card"], highlightthickness=1,
                               highlightbackground=borda, cursor="hand2")
                row.pack(fill="x", pady=2)
                dias_txt = ", ".join(DIAS[i] for i in h["dias"]) if h["dias"] else "Data única"
                hora_txt = f"{h['hora']} até {h['fim']}" if h.get("fim") else h["hora"]
                lbl = tk.Label(row, text=f"{dias_txt}  ·  {hora_txt}", font=F["corpo_b"],
                               bg=t["card"], fg=t["destaque"] if selecionado else t["tinta"],
                               padx=12, pady=6, cursor="hand2")
                lbl.pack(side="left")
                dica = tk.Label(row, text="editando" if selecionado else "clique p/ editar",
                                font=F["mini"], bg=t["card"], fg=t["suave"], cursor="hand2")
                dica.pack(side="left", padx=6)
                rm = tk.Label(row, text="remover", font=F["mini_b"], bg=t["card"],
                              fg=t["destaque"], padx=10, cursor="hand2")
                rm.pack(side="right")
                for w in (row, lbl, dica):
                    w.bind("<Button-1>", lambda e, i=idx: selecionar_para_editar(i))
                rm.bind("<Button-1>", lambda e, i=idx: remover_h(i))

        erro_interno = {"msg": ""}

        def ler_campos_atuais(exigir_dias=True):
            ini_str = e_ini.get().strip()
            fim_str = e_fim.get().strip()
            dias_sel = [i for i, v in enumerate(estado_dias) if v]
            if not ini_str:
                return None, None
            if exigir_dias and not dias_sel:
                return None, "Selecione ao menos um dia da semana para este horário."
            try:
                h_i = parse_hora(ini_str)
            except ValueError:
                return None, "Hora de início inválida. Use o formato 08:00 ou 13:00."
            h_f = ""
            if fim_str:
                try:
                    h_f = parse_hora(fim_str)
                except ValueError:
                    return None, "Hora de término inválida. Use o formato 10:00 ou 14:00."
                if h_f <= h_i:
                    return None, "O horário de término precisa ser depois do início."
            return {"dias": dias_sel, "hora": h_i, "fim": h_f}, None

        def confirmar_edicao():
            item, err = ler_campos_atuais(exigir_dias=True)
            if err:
                erro_interno["msg"] = err
                if hasattr(self, "_ultimo_erro_lbl") and self._ultimo_erro_lbl:
                    self._ultimo_erro_lbl.configure(text=err)
                return False
            if not item:
                if hasattr(self, "_ultimo_erro_lbl") and self._ultimo_erro_lbl:
                    self._ultimo_erro_lbl.configure(text="Preencha a hora de início (ex.: 08:00).")
                return False

            if edit_state["idx"] is not None:
                horarios[edit_state["idx"]] = item
            else:
                horarios.append(item)

            # Limpa para permitir adicionar o próximo horário (ex: outro dia da semana)
            edit_state["idx"] = None
            definir_dias([])
            e_ini.delete(0, "end")
            e_fim.delete(0, "end")
            if hasattr(self, "_ultimo_erro_lbl") and self._ultimo_erro_lbl:
                self._ultimo_erro_lbl.configure(text="")
            render_lista()
            atualizar_rotulo_modo()
            return True

        def obter_horarios_finais(exigir_dias=True):
            """
            Chamado ao clicar no botão principal 'Salvar'.
            Se o usuário digitou ou editou um horário nos campos e clicou direto em 'Salvar',
            aplica automaticamente sem perder as alterações.
            """
            ini_str = e_ini.get().strip()
            if ini_str:
                item, err = ler_campos_atuais(exigir_dias=exigir_dias)
                if err:
                    return None, err
                if item:
                    if edit_state["idx"] is not None:
                        horarios[edit_state["idx"]] = item
                    else:
                        # Evita duplicar se for idêntico ao que já está na lista
                        if item not in horarios:
                            horarios.append(item)
            if not horarios:
                return None, "Adicione ao menos um horário (ex.: 08:00 às 10:00)."
            return horarios, None

        render_lista()
        atualizar_rotulo_modo()
        return obter_horarios_finais

    def rodape_dialogo(self, c, d, salvar_cmd, remover_cmd=None, bind_return=True):
        t = self.t
        erro = tk.Label(c, text="", font=self.F["mini"], bg=t["bg"], fg=t["destaque"], anchor="w")
        erro.pack(fill="x", pady=(14, 0))
        self._ultimo_erro_lbl = erro
        linha = tk.Frame(c, bg=t["bg"])
        linha.pack(fill="x", pady=(8, 0))
        self.botao(linha, "Salvar", salvar_cmd).pack(side="right")
        self.botao(linha, "Cancelar", d.destroy, tipo="ghost").pack(side="right", padx=8)
        if remover_cmd:
            estado = {"confirmar": False}
            b = self.botao(linha, "Remover", lambda: None, tipo="perigo")

            def clique(_e=None):
                if not estado["confirmar"]:
                    estado["confirmar"] = True
                    b.configure(text="Confirmar remoção")
                else:
                    remover_cmd()

            b.bind("<Button-1>", clique)
            b.pack(side="left")
        if bind_return:
            d.bind("<Return>", lambda e: salvar_cmd())
        return erro

    def dialogo_materia(self, m=None):
        t, F = self.t, self.F
        d, c = self.novo_dialogo("Editar matéria" if m else "Nova matéria", largura=580)

        par_topo = tk.Frame(c, bg=t["bg"])
        par_topo.pack(fill="x")
        c_esq = tk.Frame(par_topo, bg=t["bg"])
        c_esq.pack(side="left", fill="x", expand=True, padx=(0, 8))
        c_dir = tk.Frame(par_topo, bg=t["bg"])
        c_dir.pack(side="left", fill="x", expand=True, padx=(8, 0))

        e_nome = self.campo(c_esq, "Matéria (ex.: Cálculo I)", m["nome"] if m else "")
        e_local = self.campo(c_dir, "Sala / Professor (opcional)", m.get("local", "") if m else "")

        e_atual = self.campo(c, "Conteúdo acontecendo na aula agora", m.get("atual", "") if m else "")

        self.rotulo_campo(c, "Conteúdos / Tópicos da matéria (um por linha — use [x] para concluído)")
        txt_cont = tk.Text(c, height=4, font=F["corpo"], bg=t["card"], fg=t["tinta"],
                           insertbackground=t["tinta"], relief="flat", highlightthickness=1,
                           highlightbackground=t["linha"], highlightcolor=t["destaque"], padx=10, pady=8)
        txt_cont.pack(fill="x")
        if m and m.get("conteudos"):
            linhas_init = [f"[{'x' if item.get('feito') else ' '}] {item['texto']}"
                           for item in m["conteudos"]]
            txt_cont.insert("1.0", "\n".join(linhas_init))

        self.rotulo_campo(c, "Horários da matéria (entram automaticamente no Cronograma)")
        obter_horarios = self.editor_horarios(c, m.get("horarios", []) if m else [])

        def ler_conteudos():
            bruto = txt_cont.get("1.0", "end").splitlines()
            saida = []
            for ln in bruto:
                s = ln.strip()
                if not s:
                    continue
                feito = False
                if s.lower().startswith("[x]"):
                    feito = True
                    s = s[3:].strip()
                elif s.startswith("[ ]") or s.startswith("[]"):
                    s = s.split("]", 1)[1].strip()
                elif s.startswith("- "):
                    s = s[2:].strip()
                if s:
                    saida.append({"texto": s, "feito": feito})
            return saida

        def salvar_():
            nome = e_nome.get().strip()
            if not nome:
                return erro.configure(text="Digite o nome da matéria.")
            horarios_finais, err = obter_horarios(exigir_dias=True)
            if err:
                return erro.configure(text=err)

            conteudos = ler_conteudos()
            atual = e_atual.get().strip()
            local = e_local.get().strip()

            if m:
                m.update(nome=nome, local=local, atual=atual, conteudos=conteudos, horarios=horarios_finais)
            else:
                self.dados["materias"].append({
                    "id": uuid.uuid4().hex,
                    "nome": nome,
                    "local": local,
                    "atual": atual,
                    "conteudos": conteudos,
                    "horarios": horarios_finais,
                })
            salvar(self.dados)
            d.destroy()
            self.render(conservar=True)

        def remover_():
            self.dados["materias"] = [y for y in self.dados["materias"] if y["id"] != m["id"]]
            salvar(self.dados)
            d.destroy()
            self.render(conservar=True)

        erro = self.rodape_dialogo(c, d, salvar_, remover_ if m else None, bind_return=False)
        self.mostrar(d)
        e_nome.focus_set()

    def dialogo_tarefa(self, ativ=None, pre_dias=None):
        d, c = self.novo_dialogo("Editar atividade" if ativ else "Nova atividade", largura=560)
        e_nome = self.campo(c, "O que fazer (ex.: Academia, Corrida, Estudo)", ativ["nome"] if ativ else "")

        self.rotulo_campo(c, "Horários por dia da semana (ex.: Seg 13:00–14:00, Ter 08:00–10:00)")
        obter_horarios = self.editor_horarios(
            c,
            ativ.get("horarios", []) if ativ else [],
            pre_dias=pre_dias if pre_dias is not None else [0],
        )

        e_data = self.campo(
            c,
            "Ou data única opcional (DD/MM/AAAA)",
            iso_para_br(ativ["data"]) if ativ and ativ.get("data") else "",
        )
        tk.Label(c, text="Deixe a data em branco para repetir semanalmente nos dias escolhidos.",
                 font=self.F["mini"], bg=self.t["bg"], fg=self.t["suave"]).pack(anchor="w", pady=(4, 0))

        def salvar_():
            nome = e_nome.get().strip()
            if not nome:
                return erro.configure(text="Digite o nome da atividade.")
            data_iso = ""
            if e_data.get().strip():
                try:
                    data_iso = parse_data(e_data.get())
                except ValueError:
                    return erro.configure(text="Data inválida. Use o formato DD/MM/AAAA.")

            horarios_finais, err = obter_horarios(exigir_dias=not bool(data_iso))
            if err:
                return erro.configure(text=err)

            if ativ:
                ativ.update(nome=nome, horarios=horarios_finais, data=data_iso)
            else:
                self.dados["atividades"].append({
                    "id": uuid.uuid4().hex,
                    "nome": nome,
                    "horarios": horarios_finais,
                    "data": data_iso,
                })
            salvar(self.dados)
            d.destroy()
            self.render(conservar=True)

        def remover_():
            self.dados["atividades"] = [y for y in self.dados["atividades"] if y["id"] != ativ["id"]]
            salvar(self.dados)
            d.destroy()
            self.render(conservar=True)

        erro = self.rodape_dialogo(c, d, salvar_, remover_ if ativ else None)
        self.mostrar(d)
        e_nome.focus_set()

    def dialogo_data(self, x=None):
        d, c = self.novo_dialogo("Editar evento" if x else "Novo evento")
        e_nome = self.campo(c, "Evento", x["nome"] if x else "")
        e_data = self.campo(c, "Data (DD/MM/AAAA)", iso_para_br(x["data"]) if x else "")

        def salvar_():
            nome = e_nome.get().strip()
            if not nome:
                return erro.configure(text="Digite o nome do evento.")
            try:
                data_iso = parse_data(e_data.get())
            except ValueError:
                return erro.configure(text="Data inválida. Use o formato DD/MM/AAAA.")
            if x:
                x.update(nome=nome, data=data_iso)
            else:
                self.dados["datas"].append({"id": uuid.uuid4().hex, "nome": nome, "data": data_iso})
            salvar(self.dados)
            d.destroy()
            self.render(conservar=True)

        def remover_():
            self.dados["datas"] = [y for y in self.dados["datas"] if y["id"] != x["id"]]
            salvar(self.dados)
            d.destroy()
            self.render(conservar=True)

        erro = self.rodape_dialogo(c, d, salvar_, remover_ if x else None)
        self.mostrar(d)
        e_nome.focus_set()

    # ------------------------------------------------------------ avisos
    def descricao_tarefa_alerta(self, x):
        mat = self.materia_da_tarefa(x)
        if not mat:
            return x["nome"]
        res = self.resumo_materia(mat)
        return f"{x['nome']} ({res})" if res else x["nome"]

    def itens_resumo(self, agora):
        itens = []
        futuras = sorted((d for d in self.dados["datas"] if dias_ate(d) >= 0), key=lambda d: d["data"])
        if futuras:
            itens.append((None, "Datas importantes"))
            for d in futuras[:6]:
                n = dias_ate(d)
                if n == 0:
                    itens.append(("HOJE", d["nome"]))
                else:
                    itens.append((f"{n} dia{'s' if n != 1 else ''}", f"para {d['nome']}"))
        itens.append((None, "Hoje"))
        achou = False
        for ini, x in sorted(((inicio_em(x, agora.date()), x) for x in self.dados["tarefas"]
                              if inicio_em(x, agora.date())), key=lambda i: i[0]):
            seg = (ini - agora).total_seconds()
            fim = fim_em(x, agora.date())
            ate = f"  ·  até {x['fim']}" if fim else ""
            desc = self.descricao_tarefa_alerta(x)
            if seg > 0:
                itens.append((x["hora"], f"{desc}{ate}  ·  faltam {fmt_min(math.ceil(seg / 60))}"))
                achou = True
            elif (agora < fim) if fim else seg > -3600:
                itens.append((x["hora"], f"{desc}{ate}  ·  agora"))
                achou = True
        if not achou:
            itens.append(("—", "Nada mais agendado para hoje"))
        return itens

    def alerta(self, titulo, itens, slot="aviso"):
        t, F = self.t, self.F
        antigo = self.popups.get(slot)
        if antigo is not None and antigo.winfo_exists():
            antigo.destroy()
        p = tk.Toplevel(self.root)
        self.popups[slot] = p
        p.title(titulo)
        p.configure(bg=t["card"])
        p.attributes("-topmost", True)
        tk.Frame(p, bg=t["destaque"], height=6).pack(fill="x")
        c = tk.Frame(p, bg=t["card"])
        c.pack(padx=36, pady=(24, 24))
        tk.Label(c, text=titulo.upper(), font=F["rotulo"], bg=t["card"], fg=t["destaque"]).pack(anchor="w")
        for big, txt in itens:
            if big is None:
                tk.Label(c, text=txt.upper(), font=F["rotulo"], bg=t["card"], fg=t["suave"]).pack(anchor="w", pady=(18, 4))
                continue
            r = tk.Frame(c, bg=t["card"])
            r.pack(fill="x", pady=4)
            tk.Label(r, text=big, font=F["alerta"], bg=t["card"], fg=t["destaque"], width=8,
                     anchor="w").pack(side="left")
            tk.Label(r, text=txt, font=F["corpo"], bg=t["card"], fg=t["tinta"], wraplength=330,
                     justify="left", anchor="w").pack(side="left", padx=(6, 0))
        self.botao(c, "Entendi", p.destroy, fundo=t["card"]).pack(anchor="e", pady=(22, 0))
        p.bind("<Escape>", lambda e: p.destroy())
        p.update_idletasks()
        off = 0 if slot == "resumo" else 70
        x = (p.winfo_screenwidth() - p.winfo_reqwidth()) // 2 + off
        y = p.winfo_screenheight() // 5 + off
        p.geometry(f"+{max(x, 0)}+{y}")
        p.lift()
        self.beep()
        if not IS_WIN and shutil.which("notify-send"):
            corpo = "  |  ".join(f"{b} {s}" if b else s for b, s in itens)
            try:
                subprocess.Popen(["notify-send", "-u", "critical", titulo, corpo])
            except OSError:
                pass

    def beep(self):
        try:
            if IS_WIN:
                import winsound
                winsound.MessageBeep()
            else:
                self.root.bell()
        except Exception:
            pass

    def checar(self):
        try:
            self._checar()
        finally:
            self.root.after(15000, self.checar)

    def _checar(self):
        agora = datetime.now()
        cfg = self.dados["config"]
        intervalo, antecedencia = cfg["intervalo_min"], cfg["antecedencia_min"]
        avisos = []
        for x in self.dados["tarefas"]:
            ini = inicio_em(x, agora.date())
            if not ini:
                continue
            fim = fim_em(x, agora.date())
            desc = self.descricao_tarefa_alerta(x)
            if fim and -60 < (fim - agora).total_seconds() <= 0:
                chave = (x["id"], ini.date().isoformat(), "fim")
                if chave not in self.avisados:
                    self.avisados.add(chave)
                    avisos.append((-1, "FIM", f"{desc} terminou"))
            seg = (ini - agora).total_seconds()
            if seg < -60:
                continue
            minutos = math.ceil(seg / 60) if seg > 0 else 0
            if minutos > antecedencia:
                continue
            if minutos == 0 or minutos % intervalo == 0:
                chave = (x["id"], ini.date().isoformat(), minutos)
                if chave in self.avisados:
                    continue
                self.avisados.add(chave)
                if minutos == 0:
                    avisos.append((0, "AGORA", desc))
                else:
                    avisos.append((minutos, fmt_curto(minutos), f"para começar: {desc}"))
        if avisos:
            avisos.sort()
            self.alerta("Lembrete", [(b, s) for _, b, s in avisos])

        atual = agora.replace(second=0, microsecond=0)
        if self._min is None or (self._min != atual and
                                 (self.view == "hoje" or self._min.date() != atual.date())):
            self.render(conservar=True)


def main():
    root = tk.Tk()
    App(root, auto="--auto" in sys.argv)
    root.mainloop()


if __name__ == "__main__":
    main()