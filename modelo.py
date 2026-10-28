"""Camada de MODELO do editor desktop de cidades (sem nenhuma dependência de interface gráfica).

Tudo o que a interface (editor.py) faz passa por aqui, e os testes (testes/test_modelo.py) usam só este módulo.
Princípios:
  * o JSON aberto é mantido como dict "cru" (Cidade.dados): campos que o editor não conhece são preservados;
  * nada é alterado só por abrir e salvar (o teste de ida e volta garante isso em Campo Grande e Curitiba);
  * a validação usa o validador EMBUTIDO (validador/validar_cidade.py – cópia idêntica ao da plataforma).
"""
import csv
import datetime as _dt
import io
import json
import math
import os
import re
import shutil
import sys
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
import zipfile

AQUI = os.path.dirname(os.path.abspath(__file__))
PASTA_VALIDADOR = os.path.join(AQUI, "validador")
if PASTA_VALIDADOR not in sys.path:
    sys.path.insert(0, PASTA_VALIDADOR)
import validar_cidade as _val  # noqa: E402  (cópia embutida – mesmo arquivo da plataforma)

VERSAO_SCHEMA = "1.2"
ARQ_CONFIG = os.path.join(os.path.expanduser("~"), ".editor_zoneamento.json")

# ---------------------------------------------------------------------------
# Vocabulários (iguais ao schema)
# ---------------------------------------------------------------------------
CATEGORIAS = ["residencial_baixa_densidade", "residencial_media_densidade", "residencial_alta_densidade",
              "mista_baixa_densidade", "mista_media_densidade", "mista_alta_densidade", "centralidade", "eixo",
              "especial_interesse_social", "especial_economica", "industrial", "ambiental", "patrimonio_cultural",
              "institucional", "expansao", "rural", "outra"]
TIPOS_ZONA = ["base", "sobreposta", "eixo"]
EFEITOS = ["substitui", "usa_indices_de", "apenas_alerta"]
FORMAS = ["unico", "faixa", "condicional", "formula", "lista", "livre", "herda_da_base", "nao_aplicavel", "sem_dado", "texto"]
FORMAS_CASO = [f for f in FORMAS if f != "condicional"]
TIPOS_ADICIONAL = ["numero", "inteiro", "fracao", "lista", "texto"]
TIPOS_ADICIONAL_TXT = {"numero": "número", "inteiro": "inteiro", "fracao": "fração 0–1 (taxas, %)", "lista": "lista de códigos",
                       "texto": "texto livre"}
EXTRAS_PARAM = ("faixa", "condicionais", "formula", "texto_original")

# Parâmetros padrão: (caminho, rótulo, unidade travada | lista de opções | None = livre, tipo do valor)
PARAMETROS_PADRAO = [
    ("ca_minimo", "CA mínimo", "coeficiente", "numero"),
    ("ca_basico", "CA básico", "coeficiente", "numero"),
    ("ca_maximo", "CA máximo", "coeficiente", "numero"),
    ("taxa_ocupacao", "Taxa de ocupação", "fracao", "fracao"),
    ("gabarito_altura_max_m", "Gabarito – altura máx.", "m", "numero"),
    ("gabarito_pavimentos", "Gabarito – pavimentos", "pavimentos", "inteiro"),
    ("taxa_permeabilidade", "Taxa de permeabilidade", "fracao", "fracao"),
    ("recuos.frontal", "Recuo frontal", "m", "numero"),
    ("recuos.lateral", "Recuo lateral", "m", "numero"),
    ("recuos.fundos", "Recuo de fundos", "m", "numero"),
    ("lote_minimo_m2", "Lote mínimo", "m2", "numero"),
    ("testada_minima_m", "Testada mínima", "m", "numero"),
    ("usos_permitidos", "Usos permitidos", "codigos_de_uso", "lista"),
    ("vagas", "Vagas", None, "numero"),
    ("densidade", "Densidade", ["hab/ha", "uh/ha"], "numero"),
]
PADRAO_POR_CAMINHO = {p[0]: p for p in PARAMETROS_PADRAO}
CHAVES_TOPO_PARAMETROS = ["ca_minimo", "ca_basico", "ca_maximo", "taxa_ocupacao", "gabarito_altura_max_m", "gabarito_pavimentos",
                          "taxa_permeabilidade", "recuos", "lote_minimo_m2", "testada_minima_m", "usos_permitidos", "vagas",
                          "densidade", "outros"]


class ErroEditor(ValueError):
    """Erro de preenchimento com mensagem legível em português."""


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def slugify(texto):
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def slug_cidade(municipio, uf):
    return slugify(f"{municipio} {uf}")


def chave_snake(texto):
    return re.sub(r"_+", "_", slugify(texto).replace("-", "_")).strip("_")


def hoje():
    return _dt.date.today().isoformat()


def epsg_utm(lon, lat):
    """EPSG da zona UTM SIRGAS 2000 do ponto (mesma regra do motor da plataforma)."""
    zona = int(math.floor((lon + 180) / 6)) + 1
    if -75 <= lon <= -28 and -35 <= lat <= 6:
        if lat < 0 and 18 <= zona <= 25:
            return 31960 + zona
        if lat >= 0 and 18 <= zona <= 22:
            return 31954 + zona
    return (32700 if lat < 0 else 32600) + zona


def numero(texto, tipo="numero", rotulo="valor"):
    """'1,5' → 1.5; '30%' → 0.3 (só fração); '' → None. Erros com mensagem legível."""
    if texto is None:
        return None
    if isinstance(texto, (int, float)) and not isinstance(texto, bool):
        v = texto
    else:
        t = str(texto).strip().replace(" ", "")
        if not t:
            return None
        pct = t.endswith("%")
        t = t.rstrip("%")
        if "," in t and "." in t:
            t = t.replace(".", "").replace(",", ".")
        t = t.replace(",", ".")
        try:
            v = float(t)
        except ValueError:
            raise ErroEditor(f"{rotulo}: '{texto}' não é um número.")
        if pct:
            if tipo != "fracao":
                raise ErroEditor(f"{rotulo}: '%' só é aceito em taxas (fração).")
            v = v / 100
    if tipo == "fracao" and not (0 <= v <= 1):
        raise ErroEditor(f"{rotulo}: taxa deve ser fração 0–1 (30% → 0,3 ou digite 30%). Recebido {v}.")
    if tipo == "inteiro":
        if float(v) != int(v):
            raise ErroEditor(f"{rotulo}: deve ser inteiro.")
        return int(v)
    v = float(v)
    return int(v) if v.is_integer() and tipo != "fracao" and abs(v) < 1e15 else round(v, 10)


def fmt_num(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v)) if abs(v) < 1e15 else repr(v)
    return str(v).replace(".", ",") if isinstance(v, float) else str(v)


def get_caminho(d, caminho):
    for k in caminho.split("."):
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def set_caminho(d, caminho, valor):
    ks = caminho.split(".")
    for k in ks[:-1]:
        if not isinstance(d.get(k), dict):
            d[k] = {}
        d = d[k]
    d[ks[-1]] = valor


# ---------------------------------------------------------------------------
# Parâmetro  <->  campos do formulário
# ---------------------------------------------------------------------------
CAMPOS_VAZIOS = {"valor": "", "unidade": "", "fonte_id": "", "artigo_anexo": "", "observacao": "", "forma": "", "estrutura": ""}


def campos_de_parametro(p, tipo="numero"):
    """Parâmetro (dict ou None) → campos de texto do formulário."""
    if not isinstance(p, dict):
        return dict(CAMPOS_VAZIOS)
    v = p.get("valor")
    texto_no_valor = p.get("forma") == "texto" and v is None
    if isinstance(v, list):
        tv = ", ".join(map(str, v))
    elif texto_no_valor:
        tv = p.get("texto_original") or ""
    else:
        tv = fmt_num(v)
    extra = {k: p[k] for k in EXTRAS_PARAM if k in p and not (k == "texto_original" and texto_no_valor)}
    return {"valor": tv, "unidade": p.get("unidade") or "", "fonte_id": p.get("fonte_id") or "",
            "artigo_anexo": p.get("artigo_anexo") or "", "observacao": p.get("observacao") or "",
            "forma": p.get("forma") or "", "estrutura": json.dumps(extra, ensure_ascii=False) if extra else ""}


def _caso_valido(c, rotulo, tipo, i):
    if not isinstance(c, dict) or "condicao" not in c or "forma" not in c:
        raise ErroEditor(f"{rotulo}: condicional #{i + 1} precisa de 'condicao' e 'forma'.")
    if c["forma"] not in FORMAS_CASO:
        raise ErroEditor(f"{rotulo}: condicional #{i + 1} com forma '{c['forma']}' inválida.")
    c.setdefault("valor", None)
    if c["forma"] == "unico":
        c["valor"] = numero(c["valor"], tipo, f"{rotulo} (condicional #{i + 1})")
        if c["valor"] is None:
            raise ErroEditor(f"{rotulo}: condicional #{i + 1} com forma 'unico' precisa de valor.")
    if c["forma"] == "faixa":
        fx = c.get("faixa")
        if not isinstance(fx, dict) or "min" not in fx or "max" not in fx:
            raise ErroEditor(f"{rotulo}: condicional #{i + 1} com forma 'faixa' precisa de faixa {{min, max}}.")
    return c


