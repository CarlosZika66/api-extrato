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

MARCADOR_QUEBRA_PAGINA = "<<<QUEBRA_DE_PAGINA>>>"
PADRAO_DATA_LAYOUT = re.compile(r"(?<!\d)(\d{2}[-/]?\d{2}[-/]?\d{4})(?!\d)")
PADRAO_ID_LAYOUT = re.compile(r"(?<!\d)(\d{10,18})(?!\d)")
PADRAO_DINHEIRO_LAYOUT = re.compile(r"R\$\s*-?\s*[\d.,]+", re.IGNORECASE)

DESCRICOES_IGNORADAS = (
    "saldo inicial",
    "saldo final",
    "entradas",
    "saidas",
    "dinheiro retirado",  # caixinha - ignorar todas
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
        linha_normalizada.startswith("data")
        and "descri" in linha_normalizada
        and "opera" in linha_normalizada
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


from datetime import datetime

def _normalizar_data(data: str) -> str:
    somente_digitos = re.sub(r"\D", "", data)
    if len(somente_digitos) == 8:
        return (
            f"{somente_digitos[:2]}-{somente_digitos[2:4]}-"
            f"{somente_digitos[4:]}"
        )
    return data.replace("/", "-")


def _parse_data_para_ordenacao(data: str) -> datetime:
    """Converte string DD-MM-YYYY para datetime para ordenação segura."""
    try:
        return datetime.strptime(data, "%d-%m-%Y")
    except ValueError:
        # Fallback para datas malformadas - coloca no final
        return datetime.max


def _normalizar_valor(valor: str) -> str:
    valor_sem_prefixo = re.sub(r"^R\$\s*", "", valor.strip(), flags=re.IGNORECASE)
    valor_sem_prefixo = re.sub(r"\s+", "", valor_sem_prefixo)
    return f"R$ {valor_sem_prefixo}"


def _corrigir_texto_ocr(texto: str) -> str:
    texto = texto.replace("\ufffd", "")
    correcoes = (
        (r"\bCarto\b", "Cartão"),
        (r"\bcrdito\b", "crédito"),
        (r"\bEmprstimos\b", "Empréstimos"),
        (r"\bEmergncias\b", "Emergências"),
        (r"\bDepsito\b", "Depósito"),
        (r"\bGR Pix\b", "QR Pix"),
        (r"\b[vm]oto\b", "MOTO"),
        (r"\(1o\s+DE\s+GAS\s+LTDA", "COMERCIO DE GAS LTDA"),
    )
    for padrao, substituicao in correcoes:
        texto = re.sub(padrao, substituicao, texto, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", texto).strip(" -|:;_\\")


def _descricao_indica_saida(descricao: str) -> bool:
    descricao_normalizada = _sem_acentos(descricao).casefold().strip()
    return descricao_normalizada.startswith(
        (
            "boleto",
            "compra",
            "debito",
            "pagamento",
            "pix enviado",
            "saque",
            "tarifa",
            "ted enviado",
            "transferencia enviada",
        )
    )


def _normalizar_valor_layout(valor: str, descricao: str) -> str:
    negativo_explicito = "-" in valor
    numero = re.sub(r"[^\d,.]", "", valor)

    if not numero:
        return "R$ 0,00"

    if "," in numero:
        inteiro, centavos = numero.rsplit(",", 1)
        inteiro = re.sub(r"\D", "", inteiro) or "0"
        centavos = re.sub(r"\D", "", centavos)[:2].ljust(2, "0")
    elif "." in numero and len(numero.rsplit(".", 1)[1]) == 2:
        inteiro, centavos = numero.rsplit(".", 1)
        inteiro = re.sub(r"\D", "", inteiro) or "0"
        centavos = re.sub(r"\D", "", centavos)[:2].ljust(2, "0")
    else:
        digitos = re.sub(r"\D", "", numero)
        if len(digitos) <= 2:
            inteiro = "0"
            centavos = digitos.rjust(2, "0")
        else:
            inteiro = digitos[:-2]
            centavos = digitos[-2:]

    inteiro_formatado = f"{int(inteiro):,}".replace(",", ".")
    negativo = negativo_explicito or _descricao_indica_saida(descricao)
    sinal = "-" if negativo else ""
    return f"R$ {sinal}{inteiro_formatado},{centavos}"


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


def _reposicionar_inicio_da_descricao(descricao: str) -> str:
    descricao = _corrigir_texto_ocr(descricao)
    descricao_normalizada = _sem_acentos(descricao).casefold()
    posicoes = [
        descricao_normalizada.find(prefixo)
        for prefixo in PREFIXOS_DE_TRANSACAO
        if descricao_normalizada.find(prefixo) >= 0
    ]

    if not posicoes:
        return descricao

    inicio = min(posicoes)
    if inicio == 0:
        return descricao

    trecho_inicial = descricao[:inicio].strip(" -|:;_\\")
    descricao_principal = descricao[inicio:].strip()

    # Alguns PDFs com OCR deslocam uma palavra curta (por exemplo, MOTO ou
    # SUTIL) para antes do tipo da transação. Ela pertence ao final.
    if trecho_inicial and len(trecho_inicial.split()) <= 5:
        return f"{descricao_principal} {trecho_inicial}".strip()
    return descricao_principal


def _extrair_linha_layout(linha: str, data_anterior: str | None):
    id_match = PADRAO_ID_LAYOUT.search(linha)
    if not id_match:
        return None

    valores = [
        match
        for match in PADRAO_DINHEIRO_LAYOUT.finditer(linha)
        if match.start() > id_match.end()
    ]
    if not valores:
        return None

    data_match = PADRAO_DATA_LAYOUT.search(linha[:id_match.start()])
    data = _normalizar_data(data_match.group(1)) if data_match else data_anterior
    if not data:
        return None

    caracteres = list(linha)
    intervalos = [(id_match.start(), id_match.end())]
    if data_match:
        intervalos.append((data_match.start(), data_match.end()))
    intervalos.extend((match.start(), match.end()) for match in valores)

    for inicio, fim in intervalos:
        caracteres[inicio:fim] = " " * (fim - inicio)

    descricao = "".join(caracteres)
    descricao = re.sub(r"\$\s*[\d.,]+", " ", descricao)
    descricao = re.sub(r"[�—–]+", " ", descricao)
    descricao = _reposicionar_inicio_da_descricao(descricao)

    if not descricao:
        return None

    return {
        "data": data,
        "descricao_partes": [descricao],
        "id_operacao": id_match.group(1),
        "valor_bruto": valores[0].group(0),
    }


def _limpar_fragmento_layout(linha: str) -> str:
    linha = re.sub(r"[�—–]+", " ", linha)
    linha = _corrigir_texto_ocr(linha)

    if (
        not linha
        or _eh_linha_informativa(linha)
        or re.fullmatch(r"[a-z]?\d{1,5}(?:/\d{1,3})?", linha, re.IGNORECASE)
    ):
        return ""
    return linha


def _extrair_transacoes_layout(texto_layout: str):
    transacoes = []
    ids_encontrados = set()
    transacao_atual = None
    fragmentos_pendentes = []
    data_anterior = None
    linhas_em_branco = 0
    dentro_dos_movimentos = False
    ignorar_rodape = False

    def finalizar_transacao_atual():
        nonlocal transacao_atual
        if not transacao_atual:
            return

        descricao = _reposicionar_inicio_da_descricao(
            " ".join(transacao_atual["descricao_partes"])
        )
        id_operacao = transacao_atual["id_operacao"]

        if (
            descricao
            and id_operacao not in ids_encontrados
            and not _deve_ignorar_descricao(descricao)
        ):
            ids_encontrados.add(id_operacao)
            transacoes.append(
                _montar_transacao(
                    transacao_atual["data"],
                    descricao,
                    id_operacao,
                    _normalizar_valor_layout(
                        transacao_atual["valor_bruto"], descricao
                    ),
                )
            )
        transacao_atual = None

    for linha_original in texto_layout.splitlines():
        linha = linha_original.rstrip()
        linha_limpa = linha.strip()

        if linha_limpa == MARCADOR_QUEBRA_PAGINA:
            finalizar_transacao_atual()
            linhas_em_branco = 2
            ignorar_rodape = False
            continue

        if not linha_limpa:
            linhas_em_branco += 1
            continue

        linha_normalizada = _sem_acentos(linha_limpa).casefold()
        if "detalhe dos movimentos" in linha_normalizada:
            dentro_dos_movimentos = True
            fragmentos_pendentes.clear()
            linhas_em_branco = 0
            continue

        if _eh_cabecalho_da_tabela(linha_limpa):
            dentro_dos_movimentos = True
            ignorar_rodape = False
            linhas_em_branco = 0
            continue

        if not dentro_dos_movimentos:
            continue

        if _eh_inicio_de_rodape(linha_limpa):
            ignorar_rodape = True
            continue
        if ignorar_rodape:
            continue

        nova_transacao = _extrair_linha_layout(linha, data_anterior)
        if nova_transacao:
            finalizar_transacao_atual()
            if fragmentos_pendentes:
                nova_transacao["descricao_partes"] = [
                    *fragmentos_pendentes,
                    *nova_transacao["descricao_partes"],
                ]
                fragmentos_pendentes.clear()
            transacao_atual = nova_transacao
            data_anterior = nova_transacao["data"]
            linhas_em_branco = 0
            continue

        fragmento = _limpar_fragmento_layout(linha_limpa)
        if not fragmento:
            continue

        if fragmentos_pendentes:
            fragmentos_pendentes.append(fragmento)
        elif transacao_atual and linhas_em_branco == 0:
            transacao_atual["descricao_partes"].append(fragmento)
        else:
            fragmentos_pendentes.append(fragmento)
        linhas_em_branco = 0

    finalizar_transacao_atual()
    return transacoes


def _pontuar_resultado(transacoes) -> int:
    descricoes_excessivas = sum(
        len(transacao["Descrição"]) > 200 for transacao in transacoes
    )
    return len(transacoes) * 10 - descricoes_excessivas * 500


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


def _ordenar_transacoes_por_data(transacoes: list[dict]) -> list[dict]:
    """Ordena transações por data (mais antiga primeiro)."""
    return sorted(
        transacoes,
        key=lambda t: _parse_data_para_ordenacao(t.get("Data", ""))
    )


def extrair_e_organizar_dados(texto: str):
    texto_movimentos = _extrair_secao_de_movimentos(texto)
    transacoes = _extrair_transacoes_multilinha(texto_movimentos)

    # Mantém compatibilidade com extratos simples, sem a coluna de saldo.
    if not transacoes:
        transacoes = _extrair_transacoes_simples(texto_movimentos)

    # Ordena cronologicamente (mais antiga para mais recente)
    return _ordenar_transacoes_por_data(transacoes)

@app.post("/processar-pdf")
async def processar_pdf(file: UploadFile = File(...)):
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="O arquivo deve ser um PDF.")

    try:
        reader = PdfReader(file.file)
        paginas_texto_simples = []
        paginas_texto_layout = []
        for page in reader.pages:
            texto_simples = page.extract_text() or ""
            paginas_texto_simples.append(texto_simples)

            try:
                texto_layout = page.extract_text(extraction_mode="layout") or ""
            except (TypeError, ValueError):
                texto_layout = texto_simples
            paginas_texto_layout.append(texto_layout)

        texto_completo = "\n".join(paginas_texto_simples)
        texto_layout_completo = (
            f"\n{MARCADOR_QUEBRA_PAGINA}\n".join(paginas_texto_layout)
        )

        if not texto_completo.strip():
            return {
                "total_transacoes": 0,
                "transacoes": [],
                "aviso": "Não foi possível extrair texto digital do PDF (pode ser uma imagem/escaneado)."
            }

        dados_texto_simples = extrair_e_organizar_dados(texto_completo)
        dados_layout = _ordenar_transacoes_por_data(
            _extrair_transacoes_layout(texto_layout_completo)
        )
        dados_formatados = max(
            (dados_texto_simples, dados_layout),
            key=_pontuar_resultado,
        )
        
        return {
            "total_transacoes": len(dados_formatados),
            "transacoes": dados_formatados
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno no processamento: {str(e)}")
