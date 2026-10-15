# Radar de Vagas NE — T.I. no Nordeste

Recurso que **busca vagas de Tecnologia da Informação a cada 1 hora** nos 9 estados do
Nordeste e as exibe num **painel visual**, com um **ambiente exclusivo para o Ceará**.

| Página | O que mostra |
|---|---|
| `docs/index.html` — **Nordeste** | mapa em mosaico dos estados (clique para filtrar), áreas de T.I., nível, evolução diária, empresas que mais contratam e a lista de vagas |
| `docs/ceara.html` — **Ambiente Ceará** | somente vagas de T.I. no CE: vagas por cidade (Fortaleza, RMF, Cariri, Sobral…), áreas, modalidade, nível, evolução e empresas |

Nos dois ambientes há busca livre e filtros por local, área, nível, modalidade e fonte,
além de atalhos para **novas (24h)**, **remoto/híbrido** e **vagas salvas** (★, guardadas no navegador).
O painel se recarrega sozinho a cada 5 minutos e mostra quando foi a última coleta.

## Fontes

| Fonte | Como é lida |
|---|---|
| **Gupy** (portal.gupy.io) | API pública do portal, por termo × estado. Cobre também as páginas de carreira hospedadas na Gupy de muitas empresas da região |
| **Vagas.com** | páginas `vagas-de-<termo>-em-<estado>` |
| **Sólides** (vagas.solides.com.br) | API JSON do portal, com plano B lendo a página de busca (`__NEXT_DATA__`/JSON-LD) |
| **Portais institucionais** | lista em [`config/portais_institucionais.json`](config/portais_institucionais.json): Greenhouse, Lever ou qualquer página de carreiras com dados estruturados (JSON-LD `JobPosting` ou Next.js) |

Cada fonte é independente: se uma estiver fora do ar ou mudar o layout, as demais seguem
funcionando e o painel exibe o status de cada uma (e de cada portal institucional) no rodapé.
Vagas que deixam de aparecer ficam esmaecidas por até 7 dias e depois saem do painel.

### Como uma vaga entra no painel
1. **É de T.I.?** — o título é classificado em uma de 11 áreas (Desenvolvimento, Dados & IA,
   Infraestrutura & Cloud, Segurança, Suporte, QA, Produto, UX/UI, ERP, Gestão de T.I., Outros)
   por regras em [`scraper/comum.py`](scraper/comum.py), com exclusões para falsos positivos
   (ex.: “Analista de Redes **Sociais**”, “Técnico de Enfermagem”).
2. **É do Nordeste?** — o estado/cidade informado precisa ser de AL, BA, CE, MA, PB, PE, PI, RN ou SE.
3. **Duplicada?** — a mesma vaga (título + empresa + cidade) vinda de portais diferentes aparece
   uma vez só, com o link “também em …”.

## Como funciona a atualização de hora em hora

O workflow [`.github/workflows/buscar-vagas.yml`](.github/workflows/buscar-vagas.yml) roda no
minuto 7 de cada hora: executa os testes, coleta as vagas, grava `docs/data/vagas.json` e
`docs/data/historico.json` no repositório e publica o painel no **GitHub Pages**.

### Ativar (uma vez)
1. Garanta que este código esteja na **branch padrão** do repositório (agendamentos do GitHub
   Actions só rodam nela).
2. Em **Settings → Pages → Build and deployment → Source**, escolha **GitHub Actions**.
3. Em **Settings → Actions → General → Workflow permissions**, marque **Read and write permissions**.
4. Na aba **Actions**, abra “Buscar vagas de T.I. (a cada 1h)” e clique em **Run workflow** para a
   primeira coleta. O endereço do painel aparece no resumo da execução
   (`https://<usuario>.github.io/<repositorio>/`; o ambiente Ceará fica em `.../ceara.html`).

## Rodar localmente

```bash
pip install -r requirements.txt
python -m scraper                      # uma coleta
python -m scraper --loop               # coleta a cada 1h (servidor próprio, sem GitHub Actions)
python -m scraper --fontes gupy,vagas_com
python -m http.server -d docs 8000     # abra http://localhost:8000 e http://localhost:8000/ceara.html
python -m unittest discover -s tests -t . -v
```

## Personalizar
- **Adicionar empresas** (portais institucionais): inclua uma entrada em
  `config/portais_institucionais.json`, por exemplo
  `{"empresa": "Minha Empresa", "tipo": "greenhouse", "token": "minhaempresa", "uf": "CE"}`.
  A lista inicial traz empresas com sede no Nordeste e serve de ponto de partida — confira no
  painel quais portais responderam e ajuste/desative (`"ativo": false`) os que derem erro.
- **Termos de busca**: constante `TERMOS` em cada arquivo de `scraper/fontes/`.
- **Regras de T.I.**: `CATEGORIAS_TI` e `EXCLUSOES` em `scraper/comum.py`.

## Estrutura
```
scraper/            coletor (Python)
  __main__.py       orquestra fontes, filtra T.I./Nordeste, deduplica, mantém histórico
  comum.py          HTTP com retentativas, classificação de T.I., estados e cidades do NE
  extrator.py       leitura genérica de JSON/JSON-LD/__NEXT_DATA__
  fontes/           gupy.py, vagas_com.py, solides.py, institucional.py
config/             portais institucionais
docs/               painel (HTML/CSS/JS puro, sem dependências) + data/*.json
tests/              testes offline com fixtures
```

## Uso responsável
O coletor faz poucas requisições por hora, com intervalo entre elas, e só lê páginas e APIs
públicas usadas pelos próprios portais. As vagas pertencem aos anunciantes: a candidatura é
sempre feita no link original. Verifique os termos de uso de cada portal antes de ampliar a coleta.
