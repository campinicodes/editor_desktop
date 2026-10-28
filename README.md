# Editor desktop de cidades – plataforma de zoneamento

Este é um formulário desktop em Python/Tkinter. Ele **cria uma cidade nova**, **atualiza uma cidade existente** e **cria atributos novos** (parâmetros adicionais). O resultado é o `<slug>.json` que a plataforma lê, no schema 1.2 (o 1.1 continua aceito). A validação é feita pelo **mesmo validador da plataforma**, embutido em `validador/`, então o editor funciona sem a plataforma instalada.

## Instalar e abrir (Windows)
1. Instale o Python 3.10 ou mais novo pelo python.org e marque "Add python.exe to PATH". O Tkinter já vem junto.
2. Descompacte `editor_desktop.zip`. No Prompt de Comando, dentro da pasta `editor_desktop`, rode:
   ```
   pip install -r requirements.txt
   python editor.py
   ```
   Para abrir um arquivo ou uma pasta direto, passe o caminho: `python editor.py C:\plataforma\cidades\curitiba-pr`.

No Linux ou no macOS, rode `pip3 install -r requirements.txt` e depois `python3 editor.py`. No Linux também é preciso instalar o pacote `python3-tk`.

**Pasta da plataforma (opcional).** Configure em *Cidade e fontes › Plataforma › Escolher…*. A escolha fica gravada em `~/.editor_zoneamento.json`. Também é possível usar a variável de ambiente `PLATAFORMA_ZONEAMENTO`. Se nenhuma das duas estiver definida e o editor estiver dentro de `plataforma/editor_desktop/`, ele usa a pasta-mãe. Com a plataforma configurada:
- a lista "Da plataforma" abre as cidades existentes;
- "Salvar na plataforma" grava em `cidades/<slug>/<slug>.json`, deixando um `.bak` do arquivo anterior;
- o editor avisa se o schema embutido estiver diferente do schema da plataforma.

## As 5 abas
| Aba | O que faz |
|---|---|
| **Cidade e fontes** | Metadados da cidade: município, UF, IBGE, centro do mapa, zoom, CRS métrico (o botão "sugerir UTM" ajuda), data e marco legal. O slug é gerado sozinho. Aqui também ficam as **fontes** (id, título, lei, link, data e anexo, que é copiado para `fontes/`), a pasta aberta (fontes/geo_raw/scripts preservados, histórico) e as lacunas. |
| **Zonas (fluxo por zona)** | A faixa azul mostra o fluxo: **① criar ou selecionar a zona → ② parâmetros → ③ atributos adicionais → ④ geometria**. "Aplicar e ir para o próximo passo" avança de um passo para o outro. |
| **Atributos adicionais** | Catálogo dos atributos novos da cidade: criar, editar e remover. |
| **Importar em lote** | Geometrias de várias zonas a partir de um campo do arquivo, e parâmetros por CSV. |
| **Validação** | Validador embutido, com os erros e avisos por **zona/campo** em português. Um duplo clique na linha abre a zona e o passo do problema. |

### ① Zona
"+ Nova zona" pede código, nome, tipo (`base`, `sobreposta` ou `eixo`), prioridade e categoria normalizada (combobox). Nas zonas `sobreposta` e `eixo` aparece a **regra de sobreposição**, com estes campos:
- efeito: `substitui`, `usa_indices_de` ou `apenas_alerta`;
- zona cujos índices são usados;
- `aplica_sobre`;
- fundamento;
- alerta;
- `mantem_da_base`;
- distância máxima.

Trocar o código **renomeia** a zona em todo o JSON: feições, `usa_indices_de`, `aplica_sobre`, camadas e lacunas. "Remover zona" é bloqueado enquanto outra zona fizer referência a ela.

### ② Parâmetros padrão
Cada linha da grade tem valor, **unidade travada** (CA = coeficiente; taxas = fração; m; m2; pavimentos; códigos de uso), fonte (combobox com os ids das fontes), artigo/anexo, observação e forma (combobox).
- Taxas aceitam `0,3` ou `30%`. Decimal com vírgula também é aceito.
- **Valor vazio = sem dado.** O parâmetro vira `null`, ou `forma: sem_dado` quando há observação. O motivo vai para `lacunas`.
- O botão **{…}** abre o editor estruturado de **faixa** (mín/máx), **condicional** (lista de casos com condição, forma, valor e faixa), **fórmula** e **lista**. Lá é possível editar o JSON do parâmetro direto, com os modelos prontos e o botão "conferir".
- "+ Parâmetro local em 'outros'" cria um `parametros.outros.<chave>` só dessa zona.

