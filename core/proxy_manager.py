import os
import json
from typing import Optional, Dict, List

class ProxyManager:
    def __init__(self):
        self.proxies = []
        self.current_proxy = None
        self.proxy_file = os.path.join("短剧AI剪辑输出", "proxies.json")
        self.load_proxies()
    
    def load_proxies(self):
        try:
            if os.path.exists(self.proxy_file):
                with open(self.proxy_file, 'r', encoding='utf-8') as f:
                    self.proxies = json.load(f)
        except Exception as e:
            print(f"加载代理列表失败: {e}")
            self.proxies = []
    
    def save_proxies(self):
        try:
            os.makedirs(os.path.dirname(self.proxy_file), exist_ok=True)
            with open(self.proxy_file, 'w', encoding='utf-8') as f:
                json.dump(self.proxies, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存代理列表失败: {e}")
    
    def add_proxy(self, proxy: str):
        if proxy and proxy not in self.proxies:
            self.proxies.append(proxy)
            self.save_proxies()
            return True
        return False
    
    def remove_proxy(self, proxy: str):
        if proxy in self.proxies:
            self.proxies.remove(proxy)
            self.save_proxies()
            return True
        return False
    
    def get_proxy(self) -> Optional[str]:
        if self.proxies:
            return self.proxies[0]
        return None
    
    def set_current_proxy(self, proxy: str):
        if proxy in self.proxies:
            self.current_proxy = proxy
            return True
        return False
    
    def get_all_proxies(self) -> List[str]:
        return self.proxies.copy()
    
    def clear_proxies(self):
        self.proxies = []
        self.save_proxies()

proxy_manager = ProxyManager()
