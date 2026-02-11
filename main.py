import os
import json
import gspread
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1ZOYEDVMpLfn8U-gFL5F3Rx_MdKsts6b2uUCSpPbwhjo"

def get_pcode(place):
    return {'京都':'08','東京':'05','小倉':'10','中山':'06','阪神':'09','中京':'07'}.get(place, '08')

def main():
    gcp_json = os.environ.get("GCP_JSON")
    target_date_short = os.environ.get("TARGET_DATE") 
    target_date_full = "2026" + target_date_short

    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(json.loads(gcp_json), scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID).worksheet(target_date_short)

    # A3:C17のデータを取得
    records = sheet.get("A3:C17")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        current_place = ""
        for i, row in enumerate(records):
            if len(row) < 3: continue
            
            # 場所が空なら上の行を引き継ぐ
            place = row[0] if row[0] != "" else current_place
            current_place = place
            race_no = str(row[1]).zfill(2)
            umaban = str(row[2])
            
            p_code = get_pcode(place)
            
            # 開催回・日目を探索（netkeibaのURL生成）
            found = False
            for k in range(1, 4):
                for d in range(1, 13):
                    race_id = f"{target_date_full}{p_code}{str(k).zfill(2)}{str(d).zfill(2)}{race_no}"
                    url = f"https://race.netkeiba.com/race/result.html?race_id={race_id}"
                    
                    page.goto(url)
                    if page.query_selector("#All_Result_Table"):
                        html = page.content()
                        soup = BeautifulSoup(html, "html.parser")
                        
                        # 馬番の行を探す
                        target_row = None
                        for tr in soup.select("#All_Result_Table tbody tr"):
                            if f"<div>{umaban}</div>" in str(tr):
                                target_row = tr
                                break
                        
                        if target_row:
                            rank = target_row.select_one(".Rank").text.strip()
                            tan = "0"
                            fuku = "0"
                            
                            if rank == "1":
                                tan_tag = soup.select_one("tr.Tansho .Payout span")
                                if tan_tag: tan = tan_tag.text.replace(",","").replace("円","")
                            
                            if rank.isdigit() and int(rank) <= 3:
                                fuku_tag = soup.select_one("tr.Fukusho .Payout")
                                if fuku_tag:
                                    # 複勝は複数あるので該当馬番の順位で取得
                                    payouts = fuku_tag.select("span")[0].decode_contents().split("<br/>")
                                    fuku = payouts[int(rank)-1].replace(",","").replace("円","").strip()

                            # シートのH, I, J列（8, 9, 10列目）を更新
                            row_num = i + 3
                            sheet.update_cell(row_num, 8, rank)
                            sheet.update_cell(row_num, 9, tan)
                            sheet.update_cell(row_num, 10, fuku)
                            print(f"Update: {place} {race_no}R {umaban}番 -> {rank}着")
                            found = True
                            break
                if found: break
        browser.close()

if __name__ == "__main__":
    main()
