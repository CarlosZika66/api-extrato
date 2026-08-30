import re
import os
import unicodedata
from fastapi import FastAPI, File, UploadFile, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pypdf import PdfReader

app = FastAPI()

# Configuração de CORS para permitir requisições de qualquer origem
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Servir arquivos estáticos (frontend) - pasta pai da api/
static_dir = os.path.join(os.path.dirname(__file__), "..")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def serve_frontend():
    """Serve o index.html na raiz"""
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"status": "API ativa!", "docs": "/docs", "frontend": "index.html não encontrado"}

@app.get("/favicon.ico")
async def favicon():
    """Evita erro 404 no favicon"""
    return FileResponse(os.path.join(static_dir, "favicon.ico")) if os.path.exists(os.path.join(static_dir, "favicon.ico")) else Response(status_code=204)

PADRAO_DATA_TEXTO = r"\d{2}[-/]\d{2}[-/]\d{4}"
PADRAO_DINHEIRO_TEXTO = r"R\$\s*-?\s*(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2}"

PADRAO_TRANSACAO_COMPLETA = re.compile(
    rf"(?P<data>{PADRAO_DATA_TEXTO})\s+"
    rf"(?P<descricao>.+?)\s+"
    rf"(?P<id_operacao>\d{{8,18}})\s+"
    rf"(?P<valor>{PADRAO_DINHEIRO_TEXTO})\s+"
    rf"(?P<saldo>{PADRAO_DINHEIRO_TEXTO})(?=\s|$)",
    re.IGNORECASE | re.DOTALL,
)

PADRAO_TRANSACAO_LINHA = re.compile(
    rf"^(?:(?P<data>{PADRAO_DATA_TEXTO})\s+)?"
    rf"(?P<descricao>.+?)\s+"
    rf"(?P<id_operacao>\d{{8,18}})\s+"
    rf"(?P<valor>{PADRAO_DINHEIRO_TEXTO})"
    rf"(?:\s+{PADRAO_DINHEIRO_TEXTO})?\s*$",
    re.IGNORECASE,
)

PADRAO_TRANSACAO_SIMPLES = re.compile(
    rf"^(?P<data>{PADRAO_DATA_TEXTO})\s+"
    rf"(?P<descricao>.+?)\s+"
    rf"(?P<valor>{PADRAO_DINHEIRO_TEXTO})\s*$",
    re.IGNORECASE,
)

DESCRICOES_IGNORADAS = (
    "saldo inicial",
    "saldo final",
    "entradas",
    "saidas",
    # "dinheiro retirado" -> MANTER (são saques reais para gastos: PARCELA MOTO, ÁGUA E LUZ, etc.)
    "dinheiro reservado",  # movimento interno p/ caixinha/emergências
    "reserva por gastos",  # reserva automática interna
)

PREFIXOS_DE_TRANSACAO = (
    "boleto",
    "compra",
    "credito",
    "debito",
    "deposito",
    "dinheiro",
    "estorno",
    "pagamento",
    "pix",
    "recebimento",
    "rendimentos",
    "reserva",
    "saque",
    "tarifa",
    "ted",
    "transferencia",
)


def _sem_acentos(valor: str) -> str:
    return "".join(
        caractere
        for caractere in unicodedata.normalize("NFD", valor)
        if unicodedata.category(caractere) != "Mn"
    )


def _eh_cabecalho_da_tabela(linha: str) -> bool:
    linha_normalizada = _sem_acentos(linha).casefold().strip()
    return (
        linha_normalizada.startswith("data descricao")
        and "id da operacao" in linha_normalizada
        and "valor" in linha_normalizada
        and "saldo" in linha_normalizada
    )


def _eh_inicio_de_rodape(linha: str) -> bool:
    linha_normalizada = _sem_acentos(linha).casefold().strip()
    return linha_normalizada.startswith(
        (
            "data de geracao:",
            "voce tem alguma duvida?",
            "mercado pago instituicao de pagamento",
        )
    )


def _eh_linha_informativa(linha: str) -> bool:
    linha_normalizada = _sem_acentos(linha).casefold().strip()

    if re.fullmatch(r"\d+\s*/\s*\d+", linha_normalizada):
        return True

    if _eh_cabecalho_da_tabela(linha):
        return True

    prefixos_informativos = (
        "extrato de conta",
        "cpf/cnpj:",
        "periodo:",
        "saldo inicial:",
        "saldo final:",
        "entradas:",
        "saidas:",
        "detalhe dos movimentos",
    )
    return linha_normalizada.startswith(prefixos_informativos)


def _extrair_secao_de_movimentos(texto: str) -> str:
    texto_normalizado = re.sub(r"\r\n?", "\n", texto).replace("\xa0", " ")
    inicio_movimentos = re.search(
        r"DETALHE\s+DOS\s+MOVIMENTOS", texto_normalizado, re.IGNORECASE
    )

    if inicio_movimentos:
        texto_normalizado = texto_normalizado[inicio_movimentos.end():]

    linhas_relevantes = []
    ignorar_rodape_ate_novo_cabecalho = False
    for linha in texto_normalizado.splitlines():
        linha_limpa = re.sub(r"\s+", " ", linha).strip()
        if not linha_limpa:
            continue

        if _eh_cabecalho_da_tabela(linha_limpa):
            ignorar_rodape_ate_novo_cabecalho = False
            continue

        if _eh_inicio_de_rodape(linha_limpa):
            ignorar_rodape_ate_novo_cabecalho = True
            continue

        if ignorar_rodape_ate_novo_cabecalho:
            continue

        if not _eh_linha_informativa(linha_limpa):
            linhas_relevantes.append(linha_limpa)

    return "\n".join(linhas_relevantes)


