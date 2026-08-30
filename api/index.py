import re
import os
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

def extrair_e_organizar_dados(texto: str):
    transacoes = []
    
    # Padrões mais flexíveis para diferentes formatos de extrato bancário
    # Padrão 1: Descrição + ID longo + Valor (R$ X,XX) + Saldo (R$ X,XX)
    padrao1 = re.compile(
        r'^(?P<descricao>.+?)\s+'
        r'(?P<id_operacao>\d{8,20})\s+'
        r'(?P<valor>R\$\s*-?[\d\.,]+)\s+'
        r'(?P<saldo>R\$\s*-?[\d\.,]+)\s*$',
        re.MULTILINE
    )
    
    # Padrão 2: Data + Descrição + Valor (sem ID, sem saldo)
    padrao2 = re.compile(
        r'^(?P<data>\d{2}[-/]\d{2}[-/]\d{4})\s+'
        r'(?P<descricao>.+?)\s+'
        r'(?P<valor>R\$\s*-?[\d\.,]+)\s*$',
        re.MULTILINE
    )
    
    # Padrão 3: Descrição + Valor (formato simples)
    padrao3 = re.compile(
        r'^(?P<descricao>.+?)\s+'
        r'(?P<valor>R\$\s*-?[\d\.,]+)\s*$',
        re.MULTILINE
    )
    
    # Padrão para detectar datas isoladas
    padrao_data = re.compile(r'^(\d{2}[-/]\d{2}[-/]\d{4})\s*$')
    data_atual = "Não identificada"

    linhas = texto.split('\n')
    for linha in linhas:
        linha_limpa = linha.strip()
        if not linha_limpa:
            continue
        
        # Verifica se a linha é apenas uma data
        match_data = padrao_data.search(linha_limpa)
        if match_data:
            data_atual = match_data.group(1)
            continue
        
        # Tenta padrão 1 (completo: desc + ID + valor + saldo)
        match = padrao1.search(linha_limpa)
        if match:
            dados = match.groupdict()
            transacoes.append({
                "Data": data_atual,
                "Descrição": dados["descricao"].strip(),
                "ID da operação": dados["id_operacao"].strip(),
                "Valor": dados["valor"].strip()
            })
            continue
            
        # Tenta padrão 2 (data + desc + valor)
        match = padrao2.search(linha_limpa)
        if match:
            dados = match.groupdict()
            transacoes.append({
                "Data": dados["data"],
                "Descrição": dados["descricao"].strip(),
                "ID da operação": "N/A",
                "Valor": dados["valor"].strip()
            })
            continue
            
        # Tenta padrão 3 (apenas desc + valor)
        match = padrao3.search(linha_limpa)
        if match:
            dados = match.groupdict()
            transacoes.append({
                "Data": data_atual,
                "Descrição": dados["descricao"].strip(),
                "ID da operação": "N/A",
                "Valor": dados["valor"].strip()
            })
            continue

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