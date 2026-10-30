"""Robô de Reels de TESTE no Instagram (trial reels), pela API oficial da Meta, igual ao que o Metricool faz.

  python robo.py postar <conta>      -> posta o próximo vídeo da fila da conta como Reel de teste
  python robo.py fila <conta>        -> mostra o que falta
  python robo.py --test

Cada conta fica em contas/<conta>/: fila.tsv (arquivo<TAB>legenda), midia/<arquivos .mp4>, feitos.tsv (gerado).
Segredos (GitHub Actions ou ambiente): IG_USER_ID_<CONTA> e IG_TOKEN_<CONTA> (CONTA em maiúsculas).
O vídeo precisa de link público: o GitHub Pages deste repositório serve contas/<conta>/midia/.
Sempre trial_params MANUAL: o Reel só aparece para quem não segue; vai para os seguidores só se alguém promover no app.
"""
import json, os, sys, time, urllib.parse, urllib.request

API = "https://graph.facebook.com/v26.0"
AQUI = os.path.dirname(os.path.abspath(__file__))
SITE = os.environ.get("SITE_URL", "https://brindoapp.github.io/reels-teste")
TRIAL = {"graduation_strategy": "MANUAL"}  # contrato do Lê e Léo: nunca virar Reel normal sozinho


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


def fila(conta):
    linhas = [l.rstrip("\n").split("\t") for l in open(os.path.join(pasta(conta), "fila.tsv"), encoding="utf-8") if l.strip()]
    feitos_p = os.path.join(pasta(conta), "feitos.tsv")
    feitos = {l.split("\t")[0] for l in open(feitos_p, encoding="utf-8")} if os.path.exists(feitos_p) else set()
    return [(a, leg.replace("\\n", "\n")) for a, leg in linhas if a not in feitos]


def postar(conta):
    pend = fila(conta)
    if not pend:
        print(f"{conta}: fila vazia"); return
    arquivo, legenda = pend[0]
    chave = conta.upper()
    ig, token = os.environ.get(f"IG_USER_ID_{chave}"), os.environ.get(f"IG_TOKEN_{chave}")
    if not (ig and token):
        print(f"{conta}: sem IG_USER_ID_{chave}/IG_TOKEN_{chave}; nada postado"); return
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
    with open(os.path.join(pasta(conta), "feitos.tsv"), "a", encoding="utf-8") as f:
        f.write(f"{arquivo}\t{pub['id']}\t{time.strftime('%Y-%m-%d %H:%M')}\n")
    print(f"{conta}: {arquivo} publicado como Reel de TESTE (id {pub['id']}). Faltam {len(pend) - 1}.")


def test():
    import tempfile, shutil
    global AQUI
    d = tempfile.mkdtemp(); AQUI = d
    os.makedirs(os.path.join(d, "contas", "x"))
    open(os.path.join(d, "contas", "x", "fila.tsv"), "w").write("a.mp4\tlinha1\\nlinha2\nb.mp4\tok\n")
    open(os.path.join(d, "contas", "x", "feitos.tsv"), "w").write("a.mp4\t1\tontem\n")
    assert fila("x") == [("b.mp4", "ok")], fila("x")
    open(os.path.join(d, "contas", "x", "feitos.tsv"), "w").write("")
    assert fila("x")[0] == ("a.mp4", "linha1\nlinha2")
    assert TRIAL == {"graduation_strategy": "MANUAL"}
    shutil.rmtree(d); print("ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--test"]: test()
    elif len(sys.argv) == 3 and sys.argv[1] == "postar": postar(sys.argv[2])
    elif len(sys.argv) == 3 and sys.argv[1] == "fila":
        for a, l in fila(sys.argv[2]): print(a, "|", l.split("\n")[0])
    else: sys.exit(__doc__)
