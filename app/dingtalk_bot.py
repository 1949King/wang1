import hashlib
import hmac
import json
import time
import logging
from urllib.parse import quote
import requests # 需要安装: pip install requests

# --- 日志配置 ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),  # 同时写入日志文件
        logging.StreamHandler()  # 输出到控制台
    ]
)
logger = logging.getLogger(__name__)

def get_config():
    """从 config.json 文件加载配置"""
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
            return config['webhook_url'], config['secret']
    except FileNotFoundError:
        logger.error("配置文件 'config.json' 未找到。")
        raise
    except KeyError as e:
        logger.error(f"配置文件中缺少必要的键: {e}")
        raise
    except json.JSONDecodeError:
        logger.error("配置文件 'config.json' 格式错误。")
        raise

def build_signature(secret: str) -> tuple[str, str]:
    """
    构建钉钉机器人签名参数
    
    Args:
        secret (str): 机器人的加签密钥
        
    Returns:
        tuple: 包含 timestamp 和 sign 字符串的元组
    """
    timestamp = str(round(time.time() * 1000))
    secret_enc = secret.encode('utf-8')
    string_to_sign = '{}\n{}'.format(timestamp, secret)
    string_to_sign_enc = string_to_sign.encode('utf-8')
    hmc = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
    sign = quote(hmc)
    return timestamp, sign

def send_message(url: str, message: str):
    """
    发送消息到钉钉机器人
    
    Args:
        url (str): 机器人 Webhook 地址
        message (str): 要发送的消息内容
    """
    headers = {
        'Content-Type': 'application/json'
    }
    
    payload = {
        "msgtype": "text",
        "text": {
            "content": message
        }
    }

    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=10)
        response.raise_for_status() # 如果状态码不是 2xx，会抛出 HTTPError 异常

        result = response.json()
        
        if result.get("errcode") == 0:
            logger.info(f"消息发送成功: {message}")
        else:
            logger.warning(f"钉钉API返回错误: {result.get('errmsg', '未知错误')} (错误码: {result.get('errcode')})")

    except requests.exceptions.RequestException as e:
        logger.error(f"发送消息请求失败: {e}")
    except json.JSONDecodeError:
        logger.error("无法解析钉钉服务器的响应，响应内容非JSON格式。")
    except Exception as e:
        logger.error(f"发送消息时发生未预期的错误: {e}")

def main():
    """主函数"""
    logger.info("程序启动")
    
    try:
        webhook_url, secret_key = get_config()
        timestamp, signature = build_signature(secret_key)

        # 组装最终的请求URL
        final_url = f"{webhook_url}&timestamp={timestamp}&sign={signature}"
        
        # 要发送的消息
        message_content = "测试消息，如果收到则说明运行正常！"

        logger.info(f"准备向钉钉机器人发送消息...")
        send_message(final_url, message_content)

    except Exception as e:
        logger.critical(f"程序运行失败: {e}")
        return # 可以选择在此处退出或继续其他逻辑

    logger.info("程序执行完毕")

if __name__ == "__main__":
    main()