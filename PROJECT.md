# API Extrato - Documentação do Projeto

> **Versão:** 3.2.0  
> **Última atualização:** 2026-08-30  
> **Status:** Produção (Vercel)

---

## 📋 Visão Geral

API em **FastAPI** para extrair transações de extratos bancários em PDF (Mercado Pago) e retornar JSON estruturado. Inclui frontend simples (`index.html`) servido pela própria API.

**Deploy automático:** Push na branch `main` → Vercel build → `https://api-extrato-v3.vercel.app`

---

## 🚀 Endpoints

| Método | Rota | Descrição |
|--------|------|-----------|
| `GET` | `/` | Serve `index.html` (frontend) |
| `GET` | `/docs` | Swagger UI |
| `POST` | `/processar-pdf` | Upload PDF → retorna transações |

### `POST /processar-pdf`

**Request:** `multipart/form-data` com campo `file` (PDF)

**Response 200:**
```json
{
  "total_transacoes": 73,
  "transacoes": [
    {
      "Data": "04-08-2026",
      "Descrição": "Pagamento Cartão de crédito",
      "ID da operação": "171224966085",
      "Valor": "R$ -287,89"
    }
  ],
  "aviso": "Opcional: aviso se PDF for imagem/escaneado"
}
```

**Erros:** 400 (não é PDF), 500 (erro interno)

---

## 🗂 Estrutura do Projeto

```
api-extrato/
├── api/
│   └── index.py          # FastAPI app + parser completo
├── index.html            # Frontend (tabela + filtros + resumo)
├── vercel.json           # Config deploy Vercel (Python)
├── requirements.txt      # Dependências Python
├── tests/
│   └── test_parser.py    # 8 testes unitários (pytest/unittest)
└── PROJECT.md            # Este arquivo
```

---

## ⚙️ Parser (`api/index.py`)

### Fluxo de Extração

1. **Extrai texto** de cada página em dois modos:
   - `plain` (texto corrido)
   - `layout` (preserva colunas/posição)

2. **Tenta ambos** e escolhe o que gera mais transações válidas (`_pontuar_resultado`)

3. **Ignora automaticamente:**
    - Cabeçalhos, rodapés, números de página
    - "Saldo inicial", "Saldo final", "Entradas:", "Saídas:"
    - **Caixinha:** `Dinheiro retirado *`, `Dinheiro reservado *`, `Reserva por gastos *`

4. **Junta descrições quebradas** entre linhas/páginas
5. **Reorganiza descrições** que vêm após valores (OCR bagunçado)
6. **Remove duplicatas** por ID da operação
7. **Normaliza:** datas (`DD-MM-YYYY`), valores (`R$ -1.234,56`)
8. **Ordena cronologicamente** (mais antiga → mais recente) via `_ordenar_transacoes_por_data`

### Funções Principais

| Função | Propósito |
|--------|-----------|
| `extrair_e_organizar_dados(texto)` | Entry point - texto plano |
| `_extrair_transacoes_layout(texto_layout)` | Parser para extração por colunas |
| `_extrair_linha_layout(linha, data_anterior)` | Extrai 1 transação da linha layout |
| `_reposicionar_inicio_da_descricao(desc)` | Move prefixo OCR para o final |
| `_normalizar_valor_layout(valor, desc)` | Converte string bruta → `R$ -X,YY` |
| `_ordenar_transacoes_por_data(transacoes)` | Ordena lista por data (antiga → nova) |
| `_parse_data_para_ordenacao(data)` | Converte `DD-MM-YYYY` → `datetime` para sort |

---

## 🎨 Frontend (`index.html`)

Interface single-page servida em `/`:

- **Upload** drag-and-drop / clique
- **Tabela responsiva** (Data | Descrição | ID | Valor colorido)
- **Resumo** (Total | Créditos | Débitos | Saldo líquido)
- **Filtros:** checkbox Créditos/Débitos + busca textual
- **Aviso** da API (ex: PDF escaneado)

---

## ✅ Testes

```bash
cd api-extrato
python -m unittest discover -s tests -v
```

**8 testes cobrindo:**
- Ignora saldos/resumos/caixinha
- Junta descrições multi-linha
- Junta descrições entre páginas (sem repetir data)
- Não anexa rodapé à última transação
- Não repete IDs duplicados
- Layout: separa transações em colunas
- Layout: reorganiza descrição após valores
- Layout: não anexa número de página

---

## 🔧 Como Rodar Localmente

```bash
cd api-extrato
pip install -r requirements.txt
uvicorn api.index:app --reload --port 8000
# Abre http://127.0.0.1:8000
```

---

## 📦 Deploy Vercel

1. Repo conectado: `CarlosZika66/api-extrato`
2. **Root Directory:** `api-extrato`
3. Build command: automático (detecta `vercel.json` + `requirements.txt`)
4. Output: `api/index.py` como serverless function

---

## 📝 Histórico de Versões

| Versão | Data | Mudanças |
|--------|------|----------|
| **3.2.0** | 2026-08-30 | **Ordenação cronológica** das transações (mais antiga → mais recente) via `_ordenar_transacoes_por_data` e `_parse_data_para_ordenacao`; mantidos todos filtros, dedup e regras de layout |
| **3.1.0** | 2026-08-30 | Parser layout (colunas), ignora caixinha completa, 8 testes, frontend tabela |
| 3.0.0 | 2026-08-30 | Parser multi-linha, ignora saldos/reservas, junta descrições quebradas |
| 2.0.0 | 2026-08-29 | FastAPI + pypdf, CORS, frontend básico |
| 1.0.0 | 2026-08-28 | Versão inicial |

---

## 📌 Para Próximas IAs

**Ao fazer alterações:**
1. Atualize a **versão** e **data** no topo deste arquivo
2. Adicione entrada na tabela **Histórico de Versões**
3. Rode `python -m unittest discover -s tests -v` antes de commit
4. `git add . && git commit -m "msg" && git push origin main` → deploy automático

**Arquivos que provavelmente vão mudar:**
- `api/index.py` → parser / novas regras de filtro
- `index.html` → UI / novos campos na resposta
- `tests/test_parser.py` → novos casos de teste
- `requirements.txt` → novas dependências

**Não mude sem necessidade:**
- `vercel.json` (já funcional)
- Estrutura de pastas

---

## 🐛 Problemas Conhecidos / Limitações

- `pypdf` extraction_mode="layout" depende de versão ≥ 5.0
- PDFs escaneados/imagem não têm texto extraível → retorna `aviso`
- OCR do Mercado Pago às vezes funde colunas → parser tem heurísticas mas pode falhar em layouts novos
- IDs com < 8 dígitos ou > 18 não são capturados (ajustar `PADRAO_ID_LAYOUT` se needed)

---

## 🔗 Links Úteis

- **Produção:** https://api-extrato-v3.vercel.app
- **Swagger:** https://api-extrato-v3.vercel.app/docs
- **Repo:** https://github.com/CarlosZika66/api-extrato
- **pypdf docs:** https://pypdf.readthedocs.io
- **FastAPI docs:** https://fastapi.tiangolo.com