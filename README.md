# 🎯 Vagas Hunter

Buscador pessoal de vagas **remotas no Brasil** que coleta diretamente das APIs públicas dos ATS usados nos sites de carreira das empresas (**Greenhouse, Lever, Ashby, Workable, InHire** e páginas próprias), **sem passar por LinkedIn nem Gupy**, e classifica tudo localmente usando seu currículo e **Ollama** (custo zero).

---

## 🚀 Como usar no dia a dia

### 1. Abrir o Painel Web (mais fácil)
Dê dois cliques em **`iniciar_painel.bat`** ou rode no terminal:
```powershell
.\.venv\Scripts\python.exe run.py painel
```
O navegador abrirá automaticamente em `http://localhost:8000`.  
No painel você pode:
- Filtrar vagas por **nota da IA**, **status** (`Nova`, `⭐ Interessa`, `✅ Candidatei`, `✕ Descartada`), **empresa** ou **palavra-chave** (ex.: `Java`, `Angular`, `PHP`, `Junior`).
- Clicar em **⚡ Avaliar +20 com IA** para pontuar mais vagas na fila.
- Clicar em **🔄 Coletar Novas Vagas** para buscar vagas recém-publicadas.
- Clicar em **Avaliar com IA** em qualquer vaga específica que ainda só tenha a porcentagem de embedding.

### 2. Comandos pelo Terminal
```powershell
# Coleta vagas novas em todas as empresas e avalia o Top N com a IA local
.\.venv\Scripts\python.exe run.py coletar

# Só coleta rápido (sem rodar o modelo de chat da IA)
.\.venv\Scripts\python.exe run.py coletar --sem-ia

# Avalia mais N vagas pendentes com a IA local
.\.venv\Scripts\python.exe run.py avaliar --limite 20

# Ver ou regerar o perfil extraído do seu currículo
.\.venv\Scripts\python.exe run.py perfil
.\.venv\Scripts\python.exe run.py perfil --refazer

# Adicionar uma nova empresa (URL da página de carreiras, nome ou ats:slug)
.\.venv\Scripts\python.exe run.py add-empresa https://carreiras.empresa.com.br --nome "Minha Empresa"
.\.venv\Scripts\python.exe run.py add-empresa inhire:nome-do-tenant --nome "Empresa X"
```

---

## ⚙️ Configuração (`config.yaml`)

No arquivo `config.yaml` você pode ajustar:
- **`curriculo`**: caminho do seu PDF ou DOCX (atualmente em `curriculo/curriculo.pdf`). Se trocar o arquivo, rode `.\.venv\Scripts\python.exe run.py perfil --refazer`.
- **`ollama.modelo_chat`**: `qwen2.5:7b` (padrão, roda 100% na sua RX 6700 XT) ou `qwen2.5:3b` (mais rápido).
- **`excluir_titulos`**: palavras no título que já descartam a vaga na hora (ex.: `senior`, `pleno`, `staff`, `manager`).
- **`matching.top_n_ia`**: quantas vagas a IA avalia por execução (padrão `25`).
- **`empresas`**: lista de URLs ou `ats:slug` extras para importar com `python run.py importar-empresas`.

---

## ⏰ Agendamento Diário (Windows Task Scheduler)

Para o PC buscar vagas sozinho uma vez por dia:
1. Abra o **Agendador de Tarefas** do Windows (`taskschd.msc`).
2. Clique em **Criar Tarefa Básica...**
3. Nome: `Vagas Hunter Diário` → Disparador: **Diariamente** (ex.: `09:00`).
4. Ação: **Iniciar um programa** → selecione o arquivo:
   ```
   C:\Users\alexa\vagas-hunter\coletar_vagas.bat
   ```
5. Conclua. Quando você abrir o painel (`iniciar_painel.bat`), as vagas novas já estarão coletadas e avaliadas!

