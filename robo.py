"""Robô de Reels de TESTE no Instagram (trial reels), pela API oficial da Meta, igual ao que o Metricool faz.

  python robo.py postar <conta>      -> posta o próximo vídeo da fila da conta como Reel de teste
  python robo.py fila <conta>        -> mostra o que falta
  python robo.py metricas <conta>    -> métricas dos Reels (24 h depois), ranking, ranking por tema (teste A/B) e seguidores
  python robo.py radar <conta>       -> posts que bombaram nos perfis de contas/<conta>/radar.txt
  python robo.py responder <conta>   -> responde comentários novos; palavra-chave de palavras.tsv manda mensagem no direct
  python robo.py painel <conta>      -> gera contas/<conta>/painel.html e manda o resumo no Telegram (se configurado)
  python robo.py --test

Cada conta fica em contas/<conta>/: fila.tsv (arquivo<TAB>legenda<TAB>tema opcional), midia/<arquivos .mp4>, feitos.tsv (gerado).
Segredos (GitHub Actions ou ambiente): IG_USER_ID_<CONTA> e IG_TOKEN_<CONTA> (CONTA em maiúsculas); opcionais TELEGRAM_TOKEN e TELEGRAM_CHAT.
O vídeo precisa de link público: o GitHub Pages deste repositório serve contas/<conta>/midia/.
Sempre trial_params MANUAL: o Reel só aparece para quem não segue; vai para os seguidores só se alguém promover no app.
"""
import html, json, os, random, statistics, sys, time, urllib.parse, urllib.request

API = "https://graph.facebook.com/v26.0"
AQUI = os.path.dirname(os.path.abspath(__file__))
SITE = os.environ.get("SITE_URL", "https://brindoapp.github.io/reels-teste")
TRIAL = {"graduation_strategy": "MANUAL"}  # contrato do Lê e Léo: nunca virar Reel normal sozinho
METRICAS = "views,reach,likes,comments,shares,saved,total_interactions,ig_reels_avg_watch_time"
MAX_RESPOSTAS = 15  # por rodada: responder demais de uma vez parece robô para o Instagram


