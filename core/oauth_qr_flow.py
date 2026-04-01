import os
import json
from datetime import datetime

class OAuthQRFlow:
    def __init__(self):
        self.tokens = {}
        self.token_file = os.path.join("短剧AI剪辑输出", "oauth_tokens.json")
        self.load_tokens()
    
    def load_tokens(self):
        try:
            if os.path.exists(self.token_file):
                with open(self.token_file, 'r', encoding='utf-8') as f:
                    self.tokens = json.load(f)
        except:
            self.tokens = {}
    
    def save_tokens(self):
        try:
            os.makedirs(os.path.dirname(self.token_file), exist_ok=True)
            with open(self.token_file, 'w', encoding='utf-8') as f:
                json.dump(self.tokens, f, ensure_ascii=False, indent=2)
        except:
            pass
    
    def generate_qr_url(self, platform: str) -> str:
        return f"https://oauth.example.com/{platform}/qr"
    
    def check_auth_status(self, platform: str) -> bool:
        return platform in self.tokens
    
    def save_token(self, platform: str, token: str):
        self.tokens[platform] = {
            "token": token,
            "created": datetime.now().isoformat()
        }
        self.save_tokens()
    
    def get_token(self, platform: str) -> str:
        if platform in self.tokens:
            return self.tokens[platform].get("token", "")
        return ""

oauth_qr_flow = OAuthQRFlow()

__all__ = ['OAuthQRFlow', 'oauth_qr_flow']
