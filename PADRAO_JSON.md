# Padrão de dados – Plataforma multicidades de parâmetros urbanísticos (STAR/Tenda)

> **FONTE DE VERDADE: `schema/cidade.schema.json` (JSON Schema draft 2020-12, `schema_versao` "1.1").** Este documento explica o schema. Se os dois divergirem, vale o schema. Validação: `python3 validar_cidade.py <slug>` (schema + checagens semânticas). Guia para quem consome os dados: `schema/README.md`.

## NORMALIZAÇÃO OBRIGATÓRIA (desde 27/10/2026 – nenhuma chave foi renomeada)
Atalho: gere o JSON como antes e rode `python3 schema/normalizar_cidade.py cidades/<slug>/<slug>.json --categorias Z1=mista_alta_densidade,...`. Ele converte só a FORMA (nunca inventa) e guarda o texto em `texto_original`; o que não der para converter vira `forma:"texto"` e aparece como aviso.
1. `schema_versao: "1.1"`; `codigo_ibge` string de 7 dígitos; códigos de zona/camada/macrozona são **string** não vazia, exatamente como na lei ou na base oficial, sem espaços nas pontas (ex.: `Z1`, `ZEIS2`, `AEIS FAVELA`). O mesmo código precisa aparecer em `features[].properties.codigo`, `parametros_por_codigo` e `alerta_por_codigo`.
2. **Todo parâmetro** = `{valor, unidade, fonte_id, artigo_anexo, observacao, forma}` (todas as chaves presentes, podem ser null) **ou** `null`. Opcionais: `faixa`, `condicionais`, `formula`, `texto_original`. Nenhuma outra chave.
3. `valor` é **number**, **lista de strings** (só `forma:"lista"`) ou **null**. Nunca texto. `forma` diz como ler:
   `unico` (valor number) · `faixa` (`faixa:{min,max}`, valor null) · `condicional` (`condicionais:[…]`, valor null) · `formula` (`formula:"h/6"`, mínimo/máximo em `faixa`) · `lista` · `livre` (sem limite) · `herda_da_base` (igual à zona base subjacente) · `nao_aplicavel` · `sem_dado` (não encontrado → lacunas) · `texto` (último recurso: `texto_original` obrigatório).
4. Condicional = `{condicao (texto curto), forma, valor, codigo?, faixa?, formula?, texto_original?, observacao?}`; herda unidade e fonte do pai. Ex.: TO "térreo 0,7 / demais 0,5", testada "meio de quadra 10 / esquina 15", permeabilidade por Zona Ambiental (`codigo:"ZA1"`).
5. Unidades fixas: CA → `"coeficiente"`; taxas → `"fracao"` (0–1; **30% → 0.3**); gabarito/recuos/testada → `"m"`; lote → `"m2"`; pavimentos → `"pavimentos"` (inteiro); usos → `"codigos_de_uso"`; densidade → `"hab/ha"` ou `"uh/ha"`; vagas e `outros.*` → texto livre.
6. `parametros` tem sempre as 14 chaves do padrão (ausente = null). Chaves livres **só** em `parametros.outros` e `parametros_por_codigo` (snake_case).
7. Zona: `categoria_normalizada` obrigatória (vocabulário abaixo) + `categoria_criterio` (texto, recomendado); `observacoes` é **lista de strings**.
8. `outorga_onerosa`, `zeis_his`, `outros_parametros` = `{resumo, fonte_id, artigo_anexo, itens:[ {chave, titulo, …parâmetro} ]}` (sem chaves livres); `resumo_mcmv` = lista de strings; `macrozonas[]` = `{codigo, nome, descricao, parametros:{<chave>: parâmetro}}`; `lacunas[]` = `{item, motivo}`.
9. `regra_sobreposicao.mantem_da_base` é lista (vazia se nada); `geografico.camadas[]` aceita `n_feicoes` opcional. `geografico.servidor_oficial` = URL (string) ou null; anotações extras de geografia vão em `geografico.notas_tecnicas` (livre, não normativo).