def chamar(metodo, caminho, **params):
    dados = urllib.parse.urlencode(params).encode()
    if metodo == "GET":
        req = urllib.request.Request(f"{API}/{caminho}?{dados.decode()}")
    else:
        req = urllib.request.Request(f"{API}/{caminho}", data=dados, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Erro da API ({e.code}): {e.read().decode()[:500]}")


def pasta(conta):
    return os.path.join(AQUI, "contas", conta)


def ler_tsv(conta, nome):
    p = os.path.join(pasta(conta), nome)
    return [l.rstrip("\n").split("\t") for l in open(p, encoding="utf-8") if l.strip()] if os.path.exists(p) else []


def anotar(conta, nome, *colunas):
    with open(os.path.join(pasta(conta), nome), "a", encoding="utf-8") as f:
        f.write("\t".join(str(c) for c in colunas) + "\n")


def fila(conta):
    feitos = {l[0] for l in ler_tsv(conta, "feitos.tsv")}
    return [(l[0], l[1].replace("\\n", "\n")) for l in ler_tsv(conta, "fila.tsv") if l[0] not in feitos]


def temas(conta):
    return {l[0]: (l[2] if len(l) > 2 else "sem tema") for l in ler_tsv(conta, "fila.tsv")}


def acesso(conta):
    chave = conta.upper()
    token = os.environ.get(f"IG_TOKEN_{chave}")
    if not token:
        print(f"{conta}: sem IG_TOKEN_{chave}; nada feito"); return None, None
    return os.environ.get(f"IG_USER_ID_{chave}") or achar_ig(conta, token), token


def achar_ig(conta, token, pagina=False):
    """ID da conta do Instagram pelo @ salvo em contas/<conta>/usuario.txt (as páginas que o token enxerga).
    pagina=True devolve (id da página, token da página), que o direct usa."""
    usuario = open(os.path.join(pasta(conta), "usuario.txt"), encoding="utf-8").read().strip().lstrip("@")
    pags = chamar("GET", "me/accounts", fields="name,access_token,instagram_business_account{id,username}", limit=100, access_token=token)
    for p in pags.get("data", []):
        ig = p.get("instagram_business_account") or {}
        if ig.get("username", "").lower() == usuario.lower():
            return (p["id"], p["access_token"]) if pagina else ig["id"]
    raise SystemExit(f"{conta}: o token não enxerga o Instagram @{usuario} (páginas: {[p.get('name') for p in pags.get('data', [])]})")


def postar(conta):
    pend = fila(conta)
    if not pend:
        print(f"{conta}: fila vazia"); return
    arquivo, legenda = pend[0]
    ig, token = acesso(conta)
    if not token: return
    url = f"{SITE}/contas/{conta}/midia/{urllib.parse.quote(arquivo)}"
    c = chamar("POST", f"{ig}/media", media_type="REELS", video_url=url, caption=legenda,
               trial_params=json.dumps(TRIAL), access_token=token)
    cid = c["id"]
    for _ in range(60):  # o Instagram processa o vídeo antes de deixar publicar
        st = chamar("GET", cid, fields="status_code,status", access_token=token)
        if st.get("status_code") == "FINISHED": break
        if st.get("status_code") in ("ERROR", "EXPIRED"): raise SystemExit(f"{arquivo}: {st}")
        time.sleep(10)
    else:
        raise SystemExit(f"{arquivo}: o Instagram não terminou de processar em 10 min")
    pub = chamar("POST", f"{ig}/media_publish", creation_id=cid, access_token=token)
    anotar(conta, "feitos.tsv", arquivo, pub["id"], time.strftime("%Y-%m-%d %H:%M"))
    print(f"{conta}: {arquivo} publicado como Reel de TESTE (id {pub['id']}). Faltam {len(pend) - 1}.")


def pontos(m):
    """Nota do Reel: visualização conta, mas compartilhar e salvar é o que faz o Instagram empurrar para mais gente."""
    return m.get("views", 0) + 10 * m.get("shares", 0) + 5 * m.get("saved", 0) + 3 * m.get("comments", 0) + m.get("likes", 0)


def ranking(linhas, tema_de):
    """linhas: [(arquivo, métricas)] -> (top por pontos, média de pontos por tema, do melhor para o pior)."""
    top = sorted(linhas, key=lambda x: -pontos(x[1]))
    por_tema = {}
    for arq, m in linhas:
        por_tema.setdefault(tema_de.get(arq, "sem tema"), []).append(pontos(m))
    return top, sorted(((t, round(statistics.mean(v)), len(v)) for t, v in por_tema.items()), key=lambda x: -x[1])


def metricas(conta):
    ig, token = acesso(conta)
    if not token: return
    agora, linhas = time.time(), []
    for l in ler_tsv(conta, "feitos.tsv"):
        if len(l) < 3 or not l[1].isdigit(): continue  # o 1º foi postado à mão pelo iPhone, sem id
        if agora - time.mktime(time.strptime(l[2], "%Y-%m-%d %H:%M")) < 24 * 3600: continue
        try:
            r = chamar("GET", f"{l[1]}/insights", metric=METRICAS, access_token=token)
        except SystemExit as e:
            print(f"{l[0]}: sem métricas ({e})"); continue
        linhas.append((l[0], {d["name"]: d["values"][0]["value"] for d in r.get("data", [])}))
    with open(os.path.join(pasta(conta), "metricas.json"), "w", encoding="utf-8") as f:
        json.dump({"quando": time.strftime("%Y-%m-%d %H:%M"), "reels": dict(linhas)}, f, ensure_ascii=False, indent=1)
    seg = chamar("GET", ig, fields="followers_count,media_count", access_token=token)
    anotar(conta, "seguidores.tsv", time.strftime("%Y-%m-%d"), seg.get("followers_count", ""))
    top, por_tema = ranking(linhas, temas(conta))
    with open(os.path.join(pasta(conta), "vencedores.tsv"), "w", encoding="utf-8") as f:  # a skill de memes lê isto
        for arq, m in top[:5]:
            f.write(f"{arq}\t{temas(conta).get(arq, 'sem tema')}\t{pontos(m)}\n")
    print(f"{conta}: {len(linhas)} Reels medidos; seguidores {seg.get('followers_count')}")
    for t, media, n in por_tema: print(f"  tema {t}: média {media} pontos ({n} reels)")


def radar(conta):
    """Posts dos perfis do radar com 3x mais curtidas que o normal do perfil: sinal de viral de verdade."""
    ig, token = acesso(conta)
    if not token: return
    achados = []
    for u in [l[0] for l in ler_tsv(conta, "radar.txt")]:
        campos = f"business_discovery.username({u}){{followers_count,media.limit(30){{caption,like_count,comments_count,permalink,timestamp,media_product_type}}}}"
        try:
            posts = chamar("GET", ig, fields=campos, access_token=token)["business_discovery"]["media"]["data"]
        except (SystemExit, KeyError) as e:
            print(f"radar: @{u} não deu ({e})"); continue
        achados += outliers(u, posts)
    achados.sort(key=lambda x: -x[2])
    with open(os.path.join(pasta(conta), "radar.tsv"), "w", encoding="utf-8") as f:
        for u, link, vezes, curt, leg in achados[:20]:
            f.write(f"@{u}\t{link}\t{vezes}x\t{curt}\t{leg}\n")
    print(f"radar: {len(achados)} posts acima do normal")


def outliers(u, posts):
    curt = [p.get("like_count", 0) for p in posts]
    if len(curt) < 5: return []
    normal = max(statistics.median(curt), 1)
    return [(u, p["permalink"], round(p.get("like_count", 0) / normal, 1), p.get("like_count", 0),
             (p.get("caption") or "").split("\n")[0][:120].replace("\t", " "))
            for p in posts if p.get("like_count", 0) >= 3 * normal]


def resposta_para(texto, palavras, respostas):
    """(mensagem do direct ou None, resposta pública)."""
    t = texto.upper()
    for palavra, msg in palavras:
        if palavra.upper() in t:
            return msg.replace("\\n", "\n"), "Te mandei no direct 🤠"
    return None, random.choice(respostas)


def responder(conta):
    ig, token = acesso(conta)
    if not token: return
    usuario = open(os.path.join(pasta(conta), "usuario.txt"), encoding="utf-8").read().strip().lstrip("@").lower()
    feitos = {l[0] for l in ler_tsv(conta, "respondidos.tsv")}
    palavras = [tuple(l[:2]) for l in ler_tsv(conta, "palavras.tsv")]
    respostas = [l[0] for l in ler_tsv(conta, "respostas.txt")]
    pagina = None
    n = 0
    for l in ler_tsv(conta, "feitos.tsv")[-30:]:
        if len(l) < 2 or not l[1].isdigit(): continue
        try:
            coms = chamar("GET", f"{l[1]}/comments", fields="id,text,username", limit=50, access_token=token).get("data", [])
        except SystemExit as e:
            print(f"{l[0]}: sem comentários ({e})"); continue
        for c in coms:
            if n >= MAX_RESPOSTAS: break
            if c["id"] in feitos or c.get("username", "").lower() == usuario or len(c.get("text", "")) < 2: continue
            direct, publica = resposta_para(c["text"], palavras, respostas)
            if direct:
                try:
                    pagina = pagina or achar_ig(conta, token, pagina=True)
                    req = urllib.request.Request(f"{API}/{pagina[0]}/messages?access_token={pagina[1]}", method="POST",
                                                 data=json.dumps({"recipient": {"comment_id": c["id"]}, "message": {"text": direct}}).encode(),
                                                 headers={"Content-Type": "application/json"})
                    urllib.request.urlopen(req, timeout=60).read()
                except Exception as e:  # sem permissão de mensagens ainda: responde só em público
                    print(f"direct falhou ({e})"); publica = random.choice(respostas)
            chamar("POST", f"{c['id']}/replies", message=publica, access_token=token)
            anotar(conta, "respondidos.tsv", c["id"], time.strftime("%Y-%m-%d %H:%M"), "direct" if direct else "")
            feitos.add(c["id"]); n += 1
            time.sleep(random.uniform(20, 60))  # espaçado, como gente
    print(f"{conta}: {n} comentários respondidos")


def painel(conta):
    p = pasta(conta)
    m = json.load(open(os.path.join(p, "metricas.json"), encoding="utf-8")) if os.path.exists(os.path.join(p, "metricas.json")) else {"quando": "-", "reels": {}}
    top, por_tema = ranking(list(m["reels"].items()), temas(conta))
    seg = ler_tsv(conta, "seguidores.tsv")
    ganho = int(seg[-1][1]) - int(seg[-2][1]) if len(seg) > 1 and seg[-1][1] and seg[-2][1] else 0
    hoje = time.strftime("%Y-%m-%d")
    respondidos = sum(1 for l in ler_tsv(conta, "respondidos.tsv") if l[1].startswith(hoje))
    e = html.escape
    tab = lambda cab, linhas: "<table><tr>" + "".join(f"<th>{e(c)}</th>" for c in cab) + "</tr>" + "".join(
        "<tr>" + "".join(f"<td>{e(str(c))}</td>" for c in l) + "</tr>" for l in linhas) + "</table>"
    corpo = (f"<h1>@{e(conta)}</h1><p>Atualizado {e(m['quando'])} · Seguidores: <b>{e(seg[-1][1] if seg else '-')}</b> ({ganho:+d} desde ontem) · "
             f"Na fila: {len(fila(conta))} · Comentários respondidos hoje: {respondidos}</p>"
             "<h2>Top Reels de teste (promova os 3 primeiros no app)</h2>"
             + tab(["Reel", "Views", "Compart.", "Salvos", "Coment.", "Pontos"],
                   [(a, x.get("views", 0), x.get("shares", 0), x.get("saved", 0), x.get("comments", 0), pontos(x)) for a, x in top[:10]])
             + "<h2>Teste A/B por tema</h2>" + tab(["Tema", "Média de pontos", "Reels"], por_tema)
             + "<h2>Radar: viralizando no nicho</h2>" + tab(["Perfil", "Link", "Acima do normal", "Curtidas", "Legenda"], ler_tsv(conta, "radar.tsv")[:10]))
    with open(os.path.join(p, "painel.html"), "w", encoding="utf-8") as f:
        f.write(f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>Painel {e(conta)}</title><style>
body{{font:15px system-ui;margin:16px;background:#fff;color:#111}}table{{border-collapse:collapse;width:100%;margin-bottom:20px;font-size:13px}}
td,th{{border-bottom:1px solid #ddd;padding:6px;text-align:left;word-break:break-word}}h2{{font-size:17px;margin-top:24px}}
@media (prefers-color-scheme:dark){{body{{background:#111;color:#eee}}td,th{{border-color:#333}}}}</style></head><body>{corpo}</body></html>""")
    resumo = (f"📊 @{conta}: {seg[-1][1] if seg else '-'} seguidores ({ganho:+d})\nTop para promover:\n"
              + "\n".join(f"{i + 1}. {a} — {x.get('views', 0)} views, {x.get('shares', 0)} compart." for i, (a, x) in enumerate(top[:3]))
              + (f"\nTema que mais pega: {por_tema[0][0]}" if por_tema else "") + f"\nPainel: {SITE}/contas/{conta}/painel.html")
    print(resumo)
    tg, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT")
    if tg and chat:
        urllib.request.urlopen(f"https://api.telegram.org/bot{tg}/sendMessage", data=urllib.parse.urlencode({"chat_id": chat, "text": resumo}).encode(), timeout=60)


def test():
    import tempfile, shutil
    global AQUI
    d = tempfile.mkdtemp(); AQUI = d
    os.makedirs(os.path.join(d, "contas", "x"))
    open(os.path.join(d, "contas", "x", "fila.tsv"), "w").write("a.mp4\tlinha1\\nlinha2\tex\nb.mp4\tok\n")
    open(os.path.join(d, "contas", "x", "feitos.tsv"), "w").write("a.mp4\t1\tontem\n")
    assert fila("x") == [("b.mp4", "ok")], fila("x")
    open(os.path.join(d, "contas", "x", "feitos.tsv"), "w").write("")
    assert fila("x")[0] == ("a.mp4", "linha1\nlinha2")
    assert temas("x") == {"a.mp4": "ex", "b.mp4": "sem tema"}
    assert TRIAL == {"graduation_strategy": "MANUAL"}
    top, por_tema = ranking([("a.mp4", {"views": 100}), ("b.mp4", {"views": 50, "shares": 10})], temas("x"))
    assert top[0][0] == "b.mp4" and por_tema[0] == ("sem tema", 150, 1), (top, por_tema)
    assert [o[1] for o in outliers("u", [{"like_count": 10, "permalink": "p"}] * 5 + [{"like_count": 90, "permalink": "viral"}])] == ["viral"]
    assert resposta_para("quero o modão!", [("MODÃO", "toma")], ["oi"]) == ("toma", "Te mandei no direct 🤠")
    assert resposta_para("kkk", [("MODÃO", "toma")], ["oi"]) == (None, "oi")
    painel("x"); assert os.path.exists(os.path.join(d, "contas", "x", "painel.html"))
    shutil.rmtree(d); print("ok")


if __name__ == "__main__":
    comandos = {"postar": postar, "metricas": metricas, "radar": radar, "responder": responder, "painel": painel}
    if sys.argv[1:] == ["--test"]: test()
    elif len(sys.argv) == 3 and sys.argv[1] in comandos: comandos[sys.argv[1]](sys.argv[2])
    elif len(sys.argv) == 3 and sys.argv[1] == "fila":
        for a, l in fila(sys.argv[2]): print(a, "|", l.split("\n")[0])
    else: sys.exit(__doc__)