def _limpar_descricao(descricao: str) -> str:
    descricao = re.sub(PADRAO_DATA_TEXTO, " ", descricao)
    descricao = re.sub(r"\b\d+\s*/\s*\d+\b", " ", descricao)
    descricao = re.sub(r"\s+", " ", descricao)
    return descricao.strip(" -|:;")


def _normalizar_data(data: str) -> str:
    return data.replace("/", "-")


def _normalizar_valor(valor: str) -> str:
    valor_sem_prefixo = re.sub(r"^R\$\s*", "", valor.strip(), flags=re.IGNORECASE)
    valor_sem_prefixo = re.sub(r"\s+", "", valor_sem_prefixo)
    return f"R$ {valor_sem_prefixo}"


def _deve_ignorar_descricao(descricao: str) -> bool:
    descricao_normalizada = _sem_acentos(descricao).casefold().strip()
    return any(
        descricao_normalizada == prefixo
        or descricao_normalizada.startswith(f"{prefixo} ")
        or descricao_normalizada.startswith(f"{prefixo}:")
        for prefixo in DESCRICOES_IGNORADAS
    )


def _parece_inicio_de_transacao(descricao: str) -> bool:
    descricao_normalizada = _sem_acentos(descricao).casefold().strip()
    return any(
        descricao_normalizada == prefixo
        or descricao_normalizada.startswith(f"{prefixo} ")
        for prefixo in PREFIXOS_DE_TRANSACAO
    )


def _montar_transacao(data: str, descricao: str, id_operacao: str, valor: str):
    return {
        "Data": _normalizar_data(data),
        "Descrição": descricao,
        "ID da operação": id_operacao,
        "Valor": _normalizar_valor(valor),
    }


def _extrair_transacoes_multilinha(texto_movimentos: str):
    transacoes = []
    ids_encontrados = set()
    fim_transacao_anterior = 0

    for match in PADRAO_TRANSACAO_COMPLETA.finditer(texto_movimentos):
        # O Mercado Pago pode quebrar uma descrição no fim de uma página e
        # colocar a data somente na página seguinte. O texto entre as duas
        # transações é, nesse caso, o começo da descrição atual.
        prefixo_quebrado = _limpar_descricao(
            texto_movimentos[fim_transacao_anterior:match.start()]
        )
        if not _parece_inicio_de_transacao(prefixo_quebrado):
            prefixo_quebrado = ""
        descricao = _limpar_descricao(
            f"{prefixo_quebrado} {match.group('descricao')}"
        )
        id_operacao = match.group("id_operacao")
        fim_transacao_anterior = match.end()

        if (
            not descricao
            or id_operacao in ids_encontrados
            or _deve_ignorar_descricao(descricao)
        ):
            continue

        ids_encontrados.add(id_operacao)
        transacoes.append(
            _montar_transacao(
                match.group("data"),
                descricao,
                id_operacao,
                match.group("valor"),
            )
        )

    return transacoes


def _extrair_transacoes_simples(texto_movimentos: str):
    transacoes = []
    ids_encontrados = set()
    data_atual = "Não identificada"

    for linha in texto_movimentos.splitlines():
        match_data = re.fullmatch(PADRAO_DATA_TEXTO, linha)
        if match_data:
            data_atual = _normalizar_data(match_data.group(0))
            continue

        match = PADRAO_TRANSACAO_LINHA.fullmatch(linha)
        if match:
            descricao = _limpar_descricao(match.group("descricao"))
            id_operacao = match.group("id_operacao")
            data = match.group("data") or data_atual

            if (
                descricao
                and id_operacao not in ids_encontrados
                and not _deve_ignorar_descricao(descricao)
            ):
                ids_encontrados.add(id_operacao)
                transacoes.append(
                    _montar_transacao(data, descricao, id_operacao, match.group("valor"))
                )
            continue

        match = PADRAO_TRANSACAO_SIMPLES.fullmatch(linha)
        if match:
            descricao = _limpar_descricao(match.group("descricao"))
            if descricao and not _deve_ignorar_descricao(descricao):
                transacoes.append(
                    _montar_transacao(
                        match.group("data"),
                        descricao,
                        "N/A",
                        match.group("valor"),
                    )
                )

    return transacoes


def extrair_e_organizar_dados(texto: str):
    texto_movimentos = _extrair_secao_de_movimentos(texto)
    transacoes = _extrair_transacoes_multilinha(texto_movimentos)

    # Mantém compatibilidade com extratos simples, sem a coluna de saldo.
    if not transacoes:
        transacoes = _extrair_transacoes_simples(texto_movimentos)

    return transacoes

@app.post("/processar-pdf")
async def processar_pdf(file: UploadFile = File(...)):
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="O arquivo deve ser um PDF.")

    try:
        reader = PdfReader(file.file)
        texto_completo = ""
        for page in reader.pages:
            t = page.extract_text()
            if t:
                texto_completo += t + "\n"

        if not texto_completo.strip():
            return {
                "total_transacoes": 0,
                "transacoes": [],
                "aviso": "Não foi possível extrair texto digital do PDF (pode ser uma imagem/escaneado)."
            }

        dados_formatados = extrair_e_organizar_dados(texto_completo)
        
        return {
            "total_transacoes": len(dados_formatados),
            "transacoes": dados_formatados
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno no processamento: {str(e)}")
