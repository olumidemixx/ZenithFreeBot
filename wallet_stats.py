import csv
import random
import tls_client
import time
import os
import threading

from contextlib import redirect_stderr
from fake_useragent import UserAgent
from concurrent.futures import ThreadPoolExecutor, as_completed

globalRatelimitEvent = threading.Event()

class BulkWalletChecker:

    def __init__(self):
        self.sendRequest = tls_client.Session(client_identifier='chrome_103')
        self.shorten = lambda s: f"{s[:4]}...{s[-5:]}" if len(s) >= 9 else s
        self.skippedWallets = 0
        self.proxyPosition = 0
        self.totalGrabbed = 0
        self.totalFailed = 0
        self.results = []
        self.walletCache = {}

    def randomise(self):
        self.identifier = random.choice(
            [browser for browser in tls_client.settings.ClientIdentifiers.__args__
             if browser.startswith(('chrome', 'safari', 'firefox', 'opera'))]
        )
        parts = self.identifier.split('_')
        identifier, version, *rest = parts
        identifier = identifier.capitalize()
        
        self.sendRequest = tls_client.Session(random_tls_extension_order=True, client_identifier=self.identifier)
        self.sendRequest.timeout_seconds = 60

        if identifier == 'Opera':
            identifier = 'Chrome'
            osType = 'Windows'
        elif version.lower() == 'ios':
            osType = 'iOS'
        else:
            osType = 'Windows'

        try:
            self.user_agent = UserAgent(os=[osType]).random
        except Exception:
            self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:82.0) Gecko/20100101 Firefox/82.0"

        self.headers = {
            'Host': 'gmgn.ai',
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
            'dnt': '1',
            'priority': 'u=1, i',
            'referer': 'https://gmgn.ai/?chain=sol',
            'user-agent': self.user_agent
        }

    def loadProxies(self):
        with open("Dragon/data/Proxies/proxies.txt", 'r') as file:
            proxies = file.read().splitlines()

        formattedProxies = []
        for proxy in proxies:
            if ':' in proxy:
                parts = proxy.split(':')
                if len(parts) == 4:
                    ip, port, username, password = parts
                    formattedProxies.append({
                        'http': f"http://{username}:{password}@{ip}:{port}",
                        'https': f"http://{username}:{password}@{ip}:{port}"
                    })
                else:
                    formattedProxies.append({
                        'http': f"http://{proxy}",
                        'https': f"http://{proxy}"
                    })
            else:
                formattedProxies.append(f"http://{proxy}")
        return formattedProxies

    def configureProxy(self, proxy):
        if isinstance(proxy, dict):
            self.sendRequest.proxies = {
                'http': proxy.get('http'),
                'https': proxy.get('https')
            }
        elif isinstance(proxy, str):
            self.sendRequest.proxies = {
                'http': proxy,
                'https': proxy
            }
        else:
            self.sendRequest.proxies = None
        return proxy

    def getNextProxy(self):
        proxies = self.loadProxies()
        proxy = proxies[self.proxyPosition % len(proxies)]
        self.proxyPosition += 1
        return proxy

    def getWalletData(self, wallet: str, skipWallets: bool, useProxies):
        if wallet in self.walletCache:
            print(f"[🐲] Loaded cached data for wallet {wallet}.")
            return self.walletCache[wallet]

        url = f"https://gmgn.ai/defi/quotation/v1/smartmoney/sol/walletNew/{wallet}?period=7d"
        
        while True:
            try:
                if globalRatelimitEvent.is_set():
                    print(f"[🐲] Global rate limit active. Waiting for cooldown before processing wallet {wallet}...")
                    globalRatelimitEvent.wait() 

                self.randomise()
                proxy = self.getNextProxy() if useProxies else None
                self.configureProxy(proxy)
                response = self.sendRequest.get(url, headers=self.headers)

                if response.status_code == 429:
                    print(f"[🐲] Received 429 for wallet {wallet}. Triggering global cooldown for 7.5 seconds...")
                    globalRatelimitEvent.set()
                    time.sleep(7.5)
                    globalRatelimitEvent.clear()
                    continue

                if response.status_code == 200:
                    data = response.json()
                    if data['msg'] == "success":
                        data = data['data']
                        if skipWallets:
                            if 'buy_30d' in data and isinstance(data['buy_30d'], (int, float)) and data['buy_30d'] > 0:
                                self.totalGrabbed += 1
                                print(f"[🐲] Successfully grabbed data for {wallet} ({self.totalGrabbed})")
                                result = self.processWalletData(wallet, data)
                                self.walletCache[wallet] = result
                                return result
                            else:
                                self.skippedWallets += 1
                                print(f"[🐲] Skipped {self.skippedWallets} wallets", end="\r")
                                return None
                        else:
                            result = self.processWalletData(wallet, data)
                            self.walletCache[wallet] = result
                            return result
            except Exception as e:
                self.totalFailed += 1
                print(f"[🐲] Exception for {wallet}: {str(e)}. Retrying in 7.5 seconds...")
            time.sleep(7.5)

    def processWalletData(self, wallet, data):
        directLink = f"https://gmgn.ai/sol/address/{wallet}"
        totalProfitPercent = f"{data['total_profit_pnl'] * 100:.2f}%" if data['total_profit_pnl'] is not None else "error"
        realizedProfit7dUSD = f"${data['realized_profit_7d']:,.2f}" if data['realized_profit_7d'] is not None else "error"
        realizedProfit30dUSD = f"${data['realized_profit_30d']:,.2f}" if data['realized_profit_30d'] is not None else "error"
        winrate7d = f"{data['winrate'] * 100:.2f}%" if data['winrate'] is not None else "?"
        solBalance = f"{float(data['sol_balance']):.2f}" if data['sol_balance'] is not None else "?"
        buy7d = f"{data['buy_7d']}" if data['buy_7d'] is not None else "?"

        if "Skipped" in data.get("tags", []):
            return {
                "wallet": wallet,
                "tags": ["Skipped"],
                "directLink": directLink
            }

        try:
            tags = data['tags']
        except Exception:
            tags = "?"

        # Removed any 30d winrate retrieval.
        return {
            "wallet": wallet,
            "totalProfitPercent": totalProfitPercent,
            "7dUSDProfit": realizedProfit7dUSD,
            "30dUSDProfit": realizedProfit30dUSD,  # This remains if you want to keep the 30d profit data.
            "winrate_7d": winrate7d,
            "tags": tags,
            "sol_balance": solBalance,
            "directLink": directLink,
            "buy_7d": buy7d
        }
    
    def fetchWalletData(self, wallets, threads, skipWallets, useProxies):
        with ThreadPoolExecutor(max_workers=threads) as executor:
            futures = {
                executor.submit(self.getWalletData, wallet.strip(), skipWallets, useProxies): wallet
                for wallet in wallets
            }
            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    self.results.append(result)

        resultDict = {}
        for result in self.results:
            wallet = result.get('wallet')
            if wallet:
                resultDict[wallet] = result
                result.pop('wallet', None)
            else:
                print(f"[🐲] Missing 'wallet' key in result: {result}")
        
        all_stats = []  # Create a list to store all wallet stats
        for wallet, data in resultDict.items():
            totalProfitPercent = data.get('totalProfitPercent', 'N/A')
            realizedProfit7dUSD = data.get('7dUSDProfit', 'N/A')
            realizedProfit30dUSD = data.get('30dUSDProfit', 'N/A')
            buy7d = data.get('buy_7d', 'N/A')  # Get buy_7d, default to 'N/A' if missing
            winrate = data.get('winrate_7d', 'N/A')  # Get winrate, default to 'N/A' if missing
            
            
            #stats =  str(wallet) + ":pnl = " + str(totalProfitPercent) + ", 7d profit = " + str(realizedProfit7dUSD) + ", 30d profit = " + str(realizedProfit30dUSD) + ", 7d buys = " + str(buy7d) + ", 7d winrate = " + str(winrate) + " "
            stats = f"{wallet}:\npnl = {totalProfitPercent},\n7d profit = {realizedProfit7dUSD},\n30d profit = {realizedProfit30dUSD},\n7d buys = {buy7d},\n7d winrate = {winrate}"
            all_stats.append(stats)
        
        return "\n\n".join(all_stats)  # Return all wallet stats joined with newlines
            #return (f"{wallet}:pnl = {totalProfitPercent}, 7d profit = {realizedProfit7dUSD}, 30d profit = {realizedProfit30dUSD}, 7d buys = {buy7d}, 7d winrate = {winrate} ")  # Print total profit percentage
            #print(f"7d USD Profit for {wallet}: {realizedProfit7dUSD}")  # Print 7d USD profit
            #print(f"30d USD Profit for {wallet}: {realizedProfit30dUSD}")  # Print 30d USD profit
            #print(f"Buy 7d for {wallet}: {buy7d}")  # Print buy_7d
            #print(f"Winrate for {wallet}: {winrate}")  # Print the winrate for

        #identifier = self.shorten(list(resultDict)[0])
        #print(resultDict.items())

checkBulkWallet=BulkWalletChecker()

#checkBulkWallet.fetchWalletData(["5RANC5iQzzeLFcr1D42Pih4ksUMfa7KXMoCkzoRhujuP","CvLHr9x7owfXphpPHD5bEtAcN8XSnH2p8txmA7KkTFtB","3KNCdquQuPBq6ZWChRJr8jGpkoyZ5LurLCt6sNJJMxbq","EWJuYRkYc5rPRFoRkuuevVRwrkXBQgEQttwFXqDzG3Hs",],threads=40,skipWallets="Y",useProxies=False)

def wallet_stats(contractAddresses):
    wallet_stat = BulkWalletChecker()
    data =wallet_stat.fetchWalletData(contractAddresses, threads = 40,skipWallets="Y",useProxies = False)
    return data

print(wallet_stats(["9zzzi4shE7EBNBf1jH5uTR3SHAZR3qbUvMSHysqUqYuN","3eKgQV2ddZVVsw3532eeBPBaSEx6tp5A7gbX11rgBPyU"]))