### ③ Atributos adicionais – como criar um atributo novo
1. Na tela da zona, no passo ③, clique em **"+ Novo atributo (todas as zonas)…"**. O mesmo botão existe na aba *Atributos adicionais*.
2. Preencha os campos:
   - **Rótulo**, por exemplo "Índice de arborização". A **chave** em snake_case é sugerida sozinha (`indice_de_arborizacao`) e pode ser editada;
   - **unidade**, por exemplo `fracao`, `m` ou `uh/ha`;
   - **tipo**: número, inteiro, fração (0–1), lista ou texto;
   - opcionais: descrição, grupo e fonte padrão.
3. O atributo entra em `definicoes_parametros_adicionais` e passa a existir **em todas as zonas**, como `parametros_adicionais.<chave>` com valor `null`. Preencha o valor de cada zona no passo ③. O formato é o mesmo de um parâmetro: valor, fonte, artigo, forma e {…}.
4. Depois de validar e salvar ou exportar, reinicie a plataforma. A consulta mostra a tabela **"Parâmetros adicionais da cidade"** com o rótulo e a unidade do catálogo, sem nenhuma mudança de código.

Editar um atributo muda rótulo, unidade e descrição; a chave e o tipo ficam fixos. Remover apaga o atributo do catálogo e de todas as zonas, depois de uma confirmação.

### ④ Geometria
Escolha um KMZ, KML ou GeoJSON. Se o arquivo tiver várias feições, filtre por campo e valor. Depois informe:
- EPSG de origem: vazio = automático, e um GeoJSON em UTM é detectado;
- **oficial** sim ou não;
- **erro estimado** em metros;
- método;
- fonte.

O editor reprojeta para EPSG:4326, corrige com `make_valid`, simplifica com tolerância de cerca de 2 m, arredonda para 6 casas e **calcula a área no CRS métrico** da cidade. O arquivo original é copiado para `geo_raw/` e registrado em `geografico.camadas`. "Substituir" troca a geometria da zona; desmarcado, as feições novas são acrescentadas.

A **pré-visualização** desenha os contornos simplificados da zona ("Desenhar zona") ou da cidade inteira. Arquivos grandes, acima de 5 MB como o Rio com 18 MB, abrem em segundo plano e **não** desenham nada sozinhos: o desenho só sai quando alguém clica no botão.

## Importar em lote
- **Geometrias por campo:** um único arquivo com todas as zonas e um campo com o código, por exemplo `zona` ou `SIGLA`. Cada feição vai para a zona com o código correspondente. Opcionalmente, o editor **cria as zonas que faltam**. O resultado lista as zonas atribuídas, criadas e ignoradas, com a área de cada uma.
- **Parâmetros por CSV** (o botão "Salvar modelo CSV…" gera um exemplo):
  ```
  zona;parametro;valor;unidade;fonte_id;artigo;observacao;forma
  ZR1;ca_basico;1;coeficiente;LEI1;Anexo II;;
  ZR1;taxa_ocupacao;50%;fracao;LEI1;Anexo II;;
  ZR1;recuos.frontal;5;m;LEI1;art. 20;;
  ZR1;usos_permitidos;R1, R2, C1;codigos_de_uso;LEI1;Anexo III;;lista
  ZR1;indice_arborizacao;0,2;fracao;LEI1;art. 30;;
  ```
  Regras do CSV:
  - o separador pode ser `;` ou `,`, e o editor detecta qual é;
  - as colunas `observacao` e `forma` são opcionais;
  - `parametro` pode ser um caminho padrão (`ca_basico`, `recuos.frontal`…), `outros.<chave>`, a chave ou o rótulo de um atributo adicional, ou um **nome novo**, que **cria o atributo adicional** com a unidade da linha;
  - linhas com erro (zona inexistente, unidade errada, fonte desconhecida) aparecem com o número da linha e não impedem as outras.