`categoria_normalizada` (classificação do analista, não termo legal; densidade pelo CA máximo: ≤ 1,5 baixa · ≤ 3 média · > 3 alta; "residencial" se o multifamiliar/usos não residenciais são restritos, senão "mista"):
`residencial_baixa_densidade` `residencial_media_densidade` `residencial_alta_densidade` `mista_baixa_densidade` `mista_media_densidade` `mista_alta_densidade` `centralidade` `eixo` `especial_interesse_social` `especial_economica` `industrial` `ambiental` `patrimonio_cultural` `institucional` `expansao` `rural` `outra`

---
Referência de arquitetura: /workspace/legislacao/campo-grande-ms.json (leia a estrutura dele). Todas as cidades seguem o MESMO esqueleto.

## Pastas
/workspace/legislacao/plataforma/cidades/<slug>/      slug = nome-uf minúsculo sem acento, ex.: porto-alegre-rs, curitiba-pr, goiania-go, campo-grande-ms, rio-de-janeiro-rj, salvador-ba, fortaleza-ce, recife-pe, joao-pessoa-pb
  <slug>.json          ARQUIVO ÚNICO com parâmetros + citações + geometrias (obrigatório)
  REFERENCIAS.md       lista legível das leis/decretos/camadas usadas, com número, data, artigo/anexo e link oficial
  fontes/              PDFs/HTML oficiais baixados (+ .txt extraído)
  geo_raw/             camadas originais baixadas (opcional)
  scripts/             scripts que geram o JSON (reprodutível)

## Chaves de topo do <slug>.json (obrigatórias)
- schema_versao: "1.1" (era "1.0")
- municipio, uf, slug, codigo_ibge, data_levantamento (AAAA-MM-DD)
- centro_mapa: {lat, lon, zoom}
- marco_legal_vigente: resumo das leis vigentes (plano diretor, LUOS/zoneamento, código de obras, outorga, ZEIS) e revisões em andamento
- fontes: [ {id: "F1", titulo, lei, data, url} ]
- macrozonas: [ {codigo, nome, descricao, parametros} ]
- zonas: [ ZONA ]  (ver abaixo)
- camadas_complementares: { <nome>: CAMADA }
- outorga_onerosa, zeis_his, outros_parametros: BLOCO {resumo, fonte_id, artigo_anexo, itens:[{chave, titulo, …parâmetro}]}
- resumo_mcmv: lista de strings com onde CA e gabarito favorecem MCMV/HIS, regras de ZEIS/HIS, vagas, gatilhos de custo (EIV etc.)
- geografico: {descricao, crs:"EPSG:4326", crs_area:"EPSG:<UTM SIRGAS 2000 da cidade>", servidor_oficial, camadas:[{nome, arquivo/campo, fonte_url, data_download, oficial:true|false, metodo:"vetor oficial"|"digitalização aproximada de mapa oficial", erro_estimado_m}], regras_de_consulta (texto), limitacoes}
- lacunas: [ {item, motivo} ]

## ZONA (cada item de zonas[])
{
  "codigo": "Z1",               # deve bater com properties.codigo das feições
  "nome": "...", "descricao": "...",
  "tipo": "base" | "sobreposta" | "eixo",   # base = zoneamento que cobre o território; sobreposta = ZEIS, setores especiais, centralidades, operações urbanas; eixo = linha (testada)
  "prioridade": 0,              # inteiro; base = 0; sobrepostas/eixos maiores prevalecem (ex.: ZEIE 30, centralidade 20, eixo 10)
  "categoria_normalizada": "mista_media_densidade",   # vocabulário comum (ver NORMALIZAÇÃO OBRIGATÓRIA)
  "categoria_criterio": "...",                        # por que o analista classificou assim
  "regra_sobreposicao": null | {
      "efeito": "substitui" | "usa_indices_de" | "apenas_alerta",
      "usa_indices_de": "Z4" | null,
      "aplica_sobre": ["Z5"] | null,      # null = sobre qualquer base
      "limiar_pct": 50,                   # % mínima do terreno coberta para aplicar
      "requer_testada": false,            # true p/ eixos: só vale se o lote tiver frente para a via
      "distancia_max_m": 50,              # p/ eixos
      "fundamento": "lei/artigo"
  },
  "parametros": {               # cada parâmetro = {valor, unidade, fonte_id, artigo_anexo, observacao, forma, [faixa, condicionais, formula, texto_original]} ou null
     "ca_minimo", "ca_basico", "ca_maximo", "taxa_ocupacao", "gabarito_altura_max_m", "gabarito_pavimentos",
     "taxa_permeabilidade", "recuos": {"frontal","lateral","fundos"}, "lote_minimo_m2", "testada_minima_m",
     "usos_permitidos", "vagas", "densidade", "outros": {...}
  },
  "observacoes": ["...", "..."],
  "geometria": { "type":"FeatureCollection", "crs":"EPSG:4326 (lon, lat)", "fonte":"...", "oficial": true|false, "features":[ {type:Feature, properties:{codigo, nome, ...}, geometry} ] }
}
Geometrias: EPSG:4326, coordenadas arredondadas a 6 casas, simplificação ≤ ~2 m (preserve_topology) para manter o JSON abaixo de ~40 MB por cidade.

