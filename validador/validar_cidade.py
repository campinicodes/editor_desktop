#!/usr/bin/env python3
"""Validador do padrão de dados da plataforma multicidades.

Duas camadas:
  1. JSON Schema (draft 2020-12) em schema/cidade.schema.json – FONTE DE VERDADE da estrutura (biblioteca jsonschema);
  2. checagens semânticas que o schema não expressa (fonte_id existente, códigos referenciados, geometrias válidas…).

Aceita schema_versao "1.1" e "1.2" (1.2 = blocos opcionais de atributos adicionais e histórico de alterações).

Uso:  python3 validar_cidade.py <slug> [--json]     (ex.: campo-grande-ms)
      python3 validar_cidade.py --todas
      python3 validar_cidade.py --arquivo caminho/para/cidade.json
Sai com código 1 se houver ERRO. AVISO não reprova.
Também é importado pela app (função validar)."""
import json, os, sys
from collections import Counter

BASE = os.path.dirname(os.path.abspath(__file__))
CIDADES = os.path.join(BASE, "cidades")
TOPO = ["schema_versao", "municipio", "uf", "slug", "codigo_ibge", "data_levantamento", "centro_mapa", "marco_legal_vigente",
        "fontes", "macrozonas", "zonas", "camadas_complementares", "outorga_onerosa", "zeis_his", "outros_parametros",
        "resumo_mcmv", "geografico", "lacunas"]
TIPOS = {"base", "sobreposta", "eixo"}
EFEITOS = {"substitui", "usa_indices_de", "apenas_alerta"}
PAPEIS = {"permeabilidade", "macrozona", "restricao", "informativa"}
TAM_AVISO_MB, TAM_ERRO_MB = 40, 100
SCHEMA = os.path.join(BASE, "schema", "cidade.schema.json")
VERSAO = "1.2"                      # versão atual do schema
VERSOES_ACEITAS = ("1.1", "1.2")    # 1.1 continua válida (1.2 só acrescenta blocos opcionais)
PADRAO_PARAMETROS = ("ca_minimo", "ca_basico", "ca_maximo", "taxa_ocupacao", "gabarito_altura_max_m", "gabarito_pavimentos",
                     "taxa_permeabilidade", "recuos", "lote_minimo_m2", "testada_minima_m", "usos_permitidos", "vagas",
                     "densidade", "outros")
NUMERICOS = ("ca_minimo", "ca_basico", "ca_maximo", "taxa_ocupacao", "gabarito_altura_max_m", "gabarito_pavimentos",
             "taxa_permeabilidade", "lote_minimo_m2", "testada_minima_m", "vagas", "densidade")
_VALIDADOR = None


def _validador():
    global _VALIDADOR
    if _VALIDADOR is None:
        from jsonschema import Draft202012Validator
        s = json.load(open(SCHEMA, encoding="utf-8"))
        Draft202012Validator.check_schema(s)
        _VALIDADOR = Draft202012Validator(s)
    return _VALIDADOR


def _caminho(e):
    return "$" + "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in e.absolute_path)


def validar_schema(d, maximo=40):
    """Erros de JSON Schema como textos '$.caminho: mensagem' (desce em anyOf/oneOf até o erro mais específico)."""
    try:
        v = _validador()
    except ImportError:
        return ["Biblioteca jsonschema ausente: pip install jsonschema (o schema é a fonte de verdade)."]
    from jsonschema.exceptions import best_match
    saida = []
    for e in sorted(v.iter_errors(d), key=lambda e: list(map(str, e.absolute_path))):
        while e.context:
            e = best_match(e.context)
        saida.append(f"schema {_caminho(e)}: {e.message[:220]}")
    if len(saida) > maximo:
        saida = saida[:maximo] + [f"schema: ... e mais {len(saida) - maximo} erro(s) (rode com --json para ver todos)."]
    return saida


def _walk_fonte_ids(obj, caminho, achados):
    """Coleta (caminho, fonte_id) e parâmetros {valor} sem fonte_id, ignorando geometrias."""
    if isinstance(obj, dict):
        if obj.get("type") in ("FeatureCollection", "Feature") or "coordinates" in obj:
            return
        if "fonte_id" in obj:
            achados["ids"].append((caminho, obj["fonte_id"]))
        if "valor" in obj and obj.get("valor") is not None and not obj.get("fonte_id"):
            achados["sem_fonte"].append(caminho)
        for k, v in obj.items():
            if k in ("features", "geometria", "condicionais"):   # condicionais herdam a fonte do parâmetro pai
                continue
            _walk_fonte_ids(v, f"{caminho}.{k}", achados)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _walk_fonte_ids(v, f"{caminho}[{i}]", achados)


