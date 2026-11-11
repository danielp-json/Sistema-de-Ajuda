# Sistema de Lembretes

Aplicativo de cronograma e avisos com modo acadêmico. Funciona em **Arch Linux** e **Windows**, sem dependências externas — apenas Python + Tkinter.

## Funcionalidades

- **Cronograma semanal** com grade de horários por hora
- **Modo acadêmico**: faltas, notas, médias e situação por matéria
- **Pomodoro** integrado por matéria
- **Revisão espaçada** de conteúdos
- **Datas e entregas** vinculadas às matérias
- **Semestre e feriados** configuráveis
- **Exportar agenda** para `.ics` (Google Calendar, etc.)
- **Notificação nativa** (Windows toast / Linux notify-send)
- **Bandeja do sistema** opcional (pystray)
- **Pasta de dados sincronizável** (configurável em Ajustes)
- **Fira Code** nos campos numéricos e de horário

## Requisitos

- Python 3.10+
- Tkinter (já incluso no Python padrão)
- `pystray` + `Pillow` — **opcional**, só para ícone na bandeja

## Instalação

```bash
# Clone o repositório
git clone https://github.com/danielaraujop/Sistema-de-Ajuda.git
cd Sistema-de-Ajuda

# Execute diretamente
python lembretes.py
```

> No Arch Linux: `sudo pacman -S python tk`
> No Windows: Python padrão do python.org já inclui Tkinter.

## Dados

Os dados ficam em `~/.lembretes/dados.json` (com backup automático em `dados.json.bak`).  
A pasta pode ser alterada em **Ajustes → Dados e sistema** para usar uma pasta sincronizada (Dropbox, etc.).

## Atalhos

| Atalho | Ação |
|--------|------|
| `Ctrl+1…6` | Trocar de tela |
| `Ctrl+N` | Novo item |
| `F5` | Atualizar |
| `Ctrl+Q` | Encerrar |

## Estrutura

```
Sistema-de-Ajuda/
├── lembretes.py   # Aplicativo completo (único arquivo)
└── README.md
```
