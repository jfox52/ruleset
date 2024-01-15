import requests

def update_china_list():
    url = "https://raw.githubusercontent.com/Loyalsoldier/v2ray-rules-dat/release/china-list.txt"
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.text
        updated_data = "\n".join(["DOMAIN-SUFFIX," + line.strip() for line in data.split("\n")])
        
        with open("china-list.txt", "w") as file:
            file.write(updated_data)
    else:
        print(f"Failed to fetch data from {url}")

if __name__ == "__main__":
    update_china_list()