def _coords(geom):
    t, c = geom.get("type"), geom.get("coordinates")
    if t == "Point":
        yield c
    elif t in ("LineString", "MultiPoint"):
        yield from c
    elif t in ("Polygon", "MultiLineString"):
        for r in c:
            yield from r
    elif t == "MultiPolygon":
        for p in c:
            for r in p:
                yield from r
    elif t == "GeometryCollection":
        for g in geom.get("geometries", []):
            yield from _coords(g)


def _checar_features(feats, rotulo, erros, avisos, esperado=None, codigo=None):
    """Valida geometrias (shapely), faixa lon/lat, casas decimais e tipo esperado."""
    from shapely.geometry import shape
    invalidas, tipos_errados, fora, casas, sem_codigo = 0, 0, 0, 0, 0
    for f in feats:
        g = f.get("geometry")
        if not g:
            invalidas += 1
            continue
        if codigo is not None and (f.get("properties") or {}).get("codigo") != codigo:
            sem_codigo += 1
        try:
            s = shape(g)
            if not s.is_valid or s.is_empty:
                invalidas += 1
        except Exception:
            invalidas += 1
            continue
        if esperado == "linha" and "Line" not in s.geom_type:
            tipos_errados += 1
        if esperado == "poligono" and "Polygon" not in s.geom_type:
            tipos_errados += 1
        for i, (x, y, *_) in enumerate(_coords(g)):
            if not (-180 <= x <= 180 and -90 <= y <= 90):
                fora += 1
            if i < 5 and (len(repr(x).split(".")[-1]) > 7 or len(repr(y).split(".")[-1]) > 7):
                casas += 1
    if invalidas:
        erros.append(f"{rotulo}: {invalidas} geometria(s) inválida(s)/vazia(s) (use shapely.make_valid).")
    if tipos_errados:
        erros.append(f"{rotulo}: {tipos_errados} feição(ões) com tipo de geometria inesperado (esperado {esperado}).")
    if fora:
        erros.append(f"{rotulo}: {fora} coordenada(s) fora de EPSG:4326 (lon/lat).")
    if casas:
        avisos.append(f"{rotulo}: coordenadas com mais de 6 casas decimais (aumenta o tamanho do arquivo).")
    if sem_codigo:
        avisos.append(f"{rotulo}: {sem_codigo} feição(ões) sem properties.codigo igual ao código da zona (a app usa o código da zona).")


