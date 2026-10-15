/* Radar de Vagas NE — painel estático que lê data/vagas.json e data/historico.json. */
(() => {
  "use strict";

  const ESCOPO = document.body.dataset.escopo; // "NE" ou "CE"
  const ESTADOS = {
    MA: "Maranhão", PI: "Piauí", CE: "Ceará", RN: "Rio Grande do Norte", PB: "Paraíba",
    PE: "Pernambuco", AL: "Alagoas", SE: "Sergipe", BA: "Bahia",
  };
  // Mosaico aproximado da geografia do Nordeste (linha / coluna)
  const MOSAICO = {
    MA: "1 / 1", PI: "1 / 2", CE: "1 / 3", RN: "1 / 4", PB: "2 / 4", PE: "2 / 3 / 3 / 4",
    AL: "3 / 4", SE: "4 / 4", BA: "3 / 2 / 5 / 4",
  };
  const POR_PAGINA = 40;
  const RECARREGAR_MS = 5 * 60 * 1000;
  const DIA_MS = 864e5;

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const semAcento = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const fmt = (n) => Number(n).toLocaleString("pt-BR");

  // ---------- armazenamento local (tolerante a falhas) ----------
  const local = {
    ler(chave, padrao) { try { const v = localStorage.getItem(chave); return v ? JSON.parse(v) : padrao; } catch { return padrao; } },
    gravar(chave, valor) { try { localStorage.setItem(chave, JSON.stringify(valor)); } catch { /* sem armazenamento */ } },
  };

  // ---------- tema ----------
  const temaSalvo = local.ler("tema", null);
  if (temaSalvo) document.documentElement.dataset.theme = temaSalvo;
  $("tema").addEventListener("click", () => {
    const escuroAgora = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    const novo = escuroAgora ? "light" : "dark";
    document.documentElement.dataset.theme = novo;
    local.gravar("tema", novo);
  });

  // ---------- estado ----------
  let dados = { vagas: [], fontes: [] };
  let historico = [];
  let base = []; // vagas do escopo (NE inteiro ou só CE)
  let limite = POR_PAGINA;
  const favoritas = new Set(local.ler("favoritas", []));
  const filtros = { busca: "", local: "", categoria: "", nivel: "", modalidade: "", fonte: "", novas: false, favoritas: false, remoto: false };

  const ehNova = (v) => Date.now() - new Date(v.primeira_vez).getTime() < DIA_MS;
  const localDe = (v) => (ESCOPO === "CE" ? (v.cidade || "Não informada") : v.uf);

  // ---------- carga ----------
  async function carregar() {
    try {
      const [rv, rh] = await Promise.all([
        fetch(`data/vagas.json?t=${Date.now()}`, { cache: "no-store" }),
        fetch(`data/historico.json?t=${Date.now()}`, { cache: "no-store" }),
      ]);
      dados = rv.ok ? await rv.json() : dados;
      historico = rh.ok ? await rh.json() : [];
    } catch (e) {
      console.warn("Falha ao carregar dados", e);
    }
    base = (dados.vagas || []).filter((v) => (ESCOPO === "CE" ? v.uf === "CE" : ESTADOS[v.uf]));
    montarSelects();
    renderTudo();
  }

  // ---------- filtros ----------
  function contar(lista, chave) {
    const m = new Map();
    for (const v of lista) {
      const k = typeof chave === "function" ? chave(v) : v[chave];
      if (k) m.set(k, (m.get(k) || 0) + 1);
    }
    // "Não informado(a)" vai sempre para o fim
    const peso = (k) => (/^Não informad/.test(k) ? 1 : 0);
    return [...m.entries()].sort((a, b) => peso(a[0]) - peso(b[0]) || b[1] - a[1] || String(a[0]).localeCompare(String(b[0]), "pt-BR"));
  }

  function preencher(sel, rotuloTodos, pares, rotular = (k) => k) {
    const atual = sel.value;
    sel.innerHTML = `<option value="">${esc(rotuloTodos)}</option>` +
      pares.map(([k, n]) => `<option value="${esc(k)}">${esc(rotular(k))} (${fmt(n)})</option>`).join("");
    sel.value = pares.some(([k]) => k === atual) ? atual : "";
  }

  function montarSelects() {
    preencher($("f-local"), ESCOPO === "CE" ? "Todas as cidades" : "Todos os estados", contar(base, localDe),
      (k) => (ESCOPO === "CE" ? k : ESTADOS[k]));
    preencher($("f-categoria"), "Todas as áreas", contar(base, "categoria"));
    preencher($("f-nivel"), "Todos os níveis", contar(base, "nivel"));
    preencher($("f-modalidade"), "Todas as modalidades", contar(base, "modalidade"));
    preencher($("f-fonte"), "Todas as fontes", contar(base, "fonte"));
    for (const k of ["local", "categoria", "nivel", "modalidade", "fonte"]) $(`f-${k}`).value = filtros[k];
  }

  function aplicar(lista, ignorar = "") {
    const termos = semAcento(filtros.busca).split(/\s+/).filter(Boolean);
    return lista.filter((v) => {
      if (ignorar !== "local" && filtros.local && localDe(v) !== filtros.local) return false;
      if (ignorar !== "categoria" && filtros.categoria && v.categoria !== filtros.categoria) return false;
      if (ignorar !== "nivel" && filtros.nivel && v.nivel !== filtros.nivel) return false;
      if (ignorar !== "modalidade" && filtros.modalidade && v.modalidade !== filtros.modalidade) return false;
      if (filtros.fonte && v.fonte !== filtros.fonte) return false;
      if (filtros.novas && !ehNova(v)) return false;
      if (filtros.favoritas && !favoritas.has(v.id)) return false;
      if (filtros.remoto && !["Remoto", "Híbrido"].includes(v.modalidade)) return false;
      if (termos.length) {
        const alvo = semAcento(`${v.titulo} ${v.empresa} ${v.cidade || ""} ${v.categoria}`);
        if (!termos.every((t) => alvo.includes(t))) return false;
      }
      return true;
    });
  }

  function definir(chave, valor) {
    filtros[chave] = valor;
    limite = POR_PAGINA;
    const el = $(`f-${chave}`);
    if (el && el.tagName === "SELECT") el.value = valor;
    renderTudo();
  }

  // ---------- render ----------
  function renderTudo() {
    renderAtualizacao();
    renderKpis();
    renderGraficos();
    renderLista();
    renderFontes();
  }

  function tempoRelativo(iso) {
    if (!iso) return "—";
    const min = Math.round((Date.now() - new Date(iso).getTime()) / 6e4);
    if (min < 1) return "agora";
    if (min < 60) return `há ${min} min`;
    const h = Math.round(min / 60);
    if (h < 48) return `há ${h} h`;
    return `há ${Math.round(h / 24)} dias`;
  }

  function renderAtualizacao() {
    const el = $("atualizacao");
    if (!dados.atualizado_em) {
      el.innerHTML = `<span class="pulso parado"></span><span>aguardando a primeira coleta</span>`;
      return;
    }
    const atrasada = Date.now() - new Date(dados.atualizado_em).getTime() > 2 * 3600e3;
    const prox = dados.proxima_coleta ? new Date(dados.proxima_coleta) : null;
    const proxTxt = prox && prox > new Date()
      ? ` · próxima ~${prox.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}` : "";
    el.innerHTML = `<span class="pulso${atrasada ? " parado" : ""}"></span>
      <span>Atualizado ${tempoRelativo(dados.atualizado_em)}<span class="texto-longo">${proxTxt}</span></span>`;
    el.title = new Date(dados.atualizado_em).toLocaleString("pt-BR");
  }

  function renderKpis() {
    const lista = aplicar(base);
    const novas = lista.filter(ehNova).length;
    const empresas = new Set(lista.map((v) => v.empresa)).size;
    const flex = lista.filter((v) => ["Remoto", "Híbrido"].includes(v.modalidade)).length;
    const cidades = new Set(lista.map((v) => v.cidade).filter(Boolean)).size;
    const itens = [
      ["Vagas de T.I.", fmt(lista.length), ESCOPO === "CE" ? `em ${fmt(cidades)} cidades` : `em ${new Set(lista.map((v) => v.uf)).size} estados`],
      ["Novas nas últimas 24h", fmt(novas), lista.length ? `${Math.round((novas / lista.length) * 100)}% do total` : "—"],
      ["Empresas contratando", fmt(empresas), "anunciantes distintos"],
      ["Remoto ou híbrido", fmt(flex), lista.length ? `${Math.round((flex / lista.length) * 100)}% das vagas` : "—"],
    ];
    $("kpis").innerHTML = itens.map(([r, v, s]) =>
      `<div class="kpi"><div class="rotulo">${esc(r)}</div><div class="valor">${v}</div><div class="sub">${esc(s)}</div></div>`).join("");
  }

  function barras(alvo, pares, { chave, max = 8, rotular = (k) => k } = {}) {
    const el = $(alvo);
    if (!el) return;
    const top = pares.slice(0, max);
    const maior = top.length ? top[0][1] : 1;
    if (!top.length) { el.innerHTML = `<div class="sub" style="color:var(--muted);font-size:13px">Sem dados</div>`; return; }
    el.innerHTML = top.map(([k, n]) => {
      const ativo = chave && filtros[chave] === k;
      const tag = chave ? "button" : "div";
      return `<${tag} class="barra" ${chave ? `type="button" data-chave="${chave}" data-valor="${esc(k)}" aria-pressed="${ativo}"` : ""} title="${esc(rotular(k))}: ${fmt(n)}">
        <span class="nome">${esc(rotular(k))}</span><span class="trilho"><span style="width:${(n / maior) * 100}%"></span></span><span class="qtd">${fmt(n)}</span></${tag}>`;
    }).join("");
  }

  function renderMapa() {
    const el = $("mapa");
    if (!el) return;
    const porUf = Object.fromEntries(contar(aplicar(base, "local"), "uf"));
    const maior = Math.max(1, ...Object.values(porUf));
    el.innerHTML = Object.keys(ESTADOS).map((uf) => {
      const n = porUf[uf] || 0;
      const nivel = n === 0 ? 0 : Math.min(4, 1 + Math.floor((n / maior) * 3.999));
      return `<button type="button" class="uf${nivel >= 3 ? " escuro" : ""}" style="grid-area:${MOSAICO[uf]};background:var(--heat-${nivel})"
        data-chave="local" data-valor="${uf}" aria-pressed="${filtros.local === uf}" title="${ESTADOS[uf]}: ${fmt(n)} vagas">
        <span class="sigla">${uf}</span><span class="n">${fmt(n)}</span></button>`;
    }).join("");
    $("legenda-mapa").innerHTML = `menos ${[0, 1, 2, 3, 4].map((i) => `<i style="background:var(--heat-${i})"></i>`).join("")} mais`;
  }

  function renderTendencia() {
    const el = $("g-tendencia");
    if (!el) return;
    // No Nordeste, se um estado estiver selecionado, mostra a série só dele
    const uf = ESCOPO === "CE" ? "CE" : (filtros.local || null);
    const serie = historico.slice(-30).map((h) => ({ dia: h.dia, n: uf ? (h.por_uf?.[uf] || 0) : h.total }));
    if (serie.length < 2) {
      el.innerHTML = `<p style="color:var(--muted);font-size:13px;margin:8px 0 0">O gráfico aparece após coletas em pelo menos 2 dias diferentes.${serie.length ? ` Hoje: <b>${fmt(serie[0].n)}</b> vagas.` : ""}</p>`;
      return;
    }
    const W = 600, H = 140, P = { t: 12, r: 8, b: 22, l: 34 };
    const maxN = Math.max(...serie.map((s) => s.n), 1);
    const x = (i) => P.l + (i / (serie.length - 1)) * (W - P.l - P.r);
    const y = (n) => P.t + (1 - n / maxN) * (H - P.t - P.b);
    const pts = serie.map((s, i) => `${x(i).toFixed(1)},${y(s.n).toFixed(1)}`);
    const rot = (d) => d.slice(8, 10) + "/" + d.slice(5, 7);
    const meio = Math.floor((serie.length - 1) / 2);
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Vagas ativas por dia">
      <line class="eixo" x1="${P.l}" x2="${W - P.r}" y1="${H - P.b}" y2="${H - P.b}"/>
      <text x="${P.l - 6}" y="${y(maxN) + 4}" text-anchor="end">${fmt(maxN)}</text>
      <text x="${P.l - 6}" y="${H - P.b}" text-anchor="end">0</text>
      <polygon class="area" points="${P.l},${H - P.b} ${pts.join(" ")} ${x(serie.length - 1)},${H - P.b}"/>
      <polyline class="linha" points="${pts.join(" ")}" vector-effect="non-scaling-stroke"/>
      ${serie.map((s, i) => `<circle class="ponto" cx="${x(i)}" cy="${y(s.n)}" r="2.5"><title>${rot(s.dia)}: ${fmt(s.n)} vagas</title></circle>`).join("")}
      <text x="${x(0)}" y="${H - 6}" text-anchor="start">${rot(serie[0].dia)}</text>
      <text x="${x(meio)}" y="${H - 6}" text-anchor="middle">${rot(serie[meio].dia)}</text>
      <text x="${x(serie.length - 1)}" y="${H - 6}" text-anchor="end">${rot(serie[serie.length - 1].dia)}</text>
    </svg>`;
    $("tendencia-sub").textContent = `${uf && ESCOPO !== "CE" ? `${ESTADOS[uf]} · ` : ""}últimos ${serie.length} dias`;
  }

  function renderGraficos() {
    renderMapa();
    barras("g-cidade", contar(aplicar(base, "local"), localDe), { chave: "local", max: 10 });
    barras("g-categoria", contar(aplicar(base, "categoria"), "categoria"), { chave: "categoria", max: 11 });
    barras("g-nivel", contar(aplicar(base, "nivel"), "nivel"), { chave: "nivel", max: 7 });
    barras("g-modalidade", contar(aplicar(base, "modalidade"), "modalidade"), { chave: "modalidade", max: 4 });
    barras("g-empresa", contar(aplicar(base), "empresa"), { max: 8 });
    renderTendencia();
  }

  function dataCurta(iso) {
    if (!iso) return null;
    const [a, m, d] = iso.slice(0, 10).split("-");
    return `${d}/${m}/${a}`;
  }

  function cartao(v) {
    const fav = favoritas.has(v.id);
    const lugar = [v.cidade, v.uf].filter(Boolean).join(" · ");
    const tambem = (v.extras?.tambem_em || []).map((o) => `<a href="${esc(o.url)}" target="_blank" rel="noopener">${esc(o.fonte)}</a>`).join(", ");
    return `<article class="vaga${v.ativa === false ? " inativa" : ""}">
      <div class="linha1">
        <h3><a href="${esc(v.url)}" target="_blank" rel="noopener">${esc(v.titulo)}</a></h3>
        <button class="estrela" type="button" data-fav="${esc(v.id)}" aria-pressed="${fav}" title="${fav ? "Remover das salvas" : "Salvar vaga"}">${fav ? "★" : "☆"}</button>
      </div>
      <div class="empresa">${esc(v.empresa)}${lugar ? ` — ${esc(lugar)}` : ""}</div>
      <div class="selos">
        ${ehNova(v) ? `<span class="selo nova">NOVA</span>` : ""}
        <span class="selo cat">${esc(v.categoria)}</span>
        ${v.nivel && v.nivel !== "Não informado" ? `<span class="selo">${esc(v.nivel)}</span>` : ""}
        ${v.modalidade && v.modalidade !== "Não informado" ? `<span class="selo">${esc(v.modalidade)}</span>` : ""}
      </div>
      <div class="rodape">
        <span>${esc(v.fonte)}${tambem ? ` · também em ${tambem}` : ""}${v.ativa === false ? " · não encontrada na última coleta" : ""}</span>
        <span>${v.publicada_em ? `publicada ${dataCurta(v.publicada_em)}` : `vista ${tempoRelativo(v.primeira_vez)}`}</span>
      </div>
    </article>`;
  }

  function renderLista() {
    const lista = aplicar(base);
    $("contagem").textContent = `${fmt(lista.length)} de ${fmt(base.length)} vagas`;
    const el = $("vagas");
    if (!lista.length) {
      el.innerHTML = `<div class="vazio">${base.length
        ? "Nenhuma vaga com esses filtros. Tente limpar alguns deles."
        : dados.atualizado_em
          ? "Nenhuma vaga de T.I. encontrada na última coleta."
          : "Ainda não há dados. A primeira coleta roda automaticamente no GitHub Actions (ou execute <code>python -m scraper</code>)."}</div>`;
      $("mais").hidden = true;
      return;
    }
    el.innerHTML = lista.slice(0, limite).map(cartao).join("");
    $("mais").hidden = lista.length <= limite;
    $("mais").textContent = `Mostrar mais vagas (${fmt(lista.length - limite)} restantes)`;
  }

  function renderFontes() {
    const fontes = dados.fontes || [];
    $("fontes").innerHTML = fontes.length ? fontes.map((f) => `<span class="fonte${f.ok ? "" : " erro"}" title="${esc(f.erro || "")}">
        <span class="bola"></span>${esc(f.fonte)} <small>${f.ok ? `${fmt(f.ti_nordeste)} vagas de T.I.` : "indisponível nesta coleta"}</small></span>`).join("")
      : `<span class="fonte"><small>Nenhuma coleta registrada ainda.</small></span>`;
    const ok = fontes.filter((f) => f.ok).length;
    $("fontes-resumo").textContent = fontes.length ? `${ok} de ${fontes.length} respondendo` : "";
    const inst = fontes.find((f) => f.portais);
    $("portais").innerHTML = inst ? `<details class="portais"><summary>Portais institucionais (${inst.portais.filter((p) => p.ok).length}/${inst.portais.length} ok)</summary><ul>
      ${inst.portais.map((p) => `<li>${esc(p.empresa)}: ${p.ok ? `${fmt(p.total)} vagas lidas` : `erro — ${esc(p.erro)}`}</li>`).join("")}</ul></details>` : "";
  }

  // ---------- eventos ----------
  let atraso;
  $("f-busca").addEventListener("input", (e) => {
    clearTimeout(atraso);
    atraso = setTimeout(() => definir("busca", e.target.value), 150);
  });
  for (const k of ["local", "categoria", "nivel", "modalidade", "fonte"]) {
    $(`f-${k}`).addEventListener("change", (e) => definir(k, e.target.value));
  }
  for (const k of ["novas", "favoritas", "remoto"]) {
    $(`f-${k}`).addEventListener("click", (e) => {
      const novo = !filtros[k];
      e.currentTarget.setAttribute("aria-pressed", String(novo));
      definir(k, novo);
    });
  }
  $("limpar").addEventListener("click", () => {
    Object.assign(filtros, { busca: "", local: "", categoria: "", nivel: "", modalidade: "", fonte: "", novas: false, favoritas: false, remoto: false });
    $("f-busca").value = "";
    document.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", "false"));
    montarSelects();
    limite = POR_PAGINA;
    renderTudo();
  });
  $("mais").addEventListener("click", () => { limite += POR_PAGINA; renderLista(); });

  document.addEventListener("click", (e) => {
    const alvo = e.target.closest("[data-chave]");
    if (alvo) {
      const { chave, valor } = alvo.dataset;
      definir(chave, filtros[chave] === valor ? "" : valor);
      return;
    }
    const fav = e.target.closest("[data-fav]");
    if (fav) {
      const id = fav.dataset.fav;
      favoritas.has(id) ? favoritas.delete(id) : favoritas.add(id);
      local.gravar("favoritas", [...favoritas]);
      if (filtros.favoritas) renderTudo(); else renderLista();
    }
  });

  carregar();
  setInterval(carregar, RECARREGAR_MS);
  setInterval(renderAtualizacao, 60 * 1000);
})();
