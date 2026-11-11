#!/usr/bin/env python3
"""
Lembretes — cronograma, modo acadêmico, contagem regressiva e avisos.
Funciona em Arch Linux e Windows. Sem dependências externas (só Tkinter).

Dados salvos em: ~/.lembretes/dados.json (com backup em dados.json.bak)

Atalhos: Ctrl+1…6 trocam de tela · Ctrl+N novo item · F5 atualiza · Ctrl+Q encerra
Abrir o app de novo enquanto ele já está rodando só traz a janela para frente.
"""

import json
import math
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import uuid
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import font as tkfont
from datetime import datetime, date, timedelta
from pathlib import Path

APP_DIR = Path.home() / ".lembretes"           # coisas locais deste computador
LOCAL_FILE = APP_DIR / "local.json"             # guarda só qual pasta usar para os dados
IS_WIN = sys.platform.startswith("win")


def ler_local():
    try:
        with open(LOCAL_FILE, encoding="utf-8") as f:
            v = json.load(f)
            return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def gravar_local(info):
    APP_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOCAL_FILE, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)


def pasta_dados():
    p = ler_local().get("pasta_dados", "")
    return Path(p) if p and Path(p).is_dir() else APP_DIR


DATA_DIR = pasta_dados()                        # pode ser uma pasta sincronizada (Drive, Syncthing…)
DATA_FILE = DATA_DIR / "dados.json"


def definir_pasta_dados(nova):
    """Troca a pasta dos dados (None = padrão). Atualiza as variáveis globais."""
    global DATA_DIR, DATA_FILE
    info = ler_local()
    if nova is None:
        info.pop("pasta_dados", None)
    else:
        info["pasta_dados"] = str(nova)
    gravar_local(info)
    DATA_DIR = pasta_dados()
    DATA_FILE = DATA_DIR / "dados.json"


# bandeja do sistema é opcional: só se 'pystray' e 'pillow' estiverem instalados
try:
    import pystray
    from PIL import Image, ImageDraw
    TEM_BANDEJA = True
except Exception:  # ImportError ou backend gráfico indisponível
    TEM_BANDEJA = False
PORTA_INSTANCIA = 47653          # usada só em 127.0.0.1 para evitar duas cópias abertas
SENHA_INSTANCIA = b"lembretes:mostrar"
ADIAR_MIN = 5                   # botão "Adiar" dos avisos

DIAS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
DIAS_LONGO = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
              "sexta-feira", "sábado", "domingo"]
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]

PADRAO = {
    "config": {"intervalo_min": 10, "antecedencia_min": 60, "tema": "claro",
               "resumo_ao_iniciar": True, "fechar_minimiza": True, "geometria": "",
               "bandeja": True,
               # semestre: fora dele (e nos feriados) as aulas somem e não avisam
               "semestre_inicio": "", "semestre_fim": "",
               "feriados": [],          # [{inicio, fim, nome}] em ISO
               "media_aprovacao": 7.0, "nota_max": 10.0, "limite_faltas_pct": 25,
               "pomodoro_min": 25, "pausa_min": 5, "revisoes_dias": [1, 7, 30]},
    "atividades": [],  # {id, nome, horarios: [{dias, hora, fim}], data "YYYY-MM-DD"}
    "materias": [],    # {id, nome, local, atual, horarios, max_faltas, faltas: [iso],
                       #  conteudos: [{texto, feito, feito_em, revisoes}],
                       #  avaliacoes: [{nome, peso, nota|None}]}
    "tarefas": [],     # gerado automaticamente a partir de 'atividades' e 'materias'
    "datas": [],       # {id, nome, data "YYYY-MM-DD", materia_id ""}
    "estudos": [],     # sessões de estudo: {materia_id, data "YYYY-MM-DD", min}
}

# calendário letivo (preenchido por sincronizar_grade a partir da config)
CALENDARIO = {"inicio": None, "fim": None, "feriados": set()}

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
# monoespaçada: só em números, horários e campos de dados (se a Fira Code não estiver instalada, usa a próxima)
MONO = ["Fira Code", "FiraCode Nerd Font", "FiraCode Nerd Font Mono", "Fira Mono", "JetBrains Mono",
        "Cascadia Code", "Consolas", "DejaVu Sans Mono", "Liberation Mono", "Courier New", "Courier"]

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
        m.setdefault("faltas", [])
        m.setdefault("max_faltas", 0)
        m.setdefault("avaliacoes", [])
        m.setdefault("conteudos", [])
        for idx, h in enumerate(m.get("horarios", [])):
            lista.append({
                "id": f"mat_{m['id']}_{idx}",
                "materia_id": m["id"],
                "aula": True,
                "nome": m["nome"],
                "hora": h["hora"],
                "fim": h.get("fim", ""),
                "dias": h.get("dias", []),
                "data": "",
            })

    dados["tarefas"] = lista
    atualizar_calendario(dados.get("config", {}))


def iso_ou_none(iso):
    try:
        return datetime.strptime(iso, "%Y-%m-%d").date() if iso else None
    except ValueError:
        return None


def atualizar_calendario(cfg):
    CALENDARIO["inicio"] = iso_ou_none(cfg.get("semestre_inicio", ""))
    CALENDARIO["fim"] = iso_ou_none(cfg.get("semestre_fim", ""))
    dias = set()
    for f in cfg.get("feriados", []):
        ini, fim = iso_ou_none(f.get("inicio")), iso_ou_none(f.get("fim") or f.get("inicio"))
        if ini and fim:
            d = ini
            while d <= fim and len(dias) < 2000:
                dias.add(d)
                d += timedelta(days=1)
    CALENDARIO["feriados"] = dias


def tem_aula(dia):
    """False se o dia estiver fora do semestre ou for feriado/recesso."""
    c = CALENDARIO
    if c["inicio"] and dia < c["inicio"]:
        return False
    if c["fim"] and dia > c["fim"]:
        return False
    return dia not in c["feriados"]


AVISO_CARGA = ""  # mensagem mostrada na tela se o arquivo de dados estava danificado


def carregar():
    global AVISO_CARGA
    dados = {}
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, encoding="utf-8") as f:
                dados = json.load(f)
            if not isinstance(dados, dict):
                raise ValueError("formato inesperado")
        except (OSError, ValueError):
            # Nunca sobrescrever um arquivo que não conseguimos ler: guarda uma cópia antes.
            copia = DATA_FILE.with_name(f"dados-danificado-{datetime.now():%Y%m%d-%H%M%S}.json")
            try:
                shutil.copy2(DATA_FILE, copia)
                AVISO_CARGA = f"O arquivo de dados estava danificado. Uma cópia foi guardada em {copia}."
            except OSError:
                AVISO_CARGA = "O arquivo de dados estava danificado e não pôde ser copiado."
            # tenta o backup automático da última gravação boa
            bak = DATA_FILE.with_suffix(".json.bak")
            try:
                with open(bak, encoding="utf-8") as f:
                    dados = json.load(f)
                AVISO_CARGA += " Os dados foram restaurados do último backup."
            except (OSError, ValueError):
                dados = {}
    return normalizar(dados)


def normalizar(dados):
    for k, v in PADRAO.items():
        if not isinstance(dados.get(k), type(v)):
            dados[k] = json.loads(json.dumps(v))
    for k, v in PADRAO["config"].items():
        dados["config"].setdefault(k, json.loads(json.dumps(v)))
    if dados["config"]["tema"] not in TEMAS:
        dados["config"]["tema"] = "claro"
    for d in dados["datas"]:
        d.setdefault("materia_id", "")
    sincronizar_grade(dados)
    return dados


def mtime_dados():
    try:
        return DATA_FILE.stat().st_mtime_ns
    except OSError:
        return None


def ler_se_valido():
    """Lê o arquivo sem nenhuma recuperação (usado para recarregar mudanças vindas de sincronização)."""
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            dados = json.load(f)
        return normalizar(dados) if isinstance(dados, dict) else None
    except (OSError, ValueError):
        return None


def salvar(dados):
    """Grava de forma atômica (arquivo temporário + replace) e mantém um .bak da versão anterior."""
    sincronizar_grade(dados)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, encoding="utf-8") as f:
                json.load(f)  # só vira backup se for um arquivo válido
            shutil.copy2(DATA_FILE, DATA_FILE.with_suffix(".json.bak"))
        except (OSError, ValueError):
            pass
    os.replace(tmp, DATA_FILE)


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
    """Aceita 8, 08, 8h, 8h30, 8:30, 8.30, 0830, 830, 13H, '13 30'."""
    s = s.strip().lower().replace("h", ":").replace(".", ":").replace(" ", ":").rstrip(":")
    if s.isdigit():
        if len(s) <= 2:
            s += ":00"
        elif len(s) in (3, 4):
            s = s[:-2] + ":" + s[-2:]
    return datetime.strptime(s, "%H:%M").strftime("%H:%M")


def parse_data(s):
    """Aceita 25/12/2026, 25/12/26, 25-12-2026, 25.12.2026 e 25/12 (próxima ocorrência)."""
    partes = [p for p in re.split(r"[/\-. ]+", s.strip()) if p]
    if len(partes) == 2:
        d, m = map(int, partes)
        hoje = date.today()
        alvo = date(hoje.year, m, d)
        if alvo < hoje:
            alvo = date(hoje.year + 1, m, d)
        return alvo.isoformat()
    if len(partes) != 3:
        raise ValueError("data inválida")
    d, m, a = map(int, partes)
    if a < 100:
        a += 2000
    return date(a, m, d).isoformat()


def para_min(hhmm):
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


def inicio_em(tarefa, dia):
    """datetime de início da tarefa no dia (date) informado, ou None."""
    h, m = map(int, tarefa["hora"].split(":"))
    if tarefa.get("data"):
        if datetime.strptime(tarefa["data"], "%Y-%m-%d").date() != dia:
            return None
    elif dia.weekday() not in tarefa.get("dias", []):
        return None
    if tarefa.get("aula") and not tem_aula(dia):
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


# ----------------------------------------------------------------- acadêmico: faltas, notas, revisões
def fmt_nota(v):
    """7.5 -> '7,5'; 8.0 -> '8'"""
    if v is None:
        return "—"
    v = round(float(v), 2)
    txt = f"{v:.2f}".rstrip("0").rstrip(".")
    return txt.replace(".", ",")


def ler_numero(txt):
    return float(txt.strip().replace(",", "."))


def aulas_previstas(m):
    """Quantas aulas a matéria terá no semestre (precisa das datas do semestre)."""
    ini, fim = CALENDARIO["inicio"], CALENDARIO["fim"]
    if not ini or not fim or fim < ini:
        return None
    total = 0
    d = ini
    while d <= fim:
        if tem_aula(d):
            total += sum(1 for h in m.get("horarios", []) if d.weekday() in h.get("dias", []))
        d += timedelta(days=1)
    return total


def limite_faltas(m, cfg):
    """Máximo de faltas permitido: valor da matéria ou % das aulas previstas. None se não der para saber."""
    if int(m.get("max_faltas") or 0) > 0:
        return int(m["max_faltas"])
    previstas = aulas_previstas(m)
    if not previstas:
        return None
    return int(previstas * float(cfg.get("limite_faltas_pct", 25)) / 100)


def situacao_faltas(m, cfg):
    """(faltas, limite|None, nível 'ok'|'atencao'|'estourou')"""
    n = len(m.get("faltas", []))
    lim = limite_faltas(m, cfg)
    if lim is None:
        return n, None, "ok"
    if n > lim:
        return n, lim, "estourou"
    if n >= lim * 0.75 or lim - n <= 1:
        return n, lim, "atencao"
    return n, lim, "ok"


def situacao_notas(m, cfg):
    """
    Média ponderada e quanto falta. Retorna dict ou None se não houver avaliações:
      media     - média das avaliações já feitas (ponderada)
      final     - média final se todas tiverem nota, senão None
      precisa   - nota média necessária nas avaliações que faltam para atingir a média de aprovação
      pendentes - nomes das avaliações sem nota
    """
    avs = [a for a in m.get("avaliacoes", []) if float(a.get("peso") or 0) > 0]
    if not avs:
        return None
    alvo = float(cfg.get("media_aprovacao", 7))
    feitas = [a for a in avs if a.get("nota") is not None]
    falta = [a for a in avs if a.get("nota") is None]
    p_total = sum(float(a["peso"]) for a in avs)
    p_feito = sum(float(a["peso"]) for a in feitas)
    soma = sum(float(a["nota"]) * float(a["peso"]) for a in feitas)
    media = soma / p_feito if p_feito else None
    precisa = None
    if falta:
        precisa = (alvo * p_total - soma) / (p_total - p_feito)
    return {
        "media": media,
        "final": soma / p_total if not falta else None,
        "precisa": precisa,
        "pendentes": [a["nome"] for a in falta],
        "alvo": alvo,
        "nota_max": float(cfg.get("nota_max", 10)),
    }


def texto_notas(sit):
    """Frase curta sobre a situação das notas."""
    if sit is None:
        return ""
    if sit["final"] is not None:
        passou = sit["final"] >= sit["alvo"] - 1e-9
        return f"Média final {fmt_nota(sit['final'])} · {'aprovado' if passou else 'abaixo da média'}"
    prox = sit["pendentes"][0] + (f" (+{len(sit['pendentes']) - 1})" if len(sit["pendentes"]) > 1 else "")
    base = f"Média {fmt_nota(sit['media'])} · " if sit["media"] is not None else ""
    if sit["precisa"] <= 0:
        return base + "média já garantida"
    if sit["precisa"] > sit["nota_max"] + 1e-9:
        return base + f"precisaria de {fmt_nota(sit['precisa'])} em {prox} (acima do máximo)"
    return base + f"precisa de {fmt_nota(sit['precisa'])} em {prox}"


def revisoes_devidas(dados, hoje=None):
    """Conteúdos concluídos cuja próxima revisão já venceu: [(materia, item, numero_da_revisao, dias_atraso)]"""
    hoje = hoje or date.today()
    passos = [int(x) for x in dados["config"].get("revisoes_dias", [1, 7, 30]) if int(x) > 0]
    saida = []
    for m in dados.get("materias", []):
        for item in m.get("conteudos", []):
            if not item.get("feito") or not item.get("feito_em"):
                continue
            n = int(item.get("revisoes", 0))
            if n >= len(passos):
                continue
            base = iso_ou_none(item.get("revisado_em")) or iso_ou_none(item["feito_em"])
            if not base:
                continue
            vence = base + timedelta(days=passos[n])
            if vence <= hoje:
                saida.append((m, item, n + 1, (hoje - vence).days))
    saida.sort(key=lambda r: -r[3])
    return saida