## CAMADA (cada item de camadas_complementares)
{ "papel": "permeabilidade" | "macrozona" | "restricao" | "informativa",
  "descricao", "fonte", "oficial": true|false,
  "parametros_por_codigo": { "<codigo>": {<chave>: parâmetro} } | null,
  "features": [ ... properties.codigo ... ] }
"restricao" = áreas que geram alerta (APP, tombamento, aeroporto/cone, áreas de risco etc.).

## Regras de pesquisa (absolutas)
- Só fontes oficiais e públicas (leis, planos diretores, diários oficiais, sites/geoportais das prefeituras, dados abertos municipais, câmaras). Nunca inventar: o que não achar = null + entrada em lacunas.
- Toda informação com fonte_id + artigo/anexo + link.
- Geografia: preferir vetor oficial (ArcGIS REST/WFS/GeoServer/dados abertos públicos, sem login). Se só houver mapa PDF/imagem, PODE georreferenciar/vetorizar (o Alexandre autorizou aproximado), marcando oficial:false, metodo "digitalização aproximada de mapa oficial" e erro estimado.
- Não contornar logins nem bloqueios; não usar APIs internas não públicas; não enviar nada a ninguém; trabalhar só no box.
- Validar com `python3 validar_cidade.py <slug>` (JSON Schema + semântica) e conferir que todo codigo em zonas[] tem feições e vice-versa.

## Campos OPCIONAIS (adicionados em 27/10/2026 – retrocompatíveis; a app funciona sem eles)
Todos opcionais. JSONs sem eles continuam válidos e a app usa os padrões entre parênteses.
- Topo: `orgao_confirmacao` (texto do órgão onde confirmar, ex. "PLANURB/SEMADUR – GDU"; padrão: "prefeitura").
- Topo: `macrozonas_observacao` (texto).
- `regra_sobreposicao.alerta`: texto exibido quando a zona sobreposta/eixo toca o terreno (padrão: mensagem genérica com `fundamento`).
- `regra_sobreposicao.mantem_da_base`: lista de caminhos de parâmetros (ex.: `"outros.fator_oodc_fid"`) que continuam com o valor da base original quando `usa_indices_de` troca os índices (padrão: nenhum).
- CAMADA: `alerta_por_codigo`: {"<codigo>": "texto do alerta"} para camadas `restricao` (padrão: `descricao`).
- CAMADA: `fonte_id` e `artigo_anexo` da camada inteira (citação do alerta), e `observacao`.
- `geografico.raio_divisa_m` (padrão 30), `geografico.pct_minimo_significativo` (padrão 0,5 %: abaixo disso a sobreposição é tratada como resíduo de borda).
- `geografico.camadas_detalhe`, `geografico.regras_de_consulta_texto` e `geografico.notas_tecnicas` (anotações livres, não normativas).
- `parametros.outros` pode conter qualquer índice local (ex.: `indice_elevacao`, `fator_oodc_fid`). (Desde a 1.1 a chave `unidade` é obrigatória, podendo ser null – ver NORMALIZAÇÃO OBRIGATÓRIA.)
- Fonte: `arquivo_local` (nome do PDF em fontes/).

