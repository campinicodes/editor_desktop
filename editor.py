#!/usr/bin/env python3
"""Editor desktop de cidades da plataforma de zoneamento (Tkinter).

    pip install -r requirements.txt
    python editor.py                 # abre vazio
    python editor.py <arquivo.json | pasta da cidade>

Toda a lógica fica em modelo.py (testada sem interface); este arquivo só monta as telas.
Fluxo central, por ZONA:  ① criar/selecionar a zona → ② parâmetros → ③ atributos adicionais → ④ geometria (KMZ/KML/GeoJSON).
"""
import json
import math
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import modelo as M

TITULO = "Editor de cidades – Plataforma de zoneamento"
GRANDE_MB = 5          # acima disso a pré-visualização não é desenhada automaticamente (ex.: Rio, 18 MB)
CORES = {"base": "#4c78a8", "sobreposta": "#e45756", "eixo": "#f58518"}


class Rolavel(ttk.Frame):
    """Frame com barra de rolagem vertical (para as grades de parâmetros)."""

    def __init__(self, pai, **kw):
        super().__init__(pai, **kw)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.interno = ttk.Frame(self.canvas)
        self.interno.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._win = self.canvas.create_window((0, 0), window=self.interno, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.bind_all(ev, self._roda, add="+")

    def _roda(self, e):
        w = self.winfo_containing(e.x_root, e.y_root)
        while w is not None and w is not self:
            w = w.master
        if w is None:
            return
        passo = -1 if (getattr(e, "num", 0) == 4 or getattr(e, "delta", 0) > 0) else 1
        self.canvas.yview_scroll(passo, "units")

    def limpar(self):
        for w in self.interno.winfo_children():
            w.destroy()
        self.canvas.yview_moveto(0)


def rotulo_campo(pai, texto, linha, col=0, **kw):
    ttk.Label(pai, text=texto).grid(row=linha, column=col, sticky="w", padx=4, pady=2, **kw)


class Editor(tk.Tk):
    def __init__(self, inicial=None):
        super().__init__()
        self.title(TITULO)
        self.geometry("1360x860")
        self.minsize(1100, 700)
        estilo = ttk.Style(self)
        if "clam" in estilo.theme_names():
            estilo.theme_use("clam")
        estilo.configure("Passo.TLabel", font=("TkDefaultFont", 11, "bold"), foreground="#1f4e79")
        estilo.configure("Fluxo.TLabel", background="#eaf2fb", foreground="#1f4e79", padding=6)
        estilo.configure("Erro.TLabel", foreground="#b00020")
        estilo.configure("Ok.TLabel", foreground="#1b7f3b")
        estilo.configure("Treeview", rowheight=22)
        self.cfg = M.ler_config()
        self.plataforma = tk.StringVar(value=M.achar_plataforma(self.cfg) or "")
        self.cidade = M.Cidade()
        self.zona_atual = None
        self.linhas_param = {}       # caminho -> dict de StringVar
        self.linhas_adic = {}
        self.sujo_zona = False
        self.fila = queue.Queue()
        self.ocupado = False
        self._montar()
        self.after(100, self._vigiar_fila)
        self.protocol("WM_DELETE_WINDOW", self._sair)
        self.recarregar_tudo()
        if inicial:
            self.after(200, lambda: self.abrir_caminho(inicial))

    # ------------------------------------------------------------------ infraestrutura
    def em_segundo_plano(self, func, ao_terminar, msg="Processando…"):
        """Roda func() numa thread (a janela não trava – ex.: abrir o Rio, 18 MB) e chama ao_terminar(resultado, erro)."""
        if self.ocupado:
            messagebox.showinfo(TITULO, "Aguarde a operação em andamento terminar.")
            return
        self.ocupado = True
        self.status(msg)
        self.barra.start(12)
        self.config(cursor="watch")

        def alvo():
            try:
                self.fila.put((ao_terminar, func(), None))
            except Exception as e:  # noqa: BLE001
                self.fila.put((ao_terminar, None, e))
        threading.Thread(target=alvo, daemon=True).start()

    def _vigiar_fila(self):
        try:
            while True:
                cb, res, erro = self.fila.get_nowait()
                self.ocupado = False
                self.barra.stop()
                self.config(cursor="")
                self.status("Pronto.")
                cb(res, erro)
        except queue.Empty:
            pass
        self.after(100, self._vigiar_fila)

    def status(self, texto):
        self.var_status.set(texto)

    def erro(self, e, titulo="Erro"):
        messagebox.showerror(titulo, str(e))

    def _sair(self):
        if self.cidade.alterado and not messagebox.askyesno(TITULO, "Há alterações não salvas. Sair mesmo assim?"):
            return
        self.destroy()

    # ------------------------------------------------------------------ montagem
    def _montar(self):
        barra = ttk.Frame(self, padding=(6, 6, 6, 0))
        barra.pack(fill="x")
        l1, l2 = ttk.Frame(barra), ttk.Frame(barra)
        l1.pack(fill="x")
        l2.pack(fill="x", pady=(3, 0))
        ttk.Label(l1, text="Abrir:", width=7).pack(side="left")
        for t, f in (("Nova cidade", self.nova_cidade), ("Atualizar cidade existente (abrir pasta)…", self.abrir_pasta),
                     ("Abrir JSON…", self.abrir_json)):
            ttk.Button(l1, text=t, command=f).pack(side="left", padx=2)
        ttk.Separator(l1, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Label(l1, text="Da plataforma:").pack(side="left")
        self.combo_plat = ttk.Combobox(l1, width=26, state="readonly")
        self.combo_plat.pack(side="left", padx=2)
        self.combo_plat.set("escolha a cidade…")
        self.combo_plat.bind("<<ComboboxSelected>>", lambda _: self.abrir_da_plataforma())
        ttk.Label(l2, text="Gravar:", width=7).pack(side="left")
        for t, f in (("✔ Validar", self.validar), ("Exportar pasta da cidade…", self.exportar),
                     ("Atualizar no lugar (backup .bak)", self.atualizar_no_lugar), ("Salvar na plataforma", self.salvar_plataforma),
                     ("Salvar JSON como…", self.salvar_como)):
            ttk.Button(l2, text=t, command=f).pack(side="left", padx=2)
        self.var_titulo = tk.StringVar(value="(nova cidade)")
        ttk.Label(self, textvariable=self.var_titulo, font=("TkDefaultFont", 12, "bold"), padding=(10, 4)).pack(fill="x")
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=6, pady=4)
        self.aba_cidade = ttk.Frame(self.nb, padding=6)
        self.aba_zonas = ttk.Frame(self.nb, padding=6)
        self.aba_atrib = ttk.Frame(self.nb, padding=6)
        self.aba_lote = ttk.Frame(self.nb, padding=6)
        self.aba_val = ttk.Frame(self.nb, padding=6)
        self.nb.add(self.aba_cidade, text="  Cidade e fontes  ")
        self.nb.add(self.aba_zonas, text="  Zonas (fluxo por zona)  ")
        self.nb.add(self.aba_atrib, text="  Atributos adicionais  ")
        self.nb.add(self.aba_lote, text="  Importar em lote  ")
        self.nb.add(self.aba_val, text="  Validação  ")
        self._montar_cidade()
        self._montar_zonas()
        self._montar_atributos()
        self._montar_lote()
        self._montar_validacao()
        rod = ttk.Frame(self, padding=(6, 0, 6, 4))
        rod.pack(fill="x")
        self.var_status = tk.StringVar(value="Pronto.")
        ttk.Label(rod, textvariable=self.var_status).pack(side="left")
        self.barra = ttk.Progressbar(rod, mode="indeterminate", length=160)
        self.barra.pack(side="right")

    # ------------------------------------------------------------------ aba CIDADE
    def _montar_cidade(self):
        a = self.aba_cidade
        a.columnconfigure(0, weight=1)
        a.columnconfigure(1, weight=2)
        meta = ttk.LabelFrame(a, text="Metadados da cidade", padding=6)
        meta.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        self.v_meta = {k: tk.StringVar() for k in ("municipio", "uf", "codigo_ibge", "lat", "lon", "zoom", "crs_area",
                                                   "data_levantamento", "marco_legal_vigente", "orgao_confirmacao")}
        self.v_slug = tk.StringVar()
        campos = [("Município *", "municipio"), ("UF *", "uf"), ("Código IBGE (7 dígitos) *", "codigo_ibge"),
                  ("Centro do mapa – latitude *", "lat"), ("Centro do mapa – longitude *", "lon"), ("Zoom inicial (1–20)", "zoom"),
                  ("CRS métrico para áreas", "crs_area"), ("Data do levantamento", "data_levantamento"),
                  ("Marco legal vigente", "marco_legal_vigente"), ("Órgão para confirmação", "orgao_confirmacao")]
        for i, (t, k) in enumerate(campos):
            rotulo_campo(meta, t, i)
            ttk.Entry(meta, textvariable=self.v_meta[k], width=40).grid(row=i, column=1, sticky="ew", padx=4, pady=2)
        meta.columnconfigure(1, weight=1)
        ttk.Button(meta, text="sugerir UTM", command=self._sugerir_crs).grid(row=6, column=2, padx=2)
        rotulo_campo(meta, "Slug (automático)", len(campos))
        ttk.Label(meta, textvariable=self.v_slug, foreground="#555").grid(row=len(campos), column=1, sticky="w", padx=4)
        for k in ("municipio", "uf"):
            self.v_meta[k].trace_add("write", lambda *_: self.v_slug.set(M.slug_cidade(self.v_meta["municipio"].get(), self.v_meta["uf"].get())))
        ttk.Button(meta, text="Aplicar metadados", command=self.aplicar_metadados).grid(row=len(campos) + 1, column=1, sticky="e", pady=6)

        plat = ttk.LabelFrame(a, text="Plataforma (opcional – o editor valida sozinho com o validador embutido)", padding=6)
        plat.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        ttk.Entry(plat, textvariable=self.plataforma, width=50).grid(row=0, column=0, sticky="ew", padx=4)
        ttk.Button(plat, text="Escolher…", command=self._escolher_plataforma).grid(row=0, column=1)
        plat.columnconfigure(0, weight=1)
        self.v_plat_info = tk.StringVar()
        ttk.Label(plat, textvariable=self.v_plat_info, wraplength=520).grid(row=1, column=0, columnspan=2, sticky="w", padx=4)
        self.v_pasta = tk.StringVar()
        pasta = ttk.LabelFrame(a, text="Pasta da cidade aberta (preservada ao exportar)", padding=6)
        pasta.grid(row=2, column=0, sticky="nsew", padx=4, pady=4)
        ttk.Label(pasta, textvariable=self.v_pasta, wraplength=520, justify="left").pack(anchor="w")

        fon = ttk.LabelFrame(a, text="Fontes (leis, decretos, bases) – toda citação de parâmetro aponta para um id daqui", padding=6)
        fon.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=4, pady=4)
        cols = ("id", "titulo", "lei", "data", "url", "arquivo")
        self.tv_fontes = ttk.Treeview(fon, columns=cols, show="headings", height=8)
        for c, w in zip(cols, (80, 220, 150, 80, 200, 120)):
            self.tv_fontes.heading(c, text=c)
            self.tv_fontes.column(c, width=w, stretch=c in ("titulo", "url"))
        self.tv_fontes.grid(row=0, column=0, columnspan=4, sticky="nsew")
        self.tv_fontes.bind("<<TreeviewSelect>>", self._fonte_selecionada)
        fon.columnconfigure(1, weight=1)
        fon.rowconfigure(0, weight=1)
        self.v_fonte = {k: tk.StringVar() for k in ("id", "titulo", "lei", "url", "data", "observacao", "arquivo")}
        for i, (t, k) in enumerate([("id *", "id"), ("Título *", "titulo"), ("Lei *", "lei"), ("Link (http…) *", "url"),
                                    ("Data", "data"), ("Observação", "observacao"), ("Anexo (copiado p/ fontes/)", "arquivo")]):
            rotulo_campo(fon, t, i + 1)
            ttk.Entry(fon, textvariable=self.v_fonte[k]).grid(row=i + 1, column=1, columnspan=2, sticky="ew", padx=4, pady=1)
        ttk.Button(fon, text="Arquivo…", command=lambda: self.v_fonte["arquivo"].set(
            filedialog.askopenfilename(title="Anexo da fonte") or self.v_fonte["arquivo"].get())).grid(row=7, column=3)
        bf = ttk.Frame(fon)
        bf.grid(row=8, column=0, columnspan=4, sticky="e", pady=4)
        ttk.Button(bf, text="Nova fonte", command=self._fonte_nova).pack(side="left", padx=2)
        ttk.Button(bf, text="Salvar fonte", command=self._fonte_salvar).pack(side="left", padx=2)
        ttk.Button(bf, text="Remover fonte", command=self._fonte_remover).pack(side="left", padx=2)
        self._fonte_id_sel = None
        lac = ttk.LabelFrame(a, text="Lacunas (parâmetros sem dado e o motivo)", padding=6)
        lac.grid(row=2, column=1, sticky="nsew", padx=4, pady=4)
        self.lb_lacunas = tk.Listbox(lac, height=6)
        self.lb_lacunas.pack(fill="both", expand=True)
        a.rowconfigure(0, weight=1)
        a.rowconfigure(2, weight=1)

    def _sugerir_crs(self):
        try:
            lat = M.numero(self.v_meta["lat"].get(), rotulo="latitude")
            lon = M.numero(self.v_meta["lon"].get(), rotulo="longitude")
            self.v_meta["crs_area"].set(f"EPSG:{M.epsg_utm(lon, lat)}")
        except (M.ErroEditor, TypeError):
            messagebox.showinfo(TITULO, "Preencha latitude e longitude do centro primeiro.")

    def _escolher_plataforma(self):
        p = filedialog.askdirectory(title="Pasta da plataforma (a que contém cidades/)")
        if p:
            self.plataforma.set(p)
            self.cfg["plataforma"] = p
            M.gravar_config(self.cfg)
            self._atualizar_plataforma()

    def _atualizar_plataforma(self):
        p = self.plataforma.get()
        if not p or not os.path.isdir(os.path.join(p, "cidades")):
            self.v_plat_info.set("Plataforma não configurada: tudo funciona (validação embutida, Exportar pasta); "
                                 "\"Salvar na plataforma\" e \"Abrir da plataforma\" ficam indisponíveis.")
            self.combo_plat["values"] = []
            return
        slugs = M.cidades_da_plataforma(p)
        igual = M.schema_igual_ao_da_plataforma(p)
        self.v_plat_info.set(f"{len(slugs)} cidade(s) em {os.path.join(p, 'cidades')}. Schema embutido "
                             + ("idêntico ao da plataforma." if igual else "DIFERENTE do da plataforma – rode empacotar.py --sincronizar."))
        self.combo_plat["values"] = slugs

    def _carregar_cidade_na_tela(self):
        d = self.cidade.dados
        cm = d.get("centro_mapa") or {}
        g = d.get("geografico") or {}
        vals = {"municipio": d.get("municipio"), "uf": d.get("uf"), "codigo_ibge": d.get("codigo_ibge"), "lat": M.fmt_num(cm.get("lat")),
                "lon": M.fmt_num(cm.get("lon")), "zoom": M.fmt_num(cm.get("zoom")), "crs_area": g.get("crs_area"),
                "data_levantamento": d.get("data_levantamento"), "marco_legal_vigente": d.get("marco_legal_vigente"),
                "orgao_confirmacao": d.get("orgao_confirmacao")}
        for k, v in vals.items():
            self.v_meta[k].set(v or "")
        self.v_slug.set(d.get("slug") or "")
        self._recarregar_fontes()
        self.lb_lacunas.delete(0, "end")
        for x in d.get("lacunas") or []:
            self.lb_lacunas.insert("end", f"{x.get('item')}: {x.get('motivo')}" if isinstance(x, dict) else str(x))
        inv = self.cidade.conteudo_pasta()
        if inv["pasta"]:
            hist = d.get("historico_alteracoes") or []
            self.v_pasta.set(f"{inv['pasta']}\nfontes/: {len(inv['fontes'])} arquivo(s) · geo_raw/: {len(inv['geo_raw'])} · "
                             f"scripts/: {len(inv['scripts'])} · REFERENCIAS.md: {'sim' if inv['REFERENCIAS.md'] else 'não'}\n"
                             f"Última atualização: {d.get('data_atualizacao') or '—'} · histórico: {len(hist)} registro(s)")
        else:
            self.v_pasta.set("(cidade ainda não salva)")

    def aplicar_metadados(self, silencioso=False):
        v = {k: x.get() for k, x in self.v_meta.items()}
        try:
            antes = (self.cidade.dados.get("municipio"), self.cidade.dados.get("slug"))
            self.cidade.definir_metadados(v["municipio"], v["uf"], v["codigo_ibge"], v["lat"], v["lon"], v["zoom"] or 13, v["crs_area"],
                                          v["data_levantamento"], v["marco_legal_vigente"], v["orgao_confirmacao"])
            if self.cidade.alterado and antes != (self.cidade.dados.get("municipio"), self.cidade.dados.get("slug")):
                self.cidade.registrar("metadados alterados")
            self._carregar_cidade_na_tela()
            self._titulo()
            return True
        except M.ErroEditor as e:
            if not silencioso:
                self.erro(e, "Metadados")
            return False

    def _recarregar_fontes(self):
        self.tv_fontes.delete(*self.tv_fontes.get_children())
        for f in self.cidade.dados.get("fontes") or []:
            self.tv_fontes.insert("", "end", iid=f.get("id"), values=(f.get("id"), f.get("titulo"), f.get("lei"), f.get("data"),
                                                                       f.get("url"), f.get("arquivo_local") or ""))
        ids = self.cidade.ids_fontes()
        for cb in getattr(self, "_combos_fonte", []):
            try:
                cb["values"] = [""] + ids
            except tk.TclError:
                pass

    def _fonte_selecionada(self, _=None):
        sel = self.tv_fontes.selection()
        if not sel:
            return
        f = next((x for x in self.cidade.dados.get("fontes") or [] if x.get("id") == sel[0]), {})
        self._fonte_id_sel = f.get("id")
        for k in self.v_fonte:
            self.v_fonte[k].set("" if k == "arquivo" else (f.get(k) or ""))

    def _fonte_nova(self):
        self._fonte_id_sel = None
        self.tv_fontes.selection_remove(*self.tv_fontes.selection())
        for v in self.v_fonte.values():
            v.set("")

    def _fonte_salvar(self):
        v = {k: x.get() for k, x in self.v_fonte.items()}
        try:
            f = self.cidade.salvar_fonte(self._fonte_id_sel, v["id"], v["titulo"], v["lei"], v["url"], v["data"], v["observacao"],
                                         v["arquivo"] or None)
            self.cidade.registrar(f"fonte {f['id']} salva")
            self._fonte_id_sel = f["id"]
            self._recarregar_fontes()
            self.tv_fontes.selection_set(f["id"])
            self._titulo()
        except M.ErroEditor as e:
            self.erro(e, "Fonte")

    def _fonte_remover(self):
        if not self._fonte_id_sel:
            return
        try:
            self.cidade.remover_fonte(self._fonte_id_sel)
            self.cidade.registrar(f"fonte {self._fonte_id_sel} removida")
            self._fonte_nova()
            self._recarregar_fontes()
        except M.ErroEditor as e:
            self.erro(e, "Fonte")

    # ------------------------------------------------------------------ aba ZONAS (fluxo central)
    def _montar_zonas(self):
        a = self.aba_zonas
        ttk.Label(a, style="Fluxo.TLabel",
                  text="Fluxo por zona:   ① crie ou selecione a zona   →   ② preencha os parâmetros   →   "
                       "③ atributos adicionais (crie novos aqui mesmo)   →   ④ anexe o KMZ / KML / GeoJSON da zona").pack(fill="x", pady=(0, 6))
        corpo = ttk.PanedWindow(a, orient="horizontal")
        corpo.pack(fill="both", expand=True)
        esq = ttk.Frame(corpo, padding=2)
        corpo.add(esq, weight=1)
        ttk.Label(esq, text="① Zonas da cidade", style="Passo.TLabel").pack(anchor="w")
        self.v_filtro = tk.StringVar()
        ef = ttk.Entry(esq, textvariable=self.v_filtro)
        ef.pack(fill="x", pady=2)
        self.v_filtro.trace_add("write", lambda *_: self._recarregar_zonas())
        self.tv_zonas = ttk.Treeview(esq, columns=("codigo", "tipo", "feicoes"), show="headings", height=20)
        for c, t, w in (("codigo", "Código", 150), ("tipo", "Tipo", 80), ("feicoes", "Feições", 60)):
            self.tv_zonas.heading(c, text=t)
            self.tv_zonas.column(c, width=w, stretch=c == "codigo")
        sbz = ttk.Scrollbar(esq, orient="vertical", command=self.tv_zonas.yview)
        self.tv_zonas.configure(yscrollcommand=sbz.set)
        self.tv_zonas.pack(side="top", fill="both", expand=True)
        self.tv_zonas.bind("<<TreeviewSelect>>", self._zona_selecionada)
        bz = ttk.Frame(esq)
        bz.pack(fill="x", pady=4)
        ttk.Button(bz, text="+ Nova zona", command=self.nova_zona).pack(side="left", padx=2)
        ttk.Button(bz, text="Remover zona", command=self.remover_zona).pack(side="left", padx=2)

        dir_ = ttk.Frame(corpo)
        corpo.add(dir_, weight=4)
        self.v_zona_titulo = tk.StringVar(value="Selecione ou crie uma zona à esquerda.")
        ttk.Label(dir_, textvariable=self.v_zona_titulo, font=("TkDefaultFont", 11, "bold")).pack(anchor="w", padx=4)
        self.nb_zona = ttk.Notebook(dir_)
        self.nb_zona.pack(fill="both", expand=True)
        self.passo_dados = ttk.Frame(self.nb_zona, padding=6)
        self.passo_param = ttk.Frame(self.nb_zona, padding=4)
        self.passo_adic = ttk.Frame(self.nb_zona, padding=4)
        self.passo_geo = ttk.Frame(self.nb_zona, padding=6)
        self.nb_zona.add(self.passo_dados, text=" 1 · Dados da zona ")
        self.nb_zona.add(self.passo_param, text=" 2 · Parâmetros ")
        self.nb_zona.add(self.passo_adic, text=" 3 · Atributos adicionais ")
        self.nb_zona.add(self.passo_geo, text=" 4 · Geometria ")
        self._montar_passo_dados()
        self._montar_passo_param()
        self._montar_passo_adic()
        self._montar_passo_geo()

    def _proximo(self, pai, indice, texto="Aplicar e ir para o próximo passo ›"):
        ttk.Button(pai, text=texto, command=lambda: self._avancar(indice)).pack(side="right", padx=4, pady=4)

    def _avancar(self, indice):
        if self.aplicar_zona():
            self.nb_zona.select(indice)

    def _montar_passo_dados(self):
        p = self.passo_dados
        f = ttk.Frame(p)
        f.pack(fill="x")
        self.v_z = {k: tk.StringVar() for k in ("codigo", "nome", "descricao", "tipo", "prioridade", "categoria", "criterio",
                                                "efeito", "usa_indices_de", "aplica_sobre", "fundamento", "alerta", "mantem_da_base",
                                                "distancia_max_m")}
        linhas = [("Código *", "codigo", "entry"), ("Nome *", "nome", "entry"), ("Descrição", "descricao", "entry"),
                  ("Tipo *", "tipo", M.TIPOS_ZONA), ("Prioridade (base = 0)", "prioridade", "entry"),
                  ("Categoria normalizada *", "categoria", M.CATEGORIAS), ("Critério da categoria", "criterio", "entry")]
        for i, (t, k, w) in enumerate(linhas):
            rotulo_campo(f, t, i)
            if w == "entry":
                e = ttk.Entry(f, textvariable=self.v_z[k], width=60)
            else:
                e = ttk.Combobox(f, textvariable=self.v_z[k], values=w, state="readonly", width=40)
            e.grid(row=i, column=1, sticky="ew", padx=4, pady=2)
        f.columnconfigure(1, weight=1)
        rotulo_campo(f, "Observações (uma por linha)", len(linhas))
        self.txt_obs = tk.Text(f, height=4, width=60)
        self.txt_obs.grid(row=len(linhas), column=1, sticky="ew", padx=4, pady=2)
        self.fr_regra = ttk.LabelFrame(p, text="Regra de sobreposição (zonas sobrepostas e eixos)", padding=6)
        self.fr_regra.pack(fill="x", pady=6)
        rg = [("Efeito", "efeito", M.EFEITOS), ("Usa índices de (zona)", "usa_indices_de", "zonas"),
              ("Aplica sobre (códigos, vírgula)", "aplica_sobre", "entry"), ("Fundamento legal", "fundamento", "entry"),
              ("Alerta exibido", "alerta", "entry"), ("Mantém da base (caminhos, vírgula)", "mantem_da_base", "entry"),
              ("Distância máx. ao eixo (m)", "distancia_max_m", "entry")]
        for i, (t, k, w) in enumerate(rg):
            rotulo_campo(self.fr_regra, t, i)
            if w == "entry":
                e = ttk.Entry(self.fr_regra, textvariable=self.v_z[k], width=60)
            elif w == "zonas":
                e = self.cb_usa = ttk.Combobox(self.fr_regra, textvariable=self.v_z[k], width=40)
            else:
                e = ttk.Combobox(self.fr_regra, textvariable=self.v_z[k], values=w, state="readonly", width=40)
            e.grid(row=i, column=1, sticky="ew", padx=4, pady=1)
        self.fr_regra.columnconfigure(1, weight=1)
        self.v_z["tipo"].trace_add("write", lambda *_: self._regra_visivel())
        for k in self.v_z:
            self.v_z[k].trace_add("write", self._marcar_sujo)
        self._proximo(p, 1)

    def _regra_visivel(self):
        estado = "disabled" if self.v_z["tipo"].get() == "base" else "normal"
        for w in self.fr_regra.winfo_children():
            try:
                w.configure(state=estado if not isinstance(w, ttk.Combobox) or estado == "disabled" else
                            ("readonly" if w is not getattr(self, "cb_usa", None) else "normal"))
            except tk.TclError:
                pass

    def _marcar_sujo(self, *_):
        if not getattr(self, "_carregando", False):
            self.sujo_zona = True

    def _montar_passo_param(self):
        p = self.passo_param
        ttk.Label(p, text="② Parâmetros padrão da zona. Valor vazio = sem dado (vira lacuna; escreva o motivo em Observação). "
                          "Taxas em fração (0,3) ou com % (30%). Faixa / condicional / fórmula: botão {…}.",
                  wraplength=1000, foreground="#444").pack(anchor="w")
        self.rol_param = Rolavel(p)
        self.rol_param.pack(fill="both", expand=True)
        b = ttk.Frame(p)
        b.pack(fill="x")
        ttk.Button(b, text="+ Parâmetro local em 'outros'", command=self._novo_outros).pack(side="left", padx=4, pady=4)
        self._proximo(b, 2)
        ttk.Button(b, text="Aplicar parâmetros", command=self.aplicar_zona).pack(side="right", padx=4)

    def _montar_passo_adic(self):
        p = self.passo_adic
        ttk.Label(p, text="③ Atributos adicionais da cidade (schema 1.2). Um atributo criado aqui passa a existir em TODAS as zonas "
                          "(vazio = null) e aparece na consulta da plataforma.", wraplength=1000, foreground="#444").pack(anchor="w")
        self.rol_adic = Rolavel(p)
        self.rol_adic.pack(fill="both", expand=True)
        b = ttk.Frame(p)
        b.pack(fill="x")
        ttk.Button(b, text="+ Novo atributo (todas as zonas)…", command=self.dialogo_atributo).pack(side="left", padx=4, pady=4)
        self._proximo(b, 3)
        ttk.Button(b, text="Aplicar atributos", command=self.aplicar_zona).pack(side="right", padx=4)

    def _montar_passo_geo(self):
        p = self.passo_geo
        p.columnconfigure(0, weight=1)
        p.columnconfigure(1, weight=1)
        p.rowconfigure(1, weight=1)
        self.v_geo_info = tk.StringVar(value="—")
        ttk.Label(p, textvariable=self.v_geo_info, wraplength=560, justify="left").grid(row=0, column=0, sticky="nw", padx=4)
        f = ttk.LabelFrame(p, text="④ Anexar geometria à zona (KMZ / KML / GeoJSON)", padding=6)
        f.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        self.v_g = {k: tk.StringVar() for k in ("arquivo", "campo", "valor", "epsg", "erro", "metodo", "fonte")}
        self.v_g_oficial = tk.BooleanVar(value=False)
        self.v_g_subst = tk.BooleanVar(value=True)
        rotulo_campo(f, "Arquivo *", 0)
        ttk.Entry(f, textvariable=self.v_g["arquivo"]).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(f, text="Escolher…", command=self._escolher_geo).grid(row=0, column=2)
        rotulo_campo(f, "Filtrar por campo (opcional)", 1)
        self.cb_g_campo = ttk.Combobox(f, textvariable=self.v_g["campo"], state="readonly")
        self.cb_g_campo.grid(row=1, column=1, sticky="ew", padx=4)
        self.cb_g_campo.bind("<<ComboboxSelected>>", self._geo_campo_escolhido)
        rotulo_campo(f, "… com valor", 2)
        self.cb_g_valor = ttk.Combobox(f, textvariable=self.v_g["valor"])
        self.cb_g_valor.grid(row=2, column=1, sticky="ew", padx=4)
        rotulo_campo(f, "EPSG de origem (vazio = automático)", 3)
        ttk.Entry(f, textvariable=self.v_g["epsg"]).grid(row=3, column=1, sticky="ew", padx=4)
        ttk.Checkbutton(f, text="Geometria OFICIAL (base da prefeitura)", variable=self.v_g_oficial).grid(row=4, column=1, sticky="w", padx=4)
        rotulo_campo(f, "Erro estimado (m)", 5)
        ttk.Entry(f, textvariable=self.v_g["erro"]).grid(row=5, column=1, sticky="ew", padx=4)
        rotulo_campo(f, "Método", 6)
        ttk.Entry(f, textvariable=self.v_g["metodo"]).grid(row=6, column=1, sticky="ew", padx=4)
        rotulo_campo(f, "Fonte", 7)
        cb = ttk.Combobox(f, textvariable=self.v_g["fonte"], state="readonly")
        cb.grid(row=7, column=1, sticky="ew", padx=4)
        self._combos_fonte = [cb]
        ttk.Checkbutton(f, text="Substituir a geometria atual (senão, acrescenta)", variable=self.v_g_subst).grid(
            row=8, column=1, sticky="w", padx=4)
        ttk.Label(f, text="Reprojeta para EPSG:4326, corrige (make_valid), simplifica ~2 m, arredonda a 6 casas e calcula a área no CRS métrico.",
                  wraplength=460, foreground="#555").grid(row=9, column=0, columnspan=3, sticky="w", pady=4)
        ttk.Button(f, text="Anexar à zona", command=self.anexar_geometria).grid(row=10, column=1, sticky="e", pady=4)
        f.columnconfigure(1, weight=1)
        pv = ttk.LabelFrame(p, text="Pré-visualização (contornos simplificados)", padding=4)
        pv.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=4, pady=4)
        self.canvas = tk.Canvas(pv, background="white", width=460, height=420)
        self.canvas.pack(fill="both", expand=True)
        bp = ttk.Frame(pv)
        bp.pack(fill="x")
        ttk.Button(bp, text="Desenhar zona", command=lambda: self.desenhar(False)).pack(side="left", padx=2)
        ttk.Button(bp, text="Desenhar cidade inteira", command=lambda: self.desenhar(True)).pack(side="left", padx=2)
        self.canvas.bind("<Configure>", lambda e: self.desenhar(None))

    # ---- grades de parâmetros
    def _linha_param(self, pai, linha, caminho, rotulo, unidade, tipo, p, destino):
        c = M.campos_de_parametro(p, tipo)
        v = {k: tk.StringVar(value=c[k]) for k in M.CAMPOS_VAZIOS}
        ttk.Label(pai, text=rotulo).grid(row=linha, column=0, sticky="w", padx=3, pady=1)
        ttk.Entry(pai, textvariable=v["valor"], width=16).grid(row=linha, column=1, sticky="ew", padx=2)
        if isinstance(unidade, str):
            ttk.Label(pai, text=unidade, foreground="#666", width=14).grid(row=linha, column=2, sticky="w", padx=2)
        elif isinstance(unidade, list):
            ttk.Combobox(pai, textvariable=v["unidade"], values=[""] + unidade, state="readonly", width=12).grid(row=linha, column=2, padx=2)
        else:
            ttk.Entry(pai, textvariable=v["unidade"], width=14).grid(row=linha, column=2, padx=2)
        cb = ttk.Combobox(pai, textvariable=v["fonte_id"], values=[""] + self.cidade.ids_fontes(), state="readonly", width=14)
        cb.grid(row=linha, column=3, padx=2)
        self._combos_fonte.append(cb)
        ttk.Entry(pai, textvariable=v["artigo_anexo"], width=16).grid(row=linha, column=4, sticky="ew", padx=2)
        ttk.Entry(pai, textvariable=v["observacao"], width=28).grid(row=linha, column=5, sticky="ew", padx=2)
        ttk.Combobox(pai, textvariable=v["forma"], values=[""] + M.FORMAS, state="readonly", width=13).grid(row=linha, column=6, padx=2)
        bt = ttk.Button(pai, width=4)
        bt.grid(row=linha, column=7, padx=2)
        atualiza = lambda *_: bt.configure(text="{✓}" if v["estrutura"].get().strip() else "{…}")
        atualiza()
        v["estrutura"].trace_add("write", atualiza)
        bt.configure(command=lambda: self.dialogo_estrutura(caminho, rotulo, unidade, tipo, v))
        for x in v.values():
            x.trace_add("write", self._marcar_sujo)
        destino[caminho] = (v, unidade, tipo, rotulo)

    def _cabecalho(self, pai):
        for i, t in enumerate(("Parâmetro", "Valor", "Unidade", "Fonte", "Artigo / anexo", "Observação", "Forma", "Estrut.")):
            ttk.Label(pai, text=t, font=("TkDefaultFont", 9, "bold")).grid(row=0, column=i, sticky="w", padx=3)
        for col, w in ((1, 1), (4, 1), (5, 3)):
            pai.columnconfigure(col, weight=w)

    def _montar_grades(self):
        self._carregando = True
        self._combos_fonte = self._combos_fonte[:1]
        self.rol_param.limpar()
        self.rol_adic.limpar()
        self.linhas_param, self.linhas_adic = {}, {}
        z = self.cidade.zona(self.zona_atual) if self.zona_atual else None
        if z is None:
            self._carregando = False
            return
        g = self.rol_param.interno
        self._cabecalho(g)
        i = 1
        for cam, rot, un, tipo in M.PARAMETROS_PADRAO:
            self._linha_param(g, i, cam, rot, un, tipo, M.get_caminho(z.get("parametros") or {}, cam), self.linhas_param)
            i += 1
        for k, p in ((z.get("parametros") or {}).get("outros") or {}).items():
            self._linha_param(g, i, f"outros.{k}", f"outros › {k}", None, "numero", p, self.linhas_param)
            i += 1
        g = self.rol_adic.interno
        defs = self.cidade.definicoes()
        if not defs:
            ttk.Label(g, text="Esta cidade ainda não tem atributos adicionais. Use “+ Novo atributo”.", foreground="#666").grid(row=0, column=0, pady=10)
        else:
            self._cabecalho(g)
            pa = z.get("parametros_adicionais") or {}
            for i, (k, df) in enumerate(defs.items(), start=1):
                self._linha_param(g, i, f"adicional.{k}", f"{df['rotulo']}  [{M.TIPOS_ADICIONAL_TXT.get(df['tipo'], df['tipo'])}]",
                                  df.get("unidade"), df["tipo"], pa.get(k), self.linhas_adic)
        self._carregando = False

    def dialogo_estrutura(self, caminho, rotulo, unidade, tipo, v):
        """Editor do bloco estruturado (faixa / condicionais / fórmula / texto_original) em JSON inline, validado."""
        w = tk.Toplevel(self)
        w.title(f"Estrutura – {rotulo}")
        w.transient(self)
        ttk.Label(w, text="JSON com as chaves faixa, condicionais, formula e/ou texto_original. Escolha um modelo, edite e valide.",
                  padding=6).pack(anchor="w")
        txt = tk.Text(w, width=90, height=16, font=("TkFixedFont", 10))
        txt.pack(fill="both", expand=True, padx=6)
        bruto = v["estrutura"].get()
        try:
            bruto = json.dumps(json.loads(bruto), ensure_ascii=False, indent=2) if bruto.strip() else ""
        except ValueError:
            pass
        txt.insert("1.0", bruto)
        msg = tk.StringVar()
        ttk.Label(w, textvariable=msg, wraplength=640, padding=4).pack(anchor="w")
        modelos = {
            "faixa": ("faixa", {"faixa": {"min": 1, "max": 2}}),
            "condicional": ("condicional", {"condicionais": [{"condicao": "lote até 360 m²", "forma": "unico", "valor": 1},
                                                             {"condicao": "lote acima de 360 m²", "forma": "unico", "valor": 1.5}]}),
            "fórmula": ("formula", {"formula": "h/6", "texto_original": "H/6, mínimo de 1,50 m"}),
        }
        b = ttk.Frame(w, padding=6)
        b.pack(fill="x")
        for nome, (forma, ex) in modelos.items():
            ttk.Button(b, text=f"Modelo: {nome}", command=lambda f=forma, e=ex: (txt.delete("1.0", "end"),
                       txt.insert("1.0", json.dumps(e, ensure_ascii=False, indent=2)), v["forma"].set(f))).pack(side="left", padx=2)

        def checar(fechar=False):
            texto = txt.get("1.0", "end").strip()
            if texto and not self._json_ok(texto, msg):
                return
            campos = {k: x.get() for k, x in v.items()}
            campos["estrutura"] = json.dumps(json.loads(texto), ensure_ascii=False) if texto else ""
            try:
                M.parametro_de_campos(campos, unidade, tipo, rotulo)
                msg.set("✔ Estrutura válida.")
                if fechar:
                    v["estrutura"].set(campos["estrutura"])
                    w.destroy()
            except M.ErroEditor as e:
                msg.set("✖ " + str(e))
        ttk.Button(b, text="OK", command=lambda: checar(True)).pack(side="right", padx=2)
        ttk.Button(b, text="Validar", command=checar).pack(side="right", padx=2)
        ttk.Button(b, text="Limpar", command=lambda: txt.delete("1.0", "end")).pack(side="right", padx=2)

    @staticmethod
    def _json_ok(texto, msg):
        try:
            json.loads(texto)
            return True
        except json.JSONDecodeError as e:
            msg.set(f"✖ JSON inválido: {e.msg} (linha {e.lineno}, coluna {e.colno}).")
            return False

    # ---- zonas: lista, seleção, aplicar
    def _recarregar_zonas(self, selecionar=None):
        filtro = self.v_filtro.get().strip().lower()
        self.tv_zonas.delete(*self.tv_zonas.get_children())
        for i, z in enumerate(self.cidade.dados.get("zonas") or []):
            cod = z.get("codigo") or f"#{i}"
            if filtro and filtro not in cod.lower() and filtro not in (z.get("nome") or "").lower():
                continue
            n = len((z.get("geometria") or {}).get("features") or [])
            self.tv_zonas.insert("", "end", iid=f"z{i}", values=(cod, z.get("tipo"), n))
        self.cb_usa["values"] = [""] + self.cidade.codigos()
        alvo = selecionar or self.zona_atual
        for iid in self.tv_zonas.get_children():
            if self.tv_zonas.item(iid, "values")[0] == alvo:
                self._sel_programatica = True
                self.tv_zonas.selection_set(iid)
                self.tv_zonas.see(iid)
                break

    def _zona_selecionada(self, _=None):
        if getattr(self, "_sel_programatica", False):
            self._sel_programatica = False
            if self.zona_atual == self._cod_selecionado():
                return
        cod = self._cod_selecionado()
        if cod is None or cod == self.zona_atual:
            return
        if self.sujo_zona and self.zona_atual:
            r = messagebox.askyesnocancel(TITULO, f"Aplicar as alterações da zona {self.zona_atual} antes de trocar?")
            if r is None or (r and not self.aplicar_zona()):
                self._recarregar_zonas(self.zona_atual)
                return
        self.mostrar_zona(cod)

    def _cod_selecionado(self):
        sel = self.tv_zonas.selection()
        return str(self.tv_zonas.item(sel[0], "values")[0]) if sel else None

    def mostrar_zona(self, cod):
        self.zona_atual = cod
        z = self.cidade.zona(cod)
        self._carregando = True
        if z is None:
            self.v_zona_titulo.set("Selecione ou crie uma zona à esquerda.")
            for x in self.v_z.values():
                x.set("")
            self.txt_obs.delete("1.0", "end")
        else:
            r = z.get("regra_sobreposicao") or {}
            vals = {"codigo": z.get("codigo"), "nome": z.get("nome"), "descricao": z.get("descricao"), "tipo": z.get("tipo"),
                    "prioridade": M.fmt_num(z.get("prioridade")), "categoria": z.get("categoria_normalizada"),
                    "criterio": z.get("categoria_criterio"), "efeito": r.get("efeito") or ("" if z.get("tipo") == "base" else "apenas_alerta"),
                    "usa_indices_de": r.get("usa_indices_de"), "aplica_sobre": ", ".join(r.get("aplica_sobre") or []),
                    "fundamento": r.get("fundamento"), "alerta": r.get("alerta"), "mantem_da_base": ", ".join(r.get("mantem_da_base") or []),
                    "distancia_max_m": M.fmt_num(r.get("distancia_max_m"))}
            for k, v in vals.items():
                self.v_z[k].set(v if v is not None else "")
            self.txt_obs.delete("1.0", "end")
            self.txt_obs.insert("1.0", "\n".join(z.get("observacoes") or []))
            self._obs_exibido = self.txt_obs.get("1.0", "end").strip()
            self.v_zona_titulo.set(f"Zona {cod} – {z.get('nome')}   ({z.get('tipo')}, prioridade {z.get('prioridade')})")
        self._regra_visivel()
        self._montar_grades()
        self._info_geo()
        self._carregando = False
        self.sujo_zona = False
        self.desenhar(None)

    def aplicar_zona(self):
        """Grava na cidade os dados, parâmetros e atributos da zona em tela. Mostra todos os erros de uma vez."""
        if not self.zona_atual or self.cidade.zona(self.zona_atual) is None:
            return True
        erros = []
        z = self.cidade.zona(self.zona_atual)
        v = {k: x.get() for k, x in self.v_z.items()}
        try:
            regra = None
            if v["tipo"] != "base":
                regra = {"efeito": v["efeito"] or "apenas_alerta", "usa_indices_de": v["usa_indices_de"], "aplica_sobre": v["aplica_sobre"],
                         "fundamento": v["fundamento"], "alerta": v["alerta"], "mantem_da_base": v["mantem_da_base"]}
                r0 = z.get("regra_sobreposicao") or {}
                if v["distancia_max_m"] or "distancia_max_m" in r0:
                    regra["distancia_max_m"] = v["distancia_max_m"]
                if not v["mantem_da_base"] and "mantem_da_base" not in r0:
                    regra.pop("mantem_da_base")
            texto_obs = self.txt_obs.get("1.0", "end").strip()
            obs = texto_obs.splitlines()          # uma observação por linha
            if texto_obs == getattr(self, "_obs_exibido", None) or obs == list(z.get("observacoes") or []) \
                    or (not obs and not z.get("observacoes")):
                obs = None                        # não mexeu: preserva (inclusive itens com quebra de linha interna)
            self.cidade.atualizar_zona(self.zona_atual, v["codigo"], v["nome"], v["tipo"], v["prioridade"], v["categoria"],
                                       v["descricao"], v["criterio"], obs, regra)
            self.zona_atual = z["codigo"]
        except M.ErroEditor as e:
            erros.append(str(e))
        for caminho, (vars_, _, _, _) in list(self.linhas_param.items()) + list(self.linhas_adic.items()):
            try:
                self.cidade.definir_parametro(self.zona_atual, caminho, {k: x.get() for k, x in vars_.items()})
            except M.ErroEditor as e:
                erros.append(str(e))
        self._recarregar_zonas(self.zona_atual)
        self._titulo()
        if erros:
            messagebox.showerror("Zona – corrija antes de seguir", "\n".join("• " + e for e in erros[:25]))
            return False
        self.sujo_zona = False
        self.v_zona_titulo.set(f"Zona {z['codigo']} – {z.get('nome')}   ({z.get('tipo')}, prioridade {z.get('prioridade')})   ✔ aplicada")
        self._carregar_cidade_na_tela()
        return True

    def nova_zona(self):
        if self.sujo_zona and not self.aplicar_zona():
            return
        w = tk.Toplevel(self)
        w.title("Nova zona")
        w.transient(self)
        v = {k: tk.StringVar(value=d) for k, d in (("codigo", ""), ("nome", ""), ("tipo", "base"), ("categoria", "outra"), ("prioridade", ""))}
        for i, (t, k, opc) in enumerate((("Código *", "codigo", None), ("Nome *", "nome", None), ("Tipo", "tipo", M.TIPOS_ZONA),
                                         ("Categoria normalizada", "categoria", M.CATEGORIAS), ("Prioridade (vazio: base 0, outras 1)", "prioridade", None))):
            rotulo_campo(w, t, i)
            (ttk.Combobox(w, textvariable=v[k], values=opc, state="readonly", width=34) if opc else
             ttk.Entry(w, textvariable=v[k], width=36)).grid(row=i, column=1, padx=6, pady=3)

        def ok():
            try:
                z = self.cidade.nova_zona(v["codigo"].get(), v["nome"].get(), v["tipo"].get(), v["prioridade"].get() or None, v["categoria"].get())
                w.destroy()
                self._recarregar_zonas(z["codigo"])
                self.mostrar_zona(z["codigo"])
                self.nb_zona.select(1)
                self._titulo()
            except M.ErroEditor as e:
                self.erro(e, "Nova zona")
        ttk.Button(w, text="Criar e preencher parâmetros ›", command=ok).grid(row=6, column=1, sticky="e", padx=6, pady=8)

    def remover_zona(self):
        if not self.zona_atual:
            return
        if not messagebox.askyesno(TITULO, f"Remover a zona {self.zona_atual} (parâmetros e geometria)?"):
            return
        try:
            self.cidade.remover_zona(self.zona_atual)
            self.sujo_zona = False
            self.mostrar_zona(None)
            self._recarregar_zonas()
            self._titulo()
        except M.ErroEditor as e:
            self.erro(e, "Remover zona")

    def _novo_outros(self):
        if not self.zona_atual:
            return
        w = tk.Toplevel(self)
        w.title("Parâmetro local (outros)")
        v = tk.StringVar()
        ttk.Label(w, text="Chave em snake_case (ex.: indice_elevacao). Use para índices locais desta zona;\n"
                          "para um atributo que vale para todas as zonas, prefira “Atributo adicional”.", padding=6).pack()
        ttk.Entry(w, textvariable=v, width=40).pack(padx=6)

        def ok():
            k = M.chave_snake(v.get())
            if not k:
                return
            z = self.cidade.zona(self.zona_atual)
            if k in ((z.get("parametros") or {}).get("outros") or {}):
                return self.erro("Já existe.")
            linha = len(self.linhas_param) + 1
            self._linha_param(self.rol_param.interno, linha, f"outros.{k}", f"outros › {k}", None, "numero", None, self.linhas_param)
            w.destroy()
        ttk.Button(w, text="Adicionar linha", command=ok).pack(pady=6)

    # ---- geometria
    def _info_geo(self):
        z = self.cidade.zona(self.zona_atual) if self.zona_atual else None
        if not z:
            self.v_geo_info.set("—")
            return
        g = z.get("geometria") or {}
        n = len(g.get("features") or [])
        cam = next((c for c in (self.cidade.dados.get("geografico") or {}).get("camadas") or [] if c.get("nome") == f"zona {z['codigo']}"), None)
        try:
            area = self.cidade.area_zona_m2(z["codigo"]) if n and n < 400 else None
        except Exception:  # noqa: BLE001
            area = None
        self.v_geo_info.set(f"Geometria atual: {n} feição(ões)"
                            + (f" · área {area / 1e4:,.2f} ha (EPSG:{self.cidade.epsg_area()})".replace(",", "X").replace(".", ",").replace("X", ".") if area else "")
                            + f" · {'OFICIAL' if g.get('oficial') else 'não oficial'}\nFonte: {g.get('fonte') or '—'}"
                            + (f"\nErro estimado: {cam.get('erro_estimado_m')} m · método: {cam.get('metodo')}" if cam else "")
                            + ("\n⚠ Sem geometria: a validação reprova até você anexar um arquivo." if not n else ""))

    def _escolher_geo(self):
        a = filedialog.askopenfilename(title="Geometria da zona", filetypes=[("Geometria", "*.kmz *.kml *.geojson *.json"), ("Todos", "*.*")])
        if not a:
            return
        self.v_g["arquivo"].set(a)
        try:
            geoms, epsg = M.ler_geometrias(a)
            self._geo_cache = (a, geoms)
            self.cb_g_campo["values"] = [""] + M.campos_atributo(geoms)
            self.v_g["campo"].set("")
            self.v_g["valor"].set("")
            if epsg and epsg != 4326:
                self.v_g["epsg"].set(str(epsg))
            self.status(f"{os.path.basename(a)}: {len(geoms)} feição(ões); CRS {'EPSG:' + str(epsg) if epsg else 'não declarado'}.")
        except Exception as e:  # noqa: BLE001
            self.erro(e, "Ler geometria")

    def _geo_campo_escolhido(self, _=None):
        a, geoms = getattr(self, "_geo_cache", (None, []))
        k = self.v_g["campo"].get()
        vals = sorted({str(p.get(k)) for p, _ in geoms if p.get(k) not in (None, "")}) if k else []
        self.cb_g_valor["values"] = vals
        if self.zona_atual in vals:
            self.v_g["valor"].set(self.zona_atual)

    def anexar_geometria(self):
        if not self.zona_atual:
            return messagebox.showinfo(TITULO, "Selecione a zona primeiro.")
        if self.sujo_zona and not self.aplicar_zona():
            return
        v = {k: x.get() for k, x in self.v_g.items()}
        if not v["arquivo"]:
            return messagebox.showinfo(TITULO, "Escolha o arquivo KMZ/KML/GeoJSON.")
        cod, oficial, subst = self.zona_atual, self.v_g_oficial.get(), self.v_g_subst.get()

        def fazer():
            return self.cidade.importar_geometria_zona(cod, v["arquivo"], oficial, v["erro"] or None, v["metodo"] or None, v["fonte"] or None,
                                                       v["epsg"] or None, v["campo"] or None, v["valor"] or None, subst)

        def fim(res, e):
            if e:
                return self.erro(e, "Anexar geometria")
            self._recarregar_zonas(cod)
            self._info_geo()
            self.desenhar(False)
            self._titulo()
            messagebox.showinfo(TITULO, f"Zona {cod}: {res['n_feicoes']} feição(ões) anexada(s); área {res['area_m2'] / 1e4:.2f} ha.\n"
                                        "O arquivo original será copiado para geo_raw/ ao salvar/exportar.")
        self.em_segundo_plano(fazer, fim, "Processando geometria…")

    def desenhar(self, cidade_inteira):
        """Pré-visualização simples. cidade_inteira=None → automático (só a zona, e nada em arquivos grandes)."""
        cv = self.canvas
        cv.delete("all")
        if cidade_inteira is None:
            if self._grande():
                cv.create_text(10, 10, anchor="nw", fill="#777", width=max(cv.winfo_width() - 20, 180),
                               text="Arquivo grande: a pré-visualização é sob demanda (botões abaixo).")
                return
            cidade_inteira = False
        try:
            itens = self.cidade.contornos(None if cidade_inteira else self.zona_atual) if (cidade_inteira or self.zona_atual) else []
        except Exception:  # noqa: BLE001
            itens = []
        pts = [p for _, _, an in itens for a in an for p in a]
        if not pts:
            cv.create_text(10, 10, anchor="nw", fill="#777", text="Sem geometria para mostrar.")
            return
        x1, y1 = min(p[0] for p in pts), min(p[1] for p in pts)
        x2, y2 = max(p[0] for p in pts), max(p[1] for p in pts)
        W, H = max(cv.winfo_width(), 200), max(cv.winfo_height(), 200)
        kx = math.cos(math.radians((y1 + y2) / 2))            # corrige o achatamento da longitude
        esc = min((W - 20) / max((x2 - x1) * kx, 1e-9), (H - 20) / max(y2 - y1, 1e-9))
        ox, oy = (W - (x2 - x1) * kx * esc) / 2, (H - (y2 - y1) * esc) / 2   # centraliza
        for cod, tipo, aneis in itens:
            cor = CORES.get(tipo, "#555")
            destaque = cod == self.zona_atual
            for a in aneis:
                xy = [c for x, y in a for c in (ox + (x - x1) * kx * esc, H - oy - (y - y1) * esc)]
                if len(xy) >= 4:
                    cv.create_line(*xy, fill=cor if destaque or not cidade_inteira else "#aab4c0", width=2 if destaque else 1)
        cv.create_text(W - 8, H - 8, anchor="se", fill="#777", text="EPSG:4326 · contornos simplificados")

    def _grande(self):
        try:
            return self.cidade.caminho and os.path.getsize(self.cidade.caminho) / 1e6 > GRANDE_MB
        except OSError:
            return False

    # ------------------------------------------------------------------ ATRIBUTOS ADICIONAIS
    def dialogo_atributo(self, chave=None):
        df = self.cidade.definicoes().get(chave) if chave else None
        w = tk.Toplevel(self)
        w.title("Editar atributo adicional" if df else "Novo atributo adicional (vale para todas as zonas)")
        w.transient(self)
        v = {k: tk.StringVar(value=(df or {}).get(k) or d) for k, d in (("rotulo", ""), ("chave", ""), ("unidade", ""), ("tipo", "numero"),
                                                                         ("descricao", ""), ("grupo", ""), ("fonte_id", ""))}
        if not df:
            v["rotulo"].trace_add("write", lambda *_: v["chave"].set(M.chave_snake(v["rotulo"].get())))
        linhas = [("Rótulo (nome exibido) *", "rotulo", None), ("Chave (snake_case, automática)", "chave", None),
                  ("Unidade (ex.: m, fracao, uh/ha)", "unidade", None), ("Tipo *", "tipo", M.TIPOS_ADICIONAL),
                  ("Descrição", "descricao", None), ("Grupo (opcional)", "grupo", None), ("Fonte padrão (opcional)", "fonte_id", [""] + self.cidade.ids_fontes())]
        for i, (t, k, opc) in enumerate(linhas):
            rotulo_campo(w, t, i)
            e = ttk.Combobox(w, textvariable=v[k], values=opc, state="readonly", width=38) if opc else ttk.Entry(w, textvariable=v[k], width=40)
            if df and k in ("chave", "tipo", "fonte_id"):
                e.configure(state="disabled")
            e.grid(row=i, column=1, padx=6, pady=3, sticky="ew")
        ttk.Label(w, text="Tipos: número · inteiro · fração (0–1, aceita 30%) · lista de códigos · texto livre.\n"
                          "O valor por zona tem o mesmo formato dos parâmetros (valor, unidade, fonte, artigo, observação, forma).",
                  foreground="#555", padding=6).grid(row=len(linhas), column=0, columnspan=2, sticky="w")

        def ok():
            try:
                if df:
                    self.cidade.editar_atributo(chave, v["rotulo"].get(), v["unidade"].get(), v["descricao"].get(), v["grupo"].get())
                else:
                    if self.sujo_zona and not self.aplicar_zona():
                        return
                    self.cidade.adicionar_atributo(v["rotulo"].get(), v["unidade"].get(), v["tipo"].get(), v["descricao"].get(),
                                                   v["chave"].get() or None, v["grupo"].get() or None, v["fonte_id"].get() or None)
                w.destroy()
                self._recarregar_atributos()
                self._montar_grades()
                self._titulo()
            except M.ErroEditor as e:
                self.erro(e, "Atributo")
        ttk.Button(w, text="Salvar atributo", command=ok).grid(row=len(linhas) + 1, column=1, sticky="e", padx=6, pady=8)

    def _montar_atributos(self):
        a = self.aba_atrib
        ttk.Label(a, style="Fluxo.TLabel", text="Catálogo de atributos adicionais da cidade (definicoes_parametros_adicionais, schema 1.2). "
                  "Cada atributo existe em todas as zonas; preencha os valores no passo ③ de cada zona ou por CSV.").pack(fill="x")
        cols = ("chave", "rotulo", "unidade", "tipo", "grupo", "preenchidas", "descricao")
        self.tv_atrib = ttk.Treeview(a, columns=cols, show="headings", height=14)
        for c, t, wd in zip(cols, ("Chave", "Rótulo", "Unidade", "Tipo", "Grupo", "Zonas preenchidas", "Descrição"), (170, 220, 90, 80, 100, 120, 380)):
            self.tv_atrib.heading(c, text=t)
            self.tv_atrib.column(c, width=wd, stretch=c == "descricao")
        self.tv_atrib.pack(fill="both", expand=True, pady=6)
        self.tv_atrib.bind("<Double-1>", lambda e: self._editar_atributo_sel())
        b = ttk.Frame(a)
        b.pack(fill="x")
        ttk.Button(b, text="+ Novo atributo…", command=self.dialogo_atributo).pack(side="left", padx=2)
        ttk.Button(b, text="Editar…", command=self._editar_atributo_sel).pack(side="left", padx=2)
        ttk.Button(b, text="Remover", command=self._remover_atributo_sel).pack(side="left", padx=2)

    def _recarregar_atributos(self):
        self.tv_atrib.delete(*self.tv_atrib.get_children())
        zonas = self.cidade.dados.get("zonas") or []
        for k, df in self.cidade.definicoes().items():
            n = sum(1 for z in zonas if (z.get("parametros_adicionais") or {}).get(k))
            self.tv_atrib.insert("", "end", iid=k, values=(k, df.get("rotulo"), df.get("unidade") or "—", df.get("tipo"), df.get("grupo") or "",
                                                           f"{n}/{len(zonas)}", df.get("descricao") or ""))

    def _editar_atributo_sel(self):
        sel = self.tv_atrib.selection()
        if sel:
            self.dialogo_atributo(sel[0])

    def _remover_atributo_sel(self):
        sel = self.tv_atrib.selection()
        if sel and messagebox.askyesno(TITULO, f"Remover o atributo '{sel[0]}' de TODAS as zonas?"):
            self.cidade.remover_atributo(sel[0])
            self._recarregar_atributos()
            self._montar_grades()
            self._titulo()

    # ------------------------------------------------------------------ IMPORTAR EM LOTE
    def _montar_lote(self):
        a = self.aba_lote
        a.columnconfigure(0, weight=1)
        a.columnconfigure(1, weight=1)
        a.rowconfigure(1, weight=1)
        g = ttk.LabelFrame(a, text="Geometrias de várias zonas de uma vez (KMZ / KML / GeoJSON com um campo = código da zona)", padding=6)
        g.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        self.v_l = {k: tk.StringVar() for k in ("arquivo", "campo", "epsg", "erro", "metodo", "fonte", "tipo")}
        self.v_l["tipo"].set("base")
        self.v_l_oficial, self.v_l_criar = tk.BooleanVar(value=False), tk.BooleanVar(value=False)
        rotulo_campo(g, "Arquivo *", 0)
        ttk.Entry(g, textvariable=self.v_l["arquivo"]).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(g, text="Escolher…", command=self._lote_escolher).grid(row=0, column=2)
        rotulo_campo(g, "Campo com o código da zona *", 1)
        self.cb_l_campo = ttk.Combobox(g, textvariable=self.v_l["campo"], state="readonly")
        self.cb_l_campo.grid(row=1, column=1, sticky="ew", padx=4)
        rotulo_campo(g, "EPSG de origem (vazio = automático)", 2)
        ttk.Entry(g, textvariable=self.v_l["epsg"]).grid(row=2, column=1, sticky="ew", padx=4)
        ttk.Checkbutton(g, text="Geometria OFICIAL", variable=self.v_l_oficial).grid(row=3, column=1, sticky="w", padx=4)
        rotulo_campo(g, "Erro estimado (m)", 4)
        ttk.Entry(g, textvariable=self.v_l["erro"]).grid(row=4, column=1, sticky="ew", padx=4)
        rotulo_campo(g, "Método", 5)
        ttk.Entry(g, textvariable=self.v_l["metodo"]).grid(row=5, column=1, sticky="ew", padx=4)
        rotulo_campo(g, "Fonte", 6)
        cb = ttk.Combobox(g, textvariable=self.v_l["fonte"], state="readonly")
        cb.grid(row=6, column=1, sticky="ew", padx=4)
        self._combos_fonte.append(cb)
        ttk.Checkbutton(g, text="Criar zonas que faltam – tipo:", variable=self.v_l_criar).grid(row=7, column=1, sticky="w", padx=4)
        ttk.Combobox(g, textvariable=self.v_l["tipo"], values=M.TIPOS_ZONA, state="readonly", width=12).grid(row=7, column=2)
        ttk.Button(g, text="Importar geometrias", command=self._lote_geo).grid(row=8, column=1, sticky="e", pady=6)
        g.columnconfigure(1, weight=1)
        c = ttk.LabelFrame(a, text="Parâmetros em lote por CSV", padding=6)
        c.grid(row=0, column=1, sticky="nsew", padx=4, pady=4)
        ttk.Label(c, wraplength=540, justify="left", text=
                  "Colunas: zona, parametro, valor, unidade, fonte_id, artigo [, observacao, forma]\n"
                  "• Separador ; ou , (detectado). Decimal com vírgula aceito; taxas em 0,3 ou 30%.\n"
                  "• parametro = caminho padrão (ca_basico, taxa_ocupacao, recuos.frontal…), outros.<chave>, "
                  "o rótulo/chave de um atributo adicional, ou um nome novo → cria o atributo adicional em todas as zonas.\n"
                  "• Valor vazio = sem dado (lacuna). Uma linha com erro não impede as outras.").pack(anchor="w")
        b = ttk.Frame(c)
        b.pack(fill="x", pady=6)
        ttk.Button(b, text="Salvar modelo CSV…", command=self._csv_modelo).pack(side="left", padx=2)
        ttk.Button(b, text="Importar CSV…", command=self._csv_importar).pack(side="left", padx=2)
        r = ttk.LabelFrame(a, text="Resultado", padding=6)
        r.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=4, pady=4)
        self.txt_lote = tk.Text(r, height=12)
        self.txt_lote.pack(fill="both", expand=True)

    def _lote_escolher(self):
        a = filedialog.askopenfilename(title="Geometrias das zonas", filetypes=[("Geometria", "*.kmz *.kml *.geojson *.json"), ("Todos", "*.*")])
        if not a:
            return
        self.v_l["arquivo"].set(a)
        try:
            geoms, epsg = M.ler_geometrias(a)
            campos = M.campos_atributo(geoms)
            self.cb_l_campo["values"] = campos
            for k in ("codigo", "zona", "ZONA", "sigla", "SIGLA", "nome"):
                if k in campos:
                    self.v_l["campo"].set(k)
                    break
            if epsg and epsg != 4326:
                self.v_l["epsg"].set(str(epsg))
            self._log_lote(f"{os.path.basename(a)}: {len(geoms)} feição(ões), campos: {', '.join(campos)}")
        except Exception as e:  # noqa: BLE001
            self.erro(e, "Ler geometria")

    def _log_lote(self, texto):
        self.txt_lote.insert("end", texto + "\n")
        self.txt_lote.see("end")

    def _lote_geo(self):
        v = {k: x.get() for k, x in self.v_l.items()}
        if not v["arquivo"] or not v["campo"]:
            return messagebox.showinfo(TITULO, "Escolha o arquivo e o campo com o código da zona.")
        if self.sujo_zona and not self.aplicar_zona():
            return
        oficial, criar = self.v_l_oficial.get(), self.v_l_criar.get()

        def fim(res, e):
            if e:
                return self.erro(e, "Importar geometrias")
            for x in res["atribuidas"]:
                self._log_lote(f"✔ {x['zona']}: {x['n_feicoes']} feição(ões), {x['area_m2'] / 1e4:.2f} ha")
            for x in res["criadas"]:
                self._log_lote(f"+ zona criada: {x}")
            for x in res["ignoradas"]:
                self._log_lote(f"– ignorada: {x}")
            for x in res["erros"]:
                self._log_lote(f"✖ {x}")
            self._recarregar_zonas()
            self.mostrar_zona(self.zona_atual)
            self._titulo()
        self.em_segundo_plano(lambda: self.cidade.importar_geometrias_lote(
            v["arquivo"], v["campo"], oficial, v["erro"] or None, v["metodo"] or None, v["fonte"] or None, v["epsg"] or None,
            criar, v["tipo"] or "base"), fim, "Importando geometrias…")

    def _csv_modelo(self):
        a = filedialog.asksaveasfilename(title="Salvar modelo CSV", defaultextension=".csv", initialfile="parametros_modelo.csv")
        if a:
            open(a, "w", encoding="utf-8-sig", newline="").write(M.Cidade.modelo_csv())
            self._log_lote(f"Modelo salvo em {a}")

    def _csv_importar(self):
        a = filedialog.askopenfilename(title="CSV de parâmetros", filetypes=[("CSV", "*.csv *.txt"), ("Todos", "*.*")])
        if not a:
            return
        if self.sujo_zona and not self.aplicar_zona():
            return
        try:
            r = self.cidade.importar_parametros_csv(a)
        except M.ErroEditor as e:
            return self.erro(e, "CSV")
        self._log_lote(f"CSV {os.path.basename(a)}: {r['aplicadas']} linha(s) aplicada(s), {len(r['erros'])} com erro.")
        for k in r["criados"]:
            self._log_lote(f"+ atributo adicional criado: {k}")
        for n, m in r["erros"]:
            self._log_lote(f"✖ linha {n}: {m}")
        self._recarregar_atributos()
        self.mostrar_zona(self.zona_atual)
        self._carregar_cidade_na_tela()
        self._titulo()

    # ------------------------------------------------------------------ VALIDAÇÃO
    def _montar_validacao(self):
        a = self.aba_val
        t = ttk.Frame(a)
        t.pack(fill="x")
        ttk.Button(t, text="Validar agora", command=self.validar).pack(side="left")
        self.v_val = tk.StringVar(value="Ainda não validado. O validador embutido é o mesmo da plataforma (schema 1.2 + checagens).")
        self.lb_val = ttk.Label(t, textvariable=self.v_val, padding=(10, 0), font=("TkDefaultFont", 11, "bold"))
        self.lb_val.pack(side="left")
        cols = ("nivel", "zona", "campo", "mensagem")
        self.tv_val = ttk.Treeview(a, columns=cols, show="headings")
        for c, tt, w in zip(cols, ("Nível", "Zona", "Campo", "Mensagem"), (70, 150, 260, 800)):
            self.tv_val.heading(c, text=tt)
            self.tv_val.column(c, width=w, stretch=c == "mensagem")
        self.tv_val.tag_configure("ERRO", foreground="#b00020")
        self.tv_val.tag_configure("AVISO", foreground="#8a6d00")
        self.tv_val.pack(fill="both", expand=True, pady=6)
        self.tv_val.bind("<Double-1>", self._ir_para_problema)
        ttk.Label(a, text="Duplo clique numa linha leva à zona/passo correspondente.", foreground="#555").pack(anchor="w")

    def validar(self, depois=None):
        if self.sujo_zona and not self.aplicar_zona():
            return

        def fim(res, e):
            if e:
                return self.erro(e, "Validar")
            self.ultima_validacao = res
            self.tv_val.delete(*self.tv_val.get_children())
            for i, (nivel, zona, campo, msg) in enumerate(self.cidade.problemas_legiveis(res)):
                self.tv_val.insert("", "end", iid=f"p{i}", values=(nivel, zona, campo, msg), tags=(nivel,))
            ok = res["ok"]
            self.v_val.set(f"{'APROVADO' if ok else 'REPROVADO'} – {len(res['erros'])} erro(s), {len(res['avisos'])} aviso(s) · "
                           f"{res['resumo'].get('tamanho_mb')} MB")
            self.lb_val.configure(style="Ok.TLabel" if ok else "Erro.TLabel")
            if depois:
                depois(res)
            else:
                self.nb.select(self.aba_val)
        self.em_segundo_plano(self.cidade.validar, fim, "Validando…")

    def _ir_para_problema(self, _=None):
        sel = self.tv_val.selection()
        if not sel:
            return
        _, zona, campo, _ = self.tv_val.item(sel[0], "values")
        if zona and self.cidade.zona(zona):
            self.nb.select(self.aba_zonas)
            self.v_filtro.set("")
            self._recarregar_zonas(zona)
            self.mostrar_zona(zona)
            passo = 3 if "geometria" in campo or "feições" in self.tv_val.item(sel[0], "values")[3] else \
                2 if "parametros_adicionais" in campo else 1 if campo.startswith("parametros") else 0
            self.nb_zona.select(passo)
        elif campo.startswith(("fontes", "centro_mapa", "codigo_ibge", "uf", "slug", "municipio")):
            self.nb.select(self.aba_cidade)
        elif "definicoes_parametros_adicionais" in campo:
            self.nb.select(self.aba_atrib)

    # ------------------------------------------------------------------ ARQUIVOS
    def _titulo(self):
        d = self.cidade.dados
        nome = f"{d.get('municipio') or '(nova cidade)'}{'/' + d['uf'] if d.get('uf') else ''}"
        self.var_titulo.set(f"{nome}   ·   slug {d.get('slug') or '—'}   ·   schema {d.get('schema_versao')}   ·   "
                            f"{len(d.get('zonas') or [])} zona(s)   ·   {self.cidade.caminho or 'não salvo'}" + ("   ·   ● alterado" if self.cidade.alterado else ""))
        self.title(f"{'● ' if self.cidade.alterado else ''}{nome} – {TITULO}")

    def recarregar_tudo(self):
        self.zona_atual = None
        self.sujo_zona = False
        self._atualizar_plataforma()
        self._carregar_cidade_na_tela()
        self._recarregar_zonas()
        self._recarregar_atributos()
        self.mostrar_zona(None)
        self.tv_val.delete(*self.tv_val.get_children())
        self.v_val.set("Ainda não validado.")
        self._titulo()
        zs = self.cidade.codigos()
        if zs:
            self._recarregar_zonas(zs[0])
            self.mostrar_zona(zs[0])

    def _pode_descartar(self):
        return not self.cidade.alterado or messagebox.askyesno(TITULO, "Descartar as alterações não salvas?")

    def nova_cidade(self):
        if self._pode_descartar():
            self.cidade = M.Cidade()
            self.recarregar_tudo()
            self.nb.select(self.aba_cidade)
            self.status("Nova cidade: preencha os metadados e as fontes; depois vá para Zonas.")

    def abrir_caminho(self, caminho):
        """Abre um JSON ou a PASTA de uma cidade em segundo plano (o Rio, 18 MB, não trava a janela)."""
        func = (lambda: M.Cidade.abrir_pasta(caminho)) if os.path.isdir(caminho) else (lambda: M.Cidade.abrir(caminho))

        def fim(c, e):
            if e:
                return self.erro(e, "Abrir")
            self.cidade = c
            self.recarregar_tudo()
            n = len(c.dados.get("zonas") or [])
            self.status(f"Aberto: {c.caminho} ({n} zonas). Geometrias não são desenhadas automaticamente em arquivos grandes.")
        self.em_segundo_plano(func, fim, f"Abrindo {os.path.basename(caminho.rstrip(os.sep))}…")

    def abrir_json(self):
        if self._pode_descartar():
            a = filedialog.askopenfilename(title="Abrir JSON de cidade", filetypes=[("JSON", "*.json"), ("Todos", "*.*")])
            if a:
                self.abrir_caminho(a)

    def abrir_pasta(self):
        if self._pode_descartar():
            ini = os.path.join(self.plataforma.get(), "cidades") if self.plataforma.get() else None
            p = filedialog.askdirectory(title="Pasta da cidade (ex.: cidades/curitiba-pr)", initialdir=ini)
            if p:
                self.abrir_caminho(p)

    def abrir_da_plataforma(self):
        slug = self.combo_plat.get()
        if not self.plataforma.get() or slug not in (self.combo_plat["values"] or ()):
            return messagebox.showinfo(TITULO, "Configure a pasta da plataforma (aba Cidade) e escolha a cidade na lista ao lado.")
        if self._pode_descartar():
            self.abrir_caminho(os.path.join(self.plataforma.get(), "cidades", slug))

    def _antes_de_gravar(self):
        if self.sujo_zona and not self.aplicar_zona():
            return False
        if not self.cidade.slug and not self.aplicar_metadados():
            return False
        return True

    def _gravar(self, func, descricao):
        def fim(res, e):
            if e:
                return self.erro(e, descricao)
            self._titulo()
            self._carregar_cidade_na_tela()
            self.status(f"{descricao}: {res}")
            messagebox.showinfo(TITULO, f"{descricao}:\n{res}")
        self.em_segundo_plano(func, fim, descricao + "…")

    def salvar_plataforma(self):
        if not self._antes_de_gravar():
            return
        p = self.plataforma.get()
        if not p or not os.path.isdir(os.path.join(p, "cidades")):
            return messagebox.showinfo(TITULO, "Plataforma não configurada. Use “Exportar pasta da cidade” ou configure o caminho na aba Cidade.")

        def depois(res):
            if not res["ok"] and not messagebox.askyesno(TITULO, "A validação REPROVOU – a plataforma vai ignorar esta cidade até corrigir.\n"
                                                                 "Salvar mesmo assim?"):
                return
            self._gravar(lambda: self.cidade.salvar_na_plataforma(p), "Salvo na plataforma (backup .bak do anterior)")
        self.validar(depois)

    def salvar_como(self):
        if not self._antes_de_gravar():
            return
        a = filedialog.asksaveasfilename(title="Salvar como", defaultextension=".json", initialfile=f"{self.cidade.slug or 'cidade'}.json")
        if a:
            self._gravar(lambda: self.cidade.salvar_como(a), "Salvo")

    def exportar(self):
        if not self._antes_de_gravar():
            return
        destino = filedialog.askdirectory(title="Exportar: escolha a pasta de destino (será criada <destino>/<slug>/)")
        if not destino:
            return

        def depois(res):
            rasc = False
            if not res["ok"]:
                if not messagebox.askyesno(TITULO, f"Validação REPROVADA ({len(res['erros'])} erro(s)).\n"
                                                   "Exportar como RASCUNHO em <slug>__RASCUNHO/ (a plataforma ignora)?"):
                    return
                rasc = True
            self._gravar(lambda: self.cidade.exportar_pasta(destino, rascunho=rasc, validacao=res)[0],
                         "Pasta exportada (copie-a para plataforma/cidades/ e reinicie a app)" if not rasc else "Rascunho exportado")
        self.validar(depois)

    def atualizar_no_lugar(self):
        if not self._antes_de_gravar():
            return
        pasta = getattr(self.cidade, "pasta_origem", None) or (os.path.dirname(self.cidade.caminho) if self.cidade.caminho else None)
        if not pasta:
            return messagebox.showinfo(TITULO, "Abra a cidade pela pasta (Atualizar cidade existente) ou use Exportar pasta.")

        def depois(res):
            if not res["ok"]:
                return messagebox.showerror(TITULO, "Validação REPROVADA – corrija antes de sobrescrever a pasta (veja a aba Validação).")
            if messagebox.askyesno(TITULO, f"Sobrescrever {pasta}?\nO JSON anterior fica como .bak; fontes/, geo_raw/, scripts/ e "
                                           "REFERENCIAS.md existentes são preservados."):
                self._gravar(lambda: self.cidade.atualizar_no_lugar()[0], "Pasta atualizada no lugar")
        self.validar(depois)


def main():
    app = Editor(sys.argv[1] if len(sys.argv) > 1 else None)
    app.mainloop()


if __name__ == "__main__":
    main()