def parametro_de_campos(campos, unidade_fixa=None, tipo="numero", rotulo="parâmetro", original=None):
    """Campos do formulário → parâmetro do schema (ou None).

    Regras:  tudo vazio → None;  valor vazio sem estrutura → forma 'sem_dado' (lacuna; o motivo vai em observação);
    'estrutura' = JSON com faixa / condicionais / formula / texto_original (editor estruturado ou JSON inline).
    Se os campos não mudaram em relação a `original`, devolve o próprio `original` (preserva tudo, inclusive chaves extras)."""
    normal = {k: str(campos.get(k) or "").strip() for k in CAMPOS_VAZIOS}
    antes = {k: str(v).strip() for k, v in campos_de_parametro(original, tipo).items()}
    if normal == antes:
        return original
    c = normal
    if not any(c.values()):
        return None
    unidade = unidade_fixa if isinstance(unidade_fixa, str) else (c["unidade"] or None)
    if isinstance(unidade_fixa, list) and unidade and unidade not in unidade_fixa:
        raise ErroEditor(f"{rotulo}: unidade '{unidade}' inválida (use {' ou '.join(unidade_fixa)}).")
    extra = {}
    if c["estrutura"]:
        try:
            extra = json.loads(c["estrutura"])
        except json.JSONDecodeError as e:
            raise ErroEditor(f"{rotulo}: estrutura JSON inválida ({e.msg}, coluna {e.colno}).")
        if not isinstance(extra, dict) or set(extra) - set(EXTRAS_PARAM):
            raise ErroEditor(f"{rotulo}: a estrutura só aceita as chaves {', '.join(EXTRAS_PARAM)}.")
    forma, valor = c["forma"], None
    if forma == "lista" or (tipo == "lista" and forma in ("", "lista")):
        valor = [x.strip() for x in re.split(r"[;,]", c["valor"]) if x.strip()] or None
        forma = forma or ("lista" if valor else "")
    elif forma == "texto" or (tipo == "texto" and forma in ("", "texto")):
        if c["valor"]:
            extra["texto_original"] = c["valor"]
        forma = "texto" if extra.get("texto_original") else forma
    elif c["valor"]:
        valor = numero(c["valor"], "fracao" if tipo == "fracao" else ("inteiro" if tipo == "inteiro" else "numero"), rotulo)
        forma = forma or "unico"
    if not forma:
        forma = ("condicional" if "condicionais" in extra else "formula" if "formula" in extra
                 else "faixa" if "faixa" in extra else "sem_dado")
    if forma not in FORMAS:
        raise ErroEditor(f"{rotulo}: forma '{forma}' inválida.")
    if forma not in ("unico", "lista") and valor is not None:
        raise ErroEditor(f"{rotulo}: com forma '{forma}' o campo valor deve ficar vazio (use o editor de estrutura).")
    if forma == "unico" and valor is None:
        raise ErroEditor(f"{rotulo}: forma 'unico' exige valor numérico.")
    if forma == "lista" and not isinstance(valor, list):
        raise ErroEditor(f"{rotulo}: forma 'lista' exige valores separados por vírgula.")
    num_tipo = tipo if tipo in ("fracao", "inteiro") else "numero"
    if forma == "faixa" or (forma == "formula" and "faixa" in extra):
        fx = extra.get("faixa")
        if not isinstance(fx, dict) or "min" not in fx or "max" not in fx:
            raise ErroEditor(f"{rotulo}: forma 'faixa' exige faixa {{min, max}} (null = sem limite).")
        extra["faixa"] = {"min": numero(fx["min"], num_tipo, rotulo + " (mín.)"), "max": numero(fx["max"], num_tipo, rotulo + " (máx.)")}
    if forma == "condicional":
        cs = extra.get("condicionais")
        if not isinstance(cs, list) or not cs:
            raise ErroEditor(f"{rotulo}: forma 'condicional' exige ao menos um caso em condicionais.")
        extra["condicionais"] = [_caso_valido(dict(x), rotulo, num_tipo, i) for i, x in enumerate(cs)]
    if forma == "formula" and not isinstance(extra.get("formula"), str):
        raise ErroEditor(f"{rotulo}: forma 'formula' exige o texto da fórmula (ex.: \"h/6\").")
    if forma == "texto" and not extra.get("texto_original"):
        raise ErroEditor(f"{rotulo}: forma 'texto' exige o texto original.")
    fonte = c["fonte_id"] or None
    if forma != "sem_dado" and not fonte:
        raise ErroEditor(f"{rotulo}: escolha a fonte (fonte_id) – todo parâmetro com conteúdo precisa de citação.")
    p = {"valor": valor, "unidade": unidade, "fonte_id": fonte, "artigo_anexo": c["artigo_anexo"] or None,
         "observacao": c["observacao"] or None, "forma": forma}
    for k in EXTRAS_PARAM:
        if k in extra:
            p[k] = extra[k]
    return p


# ---------------------------------------------------------------------------
# Leitura de geometrias: KML / KMZ / GeoJSON
# ---------------------------------------------------------------------------
def _local(el):
    return el.tag.rsplit("}", 1)[-1]


def _coords_kml(texto):
    pts = []
    for tupla in (texto or "").split():
        p = tupla.split(",")
        if len(p) >= 2:
            pts.append((float(p[0]), float(p[1])))
    return pts


def _geoms_kml(el):
    from shapely.geometry import Polygon, LineString, Point
    out = []
    for g in el.iter():
        t = _local(g)
        if t == "Polygon":
            ext, ints = None, []
            for sub in g:
                if _local(sub) in ("outerBoundaryIs", "innerBoundaryIs"):
                    c = next((x for x in sub.iter() if _local(x) == "coordinates"), None)
                    anel = _coords_kml(c.text if c is not None else "")
                    if _local(sub) == "outerBoundaryIs":
                        ext = anel
                    elif len(anel) >= 3:
                        ints.append(anel)
            if ext and len(ext) >= 3:
                out.append(Polygon(ext, ints))
        elif t in ("LineString", "Point"):
            c = next((x for x in g if _local(x) == "coordinates"), None)
            pts = _coords_kml(c.text if c is not None else "")
            if t == "LineString" and len(pts) >= 2:
                out.append(LineString(pts))
            elif t == "Point" and pts:
                out.append(Point(pts[0]))
    return out


def _props_kml(pm):
    props = {}
    for x in pm:
        if _local(x) == "name" and x.text:
            props["nome"] = x.text.strip()
    for x in pm.iter():
        if _local(x) == "Data" and x.get("name"):
            v = next((y.text for y in x if _local(y) == "value"), None)
            props[x.get("name")] = (v or "").strip()
        elif _local(x) == "SimpleData" and x.get("name"):
            props[x.get("name")] = (x.text or "").strip()
    return props


def _ler_kml_bytes(b):
    import shapely
    raiz = ET.fromstring(b)
    out = []
    for pm in (x for x in raiz.iter() if _local(x) == "Placemark"):
        gs = _geoms_kml(pm)
        if not gs:
            continue
        g = gs[0] if len(gs) == 1 else shapely.GeometryCollection(gs)
        out.append((_props_kml(pm), g))
    return out


def _epsg_geojson(obj):
    crs = obj.get("crs") if isinstance(obj, dict) else None
    nome = ((crs.get("properties") or {}).get("name") or "") if isinstance(crs, dict) else ""
    if "CRS84" in nome.upper():
        return 4326
    m = re.search(r"EPSG:+(\d{4,5})", nome.upper().replace("::", ":"))
    return int(m.group(1)) if m else None


def ler_geometrias(caminho):
    """→ (lista [(props, geometria shapely)], epsg_detectado ou None).  KML/KMZ são sempre EPSG:4326."""
    from shapely.geometry import shape
    n = caminho.lower()
    b = open(caminho, "rb").read()
    if n.endswith((".geojson", ".json")):
        obj = json.loads(b.decode("utf-8-sig"))
        epsg = _epsg_geojson(obj)
        if obj.get("type") == "FeatureCollection":
            feats = obj.get("features") or []
        elif obj.get("type") == "Feature":
            feats = [obj]
        else:
            feats = [{"type": "Feature", "properties": {}, "geometry": obj}]
        return [((f.get("properties") or {}), shape(f["geometry"])) for f in feats if f.get("geometry")], epsg
    if n.endswith(".kmz") or b[:2] == b"PK":
        out = []
        with zipfile.ZipFile(io.BytesIO(b)) as z:
            kmls = sorted((x for x in z.namelist() if x.lower().endswith(".kml")), key=lambda x: (x.lower() != "doc.kml", x))
            if not kmls:
                raise ErroEditor("KMZ sem arquivo .kml dentro.")
            for k in kmls:
                out += _ler_kml_bytes(z.read(k))
        return out, 4326
    if n.endswith(".kml"):
        return _ler_kml_bytes(b), 4326
    raise ErroEditor("Formato não suportado: use .kmz, .kml, .geojson ou .json.")


def parece_lonlat(geoms):
    for _, g in geoms[:200]:
        x1, y1, x2, y2 = g.bounds
        if not (-180 <= x1 <= 180 and -180 <= x2 <= 180 and -90 <= y1 <= 90 and -90 <= y2 <= 90):
            return False
    return True


def campos_atributo(geoms):
    """Campos de atributo presentes nas feições (para escolher o campo da importação em lote)."""
    vistos = []
    for p, _ in geoms:
        for k in p:
            if k not in vistos:
                vistos.append(k)
    return vistos


def _transf(f):
    import numpy as np
    return lambda xy: np.column_stack(f(xy[:, 0], xy[:, 1]))


def _arredondar(g, casas=6):
    import numpy as np
    import shapely
    return shapely.transform(g, lambda xy: np.round(xy, casas))


def _partes(g, filtro):
    return [p for x in getattr(g, "geoms", [g]) for p in getattr(x, "geoms", [x]) if filtro in p.geom_type and not p.is_empty]