def parse_avaliacoes(texto):
    """Linhas 'Nome | peso | nota'. Peso padrão 1; nota opcional. Retorna (lista, erro)."""
    saida = []
    for n, ln in enumerate(texto.splitlines(), start=1):
        if not ln.strip():
            continue
        partes = [p.strip() for p in ln.split("|")]
        nome = partes[0]
        if not nome:
            return None, f"Avaliações, linha {n}: falta o nome."
        try:
            peso = ler_numero(partes[1]) if len(partes) > 1 and partes[1] else 1.0
            nota = ler_numero(partes[2]) if len(partes) > 2 and partes[2] else None
        except ValueError:
            return None, f"Avaliações, linha {n}: use números em peso e nota (ex.: P1 | 2 | 7,5)."
        if peso <= 0:
            return None, f"Avaliações, linha {n}: o peso precisa ser maior que zero."
        saida.append({"nome": nome, "peso": peso, "nota": nota})
    return saida, None


def parse_feriados(texto):
    """Linhas 'DD/MM[/AAAA] Nome' ou 'DD/MM[/AAAA] a DD/MM[/AAAA] Nome'. Retorna (lista, erro)."""
    data_re = r"\d{1,2}[/.-]\d{1,2}(?:[/.]\d{2,4}|-\d{4})?"  # ano com '-' só se tiver 4 dígitos
    padrao = re.compile(rf"^\s*({data_re})(?:\s*(?:a|até|-|–)\s*({data_re}))?\s*(.*)$")
    saida = []
    for n, ln in enumerate(texto.splitlines(), start=1):
        if not ln.strip():
            continue
        mt = padrao.match(ln)
        if not mt:
            return None, f"Feriados, linha {n}: comece com a data (ex.: 15/11 Proclamação)."
        try:
            ini = parse_data_absoluta(mt.group(1))
            fim = parse_data_absoluta(mt.group(2)) if mt.group(2) else ini
        except ValueError:
            return None, f"Feriados, linha {n}: data inválida."
        if fim < ini:
            return None, f"Feriados, linha {n}: o fim vem antes do início."
        saida.append({"inicio": ini, "fim": fim, "nome": mt.group(3).strip()})
    saida.sort(key=lambda f: f["inicio"])
    return saida, None


def parse_data_absoluta(s):
    """Como parse_data, mas 'DD/MM' sem ano significa este ano (útil para feriados)."""
    partes = [p for p in re.split(r"[/\-. ]+", s.strip()) if p]
    if len(partes) == 2:
        return date(date.today().year, int(partes[1]), int(partes[0])).isoformat()
    return parse_data(s)


def fmt_feriados(lista):
    linhas = []
    for f in lista:
        ini = iso_para_br(f["inicio"])
        txt = ini if f["fim"] == f["inicio"] else f"{ini} a {iso_para_br(f['fim'])}"
        linhas.append(f"{txt} {f.get('nome', '')}".strip())
    return "\n".join(linhas)


def inicio_semana(d):
    return d - timedelta(days=d.weekday())


# ----------------------------------------------------------------- exportar .ics (Google Agenda etc.)
BYDAY = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


def _ics_txt(s):
    return (s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
             .replace("\n", "\\n"))


def _ics_dobrar(linha):
    """Quebra linhas com mais de 75 bytes, como manda o padrão iCalendar."""
    b = linha.encode("utf-8")
    if len(b) <= 75:
        return [linha]
    partes, atual = [], b""
    for ch in linha:
        cb = ch.encode("utf-8")
        if len(atual) + len(cb) > (75 if not partes else 74):
            partes.append(atual.decode("utf-8"))
            atual = b""
        atual += cb
    partes.append(atual.decode("utf-8"))
    return [partes[0]] + [" " + p for p in partes[1:]]


def gerar_ics(dados):
    cfg = dados["config"]
    ant = int(cfg.get("antecedencia_min", 60))
    agora = datetime.now().strftime("%Y%m%dT%H%M%S")
    hoje = date.today()
    ev = []

    def alarme(gatilho, txt):
        return ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_ics_txt(txt)}",
                f"TRIGGER:{gatilho}", "END:VALARM"]

    def dt(d, hhmm):
        return f"{d:%Y%m%d}T{hhmm.replace(':', '')}00"

    mats = {m["id"]: m for m in dados.get("materias", [])}
    for x in dados["tarefas"]:
        nome = x["nome"]
        desc = ""
        mat = mats.get(x.get("materia_id"))
        if mat:
            desc = " · ".join(p for p in (mat.get("local", ""), "Aula") if p)
        linhas = ["BEGIN:VEVENT", f"UID:{x['id']}@lembretes", f"DTSTAMP:{agora}",
                  f"SUMMARY:{_ics_txt(nome)}"]
        if desc:
            linhas.append(f"DESCRIPTION:{_ics_txt(desc)}")
        if mat and mat.get("local"):
            linhas.append(f"LOCATION:{_ics_txt(mat['local'])}")
        if x.get("data"):
            d = iso_ou_none(x["data"])
            if not d:
                continue
            primeiro = d
            linhas.append(f"DTSTART:{dt(d, x['hora'])}")
            if x.get("fim"):
                linhas.append(f"DTEND:{dt(d, x['fim'])}")
        else:
            if not x.get("dias"):
                continue
            base = hoje
            if x.get("aula") and CALENDARIO["inicio"] and CALENDARIO["inicio"] > hoje:
                base = CALENDARIO["inicio"]
            # primeira ocorrência a partir da base
            primeiro = min(base + timedelta(days=(wd - base.weekday()) % 7) for wd in x["dias"])
            linhas.append(f"DTSTART:{dt(primeiro, x['hora'])}")
            if x.get("fim"):
                linhas.append(f"DTEND:{dt(primeiro, x['fim'])}")
            regra = "RRULE:FREQ=WEEKLY;BYDAY=" + ",".join(BYDAY[d] for d in sorted(x["dias"]))
            if x.get("aula") and CALENDARIO["fim"]:
                regra += f";UNTIL={CALENDARIO['fim']:%Y%m%d}T235959"
            linhas.append(regra)
            if x.get("aula"):
                for f in sorted(CALENDARIO["feriados"]):
                    if f >= primeiro and f.weekday() in x["dias"]:
                        linhas.append(f"EXDATE:{dt(f, x['hora'])}")
        linhas += alarme(f"-PT{ant}M", nome) + ["END:VEVENT"]
        ev.append(linhas)

    for d in dados["datas"]:
        dia = iso_ou_none(d["data"])
        if not dia:
            continue
        mat = mats.get(d.get("materia_id"))
        nome = f"{d['nome']} ({mat['nome']})" if mat else d["nome"]
        ev.append(["BEGIN:VEVENT", f"UID:data_{d['id']}@lembretes", f"DTSTAMP:{agora}",
                   f"SUMMARY:{_ics_txt(nome)}", f"DTSTART;VALUE=DATE:{dia:%Y%m%d}",
                   f"DTEND;VALUE=DATE:{dia + timedelta(days=1):%Y%m%d}", "TRANSP:TRANSPARENT"]
                  + alarme("-P1D", f"Amanhã: {nome}") + ["END:VEVENT"])

    saida = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//lembretes//PT-BR//", "CALSCALE:GREGORIAN",
             "X-WR-CALNAME:Lembretes"]
    for linhas in ev:
        saida += linhas
    saida.append("END:VCALENDAR")
    return "\r\n".join(l for linha in saida for l in _ics_dobrar(linha)) + "\r\n"