## Gravar
| Botão | O que faz |
|---|---|
| **✔ Validar** | Roda o validador embutido. Ele é uma cópia byte a byte de `plataforma/validar_cidade.py` e do schema, e tem os mesmos resultados nas 9 cidades. |
| **Exportar pasta da cidade…** | Gera `<destino>/<slug>/` com `<slug>.json`, `REFERENCIAS.md` (gerado se não existir), `fontes/` (anexos), `geo_raw/` (arquivos de geometria importados) e `scripts/README.md`. Isso **só acontece com a validação APROVADA**. Se a validação reprovar, o editor oferece exportar um **rascunho** em `<slug>__RASCUNHO/`, que a plataforma ignora. Para publicar a cidade, copie a pasta exportada para `plataforma/cidades/`, ou acrescente o destino a `PLATAFORMA_CIDADES`, e reinicie a app. |
| **Atualizar no lugar (backup .bak)** | Use para uma cidade aberta pela pasta. O editor regrava `<slug>.json` na própria pasta e guarda o anterior como `<slug>.json.bak`. `fontes/`, `geo_raw/`, `scripts/` e `REFERENCIAS.md` são preservados, e um anexo novo com o nome de um arquivo existente ganha o sufixo `_2`, sem sobrescrever nada. Exige APROVADO. |
| **Salvar na plataforma** | Grava `cidades/<slug>/<slug>.json` na plataforma configurada, com `.bak`. |
| **Salvar JSON como…** | Grava o JSON onde você escolher. Os anexos são copiados para `fontes/` e `geo_raw/` ao lado do arquivo. |

## Atualizar uma cidade existente
1. Clique em **"Atualizar cidade existente (abrir pasta)…"** e escolha `cidades/<slug>/`. O editor carrega o JSON e mostra o que há em `fontes/`, `geo_raw/`, `scripts/` e `REFERENCIAS.md`.
2. Edite o que precisar: parâmetros de uma zona; zonas (incluir, renomear, remover, trocar a geometria no passo ④ com "Substituir"); fontes; atributos.
3. Grave com **Validar → "Atualizar no lugar"**, ou com "Exportar pasta da cidade…" para outro destino. Na exportação, a pasta de origem é copiada inteira, com fontes, geo_raw e scripts.
4. A atualização fica registrada no JSON de forma retrocompatível (schema 1.2):
   - `data_atualizacao` recebe a data do dia;
   - `historico_alteracoes` ganha `{data, ferramenta: "editor_desktop", resumo}`, por exemplo "zona Z3: ca_basico; zona Z5: geometria substituída (geo_raw/…)";
   - `data_levantamento` não muda.

**Campos desconhecidos são preservados.** O editor só reescreve o que você mudou. Abrir e gravar sem mexer em nada produz um JSON idêntico byte a byte ao original, e isso é testado em Campo Grande e Curitiba. "Aplicar" em todas as zonas das 9 cidades sem nenhuma mudança também não altera nada.

## Como insiro uma cidade nova na plataforma?
- **Sem o editor:** basta pôr a pasta `cidades/<slug>/<slug>.json` válida, APROVADA em `python3 validar_cidade.py <slug>`, e reiniciar a app. A pasta precisa ter o mesmo nome do slug. A app descobre as cidades sozinha.
- **Com o editor:** Nova cidade → preencher → Validar → **Exportar pasta da cidade** → copiar `<slug>/` para `plataforma/cidades/` → reiniciar a app.

## Arquivos
```
editor.py              interface (Tkinter/ttk)
modelo.py              regras sem interface: abrir/salvar/exportar, zonas, parâmetros, atributos, geometria, CSV
validador/             cópia idêntica de validar_cidade.py + schema/cidade.schema.json (validação embutida)
empacotar.py           --sincronizar (recopia o validador da plataforma) · --conferir · --zips
requirements.txt       shapely, pyproj, jsonschema
screenshots/           capturas de tela (geradas por testes/gerar_screenshots.py)
testes/test_modelo.py  testes do editor (dentro da plataforma): python3 testes/test_modelo.py
```
Se o validador ou o schema da plataforma mudar, rode `python3 empacotar.py --sincronizar`. O teste `test_c` falha enquanto a cópia embutida estiver diferente.

## Limitações
- A pré-visualização é só um contorno, sem mapa de fundo. Para conferir a posição real, use a app web.
- O editor não edita `camadas_complementares` (permeabilidade, macrozona, restrição). Essas camadas são preservadas como estão.
- Campos que não têm tela, como `macrozonas_observacao`, são preservados e podem ser editados no JSON.
- No editor de estrutura {…}, condicionais aninhadas além de 1 nível só podem ser editadas como JSON.