def processar_geometria(g, epsg_origem, epsg_area, esperado="poligono", simplificar_m=2.0):
    """Reprojeta para o CRS métrico, make_valid, simplifica ~2 m, volta para EPSG:4326 e arredonda a 6 casas.
    Devolve (geometria 4326 ou None, área m², comprimento m) – área/comprimento medidos no CRS métrico."""
    import shapely
    from pyproj import Transformer
    from shapely.geometry import MultiPolygon, MultiLineString
    para_m = Transformer.from_crs(epsg_origem or 4326, epsg_area, always_xy=True).transform
    para_ll = Transformer.from_crs(epsg_area, 4326, always_xy=True).transform
    gm = shapely.make_valid(shapely.transform(shapely.force_2d(g), _transf(para_m)))
    if esperado == "poligono":
        ps = _partes(gm, "Polygon")
        if not ps:
            return None, 0.0, 0.0
        gm = shapely.union_all(ps)
        if simplificar_m:
            gm = shapely.make_valid(gm.simplify(simplificar_m, preserve_topology=True))
        gm = shapely.union_all(_partes(gm, "Polygon"))
    else:
        ls = _partes(gm, "Line")
        if not ls:
            return None, 0.0, 0.0
        gm = ls[0] if len(ls) == 1 else MultiLineString(ls)
        if simplificar_m:
            gm = gm.simplify(simplificar_m, preserve_topology=True)
    area, comp = gm.area, gm.length
    gl = _arredondar(shapely.transform(gm, _transf(para_ll)))
    if esperado == "poligono":
        if not gl.is_valid:                       # arredondamento gerou auto-interseção (raro)
            gl = _arredondar(shapely.make_valid(gl))
        ps = _partes(gl, "Polygon")
        if not ps:
            return None, 0.0, 0.0
        gl = ps[0] if len(ps) == 1 else MultiPolygon(ps)
        if not gl.is_valid:
            gl = shapely.make_valid(gl.buffer(0))
    return gl, round(area, 1), round(comp, 1)


def _props_simples(p, limite=25):
    out = {}
    for k, v in list(p.items())[:limite]:
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[str(k)] = v[:300] if isinstance(v, str) else v
    return out