# ----------------------------------------------------------------- notificações do sistema
_PS_TOAST = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$tpl = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$t = $tpl.GetElementsByTagName('text')
$t.Item(0).AppendChild($tpl.CreateTextNode($env:LEMBRETES_TITULO)) > $null
$t.Item(1).AppendChild($tpl.CreateTextNode($env:LEMBRETES_CORPO)) > $null
$id = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($id).Show([Windows.UI.Notifications.ToastNotification]::new($tpl))
"""


def notificar_sistema(titulo, corpo):
    """Notificação nativa: notify-send no Linux, toast do Windows 10/11 via PowerShell (sem instalar nada)."""
    try:
        if IS_WIN:
            env = dict(os.environ, LEMBRETES_TITULO=titulo, LEMBRETES_CORPO=corpo[:250])
            subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                              "-Command", _PS_TOAST], env=env, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, creationflags=0x08000000)  # CREATE_NO_WINDOW
        elif shutil.which("notify-send"):
            subprocess.Popen(["notify-send", "-u", "critical", "-a", "Lembretes", titulo, corpo],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def arquivo_autostart():
    if IS_WIN:
        pasta = Path(os.environ.get("APPDATA", Path.home())) / "Microsoft/Windows/Start Menu/Programs/Startup"
        return pasta / "lembretes.bat"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart/lembretes.desktop"


def instalar_autostart():
    script = os.path.abspath(__file__)
    destino = arquivo_autostart()
    destino.parent.mkdir(parents=True, exist_ok=True)
    if IS_WIN:
        exe = Path(sys.executable)
        pythonw = exe.with_name("pythonw.exe")
        if not pythonw.exists():
            pythonw = exe
        # chcp 65001 faz o cmd ler o resto do .bat como UTF-8 (pastas com acento, ex.: C:\Users\João)
        destino.write_text(f'@echo off\r\nchcp 65001 >nul\r\nstart "" "{pythonw}" "{script}" --auto\r\n',
                           encoding="utf-8")
    else:
        esc = lambda p: p.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
        destino.write_text(
            "[Desktop Entry]\nType=Application\nName=Lembretes\nComment=Avisos de atividades e aulas\n"
            f'Exec="{esc(sys.executable)}" "{esc(script)}" --auto\n'
            "X-GNOME-Autostart-enabled=true\nTerminal=false\n",
            encoding="utf-8",
        )
    return destino


def remover_autostart():
    destino = arquivo_autostart()
    if destino.exists():
        destino.unlink()
    return destino


def abrir_pasta(caminho):
    try:
        if IS_WIN:
            os.startfile(str(caminho))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(caminho)])
        else:
            subprocess.Popen(["xdg-open", str(caminho)])
    except OSError:
        pass


# ----------------------------------------------------------------- instância única
def avisar_instancia_aberta():
    """Se já houver um Lembretes rodando, pede para ele mostrar a janela e retorna True."""
    try:
        with socket.create_connection(("127.0.0.1", PORTA_INSTANCIA), timeout=2) as s:
            s.sendall(SENHA_INSTANCIA)
            s.settimeout(2)
            return s.recv(32) == b"ok"
    except OSError:
        return False


def abrir_servidor_instancia():
    try:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if not IS_WIN:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", PORTA_INSTANCIA))
        srv.listen(4)
        srv.setblocking(False)
        return srv
    except OSError:
        return None


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
        ("estudo", "Estudo"),
        ("datas", "Datas importantes"),
        ("ajustes", "Ajustes"),
    ]

    def __init__(self, root, auto=False, servidor=None):
        self.root = root
        self.dados = carregar()
        self.popups = {}
        self.avisados = set()
        self.view = "hoje"
        self.rol = None
        self._w = 0
        self._min = None
        self._agendado = None
        self._geo_agendado = None
        self.servidor = servidor
        self.dia_resumo = date.today()
        self.timer = None              # pomodoro em andamento
        self._tick = None
        self.estudo_materia = ""       # matéria escolhida na tela Estudo
        self.lbl_relogio = None
        self.lbl_fase = None

        root.title("Lembretes")
        geo = ler_local().get("geometria") or self.dados["config"].get("geometria", "")
        root.geometry(geo if re.fullmatch(r"\d+x\d+[+-]-?\d+[+-]-?\d+", geo or "") else "1280x820")
        root.minsize(1000, 640)
        root.protocol("WM_DELETE_WINDOW", self.ao_fechar)

        self.fontes()
        self.aplicar_tema()
        root.bind("<Configure>", self.ao_redimensionar)
        for ev in ("<Button-4>", "<Button-5>", "<MouseWheel>"):
            root.bind_all(ev, self.roda)
        self.atalhos()

        self.montar()
        self.render()
        agora = datetime.now()
        if self.dados["config"].get("resumo_ao_iniciar", True) or AVISO_CARGA:
            self.mostrar_resumo(agora)
        if auto:
            root.iconify()
        root.after(2000, self.checar)
        self.fila = queue.Queue()      # pedidos vindos de outras threads (ícone da bandeja)
        self.icone = None
        self.bandeja_ok = False
        self.mtime = mtime_dados()
        if self.dados["config"].get("bandeja", True):
            self.iniciar_bandeja()
        root.after(400, self.loop_eventos)

    # ------------------------------------------------------------ janela / sistema
    def atalhos(self):
        r = self.root
        for i, (chave, _) in enumerate(self.NAV, start=1):
            r.bind(f"<Control-Key-{i}>", lambda e, k=chave: self.ir(k))
        r.bind("<Control-n>", lambda e: self.novo_conforme_tela())
        r.bind("<Control-N>", lambda e: self.novo_conforme_tela())
        r.bind("<Control-q>", lambda e: self.encerrar())
        r.bind("<F5>", lambda e: self.render(conservar=True))

    def novo_conforme_tela(self):
        if self.view in ("academico", "estudo"):
            self.dialogo_materia()
        elif self.view == "datas":
            self.dialogo_data()
        else:
            self.dialogo_tarefa()

    def ao_fechar(self):
        self.guardar_geometria()
        if self.bandeja_ok:
            self.root.withdraw()  # some da barra de tarefas; volta pelo ícone perto do relógio
            if not getattr(self, "_avisou_bandeja", False):
                self._avisou_bandeja = True
                notificar_sistema("Lembretes continua rodando",
                                  "Clique no ícone perto do relógio (ou abra o app de novo) para ver a janela.")
        elif self.dados["config"].get("fechar_minimiza", True):
            self.root.iconify()  # continua avisando; abrir o app de novo traz a janela de volta
        else:
            self.encerrar()

    def encerrar(self):
        self.guardar_geometria()
        if self.timer and self.timer["fase"] == "foco":
            self.timer_parar()  # não perde o tempo estudado
        self.parar_bandeja()
        if self.servidor is not None:
            try:
                self.servidor.close()
            except OSError:
                pass
        self.root.destroy()

    def guardar_geometria(self):
        try:
            if self.root.state() != "normal":
                return
            geo = self.root.geometry()
        except tk.TclError:
            return
        info = ler_local()
        if geo != info.get("geometria"):
            info["geometria"] = geo  # fica só neste computador (não vai para a pasta sincronizada)
            try:
                gravar_local(info)
            except OSError:
                pass

    def trazer_janela(self):
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(300, lambda: self.root.attributes("-topmost", False))
        try:
            self.root.focus_force()
        except tk.TclError:
            pass

    def loop_eventos(self):
        """Roda a cada 400 ms: atende outra cópia do app que foi aberta e os cliques no ícone da bandeja."""
        if self.servidor is not None:
            try:
                while True:
                    con, _ = self.servidor.accept()
                    with con:
                        con.settimeout(0.5)
                        try:
                            if con.recv(64) == SENHA_INSTANCIA:
                                con.sendall(b"ok")
                                self.trazer_janela()
                        except OSError:
                            pass
            except (BlockingIOError, InterruptedError):
                pass
            except OSError:
                self.servidor = None
        try:
            while True:
                pedido = self.fila.get_nowait()
                if pedido == "mostrar":
                    self.trazer_janela()
                elif pedido == "encerrar":
                    self.encerrar()
                    return
                elif pedido == "pronto":
                    self.bandeja_ok = True
        except queue.Empty:
            pass
        self.root.after(400, self.loop_eventos)

    # ------------------------------------------------------------ bandeja do sistema (opcional)
    def imagem_icone(self):
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        dr = ImageDraw.Draw(img)
        cor = TEMAS["claro"]["destaque"]
        dr.rounded_rectangle((6, 6, 58, 58), radius=12, fill=cor)
        dr.rectangle((20, 18, 26, 46), fill="white")
        dr.rectangle((20, 40, 44, 46), fill="white")
        return img

    def iniciar_bandeja(self):
        if not TEM_BANDEJA or self.icone is not None:
            return
        fila = self.fila

        def pronto(icone):
            try:
                icone.visible = True
            except Exception:
                return
            # no backend X11 dá para saber se existe bandeja de verdade; sem ela, nada de esconder a janela
            if getattr(icone, "_systray_manager", True) is None or \
                    (hasattr(icone, "_systray_manager") and not icone._systray_manager):
                return
            fila.put("pronto")

        try:
            menu = pystray.Menu(
                pystray.MenuItem("Abrir Lembretes", lambda: fila.put("mostrar"), default=True),
                pystray.MenuItem("Encerrar", lambda: fila.put("encerrar")),
            )
            self.icone = pystray.Icon("lembretes", self.imagem_icone(), "Lembretes", menu)
            threading.Thread(target=lambda: self._rodar_icone(pronto), daemon=True).start()
        except Exception:
            self.icone = None

    def _rodar_icone(self, pronto):
        try:
            self.icone.run(setup=pronto)
        except Exception:
            self.bandeja_ok = False

    def parar_bandeja(self):
        if self.icone is not None:
            try:
                self.icone.stop()
            except Exception:
                pass
        self.icone = None
        self.bandeja_ok = False

    def salvar_seguro(self):
        try:
            salvar(self.dados)
            self.mtime = mtime_dados()
            return True
        except OSError as e:
            self.alerta("Erro ao salvar", [("!", f"Não foi possível gravar {DATA_FILE}: {e}")], slot="erro")
            return False

    def mostrar_resumo(self, agora):
        global AVISO_CARGA
        itens = self.itens_resumo(agora)
        if AVISO_CARGA:
            itens = [("!", AVISO_CARGA)] + itens
            AVISO_CARGA = ""
        self.alerta(f"{self.saudacao(agora)} · resumo", itens, slot="resumo", adiar=False)

    # ------------------------------------------------------------ base visual
    def fontes(self):
        disp = set(tkfont.families())

        def escolher(opcoes, padrao):
            for f in opcoes:
                if f in disp:
                    return f
            return padrao

        sans, serif = escolher(SANS, "Helvetica"), escolher(SERIF, "Times")
        mono = escolher(MONO, "Courier")
        self.fonte_mono = mono
        self.F = {
            "h1": (serif, 34), "h2": (serif, 20, "bold"), "h3": (serif, 15, "bold"),
            "num": (mono, 32), "hora": (mono, 19, "bold"), "alerta": (mono, 20, "bold"),
            "marca": (serif, 18, "bold"), "relogio": (mono, 58),
            "mono": (mono, 11), "mono_b": (mono, 11, "bold"), "mono_mini": (mono, 9, "bold"),
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

        self.lbl_timer_lat = tk.Label(lado, text="", font=F["mono_b"], bg=t["lateral"], fg=t["destaque"],
                                      cursor="hand2", anchor="w", justify="left")
        self.lbl_timer_lat.pack(anchor="w", padx=24, pady=(24, 0))
        self.lbl_timer_lat.bind("<Button-1>", lambda e: self.ir("estudo"))
        self.atualizar_timer_ui()

        sair = tk.Label(lado, text="Encerrar aplicativo", font=F["mini"], bg=t["lateral"],
                        fg=t["suave"], cursor="hand2")
        sair.pack(side="bottom", anchor="w", padx=24, pady=24)
        sair.bind("<Button-1>", lambda e: self.encerrar())
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
        if e.widget is not self.root:
            return
        if self._geo_agendado:
            self.root.after_cancel(self._geo_agendado)
        self._geo_agendado = self.root.after(1500, self.guardar_geometria)
        mudou_altura = self.view == "semana" and abs(e.height - getattr(self, "_h", 0)) >= 8
        if abs(e.width - self._w) < 8 and not mudou_altura:
            return
        self._w = e.width
        self._h = e.height
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
            tk.Label(c, text=f"até {x['fim']}", font=F["mono_mini"], bg=t["card"],
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
        mat = self.materia_por_id(d.get("materia_id"))
        if mat:
            tk.Label(c, text=corta(mat["nome"], 24), font=F["mini_b"], bg=t["card"],
                     fg=t["suave"] if n < 0 else cor_da(mat["nome"])).pack(anchor="w")
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

        self.secao_revisoes(p)

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
            item = lista[idx]
            item["feito"] = not item.get("feito", False)
            if item["feito"]:
                # começa o ciclo de revisões a partir de hoje
                item["feito_em"] = date.today().isoformat()
                item["revisoes"] = 0
                item.pop("revisado_em", None)
            else:
                for k in ("feito_em", "revisoes", "revisado_em"):
                    item.pop(k, None)
            self.salvar_seguro()
            self.render(conservar=True)

    def marcar_revisado(self, item):
        item["revisoes"] = int(item.get("revisoes", 0)) + 1
        item["revisado_em"] = date.today().isoformat()
        self.salvar_seguro()
        self.render(conservar=True)

    def registrar_falta(self, m):
        m.setdefault("faltas", []).append(date.today().isoformat())
        self.salvar_seguro()
        n, lim, nivel = situacao_faltas(m, self.dados["config"])
        if nivel != "ok" and lim is not None:
            sobra = lim - n
            msg = (f"Você passou do limite de faltas ({n} de {lim})." if sobra < 0 else
                   "Esta foi a última falta permitida." if sobra == 0 else
                   f"Restam só {sobra} falta{'s' if sobra != 1 else ''} ({n} de {lim}).")
            self.alerta(f"Faltas · {m['nome']}", [("!", msg)], slot="faltas", adiar=False)
        self.render(conservar=True)

    def desfazer_falta(self, m):
        if m.get("faltas"):
            m["faltas"].pop()
            self.salvar_seguro()
            self.render(conservar=True)

    def entregas_da_materia(self, m, so_futuras=True):
        lista = [d for d in self.dados["datas"] if d.get("materia_id") == m["id"]]
        if so_futuras:
            lista = [d for d in lista if dias_ate(d) >= 0]
        return sorted(lista, key=lambda d: d["data"])

    def materia_por_id(self, mid):
        for m in self.dados.get("materias", []):
            if m["id"] == mid:
                return m
        return None

    def texto_faltas(self, m):
        n, lim, nivel = situacao_faltas(m, self.dados["config"])
        if lim is None:
            return f"{n} falta{'s' if n != 1 else ''}", nivel
        if nivel == "estourou":
            return f"{n}/{lim} faltas · passou do limite", nivel
        sobra = lim - n
        return f"{n}/{lim} faltas · pode faltar mais {sobra}", nivel

    def cor_nivel(self, nivel):
        return self.t["destaque"] if nivel in ("atencao", "estourou") else self.t["suave"]

    def bloco_materia_resumo(self, parent, m):
        """Cartão compacto de matéria para a tela Hoje."""
        t, F = self.t, self.F
        b = Bloco(parent, t, LARG_MAT, cor_da(m["nome"]), altura=168)
        c = b.corpo
        tk.Label(c, text=corta(m["nome"], 34), font=F["h3"], bg=t["card"], fg=t["tinta"]).pack(anchor="w")
        tk.Label(c, text=corta(self.fmt_horarios_lista(m.get("horarios", [])), 52), font=F["mini_b"],
                 bg=t["card"], fg=t["suave"]).pack(anchor="w", pady=(2, 6))
        res = self.resumo_materia(m)
        if res:
            tk.Label(c, text=f"Em aula: {corta(res, 42)}", font=F["corpo_b"], bg=t["card"],
                     fg=t["destaque"]).pack(anchor="w")
        else:
            tk.Label(c, text="Clique para definir o conteúdo atual", font=F["mini"], bg=t["card"],
                     fg=t["suave"]).pack(anchor="w")
        rodape = tk.Frame(c, bg=t["card"])
        rodape.pack(side="bottom", fill="x")
        txt_f, nivel = self.texto_faltas(m)
        tk.Label(rodape, text=txt_f, font=F["mini_b"], bg=t["card"],
                 fg=self.cor_nivel(nivel)).pack(anchor="w")
        notas = texto_notas(situacao_notas(m, self.dados["config"]))
        prox = self.entregas_da_materia(m)
        extra = notas or (f"Próxima: {prox[0]['nome']} em {dias_ate(prox[0])} dia(s)" if prox else "")
        if extra:
            tk.Label(rodape, text=corta(extra, 56), font=F["mini"], bg=t["card"],
                     fg=t["suave"]).pack(anchor="w")
        self.bloco_clicavel(b, lambda: self.dialogo_materia(m))
        return b

    def mini_botao(self, parent, texto, cmd, cor=None):
        t, F = self.t, self.F
        b = tk.Label(parent, text=texto, font=F["mini_b"], bg=t["bg"], fg=cor or t["tinta"],
                     padx=8, pady=3, cursor="hand2", highlightthickness=1, highlightbackground=t["linha"])
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.configure(highlightbackground=t["destaque"]))
        b.bind("<Leave>", lambda e: b.configure(highlightbackground=t["linha"]))
        return b

    def painel_materia(self, corpo, m, largura):
        """Três quadros: faltas, notas e próxima entrega."""
        t, F = self.t, self.F
        cfg = self.dados["config"]
        painel = tk.Frame(corpo, bg=t["card"])
        painel.pack(fill="x", pady=(0, 14))
        for col in range(3):
            painel.grid_columnconfigure(col, weight=1, uniform="painel")

        def quadro(col, rotulo):
            q = tk.Frame(painel, bg=t["bg"], highlightthickness=1, highlightbackground=t["linha"])
            q.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 6, 0))
            dentro = tk.Frame(q, bg=t["bg"])
            dentro.pack(fill="both", expand=True, padx=12, pady=10)
            tk.Label(dentro, text=rotulo, font=F["rotulo"], bg=t["bg"], fg=t["suave"]).pack(anchor="w")
            return dentro

        larg_q = max(120, (largura - 44) // 3 - 30)

        # faltas
        q = quadro(0, "FALTAS")
        n, lim, nivel = situacao_faltas(m, cfg)
        cor = self.cor_nivel(nivel) if nivel != "ok" else t["tinta"]
        tk.Label(q, text=f"{n}" + (f" / {lim}" if lim is not None else ""), font=F["hora"],
                 bg=t["bg"], fg=cor).pack(anchor="w")
        if lim is None:
            dica = "Defina o semestre em Ajustes ou o máximo na matéria"
        elif nivel == "estourou":
            dica = "Passou do limite"
        else:
            dica = f"Pode faltar mais {lim - n}"
        tk.Label(q, text=dica, font=F["mini"], bg=t["bg"], fg=cor if nivel != "ok" else t["suave"],
                 wraplength=larg_q, justify="left").pack(anchor="w")
        bts = tk.Frame(q, bg=t["bg"])
        bts.pack(anchor="w", pady=(6, 0))
        self.mini_botao(bts, "+ faltei hoje", lambda: self.registrar_falta(m), t["destaque"]).pack(side="left")
        if m.get("faltas"):
            self.mini_botao(bts, "desfazer", lambda: self.desfazer_falta(m)).pack(side="left", padx=(6, 0))

        # notas
        q = quadro(1, "NOTAS")
        sit = situacao_notas(m, cfg)
        if sit is None:
            tk.Label(q, text="—", font=F["hora"], bg=t["bg"], fg=t["suave"]).pack(anchor="w")
            tk.Label(q, text="Cadastre as avaliações em Editar", font=F["mini"], bg=t["bg"],
                     fg=t["suave"], wraplength=larg_q, justify="left").pack(anchor="w")
        else:
            media = sit["final"] if sit["final"] is not None else sit["media"]
            abaixo = media is not None and media < sit["alvo"]
            tk.Label(q, text=fmt_nota(media), font=F["hora"], bg=t["bg"],
                     fg=t["destaque"] if abaixo else t["ok"] if media is not None else t["suave"]).pack(anchor="w")
            if sit["final"] is not None:
                dica = "Média final · " + ("aprovado" if not abaixo else "abaixo da média")
            elif sit["precisa"] <= 0:
                dica = "Média já garantida"
            else:
                prox = sit["pendentes"][0]
                dica = f"Precisa de {fmt_nota(sit['precisa'])} em {prox}"
                if len(sit["pendentes"]) > 1:
                    dica += f" e nas outras {len(sit['pendentes']) - 1}"
                if sit["precisa"] > sit["nota_max"]:
                    dica += " (acima do máximo)"
            tk.Label(q, text=dica, font=F["mini"], bg=t["bg"],
                     fg=t["destaque"] if sit["precisa"] and sit["precisa"] > sit["nota_max"] else t["suave"],
                     wraplength=larg_q, justify="left").pack(anchor="w")

        # próxima entrega
        q = quadro(2, "PRÓXIMA ENTREGA")
        prox = self.entregas_da_materia(m)
        if prox:
            d = prox[0]
            n_d = dias_ate(d)
            tk.Label(q, text="Hoje" if n_d == 0 else f"{n_d} dia{'s' if n_d != 1 else ''}", font=F["hora"],
                     bg=t["bg"], fg=t["destaque"] if n_d <= 7 else t["tinta"]).pack(anchor="w")
            tk.Label(q, text=f"{d['nome']} · {iso_para_br(d['data'])}", font=F["mini"], bg=t["bg"],
                     fg=t["suave"], wraplength=larg_q, justify="left").pack(anchor="w")
            if len(prox) > 1:
                tk.Label(q, text=f"+{len(prox) - 1} depois", font=F["mini"], bg=t["bg"],
                         fg=t["suave"]).pack(anchor="w")
        else:
            tk.Label(q, text="—", font=F["hora"], bg=t["bg"], fg=t["suave"]).pack(anchor="w")
            lk = tk.Label(q, text="+ adicionar prova ou trabalho", font=F["mini_b"], bg=t["bg"],
                          fg=t["destaque"], cursor="hand2")
            lk.pack(anchor="w")
            lk.bind("<Button-1>", lambda e: self.dialogo_data(pre_materia=m["id"]))

    def card_materia(self, parent, m, largura):
        """Cartão completo de matéria para a aba Acadêmico."""
        t, F = self.t, self.F
        cor = cor_da(m["nome"])
        card = tk.Frame(parent, width=largura, bg=t["card"], highlightthickness=1,
                        highlightbackground=t["linha"])
        tk.Frame(card, bg=cor, height=5).pack(side="top", fill="x")
        corpo = tk.Frame(card, bg=t["card"], width=largura - 40)
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

        self.painel_materia(corpo, m, largura)

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

        passos = [int(x) for x in self.dados["config"].get("revisoes_dias", [1, 7, 30])]
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
                               justify="left", anchor="w", wraplength=largura - 200)
                lbl.pack(side="left", padx=(10, 0), fill="x", expand=True)
                ws = [linha, box, lbl]
                if feito and item.get("feito_em") and passos:
                    n = int(item.get("revisoes", 0))
                    if n >= len(passos):
                        info = "revisões concluídas"
                    else:
                        base = iso_ou_none(item.get("revisado_em")) or iso_ou_none(item["feito_em"])
                        falta = (base + timedelta(days=passos[n]) - date.today()).days
                        info = ("revisar hoje" if falta <= 0 else
                                f"revisão {n + 1} em {falta} dia{'s' if falta != 1 else ''}")
                    rv = tk.Label(linha, text=info, font=F["mini"], bg=t["card"],
                                  fg=t["destaque"] if info == "revisar hoje" else t["suave"])
                    rv.pack(side="right")
                    ws.append(rv)
                for w in ws:
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
        cols = 2 if avail >= 1240 else 1  # o painel de faltas/notas/entrega precisa de ~600 px por card
        larg = (avail - (cols * 16)) // cols
        g = tk.Frame(p, bg=t["bg"])
        g.pack(fill="x", anchor="w")
        for col in range(cols):
            g.grid_columnconfigure(col, minsize=larg + 2, weight=1, uniform="mat")
        for i, m in enumerate(materias):
            card = self.card_materia(g, m, larg)
            card.grid(row=i // cols, column=i % cols, padx=6, pady=8, sticky="nsew")

    # ------------------------------------------------------------ timer de estudo (pomodoro)
    def timer_restante(self):
        tm = self.timer
        if not tm:
            return 0
        if tm["rodando"]:
            return max(0, (tm["fim"] - datetime.now()).total_seconds())
        return tm["restante"]

    def timer_iniciar(self, fase="foco"):
        cfg = self.dados["config"]
        minutos = int(cfg.get("pomodoro_min", 25) if fase == "foco" else cfg.get("pausa_min", 5))
        total = max(1, minutos) * 60
        self.timer = {"fase": fase, "materia_id": self.estudo_materia, "total": total,
                      "fim": datetime.now() + timedelta(seconds=total), "restante": total, "rodando": True}
        self.agendar_tick()
        self.render(conservar=True)

    def timer_pausar(self):
        if self.timer and self.timer["rodando"]:
            self.timer["restante"] = self.timer_restante()
            self.timer["rodando"] = False
            self.render(conservar=True)

    def timer_continuar(self):
        if self.timer and not self.timer["rodando"]:
            self.timer["fim"] = datetime.now() + timedelta(seconds=self.timer["restante"])
            self.timer["rodando"] = True
            self.agendar_tick()
            self.render(conservar=True)

    def timer_parar(self):
        tm = self.timer
        if tm and tm["fase"] == "foco":
            feito = int((tm["total"] - self.timer_restante()) // 60)
            if feito >= 1:
                self.registrar_estudo(tm["materia_id"], feito)
        self.timer = None
        self.render(conservar=True)

    def registrar_estudo(self, mid, minutos):
        self.dados["estudos"].append({"materia_id": mid or "", "data": date.today().isoformat(),
                                      "min": int(minutos)})
        self.salvar_seguro()

    def agendar_tick(self):
        if self._tick:
            self.root.after_cancel(self._tick)
        self._tick = self.root.after(250, self.tick)

    def tick(self):
        self._tick = None
        tm = self.timer
        if not tm:
            self.atualizar_timer_ui()
            return
        if tm["rodando"] and self.timer_restante() <= 0:
            mat = self.materia_por_id(tm["materia_id"])
            nome = mat["nome"] if mat else "estudo geral"
            if tm["fase"] == "foco":
                self.registrar_estudo(tm["materia_id"], tm["total"] // 60)
                self.alerta("Foco concluído", [("✓", f"{fmt_min(tm['total'] // 60)} de {nome}. Hora da pausa.")],
                            slot="timer", adiar=False)
                self.timer_iniciar("pausa")
            else:
                self.timer = None
                self.alerta("Pausa terminou", [("▶", f"Bora voltar para {nome}?")], slot="timer", adiar=False)
                self.render(conservar=True)
            return
        self.atualizar_timer_ui()
        if tm["rodando"]:
            self._tick = self.root.after(1000 - datetime.now().microsecond // 1000 + 5, self.tick)

    def atualizar_timer_ui(self):
        tm = self.timer
        seg = int(math.ceil(self.timer_restante()))
        relogio = f"{seg // 60:02d}:{seg % 60:02d}"
        lat = getattr(self, "lbl_timer_lat", None)
        if lat is not None and lat.winfo_exists():
            if tm:
                mat = self.materia_por_id(tm["materia_id"])
                fase = "Foco" if tm["fase"] == "foco" else "Pausa"
                pausa = "  (pausado)" if not tm["rodando"] else ""
                lat.configure(text=f"{fase} {relogio}{pausa}\n{corta(mat['nome'], 20) if mat else 'Geral'}",
                              fg=self.t["destaque"] if tm["fase"] == "foco" else self.t["ok"])
            else:
                lat.configure(text="")
        if self.lbl_relogio is not None and self.lbl_relogio.winfo_exists():
            if not tm:
                relogio = f"{int(self.dados['config'].get('pomodoro_min', 25)):02d}:00"
            self.lbl_relogio.configure(text=relogio)

    # ------------------------------------------------------------ tela: Estudo
    def minutos_estudados(self, desde, ate=None):
        """{materia_id: minutos} entre as datas (inclusive)."""
        ate = ate or date.today()
        tot = {}
        for e in self.dados["estudos"]:
            d = iso_ou_none(e.get("data"))
            if d and desde <= d <= ate:
                tot[e.get("materia_id", "")] = tot.get(e.get("materia_id", ""), 0) + int(e.get("min", 0))
        return tot

    def view_estudo(self, p):
        t, F = self.t, self.F
        cfg = self.dados["config"]
        self.cabecalho(p, "FOCO E REVISÃO", "Estudo")
        tm = self.timer
        if tm:
            self.estudo_materia = tm["materia_id"]
        if self.estudo_materia and not self.materia_por_id(self.estudo_materia):
            self.estudo_materia = ""

        caixa = tk.Frame(p, bg=t["card"], highlightthickness=1, highlightbackground=t["linha"])
        caixa.pack(fill="x", padx=6)
        cor_lado = (cor_da(self.materia_por_id(self.estudo_materia)["nome"])
                    if self.estudo_materia else t["destaque"])
        tk.Frame(caixa, bg=cor_lado, width=8).pack(side="left", fill="y")
        dentro = tk.Frame(caixa, bg=t["card"])
        dentro.pack(side="left", fill="both", expand=True, padx=28, pady=24)

        esq = tk.Frame(dentro, bg=t["card"])
        esq.pack(side="left", fill="both", expand=True)
        tk.Label(esq, text="ESTUDAR O QUÊ?", font=F["rotulo"], bg=t["card"], fg=t["suave"]).pack(anchor="w")
        chips = tk.Frame(esq, bg=t["card"])
        chips.pack(anchor="w", pady=(8, 0), fill="x")
        opcoes = [("", "Geral")] + [(m["id"], m["nome"]) for m in self.dados.get("materias", [])]
        linha = tk.Frame(chips, bg=t["card"])
        linha.pack(anchor="w")
        larg, limite = 0, max(300, self.largura_util() - 420)
        for mid, nome in opcoes:
            on = mid == self.estudo_materia
            txt = corta(nome, 22)
            w_est = 9 * len(txt) + 34
            if larg + w_est > limite and larg:
                linha = tk.Frame(chips, bg=t["card"])
                linha.pack(anchor="w", pady=(6, 0))
                larg = 0
            lab = tk.Label(linha, text=txt, font=F["mini_b"], padx=10, pady=6,
                           cursor="arrow" if tm else "hand2", highlightthickness=1,
                           bg=t["destaque"] if on else t["bg"], fg=t["sobre"] if on else t["tinta"],
                           highlightbackground=t["destaque"] if on else t["linha"])
            lab.pack(side="left", padx=(0, 6))
            if not tm:
                lab.bind("<Button-1>", lambda e, v=mid: (setattr(self, "estudo_materia", v),
                                                         self.render(conservar=True)))
            larg += w_est
        mat = self.materia_por_id(self.estudo_materia)
        if mat:
            res = self.resumo_materia(mat)
            if res:
                tk.Label(esq, text=f"Conteúdo atual: {res}", font=F["corpo_b"], bg=t["card"],
                         fg=t["destaque"]).pack(anchor="w", pady=(14, 0))
        if tm:
            tk.Label(esq, text="Para trocar de matéria, pare o timer.", font=F["mini"], bg=t["card"],
                     fg=t["suave"]).pack(anchor="w", pady=(8, 0))
        tk.Label(esq, text=f"Foco de {cfg.get('pomodoro_min', 25)} min e pausa de {cfg.get('pausa_min', 5)} min "
                           "(muda em Ajustes). O tempo de foco fica registrado na matéria.",
                 font=F["mini"], bg=t["card"], fg=t["suave"], wraplength=max(260, self.largura_util() - 460),
                 justify="left").pack(anchor="w", pady=(10, 0))

        dir_ = tk.Frame(dentro, bg=t["card"])
        dir_.pack(side="right", padx=(24, 0))
        fase = ("FOCO" if tm["fase"] == "foco" else "PAUSA") if tm else "PRONTO PARA COMEÇAR"
        if tm and not tm["rodando"]:
            fase += " · PAUSADO"
        self.lbl_fase = tk.Label(dir_, text=fase, font=F["rotulo"], bg=t["card"],
                                 fg=t["ok"] if tm and tm["fase"] == "pausa" else t["destaque"])
        self.lbl_fase.pack(anchor="e")
        self.lbl_relogio = tk.Label(dir_, text="", font=F["relogio"], bg=t["card"], fg=t["tinta"])
        self.lbl_relogio.pack(anchor="e")
        bts = tk.Frame(dir_, bg=t["card"])
        bts.pack(anchor="e", pady=(6, 0))
        if not tm:
            self.botao(bts, "▶  Começar foco", lambda: self.timer_iniciar("foco"), fundo=t["card"]).pack(side="left")
        else:
            if tm["rodando"]:
                self.botao(bts, "Pausar", self.timer_pausar, tipo="ghost", fundo=t["card"]).pack(side="left")
            else:
                self.botao(bts, "Continuar", self.timer_continuar, fundo=t["card"]).pack(side="left")
            if tm["fase"] == "pausa":
                self.botao(bts, "Pular pausa", lambda: self.timer_iniciar("foco"), tipo="ghost",
                           fundo=t["card"]).pack(side="left", padx=(8, 0))
            self.botao(bts, "Parar", self.timer_parar, tipo="perigo", fundo=t["card"]).pack(side="left", padx=(8, 0))
        self.atualizar_timer_ui()

        # ---- semana
        hoje = date.today()
        seg = inicio_semana(hoje)
        tot = self.minutos_estudados(seg, hoje)
        total_sem = sum(tot.values())
        hoje_min = sum(self.minutos_estudados(hoje, hoje).values())
        self.secao(p, f"Esta semana · {fmt_curto(total_sem) if total_sem else '0 min'}"
                      f"  ·  hoje {fmt_curto(hoje_min) if hoje_min else '0 min'}")
        if not total_sem:
            self.vazio(p, "Nenhum estudo registrado nesta semana ainda.")
        else:
            self.grafico_semana(p, tot, seg)

        # ---- revisões
        self.secao_revisoes(p, mostrar_vazio=True)

    def grafico_semana(self, p, tot, seg):
        """Barras horizontais por matéria + colunas por dia da semana (desenhado no Canvas)."""
        t, F = self.t, self.F
        larg = self.largura_util() - 12
        linhas = sorted(tot.items(), key=lambda kv: -kv[1])
        nomes = {m["id"]: m["nome"] for m in self.dados.get("materias", [])}
        area = tk.Frame(p, bg=t["bg"])
        area.pack(fill="x", padx=6)

        larg_bar = max(320, int(larg * 0.58))
        h = 34 * len(linhas) + 8
        cv = tk.Canvas(area, width=larg_bar, height=h, bg=t["bg"], highlightthickness=0)
        cv.pack(side="left", anchor="n")
        maior = max(v for _, v in linhas)
        x0, x1 = 170, larg_bar - 90
        for i, (mid, mins) in enumerate(linhas):
            y = 4 + i * 34
            nome = nomes.get(mid, "Geral")
            cor = cor_da(nome) if mid else t["suave"]
            cv.create_text(0, y + 13, text=corta(nome, 22), anchor="w", font=F["corpo_b"], fill=t["tinta"])
            cv.create_rectangle(x0, y + 4, x1, y + 22, fill=t["card"], outline=t["linha"])
            cv.create_rectangle(x0, y + 4, x0 + max(4, (x1 - x0) * mins / maior), y + 22, fill=cor, outline="")
            cv.create_text(x1 + 10, y + 13, text=fmt_curto(mins), anchor="w", font=F["mini_b"],
                           fill=t["suave"])

        # colunas por dia
        por_dia = []
        for i in range(7):
            d = seg + timedelta(days=i)
            por_dia.append(sum(self.minutos_estudados(d, d).values()))
        larg_d = max(240, larg - larg_bar - 30)
        hd = max(h, 150)
        cd = tk.Canvas(area, width=larg_d, height=hd, bg=t["bg"], highlightthickness=0)
        cd.pack(side="right", anchor="n")
        topo = max(por_dia) or 1
        passo = larg_d / 7
        base_y = hd - 22
        hoje_i = date.today().weekday()
        for i, mins in enumerate(por_dia):
            cx = passo * i + passo / 2
            alt = (base_y - 18) * mins / topo
            cor = t["destaque"] if i == hoje_i else t["ok"]
            cd.create_rectangle(cx - passo * 0.28, base_y - max(alt, 2), cx + passo * 0.28, base_y,
                                fill=cor if mins else t["linha"], outline="")
            if mins:
                cd.create_text(cx, base_y - alt - 8, text=fmt_curto(mins).replace(" ", ""),
                               font=F["mini"], fill=t["suave"])
            cd.create_text(cx, base_y + 11, text=DIAS[i], font=F["mini_b"] if i == hoje_i else F["mini"],
                           fill=t["destaque"] if i == hoje_i else t["suave"])

    def secao_revisoes(self, p, mostrar_vazio=False):
        t, F = self.t, self.F
        rev = revisoes_devidas(self.dados)
        if not rev and not mostrar_vazio:
            return
        self.secao(p, f"Para revisar hoje · {len(rev)}" if rev else "Para revisar hoje")
        if not rev:
            passos = ", ".join(str(x) for x in self.dados["config"].get("revisoes_dias", [1, 7, 30]))
            self.vazio(p, f"Nada para revisar. Ao marcar um conteúdo como concluído no modo Acadêmico, "
                          f"ele volta aqui depois de {passos} dias.")
            return
        lista = tk.Frame(p, bg=t["bg"])
        lista.pack(fill="x", padx=6)
        total_passos = len(self.dados["config"].get("revisoes_dias", [1, 7, 30]))
        for m, item, n, atraso in rev[:12]:
            row = tk.Frame(lista, bg=t["card"], highlightthickness=1, highlightbackground=t["linha"])
            row.pack(fill="x", pady=3)
            tk.Frame(row, bg=cor_da(m["nome"]), width=5).pack(side="left", fill="y")
            txt = tk.Frame(row, bg=t["card"])
            txt.pack(side="left", fill="x", expand=True, padx=14, pady=8)
            tk.Label(txt, text=item["texto"], font=F["corpo_b"], bg=t["card"], fg=t["tinta"],
                     anchor="w").pack(anchor="w")
            info = f"{m['nome']}  ·  revisão {n} de {total_passos}"
            if atraso:
                info += f"  ·  atrasada {atraso} dia{'s' if atraso != 1 else ''}"
            tk.Label(txt, text=info, font=F["mini"], bg=t["card"], fg=t["suave"], anchor="w").pack(anchor="w")
            self.botao(row, "Revisei ✓", lambda it=item: self.marcar_revisado(it), tipo="ghost",
                       fundo=t["card"]).pack(side="right", padx=12, pady=8)
        if len(rev) > 12:
            self.vazio(p, f"+ {len(rev) - 12} outras revisões")

    # ------------------------------------------------------------ tela: Cronograma
    @staticmethod
    def choques_do_dia(itens):
        """ids dos itens (já ordenados por hora) que se sobrepõem a outro no mesmo dia."""
        ids = set()
        for a_i, a in enumerate(itens):
            a0 = para_min(a["hora"])
            a1 = para_min(a["fim"]) if a.get("fim") else a0 + 1
            for b in itens[a_i + 1:]:
                b0 = para_min(b["hora"])
                if b0 >= a1:
                    break
                ids.update((a["id"], b["id"]))
        return ids

    def view_semana(self, p):
        t, F = self.t, self.F
        self.cabecalho(p, "SEMANA", "Cronograma", ("+  Nova atividade", lambda: self.dialogo_tarefa()))
        hoje = date.today()
        seg = inicio_semana(hoje)
        dias_semana = [seg + timedelta(days=i) for i in range(7)]

        # itens de cada dia: semanais + datas únicas que caem nesta semana
        por_dia = [[] for _ in range(7)]
        for x in self.dados["tarefas"]:
            if x.get("data"):
                d = iso_ou_none(x["data"])
                if d and seg <= d <= dias_semana[-1]:
                    por_dia[d.weekday()].append(x)
            else:
                for i in x.get("dias", []):
                    por_dia[i].append(x)

        self.grade_horas(p, por_dia, dias_semana)

        unicas = sorted((x for x in self.dados["tarefas"] if x.get("data")), key=lambda x: (x["data"], x["hora"]))
        if unicas:
            self.secao(p, "Datas únicas")
            hoje_iso = hoje.isoformat()
            self.grade(p, [lambda g, x=x: self.bloco_tarefa(g, x, LADO, iso_para_br(x["data"]),
                                                            apagado=x["data"] < hoje_iso)
                           for x in unicas], lado=LADO)

    @staticmethod
    def faixas_paralelas(itens):
        """
        Distribui itens que se sobrepõem em faixas lado a lado (como na agenda do Google).
        Retorna [(item, ini_min, fim_min, faixa, total_faixas)].
        """
        evs = []
        for x in itens:
            a = para_min(x["hora"])
            b = para_min(x["fim"]) if x.get("fim") else a + 60  # sem término: mostra 1 hora
            evs.append([x, a, max(b, a + 15)])
        evs.sort(key=lambda e: (e[1], -e[2]))
        saida, grupo, fim_grupo = [], [], -1

        def fechar():
            fins = []  # fim de cada faixa
            marcados = []
            for e in grupo:
                for k, f in enumerate(fins):
                    if f <= e[1]:
                        fins[k] = e[2]
                        marcados.append((e, k))
                        break
                else:
                    fins.append(e[2])
                    marcados.append((e, len(fins) - 1))
            for e, k in marcados:
                saida.append((e[0], e[1], e[2], k, len(fins)))

        for e in evs:
            if grupo and e[1] >= fim_grupo:
                fechar()
                grupo, fim_grupo = [], -1
            grupo.append(e)
            fim_grupo = max(fim_grupo, e[2])
        if grupo:
            fechar()
        return saida

    def grade_horas(self, p, por_dia, dias_semana):
        """Cronograma em grade: cada bloco ocupa a altura proporcional à duração."""
        t, F = self.t, self.F
        hoje = date.today()
        hoje_i = hoje.weekday()
        fm = {k: tkfont.Font(font=F[k]) for k in ("mono_b", "mono_mini", "corpo_b", "mini", "rotulo", "mini_b")}

        # faixa de horas visível: do primeiro início ao último término, com folga
        todos = [x for d in por_dia for x in d]
        if todos:
            h_ini = min(para_min(x["hora"]) for x in todos) // 60
            h_fim = math.ceil(max((para_min(x["fim"]) if x.get("fim") else para_min(x["hora"]) + 60)
                                  for x in todos) / 60)
        else:
            h_ini, h_fim = 8, 18
        h_ini = max(0, h_ini - (1 if h_ini > 0 else 0))
        h_fim = min(24, max(h_fim, h_ini + 8))
        agora = datetime.now()

        TOPO = 46                                # cabeçalho com os dias
        EIXO = 54                                # coluna das horas
        LEGENDA = 40                             # texto de ajuda embaixo da grade
        # altura por hora: faz a semana inteira caber na janela, sem ficar pequeno demais para ler
        p.update_idletasks()
        janela_h = self.principal.winfo_height()
        if janela_h < 200:
            janela_h = max(self.root.winfo_height(), 600)
        livre = janela_h - 34 - p.winfo_reqheight() - TOPO - LEGENDA - 34 - 8
        PX_H = max(30, min(56, livre / (h_fim - h_ini)))
        larg = self.largura_util() - 12
        col_w = (larg - EIXO) / 7
        alt = TOPO + (h_fim - h_ini) * PX_H + 8

        def y_de(minutos):
            return TOPO + (minutos - h_ini * 60) * PX_H / 60

        cv = tk.Canvas(p, width=larg, height=alt, bg=t["bg"], highlightthickness=0, bd=0)
        cv.pack(anchor="w", padx=6)

        # fundo das colunas, cabeçalho e linhas de hora
        for i in range(7):
            x0 = EIXO + i * col_w
            eh_hoje = i == hoje_i
            cv.create_rectangle(x0 + 2, TOPO, x0 + col_w - 2, alt - 8,
                                fill=t["card"] if eh_hoje else t["lateral"], outline="", tags=("fundo",))
            d = dias_semana[i]
            cor = t["destaque"] if eh_hoje else t["suave"]
            cv.create_text(x0 + 8, 12, text=DIAS[i].upper(), anchor="w", font=F["rotulo"], fill=cor)
            cv.create_text(x0 + 8 + fm["rotulo"].measure(DIAS[i].upper()) + 8, 12,
                           text="hoje" if eh_hoje else f"{d.day:02d}/{d.month:02d}", anchor="w",
                           font=F["mini_b"] if eh_hoje else F["mini"], fill=cor)
            cv.create_line(x0 + 2, 30, x0 + col_w - 2, 30, fill=t["destaque"] if eh_hoje else t["linha"],
                           width=2)
        for h in range(h_ini, h_fim + 1):
            y = y_de(h * 60)
            cv.create_line(EIXO, y, larg, y, fill=t["linha"])
            if h < h_fim:
                cv.create_line(EIXO, y + PX_H / 2, larg, y + PX_H / 2, fill=t["linha"], dash=(1, 4))
                cv.create_text(EIXO - 10, y, text=f"{h:02d}:00", anchor="ne", font=F["mono_mini"],
                               fill=t["suave"])

        def caber(txt, fonte, largura):
            if fm[fonte].measure(txt) <= largura:
                return txt
            while txt and fm[fonte].measure(txt + "…") > largura:
                txt = txt[:-1]
            return txt.rstrip() + "…" if txt else ""

        # blocos
        blocos = {}
        borda_orig = {}
        for i, itens in enumerate(por_dia):
            dia = dias_semana[i]
            for n, (x, a, b, faixa, total) in enumerate(self.faixas_paralelas(itens)):
                x0 = EIXO + i * col_w + 4 + (col_w - 8) * faixa / total
                x1 = EIXO + i * col_w + 4 + (col_w - 8) * (faixa + 1) / total - (2 if total > 1 else 0)
                y0, y1 = y_de(max(a, h_ini * 60)) + 1, y_de(min(b, h_fim * 60)) - 2
                tag = f"b{i}_{n}"
                sem_aula = bool(x.get("aula")) and not tem_aula(dia)
                passou = dia < hoje or (dia == hoje and b <= agora.hour * 60 + agora.minute)
                apagado = sem_aula or passou
                cor = t["linha"] if sem_aula else cor_da(x["nome"])
                tinta = t["suave"] if apagado else t["tinta"]
                borda = t["destaque"] if total > 1 else t["linha"]
                cv.create_rectangle(x0, y0, x1, y1, fill=t["card"], outline=borda,
                                    dash=() if x.get("fim") else (4, 3), tags=(tag, "bloco", tag + "_r"))
                cv.create_rectangle(x0, y0, x0 + 4, y1, fill=cor, outline="", tags=(tag, "bloco"))
                tx, tw = x0 + 10, x1 - x0 - 14
                altura = y1 - y0
                hora_txt = f"{x['hora']}–{x['fim']}" if x.get("fim") else x["hora"]
                if altura < 34:
                    # bloco baixo: tudo numa linha
                    linha = caber(f"{x['hora']} {x['nome']}", "mini_b", tw)
                    cv.create_text(tx, (y0 + y1) / 2, text=linha, anchor="w", font=F["mini_b"],
                                   fill=tinta, tags=(tag, "bloco"))
                else:
                    yy = y0 + 6
                    cv.create_text(tx, yy, text=caber(hora_txt, "mono_mini", tw), anchor="nw",
                                   font=F["mono_mini"], fill=t["suave"], tags=(tag, "bloco"))
                    yy += 16
                    cv.create_text(tx, yy, text=caber(x["nome"], "corpo_b", tw), anchor="nw",
                                   font=F["corpo_b"], fill=tinta, tags=(tag, "bloco"))
                    yy += 20
                    extra = ""
                    if sem_aula:
                        extra = "sem aula (feriado/férias)"
                    elif total > 1:
                        extra = "conflito"
                    else:
                        mat = self.materia_da_tarefa(x)
                        if mat:
                            extra = self.resumo_materia(mat) or mat.get("local", "")
                        elif x.get("data"):
                            extra = "só nesta data"
                    if extra and yy + 14 <= y1:
                        cv.create_text(tx, yy, text=caber(extra, "mini", tw), anchor="nw", font=F["mini"],
                                       fill=t["destaque"] if extra == "conflito" else t["suave"],
                                       tags=(tag, "bloco"))
                blocos[tag] = x
                borda_orig[tag] = borda

        # linha da hora atual (só na coluna de hoje)
        self._linha_agora = None
        min_agora = agora.hour * 60 + agora.minute
        if h_ini * 60 <= min_agora <= h_fim * 60:
            x0 = EIXO + hoje_i * col_w
            y = y_de(min_agora)
            linha = cv.create_line(x0 + 2, y, x0 + col_w - 2, y, fill=t["destaque"], width=2, tags=("agora",))
            ponto = cv.create_oval(x0 - 3, y - 5, x0 + 7, y + 5, fill=t["destaque"], outline="", tags=("agora",))
            self._linha_agora = (cv, linha, ponto, x0, col_w, y_de)
            cv.tag_raise("agora")

        # hover: realça o bloco; num espaço vazio mostra um "+ 13:30" fantasma
        fantasma = {"ids": []}
        estado = {"tag": None}

        def tag_do_bloco(ev):
            for item in cv.find_overlapping(ev.x, ev.y, ev.x, ev.y)[::-1]:
                for tg in cv.gettags(item):
                    if tg in blocos:
                        return tg
            return None

        def slot(ev):
            if ev.x < EIXO or ev.y < TOPO:
                return None
            i = int((ev.x - EIXO) // col_w)
            minutos = h_ini * 60 + (ev.y - TOPO) * 60 / PX_H
            minutos = int(minutos // 30 * 30)
            if not 0 <= i < 7 or minutos >= h_fim * 60:
                return None
            return i, minutos

        def limpar_fantasma():
            for item in fantasma["ids"]:
                cv.delete(item)
            fantasma["ids"] = []

        def mover(ev):
            tg = tag_do_bloco(ev)
            if tg != estado["tag"]:
                if estado["tag"]:
                    cv.itemconfigure(estado["tag"] + "_r", width=1, outline=borda_orig[estado["tag"]])
                estado["tag"] = tg
                if tg:
                    cv.itemconfigure(tg + "_r", outline=t["destaque"], width=2)
            limpar_fantasma()
            if tg:
                cv.configure(cursor="hand2")
                return
            sl = slot(ev)
            if not sl:
                cv.configure(cursor="")
                return
            cv.configure(cursor="hand2")
            i, minutos = sl
            x0, x1 = EIXO + i * col_w + 4, EIXO + (i + 1) * col_w - 4
            y0, y1 = y_de(minutos) + 1, y_de(minutos + 30) - 1
            fantasma["ids"] = [
                cv.create_rectangle(x0, y0, x1, y1, outline=t["destaque"], dash=(3, 3), fill=""),
                cv.create_text(x0 + 8, (y0 + y1) / 2, anchor="w", font=F["mono_mini"], fill=t["destaque"],
                               text=f"+ {minutos // 60:02d}:{minutos % 60:02d}"),
            ]

        def sair(_ev):
            mover(type("E", (), {"x": -1, "y": -1})())
            cv.configure(cursor="")

        def clique(ev):
            tg = tag_do_bloco(ev)
            if tg:
                return self.abrir_item(blocos[tg])
            sl = slot(ev)
            if sl:
                i, minutos = sl
                self.dialogo_tarefa(pre_dias=[i], pre_hora=f"{minutos // 60:02d}:{minutos % 60:02d}")

        cv.bind("<Motion>", mover)
        cv.bind("<Leave>", sair)
        cv.bind("<Button-1>", clique)

        legenda = tk.Frame(p, bg=t["bg"])
        legenda.pack(anchor="w", padx=6, pady=(10, 0))
        tk.Label(legenda, text="Clique num espaço vazio para adicionar naquele horário  ·  "
                               "borda tracejada = sem horário de término (mostrado com 1 h)  ·  "
                               "blocos lado a lado = choque de horário",
                 font=F["mini"], bg=t["bg"], fg=t["suave"], wraplength=larg, justify="left").pack(anchor="w")

    def mover_linha_agora(self):
        info = getattr(self, "_linha_agora", None)
        if not info:
            return
        cv, linha, ponto, x0, col_w, y_de = info
        if not cv.winfo_exists():
            return
        agora = datetime.now()
        y = y_de(agora.hour * 60 + agora.minute)
        cv.coords(linha, x0 + 2, y, x0 + col_w - 2, y)
        cv.coords(ponto, x0 - 3, y - 5, x0 + 7, y + 5)

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
        campos = {}  # valores lidos ao clicar em Salvar

        def cartao(titulo):
            self.secao(p, titulo)
            caixa = tk.Frame(p, bg=t["card"], highlightthickness=1, highlightbackground=t["linha"])
            caixa.pack(anchor="w", padx=6, fill="x")
            i = tk.Frame(caixa, bg=t["card"])
            i.pack(padx=28, pady=18, fill="x")
            i.grid_columnconfigure(0, weight=1)
            i._n = 0
            return i

        def rotulo(i, titulo, desc):
            f = tk.Frame(i, bg=t["card"])
            f.grid(row=i._n, column=0, sticky="w", pady=8)
            tk.Label(f, text=titulo, font=F["corpo_b"], bg=t["card"], fg=t["tinta"]).pack(anchor="w")
            if desc:
                tk.Label(f, text=desc, font=F["mini"], bg=t["card"], fg=t["suave"], justify="left",
                         wraplength=460).pack(anchor="w")

        def entrada(i, chave, titulo, desc, valor, largura=8):
            rotulo(i, titulo, desc)
            e = tk.Entry(i, width=largura, font=F["mono"], justify="center", bg=t["bg"], fg=t["tinta"],
                         relief="flat", highlightthickness=1, highlightbackground=t["linha"],
                         highlightcolor=t["destaque"], insertbackground=t["tinta"])
            e.insert(0, valor)
            e.grid(row=i._n, column=1, padx=(40, 0), sticky="e", ipady=5)
            campos[chave] = e
            i._n += 1

        def escolha(i, titulo, desc, opcoes, atual, ao_escolher):
            """Botões lado a lado. Aplica na hora, sem redesenhar a tela (não perde o que foi digitado)."""
            rotulo(i, titulo, desc)
            tf = tk.Frame(i, bg=t["card"])
            tf.grid(row=i._n, column=1, padx=(40, 0), sticky="e")
            labs = []

            def pinta(valor_on):
                for valor, lab in labs:
                    on = valor == valor_on
                    lab.configure(bg=t["destaque"] if on else t["bg"], fg=t["sobre"] if on else t["tinta"],
                                  highlightbackground=t["destaque"] if on else t["linha"])

            def clique(valor):
                pinta(valor)
                ao_escolher(valor)

            for valor, rot in opcoes:
                lab = tk.Label(tf, text=rot, font=F["corpo_b"], padx=12, pady=7, cursor="hand2",
                               highlightthickness=1)
                lab.pack(side="left", padx=(0, 6))
                lab.bind("<Button-1>", lambda e, v=valor: clique(v))
                labs.append((valor, lab))
            pinta(atual)
            i._n += 1

        def guardar(chave):
            def f(valor):
                cfg[chave] = valor
                self.salvar_seguro()
            return f

        # ---- avisos
        i = cartao("Avisos")
        entrada(i, "intervalo_min", "Avisar a cada", "minutos entre um aviso e outro", cfg["intervalo_min"])
        entrada(i, "antecedencia_min", "Começar a avisar", "minutos antes da atividade", cfg["antecedencia_min"])
        escolha(i, "Resumo do dia", "janela com o resumo ao abrir o app e quando vira o dia",
                ((True, "Mostrar"), (False, "Não mostrar")), cfg.get("resumo_ao_iniciar", True),
                guardar("resumo_ao_iniciar"))
        if TEM_BANDEJA:
            def mudar_bandeja(v):
                cfg["bandeja"] = v
                self.salvar_seguro()
                self.iniciar_bandeja() if v else self.parar_bandeja()
            escolha(i, "Ícone perto do relógio", "fechar a janela esconde o app na bandeja do sistema",
                    ((True, "Usar"), (False, "Não usar")), cfg.get("bandeja", True), mudar_bandeja)
        escolha(i, "Ao fechar a janela", "minimizar mantém os avisos funcionando"
                + (" (vale quando o ícone perto do relógio está desligado)" if TEM_BANDEJA else ""),
                ((True, "Minimizar"), (False, "Encerrar")), cfg.get("fechar_minimiza", True),
                guardar("fechar_minimiza"))

        # ---- semestre
        i = cartao("Semestre, notas e faltas")
        entrada(i, "semestre_inicio", "Início do semestre", "antes disso as aulas não aparecem nem avisam",
                iso_para_br(cfg["semestre_inicio"]) if cfg.get("semestre_inicio") else "", 12)
        entrada(i, "semestre_fim", "Fim do semestre", "também usado para calcular o limite de faltas",
                iso_para_br(cfg["semestre_fim"]) if cfg.get("semestre_fim") else "", 12)
        entrada(i, "media_aprovacao", "Média para passar", "usada no cálculo de “quanto preciso tirar”",
                fmt_nota(cfg.get("media_aprovacao", 7)))
        entrada(i, "nota_max", "Nota máxima", "maior nota possível numa avaliação", fmt_nota(cfg.get("nota_max", 10)))
        entrada(i, "limite_faltas_pct", "Limite de faltas (%)",
                "porcentagem das aulas que você pode faltar (na maioria das faculdades, 25%)",
                cfg.get("limite_faltas_pct", 25))
        rotulo(i, "Feriados e recessos", "um por linha: “15/11 Proclamação” ou “20/12/2026 a 05/01/2027 Recesso”. "
                                         "Nesses dias não há aula nem aviso de aula.")
        i._n += 1
        txt_fer = tk.Text(i, height=5, font=F["mono"], bg=t["bg"], fg=t["tinta"], relief="flat", wrap="word",
                          highlightthickness=1, highlightbackground=t["linha"], highlightcolor=t["destaque"],
                          insertbackground=t["tinta"], padx=10, pady=8, width=60)
        txt_fer.grid(row=i._n, column=0, columnspan=2, sticky="we", pady=(0, 4))
        txt_fer.insert("1.0", fmt_feriados(cfg.get("feriados", [])))
        i._n += 1

        # ---- estudo
        i = cartao("Estudo")
        entrada(i, "pomodoro_min", "Tempo de foco", "minutos de cada bloco de estudo", cfg.get("pomodoro_min", 25))
        entrada(i, "pausa_min", "Tempo de pausa", "minutos de descanso entre os blocos", cfg.get("pausa_min", 5))
        entrada(i, "revisoes_dias", "Revisões depois de", "dias após concluir um conteúdo (separados por vírgula)",
                ", ".join(str(x) for x in cfg.get("revisoes_dias", [1, 7, 30])), 12)

        # ---- aparência
        i = cartao("Aparência")
        escolha(i, "Tema", "cores da janela", (("claro", "Claro"), ("escuro", "Escuro")),
                cfg["tema"], self.trocar_tema)

        # ---- salvar
        barra = tk.Frame(p, bg=t["bg"])
        barra.pack(anchor="w", padx=6, pady=(18, 0), fill="x")
        msg = tk.Label(barra, text="", font=F["mini"], bg=t["bg"], fg=t["ok"], justify="left",
                       wraplength=max(400, self.largura_util() - 200))

        def salvar_cfg():
            def inteiro(chave, lo, hi):
                v = int(campos[chave].get().strip())
                return min(hi, max(lo, v))
            try:
                novos = {
                    "intervalo_min": inteiro("intervalo_min", 1, 720),
                    "antecedencia_min": inteiro("antecedencia_min", 1, 1440),
                    "limite_faltas_pct": inteiro("limite_faltas_pct", 0, 100),
                    "pomodoro_min": inteiro("pomodoro_min", 1, 180),
                    "pausa_min": inteiro("pausa_min", 1, 60),
                }
            except ValueError:
                return msg.configure(text="Use apenas números inteiros nos campos de minutos e porcentagem.",
                                     fg=t["destaque"])
            try:
                novos["media_aprovacao"] = ler_numero(campos["media_aprovacao"].get())
                novos["nota_max"] = ler_numero(campos["nota_max"].get())
            except ValueError:
                return msg.configure(text="Média e nota máxima precisam ser números (ex.: 7 ou 6,5).",
                                     fg=t["destaque"])
            if not 0 < novos["media_aprovacao"] <= novos["nota_max"]:
                return msg.configure(text="A média para passar precisa estar entre 0 e a nota máxima.",
                                     fg=t["destaque"])
            for chave in ("semestre_inicio", "semestre_fim"):
                txt = campos[chave].get().strip()
                try:
                    novos[chave] = parse_data_absoluta(txt) if txt else ""
                except ValueError:
                    return msg.configure(text="Data do semestre inválida. Use DD/MM/AAAA.", fg=t["destaque"])
            if novos["semestre_inicio"] and novos["semestre_fim"] and novos["semestre_fim"] < novos["semestre_inicio"]:
                return msg.configure(text="O fim do semestre vem antes do início.", fg=t["destaque"])
            try:
                revs = sorted({int(x) for x in re.split(r"[,; ]+", campos["revisoes_dias"].get().strip()) if x})
                if any(x <= 0 for x in revs):
                    raise ValueError
            except ValueError:
                return msg.configure(text="Revisões: use números de dias maiores que zero, ex.: 1, 7, 30.",
                                     fg=t["destaque"])
            novos["revisoes_dias"] = revs
            feriados, err = parse_feriados(txt_fer.get("1.0", "end"))
            if err:
                return msg.configure(text=err, fg=t["destaque"])
            novos["feriados"] = feriados
            cfg.update(novos)
            if self.salvar_seguro():
                self.render(conservar=True)
                self.root.after(50, lambda: self._msg_ajustes("Salvo."))

        self.botao(barra, "Salvar ajustes", salvar_cfg).pack(side="left")
        msg.pack(side="left", padx=14)
        self._lbl_msg_ajustes = msg

        # ---- dados e sistema
        i = cartao("Dados e sistema")
        rotulo(i, "Pasta dos dados", str(DATA_DIR) + ("  (padrão)" if DATA_DIR == APP_DIR else "")
               + "\nUse uma pasta do Google Drive, OneDrive ou Syncthing para ter o mesmo cronograma em "
                 "vários computadores.")
        bp = tk.Frame(i, bg=t["card"])
        bp.grid(row=i._n, column=1, padx=(40, 0), sticky="e")
        self.botao(bp, "Trocar pasta…", self.trocar_pasta_dados, tipo="ghost", fundo=t["card"]).pack(side="left")
        if DATA_DIR != APP_DIR:
            self.botao(bp, "Voltar ao padrão", lambda: self.trocar_pasta_dados(padrao=True), tipo="ghost",
                       fundo=t["card"]).pack(side="left", padx=(6, 0))
        i._n += 1

        rotulo(i, "Agenda do celular", "exporta aulas, atividades e datas num arquivo .ics para importar no "
                                       "Google Agenda, Outlook ou no celular (avisos chegam por lá também)")
        self.botao(i, "Exportar .ics", self.exportar_ics, tipo="ghost", fundo=t["card"]).grid(
            row=i._n, column=1, padx=(40, 0), sticky="e")
        i._n += 1

        auto_ativo = arquivo_autostart().exists()

        def auto():
            try:
                if arquivo_autostart().exists():
                    remover_autostart()
                    texto = "Não vai mais abrir com o computador."
                else:
                    texto = f"Vai abrir minimizado ao ligar o computador ({instalar_autostart()})."
            except Exception as e:  # permissão, pasta inexistente etc.
                return self._msg_ajustes(f"Não deu certo: {e}", erro=True, sistema=True)
            self.render(conservar=True)
            self.root.after(50, lambda: self._msg_ajustes(texto, sistema=True))

        rotulo(i, "Iniciar com o computador", "ativado" if auto_ativo else "desativado")
        self.botao(i, "Desativar" if auto_ativo else "Ativar", auto, tipo="ghost", fundo=t["card"]).grid(
            row=i._n, column=1, padx=(40, 0), sticky="e")
        i._n += 1

        msg_sis = tk.Label(i, text="", font=F["mini"], bg=t["card"], fg=t["ok"], justify="left",
                           wraplength=max(400, self.largura_util() - 120))
        msg_sis.grid(row=i._n, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self._lbl_msg_sistema = msg_sis

        dicas = ("Backup automático em dados.json.bak, na mesma pasta.  ·  "
                 "Abrir o app de novo enquanto ele já roda só traz a janela de volta.")
        if not TEM_BANDEJA:
            dicas += ("\nPara ter um ícone perto do relógio, instale:  pip install pystray pillow  "
                      "e reabra o app.")
        dicas += ("\n\nAtalhos: Ctrl+1…6 trocam de tela  ·  Ctrl+N cria um item na tela atual  ·  "
                  "F5 atualiza  ·  Ctrl+Q encerra")
        tk.Label(p, text=dicas, font=F["mini"], bg=t["bg"], fg=t["suave"], anchor="w",
                 justify="left", wraplength=max(400, self.largura_util() - 20)).pack(anchor="w", padx=6,
                                                                                     pady=(18, 0))

    def trocar_pasta_dados(self, padrao=False):
        if padrao:
            nova = APP_DIR
        else:
            escolhida = filedialog.askdirectory(parent=self.root, title="Pasta para guardar os dados",
                                                initialdir=str(DATA_DIR))
            if not escolhida:
                return
            nova = Path(escolhida)
        if nova.resolve() == DATA_DIR.resolve():
            return
        alvo = nova / "dados.json"
        usar_de_la = False
        if alvo.exists():
            r = messagebox.askyesnocancel(
                "Já existem dados nessa pasta",
                "Essa pasta já tem um dados.json (talvez de outro computador).\n\n"
                "Sim: usar os dados que estão lá.\nNão: substituir pelos dados deste computador.",
                parent=self.root)
            if r is None:
                return
            usar_de_la = r
        anterior = DATA_DIR
        definir_pasta_dados(None if nova == APP_DIR else nova)
        if usar_de_la:
            novos = ler_se_valido()
            if novos is None:
                messagebox.showerror("Arquivo inválido", "Não consegui ler o dados.json dessa pasta.",
                                     parent=self.root)
                definir_pasta_dados(None if anterior == APP_DIR else anterior)
                return
            self.dados = novos
            self.mtime = mtime_dados()
        else:
            self.salvar_seguro()
        self.aplicar_tema()
        self.montar()
        self.render()
        self.root.after(50, lambda: self._msg_ajustes(f"Agora os dados ficam em {DATA_DIR}.", sistema=True))

    def exportar_ics(self):
        caminho = filedialog.asksaveasfilename(parent=self.root, title="Exportar para agenda",
                                               defaultextension=".ics", initialfile="lembretes.ics",
                                               filetypes=[("Calendário (.ics)", "*.ics")])
        if not caminho:
            return
        try:
            with open(caminho, "w", encoding="utf-8", newline="") as f:
                f.write(gerar_ics(self.dados))
        except OSError as e:
            return self._msg_ajustes(f"Não consegui salvar: {e}", erro=True, sistema=True)
        self._msg_ajustes(f"Exportado para {caminho}. No Google Agenda: Configurações → Importar e exportar → "
                          "Importar. Ao exportar de novo, importe por cima (os eventos são atualizados).",
                          sistema=True)

    def _msg_ajustes(self, texto, erro=False, sistema=False):
        lbl = getattr(self, "_lbl_msg_sistema" if sistema else "_lbl_msg_ajustes", None)
        if lbl is not None and lbl.winfo_exists():
            lbl.configure(text=texto, fg=self.t["destaque"] if erro else self.t["ok"])

    def trocar_tema(self, nome):
        self.dados["config"]["tema"] = nome
        self.salvar_seguro()
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
        x = min(x, d.winfo_screenwidth() - d.winfo_width() - 10)
        y = min(y, d.winfo_screenheight() - d.winfo_height() - 50)
        d.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        try:
            d.wait_visibility()
            d.grab_set()
        except tk.TclError:
            pass

    def rotulo_campo(self, c, texto):
        tk.Label(c, text=texto.upper(), font=self.F["rotulo"], bg=self.t["bg"],
                 fg=self.t["suave"]).pack(anchor="w", pady=(14, 5))

    def campo(self, c, rotulo, valor="", mono=False):
        t = self.t
        self.rotulo_campo(c, rotulo)
        e = tk.Entry(c, font=self.F["mono" if mono else "corpo"], bg=t["card"], fg=t["tinta"], insertbackground=t["tinta"],
                     relief="flat", highlightthickness=1, highlightbackground=t["linha"],
                     highlightcolor=t["destaque"])
        e.pack(fill="x", ipady=8)
        e.insert(0, valor)
        return e

    def editor_horarios(self, c, horarios_iniciais, pre_dias=None, exige_dias=lambda: True, pre_hora=""):
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
        e_ini = tk.Entry(linha_hr, width=8, font=F["mono"], bg=t["card"], fg=t["tinta"],
                         insertbackground=t["tinta"], relief="flat", highlightthickness=1,
                         highlightbackground=t["linha"])
        e_ini.pack(side="left", padx=(6, 14), ipady=5)

        tk.Label(linha_hr, text="Término:", font=F["mini_b"], bg=t["bg"], fg=t["suave"]).pack(side="left")
        e_fim = tk.Entry(linha_hr, width=8, font=F["mono"], bg=t["card"], fg=t["tinta"],
                         insertbackground=t["tinta"], relief="flat", highlightthickness=1,
                         highlightbackground=t["linha"])
        e_fim.pack(side="left", padx=(6, 14), ipady=5)

        if not horarios and pre_hora:
            e_ini.insert(0, pre_hora)
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
                    text=f"Editando horário #{idx + 1} ({dias_txt}) — altere abaixo ou clique em 'Novo horário'",
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
            item, err = ler_campos_atuais(exigir_dias=exige_dias())
            if err:
                erro_interno["msg"] = err
                self._erro_dialogo(err)
                return False
            if not item:
                self._erro_dialogo("Preencha a hora de início (ex.: 08:00).")
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
            self._erro_dialogo("")
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

    def conflitos(self, horarios, data_iso="", ignorar=""):
        """Lista de outras aulas/atividades que se sobrepõem aos horários informados."""
        achados = []
        hoje_iso = date.today().isoformat()
        for h in horarios:
            a0 = para_min(h["hora"])
            a1 = para_min(h["fim"]) if h.get("fim") else a0 + 1
            if data_iso:
                alvo = [(datetime.strptime(data_iso, "%Y-%m-%d").weekday(), data_iso)]
            else:
                alvo = [(wd, None) for wd in h.get("dias", [])]
            for x in self.dados["tarefas"]:
                if ignorar and x["id"].startswith(ignorar):
                    continue
                b0 = para_min(x["hora"])
                b1 = para_min(x["fim"]) if x.get("fim") else b0 + 1
                if not (a0 < b1 and b0 < a1):
                    continue
                for wd, iso in alvo:
                    if x.get("data"):
                        x_wd = datetime.strptime(x["data"], "%Y-%m-%d").weekday()
                        bate = x["data"] == iso if iso else (x_wd == wd and x["data"] >= hoje_iso)
                    else:
                        bate = wd in x.get("dias", [])
                    if bate:
                        txt = f"{x['nome']} ({DIAS[wd]} {x['hora']})"
                        if txt not in achados:
                            achados.append(txt)
        return achados

    def confirmar_conflito(self, estado, erro, conf):
        """Primeiro clique em Salvar mostra o choque de horário; o segundo salva mesmo assim."""
        if conf and estado.get("conf") != conf:
            estado["conf"] = conf
            extra = f" e mais {len(conf) - 3}" if len(conf) > 3 else ""
            erro.configure(text=f"Choca com {', '.join(conf[:3])}{extra}. "
                                f"Clique em Salvar de novo para manter assim.")
            return False
        return True

    def _erro_dialogo(self, texto):
        lbl = getattr(self, "_ultimo_erro_lbl", None)
        if lbl is not None and lbl.winfo_exists():
            lbl.configure(text=texto)

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

    def caixa_texto(self, c, altura, valor="", mono=False):
        t = self.t
        txt = tk.Text(c, height=altura, width=30, font=self.F["mono" if mono else "corpo"], bg=t["card"], fg=t["tinta"], wrap="word",
                      insertbackground=t["tinta"], relief="flat", highlightthickness=1,
                      highlightbackground=t["linha"], highlightcolor=t["destaque"], padx=10, pady=8)
        txt.pack(fill="x")
        if valor:
            txt.insert("1.0", valor)
        return txt

    def dica(self, c, texto):
        tk.Label(c, text=texto, font=self.F["mini"], bg=self.t["bg"], fg=self.t["suave"], justify="left",
                 wraplength=380).pack(anchor="w", pady=(4, 0))

    def dialogo_materia(self, m=None):
        t, F = self.t, self.F
        cfg = self.dados["config"]
        d, c = self.novo_dialogo("Editar matéria" if m else "Nova matéria", largura=980)

        colunas = tk.Frame(c, bg=t["bg"])
        colunas.pack(fill="both", expand=True)
        esq = tk.Frame(colunas, bg=t["bg"], width=540)
        esq.pack(side="left", fill="both", expand=True, padx=(0, 16))
        tk.Frame(colunas, bg=t["linha"], width=1).pack(side="left", fill="y", pady=(14, 0))
        dir_ = tk.Frame(colunas, bg=t["bg"], width=380)
        dir_.pack(side="left", fill="y", padx=(16, 0))

        # ---- coluna esquerda: identificação, conteúdos e horários
        par_topo = tk.Frame(esq, bg=t["bg"])
        par_topo.pack(fill="x")
        c_esq = tk.Frame(par_topo, bg=t["bg"])
        c_esq.pack(side="left", fill="x", expand=True, padx=(0, 8))
        c_dir = tk.Frame(par_topo, bg=t["bg"])
        c_dir.pack(side="left", fill="x", expand=True, padx=(8, 0))
        e_nome = self.campo(c_esq, "Matéria (ex.: Cálculo I)", m["nome"] if m else "")
        e_local = self.campo(c_dir, "Sala / Professor (opcional)", m.get("local", "") if m else "")
        e_atual = self.campo(esq, "Conteúdo acontecendo na aula agora", m.get("atual", "") if m else "")

        self.rotulo_campo(esq, "Conteúdos da matéria (um por linha — [x] = concluído)")
        antigos = {}
        linhas_init = []
        if m:
            for item in m.get("conteudos", []):
                antigos[item["texto"]] = item
                linhas_init.append(f"[{'x' if item.get('feito') else ' '}] {item['texto']}")
        txt_cont = self.caixa_texto(esq, 4, "\n".join(linhas_init))

        self.rotulo_campo(esq, "Horários da matéria (entram automaticamente no Cronograma)")
        obter_horarios = self.editor_horarios(esq, m.get("horarios", []) if m else [])

        # ---- coluna direita: avaliações e faltas
        self.rotulo_campo(dir_, "Avaliações  ·  nome | peso | nota")
        av_init = "\n".join(
            f"{a['nome']} | {fmt_nota(a['peso'])}" + (f" | {fmt_nota(a['nota'])}" if a.get("nota") is not None else "")
            for a in (m.get("avaliacoes", []) if m else []))
        txt_av = self.caixa_texto(dir_, 6, av_init, mono=True)
        self.dica(dir_, f"Ex.: P1 | 2 | 7,5  ·  deixe a nota vazia se ainda não fez. "
                        f"Média para passar: {fmt_nota(cfg.get('media_aprovacao', 7))} (muda em Ajustes).")

        self.rotulo_campo(dir_, "Máximo de faltas")
        linha_max = tk.Frame(dir_, bg=t["bg"])
        linha_max.pack(fill="x")
        e_max = tk.Entry(linha_max, width=6, font=F["mono"], bg=t["card"], fg=t["tinta"], justify="center",
                         insertbackground=t["tinta"], relief="flat", highlightthickness=1,
                         highlightbackground=t["linha"], highlightcolor=t["destaque"])
        e_max.pack(side="left", ipady=6)
        e_max.insert(0, str(int(m.get("max_faltas") or 0)) if m else "0")
        auto_txt = ""
        if m:
            prev = aulas_previstas(m)
            if prev:
                auto_txt = (f"0 = automático: {int(prev * float(cfg.get('limite_faltas_pct', 25)) / 100)} "
                            f"({cfg.get('limite_faltas_pct', 25)}% de {prev} aulas no semestre)")
        tk.Label(linha_max, text=auto_txt or f"0 = automático ({cfg.get('limite_faltas_pct', 25)}% das aulas;"
                                             " precisa das datas do semestre em Ajustes)",
                 font=F["mini"], bg=t["bg"], fg=t["suave"], wraplength=290,
                 justify="left").pack(side="left", padx=(10, 0))

        self.rotulo_campo(dir_, "Faltas registradas (uma data por linha)")
        faltas_init = "\n".join(iso_para_br(x) for x in (m.get("faltas", []) if m else []))
        txt_faltas = self.caixa_texto(dir_, 4, faltas_init, mono=True)
        self.dica(dir_, "No card da matéria há o botão “+ faltei hoje”. Aqui é só para corrigir.")

        def ler_conteudos():
            saida = []
            for ln in txt_cont.get("1.0", "end").splitlines():
                s_ = ln.strip()
                if not s_:
                    continue
                feito = False
                if s_.lower().startswith("[x]"):
                    feito = True
                    s_ = s_[3:].strip()
                elif s_.startswith("[ ]") or s_.startswith("[]"):
                    s_ = s_.split("]", 1)[1].strip()
                elif s_.startswith("- "):
                    s_ = s_[2:].strip()
                if not s_:
                    continue
                novo = {"texto": s_, "feito": feito}
                velho = antigos.get(s_)
                if feito:
                    # mantém o histórico de revisões se o conteúdo já estava concluído
                    if velho and velho.get("feito") and velho.get("feito_em"):
                        for k in ("feito_em", "revisoes", "revisado_em"):
                            if k in velho:
                                novo[k] = velho[k]
                    else:
                        novo["feito_em"] = date.today().isoformat()
                        novo["revisoes"] = 0
                saida.append(novo)
            return saida

        def ler_faltas():
            saida = []
            for n, ln in enumerate(txt_faltas.get("1.0", "end").splitlines(), start=1):
                if not ln.strip():
                    continue
                try:
                    saida.append(parse_data_absoluta(ln))
                except ValueError:
                    return None, f"Faltas, linha {n}: data inválida (use DD/MM/AAAA)."
            return sorted(saida), None

        estado_conf = {}

        def salvar_():
            nome = e_nome.get().strip()
            if not nome:
                return erro.configure(text="Digite o nome da matéria.")
            horarios_finais, err = obter_horarios(exigir_dias=True)
            if err:
                return erro.configure(text=err)
            avaliacoes, err = parse_avaliacoes(txt_av.get("1.0", "end"))
            if err:
                return erro.configure(text=err)
            faltas, err = ler_faltas()
            if err:
                return erro.configure(text=err)
            try:
                max_f = max(0, int(e_max.get().strip() or 0))
            except ValueError:
                return erro.configure(text="Máximo de faltas: use um número inteiro (0 = automático).")
            conf = self.conflitos(horarios_finais, ignorar=f"mat_{m['id']}_" if m else "")
            if not self.confirmar_conflito(estado_conf, erro, conf):
                return

            campos = dict(nome=nome, local=e_local.get().strip(), atual=e_atual.get().strip(),
                          conteudos=ler_conteudos(), horarios=horarios_finais,
                          avaliacoes=avaliacoes, faltas=faltas, max_faltas=max_f)
            if m:
                m.update(campos)
            else:
                self.dados["materias"].append(dict(id=uuid.uuid4().hex, **campos))
            self.salvar_seguro()
            d.destroy()
            self.render(conservar=True)

        def remover_():
            self.dados["materias"] = [y for y in self.dados["materias"] if y["id"] != m["id"]]
            for x in self.dados["datas"]:
                if x.get("materia_id") == m["id"]:
                    x["materia_id"] = ""
            self.dados["estudos"] = [x for x in self.dados["estudos"] if x.get("materia_id") != m["id"]]
            self.salvar_seguro()
            d.destroy()
            self.render(conservar=True)

        erro = self.rodape_dialogo(c, d, salvar_, remover_ if m else None, bind_return=False)
        self.mostrar(d)
        e_nome.focus_set()

    def dialogo_tarefa(self, ativ=None, pre_dias=None, pre_hora=""):
        d, c = self.novo_dialogo("Editar atividade" if ativ else "Nova atividade", largura=560)
        e_nome = self.campo(c, "O que fazer (ex.: Academia, Corrida, Estudo)", ativ["nome"] if ativ else "")

        self.rotulo_campo(c, "Horários por dia da semana (ex.: Seg 13:00–14:00, Ter 08:00–10:00)")
        obter_horarios = self.editor_horarios(
            c,
            ativ.get("horarios", []) if ativ else [],
            pre_dias=pre_dias if pre_dias is not None else [0],
            pre_hora=pre_hora,
            exige_dias=lambda: not e_data.get().strip(),
        )

        e_data = self.campo(
            c,
            "Ou data única opcional (DD/MM/AAAA)",
            iso_para_br(ativ["data"]) if ativ and ativ.get("data") else "",
            mono=True,
        )
        tk.Label(c, text="Deixe a data em branco para repetir toda semana nos dias escolhidos.",
                 font=self.F["mini"], bg=self.t["bg"], fg=self.t["suave"]).pack(anchor="w", pady=(4, 0))

        estado_conf = {}

        def salvar_():
            nome = e_nome.get().strip()
            if not nome:
                return erro.configure(text="Digite o nome da atividade.")
            data_iso = ""
            if e_data.get().strip():
                try:
                    data_iso = parse_data(e_data.get())
                except ValueError:
                    return erro.configure(text="Data inválida. Use DD/MM/AAAA (ou só DD/MM).")

            horarios_finais, err = obter_horarios(exigir_dias=not bool(data_iso))
            if err:
                return erro.configure(text=err)
            conf = self.conflitos(horarios_finais, data_iso, ignorar=f"ativ_{ativ['id']}_" if ativ else "")
            if not self.confirmar_conflito(estado_conf, erro, conf):
                return

            if ativ:
                ativ.update(nome=nome, horarios=horarios_finais, data=data_iso)
            else:
                self.dados["atividades"].append({
                    "id": uuid.uuid4().hex,
                    "nome": nome,
                    "horarios": horarios_finais,
                    "data": data_iso,
                })
            self.salvar_seguro()
            d.destroy()
            self.render(conservar=True)

        def remover_():
            self.dados["atividades"] = [y for y in self.dados["atividades"] if y["id"] != ativ["id"]]
            self.salvar_seguro()
            d.destroy()
            self.render(conservar=True)

        erro = self.rodape_dialogo(c, d, salvar_, remover_ if ativ else None)
        self.mostrar(d)
        e_nome.focus_set()

    def seletor_materia(self, c, atual=""):
        """Botões com as matérias (+ 'Nenhuma'). Retorna função que dá o id escolhido."""
        t, F = self.t, self.F
        escolha = {"id": atual or ""}
        opcoes = [("", "Nenhuma")] + [(m["id"], m["nome"]) for m in self.dados.get("materias", [])]
        caixa = tk.Frame(c, bg=t["bg"])
        caixa.pack(fill="x")
        labs = {}

        def pinta():
            for mid, lab in labs.items():
                on = escolha["id"] == mid
                lab.configure(bg=t["destaque"] if on else t["card"], fg=t["sobre"] if on else t["tinta"],
                              highlightbackground=t["destaque"] if on else t["linha"])

        def escolher(mid):
            escolha["id"] = mid
            pinta()

        linha = tk.Frame(caixa, bg=t["bg"])
        linha.pack(anchor="w")
        larg = 0
        for mid, nome in opcoes:
            txt = corta(nome, 22)
            w_est = F["corpo_b"][1] * len(txt) + 36
            if larg + w_est > 470 and larg:
                linha = tk.Frame(caixa, bg=t["bg"])
                linha.pack(anchor="w", pady=(6, 0))
                larg = 0
            lab = tk.Label(linha, text=txt, font=F["mini_b"], padx=10, pady=6, cursor="hand2",
                           highlightthickness=1)
            lab.pack(side="left", padx=(0, 6))
            lab.bind("<Button-1>", lambda e, v=mid: escolher(v))
            labs[mid] = lab
            larg += w_est
        pinta()
        return lambda: escolha["id"]

    def dialogo_data(self, x=None, pre_materia=""):
        d, c = self.novo_dialogo("Editar evento" if x else "Novo evento")
        e_nome = self.campo(c, "Evento (ex.: Prova P2, Entrega do relatório)", x["nome"] if x else "")
        e_data = self.campo(c, "Data (DD/MM/AAAA ou DD/MM)", iso_para_br(x["data"]) if x else "", mono=True)
        obter_mat = None
        if self.dados.get("materias"):
            self.rotulo_campo(c, "De qual matéria? (opcional)")
            obter_mat = self.seletor_materia(c, x.get("materia_id", "") if x else pre_materia)

        def salvar_():
            nome = e_nome.get().strip()
            if not nome:
                return erro.configure(text="Digite o nome do evento.")
            try:
                data_iso = parse_data(e_data.get())
            except ValueError:
                return erro.configure(text="Data inválida. Use DD/MM/AAAA (ou só DD/MM).")
            mid = obter_mat() if obter_mat else ""
            if x:
                x.update(nome=nome, data=data_iso, materia_id=mid)
            else:
                self.dados["datas"].append({"id": uuid.uuid4().hex, "nome": nome, "data": data_iso,
                                            "materia_id": mid})
            self.salvar_seguro()
            d.destroy()
            self.render(conservar=True)

        def remover_():
            self.dados["datas"] = [y for y in self.dados["datas"] if y["id"] != x["id"]]
            self.salvar_seguro()
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
                mat = self.materia_por_id(d.get("materia_id"))
                nome = f"{d['nome']} ({mat['nome']})" if mat else d["nome"]
                if n == 0:
                    itens.append(("HOJE", nome))
                else:
                    itens.append((f"{n} dia{'s' if n != 1 else ''}", f"para {nome}"))
        avisos_mat = []
        for m in self.dados.get("materias", []):
            n, lim, nivel = situacao_faltas(m, self.dados["config"])
            if nivel == "estourou":
                avisos_mat.append(("!", f"{m['nome']}: {n} faltas, passou do limite de {lim}"))
            elif nivel == "atencao":
                avisos_mat.append(("!", f"{m['nome']}: {n} de {lim} faltas — pode faltar só mais {lim - n}"))
        rev = revisoes_devidas(self.dados, agora.date())
        if rev:
            nomes = ", ".join(corta(item["texto"], 24) for _, item, _, _ in rev[:3])
            mais = f" e mais {len(rev) - 3}" if len(rev) > 3 else ""
            avisos_mat.append((str(len(rev)), f"para revisar: {nomes}{mais}"))
        if avisos_mat:
            itens.append((None, "Estudos"))
            itens.extend(avisos_mat)
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

    def alerta(self, titulo, itens, slot="aviso", adiar=True):
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
        rod = tk.Frame(c, bg=t["card"])
        rod.pack(anchor="e", pady=(22, 0))
        if adiar:
            def adiar_():
                p.destroy()
                self.root.after(ADIAR_MIN * 60_000,
                                lambda: self.alerta(f"{titulo} · adiado", itens, slot=slot))
            self.botao(rod, f"Adiar {ADIAR_MIN} min", adiar_, tipo="ghost", fundo=t["card"]).pack(side="left", padx=(0, 8))
        self.botao(rod, "Entendi", p.destroy, fundo=t["card"]).pack(side="left")
        p.bind("<Escape>", lambda e: p.destroy())
        p.bind("<Return>", lambda e: p.destroy())
        p.update_idletasks()
        off = 0 if slot == "resumo" else 70
        x = (p.winfo_screenwidth() - p.winfo_reqwidth()) // 2 + off
        y = p.winfo_screenheight() // 5 + off
        p.geometry(f"+{max(x, 0)}+{y}")
        p.lift()
        self.beep()
        corpo = "  |  ".join(f"{b} {s}" if b else s for b, s in itens)
        notificar_sistema(titulo, corpo)

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

    def recarregar_se_mudou(self):
        """Se o arquivo de dados foi alterado por fora (ex.: sincronizado de outro computador), recarrega."""
        atual = mtime_dados()
        if atual is None or atual == self.mtime:
            return
        if any(isinstance(w, tk.Toplevel) and w.winfo_exists() and w.grab_current() is not None
               for w in self.root.winfo_children()):
            return  # tem um diálogo aberto; tenta de novo no próximo ciclo
        novos = ler_se_valido()
        if novos is None:
            return  # arquivo no meio de uma cópia; tenta de novo depois
        self.dados = novos
        self.mtime = atual
        tema_antes = self.t
        self.aplicar_tema()
        if self.t is not tema_antes:
            self.montar()
        self.render(conservar=True)

    def _checar(self):
        self.recarregar_se_mudou()
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
            if minutos == 0 or minutos % intervalo == 0 or minutos == antecedencia:
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

        # virou o dia com o app aberto: novo resumo e limpeza dos avisos antigos
        if agora.date() != self.dia_resumo:
            self.dia_resumo = agora.date()
            hoje_iso = agora.date().isoformat()
            self.avisados = {k for k in self.avisados if k[1] >= hoje_iso}
            if self.dados["config"].get("resumo_ao_iniciar", True):
                self.mostrar_resumo(agora)

        atual = agora.replace(second=0, microsecond=0)
        if self.view == "semana":
            self.mover_linha_agora()
        if self._min is None or (self._min != atual and
                                 (self.view == "hoje" or self._min.date() != atual.date())):
            self.render(conservar=True)


def main():
    auto = "--auto" in sys.argv
    servidor = abrir_servidor_instancia()
    if servidor is None and avisar_instancia_aberta():
        return  # já estava aberto: a janela existente foi trazida para frente
    root = tk.Tk()
    try:
        root.tk.call("tk", "appname", "lembretes")
    except tk.TclError:
        pass
    App(root, auto=auto, servidor=servidor)
    root.mainloop()


if __name__ == "__main__":
    main()