## Schema 1.2 (28/10/2026) – atributos adicionais e histórico (retrocompatível)
`schema_versao` aceita **"1.1"** (as 9 cidades atuais, sem mudança) e **"1.2"**. A 1.2 só acrescenta blocos OPCIONAIS; um JSON 1.1 continua válido e a app lê os dois.

**Atributos adicionais (parâmetros novos sem mexer no schema)**
- Topo: `definicoes_parametros_adicionais` = catálogo da cidade, lista de `{chave, rotulo, unidade, tipo, descricao?, grupo?, fonte_id?}`.
  - `chave`: snake_case (`^[a-z][a-z0-9_]*$`), única e diferente das 14 chaves padrão de `parametros` (para estas, use o padrão).
  - `tipo`: `numero` | `inteiro` | `fracao` (0–1) | `lista` | `texto`. `unidade` é fixa para o atributo (ou null).
- Zona: `parametros_adicionais` = `{<chave>: parâmetro | null}`, com o valor no **mesmo formato de parâmetro** (`{valor, unidade, fonte_id, artigo_anexo, observacao, forma, [faixa], [condicionais], [formula], [texto_original]}`).
- Regras do validador: chave fora do catálogo = ERRO; tipo incompatível (fração > 1, inteiro com decimal, lista × unico) = ERRO; unidade diferente do catálogo = AVISO; zona sem alguma chave do catálogo = AVISO (tratada como null). O editor grava todas as chaves em todas as zonas (null quando sem dado).
- Diferença para `parametros.outros`: `outros` é livre e sem catálogo; os adicionais têm rótulo, unidade e tipo declarados uma vez, e a app os exibe de forma genérica ("Parâmetros adicionais da cidade") em qualquer zona.
- Exemplo: `"definicoes_parametros_adicionais": [{"chave": "indice_arborizacao", "rotulo": "Índice de arborização", "unidade": "fracao", "tipo": "fracao"}]` e, na zona, `"parametros_adicionais": {"indice_arborizacao": {"valor": 0.2, "unidade": "fracao", "fonte_id": "F01", "artigo_anexo": "art. 30", "observacao": null, "forma": "unico"}}`.

**Histórico de atualização**
- Topo: `data_atualizacao` (AAAA-MM-DD da última alteração; `data_levantamento` continua sendo a do levantamento original).
- Topo: `historico_alteracoes` = lista (da mais antiga para a mais nova) de `{data, resumo, ferramenta?, autor?}`. O editor desktop acrescenta um item por dia de edição, com o resumo do que mudou (ex.: "zona Z3: ca_basico; zona Z5: geometria substituída").
- Os dois só são aceitos com `schema_versao: "1.2"`; o editor sobe a versão sozinho quando grava um deles. Consumidores podem ignorá-los.

## Como a app interpreta o padrão (motor genérico)
1. Zonas `base`: calcula área/% do terreno em cada uma; base predominante = maior área.
2. Candidatas à zona aplicável: `sobreposta` com efeito `substitui` cobrindo ≥ `limiar_pct` (padrão 50) e com `aplica_sobre` nulo ou contendo a base; `eixo` a ≤ `distancia_max_m` (padrão 50). Vence a maior `prioridade`; senão, a base.
3. `usa_indices_de`: se a sobreposta cobre ≥ `limiar_pct` e a base está em `aplica_sobre`, os índices da base passam a ser os da zona indicada (exceto os listados em `mantem_da_base`).
4. `apenas_alerta` e coberturas abaixo do limiar: só alertas.
5. `requer_testada: true`: alerta de testada e devolve também os índices da base como alternativa.
6. camadas_complementares: `permeabilidade` → parâmetros do código predominante sobrescrevem `taxa_permeabilidade`; `macrozona` → parâmetros do código predominante; `restricao` → alerta para cada código que intersecta; `informativa` → só listada.
7. `herda_da_base` numa sobreposta: o consumidor usa o valor da zona base predominante.
8. `parametros_adicionais` (1.2): devolvidos na ficha da zona aplicável junto com os rótulos/unidades do catálogo; a app os lista em "Parâmetros adicionais da cidade". Não entram nas regras de sobreposição (`mantem_da_base` vale só para `parametros`).
9. Validação: `python3 validar_cidade.py <slug>`.