# ---------------------------------------------------------------------------
# Configuração (caminho da plataforma)
# ---------------------------------------------------------------------------
def ler_config():
    try:
        return json.load(open(ARQ_CONFIG, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def gravar_config(cfg):
    try:
        json.dump(cfg, open(ARQ_CONFIG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except OSError:
        pass


def achar_plataforma(cfg=None):
    """Pasta da plataforma: configuração do usuário › variável PLATAFORMA_ZONEAMENTO › pasta-mãe do editor. None se não achar
    (o editor funciona sem ela: valida com o validador embutido e exporta a pasta da cidade)."""
    for c in ((cfg or {}).get("plataforma"), os.environ.get("PLATAFORMA_ZONEAMENTO"), os.path.dirname(AQUI)):
        if c and os.path.isdir(os.path.join(c, "cidades")):
            return os.path.abspath(c)
    return None


def cidades_da_plataforma(plataforma):
    pasta = os.path.join(plataforma or "", "cidades")
    if not os.path.isdir(pasta):
        return []
    return [s for s in sorted(os.listdir(pasta)) if os.path.isfile(os.path.join(pasta, s, f"{s}.json"))]


def schema_igual_ao_da_plataforma(plataforma):
    """True/False se o schema embutido é idêntico ao da plataforma; None se não há plataforma."""
    a = os.path.join(plataforma or "", "schema", "cidade.schema.json")
    if not os.path.isfile(a):
        return None
    return open(a, "rb").read() == open(_val.SCHEMA, "rb").read()


# ---------------------------------------------------------------------------
# Cidade
# ---------------------------------------------------------------------------
def bloco_vazio():
    return {"resumo": None, "fonte_id": None, "artigo_anexo": None, "itens": []}


def esqueleto_cidade(municipio="", uf="", codigo_ibge="", lat=0.0, lon=0.0, zoom=13, crs_area=None):
    return {
        "schema_versao": VERSAO_SCHEMA, "municipio": municipio, "uf": (uf or "").upper(),
        "slug": slug_cidade(municipio, uf) if municipio and uf else "", "codigo_ibge": codigo_ibge,
        "data_levantamento": hoje(), "centro_mapa": {"lat": lat, "lon": lon, "zoom": zoom},
        "orgao_confirmacao": None, "marco_legal_vigente": "", "fontes": [], "zonas": [],
        "definicoes_parametros_adicionais": [], "macrozonas": [], "camadas_complementares": {},
        "outorga_onerosa": bloco_vazio(), "zeis_his": bloco_vazio(), "outros_parametros": bloco_vazio(),
        "resumo_mcmv": [],
        "geografico": {"descricao": "Geometrias importadas no editor desktop (KMZ/KML/GeoJSON), reprojetadas para EPSG:4326, "
                                    "corrigidas (make_valid), simplificadas (~2 m) e arredondadas a 6 casas.",
                       "crs": "EPSG:4326", "crs_area": crs_area or f"EPSG:{epsg_utm(lon, lat)}", "servidor_oficial": None,
                       "camadas": [], "regras_de_consulta": "Motor genérico da plataforma (tipo, prioridade e regra_sobreposicao).",
                       "limitacoes": []},
        "lacunas": [],
    }


def parametros_vazios():
    return {"ca_minimo": None, "ca_basico": None, "ca_maximo": None, "taxa_ocupacao": None, "gabarito_altura_max_m": None,
            "gabarito_pavimentos": None, "taxa_permeabilidade": None, "recuos": {"frontal": None, "lateral": None, "fundos": None},
            "lote_minimo_m2": None, "testada_minima_m": None, "usos_permitidos": None, "vagas": None, "densidade": None, "outros": {}}


class Cidade:
    """Documento em edição. `dados` é o dict cru do JSON (campos desconhecidos são preservados)."""

    def __init__(self, dados=None, caminho=None):
        self.dados = dados if dados is not None else esqueleto_cidade()
        self.caminho = caminho                 # arquivo de origem (se aberto)
        self.compacto = True                   # formato de gravação (detectado ao abrir; as 9 cidades são compactas)
        self.anexos_fontes = {}                # fonte_id -> [arquivos a copiar para fontes/]
        self.geo_raw = []                      # arquivos de geometria importados (copiados para geo_raw/)
        self.alterado = False

    # ---------------- abrir / salvar
    @classmethod
    def abrir(cls, caminho):
        with open(caminho, "rb") as f:
            bruto = f.read()
        dados = json.loads(bruto.decode("utf-8-sig"))
        if not isinstance(dados, dict):
            raise ErroEditor("O arquivo não contém um objeto JSON de cidade.")
        c = cls(dados, os.path.abspath(caminho))
        c.compacto = b"\n" not in bruto[:4096].strip()
        return c

    @property
    def slug(self):
        return self.dados.get("slug") or ""

    def texto_json(self):
        if self.compacto:
            return json.dumps(self.dados, ensure_ascii=False, separators=(",", ":"))
        return json.dumps(self.dados, ensure_ascii=False, indent=1)

    def _gravar_json(self, destino, backup=True):
        os.makedirs(os.path.dirname(os.path.abspath(destino)), exist_ok=True)
        if backup and os.path.exists(destino):
            shutil.copy2(destino, destino + ".bak")
        tmp = destino + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(self.texto_json())
        os.replace(tmp, destino)

    def salvar_como(self, destino, backup=True, referencias=True):
        """Grava o JSON em `destino` (backup .bak do anterior), cria REFERENCIAS.md se não existir e copia os anexos
        (fontes/ e geo_raw/) para a pasta do arquivo."""
        self._fechar_historico()
        pasta = os.path.dirname(os.path.abspath(destino))
        self._copiar_anexos(pasta)
        self._gravar_json(destino, backup)
        if referencias and not os.path.exists(os.path.join(pasta, "REFERENCIAS.md")):
            with open(os.path.join(pasta, "REFERENCIAS.md"), "w", encoding="utf-8") as f:
                f.write(self.gerar_referencias())
        self.caminho, self.alterado = os.path.abspath(destino), False
        return destino

    def salvar_na_plataforma(self, plataforma):
        if not self.slug:
            raise ErroEditor("Defina município e UF (o slug é gerado deles) antes de salvar.")
        return self.salvar_como(os.path.join(plataforma, "cidades", self.slug, f"{self.slug}.json"))

    def _copiar_anexos(self, pasta):
        """Copia anexos para fontes/ e geo_raw/. Nunca sobrescreve um arquivo diferente já existente: o novo ganha
        sufixo _2, _3… e as referências no JSON (arquivo_local, geografico.camadas.arquivo) são ajustadas."""
        pares = [(a, "fontes") for arqs in self.anexos_fontes.values() for a in arqs] + [(a, "geo_raw") for a in self.geo_raw]
        for a, sub in pares:
            if not os.path.isfile(a):
                continue
            os.makedirs(os.path.join(pasta, sub), exist_ok=True)
            base = os.path.basename(a)
            dst = os.path.join(pasta, sub, base)
            if os.path.abspath(a) == os.path.abspath(dst):
                continue
            n, raiz, ext = 2, *os.path.splitext(base)
            while os.path.exists(dst) and open(dst, "rb").read() != open(a, "rb").read():
                dst = os.path.join(pasta, sub, f"{raiz}_{n}{ext}")
                n += 1
            shutil.copy2(a, dst)
            novo = os.path.basename(dst)
            if novo != base:
                for f in self.dados.get("fontes") or []:
                    if f.get("arquivo_local") == f"{sub}/{base}":
                        f["arquivo_local"] = f"{sub}/{novo}"
                for c in (self.dados.get("geografico") or {}).get("camadas") or []:
                    if c.get("arquivo") == f"{sub}/{base}":
                        c["arquivo"] = f"{sub}/{novo}"

    def exportar_pasta(self, destino_dir, rascunho=False, copiar_pasta_origem=True, validacao=None):
        """Gera <destino>/<slug>/ pronta para colar em plataforma/cidades/:
        <slug>.json, REFERENCIAS.md, fontes/, geo_raw/, scripts/README.md.
        Só exporta se a validação der APROVADO; com rascunho=True grava em <slug>__RASCUNHO/ (a plataforma ignora
        essa pasta, porque o nome não bate com o slug). Devolve (pasta, resultado_da_validacao)."""
        if not self.slug:
            raise ErroEditor("Defina município e UF antes de exportar.")
        self._fechar_historico()
        res = validacao or self.validar()
        if not res["ok"] and not rascunho:
            raise ErroEditor(f"Validação REPROVADA ({len(res['erros'])} erro(s)) – corrija ou exporte como rascunho.")
        pasta = os.path.join(destino_dir, self.slug if res["ok"] else f"{self.slug}__RASCUNHO")
        os.makedirs(pasta, exist_ok=True)
        origem = os.path.dirname(self.caminho) if self.caminho else None
        if copiar_pasta_origem and origem and os.path.abspath(origem) != os.path.abspath(pasta):
            for sub in ("fontes", "geo_raw", "scripts"):
                if os.path.isdir(os.path.join(origem, sub)):
                    shutil.copytree(os.path.join(origem, sub), os.path.join(pasta, sub), dirs_exist_ok=True)
            ref = os.path.join(origem, "REFERENCIAS.md")
            if os.path.isfile(ref) and not os.path.exists(os.path.join(pasta, "REFERENCIAS.md")):
                shutil.copy2(ref, os.path.join(pasta, "REFERENCIAS.md"))
        self._copiar_anexos(pasta)
        self._gravar_json(os.path.join(pasta, f"{self.slug}.json"), backup=True)
        if not os.path.exists(os.path.join(pasta, "REFERENCIAS.md")):
            with open(os.path.join(pasta, "REFERENCIAS.md"), "w", encoding="utf-8") as f:
                f.write(self.gerar_referencias())
        for sub in ("fontes", "geo_raw", "scripts"):
            os.makedirs(os.path.join(pasta, sub), exist_ok=True)
        leia = os.path.join(pasta, "scripts", "README.md")
        if not os.path.exists(leia):
            with open(leia, "w", encoding="utf-8") as f:
                f.write(f"# scripts/ – {self.dados.get('municipio')}/{self.dados.get('uf')}\n\n"
                        f"`{self.slug}.json` foi gerado/editado no **editor desktop** da plataforma (editor_desktop/editor.py) em {hoje()}.\n"
                        "Não há script de coleta: os parâmetros foram digitados ou importados (CSV) e as geometrias importadas de "
                        "KMZ/KML/GeoJSON (originais em `../geo_raw/`). Para alterar, abra o JSON no editor e exporte de novo.\n")
        aviso = os.path.join(pasta, "RASCUNHO_LEIA.txt")
        if not res["ok"]:
            with open(aviso, "w", encoding="utf-8") as f:
                f.write("RASCUNHO – a validação REPROVOU. A plataforma ignora esta pasta (o nome difere do slug).\n"
                        "Corrija no editor e exporte de novo.\n\n" + "\n".join("ERRO  " + e for e in res["erros"]) + "\n")
        elif os.path.exists(aviso):
            os.remove(aviso)
        return pasta, res

    # ---------------- validação (validador embutido – idêntico ao da plataforma)
    def validar(self, geometrias=True):
        nominal = os.path.join(tempfile.gettempdir(), self.slug or "cidade", f"{self.slug or 'cidade'}.json")
        texto = self.texto_json()
        res = _val.validar_dados(json.loads(texto), nominal, geometrias)
        mb = len(texto.encode("utf-8")) / 1e6
        res["resumo"]["tamanho_mb"] = round(mb, 2)
        if mb > _val.TAM_ERRO_MB:
            res["erros"].insert(0, f"Arquivo com {mb:.1f} MB (> {_val.TAM_ERRO_MB} MB).")
            res["ok"] = False
        elif mb > _val.TAM_AVISO_MB:
            res["avisos"].insert(0, f"Arquivo com {mb:.1f} MB (> {_val.TAM_AVISO_MB} MB recomendado).")
        return res

    @staticmethod
    def traduzir(m):
        """Mensagens do JSON Schema (em inglês, com o objeto inteiro) → frase curta em português."""
        mm = re.match(r"schema (\$[^:]*): (.*)$", m, re.S)
        if not mm:
            return m
        cam, txt = mm.groups()
        regras = [
            (r"^(.*) is not valid under any of the given schemas", "valor fora do formato do parâmetro (confira unidade travada, forma e, "
                                                                  "em taxas, fração 0–1)"),
            (r"should be non-empty|is too short|\[\] should be non-empty", "não pode ficar vazio"),
            (r"^'(.+)' is a required property", "campo obrigatório ausente: {0}"),
            (r"^(.+) is not one of (.+)", "valor {0} fora da lista permitida {1}"),
            (r"^(.+) does not match '(.+)'", "formato inválido: {0}"),
            (r"^(.+) is greater than the maximum of (.+)", "{0} acima do máximo {1}"),
            (r"^(.+) is less than the minimum of (.+)", "{0} abaixo do mínimo {1}"),
            (r"^\{.*\} is not of type 'null'", "valor fora do formato do parâmetro (confira unidade travada, forma e, em taxas, "
                                                 "fração 0–1: 30% = 0,3)"),
            (r"^(.+) is not of type '(.+)'", "tipo errado ({0}); esperado {1}"),
            (r"^(.+) was expected", "valor esperado: {0}"),
            (r"Additional properties are not allowed \((.+) (?:was|were) unexpected\)", "campo(s) não previsto(s) no schema: {0}"),
        ]
        for pad, frase in regras:
            r = re.search(pad, txt, re.S)
            if r:
                gs = [g if len(g) <= 60 else g[:57] + "…" for g in r.groups()]
                return f"{frase.format(*gs)}  [{cam}]"
        return f"{txt[:160]}  [{cam}]"

    def problemas_legiveis(self, res):
        """[(nível, zona, campo, mensagem)] – aponta a zona/campo a partir dos caminhos do validador."""
        zonas = self.dados.get("zonas") or []
        saida = []
        for nivel, lst in (("ERRO", res["erros"]), ("AVISO", res["avisos"])):
            for m in lst:
                zona, campo = "", ""
                mm = re.search(r"\$\.zonas\[(\d+)\]((?:\.\w+|\[\d+\])*)", m)
                mz = re.match(r"zona (.+?): (parametros_adicionais\.\w+|regra_sobreposicao[.\w]*|usa_indices_de|aplica_sobre)?", m)
                if mm:
                    i = int(mm.group(1))
                    zona = zonas[i].get("codigo", f"#{i}") if i < len(zonas) and isinstance(zonas[i], dict) else f"#{i}"
                    campo = mm.group(2).lstrip(".")
                elif mz:
                    zona, campo = mz.group(1), mz.group(2) or ""
                else:
                    mt = re.search(r"\$\.(\w+)", m) or re.match(r"(fontes|camada \S+|geografico[.\w]*|centro_mapa|lacunas)", m)
                    campo = mt.group(1) if mt else ""
                saida.append((nivel, zona, campo, self.traduzir(m)))
        return saida

    # ---------------- metadados
    def definir_metadados(self, municipio, uf, codigo_ibge, lat, lon, zoom=13, crs_area=None, data_levantamento=None,
                          marco_legal=None, orgao=None):
        municipio, uf = (municipio or "").strip(), (uf or "").strip().upper()
        if not municipio:
            raise ErroEditor("Município: obrigatório.")
        if not re.fullmatch(r"[A-Z]{2}", uf):
            raise ErroEditor("UF: duas letras (ex.: MS).")
        ibge = re.sub(r"\D", "", str(codigo_ibge or ""))
        if not re.fullmatch(r"\d{7}", ibge):
            raise ErroEditor("Código IBGE: 7 dígitos (ex.: 5002704).")
        lat_n, lon_n = numero(lat, rotulo="Latitude do centro"), numero(lon, rotulo="Longitude do centro")
        if lat_n is None or lon_n is None or not (-90 <= lat_n <= 90 and -180 <= lon_n <= 180):
            raise ErroEditor("Centro do mapa: latitude (-90..90) e longitude (-180..180) em graus decimais.")
        z = numero(zoom or 13, "inteiro", "Zoom")
        if not 1 <= z <= 20:
            raise ErroEditor("Zoom: 1 a 20.")
        crs = (crs_area or "").strip().upper() or f"EPSG:{epsg_utm(lon_n, lat_n)}"
        if re.fullmatch(r"\d{4,5}", crs):
            crs = "EPSG:" + crs
        if not re.fullmatch(r"EPSG:\d{4,5}", crs):
            raise ErroEditor("CRS métrico: no formato EPSG:31981.")
        try:
            from pyproj import CRS
            if not CRS.from_user_input(crs).is_projected:
                raise ErroEditor(f"{crs} não é um CRS projetado (métrico) – use UTM SIRGAS 2000 (ex.: EPSG:{epsg_utm(lon_n, lat_n)}).")
        except ErroEditor:
            raise
        except Exception:
            raise ErroEditor(f"CRS {crs} desconhecido.")
        d = self.dados
        novo = {"municipio": municipio, "uf": uf, "slug": slug_cidade(municipio, uf), "codigo_ibge": ibge,
                "centro_mapa": {**(d.get("centro_mapa") or {}), "lat": lat_n, "lon": lon_n, "zoom": z}}
        for k, v in novo.items():
            if d.get(k) != v:
                d[k] = v
                self.alterado = True
        g = d.setdefault("geografico", esqueleto_cidade()["geografico"])
        if g.get("crs_area") != crs:
            g["crs_area"], self.alterado = crs, True
        for k, v in (("data_levantamento", data_levantamento), ("marco_legal_vigente", marco_legal)):
            if v is not None and d.get(k) != v.strip():
                d[k], self.alterado = v.strip(), True
        if orgao is not None and d.get("orgao_confirmacao") != (orgao.strip() or None):
            d["orgao_confirmacao"], self.alterado = orgao.strip() or None, True

    def epsg_area(self):
        crs = (self.dados.get("geografico") or {}).get("crs_area")
        if crs:
            return int(crs.split(":")[1])
        cm = self.dados.get("centro_mapa") or {}
        return epsg_utm(cm.get("lon", -50), cm.get("lat", -15))

    # ---------------- fontes
    def ids_fontes(self):
        return [f.get("id") for f in self.dados.get("fontes") or []]

    def salvar_fonte(self, id_antigo, id_, titulo, lei, url, data, observacao="", arquivo=None):
        id_ = (id_ or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", id_):
            raise ErroEditor("Fonte: id só com letras, números, _ ou - (ex.: LC341).")
        if not (titulo or "").strip() or not (lei or "").strip():
            raise ErroEditor("Fonte: título e lei são obrigatórios.")
        if not re.match(r"https?://", (url or "").strip()):
            raise ErroEditor("Fonte: link deve começar com http:// ou https://.")
        fontes = self.dados.setdefault("fontes", [])
        if id_ != id_antigo and id_ in self.ids_fontes():
            raise ErroEditor(f"Fonte: id '{id_}' já existe.")
        f = next((x for x in fontes if x.get("id") == id_antigo), None) if id_antigo else None
        if f is None:
            f = {}
            fontes.append(f)
        f.update({"id": id_, "titulo": titulo.strip(), "lei": lei.strip(), "data": (data or "").strip(), "url": url.strip()})
        if observacao or "observacao" in f:
            f["observacao"] = (observacao or "").strip() or None
        if arquivo:
            self.anexos_fontes.setdefault(id_, []).append(arquivo)
            f["arquivo_local"] = f"fontes/{os.path.basename(arquivo)}"
        if id_antigo and id_ != id_antigo:
            self._renomear_fonte(id_antigo, id_)
            self.anexos_fontes[id_] = self.anexos_fontes.pop(id_antigo, []) + self.anexos_fontes.get(id_, [])
        self.alterado = True
        return f

    def _renomear_fonte(self, antigo, novo):
        def rec(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    if k == "fonte_id" and v == antigo:
                        o[k] = novo
                    else:
                        rec(v)
            elif isinstance(o, list):
                for x in o:
                    rec(x)
        rec({k: v for k, v in self.dados.items() if k != "fontes"})

    def usos_fonte(self, id_):
        n = [0]

        def rec(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    if k == "fonte_id" and v == id_:
                        n[0] += 1
                    else:
                        rec(v)
            elif isinstance(o, list):
                for x in o:
                    rec(x)
        rec({k: v for k, v in self.dados.items() if k != "fontes"})
        return n[0]

    def remover_fonte(self, id_):
        n = self.usos_fonte(id_)
        if n:
            raise ErroEditor(f"Fonte '{id_}' é citada {n} vez(es); troque as citações antes de remover.")
        self.dados["fontes"] = [f for f in self.dados.get("fontes") or [] if f.get("id") != id_]
        self.anexos_fontes.pop(id_, None)
        self.alterado = True

    # ---------------- lacunas
    def _lacuna(self, item, motivo):
        lac = self.dados.setdefault("lacunas", [])
        for x in lac:
            if isinstance(x, dict) and x.get("item") == item:
                if x.get("motivo") != motivo:
                    x["motivo"] = motivo
                return
        lac.append({"item": item, "motivo": motivo})

    def _tirar_lacuna(self, item):
        lac = self.dados.get("lacunas") or []
        novo = [x for x in lac if not (isinstance(x, dict) and x.get("item") == item)]
        if len(novo) != len(lac):
            self.dados["lacunas"] = novo

    # ---------------- histórico de alterações (schema 1.2, opcional)
    def registrar(self, texto):
        """Anota uma alteração (vai para historico_alteracoes ao salvar/exportar)."""
        self.alterado = True
        if not hasattr(self, "_log"):
            self._log = []
        if texto not in self._log:
            self._log.append(texto)

    def _fechar_historico(self):
        log = getattr(self, "_log", [])
        if not log:
            return
        self._garantir_12()
        self.dados["data_atualizacao"] = hoje()
        hist = self.dados.setdefault("historico_alteracoes", [])
        if hist and hist[-1].get("data") == hoje() and hist[-1].get("ferramenta") == "editor_desktop":
            itens = hist[-1]["resumo"].split("; ")          # mesma sessão/dia: junta (idempotente)
            hist[-1]["resumo"] = "; ".join(itens + [x for x in log if x not in itens])[:2000]
        else:
            hist.append({"data": hoje(), "ferramenta": "editor_desktop", "resumo": "; ".join(log)[:2000]})
        self._log = []

    def _garantir_12(self):
        if self.dados.get("schema_versao") != VERSAO_SCHEMA:
            self.dados["schema_versao"] = VERSAO_SCHEMA

    # ---------------- zonas
    def codigos(self):
        return [z.get("codigo") for z in self.dados.get("zonas") or []]

    def zona(self, codigo):
        return next((z for z in self.dados.get("zonas") or [] if z.get("codigo") == codigo), None)

    def nova_zona(self, codigo, nome, tipo="base", prioridade=None, categoria="outra", descricao=None):
        codigo = (codigo or "").strip()
        if not codigo:
            raise ErroEditor("Zona: código obrigatório.")
        if codigo in self.codigos():
            raise ErroEditor(f"Zona: código '{codigo}' já existe.")
        if tipo not in TIPOS_ZONA:
            raise ErroEditor("Zona: tipo deve ser base, sobreposta ou eixo.")
        if categoria not in CATEGORIAS:
            raise ErroEditor(f"Zona: categoria '{categoria}' inválida.")
        z = {"codigo": codigo, "nome": (nome or codigo).strip(), "descricao": descricao or None, "tipo": tipo,
             "prioridade": 0 if tipo == "base" and prioridade in (None, "") else numero(prioridade or 1, "inteiro", "Prioridade"),
             "categoria_normalizada": categoria,
             "regra_sobreposicao": None if tipo == "base" else {"efeito": "apenas_alerta", "usa_indices_de": None, "aplica_sobre": None,
                                                                 "fundamento": None, "alerta": None},
             "parametros": parametros_vazios(), "observacoes": [],
             "geometria": {"type": "FeatureCollection", "crs": "EPSG:4326", "fonte": "", "oficial": False, "features": []}}
        defs = self.dados.get("definicoes_parametros_adicionais") or []
        if defs:
            z["parametros_adicionais"] = {x["chave"]: None for x in defs}
        self.dados.setdefault("zonas", []).append(z)
        self.registrar(f"zona {codigo} incluída")
        return z

    def atualizar_zona(self, codigo, novo_codigo=None, nome=None, tipo=None, prioridade=None, categoria=None, descricao=None,
                       categoria_criterio=None, observacoes=None, regra=None):
        """Atualiza dados da zona. Renomear o código atualiza as referências (usa_indices_de, aplica_sobre, feições, camadas)."""
        z = self.zona(codigo)
        if z is None:
            raise ErroEditor(f"Zona '{codigo}' não existe.")
        antes = json.dumps(z, sort_keys=True, ensure_ascii=False)
        if tipo is not None:
            if tipo not in TIPOS_ZONA:
                raise ErroEditor("Zona: tipo deve ser base, sobreposta ou eixo.")
            z["tipo"] = tipo
        if prioridade is not None and prioridade != "":
            p = numero(prioridade, "inteiro", "Prioridade")
            if p < 0:
                raise ErroEditor("Prioridade: inteiro ≥ 0 (base = 0; sobrepostas maiores vencem).")
            if p != z.get("prioridade"):
                z["prioridade"] = p
        if categoria is not None:
            if categoria not in CATEGORIAS:
                raise ErroEditor(f"Categoria '{categoria}' inválida.")
            z["categoria_normalizada"] = categoria
        if nome is not None:
            if not nome.strip():
                raise ErroEditor("Zona: nome obrigatório.")
            if nome.strip() != (z.get("nome") or "").strip():
                z["nome"] = nome.strip()
        if descricao is not None and (descricao.strip() or None) != ((z.get("descricao") or "").strip() or None):
            z["descricao"] = descricao.strip() or None
        if categoria_criterio is not None and (categoria_criterio.strip() or "categoria_criterio" in z):
            z["categoria_criterio"] = categoria_criterio.strip() or None
        if observacoes is not None:
            z["observacoes"] = [x.strip() for x in observacoes if x.strip()]
        if z["tipo"] == "base":
            if regra is not None or z.get("regra_sobreposicao") is not None:
                z["regra_sobreposicao"] = None
        elif regra is not None:
            z["regra_sobreposicao"] = self._regra(regra, z.get("regra_sobreposicao"))
        elif z.get("regra_sobreposicao") is None:
            z["regra_sobreposicao"] = {"efeito": "apenas_alerta", "usa_indices_de": None, "aplica_sobre": None, "fundamento": None, "alerta": None}
        if novo_codigo and novo_codigo.strip() != codigo:
            self.renomear_zona(codigo, novo_codigo.strip())
        if json.dumps(z, sort_keys=True, ensure_ascii=False) != antes:
            self.registrar(f"zona {z['codigo']} editada")
        return z

    def _regra(self, r, antiga):
        efeito = r.get("efeito") or "apenas_alerta"
        if efeito not in EFEITOS:
            raise ErroEditor(f"Regra de sobreposição: efeito '{efeito}' inválido.")
        novo = dict(antiga or {})

        def por(k, val):                       # só grava o que mudou (não acrescenta chaves null à toa)
            if novo.get(k) != val:
                novo[k] = val
        por("efeito", efeito)
        usa = (r.get("usa_indices_de") or "").strip() or None
        if efeito == "usa_indices_de":
            if usa not in self.codigos():
                raise ErroEditor("Regra 'usa_indices_de': escolha a zona cujos índices serão usados.")
        por("usa_indices_de", usa if efeito == "usa_indices_de" else None)
        ap = r.get("aplica_sobre")
        if isinstance(ap, str):
            ap = [x.strip() for x in ap.split(",") if x.strip()]
        falt = [a for a in ap or [] if a not in self.codigos()]
        if falt:
            raise ErroEditor(f"Regra: aplica_sobre com zona(s) inexistente(s): {falt}.")
        por("aplica_sobre", ap or None)
        for k in ("fundamento", "alerta"):
            if k in r:
                por(k, (r.get(k) or "").strip() or None)
        if "mantem_da_base" in r:
            m = r.get("mantem_da_base")
            if isinstance(m, str):
                m = [x.strip() for x in m.split(",") if x.strip()]
            bad = [x for x in m or [] if not re.fullmatch(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*", x)]
            if bad:
                raise ErroEditor(f"Regra: mantem_da_base com caminho inválido {bad} (ex.: taxa_permeabilidade, recuos.frontal).")
            if m:
                por("mantem_da_base", m)
            elif novo.get("mantem_da_base"):           # esvaziado na tela; null/[] originais ficam como estão
                novo.pop("mantem_da_base", None)
        for k in ("limiar_pct", "distancia_max_m"):
            if k in r:
                v = numero(r.get(k), rotulo=k)
                if v is None:
                    if novo.get(k) is not None:         # apagado na tela; um null original fica como está
                        novo.pop(k, None)
                else:
                    por(k, v)
        return novo

    def renomear_zona(self, antigo, novo):
        if not novo:
            raise ErroEditor("Zona: código obrigatório.")
        if novo in self.codigos():
            raise ErroEditor(f"Zona: código '{novo}' já existe.")
        z = self.zona(antigo)
        z["codigo"] = novo
        for f in (z.get("geometria") or {}).get("features") or []:
            if (f.get("properties") or {}).get("codigo") == antigo:
                f["properties"]["codigo"] = novo
        for o in self.dados.get("zonas") or []:
            r = o.get("regra_sobreposicao") or {}
            if r.get("usa_indices_de") == antigo:
                r["usa_indices_de"] = novo
            if r.get("aplica_sobre"):
                r["aplica_sobre"] = [novo if a == antigo else a for a in r["aplica_sobre"]]
        for c in (self.dados.get("geografico") or {}).get("camadas") or []:
            if c.get("nome") == f"zona {antigo}":
                c["nome"] = f"zona {novo}"
        for x in self.dados.get("lacunas") or []:
            if isinstance(x, dict) and isinstance(x.get("item"), str) and x["item"].startswith(f"{antigo}."):
                x["item"] = novo + x["item"][len(antigo):]
        self.registrar(f"zona {antigo} renomeada para {novo}")

    def remover_zona(self, codigo):
        refs = [o["codigo"] for o in self.dados.get("zonas") or [] if o.get("codigo") != codigo and (
            (o.get("regra_sobreposicao") or {}).get("usa_indices_de") == codigo or codigo in ((o.get("regra_sobreposicao") or {}).get("aplica_sobre") or []))]
        if refs:
            raise ErroEditor(f"Zona '{codigo}' é referenciada na regra de sobreposição de {refs}; ajuste antes de remover.")
        self.dados["zonas"] = [z for z in self.dados.get("zonas") or [] if z.get("codigo") != codigo]
        g = self.dados.get("geografico") or {}
        if g.get("camadas"):
            g["camadas"] = [c for c in g["camadas"] if c.get("nome") != f"zona {codigo}"]
        self.dados["lacunas"] = [x for x in self.dados.get("lacunas") or []
                                 if not (isinstance(x, dict) and str(x.get("item", "")).startswith(f"{codigo}."))]
        self.registrar(f"zona {codigo} removida")

    # ---------------- parâmetros
    def definicoes(self):
        return {x["chave"]: x for x in self.dados.get("definicoes_parametros_adicionais") or []}

    def info_parametro(self, caminho):
        """(rótulo, unidade_fixa, tipo) de um caminho: padrão ('recuos.frontal'), 'outros.<chave>' ou 'adicional.<chave>'."""
        if caminho in PADRAO_POR_CAMINHO:
            _, rot, un, tipo = PADRAO_POR_CAMINHO[caminho]
            return rot, un, tipo
        if caminho.startswith("adicional."):
            df = self.definicoes().get(caminho[10:])
            if not df:
                raise ErroEditor(f"Atributo adicional '{caminho[10:]}' não existe no catálogo da cidade.")
            return df.get("rotulo"), df.get("unidade"), df.get("tipo")
        if caminho.startswith("outros."):
            return caminho[7:].replace("_", " "), None, "numero"
        raise ErroEditor(f"Parâmetro '{caminho}' desconhecido.")

    def obter_parametro(self, codigo, caminho):
        z = self.zona(codigo) or {}
        if caminho.startswith("adicional."):
            return (z.get("parametros_adicionais") or {}).get(caminho[10:])
        return get_caminho(z.get("parametros") or {}, caminho)

    def definir_parametro(self, codigo, caminho, campos):
        """Aplica os campos do formulário a um parâmetro. Valor vazio = sem_dado + lacuna com o motivo (observação)."""
        z = self.zona(codigo)
        if z is None:
            raise ErroEditor(f"Zona '{codigo}' não existe.")
        rot, un, tipo = self.info_parametro(caminho)
        if caminho.startswith("outros.") and not re.fullmatch(r"[a-z][a-z0-9_]*", caminho[7:]):
            raise ErroEditor("Chave de 'outros' em snake_case (ex.: indice_elevacao).")
        original = self.obter_parametro(codigo, caminho)
        p = parametro_de_campos(campos, un, tipo or "numero", f"{codigo} › {rot}", original)
        if p is original:
            return p
        if p is not None:
            usadas = {p.get("fonte_id")} | {c.get("fonte_id") for c in p.get("condicionais") or [] if isinstance(c, dict)}
            desconhecidas = sorted(f for f in usadas - {None, ""} if f not in self.ids_fontes())
            if desconhecidas:
                raise ErroEditor(f"{codigo} › {rot}: fonte {', '.join(desconhecidas)} não cadastrada (aba Cidade e fontes).")
        if caminho.startswith("outros.") and p is None:
            (z["parametros"].get("outros") or {}).pop(caminho[7:], None)
        elif caminho.startswith("adicional."):
            self._garantir_12()
            z.setdefault("parametros_adicionais", {})[caminho[10:]] = p
        else:
            set_caminho(z.setdefault("parametros", parametros_vazios()), caminho, p)
        item = f"{codigo}.{caminho.replace('adicional.', 'parametros_adicionais.')}"
        if p is not None and p.get("forma") == "sem_dado":
            self._lacuna(item, p.get("observacao") or "Sem dado na legislação consultada.")
        else:
            self._tirar_lacuna(item)
        self.registrar(f"{codigo}: {rot} alterado")
        return p

    # ---------------- atributos adicionais (catálogo da cidade)
    def adicionar_atributo(self, rotulo, unidade=None, tipo="numero", descricao=None, chave=None, grupo=None, fonte_id=None):
        """Cria o atributo no catálogo e o coloca (null) em TODAS as zonas. Sobe schema_versao para 1.2."""
        rotulo = (rotulo or "").strip()
        if not rotulo:
            raise ErroEditor("Atributo: rótulo obrigatório.")
        chave = chave_snake(chave or rotulo)
        if not re.fullmatch(r"[a-z][a-z0-9_]*", chave or ""):
            raise ErroEditor("Atributo: a chave precisa começar com letra (snake_case).")
        if chave in CHAVES_TOPO_PARAMETROS or chave.replace("_", ".") in PADRAO_POR_CAMINHO:
            raise ErroEditor(f"Atributo: '{chave}' já é um parâmetro padrão – use o campo padrão.")
        if chave in self.definicoes():
            raise ErroEditor(f"Atributo: chave '{chave}' já existe.")
        if tipo not in TIPOS_ADICIONAL:
            raise ErroEditor(f"Atributo: tipo '{tipo}' inválido ({', '.join(TIPOS_ADICIONAL)}).")
        if fonte_id and fonte_id not in self.ids_fontes():
            raise ErroEditor(f"Atributo: fonte '{fonte_id}' não existe.")
        un = (unidade or "").strip() or None
        if tipo == "fracao":
            un = un or "fracao"
        df = {"chave": chave, "rotulo": rotulo, "unidade": un, "tipo": tipo, "descricao": (descricao or "").strip() or None}
        if grupo:
            df["grupo"] = grupo.strip()
        if fonte_id:
            df["fonte_id"] = fonte_id
        self._garantir_12()
        self.dados.setdefault("definicoes_parametros_adicionais", []).append(df)
        for z in self.dados.get("zonas") or []:
            z.setdefault("parametros_adicionais", {}).setdefault(chave, None)
        self.registrar(f"atributo adicional '{chave}' criado")
        return df

    def editar_atributo(self, chave, rotulo=None, unidade=None, descricao=None, grupo=None):
        df = self.definicoes().get(chave)
        if not df:
            raise ErroEditor(f"Atributo '{chave}' não existe.")
        if rotulo is not None:
            if not rotulo.strip():
                raise ErroEditor("Atributo: rótulo obrigatório.")
            df["rotulo"] = rotulo.strip()
        if unidade is not None:
            df["unidade"] = unidade.strip() or None
            for z in self.dados.get("zonas") or []:       # mantém a unidade travada nas zonas
                p = (z.get("parametros_adicionais") or {}).get(chave)
                if isinstance(p, dict):
                    p["unidade"] = df["unidade"]
        if descricao is not None:
            df["descricao"] = descricao.strip() or None
        if grupo is not None:
            if grupo.strip():
                df["grupo"] = grupo.strip()
            else:
                df.pop("grupo", None)
        self.registrar(f"atributo adicional '{chave}' editado")

    def remover_atributo(self, chave):
        self.dados["definicoes_parametros_adicionais"] = [x for x in self.dados.get("definicoes_parametros_adicionais") or [] if x.get("chave") != chave]
        for z in self.dados.get("zonas") or []:
            (z.get("parametros_adicionais") or {}).pop(chave, None)
            r = z.get("regra_sobreposicao") or {}
            if r.get("mantem_da_base"):
                r["mantem_da_base"] = [m for m in r["mantem_da_base"] if m != f"parametros_adicionais.{chave}"]
        self.dados["lacunas"] = [x for x in self.dados.get("lacunas") or []
                                 if not (isinstance(x, dict) and str(x.get("item", "")).endswith(f".parametros_adicionais.{chave}"))]
        self.registrar(f"atributo adicional '{chave}' removido")

    # ---------------- geometria
    def _epsg_entrada(self, geoms, epsg_detectado, epsg_origem):
        if epsg_origem:
            return int(str(epsg_origem).upper().replace("EPSG:", ""))
        if epsg_detectado:
            return epsg_detectado
        if parece_lonlat(geoms):
            return 4326
        raise ErroEditor("As coordenadas não parecem lon/lat e o arquivo não declara o CRS: informe o EPSG de origem (ex.: 31983).")

    def _aplicar_geometria(self, z, partes, arquivo, oficial, erro_m, metodo, fonte_id, epsg, campo, substituir, simplificar_m):
        esperado = "linha" if z["tipo"] == "eixo" else "poligono"
        feats, area, comp = [], 0.0, 0.0
        for props, g in partes:
            gl, a, c = processar_geometria(g, epsg, self.epsg_area(), esperado, simplificar_m)
            if gl is None:
                continue
            area, comp = area + a, comp + c
            from shapely.geometry import mapping
            feats.append({"type": "Feature", "properties": {**_props_simples(props), "codigo": z["codigo"]},
                          "geometry": json.loads(json.dumps(mapping(gl)))})
        if not feats:
            raise ErroEditor(f"Zona {z['codigo']}: nenhuma geometria do tipo esperado ({'linha' if esperado == 'linha' else 'polígono'}) no arquivo.")
        if fonte_id and fonte_id not in self.ids_fontes():
            raise ErroEditor(f"Fonte '{fonte_id}' não existe.")
        geo = z.setdefault("geometria", {"type": "FeatureCollection", "crs": "EPSG:4326", "fonte": "", "oficial": False, "features": []})
        geo["features"] = feats if substituir else (geo.get("features") or []) + feats
        geo.update({"type": "FeatureCollection", "crs": "EPSG:4326", "oficial": bool(oficial),
                    "fonte": f"{os.path.basename(arquivo)}" + (f" ({fonte_id})" if fonte_id else "")})
        erro_n = numero(erro_m, rotulo="Erro estimado (m)") if erro_m not in (None, "") else None
        geo["observacao_geometria"] = (f"Importada no editor desktop em {hoje()} de {os.path.basename(arquivo)} (EPSG:{epsg}); "
                                       f"{'oficial' if oficial else 'NÃO oficial'}; erro estimado "
                                       f"{fmt_num(erro_n) + ' m' if erro_n is not None else 'não informado'}; "
                                       f"área {area / 1e4:.2f} ha (EPSG:{self.epsg_area()}).")
        url = next((f.get("url") for f in self.dados.get("fontes") or [] if f.get("id") == fonte_id), "") or ""
        g = self.dados.setdefault("geografico", esqueleto_cidade()["geografico"])
        cam = {"nome": f"zona {z['codigo']}", "arquivo": f"geo_raw/{os.path.basename(arquivo)}", "campo": campo, "fonte_url": url,
               "data_download": hoje(), "oficial": bool(oficial), "metodo": metodo or "importado no editor desktop (KMZ/KML/GeoJSON)",
               "erro_estimado_m": erro_n, "n_feicoes": len(geo["features"])}
        camadas = g.setdefault("camadas", [])
        i = next((i for i, c in enumerate(camadas) if c.get("nome") == cam["nome"]), None)
        if i is None:
            camadas.append(cam)
        else:
            camadas[i] = cam
        if arquivo not in self.geo_raw:
            self.geo_raw.append(arquivo)
        self.registrar(f"geometria da zona {z['codigo']} {'trocada' if substituir else 'acrescentada'} ({os.path.basename(arquivo)})")
        return {"zona": z["codigo"], "n_feicoes": len(feats), "area_m2": round(area, 1), "comprimento_m": round(comp, 1)}

    def importar_geometria_zona(self, codigo, arquivo, oficial=False, erro_m=None, metodo=None, fonte_id=None, epsg_origem=None,
                                campo=None, valor=None, substituir=True, simplificar_m=2.0):
        """Anexa um KMZ/KML/GeoJSON à zona. Com campo/valor, usa só as feições cujo atributo `campo` == `valor`."""
        z = self.zona(codigo)
        if z is None:
            raise ErroEditor(f"Zona '{codigo}' não existe.")
        geoms, epsg_det = ler_geometrias(arquivo)
        if campo:
            geoms = [(p, g) for p, g in geoms if str(p.get(campo, "")).strip() == str(valor).strip()]
            if not geoms:
                raise ErroEditor(f"Nenhuma feição com {campo} = '{valor}' em {os.path.basename(arquivo)}.")
        if not geoms:
            raise ErroEditor(f"{os.path.basename(arquivo)}: nenhuma geometria encontrada.")
        epsg = self._epsg_entrada(geoms, epsg_det, epsg_origem)
        return self._aplicar_geometria(z, geoms, arquivo, oficial, erro_m, metodo, fonte_id, epsg, campo, substituir, simplificar_m)

    def importar_geometrias_lote(self, arquivo, campo, oficial=False, erro_m=None, metodo=None, fonte_id=None, epsg_origem=None,
                                 criar_zonas=False, tipo_novas="base", categoria_novas="outra", simplificar_m=2.0):
        """Distribui as feições do arquivo pelas zonas, pelo valor do atributo `campo` (= código da zona)."""
        geoms, epsg_det = ler_geometrias(arquivo)
        if not geoms:
            raise ErroEditor(f"{os.path.basename(arquivo)}: nenhuma geometria encontrada.")
        epsg = self._epsg_entrada(geoms, epsg_det, epsg_origem)
        grupos = {}
        for p, g in geoms:
            v = str(p.get(campo, "") if p.get(campo) is not None else "").strip()
            grupos.setdefault(v, []).append((p, g))
        res = {"atribuidas": [], "criadas": [], "ignoradas": [], "erros": []}
        for v, partes in grupos.items():
            if not v:
                res["ignoradas"].append(f"(vazio) – {len(partes)} feição(ões)")
                continue
            if self.zona(v) is None:
                if not criar_zonas:
                    res["ignoradas"].append(f"{v} – {len(partes)} feição(ões) (zona não cadastrada)")
                    continue
                self.nova_zona(v, v, tipo_novas, None, categoria_novas)
                res["criadas"].append(v)
            try:
                res["atribuidas"].append(self._aplicar_geometria(self.zona(v), partes, arquivo, oficial, erro_m, metodo, fonte_id,
                                                                 epsg, campo, True, simplificar_m))
            except ErroEditor as e:
                res["erros"].append(str(e))
        return res

    def area_zona_m2(self, codigo):
        import shapely
        from shapely.geometry import shape
        from pyproj import Transformer
        z = self.zona(codigo) or {}
        feats = (z.get("geometria") or {}).get("features") or []
        if not feats:
            return 0.0
        t = Transformer.from_crs(4326, self.epsg_area(), always_xy=True).transform
        return round(sum(shapely.transform(shape(f["geometry"]), _transf(t)).area for f in feats), 1)

    def contornos(self, codigo=None, max_pontos=4000):
        """Contornos simplificados [(codigo, tipo, [[(lon, lat)…]…])] para a pré-visualização (nunca a geometria completa)."""
        from shapely.geometry import shape
        out = []
        zonas = [self.zona(codigo)] if codigo else (self.dados.get("zonas") or [])
        feats_total = sum(len((z.get("geometria") or {}).get("features") or []) for z in zonas if z)
        for z in zonas:
            if not z:
                continue
            aneis = []
            for f in (z.get("geometria") or {}).get("features") or []:
                try:
                    g = shape(f["geometry"])
                except Exception:
                    continue
                tol = max(g.bounds[2] - g.bounds[0], g.bounds[3] - g.bounds[1]) / 300 if feats_total > 30 else 0
                g = g.simplify(tol) if tol else g
                for p in getattr(g, "geoms", [g]):
                    linha = p.exterior if p.geom_type == "Polygon" else p
                    if hasattr(linha, "coords"):
                        aneis.append(list(linha.coords)[:max_pontos])
            out.append((z.get("codigo"), z.get("tipo"), aneis))
        return out

    # ---------------- CSV de parâmetros (lote)
    @staticmethod
    def modelo_csv():
        return ("zona;parametro;valor;unidade;fonte_id;artigo;observacao;forma\n"
                "ZR1;ca_basico;1;coeficiente;LEI1;Anexo II;;\n"
                "ZR1;taxa_ocupacao;50%;fracao;LEI1;Anexo II;;\n"
                "ZR1;recuos.frontal;5;m;LEI1;art. 20;;\n"
                "ZR1;usos_permitidos;R1, R2, C1;codigos_de_uso;LEI1;Anexo III;;lista\n"
                "ZR1;indice_arborizacao;0,2;fracao;LEI1;art. 30;atributo novo (criado automaticamente);\n")

    def _caminho_csv(self, nome, unidade, forma, criados):
        nome = nome.strip()
        if nome.startswith(("parametros.", "parametros_adicionais.")):
            nome = nome.replace("parametros_adicionais.", "adicional.").replace("parametros.", "")
        if nome in PADRAO_POR_CAMINHO or nome.startswith(("outros.", "adicional.")):
            return nome
        rot = {p[1].lower(): p[0] for p in PARAMETROS_PADRAO}
        if nome.lower() in rot:
            return rot[nome.lower()]
        defs = self.definicoes()
        ch = chave_snake(nome)
        if ch in defs:
            return "adicional." + ch
        por_rotulo = {d["rotulo"].lower(): k for k, d in defs.items()}
        if nome.lower() in por_rotulo:
            return "adicional." + por_rotulo[nome.lower()]
        tipo = "lista" if forma == "lista" else ("fracao" if unidade == "fracao" else "texto" if forma == "texto" else "numero")
        self.adicionar_atributo(nome.replace("_", " ").capitalize() if nome == ch else nome, unidade or None, tipo, chave=ch,
                                descricao="Criado pela importação de CSV.")
        criados.append(ch)
        return "adicional." + ch

    def importar_parametros_csv(self, caminho_ou_texto, criar_atributos=True):
        """CSV (; ou ,) com colunas zona,parametro,valor,unidade,fonte_id,artigo[,observacao,forma].
        Cada linha é independente: uma linha com erro não impede as demais. → {aplicadas, erros[(linha, msg)], criados}."""
        if os.path.isfile(str(caminho_ou_texto)):
            texto = open(caminho_ou_texto, encoding="utf-8-sig").read()
        else:
            texto = str(caminho_ou_texto)
        prim = texto.splitlines()[0] if texto.strip() else ""
        delim = ";" if prim.count(";") >= prim.count(",") else ","
        leitor = csv.DictReader(io.StringIO(texto), delimiter=delim)
        cols = [c.strip().lower() for c in leitor.fieldnames or []]
        faltam = [c for c in ("zona", "parametro", "valor") if c not in cols]
        if faltam:
            raise ErroEditor(f"CSV sem coluna(s) {faltam}. Cabeçalho esperado: zona,parametro,valor,unidade,fonte_id,artigo.")
        res = {"aplicadas": 0, "erros": [], "criados": []}
        for n, linha in enumerate(leitor, start=2):
            r = {(k or "").strip().lower(): (v or "").strip() for k, v in linha.items() if k}
            if not any(r.values()):
                continue
            try:
                if self.zona(r["zona"]) is None:
                    raise ErroEditor(f"zona '{r['zona']}' não existe.")
                forma = r.get("forma", "")
                if not criar_atributos and not (r["parametro"] in PADRAO_POR_CAMINHO or r["parametro"].startswith(("outros.", "adicional."))):
                    if chave_snake(r["parametro"]) not in self.definicoes():
                        raise ErroEditor(f"parâmetro '{r['parametro']}' desconhecido.")
                cam = self._caminho_csv(r["parametro"], r.get("unidade", ""), forma, res["criados"])
                rot, un, tipo = self.info_parametro(cam)
                u = r.get("unidade", "")
                if u and isinstance(un, str) and u != un:
                    raise ErroEditor(f"{rot}: unidade '{u}' ≠ unidade travada '{un}'.")
                campos = campos_de_parametro(self.obter_parametro(r["zona"], cam), tipo)
                campos.update({"valor": r["valor"], "estrutura": "" if r["valor"] else campos["estrutura"]})
                if not r["valor"] and not forma:
                    campos["forma"] = "sem_dado"
                elif r["valor"] and campos.get("forma") not in ("unico", "lista", "texto"):
                    campos["forma"] = ""
                for k_csv, k in (("unidade", "unidade"), ("fonte_id", "fonte_id"), ("artigo", "artigo_anexo"),
                                 ("artigo_anexo", "artigo_anexo"), ("observacao", "observacao"), ("forma", "forma")):
                    if r.get(k_csv):
                        campos[k] = r[k_csv]
                self.definir_parametro(r["zona"], cam, campos)
                res["aplicadas"] += 1
            except ErroEditor as e:
                res["erros"].append((n, str(e)))
        return res

    # ---------------- REFERENCIAS.md
    def gerar_referencias(self):
        d = self.dados
        L = [f"# Referências – {d.get('municipio')}/{d.get('uf')}", "",
             f"Gerado pelo editor desktop em {hoje()}. Levantamento: {d.get('data_levantamento') or '—'}.", "",
             f"**Marco legal vigente:** {d.get('marco_legal_vigente') or '—'}", "", "## Fontes", ""]
        for f in d.get("fontes") or []:
            L.append(f"- **{f.get('id')}** – {f.get('titulo')} ({f.get('lei')}, {f.get('data') or 's/d'}): {f.get('url')}"
                     + (f" — arquivo local: `{f['arquivo_local']}`" if f.get("arquivo_local") else ""))
        L += ["", "## Zonas", "", "| Código | Nome | Tipo | Prioridade | Categoria |", "|---|---|---|---|---|"]
        for z in d.get("zonas") or []:
            L.append(f"| {z.get('codigo')} | {z.get('nome')} | {z.get('tipo')} | {z.get('prioridade')} | {z.get('categoria_normalizada')} |")
        defs = d.get("definicoes_parametros_adicionais") or []
        if defs:
            L += ["", "## Atributos adicionais (schema 1.2)", "", "| Chave | Rótulo | Unidade | Tipo | Descrição |", "|---|---|---|---|---|"]
            for x in defs:
                L.append(f"| {x['chave']} | {x['rotulo']} | {x.get('unidade') or '—'} | {x['tipo']} | {x.get('descricao') or ''} |")
        cams = (d.get("geografico") or {}).get("camadas") or []
        if cams:
            L += ["", "## Geometrias", ""]
            for c in cams:
                L.append(f"- {c.get('nome')}: `{c.get('arquivo') or c.get('campo')}` – {'oficial' if c.get('oficial') else 'NÃO oficial'}, "
                         f"erro estimado {c.get('erro_estimado_m') if c.get('erro_estimado_m') is not None else '?'} m, {c.get('metodo')}"
                         + (f" ({c['fonte_url']})" if c.get("fonte_url") else ""))
        lac = d.get("lacunas") or []
        if lac:
            L += ["", "## Lacunas", ""] + [f"- {x.get('item')}: {x.get('motivo')}" for x in lac if isinstance(x, dict)]
        return "\n".join(L) + "\n"

    # ---------------- ATUALIZAR CIDADE EXISTENTE (abrir a PASTA)
    @classmethod
    def abrir_pasta(cls, pasta):
        """Abre a pasta de uma cidade (ex.: cidades/curitiba-pr/): <slug>.json + fontes/ + geo_raw/ + scripts/ + REFERENCIAS.md.
        Os arquivos existentes ficam como estão; ao exportar no lugar só o JSON é regravado (com .bak)."""
        pasta = os.path.abspath(pasta)
        if not os.path.isdir(pasta):
            raise ErroEditor(f"Pasta não encontrada: {pasta}")
        nome = os.path.basename(pasta.rstrip(os.sep))
        cand = os.path.join(pasta, f"{nome}.json")
        if not os.path.isfile(cand):
            jsons = [x for x in os.listdir(pasta) if x.endswith(".json") and not x.endswith((".bak", ".tmp"))]
            if len(jsons) != 1:
                raise ErroEditor(f"A pasta '{nome}' deveria conter '{nome}.json' (encontrados: {jsons or 'nenhum'}).")
            cand = os.path.join(pasta, jsons[0])
        c = cls.abrir(cand)
        c.pasta_origem = pasta
        return c

    def conteudo_pasta(self):
        """Inventário da pasta de origem: {'fontes': [...], 'geo_raw': [...], 'scripts': [...], 'REFERENCIAS.md': bool}."""
        pasta = getattr(self, "pasta_origem", None) or (os.path.dirname(self.caminho) if self.caminho else None)
        inv = {"pasta": pasta, "fontes": [], "geo_raw": [], "scripts": [], "REFERENCIAS.md": False}
        if not pasta:
            return inv
        for sub in ("fontes", "geo_raw", "scripts"):
            p = os.path.join(pasta, sub)
            if os.path.isdir(p):
                inv[sub] = sorted(os.path.relpath(os.path.join(r, f), p) for r, _, fs in os.walk(p) for f in fs)
        inv["REFERENCIAS.md"] = os.path.isfile(os.path.join(pasta, "REFERENCIAS.md"))
        return inv

    def atualizar_no_lugar(self, rascunho=False):
        """Exporta sobrescrevendo a própria pasta de origem (JSON anterior vira <slug>.json.bak; fontes/, geo_raw/,
        scripts/ e REFERENCIAS.md existentes são preservados)."""
        pasta = getattr(self, "pasta_origem", None) or (os.path.dirname(self.caminho) if self.caminho else None)
        if not pasta:
            raise ErroEditor("Esta cidade não foi aberta de uma pasta – use Exportar pasta.")
        if os.path.basename(pasta) != self.slug:
            raise ErroEditor(f"O slug mudou ('{os.path.basename(pasta)}' → '{self.slug}'): exporte para outra pasta.")
        return self.exportar_pasta(os.path.dirname(pasta), rascunho=rascunho)
