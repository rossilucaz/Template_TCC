import os
import csv
import time
import logging
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from main import generate_sql, send_result_whatsapp, number, load_model

USER_DATA_DIR = os.path.abspath("./chrome-data")
PROFILE_DIR = None
CHAT_NAME = None
POLL_INTERVAL = 1.5

CSV_DIR = "outgoing_history"
os.makedirs(CSV_DIR, exist_ok=True)
timestamp_str = time.strftime("%Y%m%d_%H%M%S")
CSV_PATH = os.path.join(CSV_DIR, f"outgoing_{timestamp_str}.csv")

LOG_PATH = os.path.join(CSV_DIR, f"monitor_log_{timestamp_str}.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler()
    ]
)

def create_driver():
    opts = Options()
    opts.add_argument(f"--user-data-dir={USER_DATA_DIR}")
    if PROFILE_DIR:
        opts.add_argument(f'--profile-directory={PROFILE_DIR}')
    opts.add_experimental_option("excludeSwitches", ["enable-logging"])
    driver = webdriver.Chrome(options=opts)
    return driver

def open_whatsapp(driver, wait):
    driver.get("https://web.whatsapp.com/")
    print("Abrindo WhatsApp Web. Escaneie QR se necessário.")
    wait.until(EC.presence_of_element_located((By.XPATH, "//div[@contenteditable='true' and @data-tab]")))
    print("WhatsApp Web carregado.")

def open_chat_by_name(driver, wait, name):
    search_box = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[@contenteditable='true' and @data-tab]")))
    search_box.click()
    time.sleep(0.3)
    search_box.clear()
    search_box.send_keys(name)
    time.sleep(1.0)
    chat = wait.until(EC.element_to_be_clickable((By.XPATH, f"//span[@title='{name}']")))
    chat.click()
    time.sleep(1.0)
    print(f"Conversa '{name}' aberta.")

def wait_for_conversation_ready(driver, wait):
    print("Detectando conversa aberta...")
    chat_panel = wait.until(EC.presence_of_element_located((By.XPATH, "//div[contains(@class,'copyable-area')]")))
    time.sleep(1.0)
    print("Conversa detectada! Monitoramento iniciado.")
    seen = set()
    bubbles = driver.find_elements(By.XPATH, "//div[contains(@class,'message-out')]")
    for b in bubbles:
        try:
            spans = b.find_elements(By.XPATH, ".//span[@dir='ltr']")
            text = " ".join([s.text.strip() for s in spans if s.text.strip()])
        except:
            text = ""
        try:
            ts = b.find_element(By.XPATH, ".//span[contains(@data-testid,'msg-meta') or contains(@class,'message-meta')]").text.strip()
        except:
            ts = ""
        if text:
            seen.add((text, ts))
    return chat_panel, seen

def fetch_outgoing_messages_texts(driver):
    bubbles = driver.find_elements(By.XPATH, "//div[contains(@class,'message-out')]")
    results = []
    for b in bubbles:
        try:
            spans = b.find_elements(By.XPATH, ".//span[@dir='ltr']")
            text = " ".join([s.text.strip() for s in spans if s.text.strip()])
        except:
            text = ""
        try:
            ts = b.find_element(By.XPATH, ".//span[contains(@data-testid,'msg-meta') or contains(@class,'message-meta')]").text.strip()
        except:
            ts = ""
        if text:
            results.append((text, ts))
    return results

def append_to_csv(rows):
    if not rows:
        return
    file_exists = os.path.isfile(CSV_PATH)
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp_detected", "message_text", "msg_time_in_dom"])
        for ts_detected, text, msg_time in rows:
            writer.writerow([ts_detected, text, msg_time])

def monitor_and_process(driver, seen):
    wait = WebDriverWait(driver, 30)
    logging.info("Monitoramento iniciado (CTRL+C para parar).")

    tokenizer, model = load_model()

    try:
        while True:
            items = fetch_outgoing_messages_texts(driver)
            new_rows = []
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            for text, msg_time in items:
                key = (text, msg_time)
                if key not in seen:
                    seen.add(key)
                    logging.info(f"[OUT] {msg_time or '??'} — {text}")
                    new_rows.append((now, text, msg_time))

                    if text.startswith("#sql"):
                        question_text = text[4:].strip()
                        logging.info(f"Processando pergunta: {question_text}")
                        try:
                            sql = generate_sql(question_text, tokenizer, model)
                            send_result_whatsapp(number, sql)
                            logging.info("Resultado enviado com sucesso.")
                        except Exception as e:
                            logging.error(f"Erro ao processar pergunta: {e}")
            append_to_csv(new_rows)
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print("Encerrando monitoramento.")
    finally:
        driver.quit()
def send_whatsapp_selenium(driver, message):
    try:
        input_box = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//div[@contenteditable='true' and @data-tab]"))
        )
        
        driver.execute_script("arguments[0].innerHTML = arguments[1];", input_box, message)

        input_box.send_keys(Keys.RETURN)
        
        logging.info(f"Mensagem enviada automaticamente: {message}")
    except Exception as e:
        logging.error(f"Erro ao enviar mensagem pelo Selenium: {e}")
        print(f"Erro ao enviar mensagem: {e}")

if __name__ == "__main__":
    driver = create_driver()
    wait = WebDriverWait(driver, 30)
    open_whatsapp(driver, wait)

    if CHAT_NAME:
        open_chat_by_name(driver, wait, CHAT_NAME)

    chat_panel, seen = wait_for_conversation_ready(driver, wait)
    monitor_and_process(driver, seen)
