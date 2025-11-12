import os
import re
import time
import logging
import psycopg2
import webbrowser
import urllib.parse
from dotenv import load_dotenv
from googletrans import Translator
from transformers import AutoTokenizer, AutoModelForCausalLM

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

load_dotenv()

db_config = {
    "host": os.getenv("DB_HOST"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME")
}
number = os.getenv("NUMBER")
logging.info("Variáveis de ambiente carregadas.")

translator = Translator()
logging.info("Tradutor inicializado.")

def load_model():
    try:
        model_name = "chatdb/natural-sql-7b"
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForCausalLM.from_pretrained(model_name)
        logging.info(f"{model_name} carregado com sucesso.")
        return tokenizer, model
    except KeyError:
        return print("Error em Carregar o Modelo")

def translate_pt_to_en(text: str) -> str:
    """Traduz texto de português para inglês"""
    translation = translator.translate(text, src='pt', dest='en')
    logging.info(f"Texto traduzido: '{text}' -> '{translation.text}'")
    return translation.text

def clean_sql_output(text: str) -> str:
    """
    Extrai apenas a query SQL válida do texto gerado pelo modelo.
    Remove comentários, instruções adicionais ou schemas residuais.
    """
    match = re.search(r"(select|insert|update|delete)\s.+", text, re.IGNORECASE | re.DOTALL)
    if not match:
        return text.strip()
    
    sql = match.group(0)
    sql = sql.split(';')[0]
    sql = re.sub(r"(?i)\b(Schema|Tables)\b.*", "", sql)
    sql = " ".join(sql.split())
    
    return sql.strip()
    
def generate_sql(question: str, tokenizer, model) -> str:
    start_time = time.time()
    
    logging.info("Traduzindo pergunta para inglês...")
    question_en = translate_pt_to_en(question)
    
    schema = """
    Schema: tcc_schema
    Tables:
    - customers(customer_id, name, email, phone, created_at)
    - products(product_id, name, category, price, created_at)
    - orders(order_id, customer_id, order_date, status)
    - order_items(order_item_id, order_id, product_id, quantity, price)
    """
    prompt = f"""{schema}
        Question: {question_en}
        ### Please generate only the SQL query to answer the question above.
        SQL:
        """
    logging.info(f"Prompt gerado:\n{prompt}")

    logging.info("Tokenizando prompt...")
    inputs = tokenizer(prompt, return_tensors="pt", padding=True, truncation=True)
    logging.info(f"Tokenização concluída. Número de tokens: {inputs['input_ids'].shape[1]}")

    logging.info("Gerando SQL com o modelo...")
    outputs = model.generate(
        input_ids=inputs["input_ids"],
        attention_mask=inputs.get("attention_mask"),
        max_new_tokens=256,
        do_sample=False
    )
    raw_sql = tokenizer.decode(outputs[0], skip_special_tokens=True)
    sql_query = clean_sql_output(raw_sql)
    if "Schema" in raw_sql:
        logging.warning("Ruído 'Schema' detectado e removido do SQL gerado.")
    
    elapsed = time.time() - start_time
    logging.info(f"SQL gerado em {elapsed:.2f} segundos:\n{sql_query}")
    return sql_query

def get_data_from_db(query, params=None):
    """Executa query no banco e retorna resultados"""
    start_time = time.time()
    logging.info("Conectando ao banco de dados...")
    connection = psycopg2.connect(**db_config)
    cursor = connection.cursor()
    
    cursor.execute("SET search_path TO tcc_schema;")
    logging.info("Search path definido para tcc_schema.")
    
    logging.info(f"Executando query:\n{query}")
    cursor.execute(query, params)
    result = cursor.fetchall()
    
    logging.info(f"Query retornou {len(result)} registros.")
    cursor.close()
    connection.close()
    logging.info("Conexão com banco fechada.")
    elapsed = time.time() - start_time
    logging.info(f"Tempo de execução da consulta: {elapsed:.2f} segundos.")
    return result

def send_whatsapp(number: str, message: str):
    """Abre o WhatsApp Web no navegador com o texto pronto"""
    texto_codificado = urllib.parse.quote(message)
    url = f"https://wa.me/{number}?text={texto_codificado}"
    webbrowser.open(url)
    logging.info(f"Abrindo WhatsApp Web com mensagem para {number}...")

def send_result_whatsapp(number: str, query: str, params=None, max_rows: int = 10):
    """Executa uma query SQL e envia o resultado pelo WhatsApp"""
    try:
        results = get_data_from_db(query, params)
        if not results:
            message = "A query não retornou nenhum resultado."
        else:
            message = "Resultados da query:\n"
            for idx, row in enumerate(results[:max_rows], start=1):
                row_text = " | ".join(str(col) for col in row)
                message += f"{idx}: {row_text}\n"
            if len(results) > max_rows:
                message += f"... e mais {len(results) - max_rows} linhas."
        send_whatsapp(number, message)
    except Exception as e:
        logging.error(f"Erro ao enviar resultado pelo WhatsApp: {e}")
        send_whatsapp(number, f"Ocorreu um erro ao gerar o resultado: {e}")
