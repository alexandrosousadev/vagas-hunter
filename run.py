"""vagas-hunter: busca vagas remotas nos sites de carreira das empresas e ordena pelo seu currículo.

Uso:
  python run.py coletar [--empresa SLUG] [--sem-ia]   coleta vagas e avalia as melhores
  python run.py avaliar [--limite N]                   só roda o matching (etapas 1 e 2)
  python run.py painel [--porta 8000]                  abre o painel no navegador
  python run.py importar-empresas                      importa lista inicial + empresas do config.yaml
  python run.py add-empresa <url | nome | ats:slug>    adiciona uma empresa (detecta o ATS)
  python run.py perfil [--refazer]                     mostra o perfil extraído do currículo
"""
import argparse
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("coletar")
    c.add_argument("--empresa")
    c.add_argument("--sem-ia", action="store_true")
    a = sub.add_parser("avaliar")
    a.add_argument("--limite", type=int)
    w = sub.add_parser("painel")
    w.add_argument("--porta", type=int, default=8000)
    sub.add_parser("importar-empresas")
    e = sub.add_parser("add-empresa")
    e.add_argument("entrada")
    e.add_argument("--nome")
    pf = sub.add_parser("perfil")
    pf.add_argument("--refazer", action="store_true")
    args = p.parse_args()

    from app import companies, db, pipeline, resume

    if args.cmd == "coletar":
        pipeline.run(args.empresa, use_ai=not args.sem_ia)
    elif args.cmd == "avaliar":
        pipeline.evaluate(limit=args.limite)
    elif args.cmd == "painel":
        import threading
        import webbrowser

        import uvicorn
        url = f"http://localhost:{args.porta}"
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
        print(f"Painel em {url}  (Ctrl+C para sair)")
        uvicorn.run("app.web:app", host="127.0.0.1", port=args.porta, log_level="warning")
    elif args.cmd == "importar-empresas":
        n = companies.import_all(db.connect())
        print(f"{n} empresas cadastradas.")
    elif args.cmd == "add-empresa":
        cid, ats, slug = companies.add(db.connect(), args.entrada, args.nome)
        print(f"Empresa cadastrada: {ats}:{slug} (id {cid}). Rode `python run.py coletar --empresa {slug}`.")
    elif args.cmd == "perfil":
        prof = resume.get_profile(refresh=args.refazer)
        print(json.dumps({k: v for k, v in prof.items() if not k.startswith("_")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