def _checar_adicionais(d, zonas, erros, avisos, resumo):
    """Atributos novos (schema 1.2): catálogo definicoes_parametros_adicionais × zonas[].parametros_adicionais."""
    if (d.get("historico_alteracoes") is not None or d.get("data_atualizacao") is not None) and d.get("schema_versao") != "1.2":
        erros.append("historico_alteracoes/data_atualizacao exigem schema_versao '1.2'.")
    defs = d.get("definicoes_parametros_adicionais")
    usa = defs is not None or any("parametros_adicionais" in z for z in zonas)
    if not usa:
        return
    if d.get("schema_versao") != "1.2":
        erros.append("definicoes_parametros_adicionais/parametros_adicionais exigem schema_versao '1.2'.")
    defs = [x for x in (defs or []) if isinstance(x, dict)]
    chaves = [x.get("chave") for x in defs]
    dup = [c for c, n in Counter(chaves).items() if n > 1]
    if dup:
        erros.append(f"definicoes_parametros_adicionais: chave duplicada {dup}.")
    for c in chaves:
        if c in PADRAO_PARAMETROS:
            erros.append(f"definicoes_parametros_adicionais: chave '{c}' colide com um parâmetro padrão (use o padrão).")
    por_chave = {x.get("chave"): x for x in defs}
    resumo["parametros_adicionais"] = len(defs)
    for z in zonas:
        c, pa = z.get("codigo"), z.get("parametros_adicionais")
        if pa is None:
            if defs:
                avisos.append(f"zona {c}: sem parametros_adicionais (os {len(defs)} atributo(s) do catálogo serão tratados como null).")
            continue
        if not isinstance(pa, dict):
            continue
        for k, p in pa.items():
            df = por_chave.get(k)
            if df is None:
                erros.append(f"zona {c}: parametros_adicionais.{k} não está em definicoes_parametros_adicionais.")
                continue
            if not isinstance(p, dict):
                continue
            if p.get("unidade") != df.get("unidade"):
                avisos.append(f"zona {c}: parametros_adicionais.{k} com unidade '{p.get('unidade')}' ≠ catálogo '{df.get('unidade')}'.")
            casos = [p] + [x for x in (p.get("condicionais") or []) if isinstance(x, dict)]
            for x in casos:
                v, t = x.get("valor"), df.get("tipo")
                nums = ([v] if isinstance(v, (int, float)) and not isinstance(v, bool) else []) + \
                       [x["faixa"].get(m) for m in ("min", "max") if isinstance(x.get("faixa"), dict) and isinstance(x["faixa"].get(m), (int, float))]
                if t == "fracao" and any(not (0 <= n <= 1) for n in nums):
                    erros.append(f"zona {c}: parametros_adicionais.{k} é fração (0–1) e tem {nums} (30% → 0.3).")
                if t == "inteiro" and any(isinstance(n, float) and not n.is_integer() for n in nums):
                    erros.append(f"zona {c}: parametros_adicionais.{k} é inteiro e tem {nums}.")
                if t in ("numero", "inteiro", "fracao") and x.get("forma") == "lista":
                    erros.append(f"zona {c}: parametros_adicionais.{k} é {t} e está com forma 'lista'.")
                if t == "lista" and x.get("forma") == "unico":
                    erros.append(f"zona {c}: parametros_adicionais.{k} é lista e está com forma 'unico'.")
        falt = [k for k in por_chave if k not in pa]
        if falt:
            avisos.append(f"zona {c}: atributo(s) do catálogo ausente(s) em parametros_adicionais (tratado(s) como null): {falt}.")


def validar(caminho, geometrias=True):
    """Retorna dict {ok, erros, avisos, resumo}."""
    erros, avisos, resumo = [], [], {}
    if not os.path.exists(caminho):
        return {"ok": False, "erros": [f"Arquivo não encontrado: {caminho}"], "avisos": [], "resumo": {}}
    mb = os.path.getsize(caminho) / 1e6
    resumo["tamanho_mb"] = round(mb, 2)
    if mb > TAM_ERRO_MB:
        erros.append(f"Arquivo com {mb:.1f} MB (> {TAM_ERRO_MB} MB).")
    elif mb > TAM_AVISO_MB:
        avisos.append(f"Arquivo com {mb:.1f} MB (> {TAM_AVISO_MB} MB recomendado).")
    try:
        d = json.load(open(caminho, encoding="utf-8"))
    except Exception as e:
        return {"ok": False, "erros": [f"JSON inválido: {e}"], "avisos": avisos, "resumo": resumo}
    return validar_dados(d, caminho, geometrias, erros, avisos, resumo)


