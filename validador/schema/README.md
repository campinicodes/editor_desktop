# schema/ – como consumir os dados das cidades

`cidade.schema.json` (JSON Schema draft 2020-12) é a **fonte de verdade** do formato `cidades/<slug>/<slug>.json`, com `schema_versao` "1.1" ou "1.2" (a 1.2 acrescenta, de forma opcional, `definicoes_parametros_adicionais` + `zonas[].parametros_adicionais` e `data_atualizacao` + `historico_alteracoes`; detalhes em `../PADRAO_JSON.md`). Todo arquivo que passa no schema tem as mesmas chaves e os mesmos tipos, em qualquer cidade. Por isso, quem consome não precisa de código por cidade.

| Arquivo | Para quê |
|---|---|
| `cidade.schema.json` | o schema |
| `normalizar_cidade.py` | converte um JSON legado (1.0) para 1.1 sem inventar valores: `python3 normalizar_cidade.py <arq.json> --categorias Z1=...` |
| `exemplos/consumir.py` | exemplo executável abaixo |
| `../validar_cidade.py` | schema + checagens semânticas (fonte_id existente, geometrias válidas, atributos adicionais × catálogo…) |
| `../editor_desktop/` | editor desktop (Tkinter) que cria/atualiza JSONs neste schema; leva uma cópia idêntica do schema e do validador |

## Modelo em 30 segundos
- `zonas[]`: cada zona tem `codigo`, `tipo` (`base` / `sobreposta` / `eixo`), `categoria_normalizada` (vocabulário comum entre cidades), `regra_sobreposicao`, `parametros` e `geometria` (GeoJSON EPSG:4326, lon/lat).
- `parametros` tem sempre as mesmas 14 chaves: `ca_minimo`, `ca_basico`, `ca_maximo`, `taxa_ocupacao`, `gabarito_altura_max_m`, `gabarito_pavimentos`, `taxa_permeabilidade`, `recuos.{frontal,lateral,fundos}`, `lote_minimo_m2`, `testada_minima_m`, `usos_permitidos`, `vagas`, `densidade`, `outros{…}`.
- Cada parâmetro é `null` (não levantado) ou `{valor, unidade, fonte_id, artigo_anexo, observacao, forma, [faixa], [condicionais], [formula], [texto_original]}`. **Leia pela `forma`**:

| forma | onde está o dado |
|---|---|
| `unico` | `valor` (number) |
| `lista` | `valor` (lista de strings, ex. códigos de uso) |
| `faixa` | `faixa.min` / `faixa.max` (null = aberto) |
| `condicional` | `condicionais[]`: `{condicao, codigo?, forma, valor, faixa?, formula?}`. Cada item tem a mesma leitura (recursiva, 1 nível) |
| `formula` | `formula` (ex. `"h/6"`), com o mínimo em `faixa.min` |
| `livre` | sem limite legal |
| `herda_da_base` | use o parâmetro da zona base sob a sobreposta |
| `nao_aplicavel` / `sem_dado` | não se aplica / não encontrado (ver `lacunas`) |
| `texto` | só `texto_original`. A regra não é estruturável; mostre o texto ao usuário |

- Unidades: taxas sempre em **fração 0–1** (`"fracao"`), CA em `"coeficiente"`, metros em `"m"`, áreas em `"m2"`.
- Citação: `fonte_id` aponta para `fontes[]` (`lei`, `data`, `url`), e `artigo_anexo` dá o dispositivo legal.
- Camadas extras (`camadas_complementares`) trazem `papel`:
  - `permeabilidade`: os parâmetros de `parametros_por_codigo` sobrescrevem os da zona;
  - `macrozona`: parâmetros do código predominante;
  - `restricao`: gera alerta (`alerta_por_codigo`);
  - `informativa`.
- (1.2) Atributos adicionais: `definicoes_parametros_adicionais[]` declara `{chave, rotulo, unidade, tipo}`; cada zona traz `parametros_adicionais.<chave>` no mesmo formato de parâmetro (ou null). Para ler de forma genérica:
  ```python
  defs = {d["chave"]: d for d in cidade.get("definicoes_parametros_adicionais") or []}
  for k, d in defs.items():
      print(d["rotulo"], ler((z.get("parametros_adicionais") or {}).get(k)), d["unidade"])
  ```

## Exemplo mínimo (sem a app)
```python
import json
from jsonschema import Draft202012Validator

schema = json.load(open("schema/cidade.schema.json", encoding="utf-8"))
cidade = json.load(open("cidades/campo-grande-ms/campo-grande-ms.json", encoding="utf-8"))
assert not list(Draft202012Validator(schema).iter_errors(cidade))   # estrutura garantida

def ler(p):
    if p is None: return None
    f = p["forma"]
    if f in ("unico", "lista"): return p["valor"]
    if f == "faixa":            return (p["faixa"]["min"], p["faixa"]["max"])
    if f == "condicional":      return {c["condicao"]: ler({**c, "faixa": c.get("faixa")}) for c in p["condicionais"]}
    if f == "formula":          return p["formula"]
    return f                    # livre | herda_da_base | nao_aplicavel | sem_dado | texto

fontes = {f["id"]: f for f in cidade["fontes"]}
for z in cidade["zonas"]:
    ca = z["parametros"]["ca_maximo"]
    print(z["codigo"], z["categoria_normalizada"], ler(ca), fontes[ca["fonte_id"]]["lei"] if ca and ca["fonte_id"] else "-")
```
Versão completa, que também acha a zona de um ponto com shapely: `python3 schema/exemplos/consumir.py`. Saída: `Z1 mista_alta_densidade 5 Lei Complementar n. 341/2018 …`, `ZEIS2 especial_interesse_social herda_da_base …`.

Para cruzar um terreno com as zonas, com áreas em UTM, prioridade de sobrepostas, eixos e `usa_indices_de`, veja as regras em `../PADRAO_JSON.md` ("Como a app interpreta o padrão"). O `app/motor.py` implementa essas regras em Python e pode ser importado, mas é opcional.
