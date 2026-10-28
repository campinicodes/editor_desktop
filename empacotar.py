"""Sincroniza o validador embutido e gera os pacotes.

    python3 empacotar.py --sincronizar        copia validar_cidade.py e cidade.schema.json da plataforma para validador/
    python3 empacotar.py --conferir           só confere se a cópia embutida é idêntica (código de saída 1 se não for)
    python3 empacotar.py --zips [DESTINO]     sincroniza e gera DESTINO/editor_desktop.zip e DESTINO/plataforma_zoneamento.zip
                                              (padrão: a pasta acima da plataforma)

editor_desktop.zip: editor (editor.py, modelo.py, README, requirements, screenshots) + validador/ (validador + schema) + PADRAO_JSON.md.
plataforma_zoneamento.zip: a plataforma inteira (com editor_desktop/), sem fontes/, geo_raw/, caches, __pycache__ e .bak.
"""
import filecmp, os, shutil, sys, zipfile

AQUI = os.path.dirname(os.path.abspath(__file__))
PLAT = os.path.dirname(AQUI)
PARES = [(os.path.join(PLAT, "validar_cidade.py"), os.path.join(AQUI, "validador", "validar_cidade.py")),
         (os.path.join(PLAT, "schema", "cidade.schema.json"), os.path.join(AQUI, "validador", "schema", "cidade.schema.json"))]
IGNORAR_DIRS = {"__pycache__", "fontes", "geo_raw", "geo"}   # geo/ = intermediários pesados de vetorização
IGNORAR_ARQ = (".pyc", ".bak", ".tmp")
IGNORAR_NOMES = {".cache_descoberta.json", ".DS_Store"}


def conferir():
    dif = [d for o, d in PARES if not (os.path.isfile(d) and filecmp.cmp(o, d, shallow=False))]
    for d in dif:
        print("DIFERENTE:", os.path.relpath(d, PLAT))
    return not dif


def sincronizar():
    for o, d in PARES:
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copyfile(o, d)
        print("copiado", os.path.relpath(o, PLAT), "→", os.path.relpath(d, PLAT))
    assert conferir()


def _arquivos(raiz, excluir_dirs=()):
    for base, dirs, arqs in os.walk(raiz):
        rel = os.path.relpath(base, raiz)
        dirs[:] = sorted(x for x in dirs if x not in IGNORAR_DIRS and not x.startswith(".") and os.path.normpath(os.path.join(rel, x)) not in excluir_dirs
                         and not x.endswith("__RASCUNHO"))
        for a in sorted(arqs):
            if a.endswith(IGNORAR_ARQ) or a in IGNORAR_NOMES or a.startswith("."):
                continue
            yield os.path.join(base, a), os.path.normpath(os.path.join(rel, a))


def zip_editor(destino):
    saida = os.path.join(destino, "editor_desktop.zip")
    with zipfile.ZipFile(saida + ".tmp", "w", zipfile.ZIP_DEFLATED) as z:
        for a, rel in _arquivos(AQUI, excluir_dirs={"testes"}):
            z.write(a, os.path.join("editor_desktop", rel))
        z.write(os.path.join(PLAT, "PADRAO_JSON.md"), "editor_desktop/PADRAO_JSON.md")
        z.write(os.path.join(PLAT, "schema", "README.md"), "editor_desktop/validador/schema/README.md")
    os.replace(saida + ".tmp", saida)
    return saida


def zip_plataforma(destino):
    saida = os.path.join(destino, "plataforma_zoneamento.zip")
    cidades = os.path.join(PLAT, "cidades")
    ficticias = [s for s in os.listdir(cidades) if "ficticia" in s]
    if ficticias:
        raise SystemExit(f"cidade fictícia em plataforma/cidades/: {ficticias} – remova antes de empacotar")
    with zipfile.ZipFile(saida + ".tmp", "w", zipfile.ZIP_DEFLATED) as z:
        for a, rel in _arquivos(PLAT):
            z.write(a, os.path.join("plataforma_zoneamento", rel))
    os.replace(saida + ".tmp", saida)
    return saida


def main(args):
    if args and not os.path.isfile(PARES[0][0]):
        print("Plataforma não encontrada: rode este script dentro de plataforma/editor_desktop/ (no pacote avulso ele não é necessário).")
        return 1
    if "--conferir" in args:
        ok = conferir()
        print("validador embutido idêntico" if ok else "rode: python3 empacotar.py --sincronizar")
        return 0 if ok else 1
    if "--sincronizar" in args:
        sincronizar()
    if "--zips" in args:
        sincronizar()
        i = args.index("--zips")
        destino = args[i + 1] if len(args) > i + 1 and not args[i + 1].startswith("--") else os.path.dirname(PLAT)
        for s in (zip_editor(destino), zip_plataforma(destino)):
            with zipfile.ZipFile(s) as z:
                print(f"{s}: {len(z.namelist())} arquivos, {os.path.getsize(s) / 1e6:.1f} MB")
    if not args:
        print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