def validar_dados(d, caminho=None, geometrias=True, erros=None, avisos=None, resumo=None):
    """Valida um dict já carregado (usado pelo editor desktop, que não precisa gravar o arquivo antes).
    `caminho` (opcional) é usado só nas checagens de nome de arquivo/pasta."""
    erros, avisos, resumo = erros if erros is not None else [], avisos if avisos is not None else [], resumo if resumo is not None else {}
    caminho = caminho or os.path.join("__memoria__", f"{d.get('slug') if isinstance(d, dict) else 'x'}", f"{d.get('slug') if isinstance(d, dict) else 'x'}.json")
    if not isinstance(d, dict):
        return {"ok": False, "erros": ["O JSON precisa ser um objeto."], "avisos": avisos, "resumo": resumo}
    # 1) JSON Schema (fonte de verdade)
    if d.get("schema_versao") not in VERSOES_ACEITAS:
        erros.append(f"schema_versao '{d.get('schema_versao')}' fora de {list(VERSOES_ACEITAS)}: formato legado – rode "
                     f"python3 schema/normalizar_cidade.py {caminho} (ver PADRAO_JSON.md, NORMALIZAÇÃO OBRIGATÓRIA).")
    erros_schema = validar_schema(d)
    erros += erros_schema
    resumo["schema"] = "ok" if not erros_schema else f"{len(erros_schema)} erro(s)"
    # 2) checagens semânticas
    for k in TOPO:
        if k not in d:
            erros.append(f"Chave obrigatória ausente: '{k}'.")
    slug_pasta = os.path.basename(os.path.dirname(os.path.abspath(caminho)))
    if d.get("slug") and os.path.basename(caminho) != f"{d['slug']}.json":
        avisos.append(f"Nome do arquivo difere do slug ('{d['slug']}.json').")
    if d.get("slug") and slug_pasta != d["slug"] and os.path.dirname(os.path.dirname(os.path.abspath(caminho))) == CIDADES:
        erros.append(f"Pasta '{slug_pasta}' difere do slug '{d['slug']}'.")
    cm = d.get("centro_mapa") or {}
    if not all(isinstance(cm.get(k), (int, float)) for k in ("lat", "lon")):
        erros.append("centro_mapa precisa de lat e lon numéricos.")

    fontes = d.get("fontes") or []
    ids = [f.get("id") for f in fontes]
    dup = [i for i, n in Counter(ids).items() if n > 1]
    if dup:
        erros.append(f"fontes com id duplicado: {dup}.")
    sem_url = [f.get("id") for f in fontes if not f.get("url")]
    if sem_url:
        avisos.append(f"fontes sem url: {sem_url}.")
    resumo["n_fontes"] = len(fontes)

    achados = {"ids": [], "sem_fonte": []}
    _walk_fonte_ids({k: v for k, v in d.items() if k != "fontes"}, "$", achados)
    inexist = sorted({(c, f) for c, f in achados["ids"] if f not in ids and f is not None})
    for c, f in inexist[:30]:
        erros.append(f"fonte_id '{f}' inexistente em fontes ({c}).")
    if len(inexist) > 30:
        erros.append(f"... e mais {len(inexist) - 30} fonte_id inexistentes.")
    for c in achados["sem_fonte"][:30]:
        erros.append(f"Parâmetro com valor e sem fonte_id: {c}.")
    if len(achados["sem_fonte"]) > 30:
        erros.append(f"... e mais {len(achados['sem_fonte']) - 30} parâmetros sem fonte_id.")

    zonas = d.get("zonas") or []
    cods = [z.get("codigo") for z in zonas]
    dup = [c for c, n in Counter(cods).items() if n > 1]
    if dup:
        erros.append(f"códigos de zona duplicados: {dup}.")
    resumo["zonas"] = {}
    for z in zonas:
        c = z.get("codigo")
        for k in ("codigo", "nome", "tipo", "prioridade", "parametros", "geometria"):
            if k not in z:
                erros.append(f"zona {c}: chave '{k}' ausente.")
        if z.get("tipo") not in TIPOS:
            erros.append(f"zona {c}: tipo '{z.get('tipo')}' inválido (base|sobreposta|eixo).")
        if not isinstance(z.get("prioridade"), int):
            erros.append(f"zona {c}: prioridade deve ser inteiro.")
        elif z.get("tipo") == "base" and z["prioridade"] != 0:
            avisos.append(f"zona {c}: base com prioridade {z['prioridade']} (padrão 0).")
        r = z.get("regra_sobreposicao")
        if r is not None:
            if r.get("efeito") not in EFEITOS:
                erros.append(f"zona {c}: regra_sobreposicao.efeito '{r.get('efeito')}' inválido.")
            if r.get("efeito") == "usa_indices_de" and r.get("usa_indices_de") not in cods:
                erros.append(f"zona {c}: usa_indices_de '{r.get('usa_indices_de')}' não existe em zonas.")
            for a in r.get("aplica_sobre") or []:
                if a not in cods:
                    erros.append(f"zona {c}: aplica_sobre '{a}' não existe em zonas.")
            if not r.get("fundamento"):
                avisos.append(f"zona {c}: regra_sobreposicao sem 'fundamento'.")
        elif z.get("tipo") in ("sobreposta", "eixo"):
            avisos.append(f"zona {c}: {z.get('tipo')} sem regra_sobreposicao (será tratada como apenas_alerta).")
        geo = z.get("geometria") or {}
        feats = geo.get("features") or []
        resumo["zonas"][c] = len(feats)
        if not feats:
            erros.append(f"zona {c}: sem feições em geometria.features.")
        elif geometrias:
            _checar_features(feats, f"zona {c}", erros, avisos, "linha" if z.get("tipo") == "eixo" else "poligono", c)
        if "oficial" not in geo:
            avisos.append(f"zona {c}: geometria sem 'oficial' (true/false).")
        par = z.get("parametros") or {}
        txt = [k for k in NUMERICOS if isinstance(par.get(k), dict) and par[k].get("forma") == "texto"]
        if txt:
            avisos.append(f"zona {c}: parâmetro(s) numérico(s) só em texto (forma 'texto', sem número estruturado): {txt}.")
    if not any(z.get("tipo") == "base" for z in zonas):
        erros.append("Nenhuma zona do tipo 'base'.")
    _checar_adicionais(d, zonas, erros, avisos, resumo)

    cc = d.get("camadas_complementares") or {}
    resumo["camadas_complementares"] = {}
    for n, c in cc.items():
        if c.get("papel") not in PAPEIS:
            erros.append(f"camada {n}: papel '{c.get('papel')}' inválido.")
        feats = c.get("features") or []
        resumo["camadas_complementares"][n] = f"{c.get('papel')}:{len(feats)}"
        if not feats:
            avisos.append(f"camada {n}: sem feições.")
        cods_c = {(f.get("properties") or {}).get("codigo") for f in feats}
        if None in cods_c:
            erros.append(f"camada {n}: feição sem properties.codigo.")
        ppc = c.get("parametros_por_codigo") or {}
        if c.get("papel") == "permeabilidade" and not ppc:
            erros.append(f"camada {n}: papel permeabilidade exige parametros_por_codigo.")
        falt = sorted(x for x in cods_c - set(ppc) if x) if ppc else []
        if falt:
            avisos.append(f"camada {n}: códigos sem parametros_por_codigo: {falt}.")
        if geometrias and feats:
            _checar_features(feats, f"camada {n}", erros, avisos)

    g = d.get("geografico") or {}
    for k in ("crs", "regras_de_consulta", "limitacoes", "camadas"):
        if k not in g:
            erros.append(f"geografico.{k} ausente.")
    if "crs_area" not in g:
        avisos.append("geografico.crs_area ausente (a app calculará a zona UTM pelo centróide).")
    if not isinstance(d.get("lacunas"), list):
        erros.append("lacunas deve ser lista.")
    elif any(not isinstance(x, dict) or "item" not in x for x in d["lacunas"]):
        avisos.append("lacunas: itens deveriam ser {item, motivo}.")
    return {"ok": not erros, "erros": erros, "avisos": avisos, "resumo": resumo}


def relatorio(slug_ou_caminho, res):
    linhas = [f"=== {slug_ou_caminho}: {'APROVADO' if res['ok'] else 'REPROVADO'} ({len(res['erros'])} erro(s), {len(res['avisos'])} aviso(s))"]
    r = res["resumo"]
    if r:
        linhas.append(f"  JSON Schema: {r.get('schema', '-')}")
        linhas.append(f"  tamanho: {r.get('tamanho_mb')} MB | fontes: {r.get('n_fontes')} | zonas: " +
                      ", ".join(f"{k}={v}" for k, v in (r.get("zonas") or {}).items()))
        if r.get("camadas_complementares"):
            linhas.append("  camadas complementares: " + ", ".join(f"{k}={v}" for k, v in r["camadas_complementares"].items()))
    linhas += [f"  ERRO  {e}" for e in res["erros"]] + [f"  AVISO {a}" for a in res["avisos"]]
    return "\n".join(linhas)


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__); return 2
    como_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    if argv[0] == "--todas":
        alvos = [(s, os.path.join(CIDADES, s, f"{s}.json")) for s in sorted(os.listdir(CIDADES)) if os.path.isdir(os.path.join(CIDADES, s))]
    elif argv[0] == "--arquivo":
        alvos = [(argv[1], argv[1])]
    else:
        alvos = [(argv[0], os.path.join(CIDADES, argv[0], f"{argv[0]}.json"))]
    falhou = False
    for nome, cam in alvos:
        res = validar(cam)
        falhou |= not res["ok"]
        print(json.dumps({nome: res}, ensure_ascii=False, indent=1) if como_json else relatorio(nome, res))
        if not como_json and os.path.isdir(os.path.dirname(cam)):
            for extra in ("REFERENCIAS.md", "fontes", "scripts"):
                if not os.path.exists(os.path.join(os.path.dirname(cam), extra)):
                    print(f"  AVISO pasta da cidade sem '{extra}'")
    return 1 if falhou else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
